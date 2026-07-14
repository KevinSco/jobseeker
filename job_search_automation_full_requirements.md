# Job Search Automation MVP — Full Requirements, System Structure, and Workflows

## 1. Project Goal

Build an automated job-search system that searches job portals daily, collects job postings, opens original position or apply links, extracts full job descriptions, performs ETL, deduplicates jobs, applies strict eligibility rules, and produces a clean final list of jobs to apply to.

The system should automate the search and filtering process as much as possible. Manual work should happen only after the automation finishes, mainly for reviewing uncertain jobs and applying to final selected jobs.

---

## 2. MVP Scope

### MVP Job Portals

The MVP should support these job portals:

1. Jobright
2. Built In
3. HiringCafe
4. Glassdoor

Additional job portals can be added after the MVP using the same portal worker structure.

### MVP Output

The MVP should produce a dashboard/list containing:

- `eligible` jobs
- `needs_review` jobs

The system should hide by default:

- `rejected` jobs
- `duplicate` jobs

---

## 3. High-Level System Structure

```text
+----------------------+
|      Scheduler       |
| daily/manual trigger |
+----------+-----------+
           |
           v
+----------------------+
|   Orchestration App  |
| main workflow runner |
+----------+-----------+
           |
           v
+-------------------------------+
|       Portal Worker Layer     |
| Jobright / Built In / etc.    |
+----+---------+---------+------+
     |         |         |
     v         v         v
+---------+ +---------+ +---------+
|Browser  | |Session  | |Search   |
|Manager  | |Manager  | |Executor |
+----+----+ +----+----+ +----+----+
     |         |         |
     +---------+---------+
               |
               v
+-------------------------------+
|       Raw Job Collector       |
| cards, URLs, raw descriptions |
+---------------+---------------+
                |
                v
+-------------------------------+
|            ETL Layer          |
| clean, normalize, extract     |
+---------------+---------------+
                |
                v
+-------------------------------+
|      Deduplication Engine     |
| URL/job ID/title/description  |
+---------------+---------------+
                |
                v
+-------------------------------+
|    Strict Rule Engine         |
| eligible/rejected/review      |
+---------------+---------------+
                |
                v
+-------------------------------+
|            Database           |
| jobs, evidence, sources       |
+---------------+---------------+
                |
                v
+-------------------------------+
|            Dashboard          |
| final apply/review list       |
+-------------------------------+
```

---

## 4. Main System Components

### 4.1 Scheduler

Responsible for starting the automation.

Supported triggers:

- Daily scheduled run
- Manual run
- Per-portal test run
- Retry failed portal run

Recommended tools:

```text
Local MVP:
- cron
- Windows Task Scheduler
- manual CLI command

Production:
- Celery Beat
- GitHub Actions
- server cron
- cloud scheduler
```

---

### 4.2 Orchestration App

Responsible for coordinating the full workflow.

Responsibilities:

- Load config file.
- Start browser automation.
- Start portal workers.
- Control concurrency.
- Send raw jobs to ETL.
- Run deduplication.
- Run strict eligibility decision engine.
- Save results.
- Generate daily summary.
- Expose results to dashboard.

Example orchestration flow:

```text
load_config()
start_browser()
load_sessions()
run_portal_workers_parallel()
collect_raw_jobs()
run_etl()
deduplicate()
apply_rules()
save_results()
update_dashboard()
close_browser()
```

---

### 4.3 Browser Manager

Responsible for creating Playwright browsers, contexts, and pages.

Requirements:

- Use Playwright async.
- Support headless mode for normal runs.
- Support headful mode for login recovery.
- Create isolated browser contexts per portal.
- Reuse saved session storage.
- Limit portal concurrency.

Example:

```text
One browser instance
  ├── Jobright context
  ├── Built In context
  ├── HiringCafe context
  └── Glassdoor context
```

Each context should have separate cookies and login state.

---

### 4.4 Session Manager

Responsible for login/session state.

Requirements:

- Save successful login state to local files.
- Reuse session state in future runs.
- Detect expired sessions.
- Allow manual login recovery in headful mode.
- Never bypass CAPTCHA or MFA.

Example session files:

