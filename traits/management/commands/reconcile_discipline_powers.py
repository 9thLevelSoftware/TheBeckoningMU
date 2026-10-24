"""Offline inventory/explicit entitlement issuance; never choose powers or refund XP."""

import json

from django.core.management.base import BaseCommand, CommandError
from evennia.objects.models import ObjectDB

from traits.power_reconciliation import reconcile_discipline_powers
from typeclasses.characters import Character


class Command(BaseCommand):
    help = (
        "Inventory discipline power deficits (dry-run by default). --apply adds only proven "
        "choice entitlements. Run offline, with the game server stopped, or dispatch the "
        "service to the game reactor; never run a second writer beside a live server."
    )

    def add_arguments(self, parser):
        parser.add_argument("--character", type=int, action="append", help="Character ID (repeatable)")
        parser.add_argument("--apply", action="store_true", help="Explicitly issue proven entitlements")
        parser.add_argument("--offline", action="store_true", help="Confirm the game server is stopped")

    def handle(self, *args, **options):
        if options["apply"] and not options["offline"]:
            raise CommandError("--apply requires --offline: stop the game server before this maintenance write")
        objects = ObjectDB.objects.filter(db_typeclass_path=Character.path).order_by("pk")
        if options["character"]:
            objects = objects.filter(pk__in=options["character"])
        for character in objects.iterator():
            report = reconcile_discipline_powers(character, apply=options["apply"])
            self.stdout.write(json.dumps(report, sort_keys=True))
