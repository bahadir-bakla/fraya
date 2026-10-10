"""Claude backends for the three model-driven roles: extractor, agent, caller.

Offline the forge runs on deterministic stand-ins (``RuleExtractor``,
``NaiveAgentModel``, ``ScriptedCaller``) so the loop is testable without a
key. With ``ANTHROPIC_API_KEY`` (or an ``ant auth login`` profile) these
classes take the same places:

* ``ClaudeExtractor`` refines the rule-based draft against the full SOP text
  and returns a spec in the same JSON shape. It is validated with
  ``spec.validate`` and re-asked with the errors (up to ``retries`` times).
  ``disagreements()`` lists clauses where the two extractors cite different
  artifacts: the human review list.
* ``ClaudeAgentModel`` speaks each turn from the node prompt plus the
  runtime's step guidance, and extracts slot values.
* ``ClaudeCaller`` plays a persona from what the agent actually said.
* ``ClaudeExamCompiler`` writes tests from the SOP clauses alone (it is
  never shown the agent spec), merged with the rule-based exam.
* ``ClaudePerception`` answers the two closed perception questions
  (which allowed situation is the caller in; yes / no / correction at a
  read-back), scored on the exam's paraphrase set before it is trusted.

Requests use ``MODEL`` with server-side refusal fallbacks enabled.
None of this has been run against the live API from this repository yet.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from .emit import node_prompt
from .exam import Exam
from .ltl import Formula
from .runtime import TurnContext
from .simulate import EAR, Backends
from .slots import parse_slot
from .spec import AgentSpec, Persona, errors_only, validate

MODEL = "claude-opus-5-5"


class Claude:
    """One text-in, text-out call to Claude, through whichever route this machine has.

    * ``sdk``: the Anthropic Python SDK with ``ANTHROPIC_API_KEY`` (or an ``ant auth login`` profile),
    * ``cli``: the Claude Code CLI in headless mode (``claude -p``), using the CLI's own sign-in. No separate
      API key is needed wherever Claude Code is signed in, which includes Claude Code's cloud containers.

    Answers are cached on disk by (model, system, messages), so a repair loop that asks the same perception
    question twice pays once, and a re-run reproduces the earlier answers. ``AGENT_FORGE_CACHE`` moves the cache;
    ``AGENT_FORGE_CLAUDE=sdk|cli`` forces a route.
    """

    def __init__(self, model: str = MODEL, effort: str = "low", route: str | None = None):
        self.model = model
        self.effort = effort
        self.route = route or os.environ.get("AGENT_FORGE_CLAUDE") or self._pick()
        if self.route == "sdk":
            import anthropic  # optional dependency

            self.client = anthropic.Anthropic()
        self.cache = Path(os.environ.get("AGENT_FORGE_CACHE", Path.home() / ".cache" / "agent_forge" / "llm"))
        self.calls = 0

    @staticmethod
    def _pick() -> str:
        try:
            import anthropic  # noqa: F401

            if os.environ.get("ANTHROPIC_API_KEY"):
                return "sdk"
        except ImportError:
            pass
        if shutil.which("claude"):
            return "cli"
        raise RuntimeError("no Claude route: install `anthropic` and set ANTHROPIC_API_KEY, or sign in to Claude Code")

    def text(self, system: str, messages: list[dict], max_tokens: int = 2000, effort: str | None = None) -> str:
        effort = effort or self.effort
        key = hashlib.sha256(json.dumps([self.model, effort, system, messages], ensure_ascii=False).encode()).hexdigest()
        hit = self.cache / f"{key}.txt"
        if hit.exists():
            return hit.read_text(encoding="utf-8")
        out = self._sdk(system, messages, max_tokens, effort) if self.route == "sdk" else self._cli(system, messages, effort)
        self.calls += 1
        self.cache.mkdir(parents=True, exist_ok=True)
        tmp = hit.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(out, encoding="utf-8")
        os.replace(tmp, hit)  # calls run in parallel threads: never let one read a half-written answer
        return out

    def _sdk(self, system: str, messages: list[dict], max_tokens: int, effort: str) -> str:
        resp = self.client.beta.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            output_config={"effort": effort},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"model declined: {getattr(resp, 'stop_details', None)}")
        return "".join(b.text for b in resp.content if b.type == "text").strip()

    def _cli(self, system: str, messages: list[dict], effort: str) -> str:
        # The CLI takes one prompt: a multi-turn conversation is rendered as a transcript to continue.
        if len(messages) == 1:
            prompt = messages[0]["content"]
        else:
            turns = "\n".join(f"{'USER' if m['role'] == 'user' else 'YOU'}: {m['content']}" for m in messages)
            prompt = f"<conversation>\n{turns}\n</conversation>\nWrite only your next reply to the last USER turn."
        cmd = ["claude", "-p", "--no-session-persistence", "--tools", "", "--strict-mcp-config", "--setting-sources", "",
               "--model", self.model, "--effort", effort, "--system-prompt", system, "--output-format", "json", prompt]
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_SESSION_ID"}
        last = ""
        for attempt in range(3):
            try:
                # A full SOP at high effort can take many minutes through the CLI.
                p = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=tempfile.gettempdir(),
                                   timeout=int(os.environ.get("AGENT_FORGE_CLI_TIMEOUT", "1800")))
            except subprocess.TimeoutExpired:
                last = "timed out"
                continue
            try:
                d = json.loads(p.stdout)
            except json.JSONDecodeError:
                last = (p.stderr or p.stdout)[-300:]
                time.sleep(2 ** attempt)
                continue
            if not d.get("is_error"):
                return (d.get("result") or "").strip()
            last = str(d.get("result"))[:300]
            time.sleep(2 ** attempt)
        raise RuntimeError(f"claude CLI failed: {last}")


def _json_block(text: str) -> Any:
    """The JSON in a reply: a fenced block, the whole reply, or the last JSON value in it."""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        return json.loads(m.group(1))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        dec = json.JSONDecoder()
        for i in sorted((i for i, ch in enumerate(text) if ch in "[{"), reverse=True):
            try:
                return dec.raw_decode(text[i:])[0]
            except json.JSONDecodeError:
                continue
        raise


class ClaudeExtractor:
    SYSTEM = (
        "You turn a call-center SOP into an AgentSpec JSON for a voice agent. You are given the SOP clauses and a "
        "draft spec from a rule-based extractor. Return the corrected, complete spec as one JSON object in a "
        "```json block, same schema as the draft. Rules: every node, instruction, edge, slot, tool, constraint, "
        "and guard rule cites the clause ids it implements in `source` (guard rules: start `source` with "
        "'§<id>'). Keep the draft's ids where they are right. Add what the draft missed; remove what the SOP does "
        "not say. Keep constraint clauses as guard rules and tool constraints; do not wire them into the "
        "graph unless the clause is itself a procedure step. Edge `when` values: always, slots_filled, "
        "tool_failed, confirmed, rejected, event:<name>, intent:<name>, attempts>=<n>. Leave `personas` empty: the "
        "tests are written by a separate exam compiler that never sees this spec."
    )

    def __init__(self, claude: Claude | None = None, retries: int = 2):
        self.claude = claude or Claude(effort="high")
        self.retries = retries

    def refine(self, draft: AgentSpec, sop_text: str) -> AgentSpec:
        messages = [{"role": "user", "content": f"SOP:\n\n{sop_text}\n\nDraft spec:\n```json\n{draft.to_json()}\n```"}]
        last_err = ""
        for _ in range(self.retries + 1):
            out = self.claude.text(self.SYSTEM, messages, max_tokens=32000)
            try:
                d = _json_block(out)
                d["personas"] = []  # the agent compiler writes no tests (exam.py does); ignore any it returns
                spec = AgentSpec.from_dict(d)
                errs = errors_only(validate(spec))
            except Exception as exc:  # noqa: BLE001 - any parse/shape problem goes back to the model
                errs, spec = [f"could not load the spec: {exc}"], None
            if spec and not errs:
                return spec
            last_err = "\n".join(errs)
            messages += [{"role": "assistant", "content": out},
                         {"role": "user", "content": f"The spec has problems; fix them and return the full JSON:\n{last_err}"}]
        raise ValueError(f"extractor did not produce a valid spec: {last_err}")


def disagreements(a: AgentSpec, b: AgentSpec) -> list[dict]:
    """Clauses where two specs implement different things: what a human should review."""
    ca, cb = a.citations(), b.citations()
    out = []
    for c in a.clauses:
        x, y = sorted(ca.get(c["id"], [])), sorted(cb.get(c["id"], []))
        if x != y:
            out.append({"clause": c["id"], "only_rule": sorted(set(x) - set(y)), "only_llm": sorted(set(y) - set(x))})
    return out


class ClaudeGuardJudge:
    """Judges a drafted reply against the blocking rules that apply now. It can only name rules it was shown."""

    name = "claude"

    def __init__(self, claude: Claude | None = None):
        self.claude = claude or Claude(effort="low")

    def check(self, reply: str, rules, lang: str) -> tuple[list[str], str]:
        listing = "\n".join(f"- {r.id} ({r.kind}): {r.description}. Clause: {r.source}" for r in rules)
        out = self.claude.text(
            "You are the compliance check that runs before a call-center voice agent's reply is spoken. Decide "
            "whether the reply breaks any of the listed rules. Paraphrases and amounts in words count (a hint at "
            "court action is a threat; 'twelve thousand' is an amount). A reply that refuses or denies the "
            "forbidden thing does not break it. Reply with JSON {\"violates\": [rule ids], \"why\": \"<one line>\"}; "
            "an empty list when it breaks none.",
            [{"role": "user", "content": f"Rules in force now:\n{listing}\n\nReply ({lang}): {reply}"}],
            max_tokens=120)
        try:
            d = _json_block(out)
            ids = [x for x in d.get("violates", []) if isinstance(x, str)]
            return ids, str(d.get("why", ""))
        except (ValueError, AttributeError):
            return [], ""


    def check_many(self, sentences: list[str], rules, lang: str) -> list[list[str]]:
        """Judge many sentences in one call (the builder's templates, at build time)."""
        listing = "\n".join(f"- {r.id} ({r.kind}): {r.description}. Clause: {r.source}" for r in rules)
        numbered = "\n".join(f"{i}. {x}" for i, x in enumerate(sentences))
        out = self.claude.text(
            "You are the compliance check for a call-center voice agent. For each numbered sentence the agent may "
            "say, decide whether it breaks any listed rule (paraphrases and amounts in words count; a sentence "
            "that refuses or denies the forbidden thing does not break it). Reply with JSON "
            '{"violations": {"<number>": [rule ids]}}, listing only sentences that break a rule.',
            [{"role": "user", "content": f"Rules:\n{listing}\n\nSentences ({lang}):\n{numbered}"}],
            max_tokens=2000)
        try:
            d = _json_block(out).get("violations", {}) or {}
            return [[x for x in d.get(str(i), []) if isinstance(x, str)] for i in range(len(sentences))]
        except (ValueError, AttributeError):
            return [self.check(x, rules, lang)[0] for x in sentences]


def make_guard_judge(claude: "Claude | None" = None):
    """The guard's second opinion under --llm (AGENT_FORGE_GUARD=lexical turns it off)."""
    from .judge import CascadeGuard

    if os.environ.get("AGENT_FORGE_GUARD", "cascade") == "lexical":
        return None
    return CascadeGuard(ClaudeGuardJudge(claude or Claude(effort="low")))


def make_perception(claude: "Claude | None" = None):
    """Perception under --llm: rules first, Claude where they are unsure (AGENT_FORGE_PERCEPTION=claude asks
    Claude every turn, =rules never)."""
    from .perceive import CascadePerception, RulePerception

    mode = os.environ.get("AGENT_FORGE_PERCEPTION", "cascade")
    if mode == "rules":
        return RulePerception()
    slow = ClaudePerception(claude or Claude(effort="low"))
    return slow if mode == "claude" else CascadePerception(RulePerception(), slow)


class ClaudeAgentModel:
    """One instance per call: ``history`` is that call's conversation. Use ``claude_backends()``, which makes a
    fresh one for every simulated call, rather than sharing an instance."""

    name = "claude"

    def __init__(self, claude: Claude | None = None):
        self.claude = claude or Claude()
        self.perception = make_perception(self.claude)
        self.guard_judge = make_guard_judge(self.claude)
        # The API wants the conversation to open and end on a user turn; the agent speaks first on a call.
        self.history: list[dict] = [{"role": "user", "content": "(call connected)"}]

    def respond(self, ctx: TurnContext) -> str:
        system = node_prompt(ctx.spec, ctx.node) + (
            f"\n## Workflow state\n{ctx.guidance}\n\nThis turn the workflow needs you to convey, in order: "
            + " | ".join(ctx.plan) + "\nReply with only what you say aloud."
        )
        if ctx.user_text:
            self.history.append({"role": "user", "content": ctx.user_text})
        elif self.history[-1]["role"] == "assistant":
            self.history.append({"role": "user", "content": "(caller is waiting)"})
        text = self.claude.text(system, list(self.history), max_tokens=400)
        self.history.append({"role": "assistant", "content": text})
        return text

    def extract(self, spec: AgentSpec, slot: str, text: str) -> Any:
        s = spec.slot(slot)
        out = self.claude.text(
            "Extract one value from a caller's spoken words. If the caller corrected themselves, use the corrected "
            "value. Reply with only the value as digits or DD.MM[.YYYY], or NONE.",
            [{"role": "user", "content": f"Slot `{s.name}` ({s.kind}). Caller said: {text}"}], max_tokens=50)
        return None if "NONE" in out.upper() else parse_slot(s.kind, out)


class ClaudeCaller:
    """Plays the persona from the spoken transcript only; it never reads the runtime's state."""

    def __init__(self, spec: AgentSpec, persona: Persona, run: int = 0, claude: Claude | None = None):
        self.spec, self.p, self.run = spec, persona, run
        self.claude = claude or Claude()

    def say(self, rt) -> str:
        transcript = [m for m in rt.guard.transcript if m.get("role") in ("agent", "user")]
        msgs = [{"role": "user" if m["role"] == "agent" else "assistant", "content": m["text"] or "..."} for m in transcript]
        facts = {k[4:]: v for k, v in self.spec.facts.items() if k.startswith("crm_")}
        system = (f"You are a caller on a phone call with a bank's voice agent. Persona: {self.p.goal}. "
                  f"Behaviour: {json.dumps(self.p.behaviour, ensure_ascii=False)}. Your details: {facts}. "
                  f"Language: {self.spec.language}. Reply with one short spoken line.")
        if not msgs or msgs[-1]["role"] == "assistant":
            msgs.append({"role": "user", "content": "(silence)"})
        return self.claude.text(system, msgs, max_tokens=200)


def claude_backends(claude: Claude | None = None) -> Backends:
    """Claude on both sides of every simulated call, one client, a fresh agent and caller per call."""
    claude = claude or Claude()
    return Backends(agent=lambda: ClaudeAgentModel(claude),
                    caller=lambda spec, persona, run: ClaudeCaller(spec, persona, run, claude))


class ClaudePerception:
    """Closed-set perception: Claude may only pick among the labels the workflow already has."""

    name = "claude"

    def __init__(self, claude: Claude | None = None):
        self.claude = claude or Claude()

    def intents(self, text: str, options: dict[str, list[str]], lang: str = "tr") -> list[str]:
        if not options:
            return []
        labels = "\n".join(f"- {k}: e.g. {', '.join(v[:4])}" for k, v in options.items())
        out = self.claude.text(
            "You classify one caller utterance on a call-center phone call. Choose which of the listed situations "
            "the caller is in. Negations matter: 'I don't dispute it' is not a dispute. Reply with a JSON list of "
            "labels from the list, [] if none applies or you are unsure.",
            [{"role": "user", "content": f"Situations:\n{labels}\n\nCaller ({lang}): {text}"}], max_tokens=60)
        try:
            got = _json_block(out)
        except ValueError:
            return []
        return [x for x in got if x in options] if isinstance(got, list) else []

    def confirm(self, text: str, current: float | None = None,
                current_date: str | None = None) -> tuple[str | None, float | str | None]:
        out = self.claude.text(
            "The agent read a payment amount and date back to the caller and asked if they are right. Classify the "
            'caller\'s answer. Reply with JSON {"verdict": "yes"|"no"|"correction"|"unclear", "amount": <corrected '
            'amount or null>, "date": <corrected date as DD.MM or null>}. A yes that names a different amount or a '
            "different date is a correction.",
            [{"role": "user", "content": f"Read back: amount {current}, date {current_date or 'not read back'}. "
                                         f"Caller: {text}"}], max_tokens=80)
        try:
            d = _json_block(out)
            v = d.get("verdict")
            v = v if v in ("yes", "no", "correction") else None
            amount, date = d.get("amount"), d.get("date")
            if v == "correction" and isinstance(amount, (int, float)) and (current is None
                                                                            or abs(amount - float(current)) > 0.5):
                return v, float(amount)
            if v == "correction" and isinstance(date, str) and re.fullmatch(r"\d{2}\.\d{2}(\.\d{4})?", date):
                return v, date
            return v, amount if isinstance(amount, (int, float)) else None
        except (ValueError, AttributeError):
            return None, None


_BEHAVIOUR_KEYS = {"first_line", "interject", "amount_lines", "variants", "variant_of", "answers", "dob", "id_last4",
                   "unknown_slots", "lang", "declines"}
_EXPECT_KEYS = {"end", "tools", "no_tools", "max_tool_calls", "no_repeat", "scope", "branch"}


def _expect_shape(exp: dict) -> str:
    """Coerce the shapes a model gets slightly wrong; name what cannot be read."""
    if isinstance(exp.get("tools"), list):
        exp["tools"] = {str(t): {} for t in exp["tools"]}
    if isinstance(exp.get("no_tools"), str):
        exp["no_tools"] = [exp["no_tools"]]
    if not isinstance(exp.get("tools", {}), dict) or not all(isinstance(v, dict) for v in exp.get("tools", {}).values()):
        return "expect.tools must be {<tool>: {<arg>: <value>}}"
    if not isinstance(exp.get("no_tools", []), list) or not all(isinstance(t, str) for t in exp.get("no_tools", [])):
        return "expect.no_tools must be a list of tool names"
    m = exp.get("max_tool_calls", {})
    if not isinstance(m, dict) or not all(isinstance(v, int) for v in m.values()):
        return "expect.max_tool_calls must be {<tool>: <int>}"
    if exp.get("end") not in (None, "end", "transfer"):
        return "expect.end must be end or transfer"
    return ""


class ClaudeExamCompiler:
    """Writes tests from the clauses only. It never receives the agent spec."""

    SYSTEM = (
        "You write the acceptance exam for a call-center voice agent, from the SOP clauses alone. For every "
        "binding clause, write at least one test. Return one JSON object in a ```json block: "
        '{"tests": [{"clause": "<id>", "caller": {"id", "goal", "behaviour", "expect"} or null, '
        '"order": [{"kind": "once|since|never", "a": "call:<tool>", "b": "event:<e>|confirmed:<tool>|tool:<tool>"}], '
        '"perception": [{"task": "route", "text": "<what a caller says>", "label": "<situation id or none>"}]}]}. '
        "behaviour keys: first_line, interject {at, text}, amount_lines, variants (paraphrases of the scenario line), "
        "variant_of, answers {<question>: <reply>}, declines [<check tool that comes back negative>]. `at` and answer keys are what the caller hears asked: "
        + ", ".join(n for n, _ in EAR) + ". expect keys: end (end|transfer), tools {<tool>: {<arg>: <value>}}, "
        "no_tools, max_tool_calls, no_repeat, scope ('topology' when a specialist must handle it). For situations "
        "the caller must be routed on, give paraphrases and hard negatives (negated or near-miss phrasings, label none)."
    )

    def __init__(self, claude: Claude | None = None, retries: int = 2):
        self.claude = claude or Claude(effort="high")
        self.retries = retries

    def compile(self, title: str, clauses, lang: str) -> Exam:
        ids = {c.id for c in clauses}
        listing = "\n".join(f"§{c.id} [{c.strength}] {c.text}" for c in clauses)
        messages = [{"role": "user", "content": f"SOP: {title}\nLanguage: {lang}\n\n{listing}"}]
        errs: list[str] = []
        for _ in range(self.retries + 1):
            out = self.claude.text(self.SYSTEM, messages, max_tokens=16000)
            try:
                exam, errs = self._load(out, title, clauses, ids, lang)
            except Exception as exc:  # noqa: BLE001 - any shape problem goes back to the model
                exam, errs = None, [f"could not read the exam: {exc}"]
            if exam and not errs:
                return exam
            messages += [{"role": "assistant", "content": out},
                         {"role": "user", "content": "Fix these problems and return the full JSON:\n" + "\n".join(errs)}]
        raise ValueError("exam compiler did not produce a valid exam: " + "; ".join(errs))

    @staticmethod
    def _load(out: str, title: str, clauses, ids: set[str], lang: str) -> tuple[Exam, list[str]]:
        d = _json_block(out)
        errs: list[str] = []
        ex = Exam(title, lang, [{"id": c.id, "text": c.text, "strength": c.strength} for c in clauses])
        for t in d.get("tests", []):
            c = str(t.get("clause", "")).lstrip("§")
            if c not in ids:
                errs.append(f"unknown clause {c}")
                continue
            p = t.get("caller")
            if p:
                bad = set(p.get("behaviour", {})) - _BEHAVIOUR_KEYS | set(p.get("expect", {})) - _EXPECT_KEYS
                shape = _expect_shape(p.setdefault("expect", {}))
                if bad:
                    errs.append(f"§{c} caller {p.get('id')}: unknown keys {sorted(bad)}")
                elif shape:
                    errs.append(f"§{c} caller {p.get('id')}: {shape}")
                else:
                    ex.personas.append(Persona(f"llm_{p['id']}", p.get("goal", ""), {"lang": lang, **p.get("behaviour", {})},
                                               p.get("expect", {}), [c]))
            for o in t.get("order", []) or []:
                if o.get("kind") in ("once", "since", "never") and str(o.get("a", "")).startswith("call:"):
                    ex.formulas.append(Formula(o["kind"], o["a"], o["b"], [c]))
            for x in t.get("perception", []) or []:
                if x.get("text") and x.get("label"):
                    ex.perception.append({"task": x.get("task", "route"), "text": x["text"], "label": x["label"],
                                          "source": [c]})
        return ex, errs
