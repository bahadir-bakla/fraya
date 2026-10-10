from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from agent_forge.policy_runtime import (
    CalendarPolicy, CloseDecision, CloseRules, MoneyPolicy, PolicyViolation,
    ProductPolicy, PromiseRuntime, RetryBudget, decimal_money, guard_money,
    guard_promise_date, guard_scheduled_datetime, reduce_close,
)


SOURCE = {"policy_document": "caller supplied policy", "revision": "test"}


def calendar(*, now="2031-04-02T11:15", holidays=(), weekmask=(0, 1, 2, 3, 4), week_start=0):
    return CalendarPolicy(datetime.fromisoformat(now), frozenset(holidays), frozenset(weekmask), week_start, SOURCE)


def money(*, minimum="10.05", maximum="100.00", quantum="0.01"):
    return MoneyPolicy(minimum, maximum, quantum, SOURCE)


def product(identifier, *, attempts=2, minimum="10.05", deadline="2031-04-15"):
    return ProductPolicy(identifier, money(minimum=minimum), date.fromisoformat(deadline), attempts, SOURCE)


def runtime(*ids, attempts=2, emit_product_notes=True):
    return PromiseRuntime([product(p, attempts=attempts) for p in ids], calendar=calendar(),
                          emit_product_notes=emit_product_notes, source_policy_parameters=SOURCE)


def rules():
    # Arbitrary non-bank enum values and schema names are deliberate.
    return CloseRules(
        recorded=CloseDecision("committed"), all_exempt=CloseDecision("already_settled"),
        exempt_reason="settled_elsewhere",
        reason_decisions={
            "unaffordable": CloseDecision("uncommitted", "price_barrier"),
            "write_failed": CloseDecision("uncommitted", "upstream_fault"),
            "contested": CloseDecision("uncommitted", "review_needed"),
        },
        transfer_decisions={"specialist": CloseDecision("routed", "escalation")},
        outcome_field="disposition_code", reason_field="detail_code",
        source_policy_parameters=SOURCE,
    )


def expect_violation(code, action):
    with pytest.raises(PolicyViolation) as exc:
        action()
    assert code in [v.code for v in exc.value.violations]
    assert all(set(v) == {"code", "path", "details"} for v in exc.value.to_dict()["violations"])
    return exc.value


def commit(run, identifier):
    attempt = run.begin_record(identifier)
    run.record_result(attempt, succeeded=True)
    return attempt


def flush(run):
    for identifier, _ in run.notes_to_flush():
        attempt = run.begin_note(identifier)
        run.note_result(attempt, succeeded=True)


def test_official_calendar_parameters_are_inputs_not_runtime_defaults():
    kit = Path(__file__).resolve().parents[3] / "competition-v3" / "build-the-builder"
    brief_a = (kit / "briefs" / "brief-a.md").read_text(encoding="utf-8")
    brief_b = (kit / "briefs" / "brief-b.md").read_text(encoding="utf-8")
    holiday_strings = ("2026-10-26", "2026-11-11", "2026-11-26", "2026-12-25", "2027-01-01")
    assert all(day in brief_a for day in holiday_strings)
    assert "12th business day" in brief_a and "7th business day" in brief_a
    assert "On any transfer" in brief_b and "add no notes at all" in brief_b
    policy = CalendarPolicy(
        datetime(2026, 10, 14, 11), frozenset(date.fromisoformat(s) for s in holiday_strings),
        frozenset(range(5)), 0, {"document": str(kit / "briefs" / "brief-a.md"), "rules": [18, 22]},
    )
    assert policy.add_business_days(policy.today, 7) == date(2026, 10, 23)
    assert policy.add_business_days(policy.today, 12) == date(2026, 11, 2)
    assert policy.next_business_day(date(2026, 10, 24), inclusive=True) == date(2026, 10, 27)


