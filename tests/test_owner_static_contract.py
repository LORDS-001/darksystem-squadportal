import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class OwnerStaticContractTests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "owner-admin.html").read_text(encoding="utf-8")
        self.js = (ROOT / "owner-admin.js").read_text(encoding="utf-8")

    def test_owner_shell_defers_the_owner_script(self):
        self.assertIn('<script src="/owner-admin.js" defer>', self.html)

    def test_owner_client_declares_the_required_api_contract(self):
        for endpoint in (
            "/api/owner/setup/status",
            "/api/owner/setup",
            "/api/owner/login",
            "/api/auth/me",
            "/api/owner/overview",
            "/api/logout",
        ):
            self.assertIn(endpoint, self.js)

    def test_setup_form_collects_owner_and_initial_squad_credentials(self):
        for field in (
            'name: "username"',
            'name: "password"',
            'name: "passwordConfirmation"',
            'name: "ign"',
            'name: "gameId"',
            'name: "serverId"',
            'name: "accessCode"',
        ):
            self.assertIn(field, self.js)

    def test_login_form_uses_owner_credentials_with_correct_autocomplete(self):
        self.assertIn('autocomplete: "username"', self.js)
        self.assertIn('autocomplete: "current-password"', self.js)

    def test_dashboard_includes_foundation_sections_and_logout(self):
        for label in ("Overview", "Recent Activity", "Logout"):
            self.assertIn(label, self.js)

    def test_owner_ui_does_not_persist_browser_state(self):
        for source in (self.html, self.js):
            self.assertNotIn("localStorage", source)
            self.assertNotIn("sessionStorage", source)

    def test_owner_client_does_not_log_responses_or_credentials(self):
        self.assertNotIn("console.", self.js)


if __name__ == "__main__":
    unittest.main()
