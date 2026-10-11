"""CAL-only calibration, followed by a single frozen internal EVAL aggregate.

Unknown target elements never enter metric denominators. Source intent, slot
presence and observed response similarity cannot authorize banking actions.
"""
import copy
import hashlib
import json
import math
import time
from collections import defaultdict
from day2_multisource_data import ROOT, inference_input, sha, audit_partitions
from day2_multisource_features import sparse, feature_keys
from day2_multisource_model import HEAD_SLICES, compile_bundle, logits, head_probabilities, predict


def probabilities(z,head,temperature=1):
    import numpy as np
    a,b=HEAD_SLICES[head];z=z[:,a:b]/temperature
    if head=="banking77_intent":
        z=z-z.max(axis=1,keepdims=True);e=np.exp(z);return e/e.sum(axis=1,keepdims=True)
    return 1/(1+np.exp(-np.clip(z,-80,80)))


def source_logits(rows,p,architecture,edges,**controls):
    import numpy as np
    from day2_multisource_train import matrices,forward
    values=[];reps=[]
    for offset in range(0,len(rows),128):
        data=matrices(rows[offset:offset+128],edges,**controls);z,rep,_=forward(data,p,architecture);values.append(z);reps.append(rep)
    return np.concatenate(values),np.concatenate(reps)


def targets(rows,head):
    import numpy as np
    a,b=HEAD_SLICES[head];n=len(rows)
    if head=="banking77_intent":return np.array([r["targets"][head] for r in rows]),None
    return np.array([r["targets"][head] for r in rows]),np.array([r["target_element_masks"][head] for r in rows],dtype=bool)


def head_loss(p,y,mask):
    import numpy as np
    if mask is None:return -np.log(np.maximum(p[np.arange(len(y)),y],1e-30))
    value=-(y*np.log(np.maximum(p,1e-30))+(1-y)*np.log(np.maximum(1-p,1e-30)))
    return (value*mask).sum(axis=1)/np.maximum(mask.sum(axis=1),1)


def binary_metrics(p,y,mask,threshold,names):
    import numpy as np
    pred=p>=threshold;truth=y.astype(bool);tp=(pred&truth&mask).sum(axis=0);fp=(pred&~truth&mask).sum(axis=0);fn=(~pred&truth&mask).sum(axis=0)
    denom=2*tp+fp+fn;f1=np.divide(2*tp,denom,out=np.zeros(len(names),dtype=float),where=denom>0)
    known=mask.sum(axis=0);supported=known>0;row_known=np.maximum(mask.sum(axis=1),1)
    per_label={names[k]:{"positive":int((truth[:,k]&mask[:,k]).sum()),"known_negative":int((~truth[:,k]&mask[:,k]).sum()),"unknown":int((~mask[:,k]).sum()),"TP":int(tp[k]),"FP":int(fp[k]),"FN":int(fn[k]),"F1":float(f1[k]) if supported[k] else None} for k in range(len(names))}
    return {"rows":len(y),"known_elements":int(mask.sum()),"unknown_elements":int((~mask).sum()),"threshold":threshold,
            "micro_F1":float(2*tp.sum()/max(1,denom.sum())),"macro_F1_known_classes":float(f1[supported].mean()) if supported.any() else None,
            "precision":float(tp.sum()/max(1,tp.sum()+fp.sum())),"recall":float(tp.sum()/max(1,tp.sum()+fn.sum())),
            "known_subset_accuracy":float(np.all((pred==truth)|~mask,axis=1).mean()),"mean_masked_BCE":float(head_loss(p,y,mask).mean()),
            "mean_known_labels_per_row":float(row_known.mean()),"per_label":per_label,"zero_positive_classes":[names[k] for k in range(len(names)) if not (truth[:,k]&mask[:,k]).any()],"qualified":False}


def group_mean(rows,values):
    groups=defaultdict(list)
    for row,value in zip(rows,values):groups[row["group_id"]].append(float(value))
    return sum(sum(v)/len(v) for v in groups.values())/len(groups)


