"""Automated portal login using saved credentials."""

from __future__ import annotations

from dataclasses import dataclass

import asyncio

from playwright.async_api import Page

from job_automation.browser.credentials import CredentialStore, PortalCredential
from job_automation.email.outlook_imap import fetch_verification_link
from job_automation.logging_config import get_logger, log_event

logger = get_logger(__name__)


@dataclass
class PortalLoginConfig:
    login_url: str
    sign_in_selectors: list[str]
    email_selectors: list[str]
    password_selectors: list[str]
    submit_selectors: list[str]
    magic_link: bool = False
    manual_wait_seconds: int = 180
    email_type_delay_ms: int = 0


PORTAL_HOME_URLS: dict[str, list[str]] = {
    "hiringcafe": ["https://hiring.cafe", "https://hiring.cafe/"],
    "builtin": ["https://builtin.com", "https://builtin.com/", "https://www.builtin.com", "https://www.builtin.com/"],
    "jobright": ["https://jobright.ai", "https://jobright.ai/", "https://www.jobright.ai", "https://www.jobright.ai/"],
    "glassdoor": [
        "https://www.glassdoor.com",
        "https://www.glassdoor.com/",
        "https://glassdoor.com",
        "https://glassdoor.com/",
    ],
}


def normalize_login_url(portal: str, login_url: str | None) -> str | None:
    if not login_url:
        return None
    cleaned = login_url.strip()
    if not cleaned:
        return None
    normalized = cleaned.rstrip("/").lower()
    home_urls = {url.rstrip("/").lower() for url in PORTAL_HOME_URLS.get(portal, [])}
    if normalized in home_urls:
        return None
    return cleaned


def resolve_login_url(portal: str, credential: PortalCredential, config: PortalLoginConfig) -> str:
    custom = normalize_login_url(portal, credential.login_url)
    return custom or config.login_url


PORTAL_LOGIN_CONFIG: dict[str, PortalLoginConfig] = {
    "hiringcafe": PortalLoginConfig(
        login_url="https://hiring.cafe/",
        sign_in_selectors=[
            "a:has-text('Sign in')",
            "a:has-text('Log in')",
            "button:has-text('Sign in')",
        ],
        email_selectors=[
            "input[type='email']",
            "input[name='email']",
            "input[autocomplete='email']",
            "input[id*='email' i]",
        ],
        password_selectors=[
            "input[type='password']",
            "input[name='password']",
            "input[autocomplete='current-password']",
        ],
        submit_selectors=[
            "button[type='submit']",
            "button:has-text('Sign in')",
            "button:has-text('Log in')",
            "input[type='submit']",
        ],
    ),
    "builtin": PortalLoginConfig(
        login_url="https://builtin.com/jobs",
        sign_in_selectors=[
            "a:has-text('Log In')",
            "a:has-text('Log in')",
            "a:has-text('Sign In')",
            "a:has-text('Sign in')",
            "button:has-text('Log In')",
            "button:has-text('Log in')",
        ],
        email_selectors=[
            "input[data-js='email']",
            "#Email",
            "input.email",
            "input[name='Email']",
            "input[type='email']",
        ],
        password_selectors=[],
        submit_selectors=[
            "button.submit.email.button",
            "button.g-recaptcha[data-action='login']",
            "button.submit.email",
            "button:has-text('Login')",
        ],
        magic_link=True,
        manual_wait_seconds=180,
        email_type_delay_ms=200,
    ),
    "jobright": PortalLoginConfig(
        login_url="https://jobright.ai/login",
        sign_in_selectors=[
            "a:has-text('Sign in')",
            "a:has-text('Log in')",
        ],
        email_selectors=[
            "input[type='email']",
            "input[name='email']",
        ],
        password_selectors=["input[type='password']", "input[name='password']"],
        submit_selectors=[
            "button[type='submit']",
            "button:has-text('Sign in')",
            "button:has-text('Continue')",
        ],
    ),
    "glassdoor": PortalLoginConfig(
        login_url="https://www.glassdoor.com/profile/login_input.htm",
        sign_in_selectors=[
            "a:has-text('Sign in')",
            "button:has-text('Sign in')",
        ],
        email_selectors=[
            "input[name='username']",
            "input[id='inlineUserEmail']",
            "input[type='email']",
        ],
        password_selectors=[
            "input[name='password']",
            "input[id='inlineUserPassword']",
            "input[type='password']",
        ],
        submit_selectors=[
            "button[type='submit']",
            "button:has-text('Sign in')",
            "button[data-test='sign-in-button']",
        ],
    ),
}


async def _fill_first(page: Page, selectors: list[str], value: str) -> bool:
    for selector in selectors:
        locator = page.locator(selector).first
        if await locator.count() == 0:
            continue
        try:
            await locator.fill(value, timeout=5000)
            return True
        except Exception:
            continue
    return False


async def _type_first(page: Page, selectors: list[str], value: str, *, delay_ms: int) -> bool:
    for selector in selectors:
        locator = page.locator(selector).first
        if await locator.count() == 0:
            continue
        try:
            await locator.click(timeout=5000)
            await locator.fill("", timeout=5000)
            await locator.press_sequentially(value, delay=delay_ms)
            return True
        except Exception:
            continue
    return False


async def _click_first(page: Page, selectors: list[str]) -> bool:
    for selector in selectors:
        locator = page.locator(selector).first
        if await locator.count() == 0:
            continue
        try:
            await locator.click(timeout=5000)
            return True
        except Exception:
            continue
    return False


