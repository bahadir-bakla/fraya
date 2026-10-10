"""Publish and empirically test a development draft, preserving its review issues.

This command does not mark a candidate reviewed or final-ready. Use build-live
for the complete source compilation and independent review gates.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skill-creator-skill-lift"))
from agent_forge.builder_live import Evidence, LiveBackend
from agent_forge.freya_compiler import compile_workflow
from agent_forge.freya_lint import lint_workflow
from agent_forge.guarded_freya_adapter import validate_guard_wiring
from agent_forge.tool_api import load_tool_api


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate")
    parser.add_argument("--tool-api", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--slot", required=True)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--review", required=True)
    parser.add_argument("--budget-seconds", type=int, default=600)
    parser.add_argument("--chat-entry-adapter", action="store_true", help="Lower fixed TTS entries to documented exact-line LLM entries for text simulations")
    args = parser.parse_args()
    if not 180 <= args.budget_seconds <= 1800:
        parser.error("Probe budget must be 180..1800 seconds")
    cases = args.cases.split(",")
    if not cases or any(not case for case in cases):
        parser.error("Select explicit practice cases")
    candidate = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    review = json.loads(Path(args.review).read_text(encoding="utf-8"))
    workflow = compile_workflow(json.loads(candidate["workflow_json"]), load_tool_api(args.tool_api), chat_mode=args.chat_entry_adapter)
    lint = lint_workflow(workflow, load_tool_api(args.tool_api))
    lint += validate_guard_wiring(workflow)
    if any(item["severity"] == "error" for item in lint):
        raise ValueError("Draft has structural errors; inspect with the builder linter first")
    evidence = Evidence(Path(args.out), args.budget_seconds)
    backend = LiveBackend(ROOT, ROOT / "competition-v3/build-the-builder", evidence)
    try:
        evidence.trace.update(mode="unreviewed_development_probe", final_ready=False,
                              chat_entry_adapter=args.chat_entry_adapter,
                              source_candidate=str(Path(args.candidate).resolve()))
        evidence.write("independent-review.json", review)
        evidence.write("lint.json", lint)
        evidence.write("limitations.json", candidate["limitations"])
        evidence.event("development_probe_started", independent_verdict=review["verdict"])
        path = evidence.write("workflow.json", workflow)
        deployed = backend.deploy(path, args.slot, workflow)
        rows = backend.practice(deployed, cases)
        evidence.write("practice.json", rows)
        exported = backend.call("export", deployed["workflow_id"], filename=args.slot + ".workflow.json")
        envelope = json.loads(Path(exported["path"]).read_text(encoding="utf-8"))
        evidence.write("platform-export.workflow.json", envelope)
        result = dict(status="probe_passed" if all(row["pass"] for row in rows) else "probe_failed",
                      passed=sum(row["pass"] for row in rows), total_trials=len(rows),
                      independent_verdict=review["verdict"], final_ready=False, deployment=deployed)
        evidence.finish(result["status"], result=result, platform_tool_calls=backend.tool_calls)
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "probe_passed" else 1
    except Exception as exc:
        evidence.finish("probe_error", error=type(exc).__name__, final_ready=False)
        raise
    finally:
        backend.close()


if __name__ == "__main__":
    raise SystemExit(main())
