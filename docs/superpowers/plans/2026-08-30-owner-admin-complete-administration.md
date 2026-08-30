# Complete Overall Owner Administration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the private `/owner-admin` application from its secure foundation into the complete system-wide Squad, Community, Tournament, Season, History, Audit, Settings, and recovery administration application defined by the approved design.

**Architecture:** Add narrowly scoped `/api/owner/*` read and mutation endpoints backed by the existing SQLite/PostgreSQL compatibility layer, reusing existing domain rules only where they already enforce Overall Owner authorization. Split the Owner frontend into focused JavaScript modules loaded by the existing private shell, while leaving the public, Community, and Squad interfaces unchanged.

**Tech Stack:** Python 3.12 standard-library HTTP backend, FastAPI Vercel adapter, SQLite/PostgreSQL compatibility layer, vanilla HTML/CSS/JavaScript, Python `unittest`, Node test runner.

**Spec:** `docs/superpowers/specs/2026-08-29-owner-admin-design.md`

## Global Constraints

- Preserve the existing public, Community, and Squad Portal UI and behavior.
- Keep Owner access private at `/owner-admin`; add no public navigation link.
- Require a live `Overall Owner` session for every Owner read and mutation endpoint.
- Attribute every material action to the authenticated Overall Owner and exclude all secrets from API responses and audit details.
- Never permit public registration to grant `Overall Owner`, `Squad Owner`, or `Tournament Manager` authority.
- Use dedicated validated mutations rather than arbitrary `/api/state` synchronization.
- Preserve SQLite test compatibility and Vercel/Supabase PostgreSQL compatibility.
- Preserve the established fonts and sharp-edged button styling.
- Follow test-driven development: add an observable failing behavior test, confirm the expected failure, implement minimally, then run the focused and full suites.

---

### Task 1: Privilege and Owner API Security Boundary

**Files:**
- Modify: `server.py`
- Modify: `tests/test_owner_security.py`
- Create: `tests/test_owner_admin_api.py`

**Interfaces:**
- Produces: `require_overall_owner(handler) -> dict | None`
- Produces: safe Owner collection serialization helpers for Squad members and Community accounts.
- Changes: Community registration always creates an unprivileged Community identity regardless of submitted `role`.
- Changes: public `/api/bootstrap` returns only the minimum public projection and no Community contact data or privileged tournament administration state.
- Consumes: existing revocable session authentication and `insert_audit()`.

- [ ] Write failing integration tests proving a caller cannot self-register as Tournament Manager or another privileged role; public bootstrap excludes contact and privileged administration data; every new `/api/owner/*` collection endpoint rejects unauthenticated, Community, Squad, and Tournament Manager sessions; serialized responses exclude password hashes, access codes, recovery codes, and session tokens.
- [ ] Run `python -m unittest tests.test_owner_security tests.test_owner_admin_api -v` and confirm failures are caused by the missing boundary and unsafe role acceptance.
- [ ] Add one shared `require_overall_owner()` guard, force Community registration to its allowed default role, and add secret-excluding serializers used by all later Owner APIs.
- [ ] Run the focused tests and `python -m unittest discover -s tests -v`; confirm they pass.
- [ ] Commit as `fix: enforce owner administration security boundary`.

### Task 2: Squad and Community Account Administration APIs

**Files:**
- Modify: `server.py`
- Modify: `tests/test_owner_admin_api.py`

**Interfaces:**
- Produces: `GET /api/owner/squad-members` with search, role, status, limit, and cursor parameters.
- Produces: `POST /api/owner/squad-members`, `PATCH /api/owner/squad-members/:id`, and `DELETE /api/owner/squad-members/:id`.
- Produces: `GET /api/owner/community-accounts` and `PATCH /api/owner/community-accounts/:id` for safe profile/status administration.
- Produces: `POST /api/owner/squad-owner` for atomic appointment or replacement.
- Consumes: Task 1 authorization and serializers.

- [ ] Write failing integration tests for paginated/searchable safe lists, member creation/edit/disable/delete, valid role transitions, atomic Squad Owner replacement, Community profile/status updates, conflict responses, and audit attribution.
- [ ] Run the new tests and confirm `404` or missing-behavior failures.
- [ ] Implement validated dedicated endpoints; never return a submitted member access code, preserve unique IGN/Game ID/Server ID constraints, prevent deletion of protected Owner identities, maintain exactly one active Squad Owner, and revoke active sessions immediately when an account is disabled, deleted, or loses an authority-bearing role.
- [ ] Run focused tests and the complete backend suite.
- [ ] Commit as `feat: add owner squad and community administration`.