async def _wait_for_manual_login(
    page: Page,
    portal: str,
    check_logged_in,
    *,
    total_seconds: int,
    poll_seconds: int = 3,
) -> bool:
    """Poll for login completion, returning as soon as the user finishes login
    (e.g. clicks the magic link in their email)."""
    elapsed = 0
    while elapsed < total_seconds:
        if await check_logged_in(page, portal):
            log_event(logger, "Login detected after manual completion", portal=portal, action="credential_login")
            return True
        await page.wait_for_timeout(poll_seconds * 1000)
        elapsed += poll_seconds
    return await check_logged_in(page, portal)


async def login_with_credentials(
    page: Page,
    portal: str,
    credential: PortalCredential,
    *,
    check_logged_in,
) -> bool:
    config = PORTAL_LOGIN_CONFIG.get(portal)
    if not config:
        log_event(logger, "No login config for portal", portal=portal, action="credential_login", level=40)
        return False

    login_url = resolve_login_url(portal, credential, config)
    log_event(logger, f"Opening login page: {login_url}", portal=portal, action="credential_login")
    await page.goto(login_url, wait_until="domcontentloaded", timeout=90000)
    await page.wait_for_timeout(1500)

    if await check_logged_in(page, portal):
        log_event(logger, "Already logged in", portal=portal, action="credential_login")
        return True

    clicked_sign_in = await _click_first(page, config.sign_in_selectors)
    if clicked_sign_in and portal == "builtin":
        try:
            await page.wait_for_url("**/*account*/**", timeout=15000)
        except Exception:
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
    await page.wait_for_timeout(2000)

    email_ok = False
    pages_to_try = [page] + [p for p in page.context.pages if p is not page]
    for try_page in pages_to_try:
        if config.email_type_delay_ms > 0:
            email_ok = await _type_first(
                try_page,
                config.email_selectors,
                credential.username,
                delay_ms=config.email_type_delay_ms,
            )
        else:
            email_ok = await _fill_first(try_page, config.email_selectors, credential.username)
        if email_ok:
            page = try_page
            break

    if not email_ok:
        log_event(
            logger,
            "Could not find email field — complete login manually in browser",
            portal=portal,
            action="credential_login",
            level=30,
        )
        await page.wait_for_timeout(config.manual_wait_seconds * 1000)
        return await check_logged_in(page, portal)

    if config.magic_link:
        if config.email_type_delay_ms > 0:
            await page.wait_for_timeout(300)
        clicked = await _click_first(page, config.submit_selectors)
        if not clicked:
            try:
                await page.keyboard.press("Enter")
            except Exception:
                pass
        await page.wait_for_timeout(3000)

        if credential.email_app_password:
            log_event(
                logger,
                "Waiting for verification email in Outlook inbox...",
                portal=portal,
                action="credential_login",
            )
            magic_link = await _fetch_magic_link_from_outlook(credential)
            if magic_link:
                log_event(
                    logger,
                    f"Opening verification link from email: {magic_link[:80]}...",
                    portal=portal,
                    action="credential_login",
                )
                await page.goto(magic_link, wait_until="domcontentloaded", timeout=90000)
                await page.wait_for_timeout(4000)
                if await check_logged_in(page, portal):
                    log_event(logger, "Magic-link login succeeded via email", portal=portal, action="credential_login")
                    return True

        log_event(
            logger,
            f"ACTION NEEDED: Open your inbox, click the {portal} verification link. "
            f"Browser will continue automatically once you're logged in "
            f"(waiting up to {config.manual_wait_seconds}s).",
            portal=portal,
            action="credential_login",
            level=30,
        )
        return await _wait_for_manual_login(
            page,
            portal,
            check_logged_in,
            total_seconds=config.manual_wait_seconds,
        )

    password_ok = await _fill_first(page, config.password_selectors, credential.password)
    if not password_ok:
        log_event(
            logger,
            "Could not find login form fields — complete login manually in browser",
            portal=portal,
            action="credential_login",
            level=30,
        )
        await page.wait_for_timeout(90000)
        return await check_logged_in(page, portal)

    clicked = await _click_first(page, config.submit_selectors)
    if not clicked:
        try:
            await page.keyboard.press("Enter")
        except Exception:
            pass

    await page.wait_for_timeout(4000)
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass

    logged_in = await check_logged_in(page, portal)
    if logged_in:
        log_event(logger, "Credential login succeeded", portal=portal, action="credential_login")
    else:
        log_event(
            logger,
            "Auto-login may have failed (CAPTCHA/MFA?) — waiting for manual completion",
            portal=portal,
            action="credential_login",
            level=30,
        )
        await page.wait_for_timeout(120000)
        logged_in = await check_logged_in(page, portal)
    return logged_in


async def _fetch_magic_link_from_outlook(credential: PortalCredential) -> str | None:
    if not credential.email_app_password:
        return None
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            None,
            lambda: fetch_verification_link(
                credential.username,
                credential.email_app_password,
                timeout_seconds=180,
                poll_interval=10,
            ),
        )
    except Exception as exc:
        log_event(
            logger,
            f"Outlook IMAP failed: {exc}",
            action="email_fetch",
            level=40,
        )
        return None


def get_credential(portal: str) -> PortalCredential | None:
    return CredentialStore().get(portal)
