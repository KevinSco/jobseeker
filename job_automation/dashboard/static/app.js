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
  });
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
    if (next === "find-jobs") {
      await openFindJobsModal();
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

  if (activeEntity === "companies") {
    jobsList.className = "jobs-companies";
    jobsList.innerHTML = renderJobsByCompany(data.jobs) || "<div class='muted jobs-empty'>No jobs found.</div>";
  } else {
    jobsList.className = "jobs-grid";
    jobsList.innerHTML = data.jobs.map(renderJobCard).join("") || "<div class='muted jobs-empty'>No jobs found.</div>";
  }

  renderPagination(data.total, data.page, data.page_size);
  bindJobCards();
  updateSelectBar();
}

function formatCount(value) {
  return Number(value || 0).toLocaleString();
}

function renderJobsByCompany(jobs) {
  const groups = new Map();
  for (const job of jobs) {
    const company = job.company || "Unknown company";
    if (!groups.has(company)) groups.set(company, []);
    groups.get(company).push(job);
  }
  return Array.from(groups.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(
      ([company, items]) => `
      <div class="company-group">
        <h3 class="company-group-title">${escapeHtml(company)} · ${items.length}</h3>
        <div class="jobs-grid">
          ${items.map(renderJobCard).join("")}
        </div>
      </div>`
    )
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
  if (diffSec < 60) return `${Math.max(diffSec, 1)}s`;
  const mins = Math.floor(diffSec / 60);
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 48) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 14) return `${days}d`;
  return new Date(normalized).toLocaleDateString();
}

function renderJobCard(job) {
  const checked = selectedJobIds.has(job.id);
  const selectedClass = selectedJobId === job.id && !selectionMode ? "selected" : "";
  const checkedClass = checked ? "checked" : "";
  const selectClass = selectionMode ? "select-mode" : "";
  const company = job.company || "Unknown company";
  const location = job.location || "Remote / Unknown";
  const salary = job.salary_text || "";
  const workType = job.work_type || "";
  const level = job.experience_level || "";
  const remote = job.remote_policy || "";
  const reason = job.decision_reason || "";
  const postingUrl = job.apply_url || job.job_url || "";
  const posted = job.posted_text || relativeTime(job.created_at);
  const headline = job.company_headline || "";
  const industry = job.industry || "";

  const tags = [];
  if (salary) tags.push(`<span class="job-tag salary">${escapeHtml(salary)}</span>`);
  if (workType) tags.push(`<span class="job-tag">${escapeHtml(workType)}</span>`);
  else if (remote) tags.push(`<span class="job-tag">${escapeHtml(remote)}</span>`);
  if (level) tags.push(`<span class="job-tag">${escapeHtml(level)}</span>`);
  if (job.decision) {
    tags.push(
      `<span class="job-tag decision ${escapeHtml(job.decision)}">${escapeHtml(decisionLabel(job.decision))}</span>`
    );
  }
  if (job.source_portal) {
    tags.push(`<span class="job-tag portal">${escapeHtml(PORTAL_LABELS[job.source_portal] || job.source_portal)}</span>`);
  }

  const companySub = headline || industry || (job.source_portal ? PORTAL_LABELS[job.source_portal] || job.source_portal : "Collected role");

  return `
    <article class="job-card ${selectedClass} ${checkedClass} ${selectClass}" data-job-id="${job.id}">
      ${
        selectionMode
          ? `<label class="job-select" onclick="event.stopPropagation()">
              <input type="checkbox" class="job-select-input" data-job-id="${job.id}" ${checked ? "checked" : ""}>
            </label>`
          : ""
      }
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
          ? `<p class="job-snippet"><span class="job-snippet-icon" aria-hidden="true"></span>${escapeHtml(reason)}</p>`
          : ""
      }
      <div class="job-card-footer">
        ${
          postingUrl
            ? `<a class="job-posting-link" href="${escapeHtml(postingUrl)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">Job Posting</a>`
            : `<span class="muted">No posting link</span>`
        }
        <button type="button" class="job-view-btn" data-job-id="${job.id}">View details</button>
      </div>
      <div class="job-card-actions" aria-hidden="true">
        <button type="button" class="job-action primary job-view-btn" data-job-id="${job.id}">View details</button>
        ${
          postingUrl
            ? `<a class="job-action" href="${escapeHtml(postingUrl)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">Apply Directly</a>`
            : ""
        }
      </div>
    </article>
  `;
}

