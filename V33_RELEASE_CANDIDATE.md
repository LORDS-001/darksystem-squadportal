# Dark System V33 — Release Candidate

## Purpose
V33 is the release-candidate package after the production hardening and regression work completed through V32.

## Preserved product requirements
- Existing Dark System visual design and navigation.
- MLBB hero/background artwork and welcome/onboarding artwork.
- Community Portal and Squad Portal relationship.
- Switch to Squad and Log Out remain separate actions.
- Overall Owner, Squad Owner, Squad Leader, Assistant Leader, Squad Member, Community Member, and Tournament Manager roles.
- Community, Squad, Tournament, Season and Hall of Fame workflows.

## Production behavior
- `DARK_SYSTEM_DEMO_DATA=0` is the production default.
- No demo squad accounts are seeded unless `DARK_SYSTEM_DEMO_DATA=1` is explicitly enabled.
- A production database is created on first run and is not bundled in this release.
- Real Owner and Squad Owner credentials are created through the one-time Owner Setup flow.
- Do not use demo credentials in production.

## Validation completed
- Python syntax check: PASS
- JavaScript syntax check: PASS
- Fresh production database initialization: PASS
- No demo members with `DARK_SYSTEM_DEMO_DATA=0`: PASS
- Health endpoint: PASS
- Owner setup and setup lock: PASS
- Custom Owner login/session: PASS
- Legacy demo credentials rejected after setup: PASS
- Existing artwork/assets preserved: PASS
- Mobile viewport and responsive CSS presence: PASS

## Browser automation limitation
A full Chromium click-through could not be executed in the build environment because localhost browser navigation is blocked by the environment's administrator policy. HTTP endpoint tests and static/mobile checks were used instead.

## Launch checklist
1. Deploy the package to the production server.
2. Set a long random `DARK_SYSTEM_SESSION_SECRET`.
3. Keep `DARK_SYSTEM_DEMO_DATA=0`.
4. Configure HTTPS.
5. Configure SMTP if real password-reset email delivery is required.
6. Start the server and verify `/api/health`.
7. Complete Owner Setup once with your real credentials.
8. Back up the resulting production database securely.
