"""Salary parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class SalaryParseResult:
    salary_text: str | None
    min_annual: int | None = None
    max_annual: int | None = None
    min_hourly: float | None = None
    max_hourly: float | None = None
    evidence_text: str | None = None


def parse_salary(text: str | None) -> SalaryParseResult:
    if not text:
        return SalaryParseResult(salary_text=None)
    normalized = text.replace(",", "")
    evidence = text.strip()

    hourly_match = re.search(
        r"\$?(\d+(?:\.\d+)?)\s*(?:/hr|per hour|hourly)(?:\s*-\s*\$?(\d+(?:\.\d+)?))?",
        normalized,
        re.I,
    )
    if hourly_match:
        low = float(hourly_match.group(1))
        high = float(hourly_match.group(2)) if hourly_match.group(2) else low
        return SalaryParseResult(
            salary_text=text,
            min_hourly=low,
            max_hourly=high,
            evidence_text=evidence,
        )

    # Supports: $124K-$209K, 124K-209K Annually, $120,000 - $180,000 /year
    annual_match = re.search(
        r"\$?(\d+(?:\.\d+)?)\s*([kK])?(?:\s*-\s*\$?(\d+(?:\.\d+)?)\s*([kK])?)?"
        r"(?:\s*(?:/year|annually|per year))?",
        normalized,
    )
    if annual_match:
        low_raw, low_k, high_raw, high_k = annual_match.groups()
        # Require $ / K / annually cue so stray digits (e.g. "7") are not salaries.
        matched = annual_match.group(0)
        looks_like_salary = bool(
            "$" in matched
            or low_k
            or high_k
            or re.search(r"/year|annually|per year", matched, re.I)
            or float(low_raw) >= 1000
        )
        if looks_like_salary:
            low = _to_annual(low_raw, has_k=bool(low_k) or bool(high_k) or "k" in matched.lower())
            high = (
                _to_annual(high_raw, has_k=bool(high_k) or bool(low_k) or "k" in matched.lower())
                if high_raw
                else low
            )
            return SalaryParseResult(
                salary_text=text,
                min_annual=low,
                max_annual=high,
                evidence_text=evidence,
            )

    return SalaryParseResult(salary_text=text, evidence_text=evidence)


def _to_annual(value: str, *, has_k: bool = False) -> int:
    num = float(value)
    if has_k and num < 1000:
        num *= 1000
    elif not has_k and 1000 <= num < 10000:
        # Already full dollars like 80000; leave as-is.
        pass
    elif not has_k and num < 300:
        # Compact thousands without an explicit K (rare); treat as K only for 2-3 digit comps.
        num *= 1000
    return int(num)
