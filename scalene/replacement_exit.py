import os
import sys
from scalene.scalene_profiler import Scalene

@Scalene.shim
def replacement_exit(scalene):
    """
    Shims out the unconditional exit with
    the "neat exit" (which raises the SystemExit error and
    allows Scalene to exit neatly)
    """
    os._exit = sys.exit