def test_changed_weekmask_holidays_offsets_and_injected_now():
    # This unrelated policy works Sunday through Thursday, with a different holiday.
    policy = calendar(now="2031-04-02T23:59", holidays=[date(2031, 4, 3)],
                      weekmask=(6, 0, 1, 2, 3), week_start=6)
    assert policy.today == date(2031, 4, 2)
    assert policy.add_business_days(policy.today, 3) == date(2031, 4, 8)
    assert policy.add_business_days(date(2031, 4, 8), -3) == policy.today
    assert policy.add_business_days(date(2031, 4, 4), 0) == date(2031, 4, 4)
    assert policy.next_business_day(date(2031, 4, 4), inclusive=True) == date(2031, 4, 6)
    assert policy.next_business_day(policy.today, inclusive=True) == policy.today
    assert policy.next_business_day(policy.today, inclusive=False) == date(2031, 4, 6)
    assert policy.last_business_day_of_week(policy.today) == policy.today
    without_holiday = calendar(now="2031-04-02T23:59", weekmask=(6, 0, 1, 2, 3), week_start=6)
    assert without_holiday.add_business_days(without_holiday.today, 3) == date(2031, 4, 7)


def test_next_weekday_semantics_explicit_and_different_on_monday():
    policy = calendar(now="2031-03-31T11:15")
    assert policy.weekday_date(4, "next", next_weekday_semantics="following_calendar_week") == date(2031, 4, 11)
    assert policy.weekday_date(4, "next", next_weekday_semantics="next_occurrence") == date(2031, 4, 4)
    assert policy.weekday_date(4, "this", next_weekday_semantics="following_calendar_week") == date(2031, 4, 4)
    with pytest.raises(TypeError):
        policy.weekday_date(4, "next")
    friday = calendar(now="2031-04-04T11:15")
    assert friday.weekday_date(4, "next", next_weekday_semantics="following_calendar_week") == date(2031, 4, 11)
    sunday_start = calendar(now="2031-04-05T11:15", week_start=6)
    assert sunday_start.weekday_date(6, "next", next_weekday_semantics="following_calendar_week") == date(2031, 4, 6)


def test_date_guard_reports_multiple_violations_without_adjusting_input():
    policy = calendar(holidays=[date(2031, 4, 4)])
    assert guard_promise_date(policy.today, calendar=policy, deadline=date(2031, 4, 4)) == ()
    assert [v.code for v in guard_promise_date("2031-04-05", calendar=policy, deadline="2031-04-04")] == ["date_after_deadline", "non_business_day"]
    assert [v.code for v in guard_promise_date("2031-04-04", calendar=policy, deadline="2031-04-04")] == ["non_business_day"]
    assert [v.code for v in guard_promise_date("2031-04-01", calendar=policy, deadline="2031-04-04")] == ["date_before_today"]
    assert [v.code for v in guard_promise_date("invalid", calendar=policy, deadline="2031-04-04")] == ["invalid_date"]


def test_no_business_day_in_week_has_machine_readable_violation():
    monday = date(2031, 3, 31)
    policy = calendar(holidays=[monday + timedelta(days=i) for i in range(5)])
    expect_violation("no_business_day_in_week", lambda: policy.last_business_day_of_week(policy.today))
    expect_violation("invalid_weekmask", lambda: calendar(weekmask=()))
    expect_violation("invalid_business_day_offset", lambda: policy.add_business_days(policy.today, True))


def test_scheduling_uses_injected_time_offsets_and_inclusive_changed_window():
    policy = calendar(now="2031-04-04T13:30", holidays=[date(2031, 4, 7)])
    args = dict(calendar=policy, allowed_business_day_offsets=(0, 2), window_start=time(13, 30), window_end=time(22))
    assert guard_scheduled_datetime(datetime(2031, 4, 4, 22), **args) == ()
    assert guard_scheduled_datetime(datetime(2031, 4, 9, 13, 30), **args) == ()
    assert [v.code for v in guard_scheduled_datetime(policy.now, **args)] == ["scheduled_time_not_future"]
    assert [v.code for v in guard_scheduled_datetime(datetime(2031, 4, 8, 15), **args)] == ["scheduled_date_not_allowed"]
    assert [v.code for v in guard_scheduled_datetime(datetime(2031, 4, 9, 22, 1), **args)] == ["scheduled_time_outside_window"]
    invalid = guard_scheduled_datetime(datetime(2031, 4, 5, 10), **args)
    assert [v.code for v in invalid] == ["scheduled_date_not_allowed", "scheduled_time_outside_window"]


