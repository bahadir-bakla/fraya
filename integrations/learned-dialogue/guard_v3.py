"""Pure structural output guard; supported json/re/builtins only."""
import re


def schema_errors_v3(value,schema,root=None,path="$"):
    root=root or schema
    if "$ref" in schema:
        node=root
        for name in schema["$ref"].split("/")[1:]: node=node[name]
        return schema_errors_v3(value,node,root,path)
    if "anyOf" in schema:
        return [] if any(not schema_errors_v3(value,choice,root,path) for choice in schema["anyOf"]) else [path+":anyOf"]
    if "enum" in schema and not any(type(value) is type(item) and value==item for item in schema["enum"]): return [path+":enum"]
    kind=schema.get("type")
    valid={"object":type(value) is dict,"array":type(value) is list,"string":type(value) is str,
           "integer":type(value) is int,"number":type(value) in (int,float) and -float("inf")<value<float("inf"),
           "null":value is None,"boolean":type(value) is bool}.get(kind,True)
    if not valid: return [path+":type_or_nonfinite"]
    errors=[]
    if kind=="object":
        properties=schema.get("properties",{})
        errors += [path+":missing:"+key for key in schema.get("required",[]) if key not in value]
        if schema.get("additionalProperties") is False: errors += [path+":extra:"+key for key in value if key not in properties]
        for key,item in value.items():
            if key in properties: errors += schema_errors_v3(item,properties[key],root,path+"."+key)
    if kind=="array":
        if not schema.get("minItems",0)<=len(value)<=schema.get("maxItems",len(value)): errors.append(path+":size")
        if schema.get("uniqueItems") and any(item in value[:i] for i,item in enumerate(value)): errors.append(path+":duplicate")
        for i,item in enumerate(value): errors += schema_errors_v3(item,schema.get("items",{}),root,path+"["+str(i)+"]")
    if kind=="string":
        if not schema.get("minLength",0)<=len(value)<=schema.get("maxLength",len(value)): errors.append(path+":length")
        if schema.get("pattern") and re.search(schema["pattern"],value) is None: errors.append(path+":pattern")
    if kind in ("number","integer"):
        if value<schema.get("minimum",value) or value>schema.get("maximum",value): errors.append(path+":range")
    return errors


def wire_errors_v3(proposal,snapshot,schema):
    errors=schema_errors_v3(proposal,schema)
    text=snapshot.get("utterance",{}).get("text","")
    indices={target["index"] for target in snapshot.get("targets",[]) if type(target) is dict and type(target.get("index")) is int}
    def walk(value):
        if type(value) is dict:
            if set(value)=={"turn_id","start","end","role"}:
                if value["turn_id"]!=snapshot.get("turn_id") or type(value["start"]) is not int or type(value["end"]) is not int or not 0<=value["start"]<value["end"]<=len(text): errors.append("invalid_source_span")
            for item in value.values(): walk(item)
        elif type(value) is list:
            for item in value: walk(item)
    walk(proposal)
    clauses=proposal.get("clauses",[])
    ids=[clause.get("clause_id") for clause in clauses]
    if len(ids)!=len(set(ids)): errors.append("duplicate_clause")
    for clause in clauses:
        names=[component.get("name") for component in clause.get("components",[])]
        if len(names)!=len(set(names)): errors.append("duplicate_component")
        if any(ref.get("index") not in indices for ref in clause.get("target_refs",[])): errors.append("unknown_target")
    return errors
