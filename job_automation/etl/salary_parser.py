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
        r"\$(\d+(?:\.\d+)?)\s*(?:/hr|per hour|hourly)(?:\s*-\s*\$(\d+(?:\.\d+)?))?",
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

    annual_match = re.search(
        r"\$(\d+(?:\.\d+)?)\s*(?:k|K)?(?:\s*-\s*\$(\d+(?:\.\d+)?)\s*(?:k|K)?)?(?:\s*(?:/year|annually|per year))?",
        normalized,
    )
    if annual_match:
        low = _to_annual(annual_match.group(1), text)
        high = _to_annual(annual_match.group(2), text) if annual_match.group(2) else low
        return SalaryParseResult(
            salary_text=text,
            min_annual=low,
            max_annual=high,
            evidence_text=evidence,
        )

    return SalaryParseResult(salary_text=text, evidence_text=evidence)


def _to_annual(value: str, original: str) -> int:
    num = float(value)
    if "k" in original.lower() and num < 1000:
        num *= 1000
    if num < 1000:
        num *= 1000
    return int(num)