def test_scheduling_timezone_and_policy_input_errors_are_explicit():
    policy = calendar(now="2031-04-04T13:30+03:00")
    args = dict(calendar=policy, allowed_business_day_offsets=(0, 1), window_start=time(14), window_end=time(20))
    assert guard_scheduled_datetime(datetime(2031, 4, 4, 11, tzinfo=timezone.utc), **args) == ()
    assert [v.code for v in guard_scheduled_datetime(datetime(2031, 4, 4, 14), **args)] == ["incompatible_timezone"]
    assert [v.code for v in guard_scheduled_datetime("2031-04-04T14:00", **args)] == ["invalid_datetime"]
    assert [v.code for v in guard_scheduled_datetime(policy.now, **{**args, "window_start": time(21)})] == ["invalid_time_window"]
    assert [v.code for v in guard_scheduled_datetime(policy.now, **{**args, "allowed_business_day_offsets": (True,)})] == ["invalid_business_day_offset"]


def test_money_floor_ceiling_and_precision_are_decimal_exact():
    policy = money()
    assert guard_money("10.05", policy=policy) == ()
    assert guard_money("100.00", policy=policy) == ()
    assert [v.code for v in guard_money("10.04", policy=policy)] == ["amount_below_floor"]
    assert [v.code for v in guard_money("100.01", policy=policy)] == ["amount_above_ceiling"]
    assert [v.code for v in guard_money("10.051", policy=policy)] == ["amount_off_quantum"]
    assert decimal_money("0.1") + decimal_money("0.2") == Decimal("0.3")
    huge = money(minimum="0", maximum="999999999999999999999999999999999999.99")
    with localcontext() as context:
        context.prec = 2
        assert guard_money("123456789012345678901234567890.01", policy=huge) == ()


@pytest.mark.parametrize("value", [True, False, 10.05, None, "not money", "NaN", "Infinity", Decimal("-Infinity")])
def test_invalid_amounts_are_not_coerced_or_recorded(value):
    assert guard_money(value, policy=money())


def test_renamed_backend_fields_and_changed_floor_require_no_bank_assumptions():
    backend = {"contract_key": "z-last", "arrears_units": "90.00", "minimum_units": "22.50"}
    policy = MoneyPolicy(backend["minimum_units"], backend["arrears_units"], "0.50", SOURCE)
    config = ProductPolicy(backend["contract_key"], policy, date(2031, 4, 9), 4, SOURCE)
    run = PromiseRuntime([config], calendar=calendar(), emit_product_notes=True, source_policy_parameters=SOURCE)
    expect_violation("amount_below_floor", lambda: run.propose("z-last", "22.00", "2031-04-03"))
    expect_violation("amount_off_quantum", lambda: run.propose("z-last", "22.60", "2031-04-03"))
    run.propose("z-last", "22.50", "2031-04-03")
    run.confirm(run.readback(), accepted=True)
    commit(run, "z-last")
    decision = run.finalize_non_transfer(rules())
    assert decision.to_payload(outcome_field="result_status", reason_field="result_detail") == {"result_status": "committed"}
    assert run.begin_close() == decision


def test_retry_budget_changed_and_exempt_attempts():
    budget = RetryBudget(4, {"retries": 3, "source": "independent policy"})
    budget.consume(counted=False)
    assert (budget.used, budget.remaining) == (0, 4)
    for _ in range(4):
        budget.consume()
    expect_violation("retry_budget_exhausted", budget.consume)
    expect_violation("retry_budget_exhausted", lambda: budget.consume(counted=False))
    assert budget.used == 4
    expect_violation("retry_budget_exhausted", RetryBudget(0, SOURCE).consume)
    expect_violation("invalid_retry_budget", lambda: RetryBudget(True, SOURCE))


def test_source_policy_parameters_are_required_and_not_mutated():
    with pytest.raises(TypeError):
        MoneyPolicy("1", "2", "0.01")
    expect_violation("source_policy_parameters_required", lambda: MoneyPolicy("1", "2", "0.01", {}))
    inputs = {"document": "policy-v2"}
    policy = MoneyPolicy("1", "2", "0.01", inputs)
    inputs["document"] = "policy-v3"
    assert policy.source_policy_parameters["document"] == "policy-v2"
    with pytest.raises(TypeError):
        policy.source_policy_parameters["document"] = "other"


