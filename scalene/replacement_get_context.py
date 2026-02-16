import multiprocessing
from typing import Any

from scalene.scalene_profiler import Scalene


@Scalene.shim
def replacement_mp_get_context(scalene: Scalene) -> None:
    old_get_context = multiprocessing.get_context

    def replacement_get_context(method: Any = None) -> Any:
        # Respect the user's requested method instead of forcing fork
        return old_get_context(method)

    multiprocessing.get_context = replacement_get_context
