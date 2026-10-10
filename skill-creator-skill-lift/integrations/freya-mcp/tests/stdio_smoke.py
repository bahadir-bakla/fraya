"""Real JSON-RPC initialize/list/call smoke with bounded subprocess lifetime."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[2]


def smoke(command=None, args=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("FREYA_")}
    env["PYTHONUTF8"] = "1"
    cmd = [command or sys.executable, *(args or [str(ROOT / "freya_mcp" / "server.py"), "--workspace", str(WORKSPACE)])]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", env=env, cwd=ROOT)
    replies = queue.Queue()
    errors = []

    def receive():
        for line in proc.stdout:
            replies.put(line)

    def drain_errors():
        for line in proc.stderr:
            errors.append(line)

    threading.Thread(target=receive, daemon=True).start()
    threading.Thread(target=drain_errors, daemon=True).start()

    def send(method, params=None, rid=None):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if rid is not None:
            message["id"] = rid
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()
        if rid is None:
            return None
        try:
            line = replies.get(timeout=15)
        except queue.Empty:
            raise RuntimeError("No MCP reply; child exit=" + str(proc.poll()) + "; stderr=" + "".join(errors)) from None
        result = json.loads(line)
        assert result.get("id") == rid, result
        assert "error" not in result, result
        return result["result"]

    try:
        init = send("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                  "clientInfo": {"name": "freya-offline-smoke", "version": "1.0"}}, 1)
        assert init["serverInfo"]["name"] == "freya-mcp"
        send("notifications/initialized")
        listing = send("tools/list", {}, 2)
        names = [t["name"] for t in listing["tools"]]
        assert len(names) == 22
        assert not any("delete" in name for name in names)
        result = send("tools/call", {"name": "freya_health", "arguments": {}}, 3)
        health = json.loads(result["content"][0]["text"])
        assert health["ok"] and health["data"]["status"] == "unconfigured"
        cases = send("tools/call", {"name": "freya_practice_cases", "arguments": {"case_ids": ["PUB-01"]}}, 4)
        assert json.loads(cases["content"][0]["text"])["data"][0]["id"] == "PUB-01"
        dry = send("tools/call", {"name": "freya_validate_workflow", "arguments": {
            "workflow_path": str(WORKSPACE / "competition-v3" / "build-the-builder" / "examples" / "base-agent.json"), "remote": False}}, 5)
        assert json.loads(dry["content"][0]["text"])["data"]["local_structure_valid"]
        missing = send("tools/call", {"name": "freya_list_workspaces", "arguments": {}}, 6)
        assert not json.loads(missing["content"][0]["text"])["ok"]
        return {"initialize": "passed", "protocol_version": init["protocolVersion"], "tools_list": "passed",
                "tool_count": len(names), "tools": names, "health": health["data"], "offline_calls": "passed",
                "live_tested": False}
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=5)
        proc.stdout.close()
        proc.stderr.close()


if __name__ == "__main__":
    args = None
    if "--debug" in sys.argv:
        args = ["-X", "utf8", "-c", "import faulthandler,runpy,sys; faulthandler.dump_traceback_later(5); sys.argv=['server.py']; runpy.run_path('freya_mcp/server.py',run_name='__main__')"]
    print(json.dumps(smoke(args=args), indent=2))
