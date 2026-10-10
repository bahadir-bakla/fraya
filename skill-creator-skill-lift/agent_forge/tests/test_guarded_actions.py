"""Offline event/dispatch regressions and execution of the actual emitted code."""

import ast
import builtins
import copy
import json

import pytest

from agent_forge.guarded_actions import (
    action_envelope, guard_command, guard_dispatch, lower_guard_snippet, new_state, reduce_event,
)


@pytest.fixture
def policy():
    request_schema = {
        "type": "object", "additionalProperties": False,
        "required": ["person_ref", "asset_ref", "units", "settles_on"],
        "properties": {"person_ref": {"type": "string"}, "asset_ref": {"type": "string"},
                       "units": {"type": "number"}, "settles_on": {"type": "string", "format": "date"}},
    }
    return {
        "version": "subscription-rules-v7", "source_policy_parameters": {"document": "subscription-policy:2", "budget": 3},
        "calendar": {"now": "2031-04-02T11:15", "holidays": ["2031-04-04"],
                     "weekmask": [0, 1, 2, 3, 4], "week_start": 0},
        "products": [{"product_id": p, "deadline": "2031-04-10", "minimum": "22.50", "maximum": "90.00",
                      "quantum": "0.50", "max_write_attempts": 3} for p in ("z-first", "a-last")],
        "capabilities": {
            "save_terms": {"effect": "promise", "request_schema": request_schema,
                           "product_field": "asset_ref", "amount_field": "units", "date_field": "settles_on",
                           "requires_confirmation": True, "required_facts": {"security_step": "passed"},
                           "request_bindings": {"person_ref": "party_ref"}},
            "append_outcome": {
                "effect": "write", "product_field": "asset_ref", "amount_field": None, "date_field": None,
                "requires_confirmation": False,
                "required_facts": {"terminal_kind": "stay", "input_gate": "closed"}, "request_bindings": {},
                "request_schema": {"type": "object", "additionalProperties": False, "required": ["asset_ref", "why"],
                                   "properties": {"asset_ref": {"type": "string"}, "why": {"type": "string", "enum": ["unaffordable"]}}},
            },
        },
    }


def state_for(policy):
    return new_state(policy, facts={"party_ref": "synthetic-party", "security_step": "passed"})


def apply(policy, state, kind, **details):
    event = dict(kind=kind, **details)
    if kind != "result":
        event.setdefault("revision", state["call_revision"] + (kind != "readback"))
    return reduce_event(policy, state, event)


def consent(policy, *, products=("z-first",), amount="30.00", day="2031-04-03"):
    state = state_for(policy)
    for p in products:
        result = apply(policy, state, "propose", product_id=p, amount=amount, date=day)
        assert result["flag"] == "accepted", result["violations"]
        state = result["state"]
    result = apply(policy, state, "readback", delivered=True)
    assert result["flag"] == "accepted"
    state = result["state"]
    result = apply(policy, state, "confirm", accepted=True, readback_revision=state["call_revision"])
    assert result["flag"] == "accepted", result["violations"]
    return result["state"]


def envelope(policy, state, *, product="z-first", amount="30.0", day="2031-04-03", person="synthetic-party"):
    # Keep the amount as a JSON numeric lexeme, not a binary float.
    body = '{"person_ref":' + json.dumps(person) + ',"asset_ref":' + json.dumps(product)
    body += ',"units":' + amount + ',"settles_on":' + json.dumps(day) + '}'
    return action_envelope(policy, state, "save_terms", body)


def assert_blocked(result, code):
    assert result["flag"] == "blocked" and result["request_json"] == ""
    assert code in [v["code"] for v in result["violations"]]
    assert all(set(v) == {"code", "path", "details"} for v in result["violations"])


def run_snippet(snippet, variables):
    def only_documented_modules(name, *args, **kwargs):
        assert name in {"json", "re", "datetime"}, name
        return builtins.__import__(name, *args, **kwargs)
    sandbox_builtins = {**vars(builtins), "__import__": only_documented_modules}
    exec(compile(snippet, "<actual-freya-guard>", "exec"), {"vars": variables, "__builtins__": sandbox_builtins})
    return variables


