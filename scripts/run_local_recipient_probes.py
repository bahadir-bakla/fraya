"""Bounded source CPU diagnostics on fresh authored name/recipient speech.

Exercises one recipient transition with an UNKNOWN extraction hypothesis. This
measures deterministic raw-speech fallback, never ASR, model extraction, identity
verification, or an original full-call score. No bank or network operation runs.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-workflow", type=Path,
                        default=ROOT / "competition/releases/minilm-v2-local-a-20261011/workflow.json")
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Never overwrite probe evidence")
    probes = json.loads(args.probes.read_text(encoding="utf-8"))
    if not isinstance(probes, list) or not 1 <= len(probes) <= 96:
        raise ValueError("Invalid bounded probe list")
    if len({p["id"] for p in probes}) != len(probes):
        raise ValueError("Duplicate probe identity")
    for p in probes:
        if any(not isinstance(p[k], str) or len(p[k]) > 600 for k in
               ("id", "first_name", "last_name", "title", "raw", "rationale")):
            raise ValueError("Probe field contract")
        if p["expected_self"] is not None and type(p["expected_self"]) is not bool:
            raise ValueError("Expectation must be semantic boolean or explicit unknown")
    driver = load("recipient_probe_driver", ROOT / "scripts/local_public_replay.py")
    driver.deny_network()
    sys.path.insert(0, str(ROOT / "integrations/customer-datasets"))
    wr = load("recipient_probe_replay", ROOT / "integrations/customer-datasets/workflow_replay.py")
    sources = {"classical_A10": ROOT / "competition/releases/classic-baseline/a.review-template.json",
               "V2_assisted_A": args.candidate_workflow.resolve()}
    files = [args.probes.resolve(), Path(__file__).resolve(), ROOT / "scripts/local_public_replay.py",
             ROOT / "integrations/customer-datasets/workflow_replay.py", *sources.values()]
    pins = {p.relative_to(ROOT).as_posix(): sha(p) for p in files}
    results = {}
    for arm, source in sources.items():
        data = json.loads(source.read_text(encoding="utf-8"))
        workflow = data.get("workflow", data)
        snippet = workflow["nodes"]["dispatch"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
        rows = []
        for repetition in range(1, 4):
            for probe in probes:
                variables = {"first_name": probe["first_name"], "last_name": probe["last_name"],
                             "title": probe["title"], "customer_id": "synthetic-probe",
                             "now": "2026-10-19T10:00:00+02:00", "mode": "event"}
                code = wr.Code()
                error = None
                try:
                    code.run(snippet, variables)
                    if variables["state"]["phase"] != "recipient":
                        raise ValueError("Unexpected initial recipient phase")
                    variables.update(event="k=unknown;c=1;END", recipient_act="unknown",
                                     raw=probe["raw"], admin="none")
                    code.run(snippet, variables)
                except Exception as exc:
                    error = type(exc).__name__
                state = variables.get("state", {})
                selected = state.get("phase") in {"dob", "phone"}
                # Neither semantic expectation nor rationale enters execution.
                correct = None if probe["expected_self"] is None or error else selected == probe["expected_self"]
                rows.append({"id": probe["id"], "repetition": repetition, "raw": probe["raw"],
                             "expected_self": probe["expected_self"], "recipient_selected": selected,
                             "phase": state.get("phase"), "route": variables.get("route"),
                             "verified": state.get("verified"), "correct": correct,
                             "runtime_error": error, "dialogue": variables.get("dialogue_line")})
        results[arm] = {"rows": rows, "executions": len(rows),
                        "known": sum(r["correct"] is not None for r in rows),
                        "correct": sum(r["correct"] is True for r in rows),
                        "unresolved": sum(r["expected_self"] is None for r in rows),
                        "errors": sum(r["runtime_error"] is not None for r in rows),
                        "failing_ids": sorted({r["id"] for r in rows if r["correct"] is False}),
                        "all_still_unverified": all(r["verified"] is False for r in rows)}
    if pins != {p.relative_to(ROOT).as_posix(): sha(p) for p in files}:
        raise ValueError("Probe sources changed during execution")
    output = {"status": "COMPLETED_FRESH_AUTHORED_RECIPIENT_SOURCE_DIAGNOSTIC",
              "cases": len(probes), "repeats": 3, "source_sha256": pins, "arms": results,
              "bank_calls": 0, "Freya_calls": 0, "extractor_executed": False,
              "scope": "One current raw utterance with UNKNOWN extraction; synthetic author labels, same-model ancestry possible. Three deterministic repeats are not independent qualification or full-bank/voice score. A false recipient match still does not establish verified identity."}
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: {n: v[n] for n in ("executions", "known", "correct", "unresolved", "errors", "failing_ids")}
                      for k, v in results.items()}))


if __name__ == "__main__":
    main()
