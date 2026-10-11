"""Source-schema and inference leakage checks; executes no optimization."""
import copy
import json
from day2_multisource_data import (InputRejected, inference_input, load_split,
                                   taxonomy, validate_row, audit_partitions)
from day2_multisource_features import source_graph, feature_keys


def run(rows=None):
    rows = load_split("train") if rows is None else rows
    taxa = taxonomy()
    b = next(r for r in rows if r["source_id"] == "banking77-publisher-train")
    n = next(r for r in rows if r["source_id"] == "polyai-nlupp")
    t = next(r for r in rows if r["source_id"] == "google-taskmaster3-shard00")
    checks = {}
    def rejected(name, action):
        try:
            action()
        except (ValueError, InputRejected):
            checks[name] = True
        else:
            checks[name] = False
    for source in (b, n, t):
        original = copy.deepcopy(source)
        changed = copy.deepcopy(source)
        changed.update(record_id="NOT-A-FEATURE", source_id="NOT-A-FEATURE", source_scenario="ANNOTATION", canonical_slot_reference={"date":"2099-12-31"}, targets={"trap":"ORACLE"}, graph={"edges":[]})
        checks[source["source_id"] + ":metadata_target_invariance"] = source_graph(inference_input(source)) == source_graph(inference_input(changed))
        checks[source["source_id"] + ":input_immutable"] = original == source
    g = source_graph(inference_input(t)); off = source_graph(inference_input(t),False)
    checks["taskmaster_full_context_plus_summary"] = len(g["nodes"]) == len(t["context"]) + 1
    checks["taskmaster_actual_order_edges"] = sum(e[2] == "observed_next_turn" for e in g["edges"]) == len(t["context"])-1
    checks["edge_ablation_only_deletes_messages"] = not off["edges"] and all(off[k] == g[k] for k in ("nodes","linear","readout_nodes"))
    checks["whole_context_direct_readout_in_both_variants"] = off["readout_nodes"][0] == g["readout_nodes"][0] == 0 and off["readout_weights"][0] == .5
    single=source_graph(inference_input(b));checks["whole_turn_direct_readout"] = single["readout_nodes"][0] == 0 and single["readout_weights"][0] == .5
    checks["latest_only_really_removes_context"] = len(source_graph(inference_input(t),latest_only=True)["nodes"]) <= 4
    checks["digits_not_values"] = feature_keys("amount 123") == feature_keys("amount 987")
    checks["neutral_placeholder_control"] = feature_keys("[REDACTED_ENTITY]",True) != feature_keys("[REDACTED_ENTITY]",False)
    changed = copy.deepcopy(b); changed["head_mask"]["banking77_intent"] = "false"
    rejected("truthy_string_head_mask_rejected",lambda:validate_row(changed,"train",taxa))
    changed = copy.deepcopy(n); changed["target_element_masks"]["nlupp_intents"][0] = 1
    rejected("integer_element_mask_rejected",lambda:validate_row(changed,"train",taxa))
    changed = copy.deepcopy(n); masked = next(i for i,v in enumerate(changed["target_element_masks"]["nlupp_intents"]) if not v); changed["targets"]["nlupp_intents"][masked] = 1
    rejected("unknown_domain_not_positive",lambda:validate_row(changed,"train",taxa))
    changed = copy.deepcopy(t); changed["graph"]["edges"] = [[0,1,"permission"]]
    rejected("invented_graph_relation_rejected",lambda:validate_row(changed,"train",taxa))
    changed = copy.deepcopy(t); changed["context"][0]["speaker"] = {"role":"user"}
    rejected("structured_role_rejected",lambda:inference_input(changed))
    changed = copy.deepcopy(t); changed["text"] = "A different source"
    rejected("latest_raw_binding_mismatch",lambda:inference_input(changed))
    rejected("runtime_metadata_not_accepted",lambda:source_graph({"text":"hello","context":[],"target":"secret"}))
    rejected("truthy_feature_flag",lambda:source_graph(inference_input(b),use_edges="false"))
    changed = copy.deepcopy(b); changed["record_id"] = "cross-partition"; changed["split"] = "calibration"
    rejected("same_lineage_across_split_rejected",lambda:audit_partitions({"train":[b],"calibration":[changed]}))
    checks["empty_source_masks"] = source_graph({"text":"","context":[]}) is None
    checks["oversized_source_masks"] = source_graph({"text":"x"*8193,"context":[]}) is None
    preserved = {"text":"ok","context":[{"speaker":"assistant","text":""},{"speaker":"user","text":"ok"}]}
    checks["empty_observed_turn_preserved"] = len(source_graph(preserved)["nodes"]) == 3
    # Unoptimized mathematical canaries, no fit/update or trained file emitted.
    import hashlib
    import numpy as np
    from day2_multisource_train import labels,initialize,encode_parameters,matrices,forward,supervision,loss_gradient
    from day2_multisource_model import VERSION,compile_bundle,logits,predict,parameter_shapes
    taxonomy_names=labels();cal={h:{"fitted":False,"temperature":1.,"threshold":1.1} for h in taxonomy_names}
    sample=[b,n,t];data=matrices(sample);y,mask,weight,response=supervision(sample)
    for architecture in ("sparse","gnn"):
        p=initialize(architecture);portable={k:v for k,v in p.items() if not k.startswith("next_")}
        model={"version":VERSION,"architecture":architecture,"use_edges":True,"parameters":encode_parameters(portable),"taxonomy":taxonomy_names,"calibration":cal,"qualified":False,"bank_acceptance":False,"authority":"none"}
        raw=json.dumps(model,allow_nan=False).encode();pin=hashlib.sha256(raw).hexdigest();compiled=compile_bundle(raw,pin,taxonomy_names)
        expected,_,_=forward(data,p,architecture);error=max(abs(float(a)-v) for row,full in zip(sample,expected) for a,v in zip(full,logits(inference_input(row),compiled)))
        checks[architecture+":unoptimized_forward_parity"] = error<.0001
        checks[architecture+":bank_always_false"] = all(predict(inference_input(row),compiled)["bank_acceptance"] is False for row in sample)
        checks[architecture+":unknown_calibration_source_abstains"] = all(not h["proposed_labels"] for h in predict(inference_input(b),compiled)["source_proposals"].values())
        shape_count=sum(int(np.prod(s)) for s in parameter_shapes(architecture).values());checks[architecture+":bounded_portable_shape"] = shape_count==(80028 if architecture=="sparse" else 18540)
        if architecture=="gnn":
            _,_,grad=loss_gradient(data,p,architecture,y,mask,weight,response)
            # Finite differences of full multihead + normalized-response objective.
            active=int(np.flatnonzero(np.any(data["x"]!=0,axis=(0,1)))[0])
            for name,index in (("readout",(0,0)),("embedding",(active,1)),("next_readout",(0,3))):
                epsilon=.002;old=float(p[name][index]);p[name][index]=old+epsilon;plus=loss_gradient(data,p,architecture,y,mask,weight,response)[0];p[name][index]=old-epsilon;minus=loss_gradient(data,p,architecture,y,mask,weight,response)[0];p[name][index]=old
                numerical=(plus-minus)/(2*epsilon);checks["gradient:"+name]=abs(numerical-float(grad[name][index]))<.002
        if architecture=="sparse":
            for field,value in (("temperature",0),("temperature",-1),("temperature",float('nan')),("threshold",float('inf')),("threshold",True)):
                bad=copy.deepcopy(model);bad["calibration"]["banking77_intent"][field]=value;blob=json.dumps(bad).encode();badpin=hashlib.sha256(blob).hexdigest()
                rejected("finite_artifact:"+field+":"+str(value),lambda blob=blob,badpin=badpin:compile_bundle(blob,badpin,taxonomy_names))
            rejected("artifact_hash_tamper",lambda:compile_bundle(raw+b' ',pin,taxonomy_names))
            bad=copy.deepcopy(model);bad["parameters"]["bias"]["shape"]=[155];blob=json.dumps(bad).encode()
            rejected("artifact_shape_tamper",lambda:compile_bundle(blob,hashlib.sha256(blob).hexdigest(),taxonomy_names))
            wrong=copy.deepcopy(taxonomy_names);wrong["banking77_intent"][0]="tampered"
            rejected("taxonomy_swap_rejected",lambda:compile_bundle(raw,pin,wrong))
            badp={k:v.copy() for k,v in portable.items()};badp['bias'][0]=float('inf');bad=copy.deepcopy(model);bad['parameters']=encode_parameters(badp);blob=json.dumps(bad).encode()
            rejected("nonfinite_weight_rejected",lambda:compile_bundle(blob,hashlib.sha256(blob).hexdigest(),taxonomy_names))
    unknown=mask.copy();unknown[:,77:139]=0
    p=initialize("sparse");_,_,grad=loss_gradient(data,p,"sparse",y,unknown,weight,response)
    checks["unknown_mask_exact_zero_gradient"] = bool(np.all(grad["readout"][:,77:139]==0) and np.all(grad["bias"][77:139]==0))
    _,_,group_weights,_=supervision(rows)
    tm_group={}
    for row,w in zip(rows,group_weights[:,3]):
        if w:tm_group[row["group_id"]]=tm_group.get(row["group_id"],0)+float(w)
    checks["Taskmaster_equal_24_group_mass"] = len(tm_group)==24 and max(abs(w-1/24) for w in tm_group.values())<1e-7
    assert all(checks.values()), checks
    return {"executed":len(checks),"passed":sum(checks.values()),"checks":checks,"fits":0}


if __name__ == "__main__":
    print(json.dumps(run(),sort_keys=True))
