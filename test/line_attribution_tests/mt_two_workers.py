"""Multithreaded fixture: two worker threads, each with its own allocator line.

Used by ``tests/test_memory_multithreaded.py`` and
``tests/test_memory_multithreaded_stacks.py``. Both workers allocate pure
Python ``array.array`` objects under the GIL — no numpy, no GIL release
— so any attribution gap across threads reflects the stack-walk path in
``whereInPythonWithStack``, not a GIL-release confounder.

Per-worker allocator lines get compared directly against each other
(same iteration count; allocation sizes differ by 4x). The main thread's
``sleep`` and ``join`` lines must NOT be charged with worker bytes — that
would mean Scalene is walking the wrong thread's Python stack when a
sample fires inside a worker.

Line numbers are load-bearing: WORKER_A_ALLOC_LINE, WORKER_B_ALLOC_LINE,
MAIN_SLEEP_LINE, MAIN_JOIN_LINE are referenced as integer constants.
"""
import array
import threading
import time


def spin_a_bit():
    deadline = time.time() + 0.05
    acc = 0
    while time.time() < deadline:
        acc += 1
    return acc


def worker_a():
    held = []
    for _ in range(50):
        held.append(array.array("d", [0]) * 200_000)  # line 34 — ~1.6 MB (WORKER_A_ALLOC_LINE)
        spin_a_bit()
    return len(held)


def worker_b():
    held = []
    for _ in range(50):
        held.append(array.array("d", [0]) * 800_000)  # line 42 — ~6.4 MB (WORKER_B_ALLOC_LINE)
        spin_a_bit()
    return len(held)


def main():
    t_a = threading.Thread(target=worker_a)
    t_b = threading.Thread(target=worker_b)
    t_a.start()
    t_b.start()
    time.sleep(2.5)  # line 52 — main-thread idle (MAIN_SLEEP_LINE)
    t_a.join()       # line 53 — main-thread idle (MAIN_JOIN_LINE)
    t_b.join()


if __name__ == "__main__":
    main()
