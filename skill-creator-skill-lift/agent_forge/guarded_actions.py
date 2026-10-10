"""Small JSON-safe action gate, shared with generated Freya code snippets.

Policy, state, facts and events are TRUSTED adapter inputs, never extraction/model
outputs. This is logical integrity within that boundary, not a signed token or a
transcript verifier. A readback event's delivered flag and normalized receipts
must come from actual evidence. No function calls an API or makes speech claims.

Required policy shape (values and provenance are supplied by the caller):
version, source_policy_parameters, calendar(now/holidays/weekmask/week_start),
ordered products(product_id/deadline/minimum/maximum/quantum/max_write_attempts),
and capabilities. Each capability specifies effect (promise/write/read), request
schema, product/amount/date field names (or None), requires_confirmation,
required_facts and request_bindings (request field -> trusted fact name).
Money policy parameters are exact decimal strings. Action request_json retains
the original numeric JSON lexemes; it is the only authorized dispatch body.

Events: propose/correction/user/abandon/confirm advance revision by exactly one;
readback uses the current revision and delivered=True; result correlates the
pending action_id with status succeeded/no_write/unknown. Successful writes need
a nonempty receipt_id. Unknown writes remain pending until matching evidence
settles them; retry budgets are total requests, including the first.

For notes or other conditional writes, capabilities can require trusted facts
such as an established input cutoff and a non-transfer terminal decision. This
module does not establish that physical cutoff or infer terminal policy itself.
"""

import datetime
import inspect
import json
import re


class _Rejected(Exception):
    def __init__(self, code, path):
        self.violations = [dict(code=code, path=path, details=dict())]


class _JsonNumber(str):
    """A JSON numeric lexeme, distinguishable from a JSON string."""


def _require(condition, code, path):
    if not condition:
        raise _Rejected(code, path)


def _plain(value):
    return json.loads(json.dumps(value, allow_nan=False))


def _unique_object(pairs):
    result = dict()
    for key, value in pairs:
        _require(key not in result, "duplicate_json_field", key)
        result[key] = value
    return result


def _invalid_constant(value):
    raise _Rejected("nonfinite_json", "request")


def _request(text):
    _require(type(text) is str, "request_json_required", "request")
    try:
        value = json.loads(text, parse_float=_JsonNumber, parse_constant=_invalid_constant,
                           object_pairs_hook=_unique_object)
    except (ValueError, TypeError):
        raise _Rejected("invalid_request_json", "request") from None
    _require(type(value) is dict, "request_object_required", "request")
    return value


def _ratio(value):
    _require(type(value) is int or isinstance(value, str), "invalid_money", "amount")
    text = str(value)
    match = re.fullmatch(r"(-?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d+))?", text)
    _require(match is not None and len(text) <= 1024, "invalid_money", "amount")
    fraction = match.group(3) or ""
    exponent = int(match.group(4) or "0") - len(fraction)
    # Resource bounds, not financial policy: do not build enormous integers.
    _require(abs(exponent) <= 1024, "number_out_of_range", "amount")
    numerator = int(match.group(2) + fraction) * (-1 if match.group(1) else 1)
    return (numerator * 10 ** max(exponent, 0), 10 ** max(-exponent, 0))


def _equal(left, right):
    numeric = lambda v: type(v) is int or isinstance(v, (_JsonNumber, float))
    if numeric(left) and numeric(right):
        a, b = _ratio(str(left))
        c, d = _ratio(str(right))
        return a * d == c * b
    if type(left) is dict and type(right) is dict:
        return left.keys() == right.keys() and all(_equal(left[k], right[k]) for k in left)
    if type(left) is list and type(right) is list:
        return len(left) == len(right) and all(_equal(a, b) for a, b in zip(left, right))
    return type(left) is type(right) and left == right


def _schema_supported(schema):
    _require(type(schema) is dict, "invalid_request_schema", "schema")
    supported = {"type", "properties", "required", "additionalProperties", "enum", "minimum", "maximum",
                 "items", "minItems", "maxItems", "minLength", "maxLength", "description", "title", "format"}
    _require(set(schema) <= supported, "unsupported_schema_keyword", "schema")
    _require(schema.get("type") in {"object", "string", "number", "integer", "boolean", "array", "null"},
             "unsupported_schema_type", "schema.type")
    if "format" in schema:
        _require(schema["format"] in {"date", "date-time"}, "unsupported_schema_format", "schema.format")
    for child in schema.get("properties", dict()).values():
        _schema_supported(child)
    if "items" in schema:
        _schema_supported(schema["items"])
    if type(schema.get("additionalProperties")) is dict:
        _schema_supported(schema["additionalProperties"])


