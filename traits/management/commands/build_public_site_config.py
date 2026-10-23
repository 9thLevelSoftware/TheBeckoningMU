"""Generate the static deployment's public origin without a second configuration value."""

import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from web.website.public_config import DEFAULT_CONFIG_PATH, render_public_config


class Command(BaseCommand):
    help = "Build static site-config.js from Django's PUBLIC_GAME_BASE_URL (no database changes)."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument(
            "--output", type=Path, default=DEFAULT_CONFIG_PATH, help="Destination JavaScript asset path."
        )

    def handle(self, *args, **options):
        try:
            content = render_public_config(getattr(settings, "PUBLIC_GAME_BASE_URL", ""))
        except ValueError as error:
            raise CommandError(str(error)) from error
        output = Path(options["output"])
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", dir=output.parent, delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(content)
            os.replace(temporary, output)
        except OSError as error:
            raise CommandError(f"Could not write public site config: {error.strerror}.") from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.stdout.write(self.style.SUCCESS(f"Wrote public site config to {output}."))
