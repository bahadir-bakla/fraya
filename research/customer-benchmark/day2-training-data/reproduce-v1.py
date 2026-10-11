"""Verify frozen V1 using its exact producer/config; never rewrite V1 artifacts."""
import hashlib
import json
from pathlib import Path
import types

OUT = Path(__file__).resolve().parent
REPO = OUT.parents[2]
producer = OUT / "processor-v1.py"
config = OUT / "sources-v1.json"
module = types.ModuleType("frozen_day2_training_v1")
module.__file__ = str(producer)
exec(compile(producer.read_bytes(), str(producer), "exec"), module.__dict__)
module.HERE = REPO / "integrations/customer-datasets"
module.REPO = REPO
module.OUT = OUT
module.CACHE = OUT / ".cache"
module.SOURCES = config
artifacts, expected = module.compile_packet()
actual_bytes = (OUT / "manifest.json").read_bytes()
actual = json.loads(actual_bytes)
# The snapshot is relocated. Only its provenance PATHS are restored to their
# historical logical locations; hashes remain the hashes of frozen bytes.
relocated_paths = {"processor": expected["processor"]["path"], "source_config": expected["source_config"]["path"]}
expected["processor"]["path"] = "integrations/customer-datasets/day2_training_data.py"
expected["source_config"]["path"] = "integrations/customer-datasets/day2_training_sources.json"
module.require(expected == actual and module.encoded(expected) == actual_bytes, "Frozen V1 manifest reproduction differs beyond snapshot path relocation")
for name, value in artifacts.items():
    module.require((OUT / name).read_bytes() == value, "Frozen V1 artifact reproduction mismatch: " + name)
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
report = {"status": "passed", "frozen_manifest_sha256": digest(OUT / "manifest.json"),
          "frozen_producer_sha256": digest(producer), "frozen_source_config_sha256": digest(config),
          "all_initial_artifacts_byte_identical_to_frozen_recomputation": True,
          "initial_manifest_byte_identical_after_only_logical_snapshot_path_restoration": True,
          "relocated_snapshot_paths": relocated_paths,
          "canonical_current_metadata_drift": {"processor_sha256": digest(module.HERE / "day2_training_data.py") != actual["processor"]["sha256"],
                                               "source_config_sha256": digest(module.HERE / "day2_training_sources.json") != actual["source_config"]["sha256"]},
          "initial_v1_artifacts_rewritten": False,
          "splits": {split: actual["outputs"][split + ".jsonl"] for split in module.SPLITS},
          "invariants": expected["invariants"]}
(OUT / "v1-independent-verification.json").write_bytes(module.encoded(report))
print(json.dumps({key: report[key] for key in ("status", "frozen_manifest_sha256", "all_initial_artifacts_byte_identical_to_frozen_recomputation", "canonical_current_metadata_drift")}, sort_keys=True))
