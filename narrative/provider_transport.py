"""Bounded HTTP response collection, independent of story authority and storage."""

from dataclasses import dataclass

from twisted.internet.defer import CancelledError, Deferred
from twisted.internet.protocol import Protocol
from twisted.web.client import ResponseDone

_FAILURE_MESSAGES = {
    "timeout": "Narrative generation timed out.",
    "canceled": "Narrative generation was canceled.",
    "response_too_large": "Narrative response exceeded its limit.",
    "malformed_response": "Narrative response was malformed.",
    "upstream_failure": "Narrative provider failed.",
}


class ProviderError(Exception):
    """Only fixed, non-sensitive categories and messages cross the transport boundary."""

    def __init__(self, category):
        self.category = category if category in _FAILURE_MESSAGES else "upstream_failure"
        super().__init__(_FAILURE_MESSAGES[self.category])


def failure_category(error):
    if isinstance(error, ProviderError):
        return error.category
    if isinstance(error, CancelledError):
        return "canceled"
    if isinstance(error, (ValueError, UnicodeError, KeyError, IndexError, TypeError)):
        return "malformed_response"
    return "upstream_failure"


@dataclass(frozen=True)
class ProviderLimits:
    request_timeout_seconds: float = 30
    connect_timeout_seconds: float = 10
    response_max_bytes: int = 1048576
    prose_max_chars: int = 12000

    @classmethod
    def from_config(cls, config):
        defaults = cls()
        values = {}
        for name, maximum in (
            ("request_timeout_seconds", 300),
            ("connect_timeout_seconds", 300),
            ("response_max_bytes", 8388608),
            ("prose_max_chars", 100000),
        ):
            value = config.get(name, getattr(defaults, name))
            allowed_types = (int, float) if name.endswith("seconds") else (int,)
            if type(value) not in allowed_types or not 0 < value <= maximum:
                raise ValueError("Invalid narrative provider limits.")
            values[name] = value
        return cls(**values)


class _BoundedBody(Protocol):
    def __init__(self, operation):
        self.operation = operation
        self.chunks = []
        self.received = 0

    def connectionMade(self):  # noqa: N802
        if self.operation.finished:
            self.abort()

    def abort(self):
        self.chunks.clear()
        transport = getattr(self, "transport", None)
        if transport is not None:
            abort = getattr(transport, "abortConnection", None) or getattr(transport, "loseConnection", None)
            if abort is not None:
                abort()

    def dataReceived(self, data):  # noqa: N802
        if self.operation.finished:
            return
        if self.operation.expired():
            self.operation.fail("timeout")
            return
        self.received += len(data)
        if self.received > self.operation.limits.response_max_bytes:
            self.operation.fail("response_too_large")
            return
        self.chunks.append(data)

    def connectionLost(self, reason):  # noqa: N802
        if self.operation.finished:
            return
        if not reason.check(ResponseDone):
            self.operation.fail("upstream_failure")
            return
        body = b"".join(self.chunks)
        self.chunks.clear()
        self.operation.complete(body)


class _ProviderOperation:
    def __init__(self, agent, clock, limits, parse):
        self.agent = agent
        self.clock = clock
        self.limits = limits
        self.parse = parse
        self.finished = False
        self.headers = None
        self.reader = None
        self.deadline = clock.seconds() + limits.request_timeout_seconds
        self.result = Deferred(lambda _result: self.fail("canceled"))
        self.timer = clock.callLater(limits.request_timeout_seconds, self.fail, "timeout")

    def expired(self):
        return self.clock.seconds() >= self.deadline

    def _stop_timer(self):
        if self.timer.active():
            self.timer.cancel()

    def fail(self, category):
        if self.finished:
            return
        self.finished = True
        self._stop_timer()
        # Mark terminal before cancellation/abort: both can synchronously call us back.
        try:
            # Agent's outer Deferred can be called but still paused on the
            # protocol's pending headers Deferred. cancel() forwards to it.
            if self.headers is not None:
                self.headers.cancel()
        finally:
            try:
                if self.reader is not None:
                    self.reader.abort()
            finally:
                self.result.errback(ProviderError(category))

    def start(self, method, uri, headers, body):
        try:
            self.headers = self.agent.request(method, uri, headers, body)
            self.headers.addCallbacks(self._got_headers, self._headers_failed)
        except Exception:
            self.fail("upstream_failure")
        return self.result

    def _headers_failed(self, failure):
        self.fail("canceled" if failure.check(CancelledError) else "upstream_failure")
        return None

    def _got_headers(self, response):
        self.reader = _BoundedBody(self)
        try:
            if not self.finished:
                if self.expired():
                    self.fail("timeout")
                elif not 200 <= response.code < 300:
                    self.fail("upstream_failure")
                else:
                    lengths = response.headers.getRawHeaders(b"Content-Length", [])
                    if response.length is not None and isinstance(response.length, int):
                        lengths = [*lengths, response.length]
                    if any(int(length) > self.limits.response_max_bytes for length in lengths):
                        self.fail("response_too_large")
            # Even a rejected response needs a reader to acquire and abort its socket.
            response.deliverBody(self.reader)
        except Exception:
            self.fail("upstream_failure")
        return None

    def complete(self, body):
        if self.finished:
            return
        if self.expired():
            self.fail("timeout")
            return
        try:
            value = self.parse(body)
        except Exception as error:
            self.fail("timeout" if self.expired() else failure_category(error))
            return
        if self.finished:
            return
        if self.expired():
            self.fail("timeout")
            return
        self.finished = True
        self._stop_timer()
        self.result.callback(value)


def bounded_request(agent, clock, limits, parse, method, uri, headers, body):
    """One deadline spans headers, body, and bounded parsing; never retries."""
    return _ProviderOperation(agent, clock, limits, parse).start(method, uri, headers, body)
