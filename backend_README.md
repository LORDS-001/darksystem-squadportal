# Dark System V19 Backend

This backend adds a real SQLite persistence layer and server-side authentication while keeping the existing V19 frontend and visual design intact.

## Start

```bash
python3 server.py
```

Then open `http://127.0.0.1:8080`.

The server creates `dark_system.sqlite3` on first run.

## Main API

- `GET /api/health`
- `GET /api/bootstrap`
- `GET /api/auth/me`
- `POST /api/squad/login`
- `PUT /api/squad/profile`
- `POST /api/community/register`
- `POST /api/community/login`
- `POST /api/community/forgot`
- `POST /api/community/reset`
- `POST /api/logout`
- `PUT /api/state`

## Security boundary

Passwords and reset codes are stored server-side using PBKDF2-SHA256. The browser state-sync endpoint deliberately does not accept or overwrite password hashes or Squad access-code secrets.

The existing UI remains responsible for presentation and interaction. The server now owns persistence, authentication and password recovery. The next hardening phase should move tournament authorization and every individual write operation into dedicated server-side endpoints rather than accepting a complete UI state snapshot.
