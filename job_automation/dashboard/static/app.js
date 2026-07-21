const {
  SUPPORTED_PORTALS,
  deletePortalCredential,
  getCredentialsForPortals,
  getPortalCredential,
  listPortalCredentialStatus,
  savePortalCredential,
} = window.JobSeekCredentials || {};

let currentPage = 1;
let selectedJobId = null;
let credentialsData = { portals: [] };
let searchPollTimer = null;
let activeDecision = "all";
let activeEntity = "position";
let selectionMode = false;
const selectedJobIds = new Set();
let visibleJobIds = [];
const LONG_PRESS_MS = 1000;

const runsList = document.getElementById("runs-list");
const homeRunsList = document.getElementById("home-runs-list");
const workerLogs = document.getElementById("worker-logs");
const logSource = document.getElementById("log-source");
const logAutoScroll = document.getElementById("log-auto-scroll");
const jobsList = document.getElementById("jobs-list");
const jobDetail = document.getElementById("job-detail");
const pagination = document.getElementById("pagination");
const jobsSearchForm = document.getElementById("jobs-search-form");
const jobsSearchInput = document.getElementById("jobs-search-input");
const homeSearchForm = document.getElementById("home-search-form");
const homeSearchInput = document.getElementById("home-search-input");
const jobsPortalFilter = document.getElementById("jobs-portal-filter");
const jobsSort = document.getElementById("jobs-sort");
const jobsSortTrigger = document.getElementById("jobs-sort-trigger");
const jobsSortMenu = document.getElementById("jobs-sort-menu");
const jobsSortLabel = document.getElementById("jobs-sort-label");
const jobsTotalCount = document.getElementById("jobs-total-count");
const jobsCompanyCount = document.getElementById("jobs-company-count");
const jobsSelectBar = document.getElementById("jobs-select-bar");
const jobsSelectCount = document.getElementById("jobs-select-count");
const selectAllJobsBtn = document.getElementById("select-all-jobs");
const cancelJobsSelectBtn = document.getElementById("cancel-jobs-select");
const deleteSelectedJobsBtn = document.getElementById("delete-selected-jobs");
const runStatus = document.getElementById("run-status");
const kasmLinks = document.getElementById("kasm-links");
const findJobsBtn = document.getElementById("find-jobs-btn");
const stopJobsBtn = document.getElementById("stop-jobs-btn");
const clearJobsBtn = document.getElementById("clear-jobs-btn");
const findJobsModal = document.getElementById("find-jobs-modal");
const findPortals = document.getElementById("find-portals");
const credentialsContainer = document.getElementById("portal-credentials");
const homeView = document.getElementById("home-view");
const jobsView = document.getElementById("jobs-view");
const runsView = document.getElementById("runs-view");
const settingsView = document.getElementById("settings-view");
const authModal = document.getElementById("auth-modal");
const authForm = document.getElementById("auth-form");
const authSlot = document.getElementById("auth-slot");
const signinBtn = document.getElementById("signin-btn");

let logPollTimer = null;
let currentUser = null;
let authMode = "signin";
let authNextAction = null;
/** @type {Map<string, { company: string, jobs: any[], index: number }>} */
const jobStacks = new Map();

const DECISION_LABELS = {
  eligible: "Enable",
  needs_review: "Need Review",
  rejected: "Reject",
  duplicate: "Duplicate",
};

const PORTAL_LABELS = {
  hiringcafe: "HiringCafe",
  builtin: "Built In",
  jobright: "Jobright",
  glassdoor: "Glassdoor",
};

jobsSearchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  currentPage = 1;
  loadJobs();
});

homeSearchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = homeSearchInput.value.trim();
  showView("jobs");
  if (query) {
    jobsSearchInput.value = query;
  }
  currentPage = 1;
  loadJobs();
});

jobsPortalFilter.addEventListener("change", () => {
  currentPage = 1;
  loadJobs();
});

function closeJobsSortMenu() {
  jobsSortMenu?.classList.add("hidden");
  jobsSortTrigger?.setAttribute("aria-expanded", "false");
}

function openJobsSortMenu() {
  jobsSortMenu?.classList.remove("hidden");
  jobsSortTrigger?.setAttribute("aria-expanded", "true");
}

function setJobsSort(value, { reload = true } = {}) {
  const option = document.querySelector(`.jobs-sort-option[data-value="${value}"]`);
  if (!option || !jobsSort) return;
  jobsSort.value = value;
  if (jobsSortLabel) jobsSortLabel.textContent = option.textContent.trim();
  document.querySelectorAll(".jobs-sort-option").forEach((el) => {
    const active = el === option;
    el.classList.toggle("active", active);
    el.setAttribute("aria-selected", active ? "true" : "false");
  });
  closeJobsSortMenu();
  if (reload) {
    currentPage = 1;
    loadJobs();
  }
}

jobsSortTrigger?.addEventListener("click", (event) => {
  event.stopPropagation();
  if (jobsSortMenu?.classList.contains("hidden")) openJobsSortMenu();
  else closeJobsSortMenu();
});

document.querySelectorAll(".jobs-sort-option").forEach((option) => {
  option.addEventListener("click", (event) => {
    event.stopPropagation();
    setJobsSort(option.dataset.value || "relevance");
  });
});

document.addEventListener("click", (event) => {
  if (!event.target.closest("#jobs-sort-wrap")) closeJobsSortMenu();
});

document.querySelectorAll("#decision-chips .chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    document.querySelectorAll("#decision-chips .chip").forEach((el) => el.classList.remove("active"));
    chip.classList.add("active");
    activeDecision = chip.dataset.decision;
    currentPage = 1;
    loadJobs();
  });
});

document.querySelectorAll(".entity-toggle .toggle-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".entity-toggle .toggle-btn").forEach((el) => el.classList.remove("active"));
    btn.classList.add("active");
    activeEntity = btn.dataset.entity;
    currentPage = 1;
    loadJobs();
  });
});

function showView(view) {
  document.querySelectorAll(".nav-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.view === view);
  });
  homeView.classList.toggle("hidden", view !== "home");
  jobsView.classList.toggle("hidden", view !== "jobs");
  runsView.classList.toggle("hidden", view !== "runs");
  settingsView.classList.toggle("hidden", view !== "settings");

  if (view === "runs") {
    startLogPolling();
  } else {
    stopLogPolling();
  }
}

document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => {
    const view = btn.dataset.view;
    showView(view === "settings" ? "settings" : view === "jobs" ? "jobs" : view === "runs" ? "runs" : "home");
    if (view === "settings") loadCredentials();
    if (view === "jobs") loadJobs();
    if (view === "home") loadRuns();
    if (view === "runs") {
      loadRuns();
      loadWorkerLogs();
    }
    closeNavDrawer();
    closeJobsFiltersDrawer();
  });
});

const appShell = document.querySelector(".app");
const navBackdrop = document.getElementById("nav-drawer-backdrop");
const filtersBackdrop = document.getElementById("jobs-filters-backdrop");
const openNavMenuBtn = document.getElementById("open-nav-menu");
const closeNavMenuBtn = document.getElementById("close-nav-menu");
const editSearchCriteriaBtn = document.getElementById("edit-search-criteria");
const closeJobsFiltersBtn = document.getElementById("close-jobs-filters");

function openNavDrawer() {
  closeJobsFiltersDrawer();
  appShell?.classList.add("nav-open");
  openNavMenuBtn?.setAttribute("aria-expanded", "true");
  if (navBackdrop) navBackdrop.hidden = false;
}

function closeNavDrawer() {
  appShell?.classList.remove("nav-open");
  openNavMenuBtn?.setAttribute("aria-expanded", "false");
  if (navBackdrop) navBackdrop.hidden = true;
}

function openJobsFiltersDrawer() {
  closeNavDrawer();
  appShell?.classList.add("filters-open");
  if (filtersBackdrop) filtersBackdrop.hidden = false;
}

function closeJobsFiltersDrawer() {
  appShell?.classList.remove("filters-open");
  if (filtersBackdrop) filtersBackdrop.hidden = true;
}

openNavMenuBtn?.addEventListener("click", () => {
  if (appShell?.classList.contains("nav-open")) closeNavDrawer();
  else openNavDrawer();
});
closeNavMenuBtn?.addEventListener("click", closeNavDrawer);
navBackdrop?.addEventListener("click", closeNavDrawer);

editSearchCriteriaBtn?.addEventListener("click", openJobsFiltersDrawer);
closeJobsFiltersBtn?.addEventListener("click", closeJobsFiltersDrawer);
filtersBackdrop?.addEventListener("click", closeJobsFiltersDrawer);

window.addEventListener("resize", () => {
  if (window.innerWidth > 1400) {
    closeJobsFiltersDrawer();
  }
  if (window.innerWidth > 1100) {
    closeNavDrawer();
  }
});

document.getElementById("refresh-runs-btn")?.addEventListener("click", () => {
  loadRuns();
});

document.getElementById("refresh-logs-btn")?.addEventListener("click", () => {
  loadWorkerLogs();
});

logSource?.addEventListener("change", () => {
  loadWorkerLogs();
});

findJobsBtn.addEventListener("click", async () => {
  const ok = await requireAuth({
    reason: "Sign in to run Find Jobs and watch the live bot browser (Kasm).",
    nextAction: "find-jobs",
  });
  if (!ok) return;
  await openFindJobsModal();
});

stopJobsBtn?.addEventListener("click", async () => {
  const ok = await requireAuth({
    reason: "Sign in to stop the running bot.",
    nextAction: null,
  });
  if (!ok) return;
  const confirmed = await showAppConfirm({
    title: "Stop the bot?",
    message: "This ends the current Find Jobs run. Jobs already saved will stay in the database.",
    confirmLabel: "Stop bot",
    cancelLabel: "Keep running",
    danger: true,
  });
  if (!confirmed) return;
  stopJobsBtn.disabled = true;
  setRunStatus("Stopping bot...", true);
  if (searchPollTimer) {
    clearInterval(searchPollTimer);
    searchPollTimer = null;
  }
  const response = await fetch("/api/search/stop", { method: "POST" });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    stopJobsBtn.disabled = false;
    showCredentialToast(err.detail || "Failed to stop bot", "error");
    pollSearchStatus();
    return;
  }
  const status = await response.json();
  setSearchControls(false);
  renderKasmLinks([]);
  if (runsView?.classList.contains("hidden")) {
    stopLogPolling();
  }
  setRunStatus(status.stop_message || "Stopped", false);
  await loadRuns();
  await loadJobs();
});

