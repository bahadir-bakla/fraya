"""Offline behavior checks for compact IR expansion against changing ToolAPI."""

from copy import deepcopy
import json

import httpx
import pytest

from agent_forge.builder_live import compare_saved
from agent_forge.freya_compiler import compile_workflow
from agent_forge.freya_lint import lint_workflow
from agent_forge.tool_api import parse_openapi


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Compiler tests must not make HTTP requests")
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)


def request_schema():
    return {
        "type": "object", "additionalProperties": False,
        "required": ["subscriber", "units", "channel", "details"],
        "properties": {
            "subscriber": {"type": "string"},
            "units": {"type": "integer", "minimum": 1},
            "channel": {"type": "string", "enum": ["voice", "sms"]},
            "details": {
                "type": "object", "additionalProperties": False,
                "required": ["confirmed", "allocations"],
                "properties": {
                    "confirmed": {"type": "boolean"},
                    "allocations": {"type": "array", "minItems": 1, "items": {
                        "type": "object", "additionalProperties": False,
                        "required": ["product", "amount"],
                        "properties": {"product": {"type": "string", "enum": ["loan", "card"]},
                                       "amount": {"type": "number", "minimum": 0}},
                    }},
                },
            },
        },
    }


def document(schema=None, *, server="https://fixture.invalid/api/v1", method="post", path="/commitments"):
    return {
        "openapi": "3.0.3", "info": {"title": "Synthetic compiler API", "version": "1"},
        "servers": [{"url": server}],
        "paths": {path: {method: {
            "operationId": "record_commitment", "summary": "Record a synthetic commitment",
            "requestBody": {"required": True, "content": {"application/json": {
                "schema": deepcopy(request_schema() if schema is None else schema)}}},
            "responses": {"200": {"description": "Recorded"}},
        }}},
    }


def end_node():
    return {"name": "done", "node_type": "end_call", "transitions": [], "terminal": {
        "type": "function", "function": {"name": "finish", "handler": "__function__:end_call",
            "parameters": {"type": "object", "properties": {}}}}}


def graph(tool):
    return {"initial_node": "ask", "nodes": {
        "ask": {"name": "ask", "node_type": "conversation", "task_message": "Ask for confirmation.",
                "tools": [deepcopy(tool)], "transitions": [
                    {"target_node": "done", "condition": {"operator": "always"}}]},
        "done": end_node(),
    }, "global_nodes": {}}


def compact(spec=None):
    workflow = graph({"_tool_ref": "record"})
    workflow["_tool_library"] = {"record": deepcopy(spec if spec is not None else {"operation": "record_commitment"})}
    return workflow


def tool_of(workflow):
    return workflow["nodes"]["ask"]["tools"][0]


def body_of(workflow):
    return tool_of(workflow)["function"]["parameters"]["properties"]["body"]


def input_body_contract(body):
    """Compare the complete API schema excluding compiler-added binding defaults."""
    body = deepcopy(body)
    for field in body["properties"].values():
        if str(field.get("default", "")).startswith("{{forge_arg_"):
            field.pop("default")
    return body


def test_compact_routing_aliases_bind_actual_operation_without_rewriting_payload_data():
    workflow = compact({"operation": "record_commitment", "defaults": {"subscriber": "record_response.data.ok"}})
    workflow["nodes"]["ask"]["transitions"][0]["condition"] = {
        "logic": "or", "conditions": [{"variable": "record_response.data.ok", "operator": "equals", "operand": "true"}]}
    before = deepcopy(workflow)
    result = compile_workflow(workflow, parse_openapi(document()))
    check = result["nodes"]["ask"]["transitions"][0]["condition"]["conditions"][0]
    assert check["variable"] == "record_commitment_response.data.ok"
    assert body_of(result)["properties"]["subscriber"]["default"] == "record_response.data.ok"
    assert workflow == before


