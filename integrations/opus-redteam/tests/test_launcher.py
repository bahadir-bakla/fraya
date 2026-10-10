"""Synthetic transport fixtures only; no model, credentials, bank or Freya calls."""
from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run
import proxy_provider as proxy


def route():
    return {"requested_model": run.MODEL, "upstream_model": run.MODEL, "provider": "claude",
            "mapping_verified": True, "fallback_disabled": True, "evidence": ["synthetic route fixture"]}


def response():
    return {"model": run.MODEL, "id": "synthetic-response", "choices": [{"finish_reason": "stop",
            "message": {"role": "assistant", "content": "ready"}}], "usage": {"completion_tokens": 1}}


def events():
    return [{"type": "system", "subtype": "init", "model": run.MODEL, "tools": [], "mcp_servers": []},
            {"type": "assistant", "message": {"model": run.MODEL, "content": [{"type": "text", "text": "{}"}]}},
            {"type": "result", "subtype": "success", "is_error": False, "modelUsage": {run.MODEL: {"outputTokens": 1}}}]


class InferenceIdentityTests(unittest.TestCase):
    def test_cli_exact_identity_and_no_tools(self):
        self.assertEqual(run.verify_inference(events())["models"], [run.MODEL])

    def test_cli_init_is_not_inference(self):
        with self.assertRaises(ValueError):
            run.verify_inference(events()[:1])

    def test_cli_wrong_actual_model_rejected(self):
        value = events()
        value[1]["message"]["model"] = "claude-opus-5"
        with self.assertRaises(ValueError):
            run.verify_inference(value)

    def test_cli_mixed_usage_rejected(self):
        value = events()
        value[2]["modelUsage"]["claude-sonnet-5-5"] = {}
        with self.assertRaises(ValueError):
            run.verify_inference(value)

    def test_cli_mcp_or_tool_availability_rejected(self):
        for field, content in (("tools", ["Read"]), ("mcp_servers", [{"name": "bank"}])):
            value = events()
            value[0][field] = content
            with self.assertRaises(ValueError):
                run.verify_inference(value)

    def test_proxy_exact_response_and_verified_route(self):
        self.assertEqual(proxy.verify_completion(response(), route())["actual_response_model"], run.MODEL)

    def test_proxy_response_label_without_route_rejected(self):
        with self.assertRaises(proxy.SafeFailure):
            proxy.verify_route({"provenance": {"model_mapping": "alias named opus"}})
        with self.assertRaises(proxy.SafeFailure):
            proxy.verify_completion(response(), {})

    def test_proxy_fallback_or_wrong_upstream_rejected(self):
        for field, value in (("upstream_model", "claude-opus-5"), ("fallback_disabled", False)):
            evidence = route()
            evidence[field] = value
            with self.assertRaises(proxy.SafeFailure):
                proxy.verify_route({"provenance": {"exact_model_route": evidence}})

    def test_proxy_returned_tools_rejected(self):
        value = response()
        value["choices"][0]["message"]["tool_calls"] = [{"id": "synthetic", "type": "function"}]
        with self.assertRaises(proxy.SafeFailure):
            proxy.verify_completion(value, route())

    def test_proxy_truncated_response_rejected(self):
        value = response()
        value["choices"][0]["finish_reason"] = "length"
        with self.assertRaises(proxy.SafeFailure):
            proxy.verify_completion(value, route())

    def test_redteam_request_tools_disabled_and_exact_model(self):
        payload = proxy.completion_payload("synthetic prompt")
        self.assertEqual(payload["model"], run.MODEL)
        self.assertEqual(payload["tools"], [])
        self.assertEqual(payload["tool_choice"], "none")
        self.assertNotIn("fallback", payload)


