"""Torch-heavy workload that exposes profiler memory explosion (#991).

Run under Scalene to observe memory behaviour:

    scalene run benchmarks/bench_torch_memory.py

On master (before the fix), the Scalene process RSS grows continuously
because:
  1. torch.profiler accumulates events with full Python stacks for
     every torch operation for the entire profiling duration.
  2. cpu_samples_list appends a wallclock timestamp on every CPU sample
     without any bound.

After the fix, both are bounded via reservoir sampling / periodic
profiler flushing, so RSS stays roughly constant.

Use ``benchmarks/measure_profiler_memory.py`` to automatically measure
and compare peak RSS.
"""

import sys
import time

try:
    import torch
except ImportError:
    print("ERROR: PyTorch is required.  pip install torch", file=sys.stderr)
    sys.exit(1)

DURATION_SECONDS = 60  # wall-clock runtime (longer = more event accumulation)
MATRIX_SIZE = 256      # small matrices -> many ops per second


def main() -> None:
    print(f"Running torch workload for ~{DURATION_SECONDS}s "
          f"(matrix size {MATRIX_SIZE}) ...")

    ops = 0
    t0 = time.perf_counter()
    deadline = t0 + DURATION_SECONDS

    a = torch.randn(MATRIX_SIZE, MATRIX_SIZE)
    b = torch.randn(MATRIX_SIZE, MATRIX_SIZE)

    while time.perf_counter() < deadline:
        # Each iteration generates multiple torch profiler events
        c = a @ b
        c = c + a
        c = c.relu()
        a, b = b, c
        ops += 3  # matmul + add + relu

        # Re-normalise occasionally to avoid overflow / underflow
        if ops % 3000 == 0:
            a = torch.randn(MATRIX_SIZE, MATRIX_SIZE)
            b = torch.randn(MATRIX_SIZE, MATRIX_SIZE)

    elapsed = time.perf_counter() - t0
    print(f"Completed {ops:,} torch ops in {elapsed:.1f}s "
          f"({ops / elapsed:,.0f} ops/s)")


if __name__ == "__main__":
    main()
