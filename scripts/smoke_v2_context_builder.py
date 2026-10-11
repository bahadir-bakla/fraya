"""Actual builder diagnostic integration smoke; no generation or Freya calls.

Requires locally retained historical practice seed/call recordings. Those raw
recordings are deliberately not shared in Git. Keeps the original runs intact.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("local_pair", ROOT / "scripts/run_local_builder_pair.py")
pair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pair)
builder = pair.builder


class SmokeRun(pair.ComparisonRun):
    def prepare_semantic_assist(self):
        # This verifies the changed observed-turn V2 route. Document retrieval
        # was already exercised by the real paired builds; no reindex is needed.
        self.semantic_ready = False
        self.event("smoke_scope", document_retrieval_executed=False,
                   model_generation_executed=False, Freya_calls=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Do not overwrite smoke evidence")
    old = sys.argv
    try:
        sys.argv = ["builder.py", str(builder.KIT / "briefs/brief-a.md"),
                    "--practice-repair", pair.SEED, "--repair-first", "--local-only",
                    "--slot", "local-v2-context-integration-smoke", "--minutes", "5",
                    "--semantic-assist", "auto", "--dialogue-assist", "off",
                    "--finetuned-assist", "required", "--finetuned-version", "v2",
                    "--semantic-python", sys.executable]
        parsed = builder.arguments()
    finally:
        sys.argv = old
    for name in tuple(os.environ):
        if any(word in name.upper() for word in ("API_KEY", "TEAM_KEY", "TOKEN", "SECRET", "PASSWORD")):
            os.environ.pop(name)
    with builder.slot_lock(builder.ROOT / ".state/slots" / (parsed.slot + ".lock")):
        run = SmokeRun(parsed)
        run.prepare()
        run.prepare_finetuned_assist()
        run.check_pinned_evidence()
        if not (run.finetuned_ready and run.finetuned_context_ready):
            raise ValueError("Actual builder context integration unavailable")
        envelope = json.loads((run.work / "finetuned-context-evidence.json").read_text(encoding="utf-8"))
        run.phase("completed_diagnostic", ended=builder.stamp(), published=False,
                  evaluation="local_diagnostic_only", model_generation_executed=False)
        result = {"status": "COMPLETED_ACTUAL_BUILDER_CONTEXT_SMOKE", "run_id": run.id,
                  "rows": len(envelope["rows"]), "context_audit_status": envelope["status"],
                  "domain_disagreement_rows": sum(row["domain_disagreement"] for row in envelope["rows"]),
                  "finetuned_ready": run.finetuned_ready,
                  "context_audit_ready": run.finetuned_context_ready,
                  "source_sha256": {name: hashlib.sha256((builder.ROOT / name).read_bytes()).hexdigest()
                                    for name in ("builder.py", "finetuned_context_audit.py", "finetuned_assist.py")},
                  "artifacts_sha256": {name: hashlib.sha256((run.work / name).read_bytes()).hexdigest()
                                       for name in ("finetuned-evidence.json", "finetuned-context-evidence.json")},
                  "Freya_calls": 0, "model_generation_executed": False, "published": False,
                  "bank_authority": False, "financial_authorization": "UNKNOWN"}
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