```text
sessions/jobright.json
sessions/builtin.json
sessions/hiringcafe.json
sessions/glassdoor.json
```

Session workflow:

```text
Check if portal session file exists
  ↓
If exists, load session
  ↓
Open portal homepage
  ↓
Check login status
  ↓
If logged in, continue search
  ↓
If not logged in, open headful login recovery
  ↓
After successful login, save new session
```

---

### 4.5 Portal Worker Layer

Each job portal should have its own worker.

MVP workers:

```text
JobrightWorker
BuiltInWorker
HiringCafeWorker
GlassdoorWorker
```

Each worker must implement the same interface.

Example interface:

```text
search_jobs(config) -> list[RawJob]
open_job(raw_job) -> JobDetail
extract_apply_url(job_page) -> string
extract_description(job_page) -> string
save_or_bookmark(job) -> optional
```

Portal workers should not make final eligibility decisions. They only collect and extract data.

---

### 4.6 Raw Job Collector

Responsible for collecting the first version of job data.

Raw data may include:

```text
source_portal
source_job_id
job_card_title
job_card_company
job_card_location
job_card_salary
job_card_url
portal_job_url
apply_url
raw_html
raw_text
description_text
collected_at
```

The raw job collector should save enough information to debug broken selectors later.

---

### 4.7 ETL Layer

Responsible for transforming raw portal data into normalized job data.

ETL means:

```text
Extract
Transform
Load
```

ETL responsibilities:

- Clean HTML.
- Normalize text.
- Normalize salary.
- Normalize title.
- Normalize company name.
- Normalize remote policy.
- Normalize location.
- Extract structured fields.
- Extract evidence from full job description.
- Convert each job into standard schema.

---

### 4.8 Deduplication Engine

Responsible for detecting jobs already collected.

Deduplication should run before and after description extraction:

1. Early deduplication from job card data.
2. Final deduplication after apply URL and full description are available.

Methods:

```text
canonical apply URL
source job ID
company + title + location hash
description similarity
```

If duplicate:

```text
decision = duplicate
```

---

### 4.9 Strict Rule Engine

Responsible for applying your hard requirements.

Important:

The rule engine should not use scoring.

It should output only:

```text
eligible
needs_review
rejected
duplicate
```

The rule engine should be deterministic and evidence-based.

Rule priority:

```text
1. duplicate
2. rejected
3. needs_review
4. eligible
```

Meaning:

- If duplicate, mark duplicate.
- Else if any hard reject is true, mark rejected.
- Else if any uncertainty or review condition is true, mark needs_review.
- Else mark eligible only if every strict requirement is clearly satisfied.

---

### 4.10 Database

Responsible for storing jobs, sources, decisions, and evidence.

For MVP, SQLite is acceptable.

For production or server deployment, PostgreSQL is recommended.

---

### 4.11 Dashboard

Responsible for showing the final job list.

Default visible statuses:

```text
eligible
needs_review
```

Default hidden statuses:

```text
rejected
duplicate
```

Dashboard actions:

```text
Open apply URL
Open source portal URL
View evidence
Mark applied
Mark removed
Mark duplicate
Move needs_review to eligible
Move eligible to rejected
Add manual note
```

---

## 5. Detailed End-to-End Workflow

```text
1. Scheduler starts daily job-search run.

2. Orchestrator loads job_search_classify_rules.json.

3. Browser Manager starts Playwright.

4. Session Manager loads saved portal sessions.

5. Portal workers run in parallel:
   - JobrightWorker
   - BuiltInWorker
   - HiringCafeWorker
   - GlassdoorWorker

6. Each portal worker:
   - Opens portal
   - Confirms login
   - Applies search rules
   - Searches target keywords
   - Reads job cards
   - Skips already-seen jobs when possible
   - Saves/bookmarks job if appropriate
   - Opens job detail page
   - Clicks apply/open position button
   - Captures original apply/company URL
   - Extracts full job description

7. Raw job data is saved.

8. ETL layer cleans and normalizes data.

9. Evidence extractor reads the full job description carefully.

10. Deduplication engine detects duplicate jobs.

11. Strict rule engine decides:
   - eligible
   - needs_review
   - rejected
   - duplicate

12. Database saves final decision and evidence.

13. Dashboard shows eligible and needs_review jobs.

14. User reviews final list and applies manually.
```

