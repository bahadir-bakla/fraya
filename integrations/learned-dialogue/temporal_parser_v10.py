"""Source-only bounded temporal AST. Syntax is a hypothesis, never permission.

No labels, normalization values, models, I/O, or authority enter this module.
Offsets always address the original Python Unicode string. R4 atoms may be
attached by the offline diagnostic, but never supervise this parser.
"""
import re

VERSION = "typed_temporal_parser.v10.1"
MONTHS = set("january february march april may june july august september october november december".split())
WEEKDAYS = set("monday tuesday wednesday thursday friday saturday sunday".split())
ORDINALS = set("first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth thirtieth last final".split())
NUMBERS = set("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty".split())
PERIODS = set("day days week weeks month months year years quarter quarters summer winter spring autumn fall morning afternoon evening".split())
TOKEN = re.compile(r"\.\.\.|…|[^\W\d_]+(?:['’][^\W\d_]+)?|\d+(?:st|nd|rd|th)?|[^\s]", re.I)
EVENT_NOUNS = set("statement deposit payment salary payday trip flight return arrival departure plan line refund".split())
EVENT_VERBS = set("arrives arriving arrival closes closing clears clearing resumes resuming restarts restarting happens happening drops dropping lands landing returns returning ends ending answer answering confirm confirming".split())
MASKS = {"training": False, "qualification": False, "target": False,
         "reference": False, "normalization": False, "permission": False}
FEATURE_VERSION = "typed_temporal_source_features.v10.1"


def join_syntax(children, holes, local_status="closed"):
    """A required child's uncertainty cannot disappear at a composite join."""
    statuses = [local_status] + [c["syntax"] for c in children]
    if "unsupported" in statuses:
        return "unsupported"
    if "ambiguous" in statuses:
        return "ambiguous"
    if holes or "open" in statuses:
        return "open"
    return "closed"


def scope_from_source(text, start, end, clause_start, clause_end, context):
    """Clause-owned comma topics and exact coordinated target attachments."""
    targets = context.get("targets", [])
    universe = {t["index"] for t in targets}
    if len(universe)!=len(targets):
        return None,"ambiguous_target_index_metadata",[]
    before = text[clause_start:start]
    cut = max(before.rfind(","), before.rfind("—")) + 1
    local, offset = before[cut:], clause_start + cut
    patterns = [(t["index"], r"(?<!\w)" + r"\s+".join(re.escape(w) for w in t["label"].split()) + r"(?!\w)") for t in targets]

    def target_phrase(fragment, base, require_full=False):
        prefix = re.match(r"\s*(?:both\s+)?", fragment, re.I)
        pos, chosen, spans = prefix.end(), [], []
        while True:
            matches = [(idx, m) for idx, pattern in patterns if (m := re.match(pattern, fragment[pos:], re.I))]
            if not matches:
                return None, [], "unsupported_target_phrase"
            longest = max(len(m.group()) for idx, m in matches)
            matches = [(idx, m) for idx, m in matches if len(m.group()) == longest]
            if len({idx for idx, m in matches}) != 1:
                return None, [], "ambiguous_metadata_label"
            idx, match = matches[0]
            chosen.append(idx)
            spans.append((base + pos, base + pos + len(match.group())))
            pos += len(match.group())
            coordinator = re.match(r"\s+and\s+", fragment[pos:], re.I)
            if coordinator:
                pos += coordinator.end()
                continue
            if require_full and fragment[pos:].strip():
                return None, [], "unsupported_target_phrase"
            return sorted(set(chosen)), spans, None

    attached = re.match(r"\s+for\s+", text[end:clause_end], re.I)
    if attached:
        base = end + attached.end()
        chosen, spans, error = target_phrase(text[base:clause_end], base)
        if chosen or error == "ambiguous_metadata_label":
            return chosen, error or "explicit_postposed_attachment", spans
    # A comma topic belongs to this clause, not an old component or turn. It
    # survives local repair commas, but a new explicit governor supersedes it.
    topics = []
    for match in re.finditer(r"(?=(?:^|,)\s*for\s+([^,]+),)", before, re.I):
        base = clause_start + match.start(1)
        chosen, spans, error = target_phrase(match.group(1), base, True)
        if chosen or error == "ambiguous_metadata_label":
            topics.append((chosen, spans, error))
    mentions = []
    for idx, pattern in patterns:
        for match in re.finditer(pattern, local, re.I):
            mentions.append((match.start(), match.end(), idx, offset + match.start(), offset + match.end()))
    if mentions:
        mentions.sort()
        same_last = [m for m in mentions if m[:2] == mentions[-1][:2]]
        if len({m[2] for m in same_last}) > 1:
            return None, "ambiguous_metadata_label", []
        first = mentions[0][0]
        both = re.search(r"\bboth\s*$", local[:first], re.I)
        coordinated = len(mentions) > 1 and both and all(re.fullmatch(r"\s*and\s*", local[a[1]:b[0]], re.I) for a,b in zip(mentions, mentions[1:]))
        chosen = mentions if coordinated else [mentions[-1]]
        return sorted({m[2] for m in chosen}), "explicit_local_governor", [(m[3],m[4]) for m in chosen]
    if topics:
        chosen, spans, error = topics[-1]
        return chosen, error or "explicit_clause_topic", spans
    indexes = (context.get("question") or {}).get("target_indices")
    if indexes and any(i not in universe for i in indexes):
        return None, "invalid_question_target_reference", []
    if indexes and len(indexes) > 1 and re.search(r"\b(?:(?:this|that)\s+(?:one|plan|item|account|balance)|it)\b", local, re.I):
        return None, "unresolved_singular_reference", []
    return (list(indexes) if indexes else None), "question_fallback_hypothesis" if indexes else "unknown", []


