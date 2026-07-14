/**
 * Frontend storage for portal login credentials (localStorage).
 */
(function (global) {
  const STORAGE_KEY = "jobseek_portal_credentials_v1";
  const SUPPORTED_PORTALS = ["hiringcafe", "builtin", "jobright", "glassdoor"];

  function encodeValue(value) {
    if (!value) return null;
    try {
      return btoa(unescape(encodeURIComponent(value)));
    } catch {
      return value;
    }
  }

  function decodeValue(value) {
    if (!value) return null;
    try {
      return decodeURIComponent(escape(atob(value)));
    } catch {
      return value;
    }
  }

  function readStore() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return {};
      return JSON.parse(raw);
    } catch {
      return {};
    }
  }

  function writeStore(data) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
    } catch (error) {
      throw new Error(`Browser storage unavailable: ${error.message}`);
    }
  }

  function savePortalCredential(portal, { username, password, loginUrl = null, emailAppPassword = null }) {
    if (!SUPPORTED_PORTALS.includes(portal)) {
      throw new Error(`Unsupported portal: ${portal}`);
    }
    if (!username?.trim()) {
      throw new Error("Username is required");
    }
    if (portal !== "builtin" && !password) {
      throw new Error("Password is required");
    }
    const store = readStore();
    const existing = store[portal] || {};
    store[portal] = {
      username: username.trim(),
      password: encodeValue(password || existing.password || "magic-link-placeholder"),
      login_url: loginUrl?.trim() || null,
      email_app_password: encodeValue(emailAppPassword || decodeValue(existing.email_app_password)),
      saved_at: new Date().toISOString(),
    };
    writeStore(store);
    return { portal, username: username.trim() };
  }

  function getPortalCredential(portal) {
    const item = readStore()[portal];
    if (!item) return null;
    return {
      portal,
      username: item.username,
      password: decodeValue(item.password),
      login_url: item.login_url || null,
      email_app_password: decodeValue(item.email_app_password),
      saved_at: item.saved_at,
    };
  }

  function deletePortalCredential(portal) {
    const store = readStore();
    if (store[portal]) {
      delete store[portal];
      writeStore(store);
    }
  }

  function listPortalCredentialStatus() {
    const store = readStore();
    return SUPPORTED_PORTALS.map((portal) => {
      const item = store[portal];
      return {
        portal,
        configured: Boolean(item?.username),
        username: item?.username || null,
        has_email_app_password: Boolean(item?.email_app_password),
        saved_at: item?.saved_at || null,
      };
    });
  }

  function getCredentialsForPortals(portals) {
    return portals
      .map((portal) => getPortalCredential(portal))
      .filter(Boolean)
      .map(({ portal, username, password, login_url, email_app_password }) => ({
        portal,
        username,
        password,
        login_url: login_url || null,
        email_app_password: email_app_password || null,
      }));
  }

  global.JobSeekCredentials = {
    SUPPORTED_PORTALS,
    savePortalCredential,
    getPortalCredential,
    deletePortalCredential,
    listPortalCredentialStatus,
    getCredentialsForPortals,
  };
})(window);
