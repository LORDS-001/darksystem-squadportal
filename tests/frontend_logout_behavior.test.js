"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "..");

class ClassList {
  constructor() {
    this.values = new Set();
  }

  add(...names) {
    names.forEach((name) => this.values.add(name));
  }

  remove(...names) {
    names.forEach((name) => this.values.delete(name));
  }

  contains(name) {
    return this.values.has(name);
  }

  toggle(name, force) {
    const enabled = force === undefined ? !this.contains(name) : Boolean(force);
    if (enabled) this.add(name);
    else this.remove(name);
    return enabled;
  }

  setFromString(value) {
    this.values = new Set(String(value || "").split(/\s+/).filter(Boolean));
  }
}

class Element {
  constructor(tagName = "div", ownerDocument = null) {
    this.tagName = String(tagName).toUpperCase();
    this.ownerDocument = ownerDocument;
    this.children = [];
    this.parentNode = null;
    this.attributes = new Map();
    this.classList = new ClassList();
    this.style = {};
    this.hidden = false;
    this.disabled = false;
    this.textContent = "";
    this._innerHTML = "";
    this.listeners = new Map();
  }

  set id(value) {
    this.setAttribute("id", value);
  }

  get id() {
    return this.getAttribute("id") || "";
  }

  set className(value) {
    this.classList.setFromString(value);
  }

  get className() {
    return [...this.classList.values].join(" ");
  }

  set innerHTML(value) {
    this._innerHTML = String(value);
    this.children = [];
  }

  get innerHTML() {
    return this._innerHTML;
  }

  append(...children) {
    for (const child of children) {
      const node = typeof child === "string" ? this.ownerDocument.createTextNode(child) : child;
      node.parentNode = this;
      this.children.push(node);
    }
  }

  appendChild(child) {
    this.append(child);
    return child;
  }

  replaceChildren(...children) {
    this.children = [];
    this.append(...children);
  }

  insertBefore(child) {
    this.append(child);
    return child;
  }

  insertAdjacentHTML(_position, html) {
    this._innerHTML = String(html) + this._innerHTML;
  }

  setAttribute(name, value) {
    const normalized = String(name);
    this.attributes.set(normalized, String(value));
    if (normalized === "class") this.classList.setFromString(value);
    if (normalized === "id" && this.ownerDocument) this.ownerDocument.elementsById.set(String(value), this);
  }

  getAttribute(name) {
    return this.attributes.get(String(name)) ?? null;
  }

  addEventListener(type, listener) {
    this.listeners.set(type, listener);
  }

  focus() {}

  reportValidity() {
    return true;
  }

  reset() {
    for (const node of descendants(this.children)) if ("value" in node) node.value = "";
  }

  matches(selector) {
    if (selector === '[data-secret="true"]') return this.getAttribute("data-secret") === "true";
    return matches(this, selector);
  }

  remove() {
    if (!this.parentNode) return;
    this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
    this.parentNode = null;
  }

  closest() {
    return null;
  }

  querySelector(selector) {
    return querySelectorFrom(this.children, selector);
  }

  querySelectorAll(selector) {
    return querySelectorAllFrom(this.children, selector);
  }
}

class TestDocument {
  constructor() {
    this.elementsById = new Map();
    this.roots = [];
    this.listeners = new Map();
  }

  createElement(tagName) {
    return new Element(tagName, this);
  }

  createTextNode(text) {
    const node = new Element("#text", this);
    node.textContent = String(text);
    return node;
  }

  getElementById(id) {
    if (!this.elementsById.has(id)) {
      const element = this.createElement("div");
      element.id = id;
      this.roots.push(element);
    }
    return this.elementsById.get(id);
  }

  querySelector(selector) {
    if (selector === "footer") return this.getElementById("test-footer");
    return querySelectorFrom(this.roots, selector);
  }

  querySelectorAll(selector) {
    return querySelectorAllFrom(this.roots, selector);
  }

  addEventListener(type, listener) {
    this.listeners.set(type, listener);
  }
}

function descendants(nodes) {
  const result = [];
  for (const node of nodes) {
    result.push(node);
    result.push(...descendants(node.children || []));
  }
  return result;
}

