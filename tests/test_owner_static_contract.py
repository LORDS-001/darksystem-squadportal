import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class OwnerStaticContractTests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "owner-admin.html").read_text(encoding="utf-8")
        self.js = (ROOT / "owner-admin.js").read_text(encoding="utf-8")
        self.css = (ROOT / "owner-admin.css").read_text(encoding="utf-8")

    def test_owner_shell_defers_the_owner_script(self):
        self.assertIn('<script src="/owner-admin.js" defer>', self.html)

    def test_owner_shell_loads_modular_administration_clients(self):
        for module in (
            "owner-admin-api.js", "owner-admin-squad.js",
            "owner-admin-tournaments.js", "owner-admin-seasons.js",
            "owner-admin-audit.js",
        ):
            self.assertIn(f'<script src="/{module}" defer>', self.html)

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
            'name: "setupSecret"',
            'name: "username"',
            'name: "password"',
            'name: "passwordConfirmation"',
            'name: "ign"',
            'name: "gameId"',
            'name: "serverId"',
            'name: "accessCode"',
        ):
            self.assertIn(field, self.js)

    def test_setup_secret_is_submitted_and_cleared_on_every_form_exit(self):
        self.assertIn("setupSecret: setupSecret.input.value", self.js)
        self.assertIn("function clearOwnerSetupSecrets()", self.js)
        self.assertGreaterEqual(self.js.count("clearOwnerSetupSecrets();"), 3)

    def test_login_form_uses_owner_credentials_with_correct_autocomplete(self):
        self.assertIn('autocomplete: "username"', self.js)
        self.assertIn('autocomplete: "current-password"', self.js)

    def test_dashboard_includes_foundation_sections_and_logout(self):
        for label in (
            "Overview", "Squads", "Community", "Content", "Tournaments",
            "Seasons & Rankings", "Events & History", "Audit", "Settings",
            "Recent Activity", "Logout",
        ):
            self.assertIn(label, self.js)

    def test_dashboard_has_accessible_refresh_and_status_regions(self):
        self.assertIn('aria-live', self.js)
        self.assertIn('Refresh', self.js)
        self.assertIn('.focus()', self.js)

    def test_owner_ui_does_not_persist_browser_state(self):
        for source in (self.html, self.js):
            self.assertNotIn("localStorage", source)
            self.assertNotIn("sessionStorage", source)

    def test_owner_client_does_not_log_responses_or_credentials(self):
        self.assertNotIn("console.", self.js)

    def test_owner_workspace_keeps_responsive_sharp_established_visual_contract(self):
        self.assertIn("@media (max-width: 850px)", self.css)
        self.assertIn("@media (max-width: 560px)", self.css)
        self.assertIn("grid-template-columns: 1fr", self.css)
        self.assertIn("border-radius: 0 !important", self.css)
        self.assertIn("Orbitron", self.css)
        self.assertIn("Rajdhani", self.css)

    def test_owner_squad_creation_uses_registered_email_and_recovery_not_credentials(self):
        create_block = self.js.split('ownerForm("Create Squad member"', 1)[1].split('ownerForm("Edit Squad member', 1)[0]
        self.assertIn('{ name: "email", label: "Registered email", type: "email" }', create_block)
        self.assertNotIn('name: "accessCode"', create_block)
        self.assertIn("recovery required", create_block.lower())


if __name__ == "__main__":
    unittest.main()
