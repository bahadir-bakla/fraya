"""V11 offline source-only diagnostics. No annotation/data-label reads."""
def maximum_matching(graph):
    """One-to-one boundary-support accounting, never a semantic TP label."""
    candidate_owner = {}
    def augment(annotation, seen):
        for candidate in sorted(set(graph[annotation])):
            if candidate in seen:
                continue
            seen.add(candidate)
            if candidate not in candidate_owner or augment(candidate_owner[candidate], seen):
                candidate_owner[candidate] = annotation
                return True
        return False
    for annotation in sorted(graph):
        augment(annotation, set())
    return {annotation:candidate for candidate,annotation in candidate_owner.items()}


import ast
import hashlib
import json
import time
from pathlib import Path
from collections import Counter
from temporal_parser_v11 import (parse_temporal, source_features_v11, VERSION,
                                 FEATURE_VERSION, CONTEXT_SCHEMA_VERSION,
                                 CONTEXT_SCHEMA_ORIGIN_SHA256)
from temporal_parser_v10 import parse_temporal as parse_old

ROOT = Path(__file__).resolve().parents[2]
FROZEN = "analysis/night-learned-dialogue.v10-parser.freeze.json"
FROZEN_SHA = "b6bf5cfcb5e2ff6d3dbcbef3eba0b5b93db5fb68882de3656293ad5be584d9d9"
RAW = {
 "research/customer-benchmark/semantic-v6-extension/label-free-train-packet.json":"3992ab7f7f21bfc89c9e4a78fc00854cae286e3551cd2b956aa82b605a768bf4",
 "research/customer-benchmark/semantic-v6-peer-extension/blind-source-2f52b35f12d7.json":"84dda0e5cda28c532bbbd2e73a7c4c2c6643ad2aefe16752a2ff979dfc8207cd"}
SPEC = "analysis/learned-layer-design.checkpoint18-v10-assessment.json"

def sha(path):
    return hashlib.sha256((ROOT/path).read_bytes()).hexdigest()

def dump_new(path, value):
    data = (json.dumps(value,indent=2,ensure_ascii=False)+"\n").encode("utf8")
    with (ROOT/path).open("xb") as f: f.write(data)

def tops(o):
    return [n for n in o["nodes"] if n["node_id"] in o["top_level_ids"]]

