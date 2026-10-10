"""Offline checks of the documented node contract and its actual baked code."""

import ast
import builtins
from copy import deepcopy
import json

import httpx
import pytest

from agent_forge.freya_compiler import compile_workflow
from agent_forge.freya_lint import lint_workflow
from agent_forge.guarded_actions import action_envelope, new_state
from agent_forge.guarded_freya_adapter import (
    guarded_builtin_snippets, guard_node, validate_guard_wiring,
)
from agent_forge.tool_api import parse_openapi


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Adapter tests must not make HTTP requests")
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)


@pytest.fixture
def api():
    return parse_openapi({
        "openapi": "3.0.3", "info": {"title": "Synthetic adapter API", "version": "9"},
        "servers": [{"url": "https://fixture.invalid/v9"}],
        "paths": {"/slots": {"post": {
            "operationId": "store_slot", "responses": {"200": {"description": "Receipt"}},
            "requestBody": {"required": True, "content": {"application/json": {
                "schema": request_schema(),
            }}},
        }}},
    })


def request_schema():
    return {
        "type": "object", "additionalProperties": False,
        "required": ["actor", "sku", "credit", "due_day"],
        "properties": {
            "actor": {"type": "string"}, "sku": {"type": "string"},
            "credit": {"type": "number"}, "due_day": {"type": "string", "format": "date"},
        },
    }


@pytest.fixture
def policy():
    # Explicit synthetic source parameters; nothing is inferred by the adapter.
    return {
        "version": "source-v9", "source_policy_parameters": {"fixture_rule": "supplied"},
        "calendar": {"now": "2031-04-02T11:00:00", "holidays": ["2031-04-04"],
                     "weekmask": [0, 1, 2, 3, 4], "week_start": 0},
        "products": [{"product_id": "slot-z", "deadline": "2031-04-10",
                      "minimum": "3.25", "maximum": "10.00", "quantum": "0.25", "max_write_attempts": 1}],
        "capabilities": {
            "store_slot": {
                "effect": "promise", "request_schema": request_schema(),
                "product_field": "sku", "amount_field": "credit", "date_field": "due_day",
                "requires_confirmation": True, "required_facts": {"identity_step": "passed"},
                "request_bindings": {"actor": "party"},
            },
        },
    }


def code_parameter(node):
    return node["pre_actions"][0]["function"]["parameters"]["properties"]["code"]


def graph():
    return {
        "initial_node": "gate", "nodes": {
            "gate": guard_node("gate", "send", "hold"),
            "send": {"name": "send", "node_type": "conversation",
                     "task_message": "A separate trusted adapter may dispatch the reserved request.",
                     "tools": [{"_tool_ref": "declared_write"}],
                     "transitions": [{"target_node": "done", "condition": {"operator": "always"}}]},
            "hold": {"name": "hold", "node_type": "conversation", "task_message": "Review the blocked result.",
                     "transitions": [{"target_node": "done", "condition": {"operator": "always"}}]},
            "done": {"name": "done", "node_type": "end_call", "transitions": [], "terminal": {
                "type": "function", "function": {"name": "finish", "handler": "__function__:end_call",
                                               "parameters": {"type": "object", "properties": {}}},
            }},
        },
        "_tool_library": {"declared_write": {"operation": "store_slot"}},
    }


def execute(node, variables):
    def documented_imports(name, *args, **kwargs):
        assert name in {"json", "re", "datetime"}, name
        return builtins.__import__(name, *args, **kwargs)
    sandbox = {**vars(builtins), "__import__": documented_imports}
    exec(compile(code_parameter(node)["default"], "<actual-adapter-node>", "exec"),
         {"vars": variables, "__builtins__": sandbox})
    return json.loads(variables["guard_state_json"])


def event(node, variables, kind, **fields):
    state = json.loads(variables["guard_state_json"])
    if kind != "result":
        fields.setdefault("revision", state["call_revision"] + (kind != "readback"))
    variables["guard_command_json"] = json.dumps({"kind": "event", "event": {"kind": kind, **fields}})
    return execute(node, variables)


