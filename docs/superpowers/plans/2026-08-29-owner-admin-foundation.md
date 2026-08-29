# Overall Owner Admin Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a private `/owner-admin` application with one-time setup, Overall Owner login, revocable database sessions, a system overview, and logout.

**Architecture:** Add a dedicated Owner HTML/CSS/JavaScript frontend that calls narrowly scoped Owner APIs. Replace stateless signed-cookie authentication with opaque tokens whose SHA-256 hashes are stored in the existing `sessions` table, allowing logout and expiry to be enforced server-side for every account type.

**Tech Stack:** Python 3.12 standard library HTTP backend, FastAPI Vercel adapter, SQLite/PostgreSQL compatibility layer, vanilla HTML/CSS/JavaScript, Python `unittest`, Node syntax validation.

**Spec:** `docs/superpowers/specs/2026-08-29-owner-admin-design.md`

## Global Constraints

- Preserve the existing public, Community, and Squad Portal UI and behavior.
- Serve the Owner application only at `/owner-admin` and `/owner-admin/`; add no public navigation link.
- Mark the Owner page `noindex,nofollow`.
- Keep all authorization server-side and attribute Owner actions to `Overall Owner`.
- Never return password hashes, access codes, recovery codes, or session tokens in JSON.
- Use only dependencies already declared in `pyproject.toml`.
- Keep Vercel/Supabase PostgreSQL compatibility and local SQLite compatibility.

---

### Task 1: Backend Integration Test Harness

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/http_harness.py`
- Create: `tests/test_owner_foundation.py`

**Interfaces:**
- Produces: `BackendHarness.request(method: str, path: str, payload: dict | None = None, cookie: str = "") -> BackendResponse`
- Produces: `BackendResponse(status: int, headers: dict[str, str], json: dict | None, body: bytes)`
- Consumes: `server.Handler`, `server.init_db()`, and a temporary SQLite `server.DB_PATH`.

- [ ] **Step 1: Create the failing setup-status integration test**

```python
# tests/test_owner_foundation.py
import unittest
from tests.http_harness import BackendHarness

class OwnerFoundationTests(unittest.TestCase):
    def setUp(self):
        self.backend = BackendHarness()

    def tearDown(self):
        self.backend.close()

    def test_fresh_database_reports_owner_setup_incomplete(self):
        response = self.backend.request("GET", "/api/owner/setup/status")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.json, {"setupComplete": False})
```

- [ ] **Step 2: Run the test to verify the harness is missing**

Run: `python -m unittest tests.test_owner_foundation -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'tests.http_harness'`.

- [ ] **Step 3: Implement the in-memory HTTP harness**

`BackendHarness` must:

- create a unique database path with `tempfile.TemporaryDirectory()`;
- save and replace `server.DB_PATH`, `server.DATABASE_URL`, and `server.SESSION_SECRET`;
- set `DATABASE_URL` to an empty string and `SESSION_SECRET` to `test-owner-session-secret`;
- call `server.init_db()`;
- construct `server.Handler` with `io.BytesIO` request/response streams;
- provide `Host: test.local`, `Origin: https://test.local`, and `X-Forwarded-Proto: https`;
- JSON-encode payloads and capture status/headers/body;
- parse JSON responses when the content type is JSON;
- restore globals and remove the temporary directory in `close()`.

Use this response type:

