"""Signal-free CPU sampler for Apple Silicon with SME (issue #1056).

On Apple M4+ chips the macOS kernel mis-saves/restores ARM SME
("streaming"-mode) register state whenever a signal handler is invoked
while a thread is mid-kernel in Accelerate BLAS. This silently corrupts
in-flight numerical results — even an empty C signal handler triggers it
(see scalene/issue-1056-probes and issue #1056). No handler-side change
can fix it, because the corruption is applied by the kernel on
``sigreturn``, after the handler returns.

The only correctness-preserving mitigation is to stop delivering the
CPU-profiling timer signal on these machines. This module replaces the
``setitimer``/``SIGVTALRM`` mechanism with a background *helper thread*
that periodically calls Scalene's CPU sample handler directly. Because no
signal is ever delivered, the kernel never runs its buggy SME save/
restore path, and the worker thread's matrix state stays intact.

This mirrors the existing Windows approach (``windows_timer_loop`` in
``scalene_signal_manager``), which already drives the CPU handler from a
background thread for a different reason (``signal.raise_signal`` is
unavailable off the main thread on Windows). The handler reads thread
state via ``sys._current_frames()``, which is thread-safe and works from
any thread, so calling it from this helper is sound.

Python-vs-C time attribution still works: the CPU profiler classifies the
main thread's time from the bytecode at ``f_lasti`` (a ``CALL*`` opcode
means the frame is sitting in a native call) — the same rule already used
for worker threads — rather than relying on the signal-deferral timing
trick that needs an actual signal. See ``scalene_cpu_profiler`` and the
``probe_frames_sampler`` prototype.
"""
import contextlib
import threading
from typing import Optional

from scalene.scalene_signals import SignalHandlerFunction
from scalene.scalene_sigqueue import ScaleneSigQueue


class MacThreadSampler:
    """Drives the CPU sample handler from a background thread (no signals).

    The handler is called with ``frame=None`` (like the Windows path); it
    collects all thread frames itself via ``sys._current_frames()``.

    When memory profiling is enabled, this thread also polls the malloc/
    free and memcpy sample queues. On the SME path those signals
    (SIGXCPU/SIGXFSZ/SIGPROF) are set to SIG_IGN — delivering them would
    corrupt SME state just like the CPU signal (issue #1056) — but the
    native allocator always writes its sample record to the sample file
    *before* raising the signal, so polling the queues here drains exactly
    the same data with nothing lost. This mirrors Windows'
    ``_windows_memory_poll_loop``.
    """

    # Poll memory queues at a fixed 10ms cadence, like the Windows path,
    # independent of the (randomized, exponential) CPU sampling interval.
    _MEM_POLL_INTERVAL = 0.01

    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._handler: Optional[SignalHandlerFunction] = None
        self._cpu_signal: int = 0
        self._rate: float = 0.01
        self._alloc_sigq: Optional[ScaleneSigQueue] = None
        self._memcpy_sigq: Optional[ScaleneSigQueue] = None

    def start(
        self,
        cpu_signal_handler: SignalHandlerFunction,
        cpu_signal: int,
        cpu_sampling_rate: float,
        alloc_sigq: Optional[ScaleneSigQueue] = None,
        memcpy_sigq: Optional[ScaleneSigQueue] = None,
    ) -> None:
        """Start the sampling thread.

        cpu_signal_handler: Scalene's CPU sample handler.
        cpu_signal: the signal number passed as the handler's first arg
            (used only for bookkeeping; no signal is actually raised).
        cpu_sampling_rate: seconds between samples.
        alloc_sigq, memcpy_sigq: when memory profiling is on, the queues to
            poll-drain (their handlers' signals are SIG_IGN'd on this path).
        """
        self._handler = cpu_signal_handler
        self._cpu_signal = int(cpu_signal)
        self._rate = cpu_sampling_rate
        self._alloc_sigq = alloc_sigq
        self._memcpy_sigq = memcpy_sigq
        self._stop_event.clear()
        # Non-daemon so sampling continues for short-running programs even
        # if the main thread finishes quickly; cleanup is via stop().
        self._thread = threading.Thread(target=self._loop, daemon=False)
        self._thread.start()

    def _loop(self) -> None:
        """Periodically invoke the CPU handler (and poll memory) until stopped."""
        # Initial delay so the first samples land in user code, not in
        # Scalene's own startup (matches windows_timer_loop).
        if self._stop_event.wait(0.01):
            return
        polling_memory = self._alloc_sigq is not None
        while not self._stop_event.is_set():
            # Sample first, then wait, so we still record something even if
            # the program exits almost immediately after this point.
            if self._handler is not None:
                # The handler must not touch the timer on this path (no
                # signal-based timing); the profiler guards that. Any
                # exception in a sample must not kill the sampler thread.
                with contextlib.suppress(Exception):
                    self._handler(self._cpu_signal, None)
            if polling_memory:
                self._poll_memory()
            # Wait the shorter of the CPU rate and the memory poll interval,
            # so neither cadence is starved. Event.wait() (not time.sleep())
            # lets stop() interrupt the wait immediately.
            wait = self._rate
            if polling_memory:
                wait = min(wait, self._MEM_POLL_INTERVAL)
            if self._stop_event.wait(wait):
                break

    def _poll_memory(self) -> None:
        """Drain malloc/free and memcpy sample queues (data already on disk)."""
        with contextlib.suppress(Exception):
            if self._alloc_sigq is not None:
                self._alloc_sigq.put([0])
            if self._memcpy_sigq is not None:
                self._memcpy_sigq.put((0, None))

    def stop(self) -> None:
        """Stop the sampling thread and wait for it to finish."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
