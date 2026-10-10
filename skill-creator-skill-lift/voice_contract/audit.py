"""Post-call audit of a transcript against a Voice Acceptance Contract.

Deliberately independent of ``guard.StreamGuard``: it re-derives every verdict
from the finished transcript instead of replaying the guard, so a bug in the
live guard shows up as a disagreement here rather than being mirrored (the
same producer/checker split skill-creator enforces).

Transcript format: a list of ``{"role": "user"|"agent"|"assistant"|"event", ...}``
with the spoken text under ``text``, ``message`` or ``content`` (Freya's
call/unit-test message shape uses ``message``) and event names under ``name``.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from .contract import Contract, normalize
from .pii import find_pii


@dataclass
class Finding:
    rule_id: str
    kind: str
    turn: int  # 1-based agent turn index (0 = before any agent turn)
    detail: str


def _text(msg: dict) -> str:
    return msg.get("text") or msg.get("message") or msg.get("content") or ""


def audit_transcript(contract: Contract, transcript: list[dict]) -> list[Finding]:
    lang = contract.language
    findings: list[Finding] = []
    events: set[str] = set()
    agent_turn = 0
    disclosed: set[str] = set()
    for msg in transcript:
        role = msg.get("role")
        if role == "event":
            events.add(msg.get("name", ""))
            continue
        text = _text(msg)
        norm = normalize(text, lang)
        if role == "user":
            for r in contract.rules:
                if r.side == "user" and r.matches(norm):
                    findings.append(Finding(r.id, r.kind, agent_turn, "user trigger"))
            continue
        if role not in ("agent", "assistant", "bot"):
            continue
        agent_turn += 1
        for r in contract.rules:
            if r.kind == "forbidden" and r.matches(norm):
                findings.append(Finding(r.id, r.kind, agent_turn, f"said {r.matches(norm).group()!r}"))
            elif r.kind == "gated_topic" and r.requires_event not in events and r.matches(norm):
                findings.append(Finding(r.id, r.kind, agent_turn, f"said {r.matches(norm).group()!r} before {r.requires_event}"))
            elif r.kind == "pii_leak":
                for p in find_pii(text, r.entities):
                    findings.append(Finding(r.id, r.kind, agent_turn, f"spoke a {p.entity}"))
            elif r.kind == "max_words" and len(text.split()) > r.limit:
                findings.append(Finding(r.id, r.kind, agent_turn, f"{len(text.split())} words > {r.limit}"))
            elif r.kind == "required_disclosure" and r.id not in disclosed:
                if r.matches(norm):
                    disclosed.add(r.id)
                elif agent_turn == r.within_agent_turns:
                    findings.append(Finding(r.id, r.kind, agent_turn, "disclosure missing"))
    for r in contract.by_kind("required_disclosure"):
        if r.id not in disclosed and agent_turn < r.within_agent_turns:
            findings.append(Finding(r.id, r.kind, agent_turn, "call ended before disclosure"))
    return findings


def violations(contract: Contract, findings: list[Finding]) -> list[Finding]:
    """User-side triggers are expected events, not agent faults; drop them."""
    user_ids = {r.id for r in contract.rules if r.side == "user"}
    return [f for f in findings if f.rule_id not in user_ids]


def pass_hat_k(contract: Contract, runs: dict[str, list[list[dict]]]) -> dict:
    """Reliability across repeated runs of each scenario.

    ``runs`` maps scenario name -> list of transcripts (one per run). A run
    passes when it has no agent-side violation. Reports pass@1 (mean run pass
    rate) and pass^k (all k runs pass), the metric EVA-Bench and tau-bench use
    to separate peak capability from consistency.
    """
    per_scenario = {}
    per_rule: dict[str, int] = defaultdict(int)
    for name, transcripts in runs.items():
        results = []
        for t in transcripts:
            v = violations(contract, audit_transcript(contract, t))
            for f in v:
                per_rule[f.rule_id] += 1
            results.append(not v)
        per_scenario[name] = {
            "k": len(results),
            "pass@1": sum(results) / len(results) if results else 0.0,
            "pass^k": all(results) if results else False,
        }
    n = len(per_scenario) or 1
    return {
        "scenarios": per_scenario,
        "pass@1": sum(s["pass@1"] for s in per_scenario.values()) / n,
        "pass^k": sum(s["pass^k"] for s in per_scenario.values()) / n,
        "violations_by_rule": dict(per_rule),
    }


def load_transcript(path: str | Path) -> list[dict]:
    path = Path(path)
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("messages", data) if isinstance(data, dict) else data


def findings_json(findings: list[Finding]) -> str:
    return json.dumps([asdict(f) for f in findings], ensure_ascii=False, indent=2)
