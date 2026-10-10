"""Source provenance and coverage regressions using an unrelated, renamed API."""

import copy
import json

import pytest

from agent_forge.builder_policy import source_ids, validate_coverage, validate_policy
from agent_forge.input_contract import inspect_inputs


@pytest.fixture
def contract(tmp_path):
    base = tmp_path / "subscription-policy.md"
    amendment = tmp_path / "subscription-amendment.md"
    base.write_text(
        "# Subscription policy\n"
        "1. Use authenticate_member before disclosing account details.\n"
        "2. Call submit_commitment with subscriber_ref, units_due and settlement_day.\n",
        encoding="utf-8",
    )
    amendment.write_text(
        "# Subscription amendment\n"
        "1. Replace subscription-policy rule 2: use a retry budget of 4 attempts.\n",
        encoding="utf-8",
    )
    api_path = tmp_path / "subscription-api.json"
    operations = {}
    for name, fields in {
        "authenticate_member": {"subscriber_ref": {"type": "string"}, "pin_answer": {"type": "string"}},
        "submit_commitment": {
            "subscriber_ref": {"type": "string"}, "units_due": {"type": "number", "minimum": 22.5},
            "settlement_day": {"type": "string"},
        },
    }.items():
        operations[f"/{name}"] = {"post": {
            "operationId": name,
            "requestBody": {"required": True, "content": {"application/json": {"schema": {
                "type": "object", "properties": fields, "required": list(fields), "additionalProperties": False,
            }}}},
            "responses": {"200": {"description": "Accepted"}},
        }}
    api_path.write_text(json.dumps({"openapi": "3.0.3", "info": {"title": "Subscriptions", "version": "1"},
                                    "servers": [{"url": "https://example.invalid/only-a-fixture"}], "paths": operations}),
                        encoding="utf-8")
    return inspect_inputs([base, amendment], api_path)


@pytest.fixture
def policy(contract):
    rules = []
    for document in contract["documents"]:
        for clause in document["clauses"]:
            rules.append({
                "source_id": clause["qualified_id"], "binding": True, "policy": clause["text"],
                "trigger": "customer interaction", "actions": ["Apply this source rule"],
                "exceptions": [], "overrides": [], "tool_names": clause["mentioned_tools"],
            })
    amended = "subscription-amendment:1"
    next(rule for rule in rules if rule["source_id"] == amended)["overrides"] = ["subscription-policy:2"]
    return {
        "title": "Subscription commitments", "rules": rules,
        "parameters": [{"name": "max_commit_attempts", "value_json": "4", "source_ids": [amended],
                        "description": "Changed budget from the explicit amendment"},
                       {"name": "body_fields", "value_json": json.dumps({"identity": "subscriber_ref", "amount": "units_due", "date": "settlement_day"}),
                        "source_ids": ["subscription-policy:2"], "description": "Caller supplied backend field mapping"}],
        "stages": [{"name": "verified_commit", "source_ids": ["subscription-policy:1", "subscription-policy:2"],
                    "allowed_tools": ["submit_commitment"], "entry_gate": "identity passed", "exit_gate": "backend success"}],
        "ambiguities": [],
    }


@pytest.fixture
def workflow():
    return {"initial_node": "identity", "nodes": {"identity": {"node_type": "conversation"},
                                                 "commit": {"node_type": "conversation"}},
            "global_nodes": {"terminal": {"node_type": "end_call"}}}


@pytest.fixture
def generated(contract, workflow):
    return {"workflow_json": json.dumps(workflow),
            "coverage": [{"source_id": identifier, "node_ids": ["identity", "commit"],
                          "mechanism": "Identity gate and source-derived commit budget"}
                         for identifier in sorted(source_ids(contract))],
            "limitations": []}


def test_accepts_source_qualified_amendment_and_renamed_backend_contract(contract, policy):
    original = copy.deepcopy((contract, policy))
    assert {"subscription-policy:1", "subscription-policy:2", "subscription-amendment:1"} <= source_ids(contract)
    assert validate_policy(policy, contract) == []
    operation = contract["tool_contract"]["operations"]["submit_commitment"]
    fields = operation["request_schemas"]["application/json"]["properties"]
    assert set(fields) == {"subscriber_ref", "units_due", "settlement_day"}
    assert json.loads(policy["parameters"][1]["value_json"])["amount"] in fields
    assert fields["units_due"]["minimum"] == 22.5
    assert (contract, policy) == original


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown", "unqualified"])
def test_each_source_requires_exactly_one_qualified_policy_rule(contract, policy, mutation):
    if mutation == "missing":
        policy["rules"].pop()
    elif mutation == "duplicate":
        policy["rules"].append(copy.deepcopy(policy["rules"][0]))
    elif mutation == "unknown":
        policy["rules"][0]["source_id"] = "not-a-source:99"
    else:
        policy["rules"][0]["source_id"] = "1"
    assert validate_policy(policy, contract)


