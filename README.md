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

## Daily Scheduler

**Windows:** use Task Scheduler with [`scripts/run_daily.bat`](scripts/run_daily.bat), or run `python -m job_automation.main schedule-info`.

**Linux:** cron with [`scripts/run_daily.sh`](scripts/run_daily.sh), for example:

```bash
crontab -e
# 0 8 * * * /path/to/jobseek/scripts/run_daily.sh >> /path/to/jobseek/logs/daily.log 2>&1
```

## Configuration

Edit [`job_automation/config/job_search_classify_rules.json`](job_automation/config/job_search_classify_rules.json) for search queries, target roles/skills, excluded roles, and keyword lists.

### Kasm remote browsers (optional)

**Offline mode (default, no API keys):** run Chrome-only containers (not a full desktop OS) via Docker, then enable in `.env`:

```bash
# Linux
./scripts/start_kasm_local.sh

# Windows
scripts\start_kasm_local.cmd
```

```env
KASM_ENABLED=true
KASM_MODE=offline
KASM_CDP_ENDPOINTS=http://127.0.0.1:9333,http://127.0.0.1:9334
KASM_VIEW_URLS=https://127.0.0.1:6911,https://127.0.0.1:6912
```

- Watch (HTTPS, no Kasm password): https://127.0.0.1:6911 and https://127.0.0.1:6912  
  JobSeek **Sign in** gates Find Jobs and Watch; browsing the job list stays free.  
- Stop: `./scripts/stop_kasm_local.sh` (Linux) or `scripts\stop_kasm_local.cmd` (Windows)  
- Requires Docker running  
- Ports bind to `127.0.0.1` only  

Click **Find Jobs** (requires account) — Playwright attaches over CDP. **Watch …** opens a JobSeek-gated viewer around Kasm Chrome.

## Dashboard

**Linux:** `./run_dashboard.sh`  
**Windows:** `run_dashboard.cmd`  

Open `http://127.0.0.1:8000` after starting.

- Browse the **Jobs** list without an account
- **Find Jobs** / **Watch** require Sign up or Sign in (modal on demand — not on first load)
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