def test_json_roundtrip_retains_identity_revision_consent_and_dispatch_receipt(policy):
    original_policy = copy.deepcopy(policy)
    state = json.loads(json.dumps(consent(policy)))
    action = json.loads(json.dumps(envelope(policy, state)))
    assert state["products"]["z-first"]["recorded"] is None
    dispatched = guard_dispatch(policy, state, action)
    assert dispatched["flag"] == "allowed" and dispatched["request_json"] == action["request_json"]
    pending = json.loads(json.dumps(dispatched["state"]))
    assert pending["products"]["z-first"]["recorded"] is None
    result = apply(policy, pending, "result", action_id=action["action_id"], status="succeeded", receipt_id="receipt-1")
    assert result["flag"] == "accepted"
    recorded = result["state"]["products"]["z-first"]["recorded"]
    assert recorded["receipt_id"] == "receipt-1" and recorded["terms"]["amount"] == "30.0"
    assert state["pending"] is None and policy == original_policy


@pytest.mark.parametrize("amount,day,code", [
    ("1", "2031-04-03", "amount_below_floor"),
    ("30", "2031-04-04", "non_business_day"),
    ("30", "2031-04-30", "date_after_deadline"),
    ("NaN", "2031-04-03", "invalid_money"),
    ("30", "invalid", "invalid_date"),
])
def test_invalid_new_user_correction_revokes_all_consent_before_validation(policy, amount, day, code):
    state = consent(policy, products=("z-first", "a-last"))
    prior_action = envelope(policy, state)
    result = apply(policy, state, "correction", product_id="a-last", amount=amount, date=day)
    assert_blocked(result, code)
    changed = result["state"]
    assert changed["call_revision"] == state["call_revision"] + 1
    assert changed["readback"] is None
    assert all(p["confirmed"] is None and p["confirmation_revision"] is None for p in changed["products"].values())
    assert changed["products"]["a-last"]["proposed"] is None
    assert_blocked(guard_dispatch(policy, changed, prior_action), "stale_action_revision")
    assert_blocked(guard_dispatch(policy, changed, envelope(policy, changed)), "current_confirmation_required")


def test_replayed_correction_and_stale_confirmation_cannot_advance_or_restore_consent(policy):
    state = consent(policy)
    correction = dict(kind="correction", revision=state["call_revision"] + 1,
                      product_id="z-first", amount="40", date="2031-04-03")
    corrected = reduce_event(policy, state, correction)["state"]
    assert_blocked(reduce_event(policy, corrected, correction), "stale_event_revision")
    failed = apply(policy, corrected, "confirm", accepted=True, readback_revision=state["call_revision"])
    assert_blocked(failed, "stale_readback")
    assert failed["state"]["products"]["z-first"]["confirmed"] is None


def test_mixed_assent_and_correction_event_cannot_silently_confirm_old_terms(policy):
    state = state_for(policy)
    state = apply(policy, state, "propose", product_id="z-first", amount="30", date="2031-04-03")["state"]
    state = apply(policy, state, "readback", delivered=True)["state"]
    result = apply(policy, state, "confirm", accepted=True, readback_revision=state["call_revision"],
                   product_id="z-first", amount="40", date="2031-04-03")
    assert_blocked(result, "unexpected_event_field")
    assert result["state"]["call_revision"] == state["call_revision"] + 1
    assert result["state"]["products"]["z-first"]["confirmed"] is None
    assert_blocked(guard_dispatch(policy, result["state"], envelope(policy, result["state"])), "current_confirmation_required")


@pytest.mark.parametrize("accepted", ["yes", 1, None])
def test_confirmation_needs_explicit_boolean_and_actual_current_readback(policy, accepted):
    state = state_for(policy)
    state = apply(policy, state, "propose", product_id="z-first", amount="30", date="2031-04-03")["state"]
    assert_blocked(apply(policy, state, "readback", delivered=False), "readback_evidence_required")
    result = apply(policy, state, "confirm", accepted=accepted, readback_revision=state["call_revision"])
    assert_blocked(result, "explicit_confirmation_required")