def run():
    started=time.monotonic(); cpu=time.process_time()
    assert sha(FROZEN)==FROZEN_SHA
    frozen=json.loads((ROOT/FROZEN).read_text(encoding="utf8"))
    protected=dict(frozen["protected_sha256"])
    protected.update(frozen["source_sha256"]); protected.update(frozen["artifacts_sha256"])
    protected[FROZEN]=FROZEN_SHA
    bindings={}
    for section in ("source_sha256","artifacts_sha256","protected_sha256","input_sha256"):
        bindings.update(frozen[section])
    bindings[FROZEN]=FROZEN_SHA
    for path,h in bindings.items(): assert sha(path)==h, path
    for path,h in RAW.items(): assert sha(path)==h, path
    from test_temporal_v11 import run_checks
    tests=run_checks()
    spec=json.loads((ROOT/SPEC).read_text(encoding="utf8"))
    namespace={}; code=(ROOT/"integrations/learned-dialogue/temporal_parser_v11.py").read_text(encoding="utf8")
    exec(compile(code,"portable-v11","exec"),namespace)
    imports=[n.names[0].name for n in ast.walk(ast.parse(code)) if isinstance(n,ast.Import)]
    assert imports==["re"]
    evidence=[]; parity=0; removed=0
    for c in spec["material_fresh_execution"]["runtime_results"]["cases"]:
        source=c["input"]; o=parse_temporal(**source)
        serialized=json.loads(json.dumps(source,ensure_ascii=False))
        portable=namespace["parse_temporal"](**serialized)
        assert portable==json.loads(json.dumps(o)); parity+=1
        node_evidence=[]
        for n in tops(o):
            f=source_features_v11(source["text"],n,source["context"],True,True)
            pf=namespace["source_features_v11"](serialized["text"],json.loads(json.dumps(n)),serialized["context"],True,True)
            assert pf==f; parity+=1
            ablated={k:v for k,v in f["features"].items() if not k.startswith(("source_role=","source_polarity=","governor_visibility="))}
            removed+=len(f["features"])-len(ablated)
            node_evidence.append({"node":n,"feature_sha256":hashlib.sha256(json.dumps(f["features"],sort_keys=True).encode()).hexdigest(),"feature_nonzeros":len(f["features"]),"derived_governor_removed_nonzeros":len(f["features"])-len(ablated),"ablation_keeps_raw_source":all(ablated[k]==v for k,v in f["features"].items() if k.startswith(("w=","w2=","c3=","c4="))),"features_selected":{k:v for k,v in f["features"].items() if k.startswith(("phase=","question_role=","source_role=","source_polarity=","governor_visibility="))}})
        evidence.append({"id":c["id"],"source":source,"nodes":node_evidence,"diagnostics":o["diagnostics"],"abstain":o["abstain"]})
    # Raw TRAIN only. No annotation, adjudication, candidate truth or DEV read.
    counts={v:Counter() for v in ("A1","A2","A3","A4")}
    changes=[]; raw_rows=0; source_masks=Counter(); feature_masks=Counter()
    for path in RAW:
        packet=json.loads((ROOT/path).read_text(encoding="utf8"))
        for row in packet["records"]:
            snapshot=row["input"]; text=snapshot["utterance"]["text"]
            context={k:snapshot[k] for k in ("phase","question","targets") if k in snapshot}
            event=snapshot["turn_id"]; raw_rows+=1
            unknown_profile=snapshot.get("schema_version")!="semantic_input.v1" or snapshot.get("phase")!="payment"
            source_masks["unknown_profile"]+=int(unknown_profile)
            for v in counts:
                o=parse_temporal(text,event,context,v); ns=tops(o)
                counts[v]["rows"]+=1; counts[v]["candidate_rows"]+=int(bool(ns)); counts[v]["candidates"]+=len(ns)
                counts[v]["abstain_rows"]+=int(o["abstain"])
                for n in ns:
                    counts[v]["syntax_"+n["syntax"]]+=1
                if v!="A3": continue
                old=tops(parse_old(text,event,context,v))
                byraw={(n["projection"]["raw_extent"]["char_start"],n["projection"]["raw_extent"]["char_end"],n["kind"]):n for n in old}
                for n in ns:
                    f=source_features_v11(text,n,context,True,snapshot["utterance"].get("complete_transport") is True)
                    pf=namespace["source_features_v11"](text,json.loads(json.dumps(n)),json.loads(json.dumps(context)),True,snapshot["utterance"].get("complete_transport") is True)
                    assert pf==f; parity+=1
                    feature_masks["mechanical_nonempty"]+=bool(f["features"])
                    feature_masks["unsupported_or_other_masked"]+=not bool(f["features"])
                    feature_masks["qualified"]+=int(f["qualified"])
                    key=(n["projection"]["raw_extent"]["char_start"],n["projection"]["raw_extent"]["char_end"],n["kind"])
                    previous=byraw.get(key)
                    if previous and (previous["role_hypothesis"],previous["polarity_hypothesis"])!=(n["role_hypothesis"],n["polarity_hypothesis"]):
                        changes.append({"example_id":row["example_id"],"raw_span":n["projection"]["raw_extent"],"old":[previous["role_hypothesis"],previous["polarity_hypothesis"]],"new":[n["role_hypothesis"],n["polarity_hypothesis"]]})
    for path,h in bindings.items(): assert sha(path)==h,path
    sources={"integrations/learned-dialogue/"+p:sha("integrations/learned-dialogue/"+p) for p in ("temporal_parser_v11.py","diagnostic_v11.py","test_temporal_v11.py")}
    report={"schema_version":"night_learned_dialogue.v11.source_only","parser_version":VERSION,"feature_version":FEATURE_VERSION,"context_schema_version":CONTEXT_SCHEMA_VERSION,"context_schema_origin_sha256":CONTEXT_SCHEMA_ORIGIN_SHA256,"status":"ALL_ABSTAIN_NOFIT","source_sha256":sources,"tests":tests,"checkpoint18_evidence":evidence,"portable_json_parity_checks":parity,"limited_governor_ablation":{"finite_cases":6,"removed_nonzeros":removed,"fit_calls":0,"semantic_accuracy":None,"description":"Remove all 3 derived slots together, retain exactly the same raw lexical observations."},"raw_source_diagnostics":{"rows":raw_rows,"ablations":{v:dict(c) for v,c in counts.items()},"source_profile_masks":dict(source_masks),"A3_feature_masks":dict(feature_masks),"changed_governor_hypotheses":changes,"annotation_alignment":None,"semantic_accuracy":None,"unmatched_vs_truth":None},"preservation":{"protected_distinct_paths":len(protected),"V10_all_distinct_hash_bindings_checked":len(bindings),"unchanged":True},"footprint":{"parser_bytes":len(code.encode()),"imports":imports,"coefficients":0,"complete_trained_bundle_bytes":None},"time":{"cpu_seconds":time.process_time()-cpu,"wall_seconds":time.monotonic()-started},"admission":{"accepted":0,"new_usable_primary_groups":0,"new_usable_DATE_groups":0,"ancestry_closed":False,"qualified":False,"fit_calls":0,"all_abstain":True},"read_limits":{"DEV":0,"dataset_annotation_labels":0,"weights":0,"auth":0,"GPU":0,"USD":0,"platform":0,"network":0},"limitations":["Finite designer-authored regressions and same-code parity; no independent qualification or generalization claim.","Local coordination grammar is bounded; unsupported predicates remain unassessed. Derived governor slots are weak hypotheses.","Context source loader has scalar string domains, not a policy enum. V11 uses a versioned bounded symbol domain; unknown/missing maps explicitly to unknown, structured/non-symbol values reject. Valid symbols do not authenticate profiles.","60 peer source profiles remain masked. Source repairs do not resolve ancestry, data admission, or deployment ingress.","No data labels read: no new annotation alignment/precision/recall/unmatched-truth metrics. Raw candidate counts and governor changes are observations only."]}
    assert tests["passed"]==tests["executed"],tests
    out="analysis/night-learned-dialogue.v11-parser"
    dump_new(out+".json",report)
    summary=("V11 source-only freeze: "+VERSION+" / "+FEATURE_VERSION+"\n"+
      "Tests: %d/%d checks, %d assertions; checkpoint18 G01-G06/C01 all pass; 150 V10 equivalent checks retained.\n"%(tests["passed"],tests["executed"],tests["assertions"])+
      "Portable JSON parity: %d comparisons. Raw TRAIN sources: %d; no data annotation/DEV reads.\n"%(parity,raw_rows)+
      "A3 raw candidates: %d. Changed source governor hypotheses: %d; no truth/accuracy interpretation.\n"%(counts["A3"]["candidates"],len(changes))+
      "Preserved %d distinct protected paths; %d V10 manifest bindings verified.\n"%(len(protected),len(bindings))+
      "Context adapter is a bounded scalar-symbol schema based on pinned data_v6 string fields, not a bank-policy enum. Structured metadata rejected identically by parse/features. Peer profile admission stays masked.\n"+
      "N1 quotes masked without changing offsets; subject/modal coordination bounds the local predicate; unsupported predicate unknown.\n"+
      "Governor-slot ablation removes 3 derived fields on 6 finite probes; no fitting/performance comparison.\n"+
      "Runtime re-only, %d bytes, zero coefficients. All outputs abstain; new usable groups zero; NOFIT. No auth/GPU/platform/labels/DEV.\n"%len(code.encode())+
      "Limit: bounded source grammar and authored regression controls do not establish broad semantic competence, privacy, trusted ingress or data ancestry closure.\n")
    with (ROOT/(out+".txt")).open("xb") as f:f.write(summary.encode("utf8"))
    inputs=dict(RAW);inputs[SPEC]=sha(SPEC);inputs["analysis/learned-layer-design.checkpoint18-v10-assessment.txt"]=sha("analysis/learned-layer-design.checkpoint18-v10-assessment.txt");inputs["integrations/learned-dialogue/data_v6.py"]=CONTEXT_SCHEMA_ORIGIN_SHA256
    freeze={"schema_version":"typed_temporal_parser_freeze.v11","parser_version":VERSION,"feature_version":FEATURE_VERSION,"context_schema_version":CONTEXT_SCHEMA_VERSION,"source_sha256":sources,"artifacts_sha256":{out+s:sha(out+s) for s in (".json",".txt")},"protected_sha256":protected,"input_sha256":inputs,"tests_passed":tests["passed"],"trained":False,"qualified":False,"all_abstain":True}
    dump_new(out+".freeze.json",freeze)
    print(json.dumps({"tests":tests["passed"],"assertions":tests["assertions"],"parity":parity,"protected":len(protected),"hash_bindings":len(bindings),"raw_rows":raw_rows,"ablations":{v:dict(c) for v,c in counts.items()},"feature_masks":dict(feature_masks),"governor_changes":len(changes),"source_hashes":sources,"freeze_sha256":sha(out+".freeze.json"),"cpu_seconds":report["time"]["cpu_seconds"],"all_abstain":True},ensure_ascii=True))

if __name__=="__main__":
    run()
