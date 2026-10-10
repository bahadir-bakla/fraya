"""Offline platform-boundary regressions for the real LiveBackend.

Only the Bridge API and provider are doubles. Compiler gates, deployment,
practice orchestration, scoring and evidence persistence use production code.
All identifiers, transcripts and customer variables below are synthetic.
"""

from collections import deque
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import httpx
import pytest

from agent_forge import builder_live
from agent_forge.input_contract import inspect_inputs


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class MockBridgeError(Exception):
    pass


class MockBridge:
    """A stateful Bridge contract double, with no HTTP client or credentials.

    Session IDs deliberately differ from source customer IDs. Prepared bindings
    and run order can differ from requested order. Starting while a remote or
    local simulation is running is an assertion failure, never silently allowed.
    """

    def __init__(self, clock, directory, case_ids):
        self.clock = clock
        self.directory = directory
        self.http = SimpleNamespace(timeout=None)
        self.closed = False
        self.events = []
        self.delays = {}
        self.catalog = [{"id": cid, "identity": {"customer_id": f"source-{cid}"}}
                        for cid in case_ids]
        self.remote_states = deque([False])
        self.remote_running = False
        self.active = None
        self.prepared = []
        self.simulations = {}
        self.bank_owners = {}
        self.judges = {}
        self.ledger_failures = {}
        self.run_envelope = "runs"
        self.iteration_rows = None
        self.runs_by_iteration = {}
        self.readback_transform = lambda workflow: workflow
        self.workflow = None

    def record(self, method, *args, mutation=False, **kwargs):
        self.events.append({"method": method, "args": deepcopy(args),
                            "kwargs": deepcopy(kwargs), "at": self.clock.now,
                            "mutation": mutation})
        self.clock.now += self.delays.get(method, 0)

    def methods(self):
        return [event["method"] for event in self.events]

    def mutations(self):
        return [event for event in self.events if event["mutation"]]

    @staticmethod
    def scrub(value):
        return deepcopy(value)

    @staticmethod
    def items(result, key):
        if isinstance(result, list):
            return result
        for candidate in (key, "items"):
            if isinstance(result.get(candidate), list):
                return result[candidate]
        raise AssertionError(f"Unexpected mock Bridge list envelope: {key}")

    def cases(self):
        self.record("cases")
        return deepcopy(self.catalog)

    def health(self, *, live=False):
        self.record("health", live=live)
        return {"live_connected": True}

    def validate(self, path, *, name, remote=True):
        self.record("validate", path, name=name, remote=remote)
        return {"local_structure_valid": True, "remote_checked": remote,
                "result": {"valid": True}}

    def save(self, slot, path, *, name):
        self.record("save", slot, path, name=name, mutation=True)
        self.workflow = json.loads(Path(path).read_text(encoding="utf-8"))
        return {"workflow_id": "workflow-fixture", "agent_id": "agent-fixture",
                "published": True, "version": 1, "action": "created"}

    def get_workflow(self, workflow_id):
        self.record("get_workflow", workflow_id)
        definition = deepcopy(self.workflow)
        definition["agent_config"] = {"llmConfig": {
            "provider": "experimental-5", "model": "experimental-5"}}
        definition["nodePositions"] = {"welcome": {"x": 1, "y": 2}}
        return {"id": workflow_id, "agentId": "agent-fixture",
                "workflow": self.readback_transform(definition)}

    def list_simulations(self, *, limit=50, offset=0, status=""):
        self.record("list_simulations", limit=limit, offset=offset, status=status)
        assert status == "running"
        if len(self.remote_states) > 1:
            self.remote_running = self.remote_states.popleft()
        else:
            self.remote_running = self.remote_states[0]
        running = [{"id": "someone-elses-simulation", "status": "running"}]
        if self.active:
            running.append({"id": self.active, "status": "running"})
        elif not self.remote_running:
            running = []
        return {"items": running}

    def prepare_practice(self, *, case_ids, style=""):
        assert not self.active and not self.remote_running, "prepared during an active simulation"
        self.record("prepare_practice", case_ids=case_ids, style=style, mutation=True)
        batch = len(self.prepared) + 1
        # The Bridge selects in catalog order; caller order is not a join key.
        selected = [case["id"] for case in reversed(self.catalog) if case["id"] in case_ids]
        bindings = []
        variables = {}
        for cid in selected:
            pid = f"persona-{cid}"
            bank_id = f"bank-session-{batch}-{cid}"
            bindings.append({"case_id": cid, "persona_id": pid, "customer_id": bank_id})
            variables[pid] = {"customer_id": bank_id, "fixture_tag": cid}
            self.bank_owners[bank_id] = cid
        prepared = {"cases": bindings, "variables_by_persona": variables,
                    "simulation_started": False}
        self.prepared.append(deepcopy(prepared))
        return prepared

    def start(self, agent_id, name, variables_by_persona, *, max_seconds=420, concurrency=5):
        assert not self.active and not self.remote_running, "overlapping simulation start"
        self.record("start", agent_id, name, variables_by_persona,
                    max_seconds=max_seconds, concurrency=concurrency, mutation=True)
        sid = f"simulation-{len(self.simulations) + 1}"
        runs = []
        for pid, values in reversed(list(variables_by_persona.items())):
            cid = self.bank_owners[values["customer_id"]]
            verdict = self.judges.get(cid, {"outcome": "pass"})
            if verdict is not None:
                runs.append({"id": f"run-{sid}-{pid}", "personaId": pid,
                             "callId": f"call-{sid}-{pid}", **deepcopy(verdict)})
        self.simulations[sid] = {"runs": runs, "polls": 0}
        self.active = sid
        return {"simulation_id": sid, "status": "running", "poll_after_seconds": 10}

    def status(self, sid):
        self.record("status", sid)
        sim = self.simulations[sid]
        sim["polls"] += 1
        terminal = sim["polls"] >= 2
        if terminal:
            self.active = None
        return {"simulation_id": sid, "terminal": terminal,
                "simulation": {"id": sid, "status": "completed" if terminal else "running"}}

    def iterations(self, sid):
        self.record("iterations", sid)
        rows = self.iteration_rows
        return {"items": deepcopy(rows if rows is not None else [{"id": f"iteration-{sid}"}])}

    def iteration(self, sid, iid, *, limit=100, offset=0):
        self.record("iteration", sid, iid, limit=limit, offset=offset)
        assert 1 <= limit <= 100 and offset >= 0
        runs = self.runs_by_iteration.get(iid, self.simulations[sid]["runs"])
        page = deepcopy(runs[offset:offset + limit])
        return page if self.run_envelope == "list" else {self.run_envelope: page, "runsTotal": len(runs)}

    def ledger(self, customer_id, *, case_id=""):
        self.record("ledger", customer_id, case_id=case_id)
        assert customer_id in self.bank_owners, "used source identity instead of practice-session customer"
        assert self.bank_owners[customer_id] == case_id, "crossed case/customer ledger binding"
        failed = deepcopy(self.ledger_failures.get(case_id, []))
        return {"customer_id": customer_id,
                "ledger": {"calls": [{"tool": "verify_identity"}, {"tool": "close_call"}]},
                "ledger_score": {"pass": not failed, "failed": failed}}

    def call(self, call_id):
        self.record("call", call_id)
        return {"id": call_id, "messages": [
            {"role": "user", "message": "Synthetic customer reply."}]}

    def export(self, workflow_id, *, filename):
        self.record("export", workflow_id, filename=filename)
        path = self.directory / filename
        path.write_text(json.dumps({"workflow_id": workflow_id,
                                    "workflow": self.workflow}), encoding="utf-8")
        return {"path": str(path), "secrets_redacted": False}

    def close(self):
        self.closed = True


