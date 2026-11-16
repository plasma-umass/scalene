"""Scalene's CPU signal handler never runs inside another call of itself.

CPython runs Python signal handlers at any safe point, including inside
another Python signal handler. In wall-clock mode Scalene's timer reloads
every second until the handler re-arms it, so a handler call that took
longer (stopping and parsing a torch profiler window) was entered again, and
each nested call re-armed the 10 ms timer: nested calls kept restarting the
torch profiler while the outer call was parsing it, until CI ran out of
memory.
"""

import pytest

from scalene.scalene_profiler import Scalene


@pytest.fixture
def body(monkeypatch):
    calls = []
    monkeypatch.setattr(
        Scalene,
        "_cpu_signal_handler",
        staticmethod(lambda signum, frame: calls.append(signum)),
    )
    monkeypatch.setattr(Scalene, "_Scalene__in_cpu_signal_handler", False)
    return calls


def test_nested_call_returns_at_once(body, monkeypatch):
    def outer(signum, frame):
        body.append(("outer", signum))
        Scalene.cpu_signal_handler(signum, frame)  # what a nested signal does

    monkeypatch.setattr(Scalene, "_cpu_signal_handler", staticmethod(outer))
    Scalene.cpu_signal_handler(14, None)
    assert body == [("outer", 14)]
    Scalene.cpu_signal_handler(14, None)  # the next signal is handled again
    assert body == [("outer", 14), ("outer", 14)]


def test_guard_is_released_after_an_exception(body, monkeypatch):
    def failing(signum, frame):
        raise RuntimeError("boom")

    monkeypatch.setattr(Scalene, "_cpu_signal_handler", staticmethod(failing))
    with pytest.raises(RuntimeError):
        Scalene.cpu_signal_handler(14, None)
    assert Scalene._Scalene__in_cpu_signal_handler is False


def test_handler_runs_when_not_nested(body):
    Scalene.cpu_signal_handler(14, None)
    Scalene.cpu_signal_handler(14, None)
    assert body == [14, 14]
