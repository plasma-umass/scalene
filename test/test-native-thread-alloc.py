"""
Reproducer for issue #857: allocations in threads that don't hold a live
Python frame must not be smeared onto whatever line the main thread is on.

Uses numpy (which releases the GIL for large matmuls) plus a Python
threading.Thread. The worker thread does have a PyThreadState, so its
allocations already get correct per-thread Python-frame attribution; this
test mostly verifies the regression path — that scalene still runs, the new
native_allocations_mb field shows up in the JSON, and time.sleep in the main
thread is NOT charged with the worker's allocations.

For a genuine "native thread with no Python frame" reproducer you need a
pthread spawned by a C extension (e.g., a threaded BLAS backend). That is
harder to stage portably in a smoketest — see issue #857 for context.

Run with:
    python -m scalene run --memory --cli test/test-native-thread-alloc.py
"""

import threading
import time


def worker() -> None:
    # Large numpy allocations. With OpenBLAS/MKL these frequently happen
    # under a released GIL.
    import numpy as np
    for _ in range(64):
        a = np.zeros((1024, 1024), dtype=np.float64)  # ~8 MB
        a += 1.0
        del a


def main() -> None:
    t = threading.Thread(target=worker)
    t.start()
    time.sleep(2.0)  # <-- before fix, this line could be charged worker's MB
    t.join()


if __name__ == "__main__":
    main()
