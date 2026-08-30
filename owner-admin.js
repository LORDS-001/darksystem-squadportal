"use strict";

const ownerRoot = document.getElementById("ownerRoot");
let activeOwnerSession = null;
let activeOwnerLogoutRequest = null;

function ownerElement(tagName, className, text) {
  const element = document.createElement(tagName);
  if (className) element.className = className;
  if (text !== undefined && text !== null) element.textContent = String(text);
  return element;
}

function ownerValue(value) {
  if (value === null || value === undefined || value === "") return "Unavailable";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function ownerLabel(key) {
  return String(key).replace(/([A-Z])/g, " $1").replace(/^./, (character) => character.toUpperCase());
}

function setOwnerRoot(content) {
  ownerRoot.replaceChildren(content);
  ownerRoot.setAttribute("aria-busy", "false");
}

function appendOwnerError(container, message) {
  const error = ownerElement("p", "owner-admin__error-banner", message);
  error.setAttribute("role", "alert");
  container.append(error);
  return error;
}

function setOwnerError(error, message) {
  error.textContent = message || "";
  error.hidden = !message;
}

function setOwnerBusy(button, busy, label) {
  button.disabled = busy;
  button.textContent = busy ? "Please wait..." : label;
}

async function ownerApi(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");
  const request = {
    ...options,
    credentials: "same-origin",
    headers,
  };

  let response;
  try {
    response = await fetch(path, request);
  } catch {
    throw new Error("The request could not be completed.");
  }
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    throw new Error("The request could not be completed.");
  }
  if (!response.ok) {
    throw new Error(typeof payload.error === "string" ? payload.error : "The request could not be completed.");
  }
  return payload;
}

function ownerField({ id, name, label, type = "text", autocomplete, required = true, hint }) {
  const field = ownerElement("div", "owner-admin__field");
  const fieldLabel = ownerElement("label", "owner-admin__field-label", label);
  fieldLabel.htmlFor = id;
  const input = ownerElement("input", "owner-admin__input");
  input.id = id;
  input.name = name;
  input.type = type;
  input.required = required;
  if (autocomplete) input.autocomplete = autocomplete;
  field.append(fieldLabel, input);
  if (hint) field.append(ownerElement("p", "owner-admin__field-hint", hint));
  return { field, input };
}

function ownerAuthShell(eyebrow, title, copy) {
  const shell = ownerElement("section", "owner-admin__auth-shell");
  const intro = ownerElement("div", "owner-admin__auth-intro");
  intro.append(
    ownerElement("p", "owner-admin__eyebrow", eyebrow),
    ownerElement("h1", "owner-admin__title", title),
    ownerElement("p", "owner-admin__copy", copy),
  );
  const card = ownerElement("section", "owner-admin__auth-card");
  shell.append(intro, card);
  return { shell, card };
}

function renderOwnerSetup() {
  const { shell, card } = ownerAuthShell(
    "ONE-TIME CONFIGURATION",
    "Set up the Overall Owner",
    "Create the protected Owner account and the initial Squad Owner identity. Setup locks after it succeeds.",
  );
  const form = ownerElement("form", "owner-admin__form");
  form.noValidate = true;
  const error = ownerElement("p", "owner-admin__error-banner");
  error.hidden = true;
  error.setAttribute("role", "alert");
  const setupSecret = ownerField({ id: "owner-setup-secret", name: "setupSecret", label: "Owner setup secret", type: "password", autocomplete: "off", hint: "Enter the private setup secret configured for this deployment." });
  const ownerHeading = ownerElement("h2", "owner-admin__form-heading", "Overall Owner credentials");
  const username = ownerField({ id: "owner-setup-username", name: "username", label: "Owner username", autocomplete: "username" });
  const password = ownerField({ id: "owner-setup-password", name: "password", label: "Owner password", type: "password", autocomplete: "new-password", hint: "Use at least 10 characters." });
  const passwordConfirmation = ownerField({ id: "owner-setup-password-confirmation", name: "passwordConfirmation", label: "Confirm Owner password", type: "password", autocomplete: "new-password" });
  const squadHeading = ownerElement("h2", "owner-admin__form-heading", "Initial Squad Owner credentials");
  const ign = ownerField({ id: "owner-setup-ign", name: "ign", label: "Squad Owner IGN", autocomplete: "off" });
  const gameId = ownerField({ id: "owner-setup-game-id", name: "gameId", label: "Game ID", autocomplete: "off" });
  const serverId = ownerField({ id: "owner-setup-server-id", name: "serverId", label: "Server ID", autocomplete: "off" });
  const accessCode = ownerField({ id: "owner-setup-access-code", name: "accessCode", label: "Squad access code", type: "password", autocomplete: "new-password" });
  const submit = ownerElement("button", "owner-admin__button", "Complete secure setup");
  submit.type = "submit";
  form.append(error, setupSecret.field, ownerHeading, username.field, password.field, passwordConfirmation.field, squadHeading, ign.field, gameId.field, serverId.field, accessCode.field, submit);
  card.append(form);
  setOwnerRoot(shell);

  function clearOwnerSetupSecrets() {
    setupSecret.input.value = "";
    password.input.value = "";
    passwordConfirmation.input.value = "";
    accessCode.input.value = "";
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    setOwnerError(error, "");
    if (password.input.value !== passwordConfirmation.input.value) {
      clearOwnerSetupSecrets();
      setOwnerError(error, "Owner password confirmation must match.");
      password.input.focus();
      return;
    }
    if (!form.reportValidity()) {
      clearOwnerSetupSecrets();
      return;
    }
    setOwnerBusy(submit, true, "Complete secure setup");
    try {
      await ownerApi("/api/owner/setup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          setupSecret: setupSecret.input.value,
          username: username.input.value.trim(),
          password: password.input.value,
          squadOwner: {
            ign: ign.input.value.trim(),
            gameId: gameId.input.value.trim(),
            serverId: serverId.input.value.trim(),
            accessCode: accessCode.input.value,
          },
        }),
      });
      renderOwnerLogin("Setup is complete. Sign in as the Overall Owner.");
    } catch (requestError) {
      setOwnerError(error, requestError.message);
    } finally {
      clearOwnerSetupSecrets();
      setOwnerBusy(submit, false, "Complete secure setup");
    }
  });
}

