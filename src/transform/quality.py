"""Data quality gates.

These raise. A quality check that only logs is a quality check that gets
ignored - the job goes green, the bad data lands, and the problem surfaces
three layers downstream where nobody can trace it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

LOG = logging.getLogger(__name__)


class DataQualityError(AssertionError):
    """A gate failed. The job must not write its output."""


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str

    def __str__(self) -> str:
        return f"[{'PASS' if self.passed else 'FAIL'}] {self.name}: {self.detail}"


def check_not_null(df: DataFrame, column: str) -> CheckResult:
    nulls = df.filter(F.col(column).isNull()).count()
    return CheckResult(f"not_null({column})", nulls == 0, f"{nulls} null values")


def check_unique(df: DataFrame, columns: list[str]) -> CheckResult:
    total = df.count()
    distinct = df.select(*columns).distinct().count()
    return CheckResult(
        f"unique({','.join(columns)})",
        total == distinct,
        f"{total} rows, {distinct} distinct, {total - distinct} duplicates",
    )


def check_row_count(df: DataFrame, minimum: int, maximum: int | None = None) -> CheckResult:
    count = df.count()
    ok = count >= minimum and (maximum is None or count <= maximum)
    bound = f">= {minimum}" + (f" and <= {maximum}" if maximum else "")
    return CheckResult("row_count", ok, f"{count} rows, expected {bound}")


def check_date_ordering(df: DataFrame, earlier: str, later: str) -> CheckResult:
    """receipt_date must not precede receive_date.

    Catches parsing bugs that type checks cannot: two valid dates in an
    impossible order almost always means a format was misread.
    """
    violations = df.filter(
        F.col(earlier).isNotNull() & F.col(later).isNotNull() & (F.col(later) < F.col(earlier))
    ).count()
    return CheckResult(
        f"ordering({earlier} <= {later})", violations == 0, f"{violations} violations"
    )


def check_null_rate(df: DataFrame, column: str, max_rate: float) -> CheckResult:
    total = df.count()
    if total == 0:
        return CheckResult(f"null_rate({column})", False, "empty dataframe")
    nulls = df.filter(F.col(column).isNull()).count()
    rate = nulls / total
    return CheckResult(
        f"null_rate({column})", rate <= max_rate, f"{rate:.1%} null, threshold {max_rate:.1%}"
    )


def enforce(results: list[CheckResult], label: str) -> None:
    for result in results:
        LOG.info("%s %s", label, result)
    failures = [r for r in results if not r.passed]
    if failures:
        raise DataQualityError(
            f"{label}: {len(failures)} of {len(results)} checks failed -> "
            + "; ".join(str(f) for f in failures)
        )
