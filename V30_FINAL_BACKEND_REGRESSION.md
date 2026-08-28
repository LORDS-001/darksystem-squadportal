# Dark System V30 — Final Backend Regression Pass

This version continues V29 without redesigning the website.

## Migration completed in this pass
- Server-authoritative tournament bracket generation.
- Server-authoritative player result submission.
- Server-authoritative opponent confirmation.
- Server-authoritative result disputes with participant checks.
- Server-authoritative Tournament Manager grant/revoke.
- Server-authoritative community notification "mark all read".
- Existing dedicated endpoints remain the source of truth for Squad member management, Community profiles, tournament registration, Squad-vs-Squad approvals, result review, and event participation.

## Security corrections
- A result can only be submitted by a participant in that match.
- A participant cannot confirm their own submitted result.
- A result cannot be confirmed after it is already confirmed/disputed.
- A completed/closed result cannot be opened for dispute.
- Tournament Manager changes remain Owner-only and eligible only for Squad Leaders/Assistant Leaders.

## Regression checks performed
- Python syntax check: PASS
- JavaScript syntax check: PASS
- Fresh database startup: PASS
- One-time Owner Setup: PASS
- Second Owner Setup attempt: correctly rejected
- Overall Owner login: PASS
- Tournament creation: PASS
- Community registration: PASS
- Tournament registration by two Community members: PASS
- Server-side bracket generation: PASS
- Participant result submission: PASS
- Opponent confirmation: PASS
- Tournament completion/champion/runner-up persistence: PASS
- Unauthenticated protected endpoint: correctly rejected
- Logout invalidates session: PASS
- Result dispute after completion: correctly rejected after final fix

## Remaining release work
The next stage is a final browser/mobile regression audit and deployment checklist. The legacy `/api/state` bridge should only be removed after every remaining UI write has been verified against a dedicated endpoint.
