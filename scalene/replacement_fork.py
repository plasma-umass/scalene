import os
from scalene.scalene_profiler import Scalene
from scalene.scalene_signals import ScaleneSignals


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
            scalene.child_after_fork()
        else:
            scalene.add_child_pid(result)
        return result

    os.fork = fork_replacement
