"""Playwright browser lifecycle management."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from job_automation.config.loader import SearchConfig
from job_automation.logging_config import get_logger, log_event

logger = get_logger(__name__)


class BrowserManager:
    def __init__(
        self,
        config: SearchConfig,
        headful: bool | None = None,
        *,
        guest: bool = False,
        kasm_cdp_by_portal: dict[str, str] | None = None,
    ):
        self.config = config
        self.headful = not config.headless if headful is None else headful
        self.guest = guest
        self.kasm_cdp_by_portal = dict(kasm_cdp_by_portal or {})
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._browsers: dict[str, Browser] = {}
        self._contexts: dict[str, BrowserContext] = {}
        self._semaphore = asyncio.Semaphore(config.portal_concurrency)

    @property
    def uses_kasm(self) -> bool:
        return bool(self.kasm_cdp_by_portal)

    def _browser_for(self, portal: str) -> Browser:
        if self.uses_kasm:
            browser = self._browsers.get(portal)
            if browser is None:
                raise RuntimeError(f"No Kasm CDP browser for portal '{portal}'")
            return browser
        if self._browser is None:
            raise RuntimeError("BrowserManager not started")
        return self._browser

    async def start(self) -> None:
        self._playwright = await async_playwright().start()

        if self.uses_kasm:
            for portal, cdp_url in self.kasm_cdp_by_portal.items():
                log_event(
                    logger,
                    f"Connecting Playwright over CDP: {cdp_url}",
                    portal=portal,
                    action="kasm_cdp_connect",
                )
                try:
                    browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
                except Exception as exc:
                    raise RuntimeError(
                        f"Failed to connect to Kasm Chrome CDP for {portal} at {cdp_url}: {exc}. "
                        "Ensure the Chrome workspace exposes remote debugging "
                        f"(--remote-debugging-port and --remote-debugging-address=0.0.0.0) "
                        "and JobSeek can reach the container IP (same Docker host)."
                    ) from exc
                self._browsers[portal] = browser
            return

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if self.guest:
            launch_args.append("--guest")

        launch_kwargs: dict = {
            "headless": not self.headful,
            "args": launch_args,
        }

        if self.guest and self.headful:
            try:
                self._browser = await self._playwright.chromium.launch(
                    channel="chrome",
                    **launch_kwargs,
                )
            except Exception:
                self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        else:
            self._browser = await self._playwright.chromium.launch(**launch_kwargs)

    async def stop(self) -> None:
        for context in self._contexts.values():
            try:
                await context.close()
            except Exception:
                pass
        self._contexts.clear()

        for portal, browser in list(self._browsers.items()):
            try:
                await browser.close()
            except Exception as exc:
                log_event(
                    logger,
                    f"CDP disconnect error: {exc}",
                    portal=portal,
                    action="kasm_cdp_disconnect",
                    level=30,
                )
        self._browsers.clear()

        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def get_context(self, portal: str, storage_state: str | None = None) -> BrowserContext:
        if portal not in self._contexts:
            browser = self._browser_for(portal)
            kwargs: dict = {"viewport": {"width": 1440, "height": 900}}
            if storage_state:
                kwargs["storage_state"] = storage_state
            self._contexts[portal] = await browser.new_context(**kwargs)
        return self._contexts[portal]

    async def new_page(self, portal: str, storage_state: str | None = None) -> Page:
        context = await self.get_context(portal, storage_state)
        return await context.new_page()

    @asynccontextmanager
    async def portal_slot(self) -> AsyncGenerator[None, None]:
        async with self._semaphore:
            yield

    async def save_context_state(self, portal: str, path: str) -> None:
        context = self._contexts.get(portal)
        if context:
            await context.storage_state(path=path)
