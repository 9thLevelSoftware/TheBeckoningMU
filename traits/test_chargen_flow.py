"""Local session API lifecycle with real catalog, characters and trait persistence."""

import copy
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from evennia.objects.models import ObjectDB
from evennia.utils.create import create_account
from evennia.utils.test_resources import EvenniaTest

from traits.models import CharacterBio, CharacterPower, CharacterTrait, DisciplinePower, Trait, TraitCategory
from traits.utils import V5_ATTRIBUTES, V5_SKILLS


class ChargenFlowTests(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.owner = create_account("chargen-owner", email=None, password="local-fixture-only")
        self.other = create_account("chargen-other", email=None, password="local-fixture-only")
        self.staff = create_account("chargen-staff", email=None, password="local-fixture-only")
        self.staff.is_staff = True
        self.staff.save(update_fields=["is_staff"])
        self.web = Client()
        self.web.force_login(self.owner)
        self.bridge = patch("traits.web_bridge.run_sync_in_main_thread", side_effect=lambda work: work()).start()
        self.addCleanup(patch.stopall)
        for category, names in {
            "attributes": V5_ATTRIBUTES,
            "skills": V5_SKILLS,
            "disciplines": ["Celerity", "Potence"],
            "advantages": ["Resources", "Allies"],
            "flaws": ["Enemy"],
        }.items():
            group = TraitCategory.objects.create(name=category.title(), code=category)
            for name in names:
                Trait.objects.create(
                    name=name.replace("_", " ").title(),
                    category=group,
                    min_value=1 if category == "attributes" else 0,
                    max_value=5,
                    is_instanced=name in {"Allies", "Enemy"},
                    has_specialties=category == "skills",
                    splat_restriction="vampire" if category == "disciplines" else "",
                )
        self.payload = {
            "name": "Local Applicant",
            "splat": "vampire",
            "clan": "Brujah",
            "concept": "Night courier",
            "generation": 13,
            "predator_type": "Alleycat",
            "predator_discipline": "Potence",
            "ambition": "Build a haven",
            "desire": "Find a friend",
            "background": "Private application background",
            **dict(zip(V5_ATTRIBUTES, [4, 3, 3, 3, 3, 2, 2, 2, 2], strict=True)),
            **dict.fromkeys(V5_SKILLS, 0),
            "athletics": 5,
            "brawl": 4,
            "craft": 4,
            "insight": 3,
            "persuasion": 3,
            "streetwise": 3,
            "academics": 2,
            "awareness": 2,
            "occult": 1,
            "disciplines": {"Celerity": 2, "Potence": 2},
            "advantages": {"Resources": {"value": 4}, "Allies": {"value": 3, "instance": "Neighbors"}},
            "flaws": {"Enemy": {"value": 1, "instance": "Hunters"}},
        }

    def post(self, name, payload, character=None, *, expected=200):
        url = reverse(f"traits:{name}", args=(character.pk,) if character else ())
        response = self.web.post(url, payload, content_type="application/json")
        self.assertEqual(response.status_code, expected, response.content)
        return response

    def create(self):
        response = self.post("character_create", {"character_data": self.payload})
        return ObjectDB.objects.get(pk=response.json()["character_id"])

    def reject(self, character):
        self.web.force_login(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            self.post("character_approval", {"action": "reject", "notes": "Revise the haven."}, character)
        self.web.force_login(self.owner)

    def test_create_reject_edit_resubmit_approve_preserves_full_sheet(self):
        character = self.create()
        self.assertEqual(character.db.stats["attributes"]["physical"]["strength"], 4)
        self.assertEqual(character.db.stats["skills"]["physical"]["athletics"], 5)
        self.assertEqual(character.db.stats["disciplines"]["potence"]["level"], 2)
        self.assertEqual(character.db.vampire["clan"], "Brujah")
        self.assertEqual(character.db.pools["health"], 6)
        self.assertEqual(character.db.pools["willpower"], 4)
        self.assertNotIn(character, self.owner.characters.all())
        self.assertFalse(character.access(self.owner, "puppet"))
        self.assertEqual(CharacterBio.objects.get(character=character).status, "submitted")
        self.reject(character)
        response = self.web.get(reverse("traits:character_for_edit", args=(character.pk,)))
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()["character_data"]
        self.assertEqual(data["predator_discipline"], "Potence")
        self.assertEqual(data["advantages"]["Allies"], {"value": 3, "instance": "Neighbors"})
        self.assertEqual(data["background"], self.payload["background"])
        data["name"] = "Revised Applicant"
        data["background"] = "Revised private background"
        self.post("character_resubmit", {"character_data": data}, character)
        bio = CharacterBio.objects.get(character=character)
        self.assertEqual((bio.status, bio.rejection_count, bio.approved_by), ("submitted", 1, ""))
        self.assertIsNone(bio.approved_at)
        self.assertEqual(character.key, "Revised Applicant")
        self.web.force_login(self.staff)
        with self.settings(START_LOCATION=f"#{self.room1.pk}"), self.captureOnCommitCallbacks(execute=True):
            self.post("character_approval", {"action": "approve"}, character)
        self.assertEqual(CharacterBio.objects.get(character=character).status, "approved")
        self.assertEqual(character.location, self.room1)
        self.assertEqual(character.home, self.room1)
        self.assertIn(character, self.owner.characters.all())
        self.assertTrue(character.access(self.owner, "puppet"))
        self.assertTrue(character.db.stats["approved"])
        self.assertEqual(len(self.owner.db.pending_notifications), 2)
        self.post("character_approval", {"action": "approve"}, character, expected=409)
        self.web.force_login(self.owner)
        self.post("character_resubmit", {"character_data": data}, character, expected=400)
        self.assertGreaterEqual(self.bridge.call_count, 5)

    def test_invalid_resubmission_preserves_persisted_and_cached_sheet(self):
        character = self.create()
        self.reject(character)
        before_traits = list(CharacterTrait.objects.filter(character=character).values())
        before_stats = copy.deepcopy(dict(character.db.stats))
        before_bio = CharacterBio.objects.values().get(character=character)
        invalid = copy.deepcopy(self.payload)
        invalid["name"] = "Must not rename"
        invalid["discipline_powers"] = ["Missing power"]
        self.post("character_resubmit", {"character_data": invalid}, character, expected=400)
        self.assertEqual(list(CharacterTrait.objects.filter(character=character).values()), before_traits)
        self.assertEqual(dict(character.db.stats), before_stats)
        self.assertEqual(CharacterBio.objects.values().get(character=character), before_bio)
        self.assertEqual(character.key, self.payload["name"])

    def test_authority_is_rechecked_inside_dispatch_and_cross_owner_is_denied(self):
        character = self.create()
        self.reject(character)
        self.web.force_login(self.other)
        self.post("character_resubmit", {"character_data": self.payload}, character, expected=403)
        self.post("character_approval", {"action": "approve"}, character, expected=403)
        self.assertEqual(self.web.get(reverse("traits:character_for_edit", args=(character.pk,))).status_code, 403)
        self.web.force_login(self.staff)
        get_user_model().objects.filter(pk=self.staff.pk).update(is_staff=False, is_superuser=False)
        self.post("character_approval", {"action": "approve"}, character, expected=403)

    def test_invalid_create_and_json_do_not_create_partial_objects(self):
        before = ObjectDB.objects.count()
        for invalid in ({}, {"name": 123}, {**self.payload, "disciplines": []}):
            with self.subTest(invalid=invalid):
                self.post("character_create", {"character_data": invalid}, expected=400)
        self.post("character_create", [], expected=400)
        self.assertEqual(ObjectDB.objects.count(), before)
        self.assertEqual(CharacterBio.objects.count(), 0)

    def test_creation_requires_login_and_csrf(self):
        self.web.logout()
        self.post("character_create", {"character_data": self.payload}, expected=401)
        self.assertEqual(self.web.get(reverse("character_creation")).status_code, 302)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.owner)
        response = protected.post(
            reverse("traits:character_create"), {"character_data": self.payload}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 403)

    def test_failed_approval_restores_room_roster_and_cached_character(self):
        character = self.create()
        before_locks = character.db_lock_storage
        self.web.force_login(self.staff)
        with (
            self.settings(START_LOCATION=f"#{self.room1.pk}"),
            patch.object(CharacterBio, "save", side_effect=RuntimeError("Approval save failed")),
            self.assertRaisesMessage(RuntimeError, "Approval save failed"),
        ):
            self.post("character_approval", {"action": "approve"}, character)
        self.assertEqual(CharacterBio.objects.get(character=character).status, "submitted")
        self.assertIsNone(character.location)
        self.assertIsNone(character.home)
        self.assertNotIn(character, self.room1.contents)
        self.assertNotIn(character, self.owner.characters.all())
        self.assertEqual(character.db_lock_storage, before_locks)
        self.assertFalse(character.access(self.owner, "puppet"))
        self.assertFalse(self.owner.db.pending_notifications)

    def test_persisted_transfer_revokes_cached_owner_and_approval_uses_current_owner(self):
        character = self.create()
        self.reject(character)
        self.assertEqual(character.db_account, self.owner)  # retain a warm FK cache
        ObjectDB.objects.filter(pk=character.pk).update(db_account=self.other)
        self.assertEqual(character.db_account_id, self.owner.pk)
        for route in ("character_for_edit", "character_export", "character_available_traits"):
            response = self.web.get(reverse(f"traits:{route}", args=(character.pk,)))
            self.assertEqual(response.status_code, 403, response.content)
        self.post("character_resubmit", {"character_data": self.payload}, character, expected=403)
        self.web.force_login(self.other)
        self.post("character_resubmit", {"character_data": self.payload}, character)
        self.web.force_login(self.staff)
        with self.settings(START_LOCATION=f"#{self.room1.pk}"), self.captureOnCommitCallbacks(execute=True):
            self.post("character_approval", {"action": "approve"}, character)
        self.assertIn(character, self.other.characters.all())
        self.assertNotIn(character, self.owner.characters.all())
        self.assertEqual(self.other.db.pending_notifications[-1]["type"], "approval")

    def test_edit_roundtrip_keeps_specialties_and_learned_powers(self):
        power = DisciplinePower.objects.create(
            name="Local Fleetness",
            discipline=Trait.objects.get(name="Celerity"),
            level=1,
        )
        self.payload["specialties"] = {"Athletics": {"Climbing": 1}}
        self.payload["discipline_powers"] = [power.name]
        character = self.create()
        self.reject(character)
        data = self.web.get(reverse("traits:character_for_edit", args=(character.pk,))).json()["character_data"]
        self.post("character_resubmit", {"character_data": data}, character)
        self.assertTrue(CharacterPower.objects.filter(character=character, power=power).exists())
        self.assertTrue(CharacterTrait.objects.filter(character=character, specialty="Climbing").exists())
