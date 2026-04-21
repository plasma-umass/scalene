"""
Workload for smoketest_issue_659.py.

A threading.Thread worker runs a loop of numpy allocations while the main
thread sleeps. See https://github.com/plasma-umass/scalene/discussions/659
and test/smoketest_issue_659.py for the regression assertions.
"""

import threading
import time


def worker() -> None:
    # Import numpy inside the worker (module-level numpy import under
    # scalene on some Python versions trips an unrelated recursion in
    # scalene's os-function wrappers during pathlib init).
    import numpy as np

    # Retain allocations so cumulative footprint grows well past scalene's
    # 1 MB sampling window. Also touch every page so the allocator can't
    # skip the mapping work.
    arrays = []
    for _ in range(32):
        a = np.zeros((2048, 2048), dtype=np.float64)  # ~32 MB each, ~1 GB total
        a += 1.0
        arrays.append(a)


def main() -> None:
    t = threading.Thread(target=worker)
    t.start()
    time.sleep(3.0)  # MUST NOT be charged with worker's allocations
    t.join()


if __name__ == "__main__":
    main()
