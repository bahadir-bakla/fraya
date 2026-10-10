"""Expand compact tool/code references using the supplied API, without inference.

Private _tool_library/_code_library keys exist only in the builder IR. They
are removed before platform lint/save. This compiler never calls tools.
"""
from __future__ import annotations
from copy import deepcopy
import json
import re
import hashlib
from .tool_api import ToolAPI, validate_json


def _bank_tool(spec: dict, api: ToolAPI) -> dict:
    allowed = {"operation", "defaults", "descriptions", "description", "pre_process_code", "post_process_code", "response_mapping", "config"}
    if set(spec)-allowed or spec.get("operation") not in api.operations:
        raise ValueError("Tool macro references an unknown operation or unsupported annotation")
    operation = api.operations[spec["operation"]]
    body = deepcopy(operation.request_schema)
    if not isinstance(body, dict) or body.get("type") != "object" or not isinstance(body.get("properties"), dict):
        raise ValueError("Tool macro requires an explicit object body schema")
    defaults = spec.get("defaults", {})
    descriptions = spec.get("descriptions", {})
    if not isinstance(defaults, dict) or not isinstance(descriptions, dict) or (set(defaults)|set(descriptions))-set(body["properties"]):
        raise ValueError("Tool macro uses request fields absent from supplied OpenAPI")
    for name, value in defaults.items():
        if not (isinstance(value, str) and "{{" in value):
            errors = validate_json(body["properties"][name], value)
            if errors:
                raise ValueError("Tool macro default violates supplied schema for " + name)
        body["properties"][name]["default"] = value
    for name, description in descriptions.items():
        if not isinstance(description, str):
            raise ValueError("Tool macro descriptions must be strings")
        body["properties"][name]["description"] = description
    # Freya's HTTP body binder needs a leaf default to reconstruct the body.
    # Fresh, deliberately unbound variables expose model parameters without
    # baking old extraction values. Automatic *_args vars do not set these names.
    for name, field in body["properties"].items():
        if "default" not in field:
            digest = hashlib.sha256((operation.name + ":" + name).encode()).hexdigest()[:12]
            field["default"] = "{{forge_arg_" + digest + "}}"
    tool = {"type": "function", "config": {"maxRetries": 0, **spec.get("config", {})}, "function": {
        "name": operation.name, "handler": "__function__:api_call",
        "description": spec.get("description") or operation.summary or operation.description,
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "default": operation.url},
            "method": {"type": "string", "default": operation.method.upper()},
            "connect_retries": {"type": "number", "default": 0},
            "headers": {"type": "object", "properties": {"Content-Type": {"type": "string", "default": "application/json"}}},
            "body": body,
        }},
    }}
    for key in ("pre_process_code", "post_process_code", "response_mapping"):
        if key in spec:
            tool[key] = deepcopy(spec[key])
    return tool


def compile_workflow(compact: dict, api: ToolAPI, *, chat_mode: bool = False) -> dict:
    if not isinstance(compact, dict):
        raise ValueError("Workflow IR must be an object")
    workflow = deepcopy(compact)
    tools = workflow.pop("_tool_library", {})
    code = workflow.pop("_code_library", {})
    if not isinstance(tools, dict) or not isinstance(code, dict) or any(not isinstance(v, str) for v in code.values()):
        raise ValueError("Tool/code libraries must be maps with string code snippets")

    def action_array(path):
        return (len(path) == 1 and path[0] in {"tools", "pre_actions"}) or (
            len(path) == 3 and path[0] in {"nodes", "global_nodes"}
            and path[2] in {"tools", "pre_actions"})

    def snippet(value):
        if isinstance(value, str) and value.startswith("@builtin:"):
            from .guarded_freya_adapter import guarded_builtin_snippets
            builtins = guarded_builtin_snippets()
            name = value[len("@builtin:"):]
            if name not in builtins:
                raise ValueError("Code reference names an unknown trusted builtin")
            return builtins[name]
        if isinstance(value, str) and value.startswith("@code:"):
            name = value[len("@code:"):]
            if name not in code:
                raise ValueError("Code reference names an unknown snippet")
            return code[name]
        return value

    def expand(value, path=(), action=False, depth=0):
        if depth > 64:
            raise ValueError("Macro/reference nesting exceeds the compiler bound")
        if isinstance(value, list):
            return [expand(v, path+(str(i),), action=action_array(path), depth=depth+1) for i, v in enumerate(value)]
        if isinstance(value, dict):
            if action and "_tool_ref" in value:
                if set(value) != {"_tool_ref"} or value["_tool_ref"] not in tools:
                    raise ValueError("Tool reference must name a library entry without extra fields")
                return expand(_bank_tool(tools[value["_tool_ref"]], api), path, action=True, depth=depth+1)
            if action and "_bank_tool" in value:
                if set(value) != {"_bank_tool"}:
                    raise ValueError("Inline bank macro has unsupported fields")
                return expand(_bank_tool(value["_bank_tool"], api), path, action=True, depth=depth+1)
            if action:
                for key in ("pre_process_code", "post_process_code"):
                    if key in value:
                        value[key] = snippet(value[key])
                function = value.get("function", {})
                if function.get("handler") == "__function__:code_exec":
                    parameter = function.get("parameters", {}).get("properties", {}).get("code", {})
                    if "default" in parameter:
                        parameter["default"] = snippet(parameter["default"])
            return {k: expand(v, path+(k,), depth=depth+1) for k, v in value.items()}
        return value
    result = expand(workflow)
    # Compact references form a private namespace. Bind routing references only;
    # ordinary API payload strings/keys remain opaque customer data.
    aliases = {name + "_response": spec.get("operation") + "_response"
               for name, spec in tools.items()
               if isinstance(name, str) and isinstance(spec, dict)
               and isinstance(spec.get("operation"), str)}

    def bind_condition(condition):
        if not isinstance(condition, dict):
            return
        variable = condition.get("variable")
        if isinstance(variable, str):
            match = re.fullmatch(r"([A-Za-z_][A-Za-z_0-9]*_response)(\..*)?", variable)
            if match and match[1] in aliases:
                condition["variable"] = aliases[match[1]] + (match[2] or "")
        for child in condition.get("conditions", []):
            bind_condition(child)

    for collection in (result.get("nodes", {}), result.get("global_nodes", {})):
        if isinstance(collection, dict):
            for node in collection.values():
                if isinstance(node, dict):
                    entry = node.get("on_enter", {})
                    if (chat_mode and node.get("node_type") == "conversation"
                            and isinstance(entry, dict) and entry.get("type") == "tts"
                            and isinstance(entry.get("text"), str)):
                        # Explicit development profile, not an automatic fix:
                        # both TTS and LLM entries passed conversation controls.
                        # Keep the authored utterance while comparing entry modes.
                        node["on_enter"] = {"type": "llm", "prompt":
                            "Speak exactly the following line, without adding any other words:\n" + entry["text"]}
                    for transition in node.get("transitions", []):
                        if isinstance(transition, dict):
                            bind_condition(transition.get("condition"))
                    bind_condition(node.get("loop_condition"))
                    bind_condition(node.get("condition"))
    json.dumps(result, allow_nan=False)
    return result
