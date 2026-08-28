# Dark System V26 — Full Integration Test

## Test environment

- Fresh SQLite database created for testing
- Temporary development session secret
- Local HTTP server
- No production credentials used

## Results

- Backend health: PASS
- Owner setup: PASS
- Owner setup lock after first setup: PASS
- Overall Owner login: PASS
- Authenticated session: PASS
- Owner audit access: PASS
- Owner-created squad member: PASS
- Squad role change: PASS
- Owner-created tournament: PASS
- Logout clears the session: PASS
- Protected Owner endpoint after logout: PASS
- Old `OWNER / 000000` credentials rejected: PASS
- Community registration: PASS
- Community bootstrap: PASS
- Community tournament registration: PASS
- Community forbidden tournament creation: PASS
- Custom Squad Owner login: PASS
- Squad Owner bootstrap includes permitted access-code visibility: PASS
- Squad Leader member edit: PASS
- Squad Leader member delete rejected: PASS
- Squad Leader tournament creation rejected: PASS
- Unauthenticated member deletion rejected: PASS
- Python syntax check: PASS
- JavaScript syntax check: PASS

## Bugs found during integration testing

1. The logout route was sending `Set-Cookie` before the HTTP response status line, which caused malformed HTTP responses. It was changed to send the cookie-clear header through the normal JSON response path.
2. The server declared a DELETE route but did not implement `do_DELETE`, so DELETE requests could return an invalid/empty HTTP response. A proper DELETE handler was added.

Both issues were fixed and the complete integration suite was rerun successfully.

## Remaining production work

This test confirms the current backend integration and role boundaries. It does not replace final production deployment hardening, HTTPS configuration, real SMTP configuration, database backup configuration, or the user's final one-time Owner Setup.
