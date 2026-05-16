"""Single-threaded fixture: two allocator functions with different byte sizes.

Used by ``tests/test_memory_two_allocators.py`` and
``tests/test_memory_stack_leaf_singlethread.py``. Both allocator functions
run the same number of times, so per-line byte attribution should be
proportional to each allocator's per-call size (~4x spread here, tests
only assert a loose 2x to absorb sampling noise).

Line numbers are load-bearing: the tests reference SMALL_LINE and BIG_LINE
by integer constants. Do not reformat without updating those constants.
"""
import array
import time


def spin_a_bit():
    # Burn CPU so Scalene takes multiple sampling intervals before the
    # program exits. Without this, the loop can complete before a single
    # SIGVTALRM fires, and Scalene emits an empty profile.
    deadline = time.time() + 0.05
    acc = 0
    while time.time() < deadline:
        acc += 1
    return acc


def small_alloc():
    return array.array("d", [0]) * 150_000  # line 28 — ~1.2 MB (SMALL_LINE)


def big_alloc():
    return array.array("d", [0]) * 600_000  # line 32 — ~4.8 MB (BIG_LINE)


def run():
    held = []
    for _ in range(40):
        held.append(small_alloc())
        held.append(big_alloc())
        spin_a_bit()
    return len(held)


if __name__ == "__main__":
    print(run())
