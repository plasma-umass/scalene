"""Multithreaded fixture: worker allocates under a released GIL (numpy).

Used by ``tests/test_memory_multithreaded_gil_release.py``. This is the
asserting form of ``test/test-native-thread-alloc.py`` and pins issue
#857: when OpenBLAS/MKL drop the GIL inside a numpy allocation, the
sampled bytes must still be attributed to the worker thread's Python
frame, not to ``time.sleep`` on the main thread where the GIL happens
to be held.

Line numbers are load-bearing: WORKER_ALLOC_LINE, MAIN_SLEEP_LINE are
referenced as integer constants. If numpy is unavailable, exit cleanly
so the test skips.
"""
import sys
import threading
import time

try:
    import numpy as np
except ImportError:
    sys.exit(0)


def worker():
    for _ in range(40):
        a = np.zeros((1024, 1024), dtype=np.float64)  # line 26 — ~8 MB via libc malloc, GIL often released (WORKER_ALLOC_LINE)
        a += 1.0
        del a


def main():
    t = threading.Thread(target=worker)
    t.start()
    time.sleep(2.0)  # line 34 — main-thread idle; must NOT be charged with worker bytes (MAIN_SLEEP_LINE)
    t.join()


if __name__ == "__main__":
    main()