def peak_working_set_bytes():
    """Read only this process's memory counter; unavailable stays None."""
    try:
        import ctypes
        from ctypes import wintypes
        class Memory(ctypes.Structure):
            _fields_=[("cb",wintypes.DWORD),("PageFaultCount",wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in ("PeakWorkingSetSize","WorkingSetSize","QuotaPeakPagedPoolUsage","QuotaPagedPoolUsage","QuotaPeakNonPagedPoolUsage","QuotaNonPagedPoolUsage","PagefileUsage","PeakPagefileUsage")]
        value=Memory();value.cb=ctypes.sizeof(value)
        ok=ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(-1),ctypes.byref(value),value.cb)
        return int(value.PeakWorkingSetSize) if ok else None
    except (AttributeError,OSError,ImportError):
        return None


def calibrate(rows,p,architecture,edges,plan):
    import numpy as np
    from day2_multisource_train import cal_side
    if any(r["split"]!="calibration" for r in rows):raise ValueError("CAL-only input required")
    result={}
    for head in HEAD_SLICES:
        selected=[r for r in rows if r["head_mask"][head]];z,_=source_logits(selected,p,architecture,edges);y,mask=targets(selected,head)
        fit=np.array([cal_side(r)=="temperature" for r in selected]);choose=~fit
        fit_groups={r["group_id"] for r,flag in zip(selected,fit) if flag};select_groups={r["group_id"] for r,flag in zip(selected,choose) if flag}
        if fit_groups&select_groups or not fit.any() or not choose.any():raise ValueError("CAL group separation/coverage")
        sweep=[]
        for temperature in plan["calibration"]["temperature_grid"]:
            prob=probabilities(z[fit],head,temperature);loss=head_loss(prob,y[fit],None if mask is None else mask[fit])
            sweep.append({"temperature":temperature,"masked_group_loss":group_mean([r for r,f in zip(selected,fit) if f],loss)})
        temperature=min(sweep,key=lambda d:(d["masked_group_loss"],d["temperature"]))["temperature"]
        prob=probabilities(z[choose],head,temperature); yy=y[choose]; mm=None if mask is None else mask[choose];threshold_sweep=[]
        if head=="banking77_intent":
            confidence=prob.max(axis=1);correct=prob.argmax(axis=1)==yy;eligible=[]
            for threshold in plan["calibration"]["B77_threshold_grid"]:
                yes=confidence>=threshold;n=int(yes.sum());precision=float(correct[yes].mean()) if n else None
                threshold_sweep.append({"threshold":threshold,"proposed":n,"precision":precision,"coverage":float(yes.mean())})
                if n>=30 and precision>=.90:eligible.append((n,threshold))
            threshold=max(eligible)[1] if eligible else 1.1
        else:
            for threshold in plan["calibration"]["NLU_threshold_grid"]:
                m=binary_metrics(prob,yy,mm,threshold,plan["taxonomy"][head]);threshold_sweep.append({"threshold":threshold,"micro_F1":m["micro_F1"],"precision":m["precision"],"recall":m["recall"]})
            threshold=max(threshold_sweep,key=lambda d:(d["micro_F1"],d["threshold"]))["threshold"]
        result[head]={"fitted":True,"temperature":temperature,"threshold":threshold,"temperature_rows":int(fit.sum()),"threshold_rows":int(choose.sum()),"group_overlap":len(fit_groups&select_groups),"temperature_grid":sweep,"threshold_grid":threshold_sweep,"EVAL_used":False,"statistical_guarantee":False,
                      "unknown_calibration_labels":[plan["taxonomy"][head][k] for k in range(len(plan["taxonomy"][head])) if mask is not None and not ((yy[:,k]==1)&mm[:,k]).any()]}
    return result


