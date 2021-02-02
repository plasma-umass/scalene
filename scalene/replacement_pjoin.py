import multiprocessing
import os
from scalene.scalene_profiler import Scalene
import sys
import threading


@Scalene.shim
def replacement_pjoin(scalene: Scalene) -> None:
    def replacement_process_join(self, timeout: float = -1) -> None:
        from multiprocessing.process import _children
        # print(multiprocessing.process.active_children())
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
            res = self._popen.wait(timeout)
            if res is not None:
                _children.discard(self)
                return
            print(multiprocessing.process.active_children())
            scalene.reset_thread_sleeping(tident)
            if timeout != -1:
                end_time = scalene.get_wallclock_time()
                if end_time - start_time >= timeout:
                    _children.discard(self)
                    return
    multiprocessing.Process.join = replacement_process_join # type: ignore
