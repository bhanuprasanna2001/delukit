"""Base class shared by all data sources.

Sources extract only: they return raw per-day payloads (XML text, JSON...)
and leave parsing to the silver layer.
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import date, timedelta
from time import sleep
from typing import Any, ClassVar

import requests
from pyrate_limiter import Limiter
from tqdm import tqdm

TRANSIENT_STATUSES = frozenset({408, 425, 429})


def _progress_disabled() -> bool:
    """Show progress bars only when stderr is a terminal (not tests/cron)."""
    return not sys.stderr.isatty()


class SourceError(Exception):
    """Permanent fetch failure: bad params, bad key, missing resource."""


class TransientSourceError(Exception):
    """Fetch failed after retries: server hiccup, network, rate limit."""


class DataSource(ABC):
    """Fetches one API into per-day results.

    Subclasses implement :meth:`_fetch_day` and route every HTTP request
    through :meth:`_call`, which applies the rate limit and retry policy.
    """

    name: ClassVar[str] = ""
    colour: ClassVar[str | None] = None
    limiter: ClassVar[Limiter | None] = None
    max_retries: ClassVar[int] = 3

    def fetch(self, start: date, end: date, **params: Any) -> dict[date, Any]:
        """Fetch each day in [start, end] separately. Days are never joined.

        Each day maps to that day's raw payload(s); an empty mapping means
        the source has no data for that day. Progress is shown on a tty
        only.
        """
        if start > end:
            raise ValueError(
                f"start {start.isoformat()} is after end {end.isoformat()}"
            )
        method = params.get("method", "")
        results: dict[date, Any] = {}
        day = start
        with tqdm(
            total=(end - start).days + 1,
            desc=f"{self.name} {method}".strip(),
            colour=self.colour,
            disable=_progress_disabled(),
        ) as bar:
            while day <= end:
                results[day] = self._fetch_day(day, **params)
                bar.set_postfix(day=day.isoformat())
                bar.update()
                day += timedelta(days=1)
        return results

    @abstractmethod
    def _fetch_day(self, day: date, **params: Any) -> Any:
        """Fetch one day's raw payload(s). Raise to fail, return empty for no data."""

    def _acquire(self) -> None:
        """Block until the source's rate limit allows one more request."""
        if self.limiter is not None:
            self.limiter.try_acquire()

    def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Call a client method, applying rate limit and retry policy.

        Transient failures (5xx, 429, 599, connection errors) are retried
        with backoff; permanent failures (4xx) raise SourceError at once.
        """
        for attempt in range(self.max_retries):
            self._acquire()
            try:
                return fn(*args, **kwargs)
            except requests.RequestException as error:
                if not self._is_transient(error):
                    raise self._permanent(error) from error
                if attempt == self.max_retries - 1:
                    raise self._transient(error, attempt) from error
                sleep(self._backoff(attempt, error))
        raise AssertionError("unreachable")

    @staticmethod
    def _is_transient(error: requests.RequestException) -> bool:
        if not isinstance(error, requests.HTTPError) or error.response is None:
            return True  # connection error / timeout
        return (
            error.response.status_code in TRANSIENT_STATUSES
            or error.response.status_code >= 500
        )

    def _permanent(self, error: requests.HTTPError) -> SourceError:
        status = error.response.status_code if error.response is not None else "?"
        hint = " (check ENTSOE_API_KEY)" if status == 401 else ""
        return SourceError(f"{self.name}: HTTP {status}{hint}")

    def _transient(
        self, error: requests.RequestException, attempt: int
    ) -> TransientSourceError:
        status = None
        if isinstance(error, requests.HTTPError) and error.response is not None:
            status = error.response.status_code
        what = f"HTTP {status}" if status is not None else error.__class__.__name__
        return TransientSourceError(f"{self.name}: {what} after {attempt + 1} attempts")

    @staticmethod
    def _backoff(attempt: int, error: requests.RequestException) -> float:
        if isinstance(error, requests.HTTPError) and error.response is not None:
            retry_after = error.response.headers.get("Retry-After")
            if retry_after is not None and retry_after.isdigit():
                return float(retry_after)
            if error.response.status_code == 429:
                # ponytail: minutely window resets each minute and Retry-After
                # is often absent; 2s retries just burn the budget
                return 60.0
        return float(2**attempt)
