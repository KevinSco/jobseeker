"""Built In–style HTML fixture for Playwright e2e tests."""

BUILTIN_LIST_HTML = """
<!DOCTYPE html>
<html>
<head><title>Built In Jobs</title></head>
<body>
  <input id="locationDropdownInput-JobBoard" placeholder="Location" />
  <div id="location-options" class="hidden">
    <button type="button">USA</button>
  </div>
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
    <a href="/company/secco">SecCo</a>
    <a class="job-title-link" href="/job/security-role-1">Security Platform Engineer</a>
    <div>3 Hours Ago · Remote · United States · 120K Annually</div>
    <button id="job-dropdown-button" type="button" class="dropdown">Expand</button>
    <button type="button" aria-label="Save job" class="heart">Heart</button>
    <div class="mb-md fs-xs fw-bold industry" style="display:none">Cybersecurity</div>
  </div>

  <div class="job-card" data-card="2">
    <a href="/company/apkudo">Apkudo</a>
    <a class="job-title-link" href="/job/frontend-os-2">Frontend Engineer, Device OS</a>
    <div>3 Hours Ago · Remote · United States · 100K-130K Annually · Senior level</div>
    <button id="job-dropdown-button" type="button" class="dropdown">Expand</button>
    <button type="button" aria-label="Save job" class="heart">Heart</button>
    <div class="mb-md fs-xs fw-bold industry" style="display:none">Software</div>
  </div>

  <div class="job-card" data-card="3">
    <a href="/company/bannedco">BannedCo</a>
    <a class="job-title-link" href="/job/python-3">Python Engineer</a>
    <div>Yesterday · Remote · United States · 140K Annually</div>
    <button id="job-dropdown-button" type="button" class="dropdown">Expand</button>
    <button type="button" aria-label="Save job" class="heart">Heart</button>
    <div class="mb-md fs-xs fw-bold industry" style="display:none">Internet</div>
  </div>

  <script>
    document.getElementById('locationDropdownInput-JobBoard').addEventListener('click', () => {
      document.getElementById('location-options').classList.remove('hidden');
    });
    document.querySelector('#location-options button').addEventListener('click', () => {
      document.getElementById('locationDropdownInput-JobBoard').value = 'USA';
      document.getElementById('status').textContent = 'location=USA';
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
