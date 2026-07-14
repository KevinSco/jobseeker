"""Playwright browser lifecycle management."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from job_automation.config.loader import SearchConfig


class BrowserManager:
    def __init__(
        self,
        config: SearchConfig,
        headful: bool | None = None,
        *,
        guest: bool = False,
    ):
        self.config = config
        self.headful = not config.headless if headful is None else headful
        self.guest = guest
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._contexts: dict[str, BrowserContext] = {}
        self._semaphore = asyncio.Semaphore(config.portal_concurrency)

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
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
            await context.close()
        self._contexts.clear()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def get_context(self, portal: str, storage_state: str | None = None) -> BrowserContext:
        if self._browser is None:
            raise RuntimeError("BrowserManager not started")
        if portal not in self._contexts:
            kwargs: dict = {"viewport": {"width": 1440, "height": 900}}
            if storage_state:
                kwargs["storage_state"] = storage_state
            self._contexts[portal] = await self._browser.new_context(**kwargs)
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
