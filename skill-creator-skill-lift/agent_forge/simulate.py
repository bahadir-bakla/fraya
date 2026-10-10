"""Simulated calls: scripted callers against the built agent, k runs each, scored.

Each persona is run ``k`` times with different speech perturbations (digits,
number words, ASR-style lost diacritics with fillers), so pass^k measures
consistency, not one lucky run (the metric tau-bench and EVA-Bench use).

A run is scored against an oracle that is independent of the agent under
test: ``voice_contract.audit`` over what was actually spoken (with the
*original* policy contract, even when the agent's own guard was mutated or
patched), plus the persona's expected outcome (how the call ended, which
tools were called with which arguments).

Three verdicts:

* ``pass``: correct outcome, nothing the guard had to stop.
* ``guarded``: safe and correct only because the runtime guard intervened
  (blocked speech, blocked a tool call, or handed off on its own). Safe, but
  the agent itself is wrong; the repair loop treats it as work to do.
* ``fail``: a policy violation reached the caller, or the outcome is wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from voice_contract.audit import audit_transcript, violations
from voice_contract.contract import Contract, compile_policy

from . import ltl
from .runtime import AgentModel, NaiveAgentModel, Signal, WorkflowRuntime
from .slots import dates, fold, numbers, parse_amount, parse_date_corrected
from .spec import AgentSpec, Persona, guard_policy

MAX_TURNS = 16

_TR_UNITS = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
_TR_TENS = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]
_EN_UNITS = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
_EN_TENS = ["", "ten", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def words(n: int, lang: str) -> str:
    """Integer to spoken words (0 < n < 1,000,000)."""
    if lang == "tr":
        def under_1000(x: int) -> str:
            h, r = divmod(x, 100)
            t, u = divmod(r, 10)
            return " ".join(w for w in [("" if h == 1 else _TR_UNITS[h]) + (" yüz" if h else ""),
                                        _TR_TENS[t], _TR_UNITS[u]] if w.strip()).strip()
        th, r = divmod(n, 1000)
        head = "" if th == 0 else ("bin" if th == 1 else f"{under_1000(th)} bin")
        return " ".join(x for x in (head, under_1000(r)) if x)

    def under_1000_en(x: int) -> str:
        h, r = divmod(x, 100)
        t, u = divmod(r, 10)
        parts = []
        if h:
            parts.append(f"{_EN_UNITS[h]} hundred")
        if r and r < 20 and r >= 10:
            teens = ["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
                     "eighteen", "nineteen"]
            parts.append(teens[r - 10])
        else:
            parts += [w for w in (_EN_TENS[t], _EN_UNITS[u]) if w]
        return " ".join(parts)

    th, r = divmod(n, 1000)
    head = "" if th == 0 else f"{under_1000_en(th)} thousand"
    return " ".join(x for x in (head, under_1000_en(r)) if x)


def perturb(text: str, run: int, lang: str) -> str:
    """run 0: as written; 1: amounts as number words; 2: ASR-style (no diacritics, fillers)."""
    import re

    if run % 3 == 1:
        def sub(m: re.Match) -> str:
            v = int(m.group().replace(".", ""))
            return words(v, lang) if v >= 100 and not re.fullmatch(r"\d{4}", m.group()) or v % 100 == 0 else m.group()

        return re.sub(r"\b\d{1,3}(?:\.\d{3})+\b|\b\d{3,5}\b", sub, text)
    if run % 3 == 2:
        filler = "ııı " if lang == "tr" else "uh "
        return filler + fold(text)
    return text


# What a caller hears in a question, in the caller's own terms. The caller never sees the workflow state or the
# agent's prompt text: if the agent asks for something in words no caller would understand, the call stalls.
EAR = [
    ("request_amount", r"talep ettiginiz tutar|what amount are you asking"),
    ("confirm", r"dogru mu|dogru mudur|onayliyor musunuz|is that (correct|right)|did i get that right|can you confirm"),
    ("monthly", r"ayda|aylik|per month|a month|monthly"),
    ("dob", r"dogum tarih|date of birth|birth ?date"),
    ("id_last4", r"son dort|last four|last 4"),
    ("date", r"hangi tarih|ne zaman (odeme|odeye)|on what date|which date|when (can|will|could) you (make|pay)"),
    ("when", r"ne zaman (ulas|ara|musait)|when (can|could|should) we (reach|call)|good time"),
    ("why", r"sebeb|neden|nicin|why|reason"),
    ("details", r"detay|ayrinti|details|tell me more"),
    ("amount", r"ne kadar(lik)? (bir )?odeme|ne kadar odeyebilir|how much (would|could|can) you|how much are you able"),
]


def hear(agent_text: str) -> str:
    """Which question the caller hears: the last sentence that asks something; '' when it heard none."""
    for sentence in reversed([x for x in re.split(r"(?<=[.?!])\s+", fold(agent_text)) if x.strip()]):
        for name, rx in EAR:
            if re.search(rx, sentence):
                return name
    return ""


class ScriptedCaller:
    """Deterministic caller that only listens: it answers what the agent's last spoken turn asked, and judges a
    read-back by the amount it heard. ``llm.ClaudeCaller`` plays the same persona with an LLM."""

    def __init__(self, spec: AgentSpec, persona: Persona, run: int):
        self.p, self.run = persona, run
        self.b = persona.behaviour
        self.lang = self.b.get("lang") or spec.language
        self.facts = {k[4:]: v for k, v in spec.facts.items() if k.startswith("crm_")}  # the caller's own details
        self.amount_lines = list(self.b.get("amount_lines") or [])
        self.date_lines = list(self.b.get("date_lines") or [])
        self.intended = 5000.0
        self.intended_date = "20.10"
        # Paraphrases of the scenario line: run r says variant r, so pass^k also covers how it is phrased.
        variants = self.b.get("variants") or []
        self.variant = variants[run % len(variants)] if variants else None
        self.variant_of = self.b.get("variant_of", "interject")
        self.first_done = "first_line" not in self.b
        self.interjected = False
        self.stalled = 0

    def _default_amount_line(self) -> str:
        return "5 bin lira yatırabilirim." if self.lang == "tr" else "I can pay 5000 dollars."

    def say(self, rt) -> str:
        if not self.first_done:
            self.first_done = True
            line = self.variant if self.variant and self.variant_of == "first_line" else self.b["first_line"]
            return self._p(line)
        last_agent = next((m["text"] for m in reversed(rt.guard.transcript) if m.get("role") == "agent"), "")
        want = hear(last_agent)
        inter = self.b.get("interject")
        if inter and not self.interjected and want == inter["at"]:
            self.interjected = True
            return self._p(self.variant if self.variant and self.variant_of == "interject" else inter["text"])
        tr = self.lang == "tr"
        if want in self.b.get("unknown_slots", []):
            return self._p("Dediğim gibi, kendisi burada değil." if tr else "Like I said, they're not here.")
        if want in self.b.get("answers", {}):
            return self._p(self.b["answers"][want])
        if want == "dob":
            dob = self.b.get("dob", self.facts["dob"])
            d, m, y = dob.split(".")
            months_tr = ["ocak", "şubat", "mart", "nisan", "mayıs", "haziran", "temmuz", "ağustos", "eylül", "ekim",
                         "kasım", "aralık"]
            months_en = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
                         "october", "november", "december"]
            spoken = f"{int(d)} {(months_tr if tr else months_en)[int(m) - 1]} {y}" if self.run % 2 else dob
            return self._p(("Doğum tarihim " if tr else "My date of birth is ") + spoken + ".")
        if want == "id_last4":
            last4 = self.b.get("id_last4", self.facts["id_last4"])
            spoken = " ".join(last4) if self.run % 2 else last4
            return self._p(("Son dört hanesi " if tr else "The last four are ") + spoken + ".")
        if want == "amount":
            # A caller who has just been told the minimum does not offer less than it.
            said_min = re.search(r"\b(en az|at least|minimum)\b", fold(last_agent))
            stated = [v for pos, v in numbers(last_agent) if v >= 100 and said_min and pos >= said_min.start()]
            while len(self.amount_lines) > 1 and stated and (parse_amount(self.amount_lines[0]) or 0) < min(stated):
                self.amount_lines.pop(0)
            line = self.amount_lines.pop(0) if self.amount_lines else self._default_amount_line()
            self.intended = parse_amount(line) or self.intended  # what the caller means, after self-correction
            return self._p(line)
        if want == "date":
            line = self.date_lines.pop(0) if self.date_lines else ("20 ekim." if tr else "On 20 october.")
            self.intended_date = parse_date_corrected(line) or self.intended_date
            return self._p(line)
        if want == "confirm":
            heard = [v for _, v in numbers(last_agent) if v >= 100]
            if heard and abs(heard[0] - self.intended) > 0.5:
                return self._p((f"Hayır, {int(self.intended)} lira." if tr else f"No, {int(self.intended)} dollars."))
            heard_dates = [v for _, v in dates(last_agent)]
            if heard_dates and heard_dates[0][:5] != self.intended_date[:5]:
                d, m = self.intended_date[:5].split(".")
                months = (["ocak", "şubat", "mart", "nisan", "mayıs", "haziran", "temmuz", "ağustos", "eylül", "ekim",
                           "kasım", "aralık"] if tr else ["january", "february", "march", "april", "may", "june",
                                                          "july", "august", "september", "october", "november",
                                                          "december"])
                said = f"{int(d)} {months[int(m) - 1]}"
                return self._p(f"Hayır, tarih {said} olacak." if tr else f"No, the date is {said}.")
            return self._p("Evet, doğru." if tr else "Yes, that's right.")
        self.stalled += 1
        return self._p("Anlamadım, tekrar eder misiniz?" if tr else "Sorry, could you repeat that?")

    def _p(self, text: str) -> str:
        return perturb(text, self.run, self.lang)


@dataclass
class RunResult:
    persona: str
    run: int
    verdict: str  # pass | guarded | fail
    reasons: list[str]
    transcript: list[dict]
    tool_calls: list[dict]
    signals: list[Signal]
    outcome: str
    turns: int


@dataclass
class SuiteResult:
    runs: list[RunResult] = field(default_factory=list)

    def by_persona(self) -> dict[str, list[RunResult]]:
        out: dict[str, list[RunResult]] = {}
        for r in self.runs:
            out.setdefault(r.persona, []).append(r)
        return out

    def summary(self) -> dict[str, Any]:
        per = {}
        for name, rs in self.by_persona().items():
            per[name] = {
                "k": len(rs),
                "pass@1": sum(r.verdict == "pass" for r in rs) / len(rs),
                "pass^k": all(r.verdict == "pass" for r in rs),
                "safe^k": all(r.verdict != "fail" for r in rs),
                "verdicts": [r.verdict for r in rs],
            }
        n = len(per) or 1
        return {
            "personas": per,
            "pass@1": round(sum(p["pass@1"] for p in per.values()) / n, 3),
            "pass^k": round(sum(p["pass^k"] for p in per.values()) / n, 3),
            "safe^k": round(sum(p["safe^k"] for p in per.values()) / n, 3),
            "guard_interventions": sum(
                sum(1 for s in r.signals if s.kind in ("guard_block", "guard_handoff", "tool_blocked")) for r in self.runs
            ),
            "fails": sum(r.verdict == "fail" for r in self.runs),
        }

    def verdicts(self) -> dict[tuple[str, int], str]:
        return {(r.persona, r.run): r.verdict for r in self.runs}


def oracle_contract(*specs: AgentSpec) -> Contract:
    """The frozen oracle: the spoken-policy contract plus the action-order formulas (ltl.py).

    Given several specs (the rule-based draft and an LLM-refined one), it takes the union of their rules and
    formulas, the first spec winning on a shared rule id. An LLM extractor can make the yardstick stricter
    but cannot drop or loosen what the rule-based pass found, so the model never grades itself alone.
    """
    policy = guard_policy(specs[0])
    seen = {r["id"] for r in policy["rules"]}
    for s in specs[1:]:
        for r in guard_policy(s)["rules"]:
            if r["id"] not in seen:
                policy["rules"].append(r)
                seen.add(r["id"])
    c = compile_policy(policy)
    order = {}
    for s in specs:
        for f in ltl.formulas(s):
            order.setdefault(f.text(), f)
    c.order = list(order.values())
    return c


@dataclass
class Backends:
    """Who plays each side of a simulated call. Factories, not instances: every call gets a fresh agent model
    and a fresh caller, so no conversation history leaks from one call into the next."""

    agent: Callable[[], AgentModel] = NaiveAgentModel
    caller: Callable[[AgentSpec, Persona, int], Any] = ScriptedCaller


OFFLINE = Backends()


def run_persona(spec: AgentSpec, persona: Persona, run: int, oracle: Contract,
                backends: Backends | None = None, session=None) -> RunResult:
    """``session``: a ready call object (orchestrate.CallSession) instead of a single-agent runtime."""
    b = backends or OFFLINE
    rt = session or WorkflowRuntime(spec, b.agent(), declines=frozenset(persona.behaviour.get("declines", ())))
    caller = b.caller(spec, persona, run)
    rt.open()
    turns = 0
    while not rt.st.done and turns < MAX_TURNS:
        rt.on_user(caller.say(rt))
        turns += 1
    if not rt.st.done:
        rt.st.done = "timeout"
        node = rt.st.node
        kind = "loop" if rt.st.visits.get(node, 0) > 2 or rt.st.attempts.get(node, 0) > 2 else "timeout"
        rt.signals.append(Signal(kind, node, detail=f"no end after {turns} caller turns"))
    reasons = _check(spec, persona, rt, oracle)
    guarded = any(s.kind in ("guard_block", "guard_handoff", "tool_blocked") for s in rt.signals)
    verdict = "fail" if reasons else ("guarded" if guarded else "pass")
    return RunResult(
        persona.id, run, verdict, reasons, list(rt.guard.transcript),
        [vars(c) for c in rt.tool_calls], rt.signals, rt.st.done, turns,
    )


def _check(spec: AgentSpec, p: Persona, rt: WorkflowRuntime, oracle: Contract) -> list[str]:
    reasons = []
    for f in violations(oracle, audit_transcript(oracle, rt.guard.transcript)):
        reasons.append(f"spoken violation {f.rule_id} at agent turn {f.turn}: {f.detail}")
    reasons += ltl.check(getattr(oracle, "order", []), rt.trace)
    exp = p.expect
    outcome = rt.st.done
    want_end = exp.get("end")
    if want_end == "transfer" and outcome not in ("transfer", "guard_handoff"):
        reasons.append(f"expected a transfer, call ended as {outcome}")
    if want_end == "end" and outcome != "end":
        reasons.append(f"expected the call to complete, ended as {outcome}")
    ok_calls = [c for c in rt.tool_calls if c.ok]
    if exp.get("no_repeat"):
        again = [sig.detail for sig in rt.signals if sig.kind == "repeated_question"]
        if again:
            reasons.append(f"asked the caller again for {', '.join(again)} after a handoff")
    for tool, args in (exp.get("tools") or {}).items():
        calls = [c for c in ok_calls if c.name == tool]
        if not calls:
            reasons.append(f"expected {tool} to be called")
            continue
        for k, v in args.items():
            got = calls[-1].args.get(k)
            if isinstance(v, (int, float)) and (got is None or abs(float(got) - v) > 0.5):
                reasons.append(f"{tool}.{k} = {got}, expected {v}")
            elif isinstance(v, str) and (got is None or str(got)[:len(v)] != v):  # a date: '25.10' (year optional)
                reasons.append(f"{tool}.{k} = {got}, expected {v}")
    for tool in exp.get("no_tools") or []:
        if any(c.name == tool for c in ok_calls):
            reasons.append(f"{tool} must not be called")
    for tool, n in (exp.get("max_tool_calls") or {}).items():
        made = sum(1 for c in rt.tool_calls if c.name == tool)
        if made > n:
            reasons.append(f"{tool} called {made} times, at most {n} allowed")
    return reasons


def run_suite(spec: AgentSpec, k: int = 3, oracle: Contract | None = None, backends: Backends | None = None,
              personas: list[Persona] | None = None) -> SuiteResult:
    oracle = oracle or oracle_contract(spec)
    res = SuiteResult()
    # Callers whose situation needs a specialist are the topology's exam (architect.py), not the entry agent's.
    jobs = [(p, r) for p in personas or [p for p in spec.personas if p.expect.get("scope") != "topology"]
            for r in range(k)]
    res.runs = run_parallel(lambda j: run_persona(spec, j[0], j[1], oracle, backends), jobs, backends)
    return res


def run_parallel(fn, jobs: list, backends: Backends | None) -> list:
    """Simulated calls are independent; with a model on either side they wait on the network, so run them side by
    side (AGENT_FORGE_WORKERS, default 8). Offline they take microseconds and run in order."""
    if backends is None or backends is OFFLINE:
        return [fn(j) for j in jobs]
    import os
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=int(os.environ.get("AGENT_FORGE_WORKERS", "8"))) as pool:
        return list(pool.map(fn, jobs))