function updateSelectBar() {
  if (!jobsSelectBar) return;
  jobsSelectBar.classList.toggle("hidden", !selectionMode);
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

function bindJobCards() {
  document.querySelectorAll(".job-card").forEach((card) => {
    const jobId = Number(card.dataset.jobId);
    let pressTimer = null;
    let longPressTriggered = false;

    const clearPress = () => {
      if (pressTimer) {
        clearTimeout(pressTimer);
        pressTimer = null;
      }
    };

    const startPress = (event) => {
      if (event.type === "mousedown" && event.button !== 0) return;
      longPressTriggered = false;
      clearPress();
      pressTimer = setTimeout(() => {
        longPressTriggered = true;
        enterSelectionMode(jobId);
      }, LONG_PRESS_MS);
    };

    card.addEventListener("mousedown", startPress);
    card.addEventListener("touchstart", startPress, { passive: true });
    card.addEventListener("mouseup", clearPress);
    card.addEventListener("mouseleave", clearPress);
    card.addEventListener("touchend", clearPress);
    card.addEventListener("touchcancel", clearPress);

    card.addEventListener("click", async (event) => {
      if (event.target.closest("a, .job-select, .job-action")) return;
      if (longPressTriggered) {
        longPressTriggered = false;
        return;
      }
      if (selectionMode) {
        const currentlyChecked = selectedJobIds.has(jobId);
        toggleJobSelection(jobId, !currentlyChecked);
        return;
      }
      selectedJobId = jobId;
      await loadJobDetail(selectedJobId);
      document.querySelectorAll(".job-card.selected").forEach((el) => el.classList.remove("selected"));
      card.classList.add("selected");
    });

    card.querySelector(".job-select-input")?.addEventListener("change", (event) => {
      toggleJobSelection(jobId, event.target.checked);
    });
  });

  document.querySelectorAll(".job-view-btn").forEach((btn) => {
    btn.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (selectionMode) return;
      const jobId = Number(btn.dataset.jobId);
      selectedJobId = jobId;
      await loadJobDetail(jobId);
      document.querySelectorAll(".job-card.selected").forEach((el) => el.classList.remove("selected"));
      document.querySelector(`.job-card[data-job-id="${jobId}"]`)?.classList.add("selected");
    });
  });
}

function openJobDetailDrawer() {
  const drawer = document.getElementById("job-detail-drawer");
  if (!drawer) return;
  drawer.classList.remove("hidden");
  drawer.setAttribute("aria-hidden", "false");
}

function closeJobDetailDrawer() {
  const drawer = document.getElementById("job-detail-drawer");
  if (!drawer) return;
  drawer.classList.add("hidden");
  drawer.setAttribute("aria-hidden", "true");
}

document.getElementById("close-job-detail")?.addEventListener("click", closeJobDetailDrawer);
document.getElementById("job-detail-backdrop")?.addEventListener("click", closeJobDetailDrawer);

cancelJobsSelectBtn?.addEventListener("click", () => exitSelectionMode());
selectAllJobsBtn?.addEventListener("click", () => selectAllVisibleJobs());
deleteSelectedJobsBtn?.addEventListener("click", () => deleteSelectedJobs());

