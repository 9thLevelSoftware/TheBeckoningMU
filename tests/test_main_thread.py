"""
web.main_thread.call_in_main_thread decides per call, not at import time:
on the main thread it calls the function directly; on another thread it hands
the call to the reactor, and refuses to do so from inside a transaction.
"""

import threading
from unittest import mock

from django.db import connection, transaction
from django.test import SimpleTestCase, TransactionTestCase

from web import main_thread


def run_in_thread(fn):
    """Run fn in a worker thread; return (result, exception)."""
    outcome = {}

    def target():
        try:
            outcome["result"] = fn()
        except BaseException as err:  # noqa: BLE001 - re-raised in the test thread
            outcome["error"] = err
        finally:
            connection.close()

    thread = threading.Thread(target=target)
    thread.start()
    thread.join(10)
    return outcome.get("result"), outcome.get("error")


class MainThreadDirectCallTests(SimpleTestCase):
    def test_main_thread_calls_fn_directly(self):
        seen = {}

        def unit(a, b=0):
            seen["thread"] = threading.current_thread()
            return a + b

        with mock.patch.object(main_thread, "blockingCallFromThread") as handoff:
            self.assertEqual(main_thread.call_in_main_thread(unit, 2, b=3), 5)
        handoff.assert_not_called()
        self.assertIs(seen["thread"], threading.main_thread())

    def test_exceptions_propagate(self):
        def unit():
            raise ValueError("boom")

        with self.assertRaises(ValueError):
            main_thread.call_in_main_thread(unit)

    def test_worker_thread_hands_off_to_the_reactor(self):
        def unit(a, b=0):
            return a + b

        with mock.patch.object(main_thread, "blockingCallFromThread", return_value="from reactor") as handoff:
            result, error = run_in_thread(lambda: main_thread.call_in_main_thread(unit, 2, b=3))
        self.assertIsNone(error)
        self.assertEqual(result, "from reactor")
        handoff.assert_called_once_with(main_thread.reactor, unit, 2, b=3)

    def test_decision_is_made_per_call(self):
        """The same import serves both threads (no import-time decision)."""
        calls = []
        with mock.patch.object(main_thread, "blockingCallFromThread", side_effect=lambda r, f: calls.append("handoff")):
            main_thread.call_in_main_thread(lambda: calls.append("direct"))
            run_in_thread(lambda: main_thread.call_in_main_thread(lambda: calls.append("direct")))
            main_thread.call_in_main_thread(lambda: calls.append("direct"))
        self.assertEqual(calls, ["direct", "handoff", "direct"])


class FakeReactor:
    """Runs callFromThread work at once, standing in for the running reactor."""

    def __init__(self):
        self.calls = 0

    def callFromThread(self, f, *args, **kwargs):  # noqa: N802 - Twisted's API name
        self.calls += 1
        f(*args, **kwargs)


class RealHandOffTests(SimpleTestCase):
    """R-19: the wrapper and Twisted's real blockingCallFromThread, not a patch."""

    def test_result_and_exceptions_cross_the_hand_off(self):
        from traits.utils import ChargenError

        fake = FakeReactor()

        def ok(a, b=0):
            return ("ran on reactor", a + b)

        def refuse():
            raise ChargenError("nope", status=409)

        with mock.patch.object(main_thread, "reactor", fake):
            result, error = run_in_thread(lambda: main_thread.call_in_main_thread(ok, 2, b=3))
            self.assertIsNone(error)
            self.assertEqual(result, ("ran on reactor", 5))
            _, error = run_in_thread(lambda: main_thread.call_in_main_thread(refuse))
        self.assertIsInstance(error, ChargenError)
        self.assertEqual((error.status, error.errors), (409, ["nope"]))
        self.assertEqual(fake.calls, 2)


class MainThreadTransactionTests(TransactionTestCase):
    def test_worker_thread_inside_atomic_raises(self):
        def worker():
            with transaction.atomic():
                return main_thread.call_in_main_thread(lambda: "ran")

        with mock.patch.object(main_thread, "blockingCallFromThread") as handoff:
            result, error = run_in_thread(worker)
        self.assertIsInstance(error, main_thread.MainThreadTransactionError)
        self.assertIsNone(result)
        handoff.assert_not_called()