def confirmed_variables(node, policy):
    variables = {
        "guard_policy_json": json.dumps(policy),
        "guard_state_json": json.dumps(new_state(policy, facts={"party": "synthetic-party", "identity_step": "passed"})),
    }
    event(node, variables, "propose", product_id="slot-z", amount="4.50", date="2031-04-03")
    assert variables["guard_flag"] == "accepted"
    state = event(node, variables, "readback", delivered=True)
    event(node, variables, "confirm", accepted=True, readback_revision=state["call_revision"])
    assert variables["guard_flag"] == "accepted"
    return variables


def candidate(policy, state, body=None):
    body = body or '{"actor":"synthetic-party","sku":"slot-z","credit":4.50,"due_day":"2031-04-03"}'
    return action_envelope(policy, state, "store_slot", body)


def dispatch(node, variables, envelope):
    variables["guard_command_json"] = json.dumps({"kind": "dispatch", "envelope": envelope})
    return execute(node, variables)


def routed_target(node, variables):
    # Reference evaluator for the documented string-equals / first-match rules.
    def matches(condition):
        if "conditions" in condition:
            assert condition["logic"] == "or"
            return any(matches(child) for child in condition["conditions"])
        if condition["operator"] == "always":
            return True
        assert condition["operator"] == "equals"
        return str(variables.get(condition["variable"])) == str(condition["operand"])
    return next(t["target_node"] for t in node["transitions"] if matches(t["condition"]))


def test_builtin_is_fresh_deterministic_portable_source_with_no_template_delimiters():
    first = guarded_builtin_snippets()
    second = guarded_builtin_snippets()
    assert first == second and first is not second and set(first) == {"guarded_dispatch"}
    code = first["guarded_dispatch"]
    assert "{{" not in code and "}}" not in code
    tree = ast.parse(code)
    assert {n.names[0].name for n in ast.walk(tree) if isinstance(n, ast.Import)} == {"json", "re", "datetime"}
    assert not any(isinstance(n, ast.ImportFrom) for n in ast.walk(tree))
    first["guarded_dispatch"] = "untrusted replacement"
    assert guarded_builtin_snippets() == second


def test_baked_node_compiles_and_lints_with_changed_toy_api_without_mutating_ir(api):
    compact = graph()
    before = deepcopy(compact)
    workflow = compile_workflow(compact, api)
    assert lint_workflow(workflow, api) == []
    assert validate_guard_wiring(workflow) == []
    assert compact == before and "_tool_library" not in workflow
    node = workflow["nodes"]["gate"]
    assert code_parameter(node)["default"] == guarded_builtin_snippets()["guarded_dispatch"]
    assert node["pre_actions"][0]["function"]["handler"] == "__function__:code_exec"
    assert "tools" not in node and "test_variables" not in node
    assert "guard_policy_json" not in workflow.get("test_variables", {})
    assert not any(a["function"]["handler"] == "__function__:api_call" for a in node["pre_actions"])


@pytest.mark.parametrize("flag", ["accepted", "blocked", "true", True, "", None, "allowed"])
def test_documented_router_only_authorizes_the_allowed_string(flag):
    node = guard_node("gate", "send", "hold")
    assert routed_target(node, {"guard_flag": flag}) == ("send" if flag == "allowed" else "hold")
    assert routed_target(node, {}) == "hold"


