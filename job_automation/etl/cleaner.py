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
