import sys
from scalene.scalene_profiler import Scalene
import threading
import time
from typing import Any


@Scalene.shim
def replacement_lock(scalene: Scalene) -> None:
    class ReplacementLock(object):
        """Replace lock with a version that periodically yields and updates sleeping status."""

        def __init__(self) -> None:
            # Cache the original lock (which we replace)
            # print("INITIALIZING LOCK")
            self.__lock: threading.Lock = scalene.get_original_lock()

        def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
            tident = threading.get_ident()
            if blocking == 0:
                blocking = False
            start_time = time.perf_counter()
            if blocking:
                if timeout < 0:
                    interval = sys.getswitchinterval()
                else:
                    interval = min(timeout, sys.getswitchinterval())
            else:
                interval = -1
            while True:
                scalene.set_thread_sleeping(tident)
                acquired_lock = self.__lock.acquire(blocking, interval)
                scalene.reset_thread_sleeping(tident)
                if acquired_lock:
                    return True
                if not blocking:
                    return False
                # If a timeout was specified, check to see if it's expired.
                if timeout != -1:
                    end_time = time.perf_counter()
                    if end_time - start_time >= timeout:
                        return False

        def release(self) -> None:
            self.__lock.release()

        def locked(self) -> bool:
            return self.__lock.locked()

        def _at_fork_reinit(self) -> None:
            try:
                self.__lock._at_fork_reinit()  # type: ignore
            except AttributeError:
                pass

        def __enter__(self) -> None:
            self.acquire()

        def __exit__(self, type: str, value: str, traceback: Any) -> None:
            self.release()

    threading.Lock = ReplacementLock  # type: ignore
