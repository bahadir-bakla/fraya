"""Offline tests against official graph examples and supplied OpenAPI contracts."""

import copy
import json
import re
from pathlib import Path

import pytest

from agent_forge.freya_lint import assert_valid_workflow, lint_workflow
from agent_forge.tool_api import load_tool_api, parse_openapi

KIT = Path(__file__).resolve().parents[3] / "competition-v3" / "build-the-builder"


def api_document(schema, *, name="submit_commitment", method="post", path="/commitments"):
    return {
        "openapi": "3.0.3",
        "info": {"title": "Fixture API"},
        "servers": [{"url": "https://example.invalid/api/v3"}],
        "paths": {path: {method: {
            "operationId": name,
            "requestBody": {"required": True, "content": {"application/json": {"schema": schema}}},
            "responses": {"200": {"description": "Recorded"}},
        }}},
    }


def commitment_schema():
    return {
        "type": "object", "required": ["subscriber", "units", "channel"],
        "additionalProperties": False,
        "properties": {
            "subscriber": {"type": "string"},
            "units": {"type": "integer", "minimum": 1},
            "channel": {"type": "string", "enum": ["voice", "sms"]},
        },
    }


@pytest.fixture
def api():
    return parse_openapi(api_document(commitment_schema()))


def api_tool(api):
    operation = next(iter(api.operations.values()))
    return {
        "type": "function", "config": {"maxRetries": 0},
        "function": {
            "name": operation.name, "handler": "__function__:api_call",
            "parameters": {"type": "object", "properties": {
                "url": {"type": "string", "default": operation.url},
                "method": {"type": "string", "default": operation.method},
                "body": copy.deepcopy(operation.request_schema),
            }},
        },
        "response_mapping": [{"path": "data.receipt", "variable": "receipt"}],
    }


def end_node():
    return {
        "name": "done", "node_type": "end_call", "transitions": [],
        "terminal": {"type": "function", "function": {
            "name": "finished", "handler": "__function__:end_call",
            "parameters": {"type": "object", "properties": {}},
        }},
    }


def transition(target="done", condition=None):
    return {"target_node": target, "condition": condition or {"operator": "always"}}


def workflow(tool=None):
    node = {"name": "ask", "node_type": "conversation", "transitions": [transition()]}
    if tool is not None:
        node["tools"] = [tool]
    return {"initial_node": "ask", "nodes": {"ask": node, "done": end_node()}, "global_nodes": {}}


def with_code(source):
    result = workflow()
    result["initial_node"] = "prepare"
    result["nodes"]["prepare"] = {
        "name": "prepare", "node_type": "code", "passthrough": True,
        "passthrough_default_transition": "ask", "on_enter": {"type": "silent"},
        "transitions": [transition("ask")],
        "pre_actions": [{"type": "function", "function": {
            "name": "prepare_vars", "handler": "__function__:code_exec",
            "parameters": {"type": "object", "properties": {
                "code": {"type": "string", "default": source},
            }},
        }}],
    }
    return result


def errors(wf, api):
    return [i for i in lint_workflow(wf, api) if i["severity"] == "error"]


def messages(issues):
    return "\n".join(i["message"] for i in issues)


def body(wf):
    return wf["nodes"]["ask"]["tools"][0]["function"]["parameters"]["properties"]["body"]


def test_public_contract_is_pure_and_assertion_contains_paths(api):
    wf = workflow(api_tool(api))
    original = copy.deepcopy(wf)
    assert lint_workflow(wf, api) == []
    assert assert_valid_workflow(wf, api) is None
    assert wf == original
    wf["nodes"]["ask"]["transitions"][0]["target_node"] = "missing"
    issues = lint_workflow(wf, api)
    assert all(set(i) == {"severity", "path", "message"} for i in issues)
    assert all(i["severity"] in {"error", "warning"} and i["path"].startswith("$") for i in issues)
    with pytest.raises(ValueError, match=r"\$\.nodes\.ask\.transitions\[0\]\.target_node"):
        assert_valid_workflow(wf, api)


