"""Bounded GET transport retries using the caller's existing deadline budget.

Integration target: OfficialClient._load's local urlopen, inside its existing
try/HTTPError sanitizer. Replace its urllib.request.urlopen call with:

    open_with_read_only_retry(request, opener=urllib.request.urlopen,
                              budget=self.budget, timeout=timeout)

No requests are made until explicitly called; this module creates no budgets.
"""

from urllib.error import HTTPError, URLError
from urllib.request import Request


def open_with_read_only_retry(request: Request | str, *, opener, budget, timeout=30):
    """Call an opener(request, timeout=...) with at most three GET attempts.

    Only exact GET methods (Request.get_method(), or a URL string) retry on
    HTTP 502/503/504, TimeoutError, or URLError. All other methods run once,
    including Requests whose data implicitly selects POST. Return the original
    response; propagate the final original exception without logging or reading
    error bodies. Budget.remaining()/wait() exceptions also pass through.
    Each socket timeout is min(timeout, 30, budget.remaining()).
    """
    method = "GET" if isinstance(request, str) else request.get_method()
    for attempt in range(3):
        remaining = budget.remaining()
        try:
            return opener(request, timeout=min(timeout, 30, remaining))
        except (HTTPError, TimeoutError, URLError) as error:
            if (method != "GET" or attempt == 2
                    or isinstance(error, HTTPError) and error.code not in (502, 503, 504)):
                raise
            if isinstance(error, HTTPError):
                error.close()
            budget.remaining()
            budget.wait()
