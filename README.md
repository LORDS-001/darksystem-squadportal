# Dark System — V35 Vercel + Supabase

This is the production-prepared Dark System website/backend package for a Vercel + Supabase deployment.

- Frontend design preserved.
- Existing Python business logic preserved in `server.py`.
- Vercel entrypoint: `api/index.py`.
- PostgreSQL: Supabase via `DATABASE_URL`.
- Production demo data disabled by default.
- Do not create real Owner credentials until the deployed smoke test passes.

See `VERCEL_DEPLOYMENT.md` for deployment steps.
