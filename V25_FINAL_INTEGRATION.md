# Dark System V25 — Final Integration Pass

## What changed

- Browser localStorage is no longer the authoritative store when the site is served through the backend. It is retained only for the static/file:// prototype fallback.
- Backend bootstrap is authoritative after Squad or Community authentication.
- Server state synchronization is now role-scoped for Community members: they can only synchronize their own registrations and notifications.
- Existing dedicated server endpoints remain in place for profiles, squad members, tournaments, matches, results and permissions.
- Authentication/session, rate limiting, same-origin checks, password hashing and Owner setup lock from V24 remain intact.
- Existing MLBB artwork and website UI are preserved.

## Compatibility note

`/api/state` remains as a controlled migration bridge for legacy UI mutations. It is no longer a general-purpose write surface: accepted domains are constrained by the authenticated role. The bridge should be removed only after every legacy UI mutation has been converted to its dedicated endpoint and the full workflow test passes.

## Verification performed

- Python syntax check: passed
- JavaScript syntax check: passed
- Backend health: passed
- Owner setup lock: passed
- Role-scoped state synchronization: code-verified
- Static asset preservation: passed
