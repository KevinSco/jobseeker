"""Built In–style HTML fixture for Playwright e2e tests."""

BUILTIN_LIST_HTML = """
<!DOCTYPE html>
<html>
<head><title>Built In Jobs</title></head>
<body>
  <input id="locationDropdownInput-JobBoard" placeholder="Location" />
  <ul class="dropdown-menu p-0 w-100 hidden" x-ref="locationDropdownMenu" aria-labelledby="locationDropdownInput-JobBoard">
    <div class="list-group">
      <label class="list-group-item list-group-item-action border-0 text-truncate">United States</label>
    </div>
  </ul>
  <button id="remotePreferenceDropdownButton" type="button">Remote Preference</button>
  <div id="remote-options" class="hidden">
    <button type="button">Fully Remote</button>
  </div>
  <button id="postedDateDropdownButton" type="button">Posted Date</button>
  <div id="date-options" class="hidden">
    <button type="button">Past 24 hours</button>
  </div>
  <input id="search" type="search" placeholder="Search jobs" />
  <div id="status">idle</div>

  <div class="job-card" data-card="1">
    <a id="company-title" href="/company/secco">SecCo</a>
    <a class="job-title-link" href="/job/security-role-1">Security Platform Engineer</a>
    <div>3 Hours Ago · Remote · United States · 120K Annually</div>
    <button id="job-dropdown-button" type="button" class="dropdown">Expand</button>
    <button type="button" aria-label="Save job" class="heart">Heart</button>
    <div class="mb-md fs-xs fw-bold industry" style="display:none">Cybersecurity</div>
    <div class="border rounded-2 mt-md p-sm">
      <span class="fs-xs fw-bold text-uppercase">Top Skills:</span>
      <span class="d-md-inline ps-md-sm">
        <span class="fs-xs text-gray-04 mx-sm">React</span>
        <span class="fs-xs text-gray-04 mx-sm">Storybook</span>
        <span class="fs-xs text-gray-04 mx-sm">Tailwind</span>
        <span class="fs-xs text-gray-04 mx-sm">Typescript</span>
      </span>
    </div>
  </div>

  <div class="job-card" data-card="2">
    <a id="company-title" href="/company/apkudo">Apkudo</a>
    <a class="job-title-link" href="/job/frontend-os-2">Frontend Engineer, Device OS</a>
    <div>3 Hours Ago · Remote · United States · 100K-130K Annually · Senior level</div>
    <button id="job-dropdown-button" type="button" class="dropdown">Expand</button>
    <button type="button" aria-label="Save job" class="heart">Heart</button>
    <div class="mb-md fs-xs fw-bold industry" style="display:none">Software</div>
    <div class="border rounded-2 mt-md p-sm">
      <span class="fs-xs fw-bold text-uppercase">Top Skills:</span>
      <span class="d-md-inline ps-md-sm">
        <span class="fs-xs text-gray-04 mx-sm">TypeScript</span>
        <span class="fs-xs text-gray-04 mx-sm">React</span>
        <span class="fs-xs text-gray-04 mx-sm">Python</span>
        <span class="fs-xs text-gray-04 mx-sm">Node.js</span>
      </span>
    </div>
  </div>

  <div class="job-card" data-card="3">
    <a id="company-title" href="/company/bannedco">BannedCo</a>
    <a class="job-title-link" href="/job/python-3">Python Engineer</a>
    <div>Yesterday · Remote · United States · 140K Annually</div>
    <button id="job-dropdown-button" type="button" class="dropdown">Expand</button>
    <button type="button" aria-label="Save job" class="heart">Heart</button>
    <div class="mb-md fs-xs fw-bold industry" style="display:none">Internet</div>
  </div>

  <script>
    document.getElementById('locationDropdownInput-JobBoard').addEventListener('click', () => {
      document.querySelector('ul[x-ref="locationDropdownMenu"]').classList.remove('hidden');
    });
    document.getElementById('locationDropdownInput-JobBoard').addEventListener('input', () => {
      document.querySelector('ul[x-ref="locationDropdownMenu"]').classList.remove('hidden');
    });
    document.querySelector('ul[x-ref="locationDropdownMenu"] label').addEventListener('click', () => {
      document.getElementById('locationDropdownInput-JobBoard').value = 'United States';
      document.getElementById('status').textContent = 'location=United States';
      document.querySelector('ul[x-ref="locationDropdownMenu"]').classList.add('hidden');
    });
    document.getElementById('remotePreferenceDropdownButton').addEventListener('click', () => {
      document.getElementById('remote-options').classList.remove('hidden');
    });
    document.querySelector('#remote-options button').addEventListener('click', () => {
      document.getElementById('status').textContent = 'remote=Fully Remote';
    });
    document.getElementById('postedDateDropdownButton').addEventListener('click', () => {
      document.getElementById('date-options').classList.remove('hidden');
    });
    document.querySelector('#date-options button').addEventListener('click', () => {
      document.getElementById('postedDateDropdownButton').textContent = 'Past 24 hours';
      document.getElementById('status').textContent = 'posted=Past 24 hours';
    });
    document.querySelectorAll('.dropdown').forEach((btn) => {
      btn.addEventListener('click', () => {
        btn.parentElement.querySelector('.industry').style.display = 'block';
      });
    });
    document.querySelectorAll('.heart').forEach((btn) => {
      btn.addEventListener('click', () => {
        btn.setAttribute('aria-label', 'Unsave job');
        btn.dataset.saved = '1';
      });
    });
  </script>
  <style>.hidden{display:none}</style>
</body>
</html>
"""
