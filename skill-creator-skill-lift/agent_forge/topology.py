"""Multi-agent topology: specialist agents wired into a DAG by typed handoffs.

A call starts at the entry agent. A handoff fires when the caller's intent
matches it and moves the call to another agent, carrying a context envelope
(slots and events already established), so the next agent does not ask again.
LiveKit's handoff pattern and Hamming's state-transition write-up both name
lost context at a handoff as the main multi-agent voice failure; here the
envelope is explicit, typed and checked.

Static checks:

* the handoff graph without handback edges is acyclic (a DAG), and handbacks
  are bounded by ``max_handoffs``,
* dataflow: every carried field is produced upstream, and a field a
  specialist requires but is not handed has to be asked again (the
  repeated-question risk, reported before any call is simulated),
* policy inheritance: every specialist carries the entry agent's
  prohibitions (forbidden, gated, PII, injection, length) and escalation route,
* every agent is reachable and every agent spec passes ``spec.validate``.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field

from .spec import AgentSpec, errors_only, validate

INHERITED_KINDS = ("gated_topic", "pii_leak", "forbidden", "injection", "max_words", "escalation")


@dataclass
class Handoff:
    src: str  # agent id, or "*" for any agent
    dst: str
    intent: str
    source: list[str]
    carry: list[str] = field(default_factory=list)  # slot names and "event:<name>"
    handback: bool = False  # returns control upstream (allowed cycle, bounded)


@dataclass
class AgentRef:
    id: str
    role: str
    spec: AgentSpec
    source: list[str]
    requires: list[str] = field(default_factory=list)  # context it needs, e.g. "event:identity_verified"
    spawned_because: str = ""


@dataclass
class Topology:
    name: str
    entry: str
    agents: list[AgentRef]
    handoffs: list[Handoff]
    pending: list[dict]  # capabilities not spawned (yet)
    max_handoffs: int = 4
    max_agents: int = 6  # spawn budget (redel-style hard limit; agent count gains saturate, MacNet)
    inline: list[str] = field(default_factory=list)  # capabilities handled as a branch inside the entry agent

    def style(self) -> str:
        """The orchestration pattern the architect ended up with, in words."""
        spec = [a for a in self.agents if a.id != self.entry]
        back = [h for h in self.handoffs if h.handback]
        if not spec and not self.inline:
            return "single agent"
        parts = []
        if spec:
            parts.append(f"router + {len(spec)} specialist{'s' if len(spec) > 1 else ''}")
        if back:
            parts.append(f"{len(back)} with handback")
        if self.inline:
            parts.append(f"{len(self.inline)} inline branch{'es' if len(self.inline) > 1 else ''}")
        joins = [n for a in self.agents for n in a.spec.nodes if n.join]
        if joins:
            parts.append(f"{len(joins)} join{'s' if len(joins) > 1 else ''} (" + "; ".join(
                f"{n.tool} after all of {', '.join(n.join)}" + ("" if n.parallel else " in order") for n in joins) + ")")
        return ", ".join(parts)

    def agent(self, aid: str) -> AgentRef:
        return next(a for a in self.agents if a.id == aid)

    def has(self, aid: str) -> bool:
        return any(a.id == aid for a in self.agents)

    def clone(self) -> "Topology":
        return copy.deepcopy(self)

    def out_of(self, aid: str) -> list[Handoff]:
        return [h for h in self.handoffs if (h.src == aid or h.src == "*") and h.dst != aid]

    def produces(self, aid: str) -> set[str]:
        s = self.agent(aid).spec
        return {sl.name for sl in s.slots} | {f"event:{t.sets_event}" for t in s.tools if t.sets_event}

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "entry": self.entry,
            "max_handoffs": self.max_handoffs,
            "agents": [{"id": a.id, "role": a.role, "source": a.source, "requires": a.requires,
                        "spawned_because": a.spawned_because, "nodes": [n.id for n in a.spec.nodes],
                        "tools": [t.name for t in a.spec.tools]} for a in self.agents],
            "handoffs": [asdict(h) for h in self.handoffs],
            "pending_capabilities": [c["id"] for c in self.pending],
            "inline": self.inline,
            "style": self.style(),
        }

    def mermaid(self) -> str:
        lines = ["flowchart LR", "    caller((caller)) --> " + self.entry]
        for a in self.agents:
            label = f"{a.id}<br/><small>{', '.join('§' + s for s in a.source[:3])}</small>"
            lines.append(f"    {a.id}[\"{label}\"]")
        for h in self.handoffs:
            srcs = [a.id for a in self.agents if a.id != h.dst] if h.src == "*" else [h.src]
            carry = (" + " + ", ".join(h.carry)) if h.carry else ""
            arrow = "-.->" if h.handback else "-->"
            for src in srcs:
                lines.append(f"    {src} {arrow}|\"{h.intent}{carry}\"| {h.dst}")
        return "\n".join(lines)


def validate_topology(t: Topology) -> list[str]:
    errs: list[str] = []
    ids = [a.id for a in t.agents]
    if len(set(ids)) != len(ids):
        errs.append("duplicate agent ids")
    if t.entry not in ids:
        errs.append(f"entry agent {t.entry} does not exist")
        return errs
    for a in t.agents:
        for e in errors_only(validate(a.spec)):
            errs.append(f"agent {a.id}: {e}")
    depth: list[str] = []
    if len(ids) > t.max_agents:
        errs.append(f"spawn budget: {len(ids)} agents, at most {t.max_agents}")
    for h in t.handoffs:
        for end in ([h.src] if h.src != "*" else []) + [h.dst]:
            if end not in ids:
                errs.append(f"handoff {h.src}->{h.dst}: unknown agent {end}")
        if h.src not in (t.entry, "*") and not h.handback:
            # Only the architect spawns, and only one level below the entry agent: no specialist delegates on.
            depth.append(f"handoff {h.src}->{h.dst}: depth limit, only {t.entry} may hand off to a specialist")
    if errs:
        return errs + depth
    errs += depth
    # DAG over forward handoffs.
    fwd: dict[str, set[str]] = {a: set() for a in ids}
    for h in t.handoffs:
        if h.handback:
            continue
        for src in (ids if h.src == "*" else [h.src]):
            if src != h.dst:
                fwd[src].add(h.dst)
    state: dict[str, int] = {}

    def visit(n: str, path: list[str]) -> None:
        state[n] = 1
        for m in fwd[n]:
            if state.get(m) == 1:
                errs.append("handoff cycle: " + " -> ".join(path + [n, m]))
            elif not state.get(m):
                visit(m, path + [n])
        state[n] = 2

    for n in ids:
        if not state.get(n):
            visit(n, [])
    # Reachability from entry.
    seen, todo = set(), [t.entry]
    while todo:
        n = todo.pop()
        if n not in seen:
            seen.add(n)
            todo.extend(h.dst for h in t.out_of(n))
    for n in ids:
        if n not in seen:
            errs.append(f"agent {n}: unreachable from {t.entry}")
    # Dataflow: carried fields must exist upstream; required fields not carried will be asked again.
    for h in t.handoffs:
        srcs = [a for a in ids if a != h.dst] if h.src == "*" else [h.src]
        upstream = set().union(*(t.produces(s) for s in srcs)) if srcs else set()
        for f in h.carry:
            if f not in upstream:
                errs.append(f"handoff {h.src}->{h.dst}: carries {f}, which no upstream agent produces")
        dst = t.agent(h.dst)
        for f in dst.requires:
            if f not in h.carry and f in upstream:
                errs.append(f"warning: handoff {h.src}->{h.dst} drops {f}; {h.dst} will ask the caller again")
    # Policy inheritance.
    base = t.agent(t.entry).spec
    must = {r["id"] for r in base.rules if r["kind"] in INHERITED_KINDS}
    # Routes to a human must survive a handoff; inline branches of the core are the core's own business.
    human = {n.id for n in base.nodes if n.kind == "transfer"}
    base_routes = {e.when for e in base.global_edges if e.to in human}
    for a in t.agents:
        if a.id == t.entry:
            continue
        missing = must - {r["id"] for r in a.spec.rules}
        if missing:
            errs.append(f"agent {a.id}: does not inherit guard rules {sorted(missing)}")
        lost = base_routes - {e.when for e in a.spec.global_edges}
        if lost:
            errs.append(f"agent {a.id}: does not inherit routes {sorted(lost)}")
    return errs
