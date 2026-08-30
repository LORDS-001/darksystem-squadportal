(function (root, factory) {
  const value = factory();
  if (typeof module === "object" && module.exports) module.exports = value;
  root.OwnerAdminAudit = value;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  function query(filters = {}) {
    const params = new URLSearchParams();
    for (const key of ["action", "actor", "target", "from", "to", "cursor", "limit"]) {
      if (filters[key] !== undefined && filters[key] !== "") params.set(key, String(filters[key]));
    }
    const suffix = params.toString();
    return `/api/owner/audit${suffix ? `?${suffix}` : ""}`;
  }
  return { query };
});