def test_actual_compiled_guard_reserves_request_without_calling_api_or_claiming_recorded(api, policy):
    node = compile_workflow(graph(), api)["nodes"]["gate"]
    variables = confirmed_variables(node, policy)
    assert routed_target(node, variables) == "hold"  # Accepted events never authorize a write.
    action = candidate(policy, json.loads(variables["guard_state_json"]))
    state = dispatch(node, variables, action)
    assert routed_target(node, variables) == "send" and variables["guard_flag"] == "allowed"
    assert variables["guard_request_json"] == action["request_json"]
    assert state["pending"]["envelope"] == action
    assert state["products"]["slot-z"]["attempts"] == 1
    assert state["products"]["slot-z"]["recorded"] is None
    state = dispatch(node, variables, action)
    assert routed_target(node, variables) == "hold" and variables["guard_request_json"] == ""
    assert state["products"]["slot-z"]["attempts"] == 1


def test_actual_node_persists_invalid_correction_before_rejecting_old_dispatch(policy):
    node = guard_node("gate", "send", "hold")
    variables = confirmed_variables(node, policy)
    state = json.loads(variables["guard_state_json"])
    old_action = candidate(policy, state)
    variables.update(guard_flag="allowed", guard_request_json=old_action["request_json"])
    changed = event(node, variables, "correction", product_id="slot-z", amount="0.01", date="2031-04-03")
    assert variables["guard_flag"] == "blocked" and routed_target(node, variables) == "hold"
    assert changed["call_revision"] == state["call_revision"] + 1
    assert changed["products"]["slot-z"]["confirmed"] is None
    assert variables["guard_request_json"] == ""
    assert "amount_below_floor" in [v["code"] for v in json.loads(variables["guard_violations_json"])]
    dispatch(node, variables, old_action)
    assert routed_target(node, variables) == "hold" and variables["guard_request_json"] == ""


def test_actual_node_holds_unknown_write_until_real_matching_receipt(policy):
    node = guard_node("gate", "send", "hold")
    variables = confirmed_variables(node, policy)
    action = candidate(policy, json.loads(variables["guard_state_json"]))
    dispatch(node, variables, action)
    unknown = event(node, variables, "result", action_id=action["action_id"], status="unknown")
    assert unknown["pending"]["status"] == "unknown" and routed_target(node, variables) == "hold"
    assert unknown["products"]["slot-z"]["recorded"] is None
    dispatch(node, variables, candidate(policy, unknown))
    assert variables["guard_flag"] == "blocked" and variables["guard_request_json"] == ""
    final = event(node, variables, "result", action_id=action["action_id"], status="succeeded", receipt_id="real-fixture-receipt")
    assert final["pending"] is None and routed_target(node, variables) == "hold"
    assert final["products"]["slot-z"]["recorded"]["receipt_id"] == "real-fixture-receipt"


def test_actual_node_does_not_dispatch_stale_schema_fields_or_missing_trusted_inputs(policy):
    node = guard_node("gate", "send", "hold")
    variables = confirmed_variables(node, policy)
    state = json.loads(variables["guard_state_json"])
    old_body = '{"actor":"synthetic-party","sku":"slot-z","amount":4.50,"due_day":"2031-04-03"}'
    rejected = dispatch(node, variables, candidate(policy, state, old_body))
    assert routed_target(node, variables) == "hold" and rejected["pending"] is None
    assert rejected["products"]["slot-z"]["attempts"] == 0 and variables["guard_request_json"] == ""
    del variables["guard_policy_json"]
    variables.update(guard_flag="allowed", guard_request_json="stale-body")
    execute(node, variables)
    assert routed_target(node, variables) == "hold" and variables["guard_request_json"] == ""


def test_validation_opt_in_is_an_executing_builtin_slot_not_a_prompt_or_metadata_mention():
    unrelated = {
        "nodes": {"talk": {"node_type": "conversation", "task_message": "@builtin:guarded_dispatch",
                            "transitions": [], "metadata": guard_node("copy", "send", "hold")}},
        "metadata": {"builtin": "@builtin:guarded_dispatch"},
        "_code_library": guarded_builtin_snippets(),
    }
    assert validate_guard_wiring(unrelated) == []
    assert validate_guard_wiring(None) == []
    # Ordinary lint, not this helper, owns arbitrary author-written code.
    authored_node = guard_node("authored", "send", "hold")
    code_parameter(authored_node)["default"] = "vars['guard_flag'] = 'allowed'"
    unrelated["nodes"]["authored"] = authored_node
    assert validate_guard_wiring(unrelated) == []


