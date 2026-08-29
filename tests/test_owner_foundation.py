import hashlib
import json
import time
import unittest
from unittest.mock import patch

from fastapi import Request

import server
from api.index import invoke_existing_backend
from tests.http_harness import BackendHarness


class OwnerFoundationTests(unittest.TestCase):
    def setUp(self):
        self.backend = BackendHarness()

    def tearDown(self):
        self.backend.close()

    def test_fresh_database_reports_owner_setup_incomplete(self):
        response = self.backend.request("GET", "/api/owner/setup/status")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.json, {"setupComplete": False})

    def test_backend_harnesses_require_non_overlapping_lifetimes(self):
        with self.assertRaises(RuntimeError):
            BackendHarness()
        self.backend.close()
        self.backend = BackendHarness()
        response = self.backend.request("GET", "/api/owner/setup/status")
        self.assertEqual(response.json, {"setupComplete": False})

    def complete_owner_setup(self):
        response = self.backend.request(
            "POST",
            "/api/owner/setup",
            {
                "username": "overall-owner",
                "password": "owner-password-123",
                "squadOwner": {
                    "ign": "DarkOwner",
                    "gameId": "123456",
                    "serverId": "1234",
                    "accessCode": "DS-OWNER",
                },
            },
        )
        self.assertEqual(response.status, 200)

    def owner_login_cookie(self):
        response = self.backend.request(
            "POST",
            "/api/owner/login",
            {"username": "overall-owner", "password": "owner-password-123"},
        )
        self.assertEqual(response.status, 200)
        return response.headers["Set-Cookie"].split(";", 1)[0]

    def adapter_request(self, method, path, payload=None, cookie="", forwarded_proto=None):
        body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        headers = [(b"host", b"test.local")]
        if forwarded_proto:
            headers.append((b"x-forwarded-proto", forwarded_proto.encode("ascii")))
        if cookie:
            headers.append((b"cookie", cookie.encode("ascii")))
        if payload is not None:
            headers.extend(
                ((b"content-type", b"application/json"), (b"content-length", str(len(body)).encode("ascii")))
            )
        request = Request(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": method,
                "scheme": "http",
                "path": path,
                "raw_path": path.encode("ascii"),
                "query_string": b"",
                "headers": headers,
                "client": ("127.0.0.1", 50000),
                "server": ("test.local", 80),
            }
        )
        return invoke_existing_backend(request, body)

    def test_owner_session_is_revoked_on_logout(self):
        self.complete_owner_setup()
        copied_cookie = self.owner_login_cookie()

        me = self.backend.request("GET", "/api/auth/me", cookie=copied_cookie)
        self.assertTrue(me.json["authenticated"])
        self.assertEqual(me.json["session"]["role"], "Overall Owner")

        logout = self.backend.request("POST", "/api/logout", cookie=copied_cookie)
        self.assertEqual(logout.status, 200)

        after_logout = self.backend.request("GET", "/api/auth/me", cookie=copied_cookie)
        self.assertEqual(after_logout.json, {"authenticated": False, "session": None})

    def test_owner_session_token_is_stored_only_as_a_hash(self):
        self.complete_owner_setup()
        cookie = self.owner_login_cookie()
        token = cookie.split("=", 1)[1]

        with server.LOCK, server.db() as connection:
            raw_count = connection.execute(
                "SELECT COUNT(*) AS count FROM sessions WHERE token=?", (token,)
            ).fetchone()["count"]
            row = connection.execute(
                "SELECT token, type, role FROM sessions WHERE token=?",
                (hashlib.sha256(token.encode()).hexdigest(),),
            ).fetchone()

        self.assertEqual(raw_count, 0)
        self.assertIsNotNone(row)
        self.assertEqual(dict(row)["type"], "owner")
        self.assertEqual(dict(row)["role"], "Overall Owner")

    def test_expired_session_is_rejected_and_deleted(self):
        token = "expired-session-token"
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with server.LOCK, server.db() as connection:
            connection.execute(
                "INSERT INTO sessions(token,type,user_id,role,expires) VALUES(?,?,?,?,?)",
                (token_hash, "owner", "expired-owner", "Overall Owner", int(time.time()) - 1),
            )
            connection.commit()

        response = self.backend.request(
            "GET", "/api/auth/me", cookie=f"dark_system_session={token}"
        )
        self.assertEqual(response.json, {"authenticated": False, "session": None})

        with server.LOCK, server.db() as connection:
            row = connection.execute(
                "SELECT token FROM sessions WHERE token=?", (token_hash,)
            ).fetchone()
        self.assertIsNone(row)

    def test_session_expiring_at_the_current_second_is_rejected_and_deleted(self):
        token = "exact-expiry-session-token"
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        current_second = 1_700_000_000
        with server.LOCK, server.db() as connection:
            connection.execute(
                "INSERT INTO sessions(token,type,user_id,role,expires) VALUES(?,?,?,?,?)",
                (token_hash, "owner", "expired-owner", "Overall Owner", current_second),
            )
            connection.commit()

        with patch("server.time.time", return_value=current_second):
            response = self.backend.request(
                "GET", "/api/auth/me", cookie=f"dark_system_session={token}"
            )

        self.assertEqual(response.json, {"authenticated": False, "session": None})
        with server.LOCK, server.db() as connection:
            row = connection.execute(
                "SELECT token FROM sessions WHERE token=?", (token_hash,)
            ).fetchone()
        self.assertIsNone(row)

    def test_create_session_removes_sessions_expiring_at_the_current_second(self):
        token_hash = hashlib.sha256(b"cleanup-boundary-token").hexdigest()
        current_second = 1_700_000_000
        with server.LOCK, server.db() as connection:
            connection.execute(
                "INSERT INTO sessions(token,type,user_id,role,expires) VALUES(?,?,?,?,?)",
                (token_hash, "owner", "expired-owner", "Overall Owner", current_second),
            )
            connection.commit()

        with patch("server.time.time", return_value=current_second):
            server.create_session("owner", "new-owner", "Overall Owner")

        with server.LOCK, server.db() as connection:
            row = connection.execute(
                "SELECT token FROM sessions WHERE token=?", (token_hash,)
            ).fetchone()
        self.assertIsNone(row)

    def test_owner_logout_is_audited_without_session_secrets(self):
        self.complete_owner_setup()
        cookie = self.owner_login_cookie()
        self.backend.request("POST", "/api/logout", cookie=cookie)

        with server.LOCK, server.db() as connection:
            row = connection.execute(
                "SELECT actor_type, actor_role, action, details FROM audit_log WHERE action='owner_logout'"
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(dict(row)["actor_type"], "owner")
        self.assertEqual(dict(row)["actor_role"], "Overall Owner")
        self.assertEqual(dict(row)["action"], "owner_logout")
        self.assertNotIn(cookie.split("=", 1)[1], dict(row)["details"])

    def test_community_and_squad_sessions_remain_usable_and_opaque(self):
        community = self.backend.request(
            "POST",
            "/api/community/register",
            {
                "email": "member@example.test",
                "password": "member-password-123",
                "ign": "CommunityPlayer",
                "gameId": "654321",
                "serverId": "4321",
            },
        )
        self.assertEqual(community.status, 200)
        community_cookie = community.headers["Set-Cookie"].split(";", 1)[0]
        community_me = self.backend.request("GET", "/api/auth/me", cookie=community_cookie)
        self.assertTrue(community_me.json["authenticated"])
        self.assertEqual(community_me.json["session"]["type"], "community")

        self.complete_owner_setup()
        squad = self.backend.request(
            "POST",
            "/api/squad/login",
            {"ign": "DarkOwner", "gameId": "123456", "serverId": "1234", "accessCode": "DS-OWNER"},
        )
        self.assertEqual(squad.status, 200)
        squad_cookie = squad.headers["Set-Cookie"].split(";", 1)[0]
        squad_me = self.backend.request("GET", "/api/auth/me", cookie=squad_cookie)
        self.assertTrue(squad_me.json["authenticated"])
        self.assertEqual(squad_me.json["session"]["type"], "squad")

        for cookie in (community_cookie, squad_cookie):
            token = cookie.split("=", 1)[1]
            with server.LOCK, server.db() as connection:
                raw_row = connection.execute(
                    "SELECT token FROM sessions WHERE token=?", (token,)
                ).fetchone()
                hashed_row = connection.execute(
                    "SELECT token FROM sessions WHERE token=?",
                    (hashlib.sha256(token.encode()).hexdigest(),),
                ).fetchone()
            self.assertIsNone(raw_row)
            self.assertIsNotNone(hashed_row)

    def test_https_session_issuers_set_secure_cookie(self):
        community_registration = self.backend.request(
            "POST",
            "/api/community/register",
            {
                "email": "secure-member@example.test",
                "password": "member-password-123",
                "ign": "SecureCommunityPlayer",
                "gameId": "765432",
                "serverId": "2345",
            },
        )
        community_login = self.backend.request(
            "POST",
            "/api/community/login",
            {"email": "secure-member@example.test", "password": "member-password-123"},
        )
        self.complete_owner_setup()
        owner_login = self.backend.request(
            "POST",
            "/api/owner/login",
            {"username": "overall-owner", "password": "owner-password-123"},
        )
        squad_login = self.backend.request(
            "POST",
            "/api/squad/login",
            {"ign": "DarkOwner", "gameId": "123456", "serverId": "1234", "accessCode": "DS-OWNER"},
        )

        for response in (community_registration, community_login, owner_login, squad_login):
            self.assertEqual(response.status, 200)
            self.assertIn("; HttpOnly", response.headers["Set-Cookie"])
            self.assertIn("; SameSite=Strict", response.headers["Set-Cookie"])
            self.assertIn(f"; Max-Age={server.SESSION_TTL}", response.headers["Set-Cookie"])
            self.assertIn("; Secure", response.headers["Set-Cookie"])

    def test_adapter_lowercase_forwarded_https_sets_secure_and_http_does_not(self):
        self.complete_owner_setup()
        login = self.adapter_request(
            "POST",
            "/api/owner/login",
            {"username": "overall-owner", "password": "owner-password-123"},
            forwarded_proto="https",
        )
        self.assertEqual(login.status_code, 200)
        self.assertIn("; Secure", login.headers["set-cookie"])

        copied_cookie = login.headers["set-cookie"].split(";", 1)[0]
        me = self.adapter_request(
            "GET", "/api/auth/me", cookie=copied_cookie, forwarded_proto="https"
        )
        self.assertEqual(me.status_code, 200)
        self.assertTrue(json.loads(me.body)["authenticated"])

        logout = self.adapter_request(
            "POST", "/api/logout", cookie=copied_cookie, forwarded_proto="https"
        )
        self.assertEqual(logout.status_code, 200)
        self.assertIn("; Secure", logout.headers["set-cookie"])

        after_logout = self.adapter_request(
            "GET", "/api/auth/me", cookie=copied_cookie, forwarded_proto="https"
        )
        self.assertEqual(
            json.loads(after_logout.body), {"authenticated": False, "session": None}
        )
        token_hash = hashlib.sha256(copied_cookie.split("=", 1)[1].encode()).hexdigest()
        with server.LOCK, server.db() as connection:
            row = connection.execute(
                "SELECT token FROM sessions WHERE token=?", (token_hash,)
            ).fetchone()
        self.assertIsNone(row)

        plain_http_login = self.adapter_request(
            "POST",
            "/api/owner/login",
            {"username": "overall-owner", "password": "owner-password-123"},
        )
        self.assertEqual(plain_http_login.status_code, 200)
        self.assertNotIn("; Secure", plain_http_login.headers["set-cookie"])

    def test_owner_overview_requires_owner(self):
        response = self.backend.request("GET", "/api/owner/overview")

        self.assertEqual(response.status, 401)
        self.assertEqual(response.json, {"error": "Authentication required"})

    def test_owner_overview_rejects_community_and_squad_sessions(self):
        community = self.backend.request(
            "POST",
            "/api/community/register",
            {
                "email": "overview-member@example.test",
                "password": "member-password-123",
                "ign": "OverviewMember",
                "gameId": "654321",
                "serverId": "4321",
            },
        )
        self.assertEqual(community.status, 200)

        self.complete_owner_setup()
        squad = self.backend.request(
            "POST",
            "/api/squad/login",
            {"ign": "DarkOwner", "gameId": "123456", "serverId": "1234", "accessCode": "DS-OWNER"},
        )
        self.assertEqual(squad.status, 200)

        for cookie in (
            community.headers["Set-Cookie"].split(";", 1)[0],
            squad.headers["Set-Cookie"].split(";", 1)[0],
        ):
            response = self.backend.request("GET", "/api/owner/overview", cookie=cookie)
            self.assertIn(response.status, (401, 403))

    def test_owner_overview_reports_sanitized_system_state(self):
        community = self.backend.request(
            "POST",
            "/api/community/register",
            {
                "email": "overview-count@example.test",
                "password": "member-password-123",
                "ign": "CountMember",
                "gameId": "765432",
                "serverId": "2345",
            },
        )
        self.assertEqual(community.status, 200)
        self.complete_owner_setup()
        owner_cookie = self.owner_login_cookie()

        tournaments = [
            {
                "id": "open",
                "status": "Open",
                "matches": [
                    {"id": "legacy-pending", "result": {"winner": "member"}, "resultStatus": "Pending Confirmation"},
                    {"id": "disputed", "submission": {"status": "Disputed"}},
                    {"id": "confirmed", "submission": {"status": "Confirmed"}},
                ],
            },
            {"id": "complete", "status": "Completed", "completed": True, "matches": []},
            {"id": "cancelled", "status": "Cancelled", "matches": []},
        ]
        registrations = [
            {"id": "registered", "status": "Registered"},
            {"id": "pending", "status": "Pending"},
            {"id": "approved", "status": "Approved"},
            {"id": "rejected", "status": "Rejected"},
        ]
        approvals = [
            {"id": "waiting", "status": "Pending"},
            {"id": "approved", "status": "Approved"},
        ]
        with server.LOCK, server.db() as connection:
            connection.execute(
                """INSERT INTO squad_members
                   (id,name,ign,game_id,server_id,role,access_code,status,profile_complete,account_activated)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                ("overview-squad", "Overview Squad", "OverviewSquad", "111111", "1111", "Squad Member", "squad-secret", "Offline", 1, 1),
            )
            for key, value in (
                ("tournaments", tournaments),
                ("registrations", registrations),
                ("squadTournamentApprovals", approvals),
            ):
                connection.execute(
                    "INSERT INTO app_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(value)),
                )
            for index in range(12):
                details = {
                    "message": f"visible audit {index}",
                    "nested": {
                        "password": "audit-password",
                        "accessCode": "audit-access-code",
                        "reset_code": "audit-reset-code",
                        "sessionToken": "audit-token",
                        "credential": owner_cookie.split("=", 1)[1],
                        "safe": "visible nested value",
                    },
                }
                connection.execute(
                    """INSERT INTO audit_log
                       (id,actor_type,actor_id,actor_role,action,target_type,target_id,created_at,details)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (f"overview-audit-{index}", "owner", "owner-1", "Overall Owner", "overview_test", "system", owner_cookie.split("=", 1)[1], f"2099-01-{index + 1:02d}T00:00:00Z", json.dumps(details)),
                )
            connection.execute(
                """INSERT INTO audit_log
                   (id,actor_type,actor_id,actor_role,action,target_type,target_id,created_at,details)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                ("overview-malformed", "owner", "owner-1", "Overall Owner", "overview_test", "system", "", "2100-01-01T00:00:00Z", "{not json"),
            )
            connection.commit()

        response = self.backend.request("GET", "/api/owner/overview", cookie=owner_cookie)

        self.assertEqual(response.status, 200)
        self.assertIn("health", response.json)
        self.assertEqual(
            response.json["counts"],
            {"communityMembers": 1, "squadMembers": 2, "activeTournaments": 1, "completedTournaments": 1},
        )
        self.assertEqual(response.json["pending"], {"registrations": 2, "squadApprovals": 1, "results": 2})
        self.assertEqual(len(response.json["recentAudit"]), 10)
        self.assertEqual(response.json["recentAudit"][0]["details"], {})
        self.assertEqual(response.json["recentAudit"][1]["details"]["nested"], {"safe": "visible nested value"})

        serialized = json.dumps(response.json).lower()
        for secret_name in ("password", "access_code", "reset_code", "token"):
            self.assertNotIn(secret_name, serialized)
        for secret_value in ("audit-password", "audit-access-code", "audit-reset-code", "audit-token", "squad-secret"):
            self.assertNotIn(secret_value, serialized)
        self.assertNotIn(owner_cookie.split("=", 1)[1].lower(), serialized)