@pytest.fixture
def platform(monkeypatch, tmp_path):
    """Install mocks before actual backend construction; forbid accidental HTTP."""
    clock = Clock()
    monkeypatch.setattr(builder_live, "time", clock)
    monkeypatch.setattr(sys, "path", list(sys.path))

    def no_network(*args, **kwargs):
        raise AssertionError("Live HTTP is forbidden in platform-boundary tests")

    monkeypatch.setattr(httpx.Client, "send", no_network)
    monkeypatch.setattr(httpx.AsyncClient, "send", no_network)
    instances = []
    config_loads = []
    module = ModuleType("freya_mcp.bridge")
    package = ModuleType("freya_mcp")
    package.__path__ = []
    module.BridgeError = MockBridgeError

    class MockConfig:
        @classmethod
        def load(cls, root, kit):
            config_loads.append((root, kit))
            return SimpleNamespace(root=root, kit=kit)

    module.Config = MockConfig
    module.Bridge = lambda config: instances[-1]
    package.bridge = module
    monkeypatch.setitem(sys.modules, "freya_mcp", package)
    monkeypatch.setitem(sys.modules, "freya_mcp.bridge", module)

    def create(case_ids=("case-alpha",), *, budget=1800):
        directory = tmp_path / f"instance-{len(instances) + 1}"
        directory.mkdir()
        bridge = MockBridge(clock, directory, case_ids)
        instances.append(bridge)
        # Empty root prevents loading the real credential launcher.
        root = directory / "root"
        kit = directory / "kit"
        evidence = builder_live.Evidence(directory / "evidence", budget)
        backend = builder_live.LiveBackend(root, kit, evidence)
        assert backend.bridge is bridge
        assert config_loads[-1] == (root, kit)
        return SimpleNamespace(backend=backend, bridge=bridge, evidence=evidence,
                               clock=clock, root=root, kit=kit, directory=directory)

    yield create
    for bridge in instances:
        bridge.close()


