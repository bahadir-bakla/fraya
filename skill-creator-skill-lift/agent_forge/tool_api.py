"""Local OpenAPI 3 tool inventory and JSON request-body validation.

Public entry points: load_tool_api(path), parse_openapi(mapping_or_text).
ToolAPI.operations is keyed only by operationId or the final path component.
Descriptions are retained verbatim; policy requirements mentioned in prose
(such as conditional close reasons) are not invented as schema constraints.
No requests are sent. Validation covers the schema keywords implemented below;
format and other annotations are retained, not treated as policy enforcement.
"""

from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote

import yaml

__all__ = [
    "ToolAPI", "ToolOperation", "ToolAPIError", "RequestValidationError",
    "load_tool_api", "parse_openapi", "validate_json",
]

_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
_MISSING = object()
_ANNOTATIONS = {"description", "title", "summary", "example", "examples", "default"}


class ToolAPIError(ValueError):
    """An unsupported or ambiguous API contract."""


class RequestValidationError(ToolAPIError):
    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("Invalid request: " + "; ".join(errors))


class _Resolver:
    def __init__(self, document: dict):
        self.document = document

    def resolve(self, value: Any, stack: tuple[str, ...] = (), depth: int = 0) -> Any:
        if depth > 100:
            raise ToolAPIError("Reference/schema nesting exceeds 100 levels (possible cycle)")
        if isinstance(value, list):
            return [self.resolve(v, stack, depth + 1) for v in value]
        if not isinstance(value, dict):
            return copy.deepcopy(value)
        if "$ref" not in value:
            return {k: self.resolve(v, stack, depth + 1) for k, v in value.items()}
        reference = value["$ref"]
        if not isinstance(reference, str) or not reference.startswith("#"):
            raise ToolAPIError(f"Unsupported external $ref: {reference!r}; only local references are allowed")
        pointer = unquote(reference[1:])
        if pointer and not pointer.startswith("/"):
            raise ToolAPIError(f"Unsupported local $ref anchor: {reference!r}; use a JSON pointer")
        # Canonicalize percent-encoded pointers before checking cycles.
        canonical = "#" + pointer
        if canonical in stack:
            raise ToolAPIError("Cyclic local $ref: " + " -> ".join((*stack, canonical)))
        target: Any = self.document
        try:
            for part in pointer.split("/")[1:] if pointer else ():
                key = part.replace("~1", "/").replace("~0", "~")
                target = target[int(key)] if isinstance(target, list) else target[key]
        except (KeyError, IndexError, TypeError, ValueError):
            raise ToolAPIError(f"Unresolved local $ref: {reference!r}") from None
        resolved = self.resolve(target, (*stack, canonical), depth + 1)
        siblings = self.resolve({k: v for k, v in value.items() if k != "$ref"}, stack, depth + 1)
        if not siblings:
            return resolved
        if not isinstance(resolved, dict):
            raise ToolAPIError(f"$ref with siblings must resolve to an object: {reference!r}")
        # Never weaken a referenced schema by overwriting a repeated constraint.
        constraints = (set(resolved) & set(siblings)) - _ANNOTATIONS
        if constraints:
            annotations = {k: v for k, v in {**resolved, **siblings}.items() if k in _ANNOTATIONS}
            return {**annotations, "allOf": [resolved, siblings]}
        return {**resolved, **siblings}


def _schemas(content: Any, label: str) -> dict[str, Any]:
    if not isinstance(content, dict):
        raise ToolAPIError(f"{label}.content must be an object")
    out = {}
    for media, entry in content.items():
        if not isinstance(media, str) or not isinstance(entry, dict):
            raise ToolAPIError(f"{label}.content entries must be media-type objects")
        schema = entry.get("schema", {})
        if not isinstance(schema, (dict, bool)):
            raise ToolAPIError(f"{label} schema must be an object or boolean")
        out[media] = copy.deepcopy(schema)
    return out


