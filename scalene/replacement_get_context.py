from scalene.scalene_profiler import Scalene
import multiprocessing
from typing import Any
@Scalene.shim
def replace_get_context(scalene: Scalene) -> None:
    # This is needed because any attempt to manually override 
    # the context doesn't actually do anything-- this is a method
    def replacement_get_context(_ignore: Any):
        return multiprocessing.context.ForkContext
    multiprocessing.get_context = replacement_get_context