clearJobsBtn?.addEventListener("click", async () => {
  const authed = await requireAuth({
    reason: "Sign in to clear collected jobs.",
    nextAction: null,
  });
  if (!authed) return;
  const ok = await showAppConfirm({
    title: "Clear all jobs?",
    message: "Delete all collected jobs, sources, and run history from the database?",
    confirmLabel: "Clear all",
    cancelLabel: "Cancel",
    danger: true,
  });
  if (!ok) return;
  try {
    const response = await fetch("/api/jobs/clear", { method: "POST" });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to clear jobs");
    }
    const data = await response.json();
    selectedJobId = null;
    closeJobDetailDrawer();
    jobDetail.innerHTML = `<div class="job-detail empty">Select a job to view evidence and links.</div>`;
    await loadJobs();
    await loadRuns();
    showCredentialToast(`Cleared ${data.jobs_deleted || 0} jobs from database.`, "success");
  } catch (error) {
    showCredentialToast(error.message || "Failed to clear jobs", "error");
  }
});

document.getElementById("cancel-find-jobs").addEventListener("click", () => {
  findJobsModal.classList.add("hidden");
});

document.getElementById("go-settings-btn").addEventListener("click", () => {
  findJobsModal.classList.add("hidden");
  showView("settings");
  loadCredentials();
});

document.getElementById("confirm-find-jobs").addEventListener("click", startFindJobs);

signinBtn?.addEventListener("click", () => {
  openAuthModal({ reason: "Sign in to run the bot and watch Kasm browsers." });
});

document.getElementById("auth-cancel")?.addEventListener("click", () => {
  closeAuthModal();
});

document.querySelectorAll(".auth-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    setAuthMode(tab.dataset.authTab || "signin");
  });
});

authForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  await submitAuthForm();
});

async function openFindJobsModal() {
  await loadCredentials();
  renderFindPortalsModal();
  findJobsModal.classList.remove("hidden");
}

async function loadAuth() {
  try {
    const response = await fetch("/api/auth/me");
    const data = await response.json();
    currentUser = data.authenticated ? data.user : null;
  } catch {
    currentUser = null;
  }
  renderAuthSlot();
  return Boolean(currentUser);
}

function renderAuthSlot() {
  if (!authSlot) return;
  if (currentUser) {
    authSlot.innerHTML = `
      <span class="auth-user" title="${escapeHtml(currentUser.email)}">${escapeHtml(currentUser.email)}</span>
      <button id="signout-btn" class="secondary-btn" type="button">Sign out</button>
    `;
    document.getElementById("signout-btn")?.addEventListener("click", async () => {
      await fetch("/api/auth/signout", { method: "POST" });
      currentUser = null;
      renderAuthSlot();
      renderKasmLinks([]);
      await loadCredentials();
      showCredentialToast("Signed out.", "success");
    });
    return;
  }
  authSlot.innerHTML = `<button id="signin-btn" class="secondary-btn" type="button">Sign in</button>`;
  document.getElementById("signin-btn")?.addEventListener("click", () => {
    openAuthModal({ reason: "Sign in to run the bot and watch Kasm browsers." });
  });
}

function openAuthModal({ reason, nextAction = null } = {}) {
  authNextAction = nextAction;
  const reasonEl = document.getElementById("auth-modal-reason");
  if (reasonEl && reason) reasonEl.textContent = reason;
  setAuthMode("signin");
  const errorEl = document.getElementById("auth-error");
  if (errorEl) {
    errorEl.textContent = "";
    errorEl.classList.add("hidden");
  }
  authModal?.classList.remove("hidden");
  authModal?.setAttribute("aria-hidden", "false");
  document.getElementById("auth-email")?.focus();
}

function closeAuthModal() {
  authModal?.classList.add("hidden");
  authModal?.setAttribute("aria-hidden", "true");
  authNextAction = null;
}

function setAuthMode(mode) {
  authMode = mode === "signup" ? "signup" : "signin";
  document.querySelectorAll(".auth-tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.authTab === authMode);
  });
  const title = document.getElementById("auth-modal-title");
  const submit = document.getElementById("auth-submit");
  const password = document.getElementById("auth-password");
  if (title) {
    title.textContent = authMode === "signup" ? "Create your account" : "Sign in to use the bot";
  }
  if (submit) submit.textContent = authMode === "signup" ? "Sign up" : "Sign in";
  if (password) {
    password.autocomplete = authMode === "signup" ? "new-password" : "current-password";
  }
}

async function submitAuthForm() {
  const email = document.getElementById("auth-email")?.value.trim() || "";
  const password = document.getElementById("auth-password")?.value || "";
  const errorEl = document.getElementById("auth-error");
  const endpoint = authMode === "signup" ? "/api/auth/signup" : "/api/auth/signin";
  const submit = document.getElementById("auth-submit");
  if (submit) submit.disabled = true;
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(typeof data.detail === "string" ? data.detail : "Authentication failed");
    }
    currentUser = data.user;
    renderAuthSlot();
    const next = authNextAction;
    closeAuthModal();
    showCredentialToast(authMode === "signup" ? "Account created." : "Signed in.", "success");
    await loadCredentials();
    if (next === "find-jobs") {
      await openFindJobsModal();
    } else if (next === "settings") {
      showView("settings");
    } else if (typeof next === "string" && next.startsWith("/")) {
      window.location.href = next;
    }
  } catch (error) {
    if (errorEl) {
      errorEl.textContent = error.message || "Authentication failed";
      errorEl.classList.remove("hidden");
    }
  } finally {
    if (submit) submit.disabled = false;
  }
}

async function requireAuth({ reason, nextAction = null } = {}) {
  if (currentUser) return true;
  await loadAuth();
  if (currentUser) return true;
  openAuthModal({ reason, nextAction });
  return false;
}

async function loadRuns() {
  const response = await fetch("/api/runs?limit=20");
  const data = await response.json();
  const html = data.runs.map(renderRun).join("") || "<div class='muted'>No runs yet.</div>";
  if (runsList) runsList.innerHTML = html;
  if (homeRunsList) {
    homeRunsList.innerHTML =
      data.runs.slice(0, 5).map(renderRun).join("") || "<div class='muted'>No runs yet.</div>";
  }
}

function renderRun(run) {
  const when = run.started_at ? new Date(run.started_at).toLocaleString() : "Unknown";
  const statusClass = run.status === "failed" || run.status === "needs_manual_login"
    ? "error"
    : run.status === "running"
      ? "running"
      : "";
  const error = run.error_message
    ? `<div class="job-meta">${escapeHtml(run.error_message)}</div>`
    : "";
  return `
    <div class="run-item ${statusClass}">
      <div><strong>${escapeHtml(run.source_portal)}</strong> · ${escapeHtml(run.status || "unknown")}</div>
      <div class="job-meta">${when}</div>
      <div class="job-meta">Found ${run.jobs_found}, saved ${run.jobs_saved}, failed ${run.jobs_failed}</div>
      ${error}
    </div>
  `;
}

async function loadWorkerLogs() {
  if (!workerLogs) return;
  const source = logSource?.value || "automation";
  try {
    const response = await fetch(`/api/logs?source=${encodeURIComponent(source)}&lines=400`);
    if (!response.ok) {
      workerLogs.textContent = "Failed to load logs.";
      return;
    }
    const data = await response.json();
    const content = (data.content || "").trim();
    workerLogs.textContent = content || "No logs yet. Start a search to see bot worker activity.";
    workerLogs.classList.toggle("muted", !content);
    if (logAutoScroll?.checked) {
      workerLogs.scrollTop = workerLogs.scrollHeight;
    }
  } catch (error) {
    workerLogs.textContent = `Failed to load logs: ${error.message || error}`;
  }
}

function startLogPolling() {
  stopLogPolling();
  loadWorkerLogs();
  logPollTimer = setInterval(() => {
    loadWorkerLogs();
    loadRuns();
  }, 2500);
}

function stopLogPolling() {
  if (logPollTimer) {
    clearInterval(logPollTimer);
    logPollTimer = null;
  }
}

async function loadJobs() {
  const params = new URLSearchParams({
    page: String(currentPage),
    page_size: "48",
    sort: jobsSort?.value || "relevance",
  });
  const q = jobsSearchInput.value.trim();
  if (q) params.set("q", q);
  if (jobsPortalFilter.value) params.set("portal", jobsPortalFilter.value);

  if (activeDecision === "all") {
    params.set("show_hidden", "true");
  } else {
    params.set("decision", activeDecision);
    params.set("show_hidden", "true");
  }

  const response = await fetch(`/api/jobs?${params.toString()}`);
  const data = await response.json();
  const total = Number(data.total || 0);
  const companies = Number(data.companies || 0);
  if (jobsTotalCount) jobsTotalCount.textContent = formatCount(total);
  if (jobsCompanyCount) jobsCompanyCount.textContent = formatCount(companies);
  visibleJobIds = (data.jobs || []).map((job) => Number(job.id));
  jobStacks.clear();

  if (activeEntity === "companies") {
    jobsList.className = "jobs-grid";
    jobsList.innerHTML =
      renderJobsByCompany(data.jobs) || "<div class='muted jobs-empty'>No jobs found.</div>";
  } else {
    jobsList.className = "jobs-grid";
    jobsList.innerHTML =
      renderGroupedJobCards(data.jobs) || "<div class='muted jobs-empty'>No jobs found.</div>";
  }

  renderPagination(data.total, data.page, data.page_size);
  bindJobCards();
  updateSelectBar();
}

function formatCount(value) {
  return Number(value || 0).toLocaleString();
}

function companyKey(name) {
  return String(name || "Unknown company")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");
}

function groupJobsByCompany(jobs) {
  const groups = new Map();
  for (const job of jobs || []) {
    const company = job.company || "Unknown company";
    const key = companyKey(company);
    if (!groups.has(key)) groups.set(key, { company, jobs: [] });
    groups.get(key).jobs.push(job);
  }
  return Array.from(groups.entries());
}

