from scalene.scalene_profiler import Scalene
import sys
from typing import Optional
import threading


@Scalene.shim
def replacement_thread_join(scalene):
    orig_thread_join = threading.Thread.join
    def thread_join_replacement(
        self: threading.Thread, timeout: Optional[float] = None
    ) -> None:
        """We replace threading.Thread.join with this method which always
            periodically yields."""
        start_time = scalene.get_wallclock_time()
        interval = sys.getswitchinterval()
        while self.is_alive():
            scalene.set_thread_sleeping(threading.get_ident())
            orig_thread_join(self, interval)
            scalene.reset_thread_sleeping(threading.get_ident())
            # If a timeout was specified, check to see if it's expired.
            if timeout:
                end_time = scalene.get_wallclock_time()
                if end_time - start_time >= timeout:
                    return None
        return None
    threading.Thread.join = thread_join_replacement