```python
from dataclasses import dataclass

@dataclass
class BackendResponse:
    status: int
    headers: dict[str, str]
    json: dict | None
    body: bytes
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `python -m unittest tests.test_owner_foundation -v`

Expected: 1 test passes.

- [ ] **Step 5: Commit the harness**

```powershell
git add tests/__init__.py tests/http_harness.py tests/test_owner_foundation.py
git commit -m "test: add backend integration harness"
```

---

### Task 2: Revocable Database Sessions

**Files:**
- Modify: `server.py:109-126`
- Modify: `server.py:223-255`
- Modify: `server.py:310-312`
- Modify: `server.py:384-390`
- Modify: `server.py:437-451`
- Modify: `server.py:537-549`
- Test: `tests/test_owner_foundation.py`

**Interfaces:**
- Produces: `create_session(user_type: str, user_id: str, role: str) -> str`
- Produces: `session_token_hash(token: str) -> str`
- Produces: `revoke_session(handler) -> None`
- Changes: `auth_from_cookie(handler) -> dict | None` now verifies the database record and expiry.
- Consumes: existing `sessions(token, type, user_id, role, expires)` table; `token` stores a SHA-256 hash, never the raw cookie token.

- [ ] **Step 1: Add failing tests for persistence and revocation**

Add tests that:

1. Complete Owner Setup.
2. Log in and extract `dark_system_session` from `Set-Cookie`.
3. Confirm `/api/auth/me` returns an authenticated Overall Owner.
4. POST `/api/logout` with the cookie.
5. Confirm the same copied cookie now receives `authenticated: false`.
6. Create an already-expired row directly and confirm it is rejected and deleted.

Use assertions:

```python
self.assertTrue(me.json["authenticated"])
self.assertEqual(me.json["session"]["role"], "Overall Owner")
self.assertEqual(after_logout.json, {"authenticated": False, "session": None})
```

- [ ] **Step 2: Run the tests to prove stateless logout fails**

Run: `python -m unittest tests.test_owner_foundation.OwnerFoundationTests.test_owner_session_is_revoked_on_logout -v`

Expected: FAIL because the copied signed cookie remains valid after logout.

- [ ] **Step 3: Implement opaque session storage**

Replace `make_session()` usage with:

```python
def session_token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()

def create_session(user_type, user_id, role="Community Member"):
    token = secrets.token_urlsafe(32)
    expires = int(time.time()) + SESSION_TTL
    with LOCK, db() as c:
        c.execute(
            "INSERT INTO sessions(token,type,user_id,role,expires) VALUES(?,?,?,?,?)",
            (session_token_hash(token), user_type, str(user_id), role, expires),
        )
        c.execute("DELETE FROM sessions WHERE expires<?", (int(time.time()),))
        c.commit()
    return token
```

Update `auth_from_cookie()` to hash the raw cookie value, select the session row, reject/delete expired rows, and return:

```python
{"type": row["type"], "id": str(row["user_id"]), "role": row["role"], "exp": int(row["expires"])}
```

Implement `revoke_session(handler)` to delete the hashed cookie token. Change Owner, Community, and Squad login to call `create_session()`. Change `/api/logout` to call `revoke_session(self)` before returning the expired cookie.

- [ ] **Step 4: Verify all session tests**

Run: `python -m unittest tests.test_owner_foundation -v`

Expected: setup-status, Owner login, authentication, expiry, and copied-cookie logout tests all pass.

- [ ] **Step 5: Commit session revocation**

```powershell
git add server.py tests/test_owner_foundation.py
git commit -m "feat: add revocable database sessions"
```

---

### Task 3: Owner Overview API

**Files:**
- Modify: `server.py:301-313`
- Modify: `server.py:355-399`
- Test: `tests/test_owner_foundation.py`

**Interfaces:**
- Produces: `GET /api/owner/overview`
- Response: `{health, counts, pending, recentAudit}` where no item contains credentials.
- Consumes: the authenticated Overall Owner session from Task 2.

- [ ] **Step 1: Write authorization and response-contract tests**

Tests must verify:

- unauthenticated request returns `401`;
- Community and Squad sessions return `401` or `403`;
- Overall Owner receives `200`;
- `counts` contains `communityMembers`, `squadMembers`, `activeTournaments`, and `completedTournaments`;
- `pending` contains `registrations`, `squadApprovals`, and `results`;
- serialized response does not contain `password`, `access_code`, `reset_code`, or `token`.

- [ ] **Step 2: Run the overview tests and confirm 404**

Run: `python -m unittest tests.test_owner_foundation.OwnerFoundationTests.test_owner_overview_requires_owner -v`

Expected: FAIL because `/api/owner/overview` does not exist.

- [ ] **Step 3: Implement `owner_overview()`**

Add the route:

```python
if path == '/api/owner/overview' and method == 'GET':
    return self.owner_overview()
