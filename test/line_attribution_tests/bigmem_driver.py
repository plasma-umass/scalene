"""Regression fixture: memory-stacks flame chart end-to-end check.

The workload allocates two sizes of float arrays through a shared
allocator helper (``make_vec``) called from two distinct caller
functions (``make_big``, ``make_small``). Correct synchronous per-sample
stack capture produces two distinct call paths in the memory flame
chart — ``run -> make_big -> make_vec`` and ``run -> make_small ->
make_vec`` — with bytes attributed in a ~5:2 ratio (5 x 100 MB vs
200 x 1 MB = ~500 MB vs ~200 MB).

The fixture is sized so that Scalene reliably takes samples even under
heavy CI contention: total allocations are well above any sampling
threshold (~700 MB peak footprint, ~5 big + 200 small allocations).
See ``tests/test_memory_stacks_bigmem.py`` for the assertions.
"""
import array


def make_vec(n):  # caller on line 20 — the true allocator
    return array.array("d", [0]) * n  # line 20 — allocator body


def make_big():
    return make_vec(12_500_000)  # ~100 MB, line 24


def make_small():
    return make_vec(125_000)  # ~1 MB, line 28


def run():
    big_list = []
    small_list = []
    for _ in range(5):
        big_list.append(make_big())  # line 35 — big caller
    for _ in range(200):
        small_list.append(make_small())  # line 37 — small caller
    return len(big_list) + len(small_list)


if __name__ == "__main__":
    print(run())
