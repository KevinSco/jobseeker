# Job Search Automation MVP

Automated job search system that collects jobs from multiple portals, extracts full descriptions, deduplicates postings, applies strict eligibility rules, and presents results in a dark dashboard for manual review.

## Features

- Portal workers: HiringCafe, Built In, Jobright, Glassdoor
- Playwright browser automation with saved sessions
- ETL normalization and evidence extraction
- Deterministic rule engine (`eligible`, `needs_review`, `rejected`, `duplicate`)
- SQLite storage
- RocketReach-inspired dashboard with top-center search over collected jobs

## Setup

```bash
cd d:\work\project\jobseek
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
playwright install chromium
```

## CLI

```bash
# Run all portals
python -m job_automation.main run

# Run one portal
python -m job_automation.main run --portal hiringcafe

# Headful run (login recovery)
python -m job_automation.main run --headful

# Interactive login for a portal
python -m job_automation.main login --portal hiringcafe

# Retry failed portals
python -m job_automation.main retry-failed

# Start dashboard
python -m job_automation.main dashboard

# Scheduler setup instructions
python -m job_automation.main schedule-info
```

## Daily Scheduler (Windows)

Use Task Scheduler to run [`scripts/run_daily.bat`](scripts/run_daily.bat) daily, or run:

```bash
python -m job_automation.main schedule-info
```

## Configuration

Edit [`job_automation/config/job_search_classify_rules.json`](job_automation/config/job_search_classify_rules.json) for search queries, target roles/skills, excluded roles, and keyword lists.

## Dashboard

Open `http://127.0.0.1:8000` after starting the dashboard command.

- **Find Jobs** — sends browser-stored credentials to the runner, opens a visible browser, logs in, and searches
- **Settings** — save portal login credentials in your browser (localStorage)
- Top-center search queries jobs already collected by automation
- Default view shows `eligible` and `needs_review`
- Toggle to show rejected/duplicate jobs
- Job detail panel shows evidence and apply/source links

Credentials are stored in the browser (`localStorage`) and sent to the local automation runner only when you click **Find Jobs**. The runner also caches an encrypted copy in `data/credentials.enc` for Playwright login.

Application lifecycle tracking (applied, interview, etc.) is planned for a future phase.

## Tests

```bash
pytest
```

## Project Layout

```text
job_automation/
  config/
  browser/
  portals/
  etl/
  dedupe/
  rules/
  storage/
  orchestration/
  dashboard/
sessions/
data/
logs/
```
