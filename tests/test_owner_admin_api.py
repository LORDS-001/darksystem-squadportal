import json
import sqlite3
import unittest
from unittest.mock import patch

import server
from tests.http_harness import BackendHarness


class OwnerAuditAndSettingsTests(unittest.TestCase):
    def setUp(self):
        self.backend = BackendHarness()
        setup = self.backend.request("POST", "/api/owner/setup", {
            "setupSecret": BackendHarness.OWNER_SETUP_SECRET,
            "username": "audit-owner", "password": "owner-password-123",
            "squadOwner": {"ign": "AuditOwner", "gameId": "900001", "serverId": "9001", "accessCode": "OWNER-CODE"},
        })
        self.assertEqual(setup.status, 200)
        login = self.backend.request("POST", "/api/owner/login", {
            "username": "audit-owner", "password": "owner-password-123",
        })
        self.cookie = login.headers["Set-Cookie"].split(";", 1)[0]

    def tearDown(self):
        self.backend.close()

    def test_audit_filters_and_cursor_pagination_are_safe(self):
        with server.LOCK, server.db() as connection:
            owner = {"type": "owner", "id": "actor-filter", "role": "Overall Owner"}
            for index in range(4):
                server.insert_audit(connection, owner, "filtered_action" if index < 3 else "different_action",
                                    "squad_member", f"target-{index}", {"password": "never-return", "index": index})
            connection.commit()
        first = self.backend.request("GET", "/api/owner/audit?action=filtered_action&actor=actor-filter&target=target&limit=2", cookie=self.cookie)
        self.assertEqual(first.status, 200)
        self.assertEqual(len(first.json["audit"]), 2)
        self.assertTrue(first.json["nextCursor"])
        self.assertNotIn("never-return", str(first.json).lower())
        second = self.backend.request("GET", f"/api/owner/audit?action=filtered_action&actor=actor-filter&target=target&limit=2&cursor={first.json['nextCursor']}", cookie=self.cookie)
        self.assertEqual(len(second.json["audit"]), 1)
        self.assertFalse(second.json["nextCursor"])
        self.assertTrue(set(item["id"] for item in first.json["audit"]).isdisjoint(item["id"] for item in second.json["audit"]))

    def test_audit_date_validation_and_owner_guard(self):
        self.assertEqual(self.backend.request("GET", "/api/owner/audit?from=not-a-date", cookie=self.cookie).status, 400)
        self.assertEqual(self.backend.request("GET", "/api/owner/settings").status, 401)

    def test_owner_settings_password_change_requires_current_password_and_revokes_other_sessions(self):
        second_login = self.backend.request("POST", "/api/owner/login", {
            "username": "audit-owner", "password": "owner-password-123",
        })
        second_cookie = second_login.headers["Set-Cookie"].split(";", 1)[0]
        settings = self.backend.request("GET", "/api/owner/settings", cookie=self.cookie)
        self.assertEqual(settings.status, 200)
        self.assertEqual(settings.json["settings"]["username"], "audit-owner")
        self.assertNotIn("password", str(settings.json).lower())
        denied = self.backend.request("PATCH", "/api/owner/settings", {
            "currentPassword": "wrong-password", "newPassword": "new-owner-password-456",
        }, cookie=self.cookie)
        self.assertEqual(denied.status, 403)
        changed = self.backend.request("PATCH", "/api/owner/settings", {
            "currentPassword": "owner-password-123", "newPassword": "new-owner-password-456",
        }, cookie=self.cookie)
        self.assertEqual(changed.status, 200)
        self.assertTrue(self.backend.request("GET", "/api/auth/me", cookie=self.cookie).json["authenticated"])
        self.assertFalse(self.backend.request("GET", "/api/auth/me", cookie=second_cookie).json["authenticated"])
        self.assertEqual(self.backend.request("POST", "/api/owner/login", {
            "username": "audit-owner", "password": "owner-password-123",
        }).status, 401)
        self.assertEqual(self.backend.request("POST", "/api/owner/login", {
            "username": "audit-owner", "password": "new-owner-password-456",
        }).status, 200)

    def test_access_code_hash_never_serializes_and_owner_cannot_set_member_credentials(self):
        with server.LOCK, server.db() as connection:
            row = connection.execute("SELECT * FROM squad_members WHERE id='1'").fetchone()
            connection.execute("UPDATE squad_members SET access_code_hash=? WHERE id='1'", (server.hash_password("OWNER-CODE"),))
            connection.commit()
            row = connection.execute("SELECT * FROM squad_members WHERE id='1'").fetchone()
        self.assertNotIn("access_code_hash", server.public_member(row, True))
        self.assertNotIn("access_code_hash", server.public_member(row, False))
        listed = self.backend.request("GET", "/api/owner/squad-members", cookie=self.cookie)
        self.assertNotIn("access_code_hash", str(listed.json))
        rejected = self.backend.request("PATCH", "/api/owner/squad-members/1", {"accessCode": "OWNER-ROTATE"}, cookie=self.cookie)
        self.assertEqual(rejected.status, 400)

    def test_owner_events_reject_impossible_calendar_dates(self):
        created = self.backend.request("POST", "/api/owner/events", {"title": "Impossible", "date": "2026-02-30"}, cookie=self.cookie)
        self.assertEqual(created.status, 400)


