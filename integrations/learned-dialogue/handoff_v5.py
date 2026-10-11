"""Finalize exact TRAIN diagnostics and record the actual closed CPU pre-fit gate."""
import json
import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import alignment_v5 as alignment
import checkpoint_v5
import primary_cpu_v5 as cpu

ROOT = cpu.admission.ROOT
AUTH_PATH = "research/customer-benchmark/semantic-v3-collection/parent-cpu-authorization.primary.v4_1.json"
AUTH_TRUST = "57f4ed0dd619816147c17f30d4f55d544fd0b902f293cbcb47af69e86a11a638"
SPLITS_PATH = "research/customer-benchmark/semantic-v3-collection/parent-packet-train-splits.v4_1.json"


def write_new(path, data):
    with (ROOT / path).open("xb") as f:
        f.write(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False).encode("utf-8")+b"\n")


def main():
    raw = cpu.admission.load_allowed_inputs()
    auth = (ROOT / AUTH_PATH).read_bytes()
    splits_raw = (ROOT / SPLITS_PATH).read_bytes()
    splits = cpu.admission.strict_json(splits_raw)
    if cpu.admission.sha(Path(cpu.admission.__file__).read_bytes()) != checkpoint_v5.TRUSTED_MODULE_SHA:
        raise ValueError("admission_source_changed")
    if cpu.admission.sha(auth) != AUTH_TRUST:
        raise ValueError("out_of_band_parent_authorization_digest_mismatch")
    assessed = cpu.admission.assess_admission(raw,authorization_raw=auth,
            trusted_authorization_sha256=AUTH_TRUST,candidates=None,split_assignments=splits)
    if not assessed["admitted"]:
        raise ValueError("parent_data_admission_failed")
    rows = assessed["eligible_rows"]["primary"]
    usable, masked = [], []
    for r in rows:
        f = cpu.features(r["snapshot"])
        if f["eligible"]:
            usable.append(r)
        else:
            masked.append({"id":r["id"],"group":r["group"],"label":r["label"],"reason":f["reason"],
                           "phase":r["snapshot"]["phase"],"question_role":r["snapshot"]["question"]["role"],
                           "source_binding":r["source_binding"],"annotation_pointer":r["annotation_pointer"]})
    pos = {r["group"] for r in usable if r["y"]}
    neg = {r["group"] for r in usable if not r["y"]} - pos
    if len(pos)>=20 and len(neg)>=20:
        raise ValueError("pre_fit_gate_changed; explicitly run authorized checkpoint rather than closed report")
    suite = unittest.defaultTestLoader.discover(str(ROOT / "integrations/learned-dialogue"),pattern="test_v5.py")
    results = unittest.TextTestRunner(verbosity=1).run(suite)
    if not results.wasSuccessful():
        raise ValueError("smoke_failed")
    alignment_report = json.loads((ROOT / "analysis/night-learned-dialogue.v5.alignment.json").read_bytes())
    write_new("integrations/learned-dialogue/actual_r4_candidates_v5.json",alignment_report["candidate_vector"])
    r4_path = ROOT / "analysis/night-learned-dialogue.v3.source-r4.json"
    r4 = json.loads(r4_path.read_bytes())
    r4_sources = {p:cpu.admission.sha((ROOT/p).read_bytes())==sha for p,sha in r4["source_hashes"].items()}
    if not all(r4_sources.values()):
        raise ValueError("frozen_r4_source_modified")
    # Frozen original-source manifests are in the original checkpoint reports.
    v2_path = ROOT / "analysis/night-learned-dialogue.v2-final.json"
    sources = {str(p.relative_to(ROOT)).replace("\\", "/"):cpu.admission.sha(p.read_bytes())
        for p in [Path(__file__), Path(cpu.__file__), Path(alignment.__file__), Path(checkpoint_v5.__file__),
                  ROOT / "integrations/learned-dialogue/test_v5.py", Path(cpu.admission.__file__)]}
    # Compile the json/re inference contract without any data/model fitting.
    exported = checkpoint_v5.exported_source()
    ns = {}
    exec(compile(exported,"untrained-primary-v5-contract","exec"),ns)
    feature_parity = sum(cpu.features(r["snapshot"])==ns["features"](r["snapshot"]) for r in rows)
    if feature_parity!=len(rows):
        raise ValueError("feature_export_parity_failed")
    with (ROOT / "integrations/learned-dialogue/runtime_primary_contract_v5.py").open("x",encoding="utf-8",newline="\n") as f:
        f.write(exported)
    report = {"schema_version":"learned_primary_checkpoint.v5.closed", "utc":datetime.now(timezone.utc).isoformat(),
        "cpu_parent_data_admission":True,"authorization_raw_sha256":AUTH_TRUST,
        "authorization_trust_source":"explicit parent message; never receipt self-hash",
        "admission_module_sha256":checkpoint_v5.TRUSTED_MODULE_SHA,"source_sha256":sources,
        "source_raw_sha256":assessed["source_raw_sha256"], "split_assignments_sha256":assessed["split_assignments_sha256"],
        "feature_version":cpu.VERSION,"observed_admitted_rows":len(rows),"feature_eligible_rows":len(usable),
        "feature_eligible_groups":len({r["group"] for r in usable}),"positive_groups":len(pos),
        "additional_negative_groups":len(neg),"positive_group_ids":sorted(pos),"additional_negative_group_ids":sorted(neg),
        "feature_masked_rows":masked,"actual_fit_attempt":"authorized checkpoint validated source/auth; stopped before fit loop",
        "fit_calls_on_real_training_data":0,"weights_created":False,"training_metrics":None,
        "fixed_gate":"at least20 positive and20 additional-negative feature-eligible canonical groups",
        "blocking_reason":"feature_eligible_primary_group_floor_unmet", "unit_checks":results.testsRun,
        "toy_math_tests_are_not_actual_training_metrics":True,"native_export_feature_mask_comparisons":feature_parity,
        "runtime_contract_bytes":len(exported.encode("utf-8")),"runtime_contract_trained":False,
        "new_dev_read":False,"gpu_used":False,"qualified":False,"accepted_outputs":0,
        "human_gold_rows":0,"iid_gold_rows":0,"payment_authority":False,
        "date":{"fitted":False,"authorized":False,"candidate_vector_sha256":alignment_report["candidate_vector_sha256"],
                "actual_feature_eligible_observed_support":alignment_report["date"]["actual_feature_eligible_observed_support"],
                "alignment":alignment_report["date"]["alignment"],
                "annotation_status_counts":alignment_report["date"]["annotation_status_counts"]},
        "frozen_r4_sha256":cpu.admission.sha(r4_path.read_bytes()),"frozen_r4_source_verification":r4_sources,
        "limits":["No class-floor or privacy-mask relaxation to fit.",
                  "Need at least one additional eligible reviewed negative canonical group under same admission contract.",
                  "Security phase/role/field answers remain surface-masked; generic keyword privacy mask is conservative.",
                  "No group-disjoint controls fitted on actual data; only isolated toy mathematics smoke tests ran.",
                  "DATE completion needs four more aligned eligible unfinished groups; boundary/scope failures remain recorded.",
                  "Machine source review/adjudication is engineering supervision, not human/IID gold or live qualification."]}
    write_new("analysis/night-learned-dialogue.v5.primary-readiness.json",report)
    lines = ["V5 primary CPU checkpoint: parent data admission passed; pre-fit gate CLOSED.",
             "108 observed rows admitted;103 feature eligible/46 groups;27 positive/19 additional negative groups.",
             "5 privacy-masked rows; no real fit calls, new weights or actual training metrics.",
             f"{results.testsRun} unit/smoke checks;{feature_parity} native/export feature+mask comparisons.",
             "No new DEV/GPU/live permission; all outputs unqualified/abstain.",
             "DATE exact scoped64 incl1 ambiguous,5 boundary gaps,6 multi-target scope gaps; feature support20complete/16unfinished groups.",
             "Actual R4 vector SHA256:"+alignment_report["candidate_vector_sha256"],
             "Frozen R4 source/report preserved; no v1/v2/R3 edits.",*report["limits"]]
    with (ROOT / "analysis/night-learned-dialogue.v5.primary-readiness.txt").open("x",encoding="utf-8") as f:
        f.write("\n".join(lines)+"\n")
    print(json.dumps({k:report[k] for k in ("observed_admitted_rows","feature_eligible_rows","positive_groups",
          "additional_negative_groups","unit_checks","native_export_feature_mask_comparisons","blocking_reason")}))


if __name__ == "__main__":
    main()
