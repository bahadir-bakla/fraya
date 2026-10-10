"""Static policy check with a solver, before any call is simulated.

The spec's value constraints (``Tool.constraints``: amount >= 0.1 × overdue) and its order preconditions
(``ltl.formulas``: identity before an account write, a fresh confirmation before each save) are encoded as
one Z3 problem per tool. Three findings need no simulated call:

* **dead tool**: its rules cannot all hold, so no call to it can ever be allowed (the clauses are named);
* **vacuous rule**: no spoken value can break it, so the clause it cites is enforced by nothing;
* **conflict**: two clauses that cannot both hold, reported through the unsat core.

NOMOS (arXiv 2610.11030) rejects or repairs 13-37% of compiled policy rules this way; the solver-aided
policy check of arXiv 2603.20449 uses the same encoding at call time. Adapted from the tools thread's
prototype (/mnt/project-files/tools/proto/z3_gate.py). ``z3-solver`` is optional: without it the check is
skipped and the report says so.
"""

from __future__ import annotations

from .ltl import formulas
from .spec import AgentSpec

_OPS = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, "==": lambda a, b: a == b}


def available() -> bool:
    try:
        import z3  # noqa: F401
    except ImportError:
        return False
    return True


def static_check(spec: AgentSpec) -> dict:
    """{"solver": bool, "rules": n, "findings": [...]}; findings cite clauses."""
    if not available():
        return {"solver": False, "rules": 0, "findings": []}
    import z3

    facts = spec.facts
    rules = []  # (label, tool, kind, payload, source)
    for t in spec.tools:
        for c in t.constraints:
            rules.append((f"{'/'.join(c.source)}:{c.describe()}", t.name, "bound", c, list(c.source)))
    for f in formulas(spec):
        if f.kind in ("once", "since") and f.a.startswith("call:"):
            rules.append((f"{'/'.join(f.source)}:{f.text()}", f.a[5:], "pre", f.b, list(f.source)))
    rules = list({r[0]: r for r in rules}.values())  # one tracked assertion per label

    def encode(s, mine, tracked):
        xs = {}
        for label, _, kind, p, _ in mine:
            if kind == "bound":
                x = xs.setdefault(p.arg, z3.Real(p.arg))
                e = _OPS[p.op](x, z3.RealVal(float(facts[p.fact]) * p.factor))
                s.add(x >= 0)
            else:
                e = xs.setdefault(p, z3.Bool(p))
            if tracked:
                s.assert_and_track(e, z3.Bool(label))
            else:
                s.add(e)

    findings = []
    for tool in sorted({r[1] for r in rules}):
        mine = [r for r in rules if r[1] == tool]
        s = z3.Solver()
        encode(s, mine, tracked=True)
        if s.check() == z3.unsat:
            core = {str(b) for b in s.unsat_core()}
            named = [f"{r[0].split(':', 1)[1]} [§{', §'.join(r[4])}]" for r in mine if r[0] in core]
            findings.append(f"dead tool `{tool}`: these cannot all hold: {'; '.join(named)}")
        for label, _, kind, p, src in mine:
            if kind != "bound":
                continue
            v = z3.Solver()
            x = z3.Real(p.arg)
            v.add(x >= 0, z3.Not(_OPS[p.op](x, z3.RealVal(float(facts[p.fact]) * p.factor))))
            if v.check() == z3.unsat:
                findings.append(f"vacuous rule on `{tool}`: {p.describe()} [§{', §'.join(src)}] can never be broken")
    return {"solver": True, "rules": len(rules), "findings": findings}
