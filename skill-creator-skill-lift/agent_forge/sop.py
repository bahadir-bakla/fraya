"""Split an SOP document into numbered clauses and classify how binding each one is.

Every artifact the forge produces (workflow node, prompt instruction, guard
rule, test) cites the clause it came from, so the clause ids here are the
backbone of traceability and of per-clause mutation testing.

Accepted input is plain text or Markdown, the shape a bank PDF has after text
extraction: headings, then numbered clauses (``3.2 ...``). Unnumbered
paragraphs under a heading become clauses ``<section>.p<n>``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Binding-strength cues. Turkish SOPs mostly use passive negatives
# ("paylaşılmaz", "yapılmaz") and necessity suffixes ("-malı/-meli");
# English uses modal verbs.
_PROHIBIT = [
    r"\b\w+(ıl|il|ul|ül|n)maz\b", r"\b\w+(ıl|il|ul|ül|n)mez\b", r"\byasak", r"\bolamaz\b", r"\bverilmez\b",
    r"\w+(ıl|il|ul|ül|n)[ae]m[ae]z\b", r"\bmust not\b", r"\bnever\b", r"\bshall not\b", r"\bdo not\b", r"\bmay not\b", r"\bprohibited\b",
]
_REQUIRE = [
    r"\w+(ma|me)l[ıi]", r"\bzorunlu", r"\bşarttır\b",
    r"\w+(ıl|il|ul|ül|n)ır\b", r"\w+(ıl|il|ul|ül|n)ir\b", r"\w+(ıl|il|ul|ül|n)ur\b", r"\w+(ıl|il|ul|ül|n)ür\b",
    r"\bmust\b", r"\bshall\b", r"\brequired\b", r"\brequires\b", r"\bneeds\b", r"\bis transferred\b",
    r"\btransfer to\b", r"\bgerekir\b", r"\bgereklidir\b",
    r"\bthe agent (asks|states|collects|reads|verifies|transfers)\b",
    r"\bmay only\b", r"\bonly (?:after|once|when|if)\b",
    r"\b[a-z]+(?:_[a-z]+)+\b",  # a clause that names a tool is a step of the procedure, imperative or not
]
_INFO = [r"\bkapsar\b", r"\bkapsam", r"\bscope\b", r"\bapplies to\b", r"\billustrative\b", r"\börnektir\b"]


@dataclass(frozen=True)
class Clause:
    id: str  # "3.2" or "12"
    section: str  # heading text the clause sits under
    text: str
    strength: str  # "must" | "must_not" | "info"
    source_file: str = ""
    start_line: int = 0
    end_line: int = 0

    @property
    def ref(self) -> str:
        return f"§{self.id}"

    @property
    def normative(self) -> bool:
        return self.strength != "info"


def classify(text: str) -> str:
    low = text.lower()
    if any(re.search(p, low) for p in _INFO):
        return "info"
    if any(re.search(p, low) for p in _PROHIBIT):
        return "must_not"
    if any(re.search(p, low) for p in _REQUIRE):
        return "must"
    return "info"


_NUMBERED = re.compile(
    r"^\s*(?:§\s*)?(?:(?P<dotted>\d+(?:\.\d+)+)[.)]?|(?P<flat>\d+)[.)])\s+(?P<body>.+)$"
)
_HEADING = re.compile(r"^\s*#{1,6}\s+(.+)$")


def parse_sop(text: str, *, source_file: str = "", include_preamble: bool = False) -> tuple[str, list[Clause]]:
    """Return (title, clauses). Wrapped lines are joined to their clause."""
    title = ""
    section = "Document" if include_preamble else ""
    clauses: list[Clause] = []
    current: list[str] | None = None
    current_id = ""
    para_n = 0
    current_start = 0
    current_end = 0

    def flush() -> None:
        nonlocal current
        if current:
            body = " ".join(s.strip() for s in current).strip()
            if body:
                clauses.append(Clause(current_id, section, body, classify(body), source_file, current_start, current_end))
        current = None

    for line_no, line in enumerate(text.splitlines(), 1):
        h = _HEADING.match(line)
        if h:
            flush()
            if not title:
                title = h.group(1).strip()
                if include_preamble:
                    section = title
                    para_n = 0
            else:
                section = re.sub(r"^\d+[.)]?\s*", "", h.group(1).strip())
                para_n = 0
            continue
        m = _NUMBERED.match(line)
        if m:
            flush()
            current_id, current = m.group("dotted") or m.group("flat"), [m.group("body")]
            current_start = current_end = line_no
            continue
        if not line.strip():
            flush()
            continue
        if current is not None:
            current.append(line)
            current_end = line_no
        elif section:
            # An unnumbered paragraph under a section heading.
            para_n += 1
            current_id = f"{_slug(section)}.p{para_n}"
            current = [line]
            current_start = current_end = line_no
    flush()
    return title, clauses


def load_sop(path: str | Path) -> tuple[str, list[Clause]]:
    return parse_sop(Path(path).read_text(encoding="utf-8"), source_file=str(path))


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:24] or "sec"


# -- Reading a conditional clause ("if the caller says X, do Y with tool_z") -------------------------------
# Language utilities that both compilers use on the clause text. Neither sees the other's output.

CONDITIONAL = re.compile(r"(ederse|belirtirse|cikarsa|isterse|soylerse|derse|bildirirse|\bif\b|\bwhen\b)")
_COND_TR = re.compile(r"(?:musteri|arayan(?: kisi)?|telefona)\s+(.*?)\s*(?:ederse|belirtirse|cikarsa|isterse|soylerse"
                      r"|derse|bildirirse)\b")
_COND_EN = re.compile(r"\b(?:if|when)\s+(?:the\s+)?(?:caller|customer|policyholder|client|person)?\s*"
                      r"(?:says|reports|mentions|states|asks|tells us)?\s*(?:that\s+)?(.*?)(?:,|\bthen\b|$)")
_STOP = {"the", "their", "his", "her", "has", "have", "had", "been", "they", "that", "this", "with", "about", "from",
         "bir", "icin", "olan", "olarak", "kendi", "kendisinin", "musteri", "musterinin", "veya", "gibi", "benzeri"}
_RESUME = re.compile(r"devam edilir|kaldigi yerden|continue|resume|then return|returns to")


# "Don't use waive_fee even if the customer asks": the concessive clause is no condition, and it never turns the
# prohibition into a step.
_CONCESSIVE = re.compile(r",?\s*\b(?:even if|even when|even though|even after|regardless of|no matter)\b[^,;.]*"
                         r"|[^,;.]*?\b\w+s[ae](?:l[ae]r)?\s+(?:bile|dahi)\b", re.I)
_FORBID_BEFORE = re.compile(r"\b(?:never|not|don't|cannot|asla)\b(?:\s+(?!and\b|or\b|ve\b|but\b|then\b)(?!\w+_\w)\w+){0,4}\s*$")
_FORBID_AFTER = re.compile(r"^(?:['’]\w+)?(?:\s+(?!and\b|or\b|ve\b|but\b|then\b)(?!\w+_\w)\w+){0,2}?\s+(?:must not|may not|"
                           r"shall not|should not|cannot|is never|is not|must never|\w*(?:il|ul|n)ma[zs]\w*|"
                           r"\w*(?:il|ul|n)me[zs]\w*|yasak\w*)\b")
_SKIP_VERB = re.compile(r"\b(?:skip\w*|forget\w*|forgot\w*|omit\w*|bypass\w*|leave out|atla\w*|unut\w*|ihmal\w*|es gec\w*)")
_BEFORE_GATE = re.compile(r"\b(?:before|until|unless|without|prior to|only|except|once|\w+m[ae]d[ae]n|sadece|yalnizca|ancak)\b")


def drop_concessive(text: str) -> str:
    return _CONCESSIVE.sub(" ", text)


def forbidden_tools(text: str, tools: list[str]) -> set[str]:
    """Tools the clause forbids outright ("never call waive_fee", "waive_fee istese bile kullanılmaz"). A negated
    skip or forget ("never skip verify_identity", "atlanmaz") requires the step; a prohibition ahead of a gate
    ("not before identity is verified") forbids it only until the gate."""
    f = fold_text(drop_concessive(text))
    out = set()
    for t in tools:
        for m in re.finditer(rf"\b{re.escape(t)}\b", f):
            lo = max([0] + [x.end() for x in re.finditer(r"[;.:](?!\d)", f[:m.start()])])
            hi = next((m.end() + x.start() for x in re.finditer(r"[;.](?!\d)", f[m.end():])), len(f))
            b, a = _FORBID_BEFORE.search(f[lo:m.start()]), _FORBID_AFTER.search(f[m.end():hi])
            hit = (b and b.group(0)) or (a and a.group(0))
            if hit and not _SKIP_VERB.search(hit) and not _BEFORE_GATE.search(f[lo:hi]):
                out.add(t)
    return out


def fold_text(text: str) -> str:
    from .slots import fold

    return fold(text)


def condition_of(text: str, surface: bool = False) -> str:
    """The situation part of a conditional clause, folded: 'adresinin degistigini', 'their address has changed'.

    ``surface=True`` returns the same span as written in the SOP (diacritics and case kept), for spoken lines.
    """
    from .slots import _ASCII

    raw = text.replace("İ", "i").replace("I", "ı")
    f = raw.lower().translate(_ASCII)
    m = _COND_TR.search(f) or _COND_EN.search(f)
    if not m:
        return ""
    if surface and len(f) == len(raw):
        return re.sub(r"\s+", " ", raw[m.start(1):m.end(1)]).strip()
    return re.sub(r"\s+", " ", m.group(1)).strip()


def cue_stems(condition: str) -> list[str]:
    # "suresinin" (its term's) and "suremin" (my term's) share "sure", not "sures": drop the possessive's buffer s.
    words = [re.sub(r"([aeiou])s[iu]n[iu]n$", r"\1", w) for w in re.findall(r"[a-z]+", condition)
             if len(w) >= 4 and w not in _STOP]
    return list(dict.fromkeys(w[:5] for w in words))


def cue_patterns(condition: str) -> list[str]:
    """Regexes a caller's words must match to be in this situation: the two leading content stems, either order."""
    s = cue_stems(condition)
    if len(s) >= 2:
        return [f"{s[0]}.*{s[1]}", f"{s[1]}.*{s[0]}"]
    return s


