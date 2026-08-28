# Dark System V19 Frontend / Backend Boundary Audit

## 1. Existing boundary before V20

The V19 prototype was almost entirely browser-side.

### Squad domain

- `db` was loaded from `localStorage` under `darkSystemV4`.
- Members, announcements, reports, complaints, events, notifications and report configuration were persisted in the browser.
- Squad authentication compared IGN, Game ID, Server ID and access code directly against browser data.
- The access code was therefore present in the client-side application state.
- Presence updates and logout status changes were also browser-only.

### Community domain

- `communityDb` was loaded from `localStorage` under `darkSystemCommunityV1`.
- Community accounts, tournaments, registrations, tournament managers, notifications, season points/history, Hall of Fame data and Squad-vs-Squad approvals were browser-owned.
- Community passwords were stored as plaintext in browser state.
- Password-reset codes were generated and stored in browser state.
- Email delivery was only a client-side call to an optional endpoint.

### Tournament domain

Tournament creation, registration, brackets, result submissions, disputes, approvals, points and completion were all implemented in the frontend JavaScript.

## 2. V20 backend boundary

The backend now owns:

- SQLite persistence.
- Community account creation.
- Community password hashing.
- Community login sessions.
- Password reset code storage and expiry.
- Squad authentication.
- Mandatory Squad profile persistence.
- Server-side session cookies.
- Central storage for the existing application collections.

The frontend remains responsible for:

- Rendering.
- Navigation.
- Existing modal flow.
- Existing tournament UI and business-flow presentation.
- Local fallback behavior when opened without a backend.

## 3. Security improvements introduced

- Community passwords are no longer stored in the database as plaintext.
- Password reset codes are stored server-side and expire after 10 minutes.
- Session state uses an HttpOnly signed cookie.
- Bootstrap responses omit Community password hashes/reset secrets.
- Public bootstrap responses omit Squad access codes.
- Leadership-only authenticated bootstrap can receive the existing access-code field because the current management UI requires displaying/generating those codes.
- State sync never accepts a browser password hash or reset code.

## 4. Remaining backend work

The largest remaining boundary is tournament authorization.

The frontend currently performs many operations locally and then sends the resulting state snapshot to `/api/state`. V20 therefore centralizes persistence but does not yet make every tournament decision server-authoritative.

The next phase should introduce dedicated endpoints for:

1. Member creation/edit/removal.
2. Announcement creation/edit/removal.
3. Community profile updates.
4. Tournament creation/edit/cancel/reinstate.
5. Tournament registration.
6. Squad-vs-Squad approval.
7. Match-result submission/confirmation/dispute.
8. Tournament manager assignment.
9. Season points and Hall of Fame updates.
10. Notifications.
11. Reports and complaints.

Each endpoint should enforce the role rules on the server and use SQLite transactions where multiple records must change together.

## 5. Design constraint preserved

No visual redesign was introduced by the backend migration. The V19 HTML/CSS artwork integration remains the presentation layer. The backend work is additive and keeps the existing Community ↔ Squad portal model, including the requirement that **Log Out remains separate from Switch to Squad/Community**.

## 6. V21 Phase-2 server-authoritative API layer

V21 adds dedicated, role-checked endpoints for the highest-risk write paths:

- Squad member create/edit/remove.
- Tournament create/edit/cancel/reinstate.
- Tournament registration/withdrawal/approval.

These endpoints validate the authenticated session and role on the server before mutating SQLite. The legacy `/api/state` route remains for backward compatibility with the existing UI and will be retired incrementally as each frontend action is migrated to its dedicated endpoint.

## 7. Remaining migration work

The next frontend integration pass should replace the legacy state snapshot writes for announcements, reports and complaints, tournament managers, match results/disputes, season points/history/Hall of Fame, notifications, and community profile changes. After that migration, `/api/state` can be disabled for production.