def _validate(schema, value, path="request"):
    kind = schema["type"]
    valid = {"object": type(value) is dict, "string": type(value) is str,
             "number": type(value) is int or isinstance(value, _JsonNumber),
             "integer": type(value) is int, "boolean": type(value) is bool,
             "array": type(value) is list, "null": value is None}[kind]
    if kind == "integer" and isinstance(value, _JsonNumber):
        n, d = _ratio(value)
        valid = n % d == 0
    _require(valid, "request_type_mismatch", path)
    if "enum" in schema:
        _require(any(_equal(value, permitted) for permitted in schema["enum"]), "request_enum_mismatch", path)
    if kind in {"number", "integer"}:
        n, d = _ratio(value)
        for key in ("minimum", "maximum"):
            if key in schema:
                bound, denominator = _ratio(str(schema[key]))
                ok = n * denominator >= bound * d if key == "minimum" else n * denominator <= bound * d
                _require(ok, "request_" + key, path)
    if kind == "object":
        properties = schema.get("properties", dict())
        for key in schema.get("required", []):
            _require(key in value, "request_field_missing", path + "." + key)
        for key, child in value.items():
            child_schema = properties.get(key, schema.get("additionalProperties", True))
            _require(child_schema is not False, "request_extra_field", path + "." + key)
            if type(child_schema) is dict:
                _validate(child_schema, child, path + "." + key)
    if kind in {"string", "array"}:
        low, high = ("minLength", "maxLength") if kind == "string" else ("minItems", "maxItems")
        _require(len(value) >= schema.get(low, 0), "request_" + low, path)
        _require(high not in schema or len(value) <= schema[high], "request_" + high, path)
    if kind == "array" and "items" in schema:
        for index, child in enumerate(value):
            _validate(schema["items"], child, path + "[" + str(index) + "]")
    if schema.get("format") == "date":
        _date(value)
    if schema.get("format") == "date-time":
        try:
            datetime.datetime.fromisoformat(value)
        except (TypeError, ValueError):
            raise _Rejected("invalid_datetime", path) from None


def _date(value):
    _require(type(value) is str and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None,
             "invalid_date", "date")
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise _Rejected("invalid_date", "date") from None


def _check_policy(policy):
    _require(type(policy) is dict and type(policy.get("version")) is str and bool(policy["version"]),
             "policy_version_required", "policy")
    _require(type(policy.get("source_policy_parameters")) is dict and bool(policy["source_policy_parameters"]),
             "source_policy_parameters_required", "policy")
    cal = policy["calendar"]
    datetime.datetime.fromisoformat(cal["now"])
    _require(bool(cal["weekmask"]) and all(type(n) is int and 0 <= n < 7 for n in cal["weekmask"]),
             "invalid_weekmask", "calendar.weekmask")
    _require(type(cal["week_start"]) is int and 0 <= cal["week_start"] < 7, "invalid_week_start", "calendar.week_start")
    for day in cal["holidays"]:
        _date(day)
    identifiers = []
    for product in policy["products"]:
        identifier = product["product_id"]
        _require(type(identifier) is str and bool(identifier) and identifier not in identifiers,
                 "invalid_product_id", "products")
        identifiers.append(identifier)
        _date(product["deadline"])
        for field in ("minimum", "maximum", "quantum"):
            _require(type(product[field]) is str, "decimal_policy_string_required", field)
        low, ld = _ratio(product["minimum"])
        high, hd = _ratio(product["maximum"])
        quantum, _ = _ratio(product["quantum"])
        _require(low >= 0 and high * ld >= low * hd and quantum > 0, "invalid_money_policy", identifier)
        _require(type(product["max_write_attempts"]) is int and product["max_write_attempts"] >= 0,
                 "invalid_retry_budget", identifier)
    _require(type(policy["capabilities"]) is dict, "invalid_capabilities", "capabilities")
    for name, capability in policy["capabilities"].items():
        _require(type(name) is str and bool(name), "invalid_capability", "capabilities")
        _require(capability["effect"] in {"promise", "write", "read"}, "invalid_effect", name)
        _require(type(capability["requires_confirmation"]) is bool, "invalid_confirmation_policy", name)
        _require(type(capability["required_facts"]) is dict and type(capability["request_bindings"]) is dict,
                 "invalid_fact_policy", name)
        _require(all(capability.get(k) is None or type(capability[k]) is str and bool(capability[k])
                     for k in ("product_field", "amount_field", "date_field")), "invalid_field_mapping", name)
        if capability["effect"] == "promise" or capability["requires_confirmation"]:
            fields = [capability.get(k) for k in ("product_field", "amount_field", "date_field")]
            _require(None not in fields and len(set(fields)) == 3 and capability["requires_confirmation"],
                     "confirmation_field_mapping_required", name)
        _schema_supported(capability["request_schema"])
        _require(capability["request_schema"]["type"] == "object", "request_object_required", name)


