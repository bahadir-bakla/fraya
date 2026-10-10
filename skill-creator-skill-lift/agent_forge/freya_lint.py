"""Offline structural lint for the documented Freya workflow JSON.

Issues have ``severity``, ``path`` (a JSON-style path), and ``message``. No
workflow, snippet, request, or hook is executed or modified. API constraints
come only from the supplied ToolAPI; prose/policy correctness belongs to the
independent source critic. AST checks catch unsafe constructs, but are not a
security sandbox or a proof about arbitrary Python or runtime variable values.
"""

from __future__ import annotations

import ast
import math
import re
from typing import Any

from .tool_api import ToolAPI, ToolAPIError, validate_json

__all__ = ["lint_workflow", "assert_valid_workflow"]

_HANDLERS = {"__function__:api_call", "__function__:code_exec", "__function__:end_call"}
_NODE_TYPES = {
    "conversation", "api_request", "code", "end_call", "transfer_call",
    "integration", "knowledge_base", "reschedule_call", "invoke_agent", "exit",
}
_BINARY_OPS = {"equals", "not_equals", "greater_than", "less_than", "contains"}
_UNARY_OPS = {"is_set", "is_not_set"}
_VERIFIED_IMPORTS = {"json", "re", "datetime"}
_DETERMINISTIC_IMPORTS = {
    "math", "decimal", "fractions", "collections", "itertools", "functools",
    "operator", "statistics", "string", "bisect", "heapq", "calendar", "typing",
}
_DYNAMIC_CALLS = {
    "eval", "exec", "compile", "__import__", "getattr", "setattr", "delattr",
    "globals", "locals", "vars", "breakpoint",
}
_IO_CALLS = {"open", "input"}
_IO_ATTRIBUTES = {
    "open", "read", "write", "read_text", "write_text", "read_bytes", "write_bytes",
    "unlink", "rmdir", "mkdir", "rename", "replace_file", "touch", "listdir",
    "scandir", "walk", "system", "popen", "connect", "urlopen", "urlretrieve",
}
_CLOCK_ATTRIBUTES = {"now", "today", "utcnow"}
_HOOKS = {"pre_process_code", "post_process_code"}


def _child(path: str, key: Any) -> str:
    if isinstance(key, str) and re.fullmatch(r"[A-Za-z_]\w*", key):
        return f"{path}.{key}"
    return f"{path}[{key!r}]"


def _dynamic(value: Any) -> bool:
    if isinstance(value, str):
        return "{{" in value or "}}" in value
    if isinstance(value, dict):
        return any(_dynamic(v) for v in value.values())
    if isinstance(value, list):
        return any(_dynamic(v) for v in value)
    return False


