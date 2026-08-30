"use strict";

const assert = require("node:assert/strict");
const api = require("../owner-admin-api.js");
const squad = require("../owner-admin-squad.js");
const tournaments = require("../owner-admin-tournaments.js");
const seasons = require("../owner-admin-seasons.js");
const audit = require("../owner-admin-audit.js");

async function test(name, run) {
  try { await run(); process.stdout.write(`ok - ${name}\n`); }
  catch (error) { process.stderr.write(`not ok - ${name}\n${error.stack}\n`); process.exitCode = 1; }
}

test("API reports unauthorized responses through the session callback", async () => {
  let expired = false;
  const fetcher = async () => ({ ok: false, status: 401, json: async () => ({ error: "Unauthorized" }) });
  await assert.rejects(
    api.request("/api/owner/overview", {}, { fetcher, onUnauthorized: () => { expired = true; } }),
    /Unauthorized/,
  );
  assert.equal(expired, true);
});

test("API preserves the active session for forbidden responses", async () => {
  let expired = false;
  const fetcher = async () => ({ ok: false, status: 403, json: async () => ({ error: "The current password is incorrect." }) });
  await assert.rejects(
    api.request("/api/owner/settings", {}, { fetcher, onUnauthorized: () => { expired = true; } }),
    /current password is incorrect/i,
  );
  assert.equal(expired, false);
});

test("API rejects non-JSON responses with a safe message", async () => {
  const fetcher = async () => ({ ok: false, status: 500, json: async () => { throw new Error("html"); } });
  await assert.rejects(api.request("/broken", {}, { fetcher }), /could not be completed/);
});

test("squad helpers filter and paginate without exposing secret fields", () => {
  const rows = [
    { id: "1", ign: "Alpha", role: "Squad Owner", accessCode: "never" },
    { id: "2", ign: "Beta", role: "Squad Member", passwordHash: "never" },
  ];
  assert.deepEqual(squad.visibleRows(rows, "beta", 1, 10), [{ id: "2", ign: "Beta", role: "Squad Member" }]);
});

test("tournament actions identify destructive transitions", () => {
  assert.equal(tournaments.needsConfirmation("cancel"), true);
  assert.equal(tournaments.needsConfirmation("archive"), true);
  assert.equal(tournaments.needsConfirmation("reinstate"), false);
});

test("tournament helpers cover decisions, matches, and results", () => {
  assert.equal(tournaments.registrationDecisionPath("T 1", "R/2"), "/api/owner/tournaments/T%201/registrations/R%2F2/decision");
  assert.equal(tournaments.matchPath("T 1", "M 2"), "/api/owner/tournaments/T%201/matches/M%202");
  assert.equal(tournaments.resultPath("T 1", "M 2"), "/api/owner/tournaments/T%201/matches/M%202/result");
});

test("season helpers expose all administration endpoints", () => {
  assert.equal(seasons.endpoints.seasons, "/api/owner/seasons");
  assert.equal(seasons.endpoints.events, "/api/owner/events");
  assert.equal(seasons.endpoints.history, "/api/owner/history");
});

test("history helper builds correction paths", () => {
  assert.equal(seasons.historyCorrectionPath("hall-of-fame", "H 1"), "/api/owner/history/hall-of-fame/H%201");
});

test("audit query safely encodes filters and pagination", () => {
  assert.equal(
    audit.query({ actor: "owner action", action: "member.update", target: "member", from: "2026-01-01", to: "2026-01-31", cursor: "next+page", limit: 25 }),
    "/api/owner/audit?action=member.update&actor=owner+action&target=member&from=2026-01-01&to=2026-01-31&cursor=next%2Bpage&limit=25",
  );
});

test("secret clearing empties only marked controls", () => {
  const secret = { value: "secret", matches: (selector) => selector === '[data-secret="true"]' };
  const normal = { value: "keep", matches: () => false };
  api.clearSecrets({ querySelectorAll: () => [secret, normal] });
  assert.equal(secret.value, "");
  assert.equal(normal.value, "keep");
});
