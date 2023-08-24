import multiprocessing
import random
import sys
import threading
from multiprocessing.synchronize import Lock
from scalene.scalene_profiler import Scalene
from typing import Any

def _recreate_replacement_sem_lock():
    return ReplacementSemLock()

class ReplacementSemLock(multiprocessing.synchronize.Lock):
    def __init__(self, ctx=None):
        # Ensure to use the appropriate context while initializing
        if ctx is None:
            ctx = multiprocessing.get_context()
        super().__init__(ctx=ctx)
    def __enter__(self) -> bool:
        max_timeout = sys.getswitchinterval()
        tident = threading.get_ident()
        while True:
            Scalene.set_thread_sleeping(tident)
            timeout = random.random() * max_timeout
            acquired = self._semlock.acquire(timeout=timeout)  # type: ignore
            Scalene.reset_thread_sleeping(tident)
            if acquired:
                return True
            else:
                max_timeout *= 2 # Exponential backoff
    def __exit__(self, *args: Any) -> None:
        super().__exit__(*args)
    def __reduce__(self):
        return (_recreate_replacement_sem_lock, ())
