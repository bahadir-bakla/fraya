"""Execute an AgentSpec as a live voice agent: workflow state machine + speaker + guard.

Responsibilities are split the way a production stack splits them:

* ``WorkflowRuntime`` owns the graph: current node, slots, events, attempts,
  tool calls and their pre-call argument checks. It decides *what* this turn
  must accomplish (a plan).
* An ``AgentModel`` turns the plan into words. ``NaiveAgentModel`` is an
  offline stand-in that reproduces failure classes reported for voice agents
  (see its docstring); ``llm.ClaudeAgentModel`` is the real thing.
* ``voice_contract.StreamGuard`` sits between the speaker and TTS and blocks
  what must not be spoken.

The runtime also implements PolicyGuide's "guide, don't only block" idea:
``guidance()`` gives the speaker a step-specific instruction derived from the
graph state (which node, which slot is missing, which event has not happened),
and a blocked tool call comes back as a concrete correction rather than a
silent refusal.
"""

from __future__ import annotations

import copy

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from voice_contract.contract import Contract, compile_policy, normalize
from voice_contract.guard import Decision, StreamGuard, Violation

from .extract import LANG
from .slots import fold, parse_slot
from .spec import AgentSpec, Node, Tool, guard_policy


def fmt_amount(v: float, lang: str) -> str:
    n = int(round(v))
    s = f"{n:,}"
    return s.replace(",", ".") if lang == "tr" else s


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    ok: bool
    reason: str = ""
    blocked: bool = False  # stopped by a pre-call constraint, never reached the backend


@dataclass
class Signal:
    """Something the repair loop can act on."""

    kind: str  # guard_block | guard_handoff | tool_blocked | loop | timeout | unhandled_intent
    node: str
    rule: str = ""
    detail: str = ""


@dataclass
class State:
    node: str
    slots: dict[str, Any] = field(default_factory=dict)
    events: set[str] = field(default_factory=set)
    attempts: dict[str, int] = field(default_factory=dict)
    visits: dict[str, int] = field(default_factory=dict)
    unheard: dict[str, int] = field(default_factory=dict)  # turns a node's question went unanswered
    awaiting: list[str] = field(default_factory=list)  # slot names asked this turn, or ["confirm:<tool>"]
    done: str | None = None  # end | transfer | guard_handoff | timeout
    tool_calls: list[ToolCall] = field(default_factory=list)
    path: list[str] = field(default_factory=list)
    last_tool_failed: bool = False
    trace: list[str] = field(default_factory=list)  # call:/tool:/event:/confirmed: atoms, for ltl.py


@dataclass
class TurnContext:
    spec: AgentSpec
    node: Node
    state: State
    plan: list[str]  # what the workflow wants said this turn, in order
    user_text: str
    intents: list[str]
    guidance: str
    instruction_tags: set[str]


class AgentModel(Protocol):
    name: str

    def respond(self, ctx: TurnContext) -> str: ...

    def extract(self, spec: AgentSpec, slot: str, text: str) -> Any: ...

    # Optional: ``perception`` (perceive.RulePerception or llm.ClaudePerception); rules when absent.


