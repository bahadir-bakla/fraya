"""Offline transport tests: fake openers and one shared fake deadline budget."""

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from urllib.error import HTTPError, URLError
from urllib.request import Request

from read_only_retry import open_with_read_only_retry


URL = "https://offline.invalid/simulations/opaque"


class BudgetExhausted(Exception):
    pass


class FakeBudget:
    def __init__(self, seconds=1200):
        self.seconds = seconds
        self.elapsed = 0
        self.sleeps = []
        self.exhausted = BudgetExhausted("total_budget_exhausted")

    def remaining(self):
        left = self.seconds - self.elapsed
        if left <= 0:
            raise self.exhausted
        return left

    def wait(self):
        delay = min(10, self.remaining())
        self.sleeps.append(delay)
        self.elapsed += delay
        self.remaining()


class FakeOpener:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, request, *, timeout):
        self.calls.append((request, timeout))
        outcome = self.outcomes.pop(0)
        if callable(outcome):
            outcome = outcome()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class UnreadBody(io.BytesIO):
    def read(self, *args, **kwargs):
        raise AssertionError("error bodies must not be read")


def http_error(code):
    return HTTPError(URL, code, "opaque transport error", {"X-Private": "opaque"},
                     UnreadBody(b"opaque private error body"))


class ReadOnlyRetryTests(unittest.TestCase):
    def test_get_503_recovery_closes_error_before_wait_and_retry(self):
        budget = FakeBudget()
        error = http_error(503)
        body = error.fp
        response = object()
        events = []
        original_wait = budget.wait

        def wait():
            self.assertTrue(body.closed)
            events.append("wait")
            original_wait()

        def recovered():
            self.assertTrue(body.closed)
            events.append("retry")
            return response

        budget.wait = wait
        opener = FakeOpener(error, recovered)
        self.assertIs(open_with_read_only_retry(Request(URL), opener=opener,
                                               budget=budget), response)
        self.assertEqual(events, ["wait", "retry"])
        self.assertEqual(budget.sleeps, [10])
        self.assertEqual(len(opener.calls), 2)

    def test_retryable_http_codes_exhaust_at_three_preserving_final_error(self):
        for code in (502, 503, 504):
            with self.subTest(code=code):
                errors = [http_error(code) for _ in range(3)]
                bodies = [error.fp for error in errors]
                opener, budget = FakeOpener(*errors, object()), FakeBudget()
                try:
                    with self.assertRaises(HTTPError) as caught:
                        open_with_read_only_retry(URL, opener=opener, budget=budget)
                    self.assertIs(caught.exception, errors[-1])
                    self.assertEqual(len(opener.calls), 3)
                    self.assertEqual(budget.sleeps, [10, 10])
                    self.assertTrue(all(body.closed for body in bodies[:2]))
                    self.assertFalse(bodies[-1].closed)
                finally:
                    for error in errors:
                        error.close()

    def test_timeouts_and_url_errors_recover_or_preserve_final_error(self):
        factories = (lambda: TimeoutError("opaque"),
                     lambda: URLError("opaque"),
                     lambda: URLError(TimeoutError("opaque")))
        for factory in factories:
            with self.subTest(error=factory().__class__.__name__):
                response, budget = object(), FakeBudget()
                opener = FakeOpener(factory(), factory(), response)
                self.assertIs(open_with_read_only_retry(URL, opener=opener,
                                                       budget=budget), response)
                self.assertEqual(len(opener.calls), 3)
                self.assertEqual(budget.sleeps, [10, 10])
                final = factory()
                opener, budget = FakeOpener(factory(), factory(), final, object()), FakeBudget()
                with self.assertRaises(type(final)) as caught:
                    open_with_read_only_retry(URL, opener=opener, budget=budget)
                self.assertIs(caught.exception, final)
                self.assertEqual(len(opener.calls), 3)
                self.assertEqual(budget.sleeps, [10, 10])

    def test_unsafe_mutations_never_retry_even_after_an_uncertain_start(self):
        # Record the server-side effect *before* the transport failure, as an
        # uncertain persona/session/simulation start or bank write would do.
        requests = [("persona", Request(URL, data=b"{}", method="POST")),
                    ("session", Request(URL, data=b"{}")),
                    ("simulation", Request(URL, data=b"{}", method="POST")),
                    ("bank", Request(URL, data=b"{}", method="PUT")),
                    ("bank", Request(URL, method="DELETE")),
                    ("bank", Request(URL, data=b"{}", method="PATCH"))]
        for label, request in requests:
            for factory in (lambda: http_error(503), lambda: TimeoutError("opaque"),
                            lambda: URLError("opaque")):
                with self.subTest(action=label, method=request.get_method(), failure=factory):
                    error, effects, budget = factory(), [], FakeBudget()

                    def uncertain_start():
                        effects.append(label)
                        return error

                    opener = FakeOpener(uncertain_start, uncertain_start)
                    try:
                        with self.assertRaises(type(error)) as caught:
                            open_with_read_only_retry(request, opener=opener, budget=budget)
                        self.assertIs(caught.exception, error)
                        self.assertEqual(effects, [label])
                        self.assertEqual(len(opener.calls), 1)
                        self.assertEqual(budget.sleeps, [])
                    finally:
                        if isinstance(error, HTTPError):
                            error.close()

    def test_nonretryable_http_400_and_429_do_not_fall_through_to_url_error(self):
        for code in (400, 429):
            with self.subTest(code=code):
                error, budget = http_error(code), FakeBudget()
                opener = FakeOpener(error, object())
                try:
                    with self.assertRaises(HTTPError) as caught:
                        open_with_read_only_retry(URL, opener=opener, budget=budget)
                    self.assertIs(caught.exception, error)
                    self.assertEqual(len(opener.calls), 1)
                    self.assertEqual(budget.sleeps, [])
                finally:
                    error.close()

    def test_method_selection_uses_request_get_method(self):
        # A GET may carry data; an explicit method overrides implicit POST.
        for request in (URL, Request(URL), Request(URL, data=b"{}", method="GET")):
            with self.subTest(request=request):
                response, budget = object(), FakeBudget()
                opener = FakeOpener(TimeoutError("opaque"), response)
                self.assertIs(open_with_read_only_retry(request, opener=opener,
                                                       budget=budget), response)
                self.assertIs(opener.calls[0][0], request)
                self.assertIs(opener.calls[1][0], request)
        for method in ("HEAD", "OPTIONS", "get", "CUSTOM"):
            with self.subTest(method=method):
                error, budget = TimeoutError("opaque"), FakeBudget()
                opener = FakeOpener(error, object())
                with self.assertRaises(TimeoutError) as caught:
                    open_with_read_only_retry(Request(URL, method=method), opener=opener,
                                              budget=budget)
                self.assertIs(caught.exception, error)
                self.assertEqual(len(opener.calls), 1)
                self.assertEqual(budget.sleeps, [])

    def test_deadline_before_first_attempt_never_opens_or_sleeps(self):
        for request in (URL, Request(URL, method="POST")):
            with self.subTest(method=request):
                opener, budget = FakeOpener(object()), FakeBudget(seconds=0)
                with self.assertRaises(BudgetExhausted) as caught:
                    open_with_read_only_retry(request, opener=opener, budget=budget)
                self.assertIs(caught.exception, budget.exhausted)
                self.assertEqual(opener.calls, [])
                self.assertEqual(budget.sleeps, [])

    def test_deadline_after_failure_prevents_sleep(self):
        budget, error = FakeBudget(seconds=4), http_error(503)
        body = error.fp

        def expired_request():
            budget.elapsed = 4
            return error

        opener = FakeOpener(expired_request, object())
        with self.assertRaises(BudgetExhausted) as caught:
            open_with_read_only_retry(URL, opener=opener, budget=budget)
        self.assertIs(caught.exception, budget.exhausted)
        self.assertTrue(body.closed)
        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(budget.sleeps, [])

    def test_deadline_during_wait_prevents_next_attempt(self):
        budget = FakeBudget(seconds=4)
        opener = FakeOpener(URLError("opaque"), object())
        with self.assertRaises(BudgetExhausted) as caught:
            open_with_read_only_retry(URL, opener=opener, budget=budget)
        self.assertIs(caught.exception, budget.exhausted)
        self.assertEqual(budget.sleeps, [4])
        self.assertEqual(len(opener.calls), 1)

    def test_deadline_rechecked_before_retry_even_if_wait_returns(self):
        budget = FakeBudget(seconds=15)

        def expire_without_raising():
            budget.elapsed = 15

        budget.wait = expire_without_raising
        opener = FakeOpener(TimeoutError("opaque"), object())
        with self.assertRaises(BudgetExhausted) as caught:
            open_with_read_only_retry(URL, opener=opener, budget=budget)
        self.assertIs(caught.exception, budget.exhausted)
        self.assertEqual(len(opener.calls), 1)

    def test_timeout_caps_and_reuses_remaining_budget_on_every_attempt(self):
        response, budget = object(), FakeBudget(seconds=45)
        opener = FakeOpener(TimeoutError("opaque"), URLError("opaque"), response)
        self.assertIs(open_with_read_only_retry(URL, opener=opener, budget=budget,
                                               timeout=90), response)
        self.assertEqual([timeout for _, timeout in opener.calls], [30, 30, 25])
        self.assertEqual(budget.elapsed, 20)
        for timeout, remaining, expected in ((5, 20, 5), (90, 7, 7), (30, 1200, 30)):
            with self.subTest(timeout=timeout, remaining=remaining):
                opener, budget = FakeOpener(response), FakeBudget(seconds=remaining)
                self.assertIs(open_with_read_only_retry(URL, opener=opener, budget=budget,
                                                       timeout=timeout), response)
                self.assertEqual(opener.calls[0][1], expected)

    def test_successful_mutation_returns_original_response(self):
        response, budget = object(), FakeBudget()
        opener = FakeOpener(response)
        request = Request(URL, data=b"{}", method="POST")
        self.assertIs(open_with_read_only_retry(request, opener=opener, budget=budget), response)
        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(budget.sleeps, [])

    def test_unlisted_exception_is_not_retried(self):
        error, budget = ValueError("opaque"), FakeBudget()
        opener = FakeOpener(error, object())
        with self.assertRaises(ValueError) as caught:
            open_with_read_only_retry(URL, opener=opener, budget=budget)
        self.assertIs(caught.exception, error)
        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(budget.sleeps, [])

    def test_transport_metadata_and_error_bodies_are_never_logged_or_read(self):
        error = http_error(503)
        stdout, stderr = io.StringIO(), io.StringIO()
        response, budget = object(), FakeBudget()
        opener = FakeOpener(error, response)
        with redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertIs(open_with_read_only_retry(URL, opener=opener, budget=budget), response)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