def test_complete_official_clinic_example_is_valid_with_matching_contract():
    source = (KIT / "docs" / "workflow-format.md").read_text(encoding="utf-8")
    example = source.split("## Complete example", 1)[1]
    wf = json.loads(re.search(r"```json\s*(.*?)\s*```", example, re.S).group(1))
    doc = {"openapi": "3.0.3", "info": {"title": "Official clinic example"},
           "servers": [{"url": "https://api.example.com/v1"}], "paths": {}}
    for node in wf["nodes"].values():
        for tool in node.get("tools", []) + node.get("pre_actions", []):
            fn = tool["function"]
            props = fn["parameters"]["properties"]
            schema = copy.deepcopy(props["body"])
            # The contract requires baked fields too; they are not model arguments.
            schema["required"] = list(schema["properties"])
            doc["paths"][props["url"]["default"].removeprefix("https://api.example.com/v1")] = {
                "post": {"operationId": fn["name"], "requestBody": {
                    "required": True, "content": {"application/json": {"schema": schema}},
                }, "responses": {}},
            }
    api = parse_openapi(doc)
    assert errors(wf, api) == []
    assert_valid_workflow(wf, api)


def test_official_bank_contract_and_changed_fields_do_not_use_bank_constants():
    bank = load_tool_api(KIT / "tools" / "openapi.json")
    tool = api_tool(bank)
    assert tool["function"]["name"] == "verify_identity"
    assert errors(workflow(tool), bank) == []
    changed = parse_openapi(api_document({
        "type": "object", "required": ["member", "appointment"], "additionalProperties": False,
        "properties": {
            "member": {"type": "string"},
            "appointment": {"type": "object", "required": ["minutes", "mode"], "properties": {
                "minutes": {"type": "number"}, "mode": {"type": "string", "enum": ["video", "office"]},
            }},
        },
    }, name="reserve_visit", method="put", path="/reservations"))
    wf = workflow(api_tool(changed))
    assert lint_workflow(wf, changed) == []
    body(wf)["properties"]["appointment"]["properties"]["mode"]["enum"] = ["voice"]
    assert "OpenAPI mismatch" in messages(errors(wf, changed))
    assert "office" in messages(errors(wf, changed))


def test_resolved_refs_and_allof_body_properties_are_checked_without_false_extra_fields():
    doc = api_document({"allOf": [
        {"$ref": "#/components/schemas/Member"},
        {"type": "object", "required": ["channel"], "properties": {
            "channel": {"type": "string", "enum": ["video", "office"]},
        }},
    ]})
    doc["components"] = {"schemas": {"Member": {
        "type": "object", "required": ["member"], "properties": {"member": {"type": "string"}},
    }}}
    api = parse_openapi(doc)
    tool = api_tool(api)
    tool["function"]["parameters"]["properties"]["body"] = {
        "type": "object", "required": ["member", "channel"], "properties": {
            "member": {"type": "string"}, "channel": {"type": "string", "enum": ["video", "office"]},
        },
    }
    wf = workflow(tool)
    assert errors(wf, api) == []
    body(wf)["properties"]["channel"]["enum"] = ["voice"]
    assert "outside enum" in messages(errors(wf, api))


@pytest.mark.parametrize("keyword", ["anyOf", "oneOf"])
def test_openapi_request_alternatives_validate_declared_type_and_enum(keyword):
    api = parse_openapi(api_document({"type": "object", "required": ["identifier"], "properties": {
        "identifier": {keyword: [{"type": "integer"}, {"type": "string", "enum": ["legacy"]}]},
    }}))
    tool = api_tool(api)
    tool["function"]["parameters"]["properties"]["body"]["properties"]["identifier"] = {"type": "string", "enum": ["legacy"]}
    wf = workflow(tool)
    assert errors(wf, api) == []
    body(wf)["properties"]["identifier"]["enum"] = ["invented"]
    assert "alternative" in messages(errors(wf, api))


def test_nested_array_schema_validates_item_enum_and_literal_types():
    api = parse_openapi(api_document({"type": "object", "required": ["records"], "properties": {
        "records": {"type": "array", "items": {"type": "object", "required": ["mode"], "properties": {
            "mode": {"type": "string", "enum": ["video", "office"]},
        }}},
    }}))
    wf = workflow(api_tool(api))
    assert errors(wf, api) == []
    body(wf)["properties"]["records"]["items"]["properties"]["mode"]["enum"] = ["voice"]
    assert "outside enum" in messages(errors(wf, api))
    wf = workflow(api_tool(api))
    body(wf)["properties"]["records"]["default"] = [{"mode": True}]
    assert "expected string" in messages(errors(wf, api))