def source_governor(text, start, end, clause_start, clause_end):
    """Finite governing evidence beyond the lexical feature window."""
    prefix = text[clause_start:start]
    quote = prefix.count('"') % 2 == 1 or prefix.count('“') > prefix.count('”')
    actions = list(re.finditer(r"\b(?:(?:do\s+not|don't|never)\s+|please\s+)?(?:schedule|use|uses|pay|paying|set)\b", prefix, re.I))
    role, polarity, evidence = "uncertain", "unassessed", []
    if actions:
        action = actions[-1]
        evidence = [(clause_start+action.start(),clause_start+action.end())]
        negative = bool(re.match(r"(?:do\s+not|don't|never)\b", action.group(), re.I))
        role = "negated_proposal_hypothesis" if negative else "current_hypothesis"
        polarity = "negated_hypothesis" if negative else "asserted_hypothesis"
    if re.search(r"\b(?:if|would|could)\b", prefix, re.I):
        role, polarity = "conditional_hypothesis", "conditional_hypothesis"
    if text[clause_start:clause_end].rstrip().endswith("?"):
        role, polarity = "question_hypothesis", "question_hypothesis"
    if quote:
        role, polarity = "quoted_hypothesis", "quoted_hypothesis"
    return role, polarity, evidence


def production_key(node):
    return (node["i"], node["j"], node["kind"], tuple(node["operators"]))


def owned_keys(node):
    result = set(node.get("equivalent_parse_keys", []))
    for child in node["children"]:
        result.add(production_key(child))
        result.update(owned_keys(child))
    return result


def maximal_owned(parses):
    """Geometry alone is insufficient; suppress only explicit AST children."""
    ownership = [owned_keys(p) for p in parses]
    return [p for p in parses if not any(production_key(p) in keys for keys in ownership)]


def span(text, a, b):
    if not (type(a) is int and type(b) is int and 0 <= a <= b <= len(text)):
        raise ValueError("invalid source extent")
    return {"char_start": a, "char_end": b, "text": text[a:b],
            "offset_unit": "python_unicode_codepoints",
            "utf8_byte_start": len(text[:a].encode("utf-8")),
            "utf8_byte_end": len(text[:b].encode("utf-8"))}


def privacy_reasons(context, text):
    q = context.get("question") or {}
    reasons = []
    if context.get("phase") == "security" or q.get("role") == "security" or q.get("security_field") is not None:
        reasons.append("security_context")
    if re.search(r"\b(?:password|passcode|security\s+code|social\s+security|cvv|pin\s+code)\b", text, re.I):
        reasons.append("unisolated_secret_surface")
    return reasons


def project_segments(text, raw, semantic, attachments=(), markers=()):
    """Lossless typed partition; never deletes an operator to obtain a match."""
    a, b = raw
    sa, sb = semantic
    if not 0 <= a <= sa <= sb <= b <= len(text):
        raise ValueError("semantic extent not contained")
    for left, right in attachments:
        if not a <= left < right <= b or not re.fullmatch(r"\s*(?:(?:on|for)\s*)+", text[left:right], re.I):
            raise ValueError("only source-recognized ON/FOR attachment can project")
    for left, right in markers:
        if not a <= left < right <= b or text[left:right] not in {"...", "…"}:
            raise ValueError("invalid source marker")
    pieces = []
    boundaries = sorted({a, b, sa, sb} | {x for pair in attachments for x in pair} | {x for pair in markers for x in pair})
    for left, right in zip(boundaries, boundaries[1:]):
        if left == right:
            continue
        kind = "semantic"
        if any(x <= left and right <= y for x, y in attachments):
            kind = "attachment"
        elif any(x <= left and right <= y for x, y in markers):
            kind = "marker"
        elif not sa <= left < right <= sb:
            if re.fullmatch(r"[\s,.]*", text[left:right]):
                kind = "formatting"
            else:
                raise ValueError("unclassified nonsemantic source")
        pieces.append({"kind": kind, "span": span(text, left, right)})
    if "".join(x["span"]["text"] for x in pieces) != text[a:b]:
        raise ValueError("lossless reconstruction failed")
    return {"raw_extent": span(text, a, b), "semantic_extent": span(text, sa, sb),
            "segments": pieces, "reconstruction_lossless": True,
            "equivalence": "unqualified_typed_projection_hypothesis", "masks": dict(MASKS)}


