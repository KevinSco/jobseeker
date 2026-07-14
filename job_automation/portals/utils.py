"""Shared portal scraping utilities."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from playwright.async_api import Page


def normalize_whitespace(text: str | None) -> str | None:
    if not text:
        return text
    return re.sub(r"\s+", " ", text).strip()


async def safe_inner_text(page: Page, selector: str) -> str | None:
    locator = page.locator(selector).first
    if await locator.count() == 0:
        return None
    return normalize_whitespace(await locator.inner_text())


async def safe_attr(page: Page, selector: str, attr: str) -> str | None:
    locator = page.locator(selector).first
    if await locator.count() == 0:
        return None
    return await locator.get_attribute(attr)


async def click_apply_and_get_url(page: Page, selectors: list[str]) -> str | None:
    context = page.context
    for selector in selectors:
        locator = page.locator(selector).first
        if await locator.count() == 0:
            continue
        try:
            async with context.expect_page(timeout=8000) as new_page_info:
                await locator.click()
            new_page = await new_page_info.value
            await new_page.wait_for_load_state("domcontentloaded", timeout=15000)
            url = new_page.url
            await new_page.close()
            return url
        except Exception:
            href = await locator.get_attribute("href")
            if href and href.startswith("http"):
                return href
            try:
                await locator.click()
                await page.wait_for_timeout(1500)
                if page.url.startswith("http"):
                    return page.url
            except Exception:
                continue
    return None


def extract_job_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    match = re.search(r"/(?:job|jobs|position|careers)/([^/?#]+)", url, re.I)
    if match:
        return match.group(1)
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    for key in ("jobId", "job_id", "id", "gh_jid"):
        if key in qs:
            return qs[key][0]
    return parsed.path.rstrip("/").split("/")[-1] or None
