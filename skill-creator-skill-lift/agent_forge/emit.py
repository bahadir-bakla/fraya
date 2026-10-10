"""Compile an AgentSpec to deployable artifacts.

* ``freya_workflow.json``: Freya Workflow Builder graph with its documented
  node types (Agent, Function, Condition, Transfer, Loop; End). Freya's
  workflow *write* schema is not public (only list/get are documented), so
  field names here are our best mapping and the file says so.
* ``prompts/<node>.md``: one system prompt per agent node; every instruction
  line ends with the clause it comes from.
* ``guard_policy.yaml``: the voice_contract policy for the live guard between
  LLM and TTS.
* ``freya_unit_tests.json``, ``freya_personas.json``,
  ``freya_simulation.json``: shaped after ``POST /api/v2/unit-tests``,
  ``/personas`` and ``/simulations`` (``runsPerPersona`` = k for pass^k).
* ``pipecat_flow.json``: Pipecat Flows node configs for an open-source runtime.
* ``traceability.md``: clause -> every artifact that implements or tests it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from voice_contract.contract import compile_policy
from voice_contract.emit import freya_unit_tests

from .spec import AgentSpec, Node, guard_policy

_TYPES = {"amount": "number", "date": "string", "digits4": "string", "yesno": "boolean", "text": "string"}


def node_prompt(spec: AgentSpec, node: Node) -> str:
    lines = [f"# {node.id}: {node.goal}  [{', '.join('§' + s for s in node.source)}]", ""]
    lines.append("You are a voice agent on a phone call. Speak briefly; one question at a time.")
    if spec.global_instructions:
        lines += ["", "## Always"]
        lines += [f"- {i.text} [{', '.join('§' + s for s in i.source) or 'assumption'}]" for i in spec.global_instructions]
    if node.instructions:
        lines += ["", "## In this step"]
        lines += [f"- {i.text} [{', '.join('§' + s for s in i.source) or 'assumption'}]" for i in node.instructions]
    if node.say:
        lines += ["", "## Say on entry", node.say]
    if node.collects:
        lines += ["", "## Collect"]
        for sname in node.collects:
            s = spec.slot(sname)
            conf = f" Read it back and get a yes before using it [{', '.join('§' + c for c in s.confirm_source) or 'assumption'}]." if s.confirm else ""
            lines.append(f"- `{s.name}` ({s.kind}): {s.ask}{conf}")
    if node.tool:
        t = spec.tool(node.tool)
        lines += ["", "## Tool", f"- Call `{t.name}({', '.join(t.args)})` once every value is collected."]
        for c in t.constraints:
            lines.append(f"- Only call it when {c.describe()} [{', '.join('§' + x for x in c.source)}].")
    return "\n".join(lines) + "\n"


def freya_workflow(spec: AgentSpec, extra_intents: list[str] | None = None) -> dict:
    """One Freya workflow. Every condition reads a declared variable, and something in the graph sets it:
    agent nodes extract ``intent`` (a closed set) along with their slots, function nodes set their event, and a
    bounded retry counts its attempts in ``<node>_attempts``."""
    nodes, edges = [], []
    labels = list(dict.fromkeys([it.name for it in spec.intents] + list(extra_intents or [])))

    def edge(src: str, dst: str, cond: dict | None = None, source: list[str] | None = None) -> None:
        edges.append({"id": f"e{len(edges) + 1}", "source": src, "target": dst,
                      **({"condition": cond} if cond else {}), "policySource": source or []})

    def cond_of(when: str, nid: str) -> dict | None:
        if when in ("always", "slots_filled"):
            return None  # the fallback edge, after the conditional ones
        if when.startswith("slot:"):
            name, op, bound = re.match(r"slot:(\w+)(>=|<=|>|<)([\d.]+)", when).groups()
            return {"variable": name, "operator": {">": "gt", "<": "lt", ">=": "gte", "<=": "lte"}[op],
                    "value": float(bound)}
        if when.startswith("event:"):
            return {"variable": when[6:], "operator": "equals", "value": True}
        if when.startswith("intent:"):
            return {"variable": "intent", "operator": "equals", "value": when[7:]}
        if when.startswith("attempts>="):
            return {"variable": f"{nid}_attempts", "operator": "gte", "value": int(when[10:])}
        if when == "tool_failed":
            return {"variable": "last_call_ok", "operator": "equals", "value": False}
        return {"variable": when, "operator": "equals", "value": True}

    intent_collect = ([{"name": "intent", "type": "string", "enum": labels + ["none"],
                        "description": "Which listed situation the caller's last turn is in; none if unsure."}]
                      if labels else [])
    counters = []
    nodes.append({"id": "start", "type": "start"})
    edge("start", spec.start)
    for n in spec.nodes:
        if n.kind == "transfer":
            nodes.append({"id": n.id, "type": "transfer", "data": {"target": n.target or n.id, "message": n.say},
                          "policySource": n.source})
            continue
        if n.kind == "end":
            nodes.append({"id": n.id, "type": "agent", "data": {"prompt": node_prompt(spec, n), "endCall": True},
                          "policySource": n.source})
            continue
        bounded = any(e.when.startswith("attempts>=") for e in n.edges)
        if n.kind == "function":
            exit_from = n.id
        else:
            nodes.append({"id": n.id, "type": "agent", "data": {
                "prompt": node_prompt(spec, n),
                "collect": [{"name": s, "type": _TYPES[spec.slot(s).kind]} for s in n.collects] + intent_collect},
                "policySource": n.source})
            exit_from = n.id
        if n.tool:
            t = spec.tool(n.tool)
            fid = n.id if n.kind == "function" else f"{n.id}__{t.name}"
            nodes.append({"id": fid, "type": "function", "data": {
                "function": t.name, "args": {a: f"{{{{{a}}}}}" for a in t.args},
                "preconditions": [c.describe() for c in t.constraints],
                "outputs": {**({t.sets_event: "boolean"} if t.sets_event else {}), "last_call_ok": "boolean"},
                **({"increment": f"{n.id}_attempts"} if bounded else {})}, "policySource": t.source})
            if fid != n.id:
                edge(n.id, fid)
            exit_from = fid
        if bounded:
            counters.append(f"{n.id}_attempts")
        cid = f"{n.id}__route"
        nodes.append({"id": cid, "type": "condition", "data": {}})
        edge(exit_from, cid)
        # Attempt bounds first, so a bounded retry exits before the retry edge fires (as in the runtime).
        for e in sorted(n.edges, key=lambda e: 0 if e.when.startswith("attempts>=") else 1):
            edge(cid, e.to, cond_of(e.when, n.id), e.source)
        if n.kind != "function":
            for e in spec.global_edges:
                edge(n.id, e.to, cond_of(e.when, n.id), e.source)
    for n in spec.nodes:
        if not n.join:
            continue
        # Join: a condition node in front of the action that passes only when every check succeeded.
        fid = n.id if n.kind == "function" else f"{n.id}__{n.tool}"
        jid = f"{fid}__join"
        checks = [{"variable": spec.tool(t).sets_event, "operator": "equals", "value": True} for t in n.join]
        fail = next((e.to for e in n.edges if e.when == "tool_failed"), None)
        for e in edges:
            if e["target"] == fid:
                e["target"] = jid
        nodes.append({"id": jid, "type": "condition", "data": {"join": "all", "waitsOn": list(n.join),
                                                                 "parallel": n.parallel}, "policySource": n.source})
        edge(jid, fid, {"operator": "all", "conditions": checks}, n.source)
        if fail:
            edge(jid, fail, {"operator": "not_all", "conditions": checks}, n.source)
        if n.parallel:
            for x in nodes:
                if x["type"] == "function" and x["data"]["function"] in n.join:
                    x["data"]["parallel"] = True  # no stated order between these checks
    return {
        "$comment": "Node types from docs.freyavoice.ai Workflow Builder (Agent, Function, Condition, Transfer, "
                    "Wait, Loop). Freya's workflow write schema is not public; field names are a mapping, not a "
                    "verified payload. check_workflow() verifies reachability and that every condition reads a "
                    "declared variable some node sets.",
        "name": spec.name,
        "variables": (
            [{"name": s.name, "type": _TYPES[s.kind], "scope": "global"} for s in spec.slots]
            + [{"name": t.sets_event, "type": "boolean", "scope": "global"} for t in spec.tools if t.sets_event]
            + ([{"name": "intent", "type": "string", "scope": "global", "enum": labels + ["none"]}] if labels else [])
            + [{"name": "last_call_ok", "type": "boolean", "scope": "global"}]
            + [{"name": c, "type": "number", "scope": "global", "default": 0} for c in counters]
            + [{"name": k, "type": "number" if isinstance(v, (int, float)) else "string", "scope": "input"}
               for k, v in spec.facts.items()]
        ),
        "nodes": nodes,
        "edges": edges,
    }


def check_workflow(wf: dict) -> list[str]:
    """What a reviewer opening the file would trip on: unreachable or dangling nodes, conditions on variables
    nobody declares or sets, edges to nodes that do not exist."""
    ids = {n["id"] for n in wf["nodes"]}
    out = [f"edge {e['id']} points to missing node {x}" for e in wf["edges"] for x in (e["source"], e.get("target"))
           if x not in ids and not (x is None and e.get("targetVariable"))]
    declared = {v["name"] for v in wf.get("variables", [])}
    set_by = {"intent"} & declared
    for n in wf["nodes"]:
        d = n.get("data", {})
        set_by |= {c["name"] for c in d.get("collect", [])} | set(d.get("outputs", {})) | (
            {d["increment"]} if d.get("increment") else set())
    for e in wf["edges"]:
        set_by |= set(e.get("setVariables", {}))
    for e in wf["edges"]:
        cond = e.get("condition") or {}
        for sub in cond.get("conditions", []):
            if sub["variable"] not in declared or sub["variable"] not in set_by:
                out.append(f"edge {e['id']} joins on {sub['variable']}, which is undeclared or never set")
        v = cond.get("variable")
        if e.get("targetVariable") and e["targetVariable"] not in declared:
            out.append(f"edge {e['id']} jumps through undeclared variable {e['targetVariable']}")
        if v and v not in declared:
            out.append(f"edge {e['id']} reads undeclared variable {v}")
        elif v and v not in set_by:
            out.append(f"edge {e['id']} reads {v}, which no node sets")
    succ: dict[str, list[str]] = {}
    for e in wf["edges"]:
        if e.get("target"):
            succ.setdefault(e["source"], []).append(e["target"])
    seen, todo = set(), ["start"]
    while todo:
        x = todo.pop()
        if x in seen:
            continue
        seen.add(x)
        todo += succ.get(x, [])
    out += [f"node {i} is unreachable from start" for i in sorted(ids - seen)]
    for n in wf["nodes"]:
        terminal = n["type"] == "transfer" or n.get("data", {}).get("endCall")
        back = any(e.get("handback") and e["source"] == n["id"] for e in wf["edges"])
        if not terminal and not back and not succ.get(n["id"]):
            out.append(f"node {n['id']} ({n['type']}) leads nowhere")
    return out


def freya_personas(spec: AgentSpec, agent_ids: list[str] | None = None) -> dict:
    out = []
    for p in spec.personas:
        b = p.behaviour
        said = [b.get("first_line"), (b.get("interject") or {}).get("text"), *(b.get("amount_lines") or [])]
        prompt = p.goal + ". " + " ".join(f'Say: "{s}"' for s in said if s)
        out.append({
            "name": f"{p.id} ({', '.join('§' + s for s in p.source)})",
            "prompt": prompt.strip(),
            "successCriteria": _criteria(p.expect),
            "tags": ["agent-forge", spec.name, p.id],
            **({"agentIds": agent_ids} if agent_ids else {}),
        })
    return {"personas": out}


def _criteria(exp: dict) -> str:
    parts = []
    if exp.get("end") == "transfer":
        parts.append("The call is transferred to a human agent.")
    elif exp.get("end") == "end":
        parts.append("The call completes normally.")
    for tool, args in (exp.get("tools") or {}).items():
        parts.append(f"`{tool}` is called" + (f" with {json.dumps(args)}" if args else "") + ".")
    for tool in exp.get("no_tools") or []:
        parts.append(f"`{tool}` is never called.")
    for tool, n in (exp.get("max_tool_calls") or {}).items():
        parts.append(f"`{tool}` is called at most {n} times.")
    parts.append("No policy violation is spoken.")
    return " ".join(parts)


def freya_simulation(spec: AgentSpec, k: int) -> dict:
    return {
        "name": f"{spec.name} policy suite",
        "agentId": "<AGENT_ID>",
        "selectedPersonaIds": [f"<PERSONA_ID:{p.id}>" for p in spec.personas],
        "mode": "voice",
        "runsPerPersona": k,
        "tags": ["agent-forge", spec.name],
    }


def pipecat_flow(spec: AgentSpec) -> dict:
    nodes = {}
    for n in spec.nodes:
        fns = []
        for s in n.collects:
            sl = spec.slot(s)
            fns.append({"type": "function", "function": {
                "name": f"collect_{s}", "description": sl.ask,
                "parameters": {"type": "object", "properties": {s: {"type": _TYPES[sl.kind]}}, "required": [s]}}})
        if n.tool:
            t = spec.tool(n.tool)
            fns.append({"type": "function", "function": {
                "name": t.name, "description": f"Call when {', '.join(t.args)} are collected",
                "parameters": {"type": "object", "properties": {a: {"type": _TYPES[spec.slot(a).kind]} for a in t.args},
                               "required": t.args}}})
        nodes[n.id] = {
            "role_messages": [{"role": "system", "content": node_prompt(spec, n)}],
            "task_messages": [{"role": "system", "content": n.goal + (f" Say: {n.say}" if n.say else "")}],
            "functions": fns,
            "transitions": [{"to": e.to, "when": e.when} for e in n.edges]
            + [{"to": e.to, "when": e.when} for e in spec.global_edges if n.kind == "agent"],
            **({"post_actions": [{"type": "end_conversation"}]} if n.kind in ("end", "transfer") else {}),
        }
    return {"initial_node": spec.start, "nodes": nodes}


def traceability(spec: AgentSpec) -> str:
    cites = spec.citations()
    rows = ["| Clause | Binding | Text | Implemented by | Tested by |", "|---|---|---|---|---|"]
    for c in spec.clauses:
        arts = cites.get(c["id"], [])
        impl = [a for a in arts if not a.startswith("test:")]
        tests = [a[5:] for a in arts if a.startswith("test:")]
        text = c["text"].replace("|", "\\|")
        rows.append(f"| §{c['id']} | {c['strength']} | {text} | {'<br>'.join(impl) or '—'} | {', '.join(tests) or '—'} |")
    cov = spec.coverage()
    head = (f"# Traceability: {spec.name}\n\n{cov['implemented']}/{cov['normative']} normative clauses implemented, "
            f"{cov['tested']}/{cov['normative']} exercised by a simulated caller or the audit oracle.\n\n")
    return head + "\n".join(rows) + "\n"


def write_all(spec: AgentSpec, out: str | Path, k: int = 3) -> list[Path]:
    import yaml

    out = Path(out)
    (out / "prompts").mkdir(parents=True, exist_ok=True)
    written = []

    def put(name: str, text: str) -> None:
        p = out / name
        p.write_text(text, encoding="utf-8")
        written.append(p)

    def put_json(name: str, data) -> None:
        put(name, json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    put("spec.json", spec.to_json() + "\n")
    put_json("freya_workflow.json", freya_workflow(spec))
    for n in spec.nodes:
        if n.kind in ("agent", "end"):
            put(f"prompts/{n.id}.md", node_prompt(spec, n))
    policy = guard_policy(spec)
    put("guard_policy.yaml", yaml.safe_dump(policy, allow_unicode=True, sort_keys=False))
    put_json("freya_unit_tests.json", freya_unit_tests(compile_policy(policy), "<WORKSPACE_ID>", "<AGENT_ID>"))
    put_json("freya_personas.json", freya_personas(spec))
    put_json("freya_simulation.json", freya_simulation(spec, k))
    put_json("pipecat_flow.json", pipecat_flow(spec))
    put("traceability.md", traceability(spec))
    return written


def freya_multiagent_workflow(t) -> dict:
    """One Freya workflow with an Agent node group per agent; handoffs become intent-conditioned edges.

    Freya's docs say different agents can serve different parts of one workflow, so a topology maps onto a
    single workflow. Handoff edges carry ``context`` (the envelope fields) so a builder can wire variables.
    Each agent's ``intent`` enum includes the handoffs leaving it, so the variable a handoff edge reads is one
    the agent's own nodes fill.
    """
    nodes, edges, variables = [{"id": "start", "type": "start"}], [], {}
    returns = {h.src for h in t.handoffs if h.handback}
    for a in t.agents:
        leaving = [h.intent for h in t.handoffs if not h.handback and h.src in (a.id, "*") and h.dst != a.id]
        wf = freya_workflow(a.spec, extra_intents=leaving)
        for v in wf["variables"]:
            if v["name"] in variables and "enum" in v:
                old = variables[v["name"]]
                old["enum"] = list(dict.fromkeys(old.get("enum", []) + v["enum"]))
            else:
                variables.setdefault(v["name"], dict(v))
        for n in wf["nodes"]:
            if n["type"] == "start":
                continue
            m = {**n, "id": f"{a.id}.{n['id']}", "agent": a.id}
            if a.id in returns and n.get("data", {}).get("endCall"):
                m["data"] = {**n["data"], "endCall": False}  # a handback specialist returns instead of hanging up
            nodes.append(m)
        for e in wf["edges"]:
            if e["source"] == "start":
                if a.id == t.entry:
                    edges.append({**e, "source": "start", "target": f"{a.id}.{e['target']}"})
                continue
            edges.append({**e, "source": f"{a.id}.{e['source']}", "target": f"{a.id}.{e['target']}"})
    if returns:
        variables["returnTo"] = {"name": "returnTo", "type": "string", "scope": "global"}
    for h in t.handoffs:
        srcs = [a for a in t.agents if a.id != h.dst] if h.src == "*" else [t.agent(h.src)]
        dst = t.agent(h.dst)
        if h.handback:
            # Resume where the call left off: the forward edge stored its source node in ``returnTo``.
            src = srcs[0]
            done = next((x.sets_event for x in reversed(src.spec.tools) if x.sets_event), None)
            for n in src.spec.nodes:
                if n.kind == "end":
                    e = {"source": f"{src.id}.{n.id}", "targetVariable": "returnTo", "handback": True,
                         "policySource": h.source}
                    if done:
                        e["condition"] = {"variable": done, "operator": "equals", "value": True}
                    edges.append(e)
            continue
        for src in srcs:
            for n in src.spec.nodes:
                if n.kind == "agent":
                    e = {"source": f"{src.id}.{n.id}", "target": f"{dst.id}.{dst.spec.start}",
                         "condition": {"variable": "intent", "operator": "equals", "value": h.intent},
                         "context": h.carry, "policySource": h.source, "handoff": True}
                    if dst.id in returns:
                        e["setVariables"] = {"returnTo": f"{src.id}.{n.id}"}
                    edges.append(e)
    for i, e in enumerate(edges, 1):
        e["id"] = f"e{i}"
    return {
        "$comment": "Multi-agent topology as one Freya workflow. Node types as in freya_workflow.json; "
                    "the write schema is not public, so this is a mapping, not a verified payload.",
        "name": t.name,
        "agents": [{"id": a.id, "role": a.role, "policySource": a.source} for a in t.agents],
        "variables": list(variables.values()),
        "nodes": nodes,
        "edges": edges,
    }


def write_topology(t, out: str | Path, personas, k: int = 3) -> list[Path]:
    out = Path(out)
    written = []
    for a in t.agents:
        if a.id == t.entry:
            continue  # the entry agent's files are the root files
        written += write_all(a.spec, out / "agents" / a.id, k)
    core = t.agent(t.entry).spec

    def put(name: str, text: str) -> None:
        p = out / name
        p.write_text(text, encoding="utf-8")
        written.append(p)

    put("topology.json", json.dumps(t.to_dict(), ensure_ascii=False, indent=2) + "\n")
    put("topology.md", f"# Topology: {t.name}\n\n```mermaid\n{t.mermaid()}\n```\n")
    put("freya_multiagent_workflow.json", json.dumps(freya_multiagent_workflow(t), ensure_ascii=False, indent=2) + "\n")
    tmp = core.clone()
    tmp.personas = list(personas)
    put("freya_personas.json", json.dumps(freya_personas(tmp), ensure_ascii=False, indent=2) + "\n")
    put("freya_simulation.json", json.dumps(freya_simulation(tmp, k), ensure_ascii=False, indent=2) + "\n")
    return written
