"""Persisted case records, read projections and canonical ownership guards."""

from django.conf import settings
from evennia.utils import create
from evennia.utils.test_resources import EvenniaCommandTest

from traits.models import CharacterBio

from .commands import CmdBoon, CmdBoonAdmin
from .models import Boon
from .utils import boon_view_level, can_resolve, canonical_owner_id, offer_boon, project_boon


class BoonCaseViewTests(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.session.protocol_flags["SCREENHEIGHT"] = {0: 200}
        self.people = []
        for name, permission in (
            ("Debtor", ""),
            ("Creditor", ""),
            ("Observer", ""),
            ("Harpy", "Harpy"),
            ("Builder", "Builder"),
        ):
            account = create.create_account(name, email=f"{name}@example.com", password="testpass123")
            if permission:
                account.permissions.add(permission)
            char = create.create_object(settings.BASE_CHARACTER_TYPECLASS, key=name, location=self.room1)
            char.account = account
            CharacterBio.objects.create(character=char, account=account)
            char.sessions.add(self.session)
            self.people.append(char)
        self.debtor, self.creditor, self.observer, self.harpy, self.builder = self.people
        self.alt = create.create_object(settings.BASE_CHARACTER_TYPECLASS, key="Alt", location=self.room1)
        CharacterBio.objects.create(character=self.alt, account=self.debtor.account)
        self.alt.sessions.add(self.session)
        self.boon = Boon.objects.create(
            debtor=self.debtor,
            creditor=self.creditor,
            boon_type="major",
            description="Original public favor",
            called_in_description="PRIVATE REQUEST",
            fulfillment_description="PRIVATE CASE",
            staff_notes="STAFF SECRET",
        )

    def view(self, actor, boon=None):
        return self.call(CmdBoon(), f"/view {(boon or self.boon).pk}", caller=actor)

    def test_visibility_matrix_and_projection(self):
        for public in (True, False):
            self.boon.is_public = public
            self.boon.save()
            levels = (
                "case",
                "case",
                "summary" if public else "none",
                "case" if public else "none",
                "staff",
                "summary" if public else "none",
            )
            for actor, expected in zip(self.people + [self.alt], levels, strict=True):
                with self.subTest(public=public, actor=actor.key):
                    self.assertEqual(boon_view_level(actor, self.boon), expected)
                    output = self.view(actor)
                    self.assertEqual("PRIVATE REQUEST" in output, expected in ("case", "staff"))
                    self.assertEqual("PRIVATE CASE" in output, expected in ("case", "staff"))
                    self.assertEqual("STAFF SECRET" in output, expected == "staff")
                    if expected == "summary":
                        self.assertIn("Original public favor", output)
                        self.assertNotIn("Case record", output)
        self.assertEqual(project_boon(self.boon, "none"), {})

    def test_missing_and_denied_are_indistinguishable(self):
        self.boon.is_public = False
        self.boon.save()
        denied = self.view(self.observer)
        missing = self.call(CmdBoon(), "/view 99999999", caller=self.observer)
        self.assertEqual(denied, missing)
        self.assertEqual(self.call(CmdBoon(), "/view invalid", caller=self.observer), missing)

    def test_full_persisted_case_survives_transitions_and_read(self):
        original = "Original " + "o" * 220 + " ORIGINAL-END"
        request = "Request " + "r" * 220 + " REQUEST-END"
        confirmation = "Done " + "c" * 220 + " CONFIRM-END"
        dispute = "Dispute " + "d" * 220 + " DISPUTE-END"
        ruling = "Ruling " + "u" * 220 + " RULING-END"
        self.boon.description = original
        self.boon.save()
        self.boon.accept()
        self.boon.call_in(request)
        self.boon.confirm_fulfilled(self.debtor, confirmation)
        self.boon.dispute(dispute, by=self.creditor.key)
        self.boon.uphold(ruling, by=self.harpy.key)
        self.boon.confirm_fulfilled(self.creditor, "CREDITOR-END")
        stored = Boon.objects.get(pk=self.boon.pk)
        before = stored.modified_date
        output = self.view(self.debtor, stored)
        for text in (original, request, confirmation, dispute, ruling, "CREDITOR-END", "Case record", "Fulfilled"):
            self.assertIn(text, output)
        for field in ("created_date", "accepted_date", "called_in_date", "fulfilled_date", "modified_date"):
            self.assertIn(str(getattr(stored, field)), output)
        self.assertTrue(stored.debtor_confirmed and stored.creditor_confirmed and stored.dispute_upheld)
        self.assertEqual(Boon.objects.get(pk=stored.pk).modified_date, before)

    def test_long_case_is_available_through_pager(self):
        self.boon.fulfillment_description = "\n".join(f"Case line {n}" for n in range(150)) + "\nFINAL PAGE SUFFIX"
        self.boon.save()
        self.view(self.debtor)
        pager = self.debtor.ndb._more
        self.assertIsNotNone(pager)
        self.assertIn("FINAL PAGE SUFFIX", "\n".join(pager.paginator(n) for n in range(pager._npages)))
        pager.page_quit()

    def test_canonical_ownership_without_puppet_or_playable_links(self):
        self.debtor.account = None
        self.assertEqual(canonical_owner_id(self.alt), canonical_owner_id(self.debtor))
        self.assertFalse(offer_boon(self.alt, self.debtor, "minor", "Self dealing")[0])
        # The Harpy is an alt of a party by persistent ownership alone.
        CharacterBio.objects.filter(character=self.debtor).update(account=self.harpy.account)
        for party_field in ("debtor", "creditor"):
            boon = Boon.objects.create(debtor=self.observer, creditor=self.builder, description="Test")
            setattr(boon, party_field, self.debtor)
            self.assertFalse(can_resolve(self.harpy, boon)[0])
            self.assertTrue(can_resolve(self.builder, boon)[0])
        unowned = create.create_object(settings.BASE_CHARACTER_TYPECLASS, key="Unowned")
        self.assertIsNone(canonical_owner_id(unowned))
        self.assertTrue(offer_boon(unowned, self.alt, "minor", "Not co-owned")[0])
        self.assertFalse(can_resolve(self.debtor, self.boon)[0])

    def test_public_harpy_and_private_builder_adjudication(self):
        for actor, public in ((self.harpy, True), (self.builder, False)):
            boon = Boon.objects.create(
                debtor=self.debtor,
                creditor=self.creditor,
                description="Ruling test",
                status="disputed",
                is_public=public,
            )
            self.call(CmdBoonAdmin(), f"/fulfill {boon.pk} = Recorded ruling", caller=actor)
            self.assertEqual(Boon.objects.get(pk=boon.pk).status, "fulfilled")
            self.assertIn("Recorded ruling", self.view(actor, boon))
