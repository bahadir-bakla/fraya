"""Official TRAIN-only paired source-spec/annotation loader with explicit masks."""
from collections import Counter
import ast
import hashlib
import json
from pathlib import Path
import numpy as np
from tau_plan_runtime import ROOT, source_text

PACKET = ROOT / "research/customer-benchmark/tau-train"
ANCHOR = "ad60d0e9187c395109774c8ef81e8772eb7dcb18d1a3140ec255f182346be11b"


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def encoded(value): return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def write_new(path, value):
    with Path(path).open("xb") as f: f.write(encoded(value))


def verify(pins):
    for path,h in pins.items():
        if sha(ROOT/path) != h: raise ValueError("Pinned source changed: " + path)


def load_packet():
    if sha(PACKET/"manifest.json") != ANCHOR: raise ValueError("Parent manifest anchor changed")
    manifest = json.loads((PACKET/"manifest.json").read_text(encoding="utf-8"))
    pins = {"research/customer-benchmark/tau-train/manifest.json": ANCHOR}
    for record in manifest["outputs"] + [manifest["collector"],manifest["processor"],manifest["license_file"],manifest["source_manifest"]]: pins[record["path"]] = record["sha256"]
    verify(pins)
    # Structural evidence that every nonempty publisher action list is copied,
    # with no filter/slicing. Empty lists remain unknown because get(... ) or []
    # merges missing/null/empty. This does NOT assert all possible valid actions.
    tree = ast.parse((ROOT/manifest["processor"]["path"]).read_text(encoding="utf-8"))
    assignments = [n for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="actions" for t in n.targets)]
    if len(assignments)!=1: raise ValueError("Unverified action annotation projection")
    comp = assignments[0].value
    if not isinstance(comp,ast.ListComp) or len(comp.generators)!=1 or comp.generators[0].ifs: raise ValueError("Filtered/incomplete reference projection")
    it = comp.generators[0].iter
    if not isinstance(it,ast.BoolOp) or not isinstance(it.op,ast.Or) or ast.unparse(it)!="criteria.get('actions') or []":
        raise ValueError("Unknown annotation completeness provenance")
    specs = [json.loads(l) for l in (PACKET/"train-scenario-specs.jsonl").read_text(encoding="utf-8").splitlines()]
    annotations = {r["id"]:r for r in map(json.loads,(PACKET/"train-publisher-action-annotations.jsonl").read_text(encoding="utf-8").splitlines())}
    if len(specs)!=103 or len(annotations)!=103: raise ValueError("Unexpected official TRAIN count")
    for row in specs:
        a=annotations[row["id"]]
        if row["publisher_partition"]!="TRAIN" or a["publisher_partition"]!="TRAIN" or row["source_task_object_sha256"]!=a["source_task_object_sha256"] or row["group_root"]!=a["group_root"]:
            raise ValueError("TRAIN annotation source mismatch")
        source_text(row["generator_spec"])
        if any(v["mask"] is not False or v["value"] is not None for v in row["financial_target_masks"].values()): raise ValueError("Financial supervision forbidden")
        if type(a["reference_actions"]) is not list or any(type(x["name"]) is not str or not x["name"] for x in a["reference_actions"]): raise ValueError("Malformed literal operation labels")
    groups = sorted(set(r["group_root"] for r in specs)); partition = {}
    for group in groups:
        bucket = int(hashlib.sha256(("tau-plan-group-split-v1:"+group).encode()).hexdigest(),16)%10
        partition[group] = "FIT" if bucket<7 else "CAL" if bucket<9 else "DIAG"
    # Partitions are assigned before the class vocabulary or support is selected.
    labels = sorted(set(x["name"] for r in specs if partition[r["group_root"]]=="FIT" for x in annotations[r["id"]]["reference_actions"]))
    y=np.zeros((len(specs),len(labels)),np.float32); mask=np.zeros_like(y); complete=0
    for i,r in enumerate(specs):
        actions=annotations[r["id"]]["reference_actions"]
        if actions:
            complete+=1;mask[i]=1;names={a["name"] for a in actions}
            y[i]=[float(label in names) for label in labels]
    ix={s:np.array([i for i,r in enumerate(specs) if partition[r["group_root"]]==s],dtype=int) for s in ("FIT","CAL","DIAG")}
    split={s:{"rows":len(v),"groups":len(set(specs[i]["group_root"] for i in v)),"known_elements":int(mask[v].sum())} for s,v in ix.items()}
    unknown_ops=sorted(set(x["name"] for r in specs for x in annotations[r["id"]]["reference_actions"])-set(labels))
    return specs,labels,y,mask,ix,pins,{"partitions":split,"group_assignments":partition,"group_overlap":0,"complete_nonempty_annotation_rows":complete,
        "empty_missing_indistinguishable_rows_all_heads_UNKNOWN":len(specs)-complete,"CAL_DIAG_operations_not_seen_in_FIT":unknown_ops,
        "literal_annotation_completeness_evidence":"Pinned no-filter list comprehension copies entire nonempty publisher list; source task object digest and group match. No unique/all-valid trajectory claim.",
        "official_TEST_loaded":False,"excluded_cross_TEST_TRAIN_templates":1,"source_rows_not_observed_speech":True}