class OwnerAdministrationSecurityTests(unittest.TestCase):
    def setUp(self):
        self.backend = BackendHarness()

    def tearDown(self):
        self.backend.close()

    def setup_owner(self):
        response = self.backend.request(
            "POST",
            "/api/owner/setup",
            {
                "setupSecret": BackendHarness.OWNER_SETUP_SECRET,
                "username": "overall-owner",
                "password": "owner-password-123",
                "squadOwner": {
                    "ign": "DarkOwner",
                    "gameId": "123456",
                    "serverId": "1234",
                    "accessCode": "DS-OWNER",
                },
            },
        )
        self.assertEqual(response.status, 200)

    def register_community(self, email, role="Community Member"):
        response = self.backend.request(
            "POST",
            "/api/community/register",
            {
                "email": email,
                "password": "member-password-123",
                "ign": "BoundaryMember",
                "gameId": "654321",
                "serverId": "4321",
                "phone": "+234-555-0100",
                "role": role,
            },
        )
        self.assertEqual(response.status, 200)
        return response

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

    def ordinary_squad_cookie(self):
        with server.LOCK, server.db() as connection:
            connection.execute(
                """INSERT INTO squad_members
                   (id,name,ign,game_id,server_id,role,access_code,status,profile_complete,account_activated)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    "ordinary-squad", "Ordinary Squad Member", "OrdinarySquad",
                    "777777", "7777", "Squad Member", "DS-ORDINARY",
                    "Offline", 1, 1,
                ),
            )
            connection.commit()
        response = self.backend.request(
            "POST",
            "/api/squad/login",
            {
                "ign": "OrdinarySquad",
                "gameId": "777777",
                "serverId": "7777",
                "accessCode": "DS-ORDINARY",
            },
        )
        self.assertEqual(response.status, 200)
        return response.headers["Set-Cookie"].split(";", 1)[0]

    def test_community_registration_ignores_submitted_privileged_roles(self):
        for index, role in enumerate(
            ("Tournament Manager", "Squad Owner", "Overall Owner")
        ):
            with self.subTest(role=role):
                response = self.register_community(
                    f"privilege-{index}@example.test", role
                )
                self.assertEqual(response.json["account"]["role"], "Community Member")
                with server.LOCK, server.db() as connection:
                    row = connection.execute(
                        "SELECT role FROM community_accounts WHERE id=?",
                        (response.json["account"]["id"],),
                    ).fetchone()
                self.assertEqual(row["role"], "Community Member")

    def test_public_bootstrap_contains_only_the_public_projection(self):
        self.register_community("bootstrap-contact@example.test")
        with server.LOCK, server.db() as connection:
            server.state_set(
                connection,
                "registrations",
                [{"id": "private-registration", "accountId": "secret-account"}],
            )
            server.state_set(
                connection,
                "tournamentManagers",
                [{"id": "secret-manager"}],
            )
            connection.commit()

        response = self.backend.request("GET", "/api/bootstrap")

        self.assertEqual(response.status, 200)
        payload = response.json
        self.assertEqual(set(payload["community"]), {"accounts", "tournaments"})
        profile = next(
            item for item in payload["community"]["accounts"]
            if item["ign"] == "BoundaryMember"
        )
        self.assertTrue({"id", "ign", "role", "lane"}.issubset(profile))
        self.assertNotIn("email", profile)
        self.assertNotIn("phone", profile)
        self.assertNotIn("registrations", payload["community"])
        self.assertNotIn("tournamentManagers", payload["community"])
        self.assertNotIn("seasonPoints", payload["community"])
        self.assertNotIn("squadTournamentApprovals", payload["community"])
        serialized = json.dumps(payload).lower()
        self.assertNotIn("bootstrap-contact@example.test", serialized)
        self.assertNotIn("+234-555-0100", serialized)
        self.assertNotIn("private-registration", serialized)
        self.assertNotIn("secret-manager", serialized)

    def test_authenticated_community_bootstrap_preserves_its_tournament_workflow_without_contact_data(self):
        registration = self.register_community("community-bootstrap@example.test")
        account = registration.json["account"]
        cookie = registration.headers["Set-Cookie"].split(";", 1)[0]
        with server.LOCK, server.db() as connection:
            server.state_set(
                connection,
                "tournaments",
                [{"id": "workflow", "title": "Workflow", "matches": [{"id": "match-1", "status": "Pending"}]}],
            )
            server.state_set(
                connection,
                "registrations",
                [
                    {"id": "mine", "accountId": account["id"], "tournamentId": "workflow"},
                    {"id": "other", "accountId": "other-account", "tournamentId": "workflow"},
                ],
            )
            server.state_set(
                connection,
                "community_notifications",
                [
                    {"id": "mine-notice", "audienceId": account["id"], "message": "Mine"},
                    {"id": "other-notice", "audienceId": "other-account", "message": "Other"},
                ],
            )
            server.state_set(
                connection,
                "eventParticipation",
                [
                    {"id": "mine-event", "accountId": account["id"]},
                    {"id": "other-event", "accountId": "other-account"},
                ],
            )
            connection.commit()

        response = self.backend.request("GET", "/api/bootstrap", cookie=cookie)

        self.assertEqual(response.status, 200)
        community = response.json["community"]
        self.assertTrue({"accounts", "tournaments", "registrations", "notifications", "eventParticipation"}.issubset(community))
        self.assertEqual(community["tournaments"][0]["matches"][0]["id"], "match-1")
        self.assertEqual([item["id"] for item in community["registrations"]], ["mine"])
        self.assertEqual([item["id"] for item in community["notifications"]], ["mine-notice"])
        self.assertEqual([item["id"] for item in community["eventParticipation"]], ["mine-event"])
        serialized = json.dumps(response.json).lower()
        self.assertNotIn("community-bootstrap@example.test", serialized)
        self.assertNotIn("+234-555-0100", serialized)

    def test_tournament_manager_identity_supports_string_and_legacy_dictionary_entries(self):
        session = {"id": "delegated-manager", "role": "Squad Member"}

        self.assertTrue(
            server.tournament_manager_identity(session, ["delegated-manager"])
        )
        self.assertTrue(
            server.tournament_manager_identity(
                session, [{"id": "delegated-manager"}]
            )
        )
        self.assertTrue(
            server.tournament_manager_identity(
                session, [{"accountId": "delegated-manager"}]
            )
        )
        self.assertFalse(
            server.tournament_manager_identity(
                session,
                [
                    "different-manager",
                    {"id": "different-legacy-manager"},
                    {"accountId": "different-legacy-account"},
                ],
            )
        )

    def test_ordinary_community_and_squad_bootstrap_reject_nonmatching_string_manager(self):
        community = self.register_community("ordinary-bootstrap@example.test")
        community_cookie = community.headers["Set-Cookie"].split(";", 1)[0]
        self.setup_owner()
        squad_cookie = self.ordinary_squad_cookie()
        with server.LOCK, server.db() as connection:
            server.state_set(
                connection,
                "tournamentManagers",
                [
                    "different-manager",
                    {"id": "different-legacy-manager"},
                    {"accountId": "different-legacy-account"},
                ],
            )
            server.state_set(
                connection,
                "tournaments",
                [{
                    "id": "private-workflow", "title": "Private Workflow",
                    "leaderAccessCode": "PRIVATE-LEADER-CODE",
                }],
            )
            server.state_set(
                connection,
                "squadTournamentApprovals",
                [{
                    "id": "private-approval", "tournamentId": "private-workflow",
                    "leaderAccountId": "different-community", "status": "Approved",
                    "memberAccessCode": "PRIVATE-MEMBER-CODE",
                }],
            )
            connection.commit()

        for actor, cookie in (
            ("community", community_cookie),
            ("squad", squad_cookie),
        ):
            with self.subTest(actor=actor):
                response = self.backend.request("GET", "/api/bootstrap", cookie=cookie)
                self.assertEqual(response.status, 200)
                serialized = json.dumps(response.json)
                self.assertNotIn("PRIVATE-LEADER-CODE", serialized)
                self.assertNotIn("PRIVATE-MEMBER-CODE", serialized)

    def test_authenticated_bootstrap_scopes_tournament_codes_to_distributors(self):
        leader = self.register_community("approval-leader@example.test")
        leader_cookie = leader.headers["Set-Cookie"].split(";", 1)[0]
        member = self.register_community("approval-member@example.test")
        member_cookie = member.headers["Set-Cookie"].split(";", 1)[0]
        self.setup_owner()
        squad_cookie = self.squad_cookie()
        approvals = [
            {
                "id": "approval-1", "tournamentId": "squad-tournament",
                "leaderAccountId": leader.json["account"]["id"], "status": "Approved",
                "memberAccessCode": "MEMBER-WORKFLOW-CODE",
            },
            {
                "id": "approval-2", "tournamentId": "squad-tournament",
                "leaderAccountId": "other-leader", "status": "Approved",
                "memberAccessCode": "OTHER-MEMBER-CODE",
            },
            {
                "id": "approval-3", "tournamentId": "other-tournament",
                "leaderAccountId": leader.json["account"]["id"], "status": "Pending",
                "memberAccessCode": "PREMATURE-MEMBER-CODE",
            },
        ]
        tournaments = [{
            "id": "squad-tournament", "title": "Squad Tournament",
            "format": "Squad vs Squad", "leaderAccessCode": "TOURNAMENT-LEADER-CODE",
        }]
        with server.LOCK, server.db() as connection:
            server.state_set(connection, "squadTournamentApprovals", approvals)
            server.state_set(connection, "tournaments", tournaments)
            connection.commit()

        leader_bootstrap = self.backend.request("GET", "/api/bootstrap", cookie=leader_cookie)
        member_bootstrap = self.backend.request("GET", "/api/bootstrap", cookie=member_cookie)
        squad_bootstrap = self.backend.request("GET", "/api/bootstrap", cookie=squad_cookie)

        self.assertEqual(leader_bootstrap.status, 200)
        self.assertEqual(
            leader_bootstrap.json["community"]["squadTournamentApprovals"][0]["memberAccessCode"],
            "MEMBER-WORKFLOW-CODE",
        )
        self.assertNotIn(
            "TOURNAMENT-LEADER-CODE", json.dumps(leader_bootstrap.json)
        )
        self.assertNotIn("OTHER-MEMBER-CODE", json.dumps(leader_bootstrap.json))
        self.assertNotIn("PREMATURE-MEMBER-CODE", json.dumps(leader_bootstrap.json))
        self.assertNotIn("TOURNAMENT-LEADER-CODE", json.dumps(member_bootstrap.json))
        self.assertNotIn("MEMBER-WORKFLOW-CODE", json.dumps(member_bootstrap.json))
        self.assertNotIn("OTHER-MEMBER-CODE", json.dumps(member_bootstrap.json))
        self.assertEqual(
            squad_bootstrap.json["community"]["tournaments"][0]["leaderAccessCode"],
            "TOURNAMENT-LEADER-CODE",
        )
        self.assertEqual(
            squad_bootstrap.json["community"]["squadTournamentApprovals"][1]["memberAccessCode"],
            "OTHER-MEMBER-CODE",
        )
        synced = self.backend.request(
            "PUT", "/api/state",
            {"squad": squad_bootstrap.json["squad"], "community": squad_bootstrap.json["community"]},
            cookie=squad_cookie,
        )
        self.assertEqual(synced.status, 200)
        with server.LOCK, server.db() as connection:
            self.assertEqual(server.state_get(connection, "squadTournamentApprovals", [])[0]["memberAccessCode"], "MEMBER-WORKFLOW-CODE")
            self.assertEqual(server.state_get(connection, "tournaments", [])[0]["leaderAccessCode"], "TOURNAMENT-LEADER-CODE")

    def test_community_leader_code_is_validated_server_side_and_identity_cannot_be_spoofed(self):
        community = self.register_community("server-leader@example.test")
        cookie = community.headers["Set-Cookie"].split(";", 1)[0]
        account = community.json["account"]
        with server.LOCK, server.db() as connection:
            server.state_set(
                connection,
                "tournaments",
                [{
                    "id": "squad-tournament", "title": "Squad Tournament",
                    "format": "Squad vs Squad", "status": "Open",
                    "registrationOpen": True, "squadRegistrationOpen": True,
                    "squadSlots": 4, "membersPerSquad": 7,
                    "leaderAccessCode": "LEADER-SERVER-CODE",
                }],
            )
            connection.commit()

        rejected = self.backend.request(
            "POST", "/api/tournaments/squad-approval",
            {
                "action": "submit_leader", "tournamentId": "squad-tournament",
                "accessCode": "WRONG-CODE", "leaderAccountId": "spoofed-account",
                "squad": {"squadName": "Boundary Squad", "squadId": "BS-1"},
            },
            cookie=cookie,
        )
        self.assertEqual(rejected.status, 403)

        accepted = self.backend.request(
            "POST", "/api/tournaments/squad-approval",
            {
                "action": "submit_leader", "tournamentId": "squad-tournament",
                "accessCode": "leader-server-code", "leaderAccountId": "spoofed-account",
                "squad": {
                    "squadName": "Boundary Squad", "squadId": "BS-1",
                    "leaderIgn": "Spoofed IGN", "leaderGameId": "000000",
                    "leaderServerId": "0000",
                },
            },
            cookie=cookie,
        )

        self.assertEqual(accepted.status, 201)
        approval = accepted.json["approval"]
        self.assertEqual(approval["leaderAccountId"], account["id"])
        self.assertEqual(approval["leaderIgn"], account["ign"])
        self.assertEqual(approval["leaderGameId"], account["gameId"])
        self.assertEqual(approval["leaderServerId"], account["serverId"])
        self.assertNotIn("LEADER-SERVER-CODE", json.dumps(accepted.json))
        with server.LOCK, server.db() as connection:
            stored = server.state_get(connection, "squadTournamentApprovals", [])
        self.assertEqual(len(stored), 1)
        self.assertNotIn("accessCode", stored[0])

    def test_expired_deadline_rejects_leader_code_when_open_flags_are_stale(self):
        community = self.register_community("expired-leader@example.test")
        cookie = community.headers["Set-Cookie"].split(";", 1)[0]
        with server.LOCK, server.db() as connection:
            server.state_set(
                connection,
                "tournaments",
                [{
                    "id": "expired-squad-tournament", "title": "Expired Squad Tournament",
                    "format": "Squad vs Squad", "status": "Open",
                    "registrationOpen": True, "squadRegistrationOpen": True,
                    "registrationDeadline": "2000-01-01T23:59:59Z",
                    "squadSlots": 4, "membersPerSquad": 7,
                    "leaderAccessCode": "EXPIRED-LEADER-CODE",
                }],
            )
            connection.commit()

        response = self.backend.request(
            "POST",
            "/api/tournaments/squad-approval",
            {
                "action": "submit_leader",
                "tournamentId": "expired-squad-tournament",
                "accessCode": "EXPIRED-LEADER-CODE",
                "squad": {"squadName": "Late Squad", "squadId": "LATE-1"},
            },
            cookie=cookie,
        )

        self.assertEqual(response.status, 409)
        self.assertEqual(response.json["error"], "Squad registration is closed.")
        with server.LOCK, server.db() as connection:
            self.assertEqual(
                server.state_get(connection, "squadTournamentApprovals", []), []
            )

    def test_community_member_joins_through_server_without_downloading_approval_codes(self):
        community = self.register_community("server-member@example.test")
        cookie = community.headers["Set-Cookie"].split(";", 1)[0]
        account = community.json["account"]
        with server.LOCK, server.db() as connection:
            server.state_set(
                connection,
                "tournaments",
                [{
                    "id": "squad-tournament", "title": "Squad Tournament",
                    "format": "Squad vs Squad", "status": "Open",
                    "registrationOpen": True, "membersPerSquad": 7,
                }],
            )
            server.state_set(
                connection,
                "squadTournamentApprovals",
                [{
                    "id": "approval-1", "tournamentId": "squad-tournament",
                    "status": "Approved", "squadName": "Boundary Squad",
                    "squadId": "BS-1", "leaderAccountId": "leader-account",
                    "membersPerSquad": 7, "memberAccessCode": "MEMBER-SERVER-CODE",
                }],
            )
            connection.commit()

        rejected = self.backend.request(
            "POST", "/api/tournaments/squad-approval",
            {
                "action": "join_member", "tournamentId": "squad-tournament",
                "accessCode": "WRONG-CODE", "accountId": "spoofed-account",
            },
            cookie=cookie,
        )
        self.assertEqual(rejected.status, 403)

        accepted = self.backend.request(
            "POST", "/api/tournaments/squad-approval",
            {
                "action": "join_member", "tournamentId": "squad-tournament",
                "accessCode": "member-server-code", "accountId": "spoofed-account",
            },
            cookie=cookie,
        )

        self.assertEqual(accepted.status, 201)
        registration = accepted.json["registration"]
        self.assertEqual(registration["accountId"], account["id"])
        self.assertEqual(registration["ign"], account["ign"])
        self.assertEqual(registration["squadApprovalId"], "approval-1")
        self.assertNotIn("MEMBER-SERVER-CODE", json.dumps(accepted.json))
        duplicate = self.backend.request(
            "POST", "/api/tournaments/squad-approval",
            {
                "action": "join_member", "tournamentId": "squad-tournament",
                "accessCode": "MEMBER-SERVER-CODE",
            },
            cookie=cookie,
        )
        self.assertEqual(duplicate.status, 409)

    def test_expired_deadline_rejects_member_code_when_open_flags_are_stale(self):
        community = self.register_community("expired-member@example.test")
        cookie = community.headers["Set-Cookie"].split(";", 1)[0]
        with server.LOCK, server.db() as connection:
            server.state_set(
                connection,
                "tournaments",
                [{
                    "id": "expired-squad-tournament", "title": "Expired Squad Tournament",
                    "format": "Squad vs Squad", "status": "Open",
                    "registrationOpen": True, "squadRegistrationOpen": True,
                    "registrationDeadline": "2000-01-01T23:59:59Z",
                    "membersPerSquad": 7,
                }],
            )
            server.state_set(
                connection,
                "squadTournamentApprovals",
                [{
                    "id": "expired-approval", "tournamentId": "expired-squad-tournament",
                    "status": "Approved", "squadName": "Late Squad",
                    "squadId": "LATE-1", "leaderAccountId": "different-account",
                    "membersPerSquad": 7, "memberAccessCode": "EXPIRED-MEMBER-CODE",
                }],
            )
            connection.commit()

        response = self.backend.request(
            "POST",
            "/api/tournaments/squad-approval",
            {
                "action": "join_member",
                "tournamentId": "expired-squad-tournament",
                "accessCode": "EXPIRED-MEMBER-CODE",
            },
            cookie=cookie,
        )

        self.assertEqual(response.status, 409)
        self.assertEqual(response.json["error"], "Squad registration is closed.")
        with server.LOCK, server.db() as connection:
            self.assertEqual(server.state_get(connection, "registrations", []), [])

    def test_legacy_state_sync_cannot_bypass_squad_member_code_validation(self):
        community = self.register_community("sync-bypass@example.test")
        cookie = community.headers["Set-Cookie"].split(";", 1)[0]
        account_id = community.json["account"]["id"]
        with server.LOCK, server.db() as connection:
            server.state_set(
                connection,
                "tournaments",
                [{"id": "squad-tournament", "format": "Squad vs Squad", "status": "Open"}],
            )
            connection.commit()

        response = self.backend.request(
            "PUT", "/api/state",
            {
                "squad": {},
                "community": {
                    "registrations": [{
                        "id": "forged-registration", "tournamentId": "squad-tournament",
                        "accountId": account_id, "squadApprovalId": "forged-approval",
                    }],
                },
            },
            cookie=cookie,
        )

        self.assertEqual(response.status, 200)
        with server.LOCK, server.db() as connection:
            registrations = server.state_get(connection, "registrations", [])
        self.assertEqual(registrations, [])

    def test_authorized_squad_bootstrap_round_trip_preserves_member_contact_and_access_code_data(self):
        self.setup_owner()
        cookie = self.squad_cookie()
        with server.LOCK, server.db() as connection:
            connection.execute(
                "UPDATE squad_members SET email=?,phone=?,birthday=?,access_code=? WHERE id='1'",
                ("squad-owner@example.test", "+234-555-0199", "2000-01-01", "PRESERVED-ACCESS-CODE"),
            )
            server.state_set(connection, "reports", [{"id": "report-1", "memberId": "1", "body": "Ready"}])
            server.state_set(connection, "complaints", [{"id": "complaint-1", "memberId": "1", "body": "Private"}])
            server.state_set(connection, "reportConfig", {"title": "Daily Report", "fields": []})
            server.state_set(
                connection,
                "tournaments",
                [{"id": "squad-workflow", "matches": [{"id": "match-2", "status": "Pending"}]}],
            )
            connection.commit()

        response = self.backend.request("GET", "/api/bootstrap", cookie=cookie)

        self.assertEqual(response.status, 200)
        squad = response.json["squad"]
        self.assertEqual(squad["reports"][0]["id"], "report-1")
        self.assertEqual(squad["complaints"][0]["id"], "complaint-1")
        self.assertEqual(squad["reportConfig"]["title"], "Daily Report")
        self.assertEqual(response.json["community"]["tournaments"][0]["matches"][0]["id"], "match-2")
        member = next(item for item in squad["members"] if item["id"] == "1")
        self.assertEqual(member["email"], "squad-owner@example.test")
        self.assertEqual(member["phone"], "+234-555-0199")
        self.assertEqual(member["birthday"], "2000-01-01")
        self.assertEqual(member["accessCode"], "PRESERVED-ACCESS-CODE")

        synced = self.backend.request(
            "PUT", "/api/state", {"squad": squad, "community": response.json["community"]}, cookie=cookie
        )
        self.assertEqual(synced.status, 200)
        with server.LOCK, server.db() as connection:
            stored = connection.execute(
                "SELECT email,phone,birthday,access_code FROM squad_members WHERE id='1'"
            ).fetchone()
        self.assertEqual(
            dict(stored),
            {
                "email": "squad-owner@example.test",
                "phone": "+234-555-0199",
                "birthday": "2000-01-01",
                "access_code": "PRESERVED-ACCESS-CODE",
            },
        )

    def test_owner_collections_require_an_overall_owner_session(self):
        community = self.register_community("guard-community@example.test")
        community_cookie = community.headers["Set-Cookie"].split(";", 1)[0]
        self.setup_owner()
        squad_cookie = self.squad_cookie()
        manager = self.register_community("guard-manager@example.test")
        manager_cookie = manager.headers["Set-Cookie"].split(";", 1)[0]
        with server.LOCK, server.db() as connection:
            connection.execute(
                "UPDATE community_accounts SET role='Tournament Manager' WHERE id=?",
                (manager.json["account"]["id"],),
            )
            connection.commit()

        for endpoint in ("/api/owner/overview", "/api/owner/audit"):
            with self.subTest(endpoint=endpoint, actor="anonymous"):
                self.assertEqual(self.backend.request("GET", endpoint).status, 401)
            for actor, cookie in (
                ("community", community_cookie),
                ("squad", squad_cookie),
                ("tournament-manager", manager_cookie),
            ):
                with self.subTest(endpoint=endpoint, actor=actor):
                    self.assertEqual(
                        self.backend.request("GET", endpoint, cookie=cookie).status,
                        403,
                    )

    def test_owner_collection_serializers_are_secret_excluding_allowlists(self):
        member = server.safe_owner_squad_member(
            {
                "id": "member-1", "name": "Member", "ign": "MemberIGN", "game_id": "123456",
                "server_id": "1234", "role": "Squad Member", "lane": "Mid", "email": "member@example.test",
                "phone": "+234-555-0101", "birthday": "2000-01-01", "access_code": "MEMBER-ACCESS",
                "status": "Offline", "last_login": None, "profile_complete": 1, "account_activated": 1,
                "password_hash": "unexpected-member-hash",
            }
        )
        account = server.safe_owner_community_account(
            {
                "id": "community-1", "squad_member_id": "member-1", "ign": "CommunityIGN",
                "game_id": "654321", "server_id": "4321", "email": "community@example.test",
                "phone": "+234-555-0102", "password_hash": "COMMUNITY-HASH", "role": "Community Member",
                "lane": "Gold", "created_at": "2099-01-01T00:00:00Z", "email_notifications": 1,
                "reset_code": "COMMUNITY-RESET", "reset_expires": 2_000_000_000, "linked_squad": 0,
            }
        )

        self.assertEqual(set(member), {"id", "name", "ign", "gameId", "serverId", "role", "lane", "email", "phone", "birthday", "status", "lastLogin", "profileComplete", "accountActivated"})
        self.assertEqual(set(account), {"id", "squadMemberId", "ign", "gameId", "serverId", "email", "phone", "role", "lane", "createdAt", "emailNotifications", "linkedSquad", "status"})
        self.assertNotIn("MEMBER-ACCESS", json.dumps(member))
        self.assertNotIn("COMMUNITY-HASH", json.dumps(account))
        self.assertNotIn("COMMUNITY-RESET", json.dumps(account))

    def test_audit_storage_redacts_secret_keys_and_historical_credential_strings(self):
        self.setup_owner()
        with server.LOCK, server.db() as connection:
            server.insert_audit(
                connection,
                {"type": "owner", "id": "owner-1", "role": "Overall Owner"},
                "audit_string_redaction",
                "system",
                "system",
                {
                    "code": "HISTORICAL-CODE-123",
                    "context": "password is historical-password; token was historical-token; access code: HISTORICAL-ACCESS",
                    "nested": {"recoveryCode": "HISTORICAL-RECOVERY", "summary": "Member disabled"},
                },
            )
            connection.commit()
            row = connection.execute(
                "SELECT details FROM audit_log WHERE action='audit_string_redaction'"
            ).fetchone()

        details = json.loads(row["details"])
        serialized = json.dumps(details).lower()
        for secret in (
            "historical-code-123",
            "historical-password",
            "historical-token",
            "historical-access",
            "historical-recovery",
        ):
            self.assertNotIn(secret.lower(), serialized)
        self.assertEqual(details["nested"], {"summary": "Member disabled"})
        self.assertIn("[redacted]", details["context"])

    def test_owner_audit_never_returns_credentials_or_session_tokens(self):
        self.setup_owner()
        owner_cookie = self.owner_cookie()
        owner_token = owner_cookie.split("=", 1)[1]
        community = self.register_community("audit-reset@example.test")
        with server.LOCK, server.db() as connection:
            member = connection.execute("SELECT access_code_hash FROM squad_members LIMIT 1").fetchone()
            connection.execute(
                "UPDATE community_accounts SET reset_code=?,reset_expires=? WHERE id=?",
                ("owner-audit-reset-code", 2_000_000_000, community.json["account"]["id"]),
            )
            server.insert_audit(
                connection,
                {"type": "owner", "id": "owner-1", "role": "Overall Owner"},
                "stored_secret_redaction",
                "community_account",
                community.json["account"]["id"],
                {"note": "owner-audit-reset-code", "summary": "safe"},
            )
            connection.execute(
                "INSERT INTO audit_log(id,actor_type,actor_id,actor_role,action,target_type,target_id,created_at,details) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    "owner-audit-secret-test",
                    "owner",
                    "owner-1",
                    "Overall Owner",
                    "test_secret_redaction",
                    "system",
                    "system",
                    "2099-01-01T00:00:00Z",
                    json.dumps(
                        {
                            "passwordHash": "owner-audit-password-hash",
                            "accessCode": member["access_code_hash"],
                            "resetCode": "owner-audit-reset-code",
                            "sessionToken": owner_token,
                        }
                    ),
                ),
            )
            connection.commit()

        with server.LOCK, server.db() as connection:
            stored = connection.execute(
                "SELECT details FROM audit_log WHERE action='stored_secret_redaction'"
            ).fetchone()["details"]
        self.assertNotIn("owner-audit-reset-code", stored)
        self.assertEqual(json.loads(stored), {"summary": "safe"})

        response = self.backend.request("GET", "/api/owner/audit", cookie=owner_cookie)

        self.assertEqual(response.status, 200)
        serialized = json.dumps(response.json).lower()
        for secret in (
            "owner-audit-password-hash",
            member["access_code_hash"].lower(),
            "owner-audit-reset-code",
            owner_token.lower(),
        ):
            self.assertNotIn(secret, serialized)
        row = next(
            item
            for item in response.json["audit"]
            if item["id"] == "owner-audit-secret-test"
        )
        self.assertEqual(row["details"], {})


class OwnerAccountAdministrationTests(unittest.TestCase):
    def setUp(self):
        self.backend = BackendHarness()
        setup = self.backend.request(
            "POST", "/api/owner/setup", {
                "setupSecret": BackendHarness.OWNER_SETUP_SECRET,
                "username": "overall-owner", "password": "owner-password-123",
                "squadOwner": {
                    "ign": "DarkOwner", "gameId": "123456", "serverId": "1234",
                    "accessCode": "DS-OWNER",
                },
            },
        )
        self.assertEqual(setup.status, 200)
        login = self.backend.request(
            "POST", "/api/owner/login",
            {"username": "overall-owner", "password": "owner-password-123"},
        )
        self.assertEqual(login.status, 200)
        self.owner_cookie = login.headers["Set-Cookie"].split(";", 1)[0]

    def tearDown(self):
        self.backend.close()

    def owner_request(self, method, path, payload=None):
        return self.backend.request(method, path, payload, cookie=self.owner_cookie)

    def create_member(self, ign="NewMember", game_id="789012", server_id="7890", **extra):
        payload = {
            "name": "New Member", "ign": ign, "gameId": game_id,
            "serverId": server_id, "accessCode": "NEW-MEMBER-CODE",
        }
        payload.update(extra)
        response = self.owner_request("POST", "/api/owner/squad-members", payload)
        self.assertEqual(response.status, 201)
        self.assertNotIn("NEW-MEMBER-CODE", json.dumps(response.json))
        return response.json["member"]

    def register_community(self, email="community@example.test"):
        response = self.backend.request(
            "POST", "/api/community/register", {
                "email": email, "password": "member-password-123",
                "ign": "CommunityPlayer", "gameId": "555555", "serverId": "5555",
            },
        )
        self.assertEqual(response.status, 200)
        return response

    def test_owner_squad_list_filters_pages_and_excludes_access_codes(self):
        first = self.create_member("AlphaMember", "100001", "1001")
        second = self.create_member("BravoMember", "100002", "1002", role="Squad Leader")

        page = self.owner_request(
            "GET", "/api/owner/squad-members?search=member&limit=1"
        )
        self.assertEqual(page.status, 200)
        self.assertEqual(len(page.json["members"]), 1)
        self.assertIn("nextCursor", page.json)
        self.assertNotIn("accessCode", page.json["members"][0])
        following = self.owner_request(
            "GET", f"/api/owner/squad-members?limit=10&cursor={page.json['nextCursor']}"
        )
        self.assertEqual(following.status, 200)
        self.assertTrue({first["id"], second["id"]}.intersection(
            {item["id"] for item in page.json["members"] + following.json["members"]}
        ))
        leaders = self.owner_request("GET", "/api/owner/squad-members?role=Squad%20Leader")
        self.assertEqual(leaders.status, 200)
        self.assertEqual([item["id"] for item in leaders.json["members"]], [second["id"]])

    def test_owner_member_update_disables_and_revokes_session_without_disclosing_code(self):
        member = self.create_member()
        login = self.backend.request(
            "POST", "/api/squad/login", {
                "ign": "NewMember", "gameId": "789012", "serverId": "7890",
                "accessCode": "NEW-MEMBER-CODE",
            },
        )
        self.assertEqual(login.status, 200)
        copied_cookie = login.headers["Set-Cookie"].split(";", 1)[0]

        changed = self.owner_request(
            "PATCH", f"/api/owner/squad-members/{member['id']}",
            {"role": "Squad Leader", "status": "Disabled"},
        )

        self.assertEqual(changed.status, 200)
        self.assertEqual(changed.json["member"]["status"], "Disabled")
        self.assertEqual(changed.json["member"]["role"], "Squad Leader")
        self.assertNotIn("ROTATED-CODE", json.dumps(changed.json))
        self.assertEqual(
            self.backend.request("GET", "/api/auth/me", cookie=copied_cookie).json,
            {"authenticated": False, "session": None},
        )

    def test_owner_member_rejects_duplicate_identity_and_cannot_remove_active_squad_owner(self):
        self.create_member("UniqueMember", "900001", "9001")
        duplicate = self.owner_request(
            "POST", "/api/owner/squad-members", {
                "name": "Duplicate", "ign": "AnotherName", "gameId": "900001",
                "serverId": "9002", "accessCode": "DUPLICATE-CODE",
            },
        )
        self.assertEqual(duplicate.status, 409)
        protected = self.owner_request("DELETE", "/api/owner/squad-members/1")
        self.assertEqual(protected.status, 409)

    def test_owner_appointment_replaces_squad_owner_atomically_and_revokes_demoted_owner(self):
        member = self.create_member("Replacement", "800001", "8001")
        old_login = self.backend.request(
            "POST", "/api/squad/login", {
                "ign": "DarkOwner", "gameId": "123456", "serverId": "1234",
                "accessCode": "DS-OWNER",
            },
        )
        old_cookie = old_login.headers["Set-Cookie"].split(";", 1)[0]

        response = self.owner_request("POST", "/api/owner/squad-owner", {"memberId": member["id"]})

        self.assertEqual(response.status, 200)
        self.assertEqual(response.json["member"]["role"], "Squad Owner")
        with server.LOCK, server.db() as connection:
            owners = connection.execute(
                "SELECT id FROM squad_members WHERE role='Squad Owner'"
            ).fetchall()
        self.assertEqual([row["id"] for row in owners], [member["id"]])
        self.assertEqual(
            self.backend.request("GET", "/api/auth/me", cookie=old_cookie).json,
            {"authenticated": False, "session": None},
        )

    def test_owner_community_list_and_status_update_revoke_session_and_are_audited(self):
        created = self.register_community()
        account = created.json["account"]
        cookie = created.headers["Set-Cookie"].split(";", 1)[0]

        listed = self.owner_request("GET", "/api/owner/community-accounts?search=community")
        self.assertEqual(listed.status, 200)
        self.assertEqual([item["id"] for item in listed.json["accounts"]], [account["id"]])
        self.assertNotIn("password", json.dumps(listed.json).lower())
        updated = self.owner_request(
            "PATCH", f"/api/owner/community-accounts/{account['id']}",
            {"ign": "AdminEdited", "status": "Disabled", "emailNotifications": False},
        )
        self.assertEqual(updated.status, 200)
        self.assertEqual(updated.json["account"]["status"], "Disabled")
        self.assertEqual(updated.json["account"]["ign"], "AdminEdited")
        self.assertEqual(
            self.backend.request("GET", "/api/auth/me", cookie=cookie).json,
            {"authenticated": False, "session": None},
        )
        audit = self.owner_request("GET", "/api/owner/audit")
        self.assertTrue(any(
            row["action"] == "owner_community_account_update" and row["actor_role"] == "Overall Owner"
            for row in audit.json["audit"]
        ))

    def test_every_owner_account_route_rejects_anonymous_and_community_sessions(self):
        community = self.register_community("route-guard@example.test")
        community_cookie = community.headers["Set-Cookie"].split(";", 1)[0]
        squad_login = self.backend.request(
            "POST", "/api/squad/login", {
                "ign": "DarkOwner", "gameId": "123456", "serverId": "1234", "accessCode": "DS-OWNER",
            },
        )
        self.assertEqual(squad_login.status, 200)
        squad_cookie = squad_login.headers["Set-Cookie"].split(";", 1)[0]
        manager = self.register_community("route-manager@example.test")
        manager_cookie = manager.headers["Set-Cookie"].split(";", 1)[0]
        with server.LOCK, server.db() as connection:
            connection.execute("UPDATE community_accounts SET role='Tournament Manager' WHERE id=?", (manager.json["account"]["id"],))
            connection.commit()
        routes = (
            ("GET", "/api/owner/squad-members", None),
            ("POST", "/api/owner/squad-members", {}),
            ("PATCH", "/api/owner/squad-members/1", {}),
            ("DELETE", "/api/owner/squad-members/1", {}),
            ("POST", "/api/owner/squad-owner", {}),
            ("GET", "/api/owner/community-accounts", None),
            ("PATCH", f"/api/owner/community-accounts/{community.json['account']['id']}", {}),
        )
        for method, path, payload in routes:
            with self.subTest(path=path, actor="anonymous"):
                self.assertEqual(self.backend.request(method, path, payload).status, 401)
            with self.subTest(path=path, actor="community"):
                self.assertEqual(
                    self.backend.request(method, path, payload, cookie=community_cookie).status,
                    403,
                )
            with self.subTest(path=path, actor="squad"):
                self.assertEqual(
                    self.backend.request(method, path, payload, cookie=squad_cookie).status,
                    403,
                )
            with self.subTest(path=path, actor="tournament-manager"):
                self.assertEqual(
                    self.backend.request(method, path, payload, cookie=manager_cookie).status,
                    403,
                )

    def test_disabled_or_deactivated_accounts_cannot_log_in_again(self):
        member = self.create_member()
        disabled = self.owner_request(
            "PATCH", f"/api/owner/squad-members/{member['id']}", {"status": "Disabled"}
        )
        self.assertEqual(disabled.status, 200)
        self.assertEqual(self.backend.request(
            "POST", "/api/squad/login", {
                "ign": "NewMember", "gameId": "789012", "serverId": "7890",
                "accessCode": "NEW-MEMBER-CODE",
            },
        ).status, 401)
        reactivated = self.owner_request(
            "PATCH", f"/api/owner/squad-members/{member['id']}",
            {"status": "Offline", "accountActivated": False},
        )
        self.assertEqual(reactivated.status, 200)
        self.assertEqual(self.backend.request(
            "POST", "/api/squad/login", {
                "ign": "NewMember", "gameId": "789012", "serverId": "7890",
                "accessCode": "NEW-MEMBER-CODE",
            },
        ).status, 401)
        community = self.register_community("disabled-login@example.test")
        update = self.owner_request(
            "PATCH", f"/api/owner/community-accounts/{community.json['account']['id']}",
            {"status": "Disabled"},
        )
        self.assertEqual(update.status, 200)
        self.assertEqual(self.backend.request(
            "POST", "/api/community/login",
            {"email": "disabled-login@example.test", "password": "member-password-123"},
        ).status, 401)

    def test_legacy_member_routes_preserve_owner_invariant_revoke_and_hide_codes_from_overall_owner(self):
        member = self.create_member()
        owner_login = self.backend.request(
            "POST", "/api/squad/login", {
                "ign": "DarkOwner", "gameId": "123456", "serverId": "1234", "accessCode": "DS-OWNER",
            },
        )
        owner_cookie = owner_login.headers["Set-Cookie"].split(";", 1)[0]
        blocked = self.owner_request("POST", "/api/squad/role", {"memberId": "1", "role": "Squad Member"})
        self.assertEqual(blocked.status, 409)
        promoted = self.owner_request("POST", "/api/squad/role", {"memberId": member["id"], "role": "Squad Owner"})
        self.assertEqual(promoted.status, 200)
        self.assertNotIn("accessCode", promoted.json["member"])
        self.assertEqual(self.backend.request("GET", "/api/auth/me", cookie=owner_cookie).json,
                         {"authenticated": False, "session": None})
        disabled = self.owner_request(
            "PUT", "/api/squad/members", {"id": "1", "status": "Disabled"}
        )
        self.assertEqual(disabled.status, 200)
        self.assertNotIn("accessCode", disabled.json["member"])
        self.assertEqual(self.owner_request(
            "PUT", "/api/squad/members", {"id": "1", "status": "Unknown"}
        ).status, 400)
        self.assertEqual(self.owner_request(
            "DELETE", "/api/squad/members", {"id": member["id"]}
        ).status, 409)

    def test_owner_collection_cursor_requires_the_same_filter_and_non_object_payload_is_controlled(self):
        first = self.create_member("LeaderOne", "400001", "4001", role="Squad Leader")
        second = self.create_member("LeaderTwo", "400002", "4002", role="Squad Leader")
        first_page = self.owner_request("GET", "/api/owner/squad-members?role=Squad%20Leader&limit=1")
        self.assertEqual(first_page.status, 200)
        second_page = self.owner_request(
            "GET", "/api/owner/squad-members?role=Squad%20Leader&limit=1&cursor=" + first_page.json["nextCursor"]
        )
        self.assertEqual(second_page.status, 200)
        self.assertEqual(
            {item["id"] for item in first_page.json["members"] + second_page.json["members"]},
            {first["id"], second["id"]},
        )
        self.assertEqual(
            self.owner_request("POST", "/api/owner/squad-members", []).status,
            400,
        )

    def test_squad_identity_indexes_reject_a_duplicate_insert_at_database_boundary(self):
        member = self.create_member("DatabaseUnique", "300001", "3001")
        with server.LOCK, server.db() as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """INSERT INTO squad_members(id,name,ign,game_id,server_id,role,access_code,status)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    ("duplicate-identity", "Duplicate", "databaseunique", "999999", "9999",
                     "Squad Member", "DUPLICATE-CODE", "Offline"),
                )
        self.assertIsNotNone(member["id"])

    def test_squad_owner_partial_unique_index_rejects_a_second_owner(self):
        member = self.create_member("SecondOwner", "310001", "3101")
        with server.LOCK, server.db() as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE squad_members SET role='Squad Owner' WHERE id=?", (member["id"],))

    def test_rejected_state_sync_leaves_state_and_audit_unchanged(self):
        owner_login = self.backend.request("POST", "/api/squad/login", {
            "ign": "DarkOwner", "gameId": "123456", "serverId": "1234", "accessCode": "DS-OWNER",
        })
        self.assertEqual(owner_login.status, 200)
        owner_cookie = owner_login.headers["Set-Cookie"].split(";", 1)[0]
        with server.LOCK, server.db() as connection:
            original_announcements = server.state_get(connection, "announcements", [])
            audit_before = connection.execute("SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        rejected = self.backend.request("PUT", "/api/state", {
            "squad": {
                "announcements": [{"id": "should-not-persist", "title": "Invalid sync"}],
                "members": [{
                    "id": "1", "name": "Dark System Owner", "ign": "DarkOwner",
                    "gameId": "123456", "serverId": "1234", "status": "Disabled",
                    "profileComplete": True, "accountActivated": True,
                }],
            },
            "community": {},
        }, cookie=owner_cookie)
        self.assertEqual(rejected.status, 409)
        with server.LOCK, server.db() as connection:
            self.assertEqual(server.state_get(connection, "announcements", []), original_announcements)
            self.assertEqual(connection.execute("SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"], audit_before)

    def test_state_sync_cannot_disable_or_deactivate_the_active_squad_owner_and_revokes_disabled_member(self):
        member = self.create_member("SyncTarget", "200001", "2001")
        member_login = self.backend.request(
            "POST", "/api/squad/login", {
                "ign": "SyncTarget", "gameId": "200001", "serverId": "2001", "accessCode": "NEW-MEMBER-CODE",
            },
        )
        self.assertEqual(member_login.status, 200)
        member_cookie = member_login.headers["Set-Cookie"].split(";", 1)[0]
        owner_login = self.backend.request(
            "POST", "/api/squad/login", {
                "ign": "DarkOwner", "gameId": "123456", "serverId": "1234", "accessCode": "DS-OWNER",
            },
        )
        owner_cookie = owner_login.headers["Set-Cookie"].split(";", 1)[0]
        disabled = self.backend.request(
            "PUT", "/api/state", {"squad": {"members": [{
                "id": member["id"], "name": member["name"], "ign": member["ign"],
                "gameId": member["gameId"], "serverId": member["serverId"], "status": "Disabled",
                "profileComplete": False, "accountActivated": True,
            }]}, "community": {}}, cookie=owner_cookie,
        )
        self.assertEqual(disabled.status, 200)
        self.assertEqual(self.backend.request("GET", "/api/auth/me", cookie=member_cookie).json,
                         {"authenticated": False, "session": None})
        blocked = self.backend.request(
            "PUT", "/api/state", {"squad": {"members": [{
                "id": "1", "name": "Dark System Owner", "ign": "DarkOwner", "gameId": "123456",
                "serverId": "1234", "status": "Disabled", "profileComplete": True, "accountActivated": True,
            }]}, "community": {}}, cookie=owner_cookie,
        )
        self.assertEqual(blocked.status, 409)

    def test_deactivated_squad_session_is_rejected_and_removed_by_authentication(self):
        member = self.create_member("DeactivateAuth", "210001", "2101")
        login = self.backend.request("POST", "/api/squad/login", {
            "ign": "DeactivateAuth", "gameId": "210001", "serverId": "2101", "accessCode": "NEW-MEMBER-CODE",
        })
        self.assertEqual(login.status, 200)
        cookie = login.headers["Set-Cookie"].split(";", 1)[0]
        token_hash = server.session_token_hash(cookie.split("=", 1)[1])
        with server.LOCK, server.db() as connection:
            connection.execute("UPDATE squad_members SET account_activated=0 WHERE id=?", (member["id"],))
            connection.commit()
        self.assertEqual(self.backend.request("GET", "/api/auth/me", cookie=cookie).json,
                         {"authenticated": False, "session": None})
        with server.LOCK, server.db() as connection:
            self.assertIsNone(connection.execute("SELECT token FROM sessions WHERE token=?", (token_hash,)).fetchone())

    def test_owner_routes_reject_non_boolean_fields_and_map_identity_races_to_conflict(self):
        member = self.create_member("BooleanTarget", "220001", "2201")
        self.assertEqual(self.owner_request(
            "PATCH", f"/api/owner/squad-members/{member['id']}", {"profileComplete": "false"}
        ).status, 400)
        community = self.register_community("boolean-community@example.test")
        self.assertEqual(self.owner_request(
            "PATCH", f"/api/owner/community-accounts/{community.json['account']['id']}", {"emailNotifications": "false"}
        ).status, 400)
        with patch.object(server, "identity_conflict", return_value=False):
            race = self.owner_request("POST", "/api/owner/squad-members", {
                "name": "Race", "ign": "BooleanTarget", "gameId": "990001", "serverId": "9901",
                "accessCode": "RACE-CODE",
            })
        self.assertEqual(race.status, 409)


