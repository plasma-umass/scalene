"""Tests for the Apple-SME signal-free CPU sampler (issue #1056).

These exercise the platform-independent mechanics of MacThreadSampler and
the SME-detection helper. They run on any platform — the sampler is just a
background thread that calls a handler, so we can drive it with a fake
handler and fake sample queues without needing real SME hardware.
"""
import sys
import threading
import time

import pytest

from scalene.scalene_mac_sampler import MacThreadSampler


def test_sampler_invokes_handler_repeatedly():
    """The sampler thread should call the CPU handler more than once."""
    calls = []
    lock = threading.Lock()

    def handler(signum, frame):
        with lock:
            calls.append((signum, frame))

    sampler = MacThreadSampler()
    sampler.start(handler, cpu_signal=42, cpu_sampling_rate=0.005)
    assert sampler.is_running
    time.sleep(0.2)
    sampler.stop()
    assert not sampler.is_running

    with lock:
        # At ~200Hz over 200ms we expect many; assert a conservative lower
        # bound to avoid flakiness on a loaded CI machine.
        assert len(calls) >= 2
        # Handler is always called with frame=None (Windows-style) and the
        # signal number we passed.
        assert all(signum == 42 and frame is None for signum, frame in calls)


def test_sampler_handler_exception_does_not_kill_thread():
    """An exception in the handler must not stop sampling."""
    count = {"n": 0}

    def bad_handler(signum, frame):
        count["n"] += 1
        raise RuntimeError("boom")

    sampler = MacThreadSampler()
    sampler.start(bad_handler, cpu_signal=1, cpu_sampling_rate=0.005)
    time.sleep(0.15)
    still_running = sampler.is_running
    sampler.stop()

    assert still_running, "sampler thread died on handler exception"
    assert count["n"] >= 2, "sampler stopped calling handler after exception"


def test_sampler_stop_is_idempotent_and_prompt():
    """stop() should join quickly and be safe to call when not started."""
    sampler = MacThreadSampler()
    # Never started: stop() must not raise.
    sampler.stop()

    sampler.start(lambda s, f: None, cpu_signal=1, cpu_sampling_rate=0.01)
    t0 = time.perf_counter()
    sampler.stop()
    assert time.perf_counter() - t0 < 2.0
    # Double stop is harmless.
    sampler.stop()


class _FakeSigQueue:
    """Minimal stand-in for ScaleneSigQueue recording put() calls."""

    def __init__(self):
        self.items = []
        self.lock = threading.Lock()

    def put(self, item):
        with self.lock:
            self.items.append(item)


def test_sampler_polls_memory_queues_when_provided():
    """With memory profiling on, the sampler poll-drains both queues."""
    alloc = _FakeSigQueue()
    memcpy = _FakeSigQueue()

    sampler = MacThreadSampler()
    sampler.start(
        lambda s, f: None,
        cpu_signal=1,
        cpu_sampling_rate=0.01,
        alloc_sigq=alloc,
        memcpy_sigq=memcpy,
    )
    time.sleep(0.15)
    sampler.stop()

    with alloc.lock:
        assert len(alloc.items) >= 2
    with memcpy.lock:
        assert len(memcpy.items) >= 2


def test_sampler_does_not_poll_when_no_queues():
    """Without memory profiling, no queue polling happens (queues are None)."""
    sampler = MacThreadSampler()
    sampler.start(lambda s, f: None, cpu_signal=1, cpu_sampling_rate=0.005)
    time.sleep(0.1)
    sampler.stop()
    # Nothing to assert beyond "did not crash"; the None queues must not be
    # dereferenced. Reaching here without error is the assertion.


def test_is_apple_silicon_sme_false_off_darwin(monkeypatch):
    """SME detection must be False on non-macOS platforms without calling sysctl."""
    from scalene import scalene_utility

    scalene_utility.is_apple_silicon_sme.cache_clear()
    monkeypatch.setattr(sys, "platform", "linux")
    assert scalene_utility.is_apple_silicon_sme() is False
    scalene_utility.is_apple_silicon_sme.cache_clear()


def test_is_apple_silicon_sme_reads_sysctl(monkeypatch):
    """On darwin, the result reflects the sysctl FEAT_SME value."""
    from scalene import scalene_utility

    class _Result:
        def __init__(self, stdout):
            self.returncode = 0
            self.stdout = stdout

    monkeypatch.setattr(sys, "platform", "darwin")

    scalene_utility.is_apple_silicon_sme.cache_clear()
    monkeypatch.setattr(
        scalene_utility.subprocess, "run", lambda *a, **k: _Result("1\n")
    )
    assert scalene_utility.is_apple_silicon_sme() is True

    scalene_utility.is_apple_silicon_sme.cache_clear()
    monkeypatch.setattr(
        scalene_utility.subprocess, "run", lambda *a, **k: _Result("0\n")
    )
    assert scalene_utility.is_apple_silicon_sme() is False

    scalene_utility.is_apple_silicon_sme.cache_clear()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
