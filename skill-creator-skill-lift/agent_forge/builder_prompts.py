"""Builder knowledge concerns platform mechanics; policy values come from inputs."""
from __future__ import annotations
import json
import hashlib
from pathlib import Path


PROGRESS_GUIDANCE = """PLATFORM PROGRESS GUIDANCE (shared mechanics, not bank policy):
Use the supplied sources/API for every policy value, question, amount, calendar,
retry limit, queue, outcome/reason and speech obligation. The stage labels below
are architecture examples, not a fixed node count or an outcome table. Equivalent
implementations are acceptable if their actual paths preserve source obligations.

SMALL CYCLIC CAPABILITY/ACTION STAGES:
- Use a few reusable stages for identity, account/context, negotiation and
  confirmation, required actions, legal bank closure and native termination.
  Cycle for clarification, corrections, source-permitted retries and per-product
  work. Keep sensitive tools available only after their source prerequisites.
- Conversation nodes expose dialogue tools; api_request/code nodes execute
  pre_actions on entry. Do not put pre_actions on conversation nodes or dialogue
  tools on action nodes: the platform strips those misplaced fields. Where all
  request values are validated and available, a dedicated action stage can make
  a required operation unavoidable instead of hoping a closing prompt calls it.
  Bind every required engine-run body field to those values; unresolved single
  placeholders are dropped. Fresh model-argument placeholders need dialogue tools,
  not an engine-only pre_action with no model to fill them.
- A callback agreement, confirmed payment terms or a permitted transfer request
  creates an action obligation, not a completed action. Keep that action reachable
  until its source-required completion evidence arrives. Preserve partial commits.

TRUSTED PROGRESS STATE:
- Extraction records user speech: identity claims, proposed terms, corrections,
  consent and requested intent. It must NEVER write backend-success, recorded
  promise/callback/transfer, final outcome/reason, bank-close or terminal-ready
  facts. Separate candidate user intent from trusted policy-derived disposition.
- Only deterministic validation of source conditions and actual API receipts may
  derive legal terminal state. Some source outcomes require no preceding write;
  do not invent an extra required action for them. For required actions, correlate
  receipts to the current request/product/attempt and retain already recorded facts.
- Use documented response_mapping or guarded code to consume the API's actual
  application-level result. HTTP 200, a generic success counter, an extracted yes
  or a transfer announcement is not proof of the required bank action. Variables
  persist across nodes; clear/consume pending state so an old success cannot stand
  for a new action. Unknown writes and hook failures are not successful receipts.
- Errors do not authorize a different outcome or queue unless the source permits
  that path. Never claim a human transfer merely to escape a technical problem.

ROUTING THAT PRESERVES REQUIRED ACTIONS:
- Official workflow-format.md, Order of evaluation: loop_condition precedes node
  transitions, and node transitions precede global interrupts. Within transitions,
  deterministic conditions run first; a match suppresses semantic matches_intent
  evaluation regardless of where the semantic entry appears in the list. Merely
  moving semantic routes first is NOT a fix for a matching deterministic fallback.
- A broad always/is_set/self route or loop condition can starve specific intents
  and global interrupts. Prefer an exclusive user-intent enum or non-overlapping
  semantic routes with source priority. Validate intent before dispatch; an intent
  enum must not double as a terminal outcome. In dialogue, no matching route means
  stay and answer. A passthrough action/code node instead needs a safe always
  fallback and passthrough_default_transition, not an unconditional action loop.
- Duplicate target_node routes merge with OR; an always route to that target
  makes the merged route unconditional. Check the effective merged conditions.
- is_tool_call:true routes are dialogue-model transition tools, NOT routes checked
  by the router after each turn. They do not guarantee execution of a bank action.
- Routing runs before dialogue and again after a tool result. No result gate may
  eject a stage before its still-required tools run: prior identity/account success
  is a prerequisite, not completion of a later promise/callback/transfer action.
  Test completion of the whole stage, with fresh action receipts. Do not re-test
  an earlier user intent to leave an action stage before dispatch. Keep unfinished
  action tools reachable; advance only on the current stage's completion evidence.

LEGAL CLOSURE AND SPEECH:
- Derive outcome/reason with source priority from validated facts and required
  action receipts. Enforce source close-count/last-bank-tool rules. A goodbye,
  accepted terms or customer hangup cannot replace a missing callback, promise,
  transfer or bank closure. Avoid dialogue/lifecycle duplicate bank-close calls.
- Deliver required speech at the source-specified point, including before bank
  close when required. Tool success does NOT prove a goodbye or confirmation was
  spoken. Route a confirmed successful bank close to a silent native end_call node:
  on_enter silent, terminal handler __function__:end_call, message_mode default
  none, disable_inactivity_monitor true, no outgoing transitions. Do not return
  to a farewell conversation/self-loop or issue another bank call. Native hangup
  is distinct from the bank close API and does not manufacture bank ledger success.

OPTIONAL GUARD KERNEL BOUNDARY:
- @builtin:guarded_dispatch is available for explicit composition, not automatically
  integrated policy. Its caller must supply trusted source policy, validated command
  and state; persist guard_state_json on EVERY result, including blocked corrections.
  Only guard_flag == 'allowed' permits dispatch of the unchanged guard_request_json
  body. That is a reservation, not a successful bank receipt. Feed the actual bank
  result back into trusted state before advancing. Extraction must not author these
  control facts. validate_guard_wiring checks local gate shape, not trusted inputs,
  downstream request binding, interruption handling or every alternative write path.

Mechanics references: workflow-format.md (node types, variables, routing,
extraction and end-call nodes); tools-and-code.md (results, mappings and hooks).
"""


