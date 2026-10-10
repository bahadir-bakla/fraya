"""Authorized loopback proxy transport; no fallback or plaintext auth logs.

The parent enforces the whole 5–8 minute deadline by terminating this request
process. Only this process decrypts the designated DPAPI key. A live inventory
and independently inspected exact upstream route are required before inference:
CLIProxyAPI can rewrite the response's model field to the requested alias.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from run import MODEL, ROOT, RUNTIME, json_write, prepare, validate_review, write_reports

CONNECTION = ROOT / ".local-secrets/cli-proxy-connection.json"
KEY = ROOT / ".local-secrets/llm-proxy-key.dpapi"
ID_PATTERN = re.compile(r"[A-Za-z0-9_.:/-]{1,200}")


class SafeFailure(Exception):
    """Only credential-free error codes may cross the process boundary."""

    def __init__(self, code: str, evidence: dict | None = None):
        super().__init__(code)
        self.evidence = evidence or {}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SafeFailure("proxy_redirect_rejected")


def connection_metadata() -> dict:
    if not CONNECTION.is_file():
        raise SafeFailure("designated_proxy_metadata_missing")
    value = json.loads(CONNECTION.read_text(encoding="utf-8-sig"))
    base = value.get("base_url", "").rstrip("/")
    parsed = urlsplit(base)
    if (parsed.scheme not in ("http", "https") or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
            or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path != "/v1"):
        raise SafeFailure("designated_proxy_must_be_loopback_v1_without_url_credentials")
    if Path(value.get("credential_file", "")).resolve() != KEY.resolve():
        raise SafeFailure("proxy_key_must_be_the_user_designated_dpapi_file")
    if value.get("credential_format") != "windows_user_dpapi_hex_utf16le":
        raise SafeFailure("unsupported_designated_key_format")
    return value


def load_key() -> str:
    if not KEY.is_file() or os.name != "nt":
        raise SafeFailure("designated_windows_user_dpapi_key_unavailable")
    spec = importlib.util.spec_from_file_location("opus_authorized_dpapi", ROOT / "scripts/freya_dpapi_server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Never invoke inject_credentials/main: those deal with unrelated Freya keys.
    return module.unprotect(KEY)


def request_json(opener, url: str, key: str, timeout: float, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=body, headers={"Authorization": "Bearer " + key,
                      "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with opener.open(request, timeout=timeout) as response:
            # Keep raw headers/auth/error bodies out of files and console output.
            raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise SafeFailure("proxy_response_size_limit")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise SafeFailure("proxy_response_not_object")
        return value
    except HTTPError as exc:
        evidence = {"http_status": exc.code}
        try:
            error = json.loads(exc.read(8192)).get("error", {})
            if isinstance(error, dict):
                for field in ("type", "code"):
                    if isinstance(error.get(field), str) and ID_PATTERN.fullmatch(error[field]):
                        evidence["provider_error_" + field] = error[field]
                # Classify the message in memory; never echo arbitrary provider text.
                message = str(error.get("message", "")).lower()
                if "unknown provider" in message:
                    evidence["provider_error_classification"] = "unknown_provider_for_requested_model"
                elif "model" in message and any(word in message for word in ("not found", "unsupported", "not available", "does not exist")):
                    evidence["provider_error_classification"] = "requested_model_unavailable"
                elif any(word in message for word in ("unauthorized", "authentication", "invalid api key")):
                    evidence["provider_error_classification"] = "provider_authentication_rejected"
        except (ValueError, AttributeError):
            pass
        raise SafeFailure("proxy_http_" + str(exc.code), evidence) from None
    except URLError:
        raise SafeFailure("proxy_connection_failed") from None
    except (ValueError, TimeoutError):
        raise SafeFailure("proxy_invalid_json_or_socket_timeout") from None


def inventory_evidence(value: dict) -> dict:
    if not isinstance(value.get("data"), list):
        raise SafeFailure("proxy_inventory_invalid")
    ids = sorted({item["id"] for item in value["data"] if isinstance(item, dict)
                  and isinstance(item.get("id"), str) and ID_PATTERN.fullmatch(item["id"])})
    return {"inventory_authenticated": True, "advertised_model_ids": ids,
            "exact_model_advertised": MODEL in ids,
            "claude_model_ids": [name for name in ids if "claude" in name.lower() or "opus" in name.lower()],
            "checked_at_utc": datetime.now(timezone.utc).isoformat()}


def verify_route(metadata: dict) -> dict:
    route = metadata.get("provenance", {}).get("exact_model_route", {})
    # This is evidence from the proxy owner inspecting supported provider/config
    # metadata, not an inference from an alias or the rewriter's response label.
    if (route.get("requested_model") != MODEL or route.get("upstream_model") != MODEL
            or route.get("provider") not in ("claude", "anthropic")
            or route.get("mapping_verified") is not True or route.get("fallback_disabled") is not True
            or not route.get("evidence")):
        raise SafeFailure("exact_upstream_route_and_no_fallback_provenance_unverified")
    return {key: route[key] for key in ("requested_model", "upstream_model", "provider",
                                       "mapping_verified", "fallback_disabled", "evidence")}


def completion_payload(prompt: str) -> dict:
    return {"model": MODEL, "messages": [
        {"role": "system", "content": "You are an independent source-grounded red-team reviewer. Use no tools. Output the requested JSON only."},
        {"role": "user", "content": prompt}],
        "tools": [], "tool_choice": "none", "stream": False, "n": 1, "max_tokens": 24000}


def verify_completion(value: dict, route: dict) -> dict:
    if value.get("model") != MODEL:
        raise SafeFailure("actual_proxy_response_model_not_exact_opus_5_5")
    choices = value.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or value.get("error"):
        raise SafeFailure("proxy_completion_missing_or_error")
    choice = choices[0]
    message = choice.get("message", {})
    if message.get("role") != "assistant" or message.get("tool_calls") or message.get("function_call"):
        raise SafeFailure("proxy_returned_tools_or_non_assistant_response")
    if choice.get("finish_reason") != "stop" or not isinstance(message.get("content"), str) or not message["content"].strip():
        raise SafeFailure("proxy_completion_incomplete_or_empty")
    # Do not trust a response label without the separately verified route.
    if route.get("upstream_model") != MODEL or route.get("fallback_disabled") is not True:
        raise SafeFailure("proxy_response_label_without_exact_upstream_route")
    return {"actual_response_model": value["model"], "response_id": value.get("id"),
            "usage": value.get("usage", {}), "finish_reason": choice["finish_reason"],
            "verified_upstream_route": route, "tool_calls": 0, "text": message["content"],
            "model_field_limitation": "CLIProxyAPI may rewrite response model fields; route provenance is also required."}


def worker(timeout: int) -> int:
    started = time.monotonic()
    result = {"status": "proxy_preflight", "actual_opus_inference_verified": False,
              "model_inference_attempted": False, "credential_values_displayed": False,
              "credential_decrypted_in_request_process_only": False}
    key = None
    try:
        metadata = connection_metadata()
        base = metadata["base_url"].rstrip("/")
        result["proxy_base_url"] = base
        key = load_key()
        result["credential_decrypted_in_request_process_only"] = True
        # No ambient HTTP proxy and no redirects that could forward the key.
        opener = build_opener(ProxyHandler({}), NoRedirect())
        inventory = request_json(opener, base + "/models", key, min(30, timeout))
        result["inventory"] = inventory_evidence(inventory)
        if not result["inventory"]["exact_model_advertised"]:
            raise SafeFailure("live_inventory_does_not_advertise_claude_opus_5_5")
        route = verify_route(metadata)
        result["route_provenance"] = route
        prompt = (RUNTIME / "prompt.txt").read_text(encoding="utf-8")
        result["model_inference_attempted"] = True
        value = request_json(opener, base + "/chat/completions", key,
                             max(1, timeout - (time.monotonic() - started)), completion_payload(prompt))
        inference = verify_completion(value, route)
        result["actual_opus_inference_verified"] = True
        text = inference.pop("text")
        result["inference_evidence"] = inference
        # Only verified model output is persisted; never headers or raw errors.
        (RUNTIME / "proxy-model-output.txt").write_text(text, encoding="utf-8")
        review = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip()))
        snapshot = json.loads((RUNTIME / "input-snapshot.json").read_text(encoding="utf-8"))
        validate_review(review, snapshot)
        result.update(status="completed_actual_opus_source_review", review=review)
    except SafeFailure as exc:
        result.update(status="blocked_exact_opus_proxy_route", failure_code=str(exc), provider_error_evidence=exc.evidence)
    except Exception as exc:
        # Never serialize exception text/traceback; a library could echo auth data.
        result.update(status="failed_proxy_or_review_contract", failure_code=type(exc).__name__)
    finally:
        # CPython strings cannot promise secure memory erasure. No plaintext key
        # is written; the request process ends after this result is returned.
        key = None
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def probe_worker(timeout: int) -> int:
    """One explicitly authorized tiny exact-ID call, even absent from inventory."""
    started = time.monotonic()
    result = {"requested_model": MODEL, "timeout_seconds": timeout, "max_tokens": 32,
              "prompt": "Reply ready", "tools": [], "tool_choice": "none", "fallback_requested": False,
              "completion_requested": False, "route_accepted": False, "actual_opus_inference_verified": False,
              "credential_values_displayed": False, "credential_decrypted_in_request_process_only": False}
    key = None
    try:
        metadata = connection_metadata()
        base = metadata["base_url"].rstrip("/")
        key = load_key()
        result["credential_decrypted_in_request_process_only"] = True
        opener = build_opener(ProxyHandler({}), NoRedirect())
        payload = {"model": MODEL, "messages": [{"role": "user", "content": "Reply ready"}],
                   "max_tokens": 32, "stream": False, "tools": [], "tool_choice": "none", "n": 1}
        result["completion_requested"] = True
        value = request_json(opener, base + "/chat/completions", key, timeout, payload)
        result.update(http_status=200, route_accepted=True)
        model = value.get("model")
        result["response_model"] = model if isinstance(model, str) and ID_PATTERN.fullmatch(model) else "missing_or_invalid"
        result["exact_response_model"] = model == MODEL
        choices = value.get("choices", [])
        result["assistant_response_received"] = bool(choices and choices[0].get("message", {}).get("role") == "assistant")
        result["tools_returned"] = bool(choices and (choices[0].get("message", {}).get("tool_calls") or choices[0].get("message", {}).get("function_call")))
        # A tiny successful translated response alone cannot establish the upstream.
        route = verify_route(metadata)
        evidence = verify_completion(value, route)
        evidence.pop("text")
        result.update(actual_opus_inference_verified=True, inference_evidence=evidence)
    except SafeFailure as exc:
        result.update(failure_code=str(exc), **exc.evidence)
    except Exception as exc:
        result["failure_code"] = type(exc).__name__
    finally:
        key = None
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def probe_proxy(timeout: int) -> int:
    if not 1 <= timeout <= 30:
        raise ValueError("Tiny exact-model probe bound must be 1–30 seconds")
    RUNTIME.mkdir(exist_ok=True)
    env = {key: value for key, value in os.environ.items() if not key.startswith("FREYA_")}
    env["PYTHONUTF8"] = "1"
    child = subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "--probe-worker",
                              "--timeout-seconds", str(timeout)], env=env, cwd=RUNTIME,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        output, _ = child.communicate(timeout=timeout)
        result = json.loads(output)
    except subprocess.TimeoutExpired:
        child.kill()
        child.communicate(timeout=10)
        result = {"requested_model": MODEL, "timeout_seconds": timeout, "completion_requested": True,
                  "route_accepted": False, "actual_opus_inference_verified": False, "failure_code": "tiny_exact_route_probe_timed_out"}
    except (ValueError, TypeError):
        result = {"requested_model": MODEL, "actual_opus_inference_verified": False, "failure_code": "invalid_safe_probe_result"}
    report_path = ROOT / "analysis/opus-redteam.json"
    metadata = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {
        "status": "exact_proxy_probe_only", "requested_model": MODEL, "actual_opus_inference_verified": False}
    metadata["exact_route_probe"] = result
    if result.get("completion_requested"):
        metadata["model_inference_attempted"] = True
    if not result.get("route_accepted"):
        metadata["status"] = "blocked_exact_opus_proxy_invocation_rejected"
        metadata["failure_reason"] = ("Authenticated exact claude-opus-5-5 tiny completion was rejected: "
                                      + result.get("failure_code", "unspecified") + "; "
                                      + result.get("provider_error_classification", "sanitized evidence recorded")
                                      + ". No actual Opus inference, substitute model, or red-team attacks were obtained.")
    elif not result.get("actual_opus_inference_verified"):
        metadata["status"] = "exact_proxy_route_accepted_upstream_provenance_unverified"
        metadata["failure_reason"] = "Tiny route accepted, but exact upstream model provenance remains unverified; no red-team review attributed to Opus."
    else:
        metadata["status"] = "exact_proxy_probe_verified_review_pending"
        metadata["actual_opus_inference_verified"] = True
        metadata.pop("failure_reason", None)
    write_reports(metadata)
    print(json.dumps(result, indent=2))
    return 0 if result.get("actual_opus_inference_verified") else 2


def previous_attempts() -> list[dict]:
    report = ROOT / "analysis/opus-redteam.json"
    if not report.is_file():
        return []
    try:
        old = json.loads(report.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    keys = ("status", "provider", "requested_model", "actual_opus_inference_verified", "model_inference_attempted",
            "cli_path", "cli_version", "cli_sha256", "auth_status", "elapsed_seconds", "launched_at_utc", "failure_reason")
    return old.get("previous_attempts", []) + [{key: old[key] for key in keys if key in old}]


def run_proxy(timeout: int) -> int:
    if not 300 <= timeout <= 480:
        raise ValueError("Run bound must be between 300 and 480 seconds")
    snapshot = prepare()
    metadata = {"status": "launching_proxy_preflight", "provider": "authorized_local_cliproxy_openai_chat_completions",
                "requested_model": MODEL, "launcher_role": "different-model orchestrator; not Claude Opus",
                "launched_at_utc": datetime.now(timezone.utc).isoformat(), "timeout_seconds": timeout,
                "previous_attempts": previous_attempts(), "candidate_status": snapshot["candidate_status"],
                "candidate_paths": [c["path"] for c in snapshot["candidates"]],
                "source_manifest": "integrations/opus-redteam/source-manifest.json",
                "actual_opus_inference_verified": False, "model_inference_attempted": False,
                "tools_requested": [], "tool_choice": "none", "mcp_servers_requested": [], "fallback_requested": False,
                "credential_values_displayed": False, "credential_decrypted_in_request_process_only": False}
    write_reports(metadata)
    env = {key: value for key, value in os.environ.items() if not key.startswith("FREYA_")}
    env["PYTHONUTF8"] = "1"
    started = time.monotonic()
    child = subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "--worker",
                              "--timeout-seconds", str(timeout)], env=env, cwd=RUNTIME,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    review = None
    try:
        output, _ = child.communicate(timeout=timeout)
        result = json.loads(output)
        review = result.pop("review", None)
        metadata.update(result)
        if review:
            validate_review(review, snapshot)
            json_write(RUNTIME / "verified-review.json", review)
        if metadata.get("failure_code") == "live_inventory_does_not_advertise_claude_opus_5_5":
            metadata["failure_reason"] = ("The designated proxy accepted the in-memory DPAPI credential and returned its live model inventory, "
                                          "but advertised no exact claude-opus-5-5 route. No completion was requested and no model was substituted.")
        elif metadata.get("failure_code"):
            metadata["failure_reason"] = "Proxy route or output verification failed: " + metadata["failure_code"]
    except subprocess.TimeoutExpired:
        child.kill()
        child.communicate(timeout=10)
        metadata.update(status="timed_out", failure_reason="Bounded request process exceeded the exact-model run deadline")
    except (ValueError, TypeError, KeyError):
        metadata.update(status="failed_proxy_or_review_contract", failure_reason="Request process returned an invalid safe result or review contract")
        review = None
    metadata["elapsed_seconds"] = round(time.monotonic() - started, 3)
    write_reports(metadata, review)
    print(json.dumps({key: metadata.get(key) for key in ("status", "requested_model", "actual_opus_inference_verified",
                      "attack_count", "elapsed_seconds", "failure_reason")}, indent=2))
    return 0 if review else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--worker", action="store_true")
    mode.add_argument("--probe-worker", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=420)
    args = parser.parse_args()
    if args.probe_worker:
        if not 1 <= args.timeout_seconds <= 30:
            raise SystemExit(2)
        raise SystemExit(probe_worker(args.timeout_seconds))
    if not 300 <= args.timeout_seconds <= 480:
        raise SystemExit(2)
    raise SystemExit(worker(args.timeout_seconds))
