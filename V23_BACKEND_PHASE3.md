# Dark System V23 — Server-authoritative Community, Squad Content & Tournament Operations

V23 continues V22 without changing the visual design. It adds dedicated server endpoints for the next set of business operations so the frontend can migrate away from whole-state writes safely.

## Added server endpoints

- `PUT /api/community/profile` — authenticated Community Member profile/settings updates.
- `POST /api/community/notifications/read` — marks a permitted Community notification as read.
- `POST/PUT /api/squad/content` — leadership-controlled announcements, events, reports and complaints.
- `DELETE /api/squad/content` — Owner-only deletion of squad content.
- `POST /api/tournaments/match` — Tournament Manager match creation/update.
- `POST /api/tournaments/result` — Tournament Manager result submission.
- `POST /api/tournaments/complete` — Tournament Manager result confirmation/completion.

## Security

Every endpoint requires a valid server-side session and role checks. Passwords and access codes are never accepted through the legacy whole-state sync as secrets. Existing compatibility sync remains temporarily so the current UI is not disrupted during migration.

## Validation performed

- Python syntax compilation passed.
- Fresh SQLite initialization passed.
- Owner setup passed and locks after first completion.
- Overall Owner login passed.
- Authenticated member creation passed.
- Tournament match creation passed.
- Existing MLBB assets and frontend files preserved.
