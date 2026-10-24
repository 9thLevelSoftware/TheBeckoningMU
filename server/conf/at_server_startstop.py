"""
Server startup/shutdown hooks for The Beckoning MU

This module is called at server startup and shutdown.
"""


def at_server_init():
    """Reconstruct builder fences before Evennia resumes persistent timers."""
    from web.builder.operation_runtime import recover_operation_fences

    recover_operation_fences()


def at_server_start():
    """
    This is called every time the server starts up, regardless of
    how it was shut down.
    """
    from chronicle.generation import recover_pending_drafts
    from narrative.services import recover_pending_requests

    # Job buckets, Camarilla positions and BBS boards the help relies on;
    # creates only what is missing.
    from world.seed_defaults import seed_defaults

    seed_defaults()
    recover_pending_requests()
    recover_pending_drafts()


def at_server_stop():
    """
    This is called just before the server is shut down, regardless
    of it is for a reload, reset or shutdown.
    """
    from chronicle.generation import shutdown_pending_drafts
    from narrative.services import shutdown_pending_requests

    shutdown_pending_requests()
    shutdown_pending_drafts()
