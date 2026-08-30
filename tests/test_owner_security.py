import json
import logging
import threading
import unittest
from contextlib import nullcontext
from unittest.mock import patch

import server
from tests.http_harness import BackendHarness


class _BarrierConnection:
    """Synchronize the vulnerable read-before-write setup path in two threads."""

    def __init__(self, connection, barrier):
        self.connection = connection
        self.barrier = barrier

    def execute(self, sql, params=()):
        cursor = self.connection.execute(sql, params)
        normalized = " ".join(sql.lower().split())
        if normalized.startswith("select 1 from owner_accounts where lower(username)="):
            self.barrier.wait(timeout=5)
        return cursor

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def __enter__(self):
        self.connection.__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback):
        return self.connection.__exit__(exc_type, exc, traceback)


class _FailingSquadSessionDeleteConnection:
    """Fail after the Squad presence update to verify transaction rollback."""

    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, params=()):
        normalized = " ".join(sql.lower().split())
        if normalized.startswith("delete from sessions where token="):
            raise RuntimeError("forced synthetic squad session delete failure")
        return self.connection.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def __enter__(self):
        self.connection.__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback):
        return self.connection.__exit__(exc_type, exc, traceback)


class OwnerSecurityTests(unittest.TestCase):
    def setUp(self):
        self.backend = BackendHarness()

    def tearDown(self):
        self.backend.close()

    def setup_payload(self, **overrides):
        payload = {
            "setupSecret": BackendHarness.OWNER_SETUP_SECRET,
            "username": "overall-owner",
            "password": "owner-password-123",
            "squadOwner": {
                "ign": "DarkOwner",
                "gameId": "123456",
                "serverId": "1234",
                "accessCode": "DS-OWNER",
            },
        }
        payload.update(overrides)
        return payload

    def complete_setup(self):
        response = self.backend.request("POST", "/api/owner/setup", self.setup_payload())
        self.assertEqual(response.status, 200)

    def owner_cookie(self):
        response = self.backend.request(
            "POST",
            "/api/owner/login",
            {"username": "overall-owner", "password": "owner-password-123"},
        )
        self.assertEqual(response.status, 200)
        return response.headers["Set-Cookie"].split(";", 1)[0]

    def squad_cookie(self):
        response = self.backend.request(
            "POST",
            "/api/squad/login",
            {
                "ign": "DarkOwner",
                "gameId": "123456",
                "serverId": "1234",
                "accessCode": "DS-OWNER",
            },
        )
        self.assertEqual(response.status, 200)
        return response.headers["Set-Cookie"].split(";", 1)[0]

    def install_audit_failure(self, action):
        with server.LOCK, server.db() as connection:
            connection.execute(
                f"""CREATE TRIGGER reject_{action}_audit
                    BEFORE INSERT ON audit_log
                    WHEN NEW.action='{action}'
                    BEGIN
                      SELECT RAISE(ABORT, 'forced {action} audit failure');
                    END"""
            )
            connection.commit()

    def assert_setup_not_committed(self):
        with server.LOCK, server.db() as connection:
            state = connection.execute(
                "SELECT value FROM app_state WHERE key='owner_setup_complete'"
            ).fetchone()["value"]
            owners = connection.execute(
                "SELECT COUNT(*) AS count FROM owner_accounts"
            ).fetchone()["count"]
            audits = connection.execute(
                "SELECT COUNT(*) AS count FROM audit_log WHERE action='owner_setup'"
            ).fetchone()["count"]
        self.assertEqual(state, "false")
        self.assertEqual(owners, 0)
        self.assertEqual(audits, 0)

    def test_native_setup_requires_configured_correct_secret(self):
        missing = self.setup_payload()
        missing.pop("setupSecret")
        missing_response = self.backend.request("POST", "/api/owner/setup", missing)
        wrong_response = self.backend.request(
            "POST",
            "/api/owner/setup",
            self.setup_payload(setupSecret="wrong-owner-setup-secret"),
        )
        correct_response = self.backend.request(
            "POST", "/api/owner/setup", self.setup_payload()
        )

        self.assertEqual(missing_response.status, 403)
        self.assertEqual(wrong_response.status, 403)
        self.assertEqual(correct_response.status, 200)

    def test_adapter_setup_requires_configured_correct_secret(self):
        missing = self.setup_payload()
        missing.pop("setupSecret")
        missing_response = self.backend.adapter_request(
            "POST", "/api/owner/setup", missing
        )
        wrong_response = self.backend.adapter_request(
            "POST",
            "/api/owner/setup",
            self.setup_payload(setupSecret="wrong-owner-setup-secret"),
        )
        correct_response = self.backend.adapter_request(
            "POST", "/api/owner/setup", self.setup_payload()
        )

        self.assertEqual(missing_response.status_code, 403)
        self.assertEqual(wrong_response.status_code, 403)
        self.assertEqual(correct_response.status_code, 200)

    def test_setup_refuses_to_run_when_server_secret_is_unconfigured(self):
        with patch.object(server, "OWNER_SETUP_SECRET", "", create=True):
            native = self.backend.request(
                "POST", "/api/owner/setup", self.setup_payload()
            )
            adapter = self.backend.adapter_request(
                "POST", "/api/owner/setup", self.setup_payload()
            )

        self.assertEqual(native.status, 503)
        self.assertEqual(adapter.status_code, 503)
        self.assertEqual(
            native.json,
            {"error": "Owner setup is unavailable because server configuration is incomplete."},
        )
        self.assert_setup_not_committed()

    def test_setup_secret_is_never_returned_or_persisted(self):
        setup_secret = BackendHarness.OWNER_SETUP_SECRET
        response = self.backend.request("POST", "/api/owner/setup", self.setup_payload())

        self.assertEqual(response.status, 200)
        self.assertNotIn(setup_secret, response.body.decode("utf-8"))
        with server.LOCK, server.db() as connection:
            stored = connection.execute(
                """SELECT username AS value FROM owner_accounts
                   UNION ALL SELECT password_hash FROM owner_accounts
                   UNION ALL SELECT details FROM audit_log
                   UNION ALL SELECT value FROM app_state"""
            ).fetchall()
        self.assertNotIn(setup_secret, json.dumps([dict(row) for row in stored]))

    def test_concurrent_setup_claim_has_exactly_one_database_winner(self):
        original_db = server.db
        barrier = threading.Barrier(2)
        responses = []
        failures = []

        def unlocked_db():
            return _BarrierConnection(original_db(), barrier)

        def setup(username):
            try:
                response = self.backend.request(
                    "POST", "/api/owner/setup", self.setup_payload(username=username)
                )
                responses.append(response.status)
            except Exception as error:
                failures.append(type(error).__name__)

        with patch.object(server, "LOCK", nullcontext()), patch.object(
            server, "db", side_effect=unlocked_db
        ):
            threads = [
                threading.Thread(target=setup, args=("first-owner",)),
                threading.Thread(target=setup, args=("second-owner",)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)

        self.assertEqual(failures, [])
        self.assertEqual(sorted(responses), [200, 409])
        with server.LOCK, server.db() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM owner_accounts"
                ).fetchone()["count"],
                1,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM audit_log WHERE action='owner_setup'"
                ).fetchone()["count"],
                1,
            )

    def test_native_and_adapter_static_serving_use_only_public_allowlist(self):
        allowed = (
            "/",
            "/index.html",
            "/owner-admin",
            "/owner-admin/",
            "/style.css",
            "/script.js",
            "/owner-admin.css",
            "/owner-admin.js",
            "/assets/mlbb/birthday-mage.jpg",
            "/assets/mlbb/bunny-gunner.jpg",
            "/assets/mlbb/cafe-welcome.jpg",
            "/assets/mlbb/celestial-mage.jpg",
            "/assets/mlbb/dark-archer.jpg",
            "/assets/mlbb/hero-dragon.jpg",
            "/assets/mlbb/ice-archer.jpg",
            "/assets/mlbb/neon-warrior.jpg",
            "/assets/mlbb/pink-mage.jpg",
        )
        denied = (
            "/server.py",
            "/.env.example",
            "/README.md",
            "/docs/superpowers/specs/2026-08-29-owner-admin-design.md",
            "/tests/test_owner_foundation.py",
            "/dark_system.sqlite3",
            "/assets/../server.py",
            "/unknown.js",
        )

        for path in allowed:
            with self.subTest(path=path, transport="native"):
                self.assertEqual(self.backend.request("GET", path).status, 200)
            with self.subTest(path=path, transport="adapter"):
                self.assertEqual(
                    self.backend.adapter_request("GET", path).status_code, 200
                )
        for path in denied:
            with self.subTest(path=path, transport="native"):
                self.assertEqual(self.backend.request("GET", path).status, 404)
            with self.subTest(path=path, transport="adapter"):
                self.assertEqual(
                    self.backend.adapter_request("GET", path).status_code, 404
                )

    def test_demoted_squad_owner_cookie_uses_current_role_for_native_and_adapter_writes(self):
        self.complete_setup()
        copied_cookie = self.squad_cookie()
        with server.LOCK, server.db() as connection:
            connection.execute(
                "UPDATE squad_members SET role='Squad Member' WHERE id='1'"
            )
            connection.commit()

        payload = {
            "name": "Denied Member",
            "ign": "DeniedMember",
            "gameId": "999999",
            "serverId": "9999",
            "accessCode": "DENIED-CODE",
        }
        native = self.backend.request(
            "POST", "/api/squad/members", payload, cookie=copied_cookie
        )
        adapter = self.backend.adapter_request(
            "POST", "/api/squad/members", payload, cookie=copied_cookie
        )
        me = self.backend.request("GET", "/api/auth/me", cookie=copied_cookie)

        self.assertEqual(native.status, 403)
        self.assertEqual(adapter.status_code, 403)
        self.assertEqual(me.json["session"]["role"], "Squad Member")
        with server.LOCK, server.db() as connection:
            self.assertIsNone(
                connection.execute(
                    "SELECT id FROM squad_members WHERE ign='DeniedMember'"
                ).fetchone()
            )

    def test_disabled_or_deleted_accounts_revoke_copied_sessions(self):
        self.complete_setup()
        disabled_cookie = self.squad_cookie()
        disabled_hash = server.session_token_hash(disabled_cookie.split("=", 1)[1])
        with server.LOCK, server.db() as connection:
            connection.execute("UPDATE squad_members SET status='Disabled' WHERE id='1'")
            connection.commit()

        disabled = self.backend.request(
            "GET", "/api/auth/me", cookie=disabled_cookie
        )
        self.assertEqual(disabled.json, {"authenticated": False, "session": None})
        with server.LOCK, server.db() as connection:
            self.assertIsNone(
                connection.execute(
                    "SELECT token FROM sessions WHERE token=?", (disabled_hash,)
                ).fetchone()
            )

        with server.LOCK, server.db() as connection:
            connection.execute("UPDATE squad_members SET status='Offline' WHERE id='1'")
            connection.commit()
        deleted_cookie = self.squad_cookie()
        deleted_hash = server.session_token_hash(deleted_cookie.split("=", 1)[1])
        with server.LOCK, server.db() as connection:
            connection.execute("DELETE FROM squad_members WHERE id='1'")
            connection.commit()

        deleted = self.backend.adapter_request(
            "GET", "/api/auth/me", cookie=deleted_cookie
        )
        self.assertEqual(
            json.loads(deleted.body), {"authenticated": False, "session": None}
        )
        with server.LOCK, server.db() as connection:
            self.assertIsNone(
                connection.execute(
                    "SELECT token FROM sessions WHERE token=?", (deleted_hash,)
                ).fetchone()
            )

    def test_owner_cannot_change_squad_credentials_outside_self_service_recovery(self):
        self.complete_setup()
        squad_cookie = self.squad_cookie()
        owner_cookie = self.owner_cookie()

        changed = self.backend.request(
            "PUT",
            "/api/squad/members",
            {"id": "1", "accessCode": "NEW-OWNER-CODE"},
            cookie=owner_cookie,
        )
        copied = self.backend.request("GET", "/api/auth/me", cookie=squad_cookie)

        self.assertEqual(changed.status, 400)
        self.assertTrue(copied.json["authenticated"])

    def test_community_password_reset_revokes_existing_sessions(self):
        registration = self.backend.request(
            "POST",
            "/api/community/register",
            {
                "email": "credential-change@example.test",
                "password": "original-password",
                "ign": "CredentialChange",
                "gameId": "555555",
                "serverId": "5555",
            },
        )
        self.assertEqual(registration.status, 200)
        copied_cookie = registration.headers["Set-Cookie"].split(";", 1)[0]
        account_id = registration.json["account"]["id"]
        with server.LOCK, server.db() as connection:
            connection.execute(
                "UPDATE community_accounts SET reset_code=?,reset_expires=? WHERE id=?",
                ("123456", 2_000_000_000, account_id),
            )
            connection.commit()

        reset = self.backend.request(
            "POST",
            "/api/community/reset",
            {
                "email": "credential-change@example.test",
                "code": "123456",
                "password": "replacement-password",
            },
        )
        copied = self.backend.adapter_request(
            "GET", "/api/auth/me", cookie=copied_cookie
        )

        self.assertEqual(reset.status, 200)
        self.assertEqual(
            json.loads(copied.body), {"authenticated": False, "session": None}
        )

    def test_setup_audit_failure_rolls_back_native_setup(self):
        self.install_audit_failure("owner_setup")

        with self.assertLogs(level=logging.ERROR) as captured:
            response = self.backend.request(
                "POST", "/api/owner/setup", self.setup_payload()
            )

        self.assertEqual(response.status, 503)
        self.assertIn("setup transaction failed", " ".join(captured.output).lower())
        self.assert_setup_not_committed()

    def test_setup_audit_failure_rolls_back_adapter_setup(self):
        self.install_audit_failure("owner_setup")

        with self.assertLogs(level=logging.ERROR) as captured:
            response = self.backend.adapter_request(
                "POST", "/api/owner/setup", self.setup_payload()
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("setup transaction failed", " ".join(captured.output).lower())
        self.assert_setup_not_committed()

    def test_owner_login_audit_failure_does_not_issue_session(self):
        self.complete_setup()
        self.install_audit_failure("owner_login")

        with self.assertLogs(level=logging.ERROR) as captured:
            response = self.backend.request(
                "POST",
                "/api/owner/login",
                {"username": "overall-owner", "password": "owner-password-123"},
            )

        self.assertEqual(response.status, 503)
        self.assertIn("login transaction failed", " ".join(captured.output).lower())
        self.assertNotIn("Set-Cookie", response.headers)
        with server.LOCK, server.db() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM sessions WHERE type='owner'"
                ).fetchone()["count"],
                0,
            )

    def test_owner_logout_audit_failure_does_not_report_success(self):
        self.complete_setup()
        cookie = self.owner_cookie()
        self.install_audit_failure("owner_logout")

        with self.assertLogs(level=logging.ERROR) as captured:
            response = self.backend.adapter_request(
                "POST", "/api/logout", cookie=cookie
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("logout transaction failed", " ".join(captured.output).lower())
        still_authenticated = self.backend.request(
            "GET", "/api/auth/me", cookie=cookie
        )
        self.assertTrue(still_authenticated.json["authenticated"])

    def test_squad_logout_failure_rolls_back_presence_and_session_revocation(self):
        self.complete_setup()
        cookie = self.squad_cookie()
        original_db = server.db

        def failing_db():
            return _FailingSquadSessionDeleteConnection(original_db())

        with patch.object(server, "db", side_effect=failing_db):
            with self.assertLogs(level=logging.ERROR) as captured:
                response = self.backend.adapter_request(
                    "POST", "/api/logout", cookie=cookie
                )

        self.assertEqual(response.status_code, 503)
        self.assertIn("squad logout transaction failed", " ".join(captured.output).lower())
        self.assertEqual(
            json.loads(response.body),
            {"error": "Squad logout could not be completed."},
        )
        still_authenticated = self.backend.request(
            "GET", "/api/auth/me", cookie=cookie
        )
        self.assertTrue(still_authenticated.json["authenticated"])
        with server.LOCK, server.db() as connection:
            member = connection.execute(
                "SELECT status FROM squad_members WHERE id=?", ("1",)
            ).fetchone()
        self.assertEqual(member["status"], "Online")

    def test_legacy_audit_failure_is_logged_instead_of_silently_swallowed(self):
        self.complete_setup()
        cookie = self.squad_cookie()
        self.install_audit_failure("squad_announcement_create")

        with self.assertLogs(level=logging.ERROR) as captured:
            response = self.backend.request(
                "POST",
                "/api/squad/content",
                {"kind": "announcement", "item": {"title": "Audit failure"}},
                cookie=cookie,
            )

        self.assertEqual(response.status, 201)
        self.assertIn("audit", " ".join(captured.output).lower())

    def test_owner_login_throttle_survives_process_memory_reset_and_new_handlers(self):
        self.complete_setup()
        credentials = {"username": "overall-owner", "password": "wrong-password"}

        with patch.object(server, "RATE_LIMIT_MAX", 2), patch.object(
            server.time, "time", return_value=1_700_000_000
        ):
            first = self.backend.request("POST", "/api/owner/login", credentials)
            server.RATE_LIMITS.clear()
            second = self.backend.adapter_request(
                "POST", "/api/owner/login", credentials
            )
            server.RATE_LIMITS.clear()
            blocked = self.backend.request("POST", "/api/owner/login", credentials)

        self.assertEqual(first.status, 401)
        self.assertEqual(second.status_code, 401)
        self.assertEqual(blocked.status, 429)
        self.assertEqual(
            blocked.json,
            {"error": "Too many login attempts. Please wait a few minutes and try again."},
        )


if __name__ == "__main__":
    unittest.main()
