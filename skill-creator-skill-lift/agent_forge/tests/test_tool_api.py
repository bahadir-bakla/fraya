import copy
import json
from pathlib import Path

import pytest
import yaml

from agent_forge.tool_api import (
    RequestValidationError,
    ToolAPI,
    ToolAPIError,
    load_tool_api,
    parse_openapi,
    validate_json,
)

KIT = Path(__file__).resolve().parents[3] / "competition-v3" / "build-the-builder" / "tools" / "openapi.json"


def document(schema, *, name="record_commitment"):
    return {
        "openapi": "3.0.3",
        "info": {"title": "Renamed collection backend"},
        "servers": [{"url": "https://example.invalid/api/v3/"}],
        "paths": {
            "/commitments": {
                "post": {
                    "operationId": name,
                    "summary": "Record a commitment",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": schema}},
                    },
                    "responses": {"200": {"description": "Recorded"}},
                }
            }
        },
    }


def test_kit_inventory_is_allowlisted_and_preserves_policy_description():
    api = load_tool_api(KIT)
    assert isinstance(api, ToolAPI)
    assert set(api.operations) == {
        "verify_identity", "get_account", "create_promise", "add_note",
        "schedule_callback", "transfer_to_agent", "close_call",
    }
    close = api.operations["close_call"]
    assert close.method == "POST"
    assert close.url == "https://freya-bank-mock.freyavoice.workers.dev/v1/close_call"
    assert close.request_schema["required"] == ["customer_id", "outcome"]
    assert "Required for every outcome except promise and paid" in close.request_schema["properties"]["reason"]["description"]
    # The prose requirement belongs to the brief/policy layer, not this schema.
    assert close.validate_request({"customer_id": "fixture", "outcome": "not_verified"}) == []
    assert api.discover_tools("Outcome codes: promise, paid, transferred, not_verified, refused.") == []
    assert api.discover_tools("CALL close_call after create_promise; close_call_status is metadata.") == ["close_call", "create_promise"]
    assert api.discover_tools("create_promise_status and not_create_promise") == []
    inventory = json.loads(json.dumps(api.to_dict()))
    assert inventory["operations"]["verify_identity"]["request_schemas"]["application/json"]["properties"]["field"]["enum"] == ["date_of_birth", "phone_last4"]
    assert inventory["operations"]["get_account"]["response_schemas"]["200"]["application/json"]["properties"]["products"]["items"]["properties"]["product_id"]["type"] == "string"
    assert inventory["operations"]["verify_identity"]["response_descriptions"]["500"].startswith("The service failed")


def test_kit_requests_have_field_level_errors_and_reject_bool_amount():
    api = load_tool_api(KIT)
    assert api.validate_request("verify_identity", {"customer_id": "fixture", "field": "phone_last4", "answer": "1234"}) == []
    assert any("body.field" in e and "enum" in e for e in api.validate_request("verify_identity", {"customer_id": "fixture", "field": "passport", "answer": "1234"}))
    promise = api.operations["create_promise"]
    body = {"customer_id": "fixture", "product_id": "p1", "amount": 120.5, "date": "2026-10-14"}
    assert promise.validate_request(body) == []
    assert promise.validate_request({**body, "amount": True}) == ["body.amount: expected number"]
    assert any("body.product_id" in e for e in promise.validate_request({k: v for k, v in body.items() if k != "product_id"}))
    with pytest.raises(RequestValidationError) as exc:
        promise.require_valid_request({**body, "amount": "120"})
    assert exc.value.errors == ["body.amount: expected number"]
    with pytest.raises(ToolAPIError, match="Unknown tool"):
        api.validate_request("promise", {})


def test_yaml_load_and_renamed_schema_require_no_bank_field_assumptions(tmp_path):
    source = document({
        "type": "object",
        "required": ["subscriber", "commitment"],
        "additionalProperties": False,
        "properties": {
            "subscriber": {"type": "string", "description": "New identifier, not customer_id"},
            "commitment": {
                "type": "object", "required": ["cents", "channel"],
                "properties": {
                    "cents": {"type": "integer", "minimum": 25, "maximum": 500},
                    "channel": {"type": "string", "enum": ["sms", "voice"], "description": "Permitted channels"},
                },
            },
        },
    }, name="submit_commitment")
    path = tmp_path / "renamed.yaml"
    path.write_text(yaml.safe_dump(source), encoding="utf-8")
    api = load_tool_api(path)
    assert set(api.operations) == {"submit_commitment"}
    assert api.operations["submit_commitment"].url == "https://example.invalid/api/v3/commitments"
    assert api.validate_request("submit_commitment", {"subscriber": "fixture", "commitment": {"cents": 25, "channel": "sms"}}) == []
    errors = api.validate_request("submit_commitment", {"customer_id": "fixture", "commitment": {"cents": 24, "channel": "email"}})
    assert any("body.subscriber" in e for e in errors)
    assert any("body.customer_id" in e and "additional" in e for e in errors)
    assert any("body.commitment.cents" in e and "minimum" in e for e in errors)
    assert any("body.commitment.channel" in e and "enum" in e for e in errors)
    assert api.discover_tools("Use submit_commitment, not sms or voice.") == ["submit_commitment"]
    assert parse_openapi(json.dumps(source)).to_dict() == api.to_dict()