DEPLOYED = {"workflow_id": "workflow-fixture", "agent_id": "agent-fixture"}


@pytest.mark.parametrize("envelope", ["runs", "items", "list"])
@pytest.mark.parametrize("run_count", [200, 201])
def test_judge_results_after_first_page_are_not_lost(platform, envelope, run_count):
    env = platform(("case-alpha", "case-beta"))
    env.bridge.run_envelope = envelope
    selected = {"id": "selected-last", "personaId": "persona-case-beta",
                "callId": "call-last-page", "outcome": "fail", "reason": "Synthetic disclosure violation"}
    first = {"id": "selected-first", "personaId": "persona-case-alpha",
             "callId": "call-first-page", "outcome": "pass"}
    padding = [{"id": f"unselected-{i}", "personaId": f"unselected-persona-{i}",
                "outcome": "pass"} for i in range(run_count - 2)]
    env.bridge.runs_by_iteration["iteration-simulation-1"] = [first, *padding, selected]

    rows = env.backend.practice(DEPLOYED, ["case-alpha", "case-beta"])

    by_case = {row["case_id"]: row for row in rows}
    assert by_case["case-alpha"]["pass"] is True
    assert by_case["case-beta"]["pass"] is False
    assert by_case["case-beta"]["call_id"] == "call-last-page"
    assert any("Synthetic disclosure violation" in item for item in by_case["case-beta"]["failed"])
    pages = [event for event in env.bridge.events if event["method"] == "iteration"]
    assert [event["kwargs"]["offset"] for event in pages] == [0, 100, 200]
    archived = json.loads((env.evidence.directory / "simulation-simulation-1.json").read_text())
    assert len(archived["runs"]) == run_count
    assert archived["runs"][-1]["id"] == "selected-last"
    assert (env.evidence.directory / "call-call-last-page.json").is_file()


