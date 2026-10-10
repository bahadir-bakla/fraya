"""Scoped CLIProxy/Zep configuration and redacted local service entry points.

Credentials are read only from the explicitly supplied CLIProxy config and Zep
DPAPI path. They never enter command arguments, evidence, or plaintext files.
The upstream MiroFish launcher and source are left intact.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import time
import traceback
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import yaml

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RUNTIME = HERE / "runtime"
VENDOR = HERE / "vendor" / "MiroFish"


def redact(value, secrets=()):
    text = value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED_JWT]", text)
    text = re.sub(r"(?i)(bearer\s+)[^\s\"',;]+", r"\1[REDACTED]", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}", "[REDACTED_KEY]", text)
    return text


class RedactedStream:
    def __init__(self, stream, secrets):
        self.stream, self.secrets = stream, tuple(secrets)

    def write(self, value):
        return self.stream.write(redact(value, self.secrets))

    def __getattr__(self, name):
        return getattr(self.stream, name)


def install_redaction(secrets):
    secrets = tuple(s for s in secrets if s)
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if stream is not None and not isinstance(stream, RedactedStream):
            setattr(sys, name, RedactedStream(stream, secrets))
    factory = logging.getLogRecordFactory()

    def redacted_record(*args, **kwargs):
        record = factory(*args, **kwargs)
        record.msg, record.args = redact(record.getMessage(), secrets), ()
        if record.exc_info:
            record.exc_text = redact("".join(traceback.format_exception(*record.exc_info)), secrets)
            record.exc_info = None
        if record.stack_info:
            record.stack_info = redact(record.stack_info, secrets)
        return record

    logging.setLogRecordFactory(redacted_record)


def proxy_settings(config_path):
    path = Path(config_path).resolve(strict=True)
    document = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    host, port = document.get("host", "127.0.0.1"), int(document.get("port", 8317))
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("The designated CLIProxy configuration must bind to loopback")
    if (document.get("tls") or {}).get("enable"):
        raise ValueError("This launcher expects the designated local HTTP proxy")
    keys = [key for key in document.get("api-keys", []) if isinstance(key, str) and key.strip()]
    if not keys:
        raise ValueError("The designated CLIProxy config has no client API key")
    return {
        "config_path": path, "config_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "key": keys[0], "keys": keys,
        "base_url": f"http://{'[' + host + ']' if ':' in host else host}:{port}/v1",
    }


def zep_key(path):
    source = ROOT / "scripts" / "freya_dpapi_server.py"
    specification = importlib.util.spec_from_file_location("mirofish_dpapi", source)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    # Only this explicit encrypted key is decrypted. Never call inject_credentials().
    key = module.unprotect(Path(path).resolve(strict=True))
    if not key:
        raise ValueError("The explicitly supplied Zep key decrypted to an empty value")
    return key


def protect_key(path, key):
    """Match the existing Windows-user DPAPI hex/UTF-16 format, in memory."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    encoded = key.encode("utf-16-le")
    buffer = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
    source, destination = Blob(len(encoded), buffer), Blob()
    crypto = ctypes.WinDLL("crypt32", use_last_error=True)
    crypto.CryptProtectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_wchar_p, ctypes.c_void_p,
                                      ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    crypto.CryptProtectData.restype = wintypes.BOOL
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes, kernel.LocalFree.restype = [ctypes.c_void_p], ctypes.c_void_p
    try:
        if not crypto.CryptProtectData(ctypes.byref(source), "CLIProxy client key", None, None, None, 1, ctypes.byref(destination)):
            raise RuntimeError("Windows-user DPAPI encryption failed")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(ctypes.string_at(destination.data, destination.size).hex(), encoding="ascii")
    finally:
        ctypes.memset(buffer, 0, len(encoded))
        if destination.data:
            ctypes.memset(destination.data, 0, destination.size)
            kernel.LocalFree(destination.data)


