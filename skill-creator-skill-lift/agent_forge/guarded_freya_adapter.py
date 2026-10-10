"""Compiler-only adapter for the documented Freya code-node format.

guarded_builtin_snippets() supplies trusted source for the compiler reference
@builtin:guarded_dispatch. guard_node returns a deployable node with that source
already baked; it does not require or perform reference expansion.

The caller MUST furnish trusted guard_policy_json, guard_state_json and
guard_command_json in vars. Persist guard_state_json on EVERY result, including
blocked corrections. Only guard_flag == 'allowed' authorizes dispatch, and only
the unchanged guard_request_json body is authorized. Event results ('accepted')
take the blocked branch, which the caller may use to continue event processing.
An allowed branch reserves an action; it does not call an API or prove success.

Validation recognizes the exact builtin source or its reference in action slots,
not mentions in prompts, metadata or unused libraries. It checks the local gate,
not downstream request binding, trusted-input provenance, interrupt handling or
other paths to a write. Run ordinary workflow lint separately. No metadata keys,
policy defaults, API definitions, initial state or backend calls are generated.

Format reference: official workflow-format.md (passthrough nodes / conditions)
and tools-and-code.md (code_exec / vars / baked defaults), shipped with the kit.
"""

import re

from .guarded_actions import lower_guard_snippet

__all__ = ["guarded_builtin_snippets", "guard_node", "validate_guard_wiring"]

_BUILTIN = "guarded_dispatch"
_REFERENCE = "@builtin:" + _BUILTIN


def guarded_builtin_snippets() -> dict:
    """Return a fresh deterministic name-to-source registry; never execute it."""
    return {_BUILTIN: lower_guard_snippet()}


def guard_node(name, allowed_target, blocked_target) -> dict:
    """Create a silent gate with distinct success/fallback targets and baked code.

    The compiler can replace code.default with @builtin:guarded_dispatch in its
    compact IR. Resolve that reference from guarded_builtin_snippets before
    deployment; the reference itself is not Freya Python source.
    """
    names = (name, allowed_target, blocked_target)
    if not all(type(n) is str and re.fullmatch(r"[A-Za-z_]\w*", n) and n != "__previous__" for n in names):
        raise ValueError("Node names and targets must be ordinary identifiers")
    if len(set(names)) != len(names):
        raise ValueError("Guard, allowed and blocked nodes must be distinct")
    return {
        "name": name, "node_type": "code", "on_enter": {"type": "silent"},
        "passthrough": True, "passthrough_default_transition": blocked_target,
        "pre_actions": [{
            "type": "function", "config": {"maxRetries": 0},
            "function": {
                "name": _BUILTIN, "handler": "__function__:code_exec",
                "parameters": {"type": "object", "properties": {
                    "code": {"type": "string", "default": guarded_builtin_snippets()[_BUILTIN]},
                }},
            },
        }],
        "transitions": [
            {"target_node": allowed_target, "description": "The action was validated and reserved.",
             "condition": {"logic": "or", "conditions": [
                 {"variable": "guard_flag", "operator": "equals", "operand": "allowed"},
             ]}},
            {"target_node": blocked_target, "description": "No dispatch permission was issued.",
             "condition": {"operator": "always"}},
        ],
    }


def _object(value):
    return value if isinstance(value, dict) else {}


def _code_parameter(action):
    function = _object(_object(action).get("function"))
    parameters = _object(function.get("parameters"))
    return _object(_object(parameters.get("properties")).get("code"))


