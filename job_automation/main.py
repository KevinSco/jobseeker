"""CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import sys

import uvicorn

from job_automation.config.loader import load_rules
from job_automation.dashboard.app import create_app
from job_automation.logging_config import setup_logging
from job_automation.orchestration.runner import Orchestrator
from job_automation.orchestration.scheduler import print_windows_task_scheduler_instructions
from job_automation.paths import ensure_dirs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Job search automation system")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Run automation for all or selected portals")
    run_parser.add_argument("--portal", action="append", dest="portals")
    run_parser.add_argument("--headful", action="store_true")
    run_parser.add_argument("--guest", action="store_true", help="Use guest Chrome/Chromium profile")

    sub.add_parser("retry-failed", help="Retry portals that failed in the last run")

    login_parser = sub.add_parser("login", help="Interactive login for a portal session")
    login_parser.add_argument("--portal", required=True)

    dash_parser = sub.add_parser("dashboard", help="Start the review dashboard")
    dash_parser.add_argument("--host", default="127.0.0.1")
    dash_parser.add_argument("--port", type=int, default=8000)

    sub.add_parser("schedule-info", help="Print Windows Task Scheduler setup instructions")
    return parser


async def async_main(args: argparse.Namespace) -> int:
    ensure_dirs()
    setup_logging()

    if args.command == "run":
        config = load_rules()
        if args.headful:
            config.headless = False
        orchestrator = Orchestrator(
            config,
            headful=args.headful if args.headful else None,
            guest=args.guest,
        )
        try:
            summary = await orchestrator.run(args.portals)
            print(summary)
            from job_automation.dashboard.search_service import mark_search_finished

            mark_search_finished(summary)
            return 0
        except Exception as exc:
            from job_automation.dashboard.search_service import mark_search_finished

            mark_search_finished(error=str(exc))
            raise

    if args.command == "retry-failed":
        orchestrator = Orchestrator()
        summary = await orchestrator.retry_failed()
        print(summary)
        return 0

    if args.command == "login":
        from job_automation.browser.browser_manager import BrowserManager
        from job_automation.browser.session_manager import SessionManager

        config = load_rules()
        config.headless = False
        browser = BrowserManager(config, headful=True)
        await browser.start()
        try:
            session_manager = SessionManager(browser)
            await session_manager.interactive_login(args.portal)
        finally:
            await browser.stop()
        print(f"Saved session for {args.portal}")
        return 0

    if args.command == "schedule-info":
        print(print_windows_task_scheduler_instructions())
        return 0

    return 1


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    ensure_dirs()

    if args.command == "dashboard":
        setup_logging()
        app = create_app()
        uvicorn.run(app, host=args.host, port=args.port)
        return

    if args.command == "schedule-info":
        print(print_windows_task_scheduler_instructions())
        return

    raise SystemExit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    main()
