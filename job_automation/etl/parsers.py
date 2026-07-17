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
        # Only treat as state-limited when a real US state code appears
        # (avoid greedy matches like "works in an ..." / "Hiring Remotely in USA").
        if re.search(
            r"\bremote(?:ly)?\b.{0,40}\b(?:only|within|in)\s+"
            r"(?:AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|"
            r"MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\b",
            lowered,
            re.I,
        ):
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


def _normalize_role_text(text: str) -> str:
    """Normalize titles/roles so Sr./Senior, full-stack/full stack, eng/engineer match."""
    value = text.lower().strip()
    value = value.replace("&", " and ")
    # Senior / junior abbreviations (Sr., Sr, Sen.)
    value = re.sub(r"\b(sr|sen)\.?\b", "senior", value)
    value = re.sub(r"\bjr\.?\b", "junior", value)
    # Engineer / developer abbreviations
    value = re.sub(r"\beng\.?\b", "engineer", value)
    value = re.sub(r"\bdevs?\b", "developer", value)
    value = re.sub(r"\bdevel\.?\b", "developer", value)
    # Full stack / front-end / back-end variants
    value = re.sub(r"\bfull[\s\-]*stack\b", "full stack", value)
    value = re.sub(r"\bfs\b", "full stack", value)
    value = re.sub(r"\bfront[\s\-]*end\b", "frontend", value)
    value = re.sub(r"\bback[\s\-]*end\b", "backend", value)
    # Collapse punctuation/separators to spaces
    value = re.sub(r"[/|_]+", " ", value)
    value = re.sub(r"[^\w+#.\s]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _title_matches_role(title: str, role: str) -> bool:
    norm_title = _normalize_role_text(title)
    norm_role = _normalize_role_text(role)
    if not norm_title or not norm_role:
        return False
    if norm_role in norm_title:
        return True

    # "Sr. Software" / "Senior Software" (optional eng/dev) counts as Software Engineer/Developer.
    if re.search(r"\bsoftware\s+(?:engineer|developer)\b", norm_role):
        if re.search(
            r"\b(?:senior|junior|staff|principal|lead|mid)?\s*software"
            r"(?:\s+(?:engineer|developer))?\b",
            norm_title,
        ):
            return True

    # "Sr. Full Stack" / "Senior Full-Stack" counts as Full Stack Engineer/Developer.
    if re.search(r"\bfull stack\s+(?:engineer|developer)\b", norm_role) or norm_role in {
        "full stack",
        "full stack engineer",
        "full stack developer",
    }:
        if re.search(
            r"\b(?:senior|junior|staff|principal|lead|mid)?\s*full stack"
            r"(?:\s+(?:engineer|developer))?\b",
            norm_title,
        ):
            return True
    return False


def parse_role_match(title: str | None, target_roles: list[str]) -> ParseResult:
    if not title:
        return ParseResult(False, None, True)
    for role in target_roles:
        if _title_matches_role(title, role):
            return ParseResult(True, f"Title matches target role: {role}", False)
    return ParseResult(False, f"Title does not match target roles: {title}", False)


def parse_excluded_role(title: str | None, excluded_roles: list[str]) -> ParseResult:
    if not title:
        return ParseResult(False, None, False)
    for role in excluded_roles:
        if _title_matches_role(title, role):
            return ParseResult(True, f"Excluded role detected: {role}", False)
    return ParseResult(False, None, False)


def _normalize_skill_token(skill: str) -> str:
    text = skill.lower().strip()
    text = text.replace(".js", "js").replace(".net", "dotnet")
    return re.sub(r"[^a-z0-9+#]+", "", text)


def _skills_equivalent(left: str, right: str) -> bool:
    a = _normalize_skill_token(left)
    b = _normalize_skill_token(right)
    if not a or not b:
        return False
    if a == b:
        return True
    aliases = {
        "js": "javascript",
        "ts": "typescript",
        "golang": "go",
        "tailwind": "tailwindcss",
        "reactjs": "react",
        "vuejs": "vuejs",
        "nextjs": "nextjs",
        "nodejs": "nodejs",
        "dotnet": "dotnet",
        "csharp": "c#",
        "postgres": "postgresql",
        "gcp": "googlecloudplatform",
        "k8s": "kubernetes",
    }
    a = aliases.get(a, a)
    b = aliases.get(b, b)
    if a == b:
        return True
    # Avoid java ⊆ javascript style false positives.
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) < 4:
        return False
    if longer.startswith(shorter) or longer.endswith(shorter):
        return True
    return False


def _count_matched_skills(required: list[str], candidate_skills: list[str]) -> tuple[int, list[str]]:
    matched: list[str] = []
    for req in required:
        if any(_skills_equivalent(req, mine) for mine in candidate_skills):
            matched.append(req)
    return len(matched), matched


def parse_skill_match(
    text: str,
    target_skills: list[str],
    *,
    top_skills: list[str] | None = None,
) -> ParseResult:
    """Match user skills to a job's required stack.

    If top_skills (job necessary stack) is present:
      - > 1/2 matched → True (available)
      - < 1/4 matched → False (reject)
      - otherwise → None (need review)
    Else fall back to any target skill appearing in description text.
    """
    required = [s.strip() for s in (top_skills or []) if s and str(s).strip()]
    if required:
        hit_count, matched = _count_matched_skills(required, target_skills)
        ratio = hit_count / len(required)
        detail = (
            f"Matched {hit_count}/{len(required)} top skills "
            f"({ratio:.0%}): {', '.join(matched) if matched else 'none'}"
        )
        if ratio > 0.5:
            return ParseResult(True, detail, False)
        if ratio < 0.25:
            return ParseResult(False, detail, False)
        return ParseResult(None, detail, True)

    lowered = text.lower()
    matched = [skill for skill in target_skills if skill.lower() in lowered]
    if matched:
        return ParseResult(True, f"Skills matched in description: {', '.join(matched)}", False)
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
