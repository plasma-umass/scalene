"""Demo workload for the experimental stitched-stacks timeline view.

Runs four back-to-back phases sized to last ~1s each so signal-based
sampling lands many hits in each band. Each phase exercises a different
kind of activity, so the resulting timeline shows distinct visual
sections:

    1. CPU-bound math loop
       -> baseline; no GC, no I/O. Timeline panel shows the user code.
    2. Synchronous file I/O burst
       -> blue I/O track lights up; main panel shows _io / read / write.
    3. Forced garbage collection
       -> red GC track lights up; main panel shows gc_collect_main /
          _PyGC_Collect.
    4. Asynchronous I/O via asyncio.sleep
       -> blue I/O track again; main panel shows the full asyncio call
          chain (Runner.run -> BaseEventLoop._run_once ->
          KqueueSelector.select / EpollSelector.select / ...).

Run with:

    python3 -m scalene run --stacks --cpu-only --no-browser \\
        -o /tmp/timeline-demo.json test/timeline_view_demo.py
    python3 -m scalene view /tmp/timeline-demo.json

then click the right-arrow next to "Stitched stack timeline" near the
bottom of the rendered profile.
"""

import asyncio
import gc
import math
import os
import tempfile
import time


def cpu_phase(duration: float) -> float:
    """Pure CPU; no allocations of consequence."""
    s = 0.0
    end = time.monotonic() + duration
    while time.monotonic() < end:
        for i in range(50_000):
            s += math.sqrt(i * 1.234)
    return s


def io_phase(duration: float) -> None:
    """File I/O burst — repeatedly write and read back a temp file."""
    fd, path = tempfile.mkstemp(suffix=".scalene-timeline-demo")
    os.close(fd)
    try:
        payload = ("x" * 200 + "\n") * 2000
        end = time.monotonic() + duration
        while time.monotonic() < end:
            with open(path, "w") as f:
                f.write(payload)
            with open(path) as f:
                f.read()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def gc_phase(duration: float) -> int:
    """Build cyclic garbage and force gc.collect() in a tight loop."""
    cycles = []
    end = time.monotonic() + duration
    while time.monotonic() < end:
        for _ in range(100):
            a: list = []
            b = [a]
            a.append(b)
            cycles.append(a)
        gc.collect()
    return len(cycles)


async def _slow_io() -> None:
    for _ in range(20):
        await asyncio.sleep(0.05)


async def _async_main(concurrency: int) -> None:
    await asyncio.gather(*[_slow_io() for _ in range(concurrency)])


def async_phase() -> None:
    """asyncio workload that spends most of its time in the selector."""
    asyncio.run(_async_main(concurrency=10))


if __name__ == "__main__":
    cpu_phase(1.0)
    io_phase(1.0)
    gc_phase(1.0)
    async_phase()
