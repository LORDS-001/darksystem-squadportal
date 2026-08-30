(function (root, factory) {
  const value = factory();
  if (typeof module === "object" && module.exports) module.exports = value;
  root.OwnerAdminSeasons = value;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const endpoints = { seasons: "/api/owner/seasons", points: "/api/owner/season-points", events: "/api/owner/events", history: "/api/owner/history" };
  function historyCorrectionPath(domain, id) { return `${endpoints.history}/${encodeURIComponent(domain)}/${encodeURIComponent(id)}`; }
  return { endpoints, historyCorrectionPath };
});