function renderGroupedJobCards(jobs) {
  return groupJobsByCompany(jobs)
    .map(([key, group]) => {
      jobStacks.set(key, { company: group.company, jobs: group.jobs, index: 0 });
      return renderCompanyStackCard(key, group.jobs, 0);
    })
    .join("");
}

function renderJobsByCompany(jobs) {
  return groupJobsByCompany(jobs)
    .sort(([, a], [, b]) => a.company.localeCompare(b.company))
    .map(([key, group]) => {
      jobStacks.set(key, { company: group.company, jobs: group.jobs, index: 0 });
      return renderCompanyStackCard(key, group.jobs, 0);
    })
    .join("");
}

function decisionLabel(decision) {
  return DECISION_LABELS[decision] || decision || "Unknown";
}

function companyInitials(name) {
  const parts = String(name || "?")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
}

function relativeTime(iso) {
  if (!iso) return "";
  // Backend stores UTC without a timezone suffix; treat naive ISO as UTC.
  let normalized = String(iso).trim();
  if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(normalized) && !/[zZ]|[+-]\d{2}:?\d{2}$/.test(normalized)) {
    normalized = normalized.replace(" ", "T");
    if (!normalized.endsWith("Z")) normalized += "Z";
  }
  const then = new Date(normalized).getTime();
  if (Number.isNaN(then)) return "";
  const diffSec = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (diffSec < 60) return "Just Now";
  const mins = Math.floor(diffSec / 60);
  if (mins < 60) return `${mins} ${mins === 1 ? "Minute" : "Minutes"} Ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 48) return `${hours} ${hours === 1 ? "Hour" : "Hours"} Ago`;
  const days = Math.floor(hours / 24);
  if (days < 60) return `${days} ${days === 1 ? "Day" : "Days"} Ago`;
  return new Date(normalized).toLocaleDateString();
}

function formatPostedLabel(job) {
  if (!job) return "";
  const when = job.posted_at || job.created_at;
  if (!when) return job.posted_text || "";
  const distance = relativeTime(when);
  if (!distance) return job.posted_text || "";
  if (/^(Posted|Reposted)\b/i.test(distance)) return distance;
  const prefix = job.is_reposted ? "Reposted" : "Posted";
  if (/^just now$/i.test(distance)) return `${prefix} Just Now`;
  return `${prefix} ${distance}`;
}

function renderCompanyStackCard(stackKey, jobs, index) {
  const safeIndex = Math.max(0, Math.min(index, jobs.length - 1));
  const job = jobs[safeIndex];
  if (!job) return "";
  const checked = selectedJobIds.has(job.id);
  const selectedClass = selectedJobId === job.id && !selectionMode ? "selected" : "";
  const checkedClass = checked ? "checked" : "";
  const selectClass = selectionMode ? "select-mode" : "";
  const stackedClass = jobs.length > 1 ? "job-card-stacked" : "";
  const stackDepth = Math.min(jobs.length - 1, 2);

  return `
    <article
      class="job-card ${stackedClass} ${selectedClass} ${checkedClass} ${selectClass}"
      data-job-id="${job.id}"
      data-stack-key="${escapeHtml(stackKey)}"
      data-stack-index="${safeIndex}"
      data-stack-count="${jobs.length}"
      style="${jobs.length > 1 ? `--stack-depth: ${stackDepth}` : ""}"
    >
      ${jobs.length > 1 ? `<div class="job-card-stack-shadow" aria-hidden="true"></div>` : ""}
      ${renderJobCardBody(job, stackKey, safeIndex, jobs.length)}
    </article>
  `;
}

function renderJobCardBody(job, stackKey, index, stackCount) {
  const company = job.company || "Unknown company";
  const location = job.location || "Remote / Unknown";
  const salary = job.salary_text || "";
  const level = job.experience_level || "";
  const reason = job.decision_reason || "";
  const applyUrl = job.apply_url || "";
  const jobUrl = job.job_url || "";
  const companyUrl = job.company_url || "";
  const status = String(job.status || "new").toLowerCase();
  const decision = String(job.decision || "").toLowerCase();
  const posted = formatPostedLabel(job);
  const industry = job.industry || "";
  const requirements =
    job.match_background ||
    job.company_headline ||
    evidenceText(job.evidence, "skill_match") ||
    (decision === "eligible" ? reason : "") ||
    "";
  const skills = Array.isArray(job.skills_required)
    ? job.skills_required
    : skillsFromEvidence(job.evidence);
  const isSaved = status === "saved" || status === "applied";
  const isApplied = status === "applied";
  const showSnippet = decision === "needs_review" || decision === "rejected";

  const metaTags = [];
  if (salary && salary !== "Not listed") {
    metaTags.push(`<span class="job-tag salary">${escapeHtml(salary)}</span>`);
  }
  if (level) metaTags.push(`<span class="job-tag">${escapeHtml(level)}</span>`);
  if (job.source_portal) {
    metaTags.push(
      `<span class="job-tag portal">${escapeHtml(PORTAL_LABELS[job.source_portal] || job.source_portal)}</span>`
    );
  }
  if (isApplied) metaTags.push(`<span class="job-tag status-applied">Applied</span>`);
  else if (isSaved) metaTags.push(`<span class="job-tag status-saved">Saved</span>`);

  const skillTags = skills
    .slice(0, 6)
    .map((skill) => `<span class="job-tag skill">${escapeHtml(skill)}</span>`)
    .join("");

  const pager =
    stackCount > 5
      ? `<span class="job-stack-counter">${index + 1} / ${stackCount}</span>`
      : `<div class="job-stack-dots" role="tablist" aria-label="Jobs at ${escapeHtml(company)}">
          ${Array.from({ length: stackCount }, (_, i) =>
            `<button type="button" class="job-stack-dot ${i === index ? "active" : ""}" data-stack-key="${escapeHtml(stackKey)}" data-stack-index="${i}" aria-label="Job ${i + 1} of ${stackCount}"></button>`
          ).join("")}
        </div>`;
  const slider =
    stackCount > 1
      ? `
      <div class="job-stack-slider" onclick="event.stopPropagation()">
        <button type="button" class="job-stack-nav job-stack-prev" data-stack-key="${escapeHtml(stackKey)}" aria-label="Previous job">‹</button>
        ${pager}
        <button type="button" class="job-stack-nav job-stack-next" data-stack-key="${escapeHtml(stackKey)}" aria-label="Next job">›</button>
      </div>`
      : "";

  return `
      ${
        selectionMode
          ? `<label class="job-select" onclick="event.stopPropagation()">
              <input type="checkbox" class="job-select-input" data-job-id="${job.id}" ${selectedJobIds.has(job.id) ? "checked" : ""}>
            </label>`
          : ""
      }
      <div class="job-card-hover">
        <div class="job-hover-top">
          <button type="button" class="job-tool-btn save ${isSaved ? "active" : ""}" data-action="save" data-job-id="${job.id}">${isSaved ? "Saved" : "Save"}</button>
          <button type="button" class="job-tool-btn applied ${isApplied ? "active" : ""}" data-action="applied" data-job-id="${job.id}">${isApplied ? "Applied" : "Mark Applied"}</button>
        </div>
        ${
          companyUrl
            ? `<a class="job-icon-btn company-web job-hover-company" href="${escapeHtml(companyUrl)}" target="_blank" rel="noopener noreferrer" title="Company website" aria-label="Visit company website"></a>`
            : ""
        }
        <div class="job-hover-bottom">
          ${
            applyUrl
              ? `<a class="job-tool-btn apply" href="${escapeHtml(applyUrl)}" target="_blank" rel="noopener noreferrer">Apply Directly</a>`
              : `<span class="job-tool-btn apply disabled" title="No apply link">Apply Directly</span>`
          }
          <button type="button" class="job-icon-btn hide" data-action="hide" data-job-id="${job.id}" title="Hide job" aria-label="Hide job"></button>
        </div>
      </div>
      <div class="job-card-body">
      <div class="job-card-top">
        <h3 class="job-title">${escapeHtml(job.title || "Untitled")}</h3>
        ${posted ? `<span class="job-posted">${escapeHtml(posted)}</span>` : ""}
      </div>
      <div class="job-location">
        <span class="job-location-icon" aria-hidden="true"></span>
        <span>${escapeHtml(location)}</span>
      </div>
      ${
        decision
          ? `<div class="job-status-row"><span class="job-tag decision ${escapeHtml(decision)}">${escapeHtml(decisionLabel(decision))}</span></div>`
          : ""
      }
      ${metaTags.length ? `<div class="job-tags">${metaTags.join("")}</div>` : ""}
      <div class="job-company">
        <div class="job-company-avatar" aria-hidden="true">${escapeHtml(companyInitials(company))}</div>
        <div class="job-company-meta">
          <div class="job-company-name">${escapeHtml(company)}${stackCount > 1 ? ` <span class="job-stack-count">· ${stackCount}</span>` : ""}</div>
          ${industry ? `<div class="job-company-sub">${escapeHtml(industry)}</div>` : ""}
        </div>
      </div>
      ${
        requirements
          ? `<p class="job-requirements">${escapeHtml(requirements)}</p>`
          : ""
      }
      ${skillTags ? `<div class="job-tags job-skills">${skillTags}</div>` : ""}
      ${
        showSnippet && reason
          ? `<p class="job-snippet"><span class="job-snippet-icon" aria-hidden="true">!</span><span class="job-snippet-text">${escapeHtml(reason)}</span></p>`
          : ""
      }
      </div>
      <div class="job-card-footer">
        ${
          jobUrl
            ? `<a class="job-posting-link" href="${escapeHtml(jobUrl)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">Job Posting</a>`
            : applyUrl
              ? `<a class="job-posting-link" href="${escapeHtml(applyUrl)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">Job Posting</a>`
              : `<span class="muted">No posting link</span>`
        }
        ${slider}
        <button type="button" class="job-view-all-btn" data-stack-key="${escapeHtml(stackKey)}" data-job-id="${job.id}">View all</button>
      </div>
  `;
}

function skillsFromEvidence(evidence) {
  if (!Array.isArray(evidence)) return [];
  const item = evidence.find((entry) => String(entry?.field || "").toLowerCase() === "skills_required");
  if (!item) return [];
  if (Array.isArray(item.value)) {
    return item.value.map((part) => String(part).trim()).filter(Boolean);
  }
  const text = item.evidence_text || item.value;
  if (!text) return [];
  return String(text)
    .split(/\s*,\s*/)
    .map((part) => part.trim())
    .filter(Boolean);
}

function evidenceText(evidence, field) {
  if (!Array.isArray(evidence)) return "";
  const item = evidence.find((entry) => String(entry?.field || "").toLowerCase() === field);
  if (!item) return "";
  const text = item.evidence_text || item.value;
  if (Array.isArray(text)) return text.map((part) => String(part).trim()).filter(Boolean).join(", ");
  return text ? String(text) : "";
}

function setCompanyStackIndex(stackKey, nextIndex) {
  const stack = jobStacks.get(stackKey);
  if (!stack || !stack.jobs.length) return;
  const index = ((nextIndex % stack.jobs.length) + stack.jobs.length) % stack.jobs.length;
  stack.index = index;
  const card = document.querySelector(`.job-card[data-stack-key="${cssEscape(stackKey)}"]`);
  if (!card) return;
  const wrapper = document.createElement("div");
  wrapper.innerHTML = renderCompanyStackCard(stackKey, stack.jobs, index).trim();
  const nextCard = wrapper.firstElementChild;
  if (!nextCard) return;
  card.replaceWith(nextCard);
  bindOneJobCard(nextCard);
  bindStackControls(nextCard);
}

function syncJobInStacks(jobId, patch) {
  const id = Number(jobId);
  for (const stack of jobStacks.values()) {
    const job = stack.jobs.find((item) => Number(item.id) === id);
    if (job) Object.assign(job, patch);
  }
}

async function patchJobFields(jobId, fields) {
  const response = await fetch(`/api/jobs/${jobId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to update job");
  }
  return response.json();
}

