"""Keyword-based field extraction helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ParseResult:
    value: str | bool | None
    evidence_text: str | None = None
    uncertain: bool = False


def find_keyword_match(text: str, keywords: list[str]) -> tuple[str | None, bool]:
    lowered = text.lower()
    for keyword in keywords:
        if keyword.lower() in lowered:
            start = lowered.find(keyword.lower())
            snippet_start = max(0, start - 40)
            snippet_end = min(len(text), start + len(keyword) + 60)
            return text[snippet_start:snippet_end].strip(), True
    return None, False


def parse_remote_policy(text: str, keywords) -> ParseResult:
    lowered = text.lower()
    onsite_evidence, onsite = find_keyword_match(text, keywords.onsite)
    hybrid_evidence, hybrid = find_keyword_match(text, keywords.hybrid)
    remote_evidence, remote = find_keyword_match(text, keywords.fully_remote)

    if onsite:
        return ParseResult("onsite_required", onsite_evidence, False)
    if hybrid and not remote:
        if "remote" in lowered and ("exception" in lowered or "option" in lowered):
            return ParseResult("hybrid_possible_remote", hybrid_evidence, True)
        return ParseResult("hybrid_required", hybrid_evidence, False)
    if remote:
        if re.search(r"remote.*(only|within|in)\s+[a-z]{2}\b", lowered):
            return ParseResult("remote_specific_states", remote_evidence, True)
        return ParseResult("fully_remote_us", remote_evidence, False)
    if "remote" in lowered:
        if "united states" in lowered or "us only" in lowered or "usa" in lowered:
            return ParseResult("fully_remote_us", remote_evidence or "remote within US mentioned", False)
        return ParseResult("remote_unclear", "remote mentioned without clear US policy", True)
    return ParseResult("unclear", None, True)


def parse_travel(text: str, keywords) -> ParseResult:
    no_evidence, no_travel = find_keyword_match(text, keywords.travel_not_required)
    if no_travel:
        return ParseResult(False, no_evidence, False)
    evidence, required = find_keyword_match(text, keywords.travel_required)
    if required:
        return ParseResult(True, evidence, False)
    if "travel" in text.lower():
        return ParseResult(None, "travel mentioned but unclear", True)
    return ParseResult(False, "No travel requirement detected", False)


def parse_clearance(text: str, keywords) -> ParseResult:
    evidence, found = find_keyword_match(text, keywords.clearance)
    if found:
        obtain = "obtain" in (evidence or "").lower()
        return ParseResult(True, evidence, uncertain=obtain and "must" not in (evidence or "").lower())
    if "clearance" in text.lower():
        return ParseResult(None, "clearance mentioned but unclear", True)
    return ParseResult(False, "No clearance requirement detected", False)


def parse_security_related(text: str, keywords) -> ParseResult:
    evidence, found = find_keyword_match(text, keywords.security_related)
    if found:
        return ParseResult(True, evidence, True)
    return ParseResult(False, None, False)


def parse_government_industry(text: str, keywords) -> ParseResult:
    evidence, found = find_keyword_match(text, keywords.government_industry)
    return ParseResult(found, evidence, False)


def parse_role_match(title: str | None, target_roles: list[str]) -> ParseResult:
    if not title:
        return ParseResult(False, None, True)
    lowered = title.lower()
    for role in target_roles:
        if role.lower() in lowered:
            return ParseResult(True, f"Title matches target role: {role}", False)
    return ParseResult(False, f"Title does not match target roles: {title}", False)


def parse_excluded_role(title: str | None, excluded_roles: list[str]) -> ParseResult:
    if not title:
        return ParseResult(False, None, False)
    lowered = title.lower()
    for role in excluded_roles:
        if role.lower() in lowered:
            return ParseResult(True, f"Excluded role detected: {role}", False)
    return ParseResult(False, None, False)


def parse_skill_match(text: str, target_skills: list[str]) -> ParseResult:
    lowered = text.lower()
    matched = [skill for skill in target_skills if skill.lower() in lowered]
    if matched:
        return ParseResult(True, f"Skills matched: {', '.join(matched)}", False)
    return ParseResult(False, "No target skills found in description", False)


def parse_commitment(text: str, allowed: list[str]) -> ParseResult:
    lowered = text.lower()
    mapping = {
        "full time": "Full Time",
        "full-time": "Full Time",
        "part time": "Part Time",
        "part-time": "Part Time",
        "contract": "Contract",
    }
    for key, label in mapping.items():
        if key in lowered and label in allowed:
            return ParseResult(label, f"Commitment: {label}", False)
    return ParseResult(None, "Commitment unclear", True)


def parse_experience_level(text: str, allowed: list[str]) -> ParseResult:
    lowered = text.lower()
    if "senior" in lowered:
        value = "Senior Level"
    elif "junior" in lowered or "entry" in lowered:
        value = "Junior Level"
    elif "mid" in lowered or "intermediate" in lowered:
        value = "Mid Level"
    else:
        return ParseResult(None, "Experience level unclear", True)
    if value in allowed:
        return ParseResult(value, f"Experience level: {value}", False)
    return ParseResult(None, "Experience level not allowed", True)