@pytest.mark.parametrize("field,value", [
    ("nodes", []), ("nodes", {}), ("global_nodes", []), ("initial_node", "absent"),
    ("initial_node", "__previous__"), ("initial_node", 0),
])
def test_bad_graph_container_or_initial_node(api, field, value):
    wf = workflow()
    wf[field] = value
    assert any(i["path"] == "$." + field for i in errors(wf, api))


@pytest.mark.parametrize("target", ["missing", "__previous__", [], 4, ""])
def test_regular_transition_targets_must_exist(api, target):
    wf = workflow()
    wf["nodes"]["ask"]["transitions"][0]["target_node"] = target
    assert any(i["path"].endswith("target_node") for i in errors(wf, api))


def test_global_previous_return_and_implicit_conversation_type_are_valid(api):
    wf = workflow()
    wf["global_nodes"]["redirect"] = {
        "name": "redirect", "condition": {"operator": "matches_intent", "description": "Off topic"},
        "passthrough": True, "passthrough_default_transition": "__previous__",
        "excluded_nodes": ["done"], "transitions": [transition("__previous__")],
    }
    assert errors(wf, api) == []
    wf["initial_node"] = "redirect"
    assert any(i["path"] == "$.initial_node" for i in errors(wf, api))
    wf["initial_node"] = "ask"
    wf["global_nodes"]["redirect"]["excluded_nodes"] = ["missing"]
    assert any("excluded_nodes" in i["path"] for i in errors(wf, api))
    wf["global_nodes"]["ask"] = wf["global_nodes"].pop("redirect")
    assert "distinct" in messages(errors(wf, api))


def test_top_level_or_nested_and_and_all_documented_operators(api):
    wf = workflow()
    binary = ["equals", "not_equals", "contains", "greater_than", "less_than"]
    condition = {"logic": "or", "conditions": [{"logic": "and", "conditions": [
        *[{"operator": op, "variable": "value", "operand": 2} for op in binary],
        {"operator": "is_set", "variable": "known"},
        {"operator": "is_not_set", "variable": "unknown"},
    ]}]}
    wf["nodes"]["ask"]["transitions"][0]["condition"] = condition
    assert errors(wf, api) == []
    condition["logic"] = "and"
    assert "Top-level" in messages(errors(wf, api))


@pytest.mark.parametrize("condition,fragment", [
    ({"operator": "contains_any", "variable": "x", "operand": "a"}, "Unsupported"),
    ({"operator": "equals", "variable": "x"}, "operand"),
    ({"operator": "is_set"}, "variable"),
    ({"operator": "matches_intent"}, "description"),
    ({"operator": "greater_than", "variable": "x", "operand": "never"}, "numeric"),
    ({"logic": "or", "conditions": []}, "nonempty"),
    ({"logic": [], "conditions": [{"operator": "always"}]}, "Top-level"),
    ({"logic": "or", "conditions": [{"logic": "xor", "conditions": [{"operator": "always"}]}]}, "Nested"),
    ({"logic": "or", "conditions": [{"operator": "always"}], "operator": "always"}, "mix"),
])
def test_invalid_condition_shapes(api, condition, fragment):
    wf = workflow()
    wf["nodes"]["ask"]["transitions"][0]["condition"] = condition
    assert fragment in messages(errors(wf, api))


def test_duplicate_target_merge_warns_but_does_not_block(api):
    wf = workflow()
    wf["nodes"]["ask"]["transitions"].insert(0, transition(condition={"operator": "is_set", "variable": "ready"}))
    issues = lint_workflow(wf, api)
    assert not errors(wf, api)
    assert any(i["severity"] == "warning" and "merged" in i["message"] and "unconditional" in i["message"] for i in issues)
    assert_valid_workflow(wf, api)


@pytest.mark.parametrize("change", ["remove_fallback", "conditional_last", "tool_call_last", "remove_default", "bad_default"])
def test_passthrough_requires_real_always_fallback_and_default_target(api, change):
    wf = with_code("vars['ready'] = 'yes'")
    node = wf["nodes"]["prepare"]
    if change == "remove_fallback":
        node["transitions"] = []
    elif change == "conditional_last":
        node["transitions"][0]["condition"] = {"operator": "is_set", "variable": "ready"}
    elif change == "tool_call_last":
        node["transitions"][0]["is_tool_call"] = True
    elif change == "remove_default":
        del node["passthrough_default_transition"]
    else:
        node["passthrough_default_transition"] = "missing"
    assert errors(wf, api)


