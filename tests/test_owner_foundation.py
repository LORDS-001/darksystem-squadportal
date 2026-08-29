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
