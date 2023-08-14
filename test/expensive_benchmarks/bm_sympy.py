#!/usr/bin/env python3
import time
import pyperf

from sympy import expand, symbols, integrate, tan, summation
from sympy.core.cache import clear_cache


def bench_expand():
    x, y, z = symbols('x y z')
    expand((1 + x + y + z) ** 20)


def bench_integrate():
    x, y = symbols('x y')
    f = (1 / tan(x)) ** 10
    return integrate(f, x)


def bench_sum():
    x, i = symbols('x i')
    summation(x ** i / i, (i, 1, 400))


def bench_str():
    x, y, z = symbols('x y z')
    str(expand((x + 2 * y + 3 * z) ** 30))


def bench_sympy(loops, func):
    timer = pyperf.perf_counter
    dt = 0

    for _ in range(loops):
        # Don't benchmark clear_cache(), exclude it of the benchmark
        clear_cache()

        t0 = timer()
        func()
        dt += (timer() - t0)

    return dt


BENCHMARKS = ("expand", "integrate", "sum", "str")


def add_cmdline_args(cmd, args):
    if args.benchmark:
        cmd.append(args.benchmark)


if __name__ == "__main__":
    # sympy-expand

    import gc
    gc.disable()

    start_p = time.perf_counter()
    for _ in range(25):
        # Don't benchmark clear_cache(), exclude it of the benchmark
        clear_cache()
        bench_expand()
    
    stop_p = time.perf_counter()
    print("Time elapsed: ", stop_p - start_p)
