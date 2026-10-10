"""Run one call across a multi-agent topology.

A ``CallSession`` holds the active agent's ``WorkflowRuntime`` and one
``StreamGuard`` for the whole call. Every caller turn first goes to the
router: when the caller's intent matches a handoff out of the active agent,
the call moves to the target agent, seeded with the handoff's context
envelope. Otherwise the active agent handles the turn.

Signals the architect acts on:

* ``unrouted_intent``: the router recognised a situation the SOP gives its
  own procedure for (third party, dispute, hardship), but no agent handles it,
* ``repeated_question``: after a handoff, an agent asked the caller for
  something an earlier agent already had.
"""

from __future__ import annotations

import re

from voice_contract.contract import compile_policy, normalize
from voice_contract.guard import StreamGuard

from .runtime import NaiveAgentModel, Signal, ToolCall, WorkflowRuntime, detect_intents
from .slots import fold
from .spec import guard_policy
from .topology import Handoff, Topology


def t_intents(t: Topology) -> dict[str, list[str]]:
    caps = t.agent(t.entry).spec.capabilities
    return {c["intent"]: c["patterns"] for c in caps}


class CallSession:
    def __init__(self, t: Topology, model_factory=NaiveAgentModel, declines: frozenset[str] = frozenset()):
        self.t = t
        self.model_factory = model_factory
        self.declines = declines
        entry = t.agent(t.entry)
        self.guard = StreamGuard(compile_policy(guard_policy(entry.spec)))
        self.active = entry.id
        self.rt = WorkflowRuntime(entry.spec, model_factory(), guard=self.guard, declines=declines)
        self.runtimes: list[WorkflowRuntime] = [self.rt]
        self.own_signals: list[Signal] = []
        self.handoffs_taken: list[str] = []
        self.known_before: set[str] = set()  # slots known before the latest handoff
        self._repeats: set[str] = set()
        self.stack: list[tuple[WorkflowRuntime, str]] = []  # agents a resumable handoff will return to
        # One chronological record for the whole call: with a handback, the entry agent acts again after the
        # specialist, so concatenating per-agent records would show the order oracle the wrong order.
        self._trace: list[str] = []
        self._calls: list[ToolCall] = []
        self._seen: dict[int, tuple[int, int]] = {}

    # Interface the simulator expects from a runtime.
    @property
    def st(self):
        return self.rt.st

    @property
    def signals(self) -> list[Signal]:
        return [s for r in self.runtimes for s in r.signals] + self.own_signals

    @property
    def tool_calls(self) -> list[ToolCall]:
        return list(self._calls)

    @property
    def trace(self) -> list[str]:
        return list(self._trace)

    def _sync(self, *rts: WorkflowRuntime) -> None:
        for r in rts:
            nt, nc = self._seen.get(id(r), (0, 0))
            self._trace += r.st.trace[nt:]
            self._calls += r.st.tool_calls[nc:]
            self._seen[id(r)] = (len(r.st.trace), len(r.st.tool_calls))

    @property
    def guard_events(self) -> list[dict]:
        return [e for r in self.runtimes for e in r.guard_events]

    def open(self) -> str:
        out = self.rt.open()
        self._sync(self.rt)
        return out

    def on_user(self, text: str) -> str:
        if self.st.done:
            return ""
        intents = self.rt.perception.intents(text, t_intents(self.t), self.rt.spec.language)
        own = {e.when[7:] for e in self.rt.spec.global_edges if e.when.startswith("intent:")}
        if own & set(detect_intents(self.rt.spec, text, self.rt.perception)):
            intents = []  # the agent's own global routes (escalation to a human) win over a handoff
        if len(self.handoffs_taken) < self.t.max_handoffs:
            for h in self.t.out_of(self.active):
                if h.intent in intents and not h.handback:
                    return self._handoff(h, text)
        for it in intents:
            if not any(h.intent == it for h in self.t.out_of(self.active)):
                self.own_signals.append(Signal("unrouted_intent", self.st.node, it, f"agent {self.active}"))
        out = self.rt.on_user(text)
        self._sync(self.rt)
        back = next((h for h in self.t.handoffs if h.handback and h.src == self.active), None)
        if back and self.rt.st.done == "end" and self.stack:
            # The specialist finished a resumable job: hand the call back to the agent it came from.
            self.handoffs_taken.append(f"{self.active}->{back.dst} (back)")
            self.rt, self.active = self.stack.pop()
            out = out + " " + self.rt.resume()
            self._sync(self.rt)
        self._check_repeat()
        return out

    def _handoff(self, h: Handoff, text: str) -> str:
        self.guard.on_user(text)  # the caller's words are part of the call record whoever answers
        prev = self.rt
        envelope = {
            "slots": {f: prev.st.slots[f] for f in h.carry if not f.startswith("event:") and f in prev.st.slots},
            "events": [f[6:] for f in h.carry if f.startswith("event:") and f[6:] in prev.st.events],
        }
        self.known_before = {k for r in self.runtimes for k in r.st.slots} | {
            # A verified caller has already given their verification answers, even if a failed attempt cleared them.
            s for r in self.runtimes for s in self._verify_slots(r) if "identity_verified" in r.st.events}
        self.handoffs_taken.append(f"{self.active}->{h.dst}")
        self.stack.append((self.rt, self.active))
        self.active = h.dst
        self.rt = WorkflowRuntime(self.t.agent(h.dst).spec, self.model_factory(), guard=self.guard, seed=envelope,
                                  declines=self.declines)
        self.runtimes.append(self.rt)
        out = self.rt.open()
        self._sync(prev, self.rt)
        self._check_repeat()
        return out

    @staticmethod
    def _verify_slots(r: WorkflowRuntime) -> list[str]:
        return [a for t in r.spec.tools if t.sets_event == "identity_verified" for a in t.args]

    def _check_repeat(self) -> None:
        if len(self.runtimes) < 2:
            return
        for s in self.st.awaiting:
            if s in self.known_before and s not in self._repeats:
                self._repeats.add(s)
                self.own_signals.append(Signal("repeated_question", self.st.node, self.active, s))
