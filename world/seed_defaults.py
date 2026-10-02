"""
Default game data every server needs, created at server start.

`seed_defaults()` is called from server/conf/at_server_startstop.py. Each
step only creates what is missing and never changes an existing row, so
it is safe on every start and on a database staff have already edited.
"""

import logging

logger = logging.getLogger(__name__)

# The boards the news and help send players to. (name, description, write_perm)
DEFAULT_BOARDS = (
    ("general", "General out-of-character discussion and questions", ""),
    ("introductions", "Introduce yourself and your character", ""),
    ("rp", "Roleplay hooks, scene announcements and plots", ""),
    ("chargen", "Questions about character creation", ""),
    ("policy", "Staff announcements of game policy", "Builder"),
)


def ensure_default_boards():
    """Create any missing default BBS board. Returns the number created."""
    from bbs.models import Board

    created = 0
    for name, description, write_perm in DEFAULT_BOARDS:
        if Board.objects.filter(name__iexact=name).exists():
            continue
        Board.objects.create(name=name, description=description, write_perm=write_perm)
        created += 1
    return created


def seed_defaults():
    """Create the default job buckets, Camarilla positions and BBS boards. Returns {step: created}."""
    from jobs.utils import ensure_default_buckets
    from status.utils import initialize_default_positions

    steps = {
        "job buckets": ensure_default_buckets,
        "positions": initialize_default_positions,
        "boards": ensure_default_boards,
    }
    results = {}
    for label, step in steps.items():
        try:
            results[label] = step()
        except Exception:  # a seeding failure must not stop the server
            logger.exception("Seeding default %s failed", label)
            results[label] = None
    return results
