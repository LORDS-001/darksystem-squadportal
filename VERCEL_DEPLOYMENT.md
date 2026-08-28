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
- `DARK_SYSTEM_DEMO_DATA` = `0`

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

## Owner Setup

Do **not** create real Owner credentials until the deployed site passes the smoke/regression test. Then use the website's one-time Owner Setup screen. Setup locks after successful completion.
