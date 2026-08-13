"""openFDA drug adverse event API client.

Deliberately uses only the standard library. The Lambda deployment package is
therefore source-only - no pip install, no layer, no dependency drift between
local runs and deployed runs. `requests` would read a little nicer but is not
worth a build step here.
"""

from __future__ import annotations

import json
import logging
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass

LOG = logging.getLogger(__name__)

API_BASE = "https://api.fda.gov/drug/event.json"

# openFDA hard limits. limit is capped at 100 per request, and `skip` cannot
# exceed 25,000 - past that the API refuses to paginate and the query must be
# narrowed instead. See partition_by_week() for how that is handled.
MAX_LIMIT = 100
MAX_SKIP = 25_000

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class OpenFDAError(RuntimeError):
    """Unrecoverable API failure."""


class PaginationExhaustedError(OpenFDAError):
    """Query matched more records than `skip` can reach. Narrow the window."""


@dataclass(frozen=True)
class Page:
    records: list[dict]
    total: int
    skip: int

    @property
    def is_empty(self) -> bool:
        return len(self.records) == 0


class OpenFDAClient:
    """Paginating client with backoff on transient failures.

    An API key is optional but raises the daily quota from 1,000 to 120,000
    requests. Without one you will exhaust the day's budget quickly during
    development.
    """

    def __init__(
        self,
        api_key: str | None = None,
        timeout: int = 30,
        max_retries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        user_agent: str = "ae-signal/0.1 (portfolio project)",
    ) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.user_agent = user_agent
        # Attempts, not successes - retries consume quota too.
        self.request_count = 0

    # ---- HTTP -----------------------------------------------------------

    def _build_url(self, params: dict) -> str:
        query = dict(params)
        if self.api_key:
            query["api_key"] = self.api_key
        # openFDA's Lucene-style search syntax must not have its brackets,
        # colons or + operators percent-encoded, so `search` is passed through
        # verbatim while everything else is encoded normally.
        search = query.pop("search", None)
        encoded = urllib.parse.urlencode(query)
        if search:
            encoded = f"search={search}&{encoded}"
        return f"{API_BASE}?{encoded}"

    def _sleep(self, attempt: int, retry_after: str | None = None) -> None:
        if retry_after:
            try:
                delay = float(retry_after)
                LOG.warning("Honoring Retry-After: %.1fs", delay)
                time.sleep(min(delay, self.max_delay))
                return
            except ValueError:
                pass
        # Exponential backoff with full jitter. Without jitter, concurrent
        # workers retry in lockstep and re-trigger the same rate limit.
        ceiling = min(self.max_delay, self.base_delay * (2**attempt))
        delay = random.uniform(0, ceiling)
        LOG.warning("Retry %d after %.2fs", attempt + 1, delay)
        time.sleep(delay)

    def _get(self, params: dict) -> dict:
        """Single request with retries. Returns the decoded JSON body.

        A 404 from openFDA means 'no documents matched', not 'endpoint missing'.
        It is a normal terminal condition when paginating, so it is translated
        into an empty result rather than raised.
        """
        url = self._build_url(params)
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            self.request_count += 1
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    LOG.info("openFDA returned 404 (no matches) - treating as empty page")
                    return {
                        "meta": {"results": {"total": 0, "skip": params.get("skip", 0)}},
                        "results": [],
                    }
                if exc.code in RETRYABLE_STATUS:
                    last_error = exc
                    self._sleep(attempt, exc.headers.get("Retry-After"))
                    continue
                body = exc.read().decode("utf-8", errors="replace")[:500]
                raise OpenFDAError(f"HTTP {exc.code} from openFDA: {body}") from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                self._sleep(attempt)

        raise OpenFDAError(f"Exhausted {self.max_retries} retries against openFDA") from last_error

    # ---- Pagination -----------------------------------------------------

    def fetch_page(self, search: str, skip: int = 0, limit: int = MAX_LIMIT) -> Page:
        if limit > MAX_LIMIT:
            raise ValueError(f"limit cannot exceed {MAX_LIMIT}")
        if skip > MAX_SKIP:
            raise PaginationExhaustedError(
                f"skip={skip} exceeds openFDA's cap of {MAX_SKIP}; narrow the date window"
            )

        body = self._get({"search": search, "limit": limit, "skip": skip})
        meta = body.get("meta", {}).get("results", {})
        return Page(
            records=body.get("results", []),
            total=int(meta.get("total", 0)),
            skip=int(meta.get("skip", skip)),
        )

    def iter_records(
        self, search: str, max_records: int | None = None, limit: int = MAX_LIMIT
    ) -> Iterator[dict]:
        """Yield records for a query, paging until exhausted or capped.

        max_records exists to keep development runs bounded. Leaving it unset
        against a broad query will happily pull tens of thousands of records
        and burn the daily quota.
        """
        skip = 0
        emitted = 0

        while True:
            remaining = None if max_records is None else max_records - emitted
            if remaining is not None and remaining <= 0:
                return

            page_size = limit if remaining is None else min(limit, remaining)
            page = self.fetch_page(search, skip=skip, limit=page_size)

            if page.is_empty:
                LOG.info("Pagination complete: %d records over skip=%d", emitted, skip)
                return

            for record in page.records:
                yield record
                emitted += 1

            skip += len(page.records)

            if skip >= page.total:
                LOG.info("Reached reported total of %d records", page.total)
                return
            if skip > MAX_SKIP:
                raise PaginationExhaustedError(
                    f"Query matched {page.total} records, more than skip can reach. "
                    "Narrow the date window."
                )
