import os
from scalene.scalene_profiler import Scalene
import signal

@Scalene.shim
def replacement_fork(scalene: Scalene):
    """
    Raises a signal when a process is the child after
    a fork system call.
    """
    orig_fork = os.fork

    def fork_replacement():
        result = orig_fork()
        if result == 0:
            signal.raise_signal(signal.SIGTSTP)
        return result
    os.fork = fork_replacement