def validate_guard_wiring(workflow) -> list:
    """Return ordinary lint-shaped issues for opted-in gates; never mutate/run.

    The narrow template requires exactly one code pre-action, an allowed-string
    branch first, and an unconditional blocked branch/default. This is deliberate:
    extra actions or predicates need a separate adapter contract and validation.
    Both actual source and unresolved compiler refs are accepted here; ordinary
    Freya lint must see only expanded source.
    """
    if not isinstance(workflow, dict):
        return []
    source = guarded_builtin_snippets()[_BUILTIN]
    issues = []

    def report(path, message):
        issue = {"severity": "error", "path": path, "message": message}
        if issue not in issues:
            issues.append(issue)

    def builtin(value):
        return type(value) is str and value in (source, _REFERENCE)

    def uses(action):
        action = _object(action)
        return builtin(_code_parameter(action).get("default")) or any(
            builtin(action.get(hook)) for hook in ("pre_process_code", "post_process_code"))

    def actions(owner):
        for field in ("pre_actions", "tools"):
            values = owner.get(field)
            if isinstance(values, list):
                for index, action in enumerate(values):
                    if uses(action):
                        yield field, index, action
        if uses(owner.get("terminal")):
            yield "terminal", None, owner["terminal"]

    for field, index, _ in actions(workflow):
        report(f"$.{field}[{index}]", "The dispatch guard must run in a dedicated code node, not a lifecycle or terminal action.")

    targets = set()
    for section in ("nodes", "global_nodes"):
        targets.update(_object(workflow.get(section)))
    for section in ("nodes", "global_nodes"):
        for key, value in _object(workflow.get(section)).items():
            node = _object(value)
            sites = list(actions(node))
            if not sites:
                continue
            path = f"$.{section}[{key!r}]"
            if section != "nodes" or node.get("node_type") != "code" or node.get("name") != key:
                report(path, "The dispatch guard needs a named ordinary code node matching its map key.")
            if node.get("passthrough") is not True or node.get("on_enter") != {"type": "silent"}:
                report(path, "The dispatch guard must be silent and passthrough.")
            if node.get("loop_condition") or node.get("on_enter_first_entry_only") is True:
                report(path, "The guard must execute and route on every visit without a loop condition.")
            if "tools" in node or len(sites) != 1 or not isinstance(node.get("pre_actions"), list) or len(node["pre_actions"]) != 1:
                report(path + ".pre_actions", "The gate must contain only one guard pre-action and no dialogue tools.")
            for placement, index, action in sites:
                here = path + (f".{placement}[{index}]" if index is not None else ".terminal")
                action = _object(action)
                function = _object(action.get("function"))
                parameters = _object(function.get("parameters"))
                code = _code_parameter(action)
                if (placement != "pre_actions" or action.get("type") != "function"
                        or function.get("handler") != "__function__:code_exec"
                        or parameters.get("type") != "object" or code.get("type") != "string"
                        or not builtin(code.get("default"))):
                    report(here, "Use the builtin as baked code.default of a code_exec pre-action.")
                config = _object(action.get("config"))
                if config.get("maxRetries", 0) != 0 or config.get("alwaysRunsAt") or any(
                        hook in action for hook in ("pre_process_code", "post_process_code")):
                    report(here, "The guard has no retries, lifecycle timing or API hooks.")
            transitions = node.get("transitions")
            if not isinstance(transitions, list) or len(transitions) != 2:
                report(path + ".transitions", "Use exactly an allowed branch followed by an unconditional blocked branch.")
                continue
            allowed, blocked = map(_object, transitions)
            expected = {"logic": "or", "conditions": [
                {"variable": "guard_flag", "operator": "equals", "operand": "allowed"}]}
            if allowed.get("condition") != expected or allowed.get("is_tool_call", False) is not False:
                report(path + ".transitions[0]", "The first branch must check only the string guard_flag equals allowed.")
            if blocked.get("condition") != {"operator": "always"} or blocked.get("is_tool_call", False) is not False:
                report(path + ".transitions[1]", "The last branch must be a router-evaluated always fallback.")
            allowed_target, blocked_target = allowed.get("target_node"), blocked.get("target_node")
            if (not isinstance(allowed_target, str) or not isinstance(blocked_target, str)
                    or allowed_target not in targets or blocked_target not in targets
                    or len({key, allowed_target, blocked_target}) != 3):
                report(path + ".transitions", "Guard, allowed and blocked targets must be distinct existing node keys; duplicate targets merge by OR.")
            if node.get("passthrough_default_transition") != blocked_target:
                report(path + ".passthrough_default_transition", "The passthrough default must be the blocked target.")
    return issues