---

## 6. Portal Search Workflow

Each portal should follow this structure:

```text
Start portal worker
  ↓
Load portal session
  ↓
Open portal homepage
  ↓
Check login status
  ↓
If login expired:
    mark portal run as needs_manual_login
    optionally open headful browser
  ↓
For each search query:
    open search page
    apply filters
    read job cards
    paginate results
    collect candidate jobs
  ↓
For each candidate job:
    check early duplicate
    open job detail
    save/bookmark if appropriate
    open apply/original position link
    extract apply URL
    extract full job description
    return normalized raw job
```

---

## 7. ETL Workflow

```text
Raw job
  ↓
Clean HTML
  ↓
Extract readable text
  ↓
Normalize title/company/location
  ↓
Parse salary
  ↓
Extract remote policy
  ↓
Extract travel requirement
  ↓
Extract clearance requirement
  ↓
Extract industry/domain
  ↓
Extract security/cybersecurity relation
  ↓
Detect excluded role
  ↓
Detect role match
  ↓
Detect skill match
  ↓
Create evidence records
  ↓
Send to deduplication and rule engine
```

---

## 8. Decision Workflow

```text
Start with normalized job
  ↓
Check duplicate
  ↓
If duplicate:
    decision = duplicate
    stop
  ↓
Check hard reject rules
  ↓
If any hard reject rule is true:
    decision = rejected
    save rejection reasons and evidence
    stop
  ↓
Check needs_review rules
  ↓
If any review rule is true:
    decision = needs_review
    save review reasons and evidence
    stop
  ↓
Check all eligible requirements
  ↓
If every required condition is clearly true:
    decision = eligible
  ↓
Else:
    decision = needs_review
```

---

## 9. Dashboard Workflow

```text
User opens dashboard
  ↓
Dashboard loads jobs with status eligible or needs_review
  ↓
User filters by:
    - portal
    - role
    - company
    - salary
    - decision
    - date collected
  ↓
User opens job evidence
  ↓
User opens apply URL
  ↓
User manually applies
  ↓
User marks job as applied
```

---

## 10. Search Rules

### 10.1 Raw Search Keywords

```text
python
data engineer
Java
C#
.Net
JavaScript
TypeScript
Software Engineer
PHP
full stack engineer
frontend Engineer
```

### 10.2 Recommended Search Queries

Prefer role + skill combinations instead of broad skill-only searches.

```text
Software Engineer Python
Software Engineer Java
Software Engineer C#
.NET Developer
Full Stack Engineer JavaScript
Full Stack Engineer TypeScript
Frontend Engineer TypeScript
Backend Engineer Python
Backend Engineer Java
Data Engineer Python
PHP Developer
```

### 10.3 Target Roles

Allowed target role families:

```text
Software Engineer
Full Stack Engineer
Frontend Engineer
Backend Engineer
Data Engineer
Python Developer
Java Developer
.NET Developer
C# Developer
JavaScript Developer
TypeScript Developer
PHP Developer
```

### 10.4 Target Skills

```text
Python
Java
C#
.NET
JavaScript
TypeScript
PHP
```

### 10.5 Experience Levels

```text
Junior Level
Mid Level
Senior Level
```

### 10.6 Commitment Types

```text
Full Time
Part Time
Contract
```

### 10.7 Location

```text
United States
Fully remote only
No onsite
No hybrid auto-eligibility
```

### 10.8 Salary

Minimum salary:

```text
$80,000 annually
$50 per hour
```

Salary rules:

```text
Salary present and below minimum: rejected
Salary missing: needs_review
Salary meets or exceeds minimum: pass
```

---

## 11. Strict Eligibility Rules

A job is `eligible` only if all of the following are clearly true:

```text
Role matches target role family
Role is not excluded
Skills match target skills
Fully remote in the United States
No travel required
No security clearance required
Not government industry
Not security/cybersecurity related company, product, team, or role
Salary is present
Salary meets or exceeds minimum
Commitment is Full Time, Part Time, or Contract
Experience level is Junior, Mid, or Senior
```

