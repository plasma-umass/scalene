"""Tests for multiprocessing spawn mode support (GitHub issue #873).

This test verifies that Scalene works correctly when users set the
multiprocessing start method to 'spawn', which is the default on macOS
since Python 3.8.

The original issues were that:
1. Scalene would force 'fork' mode, causing "context has already been set" errors
2. Even with force=True, ReplacementSemLock couldn't be pickled for spawn mode
3. ReplacementSemLock's custom reducer created an independent semaphore in each
   spawned process instead of preserving mutual exclusion
"""

import multiprocessing
import pickle
import sys

import pytest


def try_acquire_lock(lock, connection):
    """Try to acquire a parent-held lock and report the result."""
    acquired = lock.acquire(timeout=0.25)
    connection.send(acquired)
    if acquired:
        lock.release()
    connection.close()


class TestReplacementSemLockPickling:
    """Test that ReplacementSemLock can be pickled for spawn mode."""

    def test_semlock_rejects_pickle_outside_process_spawning(self):
        """Match multiprocessing.Lock's restriction on arbitrary pickling."""
        from scalene.replacement_sem_lock import ReplacementSemLock

        ctx = multiprocessing.get_context("spawn")
        lock = ReplacementSemLock(ctx=ctx)

        with pytest.raises(RuntimeError, match="shared between processes"):
            pickle.dumps(lock)


class TestGetContextReplacement:
    """Test that replacement_get_context respects user's method choice."""

    def test_get_context_respects_spawn(self):
        """Test that get_context returns spawn context when requested."""
        # Import after Scalene's replacement is installed
        from scalene.replacement_get_context import replacement_mp_get_context
        from scalene.scalene_profiler import Scalene

        # Install the replacement
        replacement_mp_get_context(Scalene)

        # Request spawn context
        ctx = multiprocessing.get_context("spawn")
        assert ctx._name == "spawn"

    @pytest.mark.skipif(sys.platform == "win32", reason="fork not available on Windows")
    def test_get_context_respects_fork(self):
        """Test that get_context returns fork context when requested."""
        ctx = multiprocessing.get_context("fork")
        assert ctx._name == "fork"

    def test_get_context_default(self):
        """Test that get_context returns default context when no method specified."""
        ctx = multiprocessing.get_context()
        # Should return some valid context
        assert ctx._name in ("fork", "spawn", "forkserver")


class TestResourceTrackerFallback:
    """Test that ReplacementSemLock handles resource tracker failures gracefully."""

    @pytest.mark.skipif(sys.platform == "win32", reason="fork not available on Windows")
    def test_brokenpipe_fallback_to_fork(self):
        """Test that BrokenPipeError during semaphore creation falls back to fork."""
        from unittest.mock import patch

        from scalene.replacement_sem_lock import ReplacementSemLock

        # Simulate resource tracker failure by patching the parent __init__
        original_init = ReplacementSemLock.__bases__[0].__init__
        call_count = [0]

        def failing_init(self, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call (spawn) fails
                raise BrokenPipeError("simulated resource tracker failure")
            # Second call (fork fallback) succeeds
            original_init(self, *args, **kwargs)

        import warnings

        ctx = multiprocessing.get_context("spawn")
        with patch.object(ReplacementSemLock.__bases__[0], "__init__", failing_init):
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                lock = ReplacementSemLock(ctx=ctx)
                # Should have fallen back to fork
                assert lock._ctx_method == "fork"
                # Should have emitted a warning
                assert len(w) == 1
                assert "resource tracker failed" in str(w[0].message).lower()


class TestSpawnModeIntegration:
    """Integration tests for spawn mode with multiprocessing primitives."""

    def test_lock_with_spawn_context(self):
        """Test that locks work with spawn context."""
        from scalene.replacement_sem_lock import ReplacementSemLock

        ctx = multiprocessing.get_context("spawn")
        lock = ReplacementSemLock(ctx=ctx)

        # Test basic lock operations
        assert lock.acquire(timeout=1.0)
        lock.release()

        # Test context manager
        with lock:
            pass  # Should not deadlock

    @pytest.mark.parametrize(
        "method",
        [
            method
            for method in ("spawn", "forkserver")
            if method in multiprocessing.get_all_start_methods()
        ],
    )
    def test_lock_preserves_identity_in_spawned_process(self, method):
        """A child must not acquire the lock while its parent holds it."""
        from scalene.replacement_sem_lock import ReplacementSemLock

        ctx = multiprocessing.get_context(method)
        lock = ReplacementSemLock(ctx=ctx)
        if lock._ctx_method != method:
            pytest.skip(f"{method} semaphore creation fell back to fork")

        receive, send = ctx.Pipe(duplex=False)
        process = ctx.Process(target=try_acquire_lock, args=(lock, send))

        lock.acquire()
        try:
            process.start()
            send.close()
            assert receive.poll(10), "child did not report its lock acquisition result"
            acquired = receive.recv()
        finally:
            lock.release()

        process.join(10)
        assert not process.is_alive(), "child process did not exit"
        assert process.exitcode == 0
        assert not acquired, "child acquired the lock while its parent held it"