def parse_temporal(text, source_event_id, context=None, variant="A3"):
    """Return source hypotheses only. No annotation arguments are accepted.

    Limits: 4096 codepoints/source; 512/expression; 80 tokens/clause;
    12 clauses; 16 top candidates; recursive grammar depth <= 6.
    Overflow is explicit and fail closed, never silently truncated.
    """
    context = {} if context is None else context
    out = {"version": VERSION, "source_event_id": source_event_id, "variant": variant,
           "nodes": [], "top_level_ids": [], "correction_edges": [], "abstain": True,
           "qualified": False, "absence_established": False, "masks": dict(MASKS), "diagnostics": []}
    if type(text) is not str or type(source_event_id) is not str or not source_event_id or len(source_event_id) > 128:
        out["diagnostics"].append("missing_source_binding")
        return out
    if type(context) is not dict or type(context.get("question", {})) not in {dict, type(None)} or type(context.get("targets", [])) is not list:
        out["diagnostics"].append("malformed_source_context")
        return out
    if len(context.get("targets", [])) > 16 or any(type(t) is not dict or type(t.get("index")) is not int or t["index"]<0 or type(t.get("label")) is not str or not t["label"] for t in context.get("targets", [])):
        out["diagnostics"].append("malformed_target_metadata")
        return out
    qtargets = (context.get("question") or {}).get("target_indices", [])
    if qtargets is not None and (type(qtargets) is not list or any(type(i) is not int for i in qtargets)):
        out["diagnostics"].append("malformed_question_scope")
        return out
    if qtargets and any(i not in {t["index"] for t in context.get("targets", [])} for i in qtargets):
        out["diagnostics"].append("invalid_question_target_reference")
    blocked = privacy_reasons(context, text)
    if blocked:
        out["diagnostics"] = blocked
        return out
    if len(text) > 4096 or context.get("locale", "en") != "en":
        out["diagnostics"].append("unsupported_source_or_locale")
        return out
    tokens = [{"value": m.group().casefold(), "start": m.start(), "end": m.end()} for m in TOKEN.finditer(text)]
    cuts = [0] + [m.end() for m in re.finditer(r";|\n|(?<![\d.])[.!?](?!\.)\s+|\s+\bbut\b\s+", text, re.I)] + [len(text)]
    clauses = [(a, b) for a, b in zip(cuts, cuts[1:]) if text[a:b].strip()]
    if len(clauses) > 12:
        out["diagnostics"].append("clause_overflow")
        return out
    composed = variant in {"A2", "A3", "A4"}
    events = variant == "A3"
    attachment_enabled = variant != "A4"
    for ci, (ca, cb) in enumerate(clauses):
        ts = [t for t in tokens if ca <= t["start"] and t["end"] <= cb]
        n = len(ts)
        if n > 80:
            out["diagnostics"].append("token_overflow:c" + str(ci))
            continue
        memo = {}

        def v(i):
            return ts[i]["value"] if 0 <= i < n else ""

        def num(i):
            if v(i) in ORDINALS | NUMBERS or re.fullmatch(r"\d+(?:st|nd|rd|th)?", v(i)):
                j = i + 1
                if v(i) in {"twenty", "thirty"} and v(j) == "-" and v(j + 1) in ORDINALS | NUMBERS:
                    j += 2
                return j
            return None

        def node(i, j, kind, children=(), operators=(), holes=(), syntax="closed", reference=False):
            if j <= i:
                return None
            owned_holes = []
            owner = kind + ":" + str(i) + ":" + str(j)
            for h in [h for c in children for h in c["holes"]] + list(holes):
                item = tuple(h) if len(h) == 3 else (h[0], h[1], owner)
                if item not in owned_holes:
                    owned_holes.append(item)
            equivalent = [(i + 1, j, kind, tuple(operators))] if v(i) in {"the", "a", "an", "my", "our"} and j > i + 1 else []
            return {"i": i, "j": j, "kind": kind, "children": list(children), "operators": list(operators),
                    "equivalent_parse_keys": equivalent,
                    "holes": owned_holes, "syntax": join_syntax(children, owned_holes, syntax), "reference_required": reference,
                    "attachment_tokens": [], "marker_tokens": [], "semantic_i": i, "semantic_j": j}

        def missing(i, j, kind, hole, children=(), operators=()):
            # An unknown lexical operand is not synonymous with unfinished speech.
            status = "open" if not v(j) or v(j) in {"...", "…", ";", ".", "and", "or", "to", "until"} else "unsupported"
            return node(i, j, kind, children, operators, [(hole, j)], status, True)

        def atom(i, operand=False):
            s = i
            j = i + 1 if v(i) in {"the", "a", "an", "my", "our"} else i
            x = v(j)
            if not x:
                return None
            if x in MONTHS:
                if x == "may" and v(j+1) in {"i","we","you"} and v(j+2) in {"ask","call","have","pay","speak"}:
                    if "modal_may_disambiguated" not in out["diagnostics"]:
                        out["diagnostics"].append("modal_may_disambiguated")
                    return None
                k = j + 1
                if v(k) == "the" and composed:
                    k += 1
                    z = num(k)
                    if not z:
                        return missing(s, k, "calendar", "day")
                    k = z
                else:
                    k = num(k) or k
                if v(k) == "," and re.fullmatch(r"\d{4}", v(k + 1)):
                    k += 2
                elif re.fullmatch(r"\d{4}", v(k)):
                    k += 1
                return node(s, k, "calendar")
            if re.fullmatch(r"\d{4}", x) and v(j + 1) == "-" and re.fullmatch(r"\d{1,2}", v(j + 2)) and v(j + 3) == "-":
                k = j + 4
                return node(s, k + 1, "calendar") if re.fullmatch(r"\d{1,2}", v(k)) else missing(s, k, "calendar", "day")
            z = num(j)
            if composed and z and (v(z) in WEEKDAYS or v(z) in {"working", "business"} and v(z + 1) == "day"):
                k = z + (2 if v(z) in {"working", "business"} else 1)
                anchor = node(z, k, "calendar" if v(z) in WEEKDAYS else "relative", reference=True)
                children = [anchor]
                if v(k) in {"of", "in"}:
                    operator = (k, k + 1, v(k))
                    p = atom(k + 1, True)
                    if p:
                        h = p["j"]
                        if events and v(h) == "in" and v(h + 1) == "which":
                            event = atom(h + 2, True)
                            if event and event["kind"] == "event_time":
                                p = node(p["i"], event["j"], "relative", [p, event], [(h, h + 2, "in which")], reference=True)
                            else:
                                p = missing(p["i"], h + 2, "relative", "event_operand", [p], [(h, h + 2, "in which")])
                        return node(s, p["j"], "nth_period", children + [p], [operator], p["holes"], p["syntax"], True)
                    # Preserve an interrupted dependency as unsupported, with
                    # its entire literal interruption; never delete it to close.
                    if v(k + 1) == "," and v(k + 2) == "while":
                        ends = [h for h in range(k + 3, n - 1) if v(h) == "," and v(h + 1) in MONTHS]
                        if len(ends) == 1:
                            h = ends[0]
                            delayed = atom(h + 1, True)
                            r = node(s, delayed["j"], "nth_period", children + [delayed], [operator], [("period", k + 1)], "unsupported", True)
                            r["interruption_tokens"] = [(k + 1, h + 1)]
                            return r
                    return missing(s, k + 1, "nth_period", "period", children, [operator])
                return node(s, k, "nth_period", children, reference=True)
            if z and v(z) == "of" and v(z + 1) in MONTHS:
                k = z + 2
                if re.fullmatch(r"\d{4}", v(k)):
                    k += 1
                return node(s, k, "calendar", operators=[(z, z + 1, "of")])
            if z and v(z) == "of":
                return missing(s, z + 1, "calendar", "month", operators=[(z, z + 1, "of")])
            if z and v(z) in MONTHS:
                return node(s, z + 1, "calendar")
            if z and (v(z) in {"day", "days"} or v(z) in {"working", "business"} and v(z + 1) in {"day", "days"}):
                k = z + (2 if v(z) in {"working", "business"} else 1)
                return node(s, k, "offset", reference=True)
            if x in WEEKDAYS:
                k = j + 1
                p = atom(k + 1 if v(k) == "," else k)
                if p and p["kind"] == "calendar" and v(k + (v(k) == ",")) in MONTHS:
                    return node(s, p["j"], "calendar", [node(j, j + 1, "calendar"), p])
                return node(s, k, "calendar")
            if x in {"next", "this", "last", "following", "another", "that"} and v(j + 1) in PERIODS | {"date"}:
                return node(s, j + 2, "reference" if x in {"another", "that", "following"} else "relative", reference=True)
            if x in {"today", "tomorrow", "yesterday"}:
                return node(s, j + 1, "relative", reference=True)
            if events and x == "day" and v(j + 1) in {"the", "my", "our"}:
                e = atom(j + 1, True)
                if e and e["kind"] == "event_time":
                    return node(s, e["j"], "event_time", [e], reference=True)
            if x in PERIODS and (j > s or operand):
                if events and x == "day" and v(j + 1) in {"early", "late"}:
                    return node(s, j + 2, "relative", reference=True)
                return node(s, j + 1, "relative", reference=True)
            if events and operand and x in {"that", "it"}:
                if v(j + 1) in EVENT_VERBS:
                    return node(s, j + 2, "event_time", reference=True)
                return node(s, j + 1, "reference", reference=True)
            if events and x == "those" and v(j + 1) == "two" and v(j + 2) == "events":
                return node(s, j + 3, "reference", reference=True)
            if events and operand and x in EVENT_NOUNS | {"i", "you", "he", "she", "it", "that"} and v(j + 1) in EVENT_VERBS:
                return node(s, j + 2, "event_time", reference=True)
            if events and operand and (x == "payment" and v(j + 1) == "window" or x == "instalment" and v(j + 1) == "plan") and v(j + 2) in EVENT_VERBS:
                return node(s, j + 3, "event_time", reference=True)
            if events and operand and x == "direct" and v(j + 1) == "debit" and v(j + 2) == "is" and v(j + 3) == "posted":
                return node(s, j + 4, "event_time", reference=True)
            if events and operand and x == "statement" and v(j + 1) == "being" and v(j + 2) == "issued":
                return node(s, j + 3, "event_time", reference=True)
            if events and x in {"now", "later"}:
                return node(s, j + 1, "administrative_time", reference=True)
            if events and x == "at" and v(j + 1) == "this" and v(j + 2) == "point":
                return node(s, j + 3, "administrative_time", reference=True)
            if events and x == "at" and v(j + 1) == "once":
                return node(s, j + 2, "administrative_time", reference=True)
            if events and x == "for" and v(j + 1) == "a" and v(j + 2) == "moment":
                return node(s, j + 3, "administrative_time", reference=True)
            return None

        def expression(i, depth=0, operand=False):
            key = (i, depth, operand)
            if key in memo:
                return memo[key]
            if depth > 6 or i >= n:
                return None
            x = v(i)
            r = None
            if composed and x in {"between", "from", "either"}:
                kind = "alternative" if x == "either" else "range"
                p = expression(i + 1, depth + 1, True)
                if p:
                    k = p["j"]
                    allowed = {"or"} if x == "either" else ({"and"} if x == "between" else {"to", "until"})
                    if v(k) in allowed:
                        q = expression(k + 1, depth + 1, True)
                        ops = [(i, i + 1, x), (k, k + 1, v(k))]
                        hole = "second_operand" if kind == "alternative" else "second_endpoint"
                        r = node(i, q["j"], kind, [p, q], ops, p["holes"] + q["holes"], q["syntax"], p["reference_required"] or q["reference_required"]) if q else missing(i, k + 1, kind, hole, [p], ops)
                        if q and v(k) == "until":
                            r["equivalent_parse_keys"].append((k, q["j"], q["kind"], ((k, k + 1, "until"),)))
                        if x == "either":
                            r["equivalent_parse_keys"].append((i+1,r["j"],"alternative",((k,k+1,"or"),)))
                    else:
                        r = missing(i, k, kind, "connector", [p], [(i, i + 1, x)])
            elif composed and x == "the" and v(i+1) in {"earlier","later"} and v(i+2) == "of":
                p = expression(i+3,depth+1,True)
                if p:
                    k = p["j"]
                    q = expression(k+1,depth+1,True) if v(k)=="and" else None
                    r = node(i,q["j"] if q else k+(v(k)=="and"),"comparison",[p]+([q] if q else []),
                             [(i,i+3,"comparison_"+v(i+1))]+([(k,k+1,"and")] if v(k)=="and" else []),
                             [] if q else [("second_operand",k+1)],"unsupported",True)
            elif x in {"on", "for", "by", "until", "before", "after"}:
                p = expression(i + 1, depth + 1, True)
                if p:
                    if x in {"on", "for"}:
                        if attachment_enabled:
                            r = dict(p)
                            r["i"] = i
                            r["equivalent_parse_keys"] = [production_key(p)] + p.get("equivalent_parse_keys", [])
                            r["attachment_tokens"] = [(i, i + 1)] + p["attachment_tokens"]
                    else:
                        kind = "administrative_time" if p["kind"] == "event_time" and v(i + 1) == "i" else p["kind"]
                        r = node(i, p["j"], kind, [p], [(i, i + 1, "upper_bound" if x == "by" else x)], p["holes"], p["syntax"], p["reference_required"])
                elif x == "until" and v(i + 1) == "the" and v(i + 2) in {"", "...", "…"}:
                    r = missing(i, i + 2, "relative", "temporal_operand", operators=[(i, i + 1, "until")])
                elif events and x == "for" and v(i + 1) == "a" and v(i + 2) == "moment":
                    r = node(i, i + 3, "administrative_time", reference=True)
            elif events and x == "whichever" and v(i + 1) == "is" and v(i + 2) in {"later", "earlier"}:
                k = i + 3 + (v(i + 3) == ",")
                p = expression(k, depth + 1, True)
                if p and v(p["j"]) == "or":
                    connector = p["j"]
                    q = expression(connector + 1, depth + 1, True)
                    p = node(k, q["j"], "alternative", [p, q], [(connector, connector + 1, "or")], q["holes"], q["syntax"], True) if q else missing(k, connector + 1, "alternative", "second_operand", [p], [(connector, connector + 1, "or")])
                r = node(i, p["j"], "extremum", [p], [(i, i + 3, "extremum_" + v(i + 2))], p["holes"], p["syntax"], True) if p else missing(i, k, "extremum", "event_operand")
                r["equivalent_parse_keys"].append((i + 2, i + 3, "administrative_time", ()))
            else:
                r = atom(i, operand)
                if r:
                    k = r["j"]
                    relation = v(k) in {"before", "after", "following"} or v(k) == "nearest" and v(k + 1) == "to"
                    if composed and relation:
                        end = k + (2 if v(k) == "nearest" else 1)
                        p = expression(end, depth + 1, True)
                        kind = "offset" if r["kind"] == "offset" else "relative"
                        ops = [(k, end, " ".join(v(t) for t in range(k, end)))]
                        r = node(i, p["j"], kind, [r, p], ops, p["holes"], p["syntax"], True) if p else missing(i, end, kind, "temporal_operand", [r], ops)
                    elif composed and not operand and v(k) == "or":
                        p = expression(k + 1, depth + 1, True)
                        r = node(i, p["j"], "alternative", [r, p], [(k, k + 1, "or")], p["holes"], p["syntax"], True) if p else missing(i, k + 1, "alternative", "second_operand", [r], [(k, k + 1, "or")])
            memo[key] = r
            return r

        parsed = [p for i in range(n) if (p := expression(i))]
        # Verified containment, not nearest-span merging. Parents retain children.
        tops = maximal_owned(parsed)
        tops.sort(key=lambda p: (p["i"], -p["j"]))
        dedup = set()
        for p in tops:
            if production_key(p) in dedup:
                continue
            dedup.add(production_key(p))
            # Current source metadata, never reviewed target sets.
            prefix = text[ca:ts[p["i"]]["start"]].casefold()
            chosen, target_source, target_spans = scope_from_source(text, ts[p["i"]]["start"], ts[p["j"] - 1]["end"], ca, cb, context)
            if target_source in {"ambiguous_metadata_label","invalid_question_target_reference","ambiguous_target_index_metadata"} and target_source not in out["diagnostics"]:
                out["diagnostics"].append(target_source)
            mentioned = target_source.startswith("explicit")
            role = "uncertain"
            polarity = "unassessed"
            if mentioned and re.search(r"\b(?:use|uses|pay|paying|schedule|scheduled)\b", prefix):
                role = "current_hypothesis"
            if re.search(r"\b(?:not|instead of)\s*$", prefix):
                role, polarity = "superseded_hypothesis", "negated_hypothesis"
            if re.search(r"\b(?:i mean|i meant|actually|rather|make that)\b[^;]*$", prefix):
                role = "replacement_hypothesis"
            quote_evidence = prefix.count('"') % 2 == 1 or prefix.count('“') > prefix.count('”')
            if quote_evidence:
                polarity = "quoted_hypothesis"
                role = "uncertain"
            if p["kind"] == "administrative_time":
                chosen = None
            governed_role, governed_polarity, governor_spans = source_governor(text,ts[p["i"]]["start"],ts[p["j"]-1]["end"],ca,cb)
            if role not in {"superseded_hypothesis","replacement_hypothesis"} and governed_role != "uncertain":
                role, polarity = governed_role, governed_polarity

            def emit(r, inherited_targets, child=False):
                a, b = ts[r["i"]]["start"], ts[r["j"] - 1]["end"]
                sa, sb = ts[r["semantic_i"]]["start"], ts[r["semantic_j"] - 1]["end"]
                markers = []
                if not child and v(r["j"]) in {"...", "…"}:
                    markers = [(ts[r["j"]]["start"], ts[r["j"]]["end"])]
                    b = markers[-1][1]
                    if r["syntax"] == "closed":
                        r = dict(r, syntax="ambiguous")
                delimiter = v(r["j"]) == "," and not child
                if delimiter:
                    b = ts[r["j"]]["end"]
                if b - a > 512:
                    out["diagnostics"].append("expression_overflow")
                    return None
                attachments = [(ts[l]["start"], ts[h - 1]["end"]) for l, h in r["attachment_tokens"]]
                # Whitespace belonging to attachment is typed with it.
                if attachments:
                    attachments = [(attachments[0][0], sa)] + attachments[1:]
                idx = "n" + str(len(out["nodes"]))
                item = {"node_id": idx, "source_event_id": source_event_id, "clause_id": "c" + str(ci),
                        "parser_version": VERSION, "clause_span": span(text, ca, cb),
                        "variant":variant,
                        "kind": r["kind"], "syntax": r["syntax"], "resolution": "unresolved",
                        "projection": project_segments(text, (a, b), (sa, sb), attachments, markers),
                        "children": [], "holes": [{"expected": h, "boundary": ts[k]["start"] if k < n else cb, "source_owner": owner} for h, k, owner in r["holes"]],
                        "operators": [{"kind": op, "span": span(text, ts[l]["start"], ts[h - 1]["end"])} for l, h, op in r["operators"]],
                        "marker_spans": [span(text, l, h) for l, h in markers],
                        "interruption_spans": [span(text, ts[l]["start"], ts[h - 1]["end"]) for l, h in r.get("interruption_tokens", [])],
                        "declared_equivalent_parse_relations": [{"kind": kind, "span": span(text, ts[l]["start"], ts[h - 1]["end"]), "rule": "optional_determiner_or_owned_operator_projection"} for l, h, kind, ops in r.get("equivalent_parse_keys", [])],
                        "target_indices_hypothesis": inherited_targets,
                        "target_source_hypothesis": target_source,
                        "target_governor_spans": [span(text, a, b) for a, b in target_spans],
                        "role_hypothesis": role, "polarity_hypothesis": polarity,
                        "governor_evidence_spans":[span(text,a,b) for a,b in governor_spans],
                        "relevance_status":"non_temporal_name_hypothesis" if re.match(r"\s+is\s+the\s+name\s+of\b",text[b:cb],re.I) else "unqualified",
                        "maximality_status":"unsupported_comparison" if r["kind"]=="comparison" else "unqualified",
                        "quotation_evidence": quote_evidence, "reference_required": r["reference_required"],
                        "reference_mask": False, "normalization_mask": False, "masks": dict(MASKS),
                        "mask_reasons": ["source_semantics_unqualified", "ancestry_unqualified", "no_parent_admission"]}
                out["nodes"].append(item)
                for c in r["children"]:
                    cid = emit(c, inherited_targets, True)
                    if cid:
                        item["children"].append(cid)
                return idx

            nid = emit(p, chosen)
            if nid:
                out["top_level_ids"].append(nid)
    if len(out["top_level_ids"]) > 16:
        out["diagnostics"].append("candidate_overflow")
        out["top_level_ids"] = []
    previous = None
    for nid in out["top_level_ids"]:
        item = next(x for x in out["nodes"] if x["node_id"] == nid)
        if item["role_hypothesis"] == "superseded_hypothesis":
            previous = item
        elif item["role_hypothesis"] == "replacement_hypothesis" and previous:
            old_targets = previous["target_indices_hypothesis"]
            new_targets = item["target_indices_hypothesis"]
            if old_targets and new_targets and set(old_targets) == set(new_targets):
                out["correction_edges"].append({"old": previous["node_id"], "new": nid,
                    "component_scope": "date", "relation": "compatible_scoped_source_order_supersession_hypothesis", "qualified": False})
            else:
                out.setdefault("unresolved_correction_relations", []).append({"old": previous["node_id"], "new": nid,
                    "reason": "unequal_explicit_targets" if old_targets and new_targets else "unknown_target_scope", "qualified": False})
            previous = None
    # Shared source evidence groups overlap hypotheses without declaring
    # equivalence, suppressing them, or manufacturing independent facts.
    components = []
    tops = [n for n in out["nodes"] if n["node_id"] in out["top_level_ids"]]
    for n in tops:
        s = n["projection"]["raw_extent"]
        touching = [c for c in components if any(s["char_start"] < m["projection"]["raw_extent"]["char_end"] and m["projection"]["raw_extent"]["char_start"] < s["char_end"] for m in c)]
        combined = [n]+[m for c in touching for m in c]
        components = [c for c in components if c not in touching]+[combined]
    out["hypothesis_families"] = [{"family_id":"f"+str(i),"members":[n["node_id"] for n in c],"relation":"shared_source_evidence_not_equivalence", "independent_training_units":0,"qualified":False} for i,c in enumerate(components)]
    return out