def _preferred_schema(schemas: dict[str, Any]) -> Any:
    if "application/json" in schemas:
        return schemas["application/json"]
    json_media = [key for key in schemas if key.split(";")[0].endswith("+json")]
    if len(json_media) == 1:
        return schemas[json_media[0]]
    if len(schemas) == 1:
        return next(iter(schemas.values()))
    if schemas:
        raise ToolAPIError("Ambiguous request media types; specify content_type when validating")
    return None


@dataclass
class ToolOperation:
    name: str
    path: str
    method: str
    url: str
    summary: str
    description: str
    request_required: bool
    request_schemas: dict[str, Any]
    response_schemas: dict[str, dict[str, Any]]
    response_descriptions: dict[str, str]
    parameters: list[dict[str, Any]]

    @property
    def request_schema(self) -> Any:
        """Preferred decoded-body schema, or None when no body is declared."""
        return _preferred_schema(self.request_schemas)

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(asdict(self))

    def validate_request(self, body: Any = _MISSING, *, content_type: str | None = None) -> list[str]:
        """Validate a decoded body; URL/query/header parameters are inventoried separately."""
        if body is _MISSING:
            return ["body: request body is required"] if self.request_required else []
        if content_type is not None:
            if content_type not in self.request_schemas:
                return [f"body: undeclared content type {content_type!r}"]
            schema = self.request_schemas[content_type]
        else:
            schema = self.request_schema
        if schema is None:
            return ["body: operation declares no request body"]
        return validate_json(schema, body, path="body")

    def require_valid_request(self, body: Any = _MISSING, *, content_type: str | None = None) -> None:
        errors = self.validate_request(body, content_type=content_type)
        if errors:
            raise RequestValidationError(errors)


@dataclass
class ToolAPI:
    openapi_version: str
    title: str
    operations: dict[str, ToolOperation]

    def to_dict(self) -> dict[str, Any]:
        return {
            "openapi_version": self.openapi_version,
            "title": self.title,
            "operations": {name: op.to_dict() for name, op in self.operations.items()},
        }

    def discover_tools(self, text: str) -> list[str]:
        """Exact, case-sensitive allowlist matches, ordered by first mention.

        Never infer tools from schema enums, outcome codes, descriptions or
        substrings such as create_promise_status.
        """
        hits = []
        for name in self.operations:
            match = re.search(r"(?<![\w])" + re.escape(name) + r"(?![\w])", text)
            if match:
                hits.append((match.start(), name))
        return [name for _, name in sorted(hits)]

    def validate_request(self, name: str, body: Any = _MISSING, *, content_type: str | None = None) -> list[str]:
        try:
            operation = self.operations[name]
        except KeyError:
            raise ToolAPIError(f"Unknown tool: {name!r}") from None
        return operation.validate_request(body, content_type=content_type)


def _server_url(servers: Any) -> str:
    if not isinstance(servers, list) or not servers or not isinstance(servers[0], dict):
        raise ToolAPIError("servers must contain at least one server object")
    server = servers[0]
    url = server.get("url")
    if not isinstance(url, str) or not url:
        raise ToolAPIError("Server URL must be a non-empty string")
    variables = server.get("variables", {})
    if not isinstance(variables, dict):
        raise ToolAPIError("Server variables must be an object")
    def replacement(match):
        name = match.group(1)
        variable = variables.get(name, {})
        if not isinstance(variable, dict) or "default" not in variable:
            raise ToolAPIError(f"Server variable {name!r} has no default")
        return str(variable["default"])
    return re.sub(r"\{([^{}]+)\}", replacement, url)


