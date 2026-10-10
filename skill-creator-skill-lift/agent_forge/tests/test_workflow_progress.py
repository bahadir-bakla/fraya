"""Offline behavioral cases for advisory progress inspection, without execution."""

import builtins
from copy import deepcopy

import pytest

from agent_forge.workflow_progress import diagnose_workflow_progress


def end():
    return {"node_type": "end_call", "transitions": [], "terminal": {
        "type": "function", "function": {"name": "native_finish", "handler": "__function__:end_call",
                                       "parameters": {"type": "object", "properties": {}}}}}


def edge(target, condition=None, **fields):
    return {"target_node": target, "condition": condition or {"operator": "always"}, **fields}


def intent():
    return {"operator": "matches_intent", "description": "The caller asks to finish"}


def check(variable, operator="equals", operand="ready"):
    leaf = {"variable": variable, "operator": operator}
    if operator not in {"is_set", "is_not_set"}:
        leaf["operand"] = operand
    return leaf


def graph(transitions=None):
    return {"initial_node": "collect", "nodes": {
        "collect": {"node_type": "conversation", "transitions": transitions or [edge("done", intent())]},
        "done": end(),
    }}


def close_graph(condition=None, *, name="seal_record"):
    workflow = graph([edge("done", condition or check(name + "_response.status")), edge("collect")])
    workflow["nodes"]["collect"]["tools"] = [{
        "type": "function", "function": {
            "name": name, "handler": "__function__:api_call",
            "parameters": {"type": "object", "properties": {
                "url": {"type": "string", "default": "https://fixture.invalid/seal"},
                "method": {"type": "string", "default": "POST"},
            }},
        },
    }]
    return workflow


def findings(workflow, name=None):
    return diagnose_workflow_progress(workflow, close_operation_name=name)


def close_warnings(workflow, name="seal_record"):
    return [issue for issue in findings(workflow, name) if "backend close operation is offered" in issue["message"]]


@pytest.mark.parametrize("condition", [
    {"operator": "always"}, check("phase", "is_set"), check("phase", "is_not_set"),
    check("phase"), check("attempts", "greater_than", 0),
    {"logic": "or", "conditions": [check("phase"), check("phase", "is_not_set")]},
])
def test_earlier_state_only_self_loop_can_starve_semantic_escape(condition):
    workflow = graph([edge("collect", condition), edge("done", intent())])
    before = deepcopy(workflow)
    issues = findings(workflow)
    assert len(issues) == 1 and issues[0]["path"] == "$.nodes.collect.transitions[0].condition"
    assert "Potential semantic starvation" in issues[0]["message"]
    assert "$.nodes.collect.transitions[1].condition" in issues[0]["message"]
    assert workflow == before
    assert issues[0]["severity"] == "warning"


@pytest.mark.parametrize("transitions", [
    [edge("done", intent()), edge("collect")],  # Documented last self fallback.
    [edge("collect", intent()), edge("done", intent())],
    [edge("collect", check("phase"), is_tool_call=True), edge("done", intent())],
    [edge("collect", check("phase")), edge("done", intent(), is_tool_call=True)],
    [edge("collect", check("phase")), edge("done", check("finished"))],
])
def test_intent_or_model_tool_transitions_and_last_fallback_are_not_reported_as_early_state_starvation(transitions):
    assert findings(graph(transitions)) == []


def test_cycle_does_not_make_disconnected_end_reachable_but_declared_escape_does():
    workflow = graph([edge("again")])
    workflow["nodes"]["again"] = {"node_type": "conversation", "transitions": [edge("collect")]}
    issues = findings(workflow)
    assert len(issues) == 1 and issues[0]["path"] == "$.initial_node"
    assert "No native end_call terminal is reachable" in issues[0]["message"]
    workflow["nodes"]["again"]["transitions"].insert(0, edge("done", intent()))
    assert findings(workflow) == []


def test_large_cycle_is_inspected_iteratively_and_an_escape_is_not_claimed_impossible():
    nodes = {str(i): {"node_type": "conversation", "transitions": [edge(str((i + 1) % 1200))]}
             for i in range(1200)}
    nodes["done"] = end()
    workflow = {"initial_node": "0", "nodes": nodes}
    assert any("No native end_call" in issue["message"] for issue in findings(workflow))
    nodes["1199"]["transitions"].insert(0, edge("done", intent()))
    assert findings(workflow) == []


