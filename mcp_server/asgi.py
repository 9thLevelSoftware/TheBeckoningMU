from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.conf.settings")

import django

django.setup()

from .app import create_application  # noqa: E402

app = create_application()
application = app
