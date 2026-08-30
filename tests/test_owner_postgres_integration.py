import json
import secrets
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import server
from tests.http_harness import (
    BackendHarness,
    connect_validated_test_database,
    resolve_test_database_gate,
)


class _UnlockedContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class _ClaimBarrierConnection:
    def __init__(
        self,
        connection,
        barrier,
        claim_threads,
        claim_threads_lock,
        non_atomic_claim=False,
    ):
        self.connection = connection
        self.barrier = barrier
        self.claim_threads = claim_threads
        self.claim_threads_lock = claim_threads_lock
        self.non_atomic_claim = non_atomic_claim

    def execute(self, statement, params=()):
        normalized = " ".join(statement.lower().split())
        if normalized == (
            "update app_state set value='true' where key='owner_setup_complete' "
            "and value='false'"
        ):
            observed = None
            if self.non_atomic_claim:
                observed = self.connection.execute(
                    "SELECT value FROM app_state WHERE key='owner_setup_complete'"
                ).fetchone()
            with self.claim_threads_lock:
                self.claim_threads.add(threading.get_ident())
            self.barrier.wait(timeout=10)
            if self.non_atomic_claim:
                if observed and observed["value"] == "false":
                    return self.connection.execute(
                        "UPDATE app_state SET value='true' "
                        "WHERE key='owner_setup_complete'"
                    )
                return self.connection.execute(
                    "UPDATE app_state SET value='true' "
                    "WHERE key='owner_setup_complete' AND 1=0"
                )
        return self.connection.execute(statement, params)

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def __enter__(self):
        self.connection.__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback):
        return self.connection.__exit__(exc_type, exc, traceback)


class OwnerPostgreSQLIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_database_gate = resolve_test_database_gate()
        if cls.test_database_gate is None:
            raise unittest.SkipTest(
                "TEST_DATABASE_URL and TEST_DATABASE_CONFIRMATION are not set; "
                "disposable PostgreSQL Owner gate skipped."
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
        claim_barrier = None
        non_atomic_claim = False
        claim_threads = set()
        claim_threads_lock = threading.Lock()

        def validated_connection(autocommit=False):
            return connect_validated_test_database(
                psycopg,
                self.test_database_gate.database_url,
                self.test_database_gate.confirmation,
                autocommit=autocommit,
                row_factory=dict_row,
                connect_timeout=10,
                prepare_threshold=None,
            )

        def isolated_db():
            connection = validated_connection()
            connection.execute(
                sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name))
            )
            compatible = server.PostgresCompat(connection)
            if claim_barrier is None:
                return compatible
            return _ClaimBarrierConnection(
                compatible,
                claim_barrier,
                claim_threads,
                claim_threads_lock,
                non_atomic_claim,
            )

        with validated_connection(autocommit=True) as admin:
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
                claim_barrier = threading.Barrier(2)
                try:
                    with (
                        patch.object(server, "LOCK", _UnlockedContext()),
                        ThreadPoolExecutor(max_workers=2) as executor,
                    ):
                        responses = list(
                            executor.map(
                                lambda candidate: self.request(
                                    "POST", "/api/owner/setup", candidate
                                ),
                                candidates,
                            )
                        )
                finally:
                    claim_barrier = None

                self.assertEqual(len(claim_threads), 2)
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
                second_login = self.request(
                    "POST", "/api/owner/login",
                    {"username": winner["username"], "password": winner["password"]},
                )
                self.assertEqual(second_login.status_code, 200)
                copied_owner_cookie = second_login.headers["set-cookie"].split(";", 1)[0]

                overview = self.request(
                    "GET", "/api/owner/overview", cookie=owner_cookie
                )
                self.assertEqual(overview.status_code, 200)
                self.assertEqual(
                    json.loads(overview.body)["health"],
                    {"backend": "healthy", "database": "healthy"},
                )

                # Representative release CRUD across every Owner domain. All writes
                # remain inside the randomly named schema created above.
                squad_member = self.request(
                    "POST", "/api/owner/squad-members",
                    {
                        "name": "Postgres Gate Leader", "ign": "PostgresGateLeader",
                        "gameId": "555001", "serverId": "5551",
                        "email": "postgres-gate-leader@example.test", "role": "Squad Leader",
                    }, owner_cookie,
                )
                self.assertEqual(squad_member.status_code, 201)
                community = self.request(
                    "POST", "/api/community/register",
                    {
                        "email": "postgres-gate-player@example.test",
                        "password": "member-password-123", "ign": "PostgresGatePlayer",
                        "gameId": "555002", "serverId": "5552",
                    },
                )
                self.assertEqual(community.status_code, 200)
                community_body = json.loads(community.body)
                account_id = community_body["account"]["id"]
                self.assertEqual(self.request(
                    "PATCH", f"/api/owner/community-accounts/{account_id}",
                    {"emailNotifications": False}, owner_cookie,
                ).status_code, 200)

                content_path = "/api/owner/squad-content/announcements/postgres-gate-note"
                self.assertEqual(self.request(
                    "POST", content_path,
                    {"title": "PostgreSQL gate", "body": "Representative content CRUD."},
                    owner_cookie,
                ).status_code, 201)
                self.assertEqual(self.request(
                    "PATCH", content_path,
                    {"title": "PostgreSQL gate updated", "body": "Transaction verified."},
                    owner_cookie,
                ).status_code, 200)
                self.assertEqual(self.request(
                    "DELETE", content_path, {}, owner_cookie,
                ).status_code, 200)

                season_response = self.request(
                    "POST", "/api/owner/seasons",
                    {"name": "PostgreSQL Gate Season", "requestId": "postgres-gate-season"},
                    owner_cookie,
                )
                self.assertEqual(season_response.status_code, 201)
                season_id = json.loads(season_response.body)["season"]["id"]
                event_response = self.request(
                    "POST", "/api/owner/events",
                    {"title": "PostgreSQL Gate Event", "date": "2099-12-20", "rewardPoints": 5},
                    owner_cookie,
                )
                self.assertEqual(event_response.status_code, 201)
                event_id = json.loads(event_response.body)["event"]["id"]
                self.assertEqual(self.request(
                    "POST", f"/api/owner/events/{event_id}/publish", {}, owner_cookie,
                ).status_code, 200)
                self.assertEqual(self.request(
                    "POST", f"/api/owner/events/{event_id}/participation",
                    {"accountId": account_id}, owner_cookie,
                ).status_code, 201)
                corrected_points = self.request(
                    "PATCH", f"/api/owner/season-points/{account_id}",
                    {"points": 15, "reason": "PostgreSQL transaction gate"}, owner_cookie,
                )
                self.assertEqual(corrected_points.status_code, 200)

                tournament_response = self.request(
                    "POST", "/api/owner/tournaments",
                    {
                        "title": "PostgreSQL Gate Cup", "game": "MLBB", "format": "1v1",
                        "date": "2099-12-21", "slots": 4,
                    }, owner_cookie,
                )
                self.assertEqual(tournament_response.status_code, 201)
                tournament_id = json.loads(tournament_response.body)["tournament"]["id"]
                self.assertEqual(self.request(
                    "PATCH", f"/api/owner/tournaments/{tournament_id}",
                    {"reward": "Gate Trophy"}, owner_cookie,
                ).status_code, 200)
                self.assertEqual(self.request(
                    "POST", f"/api/owner/tournaments/{tournament_id}/cancel", {}, owner_cookie,
                ).status_code, 200)
                self.assertEqual(self.request(
                    "POST", f"/api/owner/tournaments/{tournament_id}/reinstate", {}, owner_cookie,
                ).status_code, 200)

                self.assertEqual(self.request(
                    "POST", f"/api/owner/seasons/{season_id}/complete", {}, owner_cookie,
                ).status_code, 200)
                history = self.request("GET", "/api/owner/history", cookie=owner_cookie)
                self.assertEqual(history.status_code, 200)
                season_hall = json.loads(history.body)["seasonHallOfFame"]
                self.assertTrue(season_hall)
                corrected_history = self.request(
                    "PATCH",
                    f"/api/owner/history/season-hall-of-fame/{season_hall[0]['id']}",
                    {"points": 16, "reason": "Verified PostgreSQL history correction"},
                    owner_cookie,
                )
                self.assertEqual(corrected_history.status_code, 200)
                self.assertEqual(json.loads(corrected_history.body)["entry"]["points"], 16)
                self.assertEqual(
                    self.request("GET", "/api/owner/audit?limit=100", cookie=owner_cookie).status_code,
                    200,
                )
                self.assertEqual(
                    self.request("GET", "/api/owner/settings", cookie=owner_cookie).status_code,
                    200,
                )
                changed_settings = self.request(
                    "PATCH", "/api/owner/settings",
                    {
                        "currentPassword": winner["password"],
                        "newPassword": "postgres-owner-password-456",
                    }, owner_cookie,
                )
                self.assertEqual(changed_settings.status_code, 200)
                self.assertTrue(json.loads(self.request(
                    "GET", "/api/auth/me", cookie=owner_cookie,
                ).body)["authenticated"])
                self.assertFalse(json.loads(self.request(
                    "GET", "/api/auth/me", cookie=copied_owner_cookie,
                ).body)["authenticated"])

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
                    {"owner_setup": 1, "owner_login": 2, "owner_logout": 1},
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

                with server.LOCK, server.db() as connection:
                    for table in (
                        "sessions",
                        "audit_log",
                        "owner_accounts",
                        "squad_members",
                        "login_throttle",
                    ):
                        connection.execute(f"DELETE FROM {table}")
                    connection.execute(
                        "UPDATE app_state SET value='false' "
                        "WHERE key='owner_setup_complete'"
                    )
                    connection.commit()

                claim_threads.clear()
                claim_barrier = threading.Barrier(2)
                non_atomic_claim = True
                mutated_candidates = [
                    self.payload("mutated-owner-a", "MutatedOwnerA", "333333"),
                    self.payload("mutated-owner-b", "MutatedOwnerB", "444444"),
                ]
                try:
                    with (
                        patch.object(server, "LOCK", _UnlockedContext()),
                        ThreadPoolExecutor(max_workers=2) as executor,
                    ):
                        mutated_responses = list(
                            executor.map(
                                lambda candidate: self.request(
                                    "POST", "/api/owner/setup", candidate
                                ),
                                mutated_candidates,
                            )
                        )
                finally:
                    claim_barrier = None
                    non_atomic_claim = False

                self.assertEqual(len(claim_threads), 2)
                self.assertEqual(
                    sorted(response.status_code for response in mutated_responses),
                    [200, 200],
                    "the synchronized harness must expose a deliberately non-atomic setup claim",
                )
        finally:
            with validated_connection(autocommit=True) as admin:
                admin.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        sql.Identifier(schema_name)
                    )
                )


if __name__ == "__main__":
    unittest.main()
