"""Conservative offline progress warnings for expanded, documented Freya JSON.

diagnose_workflow_progress(workflow, close_operation_name=None) returns ordinary
lint-shaped dictionaries: severity='warning', path, message. It never changes the
workflow, runs Python hooks, evaluates customer facts, or calls any service.
An empty list is NOT proof of progress, backend success or source-policy coverage.

Reachability is an overapproximation: every declared transition, tool-call edge,
turn-limit/default route and non-excluded global interrupt may fire. Conditions
are not evaluated. End-call nodes stop traversal; dynamic __previous__ returns
add no new vertices. Malformed graph parts suppress negative reachability claims;
absence of native terminal declarations is still reported for intact node maps.
Duplicate target merging, global priority, interruption windows and runtime
variable values may make declared paths unusable.

Close-operation checks are disabled unless the caller supplies the exact API
function name. A recognizable result gate must advance to a declared end route,
and every OR alternative must require result evidence (one AND conjunct suffices).
Evidence names come from documented automatic result keys, tool-level envelope
response_mapping, or literal vars assignments in the close tool's post-hook.
Pre-hooks, descriptions, argument keys and other tools' results are not evidence.
This recognizes naming/placement, not successful execution, fresh receipts,
write provenance or hook semantics. Dynamic/interprocedural hook writes and
indirect cross-node variable propagation are intentionally not inferred.

References: the kit's workflow-format.md (routing / global / end-call nodes) and
tools-and-code.md (automatic result keys / mappings / post hooks).
Run structural workflow lint separately.
"""

import ast
import math
from collections import deque

__all__ = ["diagnose_workflow_progress"]

_BINARY = {"equals", "not_equals", "greater_than", "less_than", "contains"}
_UNARY = {"is_set", "is_not_set"}


def _object(value):
    return value if isinstance(value, dict) else {}


def _path(parent, key):
    return parent + "." + key if isinstance(key, str) and key.isidentifier() else f"{parent}[{key!r}]"


def _condition_kind(value, depth=0, ancestors=frozenset()):
    """Classify well-shaped trees without evaluating any variable or intent."""
    if not isinstance(value, dict) or depth > 64 or id(value) in ancestors:
        return None
    if "conditions" in value or "logic" in value:
        children = value.get("conditions")
        if (value.get("logic") not in ("and", "or") or "operator" in value
                or not isinstance(children, list) or not children):
            return None
        kinds = [_condition_kind(child, depth + 1, ancestors | {id(value)}) for child in children]
        return None if None in kinds else "semantic" if "semantic" in kinds else "deterministic"
    operator = value.get("operator")
    if operator == "matches_intent":
        description = value.get("description")
        return "semantic" if isinstance(description, str) and description.strip() else None
    if operator == "always":
        return "deterministic"
    if not isinstance(operator, str) or operator not in _BINARY | _UNARY:
        return None
    if not isinstance(value.get("variable"), str) or not value["variable"]:
        return None
    if operator in _BINARY:
        operand = value.get("operand")
        if type(operand) not in (str, int, float, bool) or isinstance(operand, float) and not math.isfinite(operand):
            return None
    return "deterministic"


def _post_variables(source):
    """Recognize literal writes only; parse but never execute authored Python."""
    if not isinstance(source, str):
        return set()
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return set()
    names = set()
    pending = list(tree.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if (isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store)
                and isinstance(node.value, ast.Name) and node.value.id == "vars"
                and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)):
            names.add(node.slice.value)
        pending.extend(ast.iter_child_nodes(node))
    return names


def _result_variables(tool):
    names = _post_variables(tool.get("post_process_code"))
    mappings = tool.get("response_mapping", [])
    for mapping in mappings if isinstance(mappings, list) else []:
        mapping = _object(mapping)
        path, variable = mapping.get("path"), mapping.get("variable")
        if (isinstance(variable, str) and variable and isinstance(path, str)
                and (path in {"data", "status", "status_code", "message"}
                     or path.startswith(("data.", "header.")))):
            names.add(variable)
    return names


