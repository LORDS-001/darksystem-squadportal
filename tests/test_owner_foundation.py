import unittest

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
