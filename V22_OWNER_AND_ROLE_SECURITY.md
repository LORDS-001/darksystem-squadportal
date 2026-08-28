# Dark System V22 — Owner & Role Security

This phase preserves the existing V21 frontend and backend while strengthening the server boundary.

## Owner setup

The production Owner Setup endpoint is:

`POST /api/owner/setup`

Body:

```json
{
  "username": "your-owner-username",
  "password": "your-strong-password",
  "squadOwner": {
    "ign": "your-squad-owner-ign",
    "gameId": "your-game-id",
    "serverId": "your-server-id",
    "accessCode": "your-access-code"
  }
}
```

The endpoint is one-time only. After successful setup, `owner_setup_complete` is locked and a second setup attempt returns HTTP 409.

Check status with `GET /api/owner/setup/status`.

## Overall Owner login

`POST /api/owner/login`

Body:

```json
{"username":"your-owner-username","password":"your-password"}
```

The session is an HttpOnly signed cookie with role `Overall Owner`.

## Roles

- Overall Owner: full system authority and audit access.
- Squad Owner: squad administration and tournament authority.
- Squad Leader: member editing, without role/access-code control.
- Assistant Squad Leader: member editing, without role/access-code control.
- Squad Member: own squad profile.
- Community Member: own community profile and tournament registration.
- Tournament Manager: tournament administration and registration approval.

`GET /api/roles` exposes the server permission matrix.

## Audit log

Owner actions and major management operations are recorded in `audit_log`.

`GET /api/owner/audit` requires an Overall Owner session.

## Compatibility sync

`/api/state` remains temporarily available so the existing frontend does not break. It is now role-aware: squad data requires squad leadership, global tournament/season data requires owner authority, and passwords are never accepted through state synchronization.

The intended next hardening step is to replace remaining frontend-wide state writes with dedicated CRUD endpoints and then retire `/api/state`.
