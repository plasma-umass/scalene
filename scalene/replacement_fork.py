import os
from scalene.scalene_profiler import Scalene
from scalene.scalene_signals import ScaleneSignals


@Scalene.shim
def replacement_fork(scalene: Scalene) -> None:
    """
    Executes Scalene fork() handling.
    Works just like os.register_at_fork(), but unlike that also provides the child PID.
    """
    orig_fork = os.fork

    def fork_replacement() -> int:
        scalene.before_fork()

        child_pid = orig_fork()
        if child_pid == 0:
            scalene.after_fork_in_child()
        else:
            scalene.after_fork_in_parent(child_pid)

        return child_pid

    os.fork = fork_replacement