def publish_connection(settings):
    evidence = json.loads((RUNTIME / "proxy-evidence.json").read_text(encoding="utf-8"))
    if not evidence.get("completion_verified") or evidence.get("base_url") != settings["base_url"]:
        raise ValueError("A verified completion is required before publishing connection metadata")
    directory = ROOT / ".local-secrets"
    encrypted = directory / "llm-proxy-key.dpapi"
    protect_key(encrypted, settings["key"])
    if zep_key(encrypted) != settings["key"]:
        raise RuntimeError("DPAPI round-trip verification failed")
    inventory = evidence["models"]
    opus = [model for model in inventory if "opus" in model.lower()]
    metadata = {
        "schema_version": 1, "base_url": settings["base_url"], "model_ids": inventory,
        "selected_model": evidence["model"], "verified_completion_model": evidence["model"],
        "completion_verified": True, "credential_file": str(encrypted), "credential_format": "windows_user_dpapi_hex_utf16le",
        "provenance": {
            "repository_path": str(settings["config_path"].parents[1] / "CLIProxyAPI"),
            "config_path": str(settings["config_path"]), "config_sha256": settings["config_sha256"],
            "inventory_endpoint": settings["base_url"] + "/models",
            "completion_endpoint": settings["base_url"] + "/chat/completions",
            "model_mapping": "advertised IDs only; underlying provider mapping not independently established",
        },
        "opus_model_ids": opus, "exact_claude_opus_5_5_available": "claude-opus-5-5" in inventory,
        "exact_claude_opus_5_5_completion_verified": False, "opus_alias_verified": False,
        "plaintext_key_persisted": False,
    }
    (directory / "cli-proxy-connection.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"stage": "shared_connection_published", "metadata_path": str(directory / "cli-proxy-connection.json"),
                      "credential_path": str(encrypted), "base_url": metadata["base_url"], "model_ids": inventory,
                      "schema_version": 1, "exact_claude_opus_5_5_available": metadata["exact_claude_opus_5_5_available"],
                      "opus_alias_verified": False, "dpapi_roundtrip_verified": True}, ensure_ascii=True), flush=True)
    return metadata