def _check_state(policy, state):
    _require(state["policy_version"] == policy["version"], "policy_version_mismatch", "state")
    order = [p["product_id"] for p in policy["products"]]
    _require(state["product_order"] == order and set(state["products"]) == set(order), "product_inventory_mismatch", "state")
    _require(type(state["call_revision"]) is int and state["call_revision"] >= 0, "invalid_call_revision", "state")
    _require(type(state["next_action_id"]) is int and state["next_action_id"] > 0, "invalid_action_id", "state")


def _terms(policy, product_id, amount, day):
    product = next((p for p in policy["products"] if p["product_id"] == product_id), None)
    _require(product is not None, "unknown_product", "product_id")
    n, d = _ratio(amount)
    low, ld = _ratio(product["minimum"])
    high, hd = _ratio(product["maximum"])
    quantum, qd = _ratio(product["quantum"])
    _require(n * ld >= low * d, "amount_below_floor", "amount")
    _require(n * hd <= high * d, "amount_above_ceiling", "amount")
    _require((n * qd) % (d * quantum) == 0, "amount_off_quantum", "amount")
    value = _date(day)
    cal = policy["calendar"]
    today = datetime.datetime.fromisoformat(cal["now"]).date()
    _require(value >= today, "date_before_today", "date")
    _require(value <= _date(product["deadline"]), "date_after_deadline", "date")
    _require(value.weekday() in cal["weekmask"] and day not in cal["holidays"], "non_business_day", "date")
    return dict(amount=str(amount), date=day)


def _same_terms(left, right):
    a, b = _ratio(left["amount"])
    c, d = _ratio(right["amount"])
    return a * d == c * b and left["date"] == right["date"]


def new_state(policy, *, facts):
    """Initialize trusted state; products retain the backend's supplied order."""
    _check_policy(policy)
    _require(type(facts) is dict, "invalid_facts", "facts")
    products = dict()
    for product in policy["products"]:
        products[product["product_id"]] = dict(proposed=None, confirmed=None, confirmation_revision=None,
                                              recorded=None, attempts=0)
    return _plain(dict(policy_version=policy["version"], call_revision=0, next_action_id=1,
                       product_order=list(products), products=products, facts=facts, readback=None, pending=None))


def _invalidate(state):
    state["readback"] = None
    for product in state["products"].values():
        product["confirmed"] = None
        product["confirmation_revision"] = None


