"""
Reproducer for scalene issue #857 using a raw C pthread.

This exercises the specific code path that was buggy: allocations made by a
thread that has NO PyThreadState (a pthread spawned from a C extension, not
from `threading.Thread`). Before the fix, those allocations were attributed
to whatever line the main thread happened to be on — typically the sleep
below — which made unrelated Python lines look like they allocated GB.

Build the companion library first (see native_thread_alloc.c):

    cc -O2 -fPIC -shared -o test/libnative_thread_alloc.dylib \\
        test/native_thread_alloc.c

Then:

    python -m scalene run --memory --cli --- test/test-native-thread-alloc-ctypes.py
"""

import ctypes
import os
import sys
import time


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    libname = "libnative_thread_alloc.dylib" if sys.platform == "darwin" else "libnative_thread_alloc.so"
    libpath = os.path.join(here, libname)
    lib = ctypes.CDLL(libpath)
    lib.run_native_allocs.argtypes = [ctypes.c_long]
    lib.run_native_allocs.restype = None

    t0 = time.time()
    lib.run_native_allocs(128)   # 128 * 8 MB = 1 GB churn on a non-Python thread
    dt = time.time() - t0
    print(f"native thread finished in {dt:.2f}s")

    # Main-thread sleep: BEFORE the fix, this line would be charged with
    # most of the native thread's allocations. After the fix, the native
    # thread's allocations go to the <native> bucket instead.
    time.sleep(1.0)


if __name__ == "__main__":
    main()
