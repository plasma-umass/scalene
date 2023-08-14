#!/usr/bin/env python3
"""Test the performance of pprint.PrettyPrinter.

This benchmark was available as `python -m pprint` until Python 3.12.

Authors: Fred Drake (original), Oleg Iarygin (pyperformance port).
"""

from time import perf_counter
from pprint import PrettyPrinter


printable = [('string', (1, 2), [3, 4], {5: 6, 7: 8})] * 100_000
p = PrettyPrinter()


if __name__ == '__main__':

    start_p = perf_counter()
    for i in range(7):
        p.pformat(printable)
    stop_p = perf_counter()
    print("Time elapsed: ", stop_p - start_p)