def resumes(text: str) -> bool:
    """Does the call go back to where it was once this situation is handled?"""
    return bool(_RESUME.search(fold_text(text)))


_RECORD = re.compile(r"kaydedil|kaydet|kayit|record|save|\blog")
_BEFORE = re.compile(r"\bonce(sinde)?\b|\bbefore\b|\bprior to\b")


def recorder_tool(text: str, tools: list[str]) -> str | None:
    """Of the tools a promise clause names, the one that records the promise (not a lookup done along the way)."""
    f = fold_text(text)
    for t in tools:
        if re.search(r"promise|soz|pledge|commit", t):
            return t
    for t in tools:
        i = f.find(t)
        if i >= 0 and _RECORD.search(f[max(0, i - 30):i + len(t) + 30]):
            return t
    return None


def before_step(text: str) -> bool:
    """'Ödeme sözü alınmadan önce ...', 'before the promise ...': the clause describes a step ahead of another."""
    return bool(_BEFORE.search(fold_text(text)))


# -- Procedure order between named tools ("block the card first, then reissue it") --------------------------
# Turkish order words are postpositions and follow the tool they govern ("block_card ile bloke edildikten sonra",
# "reissue_card'dan önce"); English ones are prepositions and precede it ("before reissue_card", "after
# block_card", "then reissue_card"). A sentence-initial "önce" is the adverb "first".
_ORDER_TR = re.compile(r"\b(sonrasinda|sonra|ardindan|akabinde|takiben|izler|izleyen|oncesinde|once)\b")
_ORDER_EN = re.compile(r"\b(before|prior to|precedes|after|following|follows|preceded by|until|then|followed by|next)\b")


