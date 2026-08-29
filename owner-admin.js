"use strict";

const ownerRoot = document.getElementById("ownerRoot");
let activeOwnerSession = null;

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
  dashboard.append(header);

  const health = data && typeof data.health === "object" ? data.health : {};
  const healthCard = ownerElement("section", "owner-admin__health-card");
  const healthIndicator = ownerElement("p", "owner-admin__health-indicator", "Database: ");
  healthIndicator.append(ownerElement("span", "owner-admin__health-value", ownerValue(health.database)));
  healthCard.append(ownerElement("h2", "owner-admin__section-title", "System health"), healthIndicator);
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

async function ownerLogout() {
  const logoutButton = document.querySelector(".owner-admin__dashboard .owner-admin__button--secondary");
  if (logoutButton) setOwnerBusy(logoutButton, true, "Logout");
  let notice = "You have been logged out.";
  let logoutFailed = false;
  try {
    await ownerApi("/api/logout", { method: "POST" });
  } catch (requestError) {
    notice = requestError.message;
    logoutFailed = true;
  } finally {
    activeOwnerSession = null;
    renderOwnerLogin(notice, logoutFailed);
  }
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