function renderOwnerLogin(notice = "", isError = false) {
  const { shell, card } = ownerAuthShell(
    "PRIVATE ACCESS",
    "Overall Owner login",
    "Use your Owner credentials to open the secure system overview.",
  );
  const form = ownerElement("form", "owner-admin__form");
  form.noValidate = true;
  const noticeElement = ownerElement("p", isError ? "owner-admin__error-banner" : "owner-admin__notice", notice);
  noticeElement.hidden = !notice;
  noticeElement.setAttribute("role", isError ? "alert" : "status");
  const error = ownerElement("p", "owner-admin__error-banner");
  error.hidden = true;
  error.setAttribute("role", "alert");
  const username = ownerField({ id: "owner-login-username", name: "username", label: "Owner username", autocomplete: "username" });
  const password = ownerField({ id: "owner-login-password", name: "password", label: "Owner password", type: "password", autocomplete: "current-password" });
  const submit = ownerElement("button", "owner-admin__button", "Sign in");
  submit.type = "submit";
  form.append(noticeElement, error, username.field, password.field, submit);
  card.append(form);
  setOwnerRoot(shell);
  username.input.focus();

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    setOwnerError(error, "");
    if (!form.reportValidity()) {
      password.input.value = "";
      return;
    }
    setOwnerBusy(submit, true, "Sign in");
    try {
      await ownerApi("/api/owner/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.input.value.trim(), password: password.input.value }),
      });
      activeOwnerSession = { role: "Overall Owner" };
      const overview = await ownerApi("/api/owner/overview");
      renderOwnerDashboard(overview);
    } catch (requestError) {
      activeOwnerSession = null;
      setOwnerError(error, requestError.message);
    } finally {
      password.input.value = "";
      setOwnerBusy(submit, false, "Sign in");
    }
  });
}

function appendMetricGroup(container, title, values) {
  const group = ownerElement("section", "owner-admin__metric-group");
  group.append(ownerElement("h2", "owner-admin__section-title", title));
  const grid = ownerElement("div", "owner-admin__metrics-grid");
  const entries = values && typeof values === "object" ? Object.entries(values) : [];
  if (!entries.length) {
    grid.append(ownerElement("p", "owner-admin__empty", "No values are available."));
  } else {
    for (const [key, value] of entries) {
      const card = ownerElement("article", "owner-admin__metric-card");
      card.append(
        ownerElement("span", "owner-admin__metric-label", ownerLabel(key)),
        ownerElement("strong", "owner-admin__metric-value", ownerValue(value)),
      );
      grid.append(card);
    }
  }
  group.append(grid);
  container.append(group);
}

function renderOwnerDashboard(data) {
  const dashboard = ownerElement("section", "owner-admin__dashboard");
  const header = ownerElement("header", "owner-admin__dashboard-header");
  const heading = ownerElement("div", "owner-admin__dashboard-heading");
  heading.append(
    ownerElement("p", "owner-admin__eyebrow", "OVERALL OWNER"),
    ownerElement("h1", "owner-admin__title", "Overview"),
    ownerElement("p", "owner-admin__copy", "Current operational state for Dark System."),
  );
  const logout = ownerElement("button", "owner-admin__button owner-admin__button--secondary", "Logout");
  logout.type = "button";
  logout.addEventListener("click", ownerLogout);
  header.append(heading, logout);
  const logoutError = ownerElement("p", "owner-admin__error-banner owner-admin__logout-error");
  logoutError.hidden = true;
  logoutError.setAttribute("role", "alert");
  dashboard.append(header, logoutError);

  const health = data && typeof data.health === "object" ? data.health : {};
  const healthCard = ownerElement("section", "owner-admin__health-card");
  const backendHealth = ownerElement("p", "owner-admin__health-indicator", "Backend: ");
  backendHealth.append(ownerElement("span", "owner-admin__health-value", ownerValue(health.backend)));
  const databaseHealth = ownerElement("p", "owner-admin__health-indicator", "Database: ");
  databaseHealth.append(ownerElement("span", "owner-admin__health-value", ownerValue(health.database)));
  healthCard.append(ownerElement("h2", "owner-admin__section-title", "System health"), backendHealth, databaseHealth);
  dashboard.append(healthCard);
  appendMetricGroup(dashboard, "System totals", data && data.counts);
  appendMetricGroup(dashboard, "Pending work", data && data.pending);

  const activity = ownerElement("section", "owner-admin__activity-section");
  activity.append(ownerElement("h2", "owner-admin__section-title", "Recent Activity"));
  const list = ownerElement("div", "owner-admin__activity-list");
  const recentAudit = Array.isArray(data && data.recentAudit) ? data.recentAudit : [];
  if (!recentAudit.length) {
    list.append(ownerElement("p", "owner-admin__empty", "No recent activity is available."));
  } else {
    for (const item of recentAudit) {
      const row = ownerElement("article", "owner-admin__activity-item");
      const detail = ownerElement("div", "owner-admin__activity-detail");
      const meta = ownerElement("span", "owner-admin__activity-meta");
      meta.append(
        document.createTextNode(ownerValue(item && item.actor_role)),
        document.createTextNode(" / "),
        document.createTextNode(ownerValue(item && item.created_at)),
      );
      detail.append(ownerElement("span", "owner-admin__activity-dot"), ownerElement("strong", "owner-admin__activity-action", ownerValue(item && item.action)), meta);
      row.append(detail);
      list.append(row);
    }
  }
  activity.append(list);
  dashboard.append(activity);
  setOwnerRoot(dashboard);
}

const OWNER_SECTIONS = [
  ["overview", "Overview"], ["squads", "Squads"], ["community", "Community"],
  ["content", "Content"], ["tournaments", "Tournaments"],
  ["seasons", "Seasons & Rankings"], ["history", "Events & History"],
  ["audit", "Audit"], ["settings", "Settings"],
];
let ownerActiveSection = "overview";
let ownerOverviewData = null;

function ownerButton(label, onClick, secondary = false) {
  const button = ownerElement("button", `owner-admin__button${secondary ? " owner-admin__button--secondary" : ""}`, label);
  button.type = "button";
  if (onClick) button.addEventListener("click", onClick);
  return button;
}