def tool_pairs(text: str, tools: list[str]) -> list[tuple[str, str]]:
    """(earlier, later) pairs the clause states between the tools it names, read from its order words. Every
    mention counts, not only the first: "needs approve_manager and approve_lead; approve_manager only after
    approve_lead" reads the second sentence."""
    f = fold_text(text)
    occ = sorted((m.start(), t) for t in dict.fromkeys(tools) for m in re.finditer(rf"\b{re.escape(t)}\b", f))
    if len({t for _, t in occ}) < 2:
        return []

    def prev(i, skip=None):
        return next(((p, t) for p, t in reversed(occ) if p < i and t != skip), (None, None))

    def nxt(i, skip=None):
        return next(((p, t) for p, t in occ if p > i and t != skip), (None, None))

    pairs = []
    for m in _ORDER_TR.finditer(f):
        w, i = m.group(1), m.start()
        w = {"sonrasinda": "sonra", "takiben": "sonra", "akabinde": "sonra", "izler": "sonra", "izleyen": "sonra",
             "oncesinde": "once"}.get(w, w)
        pp, p = prev(i)
        if p is None:
            if w == "once":
                n1p, n1 = nxt(i)
                if n1:
                    pairs.append((n1, nxt(n1p, skip=n1)[1]))  # adverb: "önce A ..., B"
            continue
        # The postposition governs the tool before it; the other side is the next tool, else the one before.
        other = nxt(i, skip=p)[1] or prev(pp, skip=p)[1]
        pairs.append((other, p) if w == "once" else (p, other))  # "A'dan önce B" / "A'dan sonra B"
    for m in _ORDER_EN.finditer(f):
        w, i = m.group(1), m.start()
        (_, p), (np_, n) = prev(i), nxt(i)
        if w in ("before", "prior to", "precedes"):
            if p and n and p != n:
                pairs.append((p, n))  # "A before B"
            elif n:
                pairs.append((nxt(np_, skip=n)[1], n))  # "before B, A"
        elif w in ("after", "following", "follows", "preceded by", "until"):
            if p and n and p != n:
                pairs.append((n, p))  # "B after A"
            elif n:
                pairs.append((n, nxt(np_, skip=n)[1]))  # "after A, B"
        elif p and n:
            pairs.append((p, n))  # "A, then B"
    return list(dict.fromkeys((a, b) for a, b in pairs if a and b and a != b))


def tool_order(text: str, tools: list[str]) -> list[str]:
    """The named tools in the order the clause says to run them; text order where it says nothing."""
    f = fold_text(text)
    names = [t for _, t in sorted((f.find(t), t) for t in dict.fromkeys(tools) if f.find(t) >= 0)]
    pairs = tool_pairs(text, names)
    out: list[str] = []
    left = list(names)
    while left:
        # Kahn's order, text order breaking ties; a contradictory clause falls back to text order.
        ready = [t for t in left if not any(b == t and a in left for a, b in pairs)] or left[:1]
        out.append(ready[0])
        left.remove(ready[0])
    return out


# -- Joins: "only if every check is positive" -------------------------------------------------------------
_ALL = re.compile(r"\b(ikisi de|ikisinin de|hepsi|hepsinin|tumu|tum|butun|her iki|both|all|every|each)\b")
_POSITIVE = re.compile(r"olumlu|onay|gecer|uygun|pass|positive|approv|clear|succeed")
_NEGATIVE = re.compile(r"olumsuz|\bred\b|reddedil|reddeder|onaylanmaz|onay verilmez|basarisiz|aksi halde|aksi takdirde|"
                       r"\w+m[ae]zs[ae]\b|declin|reject|not approved|otherwise|if not\b|\bfails?\b|negative|unsuccessful")
_TO_HUMAN = re.compile(r"aktar|bagla|yonlendir|devred|transfer|hand(?:ed)? (?:the call )?over|escalat|human|supervisor")


def negative_branch(text: str) -> str | None:
    """What the clause says happens when a step comes back negative: 'transfer' (to a human), 'decline' (tell the
    caller), or None when it says nothing about a negative outcome."""
    f = fold_text(text)
    m = _NEGATIVE.search(f)
    if not m:
        return None
    return "transfer" if _TO_HUMAN.search(f[m.start():m.start() + 160]) else "decline"


def join_of(text: str, tools: list[str]) -> dict | None:
    """'Both check_income and check_risk must be positive before extend_due_date': the checks, the action they
    gate, whether the checks have a stated order (an approval chain) or none (parallel checks), and where a
    negative result goes."""
    f = fold_text(text)
    m = next((m for m in _ALL.finditer(f) if _POSITIVE.search(f[m.start():m.start() + 60])), None)
    if not m:
        return _approval_join(text, tools)
    pos = sorted((f.find(t), t) for t in dict.fromkeys(tools) if f.find(t) >= 0)
    lo = max([0] + [x.end() for x in re.finditer(r"[;.](?!\d)", f[:m.start()])])
    hi = next((m.end() + x.start() for x in re.finditer(r"[;.](?!\d)", f[m.end():])), len(f))
    before = [t for p, t in pos if p < m.start()]
    after = [t for p, t in pos if p > m.start()]
    if len(after) >= 2 and (len(before) == 1 or all(map(is_approval_tool, after))
                            and not any(map(is_approval_tool, before))):
        # "X only if both A and B approve"; "X and Y only if both approvals are positive".
        checks, acts = after, tool_order(text, [t for p, t in pos if lo <= p < m.start()] or before[-1:])
    elif len(before) >= 2 and after:
        # "Only if both are positive, X and Y": every coordinated action runs, in the stated order.
        checks, acts = before, tool_order(text, [t for p, t in pos if m.start() < p < hi] or after[:1])
    else:
        return None
    pairs = [(a, b) for a, b in tool_pairs(text, checks) if a in checks and b in checks]
    out = {"checks": tool_order(text, checks) if pairs else checks, "action": acts[-1], "ordered": bool(pairs),
           "on_fail": negative_branch(text) or "decline"}
    if len(acts) > 1:
        out.update(gates=list(out["checks"]), acts=acts, ordered=True)
        out["checks"] = out["checks"] + acts[:-1]
    return out