@pytest.mark.parametrize("target", ["rule_tool", "stage_tool", "override", "parameter_source", "stage_source"])
def test_unknown_tools_and_provenance_are_rejected(contract, policy, target):
    if target == "rule_tool":
        policy["rules"][0]["tool_names"] = ["create_promise"]
    elif target == "stage_tool":
        policy["stages"][0]["allowed_tools"] = ["create_promise"]
    elif target == "override":
        policy["rules"][0]["overrides"] = ["foreign-policy:2"]
    elif target == "parameter_source":
        policy["parameters"][0]["source_ids"] = ["foreign-policy:2"]
    else:
        policy["stages"][0]["source_ids"] = ["foreign-policy:2"]
    assert validate_policy(policy, contract)


@pytest.mark.parametrize("location", ["parameter", "stage"])
def test_parameter_and_stage_provenance_cannot_be_empty(contract, policy, location):
    collection = "parameters" if location == "parameter" else "stages"
    policy[collection][0]["source_ids"] = []
    assert validate_policy(policy, contract)


def test_duplicate_parameter_name_is_rejected_even_with_different_source(contract, policy):
    other = copy.deepcopy(policy["parameters"][0])
    other.update(value_json="9", source_ids=["subscription-policy:2"])
    policy["parameters"].append(other)
    assert validate_policy(policy, contract)


@pytest.mark.parametrize("serialized", ["NaN", "Infinity", "-Infinity", '{"budget":NaN}', '[1, Infinity]', '{"budget":', "{unquoted:1}"])
def test_non_json_and_nonfinite_parameter_values_are_rejected(contract, policy, serialized):
    policy["parameters"][0]["value_json"] = serialized
    assert validate_policy(policy, contract)


def test_numeric_overflow_must_not_silently_make_policy_parameter_infinite(contract, policy):
    policy["parameters"][0]["value_json"] = '{"budget":1e400}'
    assert validate_policy(policy, contract), "JSON exponent overflow became infinity without a validation error"


def test_reported_policy_ambiguity_is_a_blocker(contract, policy):
    policy["ambiguities"] = ["The amendment gives two inconsistent retry budgets without precedence."]
    issues = validate_policy(policy, contract)
    assert issues and any("inconsistent retry budgets" in issue for issue in issues)


@pytest.mark.parametrize("corruption", ["missing_required", "unknown_property", "wrong_binding_type"])
def test_invalid_ir_shape_is_rejected_before_semantic_traversal(contract, policy, corruption):
    if corruption == "missing_required":
        del policy["rules"][0]["source_id"]
    elif corruption == "unknown_property":
        policy["rules"][0]["invented_exception"] = True
    else:
        policy["rules"][0]["binding"] = "yes"
    assert validate_policy(policy, contract)


def test_coverage_accepts_existing_local_and_global_nodes_without_mutation(contract, generated, workflow):
    generated["coverage"][0]["node_ids"] = ["terminal"]
    original = copy.deepcopy((generated, workflow))
    assert validate_coverage(generated, contract, workflow) == []
    assert (generated, workflow) == original


@pytest.mark.parametrize("corruption", ["missing_source", "duplicate_source", "unknown_source", "unknown_node", "blank_mechanism", "limitation"])
def test_coverage_rejects_missing_duplicate_or_unsupported_claims(contract, generated, workflow, corruption):
    if corruption == "missing_source":
        generated["coverage"].pop()
    elif corruption == "duplicate_source":
        generated["coverage"].append(copy.deepcopy(generated["coverage"][0]))
    elif corruption == "unknown_source":
        generated["coverage"][0]["source_id"] = "not-a-source:99"
    elif corruption == "unknown_node":
        generated["coverage"][0]["node_ids"] = ["nonexistent"]
    elif corruption == "blank_mechanism":
        generated["coverage"][0]["mechanism"] = " \n\t"
    else:
        generated["limitations"] = ["The corrected-date branch has not been implemented."]
    assert validate_coverage(generated, contract, workflow)


def test_coverage_cannot_claim_implementation_without_any_node(contract, generated, workflow):
    generated["coverage"][0]["node_ids"] = []
    assert validate_coverage(generated, contract, workflow), "An unattached coverage claim was accepted as implemented"
