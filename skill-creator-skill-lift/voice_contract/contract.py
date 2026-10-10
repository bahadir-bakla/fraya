"""Compile a call-center policy into a Voice Acceptance Contract.

Same idea as skill-creator's Acceptance Contract: every policy rule becomes one
stable ``VC-*`` row with an exact invariant, the policy text it came from, and
the executable check that enforces it. A rule that exists only in a system
prompt is not enforced; a rule that compiles into a row is checked live by
``guard.StreamGuard``, after the call by ``audit``, and before release by the
generated eval scenarios.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

KINDS = {
    "required_disclosure",  # agent must say X within the first N agent turns
    "gated_topic",  # agent must not say X until an event (e.g. identity_verified) happened
    "pii_leak",  # agent must not speak checksum-valid card / TCKN / IBAN numbers
    "forbidden",  # agent must never say X (threats, guarantees, legal advice)
    "max_words",  # an agent turn is spoken audio; keep it short
    "escalation",  # user says X -> hand off to a human
    "injection",  # user tries to override instructions -> flag
}
ACTIONS = ("log", "warn", "redact", "block", "handoff")
AGENT_KINDS = {"required_disclosure", "gated_topic", "pii_leak", "forbidden", "max_words"}
USER_KINDS = {"escalation", "injection"}

_TR_UPPER = str.maketrans({"İ": "i", "I": "ı"})


def normalize(text: str, language: str = "tr") -> str:
    """Lowercase with Turkish dotted/dotless i handled, whitespace collapsed."""
    if language == "tr":
        text = text.translate(_TR_UPPER)
    return re.sub(r"\s+", " ", text.lower())


@dataclass
class Rule:
    id: str
    kind: str
    description: str
    source: str
    action: str
    patterns: list[str] = field(default_factory=list)
    entities: tuple[str, ...] = ()
    within_agent_turns: int = 1
    requires_event: str | None = None
    limit: int | None = None
    fallback: str | None = None
    prepend: str | None = None
    handoff_target: str | None = None
    probe: str | None = None  # a caller line that should trigger this rule, for generated tests
    probe_tool: str | None = None  # tool the agent must call first (gated_topic)
    compiled: list[re.Pattern] = field(default_factory=list, repr=False)

    def matches(self, normalized_text: str) -> re.Match | None:
        for rx in self.compiled:
            m = rx.search(normalized_text)
            if m:
                return m
        return None

    @property
    def side(self) -> str:
        return "user" if self.kind in USER_KINDS else "agent"

    def invariant(self) -> str:
        pats = " | ".join(self.patterns)
        return {
            "required_disclosure": f"agent says one of [{pats}] within agent turn {self.within_agent_turns}",
            "gated_topic": f"agent says none of [{pats}] before event `{self.requires_event}`",
            "pii_leak": f"agent speaks no checksum-valid {', '.join(self.entities)}",
            "forbidden": f"agent never says any of [{pats}]",
            "max_words": f"every agent turn has at most {self.limit} words",
            "escalation": f"user says one of [{pats}] -> handoff to `{self.handoff_target}`",
            "injection": f"user override attempt [{pats}] is flagged",
        }[self.kind]

    def check(self) -> str:
        live = "StreamGuard (live, before TTS)" if self.action in ("redact", "block", "handoff") else "StreamGuard (flag)"
        return f"{live}; audit.audit_transcript; generated eval scenario"


@dataclass
class Contract:
    name: str
    language: str
    hold_chars: int
    rules: list[Rule]
    default_fallback: str

    def by_kind(self, kind: str) -> list[Rule]:
        return [r for r in self.rules if r.kind == kind]

    def table(self) -> str:
        """Markdown Acceptance Contract table, in skill-creator's column layout."""
        lines = [
            "| ID | Kind | Exact invariant | Evidence source | Action | Executable check |",
            "|---|---|---|---|---|---|",
        ]
        for r in self.rules:
            inv = r.invariant().replace("|", "\\|")
            lines.append(f"| {r.id} | {r.kind} | {inv} | {r.source} | {r.action} | {r.check()} |")
        return "\n".join(lines)


class ContractError(ValueError):
    pass


def load_policy(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ContractError("PyYAML is needed for .yaml policies; use .json or pip install pyyaml") from exc
        return yaml.safe_load(text)
    return json.loads(text)


def compile_policy(policy: dict[str, Any]) -> Contract:
    """Validate a policy mapping and compile it. Every problem is reported at once."""
    errors: list[str] = []
    language = policy.get("language", "tr")
    seen: set[str] = set()
    rules: list[Rule] = []
    for i, raw in enumerate(policy.get("rules") or []):
        where = f"rules[{i}]"
        rid = raw.get("id") or f"VC-{i + 1:02d}"
        if rid in seen:
            errors.append(f"{where}: duplicate id {rid}")
        seen.add(rid)
        kind = raw.get("kind")
        if kind not in KINDS:
            errors.append(f"{where} ({rid}): unknown kind {kind!r}; expected one of {sorted(KINDS)}")
            continue
        action = raw.get("action", "warn")
        if action not in ACTIONS:
            errors.append(f"{where} ({rid}): unknown action {action!r}")
        if not raw.get("source"):
            errors.append(f"{where} ({rid}): missing `source` (which policy clause this rule enforces)")
        patterns = list(raw.get("patterns") or [])
        if kind in {"required_disclosure", "gated_topic", "forbidden", "escalation", "injection"} and not patterns:
            errors.append(f"{where} ({rid}): kind {kind} needs `patterns`")
        if kind == "gated_topic" and not raw.get("requires_event"):
            errors.append(f"{where} ({rid}): gated_topic needs `requires_event`")
        if kind == "max_words" and not isinstance(raw.get("limit"), int):
            errors.append(f"{where} ({rid}): max_words needs an integer `limit`")
        if kind == "escalation" and action == "handoff" and not raw.get("handoff_target"):
            errors.append(f"{where} ({rid}): handoff needs `handoff_target`")
        if action == "redact" and kind != "pii_leak":
            errors.append(f"{where} ({rid}): action redact only applies to pii_leak")
        if action == "handoff" and kind not in USER_KINDS:
            errors.append(f"{where} ({rid}): action handoff only applies to user-side rules")
        compiled = []
        for p in patterns:
            try:
                compiled.append(re.compile(normalize(p, language)))
            except re.error as exc:
                errors.append(f"{where} ({rid}): bad pattern {p!r}: {exc}")
        rules.append(
            Rule(
                id=rid,
                kind=kind,
                description=raw.get("description", ""),
                source=raw.get("source", ""),
                action=action,
                patterns=patterns,
                entities=tuple(raw.get("entities") or ("card", "tckn", "iban_tr")),
                within_agent_turns=int(raw.get("within_agent_turns", 1)),
                requires_event=raw.get("requires_event"),
                limit=raw.get("limit"),
                fallback=raw.get("fallback"),
                prepend=raw.get("prepend"),
                handoff_target=raw.get("handoff_target"),
                probe=raw.get("probe"),
                probe_tool=raw.get("probe_tool"),
                compiled=compiled,
            )
        )
    if not rules and not errors:
        errors.append("policy has no rules")
    if errors:
        raise ContractError("\n".join(errors))
    return Contract(
        name=policy.get("name", "policy"),
        language=language,
        hold_chars=int(policy.get("hold_chars", 40)),
        rules=rules,
        default_fallback=policy.get("default_fallback", "Bu konuda size yardımcı olamıyorum."),
    )


def load_contract(path: str | Path) -> Contract:
    return compile_policy(load_policy(path))