class OwnerSquadContentAdministrationTests(unittest.TestCase):
    """Owner-only, compatibility-safe Squad content administration."""

    def setUp(self):
        self.backend = BackendHarness()
        setup = self.backend.request(
            "POST", "/api/owner/setup", {
                "setupSecret": BackendHarness.OWNER_SETUP_SECRET,
                "username": "content-owner", "password": "owner-password-123",
                "squadOwner": {
                    "ign": "ContentOwner", "gameId": "123456", "serverId": "1234",
                    "accessCode": "DS-CONTENT-OWNER",
                },
            },
        )
        self.assertEqual(setup.status, 200)
        login = self.backend.request(
            "POST", "/api/owner/login",
            {"username": "content-owner", "password": "owner-password-123"},
        )
        self.assertEqual(login.status, 200)
        self.owner_cookie = login.headers["Set-Cookie"].split(";", 1)[0]

    def tearDown(self):
        self.backend.close()

    def owner_request(self, method, path, payload=None, cookie=None):
        return self.backend.request(method, path, payload, cookie=cookie or self.owner_cookie)

    @staticmethod
    def content_cases():
        return {
            "announcements": {"title": "Roster call", "body": "Report before 19:00."},
            "reports": {"title": "Match report", "body": "The roster is ready."},
            "complaints": {"subject": "Conduct", "body": "Review this report."},
            "events": {"title": "Practice", "date": "2099-05-01", "time": "19:00", "description": "Scrim."},
            "notifications": {"title": "Owner notice", "message": "The schedule changed."},
        }

    def test_owner_content_crud_uses_the_allowed_domain_shapes_and_audits_mutations(self):
        """Removing field validation, CRUD persistence, or transaction audit breaks this contract."""
        for index, (domain, payload) in enumerate(self.content_cases().items()):
            content_id = f"content-{index}"
            with self.subTest(domain=domain):
                created = self.owner_request(
                    "POST", f"/api/owner/squad-content/{domain}/{content_id}",
                    {**payload, "accessCode": "OWNER-CONTENT-SECRET", "actorRole": "Squad Owner"},
                )
                self.assertEqual(created.status, 201)
                self.assertEqual(created.json["item"]["id"], content_id)
                self.assertNotIn("accessCode", created.json["item"])
                self.assertNotIn("actorRole", created.json["item"])
                self.assertIn("createdAt", created.json["item"])

                listed = self.owner_request("GET", f"/api/owner/squad-content?domain={domain}")
                self.assertEqual(listed.status, 200)
                self.assertEqual(listed.json["domain"], domain)
                self.assertIn(content_id, [item["id"] for item in listed.json["items"]])

                updated_payload = dict(payload)
                if domain == "notifications":
                    updated_payload["message"] = "The schedule was moved."
                elif domain == "events":
                    updated_payload["description"] = "Scrim moved to a new time."
                else:
                    updated_payload["body"] = "Updated by the Overall Owner."
                updated = self.owner_request(
                    "PATCH", f"/api/owner/squad-content/{domain}/{content_id}", updated_payload,
                )
                self.assertEqual(updated.status, 200)
                self.assertEqual(updated.json["item"]["id"], content_id)

                deleted = self.owner_request(
                    "DELETE", f"/api/owner/squad-content/{domain}/{content_id}", {},
                )
                self.assertEqual(deleted.status, 200)
                self.assertTrue(deleted.json["ok"])

        audit = self.owner_request("GET", "/api/owner/audit")
        self.assertEqual(audit.status, 200)
        actions = {item["action"] for item in audit.json["audit"]}
        self.assertIn("owner_squad_content_create", actions)
        self.assertIn("owner_squad_content_update", actions)
        self.assertIn("owner_squad_content_delete", actions)
        self.assertNotIn("owner-content-secret", json.dumps(audit.json).lower())

    def test_owner_content_rejects_unknown_domains_and_invalid_domain_payloads(self):
        """Removing the allowlist or a domain requirement must fail these requests."""
        self.assertEqual(
            self.owner_request("GET", "/api/owner/squad-content?domain=secrets").status,
            400,
        )
        self.assertEqual(
            self.owner_request("POST", "/api/owner/squad-content/secrets/item-1", {"title": "Nope"}).status,
            400,
        )
        for domain in self.content_cases():
            with self.subTest(domain=domain):
                self.assertEqual(
                    self.owner_request(
                        "POST", f"/api/owner/squad-content/{domain}/invalid-{domain}", {},
                    ).status,
                    400,
                )

    def test_every_owner_content_route_requires_an_overall_owner_session(self):
        """Changing the common Owner guard must not expose a content read or mutation."""
        community = self.backend.request("POST", "/api/community/register", {
            "email": "content-community@example.test", "password": "member-password-123",
            "ign": "ContentCommunity", "gameId": "654321", "serverId": "4321",
        })
        self.assertEqual(community.status, 200)
        community_cookie = community.headers["Set-Cookie"].split(";", 1)[0]
        squad = self.backend.request("POST", "/api/squad/login", {
            "ign": "ContentOwner", "gameId": "123456", "serverId": "1234", "accessCode": "DS-CONTENT-OWNER",
        })
        self.assertEqual(squad.status, 200)
        squad_cookie = squad.headers["Set-Cookie"].split(";", 1)[0]
        manager = self.backend.request("POST", "/api/community/register", {
            "email": "content-manager@example.test", "password": "member-password-123",
            "ign": "ContentManager", "gameId": "654322", "serverId": "4322",
        })
        self.assertEqual(manager.status, 200)
        manager_cookie = manager.headers["Set-Cookie"].split(";", 1)[0]
        with server.LOCK, server.db() as connection:
            connection.execute("UPDATE community_accounts SET role='Tournament Manager' WHERE id=?", (manager.json["account"]["id"],))
            connection.commit()

        routes = (
            ("GET", "/api/owner/squad-content?domain=announcements", None),
            ("POST", "/api/owner/squad-content/announcements/auth-content", {"title": "Title", "body": "Body"}),
            ("PATCH", "/api/owner/squad-content/announcements/auth-content", {"title": "Title", "body": "Body"}),
            ("DELETE", "/api/owner/squad-content/announcements/auth-content", {}),
        )
        for method, path, payload in routes:
            with self.subTest(method=method, path=path, actor="anonymous"):
                self.assertEqual(self.backend.request(method, path, payload).status, 401)
            for actor, cookie in (("community", community_cookie), ("squad", squad_cookie), ("manager", manager_cookie)):
                with self.subTest(method=method, path=path, actor=actor):
                    self.assertEqual(self.backend.request(method, path, payload, cookie=cookie).status, 403)

    def test_owner_member_and_role_mutations_create_persistent_sanitized_notifications(self):
        """Removing generated notifications, their persistence, or secret sanitization breaks this flow."""
        created = self.owner_request("POST", "/api/owner/squad-members", {
            "name": "Notice Member", "ign": "NoticeMember", "gameId": "777777", "serverId": "7777",
            "accessCode": "NOTICE-MEMBER-CODE",
        })
        self.assertEqual(created.status, 201)
        member_id = created.json["member"]["id"]
        changed = self.owner_request(
            "PATCH", f"/api/owner/squad-members/{member_id}",
            {"role": "Squad Leader"},
        )
        self.assertEqual(changed.status, 200)
        appointed = self.owner_request("POST", "/api/owner/squad-owner", {"memberId": member_id})
        self.assertEqual(appointed.status, 200)
        deletable = self.owner_request("POST", "/api/owner/squad-members", {
            "name": "Delete Member", "ign": "DeleteMember", "gameId": "777778", "serverId": "7778",
            "accessCode": "DELETE-MEMBER-CODE",
        })
        self.assertEqual(deletable.status, 201)
        self.assertEqual(
            self.owner_request("DELETE", f"/api/owner/squad-members/{deletable.json['member']['id']}", {}).status,
            200,
        )
        community = self.backend.request("POST", "/api/community/register", {
            "email": "notification-status@example.test", "password": "member-password-123",
            "ign": "NotificationStatus", "gameId": "888888", "serverId": "8888",
        })
        self.assertEqual(community.status, 200)
        self.assertEqual(
            self.owner_request(
                "PATCH", f"/api/owner/community-accounts/{community.json['account']['id']}",
                {"status": "Disabled"},
            ).status,
            200,
        )

        second_login = self.backend.request(
            "POST", "/api/owner/login",
            {"username": "content-owner", "password": "owner-password-123"},
        )
        self.assertEqual(second_login.status, 200)
        second_cookie = second_login.headers["Set-Cookie"].split(";", 1)[0]
        notifications = self.owner_request(
            "GET", "/api/owner/squad-content?domain=notifications", cookie=second_cookie,
        )
        self.assertEqual(notifications.status, 200)
        actions = {item.get("action") for item in notifications.json["items"]}
        self.assertTrue({
            "owner_squad_member_create", "owner_squad_member_update", "owner_squad_member_delete",
            "owner_squad_owner_appoint", "owner_community_account_update",
        }.issubset(actions))
        serialized = json.dumps(notifications.json).lower()
        self.assertNotIn("notice-member-code", serialized)
        self.assertNotIn("notice-rotated-code", serialized)
        with server.LOCK, server.db() as connection:
            rows = connection.execute("SELECT domain,payload FROM notifications").fetchall()
        self.assertTrue(any(row["domain"] == "squad" for row in rows))
        self.assertNotIn("notice-member-code", json.dumps([dict(row) for row in rows]).lower())

    def test_persisted_notifications_are_scoped_by_audience_domain_and_read_cross_device(self):
        """Changing table scoping or read persistence must not leak notifications across audiences."""
        community = self.backend.request("POST", "/api/community/register", {
            "email": "notification-recipient@example.test", "password": "member-password-123",
            "ign": "NotificationRecipient", "gameId": "999991", "serverId": "9991",
        })
        self.assertEqual(community.status, 200)
        community_id = community.json["account"]["id"]
        community_cookie = community.headers["Set-Cookie"].split(";", 1)[0]
        squad_login = self.backend.request("POST", "/api/squad/login", {
            "ign": "ContentOwner", "gameId": "123456", "serverId": "1234", "accessCode": "DS-CONTENT-OWNER",
        })
        self.assertEqual(squad_login.status, 200)
        squad_cookie = squad_login.headers["Set-Cookie"].split(";", 1)[0]
        self.assertEqual(self.owner_request(
            "POST", "/api/owner/squad-content/notifications/squad-recipient",
            {"title": "Squad only", "message": "For the Squad Owner.", "audienceType": "squad", "audienceId": "1"},
        ).status, 201)
        self.assertEqual(self.owner_request(
            "POST", "/api/owner/squad-content/notifications/community-recipient",
            {"title": "Community only", "message": "For the Community account.", "audienceType": "community", "audienceId": community_id},
        ).status, 201)

        squad_bootstrap = self.backend.request("GET", "/api/bootstrap", cookie=squad_cookie)
        self.assertEqual([item["id"] for item in squad_bootstrap.json["squad"]["notifications"]], ["squad-recipient"])
        self.assertEqual(self.backend.request("POST", "/api/squad/notifications/read", {"id": "squad-recipient"}, cookie=squad_cookie).status, 200)
        squad_second_device = self.backend.request("GET", "/api/bootstrap", cookie=squad_cookie)
        self.assertTrue(squad_second_device.json["squad"]["notifications"][0]["read"])

        community_bootstrap = self.backend.request("GET", "/api/bootstrap", cookie=community_cookie)
        self.assertEqual([item["id"] for item in community_bootstrap.json["community"]["notifications"]], ["community-recipient"])
        self.assertEqual(self.backend.request(
            "POST", "/api/community/notifications/read", {"id": "community-recipient"}, cookie=community_cookie,
        ).status, 200)
        community_second_device = self.backend.request("GET", "/api/bootstrap", cookie=community_cookie)
        self.assertTrue(community_second_device.json["community"]["notifications"][0]["read"])
        community_list = self.owner_request("GET", "/api/owner/squad-content?domain=notifications&audienceType=community")
        self.assertEqual([item["id"] for item in community_list.json["items"]], ["community-recipient"])
        self.assertEqual(self.owner_request(
            "PATCH", "/api/owner/squad-content/notifications/community-recipient?audienceType=squad",
            {"title": "No", "message": "No"},
        ).status, 404)

    def test_owner_content_patch_preserves_legacy_render_fields_and_audit_failure_rolls_back(self):
        """Replacing a record must preserve legacy fields, and an audit failure must persist nothing."""
        with server.LOCK, server.db() as connection:
            server.state_set(connection, "reports", [{
                "id": "legacy-report", "memberId": "1", "title": "Old", "body": "Old body",
                "values": {"reportTitle": "Old", "reportDetails": "Old body"}, "time": "2099-01-01T00:00:00Z",
                "files": [{"name": "proof.png", "type": "image/png", "size": 12}], "legacyMarker": "keep",
            }])
            server.state_set(connection, "complaints", [{
                "id": "legacy-complaint", "memberId": "1", "title": "Issue", "body": "Old complaint",
                "time": "2099-01-01T00:00:00Z", "files": [{"name": "proof.pdf", "size": 13}],
                "response": "Investigating", "respondedBy": "Leader", "legacyMarker": "keep",
            }])
            server.state_set(connection, "events", [{
                "id": "legacy-event", "title": "Legacy event", "date": "2099-06-01", "time": "19:00",
                "rules": "Be ready", "body": "Venue", "legacyMarker": "keep",
            }])
            connection.commit()

        self.assertEqual(self.owner_request(
            "PATCH", "/api/owner/squad-content/reports/legacy-report", {"body": "New body"},
        ).status, 200)
        self.assertEqual(self.owner_request(
            "PATCH", "/api/owner/squad-content/complaints/legacy-complaint", {"body": "New complaint"},
        ).status, 200)
        self.assertEqual(self.owner_request(
            "PATCH", "/api/owner/squad-content/events/legacy-event", {"rules": "Updated rules", "body": "New venue"},
        ).status, 200)
        with server.LOCK, server.db() as connection:
            report = server.state_get(connection, "reports", [])[0]
            complaint = server.state_get(connection, "complaints", [])[0]
            event = server.state_get(connection, "events", [])[0]
        self.assertEqual(report["values"]["reportDetails"], "Old body")
        self.assertEqual(report["files"][0]["name"], "proof.png")
        self.assertEqual(report["legacyMarker"], "keep")
        self.assertEqual(complaint["response"], "Investigating")
        self.assertEqual(complaint["files"][0]["name"], "proof.pdf")
        self.assertEqual(event["rules"], "Updated rules")
        self.assertEqual(event["body"], "New venue")
        self.assertEqual(event["legacyMarker"], "keep")
        with patch.object(server, "insert_audit", side_effect=RuntimeError("audit unavailable")):
            failed = self.owner_request(
                "POST", "/api/owner/squad-content/announcements/rollback-test",
                {"title": "Rollback", "body": "This must not persist."},
            )
        self.assertEqual(failed.status, 503)
        with server.LOCK, server.db() as connection:
            self.assertFalse(any(item.get("id") == "rollback-test" for item in server.state_get(connection, "announcements", [])))

    def test_broadcast_notification_read_state_is_per_recipient(self):
        """Mutating a broadcast payload must not mark it read for every Squad recipient."""
        member = self.owner_request("POST", "/api/owner/squad-members", {
            "name": "Second Recipient", "ign": "SecondRecipient", "gameId": "919191", "serverId": "9191",
            "accessCode": "SECOND-RECIPIENT-CODE",
        })
        self.assertEqual(member.status, 201)
        owner_squad = self.backend.request("POST", "/api/squad/login", {
            "ign": "ContentOwner", "gameId": "123456", "serverId": "1234", "accessCode": "DS-CONTENT-OWNER",
        })
        second_squad = self.backend.request("POST", "/api/squad/login", {
            "ign": "SecondRecipient", "gameId": "919191", "serverId": "9191", "accessCode": "SECOND-RECIPIENT-CODE",
        })
        self.assertEqual(owner_squad.status, 200)
        self.assertEqual(second_squad.status, 200)
        self.assertEqual(self.owner_request(
            "POST", "/api/owner/squad-content/notifications/broadcast-notice",
            {"title": "Broadcast", "message": "Everyone should see this.", "audienceType": "squad"},
        ).status, 201)
        owner_cookie = owner_squad.headers["Set-Cookie"].split(";", 1)[0]
        second_cookie = second_squad.headers["Set-Cookie"].split(";", 1)[0]
        self.assertFalse(next(item for item in self.backend.request("GET", "/api/bootstrap", cookie=owner_cookie).json["squad"]["notifications"] if item["id"] == "broadcast-notice")["read"])
        self.assertFalse(next(item for item in self.backend.request("GET", "/api/bootstrap", cookie=second_cookie).json["squad"]["notifications"] if item["id"] == "broadcast-notice")["read"])
        self.assertEqual(self.backend.request("POST", "/api/squad/notifications/read", {"id": "broadcast-notice"}, cookie=owner_cookie).status, 200)
        self.assertTrue(next(item for item in self.backend.request("GET", "/api/bootstrap", cookie=owner_cookie).json["squad"]["notifications"] if item["id"] == "broadcast-notice")["read"])
        self.assertFalse(next(item for item in self.backend.request("GET", "/api/bootstrap", cookie=second_cookie).json["squad"]["notifications"] if item["id"] == "broadcast-notice")["read"])

    def test_content_metadata_is_bounded_sanitized_and_owner_member_failure_rolls_back(self):
        """Metadata must not persist secrets, and a member audit failure must roll back every write."""
        self.assertEqual(self.owner_request(
            "POST", "/api/owner/squad-content/reports/unsafe-values",
            {"body": "Body", "values": {"accessCode": "LEAK"}},
        ).status, 400)
        self.assertEqual(self.owner_request(
            "POST", "/api/owner/squad-content/reports/unsafe-files",
            {"body": "Body", "files": "not-a-list"},
        ).status, 400)
        with server.LOCK, server.db() as connection:
            server.state_set(connection, "reports", [{
                "id": "legacy-safe", "body": "Safe", "values": {"visible": "yes", "password": "hidden"},
                "files": [{"name": "safe.png", "token": "hidden"}],
            }])
            connection.commit()
        listed = self.owner_request("GET", "/api/owner/squad-content?domain=reports")
        legacy = next(item for item in listed.json["items"] if item["id"] == "legacy-safe")
        self.assertEqual(legacy["values"], {"visible": "yes"})
        self.assertEqual(legacy["files"], [{"name": "safe.png"}])
        with server.LOCK, server.db() as connection:
            members_before = connection.execute("SELECT COUNT(*) AS n FROM squad_members").fetchone()["n"]
            notifications_before = connection.execute("SELECT COUNT(*) AS n FROM notifications").fetchone()["n"]
            audit_before = connection.execute("SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        with patch.object(server, "insert_audit", side_effect=RuntimeError("audit unavailable")):
            failed = self.owner_request("POST", "/api/owner/squad-members", {
                "name": "Rollback Member", "ign": "RollbackMember", "gameId": "929292", "serverId": "9292",
                "accessCode": "ROLLBACK-MEMBER-CODE",
            })
        self.assertEqual(failed.status, 503)
        with server.LOCK, server.db() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) AS n FROM squad_members").fetchone()["n"], members_before)
            self.assertEqual(connection.execute("SELECT COUNT(*) AS n FROM notifications").fetchone()["n"], notifications_before)
            self.assertEqual(connection.execute("SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"], audit_before)

    def test_content_projection_keeps_valid_long_text_and_metadata_has_an_aggregate_budget(self):
        """A safe projection must not truncate valid domain text, but metadata must stay bounded."""
        long_body = "x" * 8000
        created = self.owner_request(
            "POST", "/api/owner/squad-content/events/long-event",
            {"title": "Long event", "date": "2099-07-01", "rules": long_body, "body": long_body},
        )
        self.assertEqual(created.status, 201)
        listed = self.owner_request("GET", "/api/owner/squad-content?domain=events")
        event = next(item for item in listed.json["items"] if item["id"] == "long-event")
        self.assertEqual(event["rules"], long_body)
        self.assertEqual(event["body"], long_body)
        oversized_values = {f"field-{index}": "x" * 4000 for index in range(10)}
        self.assertEqual(self.owner_request(
            "POST", "/api/owner/squad-content/reports/metadata-budget",
            {"body": "Body", "values": oversized_values},
        ).status, 400)

    def test_notification_delete_removes_recipient_receipts_before_recreate(self):
        """Deleting a notification must remove its receipts so a reused id starts unread."""
        self.assertEqual(self.owner_request(
            "POST", "/api/owner/squad-content/notifications/reused-id",
            {"title": "First", "message": "First message", "audienceType": "squad"},
        ).status, 201)
        squad_login = self.backend.request("POST", "/api/squad/login", {
            "ign": "ContentOwner", "gameId": "123456", "serverId": "1234", "accessCode": "DS-CONTENT-OWNER",
        })
        self.assertEqual(squad_login.status, 200)
        squad_cookie = squad_login.headers["Set-Cookie"].split(";", 1)[0]
        self.assertEqual(self.backend.request(
            "POST", "/api/squad/notifications/read", {"id": "reused-id"}, cookie=squad_cookie,
        ).status, 200)
        self.assertEqual(self.owner_request(
            "DELETE", "/api/owner/squad-content/notifications/reused-id", {},
        ).status, 200)
        with server.LOCK, server.db() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) AS n FROM notification_reads WHERE notification_id='reused-id'").fetchone()["n"], 0)
        self.assertEqual(self.owner_request(
            "POST", "/api/owner/squad-content/notifications/reused-id",
            {"title": "Second", "message": "Second message", "audienceType": "squad"},
        ).status, 201)
        current = self.backend.request("GET", "/api/bootstrap", cookie=squad_cookie)
        self.assertFalse(next(item for item in current.json["squad"]["notifications"] if item["id"] == "reused-id")["read"])


