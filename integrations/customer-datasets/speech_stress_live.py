"""Opt-in hosted runner for authored text-only speech stress approximations.

Defaults to a keyless, nonexecuting plan. Execution requires --execute,
--agent-id, --brief and exact --only variant IDs, as enforced by the existing
benchmark runner. Its original scorer, source/pack hashes, call provenance,
published-version guards and official transport are retained. These scenarios
do not certify voice or ASR behavior. speech_stress_adapter's CLI stays offline.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import benchmark_runner
import speech_stress_adapter

DEFAULT_PACK = speech_stress_adapter.OUT


def main(argv=None, *, client=None):
    """Verify the selected catalog locally, then delegate the whole run."""
    argv = list(sys.argv[1:] if argv is None else argv)
    # Read only the catalog option; selection, budgets, batches and execution
    # remain owned by benchmark_runner.main rather than a second runner.
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--cases", type=Path, default=DEFAULT_PACK)
    args, _ = parser.parse_known_args(argv)
    try:
        speech_stress_adapter.verify_pack(args.cases)
    except (ValueError, OSError, benchmark_runner.RunnerError):
        print(json.dumps({"execution_status": "not_completed",
                          "error_code": "pack_integrity_failed"}))
        return 2
    return benchmark_runner.main(
        ["--cases", str(DEFAULT_PACK), *argv],
        adapter=speech_stress_adapter, client=client)


if __name__ == "__main__":
    raise SystemExit(main())