function ownerActionButton(shell, label, work, { confirmText = "", secondary = true } = {}) {
  let button;
  button = ownerButton(label, async () => {
    if (confirmText && !confirm(confirmText)) return;
    setOwnerError(shell.error, ""); setOwnerBusy(button, true, label);
    try { await work(); }
    catch (error) { ownerSetNotice(shell, error.message, true); }
    finally { if (button.isConnected !== false) setOwnerBusy(button, false, label); }
  }, secondary);
  return button;
}

function ownerStatusRegion() {
  const status = ownerElement("p", "owner-admin__notice");
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  status.hidden = true;
  return status;
}

function ownerSectionShell(title, description) {
  const section = ownerElement("section", "owner-admin__panel");
  const header = ownerElement("header", "owner-admin__panel-header");
  const copy = ownerElement("div");
  copy.append(ownerElement("h1", "owner-admin__title owner-admin__title--section", title), ownerElement("p", "owner-admin__copy", description));
  const refresh = ownerButton("Refresh", () => openOwnerSection(ownerActiveSection), true);
  header.append(copy, refresh);
  const status = ownerStatusRegion();
  const error = ownerElement("p", "owner-admin__error-banner");
  error.hidden = true;
  error.setAttribute("role", "alert");
  const content = ownerElement("div", "owner-admin__panel-content");
  section.append(header, status, error, content);
  return { section, content, status, error };
}

function ownerSetNotice(shell, message, isError = false) {
  setOwnerError(shell.error, isError ? message : "");
  shell.status.textContent = isError ? "" : message;
  shell.status.hidden = isError || !message;
}

function ownerForm(title, fields, submitLabel, onSubmit) {
  const card = ownerElement("section", "owner-admin__card");
  card.append(ownerElement("h2", "owner-admin__section-title", title));
  const form = ownerElement("form", "owner-admin__form owner-admin__form--grid");
  form.noValidate = true;
  for (const field of fields) {
    const built = ownerField({ ...field, id: `owner-${title.toLowerCase().replace(/[^a-z]+/g, "-")}-${field.name}` });
    if (field.value !== undefined) built.input.value = field.value;
    if (field.secret) built.input.setAttribute("data-secret", "true");
    form.append(built.field);
  }
  const submit = ownerElement("button", "owner-admin__button", submitLabel);
  submit.type = "submit";
  form.append(submit);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!form.reportValidity()) { OwnerAdminApi.clearSecrets(form); return; }
    setOwnerBusy(submit, true, submitLabel);
    const values = Object.fromEntries(new FormData(form).entries());
    try { await onSubmit(values, form); }
    catch (requestError) {
      const panel = form.closest(".owner-admin__panel");
      const error = panel && panel.querySelector(".owner-admin__error-banner");
      if (error) setOwnerError(error, requestError.message);
    } finally { OwnerAdminApi.clearSecrets(form); setOwnerBusy(submit, false, submitLabel); }
  });
  card.append(form);
  return card;
}

function ownerRows(items, columns, actions) {
  if (!Array.isArray(items) || !items.length) return ownerElement("p", "owner-admin__empty", "No records match the current filters.");
  const wrap = ownerElement("div", "owner-admin__table-wrap");
  const table = ownerElement("table", "owner-admin__table");
  const thead = ownerElement("thead");
  const heading = ownerElement("tr");
  for (const column of columns) heading.append(ownerElement("th", "", ownerLabel(column)));
  if (actions) heading.append(ownerElement("th", "", "Actions"));
  thead.append(heading);
  const tbody = ownerElement("tbody");
  for (const raw of items) {
    const item = OwnerAdminApi.scrub(raw);
    const row = ownerElement("tr");
    for (const column of columns) row.append(ownerElement("td", "", ownerValue(item[column])));
    if (actions) { const cell = ownerElement("td", "owner-admin__actions"); actions(item, cell); row.append(cell); }
    tbody.append(row);
  }
  table.append(thead, tbody); wrap.append(table); return wrap;
}

async function ownerRequest(path, options) {
  return OwnerAdminApi.request(path, options, { onUnauthorized: () => {
    activeOwnerSession = null;
    renderOwnerLogin("Your Owner session has expired. Sign in again.", true);
  } });
}

function ownerQueryForm(onChange, options = {}) {
  const form = ownerElement("form", "owner-admin__filters");
  const label = ownerElement("label", "owner-admin__field-label", "Filter records");
  label.htmlFor = `owner-filter-${ownerActiveSection}`;
  const input = ownerElement("input", "owner-admin__input");
  input.id = label.htmlFor; input.type = "search"; input.placeholder = options.placeholder || "Search";
  const submit = ownerElement("button", "owner-admin__button owner-admin__button--secondary", "Apply filter"); submit.type = "submit";
  form.append(label, input, submit);
  form.addEventListener("submit", (event) => { event.preventDefault(); onChange(input.value.trim()); });
  return form;
}

function renderOwnerOverviewSection(shell, data) {
  const health = data && data.health || {};
  const healthCard = ownerElement("section", "owner-admin__health-card");
  const backend = ownerElement("p", "owner-admin__health-indicator", "Backend: "); backend.append(ownerElement("span", "owner-admin__health-value", ownerValue(health.backend)));
  const database = ownerElement("p", "owner-admin__health-indicator", "Database: "); database.append(ownerElement("span", "owner-admin__health-value", ownerValue(health.database)));
  healthCard.append(ownerElement("h2", "owner-admin__section-title", "System health"), backend, database);
  shell.content.append(healthCard);
  appendMetricGroup(shell.content, "System totals", data && data.counts);
  appendMetricGroup(shell.content, "Pending work", data && data.pending);
  shell.content.append(ownerElement("h2", "owner-admin__section-title", "Recent Activity"), ownerRows(data && data.recentAudit, ["action", "actor_role", "target_type", "created_at"]));
}

