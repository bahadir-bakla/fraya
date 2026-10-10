"""Provenance-preserving brief and tool inventory, before semantic compilation."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .brief_inputs import load_brief_bundle
from .tool_api import load_tool_api


def inspect_inputs(brief_paths: list[str | Path], tool_api_path: str | Path) -> dict:
    bundle = load_brief_bundle(brief_paths)
    api_path = Path(tool_api_path)
    api = load_tool_api(api_path)
    for document in bundle["documents"]:
        for clause in document["clauses"]:
            clause["mentioned_tools"] = api.discover_tools(clause["text"])
    return {
        **bundle,
        "tool_api_source": {
            "path": str(api_path),
            "sha256": hashlib.sha256(api_path.read_bytes()).hexdigest(),
        },
        "tool_contract": api.to_dict(),
        "readiness": {
            "source_inventory_complete": True,
            "semantic_policy_compiled": False,
            "freya_workflow_generated": False,
            "live_agent_tested": False,
            "remaining": [
                "Resolve amendments and compile each rule into source-linked policy predicates.",
                "Generate an official Freya workflow and independent test expectations.",
                "Validate, publish, test and export the saved platform workflow.",
            ],
        },
    }
