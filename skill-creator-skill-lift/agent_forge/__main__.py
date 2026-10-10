"""CLI.

    python -m agent_forge build  SOP.md out/ [--k 3] [--llm [compile|all]] [--no-mutate] [--quiet]
    python -m agent_forge draft  SOP.md            # print the draft spec JSON
    python -m agent_forge clauses SOP.md           # how the SOP was split and classified
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .extract import RuleExtractor
from .exam import UntestedClauses
from .forge import forge
from .sop import load_sop
from .input_contract import inspect_inputs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agent_forge", description="Build a tested, guarded voice agent from an SOP.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("sop")
    b.add_argument("out")
    b.add_argument("--k", type=int, default=3, help="runs per simulated caller (pass^k)")
    b.add_argument("--llm", nargs="?", const="all", choices=["all", "compile"], default=False,
                   help="use Claude: 'compile' for the two compilers, perception and the guard (simulated calls stay "
                        "offline); 'all' (the default with --llm) also plays agent and caller in every call")
    b.add_argument("--quiet", action="store_true", help="no progress lines on stderr")
    b.add_argument("--no-mutate", action="store_true")
    b.add_argument("--allow-untested", action="store_true",
                   help="build even when a binding clause has no test (the report lists them)")
    d = sub.add_parser("draft")
    d.add_argument("sop")
    c = sub.add_parser("clauses")
    c.add_argument("sop")
    i = sub.add_parser("inspect", help="inventory briefs and their supplied OpenAPI with source provenance")
    i.add_argument("briefs", nargs="+")
    i.add_argument("--tool-api", required=True)
    i.add_argument("--out", required=True, help="input contract JSON path")
    live = sub.add_parser("build-live", help="compile unseen sources, publish and evaluate an official Freya workflow")
    live.add_argument("briefs", nargs="+")
    live.add_argument("--tool-api", required=True)
    live.add_argument("--out", required=True)
    live.add_argument("--kit", default="../competition-v3/build-the-builder")
    live.add_argument("--model", default="gpt-6.1-sol")
    live.add_argument("--budget-seconds", type=int, default=1800)
    live.add_argument("--slot", default="codex-builder-rd")
    live.add_argument("--cases", default="", help="comma-separated official case IDs; absent means publish without testing")
    live.add_argument("--style", default="")
    live.add_argument("--reps", type=int, default=1)
    live.add_argument("--repairs", type=int, default=2)
    live.add_argument("--compile-only", action="store_true")
    live.add_argument("--policy-checkpoint", default="", help="resume matching policy.json; original start time still counts")
    live.add_argument("--allow-source-gaps", action="store_true", help="practice development only; preserve source gaps, never suppress concrete critic errors")
    live.add_argument("--workflow-checkpoint", default="", help="candidate envelope to repair from the same policy checkpoint run")
    a = ap.parse_args(argv)

    if a.cmd == "build-live":
        from .builder_live import build_live, BuildFailure
        try:
            result = build_live(a.briefs, a.tool_api, a.out, root=Path(__file__).resolve().parents[2],
                                kit=Path(a.kit).resolve(), model=a.model, budget_seconds=a.budget_seconds,
                                slot=a.slot, case_ids=[c.strip() for c in a.cases.split(",") if c.strip()],
                                style=a.style, repetitions=a.reps, repairs=a.repairs, compile_only=a.compile_only,
                                policy_checkpoint=a.policy_checkpoint, allow_source_gaps=a.allow_source_gaps,
                                workflow_checkpoint=a.workflow_checkpoint)
        except (BuildFailure, ValueError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result["status"] == "practice_failed" else 0
    if a.cmd == "inspect":
        try:
            contract = inspect_inputs(a.briefs, a.tool_api)
            out = Path(a.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except (ValueError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"inventoried {len(contract['documents'])} documents; wrote {out}")
        print("Policy compilation and Freya workflow generation remain pending.")
        return 0
    if a.cmd == "clauses":
        title, clauses = load_sop(a.sop)
        print(title)
        for cl in clauses:
            print(f"§{cl.id:<6} {cl.strength:<9} {cl.text}")
        return 0
    if a.cmd == "draft":
        print(RuleExtractor().extract(*load_sop(a.sop)).to_json())
        return 0
    try:
        res = forge(a.sop, a.out, k=a.k, llm=a.llm, mutate=not a.no_mutate, allow_untested=a.allow_untested,
                    progress=not a.quiet)
    except UntestedClauses as e:
        print(str(e), file=sys.stderr)
        for n in e.exam.notes:
            print("  " + n, file=sys.stderr)
        return 2
    s = res.summary()
    print(json.dumps({k: s[k] for k in ("agent", "before", "after", "patches_accepted", "patches_rejected",
                                        "needs_review", "mutation_score", "seconds")}, ensure_ascii=False, indent=2))
    print(f"wrote {len(res.files)} files to {a.out} (start with report.md)")
    # Green only when every exam caller passes on the final build: the core agent and the whole topology.
    failing = sorted({r.persona for r in (res.topo_after.runs if res.topo_after else []) if r.verdict == "fail"})
    if failing:
        print("callers still failing: " + ", ".join(failing), file=sys.stderr)
    for u in res.unreached:
        print("export: " + u, file=sys.stderr)
    return 0 if s["after"]["fails"] == 0 and not failing and not res.unreached else 1


if __name__ == "__main__":
    sys.exit(main())
