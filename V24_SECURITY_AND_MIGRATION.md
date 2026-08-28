# Dark System V24 — Security Hardening & Migration Integrity

V24 continues the existing V23 system without redesigning the UI.

## Completed
- Added same-origin validation for state-changing API requests.
- Removed wildcard CORS behavior from the OPTIONS handler.
- Added login/password-reset rate limiting.
- Production server now refuses the placeholder session secret unless explicitly overridden for development.
- Session cookies now use `SameSite=Strict` and become `Secure` when served over HTTPS.
- Community registration/reset password minimum raised to 8 characters; existing accounts are not forcibly changed.
- Browser localStorage snapshots are scrubbed of password/reset secrets before persistence.
- Added a frontend backend-integrity check helper for the final migration/testing stage.

## Preservation rule
The `/api/state` compatibility bridge remains intentionally available during migration. It must not be removed until every legacy frontend write has a tested dedicated API replacement.

## Next final stage
1. Replace remaining legacy state writes with dedicated endpoints.
2. Verify Community/Squad/Tournament flows end-to-end.
3. Run role abuse tests (each role attempting another role's operations).
4. Remove `/api/state` after the migration passes.
5. Production configuration and one-time Owner Setup.
