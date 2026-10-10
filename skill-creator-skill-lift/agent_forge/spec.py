"""AgentSpec: the intermediate representation the forge builds, tests and repairs.

One spec compiles to every target (Freya workflow, per-node prompts, the
voice_contract guard policy, Pipecat Flows, tests). Every element carries
``source``: the SOP clause ids it implements. That makes three things possible:

* a traceability matrix a bank's compliance team can read (clause -> artifacts),
* coverage: a normative clause that nothing cites is reported,
* per-clause mutation testing: remove everything citing one clause and check
  the test suite notices.

Edge conditions are a small closed vocabulary, so the runtime, the Freya
emitter and the static checks all read them the same way:

``always``, ``slots_filled``, ``event:<name>``, ``tool_failed``,
``attempts>=<n>``, ``intent:<name>``, ``confirmed``, ``rejected``.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

NODE_KINDS = ("agent", "function", "transfer", "end")
SLOT_KINDS = ("amount", "date", "digits4", "yesno", "text")
_WHEN = re.compile(r"^(always|slots_filled|tool_failed|confirmed|rejected|event:\w+|intent:\w+|attempts>=\d+|"
                   r"slot:\w+(?:>|<|>=|<=)\d+(?:\.\d+)?)$")


@dataclass
class Instruction:
    """One prompt instruction. ``tag`` is machine-readable so offline stand-ins can act on it."""

    text: str
    source: list[str]
    tag: str = ""


@dataclass
class Slot:
    name: str
    kind: str
    ask: str
    source: list[str]
    confirm: bool = False  # read back and get a yes before a tool uses it
    confirm_source: list[str] = field(default_factory=list)


@dataclass
class Constraint:
    """Pre-call argument check (AgentSpec-style trigger -> predicate -> enforce)."""

    arg: str
    op: str  # ">=", "<=", "=="
    fact: str  # name of a fact the bound is computed from
    factor: float
    source: list[str]

    def bound(self, facts: dict[str, Any]) -> float:
        return float(facts[self.fact]) * self.factor

    def ok(self, value: float, facts: dict[str, Any]) -> bool:
        b = self.bound(facts)
        return {">=": value >= b, "<=": value <= b, "==": value == b}[self.op]

    def describe(self) -> str:
        return f"{self.arg} {self.op} {self.factor:g} × {self.fact}"


@dataclass
class Tool:
    name: str
    args: list[str]  # slot names
    source: list[str]
    sets_event: str | None = None  # event raised on success (e.g. identity_verified)
    constraints: list[Constraint] = field(default_factory=list)
    side_effect: bool = False  # writes to a system of record


@dataclass
class Edge:
    to: str
    when: str = "always"
    source: list[str] = field(default_factory=list)


@dataclass
class Node:
    id: str
    kind: str
    goal: str
    source: list[str]
    say: str = ""  # what the agent says on entering (template, {slot}/{fact} filled)
    collects: list[str] = field(default_factory=list)
    tool: str | None = None
    instructions: list[Instruction] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    max_attempts: int | None = None  # bounded loop: after this many failed tool calls, take the attempts>= edge
    target: str | None = None  # transfer target
    join: list[str] = field(default_factory=list)  # tools that must all have succeeded before this node's tool runs
    parallel: bool = False  # the join's checks have no stated order (they may run concurrently)


@dataclass
class Intent:
    name: str
    patterns: list[str]
    source: list[str]


@dataclass
class Persona:
    """A simulated caller. ``behaviour`` keys are read by simulate.ScriptedCaller."""

    id: str
    goal: str
    behaviour: dict[str, Any]
    expect: dict[str, Any]  # end: transfer|end, tools: {name: {arg: value}}, no_tools: [...]
    source: list[str]


@dataclass
class AgentSpec:
    name: str
    language: str
    start: str
    nodes: list[Node]
    slots: list[Slot]
    tools: list[Tool]
    intents: list[Intent]
    global_edges: list[Edge]  # taken from any agent node, e.g. intent:escalate -> transfer
    global_instructions: list[Instruction]
    rules: list[dict]  # voice_contract policy rules (the guard and the test oracle)
    personas: list[Persona]
    facts: dict[str, Any]  # account data the agent can see (mock CRM)
    clauses: list[dict]  # [{id, section, text, strength}] from the SOP
    params: dict[str, Any] = field(default_factory=dict)  # policy numbers the repair loop may need: {name: {value, source}}
    # Conditional clauses that call for a separate specialist ("if the caller disputes the debt ...").
    # The architect spawns an agent for one only when a simulated call proves it is needed.
    capabilities: list[dict] = field(default_factory=list)
    hold_chars: int = 40
    default_fallback: str = ""
    notes: list[str] = field(default_factory=list)  # extractor assumptions to review

    # -- lookups -------------------------------------------------------------

    def node(self, nid: str) -> Node:
        for n in self.nodes:
            if n.id == nid:
                return n
        raise KeyError(nid)

    def has_node(self, nid: str) -> bool:
        return any(n.id == nid for n in self.nodes)

    def slot(self, name: str) -> Slot:
        return next(s for s in self.slots if s.name == name)

    def tool(self, name: str) -> Tool:
        return next(t for t in self.tools if t.name == name)

    def clone(self) -> "AgentSpec":
        return copy.deepcopy(self)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> "AgentSpec":
        d = copy.deepcopy(d)
        nodes = []
        for n in d.pop("nodes"):
            n["instructions"] = [Instruction(**i) for i in n.get("instructions", [])]
            n["edges"] = [Edge(**e) for e in n.get("edges", [])]
            nodes.append(Node(**n))
        tools = []
        for t in d.pop("tools"):
            t["constraints"] = [Constraint(**c) for c in t.get("constraints", [])]
            tools.append(Tool(**t))
        return cls(
            nodes=nodes,
            tools=tools,
            slots=[Slot(**s) for s in d.pop("slots")],
            intents=[Intent(**i) for i in d.pop("intents")],
            global_edges=[Edge(**e) for e in d.pop("global_edges")],
            global_instructions=[Instruction(**i) for i in d.pop("global_instructions")],
            personas=[Persona(**p) for p in d.pop("personas")],
            **d,
        )

    # -- provenance ----------------------------------------------------------

    def citations(self) -> dict[str, list[str]]:
        """clause id -> list of artifact labels that cite it."""
        out: dict[str, list[str]] = {}

        def cite(src: list[str], label: str) -> None:
            for c in src:
                out.setdefault(c, []).append(label)

        for n in self.nodes:
            cite(n.source, f"node:{n.id}")
            for i in n.instructions:
                cite(i.source, f"instruction:{n.id}:{i.tag or i.text[:24]}")
            for e in n.edges:
                cite(e.source, f"edge:{n.id}->{e.to}[{e.when}]")
        for s in self.slots:
            cite(s.source, f"slot:{s.name}")
            cite(s.confirm_source, f"confirm:{s.name}")
        for t in self.tools:
            cite(t.source, f"tool:{t.name}")
            for c in t.constraints:
                cite(c.source, f"constraint:{t.name}.{c.describe()}")
        for i in self.intents:
            cite(i.source, f"intent:{i.name}")
        for e in self.global_edges:
            cite(e.source, f"global_edge:{e.when}->{e.to}")
        for i in self.global_instructions:
            cite(i.source, f"instruction:*:{i.tag or i.text[:24]}")
        for r in self.rules:
            cite(_clause_ids(r.get("source", "")), f"guard:{r['id']}")
        for p in self.personas:
            cite(p.source, f"test:{p.id}")
        for c in self.capabilities:
            cite(c["source"], f"capability:{c['id']}")
        for o in self.params.get("order", []):
            cite(o["source"], f"order:{o['before']}<{o['after']}")
        return out

    def coverage(self) -> dict:
        cites = self.citations()
        normative = [c["id"] for c in self.clauses if c["strength"] != "info"]
        implemented = [c for c in normative if any(not a.startswith("test:") for a in cites.get(c, []))]
        # The audit checks every oracle rule on every simulated call, so a clause with a guard rule is tested too.
        tested = [c for c in normative if any(a.startswith(("test:", "guard:")) for a in cites.get(c, []))]
        return {
            "normative": len(normative),
            "implemented": len(implemented),
            "tested": len(tested),
            "unimplemented": [c for c in normative if c not in implemented],
            "untested": [c for c in normative if c not in tested],
        }


def _clause_ids(source: str) -> list[str]:
    """voice_contract rules carry a free-text source; the forge writes '§3.2 ...' into it."""
    return re.findall(r"§(\d+(?:\.\d+)+|[\w-]+\.p\d+)", source)


class SpecError(ValueError):
    pass


def validate(spec: AgentSpec) -> list[str]:
    """Static checks. Returns problems; an empty list means the spec is structurally sound."""
    errs: list[str] = []
    ids = [n.id for n in spec.nodes]
    if len(set(ids)) != len(ids):
        errs.append("duplicate node ids")
    if spec.start not in ids:
        errs.append(f"start node {spec.start!r} does not exist")
    slot_names = {s.name for s in spec.slots}
    tool_names = {t.name for t in spec.tools}
    intent_names = {i.name for i in spec.intents}
    for s in spec.slots:
        if s.kind not in SLOT_KINDS:
            errs.append(f"slot {s.name}: unknown kind {s.kind}")
    for t in spec.tools:
        for a in t.args:
            if a not in slot_names:
                errs.append(f"tool {t.name}: arg {a} is not a slot")
        for c in t.constraints:
            if c.fact not in spec.facts:
                errs.append(f"tool {t.name}: constraint uses unknown fact {c.fact}")
    for n in spec.nodes:
        if n.kind not in NODE_KINDS:
            errs.append(f"node {n.id}: unknown kind {n.kind}")
        if not n.source:
            errs.append(f"node {n.id}: no source clause")
        for c in n.collects:
            if c not in slot_names:
                errs.append(f"node {n.id}: collects unknown slot {c}")
        if n.tool and n.tool not in tool_names:
            errs.append(f"node {n.id}: unknown tool {n.tool}")
        if n.kind in ("agent", "function") and not n.edges:
            errs.append(f"node {n.id}: dead end (no outgoing edge)")
        if n.kind in ("transfer", "end") and n.edges:
            errs.append(f"node {n.id}: terminal node has edges")
        for e in n.edges:
            _check_edge(e, ids, intent_names, f"node {n.id}", errs)
        has_attempt_edge = any(e.when.startswith("attempts>=") for e in n.edges)
        retries = any(e.to == n.id for e in n.edges)
        if retries and not (n.max_attempts and has_attempt_edge):
            errs.append(f"node {n.id}: unbounded retry loop (self-edge without max_attempts and an attempts>= exit)")
    for e in spec.global_edges:
        _check_edge(e, ids, intent_names, "global", errs)
    # Reachability from start, following node and global edges.
    if spec.start in ids:
        seen, todo = set(), [spec.start]
        globals_to = [e.to for e in spec.global_edges]
        while todo:
            nid = todo.pop()
            if nid in seen:
                continue
            seen.add(nid)
            todo.extend(e.to for e in spec.node(nid).edges)
            todo.extend(globals_to)
        for nid in ids:
            if nid not in seen:
                errs.append(f"node {nid}: unreachable from {spec.start}")
        if not any(spec.node(n).kind in ("end", "transfer") for n in seen):
            errs.append("no terminal node reachable")
    # Every side-effecting tool whose args are spoken values should have them confirmed.
    for t in spec.tools:
        if t.side_effect:
            for a in t.args:
                s = next((s for s in spec.slots if s.name == a), None)
                if s and s.kind == "amount" and not s.confirm:
                    errs.append(f"warning: tool {t.name} writes spoken amount {a} without read-back confirmation")
    # The guard policy must compile.
    try:
        from voice_contract.contract import compile_policy

        compile_policy(guard_policy(spec))
    except Exception as exc:  # noqa: BLE001 - surface every compile problem as a spec problem
        errs.append(f"guard policy does not compile: {exc}")
    return errs


def errors_only(problems: list[str]) -> list[str]:
    return [p for p in problems if not p.startswith("warning:")]


def _check_edge(e: Edge, ids: list[str], intents: set[str], where: str, errs: list[str]) -> None:
    if e.to not in ids:
        errs.append(f"{where}: edge to unknown node {e.to}")
    if not _WHEN.match(e.when):
        errs.append(f"{where}: bad edge condition {e.when!r}")
    elif e.when.startswith("intent:") and e.when[7:] not in intents:
        errs.append(f"{where}: edge on unknown intent {e.when[7:]}")


def guard_policy(spec: AgentSpec) -> dict:
    """The voice_contract policy for the live guard."""
    return {
        "name": spec.name,
        "language": spec.language,
        "hold_chars": spec.hold_chars,
        "default_fallback": spec.default_fallback or "Bu konuda size yardımcı olamıyorum.",
        "rules": copy.deepcopy(spec.rules),
    }
