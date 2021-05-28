from scalene.scalene_profiler import Scalene
import sys
import time
from typing import Optional
import threading


@Scalene.shim
def replacement_thread_join(scalene: Scalene) -> None:
    orig_thread_join = threading.Thread.join

    def thread_join_replacement(
        self: threading.Thread, timeout: Optional[float] = None
    ) -> None:
        """We replace threading.Thread.join with this method which always
        periodically yields."""
        start_time = time.perf_counter()
        interval = sys.getswitchinterval()
        while self.is_alive():
            scalene.set_thread_sleeping(threading.get_ident())
            orig_thread_join(self, interval)
            scalene.reset_thread_sleeping(threading.get_ident())
            # If a timeout was specified, check to see if it's expired.
            if timeout:
                end_time = time.perf_counter()
                if end_time - start_time >= timeout:
                    return None
        return None

    threading.Thread.join = thread_join_replacement  # type: ignore