class NaiveAgentModel:
    """Offline speaker that fails the way voice agents are reported to fail.

    It follows the plan, but, like a helpful LLM without explicit
    instructions, it:

    * answers a direct question about account data it can see, even before
      identity is verified (rule-compliance failures, tau2-bench / tau-Voice),
    * reads a number back when asked to (sycophancy; PII leak),
    * answers "what happens if I don't pay" with a threat, and "can you
      guarantee" with a guarantee,
    * takes the first number it hears ("three thousand, sorry, five thousand"
      -> 3000; self-correction failures, Full-Duplex-Bench v3).

    Each behaviour switches off when the node or global instructions carry
    the matching tag, which is how a prompt patch from the repair loop takes
    effect offline. With a real model the instruction text does that job.
    """

    name = "naive-offline"

    def extract(self, spec: AgentSpec, slot: str, text: str) -> Any:
        return parse_slot(spec.slot(slot).kind, text, strategy="first")

    def respond(self, ctx: TurnContext) -> str:
        L = LANG[ctx.spec.language]
        tags = ctx.instruction_tags
        lead: list[str] = []
        tr = ctx.spec.language == "tr"
        if "ask_info" in ctx.intents and "identity_verified" not in ctx.state.events:
            if "gate:identity_verified" in tags:
                lead.append(L["gate_fallback"])
            else:
                lead.append(L["inform"].format(**_fill(ctx.spec, ctx.state)))
        if "ask_readback" in ctx.intents:
            digits = re.findall(r"\d[\d ]{10,}\d", ctx.user_text)
            if "no_readback" in tags:
                lead.append(L["pii_fallback"])
            elif digits:
                lead.append(("Tabii, numaranız " if tr else "Sure, your number is ") + digits[0] + ".")
        if "ask_consequence" in ctx.intents:
            lead.append(("Size bir tehditte bulunmam söz konusu değil; birlikte bir ödeme planı bulalım." if tr
                         else "I won't threaten you; let's find a payment plan together.") if "no_threat" in tags else
                        ("Ödemezseniz haciz yapılacak, polis de devreye girebilir." if tr
                         else "If you don't pay, we may involve the police and you could be arrested."))
        if "ask_guarantee" in ctx.intents:
            lead.append(("Bu konuda size bir söz veremem; ödeme planınıza birlikte bakalım." if tr
                         else "I can't promise any waiver or discount.") if "no_guarantee" in tags else
                        ("Faiziniz kesinlikle silinecek, garanti ediyorum." if tr
                         else "I guarantee we will waive the fees and give you a discount."))
        return " ".join(lead + [p for p in ctx.plan if p]).strip()


def _fill(spec: AgentSpec, st: State) -> dict[str, Any]:
    d: dict[str, Any] = {k: v for k, v in spec.facts.items()}
    d.update(st.slots)
    amounts = {"overdue"} | {s.name for s in spec.slots if s.kind == "amount"}
    for k in amounts:
        if isinstance(d.get(k), (int, float)):
            d[k] = fmt_amount(d[k], spec.language)
    d.setdefault("amount", "")
    d.setdefault("pay_date", "")
    return d


def detect_intents(spec: AgentSpec, text: str, perception=None) -> list[str]:
    from .perceive import RulePerception

    return (perception or RulePerception()).intents(text, {it.name: it.patterns for it in spec.intents}, spec.language)


_CMP = {">": lambda a, b: a > b, "<": lambda a, b: a < b, ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b}

# Lines the runtime itself says (the guard judges them once at build time with the builder's other sentences).
RUNTIME_LINES = {
    "tr": {"minimum": "Ödeme sözü en az {b} TL olmalı.",
           "below_minimum": "Bu tutarı kaydedemiyorum; ödeme sözü en az {b} TL olmalı."},
    "en": {"minimum": "A promise needs to be at least {b} dollars.",
           "below_minimum": "I can't record that; a promise must be at least {b} dollars."},
}


def mock_tools(spec: AgentSpec, declines: frozenset[str] = frozenset()):
    """Backend stand-ins: identity check against CRM facts, promise store. ``declines``: checks that come back
    negative in this call (a simulated caller's world, e.g. the manager says no)."""

    def run(tool: Tool, args: dict[str, Any]) -> tuple[bool, str]:
        if tool.name in declines:
            return False, "declined"
        if tool.sets_event == "identity_verified":
            want = {k: spec.facts.get(f"crm_{k}") for k in tool.args}
            got = {k: args.get(k) for k in tool.args}
            dob_ok = "dob" not in want or str(got.get("dob", ""))[:5] == str(want["dob"])[:5]
            last_ok = "id_last4" not in want or str(got.get("id_last4")) == str(want["id_last4"])
            return (dob_ok and last_ok), ("" if dob_ok and last_ok else "identity mismatch")
        return True, ""

    return run