_APPROVAL_TOOL = re.compile(r"approv|onay|authori[sz]|sign_?off|clearance")


_PRODUCE = re.compile(r"^(?:compute|calculate|calc|hesapla|estimate|quote|prepare|draft|generate|build|simulate|offer|"
                      r"propose|price|fetch|lookup|find|get|list|plan_options)|_(?:options|quote|offer|estimate)$")
_COMMIT = re.compile(r"^(?:record|save|kaydet|issue|apply|book|submit|execute|commit|finali[sz]e|send|pay|transfer|"
                     r"update|extend|set|cancel|close|refund|register|store|confirm)")


def step_role(tool: str) -> int | None:
    """0 computes something later steps use (a plan, a quote), 1 approves or checks it, 2 commits it (records,
    issues). Approval and recording consume what the computing step produces, so this order holds whatever the
    wording says; None when the name does not tell."""
    if _APPROVAL_TOOL.search(tool):
        return 1
    if _PRODUCE.search(tool):
        return 0
    if _COMMIT.search(tool):
        return 2
    return None


def data_order(steps: list[str], stated: list[tuple[str, str]] = ()) -> list[str]:
    """The steps in the order the SOP states; where it states none, by what each consumes (a computing step
    before the approval before the commit). Recording a request before it goes for approval is a stated order
    the roles never override."""
    role = {t: step_role(t) for t in steps}
    keep = [(a, b) for a, b in stated if a in steps and b in steps]
    dep = [(a, b) for a in steps for b in steps
           if role[a] is not None and role[b] is not None and role[a] < role[b] and (b, a) not in keep]
    return _kahn(list(steps), keep + dep)


_IF_APPROVED = re.compile(r"\b(?:only )?(?:if|once|when|after|provided) (?:it |the \w+ |they |he |she |this )?(?:is |are |has |have "
                          r"been |was )?(?:approved|signed off|granted)|\bupon approval|\bif approval is (?:given|granted)|"
                          r"onaylan(?:irsa|diktan|masi halinde|dig[ıi] takdirde|dig[ıi]nda)|onaylarsa|"
                          r"onay(?:[ıi])? (?:gelirse|verilirse|al[ıi]n[ıi]rsa|c[ıi]karsa|al[ıi]nd[ıi]ktan)")


def gated_action(text: str, tools: list[str]) -> str | None:
    """The tool the clause makes conditional on approval ("if approved, issue_refund", "issue_refund only once
    approved"): the nearest non-approval tool in the same sentence part, after the condition if there is one."""
    f = fold_text(text)
    m = _IF_APPROVED.search(f)
    if not m:
        return None
    lo = max([0] + [x.end() for x in re.finditer(r"[;.](?!\d)", f[:m.start()])])
    hi = next((m.end() + x.start() for x in re.finditer(r"[;.](?!\d)", f[m.end():])), len(f))
    occ = [(f.find(t, lo), t) for t in tools if lo <= f.find(t, lo) < hi and not _APPROVAL_TOOL.search(t)]
    after = sorted((p, t) for p, t in occ if p > m.end())
    before = sorted(((p, t) for p, t in occ if p < m.start()), reverse=True)
    return (after or before or [(0, None)])[0][1]


def gated_actions(text: str, tools: list[str]) -> list[str]:
    """Every tool the approval makes conditional, in the order the clause says to run them: "if approved, the
    policy is cancelled with cancel_policy and the refund issued with issue_refund" gates both, cancel first.
    Coordinated actions are sequential steps, none dropped; [] when the clause has no "if approved"."""
    first = gated_action(text, tools)
    if not first:
        return []
    f = fold_text(text)
    m = _IF_APPROVED.search(f)
    lo = max([0] + [x.end() for x in re.finditer(r"[;.](?!\d)", f[:m.start()])])
    hi = next((m.end() + x.start() for x in re.finditer(r"[;.](?!\d)", f[m.end():])), len(f))
    side = (m.end(), hi) if f.find(first, lo) > m.end() else (lo, m.start())
    acts = [t for t in tools if side[0] <= f.find(t, lo) < side[1] and not _APPROVAL_TOOL.search(t)]
    return tool_order(text, acts) if len(acts) > 1 else [first]


def is_approval_tool(tool: str) -> bool:
    return bool(_APPROVAL_TOOL.search(tool))


def gates_of(j: dict) -> list[str]:
    """The checks a join's action waits on (approvals, checks), as against steps that merely run before it
    (recording the request, computing the plan)."""
    return j.get("gates") or j["checks"]


def _approval_join(text: str, tools: list[str]) -> dict | None:
    """Approval tools gate the action they approve, wherever the clause names them: "the refund is issued with
    issue_refund; above $500 approve_lead and then approve_manager must approve first". Money rules fail closed:
    an approval never runs after the thing it approves, and a step that computes what is approved runs first."""
    named = [t for t in dict.fromkeys(tools) if t in fold_text(text)]
    approvals = [t for t in named if _APPROVAL_TOOL.search(t)]
    producers = [t for t in named if t not in approvals and step_role(t) == 0]
    rest = [t for t in named if t not in approvals and t not in producers]
    if not approvals:
        return None
    acts = gated_actions(text, named) if len(rest) > 1 else []
    if len(rest) != 1 and not acts:
        return None
    acts = acts or rest[:1]
    # "If approved, cancel_policy and issue_refund": every coordinated action runs, one after another in the
    # stated order, after every approval; the chain ends in the last of them.
    action = acts[-1]
    checks = [t for t in named if t != action]
    stated = [(a, b) for a, b in tool_pairs(text, named) if a in checks and b in checks]
    stated += [(g, a) for g in approvals for a in acts[:-1]] + list(zip(acts, acts[1:-1]))
    return {"checks": data_order(tool_order(text, checks), stated), "action": action, "gates": approvals,
            **({"acts": acts} if len(acts) > 1 else {}),
            "ordered": bool(stated) or len(checks) > 1 and bool(_ORDER_ANY.search(fold_text(text))) or len(checks) > len(approvals),
            "on_fail": negative_branch(text) or "decline"}


