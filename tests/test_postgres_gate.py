import unittest
from urllib.parse import urlsplit

from tests import http_harness


class PostgreSQLGateSafetyTests(unittest.TestCase):
    CONFIRMATION = "unit-test-disposable-confirmation-0123456789"

    def raw_resolver(self):
        resolver = getattr(http_harness, "resolve_test_database_url", None)
        self.assertIsNotNone(
            resolver,
            "the PostgreSQL release gate must provide an explicit environment guard",
        )
        return resolver

    def resolver(self):
        resolver = self.raw_resolver()

        def confirmed(environment):
            source = dict(environment)
            if source.get("TEST_DATABASE_URL"):
                source.setdefault(
                    "TEST_DATABASE_CONFIRMATION",
                    self.CONFIRMATION,
                )
            return resolver(source)

        return confirmed

    def test_database_url_alone_never_enables_the_postgresql_gate(self):
        resolved = self.resolver()(
            {"DATABASE_URL": "postgresql://prod.example/prod"}
        )

        self.assertIsNone(resolved)

    def test_test_database_url_and_confirmation_are_the_only_opt_in(self):
        test_url = "postgresql://gate-user@test.example/postgres"

        resolved = self.resolver()({"TEST_DATABASE_URL": test_url})

        parsed = urlsplit(resolved)
        self.assertEqual(parsed.hostname, "test.example")
        self.assertEqual(parsed.port, 5432)
        self.assertEqual(parsed.path, "/postgres")

    def test_gate_rejects_the_same_database_as_production_without_exposing_credentials(self):
        test_url = "postgresql://test-role@shared.example/postgres?sslmode=require"
        production_url = "postgresql://production-role@shared.example/postgres"

        with self.assertRaises(RuntimeError) as captured:
            self.resolver()(
                {
                    "TEST_DATABASE_URL": test_url,
                    "DATABASE_URL": production_url,
                }
            )

        self.assertNotIn("shared.example", str(captured.exception))

    def test_gate_accepts_an_explicit_separate_postgresql_test_url(self):
        test_url = "postgresql://gate-user@test-project.example/postgres"

        resolved = self.resolver()(
            {
                "TEST_DATABASE_URL": test_url,
                "DATABASE_URL": "postgresql://prod.example/postgres",
            }
        )

        self.assertEqual(
            resolved,
            "postgresql://gate-user@test-project.example:5432/postgres",
        )

    def test_gate_rejects_non_postgresql_urls_without_exposing_them(self):
        unsafe_url = "sqlite:///sensitive-marker.sqlite3"

        with self.assertRaises(RuntimeError) as captured:
            self.resolver()(
                {
                    "TEST_DATABASE_URL": unsafe_url,
                }
            )

        self.assertNotIn("sensitive-marker", str(captured.exception))

    def test_gate_rejects_keyword_test_dsn_without_exposing_it(self):
        unsafe_dsn = "host=test.example port=5432 dbname=postgres user=sensitive-role"

        with self.assertRaises(RuntimeError) as captured:
            self.resolver()({"TEST_DATABASE_URL": unsafe_dsn})

        self.assertNotIn("sensitive-role", str(captured.exception))

    def test_gate_fails_closed_when_production_uses_keyword_dsn(self):
        with self.assertRaisesRegex(RuntimeError, "DATABASE_URL"):
            self.resolver()(
                {
                    "TEST_DATABASE_URL": "postgresql://gate-user@test.example/postgres",
                    "DATABASE_URL": "host=prod.example port=5432 dbname=postgres",
                }
            )

    def test_gate_rejects_uri_query_target_overrides_on_either_target(self):
        overrides = (
            "host=override.example",
            "hostaddr=192.0.2.10",
            "port=6543",
            "dbname=other",
            "service=hidden-service",
            "servicefile=sensitive-service-file",
        )
        for override in overrides:
            with self.subTest(side="test", override=override):
                with self.assertRaises(RuntimeError):
                    self.resolver()(
                        {
                            "TEST_DATABASE_URL": (
                                f"postgresql://gate-user@test.example/postgres?{override}"
                            )
                        }
                    )
            with self.subTest(side="production", override=override):
                with self.assertRaises(RuntimeError):
                    self.resolver()(
                        {
                            "TEST_DATABASE_URL": "postgresql://gate-user@test.example/postgres",
                            "DATABASE_URL": (
                                f"postgresql://prod.example/postgres?{override}"
                            ),
                        }
                    )

    def test_gate_rejects_multihost_and_service_targets(self):
        unsafe_targets = (
            "postgresql://host-a.example,host-b.example/postgres",
            "postgresql://host-a.example:5432,host-b.example:5432/postgres",
            "service=dark-system-test",
            "postgresql://test.example/postgres?service=dark-system-test",
        )

        for unsafe_target in unsafe_targets:
            with self.subTest(target=unsafe_target):
                with self.assertRaises(RuntimeError):
                    self.resolver()({"TEST_DATABASE_URL": unsafe_target})

    def test_gate_canonicalizes_host_case_percent_encoding_and_default_port(self):
        with self.assertRaises(RuntimeError):
            self.resolver()(
                {
                    "TEST_DATABASE_URL": (
                        "postgresql://test-role@EXAMPLE%2Ecom.:5432/dark%2Dsystem"
                    ),
                    "DATABASE_URL": (
                        "postgres://production-role@example.com/dark-system"
                    ),
                }
            )

    def test_gate_rejects_every_target_affecting_libpq_environment_default(self):
        target_environment = {
            "PGHOST": "sensitive-pghost",
            "PGHOSTADDR": "sensitive-pghostaddr",
            "PGPORT": "6543",
            "PGDATABASE": "sensitive-pgdatabase",
            "PGSERVICE": "sensitive-pgservice",
            "PGSERVICEFILE": "sensitive-pgservicefile",
            "PGTARGETSESSIONATTRS": "sensitive-pgtargetsessionattrs",
            "PGLOADBALANCEHOSTS": "sensitive-pgloadbalancehosts",
            "PGSYSCONFDIR": "sensitive-pgsysconfdir",
            "PGUSER": "sensitive-pguser",
        }
        for variable, value in target_environment.items():
            environment = {
                "TEST_DATABASE_URL": "postgresql://test.example/postgres",
                variable: value,
            }
            with self.subTest(variable=variable):
                with self.assertRaises(RuntimeError) as captured:
                    self.resolver()(environment)
                self.assertNotIn(value, str(captured.exception))
                self.assertNotIn("test.example", str(captured.exception))

    def test_gate_rejects_omitted_port_bypass_from_ambient_pgport(self):
        with self.assertRaises(RuntimeError):
            self.resolver()(
                {
                    "TEST_DATABASE_URL": "postgresql://same.example/postgres",
                    "DATABASE_URL": "postgresql://same.example:6543/postgres",
                    "PGPORT": "6543",
                }
            )

    def test_gate_rejects_a_present_target_environment_variable_even_when_empty(self):
        with self.assertRaises(RuntimeError):
            self.resolver()(
                {
                    "TEST_DATABASE_URL": "postgresql://test.example/postgres",
                    "PGHOST": "",
                }
            )

    def test_gate_canonicalizes_equivalent_ipv6_literals(self):
        with self.assertRaises(RuntimeError):
            self.resolver()(
                {
                    "TEST_DATABASE_URL": (
                        "postgresql://test-role@[2001:0db8:0000:0000:0000:0000:0000:0001]:5432/postgres"
                    ),
                    "DATABASE_URL": (
                        "postgresql://production-role@[2001:db8::1]/postgres"
                    ),
                }
            )

    def test_gate_accepts_and_preserves_ordinary_supabase_pooler_uri(self):
        project_ref = "abcdefghijklmnopqrst"
        test_url = (
            f"postgresql://postgres.{project_ref}:encoded%40%3A%2F%3F%23password@"
            "aws-0-eu-west-1.pooler.supabase.com:6543/postgres?sslmode=require"
        )

        resolved = self.resolver()(
            {
                "TEST_DATABASE_URL": test_url,
                "DATABASE_URL": "postgresql://prod.example:5432/postgres",
            }
        )

        self.assertEqual(resolved, test_url)

    def test_gate_rejects_query_routing_options(self):
        for option in ("target_session_attrs=primary", "load_balance_hosts=random"):
            with self.subTest(option=option):
                with self.assertRaises(RuntimeError):
                    self.resolver()(
                        {
                            "TEST_DATABASE_URL": (
                                f"postgresql://gate-user@test.example/postgres?{option}"
                            )
                        }
                    )

    def test_gate_rejects_percent_decoded_authority_injection_without_leaking_it(self):
        encoded_hosts = (
            "attacker%40prod.example",
            "attacker%3Aprod.example",
            "attacker%2Fprod.example",
            "attacker%3Fprod.example",
            "attacker%23prod.example",
        )
        for encoded_host in encoded_hosts:
            with self.subTest(encoded_host=encoded_host):
                with self.assertRaises(RuntimeError) as captured:
                    self.resolver()(
                        {
                            "TEST_DATABASE_URL": (
                                f"postgresql://gate-user@{encoded_host}:5432/postgres"
                            )
                        }
                    )
                message = str(captured.exception)
                self.assertNotIn("attacker", message)
                self.assertNotIn("prod.example", message)
                self.assertNotIn(encoded_host, message)

    def test_gate_rejects_legacy_ipv4_aliases_of_production(self):
        aliases = (
            "127.1",
            "2130706433",
            "0177.0.0.1",
            "0x7f000001",
            "127.0.1",
            "0x7f.0.0.1",
        )
        for alias in aliases:
            with self.subTest(alias=alias):
                with self.assertRaises(RuntimeError):
                    self.resolver()(
                        {
                            "TEST_DATABASE_URL": (
                                f"postgresql://gate-user@{alias}:5432/postgres"
                            ),
                            "DATABASE_URL": (
                                "postgresql://production-user@127.0.0.1:5432/postgres"
                            ),
                        }
                    )

    def test_gate_requires_explicit_test_user_and_rejects_ambient_pguser(self):
        with self.assertRaises(RuntimeError):
            self.resolver()(
                {"TEST_DATABASE_URL": "postgresql://test.example:5432/postgres"}
            )

        with self.assertRaises(RuntimeError) as captured:
            self.resolver()(
                {
                    "TEST_DATABASE_URL": (
                        "postgresql://gate-user@test.example:5432/postgres"
                    ),
                    "PGUSER": "sensitive-ambient-user",
                }
            )
        self.assertNotIn("sensitive-ambient-user", str(captured.exception))

    def test_gate_treats_supabase_direct_and_pooler_routes_as_one_project(self):
        project_ref = "abcdefghijklmnopqrst"
        routes = (
            (
                f"postgresql://postgres:test-secret@db.{project_ref}.supabase.co:5432/postgres",
                f"postgresql://postgres.{project_ref}:prod-secret@aws-0-us-east-1.pooler.supabase.com:6543/postgres",
            ),
            (
                f"postgresql://postgres.{project_ref}:test-secret@aws-0-eu-west-1.pooler.supabase.com:5432/postgres",
                f"postgresql://postgres:prod-secret@db.{project_ref}.supabase.co:6543/postgres",
            ),
            (
                f"postgresql://postgres.{project_ref}:test-secret@aws-0-us-east-1.pooler.supabase.com:5432/postgres",
                f"postgresql://postgres.{project_ref}:prod-secret@aws-0-us-east-1.pooler.supabase.com:6543/postgres",
            ),
        )
        for test_url, production_url in routes:
            with self.subTest(test_host=urlsplit(test_url).hostname):
                with self.assertRaises(RuntimeError) as captured:
                    self.resolver()(
                        {
                            "TEST_DATABASE_URL": test_url,
                            "DATABASE_URL": production_url,
                        }
                    )
                message = str(captured.exception)
                self.assertNotIn(project_ref, message)
                self.assertNotIn("test-secret", message)
                self.assertNotIn("prod-secret", message)

    def test_gate_allows_separate_projects_on_the_same_supabase_pooler(self):
        test_ref = "abcdefghijklmnopqrst"
        production_ref = "zyxwvutsrqponmlkjihg"
        test_url = (
            f"postgresql://postgres.{test_ref}:encoded%40password@"
            "aws-0-eu-west-1.pooler.supabase.com:6543/postgres?sslmode=require"
        )

        resolved = self.resolver()(
            {
                "TEST_DATABASE_URL": test_url,
                "DATABASE_URL": (
                    f"postgresql://postgres.{production_ref}:production-secret@"
                    "aws-0-eu-west-1.pooler.supabase.com:6543/postgres"
                ),
            }
        )

        self.assertEqual(resolved, test_url)

    def test_gate_fails_closed_for_ambiguous_supabase_routing_forms(self):
        ambiguous_urls = (
            "postgresql://postgres:test-secret@aws-0-us-east-1.pooler.supabase.com:6543/postgres",
            "postgresql://postgres.short:test-secret@aws-0-us-east-1.pooler.supabase.com:6543/postgres",
            "postgresql://postgres:test-secret@db.short.supabase.co:5432/postgres",
        )
        for ambiguous_url in ambiguous_urls:
            with self.subTest(host=urlsplit(ambiguous_url).hostname):
                with self.assertRaises(RuntimeError) as captured:
                    self.resolver()({"TEST_DATABASE_URL": ambiguous_url})
                self.assertNotIn("test-secret", str(captured.exception))
            with self.subTest(production_host=urlsplit(ambiguous_url).hostname):
                with self.assertRaises(RuntimeError) as captured:
                    self.resolver()(
                        {
                            "TEST_DATABASE_URL": (
                                "postgresql://gate-user@test.example:5432/postgres"
                            ),
                            "DATABASE_URL": ambiguous_url,
                        }
                    )
                self.assertNotIn("test-secret", str(captured.exception))

    def test_gate_requires_a_strong_explicit_database_confirmation(self):
        test_url = "postgresql://gate-user@test.example:5432/postgres"

        for environment in (
            {"TEST_DATABASE_URL": test_url},
            {
                "TEST_DATABASE_URL": test_url,
                "TEST_DATABASE_CONFIRMATION": "too-short",
            },
            {
                "TEST_DATABASE_URL": test_url,
                "TEST_DATABASE_CONFIRMATION": "contains spaces and is long enough to be unsafe",
            },
            {
                "TEST_DATABASE_URL": test_url,
                "TEST_DATABASE_CONFIRMATION": f" {self.CONFIRMATION} ",
            },
        ):
            with self.subTest(confirmation=environment.get("TEST_DATABASE_CONFIRMATION")):
                with self.assertRaises(RuntimeError) as captured:
                    self.raw_resolver()(environment)
                self.assertNotIn("too-short", str(captured.exception))
                self.assertNotIn("contains spaces", str(captured.exception))

        self.assertIsNone(
            self.raw_resolver()(
                {"TEST_DATABASE_CONFIRMATION": self.CONFIRMATION}
            )
        )

    def test_gate_rejects_ipv4_mapped_ipv6_in_both_comparison_directions(self):
        routes = (
            (
                "postgresql://gate-user@[::ffff:127.0.0.1]:5432/postgres",
                "postgresql://production-user@127.0.0.1:5432/postgres",
            ),
            (
                "postgresql://gate-user@127.0.0.1:5432/postgres",
                "postgresql://production-user@[::ffff:7f00:1]:5432/postgres",
            ),
        )
        for test_url, production_url in routes:
            with self.subTest(test_host=urlsplit(test_url).hostname):
                with self.assertRaises(RuntimeError):
                    self.resolver()(
                        {
                            "TEST_DATABASE_URL": test_url,
                            "DATABASE_URL": production_url,
                        }
                    )


if __name__ == "__main__":
    unittest.main()
