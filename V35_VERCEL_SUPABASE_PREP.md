# V35 — Vercel + Supabase preparation

Dark System is prepared to deploy as one Vercel project with the existing Python backend exposed through a FastAPI adapter and Supabase providing PostgreSQL.

## Architecture

- Vercel: website + Python API
- Supabase: PostgreSQL database
- `DATABASE_URL`: Supabase connection string supplied to Vercel as a secret environment variable
- `DARK_SYSTEM_SESSION_SECRET`: strong random production secret supplied to Vercel as a secret
- `DARK_SYSTEM_DEMO_DATA=0`: production demo data disabled

The existing `server.py` business logic is retained. `api/index.py` adapts Vercel requests to the existing handler so the established UI and API behavior are preserved.

## Important free-tier note

Supabase Free currently includes a 500 MB database quota and pauses projects after one week of inactivity; it does not include automatic backups. Vercel's Python runtime is currently in beta and supports FastAPI deployments. These limits make the free setup appropriate for testing/early use, not a guarantee of unlimited permanent free production hosting.

## Deployment outline

1. Create a Supabase Free project.
2. Obtain its PostgreSQL connection string from the database connection settings.
3. Put the project in a GitHub repository.
4. Import that repository into Vercel.
5. Add `DATABASE_URL` and `DARK_SYSTEM_SESSION_SECRET` as encrypted Vercel environment variables.
6. Set `DARK_SYSTEM_DEMO_DATA` to `0`.
7. Deploy.
8. Check `/api/health` and `/api/owner/setup/status`.
9. Only after deployment testing passes, perform the one-time real Owner Setup.
