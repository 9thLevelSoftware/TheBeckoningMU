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
        self.assertEqual(self._status(boon), "accepted")
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