def _requires_result(condition, operation, aliases, depth=0):
    if depth > 64 or _condition_kind(condition) is None:
        return False
    if "conditions" in condition:
        requirements = [_requires_result(child, operation, aliases, depth + 1) for child in condition["conditions"]]
        return all(requirements) if condition["logic"] == "or" else any(requirements)
    variable, operator = condition.get("variable"), condition.get("operator")
    if not isinstance(variable, str):
        return False
    if variable in {operation + "_success_count", operation + "_failure_count"}:
        try:
            number = float(condition["operand"])
            return math.isfinite(number) and (
                operator == "greater_than" and number >= 0
                or operator == "equals" and number > 0 and number.is_integer())
        except (TypeError, ValueError, OverflowError):
            return False
        except KeyError:
            return False
    result_name = isinstance(variable, str) and (
        variable in aliases or variable.startswith(operation + "_response.") or variable == operation + "_status_code")
    if not result_name:
        return False
    if operator == "is_set":
        return True
    # Negative tests may already pass before any call. Do not treat them as gates.
    return operator == "equals" and condition.get("operand") not in ("", "None", None)


def _native_end(node):
    terminal = _object(node.get("terminal"))
    return (node.get("node_type") == "end_call" and terminal.get("type") == "function"
            and _object(terminal.get("function")).get("handler") == "__function__:end_call")


def _reachable(start, edges):
    visited, pending = set(), deque([start])
    while pending:
        key = pending.popleft()
        if key not in visited:
            visited.add(key)
            pending.extend(edges.get(key, ()))
    return visited


