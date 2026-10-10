"""Second opinion for the guard: a semantic check on the agent's drafted reply, before it is spoken.

The live guard (voice_contract.StreamGuard) is lexical: it blocks what its patterns name, in microseconds,
and misses a paraphrase ("we will have to involve the courts" is a threat its word list may not hold;
"on iki bin dört yüz elli" is an amount in words). ``CascadeGuard`` adds a model's judgement in blocking mode,
only where it can matter:

* a reply with nothing risky in it (no amount, no digits, no sensitive vocabulary) is passed at once;
* a reply the lexical guard will block anyway is left to it;
* only the remaining risky replies are judged, against the blocking rules still active at this point of the
  call (an account-data rule stops applying once the caller is verified);
* a reply the lexical guard would block but that negates the very thing it names ("I can't guarantee any
  discount") gets a second look instead of a block: the judge may clear it;
* sentences already judged clean (the builder's own templates, judged once at build time by ``prejudge``, and
  any sentence judged before, digits masked) are not sent again: only new, freely generated text reaches the
  model at run time.

The judge can only name rules that exist; it cannot invent policy. A hit replaces the reply with that rule's
fallback and is logged with the rule id and clause, like a lexical block.
"""

from __future__ import annotations

import re

from voice_contract.contract import Contract, Rule, normalize

from .slots import fold, numbers

_RISKY = re.compile(
    r"\d|tl\b|lira|dolar|dollar|borc|bakiye|tutar|faiz|indirim|sil|garanti|kesin|soz ver|icra|haciz|mahkeme|dava|"
    r"polis|avukat|hapis|ceza|el kon|maas|kart|iban|kimlik|"
    r"balance|owe|debt|premium|amount|fee|waive|discount|guarantee|promise|definitely|court|lawsuit|legal|police|"
    r"arrest|jail|enforce|seize|garnish|bailiff|cancel|card|account number|iban|social security"
)


def risky(text: str) -> bool:
    # "bir" is "a" as much as "one": only amounts count, not every number word.
    return bool(_RISKY.search(fold(text)) or any(v >= 100 for _, v in numbers(text)))


# Negation, which a word list reads as the thing it negates. Turkish negates inside the verb (-mE-, -mEz, -AmAz).
_NEG = re.compile(r"\b(degil|yok|asla|hicbir|hic|olmaz|not|never|no|cannot|can't|won't|don't|doesn't|isn't)\b|n't\b|"
                  r"\w+(m[ae]z|m[ae]y[ıiuü]|m[ıiuü]yor|m[ae]yece|[ae]m[ae]m|[ae]m[ae]y[ıi]z|m[ae]d[ıi])\w*")
_SENT = re.compile(r"(?<=[.?!])\s+")
_MEMO: dict[tuple, bool] = {}  # (lang, rule ids, masked sentence) -> judged clean; shared by every call
_TEMPLATES: dict[tuple, list[re.Pattern]] = {}  # (lang, rule ids) -> builder sentences judged clean, as patterns


def negates(text: str) -> bool:
    return bool(_NEG.search(fold(text)))


def _key(lang: str, rules: list[Rule], sentence: str) -> tuple:
    return lang, tuple(sorted(r.id for r in rules)), re.sub(r"\d+", "#", fold(sentence).strip(" .?!"))


def _pattern(template: str) -> re.Pattern:
    """A builder sentence with its blanks open: 'Gecikmiş tutarınız {overdue} TL' matches any amount there."""
    parts = re.split(r"\{[^}]*\}", fold(template).strip(" .?!"))
    return re.compile("^" + ".+?".join(re.escape(x) for x in parts) + "$")


def known_clean(lang: str, rules: list[Rule], sentence: str) -> bool:
    k = _key(lang, rules, sentence)
    if _MEMO.get(k):
        return True
    f = fold(sentence).strip(" .?!")
    return any(p.match(f) for p in _TEMPLATES.get(k[:2], ()))


def template_sentences(spec, before_verification: bool = False) -> list[str]:
    """Every sentence the builder itself wrote for the agent to say: node lines, slot questions, the runtime's
    own phrases, capability closings and the guard's fallbacks. ``before_verification``: only what can be said
    before the caller is verified (nodes reached without passing identity verification), so a balance line
    that the workflow only reaches after verification is not judged against the pre-verification rules."""
    from .extract import LANG
    from .runtime import RUNTIME_LINES

    nodes = spec.nodes
    if before_verification:
        seen, todo = set(), [spec.start]
        while todo:
            nid = todo.pop()
            if nid in seen:
                continue
            seen.add(nid)
            todo += [e.to for e in spec.node(nid).edges if e.when != "event:identity_verified"]
        nodes = [n for n in spec.nodes if n.id in seen]
    out = [n.say for n in nodes if n.say] + [spec.slot(x).ask for n in nodes for x in n.collects]
    out += [v for k, v in LANG[spec.language].items() if isinstance(v, str)
            and not (before_verification and k in ("confirm", "close", "inform"))]
    if not before_verification:
        out += list(RUNTIME_LINES[spec.language].values())
        out += [c.get(k, "") for c in spec.capabilities for k in ("done", "declined", "failed")]
    out += [r.get("fallback", "") for r in spec.rules]
    sents = [x for t in out if t for x in _SENT.split(t) if x.strip()]
    return list(dict.fromkeys(sents))


