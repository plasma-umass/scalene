import multiprocessing
import os
from scalene.scalene_profiler import Scalene
import sys
import threading
import time

minor_version = sys.version_info.minor


@Scalene.shim
def replacement_pjoin(scalene: Scalene) -> None:
    def replacement_process_join(self, timeout: float = -1) -> None:  # type: ignore
        """
        A drop-in replacement for multiprocessing.Process.join
        that periodically yields to handle signals
        """
        # print(multiprocessing.process.active_children())
        if minor_version >= 7:
            self._check_closed()
        assert self._parent_pid == os.getpid(), "can only join a child process"
        assert self._popen is not None, "can only join a started process"
        tident = threading.get_ident()
        if timeout < 0:
            interval = sys.getswitchinterval()
        else:
            interval = min(timeout, sys.getswitchinterval())
        start_time = time.perf_counter()
        while True:
            scalene.set_thread_sleeping(tident)
            res = self._popen.wait(interval)
            if res is not None:
                from multiprocessing.process import _children  # type: ignore

                scalene.remove_child_pid(self.pid)
                _children.discard(self)
                return
            scalene.reset_thread_sleeping(tident)
            # I think that this should be timeout--
            # Interval is the sleep time per-tic,
            # but timeout determines whether it returns
            if timeout != -1:
                end_time = time.perf_counter()
                if end_time - start_time >= timeout:
                    from multiprocessing.process import _children  # type: ignore

                    _children.discard(self)
                    return

    multiprocessing.Process.join = replacement_process_join  # type: ignore