def situation_steps(text: str, tools: list[str]) -> tuple[str, list[str], dict | None]:
    """(name, tools in run order, join) for a situation clause; both compilers name a situation the same way."""
    j = join_of(text, tools)
    if j:
        return j["action"], j["checks"] + [j["action"]], j
    steps = data_order(tool_order(text, tools), tool_pairs(text, tools))
    return steps[0], steps, None


# -- Thresholds: "for refunds over $500", "5.000 TL üzeri iadelerde" ----------------------------------------
_NUM = r"(\d{1,3}(?:[.,]\d{3})+|\d+)"
# Each pattern carries its own comparison, strict or not: "over $500" is > 500, "$500 or more" is >= 500,
# "below $500" is < 500, "up to $500" is <= 500. The boundary amount lands on the side the SOP says.
_TR_UNIT = r"\s*(?:tl|lira)?(?:['’]?\s*(?:n[ıi]n|[ıi]n|y[ıi]|y[ae]|[ıi]|d[ae]n|t[ae]n))?\s*"
_CMP_RX = [
    (re.compile(r"\b(?:up to|at most|not exceeding|no more than|(?:not|n't|never)\s+(?:exceed\w*|go(?:es)?\s+(?:over|above|"
                r"beyond)|more than|over|above|greater than|higher than|larger than|beyond))\s*\$?\s*" + _NUM), "<="),
    (re.compile(r"\$?\s*" + _NUM + r"\s*(?:dollars\s*)?(?:or less|or below|or under|and (?:below|under|less))"), "<="),
    (re.compile(r"\b(?:under|below|less than|lower than|smaller than)\s*\$?\s*" + _NUM), "<"),
    (re.compile(_NUM + _TR_UNIT + r"(?:ve\s+(?:alti|asagi)|kadar|asm[ae]|asm[ıi]y|gecm[ae]|gecm[ıi]y)"), "<="),
    (re.compile(_NUM + _TR_UNIT + r"(?:alti|altin|az\b|azs|dusuk|kucuk)"), "<"),
    (re.compile(r"\b(?:at least|minimum of)\s*\$?\s*" + _NUM + r"|\$?\s*" + _NUM
                + r"\s*(?:dollars\s*)?(?:or more|or above|or over|and (?:above|over|up))"), ">="),
    (re.compile(r"\b(?:over|above|more than|exceed(?:s|ing)?|greater than|larger than|higher than|in excess of|beyond)"
                r"\s*\$?\s*" + _NUM), ">"),
    (re.compile(_NUM + _TR_UNIT + r"ve\s+(?:uzer|ustu|yukari|fazla)"), ">="),
    (re.compile(_NUM + _TR_UNIT + r"(?:uzer|ustu|ustun|as(?!m[ae]|m[ıi]y)|gec(?!m[ae]|m[ıi]y)|fazla|yuksek|buyuk)"), ">"),
]
_FLIP = {">": "<=", "<=": ">", ">=": "<", "<": ">="}


def threshold_of(text: str) -> tuple[str, float] | None:
    """('>', 500.0) for 'over $500' / '500 TL üzeri' / '500 TL'yi aşarsa', ('>=', 500.0) for '$500 or more',
    ('<', 500.0) for 'below $500', ('<=', 500.0) for 'up to $500': the amounts the clause's words name."""
    f = fold_text(text)
    for rx, op in _CMP_RX:
        m = rx.search(f)
        if m:
            # A negation outside the comparison turns it round: "is not in excess of $500", "500 TL'den fazla
            # değilse", "500 TL'nin üzerinde olmayan", "that is not above".
            before = f[:m.start()].split()[-4:]
            if any(w in ("not", "never", "no") or w.endswith("n't") for w in before):
                op = _FLIP[op]
            if re.match(r"\w*\s*(?:ise\s+|bir\s+\w+\s+)?(?:degil|olmay|olmaz|olmad|olmuyor)", f[m.end():]):
                op = _FLIP[op]
            return op, float(re.sub(r"[.,]", "", next(g for g in m.groups() if g)))
    return None


# Where the checks apply. "Refunds that do not exceed $500 need no approval; otherwise ..." states the threshold
# on the side the checks are skipped, so the checks apply to the other side. Money rules fail closed: when the
# part of the clause that holds the amount neither asks for the checks nor waives them, no threshold is taken
# and the checks run at every amount.
_WAIVE = re.compile(r"\bno (?:approval|sign-?off|check|need)|(?:\bnot|n't) (?:be )?(?:need|requir|necessary)\w*|"
                    r"al[ıi]nmadan|almadan|\benough\b|\bsuffic\w*|yeterli\w*|\byeter\b|"
                    r"(?:\bnot|n't) (?:be )?(?:asked|sought|requested|obtained|called)|"
                    r"\bwithout (?:any )?approval|\bskip\w*|\bwaiv\w*|\bexempt|gerek duyulmaz|ihtiyac (?:yok|duyulmaz)|"
                    r"atlan\w*|gerekmeme\w*|"
                    r"\bneeds? no\b|\b(?:is|are) not (?:needed|required)|\bdirectly\b|\bstraight away\b|"
                    r"\bimmediately\b|onay(?:[ıi]na?)?\s+gerek(?:mez|miyor|me|\s+yok)|gerek(?:mez|miyor|\s+yok)|"
                    r"onays[ıi]z|onay\s+(?:aranmaz|al[ıi]nmaz|istenmez)|dogrudan|direkt")
_ASK = re.compile(r"onay|approv|sign-?off|gerek|requir|\bneeds?\b|\bmust\b|zorunlu")
_ELSE = re.compile(r";|\.(?!\d)|\b(?:otherwise|else|aksi halde|aksi takdirde|aksi durumda|if not)\b")