def active_rules(contract: Contract, events: set[str]) -> list[Rule]:
    """Blocking agent-side rules that still apply now."""
    return [r for r in contract.rules
            if r.action == "block" and r.kind in ("forbidden", "gated_topic", "pii_leak")
            and not (r.kind == "gated_topic" and r.requires_event in events)]


class CascadeGuard:
    """Lexical first, a model's judgement only on risky replies the lexical layer lets through."""

    def __init__(self, slow=None):
        self.slow = slow
        self.name = f"cascade(lexical→{getattr(slow, 'name', 'none')})"
        self.stats = {"passed": 0, "lexical": 0, "judged": 0, "blocked": 0, "known": 0, "cleared": 0}
        self.cleared: list[str] = []  # rule ids the last review cleared after a lexical hit (a negation)

    def prejudge(self, spec, contract: Contract, lang: str) -> dict:
        """Judge the builder's own sentences once, at build time, so a call never waits on the model for them.

        Judged with their blanks open ("{amount}"), against the rules in force before and after verification."""
        if self.slow is None:
            return {"templates": 0, "flagged": []}
        judged, flagged = 0, []
        for events in (set(), {"identity_verified"}):
            sents = template_sentences(spec, before_verification=not events)
            rules = active_rules(contract, events)
            todo = [x for x in sents if risky(x) or "{" in x]
            if not rules or not todo:
                continue
            batch = getattr(self.slow, "check_many", None)
            verdicts = batch(todo, rules, lang) if batch else [self.slow.check(x, rules, lang)[0] for x in todo]
            judged += len(todo)
            pats = _TEMPLATES.setdefault(_key(lang, rules, "")[:2], [])
            for x, ids in zip(todo, verdicts):
                if ids:
                    flagged.append({"sentence": x, "rules": ids, "verified": bool(events)})
                else:
                    pats.append(_pattern(x))
        return {"templates": judged, "flagged": flagged}

    def review(self, reply: str, contract: Contract, events: set[str], lang: str) -> tuple[Rule | None, str]:
        self.cleared = []
        rules = active_rules(contract, events)
        if not rules or not risky(reply) or self.slow is None:
            self.stats["passed"] += 1
            return None, ""
        norm = normalize(reply, lang)
        lexical = [r for r in rules if r.kind != "pii_leak" and r.matches(norm)]
        if lexical and not negates(reply):
            self.stats["lexical"] += 1  # the stream guard will block it in microseconds
            return None, ""
        sents = [x for x in _SENT.split(reply) if x.strip()]
        if not lexical and all(known_clean(lang, rules, x) for x in sents if risky(x)):
            self.stats["known"] += 1  # every risky sentence was judged clean before (a template, or seen already)
            return None, ""
        self.stats["judged"] += 1
        ids, why = self.slow.check(reply, rules, lang)
        hit = next((r for r in rules if r.id in ids), None)
        if hit:
            self.stats["blocked"] += 1
            return hit, why
        for x in sents:
            _MEMO[_key(lang, rules, x)] = True
        if lexical:
            # The word list saw a forbidden topic; the judge read it as refused or denied: let it be spoken.
            self.cleared = [r.id for r in lexical]
            self.stats["cleared"] += 1
        return None, why


def evaluate_guard(contract: Contract, probes: list[dict], lang: str, cascade: CascadeGuard | None = None) -> dict:
    """Score the guard on the exam's probes: lexical alone, and lexical plus the judge when one is given.

    A probe that breaks a clause must be blocked; a safe near miss must be spoken.
    """
    from voice_contract.guard import StreamGuard

    rows, misses = [], []
    for p in probes:
        events = {"identity_verified"} if p["verified"] else set()
        g = StreamGuard(contract)
        for e in events:
            g.on_event(e)
        g.start_agent_turn()
        g.on_agent_chunk(p["text"])
        g.end_agent_turn()
        lexical = any(v.action == "block" for v in g.violations)
        layered = lexical
        if cascade is not None:
            hit = cascade.review(p["text"], contract, events, lang)[0]
            layered = hit is not None or (lexical and not cascade.cleared)
        want = p["clause"] is not None
        rows.append((lexical == want, layered == want))
        if layered != want:
            misses.append({"text": p["text"], "expected": "block" if want else "speak",
                           "got": "block" if layered else "speak"})
    n = len(rows) or 1
    out = {"probes": len(rows), "lexical": round(sum(a for a, _ in rows) / n, 3)}
    if cascade is not None:
        out |= {"two_layer": round(sum(b for _, b in rows) / n, 3), "judged": cascade.stats["judged"],
                "guard": cascade.name}
    out["misses"] = misses
    return out
