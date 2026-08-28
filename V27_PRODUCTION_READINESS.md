# Dark System V27 — Production Readiness Pass

This release continues from V26 without redesigning the website.

## Migration completed in this pass

- Squad member creation now uses `/api/squad/members` when the backend is active.
- Squad member editing now uses `/api/squad/members` when the backend is active.
- Squad member deletion now uses `/api/squad/members` when the backend is active.
- Squad role changes now use `/api/squad/role` when the backend is active.
- LocalStorage remains only as the static/offline compatibility mode; the backend remains authoritative for these operations when served over HTTP.

## Preserved requirements

- Existing Community and Squad UI.
- MLBB hero artwork and image slots remain unchanged.
- New-member required onboarding/welcome experience remains unchanged.
- Switch to Squad and Log Out remain separate actions.
- Owner, Squad Owner, Leader, Assistant Leader, Squad Member, Community Member and Tournament Manager roles remain.
- Existing tournament, season, Hall of Fame, announcements, events, reports and complaints UI remains.

## Remaining controlled compatibility area

`/api/state` remains temporarily available for legacy UI state that has not yet been migrated to dedicated endpoints. It is role-restricted and sanitized. It should be removed only after the remaining community/tournament UI writes are individually migrated and regression-tested.

## Validation performed

- Python syntax check.
- JavaScript syntax check.
- Dedicated member CRUD code-path review.
- Dedicated role-change code-path review.
- Asset preservation check.
