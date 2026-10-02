"""
Boon lifecycle (F-031, A-006): the debtor offers, the creditor accepts and
calls the boon in, and both confirm it repaid. Staff can override.

Alice and Bob are players (no permissions); Wren is a Builder.
"""

from django.conf import settings
from evennia.utils import create
from evennia.utils.test_resources import EvenniaCommandTest

from .commands import (
    CmdBoon,
    CmdBoonAccept,
    CmdBoonAdmin,
    CmdBoonCall,
    CmdBoonDecline,
    CmdBoonFulfill,
    CmdBoonGive,
)
from .models import Boon
from .utils import dispute_boon, get_boon_totals


class BoonLifecycleTests(EvenniaCommandTest):
    def _puppet(self, name, *perms):
        account = create.create_account(name, email=f"{name}@example.com", password="pw123456")
        for perm in perms:
            account.permissions.add(perm)
        char = create.create_object(settings.BASE_CHARACTER_TYPECLASS, key=name, location=self.room1, home=self.room1)
        char.account = account
        return char

    def setUp(self):
        super().setUp()
        self.alice = self._puppet("Alice")
        self.bob = self._puppet("Bob")
        self.wren = self._puppet("Wren", "Builder")
        self.hera = self._puppet("Hera", "Harpy")
        self.iris = self._puppet("Iris", "Harpy")

    def _offer(self, boon_type="major"):
        """Alice offers to owe Bob a boon."""
        self.call(CmdBoonGive(), f"Bob {boon_type} = Saved me from a hunter", caller=self.alice)
        return Boon.objects.get(debtor=self.alice, creditor=self.bob)

    def _status(self, boon):
        return Boon.objects.get(pk=boon.pk).status

    def test_full_lifecycle(self):
        boon = self._offer()
        self.assertEqual(boon.status, "offered")
        self.assertEqual(get_boon_totals(self.alice).total_debt_weight, 0)

        self.call(CmdBoonAccept(), str(boon.id), caller=self.bob)
        self.assertEqual(self._status(boon), "accepted")
        self.assertEqual(get_boon_totals(self.alice).major_owed, 1)
        self.assertEqual(get_boon_totals(self.bob).major_held, 1)

        self.call(CmdBoonCall(), f"{boon.id} = Hide me for a night", caller=self.bob)
        self.assertEqual(self._status(boon), "called_in")
        # A called-in boon is still owed until it is repaid.
        self.assertEqual(get_boon_totals(self.alice).total_debt_weight, 3)
        self.assertEqual(get_boon_totals(self.bob).net_weight, 3)

        self.call(CmdBoonFulfill(), f"{boon.id} = Hid him in my haven", caller=self.alice)
        self.assertEqual(self._status(boon), "called_in")
        self.call(CmdBoonFulfill(), f"{boon.id} = He did", caller=self.bob)
        self.assertEqual(self._status(boon), "fulfilled")
        self.assertEqual(get_boon_totals(self.alice).total_debt_weight, 0)

    def test_offerer_cannot_accept_own_offer(self):
        boon = self._offer()
        output = self.call(CmdBoonAccept(), str(boon.id), caller=self.alice)
        self.assertIn("Only", output)
        self.assertEqual(self._status(boon), "offered")
        self.call(CmdBoonAccept(), str(boon.id), caller=self.wren)
        self.assertEqual(self._status(boon), "offered")

    def test_only_creditor_declines(self):
        boon = self._offer()
        self.call(CmdBoonDecline(), str(boon.id), caller=self.alice)
        self.assertEqual(self._status(boon), "offered")
        self.call(CmdBoonDecline(), str(boon.id), caller=self.bob)
        self.assertEqual(self._status(boon), "declined")

    def test_only_creditor_calls_in(self):
        boon = self._offer()
        self.call(CmdBoonAccept(), str(boon.id), caller=self.bob)
        self.call(CmdBoonCall(), f"{boon.id} = Pay me", caller=self.alice)
        self.assertEqual(self._status(boon), "accepted")

    def test_debtor_cannot_mark_fulfilled_alone(self):
        boon = self._offer()
        self.call(CmdBoonAccept(), str(boon.id), caller=self.bob)
        # Not yet called in: nobody can mark it repaid.
        self.call(CmdBoonFulfill(), f"{boon.id} = Done", caller=self.alice)
        self.call(CmdBoonFulfill(), f"{boon.id} = Done", caller=self.bob)
        self.assertEqual(self._status(boon), "accepted")
        stored = Boon.objects.get(pk=boon.pk)
        self.assertFalse(stored.debtor_confirmed)
        self.assertFalse(stored.creditor_confirmed)
        self.call(CmdBoonCall(), f"{boon.id} = Hide me", caller=self.bob)
        self.call(CmdBoonFulfill(), f"{boon.id} = Done", caller=self.alice)
        self.call(CmdBoonFulfill(), f"{boon.id} = Done again", caller=self.alice)
        self.assertEqual(self._status(boon), "called_in")
        # A third party's confirmation doesn't count.
        self.call(CmdBoonFulfill(), f"{boon.id} = Done", caller=self.wren)
        self.assertEqual(self._status(boon), "called_in")

    def test_boon_summary_renders_with_major_boon(self):
        boon = self._offer("major")
        self.call(CmdBoonAccept(), str(boon.id), caller=self.bob)
        output = self.call(CmdBoon(), "", caller=self.alice)
        self.assertIn("Major Boons", output)
        output = self.call(CmdBoon(), "", caller=self.bob)
        self.assertIn("Major Boons", output)

    def test_target_must_be_a_character(self):
        output = self.call(CmdBoonGive(), "Obj minor = A favor", caller=self.alice)
        self.assertIn("characters", output)
        self.assertFalse(Boon.objects.exists())

    def test_state_guards(self):
        boon = self._offer()
        self.assertFalse(dispute_boon(boon.id, "No", self.alice)[0])
        self.assertEqual(self._status(boon), "offered")
        self.call(CmdBoonAccept(), str(boon.id), caller=self.bob)
        self.assertFalse(dispute_boon(boon.id, "No", self.wren)[0])
        self.assertTrue(dispute_boon(boon.id, "Never happened", self.alice)[0])
        self.assertEqual(self._status(boon), "disputed")

    def test_admin_is_staff_only_and_can_override(self):
        self.assertFalse(CmdBoonAdmin().access(self.bob, "cmd"))
        self.assertTrue(CmdBoonAdmin().access(self.wren, "cmd"))

        boon = self._offer()
        self.call(CmdBoonAccept(), str(boon.id), caller=self.bob)
        self.call(CmdBoonAdmin(), f"/fulfill {boon.id} = Harpy ruling", caller=self.wren)
        self.assertEqual(self._status(boon), "fulfilled")

        output = self.call(CmdBoonAdmin(), f"/cancel {boon.id} = Too late", caller=self.wren)
        self.assertIn("already fulfilled", output)
        self.assertEqual(self._status(boon), "fulfilled")

    def _called_in(self, creditor=None):
        """Alice owes `creditor` (default Bob) a called-in major boon."""
        creditor = creditor or self.bob
        self.call(CmdBoonGive(), f"{creditor.key} major = A favor", caller=self.alice)
        boon = Boon.objects.get(debtor=self.alice, creditor=creditor)
        self.call(CmdBoonAccept(), str(boon.id), caller=creditor)
        self.call(CmdBoonCall(), f"{boon.id} = Pay up", caller=creditor)
        return boon

    def test_both_fulfilment_descriptions_are_kept(self):
        boon = self._called_in()
        self.call(CmdBoonFulfill(), f"{boon.id} = Voted as asked", caller=self.alice)
        self.call(CmdBoonFulfill(), f"{boon.id} = Confirmed", caller=self.bob)
        record = Boon.objects.get(pk=boon.pk).fulfillment_description
        self.assertIn("Alice: Voted as asked", record)
        self.assertIn("Bob: Confirmed", record)

    def test_same_account_characters_cannot_trade_boons(self):
        """Owner decision: alts on one account can't owe each other."""
        account = self.alice.account
        alt = create.create_object(settings.BASE_CHARACTER_TYPECLASS, key="Altea", location=self.room1, home=self.room1)
        account.characters.add(alt)  # playable, not puppeted
        output = self.call(CmdBoonGive(), "Altea minor = Self-dealing", caller=self.alice)
        self.assertIn("same account", output)
        alt.account = account  # puppeted / web-linked
        output = self.call(CmdBoonGive(), "Alice minor = Self-dealing", caller=alt)
        self.assertIn("same account", output)
        self.assertFalse(Boon.objects.exists())

    def test_harpy_cannot_rule_on_own_boon(self):
        """Owner decision: a Harpy may not fulfil or cancel a boon they are party to."""
        self.assertTrue(CmdBoonAdmin().access(self.hera, "cmd"))
        boon = self._called_in(creditor=self.hera)
        output = self.call(CmdBoonAdmin(), f"/fulfill {boon.id} = Mine", caller=self.hera)
        self.assertIn("party to", output)
        output = self.call(CmdBoonAdmin(), f"/cancel {boon.id} = Mine", caller=self.hera)
        self.assertIn("party to", output)
        self.assertEqual(self._status(boon), "called_in")
        # As debtor too.
        self.call(CmdBoonGive(), "Alice minor = Hera owes", caller=self.hera)
        owed = Boon.objects.get(debtor=self.hera)
        self.call(CmdBoonAccept(), str(owed.id), caller=self.alice)
        self.call(CmdBoonAdmin(), f"/cancel {owed.id} = Wipe my debt", caller=self.hera)
        self.assertEqual(self._status(owed), "accepted")
        # A Harpy who is not a party may rule; so may staff.
        self.call(CmdBoonAdmin(), f"/fulfill {boon.id} = Ruling", caller=self.iris)
        self.assertEqual(self._status(boon), "fulfilled")
        self.call(CmdBoonAdmin(), f"/cancel {owed.id} = Staff ruling", caller=self.wren)
        self.assertEqual(self._status(owed), "canceled")

    def test_staff_may_rule_on_own_boon(self):
        boon = self._called_in(creditor=self.wren)
        self.call(CmdBoonAdmin(), f"/fulfill {boon.id} = Staff", caller=self.wren)
        self.assertEqual(self._status(boon), "fulfilled")

    def test_dispute_and_resolution(self):
        """Owner decision: either party disputes; it stays owed; a non-party resolves."""
        boon = self._called_in()
        self.assertIn("Usage", self.call(CmdBoon(), f"/dispute {boon.id}", caller=self.alice))
        output = self.call(CmdBoon(), f"/dispute {boon.id} = I never agreed to that", caller=self.alice)
        self.assertIn("disputed", output)
        self.assertEqual(self._status(boon), "disputed")
        self.assertIn("I never agreed to that", Boon.objects.get(pk=boon.pk).fulfillment_description)
        # Still owed while disputed.
        self.assertEqual(get_boon_totals(self.alice).total_debt_weight, 3)
        self.assertEqual(get_boon_totals(self.bob).major_held, 1)
        # Can't be disputed twice, nor by a non-party.
        self.call(CmdBoon(), f"/dispute {boon.id} = Again", caller=self.bob)
        self.assertIn("Only the debtor or creditor", self.call(CmdBoon(), f"/dispute {boon.id} = x", caller=self.iris))
        # The parties can't confirm their way out of a dispute.
        self.call(CmdBoonFulfill(), f"{boon.id} = Done", caller=self.alice)
        self.assertEqual(self._status(boon), "disputed")
        # A non-party Harpy rules it fulfilled.
        self.call(CmdBoonAdmin(), f"/fulfill {boon.id} = Ruling for Bob", caller=self.iris)
        self.assertEqual(self._status(boon), "fulfilled")
        self.assertEqual(get_boon_totals(self.alice).total_debt_weight, 0)

    def test_disputed_boon_can_be_canceled_by_staff(self):
        boon = self._called_in()
        self.call(CmdBoon(), f"/dispute {boon.id} = Coerced", caller=self.bob)
        self.assertEqual(self._status(boon), "disputed")
        self.call(CmdBoonAdmin(), f"/cancel {boon.id} = Coercion upheld", caller=self.wren)
        self.assertEqual(self._status(boon), "canceled")
        self.assertEqual(get_boon_totals(self.alice).total_debt_weight, 0)

    def _harpy_alt_of(self, character, key):
        """A Harpy-account character that shares `character`'s account."""
        alt = create.create_object(settings.BASE_CHARACTER_TYPECLASS, key=key, location=self.room1, home=self.room1)
        alt.account = character.account
        character.account.characters.add(alt)
        return alt

    def test_harpy_cannot_rule_via_alt_on_same_account(self):
        """R-7: Hera's alt can't rule on a boon Hera is party to."""
        boon = self._called_in(creditor=self.hera)
        alt = self._harpy_alt_of(self.hera, "Herald")
        self.assertTrue(CmdBoonAdmin().access(alt, "cmd"))
        for switch in ("fulfill", "cancel"):
            output = self.call(CmdBoonAdmin(), f"/{switch} {boon.id} = Via my alt", caller=alt)
            self.assertIn("party to", output)
        self.call(CmdBoon(), f"/dispute {boon.id} = Coerced", caller=self.alice)
        self.assertIn("party to", self.call(CmdBoonAdmin(), f"/uphold {boon.id} = Via alt", caller=alt))
        self.assertIn("party to", self.call(CmdBoonAdmin(), f"/uphold {boon.id} = Mine", caller=self.hera))
        self.assertEqual(self._status(boon), "disputed")

    def test_uphold_restores_accepted_and_creditor_can_call_in(self):
        """R-21: a frivolous dispute of an accepted boon is rejected and the boon stands."""
        self.call(CmdBoonGive(), "Bob major = A favor", caller=self.alice)
        boon = Boon.objects.get(debtor=self.alice, creditor=self.bob)
        self.call(CmdBoonAccept(), str(boon.id), caller=self.bob)
        self.call(CmdBoon(), f"/dispute {boon.id} = Never happened", caller=self.alice)
        self.assertEqual(self._status(boon), "disputed")
        # The creditor can't call in a disputed boon.
        self.call(CmdBoonCall(), f"{boon.id} = Pay up", caller=self.bob)
        self.assertEqual(self._status(boon), "disputed")

        output = self.call(CmdBoonAdmin(), f"/uphold {boon.id} = It happened", caller=self.iris)
        self.assertIn("stands", output)
        self.assertEqual(self._status(boon), "accepted")
        self.assertIn("Upheld by Iris: It happened", Boon.objects.get(pk=boon.pk).fulfillment_description)
        # No second dispute after an upheld one.
        output = self.call(CmdBoon(), f"/dispute {boon.id} = Again", caller=self.alice)
        self.assertIn("already rejected", output)
        self.assertEqual(self._status(boon), "accepted")
        self.call(CmdBoonCall(), f"{boon.id} = Pay up", caller=self.bob)
        self.assertEqual(self._status(boon), "called_in")

    def test_uphold_restores_called_in_and_parties_can_confirm(self):
        boon = self._called_in()
        self.call(CmdBoon(), f"/dispute {boon.id} = Too much to ask", caller=self.alice)
        self.call(CmdBoonAdmin(), f"/uphold {boon.id} = Fair request", caller=self.wren)
        self.assertEqual(self._status(boon), "called_in")
        self.call(CmdBoonFulfill(), f"{boon.id} = Done", caller=self.alice)
        self.call(CmdBoonFulfill(), f"{boon.id} = Confirmed", caller=self.bob)
        self.assertEqual(self._status(boon), "fulfilled")

    def test_uphold_needs_a_disputed_boon(self):
        boon = self._called_in()
        output = self.call(CmdBoonAdmin(), f"/uphold {boon.id} = Nothing to rule", caller=self.wren)
        self.assertIn("Only a disputed boon", output)
