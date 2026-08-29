import hashlib
import time
import unittest

import server
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