def test_multiple_batches_and_repetitions_keep_bank_case_and_persona_bindings(platform):
    requested = [f"case-{i}" for i in range(7)]
    env = platform(requested)

    rows = env.backend.practice(DEPLOYED, requested, style="curt", repetitions=2)

    assert len(rows) == 14 and all(row["pass"] for row in rows)
    for rep in (1, 2):
        assert {row["case_id"] for row in rows if row["repetition"] == rep} == set(requested)
    assert len({row["customer_id"] for row in rows}) == 14
    assert all(row["execution"]["message_counts"] == {"user": 1} for row in rows)
    assert all(row["execution"]["scope"] == "observed_counts_only_no_policy_verdict" for row in rows)
    source_ids = {case["identity"]["customer_id"] for case in env.bridge.catalog}
    assert not source_ids.intersection(row["customer_id"] for row in rows)
    ledger_pairs = [(event["args"][0], event["kwargs"]["case_id"])
                    for event in env.bridge.events if event["method"] == "ledger"]
    assert ledger_pairs == [(row["customer_id"], row["case_id"]) for row in rows]
    starts = [event for event in env.bridge.events if event["method"] == "start"]
    preparations = [event for event in env.bridge.events if event["method"] == "prepare_practice"]
    assert len(starts) == len(preparations) == 4
    assert [len(event["args"][2]) for event in starts] == [5, 2, 5, 2]
    assert all(event["kwargs"]["style"] == "curt" for event in preparations)
    for event, prepared in zip(starts, env.bridge.prepared):
        assert event["args"][2] == prepared["variables_by_persona"]
        assert event["kwargs"]["concurrency"] <= 5
    for row in rows:
        assert row["persona_id"] == f"persona-{row['case_id']}"
        assert row["call_id"] == f"call-{row['simulation_id']}-{row['persona_id']}"
        assert row["tools"] == ["verify_identity", "close_call"]
    assert [len(batch["results"]) for batch in env.evidence.trace["tests"]] == [5, 2, 5, 2]
    assert sum(len(batch["results"]) for batch in env.evidence.trace["tests"]) == len(rows)


@pytest.mark.parametrize("judge,ledger_failed,expected_pass", [
    ({"outcome": "pass"}, [], True),
    ({"outcome": "fail", "reason": "Synthetic conversation failure"}, [], False),
    (None, [], False),  # No run for the selected persona.
    ({}, [], False),  # Run exists, verdict missing.
    ({"outcome": None}, [], False),
    ({"outcome": "pass"}, ["promise amount mismatch"], False),
    ({"outcome": "fail", "reason": "Synthetic conversation failure"}, ["promise amount mismatch"], False),
], ids=["both-pass", "judge-fail-ledger-pass", "missing-run", "missing-verdict",
        "null-verdict", "judge-pass-ledger-fail", "both-fail"])
def test_overall_pass_requires_both_independent_verdicts(platform, judge, ledger_failed, expected_pass):
    env = platform()
    env.bridge.judges["case-alpha"] = judge
    env.bridge.ledger_failures["case-alpha"] = ledger_failed

    row, = env.backend.practice(DEPLOYED, ["case-alpha"])

    assert row["pass"] is expected_pass
    assert set(ledger_failed).issubset(row["failed"])
    conversation_failed = judge is None or judge.get("outcome") != "pass"
    assert any(item.startswith("conversation:") for item in row["failed"]) is conversation_failed
    if conversation_failed and not (judge or {}).get("reason"):
        assert any("no verdict" in item for item in row["failed"])
    if judge is None:
        assert row["call_id"] is None
        assert "call" not in env.bridge.methods()


def test_no_iterations_cannot_be_scored_as_success(platform):
    env = platform()
    env.bridge.iteration_rows = []

    row, = env.backend.practice(DEPLOYED, ["case-alpha"])

    assert row["pass"] is False and row["call_id"] is None
    assert any("no verdict" in item for item in row["failed"])
    assert "iteration" not in env.bridge.methods()
    assert "ledger" in env.bridge.methods()


