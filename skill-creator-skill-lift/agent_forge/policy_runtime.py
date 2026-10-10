"""Deterministic policy primitives; no policy extraction, tools, clock, or LLM I/O.

Every policy requires ``source_policy_parameters``: the supplied parameters and
their provenance belong to the caller, not to this module. Weekdays use Python's
Monday=0 convention. Amounts accept Decimal, decimal strings, or integers, never
floats. Backend adapters map their own schema names/results to these primitives.

Typical lifecycle::

    runtime.propose(product_id, "125.00", "2031-04-02")
    readback = runtime.readback()      # present every term to the caller
    runtime.confirm(readback, accepted=True)
    attempt = runtime.begin_record(product_id)
    runtime.record_result(attempt, succeeded=True)  # only after backend success
    runtime.finalize_non_transfer(close_rules)
    # begin_note/note_result for notes_to_flush(), then begin_close()

Corrections invalidate the entire outstanding read-back. Successful writes stay
immutable. Notes are buffered until an irrevocable non-transfer terminal decision;
after that decision transfer is guarded, even before the first note is written.
This is an in-process coordinator, not a distributed transaction or durable log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class Violation:
    code: str
    path: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "path": self.path, "details": dict(self.details)}


class PolicyViolation(ValueError):
    def __init__(self, violations: Iterable[Violation]):
        self.violations = tuple(violations)
        super().__init__("; ".join(f"{v.path}: {v.code}" for v in self.violations))

    def to_dict(self) -> dict[str, Any]:
        return {"violations": [v.to_dict() for v in self.violations]}


def _require(condition: bool, code: str, path: str, **details: Any) -> None:
    if not condition:
        raise PolicyViolation((Violation(code, path, details),))


def _sources(value: Mapping[str, Any]) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping) and bool(value),
             "source_policy_parameters_required", "source_policy_parameters")
    return MappingProxyType(dict(value))


def _date(value: date | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        if isinstance(value, str):
            return date.fromisoformat(value)
    except ValueError:
        pass
    raise PolicyViolation((Violation("invalid_date", "date"),))


def decimal_money(value: Decimal | str | int) -> Decimal:
    """Preserve decimal inputs exactly, rejecting floats and nonfinite amounts."""
    _require(isinstance(value, (Decimal, str, int)) and not isinstance(value, bool),
             "invalid_money", "amount", input_type=type(value).__name__)
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise PolicyViolation((Violation("invalid_money", "amount"),)) from None
    _require(result.is_finite(), "nonfinite_money", "amount")
    return result


@dataclass(frozen=True)
class CalendarPolicy:
    now: datetime
    holidays: frozenset[date]
    weekmask: frozenset[int]
    week_start: int
    source_policy_parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_policy_parameters", _sources(self.source_policy_parameters))
        _require(isinstance(self.now, datetime), "invalid_now", "now")
        mask = frozenset(self.weekmask)
        _require(bool(mask) and all(type(n) is int and 0 <= n < 7 for n in mask),
                 "invalid_weekmask", "weekmask")
        _require(type(self.week_start) is int and 0 <= self.week_start < 7,
                 "invalid_week_start", "week_start")
        object.__setattr__(self, "weekmask", mask)
        object.__setattr__(self, "holidays", frozenset(_date(d) for d in self.holidays))

    @property
    def today(self) -> date:
        return self.now.date()

    def is_business_day(self, day: date | str) -> bool:
        day = _date(day)
        return day.weekday() in self.weekmask and day not in self.holidays

    def add_business_days(self, start: date | str, offset: int) -> date:
        """Exclude start when offset is nonzero; zero returns start unchanged."""
        _require(type(offset) is int, "invalid_business_day_offset", "offset")
        day = _date(start)
        direction = 1 if offset >= 0 else -1
        remaining = abs(offset)
        while remaining:
            day += timedelta(days=direction)
            if self.is_business_day(day):
                remaining -= 1
        return day

    def next_business_day(self, start: date | str, *, inclusive: bool) -> date:
        _require(type(inclusive) is bool, "invalid_inclusive", "inclusive")
        day = _date(start)
        if inclusive and self.is_business_day(day):
            return day
        return self.add_business_days(day, 1)

    def weekday_date(self, weekday: int, which: str, *, next_weekday_semantics: str) -> date:
        """Resolve 'this'/'next'; never silently roll a holiday or a past date.

        ``following_calendar_week`` means weekday in the next week beginning at
        week_start; ``next_occurrence`` means the strictly next matching weekday.
        The option is required, including for 'this', to make the contract explicit.
        """
        _require(type(weekday) is int and 0 <= weekday < 7, "invalid_weekday", "weekday")
        _require(which in {"this", "next"}, "invalid_week_reference", "which")
        _require(next_weekday_semantics in {"following_calendar_week", "next_occurrence"},
                 "invalid_next_weekday_semantics", "next_weekday_semantics")
        if which == "next" and next_weekday_semantics == "next_occurrence":
            return self.today + timedelta(days=(weekday - self.today.weekday()) % 7 or 7)
        start = self.today - timedelta(days=(self.today.weekday() - self.week_start) % 7)
        return start + timedelta(days=(weekday - self.week_start) % 7 + (7 if which == "next" else 0))

    def last_business_day_of_week(self, day: date | str) -> date:
        day = _date(day)
        start = day - timedelta(days=(day.weekday() - self.week_start) % 7)
        for offset in range(6, -1, -1):
            candidate = start + timedelta(days=offset)
            if self.is_business_day(candidate):
                return candidate
        raise PolicyViolation((Violation("no_business_day_in_week", "date", {"week_start": start.isoformat()}),))


def guard_promise_date(day: date | str, *, calendar: CalendarPolicy, deadline: date | str) -> tuple[Violation, ...]:
    try:
        day, deadline = _date(day), _date(deadline)
    except PolicyViolation as exc:
        return exc.violations
    violations = []
    if day < calendar.today:
        violations.append(Violation("date_before_today", "date", {"today": calendar.today.isoformat()}))
    if day > deadline:
        violations.append(Violation("date_after_deadline", "date", {"deadline": deadline.isoformat()}))
    if not calendar.is_business_day(day):
        violations.append(Violation("non_business_day", "date"))
    return tuple(violations)


def guard_scheduled_datetime(when: datetime, *, calendar: CalendarPolicy,
                             allowed_business_day_offsets: Iterable[int],
                             window_start: time, window_end: time) -> tuple[Violation, ...]:
    """Validate a future scheduled time against explicit dates and an inclusive window.

    Offset zero permits today even if it is not a business day; other offsets use
    add_business_days(). Naive times are local to the supplied calendar. Aware
    times convert to now's timezone; mixing naive and aware datetimes is rejected.
    The time window is within one day, expressed in that same local timezone.
    """
    if not isinstance(when, datetime):
        return (Violation("invalid_datetime", "datetime"),)
    if not (isinstance(window_start, time) and isinstance(window_end, time)
            and window_start.tzinfo is None and window_end.tzinfo is None and window_start <= window_end):
        return (Violation("invalid_time_window", "window"),)
    if (when.utcoffset() is None) != (calendar.now.utcoffset() is None):
        return (Violation("incompatible_timezone", "datetime"),)
    if calendar.now.utcoffset() is not None:
        when = when.astimezone(calendar.now.tzinfo)
    try:
        allowed = {calendar.add_business_days(calendar.today, offset) for offset in allowed_business_day_offsets}
    except PolicyViolation as exc:
        return exc.violations
    violations = []
    if when <= calendar.now:
        violations.append(Violation("scheduled_time_not_future", "datetime", {"now": calendar.now.isoformat()}))
    if when.date() not in allowed:
        violations.append(Violation("scheduled_date_not_allowed", "datetime", {"allowed_dates": sorted(d.isoformat() for d in allowed)}))
    if not window_start <= when.time() <= window_end:
        violations.append(Violation("scheduled_time_outside_window", "datetime", {
            "window_start": window_start.isoformat(), "window_end": window_end.isoformat(),
        }))
    return tuple(violations)


@dataclass(frozen=True)
class MoneyPolicy:
    minimum: Decimal | str | int
    maximum: Decimal | str | int
    quantum: Decimal | str | int
    source_policy_parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_policy_parameters", _sources(self.source_policy_parameters))
        for name in ("minimum", "maximum", "quantum"):
            object.__setattr__(self, name, decimal_money(getattr(self, name)))
        _require(self.minimum >= 0 and self.maximum >= self.minimum, "invalid_money_bounds", "money")
        _require(self.quantum > 0, "invalid_money_quantum", "quantum")


def guard_money(value: Decimal | str | int, *, policy: MoneyPolicy) -> tuple[Violation, ...]:
    try:
        value = decimal_money(value)
    except PolicyViolation as exc:
        return exc.violations
    violations = []
    if value < policy.minimum:
        violations.append(Violation("amount_below_floor", "amount", {"minimum": str(policy.minimum)}))
    if value > policy.maximum:
        violations.append(Violation("amount_above_ceiling", "amount", {"maximum": str(policy.maximum)}))
    with localcontext() as context:
        context.prec = max(28, len(value.as_tuple().digits) + abs(value.adjusted() - policy.quantum.adjusted()) + 2)
        if value % policy.quantum:
            violations.append(Violation("amount_off_quantum", "amount", {"quantum": str(policy.quantum)}))
    return tuple(violations)


@dataclass
class RetryBudget:
    """Total attempts, including the first; counted/exempt retries are explicit."""

    max_attempts: int
    source_policy_parameters: Mapping[str, Any]
    _used: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self.source_policy_parameters = _sources(self.source_policy_parameters)
        _require(type(self.max_attempts) is int and self.max_attempts >= 0,
                 "invalid_retry_budget", "max_attempts")

    @property
    def used(self) -> int:
        return self._used

    @property
    def remaining(self) -> int:
        return max(0, self.max_attempts - self._used)

    def consume(self, *, counted: bool = True) -> None:
        _require(type(counted) is bool, "invalid_counted", "counted")
        _require(self.remaining > 0, "retry_budget_exhausted", "attempts", max_attempts=self.max_attempts)
        if counted:
            self._used += 1


@dataclass(frozen=True)
class ProductPolicy:
    product_id: str
    money: MoneyPolicy
    deadline: date
    max_record_attempts: int
    source_policy_parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_policy_parameters", _sources(self.source_policy_parameters))
        _require(isinstance(self.product_id, str) and bool(self.product_id), "invalid_product_id", "product_id")
        _require(isinstance(self.money, MoneyPolicy), "invalid_money_policy", "money")
        object.__setattr__(self, "deadline", _date(self.deadline))
        _require(type(self.max_record_attempts) is int and self.max_record_attempts >= 0,
                 "invalid_retry_budget", "max_record_attempts")


@dataclass(frozen=True)
class PromiseTerms:
    amount: Decimal
    date: date


@dataclass(frozen=True)
class ProductPromise:
    product_id: str
    terms: PromiseTerms


@dataclass(frozen=True)
class Readback:
    revision: int
    promises: tuple[ProductPromise, ...]


@dataclass(frozen=True)
class ProductState:
    product_id: str
    proposed: PromiseTerms | None
    confirmed: PromiseTerms | None
    recorded: PromiseTerms | None
    attempts_used: int
    note_reason: str | None
    note_recorded: bool


@dataclass(frozen=True)
class CloseDecision:
    outcome: str
    reason: str | None = None

    def to_payload(self, *, outcome_field: str, reason_field: str) -> dict[str, str]:
        _require(isinstance(outcome_field, str) and bool(outcome_field)
                 and isinstance(reason_field, str) and bool(reason_field) and outcome_field != reason_field,
                 "invalid_close_fields", "close")
        result = {outcome_field: self.outcome}
        if self.reason is not None:
            result[reason_field] = self.reason
        return result


@dataclass(frozen=True)
class CloseRules:
    recorded: CloseDecision
    all_exempt: CloseDecision
    exempt_reason: str
    reason_decisions: Mapping[str, CloseDecision]
    transfer_decisions: Mapping[str, CloseDecision]
    outcome_field: str
    reason_field: str
    source_policy_parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_policy_parameters", _sources(self.source_policy_parameters))
        _require(isinstance(self.exempt_reason, str) and bool(self.exempt_reason), "invalid_exempt_reason", "exempt_reason")
        for name in ("reason_decisions", "transfer_decisions"):
            values = dict(getattr(self, name))
            _require(all(isinstance(k, str) and k and isinstance(v, CloseDecision) for k, v in values.items()),
                     "invalid_close_rules", name)
            object.__setattr__(self, name, MappingProxyType(values))
        _require(isinstance(self.recorded, CloseDecision) and isinstance(self.all_exempt, CloseDecision),
                 "invalid_close_rules", "close")
        for decision in (self.recorded, self.all_exempt, *self.reason_decisions.values(), *self.transfer_decisions.values()):
            _require(isinstance(decision.outcome, str) and bool(decision.outcome)
                     and (decision.reason is None or isinstance(decision.reason, str) and bool(decision.reason)),
                     "invalid_close_decision", "close")
            decision.to_payload(outcome_field=self.outcome_field, reason_field=self.reason_field)


def reduce_close(*, product_order: Sequence[str], recorded_ids: Iterable[str],
                 notes: Mapping[str, str], rules: CloseRules,
                 transfer_reason: str | None = None) -> CloseDecision:
    """Reduce complete facts in backend order; outcome/reason enums are supplied.

    Transfer overrides recorded promises. Otherwise every product must have a
    recorded promise or an explicit note reason; missing products never fabricate
    an all-exempt/recorded outcome. Note writes themselves are tracked by runtime.
    """
    order = tuple(product_order)
    _require(len(order) == len(set(order)), "duplicate_product", "products")
    if transfer_reason is not None:
        _require(transfer_reason in rules.transfer_decisions, "unknown_transfer_reason", "reason")
        return rules.transfer_decisions[transfer_reason]
    recorded = set(recorded_ids)
    _require(bool(order), "incomplete_products", "products")
    _require(recorded.union(notes) <= set(order), "unknown_product", "products")
    _require(not recorded.intersection(notes), "recorded_product_has_note", "notes")
    for product_id in order:
        _require(product_id in recorded or product_id in notes, "unresolved_product", product_id)
        if product_id in notes:
            _require(notes[product_id] == rules.exempt_reason or notes[product_id] in rules.reason_decisions,
                     "unknown_note_reason", product_id, reason=notes[product_id])
    if recorded:
        return rules.recorded
    for product_id in order:
        if notes[product_id] != rules.exempt_reason:
            return rules.reason_decisions[notes[product_id]]
    return rules.all_exempt


@dataclass(frozen=True)
class BackendAttempt:
    token: int
    kind: str
    product_id: str | None = None
    terms: PromiseTerms | None = None
    reason: str | None = None


class PromiseRuntime:
    """Sequential action guards; adapters must call begin_* before any write.

    ``emit_product_notes`` is required: policies may suppress product note writes
    while still supplying explicit product dispositions for close reduction.
    Exactly one backend attempt may be in flight. Result methods require that
    exact attempt object, so a fabricated/equal/replayed receipt cannot commit.
    An unknown/timeout result must stay pending until the adapter reconciles it;
    declaring failure is safe only when the backend definitely made no write.
    """

    def __init__(self, products: Sequence[ProductPolicy], *, calendar: CalendarPolicy,
                 emit_product_notes: bool,
                 source_policy_parameters: Mapping[str, Any]):
        self.source_policy_parameters = _sources(source_policy_parameters)
        _require(type(emit_product_notes) is bool, "invalid_note_policy", "emit_product_notes")
        self._emit_product_notes = emit_product_notes
        self.calendar = calendar
        self._order = tuple(p.product_id for p in products)
        _require(len(self._order) == len(set(self._order)), "duplicate_product", "products")
        self._policies = {p.product_id: p for p in products}
        self._budgets = {p.product_id: RetryBudget(p.max_record_attempts, p.source_policy_parameters) for p in products}
        self._proposed: dict[str, PromiseTerms] = {}
        self._confirmed: dict[str, PromiseTerms] = {}
        self._recorded: dict[str, PromiseTerms] = {}
        self._notes: dict[str, str] = {}
        self._written_notes: set[str] = set()
        self._revision = 0
        self._token = 0
        self._inflight: BackendAttempt | None = None
        self._terminal: str | None = None
        self._decision: CloseDecision | None = None
        self._transfer_reason: str | None = None
        self._transfer_completed = False
        self._closed = False

    @property
    def product_order(self) -> tuple[str, ...]:
        return self._order

    def state(self, product_id: str) -> ProductState:
        self._product(product_id)
        return ProductState(product_id, self._proposed.get(product_id), self._confirmed.get(product_id),
                            self._recorded.get(product_id), self._budgets[product_id].used,
                            self._notes.get(product_id), product_id in self._written_notes)

    def _product(self, product_id: str) -> ProductPolicy:
        _require(product_id in self._policies, "unknown_product", "product_id", product_id=product_id)
        return self._policies[product_id]

    def _idle(self) -> None:
        _require(not self._closed, "call_closed", "call")
        _require(self._inflight is None, "backend_action_in_flight", "call")

    def _open(self) -> None:
        self._idle()
        _require(self._terminal is None, "terminal_decision_locked", "call")

    def _invalidate_confirmation(self) -> None:
        self._revision += 1
        self._confirmed.clear()

    def propose(self, product_id: str, amount: Decimal | str | int, day: date | str) -> PromiseTerms:
        """Apply proposed/corrected user terms, revoking assent before validation.

        A rejected replacement retains the last valid proposal as a candidate,
        but its old readback and every outstanding confirmation become stale.
        Planner candidates should use the pure guard functions instead.
        """
        self._open()
        policy = self._product(product_id)
        _require(product_id not in self._recorded, "recorded_promise_immutable", product_id)
        self._invalidate_confirmation()
        violations = guard_money(amount, policy=policy.money) + guard_promise_date(day, calendar=self.calendar, deadline=policy.deadline)
        if violations:
            raise PolicyViolation(violations)
        terms = PromiseTerms(decimal_money(amount), _date(day))
        if self._proposed.get(product_id) != terms or product_id in self._notes:
            self._proposed[product_id] = terms
            self._notes.pop(product_id, None)
        return terms

    def readback(self) -> Readback:
        self._open()
        return Readback(self._revision, tuple(ProductPromise(p, self._proposed[p]) for p in self._order if p in self._proposed))

    def confirm(self, readback: Readback, *, accepted: bool) -> None:
        self._open()
        _require(type(accepted) is bool, "explicit_confirmation_required", "confirmation")
        _require(readback == self.readback(), "stale_readback", "confirmation")
        _require(bool(readback.promises), "empty_readback", "confirmation")
        self._confirmed.clear()
        if accepted:
            self._confirmed.update((p.product_id, p.terms) for p in readback.promises)

    def set_note(self, product_id: str, reason: str) -> None:
        """Buffer an explicit disposition, abandoning this product's terms.

        Removing a failed/refused product does not change the already confirmed
        terms of other products. A correction through propose() does invalidate
        the entire remaining batch.
        """
        self._open()
        self._product(product_id)
        _require(product_id not in self._recorded, "recorded_product_has_note", product_id)
        _require(isinstance(reason, str) and bool(reason), "invalid_note_reason", "reason")
        self._notes[product_id] = reason
        if self._proposed.pop(product_id, None) is not None:
            self._revision += 1
        self._confirmed.pop(product_id, None)

    def _attempt(self, kind: str, *, product_id: str | None = None,
                 terms: PromiseTerms | None = None, reason: str | None = None) -> BackendAttempt:
        self._token += 1
        attempt = BackendAttempt(self._token, kind, product_id, terms, reason)
        self._inflight = attempt
        return attempt

    def _result(self, attempt: BackendAttempt, kind: str, succeeded: bool) -> None:
        _require(not self._closed, "call_closed", "call")
        _require(type(succeeded) is bool, "explicit_backend_result_required", "result")
        _require(isinstance(attempt, BackendAttempt) and attempt is self._inflight and attempt.kind == kind,
                 "unexpected_backend_result", "result")
        self._inflight = None

    def begin_record(self, product_id: str) -> BackendAttempt:
        self._open()
        self._product(product_id)
        _require(product_id not in self._recorded, "recorded_promise_immutable", product_id)
        _require(product_id in self._confirmed, "promise_not_confirmed", product_id)
        pending = [p for p in self._order if p in self._proposed]
        _require(bool(pending) and pending[0] == product_id, "backend_order_violation", product_id,
                 expected=pending[0] if pending else None)
        self._budgets[product_id].consume()
        return self._attempt("record", product_id=product_id, terms=self._confirmed[product_id])

    def record_result(self, attempt: BackendAttempt, *, succeeded: bool) -> None:
        self._result(attempt, "record", succeeded)
        if succeeded:
            self._recorded[attempt.product_id] = attempt.terms
            self._proposed.pop(attempt.product_id, None)
            self._confirmed.pop(attempt.product_id, None)
            self._revision += 1

    def finalize_non_transfer(self, rules: CloseRules) -> CloseDecision:
        self._open()
        decision = reduce_close(product_order=self._order, recorded_ids=self._recorded, notes=self._notes, rules=rules)
        self._terminal = "non_transfer"
        self._decision = decision
        return decision

    def notes_to_flush(self) -> tuple[tuple[str, str], ...]:
        """Return no notes before the terminal decision or for a transfer."""
        if self._terminal != "non_transfer" or not self._emit_product_notes:
            return ()
        return tuple((p, self._notes[p]) for p in self._order if p in self._notes and p not in self._written_notes)

    def begin_note(self, product_id: str) -> BackendAttempt:
        self._idle()
        self._product(product_id)
        _require(self._emit_product_notes, "product_notes_disabled", "notes")
        _require(self._terminal == "non_transfer", "notes_require_non_transfer_terminal", "notes")
        pending = self.notes_to_flush()
        _require(bool(pending) and pending[0][0] == product_id, "backend_order_violation", product_id,
                 expected=pending[0][0] if pending else None)
        return self._attempt("note", product_id=product_id, reason=self._notes[product_id])

    def note_result(self, attempt: BackendAttempt, *, succeeded: bool) -> None:
        self._result(attempt, "note", succeeded)
        if succeeded:
            self._written_notes.add(attempt.product_id)

    def begin_transfer(self, reason: str, *, rules: CloseRules) -> BackendAttempt:
        self._idle()
        _require(self._terminal != "non_transfer", "transfer_after_non_transfer_terminal", "transfer")
        _require(not self._transfer_completed, "transfer_already_completed", "transfer")
        _require(self._transfer_reason is None or self._transfer_reason == reason, "terminal_decision_locked", "transfer")
        decision = reduce_close(product_order=self._order, recorded_ids=self._recorded, notes={}, rules=rules, transfer_reason=reason)
        self._terminal = "transfer"
        self._transfer_reason = reason
        self._decision = decision
        self._notes.clear()
        self._proposed.clear()
        self._invalidate_confirmation()
        return self._attempt("transfer", reason=reason)

    def transfer_result(self, attempt: BackendAttempt, *, succeeded: bool) -> None:
        self._result(attempt, "transfer", succeeded)
        self._transfer_completed = succeeded

    def begin_close(self) -> CloseDecision:
        """Reserve the single final backend call; no later backend action allowed."""
        self._idle()
        _require(self._decision is not None, "terminal_decision_required", "close")
        _require(self._terminal != "transfer" or self._transfer_completed, "transfer_not_completed", "close")
        _require(not self.notes_to_flush(), "notes_not_recorded", "close")
        self._closed = True
        return self._decision
