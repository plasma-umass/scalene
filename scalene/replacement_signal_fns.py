import os
import signal
import sys

from scalene.scalene_profiler import Scalene
from typing import Any

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
    if sys.version_info < (3, 8):

        def old_raise_signal(s):
            return os.kill(os.getpid(), s)

    else:
        old_raise_signal = signal.raise_signal

    old_kill = os.kill

    if sys.platform != "win32":
        new_cpu_signal = signal.SIGUSR1
    else:
        new_cpu_signal = signal.SIGFPE

    def replacement_signal(signum: int, handler: Any) -> Any:
        all_signals = scalene.get_all_signals_set()
        timer_signal, cpu_signal = scalene.get_timer_signals()
        timer_signal_str = signal.strsignal(signum)
        start_signal, stop_signal = scalene.get_lifecycle_signals()
        if signum == cpu_signal:
            print(
                f"WARNING: Scalene uses {timer_signal_str} to profile.\n"
                f"If your code raises {timer_signal_str} from non-Python code, use SIGUSR1.\n"
                "Code that raises signals from within Python code will be rerouted."
            )
            return old_signal(new_cpu_signal, handler)
        if signum in [start_signal, stop_signal]:
            if not scalene.get_lifecycle_disabled():
                print(
                    f"WARNING: signal {signal.strsignal(signum)} is used to\n"
                    "enable or disable Scalene. Starting or stopping Scalene with\n"
                    "`--start` or `--stop` will be disabled."
                )
                # Disable the other signal
                if signum == start_signal:
                    old_signal(stop_signal, signal.SIG_IGN)
                if signum == stop_signal:
                    old_signal(start_signal, signal.SIG_IGN)
                scalene.disable_lifecycle()
            return old_signal(signum, handler)
        # Fallthrough condition-- if we haven't dealt with the signal at this point in the call and the handler is
        # a NOP-like, then we can ignore it. It can't have been set already, and the expected return value is the
        # previous handler, so this behavior is reasonable
        if signal in all_signals and (handler is signal.SIG_IGN or handler is signal.SIG_DFL):
            return handler
        # If trying to "reset" to a handler that we already set it to, ignore
        if signum in expected_handlers_map and expected_handlers_map[signum] is handler:
            return signal.SIG_IGN
        if signum in all_signals:
            print(
                "Error: Scalene cannot profile your program because it (or one of its packages)\n"
                f"uses timers or a signal that Scalene depends on ({timer_signal_str}).\n"
                "If you have encountered this warning, please file an issue using this URL:\n"
                "https://github.com/plasma-umass/scalene/issues/new/choose"
            )

            exit(-1)
        return old_signal(signum, handler)

    def replacement_raise_signal(signum: int) -> None:
        _, cpu_signal = scalene.get_timer_signals()
        if signum == cpu_signal:
            old_raise_signal(new_cpu_signal)
        old_raise_signal(signum)

    def replacement_kill(pid: int, signum: int) -> None:
        _, cpu_signal = scalene.get_timer_signals()
        if pid == os.getpid() or pid in scalene.child_pids:
            if signum == cpu_signal:
                return old_kill(pid, new_cpu_signal)
        old_kill(pid, signum)

    if sys.platform != "win32":
        old_setitimer = signal.setitimer
        old_siginterrupt = signal.siginterrupt

        def replacement_siginterrupt(signum, flag):  # type: ignore
            all_signals = scalene.get_all_signals_set()
            timer_signal, cpu_signal = scalene.get_timer_signals()
            if signum == cpu_signal:
                return old_siginterrupt(new_cpu_signal, flag)
            if signum in all_signals:
                print(
                    "Error: Scalene cannot profile your program because it (or one of its packages) "
                    "uses timers or signals that Scalene depends on. If you have encountered this warning, please file an issue using this URL: "
                    "https://github.com/plasma-umass/scalene/issues/new/choose"
                )
            return old_siginterrupt(signum, flag)

        def replacement_setitimer(which, seconds, interval=0.0):  # type: ignore
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

    signal.signal = replacement_signal # type: ignore
    if sys.version_info >= (3, 8):
        signal.raise_signal = replacement_raise_signal
    os.kill = replacement_kill