@pytest.mark.parametrize("field,value,path", [
    ("metadata", {"a": [{"b": None}]}, "$.metadata.a[0].b"),
    ("test_variables", {"now": None}, "$.test_variables.now"),
    ("system_prompt", None, "$.system_prompt"),
])
def test_null_is_forbidden_at_every_depth(api, field, value, path):
    wf = workflow()
    wf[field] = value
    assert any(i["path"] == path and "Null" in i["message"] for i in errors(wf, api))


def test_non_json_data_is_reported_and_null_mapping_is_not_crash(api):
    wf = workflow(api_tool(api))
    wf["test_variables"] = {"x": float("nan"), "bad": object()}
    wf["nodes"]["ask"]["tools"][0]["response_mapping"] = None
    assert len(errors(wf, api)) >= 4


def test_cyclic_dicts_are_reported_without_recursing_into_graph_checks(api):
    wf = workflow()
    condition = {"logic": "or", "conditions": []}
    condition["conditions"].append(condition)
    wf["nodes"]["ask"]["transitions"][0]["condition"] = condition
    assert "Cyclic containers" in messages(errors(wf, api))


def test_tools_on_action_nodes_and_preactions_on_conversation_are_errors(api):
    wf = workflow(api_tool(api))
    node = wf["nodes"]["ask"]
    node["pre_actions"] = node["tools"]
    assert "$.nodes.ask.pre_actions" in {i["path"] for i in errors(wf, api)}
    del node["pre_actions"]
    node["node_type"] = "api_request"
    assert "$.nodes.ask.tools" in {i["path"] for i in errors(wf, api)}


def test_mapping_placement_envelope_and_hook_placement(api):
    wf = workflow(api_tool(api))
    tool = wf["nodes"]["ask"]["tools"][0]
    tool["response_mapping"][0]["path"] = "receipt"
    assert "data." in messages(errors(wf, api))
    tool["response_mapping"][0]["path"] = "data.receipt"
    node = wf["nodes"]["ask"]
    node["node_type"] = "api_request"
    node["pre_actions"] = node.pop("tools")
    assert "node; mappings" in messages(errors(wf, api))
    node["response_mapping"] = tool.pop("response_mapping")
    assert errors(wf, api) == []
    tool["function"]["pre_process_code"] = "vars['x'] = 1"
    assert "next to function" in messages(errors(wf, api))


@pytest.mark.parametrize("handler", ["api_call", "__function__:transfer_call", "__function__:integration", None, {}])
def test_only_three_explicit_handlers_are_allowed(api, handler):
    wf = workflow(api_tool(api))
    wf["nodes"]["ask"]["tools"][0]["function"]["handler"] = handler
    assert "Unsupported handler" in messages(errors(wf, api))


@pytest.mark.parametrize("change,fragment", [
    ("unknown_name", "allowlisted"), ("wrong_url", "exact supplied"), ("wrong_method", "exact supplied"),
    ("const_url", "const does not bake"), ("body_template", "body.default-only"),
    ("misplaced_field", "body.properties"), ("missing_body", "requires a request body"),
])
def test_api_operation_binding_and_parameter_placement(api, change, fragment):
    wf = workflow(api_tool(api))
    fn = wf["nodes"]["ask"]["tools"][0]["function"]
    props = fn["parameters"]["properties"]
    if change == "unknown_name":
        fn["name"] = "promise"
    elif change == "wrong_url":
        props["url"]["default"] += "/invented"
    elif change == "wrong_method":
        props["method"]["default"] = "GET"
    elif change == "const_url":
        props["url"]["const"] = props["url"].pop("default")
    elif change == "body_template":
        props["body"] = {"type": "object", "default": {"subscriber": "s", "units": 4, "channel": "voice"}}
    elif change == "misplaced_field":
        props["units"] = props["body"]["properties"].pop("units")
    else:
        del props["body"]
    assert fragment in messages(errors(wf, api))


