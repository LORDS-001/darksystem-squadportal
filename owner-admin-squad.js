(function (root, factory) {
  const value = factory(root.OwnerAdminApi || (typeof require === "function" ? require("./owner-admin-api.js") : null));
  if (typeof module === "object" && module.exports) module.exports = value;
  root.OwnerAdminSquad = value;
})(typeof globalThis !== "undefined" ? globalThis : this, function (api) {
  "use strict";
  const endpoints = { squads: "/api/owner/squad-members", community: "/api/owner/community-accounts", content: "/api/owner/squad-content" };
  function visibleRows(rows, search = "", page = 1, pageSize = 20) {
    const term = String(search).trim().toLowerCase();
    const safe = (Array.isArray(rows) ? rows : []).map(api.scrub).filter((row) => !term || JSON.stringify(row).toLowerCase().includes(term));
    return safe.slice((Math.max(1, page) - 1) * pageSize, Math.max(1, page) * pageSize);
  }
  function memberFields() { return ["name", "ign", "gameId", "serverId", "email", "role", "status"]; }
  function contentDomains() { return ["announcements", "reports", "complaints", "events", "notifications"]; }
  return { endpoints, visibleRows, memberFields, contentDomains };
});