def test_external_running_simulation_is_waited_out_before_any_mutation(platform):
    env = platform()
    env.bridge.remote_states = deque([True, True, False])

    row, = env.backend.practice(DEPLOYED, ["case-alpha"])

    assert row["pass"] is True
    assert env.bridge.methods()[:5] == ["cases", "list_simulations", "list_simulations",
                                      "list_simulations", "prepare_practice"]
    assert env.bridge.mutations()[0]["at"] >= env.evidence.started + 20
    assert [event["method"] for event in env.bridge.mutations()] == ["prepare_practice", "start"]
    assert env.clock.sleeps[:2] == [10, 10]


def test_budget_exhausted_waiting_for_external_simulation_makes_no_mutation(platform):
    env = platform(budget=120)
    env.bridge.remote_states = deque([True])

    with pytest.raises(builder_live.BuildFailure, match="time budget exhausted"):
        env.backend.practice(DEPLOYED, ["case-alpha"])

    assert env.bridge.mutations() == []
    assert set(env.bridge.methods()) == {"cases", "list_simulations"}
    assert env.bridge.remote_running is True


@pytest.mark.parametrize("selection", [["unknown-case"], ["case-alpha", "case-alpha"]])
def test_invalid_selection_does_not_prepare_or_start(platform, selection):
    env = platform()
    with pytest.raises(builder_live.BuildFailure, match="unknown or duplicate"):
        env.backend.practice(DEPLOYED, selection)
    assert env.bridge.mutations() == []
    assert env.bridge.methods() == ["cases"]


class FixtureProvider:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.purposes = []

    def generate(self, purpose, prompt, schema, timeout_seconds):
        self.purposes.append(purpose)
        return deepcopy(next(self.responses))


def build_fixture(env):
    """Tiny self-contained input that still passes the real compiler gates."""
    source = env.directory / "brief.txt"
    source.write_text("# Welcome\n1. Say hello to the caller.\n", encoding="utf-8")
    api_path = env.directory / "openapi.json"
    api_path.write_text(json.dumps({
        "openapi": "3.0.3", "info": {"title": "Synthetic API", "version": "1"},
        "servers": [{"url": "https://bank.invalid/v1"}],
        "paths": {"/status": {"get": {"operationId": "get_fixture_status",
                                      "responses": {"200": {"description": "Status"}}}}},
    }), encoding="utf-8")
    contract = inspect_inputs([source], api_path)
    ids = [clause["qualified_id"] for doc in contract["documents"] for clause in doc["clauses"]]
    policy = {"title": "Welcome", "rules": [
        {"source_id": cid, "binding": True, "policy": "Say hello", "trigger": "call start",
         "actions": ["greet"], "exceptions": [], "overrides": [], "tool_names": []} for cid in ids],
        "parameters": [], "stages": [], "ambiguities": []}
    tool = {"type": "function", "config": {"maxRetries": 0},
            "pre_process_code": "freya.set('request_checked', True)",
            "post_process_code": "freya.set('response_checked', True)",
            "function": {"name": "get_fixture_status", "handler": "__function__:api_call",
                         "parameters": {"type": "object", "properties": {
                             "url": {"type": "string", "default": "https://bank.invalid/v1/status"},
                             "method": {"type": "string", "default": "GET"}}}}}
    workflow = {"initial_node": "welcome", "nodes": {
        "welcome": {"name": "welcome", "node_type": "conversation", "task_message": "Say hello.",
                    "tools": [tool], "transitions": [{"target_node": "done", "condition": {"operator": "always"}}]},
        "done": {"name": "done", "node_type": "end_call", "terminal": {
            "type": "function", "function": {"name": "finish", "handler": "__function__:end_call",
                "parameters": {"type": "object", "properties": {
                    "message_mode": {"type": "string", "default": "custom"},
                    "spoken_message": {"type": "string", "default": "Hello."}}}}}}}}
    generated = {"workflow_json": json.dumps(workflow), "coverage": [
        {"source_id": cid, "node_ids": ["welcome", "done"], "mechanism": "Greeting in welcome and terminal speech"}
        for cid in ids], "limitations": []}
    # workflow_prompt reads these kit files even with a canned provider. Keep
    # this fixture independent of repository assets and their installation.
    docs = env.kit / "docs"
    examples = env.kit / "examples"
    docs.mkdir(parents=True)
    examples.mkdir(parents=True)
    (docs / "workflow-format.md").write_text(
        "# Synthetic fixture workflow format\n"
        "A workflow has initial_node and a nodes map. Conversation nodes use\n"
        "tools and transitions; end_call nodes have a terminal function.\n",
        encoding="utf-8",
    )
    (docs / "tools-and-code.md").write_text(
        "# Synthetic fixture tools\n"
        "API tools use __function__:api_call with declared URL and method.\n"
        "pre_process_code and post_process_code belong on the tool object.\n",
        encoding="utf-8",
    )
    (examples / "base-agent.json").write_text(json.dumps(workflow), encoding="utf-8")
    provider = FixtureProvider([policy, generated, {"verdict": "pass", "issues": [], "counterexamples": []}])
    return source, api_path, provider