```

`owner_overview()` must call `require_auth(self, ['owner'])`, require role `Overall Owner`, count database records, load tournament/registration/approval state, count matches with pending/disputed submissions, and return at most ten recent audit rows. Parse audit `details` JSON before returning it, but exclude secrets.

- [ ] **Step 4: Run the complete backend suite**

Run: `python -m unittest discover -s tests -v`

Expected: all tests pass.

- [ ] **Step 5: Commit the Owner overview API**

```powershell
git add server.py tests/test_owner_foundation.py
git commit -m "feat: add owner system overview API"
```

---

### Task 4: Private Owner Route and Static Shell

**Files:**
- Create: `owner-admin.html`
- Create: `owner-admin.css`
- Modify: `server.py:959-976`
- Test: `tests/test_owner_foundation.py`

**Interfaces:**
- Produces: `GET /owner-admin` and `GET /owner-admin/`, both returning `owner-admin.html`.
- Produces DOM elements: `#ownerRoot`, `#ownerStatus`, and an initial loading state.
- Consumes: existing `style.css`; later consumed by `owner-admin.js` in Task 5.

- [ ] **Step 1: Add failing route and static-security tests**

Verify both routes return `200`, `text/html`, and a body containing:

```html
<meta name="robots" content="noindex,nofollow">
<div id="ownerRoot"
```

Also assert `index.html` contains no `/owner-admin` string.

- [ ] **Step 2: Run route tests and confirm 404**

Run: `python -m unittest tests.test_owner_foundation.OwnerFoundationTests.test_owner_admin_private_route -v`

Expected: FAIL with status `404`.

- [ ] **Step 3: Add explicit static routing**

At the beginning of `static_or_404()` map:

```python
if path in ('/owner-admin', '/owner-admin/'):
    rel = 'owner-admin.html'
else:
    rel = 'index.html' if path == '/' else path.lstrip('/')
```

Keep the existing resolved-path containment check.

- [ ] **Step 4: Create the isolated Owner shell**

`owner-admin.html` must include UTF-8/viewport metadata, `noindex,nofollow`, `style.css`, `owner-admin.css`, a Dark System Owner header, an accessible loading status in `#ownerStatus`, `#ownerRoot`, and a deferred `owner-admin.js` script. Do not copy public navigation.

`owner-admin.css` must scope every new rule under `.owner-admin` and provide responsive authentication cards, dashboard header, metrics grid, recent activity list, loading state, and error banner using existing color variables/classes where available.

- [ ] **Step 5: Verify routing and unchanged public entry**

Run: `python -m unittest discover -s tests -v`

Expected: all tests pass, including absence of an Owner link from `index.html`.

Run: `node --check script.js`

Expected: exit code 0.

- [ ] **Step 6: Commit the Owner route and shell**

```powershell
git add server.py owner-admin.html owner-admin.css tests/test_owner_foundation.py
git commit -m "feat: add private owner admin route"
```

---

### Task 5: Setup, Login, Overview, and Logout UI

**Files:**
- Create: `owner-admin.js`
- Modify: `owner-admin.html`
- Modify: `owner-admin.css`
- Create: `tests/test_owner_static_contract.py`

**Interfaces:**
- Consumes: `GET /api/owner/setup/status`, `POST /api/owner/setup`, `POST /api/owner/login`, `GET /api/auth/me`, `GET /api/owner/overview`, and `POST /api/logout`.
- Produces: `ownerApi(path, options)`, `renderOwnerSetup()`, `renderOwnerLogin()`, `renderOwnerDashboard(data)`, `loadOwnerEntry()`, and `ownerLogout()`.

- [ ] **Step 1: Write failing static contract tests**

Read `owner-admin.html` and `owner-admin.js` and assert:

- the Owner JS file is referenced with `defer`;
- every required endpoint string appears in `owner-admin.js`;
- setup inputs include username, password, password confirmation, Squad Owner IGN, Game ID, Server ID, and access code;
- login uses username/password fields with correct autocomplete values;
- rendered dashboard includes Overview, Recent Activity, and Logout;
- neither file contains `localStorage` or `sessionStorage`;
- the JS source does not log response bodies or secrets.

- [ ] **Step 2: Run static tests and confirm failure**

Run: `python -m unittest tests.test_owner_static_contract -v`

