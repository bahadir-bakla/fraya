"""Real protocol smoke plus HTTP contract tests; never contact Freya in this suite."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from freya_mcp.bridge import AGENT_LLM, Bridge, BridgeError, Config, ROOT
from freya_mcp.server import build_server

WORKSPACE = ROOT.parents[2]
KIT = WORKSPACE / "competition-v3" / "build-the-builder"
API_TEST_SECRET = "fak_mock_do_not_use_0123456789"
BANK_TEST_SECRET = "mock-team-secret-0123456789"
WORKFLOW = {"initial_node": "start", "nodes": {"start": {"type": "conversation", "prompt": "Hello"}}, "global_nodes": {}}


class MockAPI:
    def __init__(self):
        self.requests = []
        self.created = 0
        self.definition = WORKFLOW
        self.version = 1
        self.published = False
        self.sim_status = "running"
        self.external = False
        self.start_count = 0
        self.persona_count = 0
        self.timeout_start = False
        self.failure = None

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        body = json.loads(req.content) if req.content else None
        path = req.url.path
        if self.failure:
            return httpx.Response(self.failure, text=API_TEST_SECRET + BANK_TEST_SECRET)
        if path.startswith("/api/"):
            assert req.headers["authorization"] == "Bearer " + API_TEST_SECRET
            assert req.headers["user-agent"].startswith("Mozilla/5.0")
        if path == "/api/v2/workspaces":
            result = {"workspaces": [{"id": "ws-1", "name": "Synthetic"}]}
        elif path == "/api/v2/workflow" and req.method == "GET":
            assert req.url.params["workspaceId"] == "ws-1"
            result = {"workflows": [{"id": "wf-1"}]}
        elif path == "/api/v2/workflow" and req.url.params.get("dryRun") == "true":
            assert req.method == "POST"
            result = {"validated": True}
        elif path == "/api/v2/workflow" and req.method == "POST":
            self.created += 1
            self.definition = body["workflow"]
            result = {"workflow": {"id": "wf-1", "agentId": "ag-1"}}
        elif path == "/api/v2/workflow/wf-1" and req.method == "PUT":
            self.definition = body["workflow"]
            self.version += 1
            self.published = False
            result = {}
        elif path == "/api/v2/workflow/wf-1":
            assert req.url.params["workspaceId"] == "ws-1"
            result = {"workflow": {"id": "wf-1", "agentId": "ag-1", "workflow": self.definition}}
        elif path == "/api/v2/versions/workflow/wf-1":
            result = {"versions": [{"id": f"v-{self.version}", "versionNumber": self.version, "isPublished": self.published}]}
        elif path == "/api/v2/versions/workflow/wf-1/publish":
            assert body["versionId"] == f"v-{self.version}"
            self.published = True
            result = {}
        elif path == "/api/v2/personas" and req.method == "GET":
            assert req.url.params["workspaceId"] == "ws-1"
            result = {"personas": []}
        elif path == "/api/v2/personas" and req.method == "POST":
            rows = []
            for _ in body["personas"]:
                self.persona_count += 1
                rows.append({"id": f"p-{self.persona_count}"})
            result = {"personas": rows}
        elif path == "/api/v2/simulations" and req.method == "GET":
            result = {"simulations": [{"id": "external", "status": "running"}] if self.external else []}
        elif path == "/api/v2/simulations" and req.method == "POST":
            if self.timeout_start:
                raise httpx.ReadTimeout("request contains " + API_TEST_SECRET, request=req)
            self.start_count += 1
            result = {"simulation": {"id": f"s-{self.start_count}", "status": "running"}}
        elif path.startswith("/api/v2/simulations/s-") and "/iterations/" in path:
            result = {"runs": [{"id": "run-1", "callId": "call-1"}], "runsTotal": 130}
        elif path.startswith("/api/v2/simulations/s-") and path.endswith("/iterations"):
            result = {"iterations": [{"id": "it-1"}]}
        elif path.startswith("/api/v2/simulations/s-"):
            result = {"simulation": {"id": path.rsplit("/", 1)[-1], "status": self.sim_status}}
        elif path == "/api/v2/call/call-1":
            result = {"call": {"messages": [{"role": "system", "message": json.dumps({"headers": {"Authorization": "Bearer " + API_TEST_SECRET, "x-team-key": BANK_TEST_SECRET}})}],
                               "nested": {"apiKey": API_TEST_SECRET, "authorization": "Bearer private_unknown"}}}
        elif path == "/v1/practice/sessions":
            assert req.headers["x-team-key"] == BANK_TEST_SECRET
            result = {"variables": {"customer_id": "customer-1", "first_name": "Daniel"}}
        elif path == "/v1/practice/ledger/customer-1":
            assert req.headers["x-team-key"] == BANK_TEST_SECRET
            case = json.loads((KIT / "public-test-set.json").read_text())[0]
            result = {**case["expected"], "calls": [{"tool": "close_call", "result": {}}]}
        else:
            raise AssertionError(f"Undocumented/unexpected mock route: {req.method} {path}")
        return httpx.Response(200, json={"success": True, "data": {"result": result}})


class BridgeTests(unittest.TestCase):
    def setUp(self):
        # Entire test write scope remains inside the integration.
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.folder = Path(self.temp.name)
        self.mock = MockAPI()
        self.bridge = Bridge(Config(WORKSPACE, KIT, state_dir=self.folder / "state",
                                   api_key=API_TEST_SECRET, bank_key=BANK_TEST_SECRET), httpx.MockTransport(self.mock))
        self.wf = self.folder / "workflow.json"
        self.wf.write_text(json.dumps(WORKFLOW))

    def tearDown(self):
        self.bridge.close()
        self.temp.cleanup()

    def test_health_is_offline_and_no_secrets(self):
        health = self.bridge.health()
        self.assertEqual(health["status"], "configured")
        self.assertFalse(health["live_connected"])
        self.assertEqual(self.mock.requests, [])
        self.assertNotIn(API_TEST_SECRET, json.dumps(health))
        self.assertTrue(self.bridge.health(live=True)["live_connected"])

    def test_unconfigured_never_makes_http_request(self):
        self.bridge.config.api_key = ""
        self.assertEqual(self.bridge.health()["status"], "unconfigured")
        with self.assertRaisesRegex(BridgeError, "unconfigured"):
            self.bridge.workspaces()
        self.assertFalse(self.mock.requests)

    def test_workspace_selection_does_not_guess(self):
        self.bridge.workspaces = lambda: [{"id": "ws-1"}, {"id": "ws-2"}]
        with self.assertRaisesRegex(BridgeError, "explicitly"):
            self.bridge.workspace_id()
        self.bridge.config.workspace_id = "ws-2"
        self.assertEqual(self.bridge.workspace_id(), "ws-2")

    def test_validation_dryrun_never_creates(self):
        self.assertTrue(self.bridge.validate(str(self.wf))["remote_checked"])
        self.assertEqual(self.mock.created, 0)
        self.assertEqual(self.mock.requests[-1].url.params["dryRun"], "true")
        count = len(self.mock.requests)
        self.assertFalse(self.bridge.validate(str(self.wf), remote=False)["remote_checked"])
        self.assertEqual(len(self.mock.requests), count)

    def test_schema_feedback_is_bounded_and_redacted_only_for_dryrun(self):
        def reject(req):
            return httpx.Response(422, json={"message": "bad body " + API_TEST_SECRET,
                                            "authorization": BANK_TEST_SECRET,
                                            "detail": "x" * 10000})
        other = Bridge(self.bridge.config, httpx.MockTransport(reject))
        try:
            with self.assertRaises(BridgeError) as caught:
                other.validate(str(self.wf))
            message = str(caught.exception)
            self.assertIn("validation:", message)
            self.assertNotIn(API_TEST_SECRET, message)
            self.assertNotIn(BANK_TEST_SECRET, message)
            self.assertLess(len(message), 6100)
            with self.assertRaisesRegex(BridgeError, "body withheld"):
                other.request("POST", "/api/v2/workflow", {"workflow": WORKFLOW})
        finally:
            other.close()

    def test_save_reuses_slot_normalizes_model_publishes(self):
        first = self.bridge.save("brief-a", str(self.wf))
        second = self.bridge.save("brief-a", str(self.wf))
        self.assertEqual(first["workflow_id"], second["workflow_id"])
        self.assertEqual(self.mock.created, 1)
        self.assertTrue(self.mock.published)
        self.assertEqual(self.mock.definition["agent_config"]["llmConfig"], AGENT_LLM)
        self.assertNotIn(API_TEST_SECRET, self.bridge.state_path().read_text())

    def test_simulation_returns_immediately_refuses_overlap_and_recovers_terminal(self):
        sim = self.bridge.start("ag-1", "practice", {"p-1": {"customer_id": "customer-1"}})
        self.assertEqual(sim["simulation_id"], "s-1")
        body = json.loads(self.mock.requests[-1].content)
        for key in ("assistantLlmOverride", "routingLlmOverride", "extractionLlmOverride"):
            self.assertEqual(body[key], AGENT_LLM)
        self.assertEqual(body["runsPerPersona"], 1)
        with self.assertRaisesRegex(BridgeError, "already active"):
            self.bridge.start("ag-1", "second", {"p-1": {}})
        self.assertEqual(self.mock.start_count, 1)
        self.mock.sim_status = "completed"
        self.assertTrue(self.bridge.status("s-1")["terminal"])
        self.assertEqual(self.bridge.start("ag-1", "second", {"p-1": {}})["simulation_id"], "s-2")

    def test_external_simulation_blocks_post(self):
        self.mock.external = True
        with self.assertRaisesRegex(BridgeError, "already running"):
            self.bridge.start("ag-1", "test", {"p-1": {}})
        self.assertEqual(self.mock.start_count, 0)

    def test_two_server_instances_share_nonblocking_workspace_lock(self):
        other = Bridge(self.bridge.config, httpx.MockTransport(self.mock))
        try:
            with self.bridge.locked_state():
                with self.assertRaisesRegex(BridgeError, "workspace lock"):
                    with other.locked_state():
                        self.fail("Two writers acquired the same workspace lock")
        finally:
            other.close()

    def test_bank_placeholder_injects_only_outgoing_memory(self):
        placeholder = "${FREYA_BANK_TEAM_KEY}"
        self.wf.write_text(json.dumps({**WORKFLOW, "headers": {"x-team-key": placeholder}}))
        loaded = self.bridge.inject_bank_placeholder(self.bridge.workflow(str(self.wf)))
        self.assertEqual(loaded["headers"]["x-team-key"], BANK_TEST_SECRET)
        self.assertNotIn(BANK_TEST_SECRET, self.wf.read_text())
        self.assertNotIn(BANK_TEST_SECRET, json.dumps(self.bridge.scrub(loaded)))
        self.bridge.config.bank_key = ""
        self.assertTrue(self.bridge.validate(str(self.wf), remote=False)["local_structure_valid"])
        self.assertTrue(self.bridge.validate(str(self.wf), remote=True)["remote_checked"])

    def test_simulation_marker_survives_bridge_restart(self):
        self.bridge.start("ag-1", "test", {"p-1": {}})
        other = Bridge(self.bridge.config, httpx.MockTransport(self.mock))
        try:
            with self.assertRaisesRegex(BridgeError, "already active"):
                other.start("ag-1", "test", {"p-1": {}})
        finally:
            other.close()

    def test_transport_unknown_start_blocks_automatic_retry(self):
        self.mock.timeout_start = True
        with self.assertRaisesRegex(BridgeError, "transport failed") as raised:
            self.bridge.start("ag-1", "test", {"p-1": {}})
        self.assertNotIn(API_TEST_SECRET, str(raised.exception))
        with self.assertRaisesRegex(BridgeError, "outcome is unknown"):
            self.bridge.start("ag-1", "test", {"p-1": {}})

    def test_outputs_and_error_messages_scrub_secrets(self):
        data = json.dumps(self.bridge.scrub(self.bridge.call("call-1")))
        self.assertNotIn(API_TEST_SECRET, data)
        self.assertNotIn(BANK_TEST_SECRET, data)
        self.assertNotIn("private_unknown", data)
        self.mock.failure = 403
        with self.assertRaises(BridgeError) as raised:
            self.bridge.workspaces()
        self.assertNotIn(API_TEST_SECRET, str(raised.exception))

    def test_export_redacts_and_rejects_escape(self):
        self.mock.definition = {**WORKFLOW, "apiKey": API_TEST_SECRET, "headers": {"x-team-key": BANK_TEST_SECRET}}
        with patch("freya_mcp.bridge.ROOT", self.folder):
            result = self.bridge.export("wf-1", "practice.workflow.json")
            self.assertTrue(result["secrets_redacted"])
            content = Path(result["path"]).read_text()
            self.assertNotIn(API_TEST_SECRET, content)
            self.assertNotIn(BANK_TEST_SECRET, content)
            with self.assertRaises(BridgeError):
                self.bridge.export("wf-1", "../escape.json")

    def test_input_and_identifier_scope(self):
        with self.assertRaises(BridgeError):
            self.bridge.read_json(str(WORKSPACE.parent / "outside.json"))
        with self.assertRaises(BridgeError):
            self.bridge.get_workflow("../keys")
        with self.assertRaises(BridgeError):
            self.bridge.list_workflows(101)

    def test_lists_and_iteration_are_documented_single_pages(self):
        self.bridge.list_workflows(20, 10)
        self.assertEqual(self.mock.requests[-1].url.params["offset"], "10")
        self.bridge.list_personas()
        before = len(self.mock.requests)
        result = self.bridge.iteration("s-1", "it-1", offset=100)
        self.assertEqual(result["runsTotal"], 130)
        self.assertEqual(len(self.mock.requests), before + 1)
        self.assertEqual(self.mock.requests[-1].url.params["offset"], "100")

    def test_practice_uses_kit_and_cached_personas(self):
        cases = self.bridge.cases(case_ids=["PUB-01"])
        self.assertEqual(cases[0]["id"], "PUB-01")
        prepared = self.bridge.prepare_practice(case_ids=["PUB-01"])
        self.assertFalse(prepared["simulation_started"])
        self.assertEqual(prepared["cases"][0]["customer_id"], "customer-1")
        self.bridge.prepare_practice(case_ids=["PUB-01"])
        self.assertEqual(self.mock.persona_count, 1)
        self.assertEqual(self.mock.start_count, 0)
        ledger = self.bridge.ledger("customer-1", "PUB-01")
        self.assertTrue(ledger["ledger_score"]["pass"])

    def test_explicit_env_file_and_env_precedence(self):
        env = self.folder / ".env"
        env.write_text("FREYA_API_KEY=" + API_TEST_SECRET + "\nFREYA_BANK_TEAM_KEY=" + BANK_TEST_SECRET)
        with patch.dict(os.environ, {"FREYA_API_KEY": "injected-test-key"}, clear=True):
            cfg = Config.load(WORKSPACE, KIT, env)
            self.assertEqual(cfg.api_key, "injected-test-key")
            self.assertEqual(cfg.bank_key, BANK_TEST_SECRET)
            self.assertTrue(cfg.env_file_configured)
            cfg2 = Config.load(WORKSPACE, KIT)
            self.assertFalse(cfg2.bank_key)


class ProtocolTests(unittest.TestCase):
    def test_real_stdio_initialize_discovery_offline_calls(self):
        async def smoke():
            env = {k: v for k, v in os.environ.items() if not k.startswith("FREYA_")}
            env["PYTHONUTF8"] = "1"
            params = StdioServerParameters(command=sys.executable,
                                          args=[str(ROOT / "freya_mcp" / "server.py"), "--workspace", str(WORKSPACE), "--kit", str(KIT)],
                                          cwd=str(ROOT), env=env)
            with tempfile.TemporaryFile(mode="w+", encoding="utf-8", dir=ROOT) as errors:
                async with stdio_client(params, errlog=errors) as (read, write):
                    async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=20)) as session:
                        initialized = await session.initialize()
                        self.assertEqual(initialized.serverInfo.name, "freya-mcp")
                        self.assertIn("one simulation", initialized.instructions)
                        tools = await session.list_tools()
                        names = {tool.name for tool in tools.tools}
                        self.assertEqual(len(names), 22)
                        self.assertFalse(any("delete" in name for name in names))
                        health = await session.call_tool("freya_health", {})
                        status = json.loads(health.content[0].text)
                        self.assertTrue(status["ok"])
                        self.assertEqual(status["data"]["status"], "unconfigured")
                        self.assertFalse(status["data"]["live_checked"])
                        cases = await session.call_tool("freya_practice_cases", {"case_ids": ["PUB-01"]})
                        self.assertEqual(json.loads(cases.content[0].text)["data"][0]["id"], "PUB-01")
                        dry = await session.call_tool("freya_validate_workflow", {"workflow_path": str(KIT / "examples" / "base-agent.json"), "remote": False})
                        self.assertTrue(json.loads(dry.content[0].text)["data"]["local_structure_valid"])
                        missing = await session.call_tool("freya_list_workspaces", {})
                        self.assertFalse(json.loads(missing.content[0].text)["ok"])
                errors.seek(0)
                self.assertNotIn(API_TEST_SECRET, errors.read())
        asyncio.run(smoke())


if __name__ == "__main__":
    unittest.main(verbosity=2)
