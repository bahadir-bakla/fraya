"""Streaming guard that sits between the LLM and TTS.

The LLM streams text in chunks; TTS speaks whatever it is given. Once a word
is spoken it cannot be taken back, so the guard keeps a short hold-back window
(``Contract.hold_chars``) and only releases text that has left that window.
Every check runs on the whole turn so far, so a card number or a forbidden
phrase split across chunk boundaries is still caught before any of it is
released. The cost is ``hold_chars`` of extra delay on the first audio, which
at normal speaking pace is a fraction of a second; ``StreamGuard.timings``
records the check cost itself.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .contract import Contract, Rule, normalize
from .pii import find_pii


@dataclass
class Violation:
    rule_id: str
    kind: str
    action: str
    turn: int
    detail: str


@dataclass
class Decision:
    """What the guard tells the pipeline after a chunk or event."""

    release: str = ""  # text that is now safe to send to TTS
    stop_turn: bool = False  # drop the rest of this agent turn
    handoff: str | None = None  # transfer target, when a handoff fired
    violations: list[Violation] = field(default_factory=list)


@dataclass
class _Turn:
    index: int
    text: str = ""
    released: int = 0  # chars of `text` already released (pre-redaction offsets)
    blocked: bool = False
    spoken: str = ""  # what actually went to TTS this turn


class StreamGuard:
    def __init__(self, contract: Contract):
        self.c = contract
        self.events: set[str] = set()
        self.agent_turns = 0
        self.violations: list[Violation] = []
        self.timings: list[float] = []
        self.transcript: list[dict] = []
        self._turn: _Turn | None = None
        self._disclosed: set[str] = set()
        self._handoff: str | None = None

    # -- inputs ------------------------------------------------------------

    def on_event(self, name: str) -> None:
        """A backend fact the policy can depend on, e.g. ``identity_verified``."""
        self.events.add(name)
        self.transcript.append({"role": "event", "name": name})

    def on_user(self, text: str) -> Decision:
        t0 = time.perf_counter()
        self.transcript.append({"role": "user", "text": text})
        d = Decision()
        norm = normalize(text, self.c.language)
        for r in self.c.rules:
            if r.side != "user":
                continue
            m = r.matches(norm)
            if not m:
                continue
            self._violate(d, r, self.agent_turns, f"user said {m.group()!r}")
            if r.kind == "escalation" and r.action == "handoff" and self._handoff is None:
                self._handoff = r.handoff_target
                d.handoff = r.handoff_target
        self.timings.append(time.perf_counter() - t0)
        return d

    def start_agent_turn(self) -> Decision:
        self.agent_turns += 1
        self._turn = _Turn(self.agent_turns)
        d = Decision()
        if self._handoff:
            # After a handoff the bot must not keep talking on its own.
            self._turn.blocked = True
            d.stop_turn = True
            return d
        for r in self.c.by_kind("required_disclosure"):
            if r.prepend and r.id not in self._disclosed and self.agent_turns <= r.within_agent_turns:
                d.release += r.prepend.rstrip() + " "
                self._disclosed.add(r.id)
        self._turn.spoken += d.release
        return d

    def on_agent_chunk(self, chunk: str) -> Decision:
        if self._turn is None:
            self.start_agent_turn()
        t0 = time.perf_counter()
        turn = self._turn
        d = Decision()
        if turn.blocked:
            d.stop_turn = True
            return d
        turn.text += chunk
        if self._check_agent(turn, d, final=False):
            self._release(turn, d, upto=max(turn.released, len(turn.text) - self.c.hold_chars))
        self.timings.append(time.perf_counter() - t0)
        return d

    def end_agent_turn(self) -> Decision:
        turn = self._turn
        d = Decision()
        if turn is None:
            return d
        t0 = time.perf_counter()
        if not turn.blocked and self._check_agent(turn, d, final=True):
            self._release(turn, d, upto=len(turn.text))
        spoken_norm = normalize(turn.spoken, self.c.language)
        for r in self.c.rules:
            # Non-blocking agent rules are flagged once the turn is complete.
            if r.action == "block" or r.kind not in ("forbidden", "gated_topic", "pii_leak"):
                continue
            if r.kind == "pii_leak":
                hit = bool(find_pii(turn.text, r.entities)) and r.action != "redact"
            elif r.kind == "gated_topic" and r.requires_event in self.events:
                hit = False
            else:
                hit = r.matches(spoken_norm) is not None
            if hit:
                self._violate(d, r, turn.index, "flagged after turn")
        words = len(turn.spoken.split())
        for r in self.c.by_kind("max_words"):
            if words > r.limit:
                self._violate(d, r, turn.index, f"{words} words > {r.limit}")
        for r in self.c.by_kind("required_disclosure"):
            if r.id in self._disclosed:
                continue
            if r.matches(normalize(turn.spoken, self.c.language)):
                self._disclosed.add(r.id)
            elif turn.index == r.within_agent_turns:
                self._violate(d, r, turn.index, f"disclosure missing by agent turn {r.within_agent_turns}")
        self.transcript.append({"role": "agent", "text": turn.spoken.strip(), "blocked": turn.blocked})
        self._turn = None
        self.timings.append(time.perf_counter() - t0)
        return d

    # -- internals ---------------------------------------------------------

    def _violate(self, d: Decision, r: Rule, turn: int, detail: str) -> Violation:
        v = Violation(r.id, r.kind, r.action, turn, detail)
        d.violations.append(v)
        self.violations.append(v)
        return v

    def _check_agent(self, turn: _Turn, d: Decision, final: bool) -> bool:
        """Run blocking agent-side rules over the whole turn. False if the turn was cut."""
        norm = normalize(turn.text, self.c.language)
        for r in self.c.rules:
            if r.action != "block":
                continue
            hit = None
            if r.kind == "forbidden" or (r.kind == "gated_topic" and r.requires_event not in self.events):
                hit = r.matches(norm)
            elif r.kind == "pii_leak":
                found = find_pii(turn.text, r.entities)
                hit = found[0] if found else None
            if hit is not None:
                what = getattr(hit, "entity", None) or hit.group()
                self._violate(d, r, turn.index, f"agent was about to say {what!r}")
                turn.blocked = True
                d.stop_turn = True
                fallback = r.fallback or self.c.default_fallback
                d.release += fallback
                turn.spoken += fallback
                return False
        return True

    def _release(self, turn: _Turn, d: Decision, upto: int) -> None:
        if upto <= turn.released:
            return
        # Never cut inside a word: release up to the last space before `upto`.
        if upto < len(turn.text):
            cut = turn.text.rfind(" ", turn.released, upto)
            if cut <= turn.released:
                return
            upto = cut + 1
        piece = turn.text[turn.released : upto]
        for r in self.c.by_kind("pii_leak"):
            if r.action == "redact":
                piece = _redact_window(turn.text, turn.released, upto, r.entities)
        turn.released = upto
        d.release += piece
        turn.spoken += piece


def _redact_window(text: str, start: int, end: int, entities: tuple[str, ...]) -> str:
    """Redact PII in text[start:end], judging matches on the whole text so split numbers are caught."""
    out, pos = [], start
    for p in find_pii(text, entities):
        if p.end <= start or p.start >= end:
            continue
        s, e = max(p.start, start), min(p.end, end)
        out.append(text[pos:s])
        if p.start >= start:
            out.append(f"[{p.entity.upper()}]")
        pos = e
    out.append(text[pos:end])
    return "".join(out)
