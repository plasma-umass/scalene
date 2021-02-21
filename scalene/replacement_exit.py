import os
import sys
from scalene.scalene_profiler import Scalene


@Scalene.shim
def replacement_exit(scalene: Scalene) -> None:
    """
    Shims out the unconditional exit with
    the "neat exit" (which raises the SystemExit error and
    allows Scalene to exit neatly)
    """
    # Note: MyPy doesn't like this, but it works because passing an int
    # to sys.exit does the right thing
    os._exit = sys.exit  # type: ignore