@pytest.mark.parametrize("field,value,code", [
    ("policy_version", "older-policy", "policy_version_mismatch"),
    ("call_revision", 0, "stale_action_revision"),
    ("action_id", 99, "stale_action_id"),
    ("confirmation_revision", 0, "current_confirmation_required"),
    ("product_id", "a-last", "action_product_mismatch"),
    ("capability", "create_promise", "capability_not_allowed"),
])
def test_envelope_tampering_is_rejected_without_reserving_a_write(policy, field, value, code):
    state = consent(policy)
    action = envelope(policy, state)
    action[field] = value
    result = guard_dispatch(policy, state, action)
    assert_blocked(result, code)
    assert result["state"]["pending"] is None and result["state"]["products"]["z-first"]["attempts"] == 0


@pytest.mark.parametrize("change,code", [
    ("identity", "required_fact_missing"), ("party", "request_binding_mismatch"),
    ("amount", "request_terms_mismatch"), ("extra", "request_extra_field"),
    ("old_fields", "request_field_missing"), ("duplicate", "duplicate_json_field"),
])
def test_identity_bound_arguments_confirmed_terms_and_schema_are_all_required(policy, change, code):
    state = consent(policy)
    action = envelope(policy, state)
    if change == "identity":
        state["facts"]["security_step"] = "failed"
    elif change == "party":
        action = envelope(policy, state, person="different-party")
    elif change == "amount":
        action = envelope(policy, state, amount="40")
    elif change == "extra":
        body = json.loads(action["request_json"])
        body["backend_ok"] = True
        action["request_json"] = json.dumps(body)
    elif change == "old_fields":
        action["request_json"] = '{"customer_id":"old","amount":30,"date":"2031-04-03"}'
    else:
        action["request_json"] = action["request_json"].replace('"units":30.0', '"units":30.0,"units":40')
    assert_blocked(guard_dispatch(policy, state, action), code)


def test_backend_order_and_confirmed_remainder_survive_partial_commit(policy):
    state = consent(policy, products=("z-first", "a-last"))
    assert_blocked(guard_dispatch(policy, state, envelope(policy, state, product="a-last")), "backend_order_violation")
    action = envelope(policy, state)
    pending = guard_dispatch(policy, state, action)["state"]
    state = apply(policy, pending, "result", action_id=action["action_id"], status="succeeded", receipt_id="first-write")["state"]
    assert state["products"]["a-last"]["confirmation_revision"] == state["call_revision"]
    next_action = envelope(policy, state, product="a-last")
    assert guard_dispatch(policy, state, next_action)["flag"] == "allowed"
    immutable = apply(policy, state, "correction", product_id="z-first", amount="40", date="2031-04-03")
    assert_blocked(immutable, "recorded_promise_immutable")
    assert immutable["state"]["products"]["z-first"]["recorded"]["receipt_id"] == "first-write"


def test_unknown_write_timeout_blocks_blind_retry_and_recorded_success_claims(policy):
    state = consent(policy)
    action = envelope(policy, state)
    pending = guard_dispatch(policy, state, action)["state"]
    unknown = apply(policy, pending, "result", action_id=action["action_id"], status="unknown")["state"]
    assert unknown["pending"]["status"] == "unknown" and unknown["products"]["z-first"]["recorded"] is None
    assert_blocked(guard_dispatch(policy, unknown, envelope(policy, unknown)), "backend_action_pending")
    assert_blocked(apply(policy, unknown, "result", action_id=999, status="succeeded", receipt_id="unrelated"), "unexpected_backend_result")
    assert_blocked(apply(policy, unknown, "result", action_id=action["action_id"], status="succeeded"), "backend_receipt_required")
    resolved = apply(policy, unknown, "result", action_id=action["action_id"], status="succeeded", receipt_id="reconciled-receipt")
    assert resolved["state"]["pending"] is None
    assert resolved["state"]["products"]["z-first"]["recorded"]["receipt_id"] == "reconciled-receipt"
    assert_blocked(apply(policy, resolved["state"], "result", action_id=action["action_id"], status="succeeded", receipt_id="replay"), "unexpected_backend_result")