def test_proposed_confirmed_and_recorded_are_distinct_and_success_only():
    run = runtime("subscription")
    terms = run.propose("subscription", "20.00", "2031-04-03")
    assert run.state("subscription").proposed == terms
    assert run.state("subscription").confirmed is None
    assert run.state("subscription").recorded is None
    expect_violation("promise_not_confirmed", lambda: run.begin_record("subscription"))
    expect_violation("explicit_confirmation_required", lambda: run.confirm(run.readback(), accepted="yes"))
    run.confirm(run.readback(), accepted=False)
    expect_violation("promise_not_confirmed", lambda: run.begin_record("subscription"))
    run.confirm(run.readback(), accepted=True)
    assert run.state("subscription").confirmed == terms
    attempt = run.begin_record("subscription")
    assert run.state("subscription").recorded is None
    expect_violation("explicit_backend_result_required", lambda: run.record_result(attempt, succeeded={"success": True}))
    run.record_result(attempt, succeeded=False)
    assert run.state("subscription").recorded is None
    commit(run, "subscription")
    state = run.state("subscription")
    assert state.recorded == terms and state.proposed is None and state.confirmed is None
    with pytest.raises(FrozenInstanceError):
        state.recorded = None
    expect_violation("recorded_promise_immutable", lambda: run.propose("subscription", "25", "2031-04-04"))
    expect_violation("recorded_product_has_note", lambda: run.set_note("subscription", "contested"))


@pytest.mark.parametrize("new_amount,new_day", [("21.00", "2031-04-03"), ("20.00", "2031-04-04")])
def test_correction_invalidates_entire_batch_and_old_readback(new_amount, new_day):
    run = runtime("z", "a")
    for p in run.product_order:
        run.propose(p, "20.00", "2031-04-03")
    old = run.readback()
    assert [p.product_id for p in old.promises] == ["z", "a"]
    run.confirm(old, accepted=True)
    run.propose("a", new_amount, new_day)
    assert all(run.state(p).confirmed is None for p in run.product_order)
    expect_violation("stale_readback", lambda: run.confirm(old, accepted=True))
    expect_violation("promise_not_confirmed", lambda: run.begin_record("z"))
    run.confirm(run.readback(), accepted=True)
    commit(run, "z")
    commit(run, "a")
    assert run.state("a").recorded.amount == Decimal(new_amount)
    assert run.state("a").recorded.date == date.fromisoformat(new_day)


@pytest.mark.parametrize("amount,day,code", [
    ("1", "2031-04-03", "amount_below_floor"),
    ("20", "2031-04-30", "date_after_deadline"),
    ("NaN", "2031-04-03", "nonfinite_money"),
    ("20", "invalid", "invalid_date"),
])
def test_invalid_correction_revokes_batch_confirmation_before_validation(amount, day, code):
    run = runtime("z", "a")
    for p in run.product_order:
        run.propose(p, "20", "2031-04-03")
    old_readback = run.readback()
    run.confirm(old_readback, accepted=True)
    prior = run.state("a").proposed
    expect_violation(code, lambda: run.propose("a", amount, day))
    assert run.state("a").proposed == prior
    assert all(run.state(p).confirmed is None for p in run.product_order)
    expect_violation("stale_readback", lambda: run.confirm(old_readback, accepted=True))
    expect_violation("promise_not_confirmed", lambda: run.begin_record("z"))
    assert all(run.state(p).attempts_used == 0 for p in run.product_order)


def test_backend_order_retry_exhaustion_and_partial_commit():
    run = runtime("z-first", "a-second", "m-third", attempts=3)
    for p in run.product_order:
        run.propose(p, "20", "2031-04-03")
    run.confirm(run.readback(), accepted=True)
    expect_violation("backend_order_violation", lambda: run.begin_record("a-second"))
    assert run.state("a-second").attempts_used == 0
    commit(run, "z-first")
    for _ in range(3):
        attempt = run.begin_record("a-second")
        run.record_result(attempt, succeeded=False)
    expect_violation("retry_budget_exhausted", lambda: run.begin_record("a-second"))
    expect_violation("backend_order_violation", lambda: run.begin_record("m-third"))
    confirmed_third = run.state("m-third").confirmed
    run.set_note("a-second", "write_failed")
    assert run.state("m-third").confirmed == confirmed_third
    commit(run, "m-third")
    assert run.state("z-first").recorded is not None
    assert run.state("a-second").recorded is None
    assert run.state("m-third").recorded is not None
    assert run.notes_to_flush() == ()
    assert run.finalize_non_transfer(rules()) == CloseDecision("committed")
    expect_violation("notes_not_recorded", run.begin_close)
    assert run.notes_to_flush() == (("a-second", "write_failed"),)
    flush(run)
    assert run.begin_close() == CloseDecision("committed")


