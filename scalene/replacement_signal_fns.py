from scalene.scalene_profiler import Scalene
import signal
from sys import stderr
import os

@Scalene.shim
def replacement_signal_fns(scalene: Scalene) -> None:
    old_setitimer = signal.setitimer
    old_signal = signal.signal
    old_raise_signal = signal.raise_signal
    old_kill = os.kill

    all_signals = scalene.get_all_signals_set()
    timer_signal, cpu_signal = scalene.get_timer_signals()
    timer_signal_str = "SIGALRM" if timer_signal == signal.SIGALRM else "SIGVTALRM"
    new_cpu_signal = signal.SIGUSR1

    
    def replacement_setitimer(which, seconds, interval=0.0):
        if which == timer_signal:
            old = scalene.client_timer.get_itimer()
            if seconds == 0:   
                scalene.client_timer.reset()
            else:
                scalene.client_timer.set_itimer(seconds, interval)
            return old
        return old_setitimer(which, seconds, interval)

    def replacement_signal(signum, handler):
        if signum == cpu_signal:
            print(f"WARNING: Scalene uses {timer_signal_str} to profile. If you manually raise {timer_signal_str} from non-python code, use SIGUSR1."
                    "If you raise signals from inside Python code, they will be rerouted." )
            return old_signal(new_cpu_signal, handler)
        if signum in all_signals:
            print("Error: Scalene cannot profile your program because it (or one of its packages)"
                  "uses timers or signals that Scalene depends on. If you have encountered this warning, please file an issue using this URL: "
                  "https://github.com/plasma-umass/scalene/issues/new/choose")
            exit(-1)
        return old_signal(signum, handler)
    
    def replacement_raise_signal(signum):
        if signum == cpu_signal:
            old_raise_signal(new_cpu_signal)
        return old_raise_signal(signum)

    def replacement_kill(pid, signum):
        if pid == os.getpid() or pid in scalene.child_pids:
            if signum == cpu_signal:
                return old_kill(pid, new_cpu_signal)
        return old_kill(pid, signum)


    signal.setitimer = replacement_setitimer
    signal.signal = replacement_signal
    signal.raise_signal = replacement_raise_signal
    os.kill = replacement_kill