class _Snippet(ast.NodeVisitor):
    """Track import provenance, including aliases, without treating params.now as a clock."""

    def __init__(self, report, path: str, *, pre_hook: bool = False):
        self.report, self.path = report, path
        self.bindings: dict[str, str] = {"config": "freya.config"} if pre_hook else {}
        self.pre_hook = pre_hook

    def issue(self, node, message: str, severity: str = "error") -> None:
        self.report(self.path, f"Python line {node.lineno}: {message}", severity)

    def qualified(self, node) -> str:
        if isinstance(node, ast.Name):
            # Unbound names are runtime inputs, not imported datetime objects.
            return self.bindings.get(node.id, node.id if node.id in _DYNAMIC_CALLS | _IO_CALLS else "")
        if isinstance(node, ast.Attribute):
            return self.qualified(node.value) + "." + node.attr
        if isinstance(node, ast.Subscript):
            owner = self.qualified(node.value)
            if owner.startswith("freya.config"):
                key = node.slice.value if isinstance(node.slice, ast.Constant) else "*"
                return owner + "." + str(key)
        if isinstance(node, ast.Call):
            name = self.qualified(node.func)
            # Datetime instances expose the same machine-clock class methods.
            for cls in ("datetime.datetime", "datetime.date"):
                if name == cls or name.startswith(cls + "."):
                    return cls
        return ""

    def import_module(self, node, module: str) -> None:
        if module in _VERIFIED_IMPORTS:
            return
        if module in _DETERMINISTIC_IMPORTS:
            self.issue(node, f"Deterministic import {module!r} is not verified in the Freya sandbox; use json, re, or datetime, or verify availability.", "warning")
        else:
            self.issue(node, f"Import {module!r} is prohibited: filesystem, network, runtime access, or unverified module capabilities are not allowed.")

    def visit_Import(self, node):
        for alias in node.names:
            self.import_module(node, alias.name)
            self.bindings[alias.asname or alias.name.split(".")[0]] = alias.name

    def visit_ImportFrom(self, node):
        module = node.module or ""
        if node.level:
            self.issue(node, "Relative imports are prohibited.")
        self.import_module(node, module)
        for alias in node.names:
            if alias.name == "*" or alias.name.startswith("__"):
                self.issue(node, "Wildcard and runtime-internal imports are prohibited.")
            self.bindings[alias.asname or alias.name] = module + "." + alias.name

    def visit_Name(self, node):
        qualified = self.qualified(node)
        if isinstance(node.ctx, ast.Load) and (
            node.id in {"__builtins__", "__loader__", "__spec__"}
            or qualified in (_DYNAMIC_CALLS - {"vars"}) | _IO_CALLS
        ):
            self.issue(node, f"Filesystem, dynamic execution, or runtime reflection via {qualified!r} is prohibited.")
        if isinstance(node.ctx, ast.Load) and qualified.rsplit(".", 1)[-1] in _CLOCK_ATTRIBUTES and qualified.startswith("datetime."):
            self.issue(node, "Machine-clock .now/.today/.utcnow is prohibited; read the supplied call variable from vars instead.")
        if isinstance(node.ctx, ast.Load) and qualified in {"json.load", "json.dump"}:
            self.issue(node, f"Filesystem access via {qualified!r} is prohibited; use json.loads/json.dumps with in-memory values.")

    def visit_Attribute(self, node):
        qualified = self.qualified(node)
        if node.attr.startswith("__"):
            self.issue(node, "Runtime-internal attribute access is prohibited.")
        elif node.attr in _CLOCK_ATTRIBUTES and qualified.startswith("datetime."):
            self.issue(node, "Machine-clock .now/.today/.utcnow is prohibited; read the supplied call variable from vars instead.")
        elif node.attr in _IO_ATTRIBUTES or qualified in {"json.load", "json.dump"}:
            self.issue(node, f"Filesystem/network access via {qualified!r} is prohibited; use in-memory values.")
        elif node.attr in _DYNAMIC_CALLS - {"vars"} and qualified != "re.compile":
            self.issue(node, "Dynamic execution or runtime reflection through an attribute is prohibited.")
        self.generic_visit(node)

    def visit_Call(self, node):
        if self.qualified(node.func) == "vars":
            self.issue(node, "Runtime reflection via vars() is prohibited; vars is the supplied workflow-variable dict.")
        if self.pre_hook and isinstance(node.func, ast.Attribute):
            owner = self.qualified(node.func.value)
            if owner.startswith("freya.config") and node.func.attr in {
                "update", "setdefault", "pop", "popitem", "clear", "append", "extend", "insert", "remove",
            }:
                if owner != "freya.config":
                    self.config_write(node, owner)
                elif node.func.attr == "update":
                    keys = [kw.arg or "*" for kw in node.keywords]
                    for argument in node.args:
                        if isinstance(argument, ast.Dict):
                            keys += [key.value if isinstance(key, ast.Constant) else "*" for key in argument.keys]
                        else:
                            keys.append("*")
                    for key in keys:
                        self.config_write(node, "freya.config." + str(key))
                else:
                    key = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else "*"
                    self.config_write(node, "freya.config." + str(key))
        self.generic_visit(node)

    def config_write(self, node, destination: str) -> None:
        field = destination.split(".")[2] if destination.startswith("freya.config.") else ""
        if destination == "freya.config" or field in {"url", "method", "*"}:
            self.issue(node, "A pre-hook cannot rewrite the API URL/method; declare the exact OpenAPI operation in parameter defaults.")
        elif field in {"body", "headers"}:
            self.issue(node, "A pre-hook rewrites the body/headers; declared schema checks cannot verify the final runtime body.", "warning")

    def bind(self, target, value):
        if isinstance(target, ast.Name):
            if value:
                self.bindings[target.id] = value
            else:
                self.bindings.pop(target.id, None)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                self.bind(item, "")

    def visit_Assign(self, node):
        self.visit(node.value)
        for target in node.targets:
            if self.pre_hook:
                if isinstance(target, ast.Name) and target.id == "config":
                    self.config_write(node, "freya.config")
                elif isinstance(target, (ast.Subscript, ast.Attribute)):
                    self.config_write(node, self.qualified(target))
            self.visit(target)
            self.bind_expression(target, node.value)

    def bind_expression(self, target, expression):
        if isinstance(target, (ast.Tuple, ast.List)) and isinstance(expression, (ast.Tuple, ast.List)) and len(target.elts) == len(expression.elts):
            for child, value in zip(target.elts, expression.elts):
                self.bind_expression(child, value)
        else:
            self.bind(target, self.qualified(expression))

    def visit_AnnAssign(self, node):
        self.visit(node.annotation)
        if node.value is not None:
            self.visit(node.value)
        if self.pre_hook:
            if isinstance(node.target, ast.Name) and node.target.id == "config":
                self.config_write(node, "freya.config")
            elif isinstance(node.target, (ast.Subscript, ast.Attribute)):
                self.config_write(node, self.qualified(node.target))
        self.visit(node.target)
        self.bind(node.target, self.qualified(node.value))

    def visit_AugAssign(self, node):
        if self.pre_hook:
            self.config_write(node, self.qualified(node.target))
        self.generic_visit(node)

    def visit_Delete(self, node):
        if self.pre_hook:
            for target in node.targets:
                self.config_write(node, self.qualified(target))
        self.generic_visit(node)

    def visit_NamedExpr(self, node):
        self.visit(node.value)
        self.bind(node.target, self.qualified(node.value))

    def visit_FunctionDef(self, node):
        arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs, node.args.vararg, node.args.kwarg]
        for expression in [*node.decorator_list, *node.args.defaults, *node.args.kw_defaults,
                           node.returns, *[arg.annotation for arg in arguments if arg is not None]]:
            if expression is not None:
                self.visit(expression)
        outer = self.bindings.copy()
        for arg in arguments:
            if arg is not None:
                self.bindings.pop(arg.arg, None)
        for statement in node.body:
            self.visit(statement)
        self.bindings = outer
        self.bindings.pop(node.name, None)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node):
        for expression in [*node.args.defaults, *node.args.kw_defaults]:
            if expression is not None:
                self.visit(expression)
        outer = self.bindings.copy()
        for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs, node.args.vararg, node.args.kwarg]:
            if arg is not None:
                self.bindings.pop(arg.arg, None)
        self.visit(node.body)
        self.bindings = outer


