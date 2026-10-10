import json
from pathlib import Path

import pytest

from agent_forge.__main__ import main
from agent_forge.emit import check_workflow, freya_workflow, node_prompt, pipecat_flow, write_all
from agent_forge.extract import RuleExtractor
from agent_forge.forge import compile_sop, forge
from agent_forge.mutate import ablate, mutation_test
from agent_forge.repair import Patch, diagnose, gate, repair
from agent_forge.runtime import NaiveAgentModel, WorkflowRuntime
from agent_forge.simulate import Backends, ScriptedCaller, oracle_contract, perturb, run_persona, run_suite, words
from agent_forge.slots import fold, numbers, parse_amount, parse_date, parse_digits, parse_yes_no
from agent_forge.sop import load_sop, parse_sop
from agent_forge.spec import AgentSpec, errors_only, validate

EX = Path(__file__).resolve().parents[1] / "examples"
TR = EX / "sop_tr_bank_collections.md"
EN = EX / "sop_en_insurance_premium.md"


def draft(path=TR) -> AgentSpec:
    """The agent compiler's draft, with the exam compiler's callers attached (what the forge simulates)."""
    return compile_sop(path)[0]


@pytest.fixture(scope="module")
def repaired_tr():
    return repair(draft(TR), k=3)


# -- SOP parsing ---------------------------------------------------------------


def test_sop_clauses_and_binding_strength():
    title, cs = load_sop(TR)
    assert title.startswith("Örnek Banka")
    by = {c.id: c for c in cs}
    assert len(cs) == 21
    assert by["1.1"].strength == "info"
    assert by["3.2"].strength == "must_not"  # "paylaşılmaz"
    assert by["3.1"].strength == "must"  # "istenir"
    assert by["8.2"].strength == "must"  # "olmalıdır"


def test_unnumbered_paragraphs_become_clauses():
    _, cs = parse_sop("# T\n## Opening\nThe agent must say hello.\n\n## Close\n1.1 Never swear.\n")
    assert [c.id for c in cs] == ["opening.p1", "1.1"]
    assert [c.strength for c in cs] == ["must", "must_not"]


# -- spoken values ---------------------------------------------------------------


@pytest.mark.parametrize("text,value", [
    ("üç bin beş yüz", 3500), ("5 bin TL", 5000), ("12.450 TL", 12450), ("bin iki yüz", 1200),
    ("yirmi beş bin", 25000), ("two thousand five hundred", 2500), ("bes bin lira", 5000),
])
def test_amounts_in_digits_and_words(text, value):
    assert parse_amount(text) == value


@pytest.mark.parametrize("text", ["üç bin, yok pardon beş bin lira", "uc bin yok pardon bes bin", "make it 3000, actually 5000"])
def test_self_correction(text):
    assert parse_amount(text) == 5000
    assert parse_amount(text, strategy="first") == 3000


def test_dates_digits_yes_no():
    assert parse_date("12 mart 1985") == "12.03.1985"
    assert parse_date("Doğum tarihim 12.03.1985.") == "12.03.1985"
    assert parse_date("March 12, 1985") == "12.03.1985"
    assert parse_digits("son dört hane dört beş altı yedi", 4) == "4567"
    assert parse_digits("4 5 6 7", 4) == "4567"
    assert parse_yes_no("Evet, doğru.") is True
    assert parse_yes_no("Hayır, beş bin.") is False
    assert fold("ŞİMDİ Ödeme") == "simdi odeme"


def test_number_words_round_trip():
    for n in (100, 1245, 2000, 5000, 12450, 25000):
        assert parse_amount(words(n, "tr")) == n
        assert parse_amount(words(n, "en")) == n


def test_perturbations_keep_meaning():
    line = "Tamam, 2000 lira olsun."
    assert [parse_amount(perturb(line, r, "tr")) for r in range(3)] == [2000, 2000, 2000]


# -- extraction -------------------------------------------------------------------


@pytest.mark.parametrize("path,lang", [(TR, "tr"), (EN, "en")])
def test_extractor_covers_every_binding_clause(path, lang):
    s = draft(path)
    assert s.language == lang
    cov = s.coverage()
    assert cov["unimplemented"] == [] and cov["untested"] == []
    assert {n.id for n in s.nodes} >= {"greet", "verify", "inform", "promise", "close", "human_agent"}
    assert {t.name for t in s.tools} == {"verify_identity", "save_promise"}
    kinds = {r["kind"] for r in s.rules}
    assert kinds >= {"required_disclosure", "gated_topic", "forbidden", "escalation", "pii_leak", "max_words"}


def test_draft_static_check_finds_unbounded_loops_and_unreachable_transfer():
    errs = errors_only(validate(draft()))
    assert any("verify: unbounded retry loop" in e for e in errs)
    assert any("human_agent: unreachable" in e for e in errs)


def test_spec_round_trips_through_json():
    s = draft()
    assert AgentSpec.from_dict(json.loads(s.to_json())).to_dict() == s.to_dict()


# -- runtime and simulation ----------------------------------------------------------


def test_draft_failures_match_known_voice_agent_failure_classes():
    s = draft()
    res = run_suite(s, k=3)
    v = {p: d["verdicts"] for p, d in res.summary()["personas"].items()}
    # Even the friendly call breaks §4.2: the amount is saved without a read-back (ordering oracle, ltl.py).
    assert v["cooperative"] == ["fail"] * 3
    coop = next(r for r in res.runs if r.persona == "cooperative")
    assert len(coop.reasons) == 1 and "S confirmed:save_promise" in coop.reasons[0]
    assert v["self_correct"] == ["fail"] * 3  # first number wins: 3000 saved instead of 5000
    assert v["wrong_identity"] == ["fail"] * 3  # retry loop never ends
    assert v["lawyer"] == ["guarded"] * 3  # only the guard handed off
    impatient = next(r for r in res.runs if r.persona == "impatient")
    assert any(s.kind == "guard_block" and s.rule == "VC-3.2" for s in impatient.signals)  # balance before verification
    self_correct = next(r for r in res.runs if r.persona == "self_correct")
    assert any("save_promise.amount = 3000" in x for x in self_correct.reasons)


def test_guard_stops_split_pii_before_tts():
    s = draft()
    rt = WorkflowRuntime(s, NaiveAgentModel())
    rt.open()
    rt.st.node = "promise"
    out = rt.on_user("Kart numaram 4111 1111 1111 1111, bir okur musunuz?")
    assert "4111" not in out
    assert any(sig.kind == "guard_block" and sig.rule == "VC-7.1" for sig in rt.signals)


def test_policyguide_guidance_names_the_pending_gate():
    rt = WorkflowRuntime(draft(), NaiveAgentModel())
    rt.open()
    g = rt.guidance()
    assert "Current step: verify" in g and "until identity_verified" in g


# -- repair ---------------------------------------------------------------------------


def test_repair_reaches_clean_pass_with_cited_patches(repaired_tr):
    final, ledger, res = repaired_tr
    s = res.summary()
    assert s["pass^k"] == 1.0 and s["guard_interventions"] == 0 and s["fails"] == 0
    assert errors_only(validate(final)) == []
    accepted = [e.patch for e in ledger if e.accepted]
    assert {p.op for p in accepted} == {"bound_loop", "confirm_slot", "instruct", "global_route"}
    uncited = [p for p in accepted if not p.source]
    assert len(uncited) == 1 and uncited[0].needs_review and uncited[0].target == "promise"
    assert final.node("verify").max_attempts == 3  # from §3.3, not a guess
    assert final.slot("amount").confirm and final.slot("amount").confirm_source == ["4.2"]


def test_regression_gate_rejects_a_patch_that_breaks_other_callers():
    s = Patch("confirm_slot", "amount", {}, ["4.2"], "read back first").apply(draft())
    oracle = oracle_contract(s)
    before = run_suite(s, 3, oracle)
    bad = Patch("global_route", "*", {"intent": "ask_info"}, ["3.2"], "send balance questions to a human",
                personas=["impatient"])
    after = run_suite(bad.apply(s), 3, oracle)
    ok, why = gate(before, after, bad)
    assert not ok and "regression" in why


def test_diagnosis_is_evidence_driven():
    s = draft()
    patches = diagnose(s, run_suite(s, 3))
    ops = {(p.op, p.target) for p in patches}
    assert ("confirm_slot", "amount") in ops
    assert ("global_route", "*") in ops
    assert all(p.personas for p in patches)


# -- mutation testing ---------------------------------------------------------------------


def test_ablation_removes_only_one_clause(repaired_tr):
    final = repaired_tr[0]
    m, removed = ablate(final, "6.1")
    assert "guard:VC-6.1" in removed and "global_edge:intent:escalate" in removed
    assert m.global_edges == [] and len(m.rules) == len(final.rules) - 1


def test_mutation_score_and_survivors(repaired_tr):
    final = repaired_tr[0]
    m = mutation_test(final, k=3, oracle=oracle_contract(draft()))
    assert m["score"] >= 0.8
    survived = {x["clause"] for x in m["survivors"]}
    assert "7.1" not in survived and "6.1" not in survived and "4.2" not in survived
    assert survived <= {"7.2", "8.2"}


# -- emit ---------------------------------------------------------------------------------------


