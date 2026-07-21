"""Keyword-based field extraction helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ParseResult:
    value: str | bool | None
    evidence_text: str | None = None
    uncertain: bool = False


_US_STATE_CODES = (
    "AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|"
    "MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY"
)

_US_STATE_NAMES = {
    "alabama",
    "alaska",
    "arizona",
    "arkansas",
    "california",
    "colorado",
    "connecticut",
    "delaware",
    "florida",
    "georgia",
    "hawaii",
    "idaho",
    "illinois",
    "indiana",
    "iowa",
    "kansas",
    "kentucky",
    "louisiana",
    "maine",
    "maryland",
    "massachusetts",
    "michigan",
    "minnesota",
    "mississippi",
    "missouri",
    "montana",
    "nebraska",
    "nevada",
    "new hampshire",
    "new jersey",
    "new mexico",
    "new york",
    "north carolina",
    "north dakota",
    "ohio",
    "oklahoma",
    "oregon",
    "pennsylvania",
    "rhode island",
    "south carolina",
    "south dakota",
    "tennessee",
    "texas",
    "utah",
    "vermont",
    "virginia",
    "washington",
    "west virginia",
    "wisconsin",
    "wyoming",
}

_NATIONWIDE_US_PATTERNS = [
    r"\bunited states\b",
    r"\bu\.?s\.?a\.?\b",
    r"\bu\.s\.\b",
    r"\bnationwide\b",
    r"\bthroughout the (?:united states|u\.?s\.?a?\.?)\b",
    r"\bu\.?s\.?\s*remote\b",
    r"\bremote\s*(?:-|–)?\s*u\.?s\.?a?\b",
    r"\busa\s*remote\b",
    r"\bremote\s*us\b",
    r"\bwork from anywhere in the (?:united states|u\.?s\.?a?\.?)\b",
    r"\bremote within the united states\b",
    r"\bavailable (?:throughout|across) the (?:united states|u\.?s\.?a?\.?)\b",
    r"\bworldwide\b",
    r"\banywhere in the (?:united states|u\.?s\.?a?\.?)\b",
    r"\bwork from anywhere\b",
    r"\b(?:can be |may be )?(?:executed|performed|done) globally\b",
    r"\bglobally\b",
    r"\bhiring remotely in (?:the )?united states\b",
]

# Two-letter codes that collide with English words when matched case-insensitively.
_AMBIGUOUS_STATE_CODES = {
    "IN",
    "OR",
    "ME",
    "HI",
    "OK",
    "OH",
    "DE",
    "MA",
    "PA",
    "LA",
    "ID",
    "MT",
    "ND",
    "NH",
    "VA",
}


def find_keyword_match(text: str, keywords: list[str]) -> tuple[str | None, bool]:
    lowered = text.lower()
    for keyword in keywords:
        if keyword.lower() in lowered:
            start = lowered.find(keyword.lower())
            snippet_start = max(0, start - 40)
            snippet_end = min(len(text), start + len(keyword) + 60)
            return text[snippet_start:snippet_end].strip(), True
    return None, False


def _mentions_connecticut(text: str) -> bool:
    lowered = text.lower()
    if re.search(r"\bct\b", text):  # uppercase CT code only when exact token
        if re.search(r"(?<![A-Za-z])CT(?![A-Za-z])", text):
            return True
    return "connecticut" in lowered or "conn." in lowered


def _has_nationwide_us(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(pat, lowered) for pat in _NATIONWIDE_US_PATTERNS)


def _listed_states(text: str) -> set[str]:
    """Return US state names/codes found as real location tokens (not English words)."""
    lowered = text.lower()
    found: set[str] = set()
    for name in _US_STATE_NAMES:
        if re.search(rf"\b{re.escape(name)}\b", lowered):
            found.add(name)
    for code in _US_STATE_CODES.split("|"):
        # Require uppercase codes so "in"/"or"/"me" are not Indiana/Oregon/Maine.
        if not re.search(rf"(?<![A-Za-z]){code}(?![A-Za-z])", text):
            continue
        if code in _AMBIGUOUS_STATE_CODES:
            # Ambiguous codes only count in list-like eligibility context.
            if not re.search(
                rf"(?:states?|locations?|reside|based)\s*[:\-]?\s*[^.{{]{{0,80}}"
                rf"(?<![A-Za-z]){code}(?![A-Za-z])",
                text,
                re.I,
            ):
                continue
        found.add(code.upper())
    return found


def _has_location_restriction_language(text: str) -> bool:
    """True only for applicant-location restrictions (not recruiter 'only contact…')."""
    return bool(
        re.search(
            r"\b(?:must (?:live|reside|be located|be based)|"
            r"restricted to|"
            r"eligible (?:states?|locations?)\s*(?:include|:)|"
            r"candidates? must (?:live|reside|be)|"
            r"applicants? must (?:live|reside|be)|"
            r"hiring only in |"
            r"open only to |"
            r"residents? of )\b",
            text,
            re.I,
        )
    )


def _states_exclude_connecticut(text: str) -> bool:
    """True when posting lists specific eligible states/regions and CT is absent."""
    # Clear nationwide / global remote wins over office-address state name noise.
    if _has_nationwide_us(text) and not re.search(
        r"\b(?:except|excluding|not (?:available|open) in)\s+connecticut\b",
        text,
        re.I,
    ):
        return False

    states = _listed_states(text)
    if not states:
        return False
    ct_present = bool(states & {"connecticut", "CT"})
    restriction = _has_location_restriction_language(text)
    if not restriction and len(states) <= 2:
        # Single HQ / office address — do not treat as applicant restriction.
        return False
    if restriction and not ct_present:
        return True
    return False


def parse_location_eligible(text: str, applicant_location: str = "Connecticut") -> ParseResult:
    """CT applicant location eligibility: Yes / No / Unknown (rule.txt §1)."""
    lowered = text.lower()
    applicant = (applicant_location or "Connecticut").lower()

    if _mentions_connecticut(text) or applicant in lowered:
        return ParseResult("Yes", "Connecticut included as eligible work location", False)

    if _has_nationwide_us(text) and not _states_exclude_connecticut(text):
        evidence, _ = find_keyword_match(
            text,
            [
                "united states",
                "nationwide",
                "u.s. remote",
                "usa remote",
                "remote us",
                "worldwide",
                "globally",
                "work from anywhere",
                "executed globally",
            ],
        )
        return ParseResult("Yes", evidence or "Nationwide / global remote eligibility", False)

    if _states_exclude_connecticut(text):
        return ParseResult("No", "Eligible locations exclude Connecticut", False)

    if re.search(
        r"\bmust (?:live|reside|be located|commute|report).{0,40}"
        r"(?:office|hq|headquarters|in)\b",
        lowered,
    ) and not _mentions_connecticut(text):
        return ParseResult("No", "Must live/commute near a non-Connecticut location", False)

    if re.search(r"\b(?:remote|fully remote|work from home|wfh)\b", lowered):
        if not _has_nationwide_us(text) and "united states" not in lowered and "usa" not in lowered:
            return ParseResult(
                "Unknown",
                "Remote mentioned without eligible country, states, or regions",
                True,
            )

    if not re.search(r"\b(?:remote|location|united states|usa|nationwide|global)\b", lowered):
        return ParseResult("Unknown", "Not enough information for Connecticut eligibility", True)

    return ParseResult("Unknown", "Connecticut eligibility unclear", True)


def parse_remote_eligible(
    text: str,
    keywords,
    *,
    location_eligible: str | None = None,
) -> ParseResult:
    """Remote for CT applicant: Yes / No / Unknown (rule.txt §2)."""
    lowered = text.lower()
    onsite_evidence, onsite = find_keyword_match(text, keywords.onsite)
    hybrid_evidence, hybrid = find_keyword_match(text, keywords.hybrid)
    remote_evidence, remote = find_keyword_match(text, keywords.fully_remote)
    has_remote_word = bool(re.search(r"\b(?:remote|work from home|wfh|virtual)\b", lowered))

    if location_eligible == "No":
        if remote or has_remote_word:
            return ParseResult("No", "Remote role excludes Connecticut applicants", False)
        if onsite or hybrid:
            return ParseResult("No", onsite_evidence or hybrid_evidence or "Non-remote for CT", False)

    if onsite and not remote and not has_remote_word:
        return ParseResult("No", onsite_evidence, False)

    if hybrid and not remote and not re.search(
        r"\bremote\b.{0,30}\b(?:or|option|alternative|exception)\b",
        lowered,
    ):
        # Hybrid required without remote alternative → No for CT unless CT office.
        if not _mentions_connecticut(text):
            return ParseResult("No", hybrid_evidence or "Hybrid/on-site attendance required", False)

    if remote or has_remote_word:
        if _states_exclude_connecticut(text) or location_eligible == "No":
            return ParseResult("No", remote_evidence or "Remote restricted away from Connecticut", False)
        if re.search(
            r"\b(?:flexible work|wfh stipend|work from home some)\b",
            lowered,
        ) and not remote:
            return ParseResult("Unknown", "Flexible/WFH language without clear remote policy", True)
        return ParseResult("Yes", remote_evidence or "Remote position stated", False)

    if not onsite and not hybrid and not has_remote_word:
        return ParseResult("Unknown", "Remote / hybrid / on-site not clearly stated", True)

    return ParseResult("Unknown", "Remote arrangement unclear", True)


def parse_remote_policy(text: str, keywords) -> ParseResult:
    """Legacy remote_policy codes kept for storage/UI compatibility."""
    location = parse_location_eligible(text)
    remote = parse_remote_eligible(text, keywords, location_eligible=str(location.value))
    if remote.value == "Yes" and location.value == "Yes":
        return ParseResult("fully_remote_us", remote.evidence_text, False)
    if remote.value == "Yes" and location.value == "Unknown":
        return ParseResult("remote_unclear", remote.evidence_text, True)
    if remote.value == "No":
        onsite_evidence, onsite = find_keyword_match(text, keywords.onsite)
        hybrid_evidence, hybrid = find_keyword_match(text, keywords.hybrid)
        if onsite:
            return ParseResult("onsite_required", onsite_evidence, False)
        if hybrid:
            return ParseResult("hybrid_required", hybrid_evidence, False)
        return ParseResult("remote_specific_states", remote.evidence_text, True)
    return ParseResult("unclear", remote.evidence_text, True)


def parse_travel(text: str, keywords) -> ParseResult:
    """Travel required for a Connecticut employee (rule.txt §6). Yes/No only."""
    no_evidence, no_travel = find_keyword_match(text, keywords.travel_not_required)
    if no_travel:
        return ParseResult(False, no_evidence, False)

    # Discretionary stipends / benefit offsites / social travel are not required travel.
    if re.search(
        r"\b(?:discretionary|optional|welcome|encouraged|hope[d]?)\b.{0,40}"
        r"\b(?:stipend|travel|visit|office|offsite|retreat)\b",
        text,
        re.I,
    ) or re.search(
        r"\b(?:social travel|travel stipend|co-?working stipend|"
        r"annual (?:company )?offsite|offsites have included)\b",
        text,
        re.I,
    ):
        # If the ONLY travel mentions are benefit/stipend style, treat as No.
        required_hit = find_keyword_match(text, keywords.travel_required)[1]
        if not required_hit or re.search(
            r"\b(?:stipend|discretionary|social travel|annual company offsite)\b",
            text,
            re.I,
        ):
            return ParseResult(False, "Travel/offsite mentioned as benefit or discretionary stipend", False)

    # Optional / welcome / encouraged visits are not required travel.
    if re.search(
        r"\b(?:welcome|encouraged|hope[d]?|optional)\b.{0,40}\b(?:visit|travel|office|offsite)\b",
        text,
        re.I,
    ):
        return ParseResult(False, "Office visit encouraged/optional, not required", False)

    # On-call is not travel.
    if re.search(r"\b(?:on-call|after-hours|incident response|shift coverage)\b", text, re.I):
        if not re.search(r"\btravel\b", text, re.I):
            return ParseResult(False, "On-call/after-hours is not travel", False)

    evidence, required = find_keyword_match(text, keywords.travel_required)
    if required:
        # Travel only for other states and CT excluded → No
        if _states_exclude_connecticut(text) and not _mentions_connecticut(text):
            return ParseResult(False, "Travel applies only to non-Connecticut locations", False)
        return ParseResult(True, evidence, False)

    if re.search(r"\btravel\b", text, re.I):
        if re.search(
            r"\b(?:optional|not required|none|0%|discretionary|stipend|social travel)\b",
            text,
            re.I,
        ):
            return ParseResult(False, "Travel explicitly not required / discretionary", False)
        # Any residual travel mention for CT employee → Yes per rule (incl. occasional / once).
        return ParseResult(True, "Travel mentioned for the role", False)

    return ParseResult(False, "No travel requirement detected", False)


def parse_clearance(text: str, keywords) -> ParseResult:
    """Clearance or fingerprint requirement (rule.txt §4). Yes/No only."""
    evidence, found = find_keyword_match(text, keywords.clearance)
    if found:
        # Normal background/drug checks alone are not clearance/fingerprint.
        snippet = (evidence or "").lower()
        if re.search(
            r"\b(?:criminal background|drug (?:screen|test)|employment verification|"
            r"identity verification|background check)\b",
            snippet,
        ) and not re.search(
            r"\b(?:clearance|fingerprint|biometric|public trust|secret|classified)\b",
            snippet,
        ):
            return ParseResult(False, "Normal background check is not clearance/fingerprint", False)
        return ParseResult(True, evidence, False)

    lowered = text.lower()
    if "clearance" in lowered or "fingerprint" in lowered or "biometric" in lowered:
        if re.search(
            r"\b(?:security clearance|public trust|fingerprint|biometric|ts/sci|top secret)\b",
            lowered,
        ):
            return ParseResult(True, "Clearance or fingerprint requirement stated", False)
    return ParseResult(False, "No clearance or fingerprint requirement detected", False)


def parse_security_related(text: str, keywords) -> ParseResult:
    """Deprecated job-function matcher — prefer parse_restricted_company_industry."""
    evidence, found = find_keyword_match(text, getattr(keywords, "security_related", []) or [])
    if found:
        return ParseResult(True, evidence, False)
    return ParseResult(False, None, False)


def parse_restricted_company_industry(
    text: str,
    keywords,
    *,
    industry: str | None = None,
    company_headline: str | None = None,
) -> ParseResult:
    """Company primary industry is security/defense/federal/gov (rule.txt §5).

    Judges company industry, not job function (IAM/DevSecOps/etc. alone → No).
    """
    company_corpus = "\n".join(filter(None, [industry, company_headline]))
    corpus = company_corpus or text
    terms = list(getattr(keywords, "restricted_company_industry", None) or [])
    terms += list(getattr(keywords, "government_industry", None) or [])
    # Prefer company-facing fields.
    evidence, found = find_keyword_match(company_corpus or "", terms) if company_corpus else (None, False)
    if not found:
        evidence, found = find_keyword_match(corpus, list(getattr(keywords, "security_related", []) or []))
    if not found:
        evidence, found = find_keyword_match(corpus, list(getattr(keywords, "government_industry", []) or []))

    if found:
        # Job-function-only security language in description without company industry → No.
        if not company_corpus and re.search(
            r"\b(?:security engineer|appsec|devsecops|iam|secure coding|fraud|"
            r"compliance|soc 2|stig|rmf)\b",
            (evidence or "").lower(),
        ):
            return ParseResult(False, "Security job function, not company industry", False)
        return ParseResult(True, evidence, False)
    return ParseResult(False, "Company industry is not restricted security/defense/government", False)


def parse_government_industry(text: str, keywords) -> ParseResult:
    evidence, found = find_keyword_match(text, keywords.government_industry)
    return ParseResult(found, evidence, False)


def parse_onsite_onboarding(text: str, keywords) -> ParseResult:
    """On-site onboarding required (rule.txt §7). Yes/No only; default No."""
    remote_ev, remote_onboard = find_keyword_match(
        text, list(getattr(keywords, "remote_onboarding", None) or [])
    )
    if remote_onboard:
        return ParseResult(False, remote_ev, False)

    evidence, found = find_keyword_match(
        text, list(getattr(keywords, "onsite_onboarding", None) or [])
    )
    if found:
        return ParseResult(True, evidence, False)

    if re.search(
        r"\b(?:on-?site|in[- ]person)\b.{0,40}\b(?:onboarding|orientation|first day|first week)\b",
        text,
        re.I,
    ):
        return ParseResult(True, "In-person onboarding stated", False)

    return ParseResult(False, "No on-site onboarding mentioned", False)


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
    elif re.search(r"\bentry[\s\-]?level\b", lowered) or re.search(r"\bentry\b", lowered):
        value = "Entry Level"
    elif "junior" in lowered:
        value = "Junior Level"
    elif "mid" in lowered or "intermediate" in lowered:
        value = "Mid Level"
    else:
        return ParseResult(None, "Experience level unclear", True)
    if value in allowed:
        return ParseResult(value, f"Experience level: {value}", False)
    # Entry Level postings remain Entry even if older configs only list Junior.
    if value == "Entry Level" and "Junior Level" in allowed and "Entry Level" not in allowed:
        return ParseResult("Junior Level", "Experience level: Entry mapped to Junior Level", False)
    return ParseResult(None, "Experience level not allowed", True)