class OwnerTournamentAdministrationTests(unittest.TestCase):
    """Dedicated Overall Owner tournament lifecycle administration."""

    def setUp(self):
        self.backend = BackendHarness()
        setup = self.backend.request(
            "POST", "/api/owner/setup", {
                "setupSecret": BackendHarness.OWNER_SETUP_SECRET,
                "username": "tournament-owner", "password": "owner-password-123",
                "squadOwner": {
                    "ign": "TournamentOwner", "gameId": "123456", "serverId": "1234",
                    "accessCode": "DS-TOURNAMENT-OWNER",
                },
            },
        )
        self.assertEqual(setup.status, 200)
        login = self.backend.request(
            "POST", "/api/owner/login",
            {"username": "tournament-owner", "password": "owner-password-123"},
        )
        self.assertEqual(login.status, 200)
        self.owner_cookie = login.headers["Set-Cookie"].split(";", 1)[0]

    def tearDown(self):
        self.backend.close()

    def owner_request(self, method, path, payload=None, cookie=None):
        return self.backend.request(method, path, payload, cookie=cookie or self.owner_cookie)

    def register_player(self, number):
        response = self.backend.request(
            "POST", "/api/community/register", {
                "email": f"player-{number}@example.test", "password": "member-password-123",
                "ign": f"Player{number}", "gameId": f"88000{number}", "serverId": f"880{number}",
            },
        )
        self.assertEqual(response.status, 200)
        return response.json["account"], response.headers["Set-Cookie"].split(";", 1)[0]

    def create_two_player_bracket(self, first_number=5, second_number=6, title="Review Cup"):
        tournament = self.owner_request("POST", "/api/owner/tournaments", {
            "title": title, "game": "MLBB", "format": "1v1", "date": "2099-12-20", "slots": 4,
        }).json["tournament"]
        players = []
        for number in (first_number, second_number):
            account, cookie = self.register_player(number)
            registered = self.backend.request(
                "POST", "/api/tournaments/register", {"tournamentId": tournament["id"]}, cookie=cookie,
            )
            registration = next(item for item in registered.json["registrations"] if item["accountId"] == account["id"])
            self.assertEqual(self.owner_request(
                "POST", f"/api/owner/tournaments/{tournament['id']}/registrations/{registration['id']}/decision",
                {"action": "approve"},
            ).status, 200)
            players.append((account, cookie))
        bracket = self.owner_request("POST", f"/api/owner/tournaments/{tournament['id']}/bracket", {})
        self.assertEqual(bracket.status, 200)
        return tournament["id"], bracket.json["tournament"]["matches"][0], players

    def test_owner_can_run_a_secret_safe_tournament_from_creation_through_archive(self):
        """Removing any dedicated lifecycle transition, safe projection, audit, or notification breaks this flow."""
        created = self.owner_request("POST", "/api/owner/tournaments", {
            "title": "Owner Championship", "game": "Mobile Legends: Bang Bang",
            "format": "1v1", "date": "2099-09-10", "time": "18:00",
            "slots": 8, "reward": "Trophy", "rules": "Best of three.",
        })
        self.assertEqual(created.status, 201)
        tournament_id = created.json["tournament"]["id"]
        edited = self.owner_request(
            "PATCH", f"/api/owner/tournaments/{tournament_id}", {"reward": "Championship Trophy"},
        )
        self.assertEqual(edited.status, 200)
        self.assertEqual(edited.json["tournament"]["reward"], "Championship Trophy")

        first, first_cookie = self.register_player(1)
        second, second_cookie = self.register_player(2)
        for account, cookie in ((first, first_cookie), (second, second_cookie)):
            registered = self.backend.request(
                "POST", "/api/tournaments/register", {"tournamentId": tournament_id}, cookie=cookie,
            )
            self.assertEqual(registered.status, 200)
            registration = next(
                item for item in registered.json["registrations"]
                if item["accountId"] == account["id"]
            )
            decided = self.owner_request(
                "POST",
                f"/api/owner/tournaments/{tournament_id}/registrations/{registration['id']}/decision",
                {"action": "approve"},
            )
            self.assertEqual(decided.status, 200)
            self.assertEqual(decided.json["registration"]["status"], "Approved")

        bracket = self.owner_request("POST", f"/api/owner/tournaments/{tournament_id}/bracket", {})
        self.assertEqual(bracket.status, 200)
        match = bracket.json["tournament"]["matches"][0]
        changed = self.owner_request(
            "PATCH", f"/api/owner/tournaments/{tournament_id}/matches/{match['id']}",
            {"scheduledAt": "2099-09-10T18:30:00Z"},
        )
        self.assertEqual(changed.status, 200)

        player_cookies = {first["id"]: first_cookie, second["id"]: second_cookie}
        submitted = self.backend.request(
            "POST", "/api/tournaments/result",
            {"tournamentId": tournament_id, "matchId": match["id"], "result": {"winner": match["player1"]}},
            cookie=player_cookies[match["player1"]],
        )
        self.assertEqual(submitted.status, 200)
        confirmed = self.owner_request(
            "POST", f"/api/owner/tournaments/{tournament_id}/matches/{match['id']}/result",
            {"action": "confirm"},
        )
        self.assertEqual(confirmed.status, 200)
        self.assertEqual(confirmed.json["match"]["winner"], match["player1"])
        completed = self.owner_request("POST", f"/api/owner/tournaments/{tournament_id}/complete", {})
        self.assertEqual(completed.status, 200)
        self.assertEqual(completed.json["tournament"]["status"], "Completed")
        archived = self.owner_request("POST", f"/api/owner/tournaments/{tournament_id}/archive", {})
        self.assertEqual(archived.status, 200)
        self.assertEqual(archived.json["tournament"]["status"], "Archived")

        with server.LOCK, server.db() as connection:
            tournaments = server.state_get(connection, "tournaments", [])
            stored = next(item for item in tournaments if item.get("id") == tournament_id)
            stored["leaderAccessCode"] = "OWNER-TOURNAMENT-SECRET"
            stored["matches"][0]["submission"]["evidenceToken"] = "OWNER-RESULT-SECRET"
            server.state_set(connection, "tournaments", tournaments)
            connection.commit()
        detail = self.owner_request("GET", f"/api/owner/tournaments/{tournament_id}")
        self.assertEqual(detail.status, 200)
        serialized = json.dumps(detail.json).lower()
        self.assertNotIn("owner-tournament-secret", serialized)
        self.assertNotIn("owner-result-secret", serialized)
        self.assertEqual(len(detail.json["registrations"]), 2)
        self.assertEqual(len(detail.json["resultSubmissions"]), 1)

        audit = self.owner_request("GET", "/api/owner/audit")
        actions = {item["action"] for item in audit.json["audit"]}
        self.assertTrue({
            "owner_tournament_create", "owner_tournament_update", "owner_tournament_registration_approve",
            "owner_tournament_bracket_generate", "owner_tournament_match_update",
            "owner_tournament_result_confirm", "owner_tournament_complete", "owner_tournament_archive",
        }.issubset(actions))
        notifications = self.owner_request("GET", "/api/owner/squad-content?domain=notifications")
        notification_actions = {item.get("action") for item in notifications.json["items"]}
        self.assertTrue({"owner_tournament_create", "owner_tournament_complete"}.issubset(notification_actions))

    def test_cancellation_reinstates_registration_state_and_rejects_invalid_transitions(self):
        """Cancellation must close dependent registrations, and only a timely reinstatement may restore them."""
        created = self.owner_request("POST", "/api/owner/tournaments", {
            "title": "Cancellation Cup", "game": "MLBB", "format": "1v1", "date": "2099-10-01", "slots": 4,
        })
        tournament_id = created.json["tournament"]["id"]
        account, cookie = self.register_player(3)
        registration = self.backend.request(
            "POST", "/api/tournaments/register", {"tournamentId": tournament_id}, cookie=cookie,
        ).json["registrations"][0]
        cancelled = self.owner_request("POST", f"/api/owner/tournaments/{tournament_id}/cancel", {})
        self.assertEqual(cancelled.status, 200)
        detail = self.owner_request("GET", f"/api/owner/tournaments/{tournament_id}")
        self.assertEqual(detail.json["registrations"][0]["status"], "Tournament Cancelled")
        self.assertEqual(self.owner_request("POST", f"/api/owner/tournaments/{tournament_id}/cancel", {}).status, 409)
        reinstated = self.owner_request("POST", f"/api/owner/tournaments/{tournament_id}/reinstate", {})
        self.assertEqual(reinstated.status, 200)
        detail = self.owner_request("GET", f"/api/owner/tournaments/{tournament_id}")
        self.assertEqual(detail.json["registrations"][0]["status"], "Registered")
        self.assertEqual(self.owner_request("POST", f"/api/owner/tournaments/{tournament_id}/complete", {}).status, 409)
        with server.LOCK, server.db() as connection:
            tournaments = server.state_get(connection, "tournaments", [])
            target = next(item for item in tournaments if item["id"] == tournament_id)
            target.update(status="Cancelled", cancelledAt="2000-01-01T00:00:00Z")
            server.state_set(connection, "tournaments", tournaments)
            connection.commit()
        self.assertEqual(self.owner_request("POST", f"/api/owner/tournaments/{tournament_id}/reinstate", {}).status, 409)

    def test_squad_approval_and_tournament_manager_permissions_are_owner_administered(self):
        """Approval decisions and Manager grants must be validated, secret-safe, notified, and audited."""
        member = self.owner_request("POST", "/api/owner/squad-members", {
            "name": "Tournament Lead", "ign": "TournamentLead", "gameId": "990001", "serverId": "9901",
            "accessCode": "TOURNAMENT-LEAD-CODE", "role": "Squad Leader",
        }).json["member"]
        granted = self.owner_request(
            "POST", f"/api/owner/tournament-managers/{member['id']}", {"action": "grant"},
        )
        self.assertEqual(granted.status, 200)
        self.assertTrue(granted.json["granted"])
        self.assertEqual(
            self.owner_request("POST", f"/api/owner/tournament-managers/{member['id']}", {"action": "grant"}).status,
            409,
        )
        revoked = self.owner_request(
            "POST", f"/api/owner/tournament-managers/{member['id']}", {"action": "revoke"},
        )
        self.assertEqual(revoked.status, 200)
        self.assertFalse(revoked.json["granted"])

        tournament = self.owner_request("POST", "/api/owner/tournaments", {
            "title": "Squad Cup", "game": "MLBB", "format": "Squad vs Squad", "date": "2099-11-01",
            "squadSlots": 8, "membersPerSquad": 7,
        }).json["tournament"]
        with server.LOCK, server.db() as connection:
            server.state_set(connection, "squadTournamentApprovals", [{
                "id": "approval-owner-test", "tournamentId": tournament["id"], "status": "Pending",
                "leaderAccountId": "leader-account", "squadName": "Dark Alpha", "memberAccessCode": "OLD-SECRET",
            }])
            connection.commit()
        approved = self.owner_request(
            "POST", f"/api/owner/tournaments/{tournament['id']}/approvals/approval-owner-test/decision",
            {"action": "approve"},
        )
        self.assertEqual(approved.status, 200)
        self.assertEqual(approved.json["approval"]["status"], "Approved")
        self.assertNotIn("code", json.dumps(approved.json).lower())
        self.assertEqual(self.owner_request(
            "POST", f"/api/owner/tournaments/{tournament['id']}/approvals/approval-owner-test/decision",
            {"action": "reject"},
        ).status, 409)

    def test_owner_tournament_routes_enforce_owner_auth_and_rollback_audit_failures(self):
        """Weakening the Owner guard or separating audit from state persistence must fail this test."""
        community, community_cookie = self.register_player(4)
        squad = self.backend.request("POST", "/api/squad/login", {
            "ign": "TournamentOwner", "gameId": "123456", "serverId": "1234", "accessCode": "DS-TOURNAMENT-OWNER",
        })
        squad_cookie = squad.headers["Set-Cookie"].split(";", 1)[0]
        routes = (
            ("GET", "/api/owner/tournaments", None),
            ("POST", "/api/owner/tournaments", {"title": "No", "game": "MLBB", "format": "1v1", "date": "2099-01-01"}),
            ("POST", "/api/owner/tournament-managers/1", {"action": "grant"}),
        )
        for method, path, payload in routes:
            self.assertEqual(self.backend.request(method, path, payload).status, 401)
            self.assertEqual(self.backend.request(method, path, payload, cookie=community_cookie).status, 403)
            self.assertEqual(self.backend.request(method, path, payload, cookie=squad_cookie).status, 403)
        with patch.object(server, "insert_audit", side_effect=RuntimeError("audit unavailable")):
            failed = self.owner_request("POST", "/api/owner/tournaments", {
                "title": "Rollback Cup", "game": "MLBB", "format": "1v1", "date": "2099-12-01",
            })
        self.assertEqual(failed.status, 503)
        listed = self.owner_request("GET", "/api/owner/tournaments")
        self.assertNotIn("Rollback Cup", [item.get("title") for item in listed.json["tournaments"]])

    def test_manager_authority_is_removed_by_owner_and_legacy_member_demotion_or_deletion(self):
        """A stale Tournament Manager id must not survive any supported role-loss or member-removal path."""
        def create_manager(suffix):
            response = self.owner_request("POST", "/api/owner/squad-members", {
                "name": f"Manager {suffix}", "ign": f"Manager{suffix}",
                "gameId": f"77{suffix:04d}", "serverId": f"7{suffix:03d}",
                "accessCode": f"MANAGER-{suffix}-CODE", "role": "Squad Leader",
            })
            self.assertEqual(response.status, 201)
            member = response.json["member"]
            self.assertEqual(self.owner_request(
                "POST", f"/api/owner/tournament-managers/{member['id']}", {"action": "grant"},
            ).status, 200)
            return member

        owner_demoted = create_manager(1)
        login = self.backend.request("POST", "/api/squad/login", {
            "ign": owner_demoted["ign"], "gameId": owner_demoted["gameId"],
            "serverId": owner_demoted["serverId"], "accessCode": "MANAGER-1-CODE",
        })
        stale_cookie = login.headers["Set-Cookie"].split(";", 1)[0]
        self.assertEqual(self.owner_request(
            "PATCH", f"/api/owner/squad-members/{owner_demoted['id']}", {"role": "Squad Member"},
        ).status, 200)
        relogin = self.backend.request("POST", "/api/squad/login", {
            "ign": owner_demoted["ign"], "gameId": owner_demoted["gameId"],
            "serverId": owner_demoted["serverId"], "accessCode": "MANAGER-1-CODE",
        })
        self.assertEqual(relogin.status, 200)
        relogin_cookie = relogin.headers["Set-Cookie"].split(";", 1)[0]
        self.assertEqual(self.backend.request("POST", "/api/tournaments", {
            "title": "Unauthorized", "game": "MLBB", "format": "1v1", "date": "2099-01-01",
        }, cookie=relogin_cookie).status, 403)
        self.assertFalse(self.backend.request("GET", "/api/auth/me", cookie=stale_cookie).json["authenticated"])

        role_demoted = create_manager(2)
        self.assertEqual(self.owner_request("POST", "/api/squad/role", {
            "memberId": role_demoted["id"], "role": "Squad Member",
        }).status, 200)
        legacy_updated = create_manager(3)
        self.assertEqual(self.owner_request("PUT", "/api/squad/members", {
            "id": legacy_updated["id"], "role": "Squad Member",
        }).status, 200)
        owner_deleted = create_manager(4)
        self.assertEqual(self.owner_request(
            "DELETE", f"/api/owner/squad-members/{owner_deleted['id']}", {},
        ).status, 200)
        legacy_deleted = create_manager(5)
        self.assertEqual(self.owner_request("DELETE", "/api/squad/members", {
            "id": legacy_deleted["id"],
        }).status, 200)
        with server.LOCK, server.db() as connection:
            managers = server.state_get(connection, "tournamentManagers", [])
        manager_ids = {
            str(item.get("id") or item.get("accountId")) if isinstance(item, dict) else str(item)
            for item in managers
        }
        self.assertTrue({
            owner_demoted["id"], role_demoted["id"], legacy_updated["id"],
            owner_deleted["id"], legacy_deleted["id"],
        }.isdisjoint(manager_ids))

    def test_disputed_result_requires_reasoned_resolution_and_rejection_allows_resubmission(self):
        """Owner confirmation must not bypass a dispute, and a rejected submission must not block a clean retry."""
        tournament_id, match, players = self.create_two_player_bracket(title="Dispute Cup")
        cookies = {account["id"]: cookie for account, cookie in players}
        submitter = match["player1"]
        opponent = match["player2"]
        self.assertEqual(self.backend.request("POST", "/api/tournaments/result", {
            "tournamentId": tournament_id, "matchId": match["id"], "result": {"winner": submitter},
        }, cookie=cookies[submitter]).status, 200)
        self.assertEqual(self.backend.request("POST", "/api/tournaments/result-dispute", {
            "tournamentId": tournament_id, "matchId": match["id"],
        }, cookie=cookies[opponent]).status, 200)
        self.assertEqual(self.owner_request(
            "POST", f"/api/owner/tournaments/{tournament_id}/matches/{match['id']}/result", {"action": "confirm"},
        ).status, 409)
        self.assertEqual(self.owner_request(
            "POST", f"/api/owner/tournaments/{tournament_id}/matches/{match['id']}/result",
            {"action": "resolve", "winner": submitter},
        ).status, 400)
        rejected = self.owner_request(
            "POST", f"/api/owner/tournaments/{tournament_id}/matches/{match['id']}/result", {"action": "reject"},
        )
        self.assertEqual(rejected.status, 200)
        self.assertIsNone(rejected.json["match"]["submission"])
        self.assertEqual(self.backend.request("POST", "/api/tournaments/result", {
            "tournamentId": tournament_id, "matchId": match["id"], "result": {"winner": opponent},
        }, cookie=cookies[opponent]).status, 200)

    def test_reinstate_preserves_capacity_closed_squad_registration(self):
        """A general registration flag must never reopen an independently capacity-closed Squad queue."""
        tournament = self.owner_request("POST", "/api/owner/tournaments", {
            "title": "Full Squad Cup", "game": "MLBB", "format": "Squad vs Squad", "date": "2099-12-22",
            "squadSlots": 1, "membersPerSquad": 7, "registrationOpen": True, "squadRegistrationOpen": False,
        }).json["tournament"]
        self.assertEqual(self.owner_request("POST", f"/api/owner/tournaments/{tournament['id']}/cancel", {}).status, 200)
        reinstated = self.owner_request("POST", f"/api/owner/tournaments/{tournament['id']}/reinstate", {})
        self.assertEqual(reinstated.status, 200)
        self.assertTrue(reinstated.json["tournament"]["registrationOpen"])
        self.assertFalse(reinstated.json["tournament"]["squadRegistrationOpen"])

    def test_upstream_correction_rejects_downstream_activity_and_final_correction_survives_auto_completion(self):
        """Corrections must preserve downstream history while still allowing an Owner to correct an auto-completed final."""
        with server.LOCK, server.db() as connection:
            server.state_set(connection, "tournaments", [{
                "id": "correction-tree", "title": "Correction Tree", "status": "In Progress", "bracketReady": True,
                "matches": [
                    {"id": "semi", "round": 1, "player1": "p1", "player2": "p2", "winner": "p1",
                     "submission": {"winner": "p1", "status": "Owner Confirmed"}, "pointsAwarded": True,
                     "nextMatchId": "final", "nextSlot": "player1"},
                    {"id": "final", "round": 2, "player1": "p1", "player2": "p3", "winner": None,
                     "submission": {"winner": "p1", "status": "Awaiting Confirmation"}},
                ],
            }])
            server.state_set(connection, "seasonPoints", {"p1": 100, "p2": 50})
            connection.commit()
        blocked = self.owner_request(
            "POST", "/api/owner/tournaments/correction-tree/matches/semi/result",
            {"action": "correct", "winner": "p2", "reason": "Verified replay"},
        )
        self.assertEqual(blocked.status, 409)
        with server.LOCK, server.db() as connection:
            tree = server.state_get(connection, "tournaments", [])[0]
            points = server.state_get(connection, "seasonPoints", {})
        self.assertEqual(tree["matches"][0]["winner"], "p1")
        self.assertEqual(points, {"p1": 100, "p2": 50})

        tournament_id, match, players = self.create_two_player_bracket(7, 8, "Auto Complete Cup")
        cookies = {account["id"]: cookie for account, cookie in players}
        self.assertEqual(self.backend.request("POST", "/api/tournaments/result", {
            "tournamentId": tournament_id, "matchId": match["id"], "result": {"winner": match["player1"]},
        }, cookie=cookies[match["player1"]]).status, 200)
        self.assertEqual(self.backend.request("POST", "/api/tournaments/result-confirm", {
            "tournamentId": tournament_id, "matchId": match["id"],
        }, cookie=cookies[match["player2"]]).status, 200)
        corrected = self.owner_request(
            "POST", f"/api/owner/tournaments/{tournament_id}/matches/{match['id']}/result",
            {"action": "correct", "winner": match["player2"], "reason": "Official replay review"},
        )
        self.assertEqual(corrected.status, 200)
        completed = self.owner_request("POST", f"/api/owner/tournaments/{tournament_id}/complete", {})
        self.assertEqual(completed.status, 200)
        self.assertEqual(completed.json["tournament"]["champion"], match["player2"])
        self.assertEqual(
            self.owner_request("POST", f"/api/owner/tournaments/{tournament_id}/complete", {}).status,
            409,
        )

    def test_owner_can_create_manual_match_with_strict_fields_and_registered_participants(self):
        """Manual match creation must reject protected fields and outsiders instead of accepting arbitrary state."""
        tournament_id, generated, players = self.create_two_player_bracket(9, 0, "Manual Match Cup")
        participants = [account["id"] for account, _cookie in players]
        self.assertEqual(self.owner_request(
            "POST", f"/api/owner/tournaments/{tournament_id}/matches",
            {"player1": participants[0], "player2": participants[1], "round": 2, "winner": participants[0]},
        ).status, 400)
        self.assertEqual(self.owner_request(
            "POST", f"/api/owner/tournaments/{tournament_id}/matches",
            {"player1": participants[0], "player2": "outsider", "round": 2},
        ).status, 400)
        self.assertEqual(self.owner_request(
            "POST", f"/api/owner/tournaments/{tournament_id}/matches",
            {"player1": participants[0], "player2": participants[1], "round": 2, "status": "Arbitrary"},
        ).status, 400)
        self.assertEqual(self.owner_request(
            "PATCH", f"/api/owner/tournaments/{tournament_id}/matches/{generated['id']}",
            {"status": "Arbitrary"},
        ).status, 400)
        created = self.owner_request(
            "POST", f"/api/owner/tournaments/{tournament_id}/matches",
            {"player1": participants[0], "player2": participants[1], "round": 2, "scheduledAt": "2099-12-20T20:00:00Z"},
        )
        self.assertEqual(created.status, 201)
        self.assertEqual(created.json["match"]["round"], 2)


