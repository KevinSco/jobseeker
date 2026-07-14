"""Description similarity helpers."""

from __future__ import annotations

import re
from difflib import SequenceMatcher


def similarity(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    a_clean = re.sub(r"\s+", " ", a.lower()).strip()
    b_clean = re.sub(r"\s+", " ", b.lower()).strip()
    if not a_clean or not b_clean:
        return 0.0
    return SequenceMatcher(None, a_clean[:5000], b_clean[:5000]).ratio()


def is_duplicate_description(a: str | None, b: str | None, threshold: float = 0.92) -> bool:
    return similarity(a, b) >= threshold
