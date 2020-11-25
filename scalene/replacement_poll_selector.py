import selectors
import threading
from scalene.scalene_profiler import Scalene
import sys


@Scalene.shim
def replacement_poll_selector(scalene: Scalene):
    class ReplacementPollSelector(selectors.PollSelector):
        def select(self, timeout: float = -1):
            tident = threading.get_ident()
            start_time = scalene.get_wallclock_time()
            if timeout < 0:
                interval = sys.getswitchinterval()
            else:
                interval = min(timeout, sys.getswitchinterval())
            while True:
                scalene.set_thread_sleeping(tident)
                selected = super().select(interval)
                scalene.reset_thread_sleeping(tident)
                if selected:
                    return selected
                end_time = scalene.get_wallclock_time()
                if timeout != -1:
                    if end_time - start_time >= timeout:
                        return None
    selectors.PollSelector = ReplacementPollSelector
