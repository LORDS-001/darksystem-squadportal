import time
import unittest
from unittest.mock import patch

import server
from tests.http_harness import BackendHarness


class SquadRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.backend = BackendHarness()
        with server.LOCK, server.db() as connection:
            connection.execute(
                """INSERT INTO squad_members
                   (id,name,ign,game_id,server_id,role,email,access_code,status,profile_complete,account_activated)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                ("recover-1", "Recovery Member", "ExactIGN", "123456", "9876",
                 "Squad Member", "recover@example.test", "OLD-CODE", "Offline", 1, 1),
            )
            connection.commit()

    def tearDown(self):
        self.backend.close()

    @staticmethod
    def identity(**changes):
        value = {
            "email": "recover@example.test", "ign": "ExactIGN",
            "gameId": "123456", "serverId": "9876",
        }
        value.update(changes)
        return value

    def test_forgot_is_enumeration_safe_exact_and_stores_only_a_hash(self):
        deliveries = []
        with patch.object(server, "smtp_send", side_effect=lambda *args: deliveries.append(args) or True):
            found = self.backend.request("POST", "/api/squad/forgot", self.identity())
            missing = self.backend.request("POST", "/api/squad/forgot", self.identity(email="missing@example.test"))
            mismatched = self.backend.request("POST", "/api/squad/forgot", self.identity(ign="exactign"))
        self.assertEqual(found.status, 200)
        self.assertEqual(found.json, missing.json)
        self.assertEqual(found.json, mismatched.json)
        self.assertEqual(len(deliveries), 1)
        code = deliveries[0][2].split(" is ", 1)[1].split(".", 1)[0]
        with server.LOCK, server.db() as connection:
            recovery = connection.execute(
                "SELECT code_hash,expires_at,used_at FROM recovery_codes WHERE account_type='squad' AND account_id='recover-1'"
            ).fetchone()
        self.assertNotEqual(recovery["code_hash"], code)
        self.assertTrue(server.verify_recovery_code(code, recovery["code_hash"]))
        self.assertGreater(int(recovery["expires_at"]), int(time.time()))
        self.assertIsNone(recovery["used_at"])

    def test_reset_rotates_access_code_revokes_sessions_and_is_single_use(self):
        login = self.backend.request("POST", "/api/squad/login", {
            **self.identity(), "accessCode": "OLD-CODE",
        })
        self.assertEqual(login.status, 200)
        cookie = login.headers["Set-Cookie"].split(";", 1)[0]
        with server.LOCK, server.db() as connection:
            migrated = connection.execute(
                "SELECT access_code,access_code_hash FROM squad_members WHERE id='recover-1'"
            ).fetchone()
        self.assertEqual(migrated["access_code"], "")
        self.assertTrue(server.verify_password("OLD-CODE", migrated["access_code_hash"]))
        deliveries = []
        with patch.object(server, "smtp_send", side_effect=lambda *args: deliveries.append(args) or True):
            self.backend.request("POST", "/api/squad/forgot", self.identity())
        code = deliveries[0][2].split(" is ", 1)[1].split(".", 1)[0]
        reset = self.backend.request("POST", "/api/squad/reset", {
            **self.identity(), "code": code, "accessCode": "NEW-ACCESS-22",
        })
        self.assertEqual(reset.status, 200)
        self.assertEqual(self.backend.request("GET", "/api/auth/me", cookie=cookie).json["authenticated"], False)
        self.assertEqual(self.backend.request("POST", "/api/squad/login", {
            **self.identity(), "accessCode": "OLD-CODE",
        }).status, 401)
        self.assertEqual(self.backend.request("POST", "/api/squad/login", {
            **self.identity(), "accessCode": "NEW-ACCESS-22",
        }).status, 200)
        self.assertEqual(self.backend.request("POST", "/api/squad/reset", {
            **self.identity(), "code": code, "accessCode": "ANOTHER-CODE-33",
        }).status, 400)
        with server.LOCK, server.db() as connection:
            row = connection.execute("SELECT access_code,access_code_hash FROM squad_members WHERE id='recover-1'").fetchone()
            audit = connection.execute("SELECT details FROM audit_log WHERE action='squad_access_code_reset'").fetchone()
        self.assertNotIn("NEW-ACCESS-22", str(row["access_code"]))
        self.assertTrue(server.verify_password("NEW-ACCESS-22", row["access_code_hash"]))
        self.assertNotIn(code, audit["details"])
        self.assertNotIn("NEW-ACCESS-22", audit["details"])

    def test_expired_code_and_throttling_are_rejected(self):
        deliveries = []
        with patch.object(server, "smtp_send", side_effect=lambda *args: deliveries.append(args) or True):
            self.backend.request("POST", "/api/squad/forgot", self.identity())
        code = deliveries[0][2].split(" is ", 1)[1].split(".", 1)[0]
        with server.LOCK, server.db() as connection:
            connection.execute("UPDATE recovery_codes SET expires_at=? WHERE account_type='squad'", (int(time.time()) - 1,))
            connection.commit()
        self.assertEqual(self.backend.request("POST", "/api/squad/reset", {
            **self.identity(), "code": code, "accessCode": "NEW-ACCESS-22",
        }).status, 400)
        statuses = [self.backend.request("POST", "/api/squad/forgot", self.identity()).status for _ in range(server.RATE_LIMIT_MAX + 1)]
        self.assertEqual(statuses[-1], 429)


class CommunityRecoveryHardeningTests(unittest.TestCase):
    def setUp(self):
        self.backend = BackendHarness()
        registered = self.backend.request("POST", "/api/community/register", {
            "email": "community-recover@example.test", "password": "old-password-123",
            "ign": "RecoverCommunity", "gameId": "555555", "serverId": "5555",
        })
        self.cookie = registered.headers["Set-Cookie"].split(";", 1)[0]

    def tearDown(self):
        self.backend.close()

    def test_community_recovery_hashes_single_use_code_and_revokes_sessions(self):
        deliveries = []
        with patch.object(server, "smtp_send", side_effect=lambda *args: deliveries.append(args) or True):
            found = self.backend.request("POST", "/api/community/forgot", {"email": "community-recover@example.test"})
            missing = self.backend.request("POST", "/api/community/forgot", {"email": "missing@example.test"})
        self.assertEqual(found.json, missing.json)
        code = deliveries[0][2].split(" is ", 1)[1].split(".", 1)[0]
        with server.LOCK, server.db() as connection:
            row = connection.execute("SELECT reset_code FROM community_accounts WHERE email='community-recover@example.test'").fetchone()
        self.assertNotEqual(row["reset_code"], code)
        reset = self.backend.request("POST", "/api/community/reset", {
            "email": "community-recover@example.test", "code": code, "password": "new-password-123",
        })
        self.assertEqual(reset.status, 200)
        self.assertFalse(self.backend.request("GET", "/api/auth/me", cookie=self.cookie).json["authenticated"])
        self.assertEqual(self.backend.request("POST", "/api/community/reset", {
            "email": "community-recover@example.test", "code": code, "password": "other-password-123",
        }).status, 400)


if __name__ == "__main__":
    unittest.main()