async function renderOwnerSquads(shell) {
  let search = "", cursor = ""; const cursors = [];
  const draw = async () => {
    const query = new URLSearchParams({ limit: "25" }); if (search) query.set("search", search); if (cursor) query.set("cursor", cursor);
    const data = await ownerRequest(`${OwnerAdminSquad.endpoints.squads}?${query}`);
    const old = shell.content.querySelector(".owner-admin__records"); if (old) old.remove();
    const records = ownerElement("section", "owner-admin__records");
    records.append(ownerRows(data.members, ["id", "name", "ign", "gameId", "serverId", "role", "status"], (member, cell) => {
      cell.append(ownerActionButton(shell, member.status === "Disabled" ? "Activate" : "Disable", async () => {
        await ownerRequest(`${OwnerAdminSquad.endpoints.squads}/${encodeURIComponent(member.id)}`, OwnerAdminApi.json("PATCH", { status: member.status === "Disabled" ? "Offline" : "Disabled" })); await draw();
      }, { confirmText: member.status === "Disabled" ? "" : `Disable ${member.ign}? Their active sessions will be revoked.` }), ownerActionButton(shell, "Appoint Owner", async () => {
        await ownerRequest("/api/owner/squad-owner", OwnerAdminApi.json("POST", { memberId: member.id })); await draw();
      }, { confirmText: `Appoint ${member.ign} as Squad Owner?` }), ownerActionButton(shell, "Remove", async () => {
        await ownerRequest(`${OwnerAdminSquad.endpoints.squads}/${encodeURIComponent(member.id)}`, { method: "DELETE" }); await draw();
      }, { confirmText: `Remove ${member.ign}? This cannot be undone.` }));
    }));
    const pager = ownerElement("div", "owner-admin__pager");
    const previous = ownerActionButton(shell, "Previous", async () => { cursor = cursors.pop() || ""; await draw(); }); previous.disabled = !cursors.length;
    const next = ownerActionButton(shell, "Next", async () => { if (!data.nextCursor) return; cursors.push(cursor); cursor = data.nextCursor; await draw(); }); next.disabled = !data.nextCursor;
    pager.append(previous, next); records.append(pager); shell.content.append(records);
  };
  shell.content.append(ownerQueryForm((value) => { search = value; cursor = ""; cursors.length = 0; draw().catch((e) => ownerSetNotice(shell, e.message, true)); }), ownerForm("Create Squad member", [
    { name: "name", label: "Name" }, { name: "ign", label: "IGN" }, { name: "gameId", label: "Game ID" }, { name: "serverId", label: "Server ID" },
    { name: "email", label: "Registered email", type: "email" }, { name: "role", label: "Role", value: "Squad Member" },
  ], "Create member", async (values, form) => { await ownerRequest(OwnerAdminSquad.endpoints.squads, OwnerAdminApi.json("POST", values)); form.reset(); ownerSetNotice(shell, "Squad account created; recovery required. The member must use self-service recovery to set their access code (audit: owner_squad_member_create)."); await draw(); }), ownerForm("Edit Squad member or role", [
    { name: "memberId", label: "Member ID" }, { name: "name", label: "Name", required: false }, { name: "ign", label: "IGN", required: false }, { name: "role", label: "Role", required: false }, { name: "status", label: "Status", required: false },
  ], "Save Squad member", async (values) => { const id = values.memberId; delete values.memberId; Object.keys(values).forEach((key) => { if (!values[key]) delete values[key]; }); await ownerRequest(`${OwnerAdminSquad.endpoints.squads}/${encodeURIComponent(id)}`, OwnerAdminApi.json("PATCH", values)); ownerSetNotice(shell, "Squad member updated (audit: owner_squad_member_update)."); await draw(); }));
  await draw();
}

async function renderOwnerCommunity(shell) {
  let search = "", cursor = ""; const cursors = [];
  const draw = async () => {
    const query = new URLSearchParams({ limit: "25" }); if (search) query.set("search", search); if (cursor) query.set("cursor", cursor);
    const data = await ownerRequest(`${OwnerAdminSquad.endpoints.community}?${query}`);
    const old = shell.content.querySelector(".owner-admin__records"); if (old) old.remove();
    const records = ownerElement("section", "owner-admin__records");
    records.append(ownerRows(data.accounts, ["id", "ign", "gameId", "serverId", "email", "role", "status"], (account, cell) => cell.append(ownerActionButton(shell, account.status === "Disabled" ? "Activate" : "Disable", async () => {
      await ownerRequest(`${OwnerAdminSquad.endpoints.community}/${encodeURIComponent(account.id)}`, OwnerAdminApi.json("PATCH", { status: account.status === "Disabled" ? "Active" : "Disabled" })); await draw();
    }, { confirmText: account.status === "Disabled" ? "" : `Disable ${account.ign}? Their active sessions will be revoked.` }))));
    const pager = ownerElement("div", "owner-admin__pager"); const previous = ownerActionButton(shell, "Previous", async () => { cursor = cursors.pop() || ""; await draw(); }); previous.disabled = !cursors.length;
    const next = ownerActionButton(shell, "Next", async () => { if (!data.nextCursor) return; cursors.push(cursor); cursor = data.nextCursor; await draw(); }); next.disabled = !data.nextCursor; pager.append(previous, next); records.append(pager); shell.content.append(records);
  };
  shell.content.append(ownerQueryForm((value) => { search = value; cursor = ""; cursors.length = 0; draw().catch((e) => ownerSetNotice(shell, e.message, true)); }), ownerForm("Edit Community profile", [
    { name: "accountId", label: "Account ID" }, { name: "ign", label: "IGN", required: false }, { name: "gameId", label: "Game ID", required: false }, { name: "serverId", label: "Server ID", required: false }, { name: "email", label: "Email", type: "email", required: false }, { name: "phone", label: "Phone", required: false }, { name: "lane", label: "Lane", required: false }, { name: "status", label: "Status", required: false },
  ], "Save Community profile", async (values) => { const id = values.accountId; delete values.accountId; Object.keys(values).forEach((key) => { if (!values[key]) delete values[key]; }); await ownerRequest(`${OwnerAdminSquad.endpoints.community}/${encodeURIComponent(id)}`, OwnerAdminApi.json("PATCH", values)); ownerSetNotice(shell, "Community account updated (audit: owner_community_account_update)."); await draw(); })); await draw();
}

