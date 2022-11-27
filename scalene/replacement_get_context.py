import multiprocessing
import sys

from typing import Any

from scalene.scalene_profiler import Scalene


@Scalene.shim
def replacement_mp_get_context(scalene: Scalene) -> None:
    old_get_context = multiprocessing.get_context

    def replacement_get_context(method: Any = None) -> Any:
        if sys.platform == "win32":
            print(
                "Scalene currently only supports the `multiprocessing` library on Mac and Unix platforms."
            )
            sys.exit(1)
        return old_get_context("fork")

    multiprocessing.get_context = replacement_get_context
