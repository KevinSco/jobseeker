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
                # Collapse leftover empty windows from earlier runs into one shared Chrome.
                await self._collapse_kasm_windows(portal, browser)
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
        if self.uses_kasm:
            # Shared Kasm Chrome must stay alive for all Watch viewers.
            # Only disconnect CDP — never close the default remote context/window.
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
        else:
            for context in self._contexts.values():
                try:
                    await context.close()
                except Exception:
                    pass
            self._contexts.clear()

            if self._browser:
                try:
                    await self._browser.close()
                except Exception:
                    pass
                self._browser = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def _collapse_kasm_windows(self, portal: str, browser: Browser) -> None:
        """Keep a single Chrome window/context; close empty extras from prior runs."""
        contexts = list(browser.contexts)
        if not contexts:
            return
        primary = contexts[0]
        for extra in contexts[1:]:
            try:
                await extra.close()
            except Exception:
                pass
        self._contexts[portal] = primary
        pages = list(primary.pages)
        if not pages:
            return
        # Prefer a page that already has content; otherwise keep the first tab.
        keep = pages[0]
        for candidate in pages:
            url = (candidate.url or "").strip().lower()
            if url and url not in {"about:blank", "chrome://newtab/", "chrome://new-tab-page/"}:
                keep = candidate
                break
        for page in pages:
            if page is keep:
                continue
            try:
                await page.close()
            except Exception:
                pass
        await self._prepare_kasm_page(keep)
        log_event(
            logger,
            "Using one shared Kasm Chrome window (flexible size)",
            portal=portal,
            action="kasm_reuse_context",
        )

    async def _prepare_kasm_page(self, page: Page) -> Page:
        """Drop fixed viewport emulation and maximize so Watch resize follows the window."""
        try:
            session = await page.context.new_cdp_session(page)
            try:
                await session.send("Emulation.clearDeviceMetricsOverride")
            except Exception:
                pass
            try:
                win = await session.send("Browser.getWindowForTarget")
                window_id = win.get("windowId")
                if window_id is not None:
                    await session.send(
                        "Browser.setWindowBounds",
                        {"windowId": window_id, "bounds": {"windowState": "maximized"}},
                    )
            except Exception:
                pass
            try:
                await session.detach()
            except Exception:
                pass
        except Exception as exc:
            log_event(
                logger,
                f"Kasm window prepare skipped: {exc}",
                action="kasm_prepare_window",
                level=30,
            )
        try:
            await page.bring_to_front()
        except Exception:
            pass
        return page

    async def get_context(self, portal: str, storage_state: str | None = None) -> BrowserContext:
        if portal not in self._contexts:
            browser = self._browser_for(portal)
            if self.uses_kasm:
                existing = list(browser.contexts)
                if existing:
                    await self._collapse_kasm_windows(portal, browser)
                else:
                    # viewport=None → page size follows the real Chrome window (flexible).
                    self._contexts[portal] = await browser.new_context(viewport=None)
            else:
                kwargs: dict = {"viewport": {"width": 1440, "height": 900}}
                if storage_state:
                    kwargs["storage_state"] = storage_state
                self._contexts[portal] = await browser.new_context(**kwargs)
        return self._contexts[portal]

    async def new_page(self, portal: str, storage_state: str | None = None) -> Page:
        context = await self.get_context(portal, storage_state)
        if self.uses_kasm:
            pages = list(context.pages)
            if pages:
                page = pages[0]
                for extra in pages[1:]:
                    try:
                        await extra.close()
                    except Exception:
                        pass
                return await self._prepare_kasm_page(page)
            page = await context.new_page()
            return await self._prepare_kasm_page(page)
        return await context.new_page()

    @asynccontextmanager
    async def portal_slot(self) -> AsyncGenerator[None, None]:
        async with self._semaphore:
            yield

    async def save_context_state(self, portal: str, path: str) -> None:
        context = self._contexts.get(portal)
        if context:
            await context.storage_state(path=path)
