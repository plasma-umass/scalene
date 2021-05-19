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
        scalene.prepare_for_fork()

        child_pid = orig_fork()
        if child_pid == 0:
            scalene.child_after_fork()
        else:
            scalene.parent_after_fork(child_pid)

        return child_pid

    os.fork = fork_replacement
