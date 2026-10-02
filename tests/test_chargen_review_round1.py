"""
Web chargen behaviour added in review round 1: applicant addresses, revoked
characters keeping their sheet, one character cap, best-effort follow-ups,
the application job's lifecycle, and the approve rollback.
"""

import json
from unittest import mock

from django.test import override_settings
from evennia.commands.default.account import CmdCharDelete, CmdIC
from evennia.objects.models import ObjectDB

from commands.v5.utils.xp_utils import award_xp
from jobs.models import Job
from tests.chargen_fixtures import legal_payload
from tests.test_character_locks import login
from tests.test_chargen_web import CREATE, ChargenWebTestCase, run_command, url
from traits import utils as chargen_utils
from traits.models import CharacterBio
from world.rules_chargen import parse_submission


class ApplicantAddressTests(ChargenWebTestCase):
    APPLICANT, REVIEWER = "203.0.113.5", "198.51.100.77"

    def create_from(self, ip, payload=None):
        self.as_(self.player_a)
        body = json.dumps(payload or legal_payload())
        response = self.client.post(CREATE, body, content_type="application/json", REMOTE_ADDR=ip)
        return response.json().get("character_id")

    def review_from(self, reviewer, char_id, ip, action="approve", notes=""):
        self.as_(reviewer)
        body = json.dumps({"action": action, "notes": notes})
        return self.client.post(url(char_id, "approval"), body, content_type="application/json", REMOTE_ADDR=ip)

    def test_addresses_are_recorded_and_same_origin_reviews_flagged(self):
        char_id = self.create_from(self.APPLICANT)
        bio = CharacterBio.objects.get(character_id=char_id)
        self.assertEqual(bio.applicant_ip, self.APPLICANT)
        self.assertEqual(self.character(char_id).db.creator_ip, self.APPLICANT)
        self.as_(self.builder_b)
        detail = self.client.get(url(char_id, "detail"), REMOTE_ADDR=self.APPLICANT).json()
        self.assertTrue(detail["same_origin_as_you"])
        self.assertEqual(detail["bio"]["applicant_ip"], self.APPLICANT)
        rows = self.client.get("/api/traits/pending-characters/", REMOTE_ADDR=self.REVIEWER).json()
        self.assertFalse(rows["pending_characters"][0]["same_origin_as_you"])
        response = self.review_from(self.builder_b, char_id, self.APPLICANT)
        self.assertTrue(response.json()["same_origin"])
        bio.refresh_from_db()
        self.assertEqual(bio.reviewer_ip, self.APPLICANT)

    def test_loopback_and_invalid_addresses_never_flag(self):
        """Behind the Portal every request is 127.0.0.1 unless a trusted proxy says otherwise."""
        char_id = self.create_from("127.0.0.1")
        response = self.review_from(self.builder_b, char_id, "127.0.0.1")
        self.assertFalse(response.json()["same_origin"])
        detail = self.as_(self.builder_b).get(url(char_id, "detail")).json()
        self.assertFalse(detail["bio"]["reviewed_same_origin"])
        self.assertFalse(detail["same_origin_as_you"])

        other = self.create_from("not-an-ip", legal_payload(name="Other Person"))
        self.assertIsNone(CharacterBio.objects.get(character_id=other).applicant_ip)
        self.assertIsNone(self.character(other).db.creator_ip)

    def test_clean_ip_and_same_origin(self):
        self.assertEqual(chargen_utils.clean_ip(" 2001:DB8::1 "), "2001:db8::1")
        for junk in ("", None, "abc", "1.2.3.4; DROP", "300.1.1.1"):
            self.assertIsNone(chargen_utils.clean_ip(junk))
        self.assertTrue(chargen_utils.same_origin("203.0.113.5", "203.0.113.5"))
        for pair in (("127.0.0.1", "127.0.0.1"), ("::1", "::1"), ("0.0.0.0", "0.0.0.0"), (None, None), ("x", "x")):
            self.assertFalse(chargen_utils.same_origin(*pair), pair)

    def test_players_never_see_addresses(self):
        """R-33: no *_ip keys (nor the reviewed-from hint) in any player's response."""
        char_id = self.create_from(self.APPLICANT)
        self.review_from(self.builder_b, char_id, self.REVIEWER, action="reject", notes="Fix it")
        for account in (self.player_a, self.player_c):
            self.as_(account)
            for path in (url(char_id, "detail"), url(char_id, "for-edit"), url(char_id, "export"),
                         "/api/traits/my-characters/"):  # fmt: skip
                response = self.client.get(path)
                text = response.content.decode()
                self.assertNotIn("_ip", text, (account.key, path))
                self.assertNotIn(self.REVIEWER, text)
                self.assertNotIn("reviewed_same_origin", text)
        self.as_(self.builder_b)
        self.assertEqual(self.client.get(url(char_id, "detail")).json()["bio"]["reviewer_ip"], self.REVIEWER)


