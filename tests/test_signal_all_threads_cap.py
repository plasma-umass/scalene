"""Regression test for the per-tick cap on signal_all_threads.

A process with many registered worker threads should not see the
signal_all_threads cost grow without bound — the implementation
caps the number of pthread_kills per call (kSignalAllBatch, exposed
as _scalene_unwind.signal_all_batch) and rotates through the
registry across successive calls, so every thread is still sampled,
just at a lower per-thread rate.

See https://github.com/plasma-umass/scalene/issues/1056 (the
--stacks-cost discussion in the issue).
"""
import signal
import sys
import threading
import time

import pytest


if sys.platform == "win32":
    pytest.skip("native unwinder is not built on Windows", allow_module_level=True)


@pytest.fixture
def unwind_module():
    try:
        from scalene import _scalene_unwind  # type: ignore[attr-defined]
    except ImportError:
        pytest.skip("scalene._scalene_unwind not available in this build")
    if not getattr(_scalene_unwind, "available", False):
        pytest.skip("native unwinder not available on this platform")
    # Install the per-thread sampler on a signal that isn't used by anyone else
    # in this test process. SIGPROF is what Scalene uses at runtime; it's safe
    # here because we don't drive ITIMER_PROF.
    _scalene_unwind.install_perthread_sampler(int(signal.SIGPROF))
    yield _scalene_unwind
    # Best-effort restore: leaving a SIGPROF handler installed for the rest of
    # the test process is harmless (no source generates the signal), and the
    # native module doesn't expose an uninstall hook.


@pytest.fixture
def batch_size(unwind_module):
    """The per-call cap exposed by the native module."""
    return int(unwind_module.signal_all_batch)


def test_cap_caps_signaled_per_call(unwind_module, batch_size):
    """signal_all_threads should signal at most batch_size threads per call
    regardless of how many are registered."""
    n_workers = batch_size * 4
    stop = threading.Event()
    ready = threading.Barrier(n_workers + 1)

    def worker():
        unwind_module.register_thread()
        ready.wait()
        # Block on the signal we care about so we don't accidentally consume
        # CPU during the test. SIGPROF is delivered by pthread_kill, which
        # interrupts the sleep but the handler doesn't unblock it permanently.
        while not stop.is_set():
            time.sleep(0.05)
        unwind_module.unregister_thread()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(n_workers)]
    for t in threads:
        t.start()
    ready.wait()
    # Let all workers fully register.
    time.sleep(0.1)

    try:
        signaled, errors = unwind_module.signal_all_threads()
        assert errors == 0, f"pthread_kill failed {errors} times"
        assert signaled <= batch_size, f"cap violated: {signaled} > {batch_size}"
        assert signaled == batch_size, (
            f"expected exactly {batch_size} signaled with "
            f"{n_workers} workers registered, got {signaled}"
        )
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=2.0)


def test_cap_rotates_across_calls(unwind_module, batch_size):
    """Across successive calls, signal_all_threads should cover every live
    worker thread, not just the same K slots over and over.

    The cap is K per call; coverage of N threads requires at least
    ceil(N/K) calls, after which the total signaled count must reach N.
    """
    n_workers = batch_size * 3
    stop = threading.Event()
    ready = threading.Barrier(n_workers + 1)

    def worker():
        unwind_module.register_thread()
        ready.wait()
        while not stop.is_set():
            time.sleep(0.05)
        unwind_module.unregister_thread()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(n_workers)]
    for t in threads:
        t.start()
    ready.wait()
    time.sleep(0.1)

    try:
        calls = (n_workers // batch_size) + 2
        total_signaled = 0
        for _ in range(calls):
            signaled, errors = unwind_module.signal_all_threads()
            assert errors == 0
            assert signaled <= batch_size
            total_signaled += signaled

        assert total_signaled >= n_workers, (
            f"after {calls} calls, only {total_signaled} signals sent; "
            f"cursor likely not rotating (n_workers={n_workers})"
        )
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=2.0)


def test_cap_is_a_noop_when_under_cap(unwind_module, batch_size):
    """With fewer than K registered threads, all of them should be signaled
    in a single call (the cap shouldn't suppress legitimate samples)."""
    n_workers = max(1, batch_size // 4)
    stop = threading.Event()
    ready = threading.Barrier(n_workers + 1)

    def worker():
        unwind_module.register_thread()
        ready.wait()
        while not stop.is_set():
            time.sleep(0.05)
        unwind_module.unregister_thread()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(n_workers)]
    for t in threads:
        t.start()
    ready.wait()
    time.sleep(0.1)

    try:
        signaled, errors = unwind_module.signal_all_threads()
        assert errors == 0
        assert signaled == n_workers, (
            f"under cap ({n_workers} < {batch_size}) but got "
            f"signaled={signaled}"
        )
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=2.0)
