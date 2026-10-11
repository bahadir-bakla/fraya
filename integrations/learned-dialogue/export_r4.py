"""Export new pure R4 entrypoint with unchanged frozen R3 helper bytes."""
import ast
from pathlib import Path
from export_v3 import export_v3

HERE=Path(__file__).resolve().parent

def stripped_r4(name):
    source=(HERE/name).read_text(encoding="utf-8")
    lines=source.splitlines(); omit=set()
    for node in ast.parse(source).body:
        if isinstance(node,(ast.Import,ast.ImportFrom)): omit.update(range(node.lineno-1,node.end_lineno))
    return "\n".join("    "+line if line else "" for i,line in enumerate(lines) if i not in omit)+"\n"

def export_r4(bundle,schema):
    old,_=export_v3(bundle,schema)
    source=old.decode("utf-8") if type(old) is bytes else old
    start=source.index("    def bound_predict(snapshot, authoritative_binding, independent_source,")
    end=source.index("    return bound_predict",start)
    bodies="".join(stripped_r4(name) for name in ("detector_r4.py","window_r4.py","alignment_r4.py","context_r4.py"))
    wrapper='''    def bound_predict(snapshot,authoritative_binding,independent_source,registry,authoritative_state,source_admission=None,date_bundle=None):
        binding=BindingContext(authoritative_binding,BUNDLE["model_id"])
        if type(independent_source) is not dict:
            raise InputRejected("Independent exact source event required")
        q=independent_source.get("question_identity")
        targets=independent_source.get("target_mapping")
        trusted=TrustedCallV3(binding,independent_source.get("call_local_id"),independent_source.get("source_event_id"),
                              independent_source.get("event_ordinal"),independent_source.get("text"),
                              independent_source.get("complete_transport"),None if q is None else tuple(q),
                              None if targets is None else tuple(tuple(x) for x in targets))
        return predict_r4(snapshot,trusted,registry,authoritative_state,WIRE_SCHEMA,source_admission,date_bundle)
'''
    source=(source[:start]+bodies+wrapper+source[end:]).replace("predict_context_v3_embedded","predict_context_r4_embedded")
    ast.parse(source)
    if len(source.encode("utf-8"))>500000: raise ValueError("Export size gate")
    imports={node.names[0].name for node in ast.walk(ast.parse(source)) if isinstance(node,ast.Import)}
    if imports!={"json","re"} or any(isinstance(n,ast.ImportFrom) for n in ast.walk(ast.parse(source))): raise ValueError("Export import gate")
    return source.encode("utf-8")
