"""Pure component algebra over independently supplied source-bound rows.

This is an engineering sidecar, never an intent parser, permission or state patch.
Input rows/edges must already have independent semantic provenance. No learned
head presently produces them, so successful algebra is not end-to-end coverage.
"""

def merge_components_v3(text,rows,edges,completion_links,prior_unresolved):
    if type(text) is not str or type(rows) is not list or not rows:
        raise ValueError("Source-bound component rows required")
    by_id={}
    for row in rows:
        rid=row["row_id"]
        if type(rid) is not str or not rid or rid in by_id or type(row["target"]) is not int or type(row["row_complete"]) is not bool:
            raise ValueError("Invalid row identity/target")
        for name,fact in row["facts"].items():
            evidence=row["fact_evidence"][name]; start,end=evidence["start"],evidence["end"]
            if type(start) is not int or type(end) is not int or not 0<=start<end<=len(text):
                raise ValueError("Source span out of bounds")
            if type(fact["value"]) is not str or text[start:end]!=fact["value"] or type(fact["token"]) is not str or not fact["token"]:
                raise ValueError("Source fact/token mismatch")
        if row["explicit_unfinished"]:
            evidence=row["unfinished_evidence"]; start,end=evidence["start"],evidence["end"]
            if type(start) is not int or type(end) is not int or not 0<=start<end<=len(text):
                raise ValueError("Unfinished span out of bounds")
        by_id[rid]=row
    target_ids={row["target"] for row in rows}
    if len(target_ids)!=1:
        raise ValueError("One target patch at a time; cross-target merge forbidden")
    links_by_component={}; retired=set()
    for edge in edges:
        old,new=edge["old"],edge["new"]; component=edge["component"]
        if old not in by_id or new not in by_id or old==new or edge["relation"]!="replacement":
            raise ValueError("Explicit correction endpoints required")
        evidence=edge["evidence"]
        if not 0<=evidence["start"]<evidence["end"]<=len(text):
            raise ValueError("Correction span invalid")
        old_span=by_id[old]["fact_evidence"].get(component,by_id[old].get("unfinished_evidence"))
        new_span=by_id[new]["fact_evidence"].get(component,by_id[new].get("unfinished_evidence"))
        if not old_span or not new_span or not old_span["end"]<=evidence["start"]<evidence["end"]<=new_span["start"]:
            raise ValueError("Correction must follow original speech order")
        links_by_component.setdefault(component,[]).append((old,new))
        retired.add((old,component))
    for link in completion_links:
        a,b=link["from_row"],link["to_row"]; component=link["component"]
        if a not in by_id or b not in by_id or component not in by_id[a]["explicit_unfinished"] or component not in by_id[b]["facts"]:
            raise ValueError("Invalid explicit completion relation")
        if by_id[a]["unfinished_evidence"]["end"]>by_id[b]["fact_evidence"][component]["start"]:
            raise ValueError("Completion must follow open source expression")
    names=set(prior_unresolved)
    for row in rows:
        names.update(row["facts"]); names.update(row["explicit_unfinished"])
    facts={}; unresolved=set(prior_unresolved)
    for component in names:
        pending=set(by_id); links=links_by_component.get(component,[])
        while pending:
            roots={rid for rid in pending if not any(b==rid and a in pending for a,b in links)}
            if not roots: break
            pending-=roots
        if pending:
            unresolved.add(component); continue
        survivors=[row for rid,row in by_id.items() if (rid,component) not in retired]
        open_ids={r["row_id"] for r in survivors if not r["row_complete"] and component in r["explicit_unfinished"]}
        value_rows={r["row_id"]:r["facts"][component]["value"] for r in survivors if component in r["facts"] and component not in r["explicit_unfinished"]}
        values=set(value_rows.values())
        if open_ids or len(values)>1: unresolved.add(component)
        explicitly_filled=all(any(link["from_row"]==rid and link["component"]==component and link["to_row"] in value_rows for link in completion_links) for rid in open_ids)
        if len(values)==1 and explicitly_filled:
            facts[component]=next(iter(values)); unresolved.discard(component)
    return {"target_index":next(iter(target_ids)),"facts":facts,"unresolved_components":sorted(unresolved),
            "diagnosis_only":True,"state_mutations":0,"semantic_producer_qualified":False}
