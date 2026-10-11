"""Actual detector-fed evaluation and reviewed-only candidate training admission.

No new gold labels. Weak frozen author masks are diagnostic, never loss-admitted.
Unmatched candidate validity needs independent whole-turn absence adjudication.
"""
import math
from collections import Counter
from context_v2 import feature_v2,distribution_v2,candidate_spans_v2,ProposalOverflow
from detector_v3 import detect_candidates_v3,align_candidates_v3
from train_v2 import prepare_examples
from context_v2 import tokens_v2
from detector_v3 import clause_ranges_v3
from modal_narrow_core import canonical,digest


def local_candidate_features_v3(snapshot,candidate):
    """Both sides of the actual span, clipped to its actual local clause."""
    text=snapshot["utterance"]["text"]
    clause=next((c for c in clause_ranges_v3(text) if c["start"]<=candidate["start"] and candidate["end"]<=c["end"]),None)
    if clause is None: raise ValueError("Unsupported crossing-clause candidate")
    start=max(clause["start"],candidate["start"]-48)
    end=min(clause["end"],candidate["end"]+48)
    local=dict(snapshot,utterance=dict(snapshot["utterance"],text=text[start:end]))
    rebased=dict(candidate,start=candidate["start"]-start,end=candidate["end"]-start)
    features=feature_v2(local,rebased)
    for token in tokens_v2(text[candidate["end"]:end]):
        features["right:"+token]=1.
    norm=sum(v*v for v in features.values())**.5 or 1.
    return {key:value/norm for key,value in features.items()}


def diagnostics_v3(records,model,split):
    examples,_=prepare_examples(records,split)
    by_id={row["example_id"]:row for row in records}
    detectors={key:detect_candidates_v3(row["input"]["utterance"]["text"],row["input"]["question"]["role"],row["input"]["targets"]) for key,row in by_id.items()}
    counts=Counter(); rows=[]
    for example in examples:
        if example["head"] not in ("component_completion","component_polarity"): continue
        candidate=example["candidate"]; detector=detectors[example["id"]]
        key=(candidate["name"],candidate["start"],candidate["end"])
        exact=next((c for c in detector["candidates"] if (c["kind"],c["start"],c["end"])==key),None)
        try: old=candidate_spans_v2(example["snapshot"])
        except ProposalOverflow: old=[]
        old_match=any((c["name"],c["start"],c["end"])==key for c in old)
        oracle=distribution_v2(model["heads"][example["head"]],example["features"])
        oracle_label=max(oracle,key=oracle.get)
        actual_scores=distribution_v2(model["heads"][example["head"]],feature_v2(example["snapshot"],exact)) if exact and example["snapshot"]["question"]["role"]!="security" else None
        actual_label=max(actual_scores,key=actual_scores.get) if actual_scores else None
        axis=example["head"]
        counts[axis+":annotated_denominator"]+=1
        counts[axis+":oracle_span_correct"]+=int(oracle_label==example["label"])
        counts[axis+":v2_detector_exact"]+=int(old_match)
        counts[axis+":v3_detector_exact"]+=int(exact is not None)
        counts[axis+":pipeline_span_and_axis_correct"]+=int(actual_label==example["label"])
        rows.append({"id":example["id"],"group":example["group"],"axis":axis,"annotated_candidate":candidate,
                     "authored_annotation":example["label"],"oracle_prediction":oracle_label,"v2_exact_detector_match":old_match,
                     "v3_exact_detector_match":exact is not None,"pipeline_prediction_or_miss":actual_label,
                     "author_labels_independent_gold":False,"eligible_for_training":False})
    candidate_count=sum(d["candidate_count"] for d in detectors.values())
    expected={(e["id"],e["candidate"]["name"],e["candidate"]["start"],e["candidate"]["end"]) for e in examples if e["candidate"]}
    unmatched=sum((key,c["kind"],c["start"],c["end"]) not in expected for key,d in detectors.items() for c in d["candidates"])
    return {"records":len(records),"groups":len({r["lineage_group_id"] for r in records}),"counts":dict(counts),"candidate_count":candidate_count,
            "unmatched_to_frozen_authored_spans":unmatched,"unmatched_are_NOT_established_false_positives":True,
            "false_candidate_precision":None,"independent_absent_region_audit_missing":True,
            "source_scope":"Frozen single-author v2 TRAIN/dev already exposed; masks/labels unchanged, not adjudicated gold",
            "target_relation_pipeline_qualified":False,"accepted_semantic_decisions":0,"rows":rows}


