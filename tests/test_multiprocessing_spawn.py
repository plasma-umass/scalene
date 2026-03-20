"""Tests for multiprocessing spawn mode support (GitHub issue #873).

This test verifies that Scalene works correctly when users set the
multiprocessing start method to 'spawn', which is the default on macOS
since Python 3.8.

The original issue was that:
1. Scalene would force 'fork' mode, causing "context has already been set" errors
2. Even with force=True, ReplacementSemLock couldn't be pickled for spawn mode
"""

import multiprocessing
import pickle
import sys

import pytest


class TestReplacementSemLockPickling:
    """Test that ReplacementSemLock can be pickled for spawn mode."""

    def test_semlock_pickle_roundtrip(self):
        """Test that ReplacementSemLock can be pickled and unpickled."""
        from scalene.replacement_sem_lock import ReplacementSemLock

        lock = ReplacementSemLock()

        # This would fail before the fix with spawn mode
        pickled = pickle.dumps(lock)
        unpickled = pickle.loads(pickled)

        # Verify the unpickled lock works
        assert unpickled.acquire(timeout=0.1)
        unpickled.release()

    def test_semlock_reduce_preserves_context_method(self):
        """Test that __reduce__ preserves the context method for spawn safety."""
        from scalene.replacement_sem_lock import ReplacementSemLock

        # Create lock with explicit spawn context
        ctx = multiprocessing.get_context("spawn")
        lock = ReplacementSemLock(ctx=ctx)

        # Verify __reduce__ returns the context method
        reduced = lock.__reduce__()
        assert len(reduced) == 2
        assert callable(reduced[0])
        assert len(reduced[1]) == 1
        # The context method should be "spawn" unless fallback occurred
        # (on systems where resource tracker fails, it falls back to "fork")
        assert reduced[1][0] in ("spawn", "fork")

    @pytest.mark.skipif(sys.platform == "win32", reason="fork not available on Windows")
    def test_semlock_reduce_with_fork_context(self):
        """Test that __reduce__ works with fork context too."""
        from scalene.replacement_sem_lock import ReplacementSemLock

        ctx = multiprocessing.get_context("fork")
        lock = ReplacementSemLock(ctx=ctx)

        reduced = lock.__reduce__()
        assert reduced[1][0] == "fork"


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

    @pytest.mark.skipif(sys.platform == "win32", reason="fork not available on Windows")
    def test_lock_pickle_with_different_contexts(self):
        """Test that locks can be pickled regardless of context type."""
        from scalene.replacement_sem_lock import ReplacementSemLock

        for method in ["fork", "spawn"]:
            ctx = multiprocessing.get_context(method)
            lock = ReplacementSemLock(ctx=ctx)

            # Should be able to pickle
            pickled = pickle.dumps(lock)
            unpickled = pickle.loads(pickled)

            # Verify it works
            assert unpickled.acquire(timeout=0.1)
            unpickled.release()
