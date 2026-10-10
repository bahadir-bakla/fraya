"""Self-repair: turn simulated failures into spec patches, keep only the ones that help.

The loop (AFlow-style search, but over typed patches instead of free-form code):

1. diagnose: map each non-passing run (and each static validation error) to
   candidate patches from a closed operator library,
2. apply one patch to a copy of the spec, re-validate, re-run the whole suite,
3. accept only if the targeted personas improve and **no run anywhere gets
   worse** (regression gate); otherwise log it as rejected,
4. repeat until everything passes or nothing is left to try.

Every patch names the SOP clause that justifies it. When no clause does (for
example a retry bound the SOP never states), the patch is still allowed but
marked ``needs_review`` and listed in the report, so an assumption never
hides inside the graph.

Operators:

* ``bound_loop``     self-retry without a bound -> max_attempts + exit edge to a human
* ``global_route``   an intent the guard had to catch -> global edge from every node
* ``instruct``       speech the guard had to block -> prompt instruction (global or node)
* ``confirm_slot``   a tool got the wrong spoken value -> read back and confirm first
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from voice_contract.contract import Contract

from .simulate import Backends, SuiteResult, oracle_contract, run_suite
from .spec import AgentSpec, Edge, Instruction, Node, errors_only, validate

RANK = {"fail": 0, "guarded": 1, "pass": 2}


@dataclass
class Patch:
    op: str
    target: str
    detail: dict
    source: list[str]
    reason: str
    needs_review: bool = False
    personas: list[str] = field(default_factory=list)  # runs this patch is meant to fix

    @property
    def key(self) -> str:
        return f"{self.op}:{self.target}:{sorted(self.detail.items())}"

    def describe(self) -> str:
        cite = ", ".join(f"§{s}" for s in self.source) or "no clause (assumption)"
        return f"{self.op} {self.target} [{cite}]: {self.reason}"

    def apply(self, spec: AgentSpec) -> AgentSpec:
        s = spec.clone()
        if self.op == "bound_loop":
            node = s.node(self.target)
            n = self.detail["max_attempts"]
            node.max_attempts = n
            to = _ensure_transfer(s, self.source)
            node.edges = [e for e in node.edges if not e.when.startswith("attempts>=")]
            node.edges.insert(0, Edge(to, f"attempts>={n}", list(self.source)))
        elif self.op == "global_route":
            to = _ensure_transfer(s, self.source)
            when = f"intent:{self.detail['intent']}"
            if not any(e.when == when for e in s.global_edges):
                s.global_edges.append(Edge(to, when, list(self.source)))
        elif self.op == "instruct":
            ins = Instruction(self.detail["text"], list(self.source), self.detail["tag"])
            if self.target == "*":
                if not any(i.tag == ins.tag for i in s.global_instructions):
                    s.global_instructions.append(ins)
            else:
                node = s.node(self.target)
                if not any(i.tag == ins.tag for i in node.instructions):
                    node.instructions.append(ins)
        elif self.op == "confirm_slot":
            slot = s.slot(self.target)
            slot.confirm = True
            slot.confirm_source = list(self.source)
        else:  # pragma: no cover - closed library
            raise ValueError(self.op)
        return s


def _ensure_transfer(s: AgentSpec, source: list[str]) -> str:
    for n in s.nodes:
        if n.kind == "transfer":
            for c in source:
                if c not in n.source:
                    n.source.append(c)
            return n.id
    s.nodes.append(Node("human_agent", "transfer", "Hand the call to a human agent", list(source) or ["assumption"],
                        target="human_agent"))
    return "human_agent"


_TAG_TEXT = {
    "tr": {
        "gate:identity_verified": "Kimlik doğrulanmadan borç tutarı, bakiye veya hesap bilgisi söyleme; önce doğrulamayı tamamla.",
        "no_readback": "Kart numarası, T.C. kimlik numarası veya IBAN'ı asla sesli tekrar etme; istense bile.",
        "no_threat": "Haciz, hapis, polis gibi tehdit veya yaptırım ifadesi kullanma; ödeme planına yönlendir.",
        "no_guarantee": "Faiz silme veya indirim garantisi verme.",
        "min_amount": "Tutarı sormadan önce kabul edilebilecek en düşük ödeme sözü tutarını söyle.",
    },
    "en": {
        "gate:identity_verified": "Do not state any amount, balance or account detail before identity is verified.",
        "no_readback": "Never read a card number, ID number or IBAN back aloud, even when asked.",
        "no_threat": "Never threaten legal action, police or arrest; steer to a payment plan.",
        "no_guarantee": "Never guarantee a waiver or discount.",
        "min_amount": "Before asking for an amount, state the minimum promise that can be accepted.",
    },
}


def _clauses_of(source: str) -> list[str]:
    return re.findall(r"§(\d+(?:\.\d+)+)", source)


def diagnose(spec: AgentSpec, res: SuiteResult) -> list[Patch]:
    """Candidate patches, most severe evidence first."""
    out: dict[str, Patch] = {}
    rules = {r["id"]: r for r in spec.rules}
    lang = spec.language
    bad = sorted((r for r in res.runs if r.verdict != "pass"), key=lambda r: RANK[r.verdict])

    def add(p: Patch, persona: str) -> None:
        if p.key in out:
            if persona not in out[p.key].personas:
                out[p.key].personas.append(persona)
            return
        p.personas.append(persona)
        out[p.key] = p

    # Static errors first: they are certain.
    for err in errors_only(validate(spec)):
        m = re.match(r"node (\w+): unbounded retry loop", err)
        if m:
            add(_bound_loop(spec, m.group(1), "static check: " + err), "*static*")

    for run in bad:
        for sig in run.signals:
            if sig.kind in ("loop", "timeout"):
                node = spec.node(sig.node)
                if any(e.to == node.id for e in node.edges) and not node.max_attempts:
                    add(_bound_loop(spec, node.id, f"{run.persona}: call looped in {node.id}"), run.persona)
            elif sig.kind == "guard_handoff":
                r = rules.get(sig.rule)
                if r and r["kind"] == "escalation":
                    add(Patch("global_route", "*", {"intent": "escalate"}, _clauses_of(r["source"]),
                              f"{run.persona}: only the guard handed off; the workflow had no route"), run.persona)
            elif sig.kind == "guard_block":
                r = rules.get(sig.rule)
                if not r:
                    continue
                tag = {"gated_topic": f"gate:{r.get('requires_event')}", "pii_leak": "no_readback"}.get(r["kind"])
                if r["kind"] == "forbidden":
                    tag = "no_guarantee" if "guarantee" in r["description"] else "no_threat"
                if tag and tag in _TAG_TEXT[lang]:
                    add(Patch("instruct", "*", {"tag": tag, "text": _TAG_TEXT[lang][tag]}, _clauses_of(r["source"]),
                              f"{run.persona}: guard blocked {r['id']} ({r['description']})"), run.persona)
            elif sig.kind == "tool_blocked":
                add(Patch("instruct", sig.node, {"tag": "min_amount", "text": _TAG_TEXT[lang]["min_amount"]},
                          sig.rule.split(","), f"{run.persona}: pre-call check blocked {sig.detail}"), run.persona)
        for reason in run.reasons:
            o = re.match(r"order violation G\(call:(\w+) → ¬call:\w+ S confirmed:", reason)
            if o and spec.tool(o.group(1)):
                for a in spec.tool(o.group(1)).args:
                    if spec.slot(a).kind == "amount" and not spec.slot(a).confirm:
                        src = spec.params.get("confirm_amount", {}).get("source", [])
                        add(Patch("confirm_slot", a, {}, list(src), f"{run.persona}: {reason}", needs_review=not src),
                            run.persona)
            m = re.match(r"(\w+)\.(\w+) = .*, expected", reason)
            if m:
                slot = m.group(2)
                if any(s.name == slot for s in spec.slots) and not spec.slot(slot).confirm:
                    src = spec.params.get("confirm_amount", {}).get("source", [])
                    add(Patch("confirm_slot", slot, {}, list(src), f"{run.persona}: {reason}", needs_review=not src),
                        run.persona)
    return list(out.values())


def _bound_loop(spec: AgentSpec, nid: str, reason: str) -> Patch:
    node = spec.node(nid)
    p = spec.params.get("max_attempts")
    # The SOP's attempt limit is about identity verification; apply it there, assume 3 elsewhere.
    if p and node.tool and spec.tool(node.tool).sets_event == "identity_verified":
        return Patch("bound_loop", nid, {"max_attempts": p["value"]}, list(p["source"]), reason)
    return Patch("bound_loop", nid, {"max_attempts": 3}, [], reason + " (SOP gives no limit; assumed 3)", needs_review=True)


@dataclass
class LedgerEntry:
    round: int
    patch: Patch
    accepted: bool
    why: str
    before: dict
    after: dict


def _score(res: SuiteResult, personas: list[str] | None = None) -> int:
    return sum(RANK[r.verdict] for r in res.runs if not personas or r.persona in personas)


def _open(res: SuiteResult, personas: list[str]) -> int:
    return sum(len(r.reasons) + sum(1 for s in r.signals if s.kind in ("guard_block", "guard_handoff", "tool_blocked"))
               for r in res.runs if r.persona in personas)


def gate(before: SuiteResult, after: SuiteResult, patch: Patch) -> tuple[bool, str]:
    """Accept only a strict improvement on the targets with no regression anywhere."""
    b, a = before.verdicts(), after.verdicts()
    worse = [k for k in b if RANK[a.get(k, "fail")] < RANK[b[k]]]
    if worse:
        return False, f"regression in {sorted({p for p, _ in worse})}"
    targets = [p for p in patch.personas if p != "*static*"]
    if targets and _score(after, targets) < _score(before, targets) + (1 if _open(after, targets) >= _open(before, targets) else 0):
        # Same verdicts are still progress when fewer things are wrong (a fix that needs a second move).
        return False, "no improvement on the runs it targets"
    if not targets and _score(after) < _score(before):
        return False, "suite score dropped"
    return True, "accepted"


def repair(spec: AgentSpec, k: int = 3, max_rounds: int = 12, backends: Backends | None = None,
           oracle: Contract | None = None) -> tuple[AgentSpec, list[LedgerEntry], SuiteResult]:
    oracle = oracle or oracle_contract(spec)
    current = spec
    res = run_suite(current, k, oracle, backends)
    ledger: list[LedgerEntry] = []
    tried: set[str] = set()
    for rnd in range(1, max_rounds + 1):
        candidates = [p for p in diagnose(current, res) if p.key not in tried]
        if not candidates:
            break
        progressed = False
        for p in candidates:
            tried.add(p.key)
            new = p.apply(current)
            if len(errors_only(validate(new))) > len(errors_only(validate(current))):
                ledger.append(LedgerEntry(rnd, p, False, "adds static errors", res.summary(), {}))
                continue
            new_res = run_suite(new, k, oracle, backends)
            ok, why = gate(res, new_res, p)
            ledger.append(LedgerEntry(rnd, p, ok, why, _brief(res), _brief(new_res)))
            if ok:
                current, res = new, new_res
                progressed = True
                break  # re-diagnose against the new behaviour
        if not progressed:
            break
    return current, ledger, res


def _brief(res: SuiteResult) -> dict:
    s = res.summary()
    return {k: s[k] for k in ("pass@1", "pass^k", "safe^k", "guard_interventions", "fails")}