function matches(element, selector) {
  if (selector.startsWith("#")) return element.id === selector.slice(1);
  if (selector.startsWith(".")) return selector.slice(1).split(".").every((name) => element.classList.contains(name));
  if (selector.startsWith("[role=")) return element.getAttribute("role") === selector.slice(6, -1).replace(/["']/g, "");
  return element.tagName.toLowerCase() === selector.toLowerCase();
}

function querySelectorAllFrom(nodes, selector) {
  if (selector.includes(",")) return selector.split(",").flatMap((part) => querySelectorAllFrom(nodes, part.trim()));
  const parts = selector.trim().split(/\s+/);
  let candidates = descendants(nodes).filter((element) => matches(element, parts[0]));
  for (const part of parts.slice(1)) {
    candidates = candidates.flatMap((candidate) => descendants(candidate.children).filter((element) => matches(element, part)));
  }
  return candidates;
}

function querySelectorFrom(nodes, selector) {
  return querySelectorAllFrom(nodes, selector)[0] || null;
}

function jsonResponse(ok, payload) {
  return { ok, json: async () => payload };
}

function deferred() {
  let resolve;
  const promise = new Promise((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

async function submitAsBrowser(form) {
  if (!form.noValidate && !form.reportValidity()) return false;
  await form.listeners.get("submit")({ preventDefault() {} });
  return true;
}

function formByHeading(root, heading) {
  const title = descendants([root]).find((node) => node.textContent === heading);
  return title && title.parentNode && title.parentNode.querySelector("form");
}

function fillForm(form, values) {
  for (const control of descendants(form.children)) if (control.name && Object.hasOwn(values, control.name)) control.value = String(values[control.name]);
}

function makeContext(scriptName, initialFetch) {
  const document = new TestDocument();
  let fetchImplementation = initialFetch;
  const localStorage = new Map();
  const sandbox = {
    console: { warn() {}, error() {}, log() {} },
    confirm: () => false,
    document,
    fetch: (...args) => fetchImplementation(...args),
    Headers,
    localStorage: {
      getItem: (key) => localStorage.get(key) ?? null,
      setItem: (key, value) => localStorage.set(key, String(value)),
    },
    location: { protocol: "https:" },
    navigator: { clipboard: null },
    Notification: function Notification() {},
    setInterval: () => 1,
    clearInterval() {},
    setTimeout,
    structuredClone,
  };
  sandbox.Notification.requestPermission = async () => "denied";
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.window.location = sandbox.location;
  sandbox.window.scrollTo = () => {};
  const context = vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(ROOT, scriptName), "utf8"), context, { filename: scriptName });
  return {
    context,
    document,
    setFetch(implementation) {
      fetchImplementation = implementation;
    },
  };
}

function ownerHarness() {
  const document = new TestDocument();
  const ownerRoot = document.getElementById("ownerRoot");
  let fetchImplementation = async () => jsonResponse(true, { setupComplete: false });
  const sandbox = {
    console,
    confirm: () => true,
    document,
    fetch: (...args) => fetchImplementation(...args),
    Headers,
    URLSearchParams,
    FormData: class FormData {
      constructor(form) { this.values = descendants([form]).filter((node) => node.name).map((node) => [node.name, node.value || ""]); }
      entries() { return this.values[Symbol.iterator](); }
    },
    setTimeout,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  const context = vm.createContext(sandbox);
  for (const moduleName of ["owner-admin-api.js", "owner-admin-squad.js", "owner-admin-tournaments.js", "owner-admin-seasons.js", "owner-admin-audit.js"]) {
    vm.runInContext(fs.readFileSync(path.join(ROOT, moduleName), "utf8"), context, { filename: moduleName });
  }
  vm.runInContext(fs.readFileSync(path.join(ROOT, "owner-admin.js"), "utf8"), context, { filename: "owner-admin.js" });
  return {
    context,
    document,
    ownerRoot,
    setFetch(implementation) {
      fetchImplementation = implementation;
    },
  };
}

test("Owner logout failure preserves the dashboard, session, and retry control", async () => {
  const harness = ownerHarness();
  await new Promise((resolve) => setImmediate(resolve));
  vm.runInContext(`
    activeOwnerSession = { id: "owner-1", role: "Overall Owner" };
    renderOwnerDashboard({ health: { backend: "healthy", database: "healthy" }, counts: {}, pending: {}, recentAudit: [] });
  `, harness.context);
  const dashboard = harness.ownerRoot.children[0];
  harness.setFetch(async () => jsonResponse(false, { error: "Logout is temporarily unavailable." }));

  await vm.runInContext("ownerLogout()", harness.context);

  assert.ok(harness.ownerRoot.children[0] === dashboard, "the protected dashboard must remain mounted");
  assert.equal(vm.runInContext("activeOwnerSession.role", harness.context), "Overall Owner");
  const retry = dashboard.querySelector(".owner-admin__button--secondary");
  assert.equal(retry.disabled, false);
  assert.equal(retry.textContent, "Logout");
  const alert = dashboard.querySelector('[role="alert"]');
  assert.equal(alert.hidden, false);
  assert.equal(alert.textContent, "Logout is temporarily unavailable.");
});

test("Owner logout success clears the session and renders the unchanged login notice", async () => {
  const harness = ownerHarness();
  await new Promise((resolve) => setImmediate(resolve));
  vm.runInContext(`
    activeOwnerSession = { id: "owner-1", role: "Overall Owner" };
    renderOwnerDashboard({ health: { backend: "healthy", database: "healthy" }, counts: {}, pending: {}, recentAudit: [] });
  `, harness.context);
  harness.setFetch(async () => jsonResponse(true, { ok: true }));

  await vm.runInContext("ownerLogout()", harness.context);

  assert.equal(vm.runInContext("activeOwnerSession", harness.context), null);
  assert.ok(harness.ownerRoot.querySelector(".owner-admin__auth-shell"));
  const status = harness.ownerRoot.querySelector('[role="status"]');
  assert.equal(status.textContent, "You have been logged out.");
});

test("Owner invalid login submission clears the password without making a request", async () => {
  const harness = ownerHarness();
  await new Promise((resolve) => setImmediate(resolve));
  vm.runInContext("renderOwnerLogin()", harness.context);
  const form = harness.ownerRoot.querySelector("form");
  const username = harness.document.getElementById("owner-login-username");
  const password = harness.document.getElementById("owner-login-password");
  username.value = "";
  password.value = "typed-owner-password";
  form.reportValidity = () => false;
  let fetchCount = 0;
  harness.setFetch(async () => {
    fetchCount += 1;
    return jsonResponse(true, {});
  });

  await submitAsBrowser(form);

  assert.equal(password.value, "");
  assert.equal(fetchCount, 0);
});

test("Owner overview renders separate backend and database health values safely", async () => {
  const harness = ownerHarness();
  await new Promise((resolve) => setImmediate(resolve));

  vm.runInContext(`renderOwnerDashboard({
    health: { backend: "healthy <script>", database: "healthy" },
    counts: {}, pending: {}, recentAudit: []
  })`, harness.context);

  const indicators = harness.ownerRoot.querySelectorAll(".owner-admin__health-indicator");
  assert.equal(indicators.length, 2);
  assert.equal(indicators[0].textContent, "Backend: ");
  assert.equal(indicators[0].children[0].textContent, "healthy <script>");
  assert.equal(indicators[0].innerHTML, "");
  assert.equal(indicators[1].textContent, "Database: ");
  assert.equal(indicators[1].children[0].textContent, "healthy");
});

async function publicHarness() {
  const harness = makeContext("script.js", async () => jsonResponse(true, {}));
  await new Promise((resolve) => setImmediate(resolve));
  return harness;
}

test("Community logout failure preserves authenticated state and visible Community UI", async () => {
  const harness = await publicHarness();
  harness.document.getElementById("communityApp").classList.remove("hidden");
  harness.document.getElementById("public").classList.add("hidden");
  harness.document.querySelector("footer").classList.add("hidden");
  vm.runInContext('communityCurrent = { id: "community-1", ign: "Tester", email: "tester@example.test" }; current = null;', harness.context);
  harness.setFetch(async () => jsonResponse(false, { error: "Logout is temporarily unavailable." }));

  await vm.runInContext("communityLogout()", harness.context);

  assert.equal(vm.runInContext("communityCurrent.id", harness.context), "community-1");
  assert.equal(harness.document.getElementById("communityApp").classList.contains("hidden"), false);
  assert.equal(harness.document.getElementById("public").classList.contains("hidden"), true);
  assert.equal(harness.document.getElementById("modal").classList.contains("open"), true);
  assert.match(harness.document.getElementById("modalBody").innerHTML, /LOGOUT FAILED/);
  assert.match(harness.document.getElementById("modalBody").innerHTML, /Logout is temporarily unavailable\./);
});

test("Squad logout failure preserves authenticated state, presence, and visible Squad UI", async () => {
  const harness = await publicHarness();
  harness.document.getElementById("app").classList.remove("hidden");
  harness.document.getElementById("public").classList.add("hidden");
  harness.document.querySelector("footer").classList.add("hidden");
  vm.runInContext(`
    current = { id: "squad-1", ign: "SquadTester", role: "Squad Member", profileComplete: true };
    db.members.push({ id: "squad-1", ign: "SquadTester", status: "Online" });
  `, harness.context);
  harness.setFetch(async () => jsonResponse(false, { error: "Logout is temporarily unavailable." }));

  await vm.runInContext("logout()", harness.context);

  assert.equal(vm.runInContext("current.id", harness.context), "squad-1");
  assert.equal(vm.runInContext('db.members.find((member) => member.id === "squad-1").status', harness.context), "Online");
  assert.equal(harness.document.getElementById("app").classList.contains("hidden"), false);
  assert.equal(harness.document.getElementById("public").classList.contains("hidden"), true);
  assert.match(harness.document.getElementById("modalBody").innerHTML, /LOGOUT FAILED/);
});

test("Squad logout success does not attempt state sync after session revocation", async () => {
  const harness = await publicHarness();
  harness.document.getElementById("app").classList.remove("hidden");
  harness.document.getElementById("public").classList.add("hidden");
  harness.document.querySelector("footer").classList.add("hidden");
  vm.runInContext(`
    current = { id: "squad-1", ign: "SquadTester", role: "Squad Member", profileComplete: true };
    db.members.push({ id: "squad-1", ign: "SquadTester", status: "Online" });
  `, harness.context);
  const requestPaths = [];
  harness.setFetch(async (requestPath) => {
    requestPaths.push(requestPath);
    return jsonResponse(true, { ok: true });
  });

  const result = await vm.runInContext("logout()", harness.context);
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(result, true);
  assert.deepEqual(requestPaths, ["/api/logout"]);
  assert.equal(vm.runInContext('db.members.find((member) => member.id === "squad-1").status', harness.context), "Offline");
  assert.equal(vm.runInContext("current", harness.context), null);
  assert.equal(harness.document.getElementById("app").classList.contains("hidden"), true);
  assert.equal(harness.document.getElementById("public").classList.contains("hidden"), false);
});

test("Owner concurrent logout calls share one successful revocation", async () => {
  const harness = ownerHarness();
  await new Promise((resolve) => setImmediate(resolve));
  vm.runInContext(`
    activeOwnerSession = { id: "owner-1", role: "Overall Owner" };
    renderOwnerDashboard({ health: { backend: "healthy", database: "healthy" }, counts: {}, pending: {}, recentAudit: [] });
  `, harness.context);
  const response = deferred();
  let fetchCount = 0;
  harness.setFetch(() => {
    fetchCount += 1;
    return response.promise;
  });

  const first = vm.runInContext("ownerLogout()", harness.context);
  const second = vm.runInContext("ownerLogout()", harness.context);
  response.resolve(jsonResponse(true, { ok: true }));
  const results = await Promise.all([first, second]);

  assert.equal(fetchCount, 1);
  assert.deepEqual(results, [true, true]);
  assert.equal(vm.runInContext("activeOwnerSession", harness.context), null);
  assert.ok(harness.ownerRoot.querySelector(".owner-admin__auth-shell"));
});

test("Community concurrent logout cannot surface a late failure after success", async () => {
  const harness = await publicHarness();
  harness.document.getElementById("communityApp").classList.remove("hidden");
  harness.document.getElementById("public").classList.add("hidden");
  vm.runInContext('communityCurrent = { id: "community-1", ign: "Tester", email: "tester@example.test" }; current = null;', harness.context);
  const success = deferred();
  const lateFailure = deferred();
  let fetchCount = 0;
  harness.setFetch(() => {
    fetchCount += 1;
    return fetchCount === 1 ? success.promise : lateFailure.promise;
  });

  const first = vm.runInContext("communityLogout()", harness.context);
  const second = vm.runInContext("communityLogout()", harness.context);
  success.resolve(jsonResponse(true, { ok: true }));
  await new Promise((resolve) => setImmediate(resolve));
  lateFailure.resolve(jsonResponse(false, { error: "Late logout failure." }));
  const results = await Promise.all([first, second]);

  assert.equal(fetchCount, 1);
  assert.deepEqual(results, [true, true]);
  assert.equal(vm.runInContext("communityCurrent", harness.context), null);
  assert.equal(harness.document.getElementById("public").classList.contains("hidden"), false);
  assert.equal(harness.document.getElementById("modal").classList.contains("open"), false);
});

test("Squad concurrent logout failure preserves state and permits one retry after settlement", async () => {
  const harness = await publicHarness();
  harness.document.getElementById("app").classList.remove("hidden");
  harness.document.getElementById("public").classList.add("hidden");
  vm.runInContext(`
    current = { id: "squad-1", ign: "SquadTester", role: "Squad Member", profileComplete: true };
    db.members.push({ id: "squad-1", ign: "SquadTester", status: "Online" });
  `, harness.context);
  const failure = deferred();
  let logoutFetchCount = 0;
  harness.setFetch((requestPath) => {
    if (requestPath === "/api/logout") {
      logoutFetchCount += 1;
      return failure.promise;
    }
    return Promise.resolve(jsonResponse(true, { ok: true }));
  });

  const first = vm.runInContext("logout()", harness.context);
  const second = vm.runInContext("logout()", harness.context);
  failure.resolve(jsonResponse(false, { error: "Logout is temporarily unavailable." }));
  const failedResults = await Promise.all([first, second]);

  assert.equal(logoutFetchCount, 1);
  assert.deepEqual(failedResults, [false, false]);
  assert.equal(vm.runInContext("current.id", harness.context), "squad-1");
  assert.equal(vm.runInContext('db.members.find((member) => member.id === "squad-1").status', harness.context), "Online");

  harness.setFetch(async (requestPath) => {
    if (requestPath === "/api/logout") logoutFetchCount += 1;
    return jsonResponse(true, { ok: true });
  });
  const retried = await vm.runInContext("logout()", harness.context);

  assert.equal(retried, true);
  assert.equal(logoutFetchCount, 2);
  assert.equal(vm.runInContext("current", harness.context), null);
  assert.equal(harness.document.getElementById("public").classList.contains("hidden"), false);
});

test("Owner tournament section renders detail identifiers and administration queues", async () => {
  const harness = ownerHarness();
  await new Promise((resolve) => setImmediate(resolve));
  harness.setFetch(async (path) => {
    if (path === "/api/owner/tournaments") return jsonResponse(true, { tournaments: [{ id: "T-1", title: "Finals", game: "MLBB", format: "1v1", date: "2099-01-01", status: "Open" }] });
    if (path === "/api/owner/tournaments/T-1") return jsonResponse(true, { tournament: { id: "T-1", title: "Finals" }, registrations: [{ id: "R-1", accountId: "C-1", status: "Pending" }], approvals: [{ id: "A-1", status: "Pending" }], bracket: [{ id: "B-1" }], matches: [{ id: "M-1", player1: "C-1", player2: "C-2" }], resultSubmissions: [{ id: "RS-1" }], disputes: [{ id: "D-1" }] });
    return jsonResponse(true, {});
  });
  vm.runInContext(`activeOwnerSession={role:"Overall Owner"}; renderOwnerDashboard({health:{},counts:{},pending:{},recentAudit:[]})`, harness.context);
  await vm.runInContext(`openOwnerSection("tournaments")`, harness.context);
  const view = harness.ownerRoot.querySelector(".owner-admin__workspace");
  assert.match(descendants([view]).map((node) => node.textContent).join(" "), /T-1/);
  const detailButton = descendants([view]).find((node) => node.textContent === "View details");
  assert.ok(detailButton);
  await detailButton.listeners.get("click")();
  const text = descendants([view]).map((node) => node.textContent).join(" ");
  for (const expected of ["R-1", "A-1", "B-1", "M-1", "RS-1", "D-1"]) assert.match(text, new RegExp(expected));
});

test("Owner Squad section uses backend cursor pagination and guarded destructive action", async () => {
  const harness = ownerHarness();
  await new Promise((resolve) => setImmediate(resolve));
  const requests = [];
  harness.setFetch(async (path, options = {}) => {
    requests.push([path, options.method || "GET"]);
    if (String(path).startsWith("/api/owner/squad-members")) return jsonResponse(true, { members: [{ id: "S-1", name: "Alpha", ign: "Alpha", role: "Squad Member", status: "Offline" }], nextCursor: "S-1" });
    return jsonResponse(true, {});
  });
  vm.runInContext(`activeOwnerSession={role:"Overall Owner"}; renderOwnerDashboard({health:{},counts:{},pending:{},recentAudit:[]})`, harness.context);
  await vm.runInContext(`openOwnerSection("squads")`, harness.context);
  const view = harness.ownerRoot.querySelector(".owner-admin__workspace");
  const next = descendants([view]).find((node) => node.textContent === "Next");
  assert.ok(next);
  await next.listeners.get("click")();
  assert.ok(requests.some(([path]) => String(path).includes("cursor=S-1")));
  const disable = descendants([view]).find((node) => node.textContent === "Disable");
  assert.ok(disable);
  await disable.listeners.get("click")();
  assert.ok(requests.some(([path, method]) => path === "/api/owner/squad-members/S-1" && method === "PATCH"));
});

test("Owner content forms switch to domain-specific event and notification fields", async () => {
  const harness = ownerHarness(); await new Promise((resolve) => setImmediate(resolve));
  harness.setFetch(async () => jsonResponse(true, { items: [] }));
  vm.runInContext(`activeOwnerSession={role:"Overall Owner"}; renderOwnerDashboard({health:{},counts:{},pending:{},recentAudit:[]})`, harness.context);
  await vm.runInContext(`openOwnerSection("content")`, harness.context);
  const domain = harness.document.getElementById("owner-content-domain");
  domain.value = "events"; await domain.listeners.get("change")();
  let text = descendants([harness.ownerRoot]).map((node) => node.textContent).join(" ");
  assert.match(text, /Date/);
  domain.value = "notifications"; await domain.listeners.get("change")();
  text = descendants([harness.ownerRoot]).map((node) => node.textContent).join(" ");
  assert.match(text, /Message/); assert.match(text, /Audience type/);
});

test("Owner settings renders the backend settings envelope", async () => {
  const harness = ownerHarness(); await new Promise((resolve) => setImmediate(resolve));
  harness.setFetch(async (path) => path === "/api/owner/settings" ? jsonResponse(true, { settings: { username: "root-owner", createdAt: "now", sessionTtlSeconds: 900, recoveryCodeTtlSeconds: 600 } }) : jsonResponse(true, {}));
  vm.runInContext(`activeOwnerSession={role:"Overall Owner"}; renderOwnerDashboard({health:{},counts:{},pending:{},recentAudit:[]})`, harness.context);
  await vm.runInContext(`openOwnerSection("settings")`, harness.context);
  assert.match(descendants([harness.ownerRoot]).map((node) => node.textContent).join(" "), /root-owner/);
});

test("Owner guarded row action surfaces a safe panel error and restores its button", async () => {
  const harness = ownerHarness(); await new Promise((resolve) => setImmediate(resolve));
  harness.setFetch(async (path, options = {}) => {
    if ((options.method || "GET") === "PATCH") return jsonResponse(false, { error: "Account update failed safely." });
    return jsonResponse(true, { members: [{ id: "S-1", name: "Alpha", ign: "Alpha", role: "Squad Member", status: "Offline" }], nextCursor: null });
  });
  vm.runInContext(`activeOwnerSession={role:"Overall Owner"}; renderOwnerDashboard({health:{},counts:{},pending:{},recentAudit:[]})`, harness.context);
  await vm.runInContext(`openOwnerSection("squads")`, harness.context);
  const disable = descendants([harness.ownerRoot]).find((node) => node.textContent === "Disable"); await disable.listeners.get("click")();
  const alert = harness.ownerRoot.querySelector(".owner-admin__workspace").querySelector('[role="alert"]'); assert.equal(alert.hidden, false); assert.equal(alert.textContent, "Account update failed safely.");
  assert.equal(disable.disabled, false); assert.equal(disable.textContent, "Disable");
});

test("Owner navigation loads all nine administration sections", async () => {
  const harness = ownerHarness(); await new Promise((resolve) => setImmediate(resolve));
  harness.setFetch(async (path) => {
    if (String(path).startsWith("/api/owner/squad-members")) return jsonResponse(true, { members: [], nextCursor: null });
    if (String(path).startsWith("/api/owner/community-accounts")) return jsonResponse(true, { accounts: [], nextCursor: null });
    if (String(path).startsWith("/api/owner/squad-content")) return jsonResponse(true, { items: [] });
    if (path === "/api/owner/tournaments") return jsonResponse(true, { tournaments: [] });
    if (path === "/api/owner/seasons") return jsonResponse(true, { currentSeason: null, leaderboard: [], seasons: [] });
    if (path === "/api/owner/events") return jsonResponse(true, { events: [], participation: [] });
    if (path === "/api/owner/history") return jsonResponse(true, { seasonHistory: [], seasonHallOfFame: [], hallOfFame: [] });
    if (String(path).startsWith("/api/owner/audit")) return jsonResponse(true, { audit: [], nextCursor: "" });
    if (path === "/api/owner/settings") return jsonResponse(true, { settings: { username: "owner" } });
    if (path === "/api/owner/overview") return jsonResponse(true, { health: {}, counts: {}, pending: {}, recentAudit: [] });
    return jsonResponse(true, {});
  });
  vm.runInContext(`activeOwnerSession={role:"Overall Owner"}; renderOwnerDashboard({health:{},counts:{},pending:{},recentAudit:[]})`, harness.context);
  for (const section of ["overview", "squads", "community", "content", "tournaments", "seasons", "history", "audit", "settings"]) {
    await vm.runInContext(`openOwnerSection(${JSON.stringify(section)})`, harness.context);
    const alert = harness.ownerRoot.querySelector(".owner-admin__workspace").querySelector('[role="alert"]');
    assert.equal(alert.hidden, true, `${section} should load without an error`);
  }
});

test("Owner representative edit and create forms send domain-correct payloads", async () => {
  const harness = ownerHarness(); await new Promise((resolve) => setImmediate(resolve)); const writes = [];
  harness.setFetch(async (path, options = {}) => {
    if (options.body) writes.push([path, options.method, JSON.parse(options.body)]);
    if (String(path).startsWith("/api/owner/community-accounts")) return jsonResponse(true, { accounts: [{ id: "C-1", ign: "One", status: "Active" }], nextCursor: "C-next", account: {} });
    if (String(path).startsWith("/api/owner/squad-content")) return jsonResponse(true, { items: [] });
    if (path === "/api/owner/tournaments") return jsonResponse(true, { tournaments: [] });
    return jsonResponse(true, {});
  });
  vm.runInContext(`activeOwnerSession={role:"Overall Owner"}; renderOwnerDashboard({health:{},counts:{},pending:{},recentAudit:[]})`, harness.context);
  await vm.runInContext(`openOwnerSection("community")`, harness.context);
  const communityForm = formByHeading(harness.ownerRoot, "Edit Community profile"); fillForm(communityForm, { accountId: "C-1", ign: "Updated", email: "updated@example.com" }); await submitAsBrowser(communityForm);
  const communityNext = descendants([harness.ownerRoot]).find((node) => node.textContent === "Next" && !node.disabled); await communityNext.listeners.get("click")();
  await vm.runInContext(`openOwnerSection("content")`, harness.context); const domain = harness.document.getElementById("owner-content-domain"); domain.value = "events"; await domain.listeners.get("change")();
  const contentForm = formByHeading(harness.ownerRoot, "Create Events"); fillForm(contentForm, { title: "Squad Day", date: "2099-05-04", time: "12:30", description: "Meet" }); await submitAsBrowser(contentForm);
  await vm.runInContext(`openOwnerSection("tournaments")`, harness.context); const tournamentForm = formByHeading(harness.ownerRoot, "Create tournament"); fillForm(tournamentForm, { title: "Cup", game: "MLBB", format: "1v1", date: "2099-06-01" }); await submitAsBrowser(tournamentForm);
  assert.ok(writes.some(([path, method, body]) => path === "/api/owner/community-accounts/C-1" && method === "PATCH" && body.ign === "Updated"));
  assert.ok(writes.some(([path, method, body]) => path === "/api/owner/squad-content/events" && method === "POST" && body.date === "2099-05-04"));
  assert.ok(writes.some(([path, method, body]) => path === "/api/owner/tournaments" && method === "POST" && body.title === "Cup"));
});

test("Owner audit cursor, history IDs, bracket object, and secret clearing follow backend contracts", async () => {
  const harness = ownerHarness(); await new Promise((resolve) => setImmediate(resolve)); const requests = [];
  harness.setFetch(async (path, options = {}) => {
    requests.push([path, options]);
    if (String(path).startsWith("/api/owner/audit")) return jsonResponse(true, { audit: [{ id: "AU-1", action: "owner_event_update" }], nextCursor: "CUR-2" });
    if (path === "/api/owner/events") return jsonResponse(true, { events: [], participation: [] });
    if (path === "/api/owner/history") return jsonResponse(true, { seasonHistory: [{ id: "SH-1", seasonId: "S-1" }], hallOfFame: [{ id: "H-1" }], seasonHallOfFame: [{ id: "SF-1" }] });
    if (path === "/api/owner/tournaments") return jsonResponse(true, { tournaments: [{ id: "T-1", title: "Cup" }] });
    if (path === "/api/owner/tournaments/T-1") return jsonResponse(true, { tournament: { id: "T-1" }, registrations: [{ id: "R-W", status: "Withdrawn" }, { id: "R-A", status: "Approved" }], approvals: [], bracket: { ready: true, generatedAt: "now", matches: [{ id: "BM-1" }] }, matches: [], resultSubmissions: [], disputes: [] });
    if (path === "/api/owner/settings" && options.method === "PATCH") return jsonResponse(true, { settings: { username: "owner" } });
    if (path === "/api/owner/settings") return jsonResponse(true, { settings: { username: "owner" } });
    return jsonResponse(true, {});
  });
  vm.runInContext(`activeOwnerSession={role:"Overall Owner"}; renderOwnerDashboard({health:{},counts:{},pending:{},recentAudit:[]})`, harness.context);
  await vm.runInContext(`openOwnerSection("audit")`, harness.context); const auditForm = formByHeading(harness.ownerRoot, "Filter audit records"); fillForm(auditForm, { action: "owner_event_update", actor: "owner", target: "event", from: "2026-01-01", to: "2026-12-31", limit: 25 }); await submitAsBrowser(auditForm); const next = descendants([harness.ownerRoot]).find((node) => node.textContent === "Next" && !node.disabled); await next.listeners.get("click")();
  assert.ok(requests.some(([path]) => String(path).includes("cursor=CUR-2") && String(path).includes("actor=owner") && String(path).includes("limit=25")));
  await vm.runInContext(`openOwnerSection("history")`, harness.context); let text = descendants([harness.ownerRoot]).map((node) => node.textContent).join(" "); for (const id of ["SH-1", "H-1", "SF-1"]) assert.match(text, new RegExp(id));
  await vm.runInContext(`openOwnerSection("tournaments")`, harness.context); const details = descendants([harness.ownerRoot]).find((node) => node.textContent === "View details"); await details.listeners.get("click")(); text = descendants([harness.ownerRoot]).map((node) => node.textContent).join(" "); for (const label of ["BM-1", "Reinstate", "Withdraw"]) assert.match(text, new RegExp(label));
  await vm.runInContext(`openOwnerSection("settings")`, harness.context); const settingsForm = formByHeading(harness.ownerRoot, "Change Owner password"); fillForm(settingsForm, { currentPassword: "old-secret", newPassword: "new-secret-123", passwordConfirmation: "new-secret-123" }); await submitAsBrowser(settingsForm); for (const input of descendants(settingsForm.children).filter((node) => node.getAttribute("data-secret") === "true")) assert.equal(input.value, "");
});

test("Squad leader registration sends the typed invitation code to the server", async () => {
  const harness = await publicHarness();
  const requests = [];
  harness.setFetch(async (requestPath, options) => {
    requests.push({ requestPath, payload: JSON.parse(options.body) });
    return jsonResponse(true, {
      approval: {
        id: "approval-1", tournamentId: "squad-tournament",
        leaderAccountId: "community-1", status: "Pending",
      },
      approvals: [],
    });
  });
  vm.runInContext(`
    communityCurrent = { id: "community-1", ign: "Leader", gameId: "123456", serverId: "4321" };
    communityDb.tournaments = [{
      id: "squad-tournament", title: "Squad Tournament", format: "Squad vs Squad",
      status: "Open", registrationOpen: true, squadRegistrationOpen: true,
      squadSlots: 4, membersPerSquad: 7
    }];
    communityDb.squadTournamentApprovals = [];
  `, harness.context);

  await vm.runInContext(
    'submitSTLeaderRegistration("squad-tournament", "Boundary Squad", "BS-1", "TYPED-LEADER-CODE", communityCurrent, null)',
    harness.context,
  );

  const submissions = requests.filter(({ requestPath }) => requestPath === "/api/tournaments/squad-approval");
  assert.equal(submissions.length, 1);
  assert.equal(submissions[0].payload.action, "submit_leader");
  assert.equal(submissions[0].payload.accessCode, "TYPED-LEADER-CODE");
  assert.equal("leaderAccountId" in submissions[0].payload, false);
});

test("Squad member registration submits its code without a downloaded approval list", async () => {
  const harness = await publicHarness();
  const requests = [];
  harness.setFetch(async (requestPath, options) => {
    requests.push({ requestPath, payload: JSON.parse(options.body) });
    return jsonResponse(true, {
      registration: {
        id: "registration-1", tournamentId: "squad-tournament",
        accountId: "community-1", squadApprovalId: "approval-1",
        squadName: "Boundary Squad", isSubstitute: false,
      },
      registrations: [],
    });
  });
  vm.runInContext(`
    communityCurrent = { id: "community-1", ign: "Member", gameId: "123456", serverId: "4321" };
    communityDb.tournaments = [{
      id: "squad-tournament", title: "Squad Tournament", format: "Squad vs Squad",
      status: "Open", registrationOpen: true, membersPerSquad: 7
    }];
    communityDb.squadTournamentApprovals = [];
    communityDb.registrations = [];
  `, harness.context);

  await vm.runInContext(
    'submitSTMemberRegistration("squad-tournament", "TYPED-MEMBER-CODE", communityCurrent)',
    harness.context,
  );

  const submissions = requests.filter(({ requestPath }) => requestPath === "/api/tournaments/squad-approval");
  assert.equal(submissions.length, 1);
  assert.equal(submissions[0].payload.action, "join_member");
  assert.equal(submissions[0].payload.accessCode, "TYPED-MEMBER-CODE");
  assert.equal("accountId" in submissions[0].payload, false);
});