def _event(policy, state, event):
    kind = event["kind"]
    if kind == "result":
        _require(set(event) <= {"kind", "action_id", "status", "receipt_id"}, "unexpected_event_field", "event")
        pending = state["pending"]
        _require(pending is not None and type(event.get("action_id")) is int
                 and event["action_id"] == pending["envelope"]["action_id"], "unexpected_backend_result", "result")
        status = event["status"]
        _require(status in {"succeeded", "no_write", "unknown"}, "invalid_backend_status", "result")
        if status == "unknown":
            pending["status"] = "unknown"
            return
        envelope = pending["envelope"]
        capability = policy["capabilities"][envelope["capability"]]
        if status == "succeeded":
            _require(type(event.get("receipt_id")) is str and bool(event["receipt_id"]), "backend_receipt_required", "result")
            if capability["effect"] == "promise":
                product = state["products"][envelope["product_id"]]
                product["recorded"] = dict(terms=pending["terms"], receipt_id=event["receipt_id"], action_id=event["action_id"])
                product["proposed"] = None
                product["confirmed"] = None
                product["confirmation_revision"] = None
                state["readback"] = None
        state["pending"] = None
        return
    _require(type(event.get("revision")) is int, "invalid_event_revision", "event")
    if kind == "readback":
        _require(set(event) == {"kind", "revision", "delivered"}, "unexpected_event_field", "event")
        _require(event["revision"] == state["call_revision"], "stale_event_revision", "event")
        _require(state["pending"] is None, "backend_action_pending", "event")
        _require(event.get("delivered") is True, "readback_evidence_required", "event")
        terms = [dict(product_id=p, terms=state["products"][p]["proposed"])
                 for p in state["product_order"] if state["products"][p]["proposed"] is not None]
        _require(bool(terms), "empty_readback", "event")
        state["readback"] = dict(revision=state["call_revision"], promises=terms)
        return
    _require(kind in {"propose", "correction", "user", "confirm", "abandon"}, "unknown_event", "event")
    _require(event["revision"] == state["call_revision"] + 1, "stale_event_revision", "event")
    readback = state["readback"]
    previous_revision = state["call_revision"]
    state["call_revision"] = event["revision"]
    _invalidate(state)  # Persist this even when replacement/request validation fails.
    fields = {"kind", "revision"}
    if kind == "confirm":
        fields.update(("accepted", "readback_revision"))
    elif kind in {"propose", "correction"}:
        fields.update(("product_id", "amount", "date"))
    elif kind == "abandon":
        fields.add("product_id")
    _require(set(event) <= fields, "unexpected_event_field", "event")
    if kind == "user":
        return
    _require(state["pending"] is None, "backend_action_pending", "event")
    if kind == "confirm":
        _require(type(event.get("accepted")) is bool, "explicit_confirmation_required", "event")
        if not event["accepted"]:
            return
        _require(readback is not None and readback["revision"] == previous_revision
                 and type(event.get("readback_revision")) is int and event["readback_revision"] == previous_revision,
                 "stale_readback", "event")
        for item in readback["promises"]:
            product = state["products"][item["product_id"]]
            _require(product["proposed"] == item["terms"], "stale_readback", "event")
        for item in readback["promises"]:
            product = state["products"][item["product_id"]]
            product["confirmed"] = _plain(item["terms"])
            product["confirmation_revision"] = state["call_revision"]
        return
    product_id = event.get("product_id")
    _require(product_id in state["products"], "unknown_product", "product_id")
    product = state["products"][product_id]
    _require(product["recorded"] is None, "recorded_promise_immutable", "product_id")
    product["proposed"] = None
    if kind != "abandon":
        product["proposed"] = _terms(policy, product_id, event.get("amount"), event.get("date"))


def action_envelope(policy, state, capability, request_json):
    """Build an untrusted candidate; guard_dispatch must authorize/reserve it."""
    config = policy["capabilities"][capability]
    request = _request(request_json)
    product_id = request.get(config["product_field"]) if config.get("product_field") else None
    product = state["products"].get(product_id, dict())
    return dict(action_id=state["next_action_id"], policy_version=policy["version"],
                call_revision=state["call_revision"], confirmation_revision=product.get("confirmation_revision"),
                product_id=product_id, capability=capability, request_json=request_json)


def _dispatch(policy, state, envelope):
    _require(type(envelope) is dict and set(envelope) == {"action_id", "policy_version", "call_revision",
             "confirmation_revision", "product_id", "capability", "request_json"}, "invalid_action_envelope", "action")
    _require(envelope["policy_version"] == policy["version"], "policy_version_mismatch", "action")
    _require(type(envelope["call_revision"]) is int and envelope["call_revision"] == state["call_revision"],
             "stale_action_revision", "action")
    _require(type(envelope["action_id"]) is int and envelope["action_id"] == state["next_action_id"], "stale_action_id", "action")
    _require(state["pending"] is None, "backend_action_pending", "action")
    name = envelope["capability"]
    _require(name in policy["capabilities"], "capability_not_allowed", "action")
    capability = policy["capabilities"][name]
    request = _request(envelope["request_json"])
    _validate(capability["request_schema"], request)
    for fact, expected in capability["required_facts"].items():
        _require(fact in state["facts"] and _equal(state["facts"][fact], expected), "required_fact_missing", fact)
    for field, fact in capability["request_bindings"].items():
        _require(field in request and fact in state["facts"] and _equal(request[field], state["facts"][fact]),
                 "request_binding_mismatch", field)
    product_id = request.get(capability["product_field"]) if capability.get("product_field") else None
    _require(product_id == envelope["product_id"], "action_product_mismatch", "product_id")
    product = state["products"].get(product_id)
    if product_id is not None:
        _require(product is not None, "unknown_product", "product_id")
    terms = None
    if capability["requires_confirmation"]:
        _require(product is not None and product["recorded"] is None, "recorded_promise_immutable", "product_id")
        _require(type(envelope["confirmation_revision"]) is int
                 and envelope["confirmation_revision"] == state["call_revision"]
                 and product["confirmation_revision"] == state["call_revision"] and product["confirmed"] is not None,
                 "current_confirmation_required", "action")
        terms = _terms(policy, product_id, request.get(capability["amount_field"]), request.get(capability["date_field"]))
        _require(product["proposed"] is not None and _same_terms(terms, product["proposed"])
                 and _same_terms(terms, product["confirmed"]), "request_terms_mismatch", "action")
    if capability["effect"] == "promise":
        first = next((p for p in state["product_order"] if state["products"][p]["proposed"] is not None), None)
        _require(first == product_id, "backend_order_violation", "product_id")
        config = next(p for p in policy["products"] if p["product_id"] == product_id)
        _require(product["attempts"] < config["max_write_attempts"], "retry_budget_exhausted", "action")
        product["attempts"] += 1
    state["pending"] = dict(envelope=_plain(envelope), status="dispatched", terms=terms)
    state["next_action_id"] += 1


