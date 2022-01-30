from scalene.scalene_profiler import Scalene
import multiprocessing
from typing import Any

@Scalene.shim
def replacement_mp_get_context(scalene: Scalene) -> None:
    old_get_context = multiprocessing.get_context
    def replacement_get_context(method: Any = None):
        return old_get_context('fork')
    multiprocessing.get_context = replacement_get_context