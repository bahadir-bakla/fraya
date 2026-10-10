"""Perception: what did the caller mean? Kept apart from what the agent may do.

The control skeleton stays static: the workflow graph, the gates and the
order formulas decide what can happen. Perception only answers two narrow
questions, each with a closed set of answers:

* ``intents(text, options)``: which of the allowed situations is the caller
  in (a subset of ``options``; empty when none or unsure). It can never
  invent an edge, only pick among the ones the graph already has.
* ``confirm(text, current)``: at a read-back, ``yes``, ``no`` or
  ``correction`` (with the corrected value), or ``None`` when unclear.

``RulePerception`` is the offline layer: cue patterns with negation scope
("itirazım yok" is not a dispute, "doğru değil" is not a yes) and a
correction check (a different amount in the answer overrides a "yes").
``llm.ClaudePerception`` answers the same questions with Claude, shown the
same closed label set. ``evaluate`` scores either on the exam's perception
set (exam.py), which the agent never sees while it is built.
"""

from __future__ import annotations

import re

from voice_contract.contract import normalize

from .slots import dates, fold, numbers

# Words that negate a situation cue when they follow it closely (Turkish) or precede it (English, Turkish "hiç").
_NEG_AFTER = re.compile(r"^\W*(\w+\W+){0,1}(yok|degil|degilim|etmiyorum|etmem|yoktur)\b")
_NEG_BEFORE = re.compile(r"\b(no|not|don't|dont|do not|never|isn't|isnt)\W+(\w+\W+){0,1}$")
_YES = re.compile(r"\b(evet|dogru|aynen|tamam|olur|onayliyorum|yes|correct|right|yep|confirm|exactly)\b")
_NO = re.compile(r"\b(hayir|yanlis|no|nope|wrong|incorrect)\b")
_YES_NEGATED = re.compile(r"\b(dogru|tamam|right|correct)\W+(degil|sayilmaz|olmaz|not)\b|\b(not|isn't|isnt)\W+(right|correct)\b")


class RulePerception:
    name = "rules"

    def intents(self, text: str, options: dict[str, list[str]], lang: str = "tr") -> list[str]:
        norm, folded = normalize(text, lang), fold(text)
        out = []
        for label, pats in options.items():
            for p in pats:
                m = re.search(fold(p), folded)
                if not m:
                    if re.search(normalize(p, lang), norm):
                        out.append(label)
                        break
                    continue
                negated_in_cue = bool(re.search(r"\b(degil|yok|not|don't|never|etmiyorum)\b", fold(p)))
                if not negated_in_cue and (_NEG_AFTER.search(folded[m.end():]) or _NEG_BEFORE.search(folded[:m.start()])):
                    continue
                out.append(label)
                break
        return out

    def confirm(self, text: str, current: float | None = None,
                current_date: str | None = None) -> tuple[str | None, float | str | None]:
        """Value is the corrected amount (float) or, for a date correction, the corrected date ('25.10')."""
        s = fold(text)
        # Any amount in the answer other than the one read back is a correction, whatever yes/no word comes with
        # it ("yes, but six thousand, not five"); the last such amount is what the caller means.
        other = [v for _, v in numbers(text) if v >= 100 and (current is None or abs(v - float(current)) > 0.5)]
        if other and current is not None:
            return "correction", other[-1]
        # The same for the date read back with it ("the amount is right but make it the 25th").
        ds = [v for _, v in dates(text) if current_date and v[:5] != current_date[:5]]
        if ds:
            return "correction", ds[-1]
        if _YES_NEGATED.search(s) or (_NO.search(s) and not _YES.search(s)):
            return "no", None
        no, yes = _NO.search(s), _YES.search(s)
        if no and yes and no.start() < yes.start():
            return "no", None
        if yes:
            return "yes", None
        return None, None


# A turn the rules can settle alone: it answers the question asked (a number, a date, digits, a bare yes or no)
# and carries nothing else. Contrast words mean there is more in it than the answer.
_CONTRAST = re.compile(r"\b(ama|fakat|ancak|yalniz|sadece|aslinda|bu arada|ayrica|but|except|though|however|"
                       r"actually|by the way|also|only)\b")
_HEDGE = re.compile(r"\b(sanirim|galiba|herhalde|bilmiyorum|emin degilim|i think|maybe|not sure|i guess|probably)\b")


