"""URL normalization for deduplication."""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gh_src",
    "ref",
    "source",
    "src",
    "campaign",
    "session_id",
}


def normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url.strip())
    query = parse_qs(parsed.query, keep_blank_values=False)
    filtered = {k: v for k, v in query.items() if k.lower() not in TRACKING_PARAMS}
    clean_query = urlencode(filtered, doseq=True)
    normalized = parsed._replace(query=clean_query, fragment="")
    path = normalized.path.rstrip("/") or "/"
    return urlunparse(normalized._replace(path=path)).lower()