If anything is unclear, the job should not become `eligible`.

---

## 12. Hard Reject Rules

Reject if any of these are clearly true:

```text
Requires security clearance
Requires Public Trust
Requires Secret / Top Secret / TS/SCI
Requires ability to obtain clearance
Requires travel
Onsite required
Hybrid required without clear fully remote option
Government industry
Salary below $80,000/year
Hourly pay below $50/hour
Role does not match target roles
Skills do not match target skills
Commitment is not allowed
Experience level is not allowed
Role is excluded
```

---

## 13. Needs Review Rules

Mark `needs_review` if any of these are true:

```text
Hybrid in several locations, but candidate's location may work remote
Salary is missing
Remote policy is unclear or conflicting
Travel requirement is unclear
Security clearance requirement is unclear
Remote eligibility depends on specific state/location
Company, product, team, or role is security/cybersecurity related
```

Important:

```text
Hybrid with possible remote exception must be needs_review, not eligible.
Salary missing must be needs_review, not eligible.
Security/cybersecurity related company or role must be needs_review, not rejected.
```

---

## 14. Remote Policy Logic

```text
Fully remote within United States:
    pass

Remote in United States with no conflicting onsite/hybrid text:
    pass

Remote only in specific states:
    needs_review

Hybrid in several locations with possible remote exception:
    needs_review

Hybrid required with no clear remote exception:
    rejected

Onsite required:
    rejected

Remote but travel required:
    rejected

Remote policy unclear:
    needs_review
```

Only clearly fully remote roles should be auto-eligible.

---

## 15. Travel Logic

```text
No travel required:
    pass

Travel required:
    rejected

Travel unclear:
    needs_review
```

Travel keywords:

```text
travel required
requires travel
up to 10% travel
up to 20% travel
up to 25% travel
occasional travel
frequent travel
domestic travel
international travel
travel to client sites
travel to office
on-site client visits
```

No-travel keywords:

```text
no travel required
travel not required
0% travel
```

---

## 16. Security Clearance Logic

```text
No security clearance required:
    pass

Any clearance required:
    rejected

Clearance unclear:
    needs_review
```

Clearance keywords:

```text
security clearance
clearance required
active clearance
must be able to obtain clearance
must obtain clearance
Public Trust
Secret clearance
Top Secret
TS/SCI
SCI clearance
polygraph
DoD clearance
Department of Defense clearance
federal clearance
```

---

## 17. Security/Cybersecurity Related Rule

This rule is different from security clearance.

If the company, product, team, or role is related to security/cybersecurity:

```text
decision = needs_review
```

Security/cybersecurity keywords:

```text
cybersecurity
cyber security
security platform
security engineer
application security
AppSec
cloud security
identity security
endpoint protection
threat detection
threat intelligence
incident response
vulnerability management
SOC
SIEM
DevSecOps
zero trust
fraud detection
risk intelligence
compliance security
information security
infosec
```

Examples:

```text
Software Engineer at CrowdStrike:
    needs_review

Backend Engineer on cloud security product:
    needs_review

Software Engineer requiring Secret clearance:
    rejected
```

---

## 18. Excluded Roles

Reject jobs if the role is not a target software engineering/development role.

Excluded roles:

```text
DevOps Engineer
DevSecOps Engineer
Site Reliability Engineer
SRE
Researcher
Research Engineer
Research Scientist
AI Researcher
ML Researcher
Network Engineer
Systems Engineer
Security Engineer
Cybersecurity Engineer
Information Security Engineer
Cloud Security Engineer
Application Security Engineer
AppSec Engineer
Solutions Architect
Solution Architect
Cloud Architect
Enterprise Architect
Founding CTO
CTO
Chief Technology Officer
Engineering Manager
Director of Engineering
VP of Engineering
Technical Program Manager
Product Manager
Data Scientist
Machine Learning Engineer
AI Engineer
Prompt Engineer
Blockchain Engineer
Sales Engineer
Support Engineer
Customer Success Engineer
Implementation Engineer
Platform Engineer
Infrastructure Engineer
Database Administrator
DBA
IT Engineer
IT Support
Help Desk Engineer
```