@pytest.mark.parametrize("change,fragment", [
    ("missing_field", "Required OpenAPI request field"), ("missing_required", "must be required"),
    ("wrong_type", "type must match"), ("missing_enum", "must declare the OpenAPI enum"),
    ("wrong_enum", "outside enum"), ("wrong_default", "outside enum"),
    ("bad_numeric_default", "minimum"), ("extra_field", "not declared"),
])
def test_body_schema_required_type_enum_and_defaults_come_from_input(api, change, fragment):
    wf = workflow(api_tool(api))
    schema = body(wf)
    props = schema["properties"]
    if change == "missing_field":
        del props["subscriber"]
    elif change == "missing_required":
        schema["required"].remove("units")
    elif change == "wrong_type":
        props["units"]["type"] = "string"
    elif change == "missing_enum":
        del props["channel"]["enum"]
    elif change == "wrong_enum":
        props["channel"]["enum"].append("email")
    elif change == "wrong_default":
        props["channel"]["default"] = "email"
    elif change == "bad_numeric_default":
        props["units"]["default"] = 0
    else:
        props["customer_id"] = {"type": "string"}
    assert fragment in messages(errors(wf, api))


def test_baked_required_values_and_dynamic_defaults_are_distinguished(api):
    wf = workflow(api_tool(api))
    schema = body(wf)
    schema["required"].remove("subscriber")
    schema["properties"]["subscriber"]["default"] = "literal"
    assert lint_workflow(wf, api) == []
    schema["properties"]["subscriber"]["default"] = "{{subscriber}}"
    assert errors(wf, api) == []
    assert "unresolved variable" in messages(lint_workflow(wf, api))


@pytest.mark.parametrize("source", [
    "import os\nvars['x'] = os.listdir('.')",
    "from pathlib import Path\nvars['x'] = Path('secret').read_text()",
    "import urllib.request as client\nclient.urlopen('https://example.invalid')",
    "import requests\nrequests.get('https://example.invalid')",
    "open('secret').read()", "read = open\nread('secret')", "eval('1 + 2')",
    "exec('vars[\"x\"] = 1')", "compile('1', 'x', 'eval')", "__import__('os')",
    "getattr(vars, '__class__')", "vars.__class__.__mro__", "vars()",
    "import json\njson.load(vars['handle'])", "from json import dump\ndump({}, vars['handle'])",
])
def test_code_and_hooks_forbid_io_imports_execution_and_reflection(api, source):
    assert errors(with_code(source), api)
    wf = workflow(api_tool(api))
    wf["nodes"]["ask"]["tools"][0]["post_process_code"] = source
    assert errors(wf, api)


@pytest.mark.parametrize("source", [
    "import datetime\nvars['today'] = datetime.date.today()",
    "import datetime as dt\nvars['today'] = dt.datetime.now()",
    "from datetime import datetime as Clock\nvars['today'] = Clock.utcnow()",
    "from datetime import date\nClock = date\nvars['today'] = Clock.today()",
    "import datetime\nclock = datetime.datetime.now\nvars['today'] = clock()",
    "import datetime\nClock, Delta = datetime.datetime, datetime.timedelta\nvars['today'] = Clock.now()",
    "from datetime import datetime\nx = datetime.fromisoformat(vars['now'])\nx.now()",
])
def test_holiday_calculation_cannot_read_machine_clock_in_code_or_hooks(api, source):
    wf = with_code(source)
    assert "Machine-clock" in messages(errors(wf, api))
    wf = workflow(api_tool(api))
    wf["nodes"]["ask"]["tools"][0]["pre_process_code"] = source
    assert "Machine-clock" in messages(errors(wf, api))


def test_holiday_calculation_uses_supplied_clock_and_unrelated_now_is_not_flagged(api):
    source = """import json
import re
import datetime as dt
try:
    now = dt.datetime.fromisoformat(str(vars.get('now') or ''))
    holidays = json.loads(str(vars.get('holidays_json') or '[]'))
    weekday = now.date().weekday()
    vars['holiday_state'] = 'holiday' if now.date().isoformat() in holidays else 'ordinary'
    vars['digits'] = re.sub(r'[^0-9]', '', str(vars.get('answer') or ''))
except Exception:
    vars['holiday_state'] = 'unknown'
"""
    wf = with_code(source)
    wf["test_variables"] = {"now": "2026-10-10T12:00", "holidays_json": "[]"}
    assert lint_workflow(wf, api) == []
    wf = with_code("now = vars.get('now')\nvars['now_copy'] = now\nvars['value'] = params.now\nvars['v'] = config.get('now')")
    assert lint_workflow(wf, api) == []
    wf = with_code("import datetime as clock\ndef f(clock):\n    return clock.now\nvars['value'] = f(params)")
    assert lint_workflow(wf, api) == []
    wf = with_code("import datetime\nf = lambda datetime: datetime.now\nvars['value'] = f(params)")
    assert lint_workflow(wf, api) == []
    wf = with_code("import datetime\ndatetime = params\nvars['value'] = datetime.now")
    assert lint_workflow(wf, api) == []


