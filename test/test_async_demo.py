"""Demo async program for profiling with --async.

Usage:
    python -m scalene run --async test/test_async_demo.py
    python -m scalene view --cli
"""

import asyncio


async def fast_io():
    """Short I/O wait - should show small await %."""
    for _ in range(10):
        await asyncio.sleep(0.01)


async def slow_io():
    """Long I/O wait - should show large await %."""
    await asyncio.sleep(2.0)


async def cpu_work():
    """CPU-bound work - should show CPU time but no await time."""
    total = sum(range(20_000_000))
    return total


async def mixed_work():
    """Mix of CPU and I/O."""
    total = sum(range(10_000_000))
    await asyncio.sleep(1.0)
    return total


async def main():
    await asyncio.gather(
        fast_io(),
        slow_io(),
        cpu_work(),
        mixed_work(),
    )


if __name__ == "__main__":
    asyncio.run(main())
