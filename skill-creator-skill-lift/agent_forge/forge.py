"""The builder loop end to end.

Phase 1 forges the entry agent: SOP -> draft -> simulate -> repair -> mutation test.
Phase 2 hands it to the architect, which grows a multi-agent topology around it
(spawn specialists, wire handoffs, carry context) under the same gate, then
mutation-tests the whole topology.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .architect import TopoLedgerEntry, grow, personas_for, topology_mutation
from .emit import freya_multiagent_workflow, freya_workflow, write_all, write_topology
from .exam import Exam, ExamCompiler, UntestedClauses, export_check
from .extract import RuleExtractor
from .judge import evaluate_guard
from .verify import static_check
from .perceive import RulePerception, evaluate
from .mutate import mutation_test
from .repair import LedgerEntry, repair
from .simulate import SuiteResult, run_suite
from .sop import forbidden_tools, gates_of, load_sop
from .extract import _tool_names
from .exam import tool_roles
from .spec import AgentSpec, guard_policy, validate
from voice_contract.contract import compile_policy
from .topology import Topology, validate_topology


@dataclass
class ForgeResult:
    draft: AgentSpec
    final: AgentSpec
    before: SuiteResult
    after: SuiteResult
    ledger: list[LedgerEntry]
    mutation: dict
    seconds: float
    files: list[Path] = field(default_factory=list)
    topology: Topology | None = None
    topo_ledger: list[TopoLedgerEntry] = field(default_factory=list)
    topo_before: SuiteResult | None = None
    topo_after: SuiteResult | None = None
    topo_mutation: dict | None = None
    exam: Exam | None = None
    perception: dict | None = None
    guard: dict | None = None
    static: dict | None = None
    unreached: list[str] = field(default_factory=list)  # export problems: a step tool unreachable, a forbidden one reachable
    export_review: list[str] = field(default_factory=list)  # tools a clause mentions only in passing

    def summary(self) -> dict:
        b, a = self.before.summary(), self.after.summary()
        keys = ("pass@1", "pass^k", "safe^k", "guard_interventions", "fails")
        return {
            "agent": self.final.name,
            "language": self.final.language,
            "before": {k: b[k] for k in keys},
            "after": {k: a[k] for k in keys},
            "patches_accepted": sum(e.accepted for e in self.ledger),
            "patches_rejected": sum(not e.accepted for e in self.ledger),
            "needs_review": [e.patch.describe() for e in self.ledger if e.accepted and e.patch.needs_review],
            "coverage": self.final.coverage(),
            "mutation_score": self.mutation["score"],
            "survivors": self.mutation["survivors"],
            "static_problems": validate(self.final),
            "extractor_notes": self.final.notes,
            "seconds": round(self.seconds, 2),
            "unreached_tools": self.unreached,
            "export_review": self.export_review,
            **({"topology": self._topo_summary()} if self.topology else {}),
            **({"exam": {"binding_clauses": len(self.exam.binding), "uncovered": self.exam.uncovered(),
                         "callers": len(self.exam.personas), "oracle_rules": len(self.exam.rules),
                         "order_formulas": len(self.exam.formulas), "perception_cases": len(self.exam.perception)}}
               if self.exam else {}),
            **({"perception": {k: self.perception[k] for k in ("perception", "cases", "accuracy", "labels")}}
               if self.perception else {}),
            **({"guard_probes": {k: v for k, v in self.guard.items() if k != "misses"}} if self.guard else {}),
            **({"solver_check": self.static} if self.static else {}),
        }

    def _topo_summary(self) -> dict:
        keys = ("pass@1", "pass^k", "safe^k", "guard_interventions", "fails")
        b, a = self.topo_before.summary(), self.topo_after.summary()
        return {
            "style": self.topology.style(),
            "inline": list(self.topology.inline),
            "forms": {x["id"]: x["form"] for x in style_rows(self)},
            "agents": [x.id for x in self.topology.agents],
            "handoffs": [f"{h.src}->{h.dst} on {h.intent}" + (f" carrying {h.carry}" if h.carry else "")
                         for h in self.topology.handoffs],
            "pending": [c["id"] for c in self.topology.pending],
            "before": {k: b[k] for k in keys},
            "after": {k: a[k] for k in keys},
            "moves_accepted": sum(e.accepted for e in self.topo_ledger),
            "moves_rejected": sum(not e.accepted for e in self.topo_ledger),
            "mutation_score": self.topo_mutation["score"] if self.topo_mutation else None,
            "survivors": self.topo_mutation["survivors"] if self.topo_mutation else [],
            "static_problems": validate_topology(self.topology),
        }


def _approval_shape(draft: AgentSpec, exam: Exam) -> tuple:
    """What approval gates, as each compiler reads it: the gated actions with their approvers and thresholds, and
    the exam's approval rules."""
    caps = sorted((c["join"]["action"], tuple(gates_of(c["join"])), str(c["join"].get("threshold")))
                  for c in draft.capabilities if c.get("join"))
    rules = sorted(f.text() for f in exam.formulas if "denied:" in f.text() or "tool:approv" in f.text())
    return caps, rules