@pytest.mark.parametrize("source", ["vars['x'] = '{{now}}'", "vars['x'] = '}}'", "vars['x'] = {'a': {'b': 1}}"])
def test_placeholder_delimiters_are_errors_even_inside_valid_python(api, source):
    assert "cannot contain" in messages(errors(with_code(source), api))


def test_bad_python_syntax_and_non_api_hooks_are_reported(api):
    assert "Invalid Python syntax" in messages(errors(with_code("if :"), api))
    assert "Invalid Python syntax" in messages(errors(with_code("return 'cannot return outside a function'"), api))
    wf = with_code("vars['x'] = 'ready'")
    wf["nodes"]["prepare"]["pre_actions"][0]["post_process_code"] = "vars['x'] = 'ready'"
    assert "honoured only" in messages(errors(wf, api))


@pytest.mark.parametrize("source", [
    "def f(x: eval('1 + 1')):\n    return x",
    "x: exec('pass') = 1",
    "import datetime\ndef f() -> datetime.datetime.now():\n    return 'x'",
])
def test_executable_annotations_are_checked_by_ast(api, source):
    assert errors(with_code(source), api)


def test_unverified_deterministic_import_warns_and_write_retry_has_reason(api):
    wf = with_code("import decimal\nvars['x'] = str(decimal.Decimal('1.0'))")
    assert errors(wf, api) == []
    assert "not verified" in messages(lint_workflow(wf, api))
    wf = workflow(api_tool(api))
    wf["nodes"]["ask"]["tools"][0]["config"]["maxRetries"] = 2
    assert errors(wf, api) == []
    assert "duplicate a write" in messages(lint_workflow(wf, api))
    assert_valid_workflow(wf, api)
    read_api = parse_openapi(api_document(commitment_schema(), method="get"))
    wf = workflow(api_tool(read_api))
    wf["nodes"]["ask"]["tools"][0]["config"]["maxRetries"] = 2
    assert lint_workflow(wf, read_api) == []


def test_lifecycle_tool_timing_and_terminal_shape(api):
    wf = workflow()
    wf["tools"] = [api_tool(api)]
    assert "never run" in messages(errors(wf, api))
    wf["tools"][0]["config"]["alwaysRunsAt"] = ["end_of_call"]
    assert errors(wf, api) == []
    wf["tools"][0]["config"]["alwaysRunsAt"] = ["each_turn"]
    assert "each_turn" in messages(errors(wf, api))
    del wf["nodes"]["done"]["terminal"]
    assert "terminal function" in messages(errors(wf, api))


def test_pre_hook_cannot_redirect_verified_endpoint_and_body_rewrite_warns(api):
    wf = workflow(api_tool(api))
    tool = wf["nodes"]["ask"]["tools"][0]
    tool["pre_process_code"] = "config['url'] = 'https://example.invalid/other'"
    assert "cannot rewrite" in messages(errors(wf, api))
    tool["pre_process_code"] = "config['body'] = vars.get('request')"
    assert errors(wf, api) == []
    assert "final runtime body" in messages(lint_workflow(wf, api))


@pytest.mark.parametrize("source", [
    "config.update({'url': 'https://example.invalid/other'})",
    "config.update(method='DELETE')", "config.update(vars.get('request'))",
    "request = config\nrequest['method'] = 'DELETE'",
    "request = config\nrequest.update({'url': 'https://example.invalid/other'})",
    "config.clear()", "config.pop('url')", "config |= vars.get('request')",
])
def test_pre_hook_endpoint_mutations_through_methods_and_aliases_are_errors(api, source):
    wf = workflow(api_tool(api))
    wf["nodes"]["ask"]["tools"][0]["pre_process_code"] = source
    assert "cannot rewrite" in messages(errors(wf, api))