def parse_openapi(document: Mapping[str, Any] | str) -> ToolAPI:
    """Parse an OpenAPI 3 mapping or JSON/YAML text without any external I/O."""
    if isinstance(document, str):
        try:
            document = yaml.safe_load(document)
        except yaml.YAMLError as exc:
            raise ToolAPIError(f"Invalid OpenAPI JSON/YAML: {exc}") from None
    if not isinstance(document, Mapping):
        raise ToolAPIError("OpenAPI document must be an object")
    document = copy.deepcopy(dict(document))
    version = document.get("openapi")
    if not isinstance(version, str) or not re.fullmatch(r"3\.\d+\.\d+(?:[-+].+)?", version):
        raise ToolAPIError("Expected an OpenAPI 3 document with an openapi version")
    paths = document.get("paths")
    if not isinstance(paths, dict):
        raise ToolAPIError("OpenAPI paths must be an object")
    resolver = _Resolver(document)
    default_servers = document.get("servers", [{"url": "/"}])
    operations: dict[str, ToolOperation] = {}
    for path, raw_item in paths.items():
        if not isinstance(path, str) or not path.startswith("/"):
            raise ToolAPIError(f"Invalid operation path: {path!r}")
        item = resolver.resolve(raw_item)
        if not isinstance(item, dict):
            raise ToolAPIError(f"Path item {path!r} must be an object")
        for method, operation in item.items():
            if method not in _METHODS:
                continue
            if not isinstance(operation, dict):
                raise ToolAPIError(f"{method.upper()} {path}: operation must be an object")
            name = operation.get("operationId", path.rstrip("/").rsplit("/", 1)[-1])
            if not isinstance(name, str) or not name.strip() or re.search(r"[{}\s]", name):
                raise ToolAPIError(f"{method.upper()} {path}: supply an unambiguous operationId")
            if name in operations:
                previous = operations[name]
                raise ToolAPIError(f"Duplicate tool name {name!r}: {previous.method} {previous.path} and {method.upper()} {path}")
            servers = operation.get("servers", item.get("servers", default_servers))
            server = _server_url(resolver.resolve(servers))
            body = operation.get("requestBody", {})
            if not isinstance(body, dict):
                raise ToolAPIError(f"{name}.requestBody must be an object")
            required = body.get("required", False)
            if not isinstance(required, bool):
                raise ToolAPIError(f"{name}.requestBody.required must be boolean")
            requests = _schemas(body.get("content", {}), f"{name}.requestBody")
            responses = operation.get("responses", {})
            if not isinstance(responses, dict):
                raise ToolAPIError(f"{name}.responses must be an object")
            response_schemas, response_descriptions = {}, {}
            for status, response in responses.items():
                if not isinstance(response, dict):
                    raise ToolAPIError(f"{name}.responses[{status!r}] must be an object")
                response_schemas[str(status)] = _schemas(response.get("content", {}), f"{name}.response[{status}]")
                response_descriptions[str(status)] = response.get("description", "")
            parameters = {}
            for entries in (item.get("parameters", []), operation.get("parameters", [])):
                if not isinstance(entries, list):
                    raise ToolAPIError(f"{name}.parameters must be an array")
                for parameter in entries:
                    if not isinstance(parameter, dict) or "name" not in parameter or "in" not in parameter:
                        raise ToolAPIError(f"{name}: parameter needs name and in")
                    parameters[(parameter["in"], parameter["name"])] = parameter
            operations[name] = ToolOperation(
                name=name, path=path, method=method.upper(), url=server.rstrip("/") + path,
                summary=operation.get("summary", ""), description=operation.get("description", ""),
                request_required=required, request_schemas=requests,
                response_schemas=response_schemas, response_descriptions=response_descriptions,
                parameters=list(parameters.values()),
            )
    info = document.get("info") or {}
    if not isinstance(info, dict):
        raise ToolAPIError("OpenAPI info must be an object")
    contract = ToolAPI(version, info.get("title", ""), operations)
    try:
        json.dumps(contract.to_dict(), allow_nan=False)
    except (TypeError, ValueError):
        raise ToolAPIError("OpenAPI contract contains non-JSON values; quote YAML date/string literals") from None
    return contract


def load_tool_api(path: str | Path) -> ToolAPI:
    """Load a local UTF-8 JSON/YAML document, never an HTTP URL."""
    if isinstance(path, str) and "://" in path:
        raise ToolAPIError("load_tool_api accepts local file paths only")
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise ToolAPIError(f"Cannot read tool API document: {exc}") from None
    return parse_openapi(text)


def _json_equal(left: Any, right: Any) -> bool:
    # Python otherwise considers True == 1, including inside enum objects.
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_json_equal(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_json_equal(a, b) for a, b in zip(left, right))
    return left == right