def approval_threshold(text: str) -> tuple[str, float] | None:
    th = threshold_of(text)
    if not th:
        return None
    f = fold_text(text)
    m = re.search(_NUM, f)
    num_at = next((x.start() for x in re.finditer(_NUM, f) if float(re.sub(r"[.,]", "", x.group(1))) == th[1]),
                  m.start() if m else 0)
    cuts = [0] + [x.end() for x in _ELSE.finditer(f)] + [len(f)]
    lo = max(c for c in cuts if c <= num_at)
    hi = min(c for c in cuts if c > num_at)
    part, at = f[lo:hi], num_at - lo
    if re.search(r"\bunless\b", part[:at]):
        th = _FLIP[th[0]], th[1]  # "unless it exceeds $500, no approval": approval above it
    # The word nearest after the amount says what happens at it ("geçerse onay gerekir, geçmezse doğrudan").
    waive = [(x.start(), "waive") for x in _WAIVE.finditer(part)]
    spans = [range(x.start(), x.end()) for x in _WAIVE.finditer(part)]
    # "approval is not required", "onaya gerek yoktur": the approval word is the waive's subject, not an ask.
    ask = [(x.start(), "ask") for x in _ASK.finditer(part) if not any(x.start() in r for r in spans)
           and not any(0 < w - x.start() < 40 and not re.search(r"[,;]", part[x.start():w]) for w, _ in waive)]
    marks = sorted(waive + ask)
    nxt = [k for i, k in marks if i > at]
    say = nxt[0] if nxt else (marks[-1][1] if marks else None)
    out = (_FLIP[th[0]], th[1]) if say == "waive" else th if say == "ask" else None
    # Monotone: a larger amount never needs less approval. A reading that asks for approval only at or under the
    # amount, and waives it above, is a misreading; money rules fail closed, so approval runs at every amount.
    return out if out and out[0] in (">", ">=") else None


# -- Rules spread over several clauses -------------------------------------------------------------------------
# "4.1 If the card is stolen, reissue it with reissue_card. 4.2 reissue_card only after the card is blocked with
# block_card." or "13.1 ... issue_refund. 13.2 A refund needs approval from approve_lead and approve_manager.
# 13.3 If an approval is declined, transfer." Both compilers read the section as a whole, the same way.
_APPROVAL = re.compile(r"onay|approv|izin|gerekir|gerekli|requires?|needs?|must be cleared|ancak|only (?:if|when|after)")
_ORDER_ANY = re.compile(r"\b(sonra|sonrasinda|once|oncesinde|ardindan|takiben|izler|izleyen|after|before|then|prior to|"
                        r"following|follows|precedes|preceded by|until)\b")


def _tools(text: str) -> list[str]:
    return [t for t in dict.fromkeys(re.findall(r"\b([a-z]+(?:_[a-z]+)+)\b", text))
            if "verif" not in t and "promise" not in t]


# A clause stated apart from its situation often names one tool and points at the other in words: "reissue_card
# only after the block", "bloke işleminden sonra reissue_card ile". Which side an order word governs decides the
# order, so it is read from the words it governs, matched against how the section itself talks about each tool
# ("block it with block_card", "kart block_card ile bloke edilir"). A side that cannot be told is not linked: the
# clause stays untested and the build stops at the gate rather than guess a safety order.
_GOV_TR = {"sonra": "earlier", "sonrasinda": "earlier", "akabinde": "earlier", "takiben": "earlier",
           "ardindan": "earlier", "once": "later", "oncesinde": "later"}
_GOV_EN = {"after": "earlier", "once": "earlier", "following": "earlier", "until": "earlier", "unless": "earlier",
           "before": "later", "prior to": "later", "then": "later", "followed by": "later"}
_GOV_WORDS = re.compile(r"\b(sonrasinda|sonra|akabinde|takiben|ardindan|oncesinde|once|after|following|until|"
                        r"unless|before|prior to|then|followed by)\b")
_WITHOUT_TR = re.compile(r"\b(\w+m[ae]d[ae]n)\b(?!\s+(?:once|sonra))")  # "bloke edilmeden": without X first
_STOPWORDS = set("the a an it its is are be been being any all this that with and or of to for on in by from has have "
                 "had was were may must can only not no new kart card musteri customer policyholder caller ile ve "
                 "bir bu su icin olan yeni".split()) - {"yeni"}
_ALIAS_SKIP = {"kart", "card", "musteri", "customer"}


def tool_aliases(texts: list[str], tools: list[str]) -> dict[str, set[str]]:
    """Word stems the section uses for each tool: its name's parts and the words it is used with ("block it with
    block_card", "reissue_card ile yeni kart talep edilir"). A stem two tools share says nothing and is dropped."""
    out: dict[str, set[str]] = {}
    f = " ".join(fold_text(t) for t in texts)
    for t in tools:
        words = [w for w in t.split("_")]
        for m in re.finditer(rf"\b{t}\s+ile\s+(\w+)(?:\s+(\w+))?", f):
            got = [w for w in m.groups() if w]
            words += got[:next((i for i, w in enumerate(got) if w in _SPAN_BREAK), len(got))]
        for m in re.finditer(rf"(\w+)\s+(\w+)\s+(?:(\w+)\s+)?with\s+{t}\b", f):
            words += [w for w in m.groups() if w]
        out[t] = {w[:4] for w in words if len(w) >= 4 and w not in _STOPWORDS and w not in _ALIAS_SKIP}
    for t in tools:
        out[t] -= set().union(*(out[u] for u in tools if u != t)) if len(tools) > 1 else set()
    return out


_SPAN_BREAK = {"ancak", "yalnizca", "sadece", "only", "just", "ise", "ama", "but"}


def _english(f: str) -> bool:
    """English "once" means "after"; the folded Turkish "önce" means "before". The clause's language decides."""
    return bool(re.search(r"\b(the|is|are|must|with|and|of|to|may|be)\b", f))


def _nearest(words: list[str], tools: list[str], aliases: dict[str, set[str]]) -> str | None:
    """The tool the nearest telling word names, scanning outward from the order word; None when unsure."""
    for x in words:
        if x in _SPAN_BREAK:
            break
        named = [t for t in tools if t in x]
        hit = named or [t for t in tools if x[:4] in aliases.get(t, ())]
        if len(hit) == 1:
            return hit[0]
        if hit:
            return None
    return None


