"""
Server startup/shutdown hooks for The Beckoning MU

This module is called at server startup and shutdown.
"""


def at_server_start():
    """
    This is called every time the server starts up, regardless of
    how it was shut down.
    """
    # Job buckets, Camarilla positions and BBS boards the help relies on;
    # creates only what is missing.
    from world.seed_defaults import seed_defaults

    seed_defaults()


def at_server_stop():
    """
    This is called just before the server is shut down, regardless
    of it is for a reload, reset or shutdown.
    """
    pass
