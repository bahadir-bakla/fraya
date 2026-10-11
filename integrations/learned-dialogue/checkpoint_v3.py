"""Freeze new shadow source checks; no data fit, cloud or workflow calls."""
import ast
import hashlib
import io
import json
import time
import unittest
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch

import jsonschema
import test_v3
from context_v2 import BindingContext
from context_v3 import predict_v3
from reference_v3 import TrustedCallV3
from candidate_v3 import diagnostics_v3
from export_v3 import export_v3
from build_data import encoded,freeze
from vector_checks_v3 import run_vectors

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def sha(blob): return hashlib.sha256(blob).hexdigest()


def main(revision="pilot"):
    suite=unittest.defaultTestLoader.loadTestsFromModule(test_v3)
    stream=io.StringIO(); started=time.perf_counter()
    results=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    if not results.wasSuccessful(): raise ValueError(stream.getvalue())
    schema=test_v3.SCHEMA; bundle=test_v3.BUNDLE
    exported,export_report=export_v3(bundle,schema)
    scope={}
    exec(compile(exported,"offline-runtime-context-v3","exec"),scope)
    embedded=scope["predict_context_v3_embedded"]
    records_by_split={name:json.loads((HERE/"v2-final-data"/(name+".json")).read_text())["records"] for name in ("train","dev")}
    diagnostics={name:diagnostics_v3(records,bundle["model"],name) for name,records in records_by_split.items()}
    status=Counter(); errors=[]; observations=[]; parity=0
    validator=jsonschema.Draft202012Validator(schema)
    with patch("builtins.open",side_effect=AssertionError("inference file I/O forbidden")),patch("socket.socket",side_effect=AssertionError("inference socket forbidden")),patch("subprocess.Popen",side_effect=AssertionError("inference process forbidden")):
        for split,records in records_by_split.items():
            for row in records:
                snapshot=row["input"]
                binding={key:snapshot[key] for key in ("turn_id","state_revision","policy_hash","api_hash")}
                context=BindingContext(binding,bundle["model_id"])
                source={"call_local_id":snapshot["call_local_id"],"source_event_id":snapshot["turn_id"],
                        "event_ordinal":1,"text":snapshot["utterance"]["text"],"complete_transport":True}
                trusted=TrustedCallV3(context,source["call_local_id"],source["source_event_id"],1,source["text"],True)
                # No historical registry synthesized from current snapshot. Thus
                # authored replay reference qualification remains unavailable.
                registry={"source_events":[],"references":[]}; state={"targets":{}}
                native=predict_v3(snapshot,bundle,trusted,registry,state,schema)
                generated=embedded(snapshot,binding,source,registry,state)
                if native!=generated: raise ValueError("Native/export parity failure:"+row["example_id"])
                parity+=1; status[native[0]["status"]]+=1
                for error in validator.iter_errors(native[0]): errors.append({"id":row["example_id"],"error":error.message})
                observations.append({"id":row["example_id"],"split":split,"status":native[0]["status"],
                                     "wire_errors":native[1].get("wire_errors",[]),"detector_status":native[1].get("detector",{}).get("status"),
                                     "input_source_scope":"Authored replay/self-consistency only; NOT independently authenticated ingress"})
    if errors: raise ValueError(str(errors[:3]))
    # Separately exercise independent literal source fixture through exported code.
    fixture_parity=0
    for length in (1,125,126,128):
        s,t,r,p=test_v3.fixture("u"*length)
        source={"call_local_id":t.call_local_id,"source_event_id":t.source_event_id,"event_ordinal":t.event_ordinal,
                "text":t.text,"complete_transport":True,"question_identity":list(t.question_identity),"target_mapping":[list(v) for v in t.target_mapping]}
        if predict_v3(s,bundle,t,r,p,schema)!=embedded(s,t.binding_context.binding(),source,r,p):
            raise ValueError("Independent fixture/export mismatch")
        fixture_parity+=1
    final=json.loads((ROOT/"analysis/night-learned-dialogue.v2-final.handoff.json").read_text())
    original=json.loads((HERE/"v1-frozen-archive.manifest.json").read_text())
    for hashes in (final["changed_file_hashes"],original["files"]):
        for name,digest in hashes.items():
            if sha((ROOT/name).read_bytes())!=digest: raise ValueError("Frozen drift:"+name)
    vectors=run_vectors()
    runtime=HERE/("runtime_context_v3.py" if revision=="pilot" else "runtime_context_v3_"+revision+".py")
    freeze(runtime,exported)
    suffix="" if revision=="pilot" else "."+revision
    freeze(ROOT/("analysis/night-learned-dialogue.v3.detector-train"+suffix+".json"),encoded(diagnostics["train"]))
    freeze(ROOT/("analysis/night-learned-dialogue.v3.detector-dev"+suffix+".json"),encoded(diagnostics["dev"]))
    freeze(ROOT/("analysis/night-learned-dialogue.v3.vectors"+suffix+".json"),encoded(vectors))
    source_files=("reference_v3.py","detector_v3.py","guard_v3.py","context_v3.py","candidate_v3.py","export_v3.py","test_v3.py","checkpoint_v3.py","vector_checks_v3.py","merge_v3.py",runtime.name)
    design_blob=(ROOT/"analysis/learned-layer-design.json").read_bytes()
    report={"utc":datetime.now(timezone.utc).isoformat(),"status":"SHADOW_SOURCE_REPAIR_CHECKPOINT; ALL_UNQUALIFIED",
            "checks":{"passed":results.testsRun,"failed":len(results.failures),"errors":len(results.errors),"output":stream.getvalue()},
            "designer_vectors":{k:v for k,v in vectors.items() if k!="rows"},
            "CPU_seconds":time.perf_counter()-started,"export":export_report,"authored_native_export_parity":parity,
            "independent_literal_fixture_export_parity":fixture_parity,"schema_errors":errors,"runtime_status_counts":dict(status),
            "inference_file_socket_process_blocked":True,"actual_detector_vs_oracle":{key:{k:v for k,v in report.items() if k!="rows"} for key,report in diagnostics.items()},
            "metrics_scope":"Exposed single-author frozen TRAIN/dev masks; no independent gold/OOD/generalization/calibration/qualification. Conditional frozen heads reuse old oracle-span training; actual candidate fit is gated and not run.",
            "independent_reference_controls":"Earlier completed source event revision3/current4, exact opaque component tokens, same-value token changes, unrelated sibling stability, no default revision, bool/missing/future/duplicate/cross-call/question mutations, offer/readback identity, deferred refusal epoch.",
            "model_file_and_weights_unchanged":bundle["model_id"],"new_models_trained":0,"GPU_jobs":0,"platform_calls":0,
            "current_review_gate_parent_report":{"single_partly_exposed_review_rows":81,"positive_groups":16,"additional_negative_groups":19,"ambiguous_rows":7,"missing_closure_id":"CSv2-E-0073","adjudicated_gold":0,"admitted":False},
            "wire":"semantic_proposal.v1 unchanged; clauses use local c0..c11; omitted missing candidates; amount_scope unresolved absent independent absence proof",
            "binding":"TrustedCallV3 needs independent exact user event and wrapper bindings; reference resolution additionally needs independent question identity/target map and deterministic historical registry. Object construction/source enum/copy equality proves no authentication.",
            "designer_sha256":sha(design_blob),"designer_version":json.loads(design_blob.decode("utf-8-sig"))["document_version"],
            "frozen_preservation":{"v1_files":len(original["files"]),"v2_final_files":len(final["changed_file_hashes"]),"byte_identical":True},
            "files":{str((HERE/name).relative_to(ROOT)).replace("\\","/"):sha((HERE/name).read_bytes()) for name in source_files},
            "remaining":["No independent reference registry for corpus/live Freya ingress", "Candidate validity/target/clause/polarity/correction/consent heads still unqualified",
                         "English deterministic pattern coverage incomplete; unmatched spans not proven false positives without absent-region audit",
                         "Actual-detector date fit requires independent reviewed spans/masks, canonical closure and class floors; no author-label fallback",
                         "Independent exact-source Opus audit pending; designer semantic cases NOT_EXERCISED; no early gate-pass claim"],
            "observations":observations}
    path=ROOT/("analysis/night-learned-dialogue.v3.source-"+revision+".json")
    freeze(path,encoded(report))
    print(json.dumps({"report":str(path),"sha256":sha(path.read_bytes()),"tests":results.testsRun,"parity":parity,"export_bytes":export_report["utf8_bytes"],"dev_counts":diagnostics["dev"]["counts"],"all_abstain":dict(status)},indent=2))


if __name__=="__main__": main("r3")
