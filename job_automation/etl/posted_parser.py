"""Parse Built In-style relative posted/reposted strings into absolute datetimes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class PostedParseResult:
    posted_at: datetime | None
    is_reposted: bool = False
    raw_text: str | None = None


_RELATIVE_RE = re.compile(
    r"(?P<reposted>reposted)?\s*"
    r"(?:posted\s+)?"
    r"(?:"
    r"(?P<num>\d+)\s*(?P<unit>minutes?|mins?|m|hours?|hrs?|h|days?|d|weeks?|w|months?)\s*ago"
    r"|"
    r"(?P<word>just\s*now|a\s*few\s*minutes?\s*ago|yesterday|today)"
    r")",
    re.I,
)


def parse_posted_relative(
    text: str | None,
    *,
    now: datetime | None = None,
) -> PostedParseResult:
    """Convert strings like 'Reposted 5 Days Ago' into an absolute UTC datetime."""
    raw = (text or "").strip()
    if not raw:
        return PostedParseResult(posted_at=None, is_reposted=False, raw_text=None)

    lowered = raw.lower()
    is_reposted = "repost" in lowered
    now = now or datetime.utcnow()

    match = _RELATIVE_RE.search(raw)
    if not match:
        # Absolute timestamp already (keep as-is if parseable).
        absolute = _try_parse_absolute(raw)
        return PostedParseResult(
            posted_at=absolute,
            is_reposted=is_reposted,
            raw_text=raw,
        )

    if match.group("reposted"):
        is_reposted = True

    word = (match.group("word") or "").lower().strip()
    if word:
        if "just now" in word or "few minute" in word:
            posted_at = now
        elif word == "today":
            posted_at = now.replace(hour=12, minute=0, second=0, microsecond=0)
            if posted_at > now:
                posted_at = now
        elif word == "yesterday":
            posted_at = now - timedelta(days=1)
        else:
            posted_at = None
        return PostedParseResult(posted_at=posted_at, is_reposted=is_reposted, raw_text=raw)

    num = int(match.group("num") or 0)
    unit = (match.group("unit") or "").lower()
    if unit.startswith("m") and not unit.startswith("mo") and unit not in {"month", "months"}:
        # minutes / mins / m
        delta = timedelta(minutes=num)
    elif unit.startswith("h"):
        delta = timedelta(hours=num)
    elif unit.startswith("d"):
        delta = timedelta(days=num)
    elif unit.startswith("w"):
        delta = timedelta(weeks=num)
    elif unit.startswith("mo"):
        delta = timedelta(days=30 * num)
    else:
        delta = timedelta(0)

    posted_at = now - delta
    # Persist to minute precision.
    posted_at = posted_at.replace(second=0, microsecond=0)
    return PostedParseResult(posted_at=posted_at, is_reposted=is_reposted, raw_text=raw)


def format_posted_relative(
    posted_at: datetime | None,
    *,
    is_reposted: bool = False,
    now: datetime | None = None,
) -> str:
    """Format stored posted_at as Built In-style 'Posted/Reposted N Units Ago'."""
    if not posted_at:
        return ""
    now = now or datetime.utcnow()
    # Treat naive datetimes as UTC wall-clock values.
    delta = now - posted_at
    seconds = max(0, int(delta.total_seconds()))
    prefix = "Reposted" if is_reposted else "Posted"

    if seconds < 60:
        return f"{prefix} Just Now"
    minutes = seconds // 60
    if minutes < 60:
        unit = "Minute" if minutes == 1 else "Minutes"
        return f"{prefix} {minutes} {unit} Ago"
    hours = minutes // 60
    if hours < 48:
        unit = "Hour" if hours == 1 else "Hours"
        return f"{prefix} {hours} {unit} Ago"
    days = hours // 24
    if days < 60:
        unit = "Day" if days == 1 else "Days"
        return f"{prefix} {days} {unit} Ago"
    return f"{prefix} {posted_at.strftime('%b %d, %Y')}"


def _try_parse_absolute(text: str) -> datetime | None:
    cleaned = text.strip()
    for fmt in (
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(cleaned.replace("Z", ""), fmt.replace("Z", ""))
            return dt.replace(second=0, microsecond=0)
        except ValueError:
            continue
    return None