def typed_signature(node):
    """Diagnostic signature. Source role/target/markers are part of equivalence."""
    return (node["kind"], node["projection"]["semantic_extent"]["text"].casefold(),
            tuple(x["kind"] for x in node["operators"]), tuple(x["expected"] for x in node["holes"]),
            node["role_hypothesis"], node["polarity_hypothesis"], tuple(node["target_indices_hypothesis"] or []),
            tuple(x["text"] for x in node["marker_spans"]))


def source_features_v10(text, node, context=None, privacy_isolated=False, framing_verified=False,
                       expected_parser_version=VERSION, expected_feature_version=FEATURE_VERSION):
    """Portable source-local sparse counts, without reviewer offsets or labels.

    Independent privacy/framing flags are required for offline mechanics. They
    do not authenticate a deployment stream or enable any training/permission.
    No R4 weights or feature-version aliases are accepted.
    """
    context = {} if context is None else context
    result = {"feature_version": FEATURE_VERSION, "parser_version": VERSION,
              "features": {}, "abstain": True, "training_mask": False,
              "qualified": False, "reasons": []}
    if type(text) is not str or type(node) is not dict or type(context) is not dict or type(context.get("question",{})) not in {dict,type(None)}:
        result["reasons"].append("malformed_typed_feature_input")
        return result
    if expected_parser_version != VERSION or expected_feature_version != FEATURE_VERSION or node.get("parser_version") != VERSION:
        result["reasons"].append("parser_or_feature_version_mismatch")
        return result
    if privacy_isolated is not True or privacy_reasons(context, text):
        result["reasons"].append("privacy_isolation_unqualified")
        return result
    if framing_verified is not True:
        result["reasons"].append("source_framing_unqualified")
        return result
    canonical = parse_temporal(text,node.get("source_event_id"),context,node.get("variant","A3"))
    matching = [n for n in canonical["nodes"] if n["node_id"]==node.get("node_id")]
    if len(matching)!=1 or any(node.get(k)!=value for k,value in matching[0].items()):
        result["reasons"].append("external_node_structure_mismatch")
        return result
    source = node["projection"]["raw_extent"]
    clause = node["clause_span"]
    a, b = source["char_start"], source["char_end"]
    if not 0 <= clause["char_start"] <= a < b <= clause["char_end"] <= len(text) or source["text"] != text[a:b]:
        result["reasons"].append("source_boundary_mismatch")
        return result
    if node["syntax"] == "unsupported" or node["interruption_spans"]:
        result["reasons"].append("unsupported_dependency_mask")
        return result
    start, end = max(clause["char_start"], a - 48), min(clause["char_end"], b + 48)
    window = text[start:end]
    result["source_window_span"] = span(text, start, end)
    values = {}
    def add(key):
        values[key] = values.get(key, 0) + 1
    add("bias")
    for key, value in (("kind", node["kind"]), ("syntax", node["syntax"]), ("phase", context.get("phase", "unknown")),
                       ("question_role", (context.get("question") or {}).get("role", "unknown")),
                       ("scope_source", node["target_source_hypothesis"])):
        add(key + "=" + str(value))
    add("source_role="+node["role_hypothesis"])
    add("source_polarity="+node["polarity_hypothesis"])
    add("governor_visibility="+("source_bound" if node["governor_evidence_spans"] else "unknown"))
    for h in node["holes"]:
        add("hole=" + h["expected"])
    for op in node["operators"]:
        add("operator=" + op["kind"])
    for marker in node["marker_spans"]:
        add("marker=" + marker["text"])
    add("child_count=" + str(len(node["children"])))
    normalized = re.sub(r"\d+(?:st|nd|rd|th)?", "<number>", window.casefold())
    words = re.findall(r"<number>|[^\W\d_]+", normalized)
    for word in words:
        add("w=" + word)
    for left, right in zip(words, words[1:]):
        add("w2=" + left + " " + right)
    for width in (3, 4):
        for index in range(len(normalized) - width + 1):
            add("c" + str(width) + "=" + normalized[index:index + width])
    if len(values) > 4096:
        result["reasons"].append("feature_overflow")
        return result
    result["features"] = dict(sorted(values.items()))
    result["mechanical_source_feature_eligible"] = True
    return result