async function renderOwnerContent(shell) {
  const domain = ownerElement("select", "owner-admin__input"); domain.id = "owner-content-domain";
  for (const name of OwnerAdminSquad.contentDomains()) { const option = ownerElement("option", "", ownerLabel(name)); option.value = name; domain.append(option); }
  const label = ownerElement("label", "owner-admin__field-label", "Content type"); label.htmlFor = domain.id;
  function fieldsForDomain() {
    if (domain.value === "events") return [{ name: "title", label: "Title" }, { name: "date", label: "Date", type: "date" }, { name: "time", label: "Time", type: "time", required: false }, { name: "description", label: "Description", required: false }, { name: "rules", label: "Rules", required: false }];
    if (domain.value === "notifications") return [{ name: "title", label: "Title" }, { name: "message", label: "Message" }, { name: "audienceType", label: "Audience type", value: "squad" }, { name: "audienceId", label: "Audience ID", required: false }];
    if (domain.value === "complaints") return [{ name: "subject", label: "Subject", required: false }, { name: "body", label: "Complaint" }];
    return [{ name: "title", label: "Title", required: domain.value === "announcements" }, { name: "body", label: "Body" }];
  }
  function rebuildForms() {
    const old = shell.content.querySelector(".owner-admin__content-forms"); if (old) old.remove();
    const forms = ownerElement("div", "owner-admin__content-forms");
    const create = ownerForm(`Create ${ownerLabel(domain.value)}`, fieldsForDomain(), "Save content", async (values, form) => {
      await ownerRequest(`${OwnerAdminSquad.endpoints.content}/${domain.value}`, OwnerAdminApi.json("POST", values)); form.reset(); ownerSetNotice(shell, `Content saved (audit: owner_squad_content_create / ${domain.value}).`); await draw();
    });
    const editFields = [{ name: "itemId", label: "Content ID" }, ...fieldsForDomain().map((field) => ({ ...field, required: false }))];
    const edit = ownerForm(`Edit ${ownerLabel(domain.value)}`, editFields, "Update content", async (values) => {
      const id = values.itemId; delete values.itemId; Object.keys(values).forEach((key) => { if (!values[key]) delete values[key]; });
      await ownerRequest(`${OwnerAdminSquad.endpoints.content}/${domain.value}/${encodeURIComponent(id)}`, OwnerAdminApi.json("PATCH", values)); ownerSetNotice(shell, `Content updated (audit: owner_squad_content_update / ${domain.value}).`); await draw();
    });
    forms.append(create, edit); shell.content.append(forms);
  }
  const draw = async () => {
    const data = await ownerRequest(`${OwnerAdminSquad.endpoints.content}?domain=${encodeURIComponent(domain.value)}`);
    const old = shell.content.querySelector(".owner-admin__records"); if (old) old.remove();
    const records = ownerElement("section", "owner-admin__records");
    records.append(ownerRows(data.items, ["id", "title", "subject", "date", "status", "audienceType", "createdAt"], (item, cell) => cell.append(ownerActionButton(shell, "Delete", async () => {
      await ownerRequest(`${OwnerAdminSquad.endpoints.content}/${domain.value}/${encodeURIComponent(item.id)}`, { method: "DELETE" }); await draw();
    }, { confirmText: "Delete this content item?" })))); shell.content.append(records);
  };
  domain.value = "announcements";
  domain.addEventListener("change", () => { rebuildForms(); draw().catch((e) => ownerSetNotice(shell, e.message, true)); });
  shell.content.append(label, domain); rebuildForms(); await draw();
}

