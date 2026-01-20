import os
import signal
import sys
from typing import Any, Optional, Tuple

from scalene.scalene_profiler import Scalene


@Scalene.shim
def replacement_signal_fns(scalene: Scalene) -> None:
    scalene_signals = scalene.get_signals()
    expected_handlers_map = {
        scalene_signals.malloc_signal: scalene.malloc_signal_handler,
        scalene_signals.free_signal: scalene.free_signal_handler,
        scalene_signals.memcpy_signal: scalene.memcpy_signal_handler,
        signal.SIGTERM: scalene.term_signal_handler,
        scalene_signals.cpu_signal: scalene.cpu_signal_handler,
    }
    old_signal = signal.signal
    old_raise_signal = signal.raise_signal

    old_kill = os.kill

    if sys.platform != "win32":
        new_cpu_signal = signal.SIGUSR1
    else:
        new_cpu_signal = signal.SIGFPE

    # Track which warnings we've already printed to avoid spam
    _warned_signals: set[int] = set()

    # On Linux, we can use real-time signals (SIGRTMIN+n) for cleaner signal redirection.
    # Real-time signals are guaranteed to be delivered and queued, and are rarely used by libraries.
    # On other platforms (macOS, Windows), we fall back to signal handler chaining.
    _use_rt_signals = sys.platform == "linux" and hasattr(signal, "SIGRTMIN")

    # Map original signals to their alternate (redirected) signals
    # On Linux: use real-time signals; on other platforms: None (use chaining)
    _signal_redirects: dict[int, int] = {}
    if _use_rt_signals:
        # Allocate real-time signals for each Scalene signal that might conflict
        # SIGRTMIN+0 is often used by threading libraries, so start from SIGRTMIN+1
        rt_base = getattr(signal, "SIGRTMIN") + 1  # noqa: B009
        start_signal, stop_signal = scalene.get_lifecycle_signals()
        # Map lifecycle and memory signals to real-time signals
        rt_offset = 0
        for sig in [
            start_signal,
            stop_signal,
            scalene_signals.memcpy_signal,
            scalene_signals.malloc_signal,
            scalene_signals.free_signal,
        ]:
            if sig is not None:
                _signal_redirects[sig] = rt_base + rt_offset
                rt_offset += 1

    # Store chained handlers for platforms without real-time signal support
    # Maps signal number -> user's handler
    _chained_handlers: dict[int, Any] = {}

    def _make_chained_handler(scalene_handler: Any, user_handler: Any) -> Any:
        """Create a handler that calls both Scalene's handler and the user's handler."""
        import contextlib
        from types import FrameType
        from typing import Optional

        def chained_handler(sig: int, frame: Optional[FrameType]) -> None:
            # Call Scalene's handler first (don't let errors break user code)
            with contextlib.suppress(Exception):
                scalene_handler(sig, frame)
            # Then call the user's handler (don't let errors propagate)
            if callable(user_handler):
                with contextlib.suppress(Exception):
                    user_handler(sig, frame)

        return chained_handler

    def replacement_signal(signum: int, handler: Any) -> Any:
        all_signals = scalene.get_all_signals_set()
        timer_signal, cpu_signal = scalene.get_timer_signals()
        timer_signal_str = signal.strsignal(signum)
        start_signal, stop_signal = scalene.get_lifecycle_signals()

        # Handle CPU profiling signal - redirect to an alternate signal
        # This allows both Scalene and user code to use timer-based profiling
        if signum == cpu_signal:
            if signum not in _warned_signals:
                print(
                    f"WARNING: Scalene uses {timer_signal_str} to profile.\n"
                    f"If your code raises {timer_signal_str} from non-Python code, use SIGUSR1.\n"
                    "Code that raises signals from within Python code will be rerouted."
                )
                _warned_signals.add(signum)
            return old_signal(new_cpu_signal, handler)

        # Handle lifecycle signals (SIGILL, SIGBUS) - allow co-existence with user code
        if start_signal is not None and signum == start_signal:
            return _handle_signal_coexistence(signum, handler, timer_signal_str)

        if stop_signal is not None and signum == stop_signal:
            return _handle_signal_coexistence(signum, handler, timer_signal_str)

        # Fallthrough condition-- if we haven't dealt with the signal at this point in the call and the handler is
        # a NOP-like, then we can ignore it. It can't have been set already, and the expected return value is the
        # previous handler, so this behavior is reasonable
        if signum in all_signals and (
            handler is signal.SIG_IGN or handler is signal.SIG_DFL
        ):
            return handler
        # If trying to "reset" to a handler that we already set it to, ignore
        if (
            signal.Signals(signum) in expected_handlers_map
            and expected_handlers_map[signal.Signals(signum)] is handler
        ):
            return signal.SIG_IGN

        # Handle memory profiling signals (SIGPROF, SIGXCPU, SIGXFSZ) - allow co-existence
        if signum in all_signals:
            return _handle_signal_coexistence(signum, handler, timer_signal_str)

        return old_signal(signum, handler)

    def _handle_signal_coexistence(
        signum: int, handler: Any, signal_name: "Optional[str]"
    ) -> Any:
        """Handle a signal that both Scalene and user code want to use.

        On Linux: Redirect user's handler to a real-time signal for clean separation.
        On other platforms: Chain handlers so both get called.
        """
        if signum not in _warned_signals:
            sig_str = signal_name or f"signal {signum}"
            if _use_rt_signals and signum in _signal_redirects:
                print(
                    f"WARNING: {sig_str} is also used by Scalene.\n"
                    "Your code's handler will be redirected to an alternate signal."
                )
            else:
                print(
                    f"WARNING: {sig_str} is also used by Scalene.\n"
                    "Both Scalene and your code will handle this signal."
                )
            _warned_signals.add(signum)

        # On Linux with real-time signals: redirect to alternate signal
        if _use_rt_signals and signum in _signal_redirects:
            return old_signal(_signal_redirects[signum], handler)

        # On other platforms: chain handlers
        if handler in (signal.SIG_IGN, signal.SIG_DFL):
            return old_signal(signum, handler)

        scalene_handler = expected_handlers_map.get(signal.Signals(signum))
        if scalene_handler:
            old_user_handler = _chained_handlers.get(signum)
            _chained_handlers[signum] = handler
            chained = _make_chained_handler(scalene_handler, handler)
            old_signal(signum, chained)
            return old_user_handler if old_user_handler else signal.SIG_DFL
        return old_signal(signum, handler)

    def replacement_raise_signal(signum: int) -> None:
        _, cpu_signal = scalene.get_timer_signals()
        if signum == cpu_signal:
            old_raise_signal(new_cpu_signal)
            return
        # On Linux, redirect to real-time signal if applicable
        if _use_rt_signals and signum in _signal_redirects:
            old_raise_signal(_signal_redirects[signum])
            return
        old_raise_signal(signum)

    def replacement_kill(pid: int, signum: int) -> None:
        _, cpu_signal = scalene.get_timer_signals()
        is_self_or_child = pid == os.getpid() or pid in scalene.child_pids
        if is_self_or_child and signum == cpu_signal:
            return old_kill(pid, new_cpu_signal)
        # On Linux, redirect to real-time signal if applicable
        if is_self_or_child and _use_rt_signals and signum in _signal_redirects:
            return old_kill(pid, _signal_redirects[signum])
        old_kill(pid, signum)

    if sys.platform != "win32":
        old_setitimer = signal.setitimer
        old_siginterrupt = signal.siginterrupt

        def replacement_siginterrupt(signum: int, flag: bool) -> None:
            _, cpu_signal = scalene.get_timer_signals()
            if signum == cpu_signal:
                return old_siginterrupt(new_cpu_signal, flag)
            # On Linux, redirect to real-time signal if applicable
            if _use_rt_signals and signum in _signal_redirects:
                return old_siginterrupt(_signal_redirects[signum], flag)
            return old_siginterrupt(signum, flag)

        def replacement_setitimer(
            which: int, seconds: float, interval: float = 0.0
        ) -> Tuple[float, float]:
            timer_signal, cpu_signal = scalene.get_timer_signals()
            if which == timer_signal:
                old = scalene.client_timer.get_itimer()
                if seconds == 0:
                    scalene.client_timer.reset()
                else:
                    scalene.client_timer.set_itimer(seconds, interval)
                return old
            return old_setitimer(which, seconds, interval)

        signal.setitimer = replacement_setitimer
        signal.siginterrupt = replacement_siginterrupt

    signal.signal = replacement_signal  # type: ignore[unused-ignore,assignment]
    signal.raise_signal = replacement_raise_signal
    os.kill = replacement_kill
