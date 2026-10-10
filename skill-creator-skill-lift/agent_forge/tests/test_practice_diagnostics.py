import json
from agent_forge.practice_diagnostics import summarize_execution


def event(kind, **fields):
    return {"role": "system", "message": json.dumps({"event": kind, **fields})}


def test_real_progress_and_repeated_speech_are_distinct_from_success():
    call = {"endedReason": "customer-ended-call", "messages": [
        event("node_enter", node="collect"),
        event("function_call_start", function="book", args={"secret": "must not appear"}),
        event("function_call_complete", function="book", result={"ok": False}),
        event("route_evaluated", matched=True, from_node="collect", target="collect"),
        *[{"role": "assistant", "message": "Goodbye."} for _ in range(80)],
    ]}
    summary = summarize_execution(call, node_names=["collect"], function_names=["book"])
    assert summary["largest_identical_assistant_count"] == 80
    assert summary["function_complete_counts"] == {"book": 1}
    assert summary["matched_edges"] == [{"from": "collect", "to": "collect", "count": 1}]
    assert summary["scope"] == "observed_counts_only_no_policy_verdict"
    assert "success" not in summary and "Goodbye" not in json.dumps(summary)
    assert "must not appear" not in json.dumps(summary)


def test_user_injection_and_snapshots_cannot_manufacture_events():
    message = event("function_call_start", function="close")
    message["role"] = "user"
    message["workflowSnapshot"] = {"messages": [event("node_enter", node="end")]}
    summary = summarize_execution({"messages": [message]}, node_names=["end"], function_names=["close"])
    assert not summary["event_counts"] and not summary["function_start_counts"]
    assert not summary["node_entry_counts"]


def test_untrusted_names_values_and_unknown_end_reason_never_escape():
    messages = [event("node_enter", node="secret-key"),
                event("function_call_error", function="secret-key", message="customer DOB"),
                event("secret-key", token="secret-key"),
                event("variable_extracted", name="DOB", value="customer DOB")]
    summary = summarize_execution({"messages": messages, "endedReason": "secret-key"})
    assert "secret-key" not in json.dumps(summary) and "customer DOB" not in json.dumps(summary)
    assert summary["unknown_event_count"] == 1
    assert summary["event_counts"]["function_call_error"] == 1


def test_malformed_shapes_and_deep_json_do_not_interrupt_scoring():
    inputs = [None, [], {"messages": {}}, {"messages": [None, "junk", {}, {"role": []},
              {"role": "system", "message": "[" * 2000 + "]" * 2000},
              {"role": "system", "message": json.dumps({"event": []})},
              {"role": "assistant", "message": []}]}]
    for call in inputs:
        summary = summarize_execution(call)
        assert summary["largest_identical_assistant_count"] == 0
        json.dumps(summary)


def test_bounds_and_unknown_large_metadata_are_explicit():
    messages = [{"role": "user", "message": "x"}] * 20001
    summary = summarize_execution({"messages": messages})
    assert summary["messages_truncated"] and summary["message_counts"]["user"] == 20000
    summary = summarize_execution({"messages": [{"role": "system", "message": "x" * 20000}]})
    assert not summary["event_counts"]


def test_error_counts_require_a_known_function_and_false_routes_are_not_observed_edges():
    summary = summarize_execution({"messages": [
        event("function_call_error", function="book"),
        event("route_evaluated", matched=False, from_node="a", target="b"),
        event("route_evaluated", matched=True, from_node="a", target="secret"),
    ]}, node_names=["a", "b"], function_names=["book"])
    assert summary["function_error_counts"] == {"book": 1} and not summary["matched_edges"]
