"""HTML and text cleaning."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup


def clean_html(raw_html: str | None) -> str:
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_company(name: str | None) -> str | None:
    if not name:
        return name
    name = normalize_text(name)
    name = re.sub(r"\s+(Inc\.?|LLC|Corp\.?|Ltd\.?)$", "", name, flags=re.I)
    return name


def normalize_job_location(value: str | None) -> str | None:
    """Clean Built In / portal location text for storage and cards.

    - Drop leading "Hiring Remotely in " / "Remote in "
    - Collapse whitespace
    - Keep multi-location as "; "-joined list (HiringCafe-style)
    """
    if not value:
        return None
    text = normalize_text(value)
    if not text:
        return None
    # Split common multi-location separators first, then clean each part.
    parts = re.split(r"\s*[;|]\s*|\s*\n\s*", text)
    cleaned: list[str] = []
    for part in parts:
        token = normalize_text(part)
        if not token:
            continue
        token = re.sub(r"(?i)^hiring\s+remotely\s+in\s+", "", token).strip()
        token = re.sub(r"(?i)^remotely\s+in\s+", "", token).strip()
        token = re.sub(r"(?i)^remote\s+in\s+", "", token).strip()
        token = re.sub(r"(?i)^hiring\s+in\s+", "", token).strip()
        # Skip the "N Locations" label itself if it leaked in.
        if re.fullmatch(r"\d+\s+locations?", token, flags=re.I):
            continue
        if token and token not in cleaned:
            cleaned.append(token)
    if not cleaned:
        return None
    return "; ".join(cleaned)


def split_job_locations(value: str | None) -> list[str]:
    """Split a stored location string into individual places."""
    normalized = normalize_job_location(value)
    if not normalized:
        return []
    return [part.strip() for part in normalized.split(";") if part.strip()]
