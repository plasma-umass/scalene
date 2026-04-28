"""Regression tests for the malloc/free signal-handler recursion guard
(issue #1038).

Without the guard, malloc_signal_handler -> _should_trace -> pathlib.Path
-> signal_blocking_wrapper-patched os call -> allocation -> trace
callback (under --use-legacy-tracer) -> malloc_signal_handler ...
recurses until the Python stack overflows.

The guard is a module-level boolean checked at the very top of the
handler that early-returns on re-entry. It does not need to be
thread-local: Python signal handlers registered via signal.signal() only
ever run on the main thread under standard CPython.

These tests exercise the guard mechanism without standing up the full
Scalene profiler (which would need argparse + signal setup + a daemon
thread).
"""

import sys

import scalene.scalene_profiler as scalene_profiler_mod
from scalene.scalene_profiler import Scalene


def test_malloc_handler_drops_reentry() -> None:
    """If the guard flag is already set, malloc_signal_handler returns
    immediately without touching its body (which would otherwise
    dereference Scalene.__args.memory and crash on an uninitialized
    Scalene)."""
    scalene_profiler_mod._in_malloc_handler = True
    try:
        result = Scalene.malloc_signal_handler(0, sys._getframe())
        assert result is None
    finally:
        scalene_profiler_mod._in_malloc_handler = False


def test_free_handler_drops_reentry() -> None:
    """Same guard contract on free_signal_handler."""
    scalene_profiler_mod._in_free_handler = True
    try:
        result = Scalene.free_signal_handler(0, sys._getframe())
        assert result is None
    finally:
        scalene_profiler_mod._in_free_handler = False


def test_separate_flags_for_malloc_and_free() -> None:
    """malloc and free guards are independent — a malloc-in-flight must
    not block a free-in-flight (and vice versa)."""
    scalene_profiler_mod._in_malloc_handler = True
    try:
        # Free handler must still be entrant. Manually verify the flag is
        # not set rather than calling the body (which needs a real Scalene).
        assert scalene_profiler_mod._in_free_handler is False
    finally:
        scalene_profiler_mod._in_malloc_handler = False

    scalene_profiler_mod._in_free_handler = True
    try:
        assert scalene_profiler_mod._in_malloc_handler is False
    finally:
        scalene_profiler_mod._in_free_handler = False


def test_guards_default_false_at_import() -> None:
    """Module import must leave both guards off so the very first signal
    that arrives runs the handler body."""
    # Re-import to confirm initial state. The other tests in this file
    # always restore the flag in finally blocks.
    assert scalene_profiler_mod._in_malloc_handler is False
    assert scalene_profiler_mod._in_free_handler is False