class ConcurrentCreateTests(ChargenWebTestCase):
    """R-34: the unit re-checks name and cap on the reactor, so a request that
    passed the web thread's checks alongside another can't create a duplicate."""

    def test_same_name_twice(self):
        sub = parse_submission(legal_payload())
        chargen_utils.create_character_unit(self.player_a, sub)
        with self.assertRaises(chargen_utils.ChargenError):
            chargen_utils.create_character_unit(self.player_a, sub)
        self.assertEqual(ObjectDB.objects.filter(db_key__iexact="Mara Voss").count(), 1)
        self.assertEqual(CharacterBio.objects.count(), 1)
        self.assertEqual(Job.objects.count(), 1)
        self.assertEqual(len(self.player_a.characters.all()), 1)

    @override_settings(MAX_NR_CHARACTERS=1)
    def test_at_the_cap(self):
        chargen_utils.create_character_unit(self.player_a, parse_submission(legal_payload()))
        with self.assertRaises(chargen_utils.ChargenError) as caught:
            chargen_utils.create_character_unit(self.player_a, parse_submission(legal_payload(name="Second Go")))
        self.assertIn("at most 1", str(caught.exception))
        self.assertFalse(ObjectDB.objects.filter(db_key="Second Go").exists())
        self.assertEqual(CharacterBio.objects.count(), 1)

    def test_web_checks_passed_but_unit_refuses(self):
        """Simulate the race: the web-thread name check passes (patched), the unit still refuses."""
        self.create_as(self.player_a)
        with mock.patch("traits.api.name_problem", return_value=None):
            response = self.post(CREATE, legal_payload(), self.player_c)
        self.assertEqual(response.status_code, 400)
        self.assertIn("already exists", response.json()["error"])
        self.assertEqual(ObjectDB.objects.filter(db_key__iexact="Mara Voss").count(), 1)


class NameAndPageTests(ChargenWebTestCase):
    def test_another_players_account_name_is_refused(self):
        response = self.post(CREATE, legal_payload(name="PlayerC"), self.player_a)
        self.assertEqual(response.status_code, 400)
        self.assertIn("another player's account name", response.json()["error"])

    def test_own_account_name_is_allowed(self):
        response = self.post(CREATE, legal_payload(name="PlayerA"), self.player_a)
        self.assertEqual(response.status_code, 201, response.content)

    def test_non_ascii_digit_edit_id(self):
        self.as_(self.player_a)
        self.assertEqual(self.client.get("/character-creation/?edit=²").status_code, 200)

    def test_creation_logs_no_lock_change_warnings(self):
        with mock.patch("evennia.locks.lockhandler.logger.log_file") as log_file:
            self.create_as(self.player_a)
        # Evennia's own DefaultCharacter.basetype_setup still overrides get/call/
        # teleport; the gated puppet/delete/edit locks must be installed once.
        logged = " ".join(str(c.args[0]) for c in log_file.call_args_list)
        for access_type in ("puppet", "delete", "edit"):
            self.assertNotIn(f"access type '{access_type}' changed", logged)


class CharacterCapTests(ChargenWebTestCase):
    @override_settings(MAX_NR_CHARACTERS=1)
    def test_rejected_characters_do_not_count(self):
        _, first = self.create_as(self.player_a)
        self.review(self.builder_b, first, "reject", "no")
        response, _ = self.create_as(self.player_a, legal_payload(name="Second Go"))
        self.assertEqual(response.status_code, 201, response.content)
        response, _ = self.create_as(self.player_a, legal_payload(name="Third Go"))
        self.assertEqual(response.status_code, 400)


class RevokedResubmitTests(ChargenWebTestCase):
    """Owner decision: revoking pauses play; resubmitting keeps the played sheet."""

    def setUp(self):
        super().setUp()
        _, self.char_id = self.create_as(self.player_a)
        self.review(self.builder_b, self.char_id, "approve")
        self.char = self.character(self.char_id)
        award_xp(self.char, 10, reason="played a session")
        self.char.set_trait("strength", 5)
        self.review(self.admin_d, self.char_id, "revoke", "Needs another look")

    def test_resubmit_keeps_sheet_and_xp(self):
        data = self.as_(self.player_a).get(url(self.char_id, "for-edit")).json()
        self.assertEqual(data["mode"], "revoked")
        self.assertEqual(data["sheet"]["xp"]["earned"], 25)
        response = self.post(url(self.char_id, "resubmit"), {"concept": "Reformed enforcer"}, self.player_a)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((self.char.xp_earned, len(self.char.db.experience["log"])), (25, 2))
        self.assertEqual(self.char.get_trait("strength"), 5)
        bio = CharacterBio.objects.get(character_id=self.char_id)
        self.assertEqual((bio.status, bio.concept), ("submitted", "Reformed enforcer"))
        self.assertEqual(self.review(self.builder_b, self.char_id, "approve").status_code, 200)

    def test_a_new_sheet_is_refused(self):
        response = self.post(url(self.char_id, "resubmit"), legal_payload(), self.player_a)
        self.assertEqual(response.status_code, 400)
        self.assertIn("keeps its sheet", response.json()["error"])
        self.assertEqual(self.char.xp_earned, 25)
        self.assertEqual(CharacterBio.objects.get(character_id=self.char_id).status, "revoked")

    def test_required_narrative(self):
        response = self.post(url(self.char_id, "resubmit"), {"ambition": ""}, self.player_a)
        self.assertEqual(response.status_code, 400)


