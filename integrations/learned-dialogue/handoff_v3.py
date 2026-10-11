"""Read-only final-source verification plus new immutable handoff report."""
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
from unittest.mock import patch
from build_data import freeze,encoded
from context_v2 import BindingContext,InputRejected
from context_v3 import predict_v3
from reference_v3 import TrustedCallV3
from vector_checks_v3 import adapt
from test_v3 import BUNDLE,SCHEMA,fixture

HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[1]

def sha(blob): return hashlib.sha256(blob).hexdigest()

def main():
    report_path=ROOT/"analysis/night-learned-dialogue.v3.source-r3.json"
    report_blob=report_path.read_bytes(); report=json.loads(report_blob)
    for name,digest in report["files"].items():
        if sha((ROOT/name).read_bytes())!=digest: raise ValueError("Frozen r3 source drift:"+name)
    generated=HERE/"runtime_context_v3_r3.py"; scope={}
    exec(compile(generated.read_bytes(),str(generated),"exec"),scope)
    embedded=scope["predict_context_v3_embedded"]
    vectors=json.loads((ROOT/"analysis/learned-layer-design.checkpoint07-vectors.json").read_bytes())
    vector_parity=0
    with patch("builtins.open",side_effect=AssertionError("file")),patch("socket.socket",side_effect=AssertionError("socket")),patch("subprocess.Popen",side_effect=AssertionError("process")):
        for v in vectors["vectors"]:
            s=v["input_snapshot"]; t,r,p=adapt(v)
            if t is None:
                try: embedded(s,None,None,r,p)
                except InputRejected: vector_parity+=1
                except Exception as exc:
                    # Embedded InputRejected is independently defined, compare
                    # public exception name rather than silently accepting all.
                    if type(exc).__name__!="InputRejected": raise
                    vector_parity+=1
                else: raise ValueError("Absent binding did not reject")
                continue
            source={"call_local_id":t.call_local_id,"source_event_id":t.source_event_id,"event_ordinal":t.event_ordinal,
                    "text":t.text,"complete_transport":True,"question_identity":list(t.question_identity),
                    "target_mapping":[list(pair) for pair in t.target_mapping]}
            if embedded(s,t.binding_context.binding(),source,r,p)!=predict_v3(s,BUNDLE,t,r,p,SCHEMA):
                raise ValueError("Vector native/export mismatch:"+v["id"])
            vector_parity+=1
    source_rows=json.loads((HERE/"v2-final-data/dev.json").read_text())["records"]
    scores=Counter(); abstentions=Counter()
    for row in source_rows:
        s=row["input"]
        ctx=BindingContext({key:s[key] for key in ("turn_id","state_revision","policy_hash","api_hash")},BUNDLE["model_id"])
        t=TrustedCallV3(ctx,s["call_local_id"],s["turn_id"],1,s["utterance"]["text"],True)
        for mode in (True,False):
            wire,side=predict_v3(s,BUNDLE,t,{"source_events":[],"references":[]},{"targets":{}},SCHEMA,include_context=mode)
            label=wire["primary"]["label"] if wire["primary"] else None
            expected=row["labels"]["frame"]["primary"]["label"]
            scores["context" if mode else "no_context"]+=int(label==expected)
            abstentions["context" if mode else "no_context"]+=int(wire["status"]=="abstain")
    handoff={"status":"FROZEN_R3_SOURCE_FOR_INDEPENDENT_REVIEW; ALL_UNQUALIFIED",
             "source_report":str(report_path.relative_to(ROOT)).replace("\\","/"),"source_report_sha256":sha(report_blob),
             "files":report["files"],"additional_artifact_sha256":sha(Path(__file__).read_bytes()),
             "model_sha256":BUNDLE["model_id"],"wire_schema_sha256":sha((HERE/"contract_v2.json").read_bytes()),
             "vectors_sha256":sha((ROOT/"analysis/learned-layer-design.checkpoint07-vectors.json").read_bytes()),
             "vector_native_export_parity":vector_parity,"exposed_dev_raw_primary":{"denominator":len(source_rows),"correct":dict(scores),"all_abstain":dict(abstentions)},
             "all_v1_v2_and_prior_v3_pilot_reports_preserved":True,"new_models_trained":0,"cloud_jobs":0,
             "scope":"Copied authored replay context, frozen weights and already-exposed single-author dev only. No semantic gold, class-floor admission, CPU ceiling or safety qualification.",
             "API":"predict_v3(snapshot,bundle,TrustedCallV3,independent_registry,independent_state,frozen_wire_schema,include_context=True,security_fields=None)->(SemanticProposal,diagnostics)",
             "export_API":"predict_context_v3_embedded(snapshot,authoritative_binding,independent_source,registry,authoritative_state,include_context=True,security_fields=None)->(SemanticProposal,diagnostics)",
             "external_authority":"Independent binding/current source/registry/state required. No Freya live ingress qualified; no tools, canonical policy values, consent grants or mutation.",
             "readiness":{"reviewed_train_adjudication":False,"canonical_closure":False,"reviewed_candidate_validity":False,"new_date_class_floors":False,"GPU_authorization":False,"accepted_semantic_proposals":0},
             "frozen_preservation":report["frozen_preservation"]}
    path=ROOT/"analysis/night-learned-dialogue.v3.handoff-r3.json"; freeze(path,encoded(handoff))
    print(json.dumps({"handoff":str(path),"sha256":sha(path.read_bytes()),"vector_native_export_parity":vector_parity,"dev_raw_primary":dict(scores)},indent=2))

if __name__=="__main__": main()