def test_unresolved_builtin_reference_can_be_wiring_checked_but_is_not_deployable_python(api):
    workflow = compile_workflow(graph(), api)
    code_parameter(workflow["nodes"]["gate"])["default"] = "@builtin:guarded_dispatch"
    before = deepcopy(workflow)
    assert validate_guard_wiring(workflow) == [] and workflow == before
    assert any("Invalid Python syntax" in issue["message"] for issue in lint_workflow(workflow, api))


@pytest.mark.parametrize("defect", [
    "accepted", "boolean", "api_success", "always_in_or", "reversed", "semantic_fallback",
    "tool_call_route", "allowed_default", "merged_targets", "missing_target", "early_write",
    "dialogue_guard", "retry", "loop",
])
def test_validation_rejects_concrete_bypass_and_deadlock_wiring_without_mutating(defect):
    workflow = graph()
    node = workflow["nodes"]["gate"]
    check = node["transitions"][0]["condition"]["conditions"][0]
    if defect == "accepted":
        check["operand"] = "accepted"
    elif defect == "boolean":
        check["operand"] = True
    elif defect == "api_success":
        check["variable"] = "store_slot_response.status"
    elif defect == "always_in_or":
        node["transitions"][0]["condition"]["conditions"].append({"operator": "always"})
    elif defect == "reversed":
        node["transitions"].reverse()
    elif defect == "semantic_fallback":
        node["transitions"][1]["condition"] = {"operator": "matches_intent", "description": "Ask again"}
    elif defect == "tool_call_route":
        node["transitions"][0]["is_tool_call"] = True
    elif defect == "allowed_default":
        node["passthrough_default_transition"] = "send"
    elif defect == "merged_targets":
        node["transitions"][1]["target_node"] = "send"
        node["passthrough_default_transition"] = "send"
    elif defect == "missing_target":
        node["transitions"][0]["target_node"] = "missing"
    elif defect == "early_write":
        node["pre_actions"].insert(0, {"_tool_ref": "declared_write"})
    elif defect == "dialogue_guard":
        node["node_type"] = "conversation"
        node["tools"] = node.pop("pre_actions")
    elif defect == "retry":
        node["pre_actions"][0]["config"]["maxRetries"] = 1
    elif defect == "loop":
        node["loop_condition"] = "Stay after a correction"
    before = deepcopy(workflow)
    issues = validate_guard_wiring(workflow)
    assert issues and workflow == before
    assert all(set(issue) == {"severity", "path", "message"} and issue["severity"] == "error" for issue in issues)
    assert any("gate" in issue["path"] for issue in issues)


def test_validation_rejects_builtin_used_as_lifecycle_action_or_api_hook():
    workflow = graph()
    action = workflow["nodes"].pop("gate")["pre_actions"][0]
    workflow["initial_node"] = "hold"
    workflow["tools"] = [action]
    assert any("$.tools[0]" == issue["path"] for issue in validate_guard_wiring(workflow))
    del workflow["tools"]
    workflow["nodes"]["hold"]["tools"] = [{
        "type": "function", "function": {"handler": "__function__:api_call"},
        "pre_process_code": guarded_builtin_snippets()["guarded_dispatch"],
    }]
    assert any("baked code.default" in issue["message"] for issue in validate_guard_wiring(workflow))


@pytest.mark.parametrize("names", [("gate", "send", "send"), ("gate", "gate", "hold"),
                                  ("gate", "send", "gate"), ("gate", "", "hold"),
                                  ("gate", "__previous__", "hold"), ("gate", None, "hold")])
def test_factory_rejects_merged_targets_self_deadlocks_and_invalid_names(names):
    with pytest.raises(ValueError):
        guard_node(*names)