def prohibition_drift(title: str, clauses: list) -> list[str]:
    """Adding or removing a prohibition never changes which tools approval gates. Each clause that forbids a tool
    is left out in turn and both compilers run again; a different gated set or approval rule stops the build."""
    base = _approval_shape(RuleExtractor().extract(title, clauses), ExamCompiler().compile(title, clauses))
    out = []
    for c in clauses:
        tools = _tool_names(c.text)
        if not tools or not (forbidden_tools(c.text, tools) or {t for t, r in tool_roles(c.text).items() if r == "prohibited"}):
            continue
        rest = [x for x in clauses if x is not c]
        if _approval_shape(RuleExtractor().extract(title, rest), ExamCompiler().compile(title, rest)) != base:
            out.append(f"{c.id} (prohibition changes what approval gates)")
    return out


def compile_sop(sop_path: str | Path, llm: bool = False) -> tuple[AgentSpec, Exam]:
    """Two compilers, blind to each other: one writes the agent, the other writes its exam from the same clauses."""
    title, clauses = load_sop(sop_path)
    draft = RuleExtractor().extract(title, clauses)
    exam = ExamCompiler().compile(title, clauses)
    exam.unplaced += [u for u in prohibition_drift(title, clauses) if u not in exam.unplaced]
    if llm:
        from .llm import ClaudeExamCompiler, ClaudeExtractor, disagreements

        rule_draft = draft
        draft = ClaudeExtractor().refine(rule_draft, Path(sop_path).read_text(encoding="utf-8"))
        draft.notes = draft.notes + [f"review §{d['clause']}: extractors disagree" for d in disagreements(rule_draft, draft)]
        # A separate Claude call, shown only the clauses, adds tests; the rule-based ones are never dropped.
        exam = exam.merge(ClaudeExamCompiler().compile(title, clauses, exam.language))
    # The simulator runs the exam's callers against the agent; the agent's own code never reads them.
    draft.personas = list(exam.personas)
    return draft, exam