async function handleJobCardAction(action, jobId, card) {
  const id = Number(jobId || card?.dataset.jobId);
  if (!id) return;
  const stackKey = card?.dataset.stackKey;
  const stack = stackKey ? jobStacks.get(stackKey) : null;
  const current = stack?.jobs.find((job) => Number(job.id) === id) || { id, status: "new" };
  const status = String(current.status || "new").toLowerCase();

  try {
    if (action === "save") {
      // new -> saved; saved -> new; applied stays applied (already counts as saved).
      if (status === "applied") return;
      const finalStatus = status === "saved" ? "new" : "saved";
      const updated = await patchJobFields(id, { status: finalStatus });
      syncJobInStacks(id, { status: updated.status || finalStatus });
      if (stackKey) setCompanyStackIndex(stackKey, stack?.index || 0);
      else await loadJobs();
      return;
    }
    if (action === "applied") {
      const finalStatus = status === "applied" ? "saved" : "applied";
      const updated = await patchJobFields(id, { status: finalStatus });
      syncJobInStacks(id, { status: updated.status || finalStatus });
      if (stackKey) setCompanyStackIndex(stackKey, stack?.index || 0);
      else await loadJobs();
      return;
    }
    if (action === "hide") {
      await patchJobFields(id, { status: "hidden" });
      if (stack && stackKey) {
        const idx = stack.jobs.findIndex((job) => Number(job.id) === id);
        if (idx >= 0) stack.jobs.splice(idx, 1);
        if (!stack.jobs.length) {
          jobStacks.delete(stackKey);
          card?.remove();
          await loadJobs();
          return;
        }
        const nextIndex = Math.min(idx, stack.jobs.length - 1);
        setCompanyStackIndex(stackKey, nextIndex);
        return;
      }
      await loadJobs();
    }
  } catch (error) {
    alert(error.message || "Action failed");
  }
}

function cssEscape(value) {
  if (window.CSS?.escape) return window.CSS.escape(value);
  return String(value).replace(/"/g, '\\"');
}

function bindStackControls(root = document) {
  root.querySelectorAll?.(".job-stack-prev").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const key = btn.dataset.stackKey;
      const stack = jobStacks.get(key);
      if (!stack) return;
      setCompanyStackIndex(key, stack.index - 1);
    });
  });
  root.querySelectorAll?.(".job-stack-next").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const key = btn.dataset.stackKey;
      const stack = jobStacks.get(key);
      if (!stack) return;
      setCompanyStackIndex(key, stack.index + 1);
    });
  });
  root.querySelectorAll?.(".job-stack-dot").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const key = btn.dataset.stackKey;
      const index = Number(btn.dataset.stackIndex || 0);
      setCompanyStackIndex(key, index);
    });
  });
}

function bindOneJobCard(card) {
  let pressTimer = null;
  let longPressTriggered = false;

  const clearPress = () => {
    if (pressTimer) {
      clearTimeout(pressTimer);
      pressTimer = null;
    }
  };

  const interactiveSelector =
    "a, button, .job-select, .job-stack-slider, .job-view-all-btn, .job-icon-btn, .job-tool-btn, .job-posting-link, .job-card-footer";

  const startPress = (event) => {
    if (event.type === "mousedown" && event.button !== 0) return;
    if (event.target.closest(interactiveSelector)) return;
    longPressTriggered = false;
    clearPress();
    pressTimer = setTimeout(() => {
      longPressTriggered = true;
      const id = Number(card.dataset.jobId);
      if (selectionMode) {
        toggleJobSelection(id, true);
      } else {
        enterSelectionMode(id);
      }
    }, LONG_PRESS_MS);
  };

  card.addEventListener("mousedown", startPress);
  card.addEventListener("touchstart", startPress, { passive: true });
  card.addEventListener("mouseup", clearPress);
  card.addEventListener("mouseleave", clearPress);
  card.addEventListener("touchend", clearPress);
  card.addEventListener("touchcancel", clearPress);

  card.addEventListener("click", async (event) => {
    if (event.target.closest(interactiveSelector)) return;
    if (longPressTriggered) {
      longPressTriggered = false;
      return;
    }
    const currentId = Number(card.dataset.jobId);
    if (selectionMode) {
      const currentlyChecked = selectedJobIds.has(currentId);
      toggleJobSelection(currentId, !currentlyChecked);
      return;
    }
    selectedJobId = currentId;
    document.querySelectorAll(".job-card.selected").forEach((el) => el.classList.remove("selected"));
    card.classList.add("selected");
    await openJobDetailScreen(currentId, card.dataset.stackKey);
  });

  card.querySelector(".job-select-input")?.addEventListener("change", (event) => {
    toggleJobSelection(Number(event.target.dataset.jobId || card.dataset.jobId), event.target.checked);
  });

  card.querySelector(".job-card-footer")?.addEventListener("click", (event) => {
    event.stopPropagation();
  });

  card.querySelectorAll(".job-view-all-btn").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (selectionMode) return;
      const id = Number(btn.dataset.jobId || card.dataset.jobId);
      selectedJobId = id;
      openCompanyJobsModal(btn.dataset.stackKey || card.dataset.stackKey, id);
    });
  });

  card.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (selectionMode) return;
      await handleJobCardAction(btn.dataset.action, btn.dataset.jobId || card.dataset.jobId, card);
    });
  });
}

function bindJobCards() {
  document.querySelectorAll(".job-card").forEach((card) => bindOneJobCard(card));
  bindStackControls(document);
}

function updateSelectBar() {
  if (!jobsSelectBar) return;
  const resultsStats = document.getElementById("jobs-results-stats");
  const sortWrap = document.getElementById("jobs-sort-wrap");
  const resultsBar = document.querySelector(".jobs-results-bar");
  jobsSelectBar.classList.toggle("hidden", !selectionMode);
  resultsStats?.classList.toggle("hidden", selectionMode);
  sortWrap?.classList.toggle("hidden", selectionMode);
  resultsBar?.classList.toggle("selecting", selectionMode);
  if (jobsSelectCount) {
    jobsSelectCount.textContent = `${selectedJobIds.size} selected`;
  }
  if (deleteSelectedJobsBtn) {
    deleteSelectedJobsBtn.disabled = selectedJobIds.size === 0;
  }
  if (selectAllJobsBtn) {
    const allSelected =
      visibleJobIds.length > 0 && visibleJobIds.every((id) => selectedJobIds.has(id));
    selectAllJobsBtn.textContent = allSelected ? "Deselect All" : "Select All";
    selectAllJobsBtn.disabled = visibleJobIds.length === 0;
  }
}

function selectAllVisibleJobs() {
  const allSelected =
    visibleJobIds.length > 0 && visibleJobIds.every((id) => selectedJobIds.has(id));
  if (allSelected) {
    for (const id of visibleJobIds) selectedJobIds.delete(id);
  } else {
    for (const id of visibleJobIds) selectedJobIds.add(id);
  }
  updateSelectBar();
  loadJobs();
}

function enterSelectionMode(jobId) {
  selectionMode = true;
  selectedJobIds.clear();
  if (jobId != null) selectedJobIds.add(Number(jobId));
  updateSelectBar();
  loadJobs();
}

function exitSelectionMode() {
  selectionMode = false;
  selectedJobIds.clear();
  updateSelectBar();
  loadJobs();
}

function toggleJobSelection(jobId, checked) {
  const id = Number(jobId);
  if (checked) selectedJobIds.add(id);
  else selectedJobIds.delete(id);
  updateSelectBar();
  const card = document.querySelector(`.job-card[data-job-id="${id}"]`);
  if (card) {
    card.classList.toggle("checked", checked);
    const input = card.querySelector(".job-select-input");
    if (input) input.checked = checked;
  }
}

function openJobDetailDrawer() {
  const drawer = document.getElementById("job-detail-drawer");
  if (!drawer) return;
  drawer.classList.remove("hidden");
  drawer.setAttribute("aria-hidden", "false");
  // Next frame so translateX transition plays (HiringCafe right-slide).
  requestAnimationFrame(() => {
    requestAnimationFrame(() => drawer.classList.add("open"));
  });
}

