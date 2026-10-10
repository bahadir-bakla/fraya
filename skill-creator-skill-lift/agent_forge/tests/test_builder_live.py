"""Deployment boundaries and artifact integrity, independent of live model quality."""
import json
from pathlib import Path
import pytest

from agent_forge.builder_live import build_live, BuildFailure, compare_saved, critic_errors, utc
from agent_forge.input_contract import inspect_inputs

ROOT = Path(__file__).resolve().parents[3]
KIT = ROOT / "competition-v3" / "build-the-builder"
API = KIT / "tools" / "openapi.json"


def fixture(tmp_path):
    source = tmp_path / "brief.md"
    source.write_text("# Welcome\n1. Say hello to the caller.\n", encoding="utf-8")
    contract = inspect_inputs([source], API)
    ids = [c["qualified_id"] for d in contract["documents"] for c in d["clauses"]]
    policy = {"title": "Welcome", "rules": [{"source_id": i, "binding": True, "policy": "Say hello",
              "trigger": "call start", "actions": ["greet"], "exceptions": [], "overrides": [], "tool_names": []} for i in ids],
              "parameters": [], "stages": [], "ambiguities": []}
    workflow = {"initial_node": "welcome", "nodes": {"welcome": {"name": "welcome", "node_type": "end_call",
                "terminal": {"type": "function", "function": {"name": "finish", "handler": "__function__:end_call",
                    "parameters": {"type": "object", "properties": {"message_mode": {"type": "string", "default": "custom"},
                                   "spoken_message": {"type": "string", "default": "Hello."}}}}}}}}
    emitted = {"workflow_json": json.dumps(workflow), "coverage": [{"source_id": i, "node_ids": ["welcome"], "mechanism": "Greeting spoken in welcome"} for i in ids], "limitations": []}
    critic = {"verdict": "pass", "issues": [], "counterexamples": []}
    return source, contract, policy, workflow, emitted, critic


class Provider:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.purposes = []

    def generate(self, purpose, prompt, schema, timeout_seconds):
        self.purposes.append(purpose)
        return next(self.responses)


class Backend:
    instances = []
    def __init__(self, root, kit, evidence):
        self.evidence = evidence
        self.tool_calls = 0
        self.deployed = False
        self.closed = False
        self.instances.append(self)

    def call(self, name, **kwargs):
        self.tool_calls += 1
        if name == "health":
            return {"live_connected": True}
        raise AssertionError("unexpected backend request")

    def close(self):
        self.closed = True


def run(source, tmp_path, provider, **kwargs):
    return build_live([str(source)], str(API), str(tmp_path / "out"), root=ROOT, kit=KIT,
                      provider=provider, backend_factory=Backend, **kwargs)


def test_no_publish_when_independent_critic_finds_source_violation(tmp_path):
    source, contract, policy, workflow, emitted, critic = fixture(tmp_path)
    critic["verdict"] = "revise"
    critic["issues"] = [{"severity": "error", "source_ids": [contract["documents"][0]["clauses"][0]["qualified_id"]],
                         "location": "welcome", "message": "greeting omitted", "fix": "add greeting"}]
    with pytest.raises(BuildFailure, match="No candidate"):
        run(source, tmp_path, Provider([policy, emitted, critic]), repairs=0)
    assert Backend.instances[-1].closed
    assert not Backend.instances[-1].deployed
    trace = json.loads((tmp_path / "out" / "trace.json").read_text())
    assert trace["status"] == "failed" and trace["final_ready"] is False


def test_missing_source_rule_fails_before_workflow_generation(tmp_path):
    source, contract, policy, *_ = fixture(tmp_path)
    policy["rules"] = []
    provider = Provider([policy])
    with pytest.raises(BuildFailure, match="Policy compilation rejected"):
        run(source, tmp_path, provider, compile_only=True)
    assert provider.purposes == ["policy"]


def test_compile_only_is_explicitly_unpublished_and_untested(tmp_path):
    source, contract, policy, workflow, emitted, critic = fixture(tmp_path)
    before = len(Backend.instances)
    result = run(source, tmp_path, Provider([policy, emitted, critic]), compile_only=True, repairs=0)
    assert result["status"] == "compiled_unpublished" and result["live_tested"] is False
    assert len(Backend.instances) == before
    assert Path(result["workflow_path"]).is_file()


def test_readback_detects_stripped_negative_hook_even_with_platform_extras():
    expected = {"nodes": {"x": {"tools": [{"post_process_code": "guard()", "config": {"maxRetries": 0}}]}}}
    actual = {"nodes": {"x": {"tools": [{"config": {"maxRetries": 0, "timeoutMs": 10000}}]}}, "agent_config": {"foo": True}}
    assert any("post_process_code was stripped" in issue for issue in compare_saved(expected, actual))


def test_readback_rejects_reordered_tool_sequence():
    assert compare_saved({"tools": [{"name": "first"}, {"name": "last"}]}, {"tools": [{"name": "last"}, {"name": "first"}]})


def test_readback_accepts_only_additional_server_defaults():
    assert not compare_saved({"nodes": {"a": {"task_message": "Hello"}}},
                             {"nodes": {"a": {"task_message": "Hello", "tools": []}}, "agent_config": {}})


def test_critic_cannot_greenwash_errors_with_pass_verdict(tmp_path):
    _, contract, *rest = fixture(tmp_path)
    source_id = contract["documents"][0]["clauses"][0]["qualified_id"]
    critic = {"verdict": "pass", "issues": [{"severity": "error", "source_ids": [source_id], "location": "x", "message": "bad", "fix": "fix"}], "counterexamples": []}
    assert critic_errors(critic, contract)


def test_unspecified_protocol_is_reviewed_without_suppressing_binding_ambiguity(tmp_path):
    source, contract, policy, workflow, emitted, critic = fixture(tmp_path)
    policy["ambiguities"] = ["Failure recovery is unspecified"]
    review = {"assessments": [{"index": 0, "source_ids": [contract["documents"][0]["clauses"][0]["qualified_id"]],
              "disposition": "safe_protocol_choice", "resolution": "Do not claim an unconfirmed tool succeeded"}]}
    result = run(source, tmp_path, Provider([policy, review, emitted, critic]), compile_only=True, repairs=0)
    assert result["status"] == "compiled_unpublished"
    review["assessments"][0]["disposition"] = "blocking"
    with pytest.raises(BuildFailure, match="Unresolved binding policy ambiguity"):
        run(source, tmp_path, Provider([policy, review]), compile_only=True, repairs=0)


def test_checkpoint_rejects_changed_brief_before_any_model_call(tmp_path):
    source, contract, policy, *_ = fixture(tmp_path)
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    for filename, value in [("input-contract.json", contract), ("policy.json", policy),
                            ("trace.json", {"started_at": utc(), "events": [], "status": "failed"})]:
        (checkpoint / filename).write_text(json.dumps(value), encoding="utf-8")
    source.write_text("# Welcome\n1. Say goodbye.\n", encoding="utf-8")
    provider = Provider([])
    with pytest.raises(BuildFailure, match="hashes differ"):
        run(source, tmp_path, provider, compile_only=True, policy_checkpoint=str(checkpoint / "policy.json"))
    assert not provider.purposes


def test_raw_sources_refuses_file_modified_after_inventory(tmp_path):
    from agent_forge.builder_prompts import raw_sources
    source, contract, *_ = fixture(tmp_path)
    source.write_text("Replacement instructions", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after inventory"):
        raw_sources(contract)