def test_correction_during_pending_write_invalidates_consent_but_does_not_fabricate_cancellation(policy):
    state = consent(policy)
    action = envelope(policy, state)
    pending = guard_dispatch(policy, state, action)["state"]
    corrected = apply(policy, pending, "correction", product_id="z-first", amount="40", date="2031-04-03")
    assert_blocked(corrected, "backend_action_pending")
    changed = corrected["state"]
    assert changed["call_revision"] == state["call_revision"] + 1 and changed["products"]["z-first"]["confirmed"] is None
    result = apply(policy, changed, "result", action_id=action["action_id"], status="succeeded", receipt_id="real-earlier-write")
    assert result["state"]["products"]["z-first"]["recorded"]["terms"]["amount"] == "30.0"


def test_changed_retry_budget_counts_only_reserved_attempts_and_definite_no_write_allows_retry(policy):
    policy["products"][0]["max_write_attempts"] = 4
    state = consent(policy)
    for index in range(4):
        action = envelope(policy, state)
        dispatched = guard_dispatch(policy, state, action)
        assert dispatched["flag"] == "allowed"
        state = apply(policy, dispatched["state"], "result", action_id=action["action_id"], status="no_write")["state"]
        assert state["products"]["z-first"]["attempts"] == index + 1
    assert_blocked(guard_dispatch(policy, state, envelope(policy, state)), "retry_budget_exhausted")


def test_changed_calendar_floor_and_numeric_lexemes_are_exact(policy):
    policy["calendar"]["weekmask"] = [6, 0, 1, 2, 3]
    policy["calendar"]["week_start"] = 6
    policy["calendar"]["holidays"] = ["2031-04-03"]
    policy["products"][0].update(minimum="0.001", maximum="99999999999999999999999999.999", quantum="0.001")
    value = "12345678901234567890123456.789"
    state = consent(policy, amount=value, day="2031-04-06")
    action = envelope(policy, state, amount=value, day="2031-04-06")
    assert guard_dispatch(policy, state, action)["request_json"] == action["request_json"]
    invalid = apply(policy, state, "correction", product_id="z-first", amount="0.0009", date="2031-04-06")
    assert_blocked(invalid, "amount_below_floor")
    holiday = apply(policy, state, "correction", product_id="z-first", amount="0.001", date="2031-04-03")
    assert_blocked(holiday, "non_business_day")


def test_conditional_capability_needs_trusted_cutoff_and_terminal_facts(policy):
    state = state_for(policy)
    body = '{"asset_ref":"z-first","why":"unaffordable"}'
    action = action_envelope(policy, state, "append_outcome", body)
    assert_blocked(guard_dispatch(policy, state, action), "required_fact_missing")
    state["facts"].update(terminal_kind="stay", input_gate="closed")
    assert guard_dispatch(policy, state, action)["flag"] == "allowed"
    state["facts"]["terminal_kind"] = "handover"
    assert_blocked(guard_dispatch(policy, state, action), "required_fact_missing")


def test_unsupported_schema_features_fail_closed_instead_of_claiming_validation(policy):
    state = consent(policy)
    action = envelope(policy, state)
    policy["capabilities"]["save_terms"]["request_schema"]["oneOf"] = []
    assert_blocked(guard_dispatch(policy, state, action), "unsupported_schema_keyword")


def test_actual_lowered_snippet_reserves_action_and_returns_only_documented_imports(policy):
    state = consent(policy)
    command = dict(kind="dispatch", envelope=envelope(policy, state))
    code = lower_guard_snippet()
    assert "{{" not in code and "}}" not in code
    tree = ast.parse(code)
    assert {node.names[0].name for node in ast.walk(tree) if isinstance(node, ast.Import)} == {"json", "re", "datetime"}
    variables = dict(guard_policy_json=json.dumps(policy), guard_state_json=json.dumps(state), guard_command_json=json.dumps(command))
    run_snippet(code, variables)
    assert variables["guard_flag"] == "allowed"
    assert variables["guard_request_json"] == command["envelope"]["request_json"]
    assert json.loads(variables["guard_state_json"]) == guard_command(policy, state, command)["state"]
    assert json.loads(variables["guard_state_json"])["products"]["z-first"]["recorded"] is None


