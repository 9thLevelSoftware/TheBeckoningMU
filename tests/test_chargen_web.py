"""
Web chargen end to end: the website is the only way to a playable character.

Django test Client against the real test DB; no mocks except an injected
failure and spies on the main-thread hand-off.
"""

import json
from unittest import mock

from django.test import Client, override_settings
from evennia.commands.default.account import CmdCharDelete, CmdIC
from evennia.objects.models import ObjectDB
from evennia.utils import create
from evennia.utils.test_resources import EvenniaTest

from jobs.models import Job
from tests.chargen_fixtures import ancilla_payload, legal_payload
from tests.test_character_locks import ensure_game_lockfuncs, login, logout_all
from traits import api as traits_api
from traits.api import export_character
from traits.models import CharacterBio
from traits.utils import approve_unit, create_character_unit, resubmit_unit, revoke_unit
from web import main_thread
from world.rules_chargen import apply_chargen, parse_submission

CREATE = "/api/traits/character/create/"
PASSWORD = "testpassword123"


def url(character_id, action):
    return f"/api/traits/character/{character_id}/{action}/"


def run_command(cmdclass, account, session, args):
    """Run an account-level command as `account` on `session`; return what it sent."""
    cmd = cmdclass()
    cmd.caller = cmd.account = account
    cmd.session = session
    cmd.args = args
    cmd.cmdname = cmd.key
    cmd.raw_string = f"{cmd.key} {args}"
    with mock.patch.object(account, "msg") as msg:
        cmd.func()
    return " ".join(str(call.args[0]) for call in msg.call_args_list if call.args)


class ChargenWebTestCase(EvenniaTest):
    def setUp(self):
        super().setUp()
        ensure_game_lockfuncs()
        start = override_settings(START_LOCATION=f"#{self.room1.id}")
        start.enable()
        self.addCleanup(start.disable)
        self.accounts = []
        self.player_a = self.make_account("PlayerA")
        self.player_c = self.make_account("PlayerC")
        self.builder_b = self.make_account("BuilderB", permissions=["Builder"])
        self.admin_d = self.make_account("AdminD", permissions=["Admin"])
        self.client = Client()

    def tearDown(self):
        logout_all()
        for account in self.accounts:
            account.delete()
        super().tearDown()

    def make_account(self, name, permissions=None):
        account = create.create_account(name, email=f"{name}@example.com", password=PASSWORD, permissions=permissions)
        self.accounts.append(account)
        return account

    def as_(self, account):
        self.client.logout()
        if account is not None:
            self.client.force_login(account)
        return self.client

    def post(self, path, data, account=None):
        if account is not None:
            self.as_(account)
        body = data if isinstance(data, str) else json.dumps(data)
        return self.client.post(path, body, content_type="application/json")

    def create_as(self, account, payload=None):
        response = self.post(CREATE, payload or legal_payload(), account)
        return response, (response.json().get("character_id") if response.status_code == 201 else None)

    def character(self, character_id):
        return ObjectDB.objects.get(id=character_id)

    def review(self, reviewer, character_id, action, notes=""):
        return self.post(url(character_id, "approval"), {"action": action, "notes": notes}, reviewer)


