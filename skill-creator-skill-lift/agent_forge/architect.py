"""The architect: the one main agent that designs a multi-agent system from an SOP.

It owns the whole build. It forges the entry agent (procedure + policy,
single-agent repair), then grows a topology around it:

* **spawn**: when a simulated caller brings a situation the SOP gives its
  own procedure for (a third party answers, the debt is disputed, the caller
  reports hardship) and no agent handles it, the architect spawns a
  specialist for that clause: its own workflow, tool and closing, the entry
  agent's prohibitions and escalation route inherited, identity verification
  included when the clause acts on the account,
* **wire**: the specialist joins the DAG through a typed handoff,
* **carry**: when a call shows a specialist asking for something the caller
  already gave, the handoff envelope learns to carry it.

Each move goes through the same gate as single-agent repair: re-run every
caller k times, keep the move only if something improves and nothing gets
worse. Nothing is spawned or carried on speculation, and every move cites its
clause. ADAS and AFlow search over agent designs with an LLM proposing code;
the architect searches over a closed set of typed moves, which keeps every
result checkable and traceable.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from voice_contract.contract import Contract

from .mutate import ablate
from .orchestrate import CallSession
from .repair import RANK, gate
from .simulate import OFFLINE, Backends, SuiteResult, oracle_contract, run_parallel, run_persona
from .sop import gates_of
from .spec import AgentSpec, Edge, Intent, Node, Persona, Slot, Tool
from .topology import INHERITED_KINDS, AgentRef, Handoff, Topology, validate_topology


def personas_for(t: Topology) -> list[Persona]:
    core = t.agent(t.entry).spec
    caps = [p for p in core.personas if p.expect.get("scope") == "topology"]
    return list(core.personas) + combined_personas(core, caps)


def combined_personas(core: AgentSpec, caps: list[Persona]) -> list[Persona]:
    """Edge cases that cross clauses (IntellAgent samples scenarios from a policy graph, not one rule at a time).

    A caller who opens adversarially (pushes for the balance before verification, tries a prompt injection)
    and later raises a situation a specialist owns. The call now crosses the identity gate, the injection
    rule *and* a handoff; each part passes on its own, the combination is what breaks real agents.
    Expectations merge: the specialist's outcome, the opener's required tools, the specialist's forbidden ones.
    """
    out = []
    # An opener with its own interjection (a relative who hands the phone over) would lose it in the merge.
    openers = [p for p in core.personas if "first_line" in p.behaviour and "interject" not in p.behaviour
               and p.expect.get("end") == "end"
               and set(p.expect.get("tools", {})) <= {t.name for t in core.tools if t.sets_event == "identity_verified"}]
    for o in openers:
        for c in caps:
            if "interject" not in c.behaviour or "first_line" in c.behaviour:
                continue
            exp = copy.deepcopy(c.expect)
            no = set(exp.get("no_tools", []))
            exp["tools"] = {**{k: v for k, v in o.expect.get("tools", {}).items() if k not in no}, **exp.get("tools", {})}
            out.append(Persona(f"{o.id}+{c.id}", f"{o.goal} Then: {c.goal}", {**o.behaviour, **c.behaviour}, exp,
                               list(dict.fromkeys(o.source + c.source))))
    return out


def run_topology(t: Topology, k: int = 3, oracle: Contract | None = None, backends: Backends | None = None,
                 personas: list[Persona] | None = None) -> SuiteResult:
    core = t.agent(t.entry).spec
    oracle = oracle or oracle_contract(core)
    b = backends or OFFLINE
    res = SuiteResult()
    jobs = [(p, r) for p in personas or personas_for(t) for r in range(k)]

    def one(j):
        session = CallSession(t, b.agent, frozenset(j[0].behaviour.get("declines", ())))
        return run_persona(core, j[0], j[1], oracle, b, session=session)

    res.runs = run_parallel(one, jobs, backends)
    return res


def _to_human(cap: dict) -> bool:
    return cap.get("on_fail") == "transfer" or (cap.get("join") or {}).get("on_fail") == "transfer"


def chain(cap: dict, slot: str, src: list[str], end: str, fail: str = "") -> tuple[list[Tool], list[Node], Node]:
    """The situation's tools in the order the SOP states, one step after another.

    The agent node collects what the caller has to say and calls the first tool; each later tool is a function
    node that runs only once the one before it succeeded. "Block first, then reissue" becomes the workflow's
    own shape, not a check bolted on after it.

    A join ("only if both checks are positive") gates the action on every check: the action node carries
    ``join`` (the runtime refuses the call unless each check succeeded in this call), and a negative check
    goes to ``fail`` (a human, or a decline the caller hears). Returns (tools, nodes after the agent node,
    the agent node).
    """
    steps = cap.get("steps") or [cap["tool"]]
    j = cap.get("join")
    checks = set(gates_of(j)) if j else set()
    tools = [Tool(t, [slot], src, sets_event=f"{t}_done", side_effect=t not in checks) for t in steps]
    main = Node(cap["id"], "agent", f"Handle: {cap['text']}", src, collects=[slot], tool=steps[0])
    rest = [Node(f"{cap['id']}__{t}", "function", f"Run {t} after {p}", src, tool=t)
            for p, t in zip(steps, steps[1:])]
    seq = [main] + rest
    for a, b in zip(seq, seq[1:]):
        a.edges = [Edge(b.id, f"event:{a.tool}_done", src)]
    seq[-1].edges = [Edge(end, f"event:{steps[-1]}_done", src)]
    if j:
        act = seq[-1]
        act.join, act.parallel = list(gates_of(j)), not j["ordered"]
        act.goal = f"Run {act.tool} only if {', '.join(j['checks'])} all succeeded"
        for n in seq[:-1]:
            if n.tool in j.get("acts", []):
                # "If approved, cancel_policy and issue_refund": each coordinated action waits on the approvals.
                n.join, n.parallel = list(gates_of(j)), False
                n.goal = f"Run {n.tool} only if {', '.join(gates_of(j))} all succeeded"
        th = j.get("threshold")
        if th:
            # "Approval for refunds over $500": the agent node asks the amount and calls nothing; above the
            # threshold the checks run, otherwise the action runs straight away.
            first = rest[0] if rest else None
            check0 = Node(f"{cap['id']}__{steps[0]}", "function", f"Run {steps[0]}", src, tool=steps[0],
                          edges=main.edges)
            direct = Node(f"{cap['id']}__direct", "function", f"Run {act.tool}: no approval needed at this amount",
                          src, tool=act.tool, edges=[Edge(end, f"event:{act.tool}_done", src)])
            # A step that computes what is approved and recorded (the plan) runs at every amount, ahead of the
            # write; only the approvals depend on the amount.
            pre = [Node(f"{cap['id']}__direct_{t}", "function", f"Run {t}", src, tool=t)
                   for t in j["checks"] if t not in gates_of(j)]
            for a, b in zip(pre, pre[1:] + [direct]):
                a.edges = [Edge(b.id, f"event:{a.tool}_done", src)]
            main.tool = None
            main.edges = [Edge(check0.id, f"slot:{th['slot']}{th['op']}{th['value']:g}", src),
                          Edge((pre or [direct])[0].id, "slots_filled", src)]
            rest[:0] = [check0]
            rest += pre + [direct]
            seq = [check0] + ([first] if first else []) + seq[2:] + pre + [direct]
    if not fail:
        # Every step has a way out when it comes back negative: the clause's own outcome, or a plain apology. A
        # step with no failure edge leaves the caller in silence.
        fail = f"{cap['id']}_declined"
        say = cap.get("declined", "") if j or cap.get("on_fail") else cap.get("failed", cap.get("declined", ""))
        rest.append(Node(fail, "end", "Tell the caller the request could not go ahead", src, say=say))
    for n in seq:
        n.edges.append(Edge(fail, "tool_failed", src))
    return tools, rest, main


class Architect:
    def plan(self, core: AgentSpec) -> Topology:
        """Start with the entry agent alone; every capability is pending until a call needs it."""
        src = list(dict.fromkeys(c for n in core.nodes for c in n.source))
        return Topology(core.name, "core", [AgentRef("core", "entry", core, src)], [], list(core.capabilities))

    def specialist(self, core: AgentSpec, cap: dict) -> AgentRef:
        L_done, slot = cap["done"], cap["slot"]
        src = list(cap["source"])
        nodes: list[Node] = []
        slots = [Slot(slot["name"], slot["kind"], slot["ask"], src)]
        transfer = next(n for n in core.nodes if n.kind == "transfer")
        fail = transfer.id if _to_human(cap) else ""
        tools, rest, main = chain(cap, slot["name"], src, "done", fail)
        requires: list[str] = []
        if cap["requires_identity"]:
            # Acting on the account needs a verified caller: reuse the entry agent's verification step.
            verify = next(n for n in core.nodes if n.tool and core.tool(n.tool).sets_event == "identity_verified")
            v = copy.deepcopy(verify)
            v.edges = [Edge(main.id if e.to not in ("verify", "human_agent") else e.to, e.when, e.source)
                       for e in v.edges if e.to in ("verify", "human_agent") or e.when.startswith("event:")]
            nodes.append(v)
            vt = core.tool(verify.tool)
            tools.insert(0, copy.deepcopy(vt))
            slots = [copy.deepcopy(core.slot(a)) for a in vt.args] + slots
            requires.append("event:identity_verified")
        goal = "Hand the call back to the agent it came from" if cap.get("mode") == "resume" else "Close the call"
        nodes += [main, *rest, Node("done", "end", goal, src, say=L_done)]
        transfer = next(n for n in core.nodes if n.kind == "transfer")
        if any(e.to == transfer.id for n in nodes for e in n.edges) or any(e.to == transfer.id for e in core.global_edges):
            nodes.append(copy.deepcopy(transfer))
        spec = AgentSpec(
            name=f"{core.name}__{cap['id']}", language=core.language, start=nodes[0].id, nodes=nodes,
            slots=slots, tools=tools, intents=copy.deepcopy(core.intents),
            # Inherit the routes to a human, not the entry agent's own inline branches.
            global_edges=[copy.deepcopy(e) for e in core.global_edges if e.to == transfer.id],
            global_instructions=copy.deepcopy(core.global_instructions),
            rules=[copy.deepcopy(r) for r in core.rules if r["kind"] in INHERITED_KINDS],
            personas=[], facts=dict(core.facts), clauses=core.clauses, default_fallback=core.default_fallback,
        )
        return AgentRef(cap["id"], "specialist", spec, src, requires)


@dataclass
class TopoPatch:
    op: str  # spawn_agent | inline_branch | carry_context
    target: str
    detail: dict
    source: list[str]
    reason: str
    personas: list[str] = field(default_factory=list)
    needs_review: bool = False

    @property
    def key(self) -> str:
        return f"{self.op}:{self.target}:{sorted(self.detail.items())}"

    def describe(self) -> str:
        return f"{self.op} {self.target} [{', '.join('§' + s for s in self.source)}]: {self.reason}"

    def apply(self, t: Topology, architect: Architect) -> Topology:
        n = t.clone()
        if self.op == "spawn_agent":
            cap = next(c for c in n.pending if c["id"] == self.target)
            ref = architect.specialist(n.agent(n.entry).spec, cap)
            ref.spawned_because = self.reason
            n.agents.append(ref)
            # Wire the connection from the typed contract: hand over exactly what the specialist requires and the
            # entry agent produces (data minimisation), so it never has to ask the caller again.
            carry = [f for f in ref.requires if f in n.produces(n.entry)]
            n.handoffs.append(Handoff(n.entry, ref.id, cap["intent"], list(cap["source"]), carry=carry))
            if cap.get("mode") == "resume":
                # The SOP says the call goes on afterwards: the specialist hands back to where the caller was.
                n.handoffs.append(Handoff(ref.id, n.entry, "done", list(cap["source"]), handback=True))
            n.pending = [c for c in n.pending if c["id"] != self.target]
        elif self.op == "inline_branch":
            # The same job as a branch inside the entry agent: no new agent, no handoff.
            cap = next(c for c in n.pending if c["id"] == self.target)
            core = n.agent(n.entry).spec
            src, slot = list(cap["source"]), cap["slot"]
            core.slots.append(Slot(slot["name"], slot["kind"], slot["ask"], src))
            done = f"{cap['id']}_done"
            transfer = next(n for n in core.nodes if n.kind == "transfer")
            fail = transfer.id if _to_human(cap) else ""
            tools, rest, main = chain(cap, slot["name"], src, done, fail)
            core.tools += tools
            core.intents.append(Intent(cap["intent"], list(cap["patterns"]), src))
            verify = next((n for n in core.nodes if n.tool and core.tool(n.tool).sets_event == "identity_verified"), None)
            if cap.get("handover") and verify:
                # "He just got home, I'll put him on": the right person is on the line now; verify them and go on.
                core.intents.append(Intent("right_party", list(cap["handover"]), src))
                main.edges.insert(0, Edge(verify.id, "intent:right_party", src))
            for x in (main, *rest, Node(done, "end", "Close the call", src, say=cap["done"])):
                core.nodes.insert(-1, x)
            core.global_edges.append(Edge(cap["id"], f"intent:{cap['intent']}", src))
            n.agent(n.entry).source = list(dict.fromkeys(n.agent(n.entry).source + src))
            n.inline.append(cap["id"])
            n.pending = [c for c in n.pending if c["id"] != self.target]
        elif self.op == "carry_context":
            h = next(h for h in n.handoffs if h.dst == self.target and h.src == self.detail["src"])
            for f in self.detail["fields"]:
                if f not in h.carry:
                    h.carry.append(f)
        return n


def diagnose_topology(t: Topology, res: SuiteResult) -> list[TopoPatch]:
    out: dict[str, TopoPatch] = {}
    pending = {c["intent"]: c for c in t.pending}

    def add(p: TopoPatch, persona: str) -> None:
        q = out.setdefault(p.key, p)
        if persona not in q.personas:
            q.personas.append(persona)

    for run in sorted((r for r in res.runs if r.verdict != "pass"), key=lambda r: RANK[r.verdict]):
        for sig in run.signals:
            if sig.kind == "unrouted_intent" and sig.rule in pending:
                cap = pending[sig.rule]
                why = f"{run.persona}: caller raised '{cap['intent']}' and no agent handles it"
                add(TopoPatch("spawn_agent", cap["id"], {}, list(cap["source"]), why), run.persona)
                if cap.get("mode", "end") == "end" and (not cap["requires_identity"] or len(t.agents) >= t.max_agents):
                    # A self-contained job that needs no verification may not need its own agent at all; with the
                    # spawn budget spent, a branch in the entry agent is the only form left to try.
                    add(TopoPatch("inline_branch", cap["id"], {}, list(cap["source"]), why), run.persona)
            elif sig.kind == "repeated_question" and t.has(sig.rule):
                dst = t.agent(sig.rule)
                h = next(h for h in t.handoffs if h.dst == dst.id)
                upstream = t.produces(t.entry) if h.src == "*" else t.produces(h.src)
                asks = {a for n in dst.spec.nodes for a in n.collects}
                # Carry the least that stops the repeat (data minimisation, KVKK/GDPR): the verified-identity
                # event makes the specialist skip verification, so the answers themselves need not travel.
                fields = [f for f in dst.requires if f in upstream] or sorted(a for a in asks if a in upstream)
                add(TopoPatch("carry_context", dst.id, {"src": h.src, "fields": tuple(fields)}, list(h.source),
                              f"{run.persona}: {dst.id} asked again for {sig.detail}"), run.persona)
    return list(out.values())


@dataclass
class TopoLedgerEntry:
    round: int
    patch: TopoPatch
    accepted: bool
    why: str
    after: dict


def grow(core: AgentSpec, k: int = 3, oracle: Contract | None = None, backends: Backends | None = None,
         max_rounds: int = 10) -> tuple[Topology, Topology, list[TopoLedgerEntry], SuiteResult, SuiteResult]:
    """Grow a topology around a repaired entry agent. Returns (draft, final, ledger, before, after)."""
    arch = Architect()
    oracle = oracle or oracle_contract(core)
    draft = arch.plan(core)
    current = draft
    before = res = run_topology(current, k, oracle, backends)
    ledger: list[TopoLedgerEntry] = []
    tried: set[str] = set()
    for rnd in range(1, max_rounds + 1):
        cands = [p for p in diagnose_topology(current, res) if p.key not in tried]
        progressed = False
        for p in cands:
            if p.key in tried:
                continue
            # Alternatives for the same job (its own agent, or a branch in the entry agent) are tried side by side
            # and the cheapest one that passes the gate is kept: the orchestration style is chosen by evidence.
            group = [q for q in cands if q.target == p.target and q.op in ("spawn_agent", "inline_branch")
                     and q.key not in tried] if p.op in ("spawn_agent", "inline_branch") else [p]
            tried.update(q.key for q in group)
            trials = []
            for q in group:
                new = q.apply(current, arch)
                errs = [e for e in validate_topology(new) if not e.startswith("warning:")]
                if errs:
                    ledger.append(TopoLedgerEntry(rnd, q, False, "invalid topology: " + "; ".join(errs[:2]), {}))
                    continue
                new_res = run_topology(new, k, oracle, backends)
                ok, why = gate(res, new_res, q)
                s = new_res.summary()
                trials.append((q, new, new_res, ok, why, {x: s[x] for x in ("pass@1", "pass^k", "safe^k", "fails")}))
            passing = [t for t in trials if t[3]]
            best = min(passing, key=lambda t: (-t[5]["pass^k"], len(t[1].agents), len(t[1].handoffs))) if passing else None
            for q, new, new_res, ok, why, after in trials:
                if best and q is not best[0] and ok:
                    ok, why = False, f"style: {best[0].op} kept (same job, {len(best[1].agents)} agents vs {len(new.agents)})"
                ledger.append(TopoLedgerEntry(rnd, q, ok, why, after))
            if best:
                current, res, progressed = best[1], best[2], True
                break
        if not progressed:
            break
    return draft, current, ledger, before, res


def topology_mutation(t: Topology, k: int = 3, oracle: Contract | None = None, backends: Backends | None = None) -> dict:
    """Per-clause ablation across every agent, plus removal of agents and handoffs that only that clause justifies."""
    core = t.agent(t.entry).spec
    oracle = oracle or oracle_contract(core)
    base = run_topology(t, k, oracle, backends).verdicts()
    detail = []
    for c in core.clauses:
        if c["strength"] == "info":
            continue
        m = t.clone()
        removed: list[str] = []
        for a in m.agents:
            a.spec, rem = ablate(a.spec, c["id"])
            removed += [f"{a.id}:{x}" for x in rem]
        gone = {a.id for a in m.agents if a.source == [c["id"]] and a.id != m.entry}
        if gone:
            removed += [f"agent:{g}" for g in sorted(gone)]
            m.agents = [a for a in m.agents if a.id not in gone]
            m.handoffs = [h for h in m.handoffs if h.dst not in gone]
            # Without its agent the capability is no longer handled: the router still sees the intent.
        for h in m.handoffs:
            if h.source == [c["id"]] and h.carry:
                removed.append(f"carry:{h.src}->{h.dst}")
                h.carry = []
        if not removed:
            detail.append({"clause": c["id"], "removed": [], "killed": False, "by": []})
            continue
        res = run_topology(m, k, oracle, backends).verdicts()
        by = sorted({p for (p, r), v in res.items() if v != base.get((p, r))})
        detail.append({"clause": c["id"], "removed": removed, "killed": bool(by), "by": by})
    # Order mutants: run each stated pair the other way round ("reissue, then block"). Only the exam's order
    # formula can catch this; both tools are still called.
    for o in core.params.get("order", []):
        m = t.clone()
        hit = False
        for a in m.agents:
            ns = {n.tool: n for n in a.spec.nodes if n.tool in (o["before"], o["after"])}
            if len(ns) == 2:
                x, y = ns[o["before"]], ns[o["after"]]
                x.tool, y.tool = y.tool, x.tool
                for n in (x, y):
                    n.edges = [Edge(e.to, f"event:{n.tool}_done", e.source) if e.when.endswith("_done") else e
                               for e in n.edges]
                hit = True
        if not hit:
            continue
        res = run_topology(m, k, oracle, backends).verdicts()
        by = sorted({p for (p, r), v in res.items() if v != base.get((p, r))})
        detail.append({"clause": "/".join(o["source"]), "removed": [f"order:{o['after']} before {o['before']}"],
                       "killed": bool(by), "by": by})
    # Join mutants: a negative check is ignored and the action runs anyway. Only a caller whose check comes back
    # negative can catch this.
    for a0 in t.agents:
        for n0 in a0.spec.nodes:
            if not n0.join:
                continue
            m = t.clone()
            spec = m.agent(a0.id).spec
            for n in spec.nodes:
                if n.tool in n0.join:
                    nxt = next(e.to for e in n.edges if e.when.startswith("event:"))
                    n.edges = [Edge(nxt, e.when, e.source) if e.when == "tool_failed" else e for e in n.edges]
            spec.node(n0.id).join = []
            res = run_topology(m, k, oracle, backends).verdicts()
            by = sorted({p for (p, r), v in res.items() if v != base.get((p, r))})
            detail.append({"clause": "/".join(n0.source), "removed": [f"join:{n0.tool} ignores {', '.join(n0.join)}"],
                           "killed": bool(by), "by": by})
    scored = [d for d in detail if d["removed"]]
    killed = sum(d["killed"] for d in scored)
    return {"score": round(killed / len(scored), 3) if scored else 0.0, "killed": killed, "mutants": len(scored),
            "survivors": [{"clause": d["clause"], "removed": d["removed"]} for d in scored if not d["killed"]],
            "detail": detail}
