"""
CharacterBio's status machine: the one record of a character's approval.
"""

from evennia.utils import create
from evennia.utils.test_resources import EvenniaTest

from traits.models import CharacterBio


class CharacterBioTransitionTests(EvenniaTest):
    def setUp(self):
        super().setUp()
        self.char = create.create_object("typeclasses.characters.Character", key="Applicant")
        self.bio = CharacterBio.objects.create(character=self.char, account=self.account2, status="submitted")

    def test_allowed_path(self):
        self.bio.transition("rejected", by=self.account)
        self.assertEqual((self.bio.status, self.bio.reviewed_by), ("rejected", self.account))
        self.assertIsNotNone(self.bio.reviewed_at)
        self.bio.transition("submitted")
        self.assertEqual(self.bio.reviewed_by, self.account, "a resubmission keeps the last review record")
        self.bio.transition("approved", by=self.account)
        self.bio.transition("revoked", by=self.account)
        self.bio.transition("submitted")
        self.assertEqual(self.bio.status, "submitted")

    def test_disallowed_transitions(self):
        for to in ("revoked", "submitted"):
            with self.assertRaises(CharacterBio.TransitionError):
                self.bio.transition(to, by=self.account)
        self.bio.transition("approved", by=self.account)
        for to in ("approved", "rejected", "submitted"):
            with self.assertRaises(CharacterBio.TransitionError):
                self.bio.transition(to, by=self.account)

    def test_a_stale_instance_cannot_transition(self):
        """Two reviewers acting on the same application: only the first wins."""
        stale = CharacterBio.objects.get(pk=self.bio.pk)
        self.bio.transition("approved", by=self.account)
        with self.assertRaises(CharacterBio.TransitionError):
            stale.transition("rejected", by=self.account2)
        self.bio.refresh_from_db()
        self.assertEqual((self.bio.status, self.bio.reviewed_by), ("approved", self.account))
