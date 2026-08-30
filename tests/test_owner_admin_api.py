import json
import unittest

import server
from tests.http_harness import BackendHarness


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
            member = connection.execute("SELECT access_code FROM squad_members LIMIT 1").fetchone()
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
                            "accessCode": member["access_code"],
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
            member["access_code"].lower(),
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
            {"role": "Squad Leader", "status": "Disabled", "accessCode": "ROTATED-CODE"},
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


if __name__ == "__main__":
    unittest.main()
