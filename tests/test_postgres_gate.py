import unittest

from tests import http_harness


class PostgreSQLGateSafetyTests(unittest.TestCase):
    def resolver(self):
        resolver = getattr(http_harness, "resolve_test_database_url", None)
        self.assertIsNotNone(
            resolver,
            "the PostgreSQL release gate must provide an explicit environment guard",
        )
        return resolver

    def test_database_url_alone_never_enables_the_postgresql_gate(self):
        resolved = self.resolver()(
            {"DATABASE_URL": "postgresql://prod.example/prod"}
        )

        self.assertIsNone(resolved)

    def test_test_database_url_requires_disposable_database_confirmation(self):
        with self.assertRaisesRegex(RuntimeError, "disposable"):
            self.resolver()(
                {"TEST_DATABASE_URL": "postgresql://test.example/postgres"}
            )

    def test_gate_rejects_the_same_database_as_production_without_exposing_credentials(self):
        test_url = "postgresql://test-role@shared.example/postgres?sslmode=require"
        production_url = "postgresql://production-role@shared.example/postgres"

        with self.assertRaises(RuntimeError) as captured:
            self.resolver()(
                {
                    "TEST_DATABASE_URL": test_url,
                    "TEST_DATABASE_DISPOSABLE": "1",
                    "DATABASE_URL": production_url,
                }
            )

        self.assertNotIn("shared.example", str(captured.exception))

    def test_gate_accepts_only_an_explicit_confirmed_postgresql_test_url(self):
        test_url = "postgresql://test-project.example/postgres"

        resolved = self.resolver()(
            {
                "TEST_DATABASE_URL": test_url,
                "TEST_DATABASE_DISPOSABLE": "1",
                "DATABASE_URL": "postgresql://prod.example/postgres",
            }
        )

        self.assertEqual(resolved, test_url)

    def test_gate_rejects_non_postgresql_urls_without_exposing_them(self):
        unsafe_url = "sqlite:///sensitive-marker.sqlite3"

        with self.assertRaises(RuntimeError) as captured:
            self.resolver()(
                {
                    "TEST_DATABASE_URL": unsafe_url,
                    "TEST_DATABASE_DISPOSABLE": "1",
                }
            )

        self.assertNotIn("sensitive-marker", str(captured.exception))


if __name__ == "__main__":
    unittest.main()