def test_inflight_replayed_or_fabricated_backend_results_cannot_commit():
    run = runtime("z", "a")
    for p in run.product_order:
        run.propose(p, "20", "2031-04-03")
    run.confirm(run.readback(), accepted=True)
    attempt = run.begin_record("z")
    expect_violation("backend_action_in_flight", lambda: run.propose("a", "30", "2031-04-03"))
    expect_violation("backend_action_in_flight", lambda: run.begin_record("a"))
    expect_violation("backend_action_in_flight", lambda: run.begin_transfer("specialist", rules=rules()))
    expect_violation("unexpected_backend_result", lambda: run.record_result(replace(attempt), succeeded=True))
    assert run.state("z").recorded is None
    run.record_result(attempt, succeeded=True)
    expect_violation("unexpected_backend_result", lambda: run.record_result(attempt, succeeded=True))
    assert run.state("z").attempts_used == 1
    expect_violation("unexpected_backend_result", lambda: run.record_result(None, succeeded=True))


def test_transfer_discards_buffered_notes_and_unrecorded_promises_only():
    run = runtime("z", "a", "m")
    run.set_note("m", "contested")
    for p in ("z", "a"):
        run.propose(p, "20", "2031-04-03")
    run.confirm(run.readback(), accepted=True)
    commit(run, "z")
    expect_violation("notes_require_non_transfer_terminal", lambda: run.begin_note("m"))
    attempt = run.begin_transfer("specialist", rules=rules())
    assert run.state("z").recorded is not None
    assert run.state("a").recorded is None and run.state("a").confirmed is None
    assert run.state("a").proposed is None and run.state("m").note_reason is None
    assert run.notes_to_flush() == ()
    expect_violation("backend_action_in_flight", run.begin_close)
    run.transfer_result(attempt, succeeded=False)
    expect_violation("transfer_not_completed", run.begin_close)
    expect_violation("terminal_decision_locked", lambda: run.begin_record("a"))
    retry = run.begin_transfer("specialist", rules=rules())
    run.transfer_result(retry, succeeded=True)
    expect_violation("notes_require_non_transfer_terminal", lambda: run.begin_note("m"))
    assert run.begin_close() == CloseDecision("routed", "escalation")


@pytest.mark.parametrize("flush_first", [False, True])
def test_late_transfer_cannot_follow_notes_even_before_flush(flush_first):
    run = runtime("x")
    run.set_note("x", "unaffordable")
    assert run.notes_to_flush() == ()
    run.finalize_non_transfer(rules())
    if flush_first:
        flush(run)
    expect_violation("transfer_after_non_transfer_terminal", lambda: run.begin_transfer("specialist", rules=rules()))
    expect_violation("terminal_decision_locked", lambda: run.propose("x", "30", "2031-04-03"))
    assert run.state("x").note_reason == "unaffordable"
    if not flush_first:
        flush(run)
    assert run.begin_close() == CloseDecision("uncommitted", "price_barrier")


def test_note_failures_block_close_and_note_calls_follow_backend_order():
    run = runtime("z", "a")
    run.set_note("a", "unaffordable")
    run.set_note("z", "contested")
    assert run.finalize_non_transfer(rules()) == CloseDecision("uncommitted", "review_needed")
    assert run.notes_to_flush() == (("z", "contested"), ("a", "unaffordable"))
    expect_violation("backend_order_violation", lambda: run.begin_note("a"))
    failed = run.begin_note("z")
    run.note_result(failed, succeeded=False)
    expect_violation("notes_not_recorded", run.begin_close)
    assert run.state("z").note_recorded is False
    flush(run)
    assert all(run.state(p).note_recorded for p in run.product_order)
    run.begin_close()
    expect_violation("call_closed", run.begin_close)
    expect_violation("call_closed", lambda: run.begin_note("z"))
    expect_violation("call_closed", lambda: run.begin_transfer("specialist", rules=rules()))