def _is_type(value: Any, kind: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "boolean": isinstance(value, bool),
        "number": type(value) in (int, float),
        "integer": type(value) is int or (type(value) is float and math.isfinite(value) and value.is_integer()),
        "null": value is None,
    }.get(kind, False)


def validate_json(schema: dict | bool, value: Any, *, path: str = "$") -> list[str]:
    """Return field-level schema errors; no coercion, defaults or policy inference."""
    errors: list[str] = []
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        return [f"{path}: value must be JSON-serializable with finite numbers"]
    def check(spec, data, here):
        if spec is True:
            return
        if spec is False:
            errors.append(f"{here}: schema forbids this value")
            return
        if not isinstance(spec, dict):
            raise ToolAPIError(f"{here}: invalid schema")
        for branch in spec.get("allOf", []):
            check(branch, data, here)
        for keyword in ("anyOf", "oneOf"):
            if keyword in spec:
                matches = sum(not validate_json(branch, data, path=here) for branch in spec[keyword])
                if matches == 0 or (keyword == "oneOf" and matches != 1):
                    errors.append(f"{here}: does not satisfy {keyword}")
        if "not" in spec and not validate_json(spec["not"], data, path=here):
            errors.append(f"{here}: matches forbidden schema")
        kinds = spec.get("type")
        kinds = [kinds] if isinstance(kinds, str) else kinds
        if kinds and not (data is None and spec.get("nullable") is True):
            if not any(_is_type(data, kind) for kind in kinds):
                errors.append(f"{here}: expected {' or '.join(kinds)}")
                return
        if "enum" in spec and not any(_json_equal(data, v) for v in spec["enum"]):
            errors.append(f"{here}: value is outside enum {spec['enum']!r}")
        if "const" in spec and not _json_equal(data, spec["const"]):
            errors.append(f"{here}: value differs from const")
        if type(data) in (int, float):
            for key, comparison in (("minimum", lambda a, b: a < b), ("maximum", lambda a, b: a > b)):
                if key in spec and comparison(data, spec[key]):
                    errors.append(f"{here}: violates {key} {spec[key]}")
            for key, bound_key, comparison in (
                ("exclusiveMinimum", "minimum", lambda a, b: a <= b),
                ("exclusiveMaximum", "maximum", lambda a, b: a >= b),
            ):
                bound = spec.get(key)
                bound = spec.get(bound_key) if bound is True else None if bound is False else bound
                if bound is not None and comparison(data, bound):
                    errors.append(f"{here}: violates {key} {bound}")
        if isinstance(data, dict):
            for name in spec.get("required", []):
                if name not in data:
                    errors.append(f"{here}.{name}: required field is missing")
            properties = spec.get("properties", {})
            additional = spec.get("additionalProperties", True)
            for name, child in data.items():
                if not isinstance(name, str):
                    errors.append(f"{here}: object keys must be strings")
                elif name in properties:
                    check(properties[name], child, f"{here}.{name}")
                elif additional is False:
                    errors.append(f"{here}.{name}: additional field is not allowed")
                elif isinstance(additional, dict):
                    check(additional, child, f"{here}.{name}")
        if isinstance(data, list):
            for key, comparison in (("minItems", lambda a, b: a < b), ("maxItems", lambda a, b: a > b)):
                if key in spec and comparison(len(data), spec[key]):
                    errors.append(f"{here}: violates {key} {spec[key]}")
            if spec.get("uniqueItems") and any(_json_equal(a, b) for i, a in enumerate(data) for b in data[i + 1:]):
                errors.append(f"{here}: array items must be unique")
            if "items" in spec:
                for index, child in enumerate(data):
                    check(spec["items"], child, f"{here}[{index}]")
        if isinstance(data, str):
            for key, comparison in (("minLength", lambda a, b: a < b), ("maxLength", lambda a, b: a > b)):
                if key in spec and comparison(len(data), spec[key]):
                    errors.append(f"{here}: violates {key} {spec[key]}")
            if "pattern" in spec and not re.search(spec["pattern"], data):
                errors.append(f"{here}: does not match pattern")
    check(schema, value, path)
    return errors
