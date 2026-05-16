"""Single-threaded fixture: Python-allocator vs C-allocator byte split.

Used by ``tests/test_memory_python_vs_c.py``. The CPython bytes allocator
counts toward the interposer's ``_pythonCount`` (see
``src/include/sampleheap.hpp``); numpy's ``np.zeros`` goes through libc
``malloc`` and counts toward ``_cCount``. The Python-fraction field in
the JSON output (``n_python_fraction``) should reflect this split
per-line.

Line numbers are load-bearing: PYTHON_LINE and C_LINE are asserted on
directly. If numpy is unavailable, exit cleanly so the test skips
instead of failing spuriously.
"""
import sys
import time

try:
    import numpy as np
except ImportError:
    # Fixture degrades cleanly: no samples attributed to this file,
    # the test recognizes the missing fixture and skips.
    sys.exit(0)


def spin_a_bit():
    deadline = time.time() + 0.05
    acc = 0
    while time.time() < deadline:
        acc += 1
    return acc


def python_alloc():
    return bytes(2 * 10_485_767)  # line 34 — ~20 MB via CPython allocator (PYTHON_LINE)


def c_alloc():
    return np.zeros(2_000_000, dtype=np.float64)  # line 38 — ~16 MB via libc malloc (C_LINE)


def run():
    held = []
    for _ in range(30):
        held.append(python_alloc())
        held.append(c_alloc())
        spin_a_bit()
    return len(held)


if __name__ == "__main__":
    print(run())
