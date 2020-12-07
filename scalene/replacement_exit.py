import os
import sys
from scalene.scalene_profiler import Scalene

@Scalene.shim
def replacement_exit(scalene):
    os._exit = sys.exit