class HappyPathTests(ChargenWebTestCase):
    def test_create_approve_play_revoke(self):
        response, char_id = self.create_as(self.player_a)
        self.assertEqual(response.status_code, 201, response.content)
        char = self.character(char_id)
        bio = CharacterBio.objects.get(character=char)

        # Ownership: the bio and Evennia's character list agree; db_account is untouched.
        self.assertEqual(bio.account, self.player_a)
        self.assertIn(char, self.player_a.characters.all())
        self.assertIsNone(char.db_account)
        self.assertEqual(bio.status, "submitted")
        self.assertEqual(Job.objects.filter(bucket__name="Approval", creator=self.player_a).count(), 1)

        # The submission is the sheet.
        self.assertEqual(char.get_trait("strength"), 4)
        self.assertEqual(char.get_trait("intimidation"), 3)
        self.assertEqual(char.clan, "Brujah")
        self.assertCountEqual(char.known_powers, ["Lethal Body", "Prowess", "Awe", "Rapid Reflexes"])
        self.assertIsNone(char.location)

        # Pending: ic is refused.
        session = login(self.player_a, 21)
        run_command(CmdIC, self.player_a, session, "Mara Voss")
        self.assertIsNone(session.puppet)

        # Builder B approves; the character is placed and A can play.
        response = self.review(self.builder_b, char_id, "approve")
        self.assertEqual(response.status_code, 200, response.content)
        bio.refresh_from_db()
        self.assertEqual((bio.status, bio.reviewed_by), ("approved", self.builder_b))
        self.assertEqual(char.location, self.room1)
        self.assertEqual(char.home, self.room1)
        run_command(CmdIC, self.player_a, session, "Mara Voss")
        self.assertEqual(session.puppet, char)

        # +sheet shows the submitted traits.
        from commands.v5.utils.display_utils import format_character_sheet

        sheet = format_character_sheet(char)
        self.assertIn("Brujah", sheet)
        self.assertIn("Alleycat", sheet)

        # Admin D revokes: A's live session loses the character and can't take it back.
        response = self.review(self.admin_d, char_id, "revoke", "Sheet needs another look")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(session.puppet)
        self.assertEqual(char.sessions.count(), 0)
        run_command(CmdIC, self.player_a, session, "Mara Voss")
        self.assertIsNone(session.puppet)
        bio.refresh_from_db()
        self.assertEqual((bio.status, bio.reviewed_by), ("revoked", self.admin_d))

    def test_owner_can_chardelete_a_pending_character(self):
        _, char_id = self.create_as(self.player_a)
        char = self.character(char_id)
        session = login(self.player_a, 22)
        run_command(CmdCharDelete, self.player_a, session, "Mara Voss")
        getinput = self.player_a.ndb._getinput
        self.assertIsNotNone(getinput, "chardelete refused before asking for confirmation")
        getinput._callback(self.player_a, getinput._prompt, "yes")

        self.assertFalse(ObjectDB.objects.filter(id=char_id).exists())
        self.assertFalse(CharacterBio.objects.filter(character_id=char_id).exists())
        self.assertNotIn(char, self.player_a.characters.all())

    def test_ancilla_with_nine_advantage_dots(self):
        response, char_id = self.create_as(self.player_a, ancilla_payload())
        self.assertEqual(response.status_code, 201, response.content)
        char = self.character(char_id)
        self.assertEqual((char.generation, char.blood_potency, char.humanity, char.xp), (11, 2, 5, 35))

    def test_validate_endpoint_uses_the_same_validator(self):
        response = self.post("/api/traits/character/validate/", legal_payload(), self.player_a)
        self.assertEqual(response.json(), {"valid": True, "errors": []})
        bad = legal_payload()
        bad["attributes"]["strength"] = 5
        response = self.post("/api/traits/character/validate/", bad, self.player_a)
        self.assertFalse(response.json()["valid"])
        self.assertFalse(ObjectDB.objects.filter(db_key="Mara Voss").exists())

    def test_my_characters_lists_only_mine(self):
        self.create_as(self.player_a)
        self.as_(self.player_c)
        self.assertEqual(self.client.get("/api/traits/my-characters/").json()["characters"], [])
        self.as_(self.player_a)
        mine = self.client.get("/api/traits/my-characters/").json()["characters"]
        self.assertEqual(
            [(c["character_name"], c["status"], c["clan"]) for c in mine], [("Mara Voss", "submitted", "Brujah")]
        )


