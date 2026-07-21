"""Salary parsing (rule.txt §3 — base salary only, formatted range)."""

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


_FUNDING_CONTEXT = re.compile(
    r"(?:raised|funding|valuation|invest(?:ed|ment)|series\s+[a-z]|venture|"
    r"\b\$\d+(?:\.\d+)?\s*[mb](?:illion)?\b)",
    re.I,
)


def parse_salary(text: str | None) -> SalaryParseResult:
    if not text or not str(text).strip():
        return SalaryParseResult(salary_text="Not listed")
    evidence = text.strip()
    lowered = text.lower()

    # Funding / valuation snippets are not compensation.
    if _FUNDING_CONTEXT.search(text) and not re.search(
        r"\b(?:salary|base pay|base salary|compensation range|pay range|annually|/year|per year|/hr|per hour)\b",
        lowered,
    ):
        return SalaryParseResult(salary_text="Not listed", evidence_text=evidence)

    # OTE / total comp without clear base salary → Not listed
    if re.search(r"\bote\b|on[- ]target earnings|total compensation", lowered):
        if not re.search(r"\bbase\b", lowered):
            return SalaryParseResult(
                salary_text="Not listed",
                evidence_text=evidence,
            )

    normalized = text.replace(",", "")

    hourly_match = re.search(
        r"\$?(\d+(?:\.\d+)?)\s*(?:/hr|per hour|hourly)(?:\s*-\s*\$?(\d+(?:\.\d+)?))?",
        normalized,
        re.I,
    )
    has_annual_cue = bool(
        re.search(r"/year|annually|per year|\d\s*[kK]\b|\$\d{2,3},\d{3}", normalized)
    )

    # Prefer annual when both annual and hourly appear (rule.txt §3).
    if has_annual_cue or not hourly_match:
        annual_match = re.search(
            r"\$?(\d+(?:\.\d+)?)\s*([kK])?(?:\s*-\s*\$?(\d+(?:\.\d+)?)\s*([kK])?)?"
            r"(?:\s*(?:/year|annually|per year))?",
            normalized,
        )
        if annual_match:
            low_raw, low_k, high_raw, high_k = annual_match.groups()
            matched = annual_match.group(0)
            # Ignore $781M / $11B style amounts.
            if re.search(r"\d\s*[mb]\b", matched, re.I) or re.search(
                r"\$\d+(?:\.\d+)?\s*[mb]\b", text[annual_match.start() : annual_match.end() + 2], re.I
            ):
                annual_match = None
            else:
                amount = float(low_raw)
                looks_like_salary = bool(
                    low_k
                    or high_k
                    or re.search(r"/year|annually|per year", matched, re.I)
                    or amount >= 10000
                    or (
                        "$" in matched
                        and amount >= 1000
                        and re.search(r"salary|pay|compensation|base", lowered)
                    )
                )
                # Bare $781 without K/annually is not a salary.
                if "$" in matched and amount < 1000 and not low_k and not high_k:
                    if not re.search(r"/year|annually|per year", matched, re.I):
                        looks_like_salary = False
                # Do not treat "$55" from "$55/hr" as annual.
                if looks_like_salary and not (
                    hourly_match
                    and not has_annual_cue
                    and amount < 300
                    and not low_k
                    and not high_k
                ):
                    low = _to_annual(
                        low_raw, has_k=bool(low_k) or bool(high_k) or "k" in matched.lower()
                    )
                    high = (
                        _to_annual(
                            high_raw, has_k=bool(high_k) or bool(low_k) or "k" in matched.lower()
                        )
                        if high_raw
                        else low
                    )
                    return SalaryParseResult(
                        salary_text=_format_annual(low, high if high_raw else None),
                        min_annual=low,
                        max_annual=high,
                        evidence_text=evidence,
                    )

    if hourly_match:
        low = float(hourly_match.group(1))
        high = float(hourly_match.group(2)) if hourly_match.group(2) else None
        return SalaryParseResult(
            salary_text=_format_hourly(low, high),
            min_hourly=low,
            max_hourly=high if high is not None else low,
            evidence_text=evidence,
        )

    return SalaryParseResult(
        salary_text="Not listed",
        evidence_text=evidence,
    )


def _format_annual(low: int, high: int | None) -> str:
    if high is None or high == low:
        return f"${low:,}"
    return f"${low:,} – ${high:,}"


def _format_hourly(low: float, high: float | None) -> str:
    def _fmt(v: float) -> str:
        return f"${v:g}" if v == int(v) else f"${v:.2f}"

    if high is None or high == low:
        return f"{_fmt(low)} per hour"
    return f"{_fmt(low)} – {_fmt(high)} per hour"


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
