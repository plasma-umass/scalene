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

    # Mix of short-lived churn (128 iterations × 8 MB) for many tracer events
    # and a few retained 32 MB arrays so the footprint grows past scalene's
    # 1 MB sampling threshold. We need both: the churn reliably fires the
    # Python line tracer, and the retained growth pushes RSS up so the
    # allocator-side sampler crosses multiple windows.
    retained = []
    for i in range(128):
        a = np.zeros((1024, 1024), dtype=np.float64)  # ~8 MB
        a += 1.0
        if i % 16 == 0:
            retained.append(np.zeros((2048, 2048), dtype=np.float64))  # ~32 MB


def main() -> None:
    t = threading.Thread(target=worker)
    t.start()
    time.sleep(2.0)  # MUST NOT be charged with worker's allocations
    t.join()


if __name__ == "__main__":
    main()