function closeJobDetailDrawer() {
  const drawer = document.getElementById("job-detail-drawer");
  if (!drawer || drawer.classList.contains("hidden")) return;
  drawer.classList.remove("open");
  setTimeout(() => {
    if (drawer.classList.contains("open")) return;
    drawer.classList.add("hidden");
    drawer.setAttribute("aria-hidden", "true");
  }, 240);
}

function renderCompanyModalJobCard(job, focusedId) {
  const company = job.company || "Unknown company";
  const location = job.location || "Remote / Unknown";
  const salary = job.salary_text || "";
  const workType = job.work_type || "";
  const level = job.experience_level || "";
  const remoteEligible = job.remote_eligible || "";
  const reason = job.decision_reason || "";
  const applyUrl = job.apply_url || "";
  const jobUrl = job.job_url || "";
  const posted = formatPostedLabel(job);
  const headline = job.company_headline || "";
  const industry = job.industry || "";
  const focused = Number(job.id) === Number(focusedId) ? "focused" : "";

  const tags = [];
  if (salary && salary !== "Not listed") {
    tags.push(`<span class="job-tag salary">${escapeHtml(salary)}</span>`);
  }
  if (remoteEligible === "Yes" || /remote/i.test(workType || "")) {
    tags.push(`<span class="job-tag remote">Remote</span>`);
  } else if (workType) {
    tags.push(`<span class="job-tag">${escapeHtml(workType)}</span>`);
  }
  if (job.commitment) tags.push(`<span class="job-tag">${escapeHtml(job.commitment)}</span>`);
  if (level) tags.push(`<span class="job-tag">${escapeHtml(level)}</span>`);
  if (job.decision) {
    tags.push(
      `<span class="job-tag decision ${escapeHtml(job.decision)}">${escapeHtml(decisionLabel(job.decision))}</span>`
    );
  }

  const companySub =
    headline ||
    industry ||
    (job.source_portal ? PORTAL_LABELS[job.source_portal] || job.source_portal : "Collected role");

  return `
    <article class="company-job-card ${focused}" data-job-id="${job.id}">
      <div class="job-card-top">
        <h3 class="job-title">${escapeHtml(job.title || "Untitled")}</h3>
        ${posted ? `<span class="job-posted">${escapeHtml(posted)}</span>` : ""}
      </div>
      <div class="job-location">
        <span class="job-location-icon" aria-hidden="true"></span>
        <span>${escapeHtml(location)}</span>
      </div>
      ${tags.length ? `<div class="job-tags">${tags.join("")}</div>` : ""}
      <div class="job-company">
        <div class="job-company-avatar" aria-hidden="true">${escapeHtml(companyInitials(company))}</div>
        <div class="job-company-meta">
          <div class="job-company-name">${escapeHtml(company)}</div>
          <div class="job-company-sub">${escapeHtml(companySub)}</div>
        </div>
      </div>
      ${
        reason
          ? `<p class="job-snippet"><span class="job-snippet-icon" aria-hidden="true">!</span><span class="job-snippet-text">${escapeHtml(reason)}</span></p>`
          : ""
      }
      <div class="job-card-footer">
        ${
          jobUrl || applyUrl
            ? `<a class="job-posting-link" href="${escapeHtml(jobUrl || applyUrl)}" target="_blank" rel="noopener noreferrer">Job Posting</a>`
            : `<span class="muted">No posting link</span>`
        }
        <button type="button" class="job-view-btn company-job-evidence" data-job-id="${job.id}">View details</button>
      </div>
    </article>
  `;
}

function openCompanyJobsModal(stackKey, focusJobId) {
  const modal = document.getElementById("company-jobs-modal");
  const grid = document.getElementById("company-jobs-grid");
  const titleEl = document.getElementById("company-jobs-title");
  const countEl = document.getElementById("company-jobs-count");
  const footnoteEl = document.getElementById("company-jobs-footnote");
  const seeAll = document.getElementById("company-jobs-see-all");
  const avatar = document.getElementById("company-jobs-avatar");
  if (!modal || !grid) return;

  const stack = stackKey ? jobStacks.get(stackKey) : null;
  let jobs = stack?.jobs ? [...stack.jobs] : [];
  if (!jobs.length) {
    // Fallback: single job from DOM/API stack miss.
    const card = document.querySelector(`.job-card[data-job-id="${focusJobId}"]`);
    jobs = card
      ? [
          {
            id: focusJobId,
            title: card.querySelector(".job-title")?.textContent,
            company: card.querySelector(".job-company-name")?.textContent?.replace(/·\s*\d+$/, "").trim(),
          },
        ]
      : [];
  }
  if (!jobs.length) return;

  const company = stack?.company || jobs[0].company || "Company";
  const companyUrl = jobs.find((job) => job.company_url)?.company_url || "";
  titleEl.textContent = company;
  countEl.textContent = `${jobs.length} job${jobs.length === 1 ? "" : "s"}`;
  footnoteEl.textContent = `${jobs.length} job${jobs.length === 1 ? "" : "s"} · the company may have more openings`;
  avatar.textContent = companyInitials(company);
  seeAll.textContent = `See all jobs at ${company}`;
  if (companyUrl) {
    seeAll.href = companyUrl;
    seeAll.classList.remove("disabled");
  } else {
    seeAll.href = "#";
    seeAll.classList.add("disabled");
  }

  grid.innerHTML = jobs.map((job) => renderCompanyModalJobCard(job, focusJobId)).join("");
  grid.querySelectorAll(".company-job-card").forEach((cardEl) => {
    cardEl.addEventListener("click", async (event) => {
      if (event.target.closest("a, button")) return;
      const id = Number(cardEl.dataset.jobId);
      closeCompanyJobsModal();
      await openJobDetailScreen(id, stackKey);
    });
  });
  grid.querySelectorAll(".company-job-evidence").forEach((btn) => {
    btn.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      const id = Number(btn.dataset.jobId);
      closeCompanyJobsModal();
      await openJobDetailScreen(id, stackKey);
    });
  });

  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
  const focused = grid.querySelector(`.company-job-card[data-job-id="${focusJobId}"]`);
  focused?.scrollIntoView({ block: "nearest", inline: "nearest" });
}

function closeCompanyJobsModal() {
  const modal = document.getElementById("company-jobs-modal");
  if (!modal) return;
  modal.classList.add("hidden");
  modal.setAttribute("aria-hidden", "true");
}

async function deleteJobById(jobId) {
  const id = Number(jobId);
  if (!id) return;
  const ok = await showAppConfirm({
    title: "Delete this job?",
    message: "Hold completed — this position will be removed from the database.",
    confirmLabel: "Delete",
    cancelLabel: "Cancel",
    danger: true,
  });
  if (!ok) return;
  selectedJobIds.clear();
  selectedJobIds.add(id);
  const response = await fetch("/api/jobs/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_ids: [id] }),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    showCredentialToast(err.detail || "Failed to delete job", "error");
    return;
  }
  if (selectedJobId === id) {
    selectedJobId = null;
    jobDetail.innerHTML = "<div class='muted'>Select a job to inspect evidence and decisions.</div>";
    closeJobDetailDrawer();
  }
  closeCompanyJobsModal();
  showCredentialToast("Deleted 1 job.", "success");
  await loadJobs();
}

document.getElementById("job-detail-backdrop")?.addEventListener("click", closeJobDetailDrawer);
document.getElementById("close-company-jobs")?.addEventListener("click", closeCompanyJobsModal);
document.getElementById("company-jobs-modal")?.addEventListener("click", (event) => {
  if (event.target.id === "company-jobs-modal") closeCompanyJobsModal();
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  closeCompanyJobsModal();
  closeJobDetailDrawer();
  closeNavDrawer();
  closeJobsFiltersDrawer();
});

cancelJobsSelectBtn?.addEventListener("click", () => exitSelectionMode());
selectAllJobsBtn?.addEventListener("click", () => selectAllVisibleJobs());
deleteSelectedJobsBtn?.addEventListener("click", () => deleteSelectedJobs());