Important:

```text
Reject excluded roles even if they include matching skills like Python, JavaScript, Java, C#, .NET, TypeScript, or PHP.
```

---

## 19. Evidence Requirements

Every decision should be explainable.

Store evidence for:

```text
remote_policy
travel_required
security_clearance_required
salary
industry
role_match
skill_match
security_related_company_or_role
role_excluded
decision
```

Evidence format:

```json
{
  "field": "travel_required",
  "value": true,
  "evidence_text": "This position requires up to 20% travel.",
  "source": "job_description"
}
```

The system should read the full job description carefully. It should not rely only on job card summaries or portal filters.

---

## 20. Deduplication Requirements

Deduplication should happen across all MVP portals.

### 20.1 Canonical Apply URL

Normalize URLs before comparison.

Remove tracking parameters:

```text
utm_source
utm_medium
utm_campaign
utm_term
utm_content
gh_src
ref
source
src
campaign
session_id
```

### 20.2 Source Job ID

Use portal job IDs when available.

### 20.3 Company + Title + Location Hash

Normalize and hash:

```text
company
title
location
remote_type
```

### 20.4 Description Similarity

Compare cleaned job description text.

### 20.5 Multiple Source References

If the same job appears on multiple portals:

```text
Keep one primary job record
Store all source portal URLs
Prefer company career/apply URL as primary apply link
```

---

## 21. Database Structure

### 21.1 jobs Table

```sql
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_portal TEXT,
    source_job_id TEXT,
    title TEXT,
    company TEXT,
    location TEXT,
    remote_policy TEXT,
    commitment TEXT,
    experience_level TEXT,
    industry TEXT,
    salary_text TEXT,
    salary_min_annual INTEGER,
    salary_max_annual INTEGER,
    salary_min_hourly REAL,
    salary_max_hourly REAL,
    security_clearance_required BOOLEAN,
    travel_required BOOLEAN,
    security_related_company_or_role BOOLEAN,
    role_excluded BOOLEAN,
    job_url TEXT,
    apply_url TEXT,
    canonical_url TEXT,
    description_text TEXT,
    raw_html TEXT,
    description_hash TEXT,
    identity_hash TEXT,
    is_duplicate BOOLEAN DEFAULT FALSE,
    decision TEXT,
    decision_reason TEXT,
    evidence_json TEXT,
    status TEXT DEFAULT 'new',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 21.2 job_sources Table

```sql
CREATE TABLE job_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    source_portal TEXT,
    source_job_id TEXT,
    job_url TEXT,
    apply_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(job_id) REFERENCES jobs(id)
);
```

### 21.3 portal_runs Table

```sql
CREATE TABLE portal_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_portal TEXT,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    status TEXT,
    jobs_found INTEGER DEFAULT 0,
    jobs_saved INTEGER DEFAULT 0,
    jobs_failed INTEGER DEFAULT 0,
    error_message TEXT
);
```

---

## 22. Recommended Project Structure

```text
job_automation/
  config/
    job_search_classify_rules.json

  main.py

  orchestration/
    runner.py
    scheduler.py
    concurrency.py

  browser/
    playwright_factory.py
    session_manager.py
    browser_manager.py

  portals/
    base.py
    jobright.py
    builtin.py
    hiringcafe.py
    glassdoor.py

  etl/
    cleaner.py
    extractor.py
    salary_parser.py
    remote_policy_parser.py
    clearance_parser.py
    travel_parser.py
    role_parser.py
    skill_parser.py
    industry_parser.py
    security_related_parser.py

  rules/
    rule_engine.py
    decisions.py

  dedupe/
    url_normalizer.py
    hash_builder.py
    similarity.py
    deduplicate.py

  storage/
    database.py
    models.py
    repositories.py

  dashboard/
    app.py
    views.py

  sessions/
    jobright.json
    builtin.json
    hiringcafe.json
    glassdoor.json

  logs/
    automation.log

  data/
    jobs.sqlite