class _Lint:
    def __init__(self, api: ToolAPI):
        self.api = api
        self.issues: list[dict] = []
        self.targets: set[str] = set()
        self.cyclic_json = False
        self.function_names: set[str] = set()
        self.declared_variables: set[str] = set()

    def report(self, path: str, message: str, severity: str = "error") -> None:
        issue = {"severity": severity, "path": path, "message": message}
        if issue not in self.issues:
            self.issues.append(issue)

    def variable_producers(self, workflow: dict, maps: dict) -> None:
        """Collect explicit names before routing checks; no order/definite-write proof.

        tools-and-code.md names automatic keys from function.name, not compiler
        reference aliases. Read only documented declaration/snippet positions;
        API body/schema fields and arbitrary strings are not declarations.
        """
        defaults = workflow.get("test_variables", {})
        if isinstance(defaults, dict):
            self.declared_variables.update(name for name in defaults if isinstance(name, str))

        def declarations(owner):
            for field, key in (("extraction_schema", "name"), ("response_mapping", "variable")):
                entries = owner.get(field, [])
                if isinstance(entries, list):
                    self.declared_variables.update(entry[key] for entry in entries
                        if isinstance(entry, dict) and isinstance(entry.get(key), str) and entry[key])

        def writes(source):
            if not isinstance(source, str):
                return
            try:
                tree = ast.parse(source)
            except (SyntaxError, ValueError, RecursionError):
                return  # Existing snippet validation reports malformed source.
            for node in ast.walk(tree):
                targets = node.targets if isinstance(node, ast.Assign) else (
                    [node.target] if isinstance(node, ast.AugAssign) or
                    (isinstance(node, ast.AnnAssign) and node.value is not None) else [])
                for target in targets:
                    for item in ast.walk(target):
                        if (isinstance(item, ast.Subscript) and isinstance(item.ctx, ast.Store)
                                and isinstance(item.value, ast.Name) and item.value.id == "vars"
                                and isinstance(item.slice, ast.Constant) and isinstance(item.slice.value, str)):
                            self.declared_variables.add(item.slice.value)

        def action(value, *, pre_action=False):
            if not isinstance(value, dict):
                return
            function = value.get("function")
            if not isinstance(function, dict):
                return
            name, handler = function.get("name"), function.get("handler")
            if isinstance(name, str) and name and isinstance(handler, str) and handler in _HANDLERS:
                self.function_names.add(name)
            if not pre_action:
                declarations(value)  # Pre-action mappings/extraction belong on the node.
            if handler == "__function__:api_call":
                for hook in _HOOKS:
                    writes(value.get(hook))
            elif handler == "__function__:code_exec":
                parameters = function.get("parameters", {})
                properties = parameters.get("properties", {}) if isinstance(parameters, dict) else {}
                code = properties.get("code", {}) if isinstance(properties, dict) else {}
                writes(code.get("default") if isinstance(code, dict) else None)

        root_tools = workflow.get("tools", [])
        for value in root_tools if isinstance(root_tools, list) else []:
            action(value)
        for mapping in maps.values():
            for node in mapping.values():
                if not isinstance(node, dict):
                    continue
                declarations(node)
                for field in ("tools", "pre_actions"):
                    actions = node.get(field, [])
                    for value in actions if isinstance(actions, list) else []:
                        action(value, pre_action=field == "pre_actions")
                action(node.get("terminal"))

    def result_variable(self, variable: Any, path: str) -> None:
        """Only reject undeclared <function>_response namespaces in routing."""
        if not isinstance(variable, str):
            return
        base = variable.split(".", 1)[0]
        if not re.fullmatch(r"[A-Za-z_]\w*_response", base):
            return
        name = base.removesuffix("_response")
        if name in self.function_names or variable in self.declared_variables or base in self.declared_variables:
            return
        self.report(path, f"Unbound automatic result variable {variable!r}: no actual function.name {name!r} "
                    "exists and this variable/base is not explicitly declared. Freya uses "
                    "<function.name>_response.*, not a tool-library reference alias.")

    def loop_variables(self, value: Any, path: str) -> None:
        if isinstance(value, dict):
            if "variable" in value:
                self.result_variable(value["variable"], path + ".variable")
            children = value.get("conditions", [])
            if isinstance(children, list):
                for i, child in enumerate(children):
                    self.loop_variables(child, f"{path}.conditions[{i}]")
        elif isinstance(value, str):
            # Loop intent prose is not an undeclared-variable lint. Inspect
            # only explicit placeholders or a whole response variable name.
            for variable in re.findall(r"\{\{\s*([^{}]+?)\s*\}\}", value):
                self.result_variable(variable.strip(), path)
            if re.fullmatch(r"[A-Za-z_]\w*_response(?:\.[A-Za-z_]\w*)*", value):
                self.result_variable(value, path)

    def json_values(self, value: Any, path: str = "$", ancestors: frozenset = frozenset()) -> None:
        if value is None:
            self.report(path, "Null values are forbidden by the Freya workflow schema; omit optional fields instead.")
        elif isinstance(value, (dict, list)):
            if id(value) in ancestors:
                self.report(path, "Cyclic containers are not valid workflow JSON.")
                self.cyclic_json = True
                return
            ancestors = ancestors | {id(value)}
            for key, child in value.items() if isinstance(value, dict) else enumerate(value):
                if isinstance(value, dict) and not isinstance(key, str):
                    self.report(path, "JSON object keys must be strings.")
                self.json_values(child, _child(path, key) if isinstance(value, dict) else f"{path}[{key}]", ancestors)
        elif not isinstance(value, (str, bool, int, float)) or (isinstance(value, float) and not math.isfinite(value)):
            self.report(path, "Workflow values must be JSON values with finite numbers.")

    def target(self, value: Any, path: str, global_node: bool) -> None:
        if value == "__previous__":
            if not global_node:
                self.report(path, "__previous__ is allowed only in global nodes.")
        elif not isinstance(value, str) or value not in self.targets:
            self.report(path, f"Target {value!r} is not a node key in this workflow.")

    def condition(self, value: Any, path: str, *, nested: bool = False) -> None:
        if not isinstance(value, dict):
            self.report(path, "A condition must be an object.")
            return
        if "logic" in value or "conditions" in value:
            if value.get("logic") not in (("or", "and") if nested else ("or",)):
                self.report(_child(path, "logic"), "Top-level condition groups must use OR; nest an AND group inside OR." if not nested else "Nested condition logic must be 'and' or 'or'.")
            if "operator" in value:
                self.report(path, "A condition cannot mix a group and a leaf operator.")
            children = value.get("conditions")
            if not isinstance(children, list) or not children:
                self.report(_child(path, "conditions"), "Condition groups need a nonempty conditions array.")
            else:
                for i, child in enumerate(children):
                    self.condition(child, f"{path}.conditions[{i}]", nested=True)
            return
        operator = value.get("operator")
        if not isinstance(operator, str) or operator not in _BINARY_OPS | _UNARY_OPS | {"always", "matches_intent"}:
            self.report(_child(path, "operator"), f"Unsupported condition operator {operator!r}.")
        elif operator == "matches_intent":
            if not isinstance(value.get("description"), str) or not value["description"].strip():
                self.report(_child(path, "description"), "matches_intent needs a nonempty description.")
        elif operator != "always":
            if not isinstance(value.get("variable"), str) or not value["variable"].strip():
                self.report(_child(path, "variable"), f"{operator} needs a variable name.")
            else:
                self.result_variable(value["variable"], _child(path, "variable"))
            if operator in _BINARY_OPS and "operand" not in value:
                self.report(_child(path, "operand"), f"{operator} needs an operand.")
            if operator in {"greater_than", "less_than"} and "operand" in value:
                try:
                    number = float(value["operand"])
                    if not math.isfinite(number):
                        raise ValueError
                except (TypeError, ValueError, OverflowError):
                    self.report(_child(path, "operand"), f"{operator} needs a numeric operand.")

    @staticmethod
    def always(condition: Any) -> bool:
        if not isinstance(condition, dict):
            return False
        if condition.get("operator") == "always":
            return True
        children = condition.get("conditions")
        if not isinstance(children, list) or not children:
            return False
        checks = [_Lint.always(c) for c in children]
        return any(checks) if condition.get("logic") == "or" else all(checks) if condition.get("logic") == "and" else False

    def snippet(self, source: Any, path: str, *, required: bool = False, pre_hook: bool = False) -> None:
        if not isinstance(source, str) or (required and not source.strip()):
            self.report(path, "Python source must be a nonempty baked string." if required else "Python hooks must be strings.")
            return
        if "{{" in source or "}}" in source:
            self.report(path, "Python snippets cannot contain '{{' or '}}'; read variables through vars instead.")
        try:
            tree = ast.parse(source)
            compile(tree, "<freya-snippet>", "exec")  # Compile only; never execute.
        except (SyntaxError, ValueError, RecursionError) as exc:
            self.report(path, f"Invalid Python syntax: {exc}.")
            return
        _Snippet(self.report, path, pre_hook=pre_hook).visit(tree)

    def mapping(self, value: Any, path: str) -> None:
        if not isinstance(value, list):
            self.report(path, "response_mapping must be an array.")
            return
        for i, entry in enumerate(value):
            here = f"{path}[{i}]"
            if not isinstance(entry, dict):
                self.report(here, "A response mapping must be an object.")
                continue
            source, variable = entry.get("path"), entry.get("variable")
            if not isinstance(source, str) or not source.startswith("data.") or len(source) == 5:
                self.report(_child(here, "path"), "API response mapping paths must start with 'data.' (the HTTP response envelope).")
            if not isinstance(variable, str) or not variable.strip():
                self.report(_child(here, "variable"), "A response mapping needs a nonempty variable name.")

    def schema_value(self, schema: Any, value: Any, path: str) -> None:
        try:
            errors = validate_json(schema, value, path=path)
        except (ToolAPIError, TypeError, ValueError, KeyError) as exc:
            self.report(path, f"Cannot validate the supplied OpenAPI schema: {exc}.")
            return
        for error in errors:
            here, _, message = error.partition(": ")
            self.report(here, "OpenAPI mismatch: " + message)

    def schema(self, actual: Any, expected: Any, path: str, *, engine_run: bool, composition: bool = False) -> None:
        """Compare declarations and literal defaults, leaving substituted values unknown."""
        if not isinstance(actual, dict):
            self.report(path, "Request fields must be JSON-schema objects.")
            return
        if expected is False:
            self.report(path, "The supplied OpenAPI schema forbids this request field.")
            return
        if expected is True:
            return
        if not isinstance(expected, dict):
            self.report(path, "The supplied OpenAPI request schema is invalid.")
            return
        branches = expected.get("allOf", [])
        for branch in branches:
            self.schema(actual, branch, path, engine_run=engine_run, composition=True)
        if branches and isinstance(actual.get("properties"), dict):
            declared = self.declared_properties(expected)
            if declared:
                for name in actual["properties"].keys() - declared:
                    self.report(_child(path + ".properties", name), f"Request field {name!r} is not declared by the supplied OpenAPI operation.")
        for keyword in ("anyOf", "oneOf"):
            if keyword in expected:
                candidates = []
                for branch in expected[keyword]:
                    critic = _Lint(self.api)
                    critic.schema(actual, branch, path, engine_run=engine_run, composition=composition)
                    candidates.append(critic.issues)
                matching = [issues for issues in candidates if not any(i["severity"] == "error" for i in issues)]
                if matching:
                    for issue in matching[0]:
                        self.report(issue["path"], issue["message"], issue["severity"])
                    if keyword == "oneOf" and len(matching) > 1:
                        self.report(path, "Declared fields match multiple OpenAPI oneOf alternatives; runtime values must match exactly one.", "warning")
                else:
                    self.report(path, f"Declared request fields do not match an OpenAPI {keyword} alternative.")
                    if candidates:
                        for issue in min(candidates, key=len):
                            self.report(issue["path"], issue["message"], issue["severity"])
        kinds = expected.get("type")
        kinds = [kinds] if isinstance(kinds, str) else kinds
        actual_kinds = actual.get("type")
        actual_kinds = [actual_kinds] if isinstance(actual_kinds, str) else actual_kinds
        if kinds and (not isinstance(actual_kinds, list) or not actual_kinds or any(
            kind not in kinds and not (kind == "integer" and "number" in kinds) for kind in actual_kinds
        )):
            self.report(_child(path, "type"), f"Request field type must match OpenAPI {kinds!r}; got {actual.get('type')!r}.")
        for keyword in ("enum", "const"):
            if keyword in actual:
                values = actual[keyword] if keyword == "enum" else [actual[keyword]]
                if not isinstance(values, list) or not values:
                    self.report(_child(path, keyword), f"{keyword} must constrain a nonempty set of values.")
                else:
                    for i, value in enumerate(values):
                        self.schema_value(expected, value, f"{path}.{keyword}[{i}]" if keyword == "enum" else f"{path}.const")
        literal = "default" in actual and not _dynamic(actual["default"])
        if literal:
            self.schema_value(expected, actual["default"], _child(path, "default"))
        if "enum" in expected and not literal and "enum" not in actual and "const" not in actual:
            self.report(_child(path, "enum"), f"A model-filled or substituted field must declare the OpenAPI enum {expected['enum']!r}.")
        if "const" in expected and not literal and actual.get("const") != expected["const"]:
            self.report(_child(path, "const"), "A dynamic request field must retain the OpenAPI const constraint.")
        if "items" in expected:
            if "items" not in actual:
                self.report(_child(path, "items"), "Array request fields must declare the OpenAPI item schema.")
            else:
                self.schema(actual["items"], expected["items"], _child(path, "items"), engine_run=engine_run)
        if "properties" not in expected and "required" not in expected:
            return
        properties = actual.get("properties", {})
        if not isinstance(properties, dict):
            self.report(_child(path, "properties"), "Request properties must be an object.")
            return
        required = actual.get("required", [])
        if not isinstance(required, list) or any(not isinstance(k, str) for k in required):
            self.report(_child(path, "required"), "Request required must be an array of field names.")
            required = []
        for name in required:
            if name not in properties:
                self.report(_child(path, "required"), f"Required field {name!r} has no declaration in properties.")
        for name in expected.get("required", []):
            field = properties.get(name)
            if not isinstance(field, dict):
                self.report(_child(_child(path, "properties"), name), "Required OpenAPI request field is missing.")
            elif name not in required:
                if "default" not in field:
                    self.report(_child(path, "required"), f"Model-filled OpenAPI field {name!r} must be required.")
                elif _dynamic(field["default"]) and not engine_run:
                    self.report(_child(path, "required"), f"Required OpenAPI field {name!r} has a variable default but is not required if the model must fill an unresolved variable.", "warning")
        expected_properties = expected.get("properties", {})
        for name, field in properties.items():
            here = _child(_child(path, "properties"), name)
            if name in expected_properties:
                self.schema(field, expected_properties[name], here, engine_run=engine_run)
            elif isinstance(expected.get("additionalProperties"), dict):
                self.schema(field, expected["additionalProperties"], here, engine_run=engine_run)
            elif expected.get("additionalProperties") is False or (expected_properties and not composition):
                self.report(here, f"Request field {name!r} is not declared by the supplied OpenAPI operation.")

    @staticmethod
    def declared_properties(schema: dict) -> set[str]:
        names = set(schema.get("properties", {}))
        for keyword in ("allOf", "anyOf", "oneOf"):
            for branch in schema.get(keyword, []):
                if isinstance(branch, dict):
                    names |= _Lint.declared_properties(branch)
        return names

    def api_call(self, function: dict, parameters: dict, config: dict, path: str, *, engine_run: bool) -> None:
        name = function.get("name")
        operation = self.api.operations.get(name) if isinstance(name, str) else None
        if operation is None:
            self.report(_child(path, "name"), f"API tool name {name!r} is not allowlisted by the supplied OpenAPI operations.")
            return
        properties = parameters.get("properties", {})
        if not isinstance(properties, dict):
            return
        base = path + ".parameters.properties"
        for key, expected in (("url", operation.url), ("method", operation.method)):
            field = properties.get(key)
            here = _child(base, key)
            if not isinstance(field, dict) or field.get("default") != expected:
                self.report(here + ".default", f"{key} must use the exact supplied OpenAPI operation value {expected!r} in default.")
            if isinstance(field, dict):
                if field.get("type") != "string":
                    self.report(here + ".type", f"API {key} must be a string parameter.")
                if "const" in field:
                    self.report(here + ".const", f"const does not bake {key}; Freya reads default for fixed request configuration.")
        for key in properties.keys() - {"url", "method", "headers", "body", "connect_retries"}:
            self.report(_child(base, key), "API body fields belong under body.properties, not beside url and method.")
        headers = properties.get("headers", {})
        content_type = None
        if isinstance(headers, dict):
            entries = headers.get("properties", {})
            if isinstance(entries, dict):
                for key, header in entries.items():
                    if isinstance(key, str) and key.lower() == "content-type" and isinstance(header, dict):
                        content_type = header.get("default")
        try:
            if content_type is not None:
                if not isinstance(content_type, str) or content_type not in operation.request_schemas:
                    if "body" in properties:
                        self.report(base + ".headers", f"Request Content-Type {content_type!r} is not declared by the OpenAPI operation.")
                    schema = None
                else:
                    schema = operation.request_schemas[content_type]
            else:
                schema = operation.request_schema
        except ToolAPIError as exc:
            self.report(base + ".body", str(exc))
            schema = None
        body = properties.get("body")
        if body is None:
            if operation.request_required:
                self.report(base + ".body", "The supplied OpenAPI operation requires a request body.")
        elif schema is None:
            self.report(base + ".body", "No matching request-body schema is declared by the supplied OpenAPI operation.")
        else:
            if isinstance(body, dict) and "default" in body and not body.get("properties"):
                self.report(base + ".body", "Declare body fields under body.properties; a body.default-only template loses field constraints in Freya.")
            self.schema(body, schema, base + ".body", engine_run=engine_run)
        retries = config.get("maxRetries", 0)
        if type(retries) is int and retries > 0 and operation.method not in {"GET", "HEAD", "OPTIONS"}:
            self.report(path.rsplit(".function", 1)[0] + ".config.maxRetries", "Tool maxRetries > 0 can duplicate a write after an ambiguous failure; this HTTP method does not establish idempotency. Use 0 unless retries are independently proven safe.", "warning")

    def tool(self, value: Any, path: str, *, placement: str, terminal: bool = False) -> None:
        if not isinstance(value, dict):
            self.report(path, "A tool must be an object.")
            return
        if value.get("type") != "function":
            self.report(path + ".type", "Tool type must be 'function'.")
        function = value.get("function")
        if not isinstance(function, dict):
            self.report(path + ".function", "A tool needs a function object.")
            return
        name, handler = function.get("name"), function.get("handler")
        if not isinstance(name, str) or not name.strip():
            self.report(path + ".function.name", "Tool function name must be a nonempty string.")
        if not isinstance(handler, str) or handler not in _HANDLERS:
            self.report(path + ".function.handler", f"Unsupported handler {handler!r}; only api_call, code_exec, and end_call are allowed.")
        if terminal and handler != "__function__:end_call":
            self.report(path + ".function.handler", "An end_call terminal must use __function__:end_call.")
        parameters = function.get("parameters")
        if not isinstance(parameters, dict) or parameters.get("type") != "object" or not isinstance(parameters.get("properties", {}), dict):
            self.report(path + ".function.parameters", "Function parameters must be an object schema with a properties map.")
            parameters = {"type": "object", "properties": {}}
        config = value.get("config", {})
        if not isinstance(config, dict):
            self.report(path + ".config", "Tool config must be an object.")
            config = {}
        if "maxRetries" in config and (type(config["maxRetries"]) is not int or config["maxRetries"] < 0):
            self.report(path + ".config.maxRetries", "Tool maxRetries must be a nonnegative integer.")
        lifecycle = config.get("alwaysRunsAt", [])
        if not isinstance(lifecycle, list) or any(v not in ("start_of_call", "end_of_call") for v in lifecycle):
            self.report(path + ".config.alwaysRunsAt", "Lifecycle tools support start_of_call/end_of_call; each_turn never runs.")
        if placement == "workflow" and not lifecycle:
            self.report(path + ".config.alwaysRunsAt", "Workflow-level tools must declare lifecycle timing or they never run.")
        for hook in _HOOKS:
            if hook in value:
                if handler != "__function__:api_call":
                    self.report(_child(path, hook), "Python hooks are honoured only on api_call tools among the allowed handlers.")
                self.snippet(value[hook], _child(path, hook), pre_hook=hook == "pre_process_code")
            for owner, label in ((function, ".function"), (config, ".config")):
                if hook in owner:
                    self.report(path + label + "." + hook, "Python hooks belong on the tool object, next to function and config.")
                    self.snippet(owner[hook], path + label + "." + hook)
        if "response_mapping" in value:
            if placement == "pre_actions":
                self.report(path + ".response_mapping", "pre_actions response_mapping belongs on the node; mappings inside an action are ignored.")
            self.mapping(value["response_mapping"], path + ".response_mapping")
        if "response_mapping" in function:
            self.report(path + ".function.response_mapping", "response_mapping belongs on the tool object or on the pre_actions node.")
            self.mapping(function["response_mapping"], path + ".function.response_mapping")
        if placement == "pre_actions" and "extraction_schema" in value:
            self.report(path + ".extraction_schema", "pre_actions result extraction belongs on the node.")
        if handler == "__function__:api_call":
            self.api_call(function, parameters, config, path + ".function", engine_run=placement != "tools" or bool(lifecycle))
        elif handler == "__function__:code_exec":
            code = parameters.get("properties", {}).get("code")
            here = path + ".function.parameters.properties.code"
            if not isinstance(code, dict) or code.get("type") != "string" or "default" not in code:
                self.report(here, "code_exec needs a string code parameter with baked source in default.")
            else:
                self.snippet(code["default"], here + ".default", required=True)

    def tool_list(self, value: Any, path: str, *, placement: str) -> None:
        if not isinstance(value, list):
            self.report(path, "Tools/pre_actions must be arrays.")
            return
        names: set[str] = set()
        for i, tool in enumerate(value):
            self.tool(tool, f"{path}[{i}]", placement=placement)
            function = tool.get("function", {}) if isinstance(tool, dict) else {}
            name = function.get("name") if isinstance(function, dict) else None
            if isinstance(name, str):
                if name in names:
                    self.report(f"{path}[{i}].function.name", "Duplicate tool names in one list make dispatch ambiguous.")
                names.add(name)

    def node(self, value: Any, key: str, path: str, *, global_node: bool) -> None:
        if not isinstance(value, dict):
            self.report(path, "A node definition must be an object.")
            return
        kind = value.get("node_type", "conversation" if global_node else None)
        if not isinstance(kind, str) or kind not in _NODE_TYPES:
            self.report(path + ".node_type", f"Unsupported or missing node_type {kind!r}.")
        if "name" in value and value["name"] != key:
            self.report(path + ".name", "Node name should match its map key.", "warning")
        if "loop_condition" in value:
            self.loop_variables(value["loop_condition"], path + ".loop_condition")
        if global_node:
            self.condition(value.get("condition"), path + ".condition")
            if "is_tool_call" in value and not isinstance(value["is_tool_call"], bool):
                self.report(path + ".is_tool_call", "is_tool_call must be a boolean.")
            excluded = value.get("excluded_nodes", [])
            if not isinstance(excluded, list):
                self.report(path + ".excluded_nodes", "excluded_nodes must be an array of node keys.")
            else:
                for i, target in enumerate(excluded):
                    if not isinstance(target, str) or target not in self.targets:
                        self.report(f"{path}.excluded_nodes[{i}]", "Excluded node must be an existing node key.")
        transitions = value.get("transitions", [])
        if not isinstance(transitions, list):
            self.report(path + ".transitions", "Transitions must be an array.")
            transitions = []
        seen: dict[str, int] = {}
        for i, transition in enumerate(transitions):
            here = f"{path}.transitions[{i}]"
            if not isinstance(transition, dict):
                self.report(here, "A transition must be an object.")
                continue
            target = transition.get("target_node")
            self.target(target, here + ".target_node", global_node)
            self.condition(transition.get("condition"), here + ".condition")
            if "is_tool_call" in transition and not isinstance(transition["is_tool_call"], bool):
                self.report(here + ".is_tool_call", "is_tool_call must be a boolean.")
            if isinstance(target, str):
                if target in seen:
                    self.report(here + ".target_node", f"Duplicate target {target!r} is merged with transition {seen[target]} by OR at load time; an always branch makes the merged transition unconditional.", "warning")
                seen[target] = i
        if "passthrough" in value and not isinstance(value["passthrough"], bool):
            self.report(path + ".passthrough", "passthrough must be a boolean.")
        for field in ("passthrough_default_transition", "max_turn_transition"):
            if field in value:
                self.target(value[field], _child(path, field), global_node)
        if value.get("passthrough") is True:
            if "passthrough_default_transition" not in value:
                self.report(path + ".passthrough_default_transition", "A passthrough node needs an explicit default target.")
            last = transitions[-1] if transitions and isinstance(transitions[-1], dict) else {}
            if not self.always(last.get("condition")) or last.get("is_tool_call"):
                self.report(path + ".transitions", "A passthrough node must end with a router-evaluated always fallback to avoid deadlock.")
        if "tools" in value:
            if kind != "conversation":
                self.report(path + ".tools", "Tools are kept only on conversation nodes; action-node tools are silently stripped.")
            self.tool_list(value["tools"], path + ".tools", placement="tools")
        if "pre_actions" in value:
            if kind in ("conversation", "end_call"):
                self.report(path + ".pre_actions", "pre_actions belong on action nodes such as api_request/code, not conversation/end_call nodes.")
            self.tool_list(value["pre_actions"], path + ".pre_actions", placement="pre_actions")
        if "response_mapping" in value:
            if "pre_actions" not in value:
                self.report(path + ".response_mapping", "Node-level response_mapping belongs on a pre_actions node; dialogue tool mappings belong on the tool.")
            self.mapping(value["response_mapping"], path + ".response_mapping")
        for hook in _HOOKS & value.keys():
            self.report(_child(path, hook), "Python hooks belong on an api_call tool, not on the node.")
            self.snippet(value[hook], _child(path, hook))
        if "terminal" in value:
            if kind != "end_call":
                self.report(path + ".terminal", "terminal belongs on an end_call node.")
            self.tool(value["terminal"], path + ".terminal", placement="terminal", terminal=True)
        elif kind == "end_call":
            self.report(path + ".terminal", "An end_call node needs a terminal function.")
        if kind == "end_call" and transitions:
            self.report(path + ".transitions", "An end_call node must have no outgoing transitions.")

    def run(self, workflow: Any) -> list[dict]:
        try:
            self.json_values(workflow)
        except RecursionError:
            self.report("$", "Workflow JSON exceeds the supported nesting depth.")
            return self.issues
        if self.cyclic_json:
            return self.issues
        if not isinstance(workflow, dict):
            self.report("$", "Workflow must be an object.")
            return self.issues
        maps = {}
        for field in ("nodes", "global_nodes"):
            mapping = workflow.get(field, {} if field == "global_nodes" else None)
            if not isinstance(mapping, dict) or (field == "nodes" and not mapping):
                self.report(_child("$", field), "nodes must be a nonempty map of node keys to definitions." if field == "nodes" else "global_nodes must be a map of node keys to definitions.")
                mapping = {}
            maps[field] = mapping
            for key in mapping:
                if not isinstance(key, str) or not key or key == "__previous__":
                    self.report(_child(_child("$", field), key), "Node keys must be nonempty strings; __previous__ is reserved for global return targets.")
                else:
                    self.targets.add(key)
        for key in maps["nodes"].keys() & maps["global_nodes"].keys():
            self.report(_child("$.global_nodes", key), "Regular and global node keys must be distinct.")
        self.variable_producers(workflow, maps)
        initial = workflow.get("initial_node")
        if not isinstance(initial, str) or initial not in maps["nodes"]:
            self.report("$.initial_node", "initial_node must identify a node in the nodes map.")
        for field, mapping in maps.items():
            for key, value in mapping.items():
                self.node(value, key, _child(_child("$", field), key), global_node=field == "global_nodes")
        for field in ("test_variables", "context_variables", "agent_config", "nodePositions"):
            if field in workflow and not isinstance(workflow[field], dict):
                self.report(_child("$", field), f"{field} must be an object.")
        if "system_prompt" in workflow and not isinstance(workflow["system_prompt"], str):
            self.report("$.system_prompt", "system_prompt must be a string.")
        if "tools" in workflow:
            self.tool_list(workflow["tools"], "$.tools", placement="workflow")
        return self.issues


def lint_workflow(workflow: dict, api: ToolAPI) -> list[dict]:
    """Return local structural/schema issues; never send requests or execute snippets."""
    return _Lint(api).run(workflow)


def assert_valid_workflow(workflow: dict, api: ToolAPI) -> None:
    """Raise ValueError containing error paths/messages; warnings alone are accepted."""
    errors = [issue for issue in lint_workflow(workflow, api) if issue["severity"] == "error"]
    if errors:
        raise ValueError("Invalid Freya workflow:\n" + "\n".join(f"{issue['path']}: {issue['message']}" for issue in errors))