def classification_metrics(rows,z,head,calibration,names):
    import numpy as np
    y,mask=targets(rows,head);p=probabilities(z,head,calibration["temperature"]);loss=head_loss(p,y,mask)
    if head!="banking77_intent":
        return {**binary_metrics(p,y,mask,calibration["threshold"],names),"fixed_half":binary_metrics(p,y,mask,.5,names),"groups":len({r["group_id"] for r in rows}),"group_mean_loss":group_mean(rows,loss)}
    pred=p.argmax(axis=1);correct=pred==y;accept=p.max(axis=1)>=calibration["threshold"];per_class={};f1=[];precisions=[]
    for k,name in enumerate(names):
        tp=int(((pred==k)&(y==k)).sum());fp=int(((pred==k)&(y!=k)).sum());fn=int(((pred!=k)&(y==k)).sum());f1.append(2*tp/max(1,2*tp+fp+fn));precisions.append(tp/max(1,tp+fp))
        per_class[name]={"support":int((y==k).sum()),"TP":tp,"FP":fp,"FN":fn,"selected":int((accept&(pred==k)).sum()),"selected_correct":int((accept&(pred==k)&correct).sum())}
    return {"rows":len(rows),"groups":len({r["group_id"] for r in rows}),"accuracy":float(correct.mean()),"macro_F1":sum(f1)/len(f1),"macro_precision":sum(precisions)/len(precisions),"CE":float(loss.mean()),"group_mean_loss":group_mean(rows,loss),"source_threshold":calibration["threshold"],"selected":int(accept.sum()),"selected_correct":int((accept&correct).sum()),"source_precision":float(correct[accept].mean()) if accept.any() else None,"source_coverage":float(accept.mean()),"source_abstention":float((~accept).mean()),"per_class":per_class,"correct_by_record":{r["record_id"]:bool(v) for r,v in zip(rows,correct)},"bank_acceptance":0,"qualified":False}


def taskmaster_metrics(rows,rep,p):
    import numpy as np
    response=rep@p["next_readout"]+p["next_bias"];response/=np.maximum(np.linalg.norm(response,axis=1,keepdims=True),1e-8)
    gold=np.zeros_like(response)
    for i,row in enumerate(rows):
        for k,v in sparse(feature_keys(row["targets"]["taskmaster_next_utterance"])).items():gold[i,k]=v
    cos=(response*gold).sum(axis=1);mse=((response-gold)**2).sum(axis=1)
    return {"rows":len(rows),"groups":len({r["group_id"] for r in rows}),"group_mean_cosine":group_mean(rows,cos),"group_mean_squared_error":group_mean(rows,mse),"row_mean_cosine":float(cos.mean()),"response_gold":"actual sanitized observed next assistant utterance hash; not reward/generation/policy gold","qualified":False}


def fit_placeholder_probe(train):
    """TRAIN-only frequency control, not a slot extractor or extra neural fit."""
    import re
    selected=[r for r in train if r["head_mask"]["nlupp_slot_presence"]];bins={str(k):{"positive":[0.]*17,"known":[0.]*17} for k in range(3)};counts=defaultdict(int)
    for r in selected:counts[r["group_id"]]+=1
    for r in selected:
        key=str(min(2,len(re.findall(r"\[REDACTED_ENTITY\]",r["text"]))));weight=1/counts[r["group_id"]]
        for k,(y,m) in enumerate(zip(r["targets"]["nlupp_slot_presence"],r["target_element_masks"]["nlupp_slot_presence"])):
            if m:bins[key]["positive"][k]+=weight*y;bins[key]["known"][k]+=weight
    for v in bins.values():v["probabilities"]=[(p+.5)/(n+1) for p,n in zip(v["positive"],v["known"])]
    return {"TRAIN_only":True,"feature":"capped sanitized REDACTED_ENTITY count0/1/2plus","bins":bins,"threshold":.5,"qualified":False}