def test_local_refs_resolve_body_response_parameter_and_escaped_pointer():
    source = document({"$ref": "#/components/schemas/Commitment"})
    source["components"] = {
        "schemas": {
            "Amount/Units~": {"type": "integer", "minimum": 10, "description": "Whole units"},
            "Commitment": {
                "type": "object", "required": ["units"],
                "properties": {"units": {"$ref": "#/components/schemas/Amount~1Units~0"}},
            },
            "Receipt": {"type": "object", "properties": {"reference": {"type": "string"}}},
        },
        "requestBodies": {"CommitmentBody": source["paths"]["/commitments"]["post"]["requestBody"]},
        "responses": {"ReceiptResponse": {"description": "Receipt", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Receipt"}}}}},
        "parameters": {"Trace": {"name": "X-Trace", "in": "header", "schema": {"type": "string"}}},
    }
    operation = source["paths"]["/commitments"]["post"]
    operation["requestBody"] = {"$ref": "#/components/requestBodies/CommitmentBody"}
    operation["responses"]["200"] = {"$ref": "#/components/responses/ReceiptResponse"}
    operation["parameters"] = [{"$ref": "#/components/parameters/Trace"}]
    untouched = copy.deepcopy(source)
    api = parse_openapi(source)
    op = api.operations["record_commitment"]
    assert op.request_required
    assert op.request_schema["properties"]["units"] == {"type": "integer", "minimum": 10, "description": "Whole units"}
    assert op.response_schemas["200"]["application/json"]["properties"]["reference"]["type"] == "string"
    assert op.parameters[0]["name"] == "X-Trace"
    assert op.validate_request({"units": 9}) == ["body.units: violates minimum 10"]
    assert source == untouched
    assert "$ref" not in json.dumps(api.to_dict())


@pytest.mark.parametrize("reference,message", [
    ("https://example.invalid/schema.json", "external"),
    ("other.yaml#/Thing", "external"),
    ("#/components/schemas/Missing", "Unresolved"),
    ("#Anchor", "anchor"),
])
def test_invalid_refs_fail_without_external_resolution(reference, message):
    with pytest.raises(ToolAPIError, match=message):
        parse_openapi(document({"$ref": reference}))


def test_recursive_ref_fails_with_a_cycle_error():
    source = document({"$ref": "#/components/schemas/A"})
    source["components"] = {"schemas": {
        "A": {"type": "object", "properties": {"next": {"$ref": "#/components/schemas/B"}}},
        "B": {"$ref": "#/components/schemas/A"},
    }}
    with pytest.raises(ToolAPIError, match="Cyclic local"):
        parse_openapi(source)


def test_repeated_nonrecursive_ref_is_allowed_and_does_not_alias():
    source = document({"type": "object", "properties": {
        "first": {"$ref": "#/components/schemas/Id"},
        "second": {"$ref": "#/components/schemas/Id", "description": "Second ID"},
    }})
    source["components"] = {"schemas": {"Id": {"type": "string", "enum": ["a", "b"], "description": "First ID"}}}
    api = parse_openapi(source)
    properties = api.operations["record_commitment"].request_schema["properties"]
    assert properties["second"]["description"] == "Second ID"
    properties["first"]["enum"].append("c")
    assert properties["second"]["enum"] == ["a", "b"]


def test_ref_siblings_do_not_weaken_numeric_constraints():
    source = document({"$ref": "#/components/schemas/Bound", "minimum": 0})
    source["components"] = {"schemas": {"Bound": {"type": "number", "minimum": 10}}}
    op = parse_openapi(source).operations["record_commitment"]
    assert op.validate_request(5)
    assert op.validate_request(10) == []


@pytest.mark.parametrize("explicit", [False, True])
def test_ambiguous_duplicate_tool_names_fail(explicit):
    source = document({"type": "object"}, name="same")
    if not explicit:
        source["paths"]["/commitments"]["post"].pop("operationId")
    second = copy.deepcopy(source["paths"]["/commitments"]["post"])
    source["paths"]["/other/commitments"] = {"post": second}
    with pytest.raises(ToolAPIError, match="Duplicate tool name"):
        parse_openapi(source)


def test_methods_override_servers_and_preserve_parameters():
    source = document({"type": "object"})
    source["servers"] = [{"url": "https://{region}.example.invalid/root", "variables": {"region": {"default": "eu"}}}]
    item = source["paths"]["/commitments"]
    item["parameters"] = [{"name": "trace", "in": "query", "schema": {"type": "string"}}]
    item["get"] = {"operationId": "read_commitments", "servers": [{"url": "/alternate"}], "responses": {}}
    api = parse_openapi(source)
    assert api.operations["record_commitment"].url == "https://eu.example.invalid/root/commitments"
    assert api.operations["read_commitments"].url == "/alternate/commitments"
    assert api.operations["read_commitments"].method == "GET"
    assert api.operations["read_commitments"].parameters[0]["in"] == "query"
    assert api.operations["read_commitments"].validate_request() == []
    assert api.operations["read_commitments"].validate_request({}) == ["body: operation declares no request body"]


@pytest.mark.parametrize("kind,value", [
    ("integer", True), ("number", False), ("boolean", 1),
    ("string", 2), ("object", []), ("array", {}),
])
def test_json_types_are_not_coerced(kind, value):
    assert validate_json({"type": kind}, value) == [f"$: expected {kind}"]


def test_nested_arrays_bounds_items_additional_properties_and_enum():
    schema = {
        "type": "array", "minItems": 1, "maxItems": 2, "uniqueItems": True,
        "items": {
            "type": "object", "required": ["value"],
            "properties": {"value": {"type": "number", "minimum": 1, "exclusiveMaximum": 3}},
            "additionalProperties": {"type": "string", "enum": ["accepted"]},
        },
    }
    assert validate_json(schema, [{"value": 1, "state": "accepted"}]) == []
    assert validate_json(schema, []) == ["$: violates minItems 1"]
    errors = validate_json(schema, [{"value": 3, "state": "rejected"}, {}])
    assert "$[0].value: violates exclusiveMaximum 3" in errors
    assert any("$[0].state" in e for e in errors)
    assert "$[1].value: required field is missing" in errors
    assert any("unique" in e for e in validate_json(schema, [{"value": 1}, {"value": 1}]))
    assert any("maxItems" in e for e in validate_json(schema, [{"value": 1}, {"value": 2}, {"value": 1.5}]))


def test_nullable_composition_enum_and_nonfinite_json():
    assert validate_json({"type": "number", "nullable": True}, None) == []
    assert validate_json({"type": ["string", "null"]}, None) == []
    assert validate_json({"enum": [1]}, True)
    assert validate_json({"enum": [{"x": 1}]}, {"x": True})
    assert validate_json({"enum": [1]}, 1.0) == []
    assert validate_json({"type": "number"}, float("nan"))
    assert validate_json({"type": "number", "minimum": 1, "exclusiveMinimum": True}, 1)
    assert validate_json({"oneOf": [{"type": "integer"}, {"type": "number"}]}, 1)
    assert validate_json({"anyOf": [{"type": "string"}, {"type": "integer"}]}, "id") == []


def test_missing_body_is_distinct_from_nullable_json_null():
    op = parse_openapi(document({"type": "string", "nullable": True})).operations["record_commitment"]
    assert op.validate_request() == ["body: request body is required"]
    assert op.validate_request(None) == []


def test_media_schema_selection_keeps_all_response_schemas():
    source = document({"type": "object"})
    op = source["paths"]["/commitments"]["post"]
    op["requestBody"]["content"]["application/vendor+json"] = {"schema": {"type": "string"}}
    op["responses"]["200"]["content"] = {
        "application/json": {"schema": {"type": "object"}},
        "text/plain": {"schema": {"type": "string"}},
    }
    operation = parse_openapi(source).operations["record_commitment"]
    assert operation.validate_request({}) == []
    assert operation.validate_request("receipt", content_type="application/vendor+json") == []
    assert operation.validate_request({}, content_type="text/xml")
    assert set(operation.response_schemas["200"]) == {"application/json", "text/plain"}


def test_errors_are_clear_for_invalid_documents_and_remote_load():
    for source in ({}, {"swagger": "2.0", "paths": {}}, "[]", "paths: ["):
        with pytest.raises(ToolAPIError):
            parse_openapi(source)
    with pytest.raises(ToolAPIError, match="local file"):
        load_tool_api("https://example.invalid/openapi.yaml")
