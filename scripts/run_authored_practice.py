"""Run an explicitly pinned, manifest-bound authored text catalog in practice."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slot", required=True)
    parser.add_argument("--version", required=True, type=int)
    parser.add_argument("--brief", required=True, choices=("A", "B"))
    parser.add_argument("--pack", required=True, type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--only", required=True)
    parser.add_argument("--budget-seconds", type=int, default=1200)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not 60 <= args.budget_seconds <= 1800 or args.version < 1:
        parser.error("budget must be 60..1800 seconds and version positive")
    catalog_root = (ROOT / "research/customer-benchmark").resolve()
    pack = args.pack.resolve()
    manifest = args.manifest.resolve()
    if not all(p.is_relative_to(catalog_root) for p in (pack, manifest)):
        parser.error("catalog and manifest must be in research/customer-benchmark")
    sys.path.insert(0, str(ROOT / "integrations/customer-datasets"))
    import benchmark_runner
    from bound_stress_catalog import BoundStressCatalog
    adapter = BoundStressCatalog(pack, expected_sha256=args.sha256,
                                manifest=manifest, manifest_sha256=args.manifest_sha256)
    rows = adapter.rows()
    plan = benchmark_runner.plan(rows, adapter, brief=args.brief, only=args.only,
                                 reps=3, batch_size=5, parallel_reps=True)
    slots = json.loads((ROOT / "competition/.state/freya-agents.json").read_text())
    slot = slots[args.slot]
    if slot["version"] != args.version:
        parser.error("slot version differs from the explicitly requested version")
    adapter.verify_pack()
    print(json.dumps({"scope": "authored text practice, three repetitions",
                      "slot": args.slot, "version": args.version,
                      "pack_sha256": hashlib.sha256(pack.read_bytes()).hexdigest(),
                      "plan": plan, "execution_requested": args.execute}), flush=True)
    if not args.execute:
        return 0
    sys.path.insert(0, str(ROOT / "scripts"))
    from freya_dpapi_server import inject_credentials
    inject_credentials()
    return benchmark_runner.main([
        "--execute", "--cases", str(pack), "--agent-id", slot["agent_id"],
        "--brief", args.brief, "--only", args.only, "--reps", "3",
        "--batch-size", "5", "--parallel-reps", "--budget-seconds", str(args.budget_seconds)
    ], adapter=adapter)


if __name__ == "__main__":
    raise SystemExit(main())