def test_freya_workflow_uses_documented_node_types(repaired_tr):
    wf = freya_workflow(repaired_tr[0])
    types = {n["type"] for n in wf["nodes"]}
    assert types <= {"start", "agent", "function", "condition", "transfer", "loop"}
    assert {"function", "condition", "transfer"} <= types
    ids = {n["id"] for n in wf["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in wf["edges"])
    # The bounded identity retry counts its attempts in a variable its own function node increments.
    fn = next(n for n in wf["nodes"] if n["type"] == "function" and n["data"].get("increment"))
    counter = fn["data"]["increment"]
    assert counter.startswith("verify") and any(
        (e.get("condition") or {}).get("variable") == counter and e["condition"]["value"] == 3 for e in wf["edges"])


def test_freya_workflows_are_wired(repaired_tr):
    """Red team: no node filled ``intent`` and the retry loops led nowhere. Every condition now reads a
    declared variable some node sets, every node is reachable, and nothing dead-ends."""
    wf = freya_workflow(repaired_tr[0])
    assert check_workflow(wf) == []
    agent = next(n for n in wf["nodes"] if n["type"] == "agent" and "collect" in n["data"])
    assert any(c["name"] == "intent" for c in agent["data"]["collect"])


def test_every_prompt_instruction_is_cited(repaired_tr):
    final = repaired_tr[0]
    for n in final.nodes:
        for line in node_prompt(final, n).splitlines():
            if line.startswith("- ") and "Call `" not in line and "`" not in line[:4]:
                assert "[§" in line or "[assumption]" in line, line


def test_write_all_and_pipecat_flow(tmp_path, repaired_tr):
    final = repaired_tr[0]
    files = write_all(final, tmp_path, k=3)
    names = {p.name for p in files}
    assert {"freya_workflow.json", "guard_policy.yaml", "freya_unit_tests.json", "freya_personas.json",
            "freya_simulation.json", "pipecat_flow.json", "traceability.md", "spec.json"} <= names
    sim = json.loads((tmp_path / "freya_simulation.json").read_text())
    assert sim["runsPerPersona"] == 3 and len(sim["selectedPersonaIds"]) == len(final.personas)
    flow = pipecat_flow(final)
    assert flow["initial_node"] == "greet"
    assert any(f["function"]["name"] == "save_promise" for f in flow["nodes"]["promise"]["functions"])
    assert AgentSpec.from_dict(json.loads((tmp_path / "spec.json").read_text())).name == final.name


def test_forge_end_to_end_english(tmp_path):
    res = forge(EN, tmp_path, k=3)
    s = res.summary()
    assert s["before"]["pass^k"] < 0.5 and s["after"]["pass^k"] == 1.0
    assert s["mutation_score"] >= 0.8
    assert (tmp_path / "report.md").read_text().startswith("# Agent forge report")


def test_cli(tmp_path, capsys):
    assert main(["build", str(TR), str(tmp_path), "--k", "2", "--no-mutate"]) == 0
    assert "report.md" in capsys.readouterr().out


# -- Phase 2: ordering oracle, architect, topology -------------------------------

from agent_forge import ltl  # noqa: E402
from agent_forge.architect import (  # noqa: E402
    Architect, TopoPatch, combined_personas, grow, personas_for, run_topology, topology_mutation)
from agent_forge.emit import freya_multiagent_workflow  # noqa: E402
from agent_forge.forge import build_log  # noqa: E402
from agent_forge.orchestrate import CallSession  # noqa: E402
from agent_forge.topology import Handoff, validate_topology  # noqa: E402


@pytest.fixture(scope="module")
def grown_tr(repaired_tr):
    final, _, _ = repaired_tr
    return grow(final, k=2)


def test_freya_multiagent_workflow_is_wired(grown_tr):
    multi = freya_multiagent_workflow(grown_tr[1])
    assert check_workflow(multi) == []
    assert any(e.get("handoff") for e in multi["edges"]) and any(e.get("handback") for e in multi["edges"])
    intent = next(v for v in multi["variables"] if v["name"] == "intent")
    assert {e["condition"]["value"] for e in multi["edges"] if e.get("handoff")} <= set(intent["enum"])


def test_ltl_formulas_and_monitor():
    fs = ltl.formulas(draft(TR))
    texts = [f.text() for f in fs]
    assert "G(call:save_promise → O event:identity_verified)" in texts
    assert "G(call:save_promise → ¬call:save_promise S confirmed:save_promise)" in texts
    assert "G(call:save_promise → ¬O tool:record_dispute)" in texts
    ok = ["call:verify_identity", "tool:verify_identity", "event:identity_verified", "confirmed:save_promise",
          "call:save_promise"]
    assert ltl.check(fs, ok) == []
    # Second write reuses the first confirmation: "since" catches it, "once" would not.
    assert any("S confirmed" in v for v in ltl.check(fs, ok + ["call:save_promise"]))
    assert any("O event:identity_verified" in v for v in ltl.check(fs, ["confirmed:save_promise", "call:save_promise"]))
    assert any("¬O tool:record_dispute" in v
               for v in ltl.check(fs, ok[:4] + ["tool:record_dispute", "confirmed:save_promise", "call:save_promise"]))


def test_ordering_oracle_flags_unconfirmed_write_in_draft():
    res = run_suite(draft(TR), k=1)
    coop = next(r for r in res.runs if r.persona == "cooperative")
    assert any(x.startswith("order violation") and "confirmed:save_promise" in x for x in coop.reasons)


def test_plan_starts_with_core_and_pending_capabilities(repaired_tr):
    final, _, _ = repaired_tr
    t = Architect().plan(final)
    assert [a.id for a in t.agents] == ["core"]
    assert {c["id"] for c in t.pending} == {"third_party", "dispute", "hardship", "update_address", "block_card", "extend_due_date"}
    assert validate_topology(t) == []


def test_unrouted_intent_and_spawn(repaired_tr):
    final, _, _ = repaired_tr
    t = Architect().plan(final)
    res = run_topology(t, k=1, personas=[p for p in personas_for(t) if p.id == "hardship"])
    assert any(s.kind == "unrouted_intent" and s.rule == "hardship" for r in res.runs for s in r.signals)
    cap = next(c for c in t.pending if c["id"] == "hardship")
    t2 = TopoPatch("spawn_agent", "hardship", {}, cap["source"], "test").apply(t, Architect())
    sp = t2.agent("hardship")
    assert sp.requires == ["event:identity_verified"] and sp.spec.start == "verify"
    assert {r["id"] for r in final.rules if r["kind"] in ("forbidden", "escalation")} <= {r["id"] for r in sp.spec.rules}
    assert validate_topology(t2) == [] or all(e.startswith("warning:") for e in validate_topology(t2))


def test_repeated_question_then_carry_fixes_it(repaired_tr):
    final, _, _ = repaired_tr
    t = Architect().plan(final)
    cap = next(c for c in t.pending if c["id"] == "hardship")
    t = TopoPatch("spawn_agent", "hardship", {}, cap["source"], "test").apply(t, Architect())
    # The architect wires the handoff from the typed contract: exactly the verified-identity event travels.
    h = next(h for h in t.handoffs if h.dst == "hardship")
    assert h.carry == ["event:identity_verified"]
    h.carry = []  # unwired, the specialist asks again; the runtime evidence brings the carry back
    hp = [p for p in personas_for(t) if p.id == "hardship"]
    res = run_topology(t, k=1, personas=hp)
    assert any(s.kind == "repeated_question" for r in res.runs for s in r.signals)
    t = TopoPatch("carry_context", "hardship", {"src": "core", "fields": ("event:identity_verified",)}, cap["source"],
                  "test").apply(t, Architect())
    res = run_topology(t, k=2, personas=hp)
    assert all(r.verdict == "pass" for r in res.runs), [r.reasons for r in res.runs]
    assert res.runs[0].tool_calls[-1]["name"] == "hardship_plan"


def test_escalation_beats_handoff(grown_tr):
    _, t, _, _, _ = grown_tr
    s = CallSession(t)
    s.open()
    s.on_user("Avukatımla görüşmeden hiçbir şey kabul etmiyorum, bu borcu kabul etmiyorum.")
    assert s.handoffs_taken == [] and s.st.done == "transfer"


def test_grow_reaches_full_pass_and_minimal_carry(grown_tr):
    draft_t, t, ledger, before, after = grown_tr
    assert before.summary()["pass^k"] < after.summary()["pass^k"] == 1.0
    # Style chosen by evidence: third party is an inline branch (no identity, call ends), the rest are specialists,
    # and the address change and the stolen card hand the call back because §12.1 and §13.1 say the call goes on.
    assert {a.id for a in t.agents} == {"core", "update_address", "dispute", "hardship", "block_card", "extend_due_date"}
    assert t.inline == ["third_party"]
    assert t.style() == ("router + 5 specialists, 3 with handback, 1 inline branch, "
                         "1 join (extend_due_date after all of check_income, check_risk)")
    carries = {h.dst: h.carry for h in t.handoffs if not h.handback}
    assert carries["hardship"] == carries["update_address"] == carries["block_card"] == ["event:identity_verified"]
    assert [(h.src, h.dst) for h in t.handoffs if h.handback] == [
        ("update_address", "core"), ("block_card", "core"), ("extend_due_date", "core")]
    lost = [e for e in ledger if not e.accepted]
    assert [(e.patch.op, e.patch.target) for e in lost] == [("spawn_agent", "third_party")]
    # A separate agent for the relative cannot take the call back to verification when the customer comes on.
    assert "third_party_handover" in lost[0].why


def test_third_party_hands_the_phone_back_to_verification(grown_tr):
    _, t, _, _, _ = grown_tr
    # A relative answers, then the customer comes to the phone: the branch goes back to the identity check,
    # the account opens only after it, and no callback is booked.
    ps = [p for p in personas_for(t) if p.id in ("third_party", "third_party_handover")]
    res = run_topology(t, k=1, personas=ps)
    runs = {r.persona: r for r in res.runs}
    assert all(r.verdict == "pass" for r in runs.values()), {k: r.reasons for k, r in runs.items()}
    names = [c["name"] for c in runs["third_party_handover"].tool_calls]
    assert names[0] == "verify_identity" and "schedule_callback" not in names
    assert [c["name"] for c in runs["third_party"].tool_calls] == ["schedule_callback"]
    # Its own interjection would be lost in a merge, so it never opens a cross-clause combination.
    assert not any(p.id.startswith("third_party_handover+") for p in personas_for(t))


def test_combined_personas_cross_clauses(repaired_tr):
    final, _, _ = repaired_tr
    caps = [p for p in personas_for(Architect().plan(final)) if p.id in ("dispute", "hardship")]
    combos = {p.id: p for p in combined_personas(final, caps)}
    assert {"impatient+hardship", "injection+dispute"} <= set(combos)
    p = combos["impatient+hardship"]
    assert "first_line" in p.behaviour and "interject" in p.behaviour
    assert "hardship_plan" in p.expect["tools"] and "save_promise" in p.expect["no_tools"]


def test_topology_validation_catches_cycles_dataflow_inheritance_and_depth(grown_tr):
    _, t, _, _, _ = grown_tr
    bad = t.clone()
    bad.handoffs.append(Handoff("hardship", "core", "x", ["11.1"]))
    errs = validate_topology(bad)
    assert any("cycle" in e for e in errs) and any("depth limit" in e for e in errs)
    bad = t.clone()
    next(h for h in bad.handoffs if h.dst == "dispute").carry = ["event:nope"]
    assert any("no upstream agent produces" in e for e in validate_topology(bad))
    bad = t.clone()
    bad.agent("dispute").spec.rules = [r for r in bad.agent("dispute").spec.rules if r["kind"] != "forbidden"]
    assert any("does not inherit guard rules" in e for e in validate_topology(bad))
    bad = t.clone()
    bad.max_agents = 2
    assert any("spawn budget" in e for e in validate_topology(bad))


def test_topology_mutation_kills_specialist_clauses(grown_tr):
    _, t, _, _, _ = grown_tr
    m = topology_mutation(t, k=1)
    killed = {d["clause"] for d in m["detail"] if d["killed"]}
    assert {"9.1", "10.1", "11.1", "12.1", "3.2"} <= killed and m["score"] >= 0.8


def test_multiagent_workflow_and_build_log(tmp_path):
    res = forge(TR, tmp_path, k=2)
    wf = freya_multiagent_workflow(res.topology)
    hand = [e for e in wf["edges"] if e.get("handoff")]
    assert {e["target"].split(".")[0] for e in hand if e["source"].split(".")[0] == "core"} == {
        "update_address", "dispute", "hardship", "block_card", "extend_due_date"}
    assert all(e["condition"]["variable"] == "intent" for e in hand)
    for f in ("topology.json", "topology.md", "freya_multiagent_workflow.json", "build_log.jsonl"):
        assert (tmp_path / f).exists()
    log = [json.loads(x) for x in (tmp_path / "build_log.jsonl").read_text().splitlines()]
    assert log[0]["actor"] == "architect" and log[-1]["action"] == "compile"
    assert {x["depth"] for x in log} == {0, 1}
    assert any(x["action"] == "spawn_agent" and x["accepted"] for x in log)
    assert res.summary()["topology"]["after"]["pass^k"] == 1.0
    assert "Phase 2" in (tmp_path / "report.md").read_text()


# -- --llm plumbing, offline (a stub stands in for the API) ------------------------


class StubClaude:
    """Checks every request the way the API would and records it. The agent says what the workflow planned;
    the caller answers from the transcript it was given."""

    def __init__(self):
        self.calls = []

    def text(self, system, messages, max_tokens=2000, effort=None):
        assert messages and messages[0]["role"] == "user" and messages[-1]["role"] == "user", messages
        self.calls.append((system, [dict(m) for m in messages]))
        if system.startswith("Extract one value"):
            from agent_forge.slots import parse_slot
            said = messages[-1]["content"].split("Caller said: ", 1)[1]
            kind = messages[-1]["content"].split("(", 1)[1].split(")", 1)[0]
            v = parse_slot(kind, said)
            return "NONE" if v is None else str(v)
        if system.startswith("You are a caller"):
            return "Evet, doğru."
        if system.startswith("You classify one caller utterance"):
            return "[]"
        if system.startswith("The agent read a payment amount and date back"):
            return '{"verdict": "yes", "amount": null, "date": null}'
        if system.startswith("You are the compliance check"):
            return '{"violates": [], "why": ""}'
        return system.rsplit("convey, in order: ", 1)[1].split("\nReply with", 1)[0].replace(" | ", " ")


def test_llm_backends_fresh_per_call_and_caller_wired(repaired_tr):
    from agent_forge.llm import ClaudeAgentModel, ClaudeCaller, claude_backends

    final, _, _ = repaired_tr
    stub = StubClaude()
    b = claude_backends(stub)
    a1, a2 = b.agent(), b.agent()
    assert a1 is not a2 and a1.history is not a2.history
    assert isinstance(b.caller(final, final.personas[0], 0), ClaudeCaller)
    res = run_suite(final, k=2, backends=b, personas=final.personas[:1])
    assert len(res.runs) == 2
    # The second call's first agent request carries no turn from the first call.
    agent_calls = [m for s, m in stub.calls if "Workflow state" in s]
    opens = [m for m in agent_calls if m == [{"role": "user", "content": "(call connected)"}]]
    assert len(opens) >= 2
    caller_calls = [m for s, m in stub.calls if s.startswith("You are a caller")]
    assert caller_calls, "ClaudeCaller was never asked"


def test_llm_backends_reach_phase_2(grown_tr):
    from agent_forge.llm import claude_backends

    _, t, _, _, _ = grown_tr
    stub = StubClaude()
    run_topology(t, k=1, backends=claude_backends(stub), personas=personas_for(t)[:1])
    assert any("Workflow state" in s for s, _ in stub.calls)


def test_oracle_union_keeps_rule_based_rules():
    rule = draft(TR)
    llm = AgentSpec.from_dict(json.loads(rule.to_json()))
    llm.rules = [r for r in llm.rules if r["id"] != "VC-5.1"]  # the refined spec "forgot" the no-threat rule
    o = oracle_contract(rule, llm)
    assert "VC-5.1" in {r.id for r in o.rules}
    assert len(o.order) == len(oracle_contract(rule).order)


# -- v3: blind exam compiler, coverage gate, listening caller, perception ------------

import inspect  # noqa: E402

from agent_forge.exam import ExamCompiler, UntestedClauses  # noqa: E402
from agent_forge.perceive import RulePerception, evaluate  # noqa: E402
from agent_forge.simulate import hear  # noqa: E402


@pytest.mark.parametrize("path", [TR, EN])
def test_exam_compiler_sees_only_clauses_and_tests_every_binding_clause(path):
    assert list(inspect.signature(ExamCompiler.compile).parameters) == ["self", "title", "clauses"]
    exam = ExamCompiler().compile(*load_sop(path))
    assert exam.uncovered() == []
    assert all(r["id"].startswith("EX-") for r in exam.rules)  # its own oracle, not the agent's guard rules
    assert {x["task"] for x in exam.perception} == {"route", "confirm"}
    assert any(x["label"] == "none" for x in exam.perception)  # hard negatives, not only paraphrases


def test_build_blocks_on_a_clause_nobody_tests(tmp_path, capsys):
    sop = tmp_path / "sop.md"
    sop.write_text(TR.read_text(encoding="utf-8") + "\n## 15. Kampanya\n\n15.1 Görüşmede müşteriye yeni kredi kartı "
                   "kampanyası önerilmez.\n", encoding="utf-8")
    with pytest.raises(UntestedClauses) as e:
        forge(sop, k=1, mutate=False)
    assert e.value.clauses == ["15.1"]
    assert main(["build", str(sop), str(tmp_path / "out"), "--k", "1", "--no-mutate"]) == 2
    assert "15.1" in capsys.readouterr().err
    res = forge(sop, k=1, mutate=False, allow_untested=True)
    assert res.summary()["exam"]["uncovered"] == ["15.1"]


def test_caller_only_hears_speech(repaired_tr):
    final, _, _ = repaired_tr
    assert hear("Bilgiler eşleşmedi. Doğum tarihinizi söyler misiniz?") == "dob"
    assert hear("Ayda ne kadar ödeyebilirsiniz?") == "monthly"
    garbled = final.clone()
    for s in garbled.slots:
        s.ask = "Lütfen bana en sevdiğiniz rengi söyleyin."
    res = run_suite(garbled, k=1, personas=[p for p in garbled.personas if p.id == "cooperative"])
    assert res.runs[0].verdict == "fail"  # the caller cannot answer a question it never heard


def test_rule_perception_negation_and_correction():
    rp = RulePerception()
    opts = {"dispute": ["itiraz", "benim değil"], "hardship": ["işimi kaybettim"]}
    assert rp.intents("Bu borca itiraz ediyorum.", opts) == ["dispute"]
    assert rp.intents("Hiçbir itirazım yok, öderim.", opts) == []
    assert rp.intents("I don't dispute it.", {"dispute": ["dispute"]}, "en") == []
    assert rp.confirm("Evet, doğru.", 5000) == ("yes", None)
    assert rp.confirm("Doğru değil.", 5000)[0] == "no"
    assert rp.confirm("Tamam ama 6000 yazın.", 5000) == ("correction", 6000)
    assert rp.confirm("Not five thousand, 6000 dollars.", 5000) == ("correction", 6000)


def test_runtime_takes_a_correction_at_read_back(repaired_tr):
    final, _, _ = repaired_tr
    rt = WorkflowRuntime(final, NaiveAgentModel())
    rt.open()
    rt.st.events.add("identity_verified")
    rt.st.node, rt.st.slots = "promise", {"amount": 5000.0, "pay_date": "20.10"}
    rt.st.awaiting = ["confirm:save_promise"]
    rt.on_user("Evet, ama beş bin değil altı bin.")
    assert rt.st.slots["amount"] == 6000 and not any(c.name == "save_promise" for c in rt.tool_calls)


def test_perception_scored_on_the_exam_set():
    res = forge(TR, k=1, mutate=False)
    p = res.summary()["perception"]
    assert p["cases"] >= 20 and p["accuracy"] == 1.0 and p["labels"]["none"]["recall"] == 1.0
    assert res.topo_after.summary()["personas"]["not_dispute"]["pass^k"]


def test_claude_exam_compiler_validates_and_merges():
    from agent_forge.llm import ClaudeExamCompiler

    title, clauses = load_sop(TR)
    good = ('```json\n{"tests": [{"clause": "10.1", "caller": {"id": "dispute2", "goal": "dispute in other words", '
            '"behaviour": {"interject": {"at": "amount", "text": "Bu borcun bana ait olduğunu düşünmüyorum."}}, '
            '"expect": {"end": "end", "tools": {"record_dispute": {}}, "scope": "topology"}}, '
            '"order": [{"kind": "once", "a": "call:record_dispute", "b": "event:identity_verified"}], '
            '"perception": [{"task": "route", "text": "Bu benim borcum değil ki", "label": "dispute"}]}]}\n```')
    ex, errs = ClaudeExamCompiler._load(good, title, clauses, {c.id for c in clauses}, "tr")
    assert errs == [] and ex.personas[0].id == "llm_dispute2" and ex.perception[0]["label"] == "dispute"
    bad = good.replace('"interject"', '"peek_state"')
    _, errs = ClaudeExamCompiler._load(bad, title, clauses, {c.id for c in clauses}, "tr")
    assert errs and "unknown keys" in errs[0]
    merged = ExamCompiler().compile(title, clauses).merge(ex)
    assert "llm_dispute2" in {p.id for p in merged.personas} and merged.uncovered() == []


# -- Open-set situations and orchestration style ----------------------------------

from agent_forge.sop import condition_of, cue_patterns, resumes  # noqa: E402


def test_condition_and_cues_from_a_conditional_clause():
    tr = "Müşteri adresinin değiştiğini belirtirse yeni adres alınır, update_address ile kaydedilir ve görüşmeye " \
         "kaldığı yerden devam edilir."
    en = "If the policyholder says their address has changed, the agent must collect the new address, record it " \
         "with update_address and continue where the call left off."
    assert condition_of(tr) == "adresinin degistigini" and condition_of(tr, surface=True) == "adresinin değiştiğini"
    assert cue_patterns(condition_of(tr)) == ["adre.*degis", "degis.*adre"]
    assert condition_of(en) == "their address has changed" and cue_patterns(condition_of(en))[0] == "addre.*chang"
    assert resumes(tr) and resumes(en)
    assert not resumes("Müşteri borca itiraz ederse itiraz gerekçesi alınır ve record_dispute ile kaydedilir.")


@pytest.mark.parametrize("path", [TR, EN])
def test_open_set_clause_reaches_both_compilers_blind(path):
    spec, exam = compile_sop(path)
    cap = next(c for c in spec.capabilities if c["id"] == "update_address")
    assert cap["known"] is False and cap["mode"] == "resume" and cap["requires_identity"]
    p = next(p for p in exam.personas if p.id == "update_address")
    # The exam writes its own caller line from the clause and demands the promise still gets saved (resume).
    assert "update_address" in p.expect["tools"] and "save_promise" in p.expect["tools"] and not p.expect["no_tools"]
    line = p.behaviour["interject"]["text"].lower()
    assert ("adresimin" in line) if path == TR else ("my address" in line)
    assert exam.uncovered() == []


def test_handback_resumes_where_the_call_left_off(grown_tr):
    _, t, _, _, _ = grown_tr
    s = CallSession(t)
    s.open()
    s.on_user("Doğum tarihim 12.03.1985.")
    s.on_user("Son dört hanesi 4567.")
    assert "kimlik" not in s.on_user("Bu arada adresim değişti, onu bildirmek istiyorum.").lower()  # carried
    out = s.on_user("Moda Caddesi 12, Kadıköy, İstanbul.")
    assert s.active == "core" and s.handoffs_taken == ["core->update_address", "update_address->core (back)"]
    assert "ödeme" in out.lower()  # the core re-asks the question it was on
    s.on_user("5 bin lira yatırabilirim.")
    s.on_user("20 ekim.")
    s.on_user("Evet, doğru.")
    tools = [x for x in s.trace if x.startswith("tool:")]
    assert tools[-2:] == ["tool:update_address", "tool:save_promise"]
    assert s.st.done == "end"


def test_style_choice_holds_in_english():
    spec, exam = compile_sop(EN)
    final, _, _ = repair(spec, k=1, oracle=exam.contract())
    _, t, ledger, _, after = grow(final, k=1, oracle=exam.contract())
    assert after.summary()["pass^k"] == 1.0
    assert t.style() == ("router + 5 specialists, 2 with handback, 1 inline branch, "
                         "1 join (issue_refund after all of approve_lead, approve_manager in order)")
    assert t.inline == ["third_party"]
    assert any(e.patch.op == "spawn_agent" and "third_party_handover" in e.why for e in ledger if not e.accepted)


def test_unseen_clause_types_get_their_own_agents(tmp_path):
    sop = tmp_path / "sop.md"
    sop.write_text(TR.read_text(encoding="utf-8") + "\n## 15. Kayıp telefon\n\n15.1 Müşteri telefonunun kaybolduğunu "
                   "bildirirse hat suspend_line ile askıya alınır ve görüşme sonlandırılır.\n", encoding="utf-8")
    res = forge(sop, None, k=1, mutate=False)
    tp = res.summary()["topology"]
    # The spawn budget is spent, so one situation becomes a branch in the entry agent instead of a seventh agent.
    assert "suspend_line" in tp["agents"] and tp["after"]["pass^k"] == 1.0 and tp["pending"] == []
    assert len(res.topology.agents) <= res.topology.max_agents
    assert not any(h.handback and h.src == "suspend_line" for h in res.topology.handoffs)  # this one ends the call


def test_tool_order_reads_turkish_and_english_order_words():
    from agent_forge.sop import tool_order

    bc = ["block_card", "reissue_card"]
    for text in (
        "Müşteri kartının çalındığını bildirirse önce kart block_card ile bloke edilir, ardından reissue_card ile yeni kart talep edilir.",
        "Yeni kart reissue_card ile, kart block_card ile bloke edildikten sonra talep edilir.",
        "Kart çalındıysa reissue_card çağrılmadan önce kart block_card ile bloke edilir.",
        "Block it with block_card before ordering a replacement with reissue_card.",
        "Order a replacement with reissue_card only after the card is blocked with block_card.",
        "Before ordering a replacement with reissue_card, the agent must block the card with block_card.",
        "If the card is stolen, block it with block_card, then reissue it with reissue_card.",
    ):
        assert tool_order(text, list(reversed(bc))) == bc, text
    assert tool_order("Record it with update_address.", ["update_address"]) == ["update_address"]


def test_ordering_clause_becomes_workflow_order_and_is_tested():
    """'Block first, then reissue' is compiled into the specialist's own chain, and the exam's order formula
    fails a topology that runs the same two tools the other way round."""
    res = forge(TR, None, k=1, mutate=False)  # §13.1: "önce block_card ile bloke edilir, ardından reissue_card"
    t = res.topology
    assert res.summary()["topology"]["after"]["pass^k"] == 1.0
    spec = t.agent("block_card").spec
    chain = [n.tool for n in spec.nodes if n.tool and n.tool != "verify_identity"]
    assert chain == ["block_card", "reissue_card"]
    assert "G(call:reissue_card → O tool:block_card)" in {f.text() for f in res.exam.formulas}
    oracle = res.exam.contract()
    bad = t.clone()
    nodes = {n.tool: n for n in bad.agent("block_card").spec.nodes if n.tool in ("block_card", "reissue_card")}
    nodes["block_card"].tool, nodes["reissue_card"].tool = "reissue_card", "block_card"
    for n in nodes.values():
        n.edges = [type(e)(e.to, f"event:{n.tool}_done", e.source) for e in n.edges]
    after = run_topology(bad, k=1, oracle=oracle)
    assert after.summary()["pass^k"] < 1.0
    assert any("O tool:block_card" in x for r in after.runs for x in r.reasons)


def test_join_waits_for_every_check_and_a_negative_check_stops_the_action():
    """'Only if both checks are positive': parallel checks (TR) and an approval chain (EN). A negative check
    must stop the action, and a topology that ignores it is caught by the caller whose check says no."""
    from agent_forge.sop import join_of

    j = join_of("If any approval is declined, transfer. Get approve_lead then approve_manager; only if every approval "
                "is positive is the refund issued with issue_refund.", ["approve_lead", "approve_manager", "issue_refund"])
    assert j["action"] == "issue_refund" and j["ordered"] and j["on_fail"] == "transfer"
    for sop, action, checks, parallel, end in ((TR, "extend_due_date", ["check_income", "check_risk"], True, "end"),
                                               (EN, "issue_refund", ["approve_lead", "approve_manager"], False,
                                                "transfer")):
        res = forge(sop, None, k=1, mutate=False)
        t = res.topology
        assert res.summary()["topology"]["after"]["pass^k"] == 1.0
        node = next(n for n in t.agent(action).spec.nodes if n.join)
        assert node.tool == action and node.join == checks and node.parallel is parallel
        declined = next(p for p in res.exam.personas if p.id == f"{action}_declined")
        assert declined.expect["end"] == end and action in declined.expect["no_tools"]
        wf = freya_multiagent_workflow(t)
        assert check_workflow(wf) == []
        join = next(n for n in wf["nodes"] if n.get("data", {}).get("join") == "all")
        assert join["data"]["waitsOn"] == checks and join["data"]["parallel"] is parallel
        m = topology_mutation(t, k=1, oracle=res.exam.contract())
        jm = [d for d in m["detail"] if any(x.startswith("join:") for x in d["removed"])]
        assert jm and all(d["killed"] for d in jm)


def test_inbound_sop_with_no_payment_step(tmp_path):
    """Red team: on a card line with no payment step, situation callers waited for an amount question that never
    came, and the build still finished green. They now say why they call first, the agent greets as an inbound
    line, and the CLI is red while any exam caller fails."""
    card = TR.parent / "sop_tr_card_inbound.md"
    res = forge(card, None, k=3, mutate=False)
    assert res.summary()["topology"]["after"]["pass^k"] == 1.0
    p = next(p for p in res.exam.personas if p.id == "block_card")
    assert "first_line" in p.behaviour and not p.behaviour["first_line"].startswith("Bu arada")
    greet = res.topology.agent("core").spec.node("greet").say
    assert "tahsilat" not in greet and "kayıt altına" in greet
    run = next(r for r in res.topo_after.runs if r.persona == "block_card")
    assert [c["name"] for c in run.tool_calls if c["ok"]] == ["verify_identity", "block_card", "reissue_card"]
    assert main(["build", str(card), str(tmp_path / "out"), "--k", "1", "--no-mutate"]) == 0


def test_every_branch_of_a_clause_is_tested_and_built(tmp_path):
    """Red team: a negative check left the call in silence, and the build stayed green because only the happy path
    was tested. The exam now tests the clause's negative branch, the gate requires it, and the builder gives every
    step a way out; without that way out the negative caller fails."""
    sop = tmp_path / "card.md"
    sop.write_text((TR.parent / "sop_tr_card_inbound.md").read_text(encoding="utf-8").replace(
        "ile yeni kart talep edilir.", "ile yeni kart talep edilir. Kart bloke edilemezse çağrı müşteri "
        "temsilcisine aktarılır."), encoding="utf-8")
    res = forge(sop, None, k=2, mutate=False)
    neg = next(p for p in res.exam.personas if p.id == "block_card_declined")
    assert neg.behaviour["declines"] == ["block_card"] and neg.expect["end"] == "transfer"
    assert "reissue_card" in neg.expect["no_tools"]
    assert res.summary()["topology"]["after"]["pass^k"] == 1.0
    bad = res.topology.clone()
    for n in bad.agent("block_card").spec.nodes:
        n.edges = [e for e in n.edges if e.when != "tool_failed" or n.tool == "verify_identity"]
    after = run_topology(bad, k=1, oracle=res.exam.contract(), personas=[neg])
    assert after.summary()["pass^k"] < 1.0
    # The gate counts branches: drop the negative caller and the clause is uncovered again.
    res.exam.personas = [p for p in res.exam.personas if not p.behaviour.get("declines")]
    assert "4.1 (negative branch)" in res.exam.uncovered()


def test_approval_applies_only_above_the_stated_amount():
    """Red team: 'approval for refunds over $500' was read without its threshold, so approval was asked at every
    amount. Above it the approval chain runs; below it the refund is issued straight away, and the order rule
    binds only calls above the amount."""
    from agent_forge.sop import threshold_of

    assert threshold_of("for refunds over $500 the agent must") == (">", 500.0)
    assert threshold_of("5.000 TL üzeri iadelerde müdür onayı alınır") == (">", 5000.0)
    res = forge(EN, None, k=1, mutate=False)
    assert res.summary()["topology"]["after"]["pass^k"] == 1.0
    fs = {f.text() for f in res.exam.formulas}
    assert "G(call:issue_refund ∧ request_amount>500 → O tool:approve_lead)" in fs
    runs = {r.persona: [c["name"] for c in r.tool_calls if c["ok"]] for r in res.topo_after.runs}
    assert runs["issue_refund_no_approval"] == ["verify_identity", "issue_refund"]
    assert runs["issue_refund"][-3:] == ["approve_lead", "approve_manager", "issue_refund"]
    wf = freya_multiagent_workflow(res.topology)
    assert check_workflow(wf) == []
    assert any((e.get("condition") or {}).get("operator") == "gt" for e in wf["edges"])


def test_rules_spread_over_a_section_compile_like_one_clause(tmp_path):
    """Red team: an order or a join split over several clauses stopped the build. A section's situation clause
    is read together with the clauses that add its order, its checks and its negative outcome."""
    from agent_forge.sop import link_clauses, parse_sop

    en = EN.read_text(encoding="utf-8")
    en = en[:en.index("## 13. Premium refund")] + (
        "## 13. Premium refund\n\n13.1 If the policyholder asks for a refund of a premium already paid, the agent "
        "must issue it with issue_refund.\n13.2 For refunds over $500, a refund requires approval from the team lead "
        "with approve_lead and then from the manager with approve_manager.\n13.3 If an approval is declined, the "
        "call is transferred to a human agent.\n")
    link = link_clauses(parse_sop(en)[1])
    j = link["joins"]["issue_refund"]
    assert j["checks"] == ["approve_lead", "approve_manager"] and j["ordered"] and j["on_fail"] == "transfer"
    assert j["threshold"]["value"] == 500 and link["linked"] == {"13.2": "join", "13.3": "negative"}
    sop = tmp_path / "en.md"
    sop.write_text(en, encoding="utf-8")
    res = forge(sop, None, k=1, mutate=False)
    assert res.exam.uncovered() == [] and res.summary()["topology"]["after"]["pass^k"] == 1.0
    node = next(n for n in res.topology.agent("issue_refund").spec.nodes if n.join)
    assert node.join == ["approve_lead", "approve_manager"]
    declined = next(p for p in res.exam.personas if p.id == "issue_refund_declined")
    assert declined.expect["end"] == "transfer" and "13.3" in declined.source

    tr = (TR.parent / "sop_tr_card_inbound.md").read_text(encoding="utf-8").replace(
        "önce kart block_card ile bloke edilir, ardından reissue_card ile yeni kart talep edilir.",
        "reissue_card ile yeni kart talep edilir.\n4.2 Yeni kart talebinden önce kart block_card ile bloke edilir.")
    sop = tmp_path / "tr.md"
    sop.write_text(tr, encoding="utf-8")
    res = forge(sop, None, k=1, mutate=False)
    assert "G(call:reissue_card → O tool:block_card)" in {f.text() for f in res.exam.formulas}
    run = next(r for r in res.topo_after.runs if r.persona == "reissue_card")
    assert [c["name"] for c in run.tool_calls if c["ok"]] == ["verify_identity", "block_card", "reissue_card"]


_HEAD_TR = "Müşteri kartının çalındığını bildirirse kart block_card ile bloke edilir."
_HEAD_TR_RE = "Müşteri kartının çalındığını bildirirse reissue_card ile yeni kart talep edilir."
_HEAD_EN = "If the customer reports a stolen card, block it with block_card."
_HEAD_EN_RE = "If the customer reports a stolen card, order a replacement with reissue_card."


@pytest.mark.parametrize("head,rule", [
    (_HEAD_TR, "Yeni kart reissue_card ile ancak bloke işleminden sonra talep edilir."),
    (_HEAD_TR, "reissue_card ile yeni kart talebi blokenin ardından yapılır."),
    (_HEAD_TR, "Bloke tamamlanmadan reissue_card ile yeni kart talep edilmez."),
    (_HEAD_TR_RE, "Yeni kart, kart block_card ile bloke edilmeden talep edilemez."),
    (_HEAD_TR_RE, "Kart block_card ile bloke edildikten sonra yeni kart talep edilebilir."),
    (_HEAD_EN, "A replacement may be ordered with reissue_card only after the block."),
    (_HEAD_EN, "reissue_card is only used once the block is in place."),
    (_HEAD_EN, "reissue_card must not be called before the card is blocked."),
    (_HEAD_EN_RE, "No replacement may be ordered until the card is blocked with block_card."),
    (_HEAD_EN_RE, "The card must be blocked with block_card before any replacement is ordered."),
])
def test_a_split_order_clause_reads_the_side_its_order_word_governs(head, rule):
    """Red team: with the block in one clause and "reissue only after the block" in another, the new card was
    issued first and the build was green. The order word's side is read from the words it governs, matched
    against how the section talks about each tool."""
    from agent_forge.sop import link_clauses, parse_sop

    link = link_clauses(parse_sop(f"# T\n\n## 4. Kart\n\n4.1 {head}\n4.2 {rule}\n")[1])
    assert [(a, b) for a, b, _ in link["pairs"]] == [("block_card", "reissue_card")] and link["joins"] == {}


def test_a_split_order_clause_that_cannot_be_read_stops_the_build(tmp_path):
    from agent_forge.sop import link_clauses, parse_sop

    tr = (TR.parent / "sop_tr_card_inbound.md").read_text(encoding="utf-8").replace(
        "önce kart block_card ile bloke edilir, ardından reissue_card ile yeni kart talep edilir.",
        "kart block_card ile bloke edilir.\n4.2 reissue_card ile yeni kart ancak ilgili adımdan sonra talep edilir.")
    assert link_clauses(parse_sop(tr)[1])["linked"] == {}
    sop = tmp_path / "tr.md"
    sop.write_text(tr, encoding="utf-8")
    with pytest.raises(UntestedClauses):
        forge(sop, None, k=1, mutate=False)


@pytest.mark.parametrize("rule", [
    "A refund needs approval from approve_manager and approve_lead; approve_manager is asked only after "
    "approve_lead has approved.",
    "The refund requires approve_manager's sign-off, which follows approval by approve_lead.",
    "İade için approve_manager onayı gerekir; bu onay approve_lead onayını takiben alınır.",
    "İade için approve_manager ve approve_lead onayı gerekir; approve_manager onayı approve_lead onayından sonra "
    "istenir.",
])
def test_an_approval_chain_over_clauses_keeps_its_stated_order(rule):
    from agent_forge.sop import link_clauses, parse_sop

    head = "If the policyholder asks for a refund, the refund must be issued with issue_refund."
    j = link_clauses(parse_sop(f"# T\n\n## 4. Refund\n\n4.1 {head}\n4.2 {rule}\n")[1])["joins"]["issue_refund"]
    assert j["checks"] == ["approve_lead", "approve_manager"] and j["ordered"]


@pytest.mark.parametrize("text,want", [
    ("If the refund does not exceed $500, no approval is needed; otherwise approve_lead must approve.", (">", 500.0)),
    ("Unless the refund exceeds $500, no approval is needed.", (">", 500.0)),
    ("Refunds of $500 or less are issued directly; otherwise approval from approve_lead is required.", (">", 500.0)),
    ("Refunds over $500 need approval from approve_lead; smaller refunds are issued directly.", (">", 500.0)),
    ("İade tutarı 500 TL'yi aşmıyorsa onay gerekmez, aksi halde approve_lead onayı alınır.", (">", 500.0)),
    ("500 TL'den fazla değilse iade doğrudan yapılır; aksi takdirde approve_lead onayı gerekir.", (">", 500.0)),
    ("İade 500 TL'yi geçerse approve_lead onayı gerekir, geçmezse iade doğrudan yapılır.", (">", 500.0)),
    # Neither asks for the approval nor waives it next to the amount: no threshold, approval at every amount.
    ("If the amount is $500 or less, issue it; for anything larger approve_lead is asked.", None),
])
def test_a_negated_threshold_puts_approval_on_the_right_side_or_everywhere(text, want):
    """Red team: "if it does not exceed X, no approval is needed; otherwise approval" let amounts above X skip the
    approval. The threshold is read where the checks apply; when that is unclear, money rules fail closed."""
    from agent_forge.sop import approval_threshold

    assert approval_threshold(text) == want


@pytest.mark.parametrize("text", [
    "If the amount is not in excess of $500, approval is not required.",
    "If the refund isn't more than $500, approval isn't required.",
    "When the amount is not above $500, approval can be skipped.",
    "Approval is not needed if the amount does not exceed $500.",
    "Tutar 500 TL'yi aşmıyorsa onaya gerek yoktur.",
    "Tutar 500 TL'nin üzerinde değilse onay aranmaz.",
    "500 TL'nin üzerinde olmayan iadelerde onay gerekmemektedir.",
    "Tutar 500 TL'yi geçmediği sürece onaya ihtiyaç yoktur.",
    "İade 500 TL'yi aşmazsa onay alınmadan yapılır.",
])
def test_two_negations_resolve_to_approval_above_the_amount(text):
    from agent_forge.sop import approval_threshold

    assert approval_threshold(text) == (">", 500.0)


@pytest.mark.parametrize("text,want", [
    # The boundary amount lands where the SOP puts it: "below X, no approval; if not, approval" asks at X.
    ("If the refund is below $500, no approval is needed; if not, approve_lead must approve.", (">=", 500.0)),
    # A lower approval "is enough" below the amount is a waiver of the approval tool there.
    ("Below $500 a team lead approval is enough; above it, approve_manager must approve.", (">=", 500.0)),
    ("500 TL altındaki iadelerde ekip lideri onayı yeterlidir; üzerindekiler approve_manager onayına gider.",
     (">=", 500.0)),
    ("Amounts that are not above $500 are not asked for approval; the other ones go to approve_lead.", (">", 500.0)),
])
def test_threshold_boundary_and_lower_approval_waivers(text, want):
    from agent_forge.sop import approval_threshold

    assert approval_threshold(text) == want


def test_a_threshold_never_waives_approval_above_the_amount():
    """Monotone: approval asked only at or under an amount and waived above it is a misreading, so the rule fails
    closed (approval at every amount), whatever the wording."""
    from agent_forge.sop import approval_threshold

    assert approval_threshold("If the amount does not exceed $500, approval from approve_lead is required.") is None


@pytest.mark.parametrize("rules", [
    ["If the policyholder asks for a payment plan, the plan is recorded with record_plan after approve_manager has "
     "approved it; the plan is calculated with compute_plan."],
    ["If the policyholder asks for a payment plan, the plan is recorded with record_plan.",
     "The plan requires approval from approve_manager.", "The plan is calculated with compute_plan."],
    ["Müşteri yapılandırma isterse plan record_plan ile kaydedilir, approve_manager onayı alınır ve plan compute_plan "
     "ile hesaplanır."],
])
def test_a_chain_follows_what_each_step_consumes(rules):
    """Red team: the step that computes the plan ran after the plan was approved and recorded. Approval and
    recording consume what the computing step produces, so that order holds whatever the wording says."""
    from agent_forge.sop import link_clauses, parse_sop, situation_steps

    cl = parse_sop("# T\n\n## 4. Plan\n\n" + "\n".join(f"4.{i + 1} {r}" for i, r in enumerate(rules)) + "\n")[1]
    j = link_clauses(cl)["joins"].get("record_plan")
    steps = j["checks"] + ["record_plan"] if j else situation_steps(cl[0].text, ["record_plan", "approve_manager",
                                                                                  "compute_plan"])[1]
    assert steps == ["compute_plan", "approve_manager", "record_plan"]


@pytest.mark.parametrize("rules", [
    ["If the policyholder asks for a payment plan, the plan is calculated with compute_plan.",
     "The calculated plan is sent to approve_manager for approval.",
     "If the supervisor approves, the plan is recorded with save_plan."],
    ["If the policyholder asks for a payment plan, the plan is calculated with compute_plan.",
     "The calculated plan requires approval: first approve_lead, then approve_manager.",
     "save_plan is not called until both approvals are in."],
])
def test_the_chain_ends_in_the_write_whatever_clause_names_the_compute_step(rules):
    """Red team: with the compute step named in the situation clause, it became the join's action and the write
    a check, so the plan was computed last. The write the chain ends in is the action."""
    from agent_forge.sop import link_clauses, parse_sop

    cl = parse_sop("# T\n\n## 4. Plan\n\n" + "\n".join(f"4.{i + 1} {r}" for i, r in enumerate(rules)) + "\n")[1]
    j = link_clauses(cl)["joins"]["compute_plan"]
    assert j["action"] == "save_plan" and j["checks"][0] == "compute_plan" and j["checks"][-1].startswith("approve")


def test_the_plan_is_computed_below_the_approval_threshold_too(tmp_path):
    en = EN.read_text(encoding="utf-8")
    en = en[:en.index("## 13. Premium refund")] + (
        "## 13. Payment plan\n\n13.1 If the policyholder asks for a payment plan, the plan is calculated with "
        "compute_plan.\n13.2 Plans over $500 require approval from approve_manager; smaller plans are recorded "
        "directly.\n13.3 The plan is recorded with save_plan, always last and only after approval.\n")
    sop = tmp_path / "en.md"
    sop.write_text(en, encoding="utf-8")
    res = forge(sop, None, k=1, mutate=False)
    runs = {r.persona: [c["name"] for c in r.tool_calls if c["ok"]] for r in res.topo_after.runs}
    assert runs["save_plan"] == ["verify_identity", "compute_plan", "approve_manager", "save_plan"]
    assert runs["save_plan_no_approval"] == ["verify_identity", "compute_plan", "save_plan"]
    assert check_workflow(freya_multiagent_workflow(res.topology)) == []


@pytest.mark.parametrize("sec", [
    "13.1 If the policyholder asks for a refund of a premium already paid, the request is recorded with "
    "record_request and then sent to approve_manager; only if it is approved is the refund paid with issue_refund.\n",
    "13.1 If the policyholder asks for a refund of a premium already paid, the request is recorded with "
    "record_request.\n13.2 The recorded request is then sent to approve_manager for approval.\n13.3 If approved, "
    "the refund is paid with issue_refund.\n",
])
def test_a_stated_order_holds_and_only_the_approved_step_is_gated(tmp_path, sec):
    """Red team: "record the request, send it for approval, pay only if approved" lost its order and paid before
    the approval. The stated order is binding; roles from tool names only fill gaps; the gated step is the one
    the approval clause names."""
    en = EN.read_text(encoding="utf-8")
    en = en[:en.index("## 13. Premium refund")] + "## 13. Premium refund\n\n" + sec
    sop = tmp_path / "en.md"
    sop.write_text(en, encoding="utf-8")
    res = forge(sop, None, k=1, mutate=False)
    runs = {r.persona: [c["name"] for c in r.tool_calls if c["ok"]] for r in res.topo_after.runs}
    assert runs["issue_refund"] == ["verify_identity", "record_request", "approve_manager", "issue_refund"]
    assert "issue_refund" not in runs["issue_refund_declined"]
    fs = {f.text() for f in res.exam.formulas}
    assert "G(call:issue_refund → ¬O denied:approve_manager)" in fs and "G(call:issue_refund → O tool:approve_manager)" in fs


@pytest.mark.parametrize("sec,tool,want", [
    ("13.1 If the policyholder asks for a new card, first the request is recorded with record_request.\n13.2 After "
     "that, the request is sent to approve_manager.\n13.3 If approved, the card is activated with activate_card; "
     "otherwise the call is transferred to a human agent.\n", "activate_card",
     ["record_request", "approve_manager", "activate_card"]),
    ("13.1 If the policyholder asks for a payment plan, eligibility is checked with check_eligibility, then the plan "
     "is calculated with calculate_plan and sent to approve_manager; if approved, it is saved with save_plan, "
     "otherwise the call is transferred to a human agent.\n", "save_plan",
     ["check_eligibility", "calculate_plan", "approve_manager", "save_plan"]),
])
def test_first_steps_and_lookups_keep_their_place_and_a_no_transfers(tmp_path, sec, tool, want):
    """Red team: a first step with a record-type name was moved after the approval, and a check_ lookup after the
    commit, with a rejected approval ending the call instead of transferring."""
    en = EN.read_text(encoding="utf-8")
    en = en[:en.index("## 13. Premium refund")] + "## 13. Request\n\n" + sec
    sop = tmp_path / "en.md"
    sop.write_text(en, encoding="utf-8")
    res = forge(sop, None, k=1, mutate=False)
    runs = {r.persona: r for r in res.topo_after.runs}
    assert [c["name"] for c in runs[tool].tool_calls if c["ok"]] == ["verify_identity"] + want
    assert runs[f"{tool}_declined"].outcome == "transfer"
    assert tool not in [c["name"] for c in runs[f"{tool}_declined"].tool_calls]


def test_every_step_of_the_situation_clause_stays_in_the_chain(tmp_path):
    en = EN.read_text(encoding="utf-8")
    en = en[:en.index("## 13. Premium refund")] + (
        "## 13. Payment plan\n\n13.1 If the policyholder asks for a payment plan, the plan is calculated with "
        "calculate_plan and a draft is saved with save_draft.\n13.2 After the draft is saved, it is sent to "
        "approve_manager.\n13.3 If approved, the plan is activated with activate_plan; if not, the call is "
        "transferred to a human agent.\n")
    sop = tmp_path / "en.md"
    sop.write_text(en, encoding="utf-8")
    res = forge(sop, None, k=1, mutate=False)
    runs = {r.persona: r for r in res.topo_after.runs}
    assert [c["name"] for c in runs["activate_plan"].tool_calls if c["ok"]] == [
        "verify_identity", "calculate_plan", "save_draft", "approve_manager", "activate_plan"]
    assert runs["activate_plan_declined"].outcome == "transfer"


def test_unanswered_identity_questions_count_as_attempts(tmp_path):
    """Red team: after the phone was handed over, the new speaker said the customer was not there; the identity
    question was repeated with no limit. Unanswered turns count against the node's attempt limit."""
    sop = tmp_path / "tr.md"
    sop.write_text("\n".join(l for l in TR.read_text(encoding="utf-8").splitlines() if not l.startswith("3.3 ")),
                   encoding="utf-8")
    res = forge(sop, None, k=1, mutate=False)
    p = next(p for p in res.exam.personas if p.id == "third_party_handover")
    s = CallSession(res.topology)
    s.open()
    s.on_user(p.behaviour["first_line"])
    s.on_user(p.behaviour["interject"]["text"])
    for _ in range(4):
        s.on_user("Kendisi burada değil ki.")
        if s.st.done:
            break
    assert s.st.done == "transfer"


def test_the_exam_reads_the_approval_clause_itself(tmp_path, monkeypatch):
    """When both compilers share a misreading that pays before the approval, the exam's rule read from the
    approval clause alone still fails the build."""
    import agent_forge.exam as E
    import agent_forge.extract as X
    from agent_forge.sop import link_clauses

    def wrong(cl):
        link = link_clauses(cl)
        for j in link["joins"].values():
            j["action"], j["checks"], j["gates"] = "approve_manager", ["record_request", "issue_refund"], ["issue_refund"]
        return link

    monkeypatch.setattr(X, "link_clauses", wrong)
    monkeypatch.setattr(E, "link_clauses", wrong)
    en = EN.read_text(encoding="utf-8")
    en = en[:en.index("## 13. Premium refund")] + (
        "## 13. Premium refund\n\n13.1 If the policyholder asks for a refund of a premium already paid, the request is "
        "recorded with record_request.\n13.2 The recorded request is then sent to approve_manager for approval.\n"
        "13.3 If approved, the refund is paid with issue_refund.\n")
    sop = tmp_path / "en.md"
    sop.write_text(en, encoding="utf-8")
    res = forge(sop, None, k=1, mutate=False)
    assert res.summary()["topology"]["after"]["pass^k"] < 1.0
    assert any("G(call:issue_refund → O tool:approve_manager)" in why and "§13.3" in why
               for r in res.topo_after.runs for why in r.reasons)


def test_approvals_named_in_one_clause_run_before_what_they_approve(tmp_path):
    en = EN.read_text(encoding="utf-8")
    en = en[:en.index("## 13. Premium refund")] + (
        "## 13. Premium refund\n\n13.1 If the policyholder asks for a refund of a premium already paid, the refund is "
        "issued with issue_refund; if the refund does not exceed $500, no approval is needed, otherwise approve_lead "
        "and then approve_manager must approve first.\n")
    sop = tmp_path / "en.md"
    sop.write_text(en, encoding="utf-8")
    res = forge(sop, None, k=1, mutate=False)
    runs = {r.persona: [c["name"] for c in r.tool_calls if c["ok"]] for r in res.topo_after.runs}
    assert runs["issue_refund"][-3:] == ["approve_lead", "approve_manager", "issue_refund"]
    assert runs["issue_refund_no_approval"] == ["verify_identity", "issue_refund"]


@pytest.mark.parametrize("rules", [
    ["The refund requires approval from approve_manager.",
     "approve_manager may only be asked after approve_lead has approved."],
    ["Refunds need sign-off from approve_manager.", "Before that, approve_lead must approve the refund."],
    ["The refund requires approval from approve_manager and approve_lead.", "approve_lead must approve first."],
    ["İade için approve_manager onayı gerekir.", "Bu onaydan önce approve_lead onayı alınmalıdır."],
    ["İade için approve_manager ve approve_lead onayı gereklidir.", "İlk olarak approve_lead onayı alınır."],
])
def test_an_approval_chain_ordered_in_a_later_clause(rules):
    from agent_forge.sop import link_clauses, parse_sop

    head = "If the policyholder asks for a refund, the refund must be issued with issue_refund."
    body = "\n".join(f"4.{i + 2} {r}" for i, r in enumerate(rules))
    j = link_clauses(parse_sop(f"# T\n\n## 4. Refund\n\n4.1 {head}\n{body}\n")[1])["joins"]["issue_refund"]
    assert j["checks"] == ["approve_lead", "approve_manager"] and j["ordered"]


def test_retry_limit_said_as_fails_three_times():
    sop = EN.read_text(encoding="utf-8").replace(
        "After 2 failed verification attempts the call is transferred to a human agent.",
        "If verification fails three times, the call is transferred to a human agent.")
    spec = RuleExtractor().extract(*parse_sop(sop))
    assert spec.params["max_attempts"]["value"] == 3


@pytest.mark.parametrize("text,want", [
    ("500 TL'nin üzerindeki iadeler", (">", 500.0)), ("iade tutarı 500 TL'yi aşarsa", (">", 500.0)),
    ("tutar 500 TL'yi aşıyorsa", (">", 500.0)), ("500 TL'den fazlaysa", (">", 500.0)),
    ("500 TL'yi geçen iadeler", (">", 500.0)), ("500 liranın üzerinde", (">", 500.0)),
    ("500 TL'den yüksek iadelerde", (">", 500.0)), ("iade 500 TL'yi aştığında", (">", 500.0)),
    ("500 TL'yi aşmayan iadeler", ("<=", 500.0)), ("tutar 500 TL'yi geçmiyorsa", ("<=", 500.0)),
    ("500 TL'ye kadar", ("<=", 500.0)), ("if the refund exceeds $500", (">", 500.0)),
    ("refunds in excess of $1,000", (">", 1000.0)), ("$500 or more", (">=", 500.0)), ("below $500", ("<", 500.0)),
    ("not exceeding $500", ("<=", 500.0)), ("son 4 hanesi ile", None), ("2 gün içinde", None),
])
def test_amount_thresholds_in_the_ways_people_write_them(text, want):
    from agent_forge.sop import threshold_of

    assert threshold_of(text) == want


def test_caller_lines_are_grammatical_first_person():
    from agent_forge.exam import _Writer

    w = _Writer.__new__(_Writer)
    w.lang = "tr"
    assert [w._first_person(c) for c in ("kartının çalındığını", "adresinin değiştiğini",
                                         "ödeme süresinin uzatılmasını")] == [
        "kartımın çalındığını", "adresimin değiştiğini", "ödeme süremin uzatılmasını"]
    assert w._first_person("kartınızın kaybolduğunu") == "kartımın kaybolduğunu"
    assert w._first_person("borcunu yapılandırmak") == "borcumu yapılandırmak"  # the object, not the verb
    assert w._first_person("kartının çalındığını") == "kartımın çalındığını"


def test_situation_tools_carry_their_own_identity_rule(grown_tr):
    _, t, _, _, _ = grown_tr
    fs = {f.text() for f in ltl.formulas(t.agent("core").spec)}
    assert "G(call:schedule_callback → O event:identity_verified)" not in fs  # third party: before verification
    assert "G(call:save_promise → O event:identity_verified)" in fs


def test_freya_export_maps_handback_to_a_return_edge(grown_tr):
    _, t, _, _, _ = grown_tr
    wf = freya_multiagent_workflow(t)
    back = [e for e in wf["edges"] if e.get("handback")]
    assert back and all(e["targetVariable"] == "returnTo" and e["source"].split(".")[0] in ("update_address", "block_card", "extend_due_date")
                        for e in back)
    into = [e for e in wf["edges"] if e.get("handoff") and e["target"].startswith(("update_address.", "block_card.", "extend_due_date."))]
    assert into and all(e["setVariables"]["returnTo"] == e["source"] for e in into)


def test_a_lookup_ahead_of_the_promise_does_not_replace_its_recorder(tmp_path):
    # Found by the tools thread: a new tool in §4 used to take over the promise node, silently.
    sop = tmp_path / "sop.md"
    sop.write_text(TR.read_text(encoding="utf-8").replace(
        "gecikmiş tutarın %10'undan az olamaz.", "gecikmiş tutarın %10'undan az olamaz.\n4.4 Ödeme sözü alınmadan önce "
        "yapılandırma seçenekleri plan_options ile hesaplanır."), encoding="utf-8")
    spec, exam = compile_sop(sop)
    nodes = {n.id: n for n in spec.nodes}
    assert nodes["promise"].tool == "save_promise" and nodes["plan_options"].kind == "function"
    assert [e.to for e in nodes["inform"].edges] == ["plan_options"]
    assert not spec.tool("plan_options").side_effect
    assert "G(call:save_promise → O tool:plan_options)" in {f.text() for f in exam.formulas}
    res = forge(sop, None, k=1, mutate=False)
    assert res.summary()["after"]["pass^k"] == 1.0


# -- Dates at the read-back, and two-layer perception -------------------------------

from agent_forge.perceive import CascadePerception  # noqa: E402
from agent_forge.slots import dates, parse_date_corrected  # noqa: E402


def test_dates_said_and_corrected():
    assert parse_date_corrected("20 ekim, yok pardon 25 ekim.") == "25.10"
    assert parse_date_corrected("On 20 october, sorry, I mean october 25.") == "25.10"
    assert [v for _, v in dates("Evet, yalnız 25 ekimde ödeyeceğim.")] == ["25.10"]
    assert [v for _, v in dates("Yes, except I'll pay on the 25th of october.")] == ["25.10"]
    assert numbers("Evet, 25.10.2026") == [] and numbers("12.450 TL") == [(0, 12450.0)]  # a date is not an amount


def test_date_correction_at_the_read_back():
    p = RulePerception()
    assert p.confirm("Tutar doğru ama tarih 25 ekim olsun.", 5000, "20.10") == ("correction", "25.10")
    assert p.confirm("Evet, doğru.", 5000, "20.10") == ("yes", None)
    final, _, _ = repair(draft(TR), k=2)
    assert final.slot("pay_date").confirm and final.slot("pay_date").confirm_source == ["4.2"]


class _Counting(RulePerception):
    name = "counting"

    def __init__(self):
        self.asked = []

    def intents(self, text, options, lang="tr"):
        self.asked.append((text, sorted(options)))
        return super().intents(text, options, lang)

    def confirm(self, text, current=None, current_date=None):
        self.asked.append((text, "confirm"))
        return super().confirm(text, current, current_date)


def test_cascade_asks_the_model_only_where_rules_are_unsure():
    slow = _Counting()
    c = CascadePerception(RulePerception(), slow)
    opts = {"dispute": ["itiraz"], "hardship": ["isimi kaybettim"]}
    for plain in ("Doğum tarihim 12.03.1985.", "Son dört hanesi 4567.", "5 bin lira yatırabilirim.", "ııı evet doğru"):
        c.intents(plain, opts, "tr")
    assert slow.asked == []
    assert c.confirm("Evet, doğru.", 5000, "20.10") == ("yes", None) and slow.asked == []
    c.intents("Bu borç benim değil, itiraz ediyorum.", opts, "tr")  # a matched situation is confirmed by the model
    c.intents("İtirazım yok ama biraz zaman lazım.", opts, "tr")  # free talk with a negated cue
    c.confirm("Evet ama aslında emin değilim.", 5000, "20.10")  # a hedge
    assert len(slow.asked) == 3
    # The router and the agent asking about the same words cost one model call, with every label at once.
    c.intents("Bu arada adresim değişti.", {"update_address": ["adres.*degis"]}, "tr")
    c.intents("Bu arada adresim değişti.", {"dispute": ["itiraz"]}, "tr")
    assert len(slow.asked) == 4 and slow.asked[-1][1] == ["dispute", "hardship", "update_address"]


# -- The guard's second opinion ------------------------------------------------------

from agent_forge.judge import CascadeGuard, evaluate_guard, risky  # noqa: E402
from agent_forge.spec import guard_policy  # noqa: E402
from voice_contract.contract import compile_policy, normalize  # noqa: E402


class _StubJudge:
    """Flags a threat in other words, the way a model would; records what it was asked."""

    name = "stub"

    def __init__(self):
        self.asked = []

    def check(self, reply, rules, lang):
        self.asked.append((reply, [r.id for r in rules]))
        f = fold(reply)
        bad = {"mahkeme": "threat", "icra": "threat", "el kon": "threat", "court": "threat", "soz veriyorum": "no guarantee",
               "kesinlikle ayarla": "no guarantee", "on iki bin": "gate", "dort bir bir bir": "pii"}
        for cue, what in bad.items():
            if cue in f:
                r = next((r for r in rules if what in r.description or what == r.kind or
                          (what == "gate" and r.kind == "gated_topic") or (what == "pii" and r.kind == "pii_leak")), None)
                if r:
                    return [r.id], cue
        return [], ""


def test_guard_probes_lexical_vs_two_layers():
    spec, exam = compile_sop(TR)
    final, _, _ = repair(spec, k=1, oracle=exam.contract())
    contract = compile_policy(guard_policy(final))
    assert {p["source"][0] for p in exam.guard_probes} >= {"3.2", "5.1", "5.2", "7.1"}
    alone = evaluate_guard(contract, exam.guard_probes, "tr")
    assert alone["lexical"] < 0.6  # paraphrases slip past word lists
    judge = _StubJudge()
    both = evaluate_guard(contract, exam.guard_probes, "tr", CascadeGuard(judge))
    assert both["two_layer"] == 1.0 and both["misses"] == []
    # Safe replies with nothing risky in them never reach the judge.
    assert not any("yardımcı olmak için buradayım" in a for a, _ in judge.asked)
    assert not risky("Size yardımcı olmak için buradayım.") and risky("on iki bin lira")


def test_semantic_block_replaces_the_reply_before_it_is_spoken():
    spec, exam = compile_sop(TR)
    final, _, _ = repair(spec, k=1, oracle=exam.contract())

    class Threatening(NaiveAgentModel):
        def respond(self, ctx):
            return "Bu böyle giderse sizi mahkemede görürüz." if ctx.state.node == "promise" else super().respond(ctx)

    m = Threatening()
    m.guard_judge = CascadeGuard(_StubJudge())
    rt = WorkflowRuntime(final, m)
    rt.open()
    rt.on_user("Doğum tarihim 12.03.1985.")
    out = rt.on_user("Son dört hanesi 4567.")
    assert "mahkeme" not in out.lower()
    ev = [e for e in rt.guard_events if e.get("layer") == "semantic"]
    assert ev and ev[0]["rule"] == "VC-5.1"


def test_a_negated_forbidden_topic_gets_a_second_look_not_a_block():
    """Red team: a reply that names a forbidden topic only to refuse it was blocked by the word list and never
    reached the judge. Now the judge reads it and may clear it; it is spoken as written and the clearance logged."""
    from agent_forge import judge as J

    J._MEMO.clear()
    spec, exam = compile_sop(TR)
    final, _, _ = repair(spec, k=1, oracle=exam.contract())
    refusal = "Faiz indirimi konusunda size hiçbir garanti veremem."

    class Careful(NaiveAgentModel):
        def respond(self, ctx):
            return refusal if ctx.state.node == "promise" else super().respond(ctx)

    contract = compile_policy(guard_policy(final))
    assert any(r.matches(normalize(refusal, "tr")) for r in contract.rules if r.kind == "forbidden")  # word list hit
    m = Careful()
    m.guard_judge = CascadeGuard(_StubJudge())
    rt = WorkflowRuntime(final, m)
    rt.open()
    rt.on_user("Doğum tarihim 12.03.1985.")
    out = rt.on_user("Son dört hanesi 4567.")
    assert refusal in out
    assert any(e["action"] == "cleared" for e in rt.guard_events)
    # An affirmative guarantee is still blocked by the word list in microseconds, with no model call.
    g = CascadeGuard(_StubJudge())
    assert g.review("Faiz indirimini garanti ediyoruz.", contract, {"identity_verified"}, "tr") == (None, "")
    assert g.stats["lexical"] == 1 and not g.slow.asked


def test_builder_sentences_are_judged_once_at_build_time():
    """Red team: most replies reached the model at run time. The builder's own sentences are judged in one batch
    before any call; a call made only of them asks the model nothing."""
    from agent_forge import judge as J

    J._MEMO.clear()
    spec, exam = compile_sop(TR)
    final, _, _ = repair(spec, k=1, oracle=exam.contract())
    stub = _StubJudge()
    g = CascadeGuard(stub)
    rep = g.prejudge(final, compile_policy(guard_policy(final)), "tr")
    assert rep["templates"] > 5 and rep["flagged"] == []
    m = NaiveAgentModel()
    m.guard_judge = g
    p = next(p for p in final.personas if p.id == "cooperative")
    run = run_persona(final, p, 0, exam.contract(), Backends(lambda: m, ScriptedCaller))
    assert run.verdict == "pass"
    assert g.stats["judged"] == 0 and g.stats["known"] > 0


def test_solver_finds_dead_tools_and_vacuous_rules():
    from agent_forge.spec import Constraint
    from agent_forge.verify import available, static_check

    if not available():
        pytest.skip("z3-solver not installed")
    spec = draft(TR)
    ok = static_check(spec)
    assert ok["solver"] and ok["rules"] >= 3 and ok["findings"] == []
    t = spec.tool("save_promise")
    t.constraints.append(Constraint("amount", "<=", "overdue", 0.05, ["9.9"]))  # contradicts §4.3's at least 10%
    t.constraints.append(Constraint("amount", ">=", "overdue", 0.0, ["9.8"]))  # nothing can break this one
    found = static_check(spec)["findings"]
    assert any(x.startswith("dead tool `save_promise`") and "§4.3" in x and "§9.9" in x for x in found)
    assert any(x.startswith("vacuous rule") and "§9.8" in x for x in found)


def _refund_sop(tmp_path, clause: str) -> Path:
    head = EN.read_text(encoding="utf-8").split("## 13.")[0]
    sop = tmp_path / "sop.md"
    sop.write_text(head + "## 13. Premium refund\n\n13.1 " + clause + "\n", encoding="utf-8")
    return sop


_TWO_ACTIONS = ("If the policyholder asks for a refund of a premium already paid, for refunds over $500 the agent must "
                "get approval from the team lead with approve_lead and then from the manager with approve_manager; "
                "only if every approval is positive, the agent issues the refund with issue_refund and sends a "
                "receipt with send_receipt. If any approval is declined, the call is transferred to a human agent.")


def test_coordinated_actions_become_sequential_steps_after_every_approval():
    """"X and Y" in one clause: both run, in the stated order, after every approval; none is dropped."""
    from agent_forge.sop import _tools, gated_actions, join_of

    j = join_of(_TWO_ACTIONS, _tools(_TWO_ACTIONS))
    assert j["checks"] + [j["action"]] == ["approve_lead", "approve_manager", "issue_refund", "send_receipt"]
    assert j["gates"] == ["approve_lead", "approve_manager"] and j["acts"] == ["issue_refund", "send_receipt"]
    t = ("the agent must get approval with approve_manager; if approved, the agent cancels the policy with "
         "cancel_policy and issues the refund with issue_refund.")
    assert gated_actions(t, _tools(t)) == ["cancel_policy", "issue_refund"]
    j = join_of(t, _tools(t))
    assert j["checks"] + [j["action"]] == ["approve_manager", "cancel_policy", "issue_refund"]
    t2 = "the agent cancels the policy with cancel_policy and issues the refund with issue_refund only if approved by approve_manager."
    assert gated_actions(t2, _tools(t2)) == ["cancel_policy", "issue_refund"]


def test_two_actions_in_one_clause_build_green_and_wait_for_approval(tmp_path):
    res = forge(_refund_sop(tmp_path, _TWO_ACTIONS), tmp_path / "out", k=1, mutate=False)
    cap = next(c for c in res.final.capabilities if "13.1" in c["source"])
    assert cap["steps"] == ["approve_lead", "approve_manager", "issue_refund", "send_receipt"]
    assert res.unreached == [] and res.exam.uncovered() == []
    f = {x.text() for x in res.exam.formulas}
    assert any("send_receipt" in x and "denied:approve_manager" in x for x in f)
    assert not [r for r in res.topo_after.runs if r.verdict == "fail"]
    wf = json.loads((tmp_path / "out" / "freya_multiagent_workflow.json").read_text())
    assert {"issue_refund", "send_receipt"} <= {n.get("data", {}).get("function") for n in wf["nodes"]}


def test_a_dropped_action_stops_the_build_and_the_export_check_goes_red(tmp_path, monkeypatch):
    """A misreading both compilers share (the first coordinated action lost) is caught twice: the exam refuses the
    clause, and the exam's check on the export itself finds the tool no reachable step calls."""
    from agent_forge import sop as S
    from agent_forge.exam import UntestedClauses, unreached_tools

    orig = S.join_of

    def drops_first(text, tools):
        j = orig(text, tools)
        if j and j.get("acts"):
            j = {k: v for k, v in j.items() if k != "acts"}
            j["checks"] = [c for c in j["checks"] if c != "issue_refund"]
        return j

    monkeypatch.setattr(S, "join_of", drops_first)
    sop = _refund_sop(tmp_path, _TWO_ACTIONS)
    with pytest.raises(UntestedClauses, match="issue_refund not placed"):
        forge(sop, tmp_path / "out", k=1, mutate=False)
    res = forge(sop, tmp_path / "out", k=1, mutate=False, allow_untested=True)
    assert any("13.1" in u and "issue_refund" in u for u in res.unreached)
    wf = {"nodes": [{"id": "start", "type": "start"}, {"id": "a", "type": "function", "data": {"function": "x_y"}},
                    {"id": "b", "type": "function", "data": {"function": "z_w"}}],
          "edges": [{"source": "start", "target": "a"}]}
    clauses = [{"id": "1.1", "text": "Run x_y and then z_w.", "strength": "must"}]
    assert unreached_tools(clauses, wf) == ["§1.1 names z_w, which no reachable step of the export calls"]


def test_export_check_reads_how_a_clause_names_a_tool(tmp_path):
    """A tool named only to forbid it, or only in passing, does not need a reachable step: a forbidden one must
    have none, and one mentioned in passing is listed for review instead of turning the build red."""
    from agent_forge.exam import export_check, tool_roles

    assert tool_roles("Never call delete_account.") == {"delete_account": "prohibited"}
    assert tool_roles("delete_account asla kullanılmaz.") == {"delete_account": "prohibited"}
    assert tool_roles("The agent must not use issue_refund before identity is verified.") == {
        "issue_refund": "gated_prohibited"}
    assert tool_roles("Note: the back office maintains archive_call.") == {"archive_call": "note"}
    assert tool_roles("the agent must record the reason with record_dispute and must not ask for payment "
                      "afterwards.") == {"record_dispute": "action"}
    assert tool_roles("doğrulama verify_identity sistemiyle yapılır.") == {"verify_identity": "action"}
    sop = tmp_path / "sop.md"
    sop.write_text(EN.read_text(encoding="utf-8").replace(
        "6.1 Never read back a card number or IBAN aloud.",
        "6.1 Never read back a card number or IBAN aloud.\n6.2 Never call delete_account.\n"
        "6.3 Note: the back office maintains archive_call."), encoding="utf-8")
    res = forge(sop, tmp_path / "out", k=1, mutate=False)
    assert res.unreached == [] and res.exam.uncovered() == []
    assert res.export_review == ["§6.3 mentions archive_call without a step to run it; check by hand"]
    assert "G(call:delete_account → O allowed:delete_account)" in {f.text() for f in res.exam.formulas}
    wf = {"nodes": [{"id": "start", "type": "start"},
                    {"id": "a", "type": "function", "data": {"function": "delete_account"}}],
          "edges": [{"source": "start", "target": "a"}]}
    clauses = [{"id": "6.2", "text": "Never call delete_account.", "strength": "must_not"}]
    assert export_check(clauses, wf)[0] == ["§6.2 forbids delete_account, which a reachable step of the export calls"]


@pytest.mark.parametrize("clause,role", [
    ("If the policyholder asks for a fee waiver, don't use waive_fee even if they insist.", "prohibited"),
    ("Never call waive_fee, even when the policyholder insists.", "prohibited"),
    ("Müşteri istese bile waive_fee kullanılmaz.", "prohibited"),
    ("The agent must not use send_statement before identity is verified.", "gated_prohibited"),
    ("Never skip verify_identity.", "action"),
    ("verify_identity adımı atlanmaz.", "action"),
    ("Do not forget to record the reason with record_dispute.", "action"),
])
def test_concessions_gates_and_negated_skips(clause, role):
    """"Even if the customer asks" never turns a prohibition into a step; "never skip X" requires X."""
    from agent_forge.exam import tool_roles
    from agent_forge.sop import _tools, forbidden_tools

    t = _tools(clause)[0] if "verify_identity" not in clause else "verify_identity"
    assert tool_roles(clause)[t] == role
    assert (t in forbidden_tools(clause, [t])) == (role == "prohibited")


def test_a_concessive_prohibition_never_builds_the_forbidden_step(tmp_path):
    sop = tmp_path / "sop.md"
    sop.write_text(EN.read_text(encoding="utf-8").replace(
        "6.1 Never read back a card number or IBAN aloud.",
        "6.1 Never read back a card number or IBAN aloud.\n"
        "6.2 If the policyholder asks for a fee waiver, don't use waive_fee even if they insist.\n"
        "6.3 Never skip verify_identity."), encoding="utf-8")
    res = forge(sop, tmp_path / "out", k=1, mutate=False)
    assert "waive_fee" not in {c["tool"] for c in res.final.capabilities}
    assert res.unreached == [] and res.exam.uncovered() == []
    assert not [r for r in res.topo_after.runs if r.verdict == "fail"]
    gated = tmp_path / "gated.md"
    gated.write_text(EN.read_text(encoding="utf-8").replace(
        "6.1 Never read back a card number or IBAN aloud.",
        "6.1 Never read back a card number or IBAN aloud.\n"
        "6.2 The agent must not use send_statement before identity is verified."), encoding="utf-8")
    res = forge(gated, tmp_path / "out2", k=1, mutate=False)
    assert res.unreached == ["§6.2 allows send_statement only after a gate, but no reachable step of the export calls it"]


_REFUND_SECTION = ["If the policyholder asks for a refund of a premium already paid, the agent records the request with "
                   "record_request.", "For refunds over $500 the request must be approved with approve_manager.",
                   "If approved, the refund is issued with issue_refund; otherwise the call is transferred to a human "
                   "agent.", "Never use waive_fee, even if the policyholder asks."]


def _section_sop(tmp_path, lines) -> Path:
    head = EN.read_text(encoding="utf-8").split("## 13.")[0]
    sop = tmp_path / "sop.md"
    sop.write_text(head + "## 13. Premium refund\n\n" + "\n".join(f"13.{i + 1} {c}" for i, c in enumerate(lines)) + "\n",
                   encoding="utf-8")
    return sop


def test_a_concessive_prohibition_in_the_refund_section_keeps_the_approval(tmp_path):
    """The prohibition's "even if" made it look like a second situation, so the section's approval was not linked
    and large refunds went through without it."""
    spec, exam = compile_sop(_section_sop(tmp_path, _REFUND_SECTION))
    cap = next(c for c in spec.capabilities if "13.1" in c["source"])
    assert cap["steps"][-1] == "issue_refund" and cap["join"]["gates"] == ["approve_manager"]
    assert cap["join"]["threshold"]["value"] == 500 and exam.uncovered() == []


def test_a_prohibition_that_changes_what_approval_gates_stops_the_build(tmp_path, monkeypatch):
    """The guard does not depend on wording: with the old reader (the concession taken as a condition), leaving the
    prohibition out changes the gated set, and the build stops."""
    from agent_forge import sop as S

    monkeypatch.setattr(S, "drop_concessive", lambda t: t)
    monkeypatch.setattr(S, "forbidden_tools", lambda t, tools: set())
    _, exam = compile_sop(_section_sop(tmp_path, _REFUND_SECTION))
    assert "13.4 (prohibition changes what approval gates)" in exam.uncovered()