def run_build(env):
    source, api_path, provider = build_fixture(env)
    result = builder_live.build_live(
        [str(source)], str(api_path), str(env.directory / "build"), root=env.root, kit=env.kit,
        case_ids=["case-alpha"], repairs=0, provider=provider,
        # Production class, not a replacement Backend implementation.
        backend_factory=builder_live.LiveBackend,
    )
    return result


def test_verified_fixed_model_and_preserved_hooks_allow_practice(platform):
    env = platform()

    result = run_build(env)

    assert result["status"] == "practice_passed"
    assert result["passed"] == result["total_trials"] == 1
    assert result["live_tested"] is True and result["final_ready"] is False
    assert env.bridge.methods().index("get_workflow") < env.bridge.methods().index("prepare_practice")
    assert env.bridge.closed
    exported = json.loads(Path(result["workflow_path"]).read_text())
    assert exported["nodes"]["welcome"]["tools"][0]["post_process_code"]


@pytest.mark.parametrize("judge", [
    {"outcome": "fail", "reason": "Synthetic conversation failure"}, None,
], ids=["judge-fail", "missing-judge"])
def test_build_result_fails_with_passing_ledger_and_unsuccessful_judge(platform, judge):
    env = platform()
    env.bridge.judges["case-alpha"] = judge

    result = run_build(env)

    assert result["status"] == "practice_failed"
    assert result["passed"] == 0 and result["total_trials"] == 1
    assert result["final_ready"] is False
    rows = json.loads((env.directory / "build" / "practice-1.json").read_text())
    assert rows[0]["pass"] is False
    assert any(item.startswith("conversation:") for item in rows[0]["failed"])
    assert "ledger" in env.bridge.methods()
    assert env.bridge.closed


@pytest.mark.parametrize("change", ["provider", "model", "missing-provider", "missing-model", "missing-config"])
def test_unverified_phone_model_prevents_practice_and_records_failure(platform, change):
    env = platform()

    def changed(workflow):
        config = workflow["agent_config"]["llmConfig"]
        if change == "missing-config":
            del workflow["agent_config"]
        elif change.startswith("missing-"):
            del config[change.removeprefix("missing-")]
        else:
            config[change] = "wrong-model-fixture"
        return workflow

    env.bridge.readback_transform = changed
    with pytest.raises(builder_live.BuildFailure, match="Saved phone model differs"):
        run_build(env)

    assert "save" in env.bridge.methods() and "get_workflow" in env.bridge.methods()
    assert [event["method"] for event in env.bridge.mutations()] == ["save"]
    assert "prepare_practice" not in env.bridge.methods() and "start" not in env.bridge.methods()
    assert "export" not in env.bridge.methods()
    trace = json.loads((env.directory / "build" / "trace.json").read_text())
    assert trace["status"] == "failed" and trace["final_ready"] is False
    assert trace["tests"] == []
    assert env.bridge.closed