class OwnerSeasonEventHistoryAdministrationTests(unittest.TestCase):
    """Server-authoritative season, ranking, event, and history administration."""

    def setUp(self):
        self.backend = BackendHarness()
        setup = self.backend.request("POST", "/api/owner/setup", {
            "setupSecret": BackendHarness.OWNER_SETUP_SECRET,
            "username": "season-owner", "password": "owner-password-123",
            "squadOwner": {"ign": "SeasonOwner", "gameId": "551100", "serverId": "5511", "accessCode": "DS-SEASON-OWNER"},
        })
        self.assertEqual(setup.status, 200)
        login = self.backend.request("POST", "/api/owner/login", {
            "username": "season-owner", "password": "owner-password-123",
        })
        self.assertEqual(login.status, 200)
        self.owner_cookie = login.headers["Set-Cookie"].split(";", 1)[0]
        self.accounts = []
        for number, ign in enumerate(("Alpha", "Bravo", "Charlie"), 1):
            registered = self.backend.request("POST", "/api/community/register", {
                "email": f"season-{number}@example.test", "password": "member-password-123",
                "ign": ign, "gameId": f"77110{number}", "serverId": f"771{number}",
            })
            self.assertEqual(registered.status, 200)
            self.accounts.append((registered.json["account"], registered.headers["Set-Cookie"].split(";", 1)[0]))

    def tearDown(self):
        self.backend.close()

    def owner_request(self, method, path, payload=None, cookie=None):
        return self.backend.request(method, path, payload, cookie=cookie or self.owner_cookie)

    def test_season_creation_points_ranking_and_completion_are_authoritative_and_idempotent(self):
        created = self.owner_request("POST", "/api/owner/seasons", {"name": "Season 9", "requestId": "season-nine"})
        self.assertEqual(created.status, 201)
        season = created.json["season"]
        retry = self.owner_request("POST", "/api/owner/seasons", {"name": "Season 9", "requestId": "season-nine"})
        self.assertEqual(retry.status, 200)
        self.assertEqual(retry.json["season"]["id"], season["id"])
        self.assertEqual(self.owner_request("POST", "/api/owner/seasons", {"name": "Another"}).status, 409)

        first_id, second_id = self.accounts[0][0]["id"], self.accounts[1][0]["id"]
        self.assertEqual(self.owner_request("PATCH", f"/api/owner/season-points/{first_id}", {"points": 120}).status, 400)
        self.assertEqual(self.owner_request("PATCH", f"/api/owner/season-points/{first_id}", {"points": 120, "reason": "Match correction"}).status, 200)
        self.assertEqual(self.owner_request("PATCH", f"/api/owner/season-points/{second_id}", {"points": 80, "reason": "Verified score"}).status, 200)
        listed = self.owner_request("GET", "/api/owner/seasons")
        self.assertEqual([row["accountId"] for row in listed.json["leaderboard"][:2]], [first_id, second_id])
        self.assertEqual([row["rank"] for row in listed.json["leaderboard"][:2]], [1, 2])

        completed = self.owner_request("POST", f"/api/owner/seasons/{season['id']}/complete", {})
        self.assertEqual(completed.status, 200)
        snapshot = completed.json["history"]
        repeated = self.owner_request("POST", f"/api/owner/seasons/{season['id']}/complete", {})
        self.assertEqual(repeated.status, 200)
        self.assertEqual(repeated.json["history"]["id"], snapshot["id"])
        history = self.owner_request("GET", "/api/owner/history")
        self.assertEqual(len(history.json["seasonHistory"]), 1)
        self.assertEqual(len(history.json["seasonHallOfFame"]), 1)
        self.assertEqual(history.json["seasonHistory"][0]["leaderboard"][0]["points"], 120)
        delayed_retry = self.owner_request("POST", "/api/owner/seasons", {"name": "Season 9", "requestId": "season-nine"})
        self.assertEqual(delayed_retry.status, 200)
        self.assertEqual(delayed_retry.json["season"]["id"], season["id"])
        self.assertTrue(delayed_retry.json["alreadyCompleted"])

        with server.LOCK, server.db() as connection:
            points = server.state_get(connection, "seasonPoints", {})
            points[first_id] = 999
            server.state_set(connection, "seasonPoints", points)
            connection.commit()
        unchanged = self.owner_request("GET", "/api/owner/history")
        self.assertEqual(unchanged.json["seasonHistory"][0]["leaderboard"][0]["points"], 120)

    def test_hall_of_fame_corrections_require_reason_and_are_audited(self):
        with server.LOCK, server.db() as connection:
            server.state_set(connection, "hallOfFame", [{"id": "H-test", "title": "Cup", "champion": "Wrong"}])
            connection.commit()
        self.assertEqual(self.owner_request("PATCH", "/api/owner/history/hall-of-fame/H-test", {"champion": "Alpha"}).status, 400)
        corrected = self.owner_request("PATCH", "/api/owner/history/hall-of-fame/H-test", {"champion": "Alpha", "reason": "Verified final"})
        self.assertEqual(corrected.status, 200)
        self.assertEqual(corrected.json["entry"]["champion"], "Alpha")
        audit = self.owner_request("GET", "/api/owner/audit")
        self.assertIn("owner_hall_of_fame_correct", {item["action"] for item in audit.json["audit"]})

    def test_history_corrections_strictly_validate_fields_dates_points_and_accounts(self):
        account = self.accounts[0][0]
        with server.LOCK, server.db() as connection:
            server.state_set(connection, "hallOfFame", [{"id": "H-strict", "tournamentId": "T-strict", "title": "Cup", "champion": account["id"]}])
            server.state_set(connection, "seasonHallOfFame", [{"id": "SF-strict", "seasonId": "S-strict", "seasonName": "Season", "accountId": account["id"], "ign": account["ign"], "points": 10}])
            connection.commit()
        bad_payloads = (
            {"title": 123, "reason": "bad type"},
            {"title": "x" * 201, "reason": "too long"},
            {"date": "2099-02-30", "reason": "bad date"},
            {"champion": "missing-account", "reason": "bad account"},
        )
        for payload in bad_payloads:
            self.assertEqual(self.owner_request("PATCH", "/api/owner/history/hall-of-fame/H-strict", payload).status, 400)
        for payload in (
            {"points": -1, "reason": "negative"},
            {"points": 100000001, "reason": "too high"},
            {"accountId": "missing-account", "reason": "bad account"},
            {"ign": "NotTheAccount", "reason": "identity mismatch"},
        ):
            self.assertEqual(self.owner_request("PATCH", "/api/owner/history/season-hall-of-fame/SF-strict", payload).status, 400)

    def test_points_and_point_bearing_participation_require_an_active_season(self):
        account = self.accounts[0][0]
        self.assertEqual(self.owner_request("PATCH", f"/api/owner/season-points/{account['id']}", {"points": 10, "reason": "No season"}).status, 409)
        event = self.owner_request("POST", "/api/owner/events", {"title": "Points Event", "date": "2099-12-20", "rewardPoints": 25}).json["event"]
        self.owner_request("POST", f"/api/owner/events/{event['id']}/publish", {})
        self.assertEqual(self.owner_request("POST", f"/api/owner/events/{event['id']}/participation", {"accountId": account["id"]}).status, 409)
        season = self.owner_request("POST", "/api/owner/seasons", {"name": "Active"}).json["season"]
        self.assertEqual(self.owner_request("POST", f"/api/owner/events/{event['id']}/participation", {"accountId": account["id"]}).status, 201)
        self.owner_request("POST", f"/api/owner/seasons/{season['id']}/complete", {})
        self.assertEqual(self.owner_request("PATCH", f"/api/owner/season-points/{account['id']}", {"points": 20, "reason": "Completed"}).status, 409)

    def test_completed_final_correction_updates_matching_hall_of_fame_atomically(self):
        first, second = self.accounts[0][0]["id"], self.accounts[1][0]["id"]
        with server.LOCK, server.db() as connection:
            server.state_set(connection, "tournaments", [{
                "id": "T-final-history", "title": "Final History", "status": "Completed", "champion": first, "runnerUp": second,
                "matches": [{"id": "final-history", "round": 1, "player1": first, "player2": second, "winner": first, "pointsAwarded": True, "submission": {"winner": first, "status": "Owner Confirmed"}}],
            }])
            server.state_set(connection, "seasonPoints", {first: 100, second: 50})
            server.state_set(connection, "hallOfFame", [{"id": "H-final-history", "tournamentId": "T-final-history", "champion": first, "runnerUp": second}])
            connection.commit()
        corrected = self.owner_request("POST", "/api/owner/tournaments/T-final-history/matches/final-history/result", {"action": "correct", "winner": second, "reason": "Verified replay"})
        self.assertEqual(corrected.status, 200)
        history = self.owner_request("GET", "/api/owner/history")
        entry = history.json["hallOfFame"][0]
        self.assertEqual((entry["champion"], entry["runnerUp"]), (second, first))

    def test_state_workflow_lock_uses_database_transaction_locking(self):
        class FakeCursor:
            def execute(self, sql, params=()):
                self.sql, self.params = sql, params
                return self
        cursor = FakeCursor()
        class FakeConnection:
            def cursor(self): return cursor
        postgres = server.PostgresCompat(FakeConnection())
        server.lock_state_workflow(postgres)
        self.assertIn("pg_advisory_xact_lock", cursor.sql)
        with server.db() as sqlite_connection:
            server.lock_state_workflow(sqlite_connection)
            sqlite_connection.rollback()

    def test_event_lifecycle_and_participation_rewards_are_idempotent(self):
        self.assertEqual(self.owner_request("POST", "/api/owner/seasons", {"name": "Event Season"}).status, 201)
        created = self.owner_request("POST", "/api/owner/events", {
            "title": "Community Night", "date": "2099-12-10", "time": "18:00", "rewardPoints": 50,
            "requestId": "community-night",
        })
        self.assertEqual(created.status, 201)
        event = created.json["event"]
        create_retry = self.owner_request("POST", "/api/owner/events", {
            "title": "Community Night", "date": "2099-12-10", "time": "18:00", "rewardPoints": 50,
            "requestId": "community-night",
        })
        self.assertEqual(create_retry.status, 200)
        self.assertEqual(create_retry.json["event"]["id"], event["id"])
        self.assertEqual(event["status"], "Draft")
        updated = self.owner_request("PATCH", f"/api/owner/events/{event['id']}", {"title": "Community Finals"})
        self.assertEqual(updated.status, 200)
        published = self.owner_request("POST", f"/api/owner/events/{event['id']}/publish", {})
        self.assertEqual(published.json["event"]["status"], "Published")
        account = self.accounts[0][0]
        awarded = self.owner_request("POST", f"/api/owner/events/{event['id']}/participation", {"accountId": account["id"]})
        self.assertEqual(awarded.status, 201)
        self.assertEqual(awarded.json["pointsAwarded"], 50)
        repeated = self.owner_request("POST", f"/api/owner/events/{event['id']}/participation", {"accountId": account["id"]})
        self.assertEqual(repeated.status, 200)
        self.assertFalse(repeated.json["created"])
        correction = {"points": 75, "reason": "Verified event total", "requestId": "points-after-event"}
        self.assertEqual(self.owner_request("PATCH", f"/api/owner/season-points/{account['id']}", correction).status, 200)
        self.assertTrue(self.owner_request("PATCH", f"/api/owner/season-points/{account['id']}", correction).json["alreadyApplied"])
        seasons = self.owner_request("GET", "/api/owner/seasons")
        self.assertEqual(next(row for row in seasons.json["leaderboard"] if row["accountId"] == account["id"])["points"], 75)
        closed = self.owner_request("POST", f"/api/owner/events/{event['id']}/close", {})
        self.assertEqual(closed.json["event"]["status"], "Closed")
        self.assertEqual(self.owner_request("POST", f"/api/owner/events/{event['id']}/participation", {"accountId": self.accounts[1][0]["id"]}).status, 409)
        archived = self.owner_request("POST", f"/api/owner/events/{event['id']}/archive", {})
        self.assertEqual(archived.json["event"]["status"], "Archived")
        self.assertEqual(len(self.owner_request("GET", "/api/owner/events").json["events"]), 1)

    def test_new_routes_require_overall_owner_and_transactions_rollback_with_audit(self):
        community_cookie = self.accounts[0][1]
        for method, path, payload in (
            ("GET", "/api/owner/seasons", None),
            ("GET", "/api/owner/history", None),
            ("GET", "/api/owner/events", None),
            ("POST", "/api/owner/seasons", {"name": "Forbidden"}),
        ):
            self.assertEqual(self.backend.request(method, path, payload).status, 401)
            self.assertEqual(self.backend.request(method, path, payload, cookie=community_cookie).status, 403)
        with patch.object(server, "insert_audit", side_effect=RuntimeError("audit unavailable")):
            failed = self.owner_request("POST", "/api/owner/seasons", {"name": "Rollback Season"})
        self.assertEqual(failed.status, 503)
        self.assertIsNone(self.owner_request("GET", "/api/owner/seasons").json["currentSeason"])


if __name__ == "__main__":
    unittest.main()
