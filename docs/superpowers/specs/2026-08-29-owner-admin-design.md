# Dark System Overall Owner Administration Design

## Purpose

Add a private Overall Owner application at `/owner-admin` without changing the existing public, Community, or Squad Portal interfaces. The Owner application provides system-wide Squad and Tournament administration while preserving backend-enforced authorization and audit attribution.

## Architecture

The Owner interface is isolated from the existing public application:

```text
/owner-admin
    -> owner-admin.html
    -> owner-admin.js
    -> authenticated /api/owner/* and existing administration APIs
    -> Supabase PostgreSQL
```

The page reuses `style.css` so it remains visually consistent with Dark System, but it does not add Owner links to public navigation. It includes `noindex` metadata. The private URL is only a discoverability measure; authentication and backend authorization provide security.

The Overall Owner remains authenticated as `Overall Owner` for every operation and never impersonates the Squad Owner. Audit records therefore identify the actual actor.

## Entry and Authentication Flow

On load, the Owner application requests `/api/owner/setup/status`.

- If setup is incomplete, it displays a one-time form for an Overall Owner username and password plus the initial Squad Owner IGN, Game ID, Server ID, and Squad access code.
- A successful `/api/owner/setup` request creates both identities and permanently locks setup.
- If setup is complete, only the Overall Owner login form is displayed.
- A successful `/api/owner/login` request creates an authenticated Owner session and opens the dashboard.
- Logout invalidates the server-side Owner session, clears the cookie, and returns to Owner Login.

Administrative data is never returned to an unauthenticated visitor.

## Dashboard

### Overview

Display backend and database health, Community and Squad member totals, active and completed tournament totals, pending registrations/approvals/results, and recent audited activity.

### Squad Management

Allow the Overall Owner to create, edit, activate, disable, and remove Squad members; assign allowed Squad roles; and appoint or replace the Squad Owner. The last Overall Owner cannot be modified through Squad role controls.

### Squad Content

Provide direct management of announcements, reports, complaints, events, and Squad notifications.

### Tournament Administration

Provide tournament creation, editing, cancellation, reinstatement, registration decisions, bracket generation, match management, result and dispute review, completion, and Tournament Manager permission management.

### Community Administration

Display Community identities and account status required for administration. Password hashes, reset codes, session tokens, and private credentials are never returned. Contact information is only returned to an authorized administrator when needed.

### Seasons and History

Provide server-authoritative season state, points, season completion, tournament history, and Hall of Fame administration. Administrative corrections must be audited.

### Audit

Provide searchable, paginated access to administrative audit records: actor, role, action, target, timestamp, and non-secret details.

### System Settings

Provide Squad Owner appointment and Overall Owner account/security settings. Overall Owner cannot view or manually set other users' passwords or access codes.

## API and Authorization

All mutations use dedicated APIs rather than arbitrary browser-state synchronization through `/api/state`. Existing endpoints may be reused where they already enforce Overall Owner access; missing operations receive narrowly scoped endpoints.

Every Owner endpoint must:

- require a valid Overall Owner session;
- validate request fields and target records;
- enforce role and state-transition rules;
- avoid returning credentials or reset secrets;
- write an audit record for material actions;
- return controlled JSON errors while logging diagnostic details server-side.

Existing Squad and Tournament endpoints used by the dashboard must explicitly recognize `Overall Owner` without weakening their rules for other roles.

## Self-Service Recovery

The Overall Owner does not reset Community or Squad credentials.

Community recovery continues to use the registered email and a short-lived reset code.

Squad recovery uses this flow:

1. The member submits registered email, IGN, Game ID, and Server ID.
2. The backend verifies that all fields identify the same active Squad record.
3. A short-lived, single-use recovery code is sent to the registered email.
4. The member submits the code and a new Squad access code.
5. The old access code becomes invalid immediately.
6. The reset is audited without recording the recovery code or access code.

Recovery responses do not reveal whether an account exists. Login and recovery requests are rate-limited. Codes expire and are invalidated after successful use.

## Session Security

Owner sessions must be revocable server-side rather than relying only on a signed stateless cookie. Production cookies use `HttpOnly`, `Secure`, and `SameSite=Strict`. Logout revokes the session record before clearing the cookie. Session expiry is enforced by the backend.

## Error Handling

- Authentication failures return a generic unauthorized message.
- Permission failures return `403` without privileged data.
- Invalid state transitions return `409`.
- Validation errors return `400` with safe field-level guidance.
- Database outages return controlled `503` responses and retain diagnostic tracebacks in Vercel logs.
- Owner forms preserve non-secret input after recoverable errors and never preserve password or access-code fields.

## Testing

Automated backend tests cover:

- first setup succeeds exactly once and setup then locks;
- Owner login, logout, revocation, and expiry;
- unauthenticated and non-Owner rejection for every Owner operation;
- Squad Owner appointment and role boundaries;
- Squad member and content administration;
- Tournament creation through completion and dispute review;
- Tournament Manager permission changes;
- season and Hall of Fame administration;
- audit creation, attribution, pagination, and secret exclusion;
- Community and Squad recovery, including incorrect, expired, and reused codes;
- safe behavior during database failure.

Browser tests cover setup, login, every dashboard section, logout, desktop/mobile layouts, and regression checks for the existing public, Community, and Squad interfaces.

## Deployment and Acceptance

The change is accepted when:

- `/owner-admin` serves the dedicated noindex Owner application;
- no Owner link appears publicly;
- setup is available only before the first successful setup;
- authenticated Overall Owner can use all specified Squad and Tournament controls directly;
- actions remain attributed to Overall Owner;
- credential recovery is self-service;
- unauthorized requests cannot read or mutate administrative data;
- the existing public UI and logic remain visually unchanged;
- automated backend and browser checks pass against the Vercel/Supabase architecture.