def test_pre_hook_unrelated_clock_fields_and_safe_normalization_remain_valid(api):
    wf = workflow(api_tool(api))
    tool = wf["nodes"]["ask"]["tools"][0]
    tool["pre_process_code"] = "vars['now'] = str(vars.get('now') or '')\nvars['next'] = config.now\nconfig['url_timeout'] = 10"
    assert errors(wf, api) == []
    tool["pre_process_code"] = "request = config\npayload = request['body']\npayload['units'] = vars.get('units')"
    assert errors(wf, api) == []
    assert "final runtime body" in messages(lint_workflow(wf, api))


def test_policy_keywords_are_not_a_substitute_for_source_criticism(api):
    wf = workflow(api_tool(api))
    wf["system_prompt"] = "Policy examples: holiday, paid, promise, refusal, verify identity, never call."
    wf["nodes"]["ask"]["task_message"] = "No prose keyword is a machine-checkable graph/schema rule."
    assert lint_workflow(wf, api) == []


def test_snippets_are_never_executed_even_when_the_source_is_valid(api, tmp_path):
    marker = tmp_path / "not_created.txt"
    wf = with_code(f"open({str(marker)!r}, 'w').write('should never execute')")
    assert errors(wf, api)
    assert not marker.exists()
    # A runtime exception in valid syntax is not raised by the static checker.
    assert lint_workflow(with_code("raise RuntimeError('AST only')"), api) == []


def response_condition(variable):
    return {"logic": "or", "conditions": [{"variable": variable, "operator": "is_set"}]}


def test_tool_library_alias_is_not_an_actual_response_namespace():
    api = parse_openapi(api_document(commitment_schema(), name="verify_identity"))
    wf = workflow(api_tool(api))  # Expanded graph: function.name is the operation, not its IR ref.
    wf["nodes"]["ask"]["transitions"][0]["condition"] = response_condition("identity_check_response.data.all_verified")
    original = copy.deepcopy(wf)
    issues = errors(wf, api)
    assert len(issues) == 1
    assert issues[0]["path"] == "$.nodes.ask.transitions[0].condition.conditions[0].variable"
    assert "Unbound automatic result" in issues[0]["message"]
    assert "identity_check" in issues[0]["message"]
    with pytest.raises(ValueError, match="Unbound automatic result"):
        assert_valid_workflow(wf, api)
    assert wf == original
    wf["nodes"]["ask"]["transitions"][0]["condition"] = response_condition("verify_identity_response.data.all_verified")
    assert errors(wf, api) == []


@pytest.mark.parametrize("name", ["submit_commitment", "verify_identity_with_many_parts", "audit_response"])
def test_response_name_uses_entire_actual_function_name_including_underscores(name):
    api = parse_openapi(api_document(commitment_schema(), name=name))
    wf = workflow(api_tool(api))
    wf["nodes"]["ask"]["transitions"][0]["condition"] = response_condition(name + "_response.data.ok")
    assert errors(wf, api) == []


@pytest.mark.parametrize("variable", ["missing_response", "missing_response.data.ok", "submit_commitment__response.data.ok"])
def test_unknown_or_malformed_response_namespace_is_an_error(api, variable):
    wf = workflow(api_tool(api))
    wf["nodes"]["ask"]["transitions"][0]["condition"] = response_condition(variable)
    assert "Unbound automatic result" in messages(errors(wf, api))


@pytest.mark.parametrize("declaration", ["extraction", "mapping_base", "mapping_exact", "test_variables", "code_write", "hook_write"])
def test_explicit_custom_response_base_or_exact_variable_is_allowed(api, declaration):
    wf = workflow(api_tool(api))
    variable = "custom_response.data.ok"
    if declaration == "extraction":
        wf["nodes"]["done"]["extraction_schema"] = [{"name": "custom_response", "type": "string"}]
    elif declaration.startswith("mapping"):
        name = variable if declaration == "mapping_exact" else "custom_response"
        wf["nodes"]["ask"]["tools"][0]["response_mapping"] = [{"path": "data.receipt", "variable": name}]
    elif declaration == "test_variables":
        wf["test_variables"] = {"custom_response": {"data": {"ok": "yes"}}}
    elif declaration == "code_write":
        wf = with_code("vars['custom_response'] = {'data': {'ok': 'yes'} }")
    elif declaration == "hook_write":
        wf["nodes"]["ask"]["tools"][0]["post_process_code"] = "vars['custom_response'] = {'data': {'ok': 'yes'} }"
    wf["nodes"]["ask"]["transitions"][0]["condition"] = response_condition(variable)
    assert errors(wf, api) == []


