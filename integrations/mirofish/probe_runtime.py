"""Offline install probes. A health-only factory smoke is NOT a working simulation.

Only loopback HTTP is used. Upstream source is unmodified; no placeholder keys,
graph uploads, model requests, bank calls, or Freya sessions are created.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "vendor" / "MiroFish"
RUNTIME = ROOT / "runtime"
PIN = json.loads((ROOT / "upstream.json").read_text(encoding="utf-8"))
KEYS = ("LLM_API_KEY", "ZEP_API_KEY")


def offline_environment() -> dict[str, str]:
    env = dict(os.environ)
    for name in (*KEYS, "ZEP_API_URL", "LLM_BOOST_API_KEY", "LLM_BOOST_BASE_URL", "LLM_BOOST_MODEL_NAME"):
        env.pop(name, None)
    env.update(PYTHON_DOTENV_DISABLED="1", PYTHONIOENCODING="utf-8",
               PYTHONDONTWRITEBYTECODE="1", FLASK_DEBUG="False", FLASK_HOST="127.0.0.1")
    return env


def block_external_network() -> list[str]:
    # Block connects before imports: factory smoke must not use external services.
    blocked: list[str] = []
    def guard(event: str, args: tuple) -> None:
        if event == "socket.getaddrinfo" and args[0] not in ("127.0.0.1", "::1", "localhost", None):
            blocked.append("external_dns_blocked")
            raise RuntimeError("External DNS disabled for MiroFish readiness probe")
        if event == "socket.connect":
            address = args[1]
            if not isinstance(address, tuple) or address[0] not in ("127.0.0.1", "::1", "localhost"):
                blocked.append("outbound_connection_blocked")
                raise RuntimeError("External network disabled for MiroFish readiness probe")
    sys.addaudithook(guard)
    return blocked


def engine_child() -> None:
    blocked = block_external_network()
    print("ENGINE_IMPORT_STAGE=camel.models", flush=True)
    from camel.models import ModelFactory
    print("ENGINE_IMPORT_STAGE=camel.types", flush=True)
    from camel.types import ModelPlatformType
    print("ENGINE_IMPORT_STAGE=oasis", flush=True)
    import oasis
    from oasis import ActionType, LLMAction, ManualAction, generate_twitter_agent_graph
    print("MIROFISH_ENGINE=" + json.dumps({
        "status": "imports_passed", "modules": ["camel.models", "camel.types", "oasis"],
        "model_created": False, "simulation_executed": False,
        "external_connection_attempts_blocked": len(blocked),
    }), flush=True)


def health_child() -> None:
    blocked = block_external_network()
    sys.path.insert(0, str(VENDOR / "backend"))
    from app import create_app
    from app.config import Config
    from werkzeug.serving import make_server
    installed = {name: importlib.metadata.version(name) for name in
                 ("mirofish-backend", "flask", "openai", "zep-cloud", "camel-oasis", "camel-ai")}
    app = create_app()
    # Only upstream /health is exposed by this temporary smoke server.
    def health_only(environ, start_response):
        if environ.get("PATH_INFO") != "/health" or environ.get("REQUEST_METHOD") != "GET":
            start_response("503 Service Unavailable", [("Content-Type", "text/plain")])
            return [b"Readiness smoke exposes GET /health only"]
        return app(environ, start_response)
    server = make_server("127.0.0.1", 0, health_only)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        connection.request("GET", "/health")
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
        print("MIROFISH_HEALTH=" + json.dumps({
            "status_code": response.status, "body": payload,
            "host": "127.0.0.1", "port": server.server_port,
            "kind": "credential_free_upstream_app_factory_health_only_http_smoke",
            "normal_launcher_validation_bypassed_for_smoke": True,
            "configuration_errors": Config.validate(), "versions": installed,
            "external_connection_attempts_blocked": len(blocked),
            "simulation_ready": False,
        }, ensure_ascii=False), flush=True)
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()


def frontend_probe(env: dict[str, str]) -> dict:
    # Official frontend package has a Vite preview script. Exercise the built assets.
    if not (VENDOR / "frontend" / "dist" / "index.html").exists():
        raise RuntimeError("Build the frontend with npm run build before probing")
    code = ("import {preview} from 'vite'; "
            "const server=await preview({preview:{host:'127.0.0.1',port:0,strictPort:false,open:false}}); "
            "console.log('MIROFISH_FRONTEND='+server.httpServer.address().port); "
            "process.stdin.resume(); process.stdin.on('data',()=>{server.httpServer.close(()=>process.exit(0));});")
    log_path = RUNTIME / "frontend-smoke.log"
    result: dict = {"kind": "upstream_vite_preview_server_loopback_http_and_built_asset_smoke"}
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([shutil.which("node") or "node", "--input-type=module", "-e", code],
                                   cwd=VENDOR / "frontend", env=env, stdin=subprocess.PIPE,
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                content = log_path.read_text(encoding="utf-8", errors="replace")
                match = re.search(r"MIROFISH_FRONTEND=(\d+)", content)
                if match:
                    port = int(match.group(1))
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    with opener.open(f"http://127.0.0.1:{port}/", timeout=10) as response:
                        html = response.read().decode("utf-8")
                        result.update(status_code=response.status, port=port,
                                      title=re.findall(r"<title>(.*?)</title>", html),
                                      backend_api_calls=0)
                    assets = re.findall(r'(?:src|href)="(/assets/[^\"]+\.(?:js|css))"', html)
                    result["built_assets"] = []
                    for asset in assets:
                        with opener.open(f"http://127.0.0.1:{port}{asset}", timeout=10) as response:
                            result["built_assets"].append({"path": asset, "status_code": response.status,
                                                          "bytes": len(response.read())})
                    result["built_assets_passed"] = bool(assets) and all(
                        asset["status_code"] == 200 and asset["bytes"] > 0 for asset in result["built_assets"])
                    break
                if process.poll() is not None:
                    raise RuntimeError(f"Vite exited with {process.returncode}; see runtime/frontend-smoke.log")
                time.sleep(0.1)
            else:
                raise RuntimeError("Vite startup timed out; see runtime/frontend-smoke.log")
        finally:
            if process.poll() is None:
                try:
                    process.communicate(b"stop\n", timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=5)
            result["process_exit_code"] = process.returncode
            result["stopped_after_probe"] = process.poll() is not None
    return result


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--health-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--engine-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--engine-timeout", type=int, default=60,
                        help="Seconds allowed for the isolated OASIS/CAMEL import smoke (default 60)")
    args = parser.parse_args()
    if args.health_child:
        health_child()
        return 0
    if args.engine_child:
        engine_child()
        return 0
    RUNTIME.mkdir(exist_ok=True)
    actual_pin = subprocess.check_output(["git", "-C", str(VENDOR), "rev-parse", "HEAD"], text=True).strip()
    if actual_pin != PIN["commit"]:
        raise RuntimeError("Vendor commit differs from upstream.json")
    backend_python = VENDOR / "backend" / ".venv" / "Scripts" / "python.exe"
    if not backend_python.exists():
        raise RuntimeError("Run install.ps1 before probing the backend")
    env = offline_environment()
    result: dict = {
        "commit": actual_pin,
        "credential_mode": "forced_empty_named_MiroFish_keys_and_dotenv_disabled_in_probe_children",
        "ambient_named_configuration_present": {name: bool(os.environ.get(name)) for name in KEYS},
        "vendor_dotenv_exists": (VENDOR / ".env").exists(),
        "simulation_executed": False, "bank_calls": 0, "freya_tests": 0,
        "locks_sha256": {str(p.relative_to(VENDOR)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (VENDOR / "backend" / "uv.lock", VENDOR / "frontend" / "package-lock.json")},
    }
    standard = subprocess.run([str(backend_python), "run.py"], cwd=VENDOR / "backend", env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
    (RUNTIME / "normal-startup.log").write_text(standard.stdout + standard.stderr, encoding="utf-8")
    result["normal_backend_startup"] = {
        "exit_code": standard.returncode,
        "missing_configuration": [key for key in KEYS if key in standard.stdout],
        "listener_started": False,
        "status": "blocked_missing_credentials" if standard.returncode == 1 and all(key in standard.stdout for key in KEYS)
                  else "unexpected_result_inspect_runtime_log",
    }
    child = subprocess.run([str(backend_python), str(Path(__file__).resolve()), "--health-child"],
                           cwd=VENDOR / "backend", env=env, capture_output=True, text=True,
                           encoding="utf-8", timeout=60)
    (RUNTIME / "health-smoke.log").write_text(child.stdout + child.stderr, encoding="utf-8")
    matches = re.findall(r"^MIROFISH_HEALTH=(.*)$", child.stdout, re.MULTILINE)
    result["backend_health_smoke"] = json.loads(matches[-1]) if matches else {
        "status": "failed", "exit_code": child.returncode, "log": "runtime/health-smoke.log"}
    try:
        engine = subprocess.run([str(backend_python), str(Path(__file__).resolve()), "--engine-child"],
                                cwd=VENDOR / "backend", env=env, capture_output=True, text=True,
                                encoding="utf-8", timeout=args.engine_timeout)
        (RUNTIME / "engine-import.log").write_text(engine.stdout + engine.stderr, encoding="utf-8")
        engine_matches = re.findall(r"^MIROFISH_ENGINE=(.*)$", engine.stdout, re.MULTILINE)
        result["engine_import_smoke"] = json.loads(engine_matches[-1]) if engine_matches else {
            "status": "failed", "exit_code": engine.returncode, "log": "runtime/engine-import.log"}
    except subprocess.TimeoutExpired as exc:
        as_text = lambda data: data.decode("utf-8", errors="replace") if isinstance(data, bytes) else (data or "")
        (RUNTIME / "engine-import.log").write_text(as_text(exc.stdout) + as_text(exc.stderr), encoding="utf-8")
        result["engine_import_smoke"] = {"status": "timed_out", "timeout_seconds": args.engine_timeout,
                                         "log": "runtime/engine-import.log"}
    try:
        result["frontend_health_smoke"] = frontend_probe(env)
    except Exception as exc:
        result["frontend_health_smoke"] = {"status": "failed", "error": str(exc)}
    result["all_install_smokes_passed"] = (
        result["normal_backend_startup"]["status"] == "blocked_missing_credentials"
        and result["backend_health_smoke"].get("status_code") == 200
        and result["backend_health_smoke"].get("body", {}).get("status") == "ok"
        and result["frontend_health_smoke"].get("status_code") == 200
        and result["frontend_health_smoke"].get("built_assets_passed") is True
        and result["engine_import_smoke"].get("status") == "imports_passed")
    (RUNTIME / "probe.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["all_install_smokes_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