@pytest.mark.parametrize("hook", ["pre_process_code", "post_process_code"])
def test_server_stripping_semantic_hook_prevents_practice(platform, hook):
    env = platform()

    def stripped(workflow):
        del workflow["nodes"]["welcome"]["tools"][0][hook]
        return workflow

    env.bridge.readback_transform = stripped
    with pytest.raises(builder_live.BuildFailure, match=hook + " was stripped"):
        run_build(env)

    assert [event["method"] for event in env.bridge.mutations()] == ["save"]
    assert "get_workflow" in env.bridge.methods()
    assert "prepare_practice" not in env.bridge.methods() and "start" not in env.bridge.methods()
    readback = json.loads((env.directory / "build" / "readback.json").read_text())
    assert readback["authored_fields_preserved"] is False
    assert any(f"$.nodes.welcome.tools[0].{hook}" in issue for issue in readback["issues"])
    assert env.bridge.closed


@pytest.mark.parametrize("method", ["save", "prepare_practice", "start"])
def test_expired_budget_dispatches_no_new_mutation(platform, method):
    env = platform()
    env.clock.now = env.evidence.deadline
    with pytest.raises(builder_live.BuildFailure, match="time budget exhausted"):
        env.backend.call(method)
    assert env.bridge.events == []
    assert env.backend.tool_calls == 0


def test_budget_used_by_validation_prevents_workflow_save(platform):
    env = platform(budget=180)
    path = env.directory / "candidate.json"
    path.write_text('{"initial_node":"done","nodes":{"done":{}}}', encoding="utf-8")
    env.bridge.delays["validate"] = 180
    with pytest.raises(builder_live.BuildFailure, match="time budget exhausted"):
        env.backend.deploy(path, "budget-fixture", json.loads(path.read_text()))
    assert env.bridge.methods() == ["validate"]
    assert env.bridge.mutations() == []
    assert (env.evidence.directory / "remote-validation.json").is_file()


def test_budget_used_by_running_simulation_prevents_next_batch_or_repetition(platform):
    ids = [f"case-{i}" for i in range(6)]
    env = platform(ids, budget=180)
    env.bridge.delays["status"] = 180
    with pytest.raises(builder_live.BuildFailure, match="time budget exhausted"):
        env.backend.practice(DEPLOYED, ids, repetitions=2)
    assert [event["method"] for event in env.bridge.mutations()] == ["prepare_practice", "start"]
    assert len(env.bridge.prepared) == len(env.bridge.simulations) == 1
    assert env.bridge.active == "simulation-1"


def test_insufficient_simulation_budget_does_not_create_practice_sessions(platform):
    # 75s settlement reserve leaves 59s, below Bridge.start's 60s minimum.
    env = platform(budget=134)
    with pytest.raises(builder_live.BuildFailure):
        env.backend.practice(DEPLOYED, ["case-alpha"])
    assert env.bridge.mutations() == [], "practice sessions created despite insufficient simulation budget"


def test_deadline_crossed_while_recording_dispatch_does_not_save(platform, monkeypatch):
    env = platform(budget=60)
    path = env.directory / "candidate.json"
    path.write_text('{"initial_node":"done","nodes":{"done":{}}}', encoding="utf-8")
    env.clock.now = env.evidence.deadline - 2
    original_write = env.evidence.write

    def slow_trace_write(name, value):
        result = original_write(name, value)
        if name == "trace.json":
            # A filesystem stall between the initial budget check and dispatch.
            env.clock.now += 3
        return result

    monkeypatch.setattr(env.evidence, "write", slow_trace_write)
    failure = None
    try:
        env.backend.call("save", "deadline-fixture", str(path), name="deadline-fixture")
    except builder_live.BuildFailure as exc:
        failure = exc
    assert env.bridge.mutations() == [], "workflow saved after the builder deadline"
    assert failure is not None and "time budget exhausted" in str(failure)