async function renderOwnerTournaments(shell) {
  const showDetail = async (id) => {
    const data = await ownerRequest(`${OwnerAdminTournaments.endpoint}/${encodeURIComponent(id)}`);
    const old = shell.content.querySelector(".owner-admin__tournament-detail"); if (old) old.remove();
    const detail = ownerElement("section", "owner-admin__card owner-admin__tournament-detail");
    detail.append(ownerElement("h2", "owner-admin__section-title", `Tournament detail: ${id}`), ownerRows([data.tournament || {}], ["id", "title", "status", "format", "registrationDeadline"]));
    const registrationActions = (item, cell) => {
      const status = String(item.status || "").toLowerCase();
      const actions = status === "approved" ? ["withdraw"] : (status === "withdrawn" || status === "rejected") ? ["reinstate"] : ["approve", "reject", "withdraw"];
      for (const action of actions) cell.append(ownerActionButton(shell, ownerLabel(action), async () => { await ownerRequest(OwnerAdminTournaments.registrationDecisionPath(id, item.id), OwnerAdminApi.json("POST", { action })); await showDetail(id); }, { confirmText: ["reject", "withdraw"].includes(action) ? `${ownerLabel(action)} registration ${item.id}?` : "" }));
    };
    const bracket = data.bracket && !Array.isArray(data.bracket) ? data.bracket : null;
    if (bracket) detail.append(ownerRows([{ ready: bracket.ready, generatedAt: bracket.generatedAt }], ["ready", "generatedAt"]));
    const groups = [
      ["Registrations", data.registrations, ["id", "accountId", "status"], registrationActions],
      ["Squad approvals", data.approvals, ["id", "leaderAccountId", "status"], (item, cell) => cell.append(ownerActionButton(shell, "Approve", async () => { await ownerRequest(OwnerAdminTournaments.approvalDecisionPath(id, item.id), OwnerAdminApi.json("POST", { action: "approve" })); await showDetail(id); }), ownerActionButton(shell, "Reject", async () => { await ownerRequest(OwnerAdminTournaments.approvalDecisionPath(id, item.id), OwnerAdminApi.json("POST", { action: "reject" })); await showDetail(id); }, { confirmText: `Reject Squad approval ${item.id}?` }))],
      ["Bracket", Array.isArray(data.bracket) ? data.bracket : (bracket && Array.isArray(bracket.matches) ? bracket.matches : []), ["id", "round", "player1", "player2"]],
      ["Matches", data.matches || (data.tournament && data.tournament.matches), ["id", "round", "player1", "player2", "winner", "status"]],
      ["Result submissions", data.resultSubmissions, ["id", "matchId", "winner", "status"]],
      ["Disputes", data.disputes, ["id", "matchId", "status", "reason"]],
    ];
    for (const [title, rows, columns, actions] of groups) detail.append(ownerElement("h3", "owner-admin__section-title", title), ownerRows(rows, columns, actions));
    shell.content.append(detail);
  };
  const draw = async () => {
    const data = await ownerRequest(OwnerAdminTournaments.endpoint);
    const old = shell.content.querySelector(".owner-admin__records"); if (old) old.remove();
    const records = ownerElement("section", "owner-admin__records");
    records.append(ownerRows(data.tournaments, ["id", "title", "game", "format", "date", "status"], (item, cell) => {
      cell.append(ownerActionButton(shell, "View details", () => showDetail(item.id)));
      for (const action of OwnerAdminTournaments.transitions) cell.append(ownerActionButton(shell, ownerLabel(action), async () => {
        await ownerRequest(OwnerAdminTournaments.transitionPath(item.id, action), OwnerAdminApi.json("POST", {})); await draw(); await showDetail(item.id);
      }, { confirmText: OwnerAdminTournaments.needsConfirmation(action) ? `${ownerLabel(action)} ${item.title}?` : "" }));
    })); shell.content.append(records);
  };
  shell.content.append(ownerForm("Create tournament", [{ name: "title", label: "Title" }, { name: "game", label: "Game" }, { name: "format", label: "Format" }, { name: "date", label: "Date", type: "date" }, { name: "registrationDeadline", label: "Registration deadline", type: "date", required: false }], "Create tournament", async (values, form) => {
    await ownerRequest(OwnerAdminTournaments.endpoint, OwnerAdminApi.json("POST", values)); form.reset(); ownerSetNotice(shell, "Tournament created."); await draw();
  }), ownerForm("Edit tournament", [{ name: "tournamentId", label: "Tournament ID" }, { name: "title", label: "Title", required: false }, { name: "date", label: "Date", type: "date", required: false }, { name: "registrationDeadline", label: "Registration deadline", type: "date", required: false }], "Save tournament", async (values) => {
    const id = values.tournamentId; delete values.tournamentId; Object.keys(values).forEach((key) => { if (!values[key]) delete values[key]; });
    await ownerRequest(`${OwnerAdminTournaments.endpoint}/${encodeURIComponent(id)}`, OwnerAdminApi.json("PATCH", values)); await draw();
  }), ownerForm("Registration or Squad approval", [{ name: "tournamentId", label: "Tournament ID" }, { name: "recordId", label: "Registration / approval ID" }, { name: "recordType", label: "Type (registration or approval)", value: "registration" }, { name: "decision", label: "Decision (approve or reject)", value: "approve" }, { name: "reason", label: "Reason", required: false }], "Save decision", async (values) => {
    const path = values.recordType === "approval" ? OwnerAdminTournaments.approvalDecisionPath(values.tournamentId, values.recordId) : OwnerAdminTournaments.registrationDecisionPath(values.tournamentId, values.recordId);
    await ownerRequest(path, OwnerAdminApi.json("POST", { action: values.decision, decision: values.decision, reason: values.reason })); await draw();
  }), ownerForm("Create match", [{ name: "tournamentId", label: "Tournament ID" }, { name: "player1", label: "Player 1 account ID" }, { name: "player2", label: "Player 2 account ID" }, { name: "round", label: "Round", type: "number", value: "1" }, { name: "scheduledAt", label: "Scheduled time", required: false }], "Create match", async (values) => {
    const tournamentId = values.tournamentId; delete values.tournamentId; values.round = Number(values.round);
    await ownerRequest(OwnerAdminTournaments.matchPath(tournamentId), OwnerAdminApi.json("POST", values)); await draw();
  }), ownerForm("Update or delete match", [{ name: "tournamentId", label: "Tournament ID" }, { name: "matchId", label: "Match ID" }, { name: "action", label: "Action (update or delete)", value: "update" }, { name: "scheduledAt", label: "Scheduled time", required: false }, { name: "status", label: "Status", required: false }], "Apply match change", async (values) => {
    const { tournamentId, matchId, action } = values; const path = OwnerAdminTournaments.matchPath(tournamentId, matchId);
    if (action === "delete") { if (!confirm("Delete this match?")) return; await ownerRequest(path, { method: "DELETE" }); }
    else { const body = {}; if (values.scheduledAt) body.scheduledAt = values.scheduledAt; if (values.status) body.status = values.status; await ownerRequest(path, OwnerAdminApi.json("PATCH", body)); }
    await draw();
  }), ownerForm("Review match result", [{ name: "tournamentId", label: "Tournament ID" }, { name: "matchId", label: "Match ID" }, { name: "action", label: "Action (confirm, correct, resolve, or reject)", value: "confirm" }, { name: "winner", label: "Winner", required: false }, { name: "reason", label: "Reason", required: false }], "Review result", async (values) => {
    const { tournamentId, matchId, ...body } = values; await ownerRequest(OwnerAdminTournaments.resultPath(tournamentId, matchId), OwnerAdminApi.json("POST", body)); await draw();
  }), ownerForm("Tournament Manager permission", [{ name: "memberId", label: "Squad member ID" }, { name: "action", label: "Action (grant or revoke)", value: "grant" }], "Update permission", async (values) => {
    if (values.action === "revoke" && !confirm("Revoke Tournament Manager permission? Active sessions will be revoked.")) return;
    await ownerRequest(`/api/owner/tournament-managers/${encodeURIComponent(values.memberId)}`, OwnerAdminApi.json("POST", { action: values.action })); ownerSetNotice(shell, "Tournament Manager permission updated.");
  })); await draw();
}

async function renderOwnerSeasons(shell) {
  const draw = async () => {
    const data = await ownerRequest(OwnerAdminSeasons.endpoints.seasons);
    const old = shell.content.querySelector(".owner-admin__records"); if (old) old.remove();
    const records = ownerElement("section", "owner-admin__records");
    if (data.currentSeason) records.append(ownerElement("p", "owner-admin__notice", `Active season: ${ownerValue(data.currentSeason.name)}`), ownerButton("Complete season", async () => { if (!confirm("Complete the active season?")) return; await ownerRequest(`${OwnerAdminSeasons.endpoints.seasons}/${encodeURIComponent(data.currentSeason.id)}/complete`, OwnerAdminApi.json("POST", {})); await draw(); }, true));
    records.append(ownerElement("h2", "owner-admin__section-title", "Rankings"), ownerRows(data.leaderboard, ["rank", "ign", "accountId", "points"])); shell.content.append(records);
  };
  shell.content.append(ownerForm("Start season", [{ name: "name", label: "Season name" }, { name: "requestId", label: "Request ID", required: false }], "Start season", async (values, form) => { await ownerRequest(OwnerAdminSeasons.endpoints.seasons, OwnerAdminApi.json("POST", values)); form.reset(); await draw(); }), ownerForm("Correct ranking points", [{ name: "accountId", label: "Community account ID" }, { name: "points", label: "Points", type: "number" }, { name: "reason", label: "Correction reason" }], "Save correction", async (values) => { await ownerRequest(`${OwnerAdminSeasons.endpoints.points}/${encodeURIComponent(values.accountId)}`, OwnerAdminApi.json("PATCH", { points: Number(values.points), reason: values.reason })); await draw(); })); await draw();
}