def test_explicit_note_suppression_still_requires_dispositions_and_blocks_writes():
    run = runtime("subscription", emit_product_notes=False)
    expect_violation("unresolved_product", lambda: run.finalize_non_transfer(rules()))
    run.set_note("subscription", "unaffordable")
    assert run.finalize_non_transfer(rules()) == CloseDecision("uncommitted", "price_barrier")
    assert run.notes_to_flush() == ()
    assert not run.state("subscription").note_recorded
    expect_violation("product_notes_disabled", lambda: run.begin_note("subscription"))
    assert run.begin_close() == CloseDecision("uncommitted", "price_barrier")


def test_close_reduction_uses_supplied_reason_mapping_and_backend_order():
    arguments = dict(product_order=("z", "a", "m"), recorded_ids=(), rules=rules())
    notes = {"m": "contested", "a": "unaffordable", "z": "settled_elsewhere"}
    assert reduce_close(**arguments, notes=notes) == CloseDecision("uncommitted", "price_barrier")
    assert reduce_close(**{**arguments, "recorded_ids": ("z",)}, notes={"m": "contested", "a": "unaffordable"}) == CloseDecision("committed")
    assert reduce_close(**arguments, notes={p: "settled_elsewhere" for p in arguments["product_order"]}) == CloseDecision("already_settled")
    decision = reduce_close(**arguments, notes={}, transfer_reason="specialist")
    assert decision.to_payload(outcome_field=rules().outcome_field, reason_field=rules().reason_field) == {"disposition_code": "routed", "detail_code": "escalation"}


def test_close_reduction_never_fabricates_completeness():
    inputs = dict(product_order=("z", "a"), recorded_ids=(), notes={}, rules=rules())
    expect_violation("unresolved_product", lambda: reduce_close(**inputs))
    expect_violation("incomplete_products", lambda: reduce_close(**{**inputs, "product_order": ()}))
    expect_violation("unresolved_product", lambda: reduce_close(**{**inputs, "recorded_ids": ("z",)}))
    expect_violation("unknown_product", lambda: reduce_close(**{**inputs, "notes": {"extra": "contested"}}))
    expect_violation("unknown_note_reason", lambda: reduce_close(**{**inputs, "notes": {"z": "invented", "a": "contested"}}))
    expect_violation("recorded_product_has_note", lambda: reduce_close(**{**inputs, "recorded_ids": ("z",), "notes": {"z": "contested"}}))
    expect_violation("unknown_transfer_reason", lambda: reduce_close(**inputs, transfer_reason="made_up"))


def test_incomplete_finalization_does_not_lock_runtime_or_infer_a_note():
    run = runtime("z", "a")
    run.propose("z", "20", "2031-04-03")
    run.confirm(run.readback(), accepted=True)
    commit(run, "z")
    expect_violation("unresolved_product", lambda: run.finalize_non_transfer(rules()))
    assert run.state("a").note_reason is None
    run.set_note("a", "contested")
    run.finalize_non_transfer(rules())
    flush(run)
    assert run.begin_close() == CloseDecision("committed")


def test_unknown_transfer_does_not_abandon_confirmed_terms_or_notes():
    run = runtime("z", "a")
    run.set_note("a", "contested")
    run.propose("z", "20", "2031-04-03")
    run.confirm(run.readback(), accepted=True)
    before = tuple(run.state(p) for p in run.product_order)
    expect_violation("unknown_transfer_reason", lambda: run.begin_transfer("invented", rules=rules()))
    assert tuple(run.state(p) for p in run.product_order) == before
    commit(run, "z")


def test_per_product_dates_and_floors_are_independent():
    policies = [product("z", minimum="50", deadline="2031-04-03"), product("a", minimum="15", deadline="2031-04-10")]
    run = PromiseRuntime(policies, calendar=calendar(), emit_product_notes=True, source_policy_parameters=SOURCE)
    expect_violation("date_after_deadline", lambda: run.propose("z", "50", "2031-04-04"))
    expect_violation("amount_below_floor", lambda: run.propose("z", "20", "2031-04-03"))
    run.propose("z", "50", "2031-04-03")
    run.propose("a", "20", "2031-04-04")
    run.confirm(run.readback(), accepted=True)
    for p in run.product_order:
        commit(run, p)
    assert run.state("z").recorded != run.state("a").recorded
