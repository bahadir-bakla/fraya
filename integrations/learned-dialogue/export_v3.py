"""Lossless new shadow runtime export; frozen v2 source/export remain untouched."""
import ast
import hashlib
import json
from pathlib import Path
from export_v2 import export_v2

HERE=Path(__file__).resolve().parent


def body_without_imports(path):
    source=path.read_text(encoding="utf-8")
    removed=set()
    for node in ast.parse(source).body:
        if isinstance(node,(ast.Import,ast.ImportFrom)):
            removed.update(range(node.lineno,node.end_lineno+1))
    return "\n".join(line for i,line in enumerate(source.splitlines(),1) if i not in removed)


def export_v3(bundle,schema):
    source,old_report=export_v2(bundle)
    start=source.index("    def bound_predict(snapshot, authoritative_binding):")
    end=source.index("    return bound_predict",start)+len("    return bound_predict")
    additions="\n".join(body_without_imports(HERE/name) for name in ("reference_v3.py","detector_v3.py","guard_v3.py","context_v3.py"))
    text=json.dumps(schema,separators=(",",":"),allow_nan=False).replace("{","~L~").replace("}","~R~")
    additions += "\nWIRE_SCHEMA = json.loads("+repr(text)+".replace('~L~',chr(123)).replace('~R~',chr(125)))\n"
    additions += '''
def bound_predict(snapshot, authoritative_binding, independent_source, registry, authoritative_state, include_context=True, security_fields=None):
    context=BindingContext(authoritative_binding,BUNDLE["model_id"])
    q=independent_source.get("question_identity")
    targets=independent_source.get("target_mapping")
    trusted=TrustedCallV3(context,independent_source["call_local_id"],independent_source["source_event_id"],independent_source["event_ordinal"],independent_source["text"],independent_source["complete_transport"],tuple(q) if q is not None else None,tuple(tuple(t) for t in targets) if targets is not None else None)
    return predict_v3(snapshot,BUNDLE,trusted,registry,authoritative_state,WIRE_SCHEMA,include_context,security_fields)
return bound_predict
'''
    source=source[:start]+"\n".join("    "+line if line else "" for line in additions.splitlines())+source[end:]
    source=source.replace("predict_context_embedded =", "predict_context_v3_embedded =")
    blob=source.encode("utf-8")
    if len(blob)>500000: raise ValueError("New export exceeds500000UTF8bytes")
    imports={alias.name for node in ast.walk(ast.parse(source)) if isinstance(node,ast.Import) for alias in node.names}
    if imports!={"json","re"}: raise ValueError("Unqualified runtime imports")
    return blob,{"utf8_bytes":len(blob),"sha256":hashlib.sha256(blob).hexdigest(),"coefficient_count":old_report["coefficient_count"],"runtime_imports":sorted(imports),"qualified":False,"model_id":bundle["model_id"]}
