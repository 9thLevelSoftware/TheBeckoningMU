"""Explicit offline normalization; default inventory never writes or invents IDs."""

import json

from django.core.management.base import BaseCommand, CommandError
from evennia.objects.models import ObjectDB

from commands.v5.utils.discipline_effects import normalize_effects
from typeclasses.characters import Character


class Command(BaseCommand):
    help = (
        "Inventory legacy active effects (dry-run by default). --apply --offline persists "
        "safe normalization with stable IDs. Stop the game server before maintenance writes."
    )

    def add_arguments(self, parser):
        parser.add_argument("--character", type=int, action="append", help="Character ID (repeatable)")
        parser.add_argument("--apply", action="store_true", help="Persist normalization explicitly")
        parser.add_argument("--offline", action="store_true", help="Confirm the game server is stopped")
        parser.add_argument(
            "--retire-instant", action="store_true", help="Report/retire verified instant formula leftovers"
        )

    def handle(self, *args, **options):
        if options["apply"] and not options["offline"]:
            raise CommandError("--apply requires --offline: stop the game server before this maintenance write")
        objects = ObjectDB.objects.filter(db_typeclass_path=Character.path).order_by("pk")
        if options["character"]:
            objects = objects.filter(pk__in=options["character"])
        for character in objects.iterator():
            report = normalize_effects(character, persist=options["apply"], retire_instant=options["retire_instant"])
            self.stdout.write(json.dumps(dict(report, character=character.pk), sort_keys=True, default=str))