def test_turn_limit_passthrough_and_nonexcluded_global_routes_are_possible_not_guaranteed():
    workflow = graph([edge("collect")])
    workflow["nodes"]["collect"].update(max_turn_transition="", passthrough_default_transition="")
    assert any("No native end_call" in issue["message"] for issue in findings(workflow))
    workflow["nodes"]["collect"]["max_turn_transition"] = "done"
    assert findings(workflow) == []
    del workflow["nodes"]["collect"]["max_turn_transition"]
    workflow["nodes"]["collect"].update(passthrough=True, passthrough_default_transition="done")
    assert findings(workflow) == []
    workflow["nodes"]["collect"]["passthrough"] = False
    assert any("No native end_call" in issue["message"] for issue in findings(workflow))
    del workflow["nodes"]["done"]
    workflow["global_nodes"] = {"global_end": {**end(), "condition": intent(), "excluded_nodes": []}}
    assert findings(workflow) == []  # Upper bound includes global entry despite local self-loop.
    workflow["global_nodes"]["global_end"]["excluded_nodes"] = ["collect"]
    assert any("No native end_call" in issue["message"] for issue in findings(workflow))


def test_global_previous_returns_do_not_fabricate_access_to_an_unvisited_end():
    workflow = graph([edge("collect")])
    workflow["global_nodes"] = {"interrupt": {
        "condition": intent(), "transitions": [edge("__previous__")],
        "passthrough": True, "passthrough_default_transition": "__previous__",
    }}
    assert any("No native end_call" in issue["message"] for issue in findings(workflow))


def test_native_end_actions_and_outgoing_routes_are_warned_at_their_actual_paths():
    workflow = graph()
    node = workflow["nodes"]["done"]
    node.update(transitions=[edge("collect")], tools=[{"function": {"name": "ignored"}}],
                pre_actions=[{"function": {"name": "also_ignored"}}])
    issues = findings(workflow)
    assert {issue["path"] for issue in issues} == {
        "$.nodes.done.transitions", "$.nodes.done.tools", "$.nodes.done.pre_actions"}
    assert all(issue["severity"] == "warning" for issue in issues)
    assert not any("No native end_call" in issue["message"] for issue in issues)


def test_a_node_named_end_or_backend_api_terminal_is_not_a_native_hangup():
    workflow = graph()
    workflow["nodes"]["done"]["terminal"]["function"]["handler"] = "__function__:api_call"
    issues = findings(workflow)
    assert any(issue["path"] == "$.nodes.done.terminal" for issue in issues)
    assert any(issue["path"] == "$.initial_node" for issue in issues)


def test_malformed_optional_route_does_not_conceal_missing_native_terminal_declarations():
    workflow = {"initial_node": "start", "nodes": {
        "start": {"node_type": "conversation", "transitions": [edge("start")], "max_turn_transition": None}}}
    issues = findings(workflow)
    assert any(issue["path"] == "$.nodes.start.max_turn_transition" for issue in issues)
    assert any(issue["path"] == "$.nodes" and "No native end_call terminal is declared" in issue["message"] for issue in issues)
    assert not any("is reachable from" in issue["message"] for issue in issues)


def test_exact_supplied_close_name_is_optional_and_backend_close_does_not_hang_up():
    workflow = close_graph()
    workflow["nodes"]["collect"]["transitions"] = [edge("collect")]
    assert close_warnings(workflow) and close_warnings(workflow)[0]["path"] == "$.nodes.collect.tools[0].function.name"
    assert not close_warnings(workflow, "a_different_operation")
    assert not any("backend close operation is offered" in issue["message"] for issue in findings(workflow))
    workflow["nodes"]["done"] = {"node_type": "conversation", "transitions": []}
    assert any("No native end_call" in issue["message"] for issue in findings(workflow))


@pytest.mark.parametrize("condition", [
    check("seal_record_response.data.accepted", "is_set"),
    check("seal_record_status_code", operand=200),
    check("seal_record_success_count", "greater_than", 0),
    check("seal_record_failure_count", "equals", "1"),
    {"logic": "or", "conditions": [check("seal_record_response.status", operand="ok"),
                                  check("seal_record_response.status", operand="error")]},
    {"logic": "or", "conditions": [{"logic": "and", "conditions": [
        check("seal_record_response.status"), intent()]}]},
])
def test_result_gates_and_positive_call_counts_can_advance_to_native_end(condition):
    assert findings(close_graph(condition), "seal_record") == []


@pytest.mark.parametrize("condition", [
    intent(), {"operator": "always"}, check("seal_record_args.receipt", "is_set"),
    check("other_operation_response.status"), check("seal_record_response.status", "is_not_set"),
    check("seal_record_response.status", "not_equals", "error"),
    check("seal_record_success_count", "greater_than", -1),
    {"logic": "or", "conditions": [check("seal_record_response.status"), intent()]},
    {"logic": "or", "conditions": [check("seal_record_response.status"), {"operator": "always"}]},
])
def test_paths_that_can_leave_before_a_close_result_do_not_count_as_result_gates(condition):
    assert close_warnings(close_graph(condition))


def test_result_gate_needs_progress_and_a_native_end_beyond_intermediate_cycles():
    workflow = close_graph()
    workflow["nodes"]["collect"]["transitions"][0]["target_node"] = "bridge"
    workflow["nodes"]["bridge"] = {"node_type": "code", "transitions": [edge("bridge")]}
    assert close_warnings(workflow)
    workflow["nodes"]["bridge"]["transitions"].insert(0, edge("done"))
    assert not close_warnings(workflow)
    workflow["nodes"]["collect"]["transitions"] = [edge("collect", check("seal_record_response.status")), edge("done", intent())]
    assert close_warnings(workflow)