async function renderOwnerHistory(shell) {
  const draw = async () => {
    const [events, history] = await Promise.all([ownerRequest(OwnerAdminSeasons.endpoints.events), ownerRequest(OwnerAdminSeasons.endpoints.history)]);
    const old = shell.content.querySelector(".owner-admin__records"); if (old) old.remove();
    const records = ownerElement("section", "owner-admin__records");
    records.append(ownerElement("h2", "owner-admin__section-title", "Events"), ownerRows(events.events, ["id", "title", "date", "time", "status", "rewardPoints"], (item, cell) => {
      for (const action of ["publish", "close", "archive"]) cell.append(ownerActionButton(shell, ownerLabel(action), async () => { await ownerRequest(`${OwnerAdminSeasons.endpoints.events}/${encodeURIComponent(item.id)}/${action}`, OwnerAdminApi.json("POST", {})); await draw(); }, { confirmText: action === "archive" ? "Archive this event?" : "" }));
    }), ownerElement("h2", "owner-admin__section-title", "Season history"), ownerRows(history.seasonHistory, ["id", "seasonId", "name", "completedAt"]), ownerElement("h2", "owner-admin__section-title", "Tournament history"), ownerRows(history.hallOfFame, ["id", "title", "champion", "runnerUp", "date"]), ownerElement("h2", "owner-admin__section-title", "Season Hall of Fame"), ownerRows(history.seasonHallOfFame, ["id", "seasonId", "seasonName", "ign", "points", "completedAt"])); shell.content.append(records);
  };
  shell.content.append(ownerForm("Create event", [{ name: "title", label: "Title" }, { name: "date", label: "Date", type: "date" }, { name: "time", label: "Time", type: "time" }, { name: "description", label: "Description" }, { name: "rules", label: "Rules" }, { name: "rewardPoints", label: "Reward points", type: "number" }], "Create event", async (values, form) => { values.rewardPoints = Number(values.rewardPoints); await ownerRequest(OwnerAdminSeasons.endpoints.events, OwnerAdminApi.json("POST", values)); form.reset(); ownerSetNotice(shell, "Event created (audit: owner_event_create)."); await draw(); }), ownerForm("Edit event", [{ name: "eventId", label: "Event ID" }, { name: "title", label: "Title", required: false }, { name: "date", label: "Date", type: "date", required: false }, { name: "time", label: "Time", type: "time", required: false }, { name: "description", label: "Description", required: false }, { name: "rules", label: "Rules", required: false }, { name: "rewardPoints", label: "Reward points", type: "number", required: false }], "Save event", async (values) => { const id = values.eventId; delete values.eventId; Object.keys(values).forEach((key) => { if (!values[key]) delete values[key]; }); if (values.rewardPoints !== undefined) values.rewardPoints = Number(values.rewardPoints); await ownerRequest(`${OwnerAdminSeasons.endpoints.events}/${encodeURIComponent(id)}`, OwnerAdminApi.json("PATCH", values)); ownerSetNotice(shell, "Event updated (audit: owner_event_update)."); await draw(); }), ownerForm("Record event participation", [{ name: "eventId", label: "Event ID" }, { name: "accountId", label: "Community account ID" }], "Award participation", async (values) => { await ownerRequest(`${OwnerAdminSeasons.endpoints.events}/${encodeURIComponent(values.eventId)}/participation`, OwnerAdminApi.json("POST", { accountId: values.accountId })); await draw(); }), ownerForm("Correct Hall of Fame", [{ name: "domain", label: "Domain (hall-of-fame or season-hall-of-fame)", value: "hall-of-fame" }, { name: "entryId", label: "Entry ID" }, { name: "field", label: "Field to correct", value: "champion" }, { name: "value", label: "Corrected value" }, { name: "reason", label: "Correction reason" }], "Save history correction", async (values) => {
    const body = { reason: values.reason, [values.field]: values.field === "points" ? Number(values.value) : values.value };
    await ownerRequest(OwnerAdminSeasons.historyCorrectionPath(values.domain, values.entryId), OwnerAdminApi.json("PATCH", body)); await draw();
  })); await draw();
}

async function renderOwnerAudit(shell) {
  let cursor = ""; const cursors = []; const filters = { action: "", actor: "", target: "", from: "", to: "", limit: 25 };
  const draw = async () => {
    const data = await ownerRequest(OwnerAdminAudit.query({ ...filters, cursor }));
    const old = shell.content.querySelector(".owner-admin__records"); if (old) old.remove();
    const records = ownerElement("section", "owner-admin__records");
    records.append(ownerRows(data.audit, ["actor_id", "actor_role", "action", "target_type", "target_id", "created_at", "details"]));
    const pager = ownerElement("div", "owner-admin__pager"); const previous = ownerActionButton(shell, "Previous", async () => { cursor = cursors.pop() || ""; await draw(); }); previous.disabled = !cursors.length; const next = ownerActionButton(shell, "Next", async () => { if (!data.nextCursor) return; cursors.push(cursor); cursor = data.nextCursor; await draw(); }); next.disabled = !data.nextCursor; pager.append(previous, next); records.append(pager); shell.content.append(records);
  };
  const filterForm = ownerForm("Filter audit records", [{ name: "action", label: "Action" , required: false }, { name: "actor", label: "Actor / role", required: false }, { name: "target", label: "Target", required: false }, { name: "from", label: "From", type: "date", required: false }, { name: "to", label: "To", type: "date", required: false }, { name: "limit", label: "Rows per page", type: "number", value: "25" }], "Apply audit filters", async (values) => { Object.assign(filters, values, { limit: Number(values.limit) || 25 }); cursor = ""; cursors.length = 0; await draw(); });
  shell.content.append(filterForm); await draw();
}

