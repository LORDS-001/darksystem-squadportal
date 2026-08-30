(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.OwnerAdminApi = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const SAFE_ERROR = "The request could not be completed.";
  async function request(path, options = {}, dependencies = {}) {
    const fetcher = dependencies.fetcher || fetch;
    const HeadersClass = typeof Headers === "function" ? Headers : class {
      constructor(values) { this.values = values || {}; }
      set(key, value) { this.values[key] = value; }
    };
    const headers = new HeadersClass(options.headers || {});
    headers.set("Accept", "application/json");
    let response;
    try { response = await fetcher(path, { ...options, credentials: "same-origin", headers }); }
    catch { throw new Error(SAFE_ERROR); }
    let payload;
    try { payload = await response.json(); }
    catch { throw new Error(SAFE_ERROR); }
    if (!response.ok) {
      if ((response.status === 401 || response.status === 403) && dependencies.onUnauthorized) dependencies.onUnauthorized();
      throw new Error(typeof payload.error === "string" ? payload.error : SAFE_ERROR);
    }
    return payload;
  }
  function json(method, body) {
    return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) };
  }
  function clearSecrets(container) {
    if (!container || !container.querySelectorAll) return;
    for (const control of container.querySelectorAll("input, textarea")) {
      if (control.matches('[data-secret="true"]')) control.value = "";
    }
  }
  function scrub(row) {
    const forbidden = /password|access.?code|reset.?code|secret|token|hash/i;
    return Object.fromEntries(Object.entries(row || {}).filter(([key]) => !forbidden.test(key)));
  }
  return { request, json, clearSecrets, scrub, SAFE_ERROR };
});