### Task 3: Squad Content and Notification Administration APIs

**Files:**
- Modify: `server.py`
- Modify: `tests/test_owner_admin_api.py`

**Interfaces:**
- Produces: `GET /api/owner/squad-content?domain=<announcements|reports|complaints|events|notifications>`.
- Produces: `POST`, `PATCH`, and `DELETE /api/owner/squad-content/:domain/:id` with domain-specific validation.
- Produces: server-created notification records for material Owner role, member, tournament, and season actions.
- Consumes: existing `notifications` table, state compatibility helpers, and Task 1 authorization.

- [ ] Write failing tests for each allowed content domain, invalid-domain rejection, content CRUD, server-generated notifications, cross-device persistence, and audit records without secret values.
- [ ] Run focused tests and verify expected missing-route failures.
- [ ] Implement explicit domain allowlists, safe payload normalization, persistent notification generation, and mutations that commit their material audit record in the same database transaction.
- [ ] Run focused and full suites.
- [ ] Commit as `feat: add owner squad content administration`.

### Task 4: Complete Owner Tournament Administration APIs

**Files:**
- Modify: `server.py`
- Modify: `tests/test_owner_admin_api.py`

**Interfaces:**
- Produces: `GET /api/owner/tournaments/:id?` returning tournaments with registrations, approvals, bracket, matches, result submissions, and disputes.
- Produces: dedicated Owner routes for create/edit/cancel/reinstate, registration decisions, bracket generation, match changes, result confirmation/correction/dispute resolution, completion/archive, and Tournament Manager grant/revoke.
- Consumes: existing tournament transition rules and Task 1 authorization.

- [ ] Write failing lifecycle tests covering creation through completion, cancellation/reinstatement rules, registration/withdrawal/approval decisions, bracket and match management, result confirmation/correction, disputes, Manager grant/revoke, invalid transitions, notifications, and audit attribution.
- [ ] Run the lifecycle tests and verify failures are due to absent Owner routes or incomplete transitions.
- [ ] Extract validated shared domain functions from existing handlers where necessary, then expose dedicated Owner endpoints without weakening Community, Squad, or Tournament Manager permissions; commit each material state change and its sanitized audit record atomically.
- [ ] Run the focused lifecycle and complete backend suites.
- [ ] Commit as `feat: add complete owner tournament administration`.

### Task 5: Server-Authoritative Seasons, Rankings, Events, and History

**Files:**
- Modify: `server.py`
- Modify: `tests/test_owner_admin_api.py`

**Interfaces:**
- Produces: `GET /api/owner/seasons`, `POST /api/owner/seasons`, `POST /api/owner/seasons/:id/complete`, and `PATCH /api/owner/season-points/:accountId`.
- Produces: `GET /api/owner/history` and audited Hall of Fame correction endpoints.
- Produces: Owner event create/edit/publish/close/archive and participation-administration endpoints.
- Consumes: existing `currentSeason`, `seasonPoints`, `seasonHistory`, `seasonHallOfFame`, `hallOfFame`, and `eventParticipation` state domains.

- [ ] Write failing tests for one active season at a time, atomic/idempotent completion, literal point corrections with mandatory reasons, derived leaderboard ordering, immutable history snapshots, Hall of Fame correction, event lifecycle, and duplicate-participation reward prevention.
- [ ] Run focused tests and confirm missing-behavior failures.
- [ ] Implement server-authoritative transactions and stable identifiers; ensure retries cannot duplicate points, history, awards, or notifications.
- [ ] Run focused and full suites.
- [ ] Commit as `feat: add owner season event and history administration`.

### Task 6: Audit Browser, Settings, and Self-Service Recovery APIs

**Files:**
- Modify: `server.py`
- Modify: `.env.example`
- Modify: `tests/test_owner_admin_api.py`
- Create: `tests/test_squad_recovery.py`

**Interfaces:**
- Changes: `GET /api/owner/audit` accepts safe action, actor, target, date, limit, and cursor filters.
- Produces: `GET/PATCH /api/owner/settings` for non-secret Owner security settings and account-password change requiring the current password.
- Produces: `POST /api/squad/forgot` and `POST /api/squad/reset` with generic responses, short-lived single-use codes, throttling, and immediate old-session/access-code invalidation.
- Consumes: configured SMTP delivery and existing Community recovery conventions.

