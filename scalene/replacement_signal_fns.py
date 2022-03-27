import os
import signal
import sys
import traceback

from scalene.scalene_profiler import Scalene


@Scalene.shim
def replacement_signal_fns(scalene: Scalene) -> None:

    old_signal = signal.signal
    if sys.version_info < (3, 8):
        old_raise_signal = lambda s: os.kill(os.getpid(), s)
    else:
        old_raise_signal = signal.raise_signal

    old_kill = os.kill

    if sys.platform != "win32":
        new_cpu_signal = signal.SIGUSR1
    else:
        new_cpu_signal = signal.SIGFPE

    def replacement_signal(signum: int, handler):  # type: ignore
        all_signals = scalene.get_all_signals_set()
        timer_signal, cpu_signal = scalene.get_timer_signals()
        timer_signal_str = signal.strsignal(signum)
        if signum == cpu_signal:
            print(
                f"WARNING: Scalene uses {timer_signal_str} to profile. If your code raises {timer_signal_str} from non-Python code, use SIGUSR1. "
                "Code that raises signals from within Python code will be rerouted."
            )
            return old_signal(new_cpu_signal, handler)
        if signum in all_signals:
            print(
                "Error: Scalene cannot profile your program because it (or one of its packages) "
                "uses timers or signals that Scalene depends on. If you have encountered this warning, please file an issue using this URL: "
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
            timer_signal_str = (
                "SIGALRM" if timer_signal == signal.SIGALRM else "SIGVTALRM"
            )
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

    signal.signal = replacement_signal
    if sys.version_info >= (3, 8):
        signal.raise_signal = replacement_raise_signal
    os.kill = replacement_kill