def test_node_level_pre_action_mapping_and_code_result_names_are_collected(api):
    wf = with_code("vars['seed'] = 'yes'")
    wf["nodes"]["prepare"]["response_mapping"] = [{"path": "data.ok", "variable": "custom_response"}]
    wf["nodes"]["ask"]["transitions"][0]["condition"] = {
        "logic": "or", "conditions": [
            {"variable": "prepare_vars_response.status", "operator": "is_set"},
            {"variable": "custom_response.data.ok", "operator": "is_set"},
        ],
    }
    assert errors(wf, api) == []


def test_root_lifecycle_and_global_tool_function_names_are_collected(api):
    wf = workflow()
    tool = api_tool(api)
    tool["config"]["alwaysRunsAt"] = ["start_of_call"]
    wf["tools"] = [tool]
    wf["nodes"]["ask"]["transitions"][0]["condition"] = response_condition("submit_commitment_response.status")
    wf["global_nodes"]["help"] = {
        "name": "help", "node_type": "conversation", "condition": response_condition("submit_commitment_response.data.ok"),
        "transitions": [transition("__previous__")], "tools": [api_tool(api)],
    }
    assert errors(wf, api) == []
    wf.pop("tools")
    assert errors(wf, api) == []  # Still produced by the global node's actual tool.


@pytest.mark.parametrize("loop", [
    response_condition("unknown_response.data.ok"),
    "Stay until {{unknown_response.data.ok}} is set.",
    "unknown_response.data.ok",
])
def test_unknown_loop_response_variables_are_checked_without_rewriting(api, loop):
    wf = workflow(api_tool(api))
    wf["nodes"]["ask"]["loop_condition"] = loop
    original = copy.deepcopy(wf)
    issues = errors(wf, api)
    assert "Unbound automatic result" in messages(issues)
    assert all(issue["path"].startswith("$.nodes.ask.loop_condition") for issue in issues)
    assert wf == original


def test_nested_and_and_global_conditions_check_response_variables(api):
    wf = workflow(api_tool(api))
    wf["nodes"]["ask"]["transitions"][0]["condition"] = {
        "logic": "or", "conditions": [{"logic": "and", "conditions": [
            {"variable": "submit_commitment_response.data.ok", "operator": "is_set"},
            {"variable": "unknown_response.data.ok", "operator": "is_set"},
        ]}],
    }
    wf["global_nodes"]["help"] = {"name": "help", "condition": response_condition("other_response.status"),
                                    "transitions": [transition("__previous__")]}
    issues = errors(wf, api)
    assert len(issues) == 2
    assert {issue["path"] for issue in issues} == {
        "$.nodes.ask.transitions[0].condition.conditions[0].conditions[1].variable",
        "$.global_nodes.help.condition.conditions[0].variable",
    }


@pytest.mark.parametrize("source", [
    "vars.get('custom_response')", "value = 'vars[\"custom_response\"] = 1'",
    "params['custom_response'] = 'yes'", "vars[key] = 'yes'", "vars['custom_response']: str",
])
def test_reads_literals_other_dicts_and_dynamic_keys_are_not_declarations(api, source):
    wf = with_code(source)
    wf["nodes"]["ask"]["transitions"][0]["condition"] = response_condition("custom_response.data.ok")
    assert "Unbound automatic result" in messages(errors(wf, api))


def test_ordinary_names_api_literals_and_prose_are_outside_response_alias_lint(api):
    wf = workflow(api_tool(api))
    wf["nodes"]["ask"]["transitions"][0]["condition"] = {
        "logic": "or", "conditions": [
            {"variable": "custom_response_status", "operator": "equals", "operand": "unknown_response.data.ok"},
            {"variable": "data.unknown_response.status", "operator": "is_set"},
            {"variable": "ordinary_undeclared_name", "operator": "is_not_set"},
        ],
    }
    body(wf)["properties"]["subscriber"]["default"] = "unknown_response.data.ok"
    wf["nodes"]["ask"]["task_message"] = "unknown_response.data.ok is literal example text"
    wf["nodes"]["ask"]["loop_condition"] = "The caller discusses unknown_response.data.ok as a literal example"
    original = copy.deepcopy(wf)
    assert errors(wf, api) == []
    assert wf == original
