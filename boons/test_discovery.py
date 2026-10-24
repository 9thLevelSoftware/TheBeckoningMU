"""Stable discovery of current authorized debt and case records."""

from django.conf import settings
from django.utils import timezone
from evennia.utils import create
from evennia.utils.test_resources import EvenniaCommandTest

from traits.models import CharacterBio

from .commands import CmdBoon, CmdBoonAdmin
from .models import Boon
from .utils import list_visible_boons


class BoonDiscoveryTests(EvenniaCommandTest):
    def setUp(self):
        super().setUp()
        self.people = []
        for name, permission in (("Player", ""), ("Other", ""), ("Harpy", "Harpy")):
            account = create.create_account(name, email=f"{name}@example.com", password="testpass123")
            if permission:
                account.permissions.add(permission)
            char = create.create_object(settings.BASE_CHARACTER_TYPECLASS, key=name, location=self.room1)
            char.account = account
            CharacterBio.objects.create(character=char, account=account)
            char.sessions.add(self.session)
            self.people.append(char)
        self.player, self.other, self.harpy = self.people

    def boon(self, **changes):
        fields = {
            "debtor": self.player,
            "creditor": self.other,
            "status": "accepted",
            "boon_type": "major",
            "description": "Original favor",
            "called_in_description": "CASE REQUEST",
            "staff_notes": "STAFF SECRET",
        }
        fields.update(changes)
        return Boon.objects.create(**fields)

    def ids(self, page):
        return [row["ID"] for row in page.rows]

    def test_old_outstanding_debt_survives_terminal_crowding_and_opens_detail(self):
        old = self.boon()
        for _ in range(12):
            self.boon(status="fulfilled")
        called = self.boon(status="called_in")
        disputed = self.boon(status="disputed")
        output = self.call(CmdBoon(), "/list", caller=self.player)
        self.assertIn(f"+boon/view {old.pk}", output)
        self.assertEqual(
            self.ids(list_visible_boons(self.player, mode="outstanding")), [disputed.pk, called.pk, old.pk]
        )
        output = self.call(CmdBoon(), f"/view {old.pk}", caller=self.player)
        self.assertIn("CASE REQUEST", output)
        self.assertNotIn("STAFF SECRET", output)

    def test_keyset_three_pages_equal_dates_and_new_insert(self):
        records = [self.boon(status="fulfilled") for _ in range(45)]
        Boon.objects.all().update(created_date=timezone.now())
        first = list_visible_boons(self.player, mode="history")
        inserted = self.boon()
        second = list_visible_boons(self.player, mode="history", before=first.next_before)
        third = list_visible_boons(self.player, mode="history", before=second.next_before)
        self.assertEqual(self.ids(first) + self.ids(second) + self.ids(third), [b.pk for b in reversed(records)])
        self.assertEqual([len(page.rows) for page in (first, second, third)], [20, 20, 5])
        self.assertEqual(first.next_before, first.rows[-1]["ID"])
        self.assertEqual(second.next_before, second.rows[-1]["ID"])
        self.assertIsNone(third.next_before)
        self.assertEqual(list_visible_boons(self.player, mode="history").rows[0]["ID"], inserted.pk)
        self.assertEqual(list_visible_boons(self.player, mode="history", before=records[0].pk).rows, [])

    def test_exact_history_continuation_command(self):
        records = [self.boon() for _ in range(21)]
        output = self.call(CmdBoon(), "/history", caller=self.player)
        self.assertIn(f"Next: +boon/history before={records[1].pk}", output)
        output = self.call(CmdBoon(), f"/history before={records[1].pk}", caller=self.player)
        self.assertIn(f"+boon/view {records[0].pk}", output)
        self.assertNotIn("Next:", output)
        self.assertIn("Other", output)
        self.assertIn("Major", output)
        self.assertIn("Accepted", output)

    def test_sparse_visibility_filters_before_limit_and_hides_metadata(self):
        visible = []
        hidden = []
        for _ in range(5):
            visible.append(self.boon())
            for _ in range(7):
                hidden.append(self.boon(is_public=False))
        page = list_visible_boons(self.harpy, mode="adjudication", page_size=2)
        self.assertEqual(self.ids(page), [visible[-1].pk, visible[-2].pk])
        self.assertEqual(page.next_before, visible[-2].pk)
        next_page = list_visible_boons(self.harpy, mode="adjudication", page_size=2, before=page.next_before)
        last = list_visible_boons(self.harpy, mode="adjudication", page_size=2, before=next_page.next_before)
        self.assertEqual(self.ids(page) + self.ids(next_page) + self.ids(last), [b.pk for b in reversed(visible)])
        self.assertIsNone(last.next_before)
        output = self.call(CmdBoonAdmin(), "/list", caller=self.harpy)
        for boon in hidden:
            self.assertNotIn(f"#{boon.pk} -", output)
        self.assertNotIn("STAFF SECRET", output)
        self.assertNotIn("CASE REQUEST", output)
        self.assertNotIn("Next:", output)

    def test_permissions_and_ownership_are_current_between_pages(self):
        private = self.boon(is_public=False)
        self.boon()
        first = list_visible_boons(self.harpy, mode="adjudication", page_size=1)
        self.assertIsNone(first.next_before)
        # Gaining Builder permission grants the existing private read boundary.
        self.harpy.account.permissions.add("Builder")
        page = list_visible_boons(self.harpy, mode="adjudication", before=first.rows[-1]["ID"])
        self.assertEqual(self.ids(page), [private.pk])
        self.assertIn("Staff notes", page.rows[0])
        self.harpy.account.permissions.remove("Builder")
        self.assertEqual(list_visible_boons(self.harpy, mode="adjudication", before=first.rows[-1]["ID"]).rows, [])
        # Canonical ownership changes never grant another actual character participation.
        CharacterBio.objects.filter(character=self.player).update(account=self.harpy.account)
        self.assertEqual(list_visible_boons(self.harpy, mode="history").rows, [])
        self.assertEqual(list_visible_boons(self.harpy, mode="adjudication", before=first.rows[-1]["ID"]).rows, [])
        private.creditor = self.harpy
        private.save()
        self.assertEqual(self.ids(list_visible_boons(self.harpy, mode="history")), [private.pk])

    def test_cursor_validation_bounds_and_counterpart(self):
        for cursor in ("bad", "-1", "0", "1.5", True, "9" * 30):
            with self.subTest(cursor=cursor), self.assertRaises(ValueError):
                list_visible_boons(self.player, mode="history", before=cursor)
        for argument in ("before=-1", "before=0", "before=bad", "123", "before=1 extra"):
            self.assertIn("positive", self.call(CmdBoon(), f"/history {argument}", caller=self.player))
        for size in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                list_visible_boons(self.player, mode="history", page_size=size)
        mine = self.boon()
        self.boon(creditor=self.harpy)
        page = list_visible_boons(self.player, mode="history", counterpart_id=self.other.pk, page_size=1000)
        self.assertEqual(self.ids(page), [mine.pk])

    def test_admin_continuation_and_player_pending_and_pair_links(self):
        records = [self.boon(status="offered") for _ in range(21)]
        output = self.call(CmdBoonAdmin(), "/list", caller=self.harpy)
        self.assertIn(f"Next: +boonadmin/list before={records[1].pk}", output)
        output = self.call(CmdBoonAdmin(), f"/list before={records[1].pk}", caller=self.harpy)
        self.assertIn(f"+boon/view {records[0].pk}", output)
        output = self.call(CmdBoon(), "/pending", caller=self.other)
        self.assertIn(f"+boon/view {records[0].pk}", output)
        self.assertIn(f"+boonaccept {records[0].pk}", output)
        output = self.call(CmdBoon(), "Other", caller=self.player)
        self.assertIn("+boon/history", output)
        self.assertIn("+boon/view", output)
