(function (root, factory) {
  const value = factory();
  if (typeof module === "object" && module.exports) module.exports = value;
  root.OwnerAdminTournaments = value;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const endpoint = "/api/owner/tournaments";
  const transitions = ["cancel", "reinstate", "bracket", "complete", "archive"];
  function needsConfirmation(action) { return ["cancel", "archive", "complete"].includes(action); }
  function transitionPath(id, action) { return `${endpoint}/${encodeURIComponent(id)}/${action}`; }
  function registrationDecisionPath(id, registrationId) { return `${endpoint}/${encodeURIComponent(id)}/registrations/${encodeURIComponent(registrationId)}/decision`; }
  function approvalDecisionPath(id, approvalId) { return `${endpoint}/${encodeURIComponent(id)}/approvals/${encodeURIComponent(approvalId)}/decision`; }
  function matchPath(id, matchId) { return `${endpoint}/${encodeURIComponent(id)}/matches${matchId ? `/${encodeURIComponent(matchId)}` : ""}`; }
  function resultPath(id, matchId) { return `${matchPath(id, matchId)}/result`; }
  return { endpoint, transitions, needsConfirmation, transitionPath, registrationDecisionPath, approvalDecisionPath, matchPath, resultPath };
});
