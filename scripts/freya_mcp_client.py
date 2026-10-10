"""Call the local MCP bridge now, including before an existing chat reloads tools."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def call(request_path: Path, output_path: Path) -> int:
    requests = json.loads(request_path.read_text(encoding="utf-8-sig"))
    if not isinstance(requests, list) or not requests:
        raise ValueError("Request file must contain a nonempty list of tool calls")
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "calls": []}
    server = StdioServerParameters(command=str(ROOT / "skill-creator-skill-lift" / "integrations" / "freya-mcp" / ".venv" / "Scripts" / "python.exe"), args=[
        "-X", "utf8", "-B", str(ROOT / "scripts" / "freya_dpapi_server.py"),
    ])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    async with stdio_client(server) as streams:
        async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=30)) as session:
            initialized = await session.initialize()
            listing = await session.list_tools()
            report["server"] = initialized.serverInfo.model_dump()
            report["tools"] = [tool.name for tool in listing.tools]
            for request in requests:
                result = await session.call_tool(request["tool"], request.get("arguments", {}))
                texts = [item.text for item in result.content if item.type == "text"]
                decoded = json.loads(texts[0]) if len(texts) == 1 else {"content": texts}
                entry = {"tool": request["tool"], "arguments": request.get("arguments", {}), "result": decoded}
                report["calls"].append(entry)
                # Save after each call: recover ids even if a subsequent tool fails.
                output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                data = decoded.get("data", {})
                summary = {"tool": request["tool"], "ok": decoded.get("ok", not result.isError)}
                if isinstance(data, dict):
                    for key in ("status", "live_connected", "workspace_id", "remote_checked", "local_structure_valid", "node_count", "workflow_id", "agent_id", "published", "version", "action", "simulation_id", "terminal", "path", "secrets_redacted"):
                        if key in data:
                            summary[key] = data[key]
                if not summary["ok"]:
                    summary["error"] = decoded.get("error", "MCP call failed")
                print(json.dumps(summary, ensure_ascii=False), flush=True)
                if result.isError or decoded.get("ok") is False:
                    break
    report["ended_at"] = datetime.now(timezone.utc).isoformat()
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved MCP evidence: {output_path}")
    return 0 if len(report["calls"]) == len(requests) and all(c["result"].get("ok") for c in report["calls"]) else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    return asyncio.run(call(args.request.resolve(), args.out.resolve()))


if __name__ == "__main__":
    raise SystemExit(main())
