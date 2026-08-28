# Dark System V29 — Final Workflow Migration

This pass moves the remaining high-risk browser-only writes for Squad-vs-Squad approvals, tournament result review, tournament completion/points/Hall of Fame, and Community event participation behind authenticated server endpoints.

The existing visual UI is preserved. The legacy `/api/state` compatibility bridge remains only for workflows not yet migrated, so no existing feature is intentionally broken.

Validated:
- Python syntax
- JavaScript syntax
- Server-authoritative Squad-vs-Squad leader submission/approval/rejection
- Server-authoritative tournament result approval/rejection
- Server-side tournament points and Hall of Fame update on approved completion
- Server-authoritative Community event participation