async function openJobDetailScreen(jobId, stackKey = null) {
  const response = await fetch(`/api/jobs/${jobId}`);
  if (!response.ok) {
    showCredentialToast("Failed to load job detail", "error");
    return;
  }
  const job = await response.json();
  selectedJobId = Number(job.id);
  const resolvedStackKey = stackKey || companyKey(job.company || "");
  const status = String(job.status || "new").toLowerCase();
  const decision = String(job.decision || "").toLowerCase();
  const isSaved = status === "saved" || status === "applied";
  const isApplied = status === "applied";
  const applyUrl = job.apply_url || "";
  const jobUrl = job.job_url || "";
  const companyUrl = job.company_url || "";
  const posted = formatPostedLabel(job);
  const applyHref = applyUrl || jobUrl;
  const HIDDEN_EVIDENCE_FIELDS = new Set([
    "remote_policy",
    "work_type",
    "salary",
    "match_background",
    "security_related_company_or_role",
    "role_excluded",
  ]);
  const evidenceItems = (job.evidence || []).filter(
    (item) => !HIDDEN_EVIDENCE_FIELDS.has(String(item.field || "").toLowerCase())
  );
  const evidenceHtml = evidenceItems
    .map(
      (item) => `
      <div class="evidence-item">
        <strong>${escapeHtml(item.field)}</strong>: ${escapeHtml(String(item.value))}
        <div class="job-meta">${escapeHtml(item.evidence_text || "")}</div>
      </div>`
    )
    .join("");

  const tags = [];
  if (job.salary_text && job.salary_text !== "Not listed") {
    tags.push(`<span class="job-tag salary">${escapeHtml(job.salary_text)}</span>`);
  }
  if (job.remote_eligible === "Yes" || /remote/i.test(job.work_type || "")) {
    tags.push(`<span class="job-tag remote">Remote</span>`);
  } else if (job.work_type) {
    tags.push(`<span class="job-tag">${escapeHtml(job.work_type)}</span>`);
  }
  if (job.commitment) tags.push(`<span class="job-tag">${escapeHtml(job.commitment)}</span>`);
  if (job.experience_level) tags.push(`<span class="job-tag">${escapeHtml(job.experience_level)}</span>`);
  if (job.decision) {
    tags.push(
      `<span class="job-tag decision ${escapeHtml(job.decision)}">${escapeHtml(decisionLabel(job.decision))}</span>`
    );
  }

  jobDetail.innerHTML = `
    <div class="jd-screen" data-job-id="${job.id}" data-stack-key="${escapeHtml(resolvedStackKey)}">
      <div class="jd-topbar">
        <div class="jd-top-left">
          <span class="jd-mode-pill active">Job</span>
          <span class="jd-mode-pill muted-pill">Detail</span>
        </div>
        <div class="jd-top-actions">
          <button type="button" id="close-job-detail" class="icon-close-btn" aria-label="Close">×</button>
        </div>
      </div>

      <div class="jd-tabs" role="tablist">
        <button type="button" class="jd-tab active" data-tab="info">Job Info</button>
        <button type="button" class="jd-tab" data-tab="company">Company Info</button>
        <button type="button" class="jd-tab" data-tab="description">Job Description</button>
      </div>

      <div class="jd-body">
        <p class="jd-posted">${posted ? escapeHtml(posted) : ""}</p>
        <h1 class="jd-title">${escapeHtml(job.title || "Untitled")}</h1>
        <p class="jd-company">@ ${escapeHtml(job.company || "Unknown company")}</p>
        <div class="jd-company-actions">
          <button type="button" class="jd-link-btn" id="jd-view-all">View All Jobs</button>
          ${
            companyUrl
              ? `<a class="jd-link-btn" href="${escapeHtml(companyUrl)}" target="_blank" rel="noopener noreferrer">Website</a>`
              : ""
          }
        </div>
        <div class="job-location jd-location">
          <span class="job-location-icon" aria-hidden="true"></span>
          <span>${escapeHtml(job.location || "Remote / Unknown")}</span>
        </div>
        ${tags.length ? `<div class="job-tags jd-tags">${tags.join("")}</div>` : ""}

        <div class="jd-panel active" data-panel="info">
          ${
            job.decision_reason
              ? `<section class="jd-section"><h3>Summary</h3><p>${escapeHtml(job.decision_reason)}</p></section>`
              : ""
          }
          <section class="jd-section">
            <h3>Evidence</h3>
            ${evidenceHtml || "<div class='muted'>No evidence stored.</div>"}
          </section>

          <section class="jd-actions" aria-label="Job actions">
            <div class="jd-ai-banner">
              <div class="jd-ai-icon" aria-hidden="true">✦</div>
              <div class="jd-ai-copy">
                <strong>Apply with AI</strong>
                <span>apply automatically with openAI API</span>
              </div>
              <button type="button" class="jd-ai-cta" id="jd-apply-ai">Apply with AI →</button>
            </div>

            ${
              applyHref
                ? `<a class="jd-apply-now" href="${escapeHtml(applyHref)}" target="_blank" rel="noopener noreferrer">Apply now <span aria-hidden="true">↗</span></a>`
                : `<button type="button" class="jd-apply-now" disabled>Apply now</button>`
            }

            <div class="jd-action-grid">
              <div class="jd-action-row">
                <button type="button" class="jd-action-btn save ${isSaved ? "active" : ""}" data-action="save">${isSaved ? "Saved" : "Save"}</button>
                <button type="button" class="jd-action-btn applied ${isApplied ? "active" : ""}" data-action="applied">${isApplied ? "Applied" : "Mark Applied"}</button>
                <button type="button" class="jd-action-btn hide" data-action="hide">Hide Job</button>
              </div>
              <div class="jd-action-row">
                <button type="button" class="jd-action-btn decision eligible ${decision === "eligible" ? "enclicked" : ""}" data-decision="eligible" ${decision === "eligible" ? "disabled" : ""}>Enable</button>
                <button type="button" class="jd-action-btn decision review ${decision === "needs_review" ? "enclicked" : ""}" data-decision="needs_review" ${decision === "needs_review" ? "disabled" : ""}>Need Review</button>
                <button type="button" class="jd-action-btn decision reject ${decision === "rejected" ? "enclicked" : ""}" data-decision="rejected" ${decision === "rejected" ? "disabled" : ""}>Reject</button>
              </div>
            </div>
          </section>
        </div>

        <div class="jd-panel" data-panel="company">
          <section class="jd-section">
            <h3>Company</h3>
            <p><strong>${escapeHtml(job.company || "Unknown")}</strong></p>
            ${job.industry ? `<p class="job-meta">${escapeHtml(job.industry)}</p>` : ""}
            ${job.company_headline ? `<p>${escapeHtml(job.company_headline)}</p>` : ""}
            ${
              companyUrl
                ? `<p><a href="${escapeHtml(companyUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(companyUrl)}</a></p>`
                : "<p class='muted'>No company website on file.</p>"
            }
          </section>
        </div>

        <div class="jd-panel" data-panel="description">
          <section class="jd-section">
            <h3>Job Description</h3>
            <div class="jd-description">${
              job.description_text
                ? escapeHtml(job.description_text).replace(/\n/g, "<br>")
                : "<span class='muted'>No description stored.</span>"
            }</div>
          </section>
          ${
            jobUrl || applyUrl
              ? `<p><a class="job-posting-link" href="${escapeHtml(jobUrl || applyUrl)}" target="_blank" rel="noopener noreferrer">Job Posting</a></p>`
              : ""
          }
        </div>
      </div>
    </div>
  `;

  document.getElementById("close-job-detail")?.addEventListener("click", closeJobDetailDrawer);
  document.getElementById("jd-view-all")?.addEventListener("click", () => {
    openCompanyJobsModal(resolvedStackKey, job.id);
  });
  document.getElementById("jd-apply-ai")?.addEventListener("click", () => {
    showCredentialToast("Apply with AI coming soon — OpenAI auto-apply.", "info");
  });

  jobDetail.querySelectorAll(".jd-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const name = tab.dataset.tab;
      jobDetail.querySelectorAll(".jd-tab").forEach((el) => el.classList.toggle("active", el === tab));
      jobDetail.querySelectorAll(".jd-panel").forEach((panel) => {
        panel.classList.toggle("active", panel.dataset.panel === name);
      });
    });
  });

  jobDetail.querySelectorAll(".jd-action-grid [data-action]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const action = btn.dataset.action;
      const current = String(job.status || "new").toLowerCase();
      try {
        if (action === "save") {
          if (current === "applied") return;
          const next = current === "saved" ? "new" : "saved";
          const updated = await patchJobFields(job.id, { status: next });
          job.status = updated.status || next;
          syncJobInStacks(job.id, { status: job.status });
        } else if (action === "applied") {
          const next = current === "applied" ? "saved" : "applied";
          const updated = await patchJobFields(job.id, { status: next });
          job.status = updated.status || next;
          syncJobInStacks(job.id, { status: job.status });
        } else if (action === "hide") {
          await patchJobFields(job.id, { status: "hidden" });
          closeJobDetailDrawer();
          await loadJobs();
          return;
        }
        await openJobDetailScreen(job.id, resolvedStackKey);
        await loadJobs();
      } catch (error) {
        alert(error.message || "Action failed");
      }
    });
  });

  jobDetail.querySelectorAll(".jd-action-grid [data-decision]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (btn.disabled || btn.classList.contains("enclicked")) return;
      const nextDecision = btn.dataset.decision;
      try {
        await updateDecision(job.id, nextDecision, resolvedStackKey);
      } catch (error) {
        alert(error.message || "Failed to update decision");
      }
    });
  });

  openJobDetailDrawer();
}

async function loadJobDetail(jobId) {
  await openJobDetailScreen(jobId);
}

async function deleteSelectedJobs() {
  const ids = Array.from(selectedJobIds);
  if (!ids.length) {
    showCredentialToast("Select at least one job to delete.", "error");
    return;
  }
  const count = ids.length;
  const ok = await showAppConfirm({
    title: count === 1 ? "Delete this job?" : `Delete ${count} jobs?`,
    message:
      count === 1
        ? "This position will be removed from the database."
        : `Delete ${count} selected jobs from the database?`,
    confirmLabel: "Delete",
    cancelLabel: "Cancel",
    danger: true,
  });
  if (!ok) return;

  const response = await fetch("/api/jobs/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_ids: ids }),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    showCredentialToast(err.detail || "Failed to delete jobs", "error");
    return;
  }
  const data = await response.json();
  if (ids.includes(selectedJobId)) {
    selectedJobId = null;
    jobDetail.innerHTML = "<div class='muted'>Select a job to inspect evidence and decisions.</div>";
    closeJobDetailDrawer();
  }
  exitSelectionMode();
  showCredentialToast(`Deleted ${data.jobs_deleted || ids.length} job(s).`, "success");
  await loadJobs();
}

async function updateDecision(jobId, decision, stackKey = null) {
  const updated = await patchJobFields(jobId, { decision });
  syncJobInStacks(jobId, { decision: updated.decision || decision });
  await openJobDetailScreen(jobId, stackKey);
  await loadJobs();
}

function renderPagination(total, page, pageSize) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  pagination.innerHTML = "";
  if (total <= 0) return;

  const makeNavBtn = (label, { disabled = false, active = false, onClick } = {}) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `page-nav-btn${active ? " active" : ""}${disabled ? " disabled" : ""}`;
    button.innerHTML = label;
    button.disabled = Boolean(disabled);
    button.setAttribute("aria-disabled", disabled ? "true" : "false");
    if (active) button.setAttribute("aria-current", "page");
    if (onClick && !disabled) {
      button.addEventListener("click", onClick);
    }
    pagination.appendChild(button);
    return button;
  };

  makeNavBtn('<span aria-hidden="true">‹</span>', {
    disabled: page <= 1,
    onClick: () => {
      currentPage = Math.max(1, page - 1);
      loadJobs();
    },
  });

  // Built In–style window: prev, nearby page numbers, next.
  const windowSize = 5;
  let start = Math.max(1, page - Math.floor(windowSize / 2));
  let end = Math.min(pages, start + windowSize - 1);
  start = Math.max(1, end - windowSize + 1);

  if (start > 1) {
    makeNavBtn("1", {
      onClick: () => {
        currentPage = 1;
        loadJobs();
      },
    });
    if (start > 2) {
      const dots = document.createElement("span");
      dots.className = "page-nav-ellipsis";
      dots.textContent = "…";
      pagination.appendChild(dots);
    }
  }

  for (let i = start; i <= end; i += 1) {
    makeNavBtn(String(i), {
      active: i === page,
      onClick: () => {
        currentPage = i;
        loadJobs();
      },
    });
  }

  if (end < pages) {
    if (end < pages - 1) {
      const dots = document.createElement("span");
      dots.className = "page-nav-ellipsis";
      dots.textContent = "…";
      pagination.appendChild(dots);
    }
    makeNavBtn(String(pages), {
      onClick: () => {
        currentPage = pages;
        loadJobs();
      },
    });
  }

  makeNavBtn('<span aria-hidden="true">›</span>', {
    disabled: page >= pages,
    onClick: () => {
      currentPage = Math.min(pages, page + 1);
      loadJobs();
    },
  });
}

async function loadCredentials() {
  let portals = [];
  let sessionMap = {};

  if (currentUser) {
    try {
      const response = await fetch("/api/credentials");
      if (response.status === 401) {
        currentUser = null;
        renderAuthSlot();
      } else if (response.ok) {
        const data = await response.json();
        portals = data.portals || [];
        // One-time migrate browser-local credentials into the account.
        await migrateLocalCredentialsToAccount(portals);
        // Reload after migration so UI shows account state.
        const refreshed = await fetch("/api/credentials");
        if (refreshed.ok) {
          const refreshedData = await refreshed.json();
          portals = refreshedData.portals || portals;
        }
      }
    } catch {
      // Fall through to local fallback.
    }
  }

  if (!portals.length) {
    const localPortals = listPortalCredentialStatus?.() || [];
    try {
      const response = await fetch("/api/credentials/sessions");
      if (response.ok) {
        const data = await response.json();
        sessionMap = Object.fromEntries(data.portals.map((item) => [item.portal, item.has_session]));
      }
    } catch {
      // Optional.
    }
    portals = localPortals.map((item) => ({
      ...item,
      has_session: sessionMap[item.portal] || false,
      login_url: getPortalCredential?.(item.portal)?.login_url || null,
      has_password: Boolean(getPortalCredential?.(item.portal)?.password),
      has_email_app_password: Boolean(getPortalCredential?.(item.portal)?.email_app_password),
    }));
  }

  credentialsData = {
    portals:
      portals.length > 0
        ? portals
        : SUPPORTED_PORTALS.map((portal) => ({
            portal,
            configured: false,
            username: null,
            login_url: null,
            has_password: false,
            has_email_app_password: false,
            has_session: false,
          })),
    supported_portals: SUPPORTED_PORTALS,
  };

  credentialsContainer.innerHTML = credentialsData.portals.map(renderCredentialCard).join("");
  bindCredentialForms();
}

async function migrateLocalCredentialsToAccount(accountPortals) {
  if (!currentUser || !getPortalCredential || !savePortalCredential) return;
  const configured = new Set(
    (accountPortals || []).filter((p) => p.configured).map((p) => p.portal)
  );
  let migrated = 0;
  for (const portal of SUPPORTED_PORTALS) {
    if (configured.has(portal)) continue;
    const local = getPortalCredential(portal);
    if (!local?.username) continue;
    try {
      const response = await fetch(`/api/credentials/${portal}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: local.username,
          password: local.password || null,
          login_url: local.login_url || null,
          email_app_password: local.email_app_password || null,
        }),
      });
      if (response.ok) migrated += 1;
    } catch {
      // Ignore migration failures; user can re-save manually.
    }
  }
  if (migrated > 0) {
    showCredentialToast(`Moved ${migrated} portal login(s) to your JobSeek account.`);
  }
}