def _governed(f: str, m: re.Match, tools: list[str], aliases: dict[str, set[str]]) -> str | None:
    """The one tool an order word governs, by name or by the words the section uses for it; None when unsure.
    A Turkish postposition governs the words just before it, an English preposition the words after it."""
    w = m.group(1)
    before_txt = re.split(r"[,.;:]", f[:m.start()])[-1]
    after_txt = re.split(r"[,.;:]", f[m.end():])[0]
    tr_post = w in _GOV_TR and before_txt.strip() and not _english(f) and not (w == "ardindan" and not re.search(
        r"(n[ıi]n|[ıi]n|un|n[uü]n)\s*$", before_txt.strip()))
    span = list(reversed(before_txt.split()))[:4] if tr_post else after_txt.split()[:6]
    return _nearest(span, tools, aliases)


def order_reading(text: str, tools: list[str], aliases: dict[str, set[str]]) -> list[tuple[str, str]]:
    """(earlier, later) pairs between two tools, one of which the clause may only point at in words. Empty when
    any order word in the clause cannot be read with confidence, or two readings disagree."""
    if len(tools) != 2:
        return []
    f = fold_text(text)
    neg = classify(text) == "must_not" or bool(re.search(r"\b(no|hicbir)\b", f))
    pairs = set()
    for m in _GOV_WORDS.finditer(f):
        w = m.group(1)
        before_txt = re.split(r"[,.;:]", f[:m.start()])[-1].strip()
        if w == "once" and (not before_txt or _english(f)):
            rel = "earlier"  # sentence-initial "önce": "first X"; English "once X, ..." means the same here
        elif w == "ardindan" and not re.search(r"(n[ıi]n|[ıi]n|un|n[uü]n)$", before_txt):
            rel = "later"  # a connector: "..., ardından X"
        else:
            rel = (_GOV_TR if w in _GOV_TR and before_txt else _GOV_EN).get(w) or _GOV_TR.get(w)
        g = _governed(f, m, tools, aliases)
        if g is None:
            return []
        if neg and w in ("before", "prior to", "once", "oncesinde") and rel == "later" and before_txt:
            rel = "earlier"  # "must not be called before the block": the block comes first
        o = tools[1] if g == tools[0] else tools[0]
        pairs.add((g, o) if rel == "earlier" else (o, g))
    for m in _WITHOUT_TR.finditer(f):
        g = _nearest(list(reversed(re.split(r"[,.;:]", f[:m.end()])[-1].split()))[:4], tools, aliases)
        if g is None:
            return []
        o = tools[1] if g == tools[0] else tools[0]
        pairs.add((g, o))  # "X yapılmadan Y yapılamaz": X first
    return list(pairs) if len(pairs) == 1 else []