def guard_command(policy, state, command):
    """Return updated state even for rejected corrections; callers must persist it."""
    working = None
    try:
        _check_policy(policy)
        working = _plain(state)
        _check_state(policy, working)
        if command["kind"] == "event":
            _event(policy, working, command["event"])
            return dict(state=working, flag="accepted", violations=[], request_json="")
        _require(command["kind"] == "dispatch", "unknown_command", "command")
        _dispatch(policy, working, command["envelope"])
        return dict(state=working, flag="allowed", violations=[], request_json=command["envelope"]["request_json"])
    except _Rejected as error:
        return dict(state=working, flag="blocked", violations=error.violations, request_json="")
    except Exception:
        return dict(state=working, flag="blocked", violations=[dict(code="invalid_guard_input", path="command", details=dict())], request_json="")


def reduce_event(policy, state, event):
    return guard_command(policy, state, dict(kind="event", event=event))


def guard_dispatch(policy, state, envelope):
    return guard_command(policy, state, dict(kind="dispatch", envelope=envelope))


_PORTABLE = (_Rejected, _JsonNumber, _require, _plain, _unique_object, _invalid_constant, _request,
             _ratio, _equal, _schema_supported, _validate, _date, _check_policy, _check_state, _terms,
             _same_terms, _invalidate, _event, _dispatch, guard_command)


def lower_guard_snippet(*, policy_var="guard_policy_json", state_var="guard_state_json",
                        command_var="guard_command_json", flag_var="guard_flag",
                        violations_var="guard_violations_json", request_var="guard_request_json"):
    """Return code_exec source: only json/re/datetime imports, no I/O or API calls.

    Always reset dispatch outputs. 'allowed' is emitted only for a reserved action;
    event reductions emit 'accepted'. Policy/state/command vars accept JSON strings
    or objects. The parent must route on flag=='allowed' and use request_var exactly.
    """
    names = (policy_var, state_var, command_var, flag_var, violations_var, request_var)
    if len(set(names)) != len(names) or not all(type(n) is str and re.fullmatch(r"[A-Za-z_]\w*", n) for n in names):
        raise ValueError("Guard variable names must be distinct identifiers")
    source = "import json\nimport re\nimport datetime\n\n" + "\n\n".join(inspect.getsource(function) for function in _PORTABLE)
    wrapper = f"""
vars[{flag_var!r}] = 'blocked'
vars[{violations_var!r}] = '[]'
vars[{request_var!r}] = ''
try:
    _policy_input = vars.get({policy_var!r})
    _state_input = vars.get({state_var!r})
    _command_input = vars.get({command_var!r})
    _policy_input = json.loads(_policy_input) if isinstance(_policy_input, str) else _policy_input
    _state_input = json.loads(_state_input) if isinstance(_state_input, str) else _state_input
    _command_input = json.loads(_command_input) if isinstance(_command_input, str) else _command_input
    _guard_result = guard_command(_policy_input, _state_input, _command_input)
    if _guard_result['state'] is not None:
        vars[{state_var!r}] = json.dumps(_guard_result['state'], allow_nan=False)
    vars[{violations_var!r}] = json.dumps(_guard_result['violations'], allow_nan=False)
    vars[{request_var!r}] = _guard_result['request_json']
    vars[{flag_var!r}] = _guard_result['flag']
except Exception:
    vars[{flag_var!r}] = 'blocked'
    vars[{request_var!r}] = ''
    vars[{violations_var!r}] = json.dumps([dict(code='invalid_guard_input', path='command', details=dict())])
"""
    # Space adjacent dict braces: Freya can treat them as template delimiters.
    return (source + wrapper).replace("{{", "{ {").replace("}}", "} }")
