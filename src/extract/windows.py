"""Date-window partitioning for openFDA queries.

openFDA caps `skip` at 25,000, so any query matching more than that cannot be
fully paginated. The fix is to split the request into narrower date windows
whose individual result counts stay under the cap.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta


def fda_date(value: date) -> str:
    """openFDA expects dates as YYYYMMDD with no separators."""
    return value.strftime("%Y%m%d")


def received_date_query(start: date, end: date) -> str:
    """Lucene range filter on receivedate. Bounds are inclusive."""
    return f"receivedate:[{fda_date(start)}+TO+{fda_date(end)}]"


def partition_by_days(start: date, end: date, days: int = 7) -> Iterator[tuple[date, date]]:
    """Split an inclusive date range into consecutive windows.

    Narrower windows mean more requests but keep each one under the skip cap.
    Seven days is a reasonable default for the drug event endpoint.
    """
    if start > end:
        raise ValueError("start must not be after end")
    if days < 1:
        raise ValueError("days must be at least 1")

    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=days - 1), end)
        yield cursor, window_end
        cursor = window_end + timedelta(days=1)
