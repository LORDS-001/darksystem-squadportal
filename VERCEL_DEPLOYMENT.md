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

Optional password-reset email variables can be added later:

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_FROM`
- `SMTP_TLS`

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

## Production release gate

Run this gate against either `vercel dev` or an already-created Preview deployment. This procedure does not authorize a deployment. Always use a fresh disposable Supabase/PostgreSQL project; never point the smoke test at Production data.

### Automated prerequisites

Run the local suites first:

```powershell
python -m unittest discover -s tests -v
node --test tests/frontend_logout_behavior.test.js
node --check script.js
node --check owner-admin.js
python -m compileall -q server.py api tests
```

The PostgreSQL Owner gate is opt-in and never reads `DATABASE_URL` as a fallback. It creates a randomly named schema, runs the Owner lifecycle/concurrent setup/session revocation/audit/durable-throttle checks, and drops that schema in cleanup. The concurrency check removes the in-process lock only inside the isolated test, synchronizes two independent database transactions immediately before the conditional setup claim, and verifies that a deliberately non-atomic test mutation would allow two winners. Production locking is not changed. Use a dedicated disposable database, not merely a spare schema in a Production project:

```powershell
$env:TEST_DATABASE_URL = '<disposable Supabase/PostgreSQL connection URL>'
python -m unittest tests.test_owner_postgres_integration -v
Remove-Item Env:TEST_DATABASE_URL
```

`TEST_DATABASE_URL` is the only opt-in variable. The guard uses psycopg conninfo normalization when that package is available and otherwise accepts only a strict, single-host PostgreSQL URI it can compare conservatively. It refuses keyword DSNs, service/multi-host targets, URI query options that override host/hostaddr/port/database/service, an unparseable `DATABASE_URL`, and a test target resolving to the same host, port, and database name as `DATABASE_URL`, even when a different database user, host case, percent encoding, or omitted default port is supplied. All guard failures are generic and do not echo either URL. Do not put connection URLs in source files, shell history shared with others, screenshots, tickets, or test output. With no `TEST_DATABASE_URL`, the integration class must report one safe skip.

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
