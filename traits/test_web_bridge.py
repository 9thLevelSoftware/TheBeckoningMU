"""Thread dispatch is exercised in an isolated real Twisted reactor process."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from traits.web_bridge import run_sync_in_main_thread


class WebWriteDispatchTests(SimpleTestCase):
    def test_real_worker_thread_dispatches_to_reactor_and_propagates_errors(self):
        root = Path(__file__).resolve().parents[1]
        script = r"""
import os
import threading
os.environ['DJANGO_SETTINGS_MODULE'] = 'server.conf.settings'
import django
django.setup()
from twisted.internet import defer, reactor, task, threads
from traits.web_bridge import run_sync_in_main_thread

@defer.inlineCallbacks
def exercise(reactor):
    yield task.deferLater(reactor, 0, lambda: None)
    reactor_thread = threading.get_ident()
    assert run_sync_in_main_thread(threading.get_ident) == reactor_thread
    def worker():
        assert threading.get_ident() != reactor_thread
        assert run_sync_in_main_thread(threading.get_ident) == reactor_thread
        def fail():
            raise ValueError('local-thread-error')
        try:
            run_sync_in_main_thread(fail)
        except ValueError as error:
            assert str(error) == 'local-thread-error'
        else:
            raise AssertionError('Lost dispatch error')
    yield threads.deferToThread(worker)
    print('web-thread-dispatch passed')
task.react(exercise)
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("web-thread-dispatch passed", result.stdout)

    def test_expired_queued_write_is_cancelled_before_it_starts(self):
        pending = []
        work = Mock()
        with (
            patch("traits.web_bridge.isInIOThread", return_value=False),
            patch("traits.web_bridge.reactor") as reactor,
            patch("traits.web_bridge.threading.Event") as event,
        ):
            reactor.running = True
            reactor.callFromThread.side_effect = pending.append
            event.return_value.wait.return_value = False
            with self.assertRaises(TimeoutError):
                run_sync_in_main_thread(work)
            pending[0]()
        work.assert_not_called()

    def test_stopped_reactor_denies_write(self):
        work = Mock()
        with patch("traits.web_bridge.isInIOThread", return_value=False), patch("traits.web_bridge.reactor") as reactor:
            reactor.running = False
            with self.assertRaises(TimeoutError):
                run_sync_in_main_thread(work)
        work.assert_not_called()