def test_mapping_and_literal_post_hook_names_are_recognized_without_executing_hooks(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Progress diagnostics must not execute authored code")
    monkeypatch.setattr(builtins, "exec", forbidden)
    monkeypatch.setattr(builtins, "eval", forbidden)
    workflow = close_graph(check("custom_receipt", "is_set"), name="finish_ledger")
    tool = workflow["nodes"]["collect"]["tools"][0]
    tool["response_mapping"] = [{"path": "data.receipt", "variable": "custom_receipt"}]
    assert findings(workflow, "finish_ledger") == []
    del tool["response_mapping"]
    tool["post_process_code"] = "vars['custom_receipt'] = result\nraise RuntimeError('Never execute this')"
    assert findings(workflow, "finish_ledger") == []
    assert close_warnings(workflow, "seal_record") == []  # Exact operation name, not guessed aliases.


@pytest.mark.parametrize("annotation", [
    {"pre_process_code": "vars['custom_receipt'] = 'ready'"},
    {"post_process_code": "print(vars['custom_receipt'])"},
    {"post_process_code": "def not_called():\n    vars['custom_receipt'] = result"},
    {"post_process_code": "vars[dynamic_name] = result"},
    {"post_process_code": "vars['custom_receipt'] ="},
    {"response_mapping": [{"path": "ok", "variable": "custom_receipt"}]},
])
def test_pre_hooks_reads_dynamic_or_unexecuted_writes_and_unconfirmed_mappings_are_not_result_provenance(annotation):
    workflow = close_graph(check("custom_receipt", "is_set"))
    workflow["nodes"]["collect"]["tools"][0].update(annotation)
    assert close_warnings(workflow)


def test_wrong_mapping_placement_other_handler_and_lifecycle_tools_do_not_fabricate_dialogue_result_gates():
    workflow = close_graph(check("custom_receipt", "is_set"))
    tool = workflow["nodes"]["collect"]["tools"][0]
    tool["function"]["response_mapping"] = [{"path": "data.receipt", "variable": "custom_receipt"}]
    assert close_warnings(workflow)
    tool["function"]["handler"] = "__function__:code_exec"
    assert not close_warnings(workflow)
    tool["function"]["handler"] = "__function__:api_call"
    tool["config"] = {"alwaysRunsAt": ["end_of_call"]}
    assert not close_warnings(workflow)


@pytest.mark.parametrize("workflow", [
    None, [], "not a workflow", {}, {"nodes": []}, {"nodes": {"bad": None}, "initial_node": "bad"},
    {"nodes": {}, "initial_node": []},
    {"nodes": {"start": {"transitions": {}}}, "initial_node": "start"},
    {"nodes": {"start": {"transitions": [None]}}, "initial_node": "start"},
    {"nodes": {"start": {"transitions": [edge(["invalid"])]}}, "initial_node": "start"},
    {"nodes": {"start": {"transitions": [edge("missing")]}}, "initial_node": "start"},
    {"nodes": {"start": {}}, "initial_node": "start", "global_nodes": []},
])
def test_malformed_input_yields_only_advisory_inspection_limits_not_exceptions(workflow):
    issues = findings(workflow)
    assert issues and all(set(issue) == {"severity", "path", "message"} and issue["severity"] == "warning" for issue in issues)
    assert not any("terminal is reachable from the initial node" in issue["message"] for issue in issues)


def test_unknown_or_cyclic_conditions_are_not_fabricated_as_known_starvation_or_result_evidence():
    for bad in ({"operator": []}, {"operator": "equals", "variable": [], "operand": "ready"},
                {"logic": "or", "conditions": []}):
        workflow = graph([edge("collect", bad), edge("done", intent())])
        assert findings(workflow) == []
    cyclic = {"logic": "or", "conditions": []}
    cyclic["conditions"].append(cyclic)
    assert close_warnings(close_graph(cyclic))
    assert close_warnings(close_graph({"operator": "always", "variable": []}))


def test_ambiguous_node_maps_and_invalid_option_report_limits_without_negative_reachability_claims():
    workflow = graph([edge("collect")])
    workflow["global_nodes"] = {"collect": {"condition": intent(), "transitions": []}}
    issues = findings(workflow, [])
    assert any("ambiguous" in issue["message"] for issue in issues)
    assert any("close_operation_name" in issue["message"] for issue in issues)
    assert not any("No native end_call" in issue["message"] for issue in issues)


def test_valid_workflow_and_hook_annotations_are_not_mutated():
    workflow = close_graph()
    workflow["nodes"]["collect"]["tools"][0]["post_process_code"] = "result['data']['next_action'] = 'Review receipt'"
    before = deepcopy(workflow)
    assert findings(workflow, "seal_record") == []
    assert workflow == before
