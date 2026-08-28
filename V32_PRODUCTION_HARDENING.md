# V32 Production Hardening

- Production/demo data separation: `DARK_SYSTEM_DEMO_DATA=0` by default.
- Demo Squad Owner credentials are no longer seeded in a normal production start.
- Runtime SQLite database is excluded from the release package.
- Backup source files are excluded from the release package.
- Real Owner/Squad Owner credentials are still created only through the one-time Owner Setup.
- Existing UI/design and backend compatibility behavior are preserved.

## Development
Set `DARK_SYSTEM_DEMO_DATA=1` only when a disposable demo environment is desired.

## Production
Set a long random `DARK_SYSTEM_SESSION_SECRET`, keep `DARK_SYSTEM_DEMO_DATA=0`, configure SMTP if password-reset email is required, and run Owner Setup once on the production database.