def prepare_reviewed_candidate_table_v3(source_rows,review_overlay,lineage_map):
    """Future adjudicated overlays only; no fallback author labels."""
    table=[]; audits=[]
    for record in source_rows:
        if record["split"] not in ("train","dev","development"): raise ValueError("Calibration/qualification cannot enter candidate training")
        review=review_overlay.get(record["example_id"])
        if not review or review.get("independently_adjudicated") is not True or review.get("source_value_free_verified") is not True:
            audits.append({"id":record["example_id"],"reason":"independent_component_or_privacy_review_missing"}); continue
        if review.get("input_sha256") != digest(canonical(record["input"])):
            raise ValueError("Exact reviewed input hash mismatch")
        detector=detect_candidates_v3(record["input"]["utterance"]["text"],record["input"]["question"]["role"],record["input"]["targets"])
        aligned=align_candidates_v3(detector,review["components"],review.get("whole_turn_absence"))
        for row in aligned["rows"]:
            table.append(dict(row,id=record["example_id"],group=lineage_map[record["lineage_group_id"]],split=record["split"],
                              features=local_candidate_features_v3(record["input"],row["candidate"]),annotation_source="parent_verified_independent_adjudication"))
        audits.append({"id":record["example_id"],"missed_component_indices":aligned["missed_reviewed_component_indices"],"unreviewed_candidates":aligned["unreviewed_candidates"]})
    return table,audits


def fit_date_candidates_v3(table,parent_authorization,epochs=80):
    """Mean candidate->example->canonical-group binary CE; current gate closed."""
    if parent_authorization.get("source_review_lineage_hashes_verified") is not True or parent_authorization.get("authorized_cpu_fit") is not True:
        raise ValueError("No independently verified fit authorization")
    rows=[r for r in table if r["split"]=="train" and r["candidate"]["kind"]=="date" and r["validity_mask"] is True and r["validity_label"] is True and r["completion_mask"] is True and r["completion_label"] in ("complete","unfinished")]
    classes={label:{r["group"] for r in rows if r["completion_label"]==label} for label in ("complete","unfinished")}
    if any(len(groups)<20 for groups in classes.values()): raise ValueError("Reviewed date class-group engineering floor closed")
    if epochs != 80: raise ValueError("Frozen bounded date pilot config required")
    groups={}
    for row in rows: groups.setdefault(row["group"],{}).setdefault(row["id"],[]).append(row)
    frequency=Counter(k for examples in groups.values() for k in {key for members in examples.values() for r in members for key in r["features"]})
    vocabulary=sorted(sorted(frequency,key=lambda k:(-frequency[k],k))[:384])
    head={"bias":0.,"weights":dict.fromkeys(vocabulary,0.)}; losses=[]
    for epoch in range(80):
        gradient=dict.fromkeys(vocabulary,0.); bg=0.; loss=0.
        for examples in groups.values():
            for members in examples.values():
                for row in members:
                    z=head["bias"]+sum(head["weights"][k]*row["features"].get(k,0) for k in vocabulary)
                    p=1/(1+math.exp(-max(-32,min(32,z)))); y=int(row["completion_label"]=="complete")
                    scale=1/(len(groups)*len(examples)*len(members)); error=(p-y)*scale
                    bg+=error; loss-=scale*math.log(max(p if y else 1-p,1e-15))
                    for k in vocabulary: gradient[k]+=error*row["features"].get(k,0)
        rate=.7/math.sqrt(1+epoch/10); head["bias"]-=rate*bg
        for k in vocabulary: head["weights"][k]-=rate*(gradient[k]+.0002*head["weights"][k])
        losses.append(loss)
    return {"task":"date_linguistic_completion","head":head,"vocabulary":vocabulary,"qualified":False,"calibrated":False,"decision":"abstain","class_group_counts":{k:len(v) for k,v in classes.items()}},losses
