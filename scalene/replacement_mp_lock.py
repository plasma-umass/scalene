import multiprocessing.synchronize
import sys
import threading
from typing import Any

from scalene.scalene_profiler import Scalene

# import _multiprocessing


# The _multiprocessing module is entirely undocumented-- the header of the
# acquire function is
# static PyObject * _multiprocessing_SemLock_acquire_impl(SemLockObject *self, int blocking, PyObject *timeout_obj)
#
# timeout_obj is parsed as a double

from scalene.replacement_sem_lock import ReplacementSemLock


@Scalene.shim
def replacement_mp_semlock(scalene: Scalene) -> None:
    ReplacementSemLock.__qualname__ = "replacement_semlock.ReplacementSemLock"
    multiprocessing.synchronize.Lock = ReplacementSemLock  # type: ignore
