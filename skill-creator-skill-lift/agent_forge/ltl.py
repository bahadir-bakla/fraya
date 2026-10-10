"""Ordering oracle: past-time LTL over the call's action trace.

The spoken audit (voice_contract) judges *what was said*. SOPs also fix *the
order of actions*: no account action before the caller is verified, no
promise saved without the caller confirming that amount. VAmoS-Bench finds
exactly these to be where financial voice agents break (procedure order,
disclosure after failed verification), and AgentLTL / Agentproof check them
as temporal properties over the trace rather than asking a model.

Each property is a past-time LTL formula checked at every step of the trace,
so it is a small deterministic monitor (a DFA), not a judgement call:

* ``once``:   G(a -> O b)               "a only after b has happened"
* ``since``:  G(a -> (not a) S b)       "every a needs a fresh b since the previous a"
* ``never``:  G(a -> not O b)           "no a once b has happened"

Trace atoms come from the runtime: ``call:T`` (the backend was asked),
``tool:T`` (it succeeded), ``event:E`` (including events carried in a
handoff envelope) and ``confirmed:T`` (the caller said yes to the read-back).
The formulas are derived from the *draft* spec and frozen with the oracle, so
a patch or a mutant cannot move the yardstick.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .spec import AgentSpec


@dataclass
class Formula:
    kind: str  # once | since | never
    a: str
    b: str
    source: list[str] = field(default_factory=list)
    guard: str = ""  # "amount>500": the formula binds only calls whose argument meets it

    def text(self) -> str:
        a = f"{self.a} ∧ {self.guard}" if self.guard else self.a
        return {"once": f"G({a} → O {self.b})",
                "since": f"G({a} → ¬{self.a} S {self.b})",
                "never": f"G({a} → ¬O {self.b})"}[self.kind]

    def binds(self, trace: list[str], i: int) -> bool:
        """Does the guard hold for the call at trace[i]? Its arguments are the arg: atoms just before it."""
        if not self.guard:
            return True
        name, op, bound = re.match(r"(\w+)(>=|<=|>|<)([\d.]+)", self.guard).groups()
        tool = self.a[5:]
        for x in reversed(trace[max(0, i - 8):i]):
            if x.startswith(f"arg:{tool}.{name}="):
                v = float(x.split("=", 1)[1])
                return {">": v > float(bound), "<": v < float(bound), ">=": v >= float(bound),
                        "<=": v <= float(bound)}[op]
        return False


def formulas(spec: AgentSpec) -> list[Formula]:
    """Order properties implied by the spec: identity before account actions, confirmation before each write."""
    out: list[Formula] = []
    verify = next((t for t in spec.tools if t.sets_event == "identity_verified"), None)
    if verify:
        gate = [r["id"].removeprefix("VC-") for r in spec.rules if r.get("kind") == "gated_topic"]
        src = list(verify.source) + gate
        # Situation tools (third party, dispute, ...) say for themselves whether they need a verified caller.
        situational = {t for c in spec.capabilities for t in (c.get("steps") or [c["tool"]])}
        for t in spec.tools:
            if t.side_effect and t is not verify and t.name not in situational:
                out.append(Formula("once", f"call:{t.name}", "event:identity_verified", list(dict.fromkeys(src))))
        for c in spec.capabilities:
            if c.get("requires_identity"):
                out.append(Formula("once", f"call:{c['tool']}", "event:identity_verified", list(c["source"])))
    # Read back and confirm before every write that takes a spoken value the SOP says to confirm.
    req = spec.params.get("confirm_amount", {}).get("source", [])
    for t in spec.tools:
        conf = [a for a in t.args if spec.slot(a) and (spec.slot(a).confirm or req and spec.slot(a).kind == "amount")]
        if conf:
            src = list(dict.fromkeys(s for a in conf for s in spec.slot(a).confirm_source)) or list(req) or list(t.source)
            out.append(Formula("since", f"call:{t.name}", f"confirmed:{t.name}", src))
    # Procedure order the SOP states between tools: "reissue only after the card is blocked".
    for o in spec.params.get("order", []):
        out.append(Formula("once", f"call:{o['after']}", f"tool:{o['before']}", list(o["source"]), o.get("guard", "")))
    # A disputed debt is not collected in the same call: no promise once a dispute is on record.
    for c in spec.capabilities:
        if c["id"] == "dispute":
            for t in spec.tools:
                if t.sets_event == "promise_saved":
                    out.append(Formula("never", f"call:{t.name}", f"tool:{c['tool']}", list(c["source"])))
    return out


def check(fs: list[Formula], trace: list[str]) -> list[str]:
    """Run every formula as an online monitor; one message per violated formula (first violation)."""
    out = []
    for f in fs:
        seen_b = False  # O b
        fresh = False  # (not a) S b
        for i, x in enumerate(trace):
            if x == f.b:
                seen_b = fresh = True
            if x == f.a and f.binds(trace, i):
                bad = (f.kind == "once" and not seen_b) or (f.kind == "since" and not fresh) or (
                    f.kind == "never" and seen_b)
                if bad:
                    cite = ", ".join("§" + s for s in f.source)
                    out.append(f"order violation {f.text()} at step {i} [{cite}]")
                    break
                fresh = False
    return out