class SelfApprovalTests(ChargenWebTestCase):
    def test_builder_cannot_approve_own_character(self):
        _, char_id = self.create_as(self.builder_b)
        response = self.review(self.builder_b, char_id, "approve")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(CharacterBio.objects.get(character_id=char_id).status, "submitted")
        response = self.review(self.builder_b, char_id, "reject", "nope")
        self.assertEqual(response.status_code, 403)

    def test_admin_may_approve_own_character_and_it_is_recorded(self):
        _, char_id = self.create_as(self.admin_d)
        response = self.review(self.admin_d, char_id, "approve")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["self_reviewed"])
        bio = CharacterBio.objects.get(character_id=char_id)
        self.assertEqual((bio.status, bio.reviewed_by), ("approved", self.admin_d))
        detail = self.as_(self.builder_b).get(url(char_id, "detail")).json()
        self.assertEqual(detail["bio"]["reviewed_by"], "AdminD")
        self.assertTrue(detail["bio"]["self_reviewed"])


class BypassTests(ChargenWebTestCase):
    def test_stock_create_route_creates_nothing(self):
        before = ObjectDB.objects.count()
        self.as_(self.player_a)
        response = self.client.post("/characters/create/", {"db_key": "Sneaky", "desc": "x"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/character-creation/")
        self.assertEqual(ObjectDB.objects.count(), before)
        self.assertFalse(ObjectDB.objects.filter(db_key="Sneaky").exists())

    def test_stock_update_route_redirects(self):
        _, char_id = self.create_as(self.player_a)
        self.as_(self.player_a)
        response = self.client.post(f"/characters/update/mara-voss/{char_id}/", {"db_key": "Renamed"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.character(char_id).key, "Mara Voss")
        self.assertEqual(self.client.get(f"/characters/update/mara-voss/{char_id}/").status_code, 302)

    def test_raw_create_object_cannot_be_puppeted(self):
        char = create.create_object("typeclasses.characters.Character", key="RawMade")
        self.player_a.characters.add(char)
        session = login(self.player_a, 23)
        run_command(CmdIC, self.player_a, session, "RawMade")
        self.assertIsNone(session.puppet)


class AuthorizationTests(ChargenWebTestCase):
    def test_other_players_get_403(self):
        _, char_id = self.create_as(self.player_a)
        self.review(self.builder_b, char_id, "reject", "Fix it")
        self.as_(self.player_c)
        self.assertEqual(self.client.get(url(char_id, "detail")).status_code, 403)
        self.assertEqual(self.client.get(url(char_id, "export")).status_code, 403)
        self.assertEqual(self.client.get(url(char_id, "for-edit")).status_code, 403)
        self.assertEqual(self.post(url(char_id, "resubmit"), legal_payload()).status_code, 403)
        # A Builder may read it but can't resubmit someone else's application.
        self.as_(self.builder_b)
        self.assertEqual(self.client.get(url(char_id, "detail")).status_code, 200)
        self.assertEqual(self.client.get(url(char_id, "export")).status_code, 200)
        self.assertEqual(self.post(url(char_id, "resubmit"), legal_payload()).status_code, 403)
        # The owner may read it.
        self.as_(self.player_a)
        self.assertEqual(self.client.get(url(char_id, "detail")).status_code, 200)

    def test_non_builders_cannot_review(self):
        _, char_id = self.create_as(self.player_a)
        staff_flag_only = self.make_account("StaffFlag")
        staff_flag_only.is_staff = True
        staff_flag_only.save()
        for account in (self.player_c, staff_flag_only):
            self.assertEqual(self.review(account, char_id, "approve").status_code, 403)
            self.assertEqual(self.as_(account).get("/api/traits/pending-characters/").status_code, 403)
            self.assertEqual(self.as_(account).get("/staff/character-approval/").status_code, 403)
        self.assertEqual(self.as_(self.builder_b).get("/staff/character-approval/").status_code, 200)
        self.assertEqual(CharacterBio.objects.get(character_id=char_id).status, "submitted")

    def test_only_admins_revoke(self):
        _, char_id = self.create_as(self.player_a)
        self.review(self.builder_b, char_id, "approve")
        builder2 = self.make_account("BuilderE", permissions=["Builder"])
        self.assertEqual(self.review(builder2, char_id, "revoke", "no").status_code, 403)
        self.assertEqual(CharacterBio.objects.get(character_id=char_id).status, "approved")

    def test_anonymous_callers_are_refused(self):
        _, char_id = self.create_as(self.player_a)
        self.as_(None)
        self.assertEqual(self.post(CREATE, legal_payload()).status_code, 401)
        self.assertEqual(self.client.get(url(char_id, "detail")).status_code, 401)
        self.assertEqual(self.client.get("/api/traits/pending-characters/").status_code, 401)

    def test_pending_list_shows_review_rights(self):
        _, mine = self.create_as(self.builder_b)
        _, theirs = self.create_as(self.player_a, legal_payload(name="Other Person"))
        rows = self.as_(self.builder_b).get("/api/traits/pending-characters/").json()["pending_characters"]
        rights = {row["character_id"]: row["can_review"] for row in rows}
        self.assertEqual(rights, {mine: False, theirs: True})

    def test_double_review_is_a_conflict(self):
        _, char_id = self.create_as(self.player_a)
        self.assertEqual(self.review(self.builder_b, char_id, "approve").status_code, 200)
        self.assertEqual(self.review(self.admin_d, char_id, "reject", "late").status_code, 409)
        self.assertEqual(CharacterBio.objects.get(character_id=char_id).status, "approved")


class ValidationTests(ChargenWebTestCase):
    def assert_400(self, payload, fragment=None):
        response = self.post(CREATE, payload, self.player_a)
        self.assertEqual(response.status_code, 400, response.content)
        if fragment:
            self.assertIn(fragment, response.json()["error"])
        self.assertFalse(CharacterBio.objects.exists())
        self.assertEqual(list(self.player_a.characters.all()), [])

    def test_smuggled_dict(self):
        payload = legal_payload()
        payload["advantages"][0]["value"] = {"dots": 5}
        payload["attributes"]["strength"] = {"value": 4, "approved": True}
        self.assert_400(payload, "unknown key(s) value")

    def test_bad_attribute_spread(self):
        payload = legal_payload()
        payload["attributes"].update({"dexterity": 4, "stamina": 3, "wits": 1})
        self.assert_400(payload, "Attributes:")

    def test_v20_payload(self):
        """The old form's character_data wrapper and flat 7/5/3 keys."""
        old = {
            "character_data": {
                "name": "Old Form", "clan": "Brujah", "strength": 3, "dexterity": 3, "stamina": 3,
                "disciplines": {"Potence": 2, "Celerity": 1}, "advantages": {"Resources": {"value": 3}},
            }
        }  # fmt: skip
        self.assert_400(old, "Unknown key(s): character_data")

    def test_neonate_with_nine_advantage_dots(self):
        payload = legal_payload()
        payload["advantages"].append({"name": "Herd", "dots": 2})
        self.assert_400(payload, "spend at most 7 dots")

    def test_non_object_bodies(self):
        for body in ("[1, 2]", '"text"', "3", "null", "{not json"):
            self.assert_400(body)

    def test_illegal_powers(self):
        payload = legal_payload()
        payload["discipline_powers"] = ["Lethal Body", "Prowess", "Entrancement", "Rapid Reflexes"]
        self.assert_400(payload, "Entrancement needs Presence 3")
        payload["discipline_powers"] = ["Lethal Body", "Prowess", "Awe", "Heightened Senses"]
        self.assert_400(payload, "you have no Auspex")

    def test_illegal_advantages(self):
        payload = legal_payload()
        payload["advantages"][3] = {"name": "Iron Will", "dots": 1}
        self.assert_400(payload, "unknown advantage 'Iron Will'")
        payload["advantages"][3] = {"name": "Beautiful", "dots": 1}
        self.assert_400(payload, "Beautiful is taken at 2 dots")

    def test_specialty_on_unrated_skill(self):
        payload = legal_payload()
        payload["specialties"][1] = {"skill": "finance", "name": "Banking"}
        self.assert_400(payload, "needs at least one dot in Finance")

    def test_unknown_inner_key(self):
        payload = legal_payload()
        payload["skills"]["hacking"] = 2
        self.assert_400(payload, "skills: unknown key 'hacking'")

    def test_name_rules_and_uniqueness(self):
        self.assert_400(legal_payload(name="Bad|rName"), "Name:")
        self.create_as(self.player_c, legal_payload(name="Taken Name"))
        response = self.post(CREATE, legal_payload(name="taken name"), self.player_a)
        self.assertEqual(response.status_code, 400)
        self.assertIn("already exists", response.json()["error"])

    @override_settings(MAX_NR_CHARACTERS=1)
    def test_character_limit(self):
        self.assertEqual(self.create_as(self.player_a)[0].status_code, 201)
        response, _ = self.create_as(self.player_a, legal_payload(name="Second Try"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("at most 1", response.json()["error"])
        self.assertFalse(ObjectDB.objects.filter(db_key="Second Try").exists())


class ResubmitTests(ChargenWebTestCase):
    def setUp(self):
        super().setUp()
        _, self.char_id = self.create_as(self.player_a)
        self.review(self.builder_b, self.char_id, "reject", "Pick a different spread")

    def test_for_edit_returns_the_submission(self):
        data = self.as_(self.player_a).get(url(self.char_id, "for-edit")).json()
        self.assertEqual(data["character_data"], parse_submission(legal_payload()).as_dict())
        self.assertEqual(data["rejection_notes"], "Pick a different spread")

    def test_typo_is_rejected_and_the_sheet_is_unchanged(self):
        char = self.character(self.char_id)
        before = export_character(char)
        payload = legal_payload()
        payload["advantages"][3] = {"name": "Linguistcs", "dots": 1}
        response = self.post(url(self.char_id, "resubmit"), payload, self.player_a)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(export_character(char), before)
        self.assertEqual(CharacterBio.objects.get(character_id=self.char_id).status, "rejected")

    def test_resubmit_replaces_the_sheet(self):
        payload = legal_payload(name="Mara Vossen")
        payload["attributes"].update({"strength": 2, "charisma": 4, "manipulation": 3, "composure": 3, "wits": 2})
        payload["attributes"].update({"dexterity": 3, "stamina": 2, "intelligence": 2, "resolve": 1})
        payload["disciplines"] = {"Celerity": 2, "Presence": 2}
        payload["discipline_powers"] = ["Cat's Grace", "Fleetness", "Daunt", "Lingering Kiss"]
        response = self.post(url(self.char_id, "resubmit"), payload, self.player_a)
        self.assertEqual(response.status_code, 200, response.content)

        char = self.character(self.char_id)
        fresh = create.create_object("typeclasses.characters.Character", key="Fresh Copy")
        apply_chargen(fresh, parse_submission(payload))
        resubmitted, expected = export_character(char), export_character(fresh)
        for sheet in (resubmitted, expected):
            sheet.pop("name"), sheet.pop("status")
        self.assertEqual(resubmitted, expected)
        self.assertEqual(char.key, "Mara Vossen")
        self.assertNotIn("Potence", char.discipline_levels)
        bio = CharacterBio.objects.get(character_id=self.char_id)
        self.assertEqual((bio.status, bio.rejection_notes), ("submitted", ""))

    def test_only_rejected_or_revoked_can_be_resubmitted(self):
        self.post(url(self.char_id, "resubmit"), legal_payload(), self.player_a)
        response = self.post(url(self.char_id, "resubmit"), legal_payload(), self.player_a)
        self.assertEqual(response.status_code, 409)


class FailurePathTests(ChargenWebTestCase):
    def test_failure_after_create_leaves_nothing_behind(self):
        """R-11: undo is Evennia-level; check in-memory state, not just rows."""
        characters_before = list(self.player_a.characters.all())
        with mock.patch("traits.utils.apply_chargen", side_effect=RuntimeError("injected")):
            response, _ = self.create_as(self.player_a)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(list(self.player_a.characters.all()), characters_before)
        self.assertFalse(ObjectDB.objects.filter(db_key="Mara Voss").exists())
        self.assertFalse(CharacterBio.objects.exists())
        self.assertFalse(Job.objects.exists())
        # The name is free again.
        self.assertEqual(self.create_as(self.player_a)[0].status_code, 201)

    def test_failure_after_the_bio_is_written(self):
        with mock.patch("traits.utils._open_approval_job", side_effect=RuntimeError("injected")):
            response, _ = self.create_as(self.player_a)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(list(self.player_a.characters.all()), [])
        self.assertFalse(ObjectDB.objects.filter(db_key="Mara Voss").exists())
        self.assertFalse(CharacterBio.objects.exists())

    def test_failed_resubmit_restores_the_sheet(self):
        _, char_id = self.create_as(self.player_a)
        self.review(self.builder_b, char_id, "reject", "again")
        char = self.character(char_id)
        before = export_character(char)
        payload = legal_payload(name="New Name")
        payload["attributes"].update({"strength": 3, "dexterity": 4})
        with mock.patch.object(CharacterBio, "transition", side_effect=RuntimeError("injected")):
            response = self.post(url(char_id, "resubmit"), payload, self.player_a)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(export_character(char), before)
        self.assertEqual(char.key, "Mara Voss")

    def test_approval_needs_a_start_location(self):
        _, char_id = self.create_as(self.player_a)
        with override_settings(START_LOCATION="#999999"):
            response = self.review(self.builder_b, char_id, "approve")
        self.assertEqual(response.status_code, 409)
        self.assertIn("START_LOCATION", response.json()["error"])
        self.assertIsNone(self.character(char_id).location)
        self.assertEqual(CharacterBio.objects.get(character_id=char_id).status, "submitted")


class ThreadDisciplineTests(ChargenWebTestCase):
    def test_world_changes_go_through_the_main_thread_helper(self):
        with mock.patch.object(traits_api, "call_in_main_thread", wraps=main_thread.call_in_main_thread) as spy:
            _, char_id = self.create_as(self.player_a)
            self.review(self.builder_b, char_id, "reject", "fix")
            self.post(url(char_id, "resubmit"), legal_payload(), self.player_a)
            self.review(self.builder_b, char_id, "approve")
            self.review(self.admin_d, char_id, "revoke", "bye")
        units = [call.args[0] for call in spy.call_args_list]
        self.assertEqual(
            units, [create_character_unit, traits_api.reject_unit, resubmit_unit, approve_unit, revoke_unit]
        )


class RulesDataTests(ChargenWebTestCase):
    def test_trait_lists_come_from_v5_data(self):
        self.as_(self.player_a)
        advantages = self.client.get("/api/traits/?category=advantages").json()["traits"]
        flaws = self.client.get("/api/traits/?category=flaws").json()["traits"]
        self.assertIn("Herd", [t["name"] for t in advantages])
        self.assertIn("Suspect", [t["name"] for t in flaws])
        disciplines = [t["name"] for t in self.client.get("/api/traits/?category=disciplines").json()["traits"]]
        self.assertNotIn("Oblivion", disciplines)
        self.assertEqual(self.client.get("/api/traits/?category=nonsense").status_code, 400)
        powers = self.client.get("/api/traits/discipline-powers/?discipline=Potence").json()["powers"]
        self.assertIn("Prowess", [p["name"] for p in powers])
