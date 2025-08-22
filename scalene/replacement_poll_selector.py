import selectors
import sys
import threading
import time
from typing import List, Optional, Tuple

from scalene.scalene_profiler import Scalene


@Scalene.shim
def replacement_poll_selector(scalene: Scalene) -> None:
    """
    A replacement for selectors.PollSelector that
    periodically wakes up to accept signals
    """

    class ReplacementPollSelector(selectors.PollSelector):
        def select(
            self, timeout: Optional[float] = -1
        ) -> List[Tuple[selectors.SelectorKey, int]]:
            tident = threading.get_ident()
            start_time = time.perf_counter()
            if not timeout or timeout < 0:
                interval = sys.getswitchinterval()
            else:
                interval = min(timeout, sys.getswitchinterval())
            while True:
                scalene.set_thread_sleeping(tident)
                selected = super().select(interval)
                scalene.reset_thread_sleeping(tident)
                if selected or timeout == 0:
                    return selected
                end_time = time.perf_counter()
                if timeout and timeout != -1 and end_time - start_time >= timeout:
                    return []  # None

    ReplacementPollSelector.__qualname__ = (
        "replacement_poll_selector.ReplacementPollSelector"
    )
    selectors.PollSelector = ReplacementPollSelector  # type: ignore