def link_clauses(clauses) -> dict:
    """Links between clauses of one section: order pairs, joins and negative branches stated apart from the
    clause that names the situation. Returns {"pairs": [(a, b, clause)], "joins": {action: join},
    "linked": {clause id: what it adds}}."""
    by_section: dict[str, list] = {}
    for c in clauses:
        if c.normative:
            by_section.setdefault(c.section, []).append(c)
    pairs, joins, linked = [], {}, {}
    order_pairs: dict[str, list[tuple[str, str]]] = {}
    for sec in by_section.values():
        # A clause that only forbids tools ("never use waive_fee, even if the customer asks") is no situation and no
        # step of the section's chain: its "if" is a concession, and it must not change what approval gates.
        sec = [c for c in sec if not _tools(c.text) or set(_tools(c.text)) - forbidden_tools(c.text, _tools(c.text))]
        situ = [(c, _tools(c.text)) for c in sec if CONDITIONAL.search(fold_text(drop_concessive(c.text)))
                and _tools(c.text) and not _APPROVAL.search(fold_text(c.text))]
        if len(situ) != 1:
            continue  # one situation per section is what the link can be sure of
        head, head_tools = situ[0]
        action = situation_steps(head.text, head_tools)[1][-1]
        producers: list[tuple[str, str]] = []
        if len(head_tools) == 1 and _FIRST.search(fold_text(head.text)):
            order_pairs.setdefault(action, []).append((action, "*"))  # "first the request is recorded"
        aliases = tool_aliases([c.text for c in sec], list(dict.fromkeys(t for c in sec for t in _tools(c.text))))
        for c in sec:
            if c is head:
                continue
            ts = _tools(c.text)
            f = fold_text(c.text)
            new = [t for t in ts if t not in head_tools]
            ordered = bool(_GOV_WORDS.search(f) or _WITHOUT_TR.search(f))
            # The pair this clause states between its one new tool and the step it points at, named or in words.
            ref = next((t for t in ts if t in head_tools), action)
            rd = order_reading(c.text, [ref, new[0]], aliases) if len(new) == 1 and len(ts) <= 2 and ordered else []
            after_action = bool(rd) and rd[0][0] == ref
            # An approver stated after the head's step ("the recorded request is then sent to approve_manager") is
            # still a check: what it gates is named by the section's "if approved" clause.
            approver = len(new) == 1 and is_approval_tool(new[0])
            if (new and action not in ts and _APPROVAL.search(f) and len(new) == len(ts)
                    and (not after_action or approver) and (len(new) > 1 or _POSITIVE.search(f))):
                # Checks that must pass before the section's action, stated on their own.
                j = joins.setdefault(action, {"checks": [], "action": action, "ordered": False, "on_fail": "decline",
                                              "source": [head.id]})
                order = tool_order(c.text, new)
                prev = j["checks"][-1] if j["checks"] else None
                j["checks"] += [t for t in order if t not in j["checks"]]
                j["ordered"] = j["ordered"] or bool(tool_pairs(c.text, new)) or bool(_ORDER_ANY.search(f))
                # The chain's order may be stated in a later clause than the one that names a check
                # ("13.2 approve_manager must approve. 13.3 approve_manager only after approve_lead."): every
                # clause's pairs are kept and the checks sorted by all of them at the end.
                order_pairs.setdefault(action, []).extend(tool_pairs(c.text, ts))
                g = gated_actions(c.text, ts)
                if g:
                    j["gated"] = g
                nb = negative_branch(c.text)
                if nb:
                    j["on_fail"] = nb  # "if approved, X; otherwise transfer"
                order_pairs[action].extend(rd)
                if len(new) == 1 and ordered and not rd:
                    # "After that, it is sent to approve_manager": "that" is the step named just before.
                    back = prev or ref
                    order_pairs[action].extend(order_reading(c.text, [back, new[0]],
                                                             {**aliases, back: aliases.get(back, set()) | _ANAPHOR}))
                if len(new) == 1 and ordered and prev and prev not in ts:
                    # "Before that, approve_lead must approve": "that" is the check the section named last.
                    al = {**aliases, prev: aliases.get(prev, set()) | _ANAPHOR}
                    order_pairs[action].extend(order_reading(c.text, [prev, new[0]], al))
                if len(new) == 1 and _FIRST.search(f):
                    order_pairs[action].append((new[0], "*"))
                if len(new) == 1 and _LAST.search(f):
                    order_pairs[action].append(("*", new[0]))
                j["source"].append(c.id)
                th = approval_threshold(c.text)
                if th:
                    j["threshold"] = {"op": th[0], "value": th[1], "slot": "request_amount"}
                linked[c.id] = "join"
            elif (len(new) == 1 and len(ts) == 1 and step_role(new[0]) == 0 and step_role(action) in (1, 2)
                  and not ordered):
                # "The plan is computed with compute_plan": what the action consumes comes first, stated or not.
                producers.append((new[0], c.id))
                linked[c.id] = "order"
            elif len(ts) == 1 and ts[0] in head_tools + [action] and ordered and len(head_tools) == 1:
                pass  # restates the head's own tool; nothing to link
            elif len(new) == 1 and ordered and len(ts) <= 2:
                # "reissue_card only after the block", "bloke işleminden sonra reissue_card ile", "yeni kart
                # talebinden önce kart block_card ile bloke edilir": the other side is read from the words the
                # order word governs. Two named tools are read by name too; the readings must agree.
                named = tool_pairs(c.text, ts) if len(ts) == 2 else []
                p = rd if not named or set(named) == set(rd) or not rd else []
                if named and not rd:
                    p = named
                if p:
                    pairs += [(a, b, c.id) for a, b in p]
                    linked[c.id] = "order"
            elif not ts and negative_branch(c.text) and action in joins:
                joins[action]["on_fail"] = negative_branch(c.text)
                joins[action]["source"].append(c.id)
                linked[c.id] = "negative"
        if action in joins:
            j = joins[action]
            j["checks"] = [t for t in j["checks"] if t != action]
            for t, cid in producers:
                j["checks"].insert(0, t)
                j["source"].append(cid)
                j["ordered"] = True
        else:
            pairs += [(t, action, cid) for t, cid in producers]
        if action in joins:
            ps = order_pairs.get(action, [])
            ps = [(a, b) for a0, b0 in ps for a, b in
                  ([(a0, x) for x in j["checks"] if x != a0] if b0 == "*" else
                   [(x, b0) for x in j["checks"] if x != b0] if a0 == "*" else [(a0, b0)])
                  if a in j["checks"] and b in j["checks"]]
            if ps:
                j["checks"] = _kahn(j["checks"], ps)
                j["ordered"] = True
            checks = data_order(j["checks"], ps)
            if checks != j["checks"]:
                j["checks"], j["ordered"] = checks, True
            # The situation clause may name the step that computes the plan, and a later clause the write that
            # records it once approved: the chain ends in the write, so the write is the action and the computing
            # step heads the chain (compute, approve, record), whatever clause names which.
            # Every step the situation clause names belongs to the chain ("the plan is calculated with P and a
            # draft saved with D"), in the clause's own order.
            head_steps = situation_steps(head.text, head_tools)[1]
            items = list(dict.fromkeys(head_steps + j["checks"] + [action]))
            order_pairs.setdefault(action, []).extend(zip(head_steps, head_steps[1:]))
            ps_all = [(a, b) for a0, b0 in order_pairs.get(action, []) for a, b in
                      ([(a0, x) for x in items if x != a0] if b0 == "*" else
                       [(x, b0) for x in items if x != b0] if a0 == "*" else [(a0, b0)])]
            # Where nothing is stated, the section's own sequence: the situation clause's step comes first.
            items = sorted(items, key=lambda t: next((i for i, c in enumerate(sec) if t in _tools(c.text)), 99))
            gated = [t for t in j.pop("gated", []) if t in items]
            # Coordinated actions the approval makes conditional run one after another, after every approval.
            ps_all += [(g, a) for g in items if is_approval_tool(g) for a in gated] + list(zip(gated, gated[1:]))
            full = data_order(items, ps_all)
            if gated:
                # The approval clause names what it makes conditional: that is the action, and everything else
                # runs before it in the stated order (record the request, send it for approval, then pay).
                j["action"], j["checks"], j["ordered"] = gated[-1], [t for t in full if t != gated[-1]], True
                if len(gated) > 1:
                    j["acts"] = gated
            elif full[-1] != action and step_role(full[-1]) == 2 and step_role(action) in (0, 1):
                j["action"], j["checks"], j["ordered"] = full[-1], full[:-1], True
            j["gates"] = [t for t in j["checks"] if step_role(t) == 1 and t not in j.get("acts", [])] or [
                t for t in j["checks"] if t not in j.get("acts", [])]
    return {"pairs": pairs, "joins": joins, "linked": linked}


_ANAPHOR = {"that", "this", "it", "bu", "bund", "buna", "bunu", "onda", "o"}
_FIRST = re.compile(r"\b(first|firstly|ilk olarak|ilk once|oncelikle|ilk)\b")
_LAST = re.compile(r"\b(last|lastly|finally|son olarak|en son)\b")


def _kahn(items: list[str], pairs: list[tuple[str, str]]) -> list[str]:
    out, left = [], list(items)
    while left:
        ready = [t for t in left if not any(b == t and a in left for a, b in pairs)] or left[:1]
        out.append(ready[0])
        left.remove(ready[0])
    return out