- [ ] Write failing tests for audit pagination/filtering/secret exclusion, Owner current-password change, recovery enumeration resistance, exact identity matching, expired/reused code rejection, access-code rotation, session revocation, throttling, and audit safety.
- [ ] Run focused tests and confirm missing capability failures.
- [ ] Add minimal recovery persistence fields/tables using backward-compatible migrations, store recovery codes and Squad access codes as one-way hashes, migrate legacy access codes safely on successful authentication, implement safe SMTP delivery boundaries, and document required SMTP environment keys in `.env.example`.
- [ ] Run focused and full suites.
- [ ] Commit as `feat: add owner audit settings and squad recovery`.

### Task 7: Modular Owner Administration Interface

**Files:**
- Modify: `owner-admin.html`
- Modify: `owner-admin.css`
- Modify: `owner-admin.js`
- Create: `owner-admin-api.js`
- Create: `owner-admin-squad.js`
- Create: `owner-admin-tournaments.js`
- Create: `owner-admin-seasons.js`
- Create: `owner-admin-audit.js`
- Modify: `tests/test_owner_static_contract.py`
- Create: `tests/owner_admin_behavior.test.js`

**Interfaces:**
- Produces: authenticated navigation for Overview, Squads, Community, Content, Tournaments, Seasons & Rankings, Events & History, Audit, and Settings.
- Consumes: Tasks 2-6 dedicated Owner APIs through one same-origin `ownerApi()` client.

- [ ] Write failing DOM behavior tests for section navigation, loading/error/empty states, list filtering and pagination, every mutation form, confirmation for destructive actions, secret-field clearing, unauthorized-session return to login, accessible labels/focus, and dashboard refresh after success.
- [ ] Run `node --test tests/owner_admin_behavior.test.js` and the Python static-contract suite; confirm failures reflect missing sections and modules.
- [ ] Implement the focused modules and responsive private dashboard. Reuse existing type, color, spacing, and sharp button treatment; do not alter `index.html`, `style.css`, or `script.js` except where a proven shared bug requires a separately tested fix.
- [ ] Run Node syntax checks, behavior tests, Python static contracts, and the complete backend suite.
- [ ] Commit as `feat: add complete owner administration interface`.

### Task 8: End-to-End Regression and Deployment Acceptance

**Files:**
- Modify: `VERCEL_DEPLOYMENT.md`
- Modify: `tests/test_owner_postgres_integration.py`
- Modify: `tests/test_owner_admin_api.py`
- Modify: `tests/owner_admin_behavior.test.js`

**Interfaces:**
- Produces: a complete automated Owner lifecycle and a documented Vercel/Supabase production smoke checklist.
- Consumes: all interfaces from Tasks 1-7.

- [ ] Add one end-to-end backend scenario that logs in as Overall Owner, administers Squad and Community identities, manages content and a tournament, completes a season, inspects history/audit, changes settings, and logs out; assert every protected endpoint rejects the copied revoked cookie.
- [ ] Extend the opt-in PostgreSQL gate to exercise representative CRUD and transaction paths from every Owner domain against a marked disposable database.
- [ ] Run the complete Python and Node suites, Python compilation checks, JavaScript syntax checks, and `git diff --check`.
- [ ] Update `VERCEL_DEPLOYMENT.md` with environment keys, migration/backup steps, `/owner-admin` section-by-section smoke tests, authorization checks, recovery email checks, and Vercel runtime-log inspection.
- [ ] Commit as `test: verify complete owner administration` and stop before push or deployment for final whole-branch review.

## Verification Gate

```powershell
python -m unittest discover -s tests -v
node --test tests/frontend_logout_behavior.test.js tests/owner_admin_behavior.test.js
python -B -c "from pathlib import Path; compile(Path('server.py').read_text(encoding='utf-8'),'server.py','exec'); compile(Path('api/index.py').read_text(encoding='utf-8'),'api/index.py','exec')"
node --check script.js
node --check owner-admin.js
node --check owner-admin-api.js
node --check owner-admin-squad.js
node --check owner-admin-tournaments.js
node --check owner-admin-seasons.js
node --check owner-admin-audit.js
git diff --check
```

The optional PostgreSQL command remains gated by the repository's disposable-database marker and must never target the production Supabase database.