class WorkflowRuntime:
    def __init__(self, spec: AgentSpec, model: AgentModel, guard_contract: Contract | None = None, tools=None,
                 guard: StreamGuard | None = None, seed: dict | None = None, declines: frozenset[str] = frozenset()):
        self.spec = spec
        self.model = model
        self.L = LANG[spec.language]
        # One call has one guard: agents that take over a call (orchestrate.py) share it.
        self.guard = guard or StreamGuard(guard_contract or compile_policy(guard_policy(spec)))
        self.tools = tools or mock_tools(spec, declines)
        self.st = State(spec.start)
        if seed:  # context carried in a handoff envelope
            self.st.slots.update(seed.get("slots", {}))
            self.st.events |= set(seed.get("events", ()))
            self.st.trace += [f"event:{e}" for e in seed.get("events", ())]
        self.signals: list[Signal] = []
        self.guard_events: list[dict] = []
        from .perceive import RulePerception

        self.perception = getattr(model, "perception", None) or RulePerception()
        self.judge = getattr(model, "guard_judge", None)  # judge.CascadeGuard: a semantic second opinion

    # -- public API -----------------------------------------------------------

    @property
    def tool_calls(self) -> list[ToolCall]:
        return self.st.tool_calls

    @property
    def trace(self) -> list[str]:
        return self.st.trace

    def open(self) -> str:
        plan = self._enter(self.spec.start)
        return self._speak(plan, "", [])

    def resume(self, lead: str = "") -> str:
        """Pick the call up where this agent left it (after a specialist handed it back): ask again what was open."""
        st = self.st
        if st.awaiting and st.awaiting[0].startswith("confirm:"):
            plan = self._confirm_plan(self.spec.tool(st.awaiting[0][8:]))
        elif st.awaiting:
            plan = [self.spec.slot(st.awaiting[0]).ask]
        else:
            plan = self._enter(st.node)
        return self._speak(([lead] if lead else []) + plan, "", [])

    def on_user(self, text: str) -> str:
        st = self.st
        if st.done:
            return ""
        intents = detect_intents(self.spec, text, self.perception)
        decision = self.guard.on_user(text)
        plan: list[str] = []
        routed = False
        for e in self.spec.global_edges:
            if e.when.startswith("intent:") and e.when[7:] in intents:
                plan = self._enter(e.to)
                routed = True
                break
        if not routed:
            # A route out of the current node only ("the right person came to the phone" in the third-party branch).
            e = next((e for e in self.spec.node(st.node).edges
                      if e.when.startswith("intent:") and e.when[7:] in intents), None)
            if e:
                st.awaiting = []
                plan = self._enter(e.to)
                routed = True
        if not routed and decision.handoff:
            # The workflow had no route for this; only the guard stopped the bot.
            self.signals.append(Signal("guard_handoff", st.node, _rule_for(self.guard, decision), text[:60]))
            st.done = "guard_handoff"
            return ""
        if not routed:
            for it in intents:
                if not any(e.when == f"intent:{it}" for e in self.spec.global_edges) and it in ("escalate",):
                    self.signals.append(Signal("unhandled_intent", st.node, it))
            plan = self._step(text)
        # A transfer the workflow routed itself is announced with its canned line; the guard has
        # already flagged the same handoff and would otherwise silence the announcement.
        return self._speak(plan, text, intents, guarded=not (routed and st.done == "transfer"))

    # -- workflow -------------------------------------------------------------

    def _enter(self, nid: str) -> list[str]:
        st = self.st
        node = self.spec.node(nid)
        st.node = nid
        st.visits[nid] = st.visits.get(nid, 0) + 1
        st.path.append(nid)
        if st.visits[nid] > 6:
            self.signals.append(Signal("loop", nid, detail=f"entered {st.visits[nid]} times"))
        plan = [self._render(node.say)] if node.say else []
        if node.kind == "transfer":
            st.done = "transfer"
            return plan
        if node.kind == "end":
            st.done = "end"
            return plan
        if node.tool and self.spec.tool(node.tool).sets_event in st.events:
            # Already done earlier in the call (e.g. identity verified before a handoff): don't ask again.
            return plan + self._follow(node)
        plan += self._node_preamble(node)
        missing = [s for s in node.collects if s not in st.slots]
        if missing:
            st.awaiting = [missing[0]]
            plan.append(self.spec.slot(missing[0]).ask)
            return plan
        if node.tool:
            return plan + self._call(node)
        return plan + self._follow(node)

    def _node_preamble(self, node: Node) -> list[str]:
        tags = {i.tag for i in node.instructions}
        if "min_amount" in tags and node.tool:
            c = next((c for c in self.spec.tool(node.tool).constraints if c.arg == "amount"), None)
            if c:
                b = fmt_amount(c.bound(self.spec.facts), self.spec.language)
                return [RUNTIME_LINES[self.spec.language]["minimum"].format(b=b)]
        return []

    def _step(self, text: str) -> list[str]:
        st = self.st
        node = self.spec.node(st.node)
        if st.awaiting and st.awaiting[0].startswith("confirm:"):
            tool = self.spec.tool(st.awaiting[0][8:])
            amount = next((a for a in tool.args if self.spec.slot(a).confirm and self.spec.slot(a).kind == "amount"), None)
            date = next((a for a in tool.args if self.spec.slot(a).confirm and self.spec.slot(a).kind == "date"), None)
            verdict, value = self.perception.confirm(text, st.slots.get(amount) if amount else None,
                                                     st.slots.get(date) if date else None)
            if verdict == "yes":
                st.awaiting = []
                st.trace.append(f"confirmed:{tool.name}")
                return self._call(node, confirmed=True)
            # "No", a correction ("yes, but six thousand, not five") or unclear: take any corrected value, read back again.
            if verdict == "correction" and isinstance(value, str) and date:
                st.slots[date] = value
            elif verdict == "correction" and amount and isinstance(value, (int, float)):
                st.slots[amount] = value
            else:
                for a in tool.args:
                    v = self.model.extract(self.spec, a, text)
                    if v is not None and self.spec.slot(a).confirm:
                        st.slots[a] = v
            return self._confirm_plan(tool)
        for s in node.collects:
            # Only the slot the agent asked for: a date of birth also contains four digits.
            if s in st.slots or s not in st.awaiting:
                continue
            v = self.model.extract(self.spec, s, text)
            if v is not None:
                st.slots[s] = v
        missing = [s for s in node.collects if s not in st.slots]
        if missing:
            if st.awaiting == [missing[0]]:
                # The same question went unanswered again ("he isn't here" after the phone was handed over). Each
                # unanswered turn counts as an attempt, so the node's attempt limit ends the loop as the SOP says.
                st.unheard[node.id] = st.unheard.get(node.id, 0) + 1
                out = next((e for e in node.edges if e.when.startswith("attempts>=")
                            and st.unheard[node.id] + st.attempts.get(node.id, 0) >= int(e.when[10:])), None)
                if out:
                    st.awaiting = []
                    return self._enter(out.to)
            st.awaiting = [missing[0]]
            return [self.spec.slot(missing[0]).ask]
        if node.tool:
            return self._call(node)
        return self._follow(node)

    def _confirm_plan(self, tool: Tool) -> list[str]:
        vals = []
        for a in tool.args:
            s = self.spec.slot(a)
            if s.confirm:
                v = self.st.slots.get(a)
                vals.append(fmt_amount(v, self.spec.language) + (" TL" if self.spec.language == "tr" else " dollars")
                            if s.kind == "amount" and v is not None else str(v))
        self.st.awaiting = [f"confirm:{tool.name}"]
        return [self.L["confirm"].format(value=", ".join(vals))]

    def _call(self, node: Node, confirmed: bool = False) -> list[str]:
        st = self.st
        tool = self.spec.tool(node.tool)
        if not confirmed and any(self.spec.slot(a).confirm for a in tool.args):
            return self._confirm_plan(tool)
        args = {a: st.slots.get(a) for a in tool.args}
        missing = [t for t in node.join if f"tool:{t}" not in st.trace]
        if missing:
            # Join: the action runs only once every check it waits on has succeeded in this call.
            st.tool_calls.append(ToolCall(tool.name, args, False, f"waiting on {', '.join(missing)}", blocked=True))
            self.signals.append(Signal("join_blocked", node.id, ",".join(node.source), ", ".join(missing)))
            st.last_tool_failed = True
            return self._follow(node)
        for c in tool.constraints:
            v = args.get(c.arg)
            if v is not None and not c.ok(float(v), self.spec.facts):
                # Pre-call argument guard: the backend never sees this call.
                st.tool_calls.append(ToolCall(tool.name, args, False, f"violates {c.describe()}", blocked=True))
                self.signals.append(Signal("tool_blocked", node.id, ",".join(c.source), c.describe()))
                st.slots.pop(c.arg, None)
                st.last_tool_failed = True
                st.attempts[node.id] = st.attempts.get(node.id, 0) + 1
                b = fmt_amount(c.bound(self.spec.facts), self.spec.language)
                correction = RUNTIME_LINES[self.spec.language]["below_minimum"].format(b=b)
                return [correction] + self._follow(node)
        for a, v in args.items():
            if isinstance(v, (int, float)):
                st.trace.append(f"arg:{tool.name}.{a}={v}")  # for order rules that hold above an amount only
        st.trace.append(f"call:{tool.name}")
        ok, reason = self.tools(tool, args)
        st.tool_calls.append(ToolCall(tool.name, args, ok, reason))
        st.last_tool_failed = not ok
        if ok:
            st.trace.append(f"tool:{tool.name}")
            if tool.sets_event:
                st.trace.append(f"event:{tool.sets_event}")
                st.events.add(tool.sets_event)
                self.guard.on_event(tool.sets_event)
            st.attempts[node.id] = 0
            return self._follow(node)
        st.trace.append(f"denied:{tool.name}")  # a negative answer: what it gates must not run after it
        st.attempts[node.id] = st.attempts.get(node.id, 0) + 1
        if node.kind == "function" or any(node.tool in self.spec.node(e.to).join for e in node.edges
                                          if e.when.startswith("event:")) or reason == "declined":
            return self._follow(node)  # a check said no: not the caller's input to correct
        for a in tool.args:
            st.slots.pop(a, None)
        return [self.L["verify_failed"]] + self._follow(node)

    def _follow(self, node: Node) -> list[str]:
        st = self.st
        # Attempt bounds first, so a bounded loop exits before the retry edge fires.
        edges = sorted(node.edges, key=lambda e: 0 if e.when.startswith("attempts>=") else 1)
        for e in edges:
            if self._holds(e.when, node):
                if e.when == "tool_failed":
                    st.last_tool_failed = False
                return self._enter(e.to)
        missing = [s for s in node.collects if s not in st.slots]
        if missing:
            st.awaiting = [missing[0]]
            return [self.spec.slot(missing[0]).ask]
        return []

    def _holds(self, when: str, node: Node) -> bool:
        st = self.st
        if when == "always":
            return True
        if when == "slots_filled":
            return all(s in st.slots for s in node.collects)
        if when.startswith("event:"):
            return when[6:] in st.events
        if when == "tool_failed":
            return st.last_tool_failed
        if when.startswith("attempts>="):
            limit = int(when[10:])
            return st.attempts.get(node.id, 0) >= limit
        if when.startswith("slot:"):
            name, op, bound = re.match(r"slot:(\w+)(>=|<=|>|<)([\d.]+)", when).groups()
            v = st.slots.get(name)
            return v is not None and _CMP[op](float(v), float(bound))
        return False

    def _render(self, template: str) -> str:
        try:
            return template.format(**_fill(self.spec, self.st))
        except (KeyError, IndexError):
            return template

    # -- speaking through the guard -----------------------------------------------

    def guidance(self) -> str:
        """PolicyGuide-style step instruction from the graph state."""
        st, node = self.st, self.spec.node(self.st.node)
        parts = [f"Current step: {node.id} ({node.goal})."]
        if st.awaiting:
            parts.append(f"You are waiting for: {', '.join(st.awaiting)}.")
        pending = [r for r in self.spec.rules if r.get("kind") == "gated_topic" and r["requires_event"] not in st.events]
        for r in pending:
            parts.append(f"Do not discuss {r['description']} until {r['requires_event']}.")
        return " ".join(parts)

    def _tags(self) -> set[str]:
        node = self.spec.node(self.st.node)
        return {i.tag for i in node.instructions + self.spec.global_instructions if i.tag}

    def _speak(self, plan: list[str], user_text: str, intents: list[str], guarded: bool = True) -> str:
        node = self.spec.node(self.st.node)
        ctx = TurnContext(self.spec, node, self.st, plan, user_text, intents, self.guidance(), self._tags())
        text = self.model.respond(ctx)
        if guarded and self.judge is not None and not self.guard._handoff:
            rule, why = self.judge.review(text, self.guard.c, self.guard.events, self.spec.language)
            if rule is not None:
                # Blocked before a word was spoken: say the rule's fallback instead, logged like a lexical block.
                v = Violation(rule.id, rule.kind, "block", self.guard.agent_turns + 1, f"semantic: {why}"[:160])
                self.guard.violations.append(v)
                self._note_guard(Decision(violations=[v]))
                self.guard_events[-1]["layer"] = "semantic"
                text = rule.fallback or self.guard.c.default_fallback
            elif self.judge.cleared and self._only_blocked_by(text, set(self.judge.cleared)):
                # The word list would block a reply that only negates what it names; the judge read the whole
                # sentence and cleared it. Spoken as written, and the clearance is logged.
                for rid in self.judge.cleared:
                    self.guard_events.append({"rule": rid, "kind": "cleared", "action": "cleared", "node": self.st.node,
                                              "layer": "semantic"})
                guarded = False
        if not guarded:
            self.guard.transcript.append({"role": "agent", "text": text, "blocked": False})
            self.guard.agent_turns += 1
            return text
        out = []
        d = self.guard.start_agent_turn()
        out.append(d.release)
        words = text.split(" ")
        for i in range(0, len(words), 4):
            d = self.guard.on_agent_chunk(" ".join(words[i:i + 4]) + (" " if i + 4 < len(words) else ""))
            out.append(d.release)
            self._note_guard(d)
            if d.stop_turn:
                break
        d = self.guard.end_agent_turn()
        out.append(d.release)
        self._note_guard(d)
        return "".join(out).strip()

    def _only_blocked_by(self, text: str, cleared: set[str]) -> bool:
        """Would the stream guard block this reply for the cleared rules only? (A dry run on a copy.)"""
        g = copy.deepcopy(self.guard)
        g.start_agent_turn()
        g.on_agent_chunk(text)
        g.end_agent_turn()
        blocks = {v.rule_id for v in g.violations[len(self.guard.violations):] if v.action == "block"}
        return bool(blocks) and blocks <= cleared

    def _note_guard(self, d) -> None:
        for v in d.violations:
            self.guard_events.append({"rule": v.rule_id, "kind": v.kind, "action": v.action, "node": self.st.node})
            if v.action == "block":
                self.signals.append(Signal("guard_block", self.st.node, v.rule_id, v.detail))


def _rule_for(guard: StreamGuard, decision) -> str:
    for v in decision.violations:
        if v.action == "handoff":
            return v.rule_id
    return ""
