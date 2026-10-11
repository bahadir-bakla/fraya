"""Offline strict schema and authoritative-binding checks; pure validator core."""
import json
from pathlib import Path

from build_data import encoded, freeze
from context_v2 import BindingContext, InputRejected, predict_v2
from train_v2 import ROOT, strict_json

CONTRACT_PATH = Path(__file__).resolve().parent / "contract_v2.json"


def freeze_contract_v2():
    import hashlib
    path = ROOT / "analysis/learned-layer-design.json"
    data = path.read_bytes()
    design = strict_json(data)
    contract = {"source_path": str(path.relative_to(ROOT)), "source_sha256": hashlib.sha256(data).hexdigest(),
                "schema": design["output_json_schema"], "schema_semantic_checks": design["schema_semantic_checks"],
                "source_warning": "Syntax is not semantic support, authentication or safety proof"}
    if not CONTRACT_PATH.exists():
        freeze(CONTRACT_PATH, encoded(contract))
    return strict_json(CONTRACT_PATH.read_bytes())


def validate_v2(proposal, snapshot, bundle, binding_context):
    import jsonschema  # Existing offline dependency; never in generated runtime.
    if not isinstance(binding_context, BindingContext):
        raise InputRejected("Authoritative BindingContext required")
    contract = strict_json(CONTRACT_PATH.read_bytes())
    jsonschema.Draft202012Validator(contract["schema"]).validate(proposal)
    if proposal["binding"] != binding_context.binding() or proposal["model_id"] != binding_context.model_id:
        raise ValueError("Proposal binding/model differs from authoritative wrapper")
    if proposal["status"] != "abstain" or not proposal["abstentions"]:
        raise ValueError("Current unqualified v2 cannot accept or suppress abstention reasons")
    def visit(value):
        if isinstance(value, dict):
            if "score" in value:
                if type(value["score"]) not in (float, int) or not (-float("inf") < value["score"] < float("inf")):
                    raise ValueError("Nonfinite score")
                if value["decision"] != "abstain" or value["calibrated_probability"] is not None or value["calibration_id"] is not None:
                    raise ValueError("Unqualified or uncalibrated head acceptance")
            if "start" in value and "end" in value:
                if value["turn_id"] != binding_context.binding()["turn_id"] or not 0 <= value["start"] < value["end"] <= len(snapshot["utterance"]["text"]):
                    raise ValueError("Stale/invalid evidence span")
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(proposal)
    expected = predict_v2(snapshot, bundle, binding_context)
    if proposal != expected:
        raise ValueError("Proposal differs from deterministic recomputation on authoritative input")
    return True


if __name__ == "__main__":
    contract = freeze_contract_v2()
    print(json.dumps({"contract_source_sha256": contract["source_sha256"], "frozen_contract": str(CONTRACT_PATH)}, indent=2))
