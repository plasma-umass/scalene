import multiprocessing
import os
from scalene.scalene_profiler import Scalene
import sys
import threading


@Scalene.shim
def replacement_pjoin(scalene: Scalene):
    """
    A drop-in replacement for multiprocessing.Process.join
    that periodically yields to handle signals
    """
    def replacement_process_join(self, timeout: float = -1):
        self._check_closed()
        assert self._parent_pid == os.getpid(), 'can only join a child process'
        assert self._popen is not None, 'can only join a started process'
        tident = threading.get_ident()
        if timeout < 0:
            interval = sys.getswitchinterval()
        else:
            interval = min(timeout, sys.getswitchinterval())
        start_time = scalene.get_wallclock_time()
        while True:
            scalene.set_thread_sleeping(tident)
            res = self._popen.wait(interval)
            if res is not None:
                from multiprocessing.process import _children
                _children.discard(self)
                return
            scalene.reset_thread_sleeping(tident)
            if timeout != -1:
                end_time = scalene.get_wallclock_time()
                if end_time - start_time >= timeout:
                    from multiprocessing.process import _children
                    _children.discard(self)
                    return
    multiprocessing.Process.join = replacement_process_join