def request_json(url, key=None, payload=None, timeout=120):
    headers = {"Accept": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return response.status, json.load(response)


def save_evidence(name, data):
    RUNTIME.mkdir(parents=True, exist_ok=True)
    (RUNTIME / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def probe_proxy(settings, preferred_model=None):
    install_redaction(settings["keys"])
    started = time.monotonic()
    status, models = request_json(settings["base_url"] + "/models", settings["key"], timeout=15)
    ids = [entry["id"] for entry in models.get("data", []) if isinstance(entry, dict) and isinstance(entry.get("id"), str)]
    preferred = [preferred_model] if preferred_model else []
    preferred += [model for model in ids if "mini" in model.lower() or "flash" in model.lower() or "haiku" in model.lower()]
    preferred += [model for model in ids if model in {"gpt-6-luna", "gpt-5.6-luna"}]
    preferred += [model for model in ids if "codex" in model.lower()]
    preferred += ids
    if preferred_model and preferred_model not in ids:
        raise ValueError("The explicitly selected model is absent from the live inventory; no substitution attempted")
    candidates = [preferred_model] if preferred_model else list(dict.fromkeys(m for m in preferred if m in ids))[:3]
    evidence = {
        "status": "models_authenticated", "base_url": settings["base_url"],
        "config_path": str(settings["config_path"]), "config_sha256": settings["config_sha256"],
        "models_status_code": status, "models": ids, "key_source": "designated_desktop_cliproxy_config",
        "credential_values_logged": False, "completion_verified": False, "attempts": [],
    }
    save_evidence("proxy-evidence.json", evidence)
    for model in candidates:
        attempt = {"model": model, "max_tokens": 64}
        try:
            code, answer = request_json(settings["base_url"] + "/chat/completions", settings["key"], {
                "model": model, "messages": [{"role": "user", "content": "Reply with exactly MIROFISH_PROXY_OK. No explanation."}],
                "max_tokens": 64, "stream": False,
            }, timeout=150)
            content = answer["choices"][0]["message"].get("content")
            attempt.update(status_code=code, content=content, usage=answer.get("usage"))
            if isinstance(content, str) and "MIROFISH_PROXY_OK" in content:
                evidence.update(status="completion_verified", completion_verified=True, model=model)
        except HTTPError as error:
            attempt.update(status_code=error.code, error=redact(error.read().decode("utf-8", "replace")[:700], settings["keys"]))
        except Exception as error:
            attempt.update(error_type=type(error).__name__, error=redact(str(error)[:300], settings["keys"]))
        evidence["attempts"].append(attempt)
        evidence["elapsed_seconds"] = round(time.monotonic() - started, 2)
        save_evidence("proxy-evidence.json", evidence)
        print(json.dumps({"stage": "proxy_completion", **attempt}, ensure_ascii=True), flush=True)
        if evidence["completion_verified"]:
            return evidence
    raise RuntimeError("The authenticated model list did not produce a verified completion in the bounded probes")


def serve_proxy(settings, executable):
    install_redaction(settings["keys"])
    (RUNTIME / "proxy").mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        [str(Path(executable).resolve(strict=True)), "--config", str(settings["config_path"])],
        cwd=RUNTIME / "proxy", stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW,
    )
    save_evidence("proxy-service.json", {"supervisor_pid": os.getpid(), "pid": process.pid,
                                         "base_url": settings["base_url"], "config_unchanged_sha256": settings["config_sha256"]})
    for line in process.stdout:
        print(redact(line, settings["keys"]), end="", flush=True)
    return process.wait()


def serve_backend(settings, encrypted_key, port):
    evidence = json.loads((RUNTIME / "proxy-evidence.json").read_text(encoding="utf-8"))
    if not evidence.get("completion_verified") or evidence.get("base_url") != settings["base_url"]:
        raise ValueError("Verify an actual CLIProxy completion before launching MiroFish")
    secret = zep_key(encrypted_key)
    install_redaction([*settings["keys"], secret])
    pin = json.loads((HERE / "upstream.json").read_text(encoding="utf-8"))["commit"]
    actual = subprocess.check_output(["git", "-C", str(VENDOR), "rev-parse", "HEAD"], text=True).strip()
    if actual != pin:
        raise ValueError("The MiroFish upstream checkout does not match the recorded pin")
    for name in list(os.environ):
        if name.startswith("LLM_BOOST_") or name == "ZEP_API_URL":
            os.environ.pop(name, None)
    os.environ.update({
        "LLM_API_KEY": settings["key"], "LLM_BASE_URL": settings["base_url"], "LLM_MODEL_NAME": evidence["model"],
        "ZEP_API_KEY": secret, "PYTHON_DOTENV_DISABLED": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "FLASK_HOST": "127.0.0.1", "FLASK_PORT": str(port), "FLASK_DEBUG": "False",
        "OASIS_DEFAULT_MAX_ROUNDS": "1", "REPORT_AGENT_MAX_TOOL_CALLS": "1", "REPORT_AGENT_MAX_REFLECTION_ROUNDS": "1",
        "HF_HOME": str(RUNTIME / "huggingface"), "TORCH_HOME": str(RUNTIME / "torch"),
        "TIKTOKEN_CACHE_DIR": str(RUNTIME / "tiktoken"),
    })
    # Child simulation processes inherit scoped configuration and log redaction.
    hook_path = HERE / "runtime_hooks"
    os.environ["PYTHONPATH"] = str(hook_path) + os.pathsep + str(HERE)
    save_evidence("backend-service.json", {
        "pid": os.getpid(), "base_url": f"http://127.0.0.1:{port}", "llm_base_url": settings["base_url"],
        "llm_model": evidence["model"], "llm_key_source": "designated_desktop_cliproxy_config",
        "zep_key_source": "explicit_dpapi_in_memory", "plaintext_credential_files_created": False,
        "upstream_default_launcher": "backend/run.py", "startup_validation_bypassed": False,
    })
    os.chdir(VENDOR / "backend")
    runpy.run_path(str(VENDOR / "backend" / "run.py"), run_name="__main__")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["proxy", "probe", "backend", "publish", "settings"])
    parser.add_argument("--proxy-config", required=True)
    parser.add_argument("--proxy-executable")
    parser.add_argument("--zep-key-path", default=str(ROOT / ".local-secrets" / "zep-key.dpapi"))
    parser.add_argument("--model")
    parser.add_argument("--port", type=int, default=5001)
    args = parser.parse_args()
    try:
        settings = proxy_settings(args.proxy_config)
        if args.command == "settings":
            print(json.dumps({"base_url": settings["base_url"], "config_path": str(settings["config_path"]),
                              "config_sha256": settings["config_sha256"]}, ensure_ascii=True))
            return 0
        if args.command == "proxy":
            return serve_proxy(settings, args.proxy_executable)
        if args.command == "probe":
            probe_proxy(settings, args.model)
            return 0
        if args.command == "publish":
            publish_connection(settings)
            return 0
        return serve_backend(settings, args.zep_key_path, args.port)
    except Exception as error:
        # The service's redactor is installed before provider operations; never dump config.
        print(json.dumps({"status": "failed", "error_type": type(error).__name__, "message": redact(str(error)[:700])}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