def raw_sources(contract: dict) -> list[dict]:
    result = []
    for document in contract["documents"]:
        raw = Path(document["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != document["sha256"]:
            raise ValueError("A brief changed after inventory; start a fresh build to keep source provenance consistent")
        result.append({"id": document["id"], "text": raw.decode("utf-8-sig")})
    return result


def policy_prompt(contract: dict) -> str:
    return """Compile all supplied source documents into a policy IR for a phone-agent builder.
Preserve EVERY qualified clause ID, including context and tables, once in rules.
Keep the IR terse: one short policy sentence per source, short trigger/action
phrases. Extract only operational parameters; avoid repeating prose as parameters.
Most rule policy/trigger/action phrases should be under 12 words each. Do not
classify absence of amendments, optional recovery strategies, or hypothetical
post-terminal customer statements outside the specified domain as blocking gaps.
Do not treat heuristic source strength as authoritative: an imperative without
must can still bind. Later file order alone does not establish precedence;
resolve ONLY explicit inheritance/replacements. Use qualified source IDs in
overrides, parameters and stages. Parameters contain valid serialized JSON,
including calendars, amounts, limits, outcome tables and field mappings when
present. No example customer facts may become permanent policy values. Every
operation name must come from supplied OpenAPI. Derive question order, identity
gates, disclosure limits, counting/retry semantics, confirmation, tool success,
per-product obligations, terminal priority and required spoken statements from
these inputs. Distinguish proposed, confirmed and recorded state; preserve
partial commits. For each required action and terminal outcome, identify the
source conditions and completion evidence; user intent is not bank completion.
Keep required speech separate from action success. Identify constraints over the
WHOLE conversation, including
actions forbidden before a later event. Report unresolved ambiguities rather
than inventing policy. This stage has no platform side effects.

INPUT CONTRACT:
""" + json.dumps(contract, ensure_ascii=False) + "\nRAW SOURCES:\n" + json.dumps(raw_sources(contract), ensure_ascii=False)


def workflow_prompt(contract: dict, policy: dict, kit: Path, feedback: dict | None = None) -> str:
    references = {name: (kit / "docs" / name).read_text(encoding="utf-8")
                  for name in ["workflow-format.md", "tools-and-code.md"]}
    base = json.loads((kit / "examples" / "base-agent.json").read_text(encoding="utf-8"))
    return """Generate a complete deployable Freya workflow from the supplied sources and policy IR.
Return workflow_json as the serialized workflow object, plus source coverage.
Use the official documentation for format/runtime behavior. The base agent is
only a schema illustration, NOT the solution. Implement all source rules;
do not silently omit difficult branches. Cover all qualified IDs once.
Use a compact hybrid graph: capability stages gate sensitive tool availability,
while semantic dialogue within a stage handles varied wording and interruptions.
Do not add a node for every possible sentence. Prefer shared source-derived
deterministic snippets and reusable state over duplicated long code/prompts.
Apply the shared mechanics below using only source-derived policy values.
""" + PROGRESS_GUIDANCE + """
COMPACT BUILDER IR (expanded deterministically before Freya sees it):
- Put bank tool definitions in root _tool_library, a map of your chosen reference
  IDs to {operation, defaults, descriptions, description, pre_process_code,
  post_process_code, response_mapping, config}. operation is from supplied API;
  defaults maps ONLY baked body fields to their value/placeholder; descriptions
  maps fresh model-filled body fields to guidance. Omit unused annotations.
  The compiler supplies exact URL, method, body schemas/required/enums and headers.
  It gives fresh model-filled body leaves unique unbound defaults required by
  Freya's body binder. Omit defaults for these in the compact spec; never bind them
  to extraction variables that would bake stale values on node entry.
- In node tools/pre_actions use {"_tool_ref":"your_reference_id"}. Do not output
  duplicate full api_call schemas. Separate definitions can bind different fields
  or prompts for the same supplied operation. Node-level mappings remain on nodes.
- Put shared snippets in root _code_library as name->Python string. Replace a code
  default or pre/post hook string with "@code:name". The compiler substitutes the
  actual snippet. Use snippets once, do not repeat their text for every tool/node.
- All other node/transition/code_exec/terminal fields follow the official schema.
  Macros are compiler-only and removed before deployment. Aim for compact output
  under 25,000 characters while retaining all required source behavior. Keep
  coverage mechanism phrases short; use shared prompts rather than repeating rules.
  Coverage node_ids are actual nodes/global_nodes keys, never library references.
  Each node's action list must have unique function names. Different bindings of
  one API operation belong in separate nodes, or use one operation with fresh
  model-filled arguments such as a queue constrained by the actual API enum.

PLATFORM HARDENING:
- Extraction/routing/dialogue prompts are separate. Route on actual tool results,
  never on a user's claim that a check succeeded. Availability of sensitive tools
  must be structurally gated. Keep mutable counters/state explicit.
- Bind URLs/methods/body types/required/enums from this OpenAPI, not examples.
  Fixed backend values use default. Each body field has a leaf schema/default;
  unresolved model fields use unique parameter variables to avoid stale baking.
- Success mappings begin data.; test true/True or map string states. Post hooks
  should give a clear next action on both success and negative/tool-error results.
- A tool's result variable is ACTUAL function.name + '_response', not its compact
  library reference ID. For example a reference check mapped to verify_identity
  produces verify_identity_response, never check_response. Route on that exact
  result or an explicit response_mapping variable, and never invent result keys.
- Calendar/math/counting are deterministic generated Python using source-derived
  constants, call vars['now'], and verified json/re/datetime modules. No real clock.
  Snippets use vars/config/result, no files/network, no {{ or }} anywhere in code,
  and always set safe fallback state. Money boundaries must not use lax rounding.
- A confirmation can be invalidated by correction. Recorded promises survive
  later requests, unless source says otherwise. Distinguish proposed/confirmed/
  recorded and product IDs returned by the backend. No invented IDs or contact info.
- Respect source-defined retry counts; avoid automatic write retries. Defer any
  action whose legality depends on a later terminal decision.
- Every passthrough node has an always fallback; top condition groups use OR,
  with nested AND if needed. Avoid unconditional self-loops in passthrough nodes.
- All required spoken sentences must be delivered at the source-specified point.
  A successful tool result alone does not prove required speech happened.
- No null fields. Omit agent_config; the deployer normalizes the official model.
  Only documented handlers. No external APIs beyond supplied tool URLs.
- Maintain complete per-product behavior and the source terminal priority. If
  source requires goodbye before a final backend tool, a later hangup farewell
  does not satisfy it. No extra bank API tool after the final backend close;
  the native end_call terminal ends the platform call.

Any source behavior you cannot implement is a limitation, never a success claim.
Coverage mechanism describes real node/hooks/routes, not simply 'covered'.
INPUT CONTRACT:
""" + json.dumps(contract, ensure_ascii=False) + "\nRAW SOURCES:\n" + json.dumps(raw_sources(contract), ensure_ascii=False) + \
        "\nCOMPILED POLICY:\n" + json.dumps(policy, ensure_ascii=False) + \
        "\nOFFICIAL PLATFORM REFERENCES:\n" + json.dumps(references, ensure_ascii=False) + \
        "\nSCHEMA EXAMPLE:\n" + json.dumps(base, ensure_ascii=False) + \
        "\nFEEDBACK FROM PREVIOUS CANDIDATE:\n" + json.dumps(feedback or {}, ensure_ascii=False)


def critic_prompt(contract: dict, workflow: dict) -> str:
    # Independent source read: do not show the author's IR or coverage claims.
    return """Independently audit this workflow against the ORIGINAL sources and supplied API.
Do not accept the author's claims of coverage. Find concrete counterexamples,
including uncommon branches, retries, corrections, out-of-order speech,
per-product partial commits, calendar/amount limits, terminal priority,
required sentences and whole-conversation prohibitions. Judge actual tools,
hooks and conditions. A prompt-only instruction can be weak, but do not invent
a violation without a plausible path. Ensure no constants were copied from
example customer data, and changed input fields/enums are honored. Distinguish
blocking source violations from optional hardening. 'pass' requires no errors;
'blocked' indicates unresolved source ambiguity. Include 3-6 independent
scenario/expected-output counterexamples with qualified source references.
Use warning severity for a gap in the source itself; use error severity for
a concrete workflow path that violates an existing binding source instruction.
This is an independent model review, not empirical validation of the agent.
Interpret the specified input domain before constructing counterexamples. Do not
require a policy amendment for backend data expressly outside that domain or
an optional recovery strategy. Never turn a may-retry option into a requirement.
Use 'revise' only with at least one concrete error. With only advisory warnings,
use 'pass'; with only an irreducible contradictory binding source gap, use
'blocked'. A model review passing still does not prove a runtime test passed.
Use the shared platform mechanics to audit actual paths, not to accept a named
stage or the author's claim that a guard is integrated. For each source-required
callback/promise/transfer, trace validated input -> required dispatch -> actual
receipt -> source-legal disposition. Check that a success gate cannot route away
before an outstanding action runs, including on the next user turn. Inspect all
writers of progress/outcome variables: user extraction must not author backend
success or terminal readiness. Test deterministic-route starvation, merged OR
targets and model-triggered transitions under the documented evaluation order.
Trace accepted terms/callback times, corrections and technical failures through
closure; flag invented transfers, skipped actions and repeated farewell paths
when they violate binding sources. Check required speech separately from bank
success, and bank closure separately from actual native termination. For every
error, cite qualified source IDs plus concrete node/tool/condition evidence and
an input/action/ledger/transcript counterexample. Do not relax the verdict because
some tools now work or dialogue sounds correct. Do not require this exact stage
layout or optional guard kernel without a source-grounded violation.
""" + PROGRESS_GUIDANCE + """
RAW SOURCES:
""" + json.dumps(raw_sources(contract), ensure_ascii=False) + \
        "\nSOURCE CLAUSES/TABLES AND API:\n" + json.dumps(contract, ensure_ascii=False) + \
        "\nWORKFLOW:\n" + json.dumps(workflow, ensure_ascii=False)


def policy_gap_prompt(contract: dict, ambiguities: list[str]) -> str:
    return """Review alleged policy ambiguities against original sources. Assess every
listed index exactly once with source references. Blocking means contradictory
binding instructions or missing information indispensable to a REQUIRED action.
No amendment is needed when only a standalone brief is supplied. Do not label
absence of a source amendment, arbitrary invalid backend data outside the input
domain, or an optional recovery strategy as blocking. Choose a safe protocol
for unspecified failures: no fabricated data, no false success claim, no blind
retry of an unknown write. Never invent a new policy value, API field, contact
number, queue, product, deadline or amount. Source bounds take priority. If the
sources already resolve a claim, state the actual resolution. Use short concrete
resolutions, rather than copying all source text. A genuine irreducible ambiguity
must remain blocking; do not conceal it just to permit publishing.
ORIGINAL SOURCE CONTRACT:\n""" + json.dumps(contract, ensure_ascii=False) + \
        "\nRAW SOURCES:\n" + json.dumps(raw_sources(contract), ensure_ascii=False) + \
        "\nCLAIMS:\n" + json.dumps(list(enumerate(ambiguities)), ensure_ascii=False)