def test_trusted_guard_builtin_compiles_to_baked_code_and_retains_blocked_fallback():
    from agent_forge.guarded_freya_adapter import guard_node, guarded_builtin_snippets, validate_guard_wiring
    workflow = compact()
    workflow["nodes"]["gate"] = guard_node("gate", "ask", "done")
    workflow["initial_node"] = "gate"
    parameter = workflow["nodes"]["gate"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]
    parameter["default"] = "@builtin:guarded_dispatch"
    result = compile_workflow(workflow, parse_openapi(document()))
    baked = result["nodes"]["gate"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    assert baked == guarded_builtin_snippets()["guarded_dispatch"]
    assert validate_guard_wiring(result) == []
    assert result["nodes"]["gate"]["passthrough_default_transition"] == "done"


def test_chat_entry_profile_preserves_fixed_source_line_and_ordinary_voice_entry():
    workflow = compact()
    entry = {"type": "tts", "text": "Hello {{title}} {{last_name}}. This call is recorded."}
    workflow["nodes"]["ask"]["on_enter"] = deepcopy(entry)
    workflow["nodes"]["ask"]["on_enter_first_entry_only"] = True
    api = parse_openapi(document())
    original = compile_workflow(workflow, api)
    lowered = compile_workflow(workflow, api, chat_mode=True)
    assert original["nodes"]["ask"]["on_enter"] == entry
    assert lowered["nodes"]["ask"]["on_enter"]["type"] == "llm"
    assert lowered["nodes"]["ask"]["on_enter"]["prompt"].endswith(entry["text"])
    assert lowered["nodes"]["ask"]["on_enter_first_entry_only"] is True
    assert workflow["nodes"]["ask"]["on_enter"] == entry


def test_model_body_fields_have_distinct_unbound_defaults_without_baking_extraction_values():
    workflow = compact({"operation": "record_commitment", "defaults": {"subscriber": "{{customer_id}}"}})
    body = body_of(compile_workflow(workflow, parse_openapi(document())))
    assert body["properties"]["subscriber"]["default"] == "{{customer_id}}"
    values = [field["default"] for name, field in body["properties"].items() if name != "subscriber"]
    assert len(values) == len(set(values))
    assert all(value.startswith("{{forge_arg_") and value.endswith("}}") for value in values)
    assert body["properties"]["units"]["type"] == "integer"
    assert body["properties"]["channel"]["enum"] == ["voice", "sms"]
    assert body["required"] == ["subscriber", "units", "channel", "details"]


def test_api_changes_drive_url_method_names_types_required_enums_and_nested_fields():
    original = request_schema()
    changed = deepcopy(original)
    changed["properties"].pop("subscriber")
    changed["properties"]["account_key"] = {"type": "integer", "minimum": 100}
    changed["properties"]["units"] = {"type": "string", "enum": ["one", "two"]}
    changed["properties"]["channel"]["enum"] = ["app", "branch"]
    changed["required"] = ["account_key", "units", "channel", "details"]
    details = changed["properties"]["details"]
    details["properties"].pop("confirmed")
    details["properties"]["approved"] = {"type": "string", "enum": ["yes", "no"]}
    details["required"] = ["approved", "allocations"]
    allocation = details["properties"]["allocations"]["items"]
    allocation["properties"]["amount"] = {"type": "integer", "minimum": 1}
    allocation["properties"]["product"]["enum"] = ["mortgage", "overdraft"]
    allocation["properties"]["due_day"] = {"type": "string"}
    allocation["required"].append("due_day")

    before = compile_workflow(compact(), parse_openapi(document(original)))
    after = compile_workflow(compact(), parse_openapi(document(
        changed, server="https://changed.invalid/v9", method="patch", path="/scheduled-promises")))

    assert input_body_contract(body_of(before)) == original
    assert input_body_contract(body_of(after)) == changed
    params = tool_of(after)["function"]["parameters"]["properties"]
    assert params["url"]["default"] == "https://changed.invalid/v9/scheduled-promises"
    assert params["method"]["default"] == "PATCH"
    assert "subscriber" not in params["body"]["properties"]
    assert params["body"]["properties"]["units"]["type"] == "string"
    assert allocation["required"] == ["product", "amount", "due_day"]


def test_local_schema_references_are_resolved_in_the_expanded_body():
    source = document({"$ref": "#/components/schemas/Commitment"})
    source["components"] = {"schemas": {"Commitment": request_schema()}}
    output = compile_workflow(compact(), parse_openapi(source))
    assert input_body_contract(body_of(output)) == request_schema()
    assert "$ref" not in json.dumps(body_of(output))


def test_defaults_descriptions_hooks_and_mappings_survive_compilation_and_lint():
    details = {"confirmed": True, "allocations": [{"product": "loan", "amount": 125.5}]}
    spec = {"operation": "record_commitment", "description": "Record only the confirmed proposal",
            "defaults": {"subscriber": "{{customer_id}}", "channel": "voice", "details": details},
            "descriptions": {"units": "Freshly confirmed number of installments"},
            "pre_process_code": "@code:pre", "post_process_code": "@code:post",
            "response_mapping": [{"path": "data.receipt", "variable": "recorded_receipt"}],
            "config": {"maxRetries": 0}}
    workflow = compact(spec)
    workflow["_code_library"] = {"pre": "freya.set('request_checked', True)",
                                 "post": "freya.set('response_checked', True)"}
    api = parse_openapi(document())
    output = compile_workflow(workflow, api)
    tool = tool_of(output)
    body = body_of(output)
    assert body["properties"]["subscriber"]["default"] == "{{customer_id}}"
    assert body["properties"]["details"]["default"] == details
    assert body["properties"]["units"]["description"] == spec["descriptions"]["units"]
    assert body["properties"]["channel"]["enum"] == ["voice", "sms"]
    assert body["required"] == request_schema()["required"]
    assert tool["pre_process_code"] == workflow["_code_library"]["pre"]
    assert tool["post_process_code"] == workflow["_code_library"]["post"]
    assert tool["response_mapping"] == spec["response_mapping"]
    assert tool["function"]["description"] == spec["description"]
    assert not [issue for issue in lint_workflow(output, api) if issue["severity"] == "error"]


@pytest.mark.parametrize("defaults", [
    {"obsolete_field": 1}, {"channel": "fax"}, {"units": "two"}, {"units": 1.5},
    {"units": True}, {"units": 0},
    {"details": {"confirmed": True, "allocations": [{"product": "unknown", "amount": 1}]}},
    {"details": {"confirmed": True, "allocations": [{"product": "loan", "amount": -1}]}},
    {"details": {"confirmed": True, "allocations": [{"product": "loan"}]}},
    {"details": {"confirmed": "yes", "allocations": [{"product": "loan", "amount": 1}]}},
    {"details": {"confirmed": True, "allocations": [], "extra": "undeclared"}},
], ids=["unknown-field", "outside-enum", "wrong-type", "fractional-integer", "boolean-integer",
        "below-minimum", "nested-enum", "nested-minimum", "nested-required", "nested-type", "nested-extra"])
def test_invalid_static_defaults_rejected_without_mutating_ir_or_api(defaults):
    api = parse_openapi(document())
    workflow = compact({"operation": "record_commitment", "defaults": defaults})
    before, api_before = deepcopy(workflow), api.to_dict()
    with pytest.raises(ValueError):
        compile_workflow(workflow, api)
    assert workflow == before and api.to_dict() == api_before


def test_old_default_is_rejected_when_api_enum_changes():
    workflow = compact({"operation": "record_commitment", "defaults": {"channel": "voice"}})
    assert body_of(compile_workflow(workflow, parse_openapi(document())))["properties"]["channel"]["default"] == "voice"
    changed = request_schema()
    changed["properties"]["channel"]["enum"] = ["app", "branch"]
    with pytest.raises(ValueError):
        compile_workflow(workflow, parse_openapi(document(changed)))


def test_all_graph_action_positions_and_code_defaults_expand_without_private_keys():
    workflow = compact()
    workflow["_code_library"] = {"prepare": "freya.set('prepared', True)"}
    workflow["initial_node"] = "prepare"
    workflow["nodes"]["prepare"] = {
        "name": "prepare", "node_type": "code", "passthrough": True,
        "passthrough_default_transition": "ask", "transitions": [
            {"target_node": "ask", "condition": {"operator": "always"}}],
        "pre_actions": [{"type": "function", "function": {
            "name": "prepare", "handler": "__function__:code_exec", "parameters": {
                "type": "object", "properties": {"code": {"type": "string", "default": "@code:prepare"}}}}}],
    }
    workflow["nodes"]["record"] = {"name": "record", "node_type": "api_request",
        "pre_actions": [{"_bank_tool": {"operation": "record_commitment"}}],
        "transitions": [{"target_node": "done", "condition": {"operator": "always"}}]}
    workflow["global_nodes"]["interrupt"] = {"name": "interrupt", "node_type": "conversation",
        "tools": [{"_tool_ref": "record"}], "condition": {"operator": "always"}}
    workflow["tools"] = [{"_tool_ref": "record"}]
    original = deepcopy(workflow)
    api = parse_openapi(document())
    api_before = api.to_dict()

    result = compile_workflow(workflow, api)

    assert "_tool_library" not in result and "_code_library" not in result
    assert "_tool_ref" not in json.dumps(result) and "_bank_tool" not in json.dumps(result)
    assert "@code:" not in json.dumps(result)
    code = result["nodes"]["prepare"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    assert code == "freya.set('prepared', True)"
    tools = [tool_of(result), result["nodes"]["record"]["pre_actions"][0],
             result["global_nodes"]["interrupt"]["tools"][0], result["tools"][0]]
    assert all(tool["function"]["name"] == "record_commitment" for tool in tools)
    assert all(tool["function"]["handler"] == "__function__:api_call" for tool in tools)
    assert workflow == original and api.to_dict() == api_before
    tools[0]["function"]["parameters"]["properties"]["body"]["properties"]["channel"]["enum"].append("mutated")
    assert all("mutated" not in tool["function"]["parameters"]["properties"]["body"]["properties"]["channel"]["enum"]
               for tool in tools[1:])
    assert workflow == original and api.to_dict() == api_before


def test_existing_plain_workflow_is_unchanged_including_literal_code_prefixes():
    tool = {"type": "function", "config": {"maxRetries": 0}, "function": {
        "name": "record_commitment", "handler": "__function__:api_call", "parameters": {
            "type": "object", "properties": {
                "url": {"type": "string", "default": "https://fixture.invalid/api/v1/commitments"},
                "method": {"type": "string", "default": "POST"}, "body": request_schema()}}}}
    workflow = graph(tool)
    workflow["nodes"]["ask"]["task_message"] = "@code:this-is-spoken-text"
    workflow["metadata"] = {"_tool_ref": "this-is-metadata", "note": "@code:literal"}
    original = deepcopy(workflow)
    result = compile_workflow(workflow, parse_openapi(document()))
    assert result == original and workflow == original
    result["nodes"]["ask"]["task_message"] = "Changed output"
    assert workflow == original


@pytest.mark.parametrize("location", ["top-level", "nested-schema", "nested-data-tools", "nested-data-pre_actions"])
def test_literal_api_tool_ref_fields_are_not_macro_instructions(location):
    literal = {"_tool_ref": "literal-customer-data"}
    schema = {"type": "object", "properties": {}, "additionalProperties": False, "required": []}
    defaults = {}
    if location == "top-level":
        schema["properties"]["_tool_ref"] = {"type": "string"}
        schema["required"] = ["_tool_ref"]
        defaults["_tool_ref"] = "literal-customer-data"
    elif location == "nested-schema":
        schema["properties"]["payload"] = {"type": "object", "properties": {
            "_tool_ref": {"type": "string"}}, "required": ["_tool_ref"], "additionalProperties": False}
        defaults["payload"] = literal
    else:
        # API data may legitimately contain a list named tools/pre_actions;
        # these are not graph action arrays. Opaque objects remain ordinary JSON.
        data_field = location.removeprefix("nested-data-")
        schema["properties"]["payload"] = {"type": "object", "properties": {
            data_field: {"type": "array", "items": {"type": "object", "additionalProperties": True}}},
            "required": [data_field], "additionalProperties": False}
        defaults["payload"] = {data_field: [literal]}
    workflow = compact({"operation": "record_commitment", "defaults": defaults})
    original = deepcopy(workflow)
    result = compile_workflow(workflow, parse_openapi(document(schema)))
    body = body_of(result)
    assert body["required"] == schema["required"]
    for name, value in defaults.items():
        assert body["properties"][name]["default"] == value
    assert workflow == original


@pytest.mark.parametrize("location", ["body-code-field", "nested-hook-field"])
def test_literal_api_data_code_prefix_is_not_executable_code_reference(location):
    literal = "@code:customer-code"
    if location == "body-code-field":
        schema = {"type": "object", "properties": {
            "code": {"type": "string", "enum": [literal]}}, "required": ["code"]}
        defaults = {"code": literal}
    else:
        schema = {"type": "object", "properties": {"payload": {
            "type": "object", "properties": {"post_process_code": {"type": "string"}},
            "required": ["post_process_code"]}}, "required": ["payload"]}
        defaults = {"payload": {"post_process_code": literal}}
    workflow = compact({"operation": "record_commitment", "defaults": defaults})
    # A matching library name makes erroneous interpretation silently rewrite
    # request data, rather than merely throwing an unknown-reference error.
    workflow["_code_library"] = {"customer-code": "freya.set('not_customer_data', True)"}
    original = deepcopy(workflow)
    output = compile_workflow(workflow, parse_openapi(document(schema)))
    for name, value in defaults.items():
        assert body_of(output)["properties"][name]["default"] == value
    assert workflow == original


@pytest.mark.parametrize("kind", ["missing-tool", "missing-code", "tool-extra-fields", "cyclic-tool-aliases"])
def test_unknown_or_untrusted_macro_references_fail_with_bounded_errors(kind):
    workflow = compact()
    if kind == "missing-tool":
        workflow["nodes"]["ask"]["tools"][0] = {"_tool_ref": "missing"}
    elif kind == "missing-code":
        workflow["_tool_library"]["record"]["post_process_code"] = "@code:missing"
    elif kind == "tool-extra-fields":
        workflow["nodes"]["ask"]["tools"][0]["config"] = {"maxRetries": 0}
    else:
        # References inside library definitions are unsupported, even if cyclic.
        workflow["_tool_library"] = {"record": {"_tool_ref": "other"}, "other": {"_tool_ref": "record"}}
    original = deepcopy(workflow)
    with pytest.raises(ValueError):
        compile_workflow(workflow, parse_openapi(document()))
    assert workflow == original


@pytest.mark.parametrize("kind", ["self-schema", "mutual-schema", "cyclic-workflow", "deep-workflow"])
def test_untrusted_reference_or_container_cycles_do_not_recurse_without_bound(kind):
    if kind in {"self-schema", "mutual-schema"}:
        source = document({"$ref": "#/components/schemas/A"})
        target = "A" if kind == "self-schema" else "B"
        source["components"] = {"schemas": {"A": {"$ref": f"#/components/schemas/{target}"},
                                               "B": {"$ref": "#/components/schemas/A"}}}
        with pytest.raises(ValueError):
            compile_workflow(compact(), parse_openapi(source))
    else:
        workflow = graph({"type": "function"})
        if kind == "cyclic-workflow":
            workflow["metadata"] = workflow
        else:
            value = "leaf"
            for _ in range(180):
                value = {"child": value}
            workflow["metadata"] = value
        with pytest.raises(ValueError):
            compile_workflow(workflow, parse_openapi(document()))


@pytest.mark.parametrize("field", ["url", "method", "required", "enum", "hook"])
def test_expanded_semantics_survive_serialization_and_are_checked_on_readback(field):
    workflow = compact({"operation": "record_commitment", "post_process_code": "freya.set('saved', True)"})
    compiled = compile_workflow(workflow, parse_openapi(document()))
    saved = json.loads(json.dumps(compiled))
    saved["nodePositions"] = {"ask": {"x": 10, "y": 20}}
    saved["agent_config"] = {"llmConfig": {"provider": "experimental-5", "model": "experimental-5"}}
    assert compare_saved(compiled, saved) == []
    tool = tool_of(saved)
    properties = tool["function"]["parameters"]["properties"]
    if field in {"url", "method"}:
        properties[field]["default"] = "changed"
    elif field == "required":
        properties["body"]["required"].remove("units")
    elif field == "enum":
        properties["body"]["properties"]["channel"]["enum"].remove("sms")
    else:
        del tool["post_process_code"]
    issues = compare_saved(compiled, saved)
    assert issues and any("$.nodes.ask.tools[0]" in issue for issue in issues)
