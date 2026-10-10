"""CLI.

    python -m voice_contract table   POLICY
    python -m voice_contract audit   POLICY TRANSCRIPT.json[l]
    python -m voice_contract emit    POLICY OUT_DIR [--workspace ID --entity ID]
    python -m voice_contract bench   POLICY [--chunks N]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

from .audit import audit_transcript, findings_json, load_transcript, violations
from .contract import ContractError, load_contract
from .emit import freya_personas, freya_unit_tests, pipecat_scenarios, uncovered
from .guard import StreamGuard


def _bench(contract, chunks: int) -> dict:
    """Per-chunk guard cost on a realistic streamed reply, in milliseconds."""
    reply = (
        "Kimliğinizi doğruladığım için teşekkürler. Kartınızın son ödeme tarihi geçmiş görünüyor, "
        "dilerseniz şimdi taksitlendirme seçeneklerini konuşabiliriz veya bir ödeme planı oluşturabiliriz. "
    )
    text = (reply * (chunks * 4 // len(reply.split()) + 1)).split(" ")[: chunks * 4]
    pieces = [" ".join(text[i : i + 4]) + " " for i in range(0, len(text), 4)]
    g = StreamGuard(contract)
    g.on_event("identity_verified")
    g.start_agent_turn()
    per_chunk = []
    for p in pieces:
        t0 = time.perf_counter()
        g.on_agent_chunk(p)
        per_chunk.append((time.perf_counter() - t0) * 1000)
    g.end_agent_turn()
    per_chunk.sort()
    return {
        "chunks": len(per_chunk),
        "p50_ms": round(statistics.median(per_chunk), 4),
        "p95_ms": round(per_chunk[int(len(per_chunk) * 0.95) - 1], 4),
        "max_ms": round(per_chunk[-1], 4),
        "hold_chars": contract.hold_chars,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="voice_contract")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("table")
    s.add_argument("policy")
    s = sub.add_parser("audit")
    s.add_argument("policy")
    s.add_argument("transcript")
    s = sub.add_parser("emit")
    s.add_argument("policy")
    s.add_argument("out_dir")
    s.add_argument("--workspace", default="00000000-0000-0000-0000-000000000000")
    s.add_argument("--entity", default="AGENT_ID")
    s = sub.add_parser("bench")
    s.add_argument("policy")
    s.add_argument("--chunks", type=int, default=200)
    args = ap.parse_args(argv)

    try:
        contract = load_contract(args.policy)
    except ContractError as exc:
        print(f"policy invalid:\n{exc}", file=sys.stderr)
        return 2

    if args.cmd == "table":
        print(contract.table())
    elif args.cmd == "audit":
        found = violations(contract, audit_transcript(contract, load_transcript(args.transcript)))
        print(findings_json(found))
        return 1 if found else 0
    elif args.cmd == "emit":
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "freya_unit_tests.json").write_text(
            json.dumps(freya_unit_tests(contract, args.workspace, args.entity), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (out / "freya_personas.json").write_text(json.dumps(freya_personas(contract), ensure_ascii=False, indent=2), encoding="utf-8")
        import yaml

        (out / "pipecat_eval.yaml").write_text(
            yaml.safe_dump(pipecat_scenarios(contract), allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        (out / "contract.md").write_text(contract.table() + "\n", encoding="utf-8")
        missing = uncovered(contract)
        print(f"wrote {out}/: freya_unit_tests.json, freya_personas.json, pipecat_eval.yaml, contract.md")
        if missing:
            print(f"rules with no probe (no generated test): {', '.join(missing)}")
    elif args.cmd == "bench":
        print(json.dumps(_bench(contract, args.chunks), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
