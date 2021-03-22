import os
from scalene.scalene_profiler import Scalene
from scalene.scalene_signals import ScaleneSignals
import signal


@Scalene.shim
def replacement_fork(scalene: Scalene) -> None:
    """
    Raises a signal when a process is the child after
    a fork system call.
    """
    orig_fork = os.fork

    def fork_replacement() -> int:
        result = orig_fork()
        if result == 0:
            os.kill(os.getpid(), ScaleneSignals.fork_signal)
        else:
            scalene.add_child_pid(result)
        return result

    os.fork = fork_replacement