```

---

## 23. Component Responsibility Matrix

| Component | Responsibility |
|---|---|
| Scheduler | Starts daily/manual runs |
| Orchestrator | Coordinates full workflow |
| Browser Manager | Creates browser, context, and page objects |
| Session Manager | Loads/saves login sessions |
| Portal Worker | Searches and extracts jobs from one portal |
| Raw Collector | Stores raw job cards, URLs, descriptions |
| ETL Cleaner | Cleans HTML and text |
| Extractor | Extracts normalized job fields |
| Evidence Extractor | Stores text evidence for decisions |
| Deduplication Engine | Detects duplicate jobs |
| Rule Engine | Applies strict eligible/reject/review logic |
| Database | Stores jobs, decisions, evidence, runs |
| Dashboard | Shows final apply/review list |

---

## 24. Error Handling Requirements

The system should handle:

```text
Portal login expired
CAPTCHA appears
MFA required
Page timeout
Apply link fails to open
New tab blocked
Selector changed
Job description missing
Salary parsing failed
Remote policy unclear
Network error
Duplicate database insert
```

Error handling rules:

```text
If portal login fails:
    mark portal run as needs_manual_login

If one job fails:
    log error and continue with next job

If apply URL cannot be opened:
    save portal job URL and mark needs_review

If job description cannot be extracted:
    mark needs_review

If remote/travel/clearance/salary is unclear:
    mark needs_review
```

---

## 25. Logging Requirements

Log important events:

```text
Run started
Portal worker started
Portal login status
Search query started
Jobs found
Jobs extracted
Jobs deduplicated
Jobs rejected
Jobs marked needs_review
Jobs marked eligible
Portal errors
Run completed
```

Suggested log format:

```text
timestamp | level | portal | job_id | action | message
```

---

## 26. MVP Build Order

```text
1. Finalize rule JSON config.
2. Build database schema.
3. Build base portal worker interface.
4. Build Browser Manager and Session Manager.
5. Build HiringCafe worker first.
6. Extract job cards and full descriptions.
7. Build ETL cleaner and normalizer.
8. Build deduplication engine.
9. Build strict rule engine.
10. Store evidence.
11. Build simple dashboard.
12. Add Built In worker.
13. Add Jobright worker.
14. Add Glassdoor worker.
15. Add daily scheduler.
16. Add run logs and error handling.
```

---

## 27. Out of Scope for MVP

The MVP should not:

```text
Automatically submit applications
Bypass CAPTCHA
Bypass MFA
Spam job portals
Ignore portal terms of service
Apply to hundreds of jobs without review
```

MVP focus:

```text
Search
Extract
Deduplicate
Filter
Classify strictly
Prepare final apply list
```

---

## 28. Definition of Done

The MVP is complete when it can:

```text
Run daily or manually
Search Jobright, Built In, HiringCafe, and Glassdoor
Use configured search keywords and filters
Open apply/company job links
Extract full job descriptions
Read descriptions carefully for remote/travel/clearance/salary/role evidence
Reject clearly invalid jobs
Mark uncertain jobs as needs_review
Deduplicate jobs across portals
Save eligible and needs_review jobs
Show a clean dashboard of jobs to apply to
Store evidence for every decision
```

---

## 29. Example Final Output Record

```json
{
  "decision": "eligible",
  "title": "Backend Software Engineer",
  "company": "Example Corp",
  "location": "Remote, United States",
  "remote_policy": "fully_remote_us",
  "salary_text": "$120,000 - $150,000",
  "commitment": "Full Time",
  "experience_level": "Mid Level",
  "source_portal": "Built In",
  "apply_url": "https://company.example/careers/backend-software-engineer",
  "decision_reason": "Fully remote US role, no travel, no clearance, salary meets minimum, and role/skills match.",
  "evidence": [
    {
      "field": "remote_policy",
      "value": "fully_remote_us",
      "evidence_text": "This role is fully remote within the United States.",
      "source": "job_description"
    },
    {
      "field": "travel_required",
      "value": false,
      "evidence_text": "No travel is required.",
      "source": "job_description"
    },
    {
      "field": "salary",
      "value": "$120,000 - $150,000",
      "evidence_text": "Salary range: $120,000 - $150,000.",
      "source": "job_description"
    }
  ]
}
```
