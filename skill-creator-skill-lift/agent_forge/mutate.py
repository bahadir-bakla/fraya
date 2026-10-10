"""Per-clause mutation testing: does the generated test suite notice when a clause is gone?

Generating tests is easy; knowing they test anything is not. Because every
element of the spec cites the clause it implements, the forge can delete one
clause's whole implementation (its guard rules, prompt instructions, edges,
confirmation steps, tool constraints) and re-run the suite against the
*unchanged* oracle. If every run still passes, the mutant survived: nothing
in the suite exercises that clause, and the report names it.

Mutation score = killed mutants / mutants. A survivor is either a missing
test or a clause the agent satisfies anyway (for example the disclosure is in
the greeting text itself, so removing the guard rule changes nothing); the
report shows which artifacts were removed so a reviewer can tell which.
"""

from __future__ import annotations

from dataclasses import dataclass

from voice_contract.contract import Contract

from .simulate import oracle_contract, run_suite
from .spec import AgentSpec, _clause_ids


@dataclass
class Mutant:
    clause: str
    removed: list[str]
    killed: bool
    by: list[str]  # personas whose runs changed verdict


def ablate(spec: AgentSpec, clause: str) -> tuple[AgentSpec, list[str]]:
    """Remove every implementation artifact whose only justification is ``clause``.

    Artifacts citing several clauses lose only this citation. Nodes, slots and
    tools stay (removing them breaks the graph rather than testing the clause);
    their clause-specific behaviour (instructions, edges, confirm, constraints)
    goes.
    """
    s = spec.clone()
    removed: list[str] = []

    def only(src: list[str]) -> bool:
        return src == [clause]

    keep_rules = []
    for r in s.rules:
        if _clause_ids(r.get("source", "")) == [clause]:
            removed.append(f"guard:{r['id']}")
        else:
            keep_rules.append(r)
    s.rules = keep_rules
    for n in s.nodes:
        for i in [i for i in n.instructions if only(i.source)]:
            removed.append(f"instruction:{n.id}:{i.tag}")
            n.instructions.remove(i)
        for e in [e for e in n.edges if only(e.source) and e.when.startswith("attempts>=")]:
            removed.append(f"edge:{n.id}->{e.to}[{e.when}]")
            n.edges.remove(e)
            n.max_attempts = None
    for i in [i for i in s.global_instructions if only(i.source)]:
        removed.append(f"instruction:*:{i.tag}")
        s.global_instructions.remove(i)
    for e in [e for e in s.global_edges if only(e.source)]:
        removed.append(f"global_edge:{e.when}")
        s.global_edges.remove(e)
    for sl in s.slots:
        if sl.confirm and only(sl.confirm_source):
            sl.confirm = False
            removed.append(f"confirm:{sl.name}")
    for t in s.tools:
        for c in [c for c in t.constraints if only(c.source)]:
            removed.append(f"constraint:{t.name}.{c.describe()}")
            t.constraints.remove(c)
    if spec.node(spec.start).say and any(c == clause for c in spec.node(spec.start).source):
        # The opening disclosure lives in the greeting text; drop it so the mutant really lacks it.
        greet = s.node(s.start)
        greet.say = greet.say.split(".")[0] + "."
        removed.append(f"say:{greet.id}")
    return s, removed


def mutation_test(spec: AgentSpec, k: int = 3, oracle: Contract | None = None, backends=None) -> dict:
    oracle = oracle or oracle_contract(spec)
    base = run_suite(spec, k, oracle, backends).verdicts()
    mutants: list[Mutant] = []
    for c in spec.clauses:
        if c["strength"] == "info":
            continue
        mutant, removed = ablate(spec, c["id"])
        if not removed:
            mutants.append(Mutant(c["id"], [], False, []))
            continue
        res = run_suite(mutant, k, oracle, backends).verdicts()
        changed = sorted({p for (p, r), v in res.items() if v != base.get((p, r))})
        mutants.append(Mutant(c["id"], removed, bool(changed), changed))
    scored = [m for m in mutants if m.removed]
    killed = sum(m.killed for m in scored)
    return {
        "score": round(killed / len(scored), 3) if scored else 0.0,
        "killed": killed,
        "mutants": len(scored),
        "no_artifact": [m.clause for m in mutants if not m.removed],
        "survivors": [{"clause": m.clause, "removed": m.removed} for m in scored if not m.killed],
        "detail": [vars(m) for m in mutants],
    }