async function loadJobDetail(jobId) {
  const response = await fetch(`/api/jobs/${jobId}`);
  const job = await response.json();
  const evidence = (job.evidence || [])
    .map(
      (item) => `
      <div class="evidence-item">
        <strong>${escapeHtml(item.field)}</strong>: ${escapeHtml(String(item.value))}
        <div class="job-meta">${escapeHtml(item.evidence_text || "")}</div>
      </div>`
    )
    .join("");

  const metaBits = [
    job.location,
    job.work_type,
    job.experience_level,
    job.salary_text,
    job.posted_text,
  ].filter(Boolean);

  jobDetail.innerHTML = `
    <div class="job-title">${escapeHtml(job.title || "Untitled")}</div>
    <div class="job-meta">
      ${
        job.company_url
          ? `<a href="${escapeHtml(job.company_url)}" target="_blank" rel="noopener">${escapeHtml(job.company || "Company")}</a>`
          : escapeHtml(job.company || "")
      }
      ${metaBits.length ? ` · ${escapeHtml(metaBits.join(" · "))}` : ""}
    </div>
    ${job.industry ? `<div class="job-meta">${escapeHtml(job.industry)}</div>` : ""}
    ${job.company_headline ? `<p class="job-headline">${escapeHtml(job.company_headline)}</p>` : ""}
    <div style="margin:8px 0"><span class="badge ${job.decision || ""}">${escapeHtml(decisionLabel(job.decision))}</span></div>
    <p>${escapeHtml(job.decision_reason || "")}</p>
    <div class="detail-actions">
      ${job.apply_url ? `<a href="${job.apply_url}" target="_blank" rel="noopener">Open Apply URL</a>` : ""}
      ${job.job_url ? `<a href="${job.job_url}" target="_blank" rel="noopener">Open Source URL</a>` : ""}
      ${job.company_url ? `<a href="${job.company_url}" target="_blank" rel="noopener">Open Company</a>` : ""}
      <button type="button" id="mark-review">Need Review</button>
      <button type="button" id="mark-eligible">Enable</button>
      <button type="button" id="mark-rejected">Reject</button>
      <button type="button" id="delete-job" class="danger-btn">Delete</button>
    </div>
    <h3>Evidence</h3>
    ${evidence || "<div class='muted'>No evidence stored.</div>"}
  `;

  document.getElementById("mark-review")?.addEventListener("click", () => updateDecision(job.id, "needs_review"));
  document.getElementById("mark-eligible")?.addEventListener("click", () => updateDecision(job.id, "eligible"));
  document.getElementById("mark-rejected")?.addEventListener("click", () => updateDecision(job.id, "rejected"));
  document.getElementById("delete-job")?.addEventListener("click", () => {
    selectedJobIds.clear();
    selectedJobIds.add(job.id);
    deleteSelectedJobs();
  });
  openJobDetailDrawer();
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

async function updateDecision(jobId, decision) {
  await fetch(`/api/jobs/${jobId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision }),
  });
  await loadJobDetail(jobId);
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
  const localPortals = listPortalCredentialStatus();
  let sessionMap = {};

  try {
    const response = await fetch("/api/credentials/sessions");
    if (response.ok) {
      const data = await response.json();
      sessionMap = Object.fromEntries(data.portals.map((item) => [item.portal, item.has_session]));
    }
  } catch {
    // Optional: only available after dashboard restart on latest version.
  }

  credentialsData = {
    portals: localPortals.map((item) => ({
      ...item,
      has_session: sessionMap[item.portal] || false,
    })),
    supported_portals: SUPPORTED_PORTALS,
  };

  if (credentialsData.portals.length === 0) {
    credentialsData.portals = SUPPORTED_PORTALS.map((portal) => ({
      portal,
      configured: false,
      username: null,
      has_session: sessionMap[portal] || false,
    }));
  }

  credentialsContainer.innerHTML = credentialsData.portals.map(renderCredentialCard).join("");
  bindCredentialForms();
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
  const saved = getPortalCredential(portalInfo.portal);
  const configured = portalInfo.configured
    ? `Saved in browser as ${escapeHtml(portalInfo.username || "")}`
    : "Not saved in browser";
  const session = portalInfo.has_session ? " · Login session saved" : " · No login session";

  return `
    <div class="credential-card" data-portal="${portalInfo.portal}">
      <h3>${escapeHtml(label)} <span class="credential-status">${configured}${session}</span></h3>
      <form class="credential-form" data-portal="${portalInfo.portal}">
        <input
          type="email"
          name="username"
          placeholder="Email / username"
          autocomplete="username"
          value="${escapeHtml(saved?.username || "")}"
          required
        >
        <input
          type="password"
          name="password"
          placeholder="${portalInfo.portal === "builtin" ? "Not used for Built In (magic link)" : saved ? "Password saved (enter to change)" : "Password"}"
          autocomplete="current-password"
          ${portalInfo.portal === "builtin" ? "" : saved ? "" : "required"}
        >
        <input
          type="url"
          name="login_url"
          placeholder="Custom login URL (optional, leave empty for Built In)"
          value="${escapeHtml(saved?.login_url || "")}"
        >
        ${
          portalInfo.portal === "builtin"
            ? `
        <input
          type="password"
          name="email_app_password"
          placeholder="${saved?.email_app_password ? "Outlook App Password saved (enter to change)" : "Outlook App Password (for magic-link email)"}"
          autocomplete="off"
        >
        <p class="portal-hint builtin-hint">
          Built In sends a magic link to your email. Add a Microsoft App Password so automation can read Outlook and open the link.
          <a href="https://account.microsoft.com/security" target="_blank" rel="noopener">Create App Password</a>
        </p>`
            : ""
        }
        <div class="credential-actions">
          <button type="submit" class="primary-btn">Save to Browser</button>
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
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const portal = form.dataset.portal;
      try {
        if (saveCredentialsLocally(portal, form)) {
          loadCredentials();
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
        deletePortalCredential(portal);
        const response = await fetch(`/api/credentials/${portal}`, { method: "DELETE" });
        if (!response.ok && response.status !== 404) {
          const err = await response.json().catch(() => ({}));
          throw new Error(err.detail || "Failed to delete server credentials");
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

  const credentials = getCredentialsForPortals(selected);
  const missing = selected.filter((portal) => !credentials.find((c) => c.portal === portal));
  if (missing.length) {
    const names = missing.map((p) => PORTAL_LABELS[p] || p).join(", ");
    alert(`Save credentials in Settings for: ${names}`);
    return;
  }

  const response = await fetch("/api/search/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ portals: selected, headful: true, guest: false, credentials }),
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
