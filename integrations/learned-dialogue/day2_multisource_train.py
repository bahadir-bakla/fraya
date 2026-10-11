"""One freshly authorized, source-pinned CPU experiment. No default fitting.

TRAIN-only gradients, domain-masked labels, group-mean objectives, immutable
pre-EVAL weights/calibration and matched information in graph/no-edge fits.
"""
import argparse
import base64
import hashlib
import json
import math
import threading
import time
from collections import Counter
from pathlib import Path
from day2_multisource_data import ROOT, DATA, MANIFEST_SHA, SPLIT_SHA, HEADS, load_split, taxonomy, sha, inference_input, audit_partitions
from day2_multisource_features import WIDTH, MAX_NODES, RELATIONS, source_graph, sparse, feature_keys
from day2_multisource_model import VERSION, HIDDEN, HEAD_SLICES, parameter_shapes

HERE = Path(__file__).resolve().parent
PLAN = HERE / "day2_multisource_plan.json"
SEED = 20261012


def save(path, value):
    with Path(path).open("x", encoding="utf8") as file:
        json.dump(value, file, sort_keys=True, separators=(",", ":"), allow_nan=False)
        file.write("\n")


def labels():
    taxa = taxonomy()
    return {"banking77_intent": [v["source_label"] for v in taxa["banking77-taxonomy.json"]["labels"]],
            "nlupp_intents": [v["name"] for v in taxa["nlupp-taxonomy.json"]["intents"]],
            "nlupp_slot_presence": [v["name"] for v in taxa["nlupp-taxonomy.json"]["slots"]]}


