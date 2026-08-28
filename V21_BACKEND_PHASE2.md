# Dark System V21 — Backend Phase 2

V21 keeps the existing V19 visual interface unchanged and strengthens the server boundary.

## Added server-authoritative endpoints

- `POST /api/squad/members`
- `PUT /api/squad/members`
- `DELETE /api/squad/members`
- `POST /api/tournaments`
- `PUT /api/tournaments`
- `POST /api/tournaments/cancel`
- `POST /api/tournaments/reinstate`
- `POST /api/tournaments/register`
- `POST /api/tournaments/withdraw`
- `POST /api/tournaments/approve`

All require a valid server session. Owner-only operations are enforced by the backend, not merely hidden in the UI.

## Compatibility

The existing frontend still uses `/api/state` for some legacy actions. This is intentional for this migration step so the current UI continues working. Dedicated endpoints will be wired into those UI actions before `/api/state` is retired.

## Production setup still required

1. Replace the bootstrap/demo Owner credentials.
2. Set a strong `DARK_SYSTEM_SESSION_SECRET` in `.env`.
3. Configure SMTP if password recovery/email notifications are required.
4. Run end-to-end authorization tests for every role.
5. Put the server behind HTTPS/reverse proxy and restrict origins.
6. Back up SQLite or move to PostgreSQL if traffic grows substantially.
