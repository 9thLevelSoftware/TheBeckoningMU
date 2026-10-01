"""
Status requests go through the same rules as the admin path (F-069).

Alice is a player; Wren is a Builder running +statusadmin.
"""

from django.conf import settings
from evennia.utils import create
from evennia.utils.test_resources import EvenniaCommandTest

from .commands import CmdStatusAdmin
from .models import CamarillaPosition, StatusRequest
from .utils import create_status_request, get_or_create_character_status


class StatusRequestTests(EvenniaCommandTest):
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
        self.wren = self._puppet("Wren", "Builder")
        self.prince = CamarillaPosition.objects.create(
            name="Prince", status_granted=3, hierarchy_level=5, is_unique=True, requires_status=4
        )

    def _approve(self, request):
        return self.call(CmdStatusAdmin(), f"/approve {request.id} = Earned it", caller=self.wren)

    def test_position_request_enforces_required_status(self):
        """requires_status=4 at earned Status 0 is refused, and the request stays pending."""
        request = create_status_request(self.alice, "position", "I rule", requested_position=self.prince)
        output = self._approve(request)
        self.assertIn("requires 4", output)
        request.refresh_from_db()
        self.assertEqual(request.status, "pending")
        self.assertIsNone(get_or_create_character_status(self.alice).position)

    def test_position_request_granted_when_requirements_met(self):
        status = get_or_create_character_status(self.alice)
        status.earned_status = 4
        status.save()
        request = create_status_request(self.alice, "position", "I rule", requested_position=self.prince)
        self._approve(request)
        request.refresh_from_db()
        self.assertEqual(request.status, "approved")
        self.assertEqual(get_or_create_character_status(self.alice).position, self.prince)

    def test_approve_only_acts_on_pending(self):
        request = create_status_request(self.alice, "earned_status", "Good deeds", requested_change=2)
        self.assertTrue(request.approve(self.wren, "ok")[0])
        self.assertEqual(get_or_create_character_status(self.alice).earned_status, 2)
        # A second approval does nothing.
        self.assertFalse(request.approve(self.wren, "again")[0])
        self.assertFalse(request.deny(self.wren, "no")[0])
        self.assertEqual(get_or_create_character_status(self.alice).earned_status, 2)
        self.assertEqual(StatusRequest.objects.get(pk=request.pk).status, "approved")

    def test_sect_change_is_rejected(self):
        with self.assertRaises(ValueError):
            create_status_request(self.alice, "sect_change", "Joining the Anarchs")
        # A stored one (e.g. from the admin) can't be approved as a no-op.
        request = StatusRequest.objects.create(character=self.alice, request_type="sect_change", reason="x")
        success, _ = request.approve(self.wren, "ok")
        self.assertFalse(success)
        request.refresh_from_db()
        self.assertEqual(request.status, "pending")

    def test_set_echoes_stored_value(self):
        output = self.call(CmdStatusAdmin(), "/set Alice = 9", caller=self.wren)
        self.assertIn("set to 5", output)
        self.assertNotIn("set to 9", output)

    def test_approval_is_atomic(self):
        """R-16: if recording the approval fails, the applied change rolls back."""
        from unittest.mock import patch

        request = create_status_request(self.alice, "earned_status", "Good deeds", requested_change=2)
        with (
            patch.object(StatusRequest, "save", side_effect=RuntimeError("disk full")),
            self.assertRaises(RuntimeError),
        ):
            request.approve(self.wren, "ok")
        self.assertEqual(get_or_create_character_status(self.alice).earned_status, 0)
        self.assertEqual(StatusRequest.objects.filter(pk=request.pk).values_list("status", flat=True).get(), "pending")