def partition_digest(partitions):
    return hashlib.sha256(json.dumps(partitions, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def historical():
    if sha(HERE/"day2_model.freeze.json") != "9081a4c4e5b8fd0ed208fcc0c313700f576d266a0970f5fa4b38b5dd8b169b4d" or sha(HERE/"day2_public_freeze_v2.json") != "846904edf6afd341b54f0eb1d1f791bdbe90fa4a65b5882179d08b7e19138830":
        raise ValueError("Historical out-of-band freeze anchor changed")
    old = json.loads((HERE / "day2_model.freeze.json").read_text(encoding="utf8"))
    public = json.loads((HERE / "day2_public_freeze_v2.json").read_text(encoding="utf8"))
    pins = {**old["historical_protected_sha256"], **old["sha256"]}
    for k in ("source_sha256", "input_sha256", "models_sha256", "artifacts_sha256"):
        pins.update(public[k])
    for path in ("day2_model.freeze.json", "day2_public_freeze_v2.json", "day2_public_plan_v2.json", "day2_public_pre_eval_freeze_v2.json"):
        pins[str((HERE/path).relative_to(ROOT)).replace("\\", "/")] = sha(HERE/path)
    return pins


def verify_pins(pins):
    for path, expected in pins.items():
        if sha(ROOT/path) != expected:
            raise ValueError("Pinned code/input/historical drift: " + path)


def support(rows, head):
    a, b = HEAD_SLICES[head]; size = b-a
    result = [{"positive":0, "known_negative":0, "unknown":0} for _ in range(size)]
    for row in rows:
        if not row["head_mask"][head]:
            continue
        y = row["targets"][head]
        mask = row.get("target_element_masks", {}).get(head, [True]*size)
        for k in range(size):
            positive = (y==k) if head=="banking77_intent" else y[k]==1
            result[k]["unknown" if not mask[k] else "positive" if positive else "known_negative"] += 1
    return result


def prepare():
    import numpy as np
    from day2_multisource_test import run
    partitions = {s:load_split(s) for s in SPLIT_SHA}
    audit = audit_partitions(partitions)
    tests = run(partitions["train"])
    source_paths = sorted(HERE.glob("day2_multisource_*.py"))
    inputs = {str(p.relative_to(ROOT)).replace("\\","/"):sha(p) for p in DATA.iterdir() if p.is_file()}
    design = ROOT/"analysis/day2-multisource-gnn-design.json"
    review = ROOT/"analysis/day2-opus-training-engine-review.json"
    for p in (design,review,ROOT/"research/customer-benchmark/day2-training-data/build-v2.py"):
        inputs[str(p.relative_to(ROOT)).replace("\\","/")] = sha(p)
    old = historical(); verify_pins(old)
    available = {}; parity_ids = set(r["record_id"] for r in partitions["eval"])
    for split, rows in partitions.items():
        rejected = [r["record_id"] for r in rows if source_graph(inference_input(r)) is None]
        available[split] = {"rows":len(rows),"unsupported_feature_rows":rejected,"head_support":{h:support(rows,h) for h in HEAD_SLICES}}
    if any(v["unsupported_feature_rows"] for v in available.values()):
        raise ValueError("Unsupported raw source; needs explicitly reviewed plan, no silent clipping")
    # Before scoring: one TRAIN and CAL example per B77 category in addition to ALL EVAL.
    for split in ("train","calibration"):
        for k in range(77):
            matches = [r for r in partitions[split] if r["head_mask"]["banking77_intent"] and r["targets"]["banking77_intent"]==k]
            if not matches: raise ValueError("Missing predeclared parity category")
            parity_ids.add(min(matches,key=lambda r:r["record_id"])["record_id"])
    cal = {}
    for source in audit["partitions"]["calibration"]["sources"]:
        members = [r for r in partitions["calibration"] if r["source_id"]==source]
        cal[source] = {name:{"rows":sum(cal_side(r)==name for r in members),"groups":len({r["group_id"] for r in members if cal_side(r)==name})} for name in ("temperature","threshold")}
    plan = {"version":"day2.multisource.plan.v1","status":"WAIT_NEW_EXACT_HASH_CPU_GRANT","input_sha256":inputs,
            "source_sha256":{str(p.relative_to(ROOT)).replace("\\","/"):sha(p) for p in source_paths},"historical_sha256":old,
            "partition_digest":partition_digest(partitions),"partition_audit":audit,"source_masks":available,"taxonomy":labels(),
            "CAL_subpartitions":cal,"source_checks":tests,"parity_record_ids":sorted(parity_ids),
            "parity_contract":"All EVAL rows plus TRAIN/CAL representative of every B77 class; full logits/probability/threshold parity; full float32 native states retained.",
            "models":["sparse","gnn","no_edges"],"teacher":"Separate Kuhn worker; no teacher/cache/download invoked here",
            "features":{"width":WIDTH,"hidden":HIDDEN,"max_nodes":MAX_NODES,"relations":list(RELATIONS),
                        "matched_pooling":"0.5 whole-turn/context-summary +0.5 designer local readout; identical for G and NoEdges; sparse shares same raw pooling",
                        "runtime_inputs":["text","context.speaker","context.text"],"supervision_features":False,
                        "controls":["no nonself edges","Taskmaster latest-only","Taskmaster past-order reversal","placeholder neutral inference","TRAIN-only placeholder frequency probe"]},
            "optimizer":{"seed":SEED,"epochs":90,"batch_size":128,"lr":.01,"l2_objective":.0005,"algorithm":"Adam; deterministic shuffled TRAIN rows; exact group/source weight with unbiased minibatch scaling","early_stop_or_search":False},
            "objective":"B77 groupCE/log77 +0.5 NLUintent maskedgroupBCE/log2 +0.5 NLUslot maskedgroupBCE/log2 +0.2 Taskmaster group squared-error(normalized512 response hash) +0.0005||weights||^2",
            "resources":{"numpy":np.__version__,"CPU_threads":2,"per_fit_seconds":300,"total_fit_seconds":900,"overall_seconds":1800,"attempts":1,"retries":0,"GPU":False,"network":False,"runtime_plus_bundle_cap_bytes":500000},
            "calibration":{"temperature_grid":[.5,.75,1,1.5,2,3],"B77_threshold_grid":[.4,.5,.6,.7,.8,.9,.95,.99,1.1],"B77_rule":"max coverage with >=30 proposals and observed precision>=.90, tie higher; else1.1","NLU_threshold_grid":[.3,.5,.7,.9,1.1],"NLU_rule":"max maskedmicroF1, tie higher; one threshold per head; no rare-class tuning","groups":"SHA256 literal publisher group_id parity, measured actual counts; may differ from earlier derived B77 union IDs","freeze_before_EVAL":True},
            "known_limits":["Internal exposed publisher TRAIN/fold/shard EVAL; not qualification","Two known contraction cross-split families preserved/disclosed; broader semantic ancestry unknown","Taskmaster24TRAIN/30total closure components are embargo units, not IID","NLU slot-marker leakage: sanitized-domain scores only; controls do not restore raw slot extraction","No bank adaptation, permission, policy values or hidden/live claims"],
            "deployment":{"qualified":False,"bank_acceptance":False,"floor20":"unchanged_closed"}}
    save(PLAN, plan)
    report = {"status":plan["status"],"plan_path":str(PLAN.relative_to(ROOT)),"plan_sha256":sha(PLAN),"partitions":audit,"source_checks":tests,"fit_calls":0,"input_sha256":inputs,"source_sha256":plan["source_sha256"],"CAL_subpartitions":cal,"parity_rows_per_model":len(parity_ids),"historical_bindings_preserved":len(old),"implementation_contract_deltas":plan["features"],"new_fit_requires_parent_exact_hash":True}
    save(ROOT/"analysis/day2-multisource-implementation-preparation.json", report)
    print(json.dumps(report,ensure_ascii=True))


def cal_side(row):
    return "temperature" if int(hashlib.sha256(row["group_id"].encode()).hexdigest()[:8],16)%2==0 else "threshold"


def encode_parameters(p):
    import numpy as np
    return {name:{"shape":list(value.shape),"dtype":"float32-le","base64":base64.b64encode(np.asarray(value,dtype="<f4").tobytes()).decode("ascii")} for name,value in p.items()}


def matrices(rows, edges=True, neutral=False, latest=False):
    import numpy as np
    n=len(rows); x=np.zeros((n,MAX_NODES,WIDTH),dtype=np.float32); linear=np.zeros((n,WIDTH),dtype=np.float32)
    adjacency=np.zeros((len(RELATIONS),n,MAX_NODES,MAX_NODES),dtype=np.float32); pool=np.zeros((n,MAX_NODES),dtype=np.float32)
    for i,row in enumerate(rows):
        g=source_graph(inference_input(row),edges,neutral,latest)
        if g is None: raise ValueError("Unplanned unsupported source")
        for j,node in enumerate(g["nodes"]):
            for k,v in node.items():x[i,j,k]=v
        for k,v in g["linear"].items():linear[i,k]=v
        for a,b,relation in g["edges"]:adjacency[RELATIONS.index(relation),i,b,a]=1
        for j,w in zip(g["readout_nodes"],g["readout_weights"]):pool[i,j]+=w
    count=adjacency.sum(axis=3,keepdims=True); adjacency/=np.maximum(count,1)
    return {"x":x,"linear":linear,"adjacency":adjacency,"pool":pool}


def forward(data,p,architecture):
    import numpy as np
    if architecture=="sparse": rep=data["linear"]; cache=None
    else:
        h0=np.tanh(data["x"]@p["embedding"]+p["embedding_bias"])
        messages=[data["adjacency"][j]@h0 for j in range(len(RELATIONS))]
        h1=np.tanh(h0@p["self"]+sum(m@p[r] for m,r in zip(messages,RELATIONS))+p["message_bias"])
        rep=np.einsum("bn,bnh->bh",data["pool"],h1);cache=(h0,messages,h1)
    return rep@p["readout"]+p["bias"],rep,cache


def initialize(architecture):
    import numpy as np
    rng=np.random.default_rng(SEED); shapes=parameter_shapes(architecture,True)
    p={k:np.zeros(s,dtype=np.float32) for k,s in shapes.items()}
    if architecture=="gnn":
        p["embedding"]=rng.normal(0,.1,shapes["embedding"]).astype(np.float32);p["self"]=np.eye(HIDDEN,dtype=np.float32)
        for r in RELATIONS:p[r]=rng.normal(0,.08,shapes[r]).astype(np.float32)
        p["readout"]=rng.normal(0,.1,shapes["readout"]).astype(np.float32)
    p["next_readout"]=rng.normal(0,.02,shapes["next_readout"]).astype(np.float32)
    return p


def supervision(rows):
    import numpy as np
    n=len(rows); y=np.zeros((n,156),dtype=np.float32);mask=np.zeros_like(y);weights=np.zeros((n,4),dtype=np.float32); response=np.zeros((n,WIDTH),dtype=np.float32)
    for hindex,head in enumerate(HEADS):
        selected=[r for r in rows if r["head_mask"][head]];counts=Counter(r["group_id"] for r in selected)
        for i,row in enumerate(rows):
            if not row["head_mask"][head]:continue
            weights[i,hindex]=1/(len(counts)*counts[row["group_id"]])
            target=row["targets"][head]
            if head=="taskmaster_next_utterance":
                for k,v in sparse(feature_keys(target)).items():response[i,k]=v
            else:
                a,b=HEAD_SLICES[head]
                if head=="banking77_intent":y[i,a+target]=1;mask[i,a:b]=1
                else:y[i,a:b]=target;mask[i,a:b]=row["target_element_masks"][head]
    return y,mask,weights,response


def loss_gradient(data,p,architecture,y,mask,weights,response,scale=1):
    import numpy as np
    z,rep,cache=forward(data,p,architecture); dz=np.zeros_like(z); components={}; normalized=0
    shifted=z[:,:77]-z[:,:77].max(axis=1,keepdims=True); ez=np.exp(shifted);probs=ez/ez.sum(axis=1,keepdims=True)
    ce=-(y[:,:77]*np.log(np.maximum(probs,1e-30))).sum(axis=1);components["banking77_intent"]=float((weights[:,0]*ce).sum())
    dz[:,:77]=(probs-y[:,:77])*weights[:,0,None]/math.log(77)*scale;normalized+=components["banking77_intent"]/math.log(77)
    for index,head in ((1,"nlupp_intents"),(2,"nlupp_slot_presence")):
        a,b=HEAD_SLICES[head];zz=z[:,a:b];mm=mask[:,a:b];den=np.maximum(mm.sum(axis=1),1)
        bce=(np.maximum(zz,0)-zz*y[:,a:b]+np.log1p(np.exp(-np.abs(zz))))
        components[head]=float((weights[:,index]*(bce*mm).sum(axis=1)/den).sum())
        sigmoid=1/(1+np.exp(-np.clip(zz,-80,80)))
        dz[:,a:b]=(sigmoid-y[:,a:b])*mm/den[:,None]*weights[:,index,None]*.5/math.log(2)*scale
        normalized+=.5*components[head]/math.log(2)
    active=np.flatnonzero(weights[:,3]>0);drep=dz@p["readout"].T
    grad={"readout":rep.T@dz,"bias":dz.sum(axis=0),"next_readout":np.zeros_like(p["next_readout"]),"next_bias":np.zeros_like(p["next_bias"])}
    if len(active):
        v=rep[active]@p["next_readout"]+p["next_bias"];norm=np.maximum(np.linalg.norm(v,axis=1,keepdims=True),1e-8);u=v/norm;diff=u-response[active]
        components["taskmaster_next_utterance"]=float((weights[active,3]*(diff*diff).sum(axis=1)).sum())
        du=2*diff*weights[active,3,None]*.2*scale;dv=(du-u*(du*u).sum(axis=1,keepdims=True))/norm
        grad["next_readout"]=rep[active].T@dv;grad["next_bias"]=dv.sum(axis=0);drep[active]+=dv@p["next_readout"].T
    else:components["taskmaster_next_utterance"]=0.
    normalized+=.2*components["taskmaster_next_utterance"]
    if architecture=="gnn":
        h0,messages,h1=cache;dh1=drep[:,None,:]*data["pool"][:,:,None]*(1-h1*h1)
        grad.update(self=h0.reshape(-1,HIDDEN).T@dh1.reshape(-1,HIDDEN),message_bias=dh1.sum(axis=(0,1)))
        dh0=dh1@p["self"].T
        for j,r in enumerate(RELATIONS):
            grad[r]=messages[j].reshape(-1,HIDDEN).T@dh1.reshape(-1,HIDDEN)
            dh0+=np.swapaxes(data["adjacency"][j],1,2)@(dh1@p[r].T)
        de=dh0*(1-h0*h0);grad["embedding"]=data["x"].reshape(-1,WIDTH).T@de.reshape(-1,HIDDEN);grad["embedding_bias"]=de.sum(axis=(0,1))
    return normalized,components,grad


def fit_one(rows,architecture,edges,plan):
    import numpy as np
    start=time.monotonic();data=matrices(rows,edges);y,mask,w,response=supervision(rows);p=initialize(architecture)
    m={k:np.zeros_like(v) for k,v in p.items()};v={k:np.zeros_like(v) for k,v in p.items()};rng=np.random.default_rng(SEED+1);history=[];step=0;fit_start=time.monotonic()
    for epoch in range(plan["optimizer"]["epochs"]):
        components=Counter();loss=0;order=rng.permutation(len(rows))
        for offset in range(0,len(rows),128):
            if time.monotonic()-start>300:
                save(HERE/("day2_multisource_partial."+architecture+(".edges" if edges else ".no_edges")+".json"),{"status":"partial_unscored_no_retry","architecture":architecture,"use_edges":edges,"elapsed":time.monotonic()-start,"completed_epochs":history,"current_epoch":epoch+1,"current_epoch_processed_rows":offset,"parameters":encode_parameters(p),"qualified":False,"plan_sha256":sha(PLAN)})
                raise TimeoutError("Per-fit300s; preserved partial state, no retry")
            ids=order[offset:offset+128];batch={k:a[:,ids] if k=="adjacency" else a[ids] for k,a in data.items()}
            value,parts,g=loss_gradient(batch,p,architecture,y[ids],mask[ids],w[ids],response[ids],len(rows)/len(ids));loss+=value;components.update(parts);step+=1
            for k in p:
                gg=g[k]+(.001*p[k] if "bias" not in k else 0);m[k]=.9*m[k]+.1*gg;v[k]=.999*v[k]+.001*gg*gg
                p[k]-=.01*(m[k]/(1-.9**step))/(np.sqrt(v[k]/(1-.999**step))+1e-8)
        if not all(np.isfinite(a).all() for a in p.values()):raise ValueError("Nonfinite fit; no retry")
        history.append({"epoch":epoch+1,"group_components":dict(components),"weighted_objective_without_L2":loss})
        if epoch%10==9:print(json.dumps({"architecture":architecture,"edges":edges,"epoch":epoch+1,"seconds":time.monotonic()-start,"objective":loss}),flush=True)
    return p,{"epochs":len(history),"preprocess_fit_seconds":time.monotonic()-start,"optimizer_seconds":time.monotonic()-fit_start,"epoch_losses":history,"rows":len(rows),"CPU_threads":2}


def fit(approved):
    if type(approved) is not str or sha(PLAN)!=approved:raise ValueError("New exact-hash parent CPU grant required")
    plan=json.loads(PLAN.read_text(encoding="utf8"));verify_pins({**plan["source_sha256"],**plan["input_sha256"],**plan["historical_sha256"]})
    import numpy as np
    from threadpoolctl import threadpool_limits
    if np.__version__!=plan["resources"]["numpy"]:raise ValueError("Runtime version drift")
    partitions={s:load_split(s) for s in SPLIT_SHA}
    if partition_digest(partitions)!=plan["partition_digest"]:raise ValueError("Source masks/group/split drift")
    # Consume this experiment attempt before optimization. Restart/replay cannot
    # refit under the same approval, even after a failure or partial output.
    attempt=HERE/"day2_multisource_attempt.json"
    if attempt.exists() or list(HERE.glob('day2_multisource_state.*.json')) or list(HERE.glob('day2_multisource_model.*.json')):
        raise ValueError("This experiment was already attempted; no replay/refit")
    save(attempt,{"approved_plan_sha256":approved,"attempt":1,"status":"started","GPU":False,"network":False,"bank_acceptance":False})
    import _thread
    started=time.monotonic();timer=threading.Timer(1800,_thread.interrupt_main);timer.daemon=True;timer.start();outputs={}
    from day2_multisource_eval import calibrate, evaluate, fit_placeholder_probe
    try:
        with threadpool_limits(limits=2):
            for name,architecture,edges in (("sparse","sparse",True),("gnn","gnn",True),("no_edges","gnn",False)):
                if time.monotonic()-started>900:raise TimeoutError("Fit/CAL900s exhausted")
                p,history=fit_one(partitions["train"],architecture,edges,plan)
                state=HERE/("day2_multisource_state."+name+".json");save(state,{"architecture":architecture,"use_edges":edges,"parameters":encode_parameters(p),"training_only":True,"approved_plan_sha256":approved})
                calibration=calibrate(partitions["calibration"],p,architecture,edges,plan)
                portable={k:v for k,v in p.items() if not k.startswith("next_")}
                bundle={"version":VERSION,"architecture":architecture,"use_edges":edges,"parameters":encode_parameters(portable),"taxonomy":plan["taxonomy"],"calibration":calibration,"qualified":False,"bank_acceptance":False,"authority":"none","approved_plan_sha256":approved,"source_notices":"Three public CC-BY-4.0 sources; frozen dataset NOTICE/license; no bank mapping"}
                path=HERE/("day2_multisource_model."+name+".json");save(path,bundle)
                size=path.stat().st_size+sum((HERE/f).stat().st_size for f in ("day2_multisource_model.py","day2_multisource_features.py"))
                if size>500000:raise ValueError("Actual runtime+model exceeds500KB")
                outputs[name]={"model_path":str(path.relative_to(ROOT)).replace("\\","/"),"model_sha256":sha(path),"native_state_path":str(state.relative_to(ROOT)).replace("\\","/"),"native_state_sha256":sha(state),"runtime_plus_model_bytes":size,"training":history,"p":p,"architecture":architecture,"edges":edges}
            probe=fit_placeholder_probe(partitions["train"]);probe_path=HERE/"day2_multisource_placeholder_probe.json";save(probe_path,probe)
            pre={"approved_plan_sha256":approved,"models":{n:{k:v for k,v in d.items() if k.endswith("sha256") or k.endswith("path")} for n,d in outputs.items()},"probe_sha256":sha(probe_path),"calibration_frozen":True,"EVAL_started":False}
            save(HERE/"day2_multisource_pre_eval_freeze.json",pre)
            evaluate(partitions,outputs,plan,approved,time.monotonic()-started,probe)
    except BaseException as error:
        save(ROOT/"analysis/day2-multisource-failure.json",{"status":"failed_or_partial_no_retry","error_type":type(error).__name__,"error":str(error),"elapsed":time.monotonic()-started,"approved_plan_sha256":approved,"completed_models":{n:{k:v for k,v in d.items() if k!="p"} for n,d in outputs.items()},"qualified":False})
        raise
    finally:timer.cancel()


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--prepare",action="store_true");parser.add_argument("--fit",action="store_true");parser.add_argument("--approved-plan-sha");args=parser.parse_args()
    if args.prepare and not args.fit:prepare()
    elif args.fit and not args.prepare:fit(args.approved_plan_sha)
    else:parser.error("Explicit prepare OR newly-authorized fit required")
