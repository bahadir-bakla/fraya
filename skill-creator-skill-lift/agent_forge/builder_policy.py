"""Source-linked policy IR; model inference is separate from source validation."""
from __future__ import annotations
import json

from .tool_api import validate_json


def obj(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


STRING = {"type": "string"}
STRINGS = {"type": "array", "items": STRING}
POLICY_SCHEMA = obj({
    "title": STRING,
    "rules": {"type": "array", "items": obj({
        "source_id": STRING, "binding": {"type": "boolean"},
        "policy": STRING, "trigger": STRING, "actions": STRINGS,
        "exceptions": STRINGS, "overrides": STRINGS, "tool_names": STRINGS,
    })},
    "parameters": {"type": "array", "items": obj({
        "name": STRING, "value_json": STRING, "source_ids": STRINGS, "description": STRING,
    })},
    "stages": {"type": "array", "items": obj({
        "name": STRING, "source_ids": STRINGS, "allowed_tools": STRINGS,
        "entry_gate": STRING, "exit_gate": STRING,
    })},
    "ambiguities": STRINGS,
})

WORKFLOW_SCHEMA = obj({
    "workflow_json": STRING,
    "coverage": {"type": "array", "items": obj({
        "source_id": STRING, "node_ids": STRINGS, "mechanism": STRING,
    })},
    "limitations": STRINGS,
})

CRITIC_SCHEMA = obj({
    "verdict": {"type": "string", "enum": ["pass", "revise", "blocked"]},
    "issues": {"type": "array", "items": obj({
        "severity": {"type": "string", "enum": ["error", "warning"]},
        "source_ids": STRINGS, "location": STRING, "message": STRING, "fix": STRING,
    })},
    "counterexamples": {"type": "array", "items": obj({
        "source_ids": STRINGS, "scenario": STRING, "expected_output": STRING,
    })},
})

POLICY_GAP_SCHEMA = obj({
    "assessments": {"type": "array", "items": obj({
        "index": {"type": "integer"}, "source_ids": STRINGS,
        "disposition": {"type": "string", "enum": ["blocking", "resolved_by_source", "safe_protocol_choice", "outside_input_domain"]},
        "resolution": STRING,
    })},
})


def source_ids(contract: dict) -> set[str]:
    return {c["qualified_id"] for d in contract["documents"] for c in d["clauses"]}


def validate_policy(policy: dict, contract: dict) -> list[str]:
    issues = validate_json(POLICY_SCHEMA, policy)
    if issues:
        return issues
    known = source_ids(contract)
    ids = [r["source_id"] for r in policy["rules"]]
    if len(ids) != len(set(ids)):
        issues.append("Duplicate policy source IDs")
    if set(ids) != known:
        issues.append(f"Policy coverage missing={sorted(known-set(ids))}, unknown={sorted(set(ids)-known)}")
    tools = set(contract["tool_contract"]["operations"])
    for rule in policy["rules"]:
        if set(rule["overrides"]) - known:
            issues.append(f"Unknown override sources in {rule['source_id']}")
        if set(rule["tool_names"]) - tools:
            issues.append(f"Unknown policy tools in {rule['source_id']}")
    names = [p["name"] for p in policy["parameters"]]
    if len(names) != len(set(names)):
        issues.append("Duplicate parameter names")
    for item in policy["parameters"]:
        try:
            parsed = json.loads(item["value_json"], parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            json.dumps(parsed, allow_nan=False)
        except (TypeError, ValueError):
            issues.append(f"Invalid JSON parameter {item['name']}")
        if not item["source_ids"] or set(item["source_ids"]) - known:
            issues.append(f"Missing/unknown parameter provenance {item['name']}")
    for stage in policy["stages"]:
        if not stage["source_ids"] or set(stage["source_ids"]) - known:
            issues.append(f"Missing/unknown stage provenance {stage['name']}")
        if set(stage["allowed_tools"]) - tools:
            issues.append(f"Unknown stage tools {stage['name']}")
    if policy["ambiguities"]:
        issues.append("Unresolved policy ambiguities: " + "; ".join(policy["ambiguities"]))
    return issues


def validate_coverage(generated: dict, contract: dict, workflow: dict) -> list[str]:
    issues = validate_json(WORKFLOW_SCHEMA, generated)
    if issues:
        return issues
    known = source_ids(contract)
    covered = [r["source_id"] for r in generated["coverage"]]
    if len(covered) != len(set(covered)) or set(covered) != known:
        issues.append(f"Workflow source coverage mismatch; missing={sorted(known-set(covered))}")
    nodes = set(workflow.get("nodes", {})) | set(workflow.get("global_nodes", {}))
    for row in generated["coverage"]:
        if not row["node_ids"]:
            issues.append(f"Coverage has no implementation nodes for {row['source_id']}")
        if set(row["node_ids"]) - nodes:
            issues.append(f"Unknown coverage nodes for {row['source_id']}")
        if not row["mechanism"].strip():
            issues.append(f"Empty implementation mechanism for {row['source_id']}")
    if generated["limitations"]:
        issues.append("Unresolved emitter limitations: " + "; ".join(generated["limitations"]))
    return issues