async function renderOwnerSettings(shell) {
  const data = await ownerRequest("/api/owner/settings");
  shell.content.append(ownerRows([data.settings || data.owner || data.account || data], ["username", "createdAt", "sessionTtlSeconds", "recoveryCodeTtlSeconds"]), ownerForm("Change Owner password", [{ name: "currentPassword", label: "Current password", type: "password", secret: true }, { name: "newPassword", label: "New password", type: "password", secret: true }, { name: "passwordConfirmation", label: "Confirm new password", type: "password", secret: true }], "Update password", async (values) => {
    if (values.newPassword !== values.passwordConfirmation) throw new Error("New password confirmation must match.");
    await ownerRequest("/api/owner/settings", OwnerAdminApi.json("PATCH", { currentPassword: values.currentPassword, newPassword: values.newPassword, revokeOtherSessions: true })); ownerSetNotice(shell, "Owner password updated and other sessions revoked.");
  }));
}

async function openOwnerSection(sectionName) {
  ownerActiveSection = sectionName;
  document.querySelectorAll(".owner-admin__nav-button").forEach((button) => { button.setAttribute("aria-current", button.getAttribute("data-section") === sectionName ? "page" : "false"); });
  const region = document.getElementById("ownerWorkspace"); if (!region) return;
  const definition = OWNER_SECTIONS.find(([key]) => key === sectionName) || OWNER_SECTIONS[0];
  const shell = ownerSectionShell(definition[1], `Manage ${definition[1].toLowerCase()} for Dark System.`);
  region.replaceChildren(shell.section); region.setAttribute("aria-busy", "true");
  try {
    if (sectionName === "overview") { ownerOverviewData = await ownerRequest("/api/owner/overview"); renderOwnerOverviewSection(shell, ownerOverviewData); }
    else if (sectionName === "squads") await renderOwnerSquads(shell);
    else if (sectionName === "community") await renderOwnerCommunity(shell);
    else if (sectionName === "content") await renderOwnerContent(shell);
    else if (sectionName === "tournaments") await renderOwnerTournaments(shell);
    else if (sectionName === "seasons") await renderOwnerSeasons(shell);
    else if (sectionName === "history") await renderOwnerHistory(shell);
    else if (sectionName === "audit") await renderOwnerAudit(shell);
    else if (sectionName === "settings") await renderOwnerSettings(shell);
  } catch (error) { ownerSetNotice(shell, error.message, true); }
  finally { region.setAttribute("aria-busy", "false"); const heading = shell.section.querySelector("h1"); if (heading) { heading.tabIndex = -1; heading.focus(); } }
}

// This later declaration intentionally upgrades the original foundation renderer.
function renderOwnerDashboard(data) {
  ownerOverviewData = data;
  const app = ownerElement("section", "owner-admin__application owner-admin__dashboard");
  const top = ownerElement("header", "owner-admin__dashboard-header");
  const title = ownerElement("div"); title.append(ownerElement("p", "owner-admin__eyebrow", "OVERALL OWNER"), ownerElement("h1", "owner-admin__title", "Administration"));
  top.append(title, ownerButton("Logout", ownerLogout, true));
  const logoutError = ownerElement("p", "owner-admin__error-banner owner-admin__logout-error"); logoutError.hidden = true; logoutError.setAttribute("role", "alert");
  const layout = ownerElement("div", "owner-admin__layout"); const nav = ownerElement("nav", "owner-admin__nav"); nav.setAttribute("aria-label", "Owner administration");
  for (const [key, label] of OWNER_SECTIONS) { const button = ownerButton(label, () => openOwnerSection(key), true); button.classList.add("owner-admin__nav-button"); button.setAttribute("data-section", key); nav.append(button); }
  const workspace = ownerElement("main", "owner-admin__workspace"); workspace.id = "ownerWorkspace"; workspace.setAttribute("aria-live", "polite");
  layout.append(nav, workspace); app.append(top, logoutError, layout); setOwnerRoot(app);
  const firstButton = nav.querySelector(".owner-admin__nav-button"); if (firstButton) firstButton.setAttribute("aria-current", "page");
  const shell = ownerSectionShell("Overview", "Current operational state for Dark System.");
  workspace.replaceChildren(shell.section); renderOwnerOverviewSection(shell, data); workspace.setAttribute("aria-busy", "false");
}

function ownerLogout() {
  if (activeOwnerLogoutRequest) return activeOwnerLogoutRequest;
  const request = (async () => {
    const logoutButton = document.querySelector(".owner-admin__dashboard .owner-admin__button--secondary");
    const logoutError = document.querySelector(".owner-admin__dashboard .owner-admin__logout-error");
    if (logoutError) setOwnerError(logoutError, "");
    if (logoutButton) setOwnerBusy(logoutButton, true, "Logout");
    try {
      await ownerApi("/api/logout", { method: "POST" });
      activeOwnerSession = null;
      renderOwnerLogin("You have been logged out.");
      return true;
    } catch (requestError) {
      if (logoutError) setOwnerError(logoutError, requestError.message);
      return false;
    } finally {
      if (activeOwnerSession && logoutButton) setOwnerBusy(logoutButton, false, "Logout");
    }
  })();
  activeOwnerLogoutRequest = request;
  const clearRequest = () => {
    if (activeOwnerLogoutRequest === request) activeOwnerLogoutRequest = null;
  };
  request.then(clearRequest, clearRequest);
  return request;
}

async function loadOwnerEntry() {
  ownerRoot.setAttribute("aria-busy", "true");
  try {
    const setup = await ownerApi("/api/owner/setup/status");
    if (!setup.setupComplete) {
      renderOwnerSetup();
      return;
    }
    const account = await ownerApi("/api/auth/me");
    if (account.authenticated && account.session && account.session.role === "Overall Owner") {
      activeOwnerSession = account.session;
      const overview = await ownerApi("/api/owner/overview");
      renderOwnerDashboard(overview);
      return;
    }
    activeOwnerSession = null;
    renderOwnerLogin();
  } catch (requestError) {
    activeOwnerSession = null;
    const failed = ownerElement("section", "owner-admin__auth-card owner-admin__entry-error");
    failed.append(ownerElement("h1", "owner-admin__title", "Owner workspace unavailable"));
    appendOwnerError(failed, requestError.message);
    const retry = ownerElement("button", "owner-admin__button", "Try again");
    retry.type = "button";
    retry.addEventListener("click", loadOwnerEntry);
    failed.append(retry);
    setOwnerRoot(failed);
  }
}

loadOwnerEntry();