def diagnose_workflow_progress(workflow, *, close_operation_name=None) -> list:
    """Inspect declared progress mechanisms, with no source/customer assumptions."""
    issues = []

    def warn(path, message):
        issue = {"severity": "warning", "path": path, "message": message}
        if issue not in issues:
            issues.append(issue)

    if not isinstance(workflow, dict):
        warn("$", "Progress inspection skipped: workflow must be an object.")
        return issues
    if not isinstance(workflow.get("nodes"), dict):
        warn("$.nodes", "Progress inspection skipped: nodes must be an object map.")
        return issues
    complete = True
    globals_ = workflow.get("global_nodes", {})
    if not isinstance(globals_, dict):
        warn("$.global_nodes", "Global routes are malformed; negative reachability conclusions are skipped.")
        globals_, complete = {}, False
    records, nodes = [], {}
    for section, mapping in (("nodes", workflow["nodes"]), ("global_nodes", globals_)):
        for key, node in mapping.items():
            path = _path("$." + section, key)
            if not isinstance(key, str) or not isinstance(node, dict):
                warn(path, "Malformed node entry skipped; negative reachability conclusions are skipped.")
                complete = False
                continue
            if key in nodes:
                warn(path, "Node key also occurs in the other node map; reachability is ambiguous.")
                complete = False
            nodes.setdefault(key, node)
            records.append((section, key, node, path))
    inventory_complete = complete
    edges = {key: set() for key in nodes}
    for section, key, node, path in records:
        transitions = node.get("transitions", [])
        if not isinstance(transitions, list):
            warn(path + ".transitions", "Transitions are malformed; negative reachability conclusions are skipped.")
            transitions, complete = [], False
        if node.get("node_type") == "end_call":
            if transitions:
                warn(path + ".transitions", "Native end-call nodes terminate; outgoing transitions are not documented post-close progress.")
            for field in ("tools", "pre_actions"):
                if node.get(field):
                    warn(path + "." + field, "Actions here do not provide documented progress: end-call nodes use terminal, and dialogue tools/action-node pre_actions are stripped.")
            if not _native_end(node):
                warn(path + ".terminal", "This end-call node has no documented native __function__:end_call terminal.")
            continue
        for index, edge in enumerate(transitions):
            edge_path = f"{path}.transitions[{index}]"
            edge = _object(edge)
            target = edge.get("target_node")
            if isinstance(target, str) and target in nodes:
                edges[key].add(target)
            elif target != "__previous__" or section != "global_nodes":
                warn(edge_path + ".target_node", "Unresolved transition target; negative reachability conclusions are skipped.")
                complete = False
            if (target == key and edge.get("is_tool_call", False) is False
                    and _condition_kind(edge.get("condition")) == "deterministic"):
                later = [f"{path}.transitions[{j}].condition" for j, other in enumerate(transitions)
                         if j > index and isinstance(other, dict) and other.get("target_node") != key
                         and other.get("is_tool_call", False) is False
                         and _condition_kind(other.get("condition")) == "semantic"]
                if later:
                    warn(edge_path + ".condition", "Potential semantic starvation: while this deterministic self-loop condition stays true, it can preempt later semantic branches at " + ", ".join(later) + ". Variable values and intentional waiting are not evaluated.")
        for field in ("passthrough_default_transition", "max_turn_transition"):
            if field not in node or field == "passthrough_default_transition" and node.get("passthrough") is not True:
                continue
            target = node[field]
            if target == "":  # Documented optional strings can be empty.
                continue
            if isinstance(target, str) and target in nodes:
                edges[key].add(target)
            elif target != "__previous__" or section != "global_nodes":
                warn(path + "." + field, "Unresolved fallback/turn-limit target; negative reachability conclusions are skipped.")
                complete = False
        for global_key, global_node in globals_.items():
            if global_key in nodes and isinstance(global_node, dict):
                excluded = global_node.get("excluded_nodes", [])
                if not isinstance(excluded, list) or key not in excluded:
                    edges[key].add(global_key)
    initial = workflow.get("initial_node")
    if not isinstance(initial, str) or initial not in workflow["nodes"] or initial not in nodes:
        warn("$.initial_node", "Initial node is missing or unresolved; initial reachability cannot be assessed.")
    elif complete and not any(_native_end(nodes[key]) for key in _reachable(initial, edges)):
        warn("$.initial_node", "No native end_call terminal is reachable from the initial node in the declared graph. A backend close operation does not itself hang up. Conditions are not evaluated; external termination is outside this check.")
    elif inventory_complete and not any(_native_end(node) for node in nodes.values()):
        warn("$.nodes", "No native end_call terminal is declared in the inspected node maps. Malformed routes prevent a full reachability conclusion; a backend close tool is not a native hangup.")
    if close_operation_name is not None and (not isinstance(close_operation_name, str) or not close_operation_name):
        warn("$", "Close-operation inspection skipped: close_operation_name must be a nonempty string or None.")
        return issues
    if close_operation_name is None:
        return issues
    for section, key, node, path in records:
        if node.get("node_type", "conversation" if section == "global_nodes" else None) != "conversation":
            continue
        tools = node.get("tools", [])
        for index, tool in enumerate(tools if isinstance(tools, list) else []):
            tool = _object(tool)
            function = _object(tool.get("function"))
            if (function.get("name") != close_operation_name or function.get("handler") != "__function__:api_call"
                    or _object(tool.get("config")).get("alwaysRunsAt")):
                continue  # Lifecycle tools are not offered to the dialogue model.
            aliases = _result_variables(tool)
            transitions = node.get("transitions", [])
            gated = False
            for edge in transitions if isinstance(transitions, list) else []:
                edge = _object(edge)
                target = edge.get("target_node")
                if (isinstance(target, str) and target in nodes and target != key
                        and edge.get("is_tool_call", False) is False
                        and _requires_result(edge.get("condition"), close_operation_name, aliases)
                        and any(_native_end(nodes[k]) for k in _reachable(target, edges))):
                    gated = True
                    break
            if not gated:
                warn(f"{path}.tools[{index}].function.name", "The supplied backend close operation is offered as a conversation tool, but no recognizable tool-result-gated route advancing to a native end_call was found. Review result routing; hooks, runtime values and malformed graph parts are not proven by this inspection.")
    return issues
