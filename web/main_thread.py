"""
Run a web-side unit of work on the Twisted reactor (Evennia's main thread).

Django views run in a worker thread, outside the game loop. Evennia objects
(their idmapper caches, contents caches, sessions, scripts) belong to the
reactor thread, so every web operation that changes the game world runs as
one callable on the reactor:

    result = call_in_main_thread(unit, *args, **kwargs)

The decision is made on every call, not at import time: on the main thread
(the reactor itself, or a test runner) `fn` runs directly; on any other thread
the call is handed to the reactor with `blockingCallFromThread` and the worker
waits for its result or exception.

A unit does all of its own DB writes on the reactor. The caller must not hold
a transaction open when it hands over: Django connections are per-thread, so
an atomic block here would neither cover the reactor's writes nor release
SQLite's write lock while the reactor waits on it.
"""

import threading

from django.db import connection
from twisted.internet import reactor, threads

__all__ = ["call_in_main_thread", "MainThreadTransactionError"]


class MainThreadTransactionError(RuntimeError):
    """Raised when a worker thread hands work to the reactor inside atomic()."""


def blockingCallFromThread(reactor_, fn, *args, **kwargs):  # noqa: N802 - mirrors Twisted's name
    """Indirection so tests can patch the hand-off in one place."""
    return threads.blockingCallFromThread(reactor_, fn, *args, **kwargs)


def call_in_main_thread(fn, *args, **kwargs):
    """Call `fn(*args, **kwargs)` on the reactor thread and return its result.

    Exceptions raised by `fn` propagate to the caller.
    """
    if threading.current_thread() is threading.main_thread():
        return fn(*args, **kwargs)
    if connection.in_atomic_block:
        raise MainThreadTransactionError(
            "call_in_main_thread() was called inside a transaction; the reactor "
            "can't see uncommitted writes and SQLite would stay locked"
        )
    return blockingCallFromThread(reactor, fn, *args, **kwargs)