class CredentialAndBoundTests(unittest.TestCase):
    def test_inventory_gap_never_sends_completion(self):
        transport = Mock(return_value={"data": [{"id": "gpt-6.1-sol"}]})
        output = io.StringIO()
        with patch.object(proxy, "connection_metadata", return_value={"base_url": "http://127.0.0.1:8317/v1"}), \
             patch.object(proxy, "load_key", return_value="SYNTHETIC_AUTH_DO_NOT_LOG"), \
             patch.object(proxy, "request_json", transport), redirect_stdout(output):
            proxy.worker(420)
        result = json.loads(output.getvalue())
        self.assertFalse(result["model_inference_attempted"])
        self.assertEqual(transport.call_count, 1)
        self.assertTrue(transport.call_args.args[1].endswith("/models"))
        self.assertNotIn("SYNTHETIC_AUTH_DO_NOT_LOG", output.getvalue())

    def test_explicit_probe_makes_only_one_exact_call_without_inventory(self):
        failure = proxy.SafeFailure("proxy_http_502", {"http_status": 502})
        transport = Mock(side_effect=failure)
        output = io.StringIO()
        with patch.object(proxy, "connection_metadata", return_value={"base_url": "http://127.0.0.1:8317/v1"}), \
             patch.object(proxy, "load_key", return_value="SYNTHETIC_AUTH_DO_NOT_LOG"), \
             patch.object(proxy, "request_json", transport), redirect_stdout(output):
            proxy.probe_worker(30)
        self.assertEqual(transport.call_count, 1)
        self.assertTrue(transport.call_args.args[1].endswith("/chat/completions"))
        payload = transport.call_args.args[4]
        self.assertEqual(payload["max_tokens"], 32)
        self.assertEqual(payload["model"], run.MODEL)
        self.assertEqual(payload["tools"], [])
        self.assertEqual(json.loads(output.getvalue())["http_status"], 502)
        self.assertNotIn("SYNTHETIC_AUTH_DO_NOT_LOG", output.getvalue())

    def test_error_body_never_leaks_arbitrary_message_or_auth(self):
        body = json.dumps({"error": {"message": "unknown provider for model claude-opus-5-5 SYNTHETIC_AUTH_DO_NOT_LOG",
                                    "type": "server_error", "code": "internal_server_error"}}).encode()
        error = HTTPError("http://127.0.0.1:8317/v1/chat/completions", 502, "Bad Gateway", {}, io.BytesIO(body))
        opener = Mock()
        opener.open.side_effect = error
        with self.assertRaises(proxy.SafeFailure) as raised:
            proxy.request_json(opener, error.url, "SYNTHETIC_AUTH_DO_NOT_LOG", 30, {})
        evidence = raised.exception.evidence
        self.assertEqual(evidence["provider_error_classification"], "unknown_provider_for_requested_model")
        self.assertNotIn("SYNTHETIC_AUTH_DO_NOT_LOG", str(raised.exception) + json.dumps(evidence))

    def test_whole_request_process_is_killed_at_deadline(self):
        child = Mock()
        child.communicate.side_effect = [subprocess.TimeoutExpired("synthetic", 420), (b"", b"")]
        reports = []
        snapshot = {"candidate_status": "no_complete_candidate_available", "candidates": []}
        with patch.object(proxy, "prepare", return_value=snapshot), \
             patch.object(proxy, "previous_attempts", return_value=[]), \
             patch.object(proxy.subprocess, "Popen", return_value=child), \
             patch.object(proxy, "write_reports", side_effect=lambda meta, *args: reports.append(deepcopy(meta))), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(proxy.run_proxy(420), 2)
        child.kill.assert_called_once()
        self.assertEqual(reports[-1]["status"], "timed_out")
        self.assertEqual(child.communicate.call_args_list[0].kwargs["timeout"], 420)

    def test_redirect_cannot_forward_authorization(self):
        with self.assertRaises(proxy.SafeFailure):
            proxy.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://example.com")

    def test_invalid_full_run_bounds_rejected_before_credentials(self):
        for bound in (30, 299, 481):
            with self.assertRaises(ValueError):
                proxy.run_proxy(bound)


if __name__ == "__main__":
    unittest.main()
