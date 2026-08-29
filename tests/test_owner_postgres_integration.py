import json
import secrets
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import server
from tests.http_harness import BackendHarness, resolve_test_database_url


class OwnerPostgreSQLIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_database_url = resolve_test_database_url()
        if cls.test_database_url is None:
            raise unittest.SkipTest(
                "TEST_DATABASE_URL is not set; disposable PostgreSQL Owner gate skipped."
            )

    @staticmethod
    def request(method, path, payload=None, cookie=""):
        return BackendHarness.adapter_request(
            None,
            method,
            path,
            payload=payload,
            cookie=cookie,
        )

    @staticmethod
    def payload(username, ign, game_id):
        return {
            "setupSecret": "postgres-gate-setup-secret",
            "username": username,
            "password": "owner-password-123",
            "squadOwner": {
                "ign": ign,
                "gameId": game_id,
                "serverId": "1234",
                "accessCode": "POSTGRES-GATE-SQUAD-CODE",
            },
        }

    def test_owner_lifecycle_concurrency_revocation_audit_and_durable_throttle(self):
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row

        schema_name = f"dark_system_gate_{secrets.token_hex(8)}"

        def isolated_db():
            connection = psycopg.connect(
                self.test_database_url,
                row_factory=dict_row,
                connect_timeout=10,
                prepare_threshold=None,
            )
            connection.execute(
                sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name))
            )
            return server.PostgresCompat(connection)

        with psycopg.connect(self.test_database_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
            )

        try:
            with (
                patch.object(server, "db", isolated_db),
                patch.object(server, "DATABASE_URL", ""),
                patch.object(server, "OWNER_SETUP_SECRET", "postgres-gate-setup-secret"),
                patch.object(server, "SESSION_SECRET", "postgres-gate-session-secret"),
            ):
                server.RATE_LIMITS.clear()
                server.init_db()
                fresh = self.request("GET", "/api/owner/setup/status")
                self.assertEqual(fresh.status_code, 200)
                self.assertEqual(json.loads(fresh.body), {"setupComplete": False})

                candidates = [
                    self.payload("postgres-owner-a", "PostgresOwnerA", "111111"),
                    self.payload("postgres-owner-b", "PostgresOwnerB", "222222"),
                ]
                with ThreadPoolExecutor(max_workers=2) as executor:
                    responses = list(
                        executor.map(
                            lambda candidate: self.request(
                                "POST", "/api/owner/setup", candidate
                            ),
                            candidates,
                        )
                    )

                self.assertEqual(
                    sorted(response.status_code for response in responses),
                    [200, 409],
                )
                winner_index = next(
                    index
                    for index, response in enumerate(responses)
                    if response.status_code == 200
                )
                winner = candidates[winner_index]
                locked = self.request("GET", "/api/owner/setup/status")
                self.assertEqual(json.loads(locked.body), {"setupComplete": True})

                login = self.request(
                    "POST",
                    "/api/owner/login",
                    {
                        "username": winner["username"],
                        "password": winner["password"],
                    },
                )
                self.assertEqual(login.status_code, 200)
                owner_cookie = login.headers["set-cookie"].split(";", 1)[0]

                overview = self.request(
                    "GET", "/api/owner/overview", cookie=owner_cookie
                )
                self.assertEqual(overview.status_code, 200)
                self.assertEqual(
                    json.loads(overview.body)["health"],
                    {"backend": "healthy", "database": "healthy"},
                )

                logout = self.request("POST", "/api/logout", cookie=owner_cookie)
                self.assertEqual(logout.status_code, 200)
                revoked = self.request("GET", "/api/auth/me", cookie=owner_cookie)
                self.assertEqual(
                    json.loads(revoked.body),
                    {"authenticated": False, "session": None},
                )

                with server.LOCK, server.db() as connection:
                    audit_counts = {
                        row["action"]: row["count"]
                        for row in connection.execute(
                            """SELECT action, COUNT(*) AS count
                               FROM audit_log
                               WHERE action IN ('owner_setup','owner_login','owner_logout')
                               GROUP BY action"""
                        ).fetchall()
                    }
                    connection.execute("DELETE FROM login_throttle")
                    connection.commit()
                self.assertEqual(
                    audit_counts,
                    {"owner_setup": 1, "owner_login": 1, "owner_logout": 1},
                )

                credentials = {
                    "username": winner["username"],
                    "password": "definitely-wrong-password",
                }
                fixed_time = int(time.time()) + 60
                with (
                    patch.object(server, "RATE_LIMIT_MAX", 2),
                    patch.object(server.time, "time", return_value=fixed_time),
                ):
                    first = self.request("POST", "/api/owner/login", credentials)
                    server.RATE_LIMITS.clear()
                    second = self.request("POST", "/api/owner/login", credentials)
                    server.RATE_LIMITS.clear()
                    blocked = self.request("POST", "/api/owner/login", credentials)

                self.assertEqual(
                    [first.status_code, second.status_code, blocked.status_code],
                    [401, 401, 429],
                )
                self.assertEqual(
                    json.loads(blocked.body),
                    {
                        "error": "Too many login attempts. Please wait a few minutes and try again."
                    },
                )
        finally:
            with psycopg.connect(self.test_database_url, autocommit=True) as admin:
                admin.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        sql.Identifier(schema_name)
                    )
                )


if __name__ == "__main__":
    unittest.main()
