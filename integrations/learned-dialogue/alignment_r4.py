"""Independent reviewed annotations align ONLY by exact kind/start/end."""
from window_r4 import date_features_r4

def align_date_r4(snapshot,detector,source_annotations=None,source_admission=None,reviewed_negative_regions=None):
    annotations=source_annotations or []; negatives=reviewed_negative_regions or []
    rows=[]; matched=set()
    for candidate in detector["candidates"]:
        key=("date",candidate["start"],candidate["end"])
        hits=[(i,a) for i,a in enumerate(annotations) if (a.get("kind"),a.get("start"),a.get("end"))==key]
        feature=date_features_r4(snapshot,candidate,source_admission)
        row={"candidate":candidate,"features":feature,"validity_label":None,"validity_mask":False,
             "completion_label":None,"completion_mask":False,"polarity_label":None,"polarity_mask":False,
             "reference_mask":False,"normalization_mask":False,"reason":"unreviewed_candidate"}
        if len(hits)==1:
            i,ann=hits[0]; matched.add(i)
            if ann.get("independently_adjudicated") is True and ann.get("presence_mask") is True:
                row.update(validity_label=ann.get("valid_date") is True,validity_mask=True,reason="matched_independent_source_annotation")
                if ann.get("valid_date") is True and ann.get("completion_mask") is True and ann.get("completion") in {"complete","unfinished"} and feature["eligible"]:
                    row.update(completion_label=ann["completion"],completion_mask=True)
                if ann.get("polarity_mask") is True:
                    row.update(polarity_label=ann.get("polarity"),polarity_mask=True)
                # Reference and normalization need separate independent checks.
                row["reference_mask"]=ann.get("reference_verified") is True
                row["normalization_mask"]=ann.get("normalization_verified") is True
            else: row["reason"]="source_annotation_unqualified_or_ambiguous"
        elif len(hits)>1: row["reason"]="source_boundary_disagreement"
        elif any(r.get("independently_adjudicated") is True and r.get("kind")=="date" and r.get("date_absent") is True and r["start"]<=candidate["start"]<candidate["end"]<=r["end"] for r in negatives):
            row.update(validity_label=False,validity_mask=True,reason="independently_reviewed_absent_region")
        rows.append(row)
    return {"rows":rows,"missed_source_annotation_indices":[i for i in range(len(annotations)) if i not in matched],
            "source_annotation_count":len(annotations),"unmatched_candidates":sum(r["reason"]=="unreviewed_candidate" for r in rows),
            "no_nearest_span_labels":True,"no_absence_from_no_candidate":True,
            "no_actual_review_admission_claim":not any(r["completion_mask"] for r in rows)}
