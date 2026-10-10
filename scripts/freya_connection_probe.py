"""Read-only connectivity probe against routes documented in the official kit."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "competition-v3" / "build-the-builder"))
import freya


def main() -> int:
    if not os.environ.get("FREYA_API_KEY"):
        print("FREYA_API_KEY is required", file=sys.stderr)
        return 2
    report = {"at": datetime.now(timezone.utc).isoformat(), "base_url": freya.URL}
    try:
        result = freya.api("GET", "/api/v2/workspaces")
        items = (result.get("workspaces") or result.get("items") or []) if isinstance(result, dict) else result
        report.update(authenticated=True, workspace_count=len(items), workspace_ids=[w["id"] for w in items])
    except Exception as exc:
        report.update(authenticated=False, error_type=type(exc).__name__,
                      message=str(exc).replace(os.environ["FREYA_API_KEY"], "[redacted]")[:350])
    target = ROOT / "analysis" / "freya-live-probe.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["authenticated"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