class CascadePerception:
    """Two layers: rules decide at once where they are sure; the model is asked only where they are not.

    Sure means the caller's turn is a plain answer (a value, or a bare yes/no) and the rules see no situation
    in it. Anything else (a situation the rules matched, a negated cue, free talk, a hedge, a contrast) goes to
    ``slow``. A matched situation is escalated too: a wrong route costs the call, so the model confirms it.
    ``stats`` counts how often each layer answered, which is the latency budget in a live call.
    """

    def __init__(self, fast=None, slow=None):
        self.fast = fast or RulePerception()
        self.slow = slow
        self.name = f"cascade({self.fast.name}→{getattr(slow, 'name', 'none')})"
        self.stats = {"intents_fast": 0, "intents_slow": 0, "confirm_fast": 0, "confirm_slow": 0}
        # One model call per caller turn: the router and the agent ask about the same words with different label
        # sets, so ask once with every label seen in this call and filter per question.
        self._labels: dict[str, list[str]] = {}
        self._last: tuple[str, frozenset, list[str]] | None = None

    @staticmethod
    def plain(text: str) -> bool:
        f = re.sub(r"\b(ii+|ee+|hm+|uh+|um+|erm)\b", " ", fold(text))  # fillers an ASR transcript keeps
        words = re.findall(r"\w+", f)
        has_value = bool(numbers(text) or dates(text) or re.search(r"\d", f))
        bare_yes_no = len(words) <= 4 and bool(_YES.search(f) or _NO.search(f))
        return len(words) <= 9 and (has_value or bare_yes_no) and not _CONTRAST.search(f) and not _HEDGE.search(f)

    def intents(self, text: str, options: dict[str, list[str]], lang: str = "tr") -> list[str]:
        got = self.fast.intents(text, options, lang)
        if self.slow is None or (not got and self.plain(text)):
            self.stats["intents_fast"] += 1
            return got
        self._labels.update(options)
        if self._last and self._last[0] == text and set(options) <= self._last[1]:
            return [x for x in self._last[2] if x in options]
        self.stats["intents_slow"] += 1
        got = self.slow.intents(text, dict(self._labels), lang)
        self._last = (text, frozenset(self._labels), got)
        return [x for x in got if x in options]

    def confirm(self, text: str, current=None, current_date=None):
        v, val = self.fast.confirm(text, current, current_date)
        f = fold(text)
        sure = v == "correction" or (v in ("yes", "no") and self.plain(text) and not (_YES.search(f) and _NO.search(f)))
        if self.slow is None or sure:
            self.stats["confirm_fast"] += 1
            return v, val
        self.stats["confirm_slow"] += 1
        return self.slow.confirm(text, current, current_date)


def evaluate(perception, cases: list[dict], options: dict[str, list[str]], lang: str) -> dict:
    """Precision / recall per label on the exam's perception set, plus every miss."""
    tally: dict[str, dict[str, int]] = {}
    misses = []

    def count(label: str, key: str) -> None:
        tally.setdefault(label, {"tp": 0, "fp": 0, "fn": 0})[key] += 1

    def ask(c: dict):
        if c["task"] == "route":
            return perception.intents(c["text"], options, lang), None
        return perception.confirm(c["text"], 5000, "20.10")

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as pool:  # a model-backed perception answers in seconds, not microseconds
        answers = list(pool.map(ask, cases))
    for c, (got, val) in zip(cases, answers):
        if c["task"] == "route":
            pred = got[0] if len(got) == 1 else ("none" if not got else "+".join(sorted(got)))
        else:
            pred = got
            pred = pred or "unclear"
            if pred == "correction" and c.get("value") and (not isinstance(val, (int, float))
                                                             or abs(val - c["value"]) > 0.5):
                pred = "correction(wrong value)"
            if pred == "correction" and c.get("date") and val != c["date"]:
                pred = "correction(wrong value)"
        gold = c["label"]
        if pred == gold:
            count(gold, "tp")
        else:
            count(gold, "fn")
            count(pred, "fp")
            misses.append({"task": c["task"], "text": c["text"], "expected": gold, "got": pred})
    per = {}
    for label, t in tally.items():
        p = t["tp"] / (t["tp"] + t["fp"]) if t["tp"] + t["fp"] else 1.0
        r = t["tp"] / (t["tp"] + t["fn"]) if t["tp"] + t["fn"] else 1.0
        if t["tp"] + t["fn"]:
            per[label] = {"precision": round(p, 3), "recall": round(r, 3), "n": t["tp"] + t["fn"]}
    acc = 1 - len(misses) / len(cases) if cases else 1.0
    out = {"perception": getattr(perception, "name", type(perception).__name__), "cases": len(cases),
           "accuracy": round(acc, 3), "labels": per, "misses": misses}
    if hasattr(perception, "stats"):
        st = perception.stats
        slow = st["intents_slow"] + st["confirm_slow"]
        out["escalated"] = {"to_model": slow, "of": slow + st["intents_fast"] + st["confirm_fast"]}
    return out
