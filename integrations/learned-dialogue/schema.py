"""Freeze a machine-readable v1 record/oracle/input/proposal contract."""
import json
from pathlib import Path
from build_data import PREFIX, encoded, freeze
from inference import HEADS, LABELS


def obj(properties, required=None):
    return {"type": "object", "additionalProperties": False, "properties": properties,
            "required": list(properties) if required is None else required}


def main():
    string = {"type": "string"}
    nullable_string = {"type": ["string", "null"]}
    label_properties = {h: {"enum": list(LABELS[h])} for h in HEADS}
    provenance = obj({"fictional": {"const": True}, "author": string, "origin": string,
                      "raw_public_text_copied": {"const": False}, "policy_oracle": {"const": False},
                      "source_locator": {"type": ["object", "null"]}})
    record = obj({"id": string, "utterance": {"type": "string", "maxLength": 4096},
                  "split": {"enum": ["train", "calibration", "holdout"]},
                  "semantic_template_group": string, "scenario_family": string, "source_group": string,
                  "augmentation_parent": nullable_string, "provenance": provenance})
    label = obj(dict(label_properties, must_abstain={"type": "boolean"}, rationale=string))
    snapshot = obj({"utterance": {"type": "string", "maxLength": 4096}, "turn_id": {"type": "string", "minLength": 1},
                    "state_revision": {"type": "integer", "minimum": 0},
                    "policy_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "raw_text_provenance": string})
    proposal = obj({"schema_version": {"const": 1}, "authority": {"const": "semantic_proposal_only"},
                    "research_only": {"const": True}, "turn_id": string,
                    "state_revision": {"type": "integer", "minimum": 0},
                    "policy_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "input_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "candidate": obj(label_properties), "confidence": {"type": "object"},
                    "abstain": {"type": "boolean"}, "reasons": {"type": "array", "items": string},
                    "clauses": {"type": "array", "maxItems": 1}, "corrections": {"type": "array", "maxItems": 1},
                    "consent_signal": {"const": "unassessed"}})
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "Learned dialogue v1 research contracts",
              "$comment": "V1 completion conflates correction/negation; retained for honest original metrics. V2 uses designer-owned independent dimensions. Oracle labels are synthetic pre-fit declarations, not human gold or policy truth.",
              "$defs": {"record": record, "oracle_label": label, "input_snapshot": snapshot, "semantic_proposal": proposal}}
    freeze(Path(str(PREFIX) + ".schema.json"), encoded(schema))
    print("Frozen schema: " + str(PREFIX) + ".schema.json")


if __name__ == "__main__":
    main()