async function saveCredentialsToAccount(portal, form) {
  const data = new FormData(form);
  const username = String(data.get("username") || "").trim();
  let password = String(data.get("password") || "");
  const loginUrl = String(data.get("login_url") || "").trim() || null;
  const emailAppPassword = String(data.get("email_app_password") || "").trim() || null;
  const existing = credentialsData.portals.find((p) => p.portal === portal);

  if (!username) {
    alert("Username is required.");
    return false;
  }
  if (!password) {
    if (portal === "builtin") {
      password = null;
    } else if (!existing?.configured) {
      alert("Password is required.");
      return false;
    } else {
      password = null; // keep existing on server
    }
  }

  const response = await fetch(`/api/credentials/${portal}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username,
      password,
      login_url: loginUrl,
      email_app_password: emailAppPassword || null,
    }),
  });
  if (response.status === 401) {
    openAuthModal({
      reason: "Sign in to save portal credentials on your JobSeek account.",
      nextAction: "settings",
    });
    return false;
  }
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to save credentials");
  }

  // Optional local cache for offline UI (no longer required for Find Jobs).
  try {
    if (password || portal === "builtin") {
      savePortalCredential?.(portal, {
        username,
        password: password || "magic-link-placeholder",
        loginUrl,
        emailAppPassword,
      });
    }
  } catch {
    // Ignore local cache errors.
  }

  showCredentialToast(`${PORTAL_LABELS[portal] || portal} credentials saved to your account.`);
  return true;
}

function saveCredentialsLocally(portal, form) {
  const data = new FormData(form);
  const username = String(data.get("username") || "").trim();
  let password = String(data.get("password") || "");
  const loginUrl = String(data.get("login_url") || "").trim() || null;
  const emailAppPassword = String(data.get("email_app_password") || "").trim() || null;

  if (!password) {
    const existing = getPortalCredential(portal);
    if (portal === "builtin") {
      password = existing?.password || "magic-link-placeholder";
    } else if (!existing) {
      alert("Password is required.");
      return false;
    } else {
      password = existing.password;
    }
  }

  let resolvedEmailAppPassword = emailAppPassword;
  if (!resolvedEmailAppPassword && portal === "builtin") {
    resolvedEmailAppPassword = getPortalCredential(portal)?.email_app_password || null;
  }

  savePortalCredential(portal, {
    username,
    password,
    loginUrl,
    emailAppPassword: resolvedEmailAppPassword,
  });
  showCredentialToast(`${PORTAL_LABELS[portal] || portal} credentials saved in browser.`);
  return true;
}

function renderCredentialCard(portalInfo) {
  const label = PORTAL_LABELS[portalInfo.portal] || portalInfo.portal;
  const storageLabel = currentUser ? "account" : "browser";
  const configured = portalInfo.configured
    ? `Saved on ${storageLabel} as ${escapeHtml(portalInfo.username || "")}`
    : `Not saved on ${storageLabel}`;
  const session = portalInfo.has_session ? " · Login session saved" : " · No login session";
  const hasPassword = Boolean(portalInfo.has_password || getPortalCredential?.(portalInfo.portal)?.password);
  const hasEmailApp = Boolean(
    portalInfo.has_email_app_password || getPortalCredential?.(portalInfo.portal)?.email_app_password
  );
  const loginUrl =
    portalInfo.login_url || getPortalCredential?.(portalInfo.portal)?.login_url || "";
  const username =
    portalInfo.username || getPortalCredential?.(portalInfo.portal)?.username || "";

  return `
    <div class="credential-card" data-portal="${portalInfo.portal}">
      <h3>${escapeHtml(label)} <span class="credential-status">${configured}${session}</span></h3>
      <form class="credential-form" data-portal="${portalInfo.portal}">
        <input
          type="email"
          name="username"
          placeholder="Email / username"
          autocomplete="username"
          value="${escapeHtml(username)}"
          required
        >
        <input
          type="password"
          name="password"
          placeholder="${
            portalInfo.portal === "builtin"
              ? "Not used for Built In (magic link)"
              : hasPassword
                ? "Password saved (enter to change)"
                : "Password"
          }"
          autocomplete="current-password"
          ${portalInfo.portal === "builtin" ? "" : hasPassword ? "" : "required"}
        >
        <input
          type="url"
          name="login_url"
          placeholder="Custom login URL (optional, leave empty for Built In)"
          value="${escapeHtml(loginUrl)}"
        >
        ${
          portalInfo.portal === "builtin"
            ? `
        <input
          type="password"
          name="email_app_password"
          placeholder="${hasEmailApp ? "Outlook App Password saved (enter to change)" : "Outlook App Password (for magic-link email)"}"
          autocomplete="off"
        >
        <p class="portal-hint builtin-hint">
          Built In sends a magic link to your email. Add a Microsoft App Password so automation can read Outlook and open the link.
          <a href="https://account.microsoft.com/security" target="_blank" rel="noopener">Create App Password</a>
        </p>`
            : ""
        }
        <div class="credential-actions">
          <button type="submit" class="primary-btn">${currentUser ? "Save to Account" : "Save to Browser"}</button>
          <button type="button" class="secondary-btn delete-cred" ${portalInfo.configured ? "" : "disabled"}>
            Delete Credentials
          </button>
          <button type="button" class="secondary-btn delete-session" ${portalInfo.has_session ? "" : "disabled"}>
            Clear Login Session
          </button>
        </div>
      </form>
    </div>
  `;
}

function bindCredentialForms() {
  document.querySelectorAll(".credential-form").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const portal = form.dataset.portal;
      try {
        let ok = false;
        if (currentUser) {
          ok = await saveCredentialsToAccount(portal, form);
        } else {
          ok = saveCredentialsLocally(portal, form);
          if (ok) {
            openAuthModal({
              reason: "Sign in to keep portal credentials on your JobSeek account across devices.",
              nextAction: "settings",
            });
          }
        }
        if (ok) {
          await loadCredentials();
        }
      } catch (error) {
        alert(error.message || "Failed to save credentials");
      }
    });
  });

  document.querySelectorAll(".delete-cred").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const portal = btn.closest(".credential-card").dataset.portal;
      const label = PORTAL_LABELS[portal] || portal;
      if (!confirm(`Delete saved credentials for ${label}?`)) {
        return;
      }
      try {
        deletePortalCredential?.(portal);
        if (currentUser) {
          const response = await fetch(`/api/credentials/${portal}`, { method: "DELETE" });
          if (!response.ok && response.status !== 404) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || "Failed to delete account credentials");
          }
        }
        showCredentialToast(`${label} credentials deleted.`);
        await loadCredentials();
      } catch (error) {
        alert(error.message || "Failed to delete credentials");
      }
    });
  });

  document.querySelectorAll(".delete-session").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const portal = btn.closest(".credential-card").dataset.portal;
      const label = PORTAL_LABELS[portal] || portal;
      if (!confirm(`Clear saved login session for ${label}? You will need to log in again next search.`)) {
        return;
      }
      try {
        const response = await fetch(`/api/credentials/sessions/${portal}`, { method: "DELETE" });
        if (response.status === 401) {
          openAuthModal({ reason: "Sign in to manage login sessions." });
          return;
        }
        if (!response.ok) {
          const err = await response.json().catch(() => ({}));
          throw new Error(err.detail || "Failed to clear login session");
        }
        showCredentialToast(`${label} login session cleared.`);
        await loadCredentials();
      } catch (error) {
        alert(error.message || "Failed to clear login session");
      }
    });
  });
}

function showCredentialToast(message, variant = "success") {
  let toast = document.getElementById("credential-toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "credential-toast";
    toast.className = "credential-toast";
    document.body.appendChild(toast);
  }
  toast.textContent = message;
  toast.classList.remove("toast-error", "toast-success", "visible");
  toast.classList.add(variant === "error" ? "toast-error" : "toast-success");
  // force reflow for animation restart
  void toast.offsetWidth;
  toast.classList.add("visible");
  clearTimeout(showCredentialToast._timer);
  showCredentialToast._timer = setTimeout(() => toast.classList.remove("visible"), 2800);
}

function showAppConfirm({
  title = "Confirm",
  message = "",
  confirmLabel = "Delete",
  cancelLabel = "Cancel",
  danger = true,
} = {}) {
  const modal = document.getElementById("app-confirm-modal");
  const titleEl = document.getElementById("app-confirm-title");
  const messageEl = document.getElementById("app-confirm-message");
  const okBtn = document.getElementById("app-confirm-ok");
  const cancelBtn = document.getElementById("app-confirm-cancel");
  const card = modal?.querySelector(".app-alert-card");
  if (!modal || !titleEl || !messageEl || !okBtn || !cancelBtn) {
    return Promise.resolve(window.confirm(message || title));
  }

  titleEl.textContent = title;
  messageEl.textContent = message;
  okBtn.textContent = confirmLabel;
  cancelBtn.textContent = cancelLabel;
  card?.classList.toggle("app-alert-danger", Boolean(danger));
  card?.classList.toggle("app-alert-info", !danger);
  okBtn.className = danger ? "danger-btn" : "primary-btn";

  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
  okBtn.focus();

  return new Promise((resolve) => {
    const close = (result) => {
      modal.classList.add("hidden");
      modal.setAttribute("aria-hidden", "true");
      okBtn.removeEventListener("click", onOk);
      cancelBtn.removeEventListener("click", onCancel);
      modal.removeEventListener("click", onBackdrop);
      document.removeEventListener("keydown", onKey);
      resolve(result);
    };
    const onOk = () => close(true);
    const onCancel = () => close(false);
    const onBackdrop = (event) => {
      if (event.target === modal) close(false);
    };
    const onKey = (event) => {
      if (event.key === "Escape") close(false);
      if (event.key === "Enter") close(true);
    };
    okBtn.addEventListener("click", onOk);
    cancelBtn.addEventListener("click", onCancel);
    modal.addEventListener("click", onBackdrop);
    document.addEventListener("keydown", onKey);
  });
}

function renderFindPortalsModal() {
  const hint = document.getElementById("find-jobs-hint");
  const configuredCount = credentialsData.portals.filter((p) => p.configured).length;

  if (hint) {
    if (configuredCount === 0) {
      hint.textContent = "No credentials saved yet. Open Settings, save login info, then return here.";
      hint.classList.remove("hidden");
      hint.classList.add("warning");
    } else {
      hint.textContent = `${configuredCount} portal(s) ready. Portals without credentials can still be selected but will fail at login.`;
      hint.classList.remove("hidden", "warning");
    }
  }

  findPortals.innerHTML = credentialsData.portals
    .map((item) => {
      const label = PORTAL_LABELS[item.portal] || item.portal;
      const statusClass = item.configured ? "portal-ready" : "portal-missing";
      const hintText = item.configured
        ? ` — ${escapeHtml(item.username || "saved")}`
        : " — add credentials in Settings";
      const checked = item.configured ? "checked" : "";
      return `
        <label class="${statusClass}">
          <input type="checkbox" name="portal" value="${item.portal}" ${checked}>
          ${escapeHtml(label)}<span class="portal-hint">${hintText}</span>
        </label>`;
    })
    .join("");
}

async function startFindJobs() {
  const selected = Array.from(findPortals.querySelectorAll("input:checked")).map((el) => el.value);
  if (!selected.length) {
    alert("Select at least one portal to search.");
    return;
  }

  const missing = selected.filter((portal) => {
    const info = credentialsData.portals.find((p) => p.portal === portal);
    return !info?.configured;
  });
  if (missing.length) {
    const names = missing.map((p) => PORTAL_LABELS[p] || p).join(", ");
    alert(`Save credentials in Settings for: ${names}`);
    return;
  }

  // When signed in, the server loads credentials from the account.
  // Keep body credentials only as a fallback for unsigned local-browser saves.
  const body = { portals: selected, headful: true, guest: false };
  if (!currentUser) {
    const credentials = getCredentialsForPortals?.(selected) || [];
    body.credentials = credentials;
  }

  const response = await fetch("/api/search/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    if (response.status === 401) {
      findJobsModal.classList.add("hidden");
      openAuthModal({
        reason: err.detail || "Sign in to run Find Jobs and watch the live bot browser.",
        nextAction: "find-jobs",
      });
      return;
    }
    alert(err.detail || "Failed to start search");
    return;
  }

  findJobsModal.classList.add("hidden");
  const started = await response.json().catch(() => ({}));
  if (started.kasm_enabled) {
    setRunStatus("Search running — starting Kasm browsers...", true);
  } else {
    setRunStatus("Search running — browser opening...", true);
  }
  setSearchControls(true);
  showView("jobs");
  // Show every decision while live search is collecting jobs.
  document.querySelectorAll("#decision-chips .chip").forEach((el) => el.classList.remove("active"));
  document.querySelector('#decision-chips .chip[data-decision="all"]')?.classList.add("active");
  activeDecision = "all";
  currentPage = 1;
  await loadJobs();
  // Keep Runs logs warm in background while searching.
  startLogPolling();
  pollSearchStatus();
}

function setSearchControls(running) {
  if (findJobsBtn) findJobsBtn.disabled = !!running;
  if (stopJobsBtn) {
    stopJobsBtn.hidden = !running;
    stopJobsBtn.disabled = false;
  }
}

async function pollSearchStatus() {
  if (searchPollTimer) clearInterval(searchPollTimer);
  searchPollTimer = setInterval(async () => {
    const response = await fetch("/api/search/status");
    const status = await response.json();
    if (status.running) {
      setSearchControls(true);
      const saved = status.saved || 0;
      const found = status.found || 0;
      const last = status.last_job_title ? ` · latest: ${status.last_job_title}` : "";
      const prefix = status.kasm_enabled ? "Kasm search" : "Searching";
      setRunStatus(`${prefix} — saved ${saved}/${found || saved}${last}`, true);
      renderKasmLinks(status.kasm_sessions);
      // Refresh job list as soon as the bot saves each job.
      await loadJobs();
      return;
    }
    clearInterval(searchPollTimer);
    setSearchControls(false);
    renderKasmLinks([]);
    // Keep log polling only while Runs tab is open.
    if (runsView?.classList.contains("hidden")) {
      stopLogPolling();
    }
    if (status.stopped) {
      setRunStatus(status.stop_message || "Stopped", false);
    } else if (status.error) {
      setRunStatus(`Search failed: ${status.error}`, false);
      alert(`Search failed: ${status.error}\n\nCheck data/search_run.log for details.`);
    } else {
      setRunStatus("Ready", false);
    }
    await loadRuns();
    await loadJobs();
    if (status.summary && !status.error && !status.stopped) {
      setRunStatus(`Done — found ${status.summary.found}, saved ${status.summary.saved}`, false);
      showView("jobs");
    }
  }, 2000);
}

function setRunStatus(text, running) {
  runStatus.innerHTML = `<span class="status-dot ${running ? "running" : "ready"}"></span>${escapeHtml(text)}`;
}

function renderKasmLinks(sessions) {
  if (!kasmLinks) return;
  if (!currentUser) {
    kasmLinks.hidden = true;
    kasmLinks.innerHTML = "";
    return;
  }
  const list = Array.isArray(sessions) ? sessions.filter((s) => s && s.view_url) : [];
  if (!list.length) {
    kasmLinks.hidden = true;
    kasmLinks.innerHTML = "";
    return;
  }
  kasmLinks.hidden = false;
  kasmLinks.innerHTML = list
    .map((s) => {
      const label = PORTAL_LABELS[s.portal] || s.portal || "Kasm";
      return `<a class="kasm-link" href="${escapeHtml(s.view_url)}" target="_blank" rel="noopener noreferrer">Watch ${escapeHtml(label)}</a>`;
    })
    .join("");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function init() {
  if (!window.JobSeekCredentials) {
    alert("Credential storage failed to load. Please hard-refresh the page (Ctrl+F5).");
    return;
  }
  await loadAuth();
  const params = new URLSearchParams(window.location.search);
  if (params.get("auth") === "1" && !currentUser) {
    const next = params.get("next") || null;
    openAuthModal({
      reason: "Sign in to watch the live JobSeek bot browser.",
      nextAction: next,
    });
  }
  await loadCredentials();
  await loadRuns();
  showView("jobs");
  await loadJobs();
  const statusResp = await fetch("/api/search/status");
  const status = await statusResp.json();
  if (status.running) {
    setSearchControls(true);
    setRunStatus(status.kasm_enabled ? "Kasm search running..." : "Search running...", true);
    renderKasmLinks(status.kasm_sessions);
    pollSearchStatus();
  } else {
    setSearchControls(false);
  }
}

init();