class BestEffortTests(ChargenWebTestCase):
    def test_revoke_continues_past_a_failing_session(self):
        _, char_id = self.create_as(self.player_a)
        self.review(self.builder_b, char_id, "approve")
        first, second = login(self.player_a, 31), login(self.player_a, 32)
        run_command(CmdIC, self.player_a, first, "Mara Voss")
        run_command(CmdIC, self.player_a, second, "Mara Voss")
        char = self.character(char_id)
        self.assertEqual(char.sessions.count(), 2)
        real_evict = chargen_utils._evict
        calls = []

        def flaky(character, session, notes):
            calls.append(session)
            if len(calls) == 1:
                raise RuntimeError("injected")
            return real_evict(character, session, notes)

        with mock.patch.object(chargen_utils, "_evict", side_effect=flaky):
            response = self.review(self.admin_d, char_id, "revoke", "bye")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(calls), 2)
        self.assertEqual(char.sessions.count(), 1)
        self.assertEqual(CharacterBio.objects.get(character_id=char_id).status, "revoked")

    def test_a_failing_notification_still_reports_the_approval(self):
        _, char_id = self.create_as(self.player_a)
        with mock.patch.object(chargen_utils, "notify_account", side_effect=RuntimeError("injected")):
            response = self.review(self.builder_b, char_id, "approve")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(CharacterBio.objects.get(character_id=char_id).status, "approved")

    def test_failed_move_is_not_approved(self):
        _, char_id = self.create_as(self.player_a)
        with mock.patch("typeclasses.characters.Character.move_to", return_value=False):
            response = self.review(self.builder_b, char_id, "approve")
        self.assertEqual(response.status_code, 500)
        self.assertIsNone(self.character(char_id).location)
        self.assertEqual(CharacterBio.objects.get(character_id=char_id).status, "submitted")

    def test_failed_transition_restores_the_character(self):
        """R-20: the approve rollback, checked on the in-memory objects."""
        _, char_id = self.create_as(self.player_a)
        char = self.character(char_id)
        old_home = char.home
        with mock.patch.object(CharacterBio, "transition", side_effect=CharacterBio.TransitionError("raced")):
            response = self.review(self.builder_b, char_id, "approve")
        self.assertEqual(response.status_code, 409)
        self.assertIsNone(char.location)
        self.assertEqual(char.home, old_home)
        self.assertNotIn(char, self.room1.contents)
        self.assertEqual(CharacterBio.objects.get(character_id=char_id).status, "submitted")

    def test_undo_removes_the_character_from_the_account_even_if_delete_fails(self):
        with (
            mock.patch("traits.utils.apply_chargen", side_effect=RuntimeError("injected")),
            mock.patch("typeclasses.characters.Character.delete", side_effect=RuntimeError("stuck")),
        ):
            response, _ = self.create_as(self.player_a)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(list(self.player_a.characters.all()), [])


class ApplicationJobTests(ChargenWebTestCase):
    def job(self, char_id):
        return Job.objects.get(id=CharacterBio.objects.get(character_id=char_id).job_id)

    def test_job_follows_the_application(self):
        _, char_id = self.create_as(self.player_a)
        job = self.job(char_id)
        self.assertEqual((job.status, job.bucket.name), ("OPEN", "Approval"))
        self.assertIn("Mara Voss", job.title)

        self.review(self.builder_b, char_id, "reject", "Pick another spread")
        job.refresh_from_db()
        self.assertEqual(job.status, "OPEN")
        self.assertIn("Pick another spread", job.comments.last().content)

        self.post(url(char_id, "resubmit"), legal_payload(name="Mara Vossen"), self.player_a)
        job.refresh_from_db()
        self.assertIn("Mara Vossen", job.title)
        self.assertIn("resubmitted", job.comments.last().content)

        self.review(self.builder_b, char_id, "approve")
        job.refresh_from_db()
        self.assertEqual((job.status, job.completed), ("CLOSED", True))

        self.review(self.admin_d, char_id, "revoke", "Recheck")
        job.refresh_from_db()
        self.assertEqual(job.status, "OPEN")

    def test_chardelete_closes_the_job(self):
        _, char_id = self.create_as(self.player_a)
        job_id = CharacterBio.objects.get(character_id=char_id).job_id
        session = login(self.player_a, 33)
        run_command(CmdCharDelete, self.player_a, session, "Mara Voss")
        getinput = self.player_a.ndb._getinput
        getinput._callback(self.player_a, getinput._prompt, "yes")
        self.assertFalse(ObjectDB.objects.filter(id=char_id).exists())
        job = Job.objects.get(id=job_id)
        self.assertEqual(job.status, "CLOSED")
        self.assertIn("was deleted", job.comments.last().content)
