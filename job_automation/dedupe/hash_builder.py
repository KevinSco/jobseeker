"""Identity and description hashing."""

from __future__ import annotations

import hashlib
import re

from job_automation.dedupe.url_normalizer import normalize_url


def build_identity_hash(
    company: str | None,
    title: str | None,
    location: str | None,
    remote_policy: str | None = None,
) -> str:
    parts = [
        _normalize_token(company),
        _normalize_token(title),
        _normalize_token(location),
        _normalize_token(remote_policy),
    ]
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_description_hash(description: str | None) -> str | None:
    if not description:
        return None
    cleaned = re.sub(r"\s+", " ", description.lower()).strip()
    if not cleaned:
        return None
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()


def canonical_apply_url(apply_url: str | None, job_url: str | None) -> str | None:
    return normalize_url(apply_url) or normalize_url(job_url)


def _normalize_token(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "", value.lower())
