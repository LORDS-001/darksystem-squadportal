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
    document,
    fetch: (...args) => fetchImplementation(...args),
    Headers,
    setTimeout,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  const context = vm.createContext(sandbox);
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
