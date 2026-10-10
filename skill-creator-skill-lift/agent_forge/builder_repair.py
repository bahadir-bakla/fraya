"""Bounded data-only workflow patches; original candidates are never overwritten."""
from __future__ import annotations
from copy import deepcopy
import json
import re

from .builder_policy import obj, STRING, STRINGS, WORKFLOW_SCHEMA
from .tool_api import validate_json

PATCH_SCHEMA = obj({
    "patches": {"type": "array", "items": obj({
        "op": {"type": "string", "enum": ["add", "replace", "remove"]},
        "path": STRING, "value_json": STRING,
    })},
    "coverage_updates": WORKFLOW_SCHEMA["properties"]["coverage"],
    "limitations": STRINGS,
})


def apply_repair(previous: dict, repair: dict) -> dict:
    if validate_json(PATCH_SCHEMA, repair) or len(repair["patches"]) > 64:
        raise ValueError("Repair must be a valid bounded patch response")
    workflow = json.loads(previous["workflow_json"])
    workflow = deepcopy(workflow)
    for patch in repair["patches"]:
        path = patch["path"]
        if not path.startswith("/") or len(path) > 1000:
            raise ValueError("Repair paths must be non-root JSON pointers")
        parts = path[1:].split("/")
        if any("~" in p.replace("~0", "").replace("~1", "") for p in parts):
            raise ValueError("Invalid JSON pointer escaping")
        parts = [p.replace("~1", "/").replace("~0", "~") for p in parts]
        parent = workflow
        for part in parts[:-1]:
            if isinstance(parent, dict):
                parent = parent[part]
            elif isinstance(parent, list) and re.fullmatch(r"0|[1-9][0-9]*", part):
                parent = parent[int(part)]
            else:
                raise ValueError("Repair pointer does not name a container")
        key = parts[-1]
        op = patch["op"]
        if op != "remove":
            value = json.loads(patch["value_json"])
            json.dumps(value, allow_nan=False)
        if isinstance(parent, dict):
            if op in {"remove", "replace"} and key not in parent:
                raise ValueError("Repair remove/replace target is missing")
            if op == "remove":
                del parent[key]
            else:
                parent[key] = value
        elif isinstance(parent, list):
            if key == "-" and op == "add":
                parent.append(value)
                continue
            if not re.fullmatch(r"0|[1-9][0-9]*", key):
                raise ValueError("Invalid repair array index")
            index = int(key)
            if index > len(parent) or (op != "add" and index == len(parent)):
                raise ValueError("Repair array index is out of bounds")
            if op == "add":
                parent.insert(index, value)
            elif op == "remove":
                parent.pop(index)
            else:
                parent[index] = value
        else:
            raise ValueError("Repair parent is not a container")
    coverage = {r["source_id"]: deepcopy(r) for r in previous["coverage"]}
    updates = [r["source_id"] for r in repair["coverage_updates"]]
    if len(updates) != len(set(updates)) or set(updates)-set(coverage):
        raise ValueError("Repair coverage references unknown or duplicate source IDs")
    coverage.update({r["source_id"]: deepcopy(r) for r in repair["coverage_updates"]})
    return {"workflow_json": json.dumps(workflow, ensure_ascii=False, allow_nan=False),
            "coverage": list(coverage.values()), "limitations": repair["limitations"]}


def repair_prompt(contract: dict, policy: dict, kit, feedback: dict) -> str:
    from .builder_prompts import raw_sources
    instructions = """Repair the previous workflow with a minimal bounded JSON patch.
Return ONLY changed paths, not the whole workflow. op is add, replace or remove;
path is an RFC6901 JSON pointer into TARGET_WORKFLOW itself; value_json is valid
serialized JSON (empty string for remove). Preserve unrelated behavior. Use
coverage_updates only for clauses whose implementation nodes/mechanism changed.
For strings, value_json MUST include the JSON quotation marks and escaped newlines;
raw Python source is not valid JSON. For example a string value is serialized
as \"\\\"hello\\\"\", not \"hello\". Code snippets are string values too.
Coverage node_ids must name actual keys in nodes or global_nodes, NEVER code or
tool library entries. Each node's action list must have unique function names:
use one transfer operation with a fresh enum queue field or separate handoff nodes.
Tool result variables are actual function.name + '_response', not _tool_library
reference IDs. Replace alias_response routes with the actual API operation's
response variable or a variable explicitly populated by a mapping/hook.
Every limitation remaining must be explicitly listed. Re-check the ORIGINAL
source rules, actual API and concrete feedback. Never add customer/case-specific
exceptions or claim a patch passed before testing. Do not change model settings.
TARGET_WORKFLOW has top-level nodes/_tool_library/_code_library/initial_node.
Paths start /nodes/... or /_tool_library/... or /_code_library/..., NEVER
/previous_workflow/... . Critic paths can refer to the expanded platform graph:
patch the matching compact tool/code library or node, not generated API boilerplate.
Use the supplied API for exact fields. Bank macros are expanded automatically.
Fix actual source violations; do not convert optional may-retry wording into must,
or assume a standalone brief requires a missing amendment. State is trusted only
when established by backend/tool/code, not user assertions. Deterministic calendar,
floor, confirmation revision, retry counting and bank-call guards belong in code
nodes/hooks, not mere dialogue instructions. An invalid correction must revoke
old consent. Prevent unconditional passthrough from skipping necessary dialogue.
If errors require a larger structural patch, add compact nodes/shared snippets;
do not return an empty patch or silently leave a missing required branch.
"""
    diagnostics = {k: v for k, v in feedback.items() if k not in {"previous_workflow", "expanded_workflow"}}
    refs = {name: (kit / "docs" / name).read_text(encoding="utf-8") for name in ["workflow-format.md", "tools-and-code.md"]}
    return instructions + "\nTARGET_WORKFLOW:\n" + json.dumps(feedback["previous_workflow"], ensure_ascii=False) + \
        "\nDIAGNOSTICS:\n" + json.dumps(diagnostics, ensure_ascii=False) + \
        "\nRAW SOURCES:\n" + json.dumps(raw_sources(contract), ensure_ascii=False) + \
        "\nINPUT API/CLAUSES:\n" + json.dumps(contract, ensure_ascii=False) + \
        "\nCOMPILED POLICY:\n" + json.dumps(policy, ensure_ascii=False) + \
        "\nFREYA REFERENCES:\n" + json.dumps(refs, ensure_ascii=False)
