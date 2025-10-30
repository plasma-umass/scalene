import multiprocessing.context
import multiprocessing.synchronize
import random
import sys
import threading
from typing import Any, Callable, Optional, Tuple

from scalene.scalene_profiler import Scalene

def _make_replacement_semlock() -> "ReplacementSemLock":
    # create it using the default mp context so it is spawn-safe on Windows
    ctx = multiprocessing.get_context()
    return ReplacementSemLock(ctx=ctx)

class ReplacementSemLock(multiprocessing.synchronize.Lock):
    def __init__(
        self, ctx: Optional[multiprocessing.context.DefaultContext] = None
    ) -> None:
        # Ensure to use the appropriate context while initializing
        if ctx is None:
            ctx = multiprocessing.get_context()
        super().__init__(ctx=ctx)

    def __enter__(self) -> bool:
        switch_interval = sys.getswitchinterval()
        max_timeout = switch_interval
        tident = threading.get_ident()
        while True:
            timeout = random.random() * max_timeout
            Scalene.set_thread_sleeping(tident)
            acquired = self._semlock.acquire(timeout=timeout)  # type: ignore
            Scalene.reset_thread_sleeping(tident)
            if acquired:
                return True
            else:
                max_timeout *= 2  # Exponential backoff
                # Cap timeout at 1 second
                if max_timeout >= 1.0:
                    max_timeout = 1.0

    def __exit__(self, *args: Any) -> None:
        super().__exit__(*args)


    def __reduce__(self) -> Tuple[Callable[..., Any], Tuple[Any, ...]]:
        return (_make_replacement_semlock, ())

# important: force the class to live in the module name that workers will import
ReplacementSemLock.__module__ = "scalene.replacement_sem_lock"