def evaluate(partitions,outputs,plan,approved,fit_seconds,probe):
    import numpy as np
    import re
    from day2_multisource_train import save, verify_pins
    verify_pins({**plan["source_sha256"],**plan["input_sha256"],**plan["historical_sha256"]})
    report={"version":"day2.multisource.results.v1","approved_plan_sha256":approved,"status":"actual_fitted_auxiliary_only","partition_audit":audit_partitions(partitions),"fit_save_CAL_seconds":fit_seconds,"models":{},"GPU_USD":0,"qualified":False,"bank_acceptance":0,"limitations":plan["known_limits"]}
    evals=partitions["eval"];parity_ids=set(plan["parity_record_ids"]);allrows=sum(partitions.values(),[]);parity_rows=[r for r in allrows if r["record_id"] in parity_ids]
    for name,info in outputs.items():
        path=ROOT/info["model_path"]
        if sha(path)!=info["model_sha256"] or sha(ROOT/info["native_state_path"])!=info["native_state_sha256"]:raise ValueError("Pre-EVAL model hash changed")
        compiled=compile_bundle(path.read_bytes(),info["model_sha256"],plan["taxonomy"]);p=info["p"];architecture=info["architecture"];edges=info["edges"]
        model_report={k:v for k,v in info.items() if k!="p"};model_report["metrics"]={}
        for split,rows in partitions.items():
            source_report={}
            for head in HEAD_SLICES:
                selected=[r for r in rows if r["head_mask"][head]];z,_=source_logits(selected,p,architecture,edges)
                source_report[head]=classification_metrics(selected,z,head,compiled["calibration"][head],plan["taxonomy"][head])
            tm=[r for r in rows if r["head_mask"]["taskmaster_next_utterance"]];_,rep=source_logits(tm,p,architecture,edges)
            source_report["taskmaster_next_utterance"]=taskmaster_metrics(tm,rep,p);model_report["metrics"][split]=source_report
        model_report["calibration"]=compiled["calibration"]
        nlu=[r for r in evals if r["head_mask"]["nlupp_slot_presence"]];neutral_z,_=source_logits(nlu,p,architecture,edges,neutral=True)
        model_report["NLU_placeholder_neutral_inference_control"]={h:classification_metrics(nlu,neutral_z,h,compiled["calibration"][h],plan["taxonomy"][h]) for h in ("nlupp_intents","nlupp_slot_presence")}
        tm=[r for r in evals if r["head_mask"]["taskmaster_next_utterance"]];controls={}
        _,rep=source_logits(tm,p,architecture,edges,latest=True);controls["latest_only"]=taskmaster_metrics(tm,rep,p)
        reversed_rows=copy.deepcopy(tm)
        for row in reversed_rows:row["context"]=list(reversed(row["context"][:-1]))+row["context"][-1:]
        _,rep=source_logits(reversed_rows,p,architecture,edges);controls["past_order_reversal"]=taskmaster_metrics(tm,rep,p)
        model_report["Taskmaster_context_controls"]=controls
        parity_z,_=source_logits(parity_rows,p,architecture,edges);maxlog=maxprob=0.;decoder=flips=0;seen=set();min_margin=min_threshold_gap=float('inf')
        for row,full in zip(parity_rows,parity_z):
            snapshot=inference_input(row);export=logits(snapshot,compiled);maxlog=max(maxlog,max(abs(float(a)-b) for a,b in zip(full,export)))
            pp=head_probabilities(export,compiled["calibration"])
            for head in HEAD_SLICES:
                fp=probabilities(full[None,:],head,compiled["calibration"][head]["temperature"])[0];maxprob=max(maxprob,max(abs(float(a)-b) for a,b in zip(fp,pp[head])))
                if head=="banking77_intent":
                    decoder+=int(np.argmax(fp)!=max(range(77),key=lambda i:pp[head][i]));t=compiled["calibration"][head]["threshold"];flips+=int((float(fp.max())>=t)!=(max(pp[head])>=t));order=sorted(fp);min_margin=min(min_margin,float(order[-1]-order[-2]));min_threshold_gap=min(min_threshold_gap,abs(float(fp.max())-t))
                else:flips+=sum((float(a)>=compiled["calibration"][head]["threshold"])!=(b>=compiled["calibration"][head]["threshold"]) for a,b in zip(fp,pp[head]))
            if row["head_mask"]["banking77_intent"]:seen.add(row["targets"]["banking77_intent"])
            assert predict(snapshot,compiled)["bank_acceptance"] is False
        assert seen==set(range(77)) and maxlog<.001 and maxprob<.0001 and not decoder and not flips
        model_report["parity"]={"rows":len(parity_rows),"all_EVAL_rows":len(evals),"B77_classes":len(seen),"max_logit_error":maxlog,"max_probability_error":maxprob,"top1_decoder_mismatches":decoder,"threshold_flips":flips,"smallest_B77_top1_margin":min_margin,"smallest_B77_threshold_distance":min_threshold_gap,"full_native_state_persisted":True}
        samples=parity_rows[:100];timings=[]
        for row in samples:
            start=time.perf_counter();predict(inference_input(row),compiled);timings.append((time.perf_counter()-start)*1000)
        model_report["latency_ms"]={str(q):float(np.percentile(timings,q)) for q in (50,95,99)}
        report["models"][name]=model_report
    g=report["models"]["gnn"]["metrics"]["eval"]["banking77_intent"]["correct_by_record"];n=report["models"]["no_edges"]["metrics"]["eval"]["banking77_intent"]["correct_by_record"]
    report["matched_edge_disagreements"]={"G_only_correct":sum(g[k] and not n[k] for k in g),"NoEdges_only_correct":sum(n[k] and not g[k] for k in g),"same_information_pooling":True,"qualification":False}
    nlu=[r for r in evals if r["head_mask"]["nlupp_slot_presence"]];pred=np.array([probe["bins"][str(min(2,len(re.findall(r"\[REDACTED_ENTITY\]",r["text"]))))]["probabilities"] for r in nlu]);y,mask=targets(nlu,"nlupp_slot_presence")
    report["TRAIN_fitted_placeholder_only_slot_probe"]=binary_metrics(pred,y,mask,.5,plan["taxonomy"]["nlupp_slot_presence"])
    report["peak_current_process_working_set_bytes"]=peak_working_set_bytes()
    verify_pins({**plan["source_sha256"],**plan["input_sha256"],**plan["historical_sha256"]})
    path=ROOT/"analysis/day2-multisource-model-experiment.json";save(path,report)
    text_path=ROOT/"analysis/day2-multisource-model-experiment.txt"
    lines=["Actual three-source CPU auxiliary experiment; no bank authority/qualification.","Plan SHA256 "+approved]
    for name,m in report["models"].items():
        b=m["metrics"]["eval"]["banking77_intent"];ni=m["metrics"]["eval"]["nlupp_intents"];ns=m["metrics"]["eval"]["nlupp_slot_presence"];tm=m["metrics"]["eval"]["taskmaster_next_utterance"]
        lines.append("%s B77 %.4f accuracy/%.4f source precision/%.4f coverage; NLU intents %.4f microF1, slots %.4f microF1; TM groupedcos %.4f; runtime+weights %dbytes"%(name,b['accuracy'],b['source_precision'] or 0,b['source_coverage'],ni['micro_F1'],ns['micro_F1'],tm['group_mean_cosine'],m['runtime_plus_model_bytes']))
    lines+=report['limitations']
    with text_path.open('x',encoding='utf8') as file:file.write('\n'.join(lines)+'\n')
    probe_path=ROOT/'integrations/learned-dialogue/day2_multisource_placeholder_probe.json';pre_path=ROOT/'integrations/learned-dialogue/day2_multisource_pre_eval_freeze.json'
    freeze={"approved_plan_sha256":approved,"source_sha256":plan["source_sha256"],"input_sha256":plan["input_sha256"],"historical_sha256":plan["historical_sha256"],"artifacts_sha256":{str(p.relative_to(ROOT)).replace("\\","/"):sha(p) for p in (path,text_path,probe_path,pre_path)},"models":{name:{k:v for k,v in info.items() if k.endswith("sha256") or k.endswith("path")} for name,info in outputs.items()},"qualified":False,"bank_acceptance":False}
    save(ROOT/"integrations/learned-dialogue/day2_multisource_freeze.json",freeze)
    print(json.dumps({"status":report["status"],"report_path":str(path.relative_to(ROOT)),"report_sha256":sha(path),"fits":3,"qualified":False}),flush=True)
