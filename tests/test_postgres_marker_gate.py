import unittest

from tests import http_harness


class _FakeMarkerResult:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _FakeMarkerConnection:
    def __init__(self, row=None, query_error=None):
        self.row = row
        self.query_error = query_error
        self.executions = []
        self.rollback_count = 0
        self.closed = False
        self.read_only = True
        self.autocommit = False

    def execute(self, statement, params=()):
        self.executions.append((statement, params))
        if self.query_error is not None:
            raise self.query_error
        return _FakeMarkerResult(self.row)

    def rollback(self):
        self.rollback_count += 1

    def close(self):
        self.closed = True


class _FakePsycopg:
    def __init__(self, connection):
        self.connection = connection
        self.calls = []

    def connect(self, database_url, **kwargs):
        self.calls.append((database_url, kwargs))
        return self.connection


class PostgreSQLMarkerGateTests(unittest.TestCase):
    DATABASE_URL = "postgresql://gate-user:synthetic-password@test.example:5432/postgres"
    CONFIRMATION = "unit-test-disposable-confirmation-0123456789"

    def connector(self):
        connector = getattr(
            http_harness,
            "connect_validated_test_database",
            None,
        )
        self.assertIsNotNone(
            connector,
            "the integration gate must validate a read-only marker before mutation",
        )
        return connector

    def assert_parameterized_marker_read(self, connection):
        self.assertGreaterEqual(len(connection.executions), 1)
        statement, params = connection.executions[0]
        normalized = " ".join(statement.upper().split())
        self.assertTrue(normalized.startswith("SELECT "))
        self.assertIn(
            "FROM PUBLIC.DARK_SYSTEM_DISPOSABLE_TEST_MARKER",
            normalized,
        )
        self.assertIn("WHERE MARKER_NAME=%S", normalized)
        for mutation in ("CREATE", "INSERT", "UPDATE", "DELETE", "DROP", "ALTER"):
            self.assertNotIn(mutation, normalized)
        self.assertEqual(params, ("dark-system-owner-release-gate-v1",))
        self.assertNotIn(self.CONFIRMATION, statement)
        self.assertNotIn(self.CONFIRMATION, params)

    def test_missing_mismatched_or_failed_marker_closes_without_mutation(self):
        cases = (
            (None, None),
            ({"confirmation": "different-synthetic-confirmation-value-1234"}, None),
            (None, RuntimeError("sensitive database failure")),
        )
        for row, query_error in cases:
            with self.subTest(row=row, query_error=type(query_error).__name__):
                connection = _FakeMarkerConnection(row=row, query_error=query_error)
                psycopg = _FakePsycopg(connection)

                with self.assertRaises(RuntimeError) as captured:
                    self.connector()(
                        psycopg,
                        self.DATABASE_URL,
                        self.CONFIRMATION,
                    )

                self.assertTrue(connection.closed)
                self.assertEqual(connection.rollback_count, 0)
                self.assertEqual(len(connection.executions), 1)
                self.assert_parameterized_marker_read(connection)
                message = str(captured.exception)
                self.assertNotIn(self.DATABASE_URL, message)
                self.assertNotIn(self.CONFIRMATION, message)
                self.assertNotIn("sensitive database failure", message)

    def test_exact_marker_match_returns_same_connection_after_read_only_preflight(self):
        connection = _FakeMarkerConnection(
            row={"confirmation": self.CONFIRMATION}
        )
        psycopg = _FakePsycopg(connection)

        returned = self.connector()(
            psycopg,
            self.DATABASE_URL,
            self.CONFIRMATION,
            autocommit=True,
            connect_timeout=10,
        )

        self.assertIs(returned, connection)
        self.assertFalse(connection.closed)
        self.assertEqual(connection.rollback_count, 1)
        self.assertFalse(connection.read_only)
        self.assertTrue(connection.autocommit)
        self.assert_parameterized_marker_read(connection)
        self.assertEqual(len(connection.executions), 2)
        write_transition, transition_params = connection.executions[1]
        self.assertEqual(
            " ".join(write_transition.upper().split()),
            "SET DEFAULT_TRANSACTION_READ_ONLY=OFF",
        )
        self.assertEqual(transition_params, ())
        self.assertEqual(len(psycopg.calls), 1)
        called_url, kwargs = psycopg.calls[0]
        self.assertEqual(called_url, self.DATABASE_URL)
        self.assertFalse(kwargs["autocommit"])
        self.assertIn("default_transaction_read_only=on", kwargs["options"])
        self.assertEqual(kwargs["connect_timeout"], 10)

    def test_invalid_confirmation_never_connects(self):
        connection = _FakeMarkerConnection()
        psycopg = _FakePsycopg(connection)

        with self.assertRaises(RuntimeError):
            self.connector()(psycopg, self.DATABASE_URL, "too-short")

        self.assertEqual(psycopg.calls, [])
        self.assertEqual(connection.executions, [])

    def test_gate_config_representation_redacts_url_and_confirmation(self):
        gate = http_harness.resolve_test_database_gate(
            {
                "TEST_DATABASE_URL": self.DATABASE_URL,
                "TEST_DATABASE_CONFIRMATION": self.CONFIRMATION,
            }
        )

        representation = repr(gate)

        self.assertNotIn(self.DATABASE_URL, representation)
        self.assertNotIn("synthetic-password", representation)
        self.assertNotIn(self.CONFIRMATION, representation)


if __name__ == "__main__":
    unittest.main()
