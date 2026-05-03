"""Replacement for threading.Thread.start to register threads for per-thread sampling."""

import threading
from typing import Any

from scalene.scalene_profiler import Scalene


@Scalene.shim
def replacement_thread_start(scalene: Scalene) -> None:
    """Replace Thread.start to register worker threads for per-thread native stack sampling."""
    orig_thread_start = threading.Thread.start
    orig_thread_run = threading.Thread.run

    def thread_start_replacement(self: threading.Thread) -> None:
        """Wrapper around Thread.start."""
        # Just call original start - registration happens in run()
        orig_thread_start(self)

    def thread_run_replacement(self: threading.Thread) -> None:
        """Wrapper around Thread.run that registers/unregisters for sampling."""
        from scalene.scalene_utility import (
            register_thread_for_sampling,
            unregister_thread_from_sampling,
        )

        # Register this thread for per-thread native stack sampling
        register_thread_for_sampling()
        try:
            orig_thread_run(self)
        finally:
            # Unregister on thread exit
            unregister_thread_from_sampling()

    threading.Thread.start = thread_start_replacement  # type: ignore
    threading.Thread.run = thread_run_replacement  # type: ignore