Expected: FAIL because `owner-admin.js` does not exist.

- [ ] **Step 3: Implement the Owner API client and state machine**

`ownerApi()` uses same-origin `fetch`, `credentials: 'same-origin'`, JSON request/response handling, and throws only the safe backend `error` message.

`loadOwnerEntry()` follows this exact order:

1. GET `/api/owner/setup/status`.
2. If incomplete, call `renderOwnerSetup()`.
3. If complete, GET `/api/auth/me`.
4. If the session is an Overall Owner, load `/api/owner/overview` and render the dashboard.
5. Otherwise render Owner Login.

Setup validates matching passwords client-side, posts the approved payload shape, clears secret fields, and transitions to login. Login clears the password field regardless of success. Logout awaits `/api/logout`, clears in-memory state, and renders login.

- [ ] **Step 4: Render the foundation dashboard**

Render metric cards for all values returned by `/api/owner/overview`, a recent activity list, a system/database healthy indicator, and a Logout button. Do not render controls belonging to later plans.

Use text-node-safe escaping for every server value and disable submit buttons while requests are active. Display safe inline errors and restore the button after failure.

- [ ] **Step 5: Run frontend and backend verification**

Run: `python -m unittest discover -s tests -v`

Expected: all backend and static contract tests pass.

Run: `node --check owner-admin.js`

Expected: exit code 0.

Run: `node --check script.js`

Expected: exit code 0, confirming the existing public application was untouched syntactically.

- [ ] **Step 6: Commit the Owner foundation UI**

```powershell
git add owner-admin.html owner-admin.css owner-admin.js tests/test_owner_static_contract.py
git commit -m "feat: add owner setup and overview interface"
```

---

### Task 6: Foundation Regression and Deployment Verification

**Files:**
- Modify: `VERCEL_DEPLOYMENT.md`
- Test: `tests/test_owner_foundation.py`
- Test: `tests/test_owner_static_contract.py`

**Interfaces:**
- Consumes: all foundation interfaces from Tasks 1-5.
- Produces: a documented deployment smoke sequence and final evidence for the foundation increment.

- [ ] **Step 1: Add a complete lifecycle regression test**

One test must execute:

```text
fresh status -> setup -> repeated setup rejected -> login -> overview -> logout -> copied cookie rejected
```

Assert status codes `200, 200, 409, 200, 200, 200, 401/unauthenticated` and verify one `owner_setup`, one `owner_login`, and one `owner_logout` audit record.

- [ ] **Step 2: Run the lifecycle test**

Run: `python -m unittest tests.test_owner_foundation.OwnerFoundationTests.test_complete_owner_foundation_lifecycle -v`

Expected: PASS.

- [ ] **Step 3: Document the deployment smoke test**

Add these steps to `VERCEL_DEPLOYMENT.md`:

1. Verify `/api/health`.
2. Verify `/api/owner/setup/status`.
3. Open `/owner-admin` and confirm it is absent from public navigation.
4. On a fresh database, complete setup once and confirm a repeat is rejected.
5. Log in, verify overview counts, log out, and confirm browser Back cannot reopen protected data.
6. Confirm `/api/owner/overview` returns `401` after logout.
7. Inspect Vercel logs for uncaught exceptions and confirm none occurred during the smoke test.

- [ ] **Step 4: Run the full verification gate**

Run:

```powershell
python -m unittest discover -s tests -v
python -B -c "from pathlib import Path; compile(Path('server.py').read_text(encoding='utf-8'),'server.py','exec'); compile(Path('api/index.py').read_text(encoding='utf-8'),'api/index.py','exec')"
node --check script.js
node --check owner-admin.js
git diff --check
```

Expected: all tests pass and every command exits 0.

- [ ] **Step 5: Commit documentation and regression coverage**

```powershell
git add VERCEL_DEPLOYMENT.md tests/test_owner_foundation.py tests/test_owner_static_contract.py
git commit -m "test: verify owner admin foundation lifecycle"
```

- [ ] **Step 6: Stop for review before deployment**

Review the complete diff against `docs/superpowers/specs/2026-08-29-owner-admin-design.md`. Do not push or redeploy until the Owner foundation implementation and test evidence are approved.