def forge(sop_path: str | Path, out: str | Path | None = None, k: int = 3, llm: bool | str = False,
          mutate: bool = True, allow_untested: bool = False, progress: bool = False) -> ForgeResult:
    """``llm``: False (rules only), "compile" (Claude writes the agent spec, the exam, and judges perception and
    the guard probes; simulated calls stay offline and fast), True or "all" (Claude also plays the agent and the
    caller in every simulated call: thorough, slow without an API key)."""
    t0 = time.perf_counter()

    def say(msg: str) -> None:
        if progress:
            print(f"[{time.perf_counter() - t0:7.1f}s] {msg}", file=sys.stderr, flush=True)

    sim_llm = llm is True or llm == "all"
    say("compiling the SOP: agent spec and exam" + (" (Claude)" if llm else ""))
    draft, exam = compile_sop(sop_path, bool(llm))
    missing = exam.uncovered()
    if missing and not allow_untested:
        raise UntestedClauses(missing, exam)
    # The oracle is the exam's, frozen before any repair: patches change the agent, never the yardstick.
    oracle = exam.contract()
    backends = None
    perception = RulePerception()
    judge = None
    prejudged = None
    if llm:
        from .llm import claude_backends, make_guard_judge, make_perception

        if sim_llm:
            backends = claude_backends()  # a fresh Claude agent and Claude caller for every simulated call
        perception = make_perception()
        judge = make_guard_judge()
        if judge is not None:
            say("judging the builder's own sentences once, before any call")
            prejudged = judge.prejudge(draft, compile_policy(guard_policy(draft)), draft.language)
    say(f"perception on {len(exam.perception)} exam lines")
    options = {c["intent"]: c["patterns"] for c in draft.capabilities}
    perception_report = evaluate(perception, exam.perception, options, draft.language)
    say(f"simulating {len(draft.personas)} callers x k={k}, then repair")
    before = run_suite(draft, k, oracle, backends)
    final, ledger, after = repair(draft, k, oracle=oracle, backends=backends)
    say(f"guard probes ({len(exam.guard_probes)})")
    guard_report = evaluate_guard(compile_policy(guard_policy(final)), exam.guard_probes, final.language, judge)
    if prejudged is not None:
        guard_report["prejudged"] = prejudged
    if mutate:
        say("clause mutation")
    mutation = mutation_test(final, k, oracle, backends) if mutate else {"score": None, "survivors": [], "detail": []}
    res = ForgeResult(draft, final, before, after, ledger, mutation, 0.0, exam=exam, perception=perception_report)
    res.guard = guard_report
    res.static = static_check(final)
    if final.capabilities:
        say(f"architect: growing the topology for {len(final.capabilities)} situations")
        _, topo, tledger, tb, ta = grow(final, k, oracle, backends)
        res.topology, res.topo_ledger, res.topo_before, res.topo_after = topo, tledger, tb, ta
        if mutate:
            say("topology mutation")
        res.topo_mutation = topology_mutation(topo, k, oracle, backends) if mutate else None
    # The exam reads the export the customer would import: every tool a clause names must be reachable there.
    wf = freya_multiagent_workflow(res.topology) if res.topology else freya_workflow(final)
    res.unreached, res.export_review = export_check(exam.clauses, wf)
    res.seconds = time.perf_counter() - t0
    say("writing outputs")
    if out:
        out = Path(out)
        res.files = write_all(final, out, k)
        for name, data in (("exam.json", exam.to_dict()), ("perception.json", perception_report)):
            (out / name).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=vars) + "\n", encoding="utf-8")
            res.files.append(out / name)
        if res.topology:
            res.files += write_topology(res.topology, out, personas_for(res.topology), k)
        (out / "build_log.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in build_log(res)),
                                             encoding="utf-8")
        res.files.append(out / "build_log.jsonl")
        (out / "report.md").write_text(report_md(res), encoding="utf-8")
        (out / "report.json").write_text(json.dumps(res.summary(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        res.files += [out / "report.md", out / "report.json"]
    return res


def build_log(r: ForgeResult) -> list[dict]:
    """The build as a delegation log (redel-style JSONL): the architect at depth 0 decides, workers at depth 1
    (simulator, repairer, mutator) test and propose. Every line cites its clauses."""
    keys = ("pass@1", "pass^k", "safe^k", "fails")
    log: list[dict] = []

    def add(depth: int, actor: str, action: str, **kw) -> None:
        log.append({"seq": len(log) + 1, "depth": depth, "actor": actor, "action": action, **kw})

    add(0, "architect", "read_sop", clauses=len(r.final.clauses), binding=r.final.coverage()["normative"])
    add(0, "architect", "draft_agent", agent="core", nodes=len(r.draft.nodes), rules=len(r.draft.rules),
        capabilities=[c["id"] for c in r.draft.capabilities])
    if r.exam:
        add(1, "examiner", "write_exam", sees="clauses only", callers=len(r.exam.personas), oracle_rules=len(r.exam.rules),
            order_formulas=len(r.exam.formulas), perception_cases=len(r.exam.perception), uncovered=r.exam.uncovered())
    if r.perception:
        add(1, "examiner", "score_perception", perception=r.perception["perception"], accuracy=r.perception["accuracy"],
            misses=len(r.perception["misses"]))
    add(1, "simulator", "run_suite", agent="core", **{k: r.before.summary()[k] for k in keys})
    for e in r.ledger:
        add(1, "repairer", e.patch.op, target=e.patch.target, clauses=e.patch.source, evidence=e.patch.personas,
            accepted=e.accepted, why=e.why, needs_review=e.patch.needs_review, **{k: e.after.get(k) for k in keys if e.after})
    for d in r.mutation.get("detail", []):
        if d["removed"]:
            add(1, "mutator", "ablate", agent="core", clauses=[d["clause"]], killed=d["killed"], by=d["by"])
    if r.topology:
        add(1, "simulator", "run_topology", agents=["core"], **{k: r.topo_before.summary()[k] for k in keys})
        for e in r.topo_ledger:
            add(0, "architect", e.patch.op, target=e.patch.target, clauses=e.patch.source, evidence=e.patch.personas,
                detail={k: list(v) if isinstance(v, tuple) else v for k, v in e.patch.detail.items()},
                accepted=e.accepted, why=e.why, **{k: e.after.get(k) for k in keys if e.after})
        for d in (r.topo_mutation or {}).get("detail", []):
            if d["removed"]:
                add(1, "mutator", "ablate", agent="topology", clauses=[d["clause"]], killed=d["killed"], by=d["by"])
        add(0, "architect", "compile", agents=[a.id for a in r.topology.agents],
            handoffs=[f"{h.src}->{h.dst}" for h in r.topology.handoffs], runtime="static workflow, no runtime spawning")
    return log


def _transcript(run) -> str:
    lines = []
    for m in run.transcript:
        if m["role"] == "event":
            lines.append(f"    · event `{m['name']}`")
        elif m["role"] in ("user", "agent"):
            who = "Caller" if m["role"] == "user" else "Agent "
            mark = " ⛔ (guard replaced this turn)" if m.get("blocked") else ""
            lines.append(f"    {who}: {m['text']}{mark}")
    lines.append(f"    → {run.outcome}; verdict **{run.verdict}**" + (f" ({'; '.join(run.reasons)})" if run.reasons else ""))
    return "\n".join(lines)


def report_md(r: ForgeResult) -> str:
    s = r.summary()
    b, a = s["before"], s["after"]
    out = [f"# Agent forge report: {s['agent']}", ""]
    out += [
        f"Built from {len(r.final.clauses)} SOP clauses ({s['coverage']['normative']} binding) in {s['seconds']} s. "
        f"{len(r.after.summary()['personas'])} simulated callers × k={r.after.runs and max(x.run for x in r.after.runs) + 1} runs "
        "(digits, number words, ASR-style text).",
        "",
        "| | Draft | After repair |",
        "|---|---|---|",
        f"| pass@1 | {b['pass@1']} | {a['pass@1']} |",
        f"| pass^k (every run clean) | {b['pass^k']} | {a['pass^k']} |",
        f"| safe^k (no violation reached the caller) | {b['safe^k']} | {a['safe^k']} |",
        f"| guard interventions | {b['guard_interventions']} | {a['guard_interventions']} |",
        f"| failed runs | {b['fails']} | {a['fails']} |",
        "",
        f"Mutation score: **{s['mutation_score']}** ({r.mutation.get('killed')}/{r.mutation.get('mutants')} clause "
        "ablations caught by the suite).",
        "",
        *([f"**Export check failed**: {u}." for u in r.unreached] + [""] if r.unreached else
          ["Export check: every tool a binding clause names as a step is called by a reachable step of the export, "
           "and no tool a clause forbids outright is.", ""]),
        *([f"**Needs review**: {u}." for u in r.export_review] + [""] if r.export_review else []),
        "## Per caller",
        "",
        "| Caller | Clauses | Draft | After |",
        "|---|---|---|---|",
    ]
    bp, ap = r.before.summary()["personas"], r.after.summary()["personas"]
    for p in (p for p in r.final.personas if p.id in ap):
        out.append(f"| {p.id} | {', '.join('§' + c for c in p.source[:4])}{'…' if len(p.source) > 4 else ''} | "
                   f"{' '.join(bp[p.id]['verdicts'])} | {' '.join(ap[p.id]['verdicts'])} |")
    out += ["", "## Repairs", "", "| Round | Patch | Clause | Result | pass^k after |", "|---|---|---|---|---|"]
    for e in r.ledger:
        cite = ", ".join("§" + c for c in e.patch.source) or "assumption ⚠"
        res = "accepted" if e.accepted else f"rejected: {e.why}"
        out.append(f"| {e.round} | {e.patch.op} `{e.patch.target}` {e.patch.detail.get('tag') or e.patch.detail.get('intent') or e.patch.detail.get('max_attempts') or ''} "
                   f"| {cite} | {res} | {e.after.get('pass^k', '')} |")
    if s["needs_review"]:
        out += ["", "**Needs human review** (accepted without an SOP clause behind it):", ""]
        out += [f"- {x}" for x in s["needs_review"]]
    out += ["", "## Mutation testing", "", "| Clause | Removed | Caught by |", "|---|---|---|"]
    for d in r.mutation.get("detail", []):
        caught = ", ".join(d["by"]) if d["killed"] else ("survived ⚠" if d["removed"] else "procedure step (nothing to ablate)")
        out.append(f"| §{d['clause']} | {'<br>'.join(d['removed']) or '—'} | {caught} |")
    # One before/after call, the first caller that changed verdict.
    changed = next((p.id for p in r.final.personas if p.id in ap and bp[p.id]["verdicts"] != ap[p.id]["verdicts"]), None)
    if changed:
        rb = next(x for x in r.before.runs if x.persona == changed and x.run == 0)
        ra = next(x for x in r.after.runs if x.persona == changed and x.run == 0)
        out += ["", f"## Example: `{changed}` before and after", "", "Draft:", "", _transcript(rb), "", "Repaired:", "",
                _transcript(ra)]
    if r.topology:
        out += topology_md(r)
    if r.exam:
        out += exam_md(r)
    if s["static_problems"] or s["extractor_notes"]:
        out += ["", "## Open items", ""] + [f"- {x}" for x in s["static_problems"] + s["extractor_notes"]]
    return "\n".join(out) + "\n"


def exam_md(r: ForgeResult) -> list[str]:
    ex, per = r.exam, r.perception
    t = ex.tests_by_clause()
    out = ["", "## The exam, written blind", "",
           f"A second compiler read only the SOP clauses and wrote {len(ex.personas)} callers, {len(ex.rules)} oracle "
           f"rules, {len(ex.formulas)} order formulas and {len(ex.perception)} perception cases. It never saw the "
           "agent. A binding clause without a test blocks the build.", "",
           "| Clause | Tests |", "|---|---|"]
    for c in ex.binding:
        out.append(f"| §{c} | {', '.join(t.get(c, [])) or '**none: build blocked**'} |")
    if per:
        out += ["", f"### Perception: {per['perception']}, accuracy {per['accuracy']} on {per['cases']} cases", "",
                "| Label | Precision | Recall | n |", "|---|---|---|---|"]
        out += [f"| {k} | {v['precision']} | {v['recall']} | {v['n']} |" for k, v in sorted(per["labels"].items())]
        if per["misses"]:
            out += ["", "Misses:", ""] + [f"- \"{m['text']}\": expected {m['expected']}, got {m['got']}"
                                          for m in per["misses"]]
    st = r.static
    if st:
        out += ["", "### Solver check of the policy (before any simulated call)", ""]
        if not st["solver"]:
            out.append("Skipped: `pip install z3-solver` to check for dead tools, vacuous rules and conflicting clauses.")
        else:
            out.append(f"Z3 checked {st['rules']} value bounds and order preconditions, one problem per tool: "
                       + ("no dead tool, no vacuous rule, no conflicting clauses." if not st["findings"] else ""))
            out += [f"- {x}" for x in st["findings"]]
    g = r.guard
    if g and g["probes"]:
        layered = f", lexical plus {g['guard']}: **{g['two_layer']}** ({g['judged']} replies judged)" if "two_layer" in g else (
            " (the semantic second opinion runs under --llm)")
        out += ["", f"### Guard: {g['probes']} probe replies (paraphrased violations and safe near misses)", "",
                f"Lexical guard alone: **{g['lexical']}**{layered}."]
        if g["misses"]:
            out += ["", "Not caught:" if "two_layer" not in g else "Misses:", ""] + [
                f"- \"{m['text']}\": expected {m['expected']}, got {m['got']}" for m in g["misses"]]
    return out


def topology_md(r: ForgeResult) -> list[str]:
    t, ts = r.topology, r.summary()["topology"]
    b, a = ts["before"], ts["after"]
    out = ["", "## Phase 2: the architect's multi-agent topology", "",
           f"Entry agent alone vs. grown topology, over all {len(personas_for(t))} callers "
           "(the entry agent's callers plus one per specialist clause):", "",
           "| | Entry agent only | Topology |", "|---|---|---|"]
    for k in ("pass@1", "pass^k", "safe^k", "fails"):
        out.append(f"| {k} | {b[k]} | {a[k]} |")
    out += ["", f"Orchestration style, chosen by the architect: **{t.style()}**.", "",
            "| Situation | Clause | Form | Why |", "|---|---|---|---|"]
    out += [f"| {row['id']} | {', '.join('§' + c for c in row['source'])} | {row['form']} | {row['why']} |"
            for row in style_rows(r)]
    rows = style_rows(r)
    agree = sum(x["rule_agrees"] for x in rows)
    out += ["", f"The orchestration guides' rule (one agent by default; a handoff only at an authority boundary, here "
                f"an action on the account that needs a verified caller) predicts the same form for {agree} of "
                f"{len(rows)} situations. The rule is a prior; the kept form is the one the calls supported."]
    out += ["", "```mermaid", t.mermaid(), "```", "",
            "| Round | Move | Clause | Result | pass^k after |", "|---|---|---|---|---|"]
    for e in r.topo_ledger:
        detail = ", ".join(e.patch.detail.get("fields", ())) if e.patch.op == "carry_context" else ""
        out.append(f"| {e.round} | {e.patch.op} `{e.patch.target}` {detail} | "
                   f"{', '.join('§' + c for c in e.patch.source)} | {'accepted' if e.accepted else 'rejected: ' + e.why} | "
                   f"{e.after.get('pass^k', '')} |")
    out += ["", "| Agent | Role | Clauses | Needs from upstream | Spawned because |", "|---|---|---|---|---|"]
    for ag in t.agents:
        out.append(f"| {ag.id} | {ag.role} | {', '.join('§' + c for c in ag.source[:5])} | "
                   f"{', '.join(ag.requires) or '—'} | {ag.spawned_because or '—'} |")
    bp, ap = r.topo_before.summary()["personas"], r.topo_after.summary()["personas"]
    out += ["", "| Caller | Entry agent only | Topology |", "|---|---|---|"]
    for p in personas_for(t):
        out.append(f"| {p.id} | {' '.join(bp[p.id]['verdicts'])} | {' '.join(ap[p.id]['verdicts'])} |")
    if r.topo_mutation:
        m = r.topo_mutation
        out += ["", f"Topology mutation score: **{m['score']}** ({m['killed']}/{m['mutants']}). Survivors: "
                + (", ".join("§" + x["clause"] for x in m["survivors"]) or "none") + "."]
        jm = [d for d in m["detail"] if any(x.startswith("join:") for x in d["removed"])]
        if jm:
            out += ["", "Join mutants (a negative check ignored, the action run anyway): "
                    + "; ".join(f"§{d['clause']} {d['removed'][0][5:]}: "
                                + (f"caught by {', '.join(d['by'])}" if d["killed"] else "**survived**") for d in jm)
                    + "."]
        om = [d for d in m["detail"] if any(x.startswith("order:") for x in d["removed"])]
        if om:
            out += ["", "Order mutants (each stated pair run the other way round, both tools still called): "
                    + "; ".join(f"§{d['clause']} {d['removed'][0][6:]}: "
                                + (f"caught by {', '.join(d['by'])}" if d["killed"] else "**survived**") for d in om)
                    + "."]
    ex = next((x for x in r.topo_after.runs if x.persona == "hardship" and x.run == 0), None)
    if ex:
        out += ["", "### Example: `hardship` across a handoff", "", _transcript(ex)]
    back = {h.src for h in t.handoffs if h.handback}
    ex = next((x for x in r.topo_after.runs if x.persona in back and x.run == 0), None)
    if ex:
        out += ["", f"### Example: `{ex.persona}` hands the call back", "", _transcript(ex)]
    return out


def style_rows(r: ForgeResult) -> list[dict]:
    """One row per situation the SOP gives its own procedure: the form the architect kept, and the evidence."""
    t = r.topology
    caps = {c["id"]: c for c in r.final.capabilities}
    lost = {e.patch.target: e.why for e in r.topo_ledger if not e.accepted and e.why.startswith("style:")}
    rows = []
    for cid, c in caps.items():
        if cid in t.inline:
            form = "inline branch in the entry agent"
            why = ("needs no verified caller and ends the call; " + lost[cid].removeprefix("style: ")
                   if cid in lost else "needs no verified caller and ends the call")
        elif t.has(cid):
            h = next(h for h in t.handoffs if h.dst == cid and not h.handback)
            back = any(x.handback and x.src == cid for x in t.handoffs)
            form = "specialist agent" + (", hands back" if back else "")
            why = []
            if c.get("requires_identity"):
                why.append(f"acts on the account, so it verifies; the handoff carries {', '.join(h.carry) or 'nothing'}")
            if back:
                why.append("the clause says the call goes on afterwards")
            if cid in lost:
                why.append(lost[cid].removeprefix("style: "))
            if not c.get("known", True):
                why.append("a clause type the lexicon does not know, read from its condition")
            why = "; ".join(why) or "its own procedure"
        else:
            form, why = "not handled", "no move passed the gate"
        rule = "specialist" if c.get("requires_identity") else "inline"
        rows.append({"id": cid, "source": c["source"], "form": form, "why": why, "rule": rule,
                     "rule_agrees": form.startswith(rule if rule == "inline" else "specialist")})
    return rows
