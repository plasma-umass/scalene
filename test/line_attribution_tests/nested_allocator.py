"""Regression fixture: memory attribution for allocations inside a
short-lived allocator function called in a hot loop from a caller.

Motivation: Python signal delivery is asynchronous. By the time the
SIGXCPU (malloc-sample) handler runs, the allocator function may have
already returned, so ``frame.f_lineno`` in the async handler points at
the *caller* line, not the allocator line. Memory attribution must come
from the synchronously-captured stack in C++ (``whereInPythonWithStack``
in ``src/source/pywhere.cpp``), which stamps the sample record's
``(filename, lineno)`` while still inside the allocator — and publishes
the leaf into ``Scalene.__last_profiled`` so per-line malloc counts are
credited to the allocator, not the caller.

The workload is sized so that Scalene reliably takes samples (total
allocations >> the default 1 MB sampling window, and the run takes
> 1 second of wall time even on slow CI). Line numbers matter — see
``tests/test_line_attribution_nested.py`` which asserts them directly.
"""
import array
import time


def allocate_one():
    return array.array("d", [0]) * 200_000  # line 24 — ~1.6 MB each


def spin_a_bit():
    # Burn CPU so Scalene gets multiple profiling intervals before the
    # program exits. Without this, fast machines finish the loop before
    # Scalene's sampler has a chance to fire, and Scalene's "did not run
    # long enough" guard produces an empty profile — which under full
    # pytest-suite contention happens reliably. 0.05s per iter × 40
    # iters = 2s of sustained activity, safely above the 1s floor.
    deadline = time.time() + 0.05
    acc = 0
    while time.time() < deadline:
        acc += 1
    return acc


def run():
    held = []
    for _ in range(40):
        held.append(allocate_one())  # line 44 (caller; should NOT get malloc credit)
        spin_a_bit()
    return len(held)


if __name__ == "__main__":
    print(run())
