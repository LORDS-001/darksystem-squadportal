# Dark System — Vercel + Supabase deployment

## Before deployment

Do not enter your real Owner password into the source code or GitHub.

### Supabase
Create a Free project, then copy the PostgreSQL connection string from the project's database connection settings. Keep it private.

### GitHub
Create a private repository and upload the contents of this project.

### Vercel
Import the GitHub repository as a new project. Vercel should detect the Python function in `api/index.py`.

Add these Environment Variables for **Production**:

- `DATABASE_URL` = your Supabase PostgreSQL connection string (Secret)
- `DARK_SYSTEM_SESSION_SECRET` = a long random secret (Secret)
- `OWNER_SETUP_SECRET` = a separate long random secret used only for the one-time Owner setup (Secret)
- `DARK_SYSTEM_DEMO_DATA` = `0`

Keep `OWNER_SETUP_SECRET` private and separate from the Owner password and session secret. Vercel Production deployments refuse Owner setup when it is missing. Enter it only in the private one-time Owner setup form; after setup locks, rotate or remove it from the Production environment.

Password recovery is self-service. Configure these for Production before testing
recovery (all credentials are Secrets; `SMTP_PORT` and `SMTP_TLS` are Config):

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_FROM`
- `SMTP_TLS`

Use `SMTP_TLS=1` for STARTTLS (the default). The application does not require a
separate recovery secret: reset codes are generated randomly, stored only as
hashes, expire after ten minutes, and are single-use. Never configure
`DARK_SYSTEM_ALLOW_DEFAULT_SECRET` in Vercel; it is a local-development escape
hatch. Apply the same variable set deliberately to Preview if Preview is part of
the release gate. Do not expose any server secret with a `NEXT_PUBLIC_` or other
client-visible prefix.

Deploy and test:

- `/api/health`
- `/api/owner/setup/status`
- `/`

The normal website should load from the same Vercel domain, and the API remains same-origin.

### Owner foundation smoke test

Use the production release gate below before creating real credentials. The abbreviated post-deployment check is:

1. Verify `/api/health`.
2. Verify `/api/owner/setup/status`.
3. Open `/owner-admin` and confirm it is absent from public navigation.
4. On a fresh database, enter the configured `OWNER_SETUP_SECRET`, complete setup once, and confirm a repeat is rejected.
5. Log in, verify overview counts, log out, and confirm browser Back cannot reopen protected data.
6. Confirm `/api/owner/overview` returns `401` after logout.
7. Inspect Vercel logs for uncaught exceptions and confirm none occurred during the smoke test.

### Database backup and migration

Take a Supabase backup before deploying a commit that changes persistence. On a
paid project, confirm the latest managed backup is restorable; otherwise use
`pg_dump` from a trusted machine against the direct connection and store the
encrypted dump outside the repository. Record the commit and backup timestamp,
not the connection URL. Test restoration into a separate disposable project at
least once before relying on the procedure.

Schema initialization and compatible column/index additions run during backend
startup. Deploy to Preview against a disposable database first, open
`/api/health`, and inspect runtime logs until initialization completes. Compare
the expected tables/indexes in Supabase, run the automated release gate, then
promote the same tested commit. Do not point Preview at Production, manually
edit application rows during migration, or delete the pre-deployment backup.
Rollback means restoring the prior tested commit; if persistence changed
incompatibly, restore the verified backup into a new project and change
`DATABASE_URL` rather than experimenting on Production.

### Complete `/owner-admin` smoke checklist

Use synthetic records and a dedicated Preview/disposable database first. The
private route must remain absent from the public navigation. Sign in as Overall
Owner and verify each dashboard section:

1. **Overview:** health, totals, pending work, recent activity, refresh, loading,
   empty, and controlled-error states render without revealing secrets.
2. **Squads:** search/page members, create and edit a member, change role/status,
   appoint exactly one Squad Owner, and confirm disabling an account revokes its
   existing session. No access code or hash may appear in responses or logs.
3. **Community:** search/page accounts, edit identity/preferences, disable and
   restore a synthetic account, and confirm its session is revoked when disabled.
4. **Content:** create, edit, list, and delete an announcement, report,
   complaint, Squad event, and scoped notification. Confirm only the intended
   audience receives the notification and read state is per recipient.
5. **Tournaments:** create/edit a tournament, approve two synthetic
   registrations, generate a bracket, schedule a match, submit and confirm a
   result, complete/archive it, and separately test cancel/reinstate. Verify
   Squad approvals and Tournament Manager grant/revoke with synthetic accounts.
6. **Seasons & Rankings:** create one active season, apply a reasoned point
   correction, verify ordering/ranks, complete the season once, and confirm a
   retry creates no duplicate rewards or history.
7. **Events & History:** create/publish/close/archive an event, record one
   participant only once, inspect season and tournament Hall of Fame entries,
   and test a reasoned correction on disposable data.
8. **Audit:** filter and page by action/actor/target/date; verify the mutations
   above are present and payloads contain no password, access code, token,
   cookie, SMTP value, or connection string.
9. **Settings:** verify the safe settings view, change the Owner password using
   the current password, confirm other sessions are revoked, and confirm the
   current session remains valid until explicit Logout.
10. **Logout:** copy the current cookie before logout, log out, then verify
    `/api/auth/me` reports unauthenticated and every `/api/owner/*` section read
    returns `401` with that copied cookie. Browser Back must not restore data.

Run authorization checks for representative read and mutation routes while
anonymous and while signed in as Community Member, Squad Member/Leader/Owner,
and Tournament Manager. Expect `401` without a session and `403` for every
non-Overall-Owner session; the response must not contain administrative data.

For both Community and Squad recovery, request a code for a synthetic account,
confirm the email is delivered by the configured provider without the password
or existing access code, use it once, and confirm expiry, replay, and invalid
codes fail safely. Inspect provider delivery/bounce logs and Vercel runtime logs;
never paste a real reset code into tickets or deployment notes.

## Production release gate

Run this gate against either `vercel dev` or an already-created Preview deployment. This procedure does not authorize a deployment. Always use a fresh disposable Supabase/PostgreSQL project; never point the smoke test at Production data.

### Automated prerequisites

Run the local suites first:

```powershell
python -m unittest discover -s tests -v
node --test tests/frontend_logout_behavior.test.js tests/owner_admin_behavior.test.js
node --check script.js
node --check owner-admin.js
node --check owner-admin-api.js
node --check owner-admin-squad.js
node --check owner-admin-tournaments.js
node --check owner-admin-seasons.js
node --check owner-admin-audit.js
python -B -c "from pathlib import Path; compile(Path('server.py').read_text(encoding='utf-8'),'server.py','exec'); compile(Path('api/index.py').read_text(encoding='utf-8'),'api/index.py','exec')"
git diff --check
```

The PostgreSQL Owner gate is opt-in and never reads `DATABASE_URL` as a fallback. It creates a randomly named schema; exercises representative Squad, Community, content, tournament, season/ranking, event/history, audit, settings, session-revocation, and durable-throttle CRUD/transaction paths; and drops that schema in cleanup. The concurrency check removes the in-process lock only inside the isolated test, synchronizes two independent database transactions immediately before the conditional setup claim, and verifies that a deliberately non-atomic test mutation would allow two winners. Production locking is not changed. Use a dedicated disposable database, not merely a spare schema in a Production project:

Before the first run, manually create this marker **only after independently verifying that the connected database is disposable**. Generate a unique value with `python -c "import secrets; print(secrets.token_urlsafe(32))"`; do not reuse a Production secret or commit the generated value. In a SQL client connected directly to the disposable database, replace the placeholder with that generated value and run once:

```sql
CREATE TABLE public.dark_system_disposable_test_marker (
  marker_name text PRIMARY KEY,
  confirmation text NOT NULL CHECK (length(confirmation) >= 32)
);
INSERT INTO public.dark_system_disposable_test_marker(marker_name, confirmation)
VALUES ('dark-system-owner-release-gate-v1', '<generated-random-confirmation>');
```

The automated gate never creates, updates, or drops this public marker. It opens every database connection with `default_transaction_read_only=on`, performs only a parameterized marker `SELECT`, compares the returned value in constant time, and enables writes on that same connection only after an exact match. Thus aliases, CNAMEs, DNS rebinding, and static identity gaps cannot authorize mutation unless the resolved database already carries the out-of-band disposable marker.

```powershell
'PGHOST','PGHOSTADDR','PGPORT','PGDATABASE','PGSERVICE','PGSERVICEFILE','PGTARGETSESSIONATTRS','PGLOADBALANCEHOSTS','PGSYSCONFDIR','PGUSER' | ForEach-Object { Remove-Item "Env:$_" -ErrorAction SilentlyContinue }
$env:TEST_DATABASE_URL = '<disposable Supabase/PostgreSQL connection URL>'
$env:TEST_DATABASE_CONFIRMATION = '<same-generated-random-confirmation>'
python -m unittest tests.test_owner_postgres_integration -v
Remove-Item Env:TEST_DATABASE_URL
Remove-Item Env:TEST_DATABASE_CONFIRMATION
```

`TEST_DATABASE_URL` and `TEST_DATABASE_CONFIRMATION` are the only opt-in variables; both are required, the URL must contain an explicit database user, and the confirmation must be 32–128 URL-safe characters. `DATABASE_URL` alone never connects. Before running, unset `PGHOST`, `PGHOSTADDR`, `PGPORT`, `PGDATABASE`, `PGSERVICE`, `PGSERVICEFILE`, `PGTARGETSESSIONATTRS`, `PGLOADBALANCEHOSTS`, `PGSYSCONFDIR`, and `PGUSER`; the guard fails closed if any is present, including with an empty value. It uses psycopg conninfo normalization when that package is available and otherwise accepts only a strict, single-host PostgreSQL URI it can compare conservatively. Host names must be canonical IP literals or strict DNS names: decoded authority delimiters, IPv4-mapped IPv6, and legacy numeric IPv4 aliases such as `127.1`, integer, octal, hex, or mixed forms are rejected. It also refuses keyword DSNs, service/multi-host targets, URI query options that override authority or route host/port/database selection, an unparseable `DATABASE_URL`, and a test target resolving to the same host, port, and database name as `DATABASE_URL`.

For hosted Supabase, direct and dedicated-pooler hosts use `db.<20-character-project-ref>.supabase.co`, while shared pooler users use `<database-user>.<20-character-project-ref>` on `*.pooler.supabase.com`. The guard derives that project reference and treats direct, dedicated, session-pooler, and transaction-pooler URLs for the same project/database as one target despite different hosts or ports. Distinct project references remain valid on the same regional pooler. Ambiguous Supabase forms fail closed. This matches Supabase's [current connection-string formats](https://supabase.com/docs/guides/database/connecting-to-postgres).

The returned connection URI has explicit normalized host, port, database, and user components. Each authority component is re-encoded separately, IPv6 is bracketed, and encoded passwords plus allowed options such as `sslmode` are preserved without logging. All guard failures are generic and do not echo either URL, password, project reference, or ambient value. See PostgreSQL's [libpq environment-variable reference](https://www.postgresql.org/docs/current/libpq-envars.html) for the destination and routing defaults covered by the guard. Do not put connection URLs in source files, shell history shared with others, screenshots, tickets, or test output. With no `TEST_DATABASE_URL`, the integration class must report one safe skip.

Rotate the marker by generating a new value, manually updating only the disposable database row, and replacing `TEST_DATABASE_CONFIRMATION`; the old value then stops authorizing the gate. When retiring the disposable database, remove the row or drop `public.dark_system_disposable_test_marker` manually before deleting the database. Never perform marker creation, rotation, or removal through this test command, and never create the marker in Production.

### Native Vercel routing smoke

For local verification, configure only disposable credentials in the current shell, ensure a Production `.env` is not being reused, then start Vercel's local runtime from the repository root:

```powershell
$env:DATABASE_URL = '<disposable smoke-test database URL>'
$env:DARK_SYSTEM_SESSION_SECRET = '<temporary random smoke-test value>'
$env:OWNER_SETUP_SECRET = '<temporary separate smoke-test value>'
$env:DARK_SYSTEM_DEMO_DATA = '0'
vercel dev --listen 3000
```

`vercel dev` is the Vercel-supported local deployment emulator: <https://vercel.com/docs/cli/dev>. Keep its terminal visible for request and traceback inspection. In a second terminal, set `$Base = 'http://localhost:3000'`. For an existing Preview, set `$Base` to its HTTPS URL instead; do not run `vercel deploy` as part of this gate.

Verify native routes and the static allowlist:

```powershell
curl.exe -i "$Base/api/health"
curl.exe -i "$Base/api/owner/setup/status"
curl.exe -i "$Base/owner-admin"
curl.exe -i "$Base/owner-admin.js"
curl.exe -i "$Base/server.py"
curl.exe -i "$Base/tests/test_owner_foundation.py"
curl.exe -i "$Base/.env"
```

Expected results:

- health, setup status, `/owner-admin`, and its JavaScript asset return `200`;
- `/server.py`, `/tests/test_owner_foundation.py`, and `/.env` return `404` with no file content;
- `/owner-admin` remains absent from public navigation;
- the health payload exposes only the public service status/time fields.

### Setup-secret and Owner lifecycle smoke

Use a fresh disposable database. Before setup, `GET /api/owner/setup/status` must return `{"setupComplete":false}`. Send `POST /api/owner/setup` once with the setup secret omitted and once with a deliberately wrong value; both must return `403`, reveal no configured secret, and leave setup incomplete.

Then use `/owner-admin` to complete setup with the temporary configured secret and synthetic credentials. Confirm all of the following:

1. Setup succeeds once, status becomes `{"setupComplete":true}`, and a second setup attempt returns `409`.
2. Wrong Owner credentials return the same controlled `401` response; correct credentials open the protected overview.
3. Overview displays separate `Backend: healthy` and `Database: healthy` values, totals, pending work, and sanitized audit activity.
4. An unauthenticated request to `/api/owner/overview` returns `401` and no administrative data.
5. Successful Logout returns to the unchanged Owner Login view; browser Back does not restore protected content; `/api/auth/me` reports an unauthenticated session and `/api/owner/overview` returns `401`.

### Logout failure and retry smoke

Exercise this without changing the server by using the browser developer tools' request-blocking feature for `*/api/logout`:

1. Log in to Owner, enable the block, click Logout, and confirm the dashboard and in-memory authenticated view remain visible, the Logout button is restored, and a `role="alert"` retry message is shown.
2. Repeat from an authenticated Community account and an authenticated Squad account. Their current dashboards/state must remain visible and the existing escaped Dark System error modal must appear.
3. Disable the block and retry Logout in each portal. Each portal must then render exactly its normal logged-out view and the copied session must fail `/api/auth/me`.

This check covers a transport failure. A controlled `503` from `/api/logout` must follow the same client behavior.

### Log inspection and release decision

For local `vercel dev`, inspect the running terminal for each request. For an existing linked Preview, inspect the Vercel Dashboard Logs page or use the current CLI log filter:

```powershell
vercel logs --deployment <preview-deployment-id-or-url> --level error --since 1h
```

Vercel documents the current log flags at <https://vercel.com/docs/cli/logs>. Do not release if the smoke window contains an uncaught exception, secret/credential value, unexpected `5xx`, source-file disclosure, setup bypass, stale authenticated UI after successful logout, or logged-out UI after failed logout. Record the tested commit, Preview identifier (if used), database project marked disposable, command results, and reviewer; do not record credentials or connection URLs.

## Owner Setup

Do **not** create real Owner credentials until the deployed site passes the smoke/regression test. Then use the website's one-time Owner Setup screen. Setup locks after successful completion.