def test_actual_snippet_persists_rejected_correction_and_resets_stale_dispatch_vars(policy):
    state = consent(policy)
    action = envelope(policy, state)
    event = dict(kind="correction", revision=state["call_revision"] + 1, product_id="z-first", amount="1", date="2031-04-03")
    variables = dict(guard_policy_json=policy, guard_state_json=state, guard_command_json=dict(kind="event", event=event),
                     guard_flag="allowed", guard_request_json=action["request_json"])
    code = lower_guard_snippet()
    run_snippet(code, variables)
    assert variables["guard_flag"] == "blocked" and variables["guard_request_json"] == ""
    changed = json.loads(variables["guard_state_json"])
    assert changed["call_revision"] == event["revision"] and changed["products"]["z-first"]["confirmed"] is None
    variables["guard_command_json"] = dict(kind="dispatch", envelope=action)
    run_snippet(code, variables)
    assert variables["guard_flag"] == "blocked" and variables["guard_request_json"] == ""


def test_actual_snippet_unknown_timeout_persists_pending_and_blocks_another_dispatch(policy):
    state = consent(policy)
    action = envelope(policy, state)
    variables = dict(guard_policy_json=json.dumps(policy), guard_state_json=json.dumps(state),
                     guard_command_json=json.dumps(dict(kind="dispatch", envelope=action)))
    code = lower_guard_snippet()
    run_snippet(code, variables)
    variables["guard_command_json"] = json.dumps(dict(kind="event", event=dict(kind="result", action_id=action["action_id"], status="unknown")))
    run_snippet(code, variables)
    assert variables["guard_flag"] == "accepted" and variables["guard_request_json"] == ""
    state = json.loads(variables["guard_state_json"])
    assert state["pending"]["status"] == "unknown" and state["products"]["z-first"]["recorded"] is None
    variables["guard_command_json"] = json.dumps(dict(kind="dispatch", envelope=envelope(policy, state)))
    run_snippet(code, variables)
    assert variables["guard_flag"] == "blocked" and variables["guard_request_json"] == ""


@pytest.mark.parametrize("fault", ["missing", "malformed", "unsupported"])
def test_actual_snippet_always_writes_blocked_string_and_machine_readable_errors(policy, fault):
    state = consent(policy)
    variables = dict(guard_policy_json=json.dumps(policy), guard_state_json=json.dumps(state),
                     guard_command_json=json.dumps(dict(kind="dispatch", envelope=envelope(policy, state))),
                     guard_flag="allowed", guard_request_json="stale-request")
    if fault == "missing":
        del variables["guard_policy_json"]
    elif fault == "malformed":
        variables["guard_command_json"] = "{broken"
    else:
        variables["guard_command_json"] = json.dumps(dict(kind="invented"))
    run_snippet(lower_guard_snippet(), variables)
    assert variables["guard_flag"] == "blocked" and variables["guard_request_json"] == ""
    assert all(set(v) == {"code", "path", "details"} for v in json.loads(variables["guard_violations_json"]))


def test_snippet_output_names_are_configurable_and_cannot_collide(policy):
    state = consent(policy)
    code = lower_guard_snippet(policy_var="p", state_var="s", command_var="c", flag_var="gate", violations_var="errors", request_var="body")
    variables = dict(p=json.dumps(policy), s=json.dumps(state), c=json.dumps(dict(kind="dispatch", envelope=envelope(policy, state))))
    run_snippet(code, variables)
    assert variables["gate"] == "allowed" and variables["body"]
    with pytest.raises(ValueError):
        lower_guard_snippet(flag_var="guard_state_json")
