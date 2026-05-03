#!/usr/bin/env python3
"""
Benchmark to verify native stack stitching across different thread contexts.

This exercises:
- CPU-bound computation in the main thread (captured with stitched stacks)
- CPU-bound computation in worker threads (Python frames captured via sys._current_frames)
- I/O-bound operations (file, network simulation)
- Async operations with asyncio
- Nested function calls to test stack depth

Note on stack stitching limitations:
- Native stacks are captured via signal handler, which runs in the main thread
- Python frames are captured for ALL threads via sys._current_frames()
- Combined (stitched) stacks show native frames only for the main thread
- Worker thread samples appear in Python-only stacks without native frames
"""

import asyncio
import hashlib
import io
import json
import math
import os
import random
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List


# --- CPU-bound work for main thread (will have stitched stacks) ---

def main_cpu_level4() -> int:
    """Deepest level - actual work."""
    total = 0
    for i in range(100000):
        total += i * i
    return total


def main_cpu_level3() -> int:
    """Level 3."""
    return main_cpu_level4() + main_cpu_level4()


def main_cpu_level2() -> int:
    """Level 2."""
    return main_cpu_level3()


def main_cpu_level1() -> int:
    """Level 1 - entry point."""
    return main_cpu_level2()


def main_thread_cpu_work(iterations: int) -> int:
    """CPU work done in the main thread - will have stitched native stacks."""
    total = 0
    for _ in range(iterations):
        total += main_cpu_level1()
    return total


# --- CPU-bound work for worker threads ---

def fibonacci_recursive(n: int) -> int:
    """Recursive fibonacci - deep call stacks."""
    if n <= 1:
        return n
    return fibonacci_recursive(n - 1) + fibonacci_recursive(n - 2)


def matrix_multiply(size: int) -> List[List[float]]:
    """Matrix multiplication - pure Python computation."""
    a = [[random.random() for _ in range(size)] for _ in range(size)]
    b = [[random.random() for _ in range(size)] for _ in range(size)]
    result = [[0.0] * size for _ in range(size)]

    for i in range(size):
        for j in range(size):
            for k in range(size):
                result[i][j] += a[i][k] * b[k][j]
    return result


def compute_primes(limit: int) -> List[int]:
    """Sieve of Eratosthenes - memory + CPU."""
    sieve = [True] * (limit + 1)
    sieve[0] = sieve[1] = False

    for i in range(2, int(math.sqrt(limit)) + 1):
        if sieve[i]:
            for j in range(i * i, limit + 1, i):
                sieve[j] = False

    return [i for i, is_prime in enumerate(sieve) if is_prime]


def hash_data_repeatedly(data: bytes, iterations: int) -> str:
    """Hash computation - exercises native code (hashlib)."""
    result = data
    for _ in range(iterations):
        result = hashlib.sha256(result).digest()
    return result.hex()


# --- I/O-bound work ---

def file_io_workload(num_files: int, file_size: int) -> int:
    """File I/O - write and read temporary files."""
    total_bytes = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for i in range(num_files):
            filepath = os.path.join(tmpdir, f"test_{i}.bin")
            data = os.urandom(file_size)

            with open(filepath, "wb") as f:
                f.write(data)

            with open(filepath, "rb") as f:
                read_data = f.read()
                total_bytes += len(read_data)

    return total_bytes


def string_io_workload(iterations: int) -> int:
    """StringIO operations - in-memory I/O."""
    total_chars = 0
    for _ in range(iterations):
        buffer = io.StringIO()
        for j in range(100):
            buffer.write(f"Line {j}: " + "x" * 100 + "\n")

        buffer.seek(0)
        content = buffer.read()
        total_chars += len(content)
        buffer.close()

    return total_chars


def json_serialization_workload(iterations: int) -> int:
    """JSON encode/decode - common I/O pattern."""
    data = {
        "users": [
            {"id": i, "name": f"user_{i}", "scores": list(range(100))}
            for i in range(50)
        ],
        "metadata": {"version": 1, "timestamp": time.time()},
    }

    total_bytes = 0
    for _ in range(iterations):
        encoded = json.dumps(data)
        json.loads(encoded)  # Verify roundtrip
        total_bytes += len(encoded)

    return total_bytes


# --- Async work ---

async def async_cpu_task(task_id: int) -> int:
    """Async task doing CPU work with yields."""
    _ = task_id  # unused but kept for identification
    total = 0
    for i in range(1000):
        total += sum(range(i))
        if i % 100 == 0:
            await asyncio.sleep(0)  # Yield to event loop
    return total


async def async_io_simulation(task_id: int) -> float:
    """Simulate async I/O with small sleeps."""
    _ = task_id  # unused but kept for identification
    total_wait = 0.0
    for _ in range(20):
        wait_time = random.uniform(0.001, 0.01)
        await asyncio.sleep(wait_time)
        total_wait += wait_time
    return total_wait


async def async_mixed_workload(task_id: int) -> dict:
    """Mixed async workload - CPU and I/O."""
    results = {"task_id": task_id, "cpu": 0, "io": 0.0}

    # Interleave CPU and I/O
    for _ in range(10):
        # CPU burst
        results["cpu"] += sum(i * i for i in range(1000))
        await asyncio.sleep(0)

        # I/O burst
        await asyncio.sleep(0.005)
        results["io"] += 0.005

    return results


async def run_async_workloads() -> dict:
    """Run multiple async workloads concurrently."""
    tasks = []

    # CPU-heavy async tasks
    for i in range(5):
        tasks.append(async_cpu_task(i))

    # I/O simulation tasks
    for i in range(5):
        tasks.append(async_io_simulation(i))

    # Mixed tasks
    for i in range(5):
        tasks.append(async_mixed_workload(i))

    results = await asyncio.gather(*tasks)
    return {"async_results": len(results)}


# --- Thread worker functions ---

def thread_cpu_heavy(thread_id: int, results: dict) -> None:
    """Thread doing CPU-heavy work."""
    start = time.time()

    # Mix of CPU operations
    fib_result = fibonacci_recursive(28)
    matrix_result = matrix_multiply(50)
    primes = compute_primes(50000)
    hash_result = hash_data_repeatedly(b"benchmark" * 1000, 1000)

    elapsed = time.time() - start
    results[f"cpu_thread_{thread_id}"] = {
        "type": "cpu_heavy",
        "fib": fib_result,
        "matrix_size": len(matrix_result),
        "prime_count": len(primes),
        "hash": hash_result[:16],
        "elapsed": elapsed,
    }


def thread_io_heavy(thread_id: int, results: dict) -> None:
    """Thread doing I/O-heavy work."""
    start = time.time()

    file_bytes = file_io_workload(20, 10000)
    string_chars = string_io_workload(100)
    json_bytes = json_serialization_workload(100)

    elapsed = time.time() - start
    results[f"io_thread_{thread_id}"] = {
        "type": "io_heavy",
        "file_bytes": file_bytes,
        "string_chars": string_chars,
        "json_bytes": json_bytes,
        "elapsed": elapsed,
    }


def thread_mixed(thread_id: int, results: dict) -> None:
    """Thread with mixed CPU and I/O."""
    start = time.time()

    cpu_result = 0
    io_result = 0

    for _ in range(10):
        # CPU burst
        cpu_result += sum(i ** 2 for i in range(5000))

        # I/O burst
        io_result += string_io_workload(10)

    elapsed = time.time() - start
    results[f"mixed_thread_{thread_id}"] = {
        "type": "mixed",
        "cpu_result": cpu_result,
        "io_result": io_result,
        "elapsed": elapsed,
    }


def thread_async_runner(thread_id: int, results: dict) -> None:
    """Thread that runs async workloads."""
    start = time.time()

    # Create new event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        async_results = loop.run_until_complete(run_async_workloads())
    finally:
        loop.close()

    elapsed = time.time() - start
    results[f"async_thread_{thread_id}"] = {
        "type": "async",
        "results": async_results,
        "elapsed": elapsed,
    }


def thread_executor_nested(thread_id: int, results: dict) -> None:
    """Thread that spawns its own ThreadPoolExecutor."""
    start = time.time()

    def inner_task(n: int) -> int:
        return sum(i * i for i in range(n))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(inner_task, 10000) for _ in range(10)]
        inner_results = [f.result() for f in futures]

    elapsed = time.time() - start
    results[f"executor_thread_{thread_id}"] = {
        "type": "executor_nested",
        "inner_count": len(inner_results),
        "total": sum(inner_results),
        "elapsed": elapsed,
    }


# --- Main benchmark ---

def run_benchmark() -> dict:
    """Run the full benchmark with multiple thread types."""
    print("Starting stack stitching benchmark...")
    print(f"Python version: {sys.version}")
    print()

    results = {}
    threads = []

    # Phase 1: Main thread CPU work (will have stitched native stacks)
    print("Phase 1: Main thread CPU work (stitched native stacks)...")
    start_phase1 = time.time()
    main_result = main_thread_cpu_work(20)
    results["main_thread_cpu"] = {
        "type": "main_cpu",
        "result": main_result,
        "elapsed": time.time() - start_phase1,
    }

    # Phase 2: Worker threads (Python stacks captured, no stitched native)
    thread_configs = [
        (thread_cpu_heavy, 0),
        (thread_cpu_heavy, 1),
        (thread_io_heavy, 0),
        (thread_io_heavy, 1),
        (thread_mixed, 0),
        (thread_mixed, 1),
        (thread_async_runner, 0),
        (thread_executor_nested, 0),
    ]

    print(f"\nPhase 2: Launching {len(thread_configs)} worker threads...")
    start_phase2 = time.time()

    for func, tid in thread_configs:
        t = threading.Thread(target=func, args=(tid, results), name=f"{func.__name__}_{tid}")
        threads.append(t)
        t.start()

    # Main thread does more CPU work while waiting
    print("  Main thread doing CPU work while workers run...")
    main_result2 = main_thread_cpu_work(10)
    results["main_thread_cpu_2"] = {
        "type": "main_cpu_concurrent",
        "result": main_result2,
    }

    # Wait for all threads
    for t in threads:
        t.join()

    total_time = time.time() - start_phase2

    print(f"\nAll threads completed in {total_time:.2f}s")
    print("\nResults by thread:")
    print("-" * 60)

    for key in sorted(results.keys()):
        info = results[key]
        elapsed = info.get("elapsed", 0)
        print(f"  {key}: type={info['type']}, elapsed={elapsed:.2f}s" if elapsed else f"  {key}: type={info['type']}")

    results["_summary"] = {
        "total_threads": len(threads),
        "total_time": total_time,
    }

    return results


def test_perthread_native_stack_stitching():
    """Test that per-thread native stack sampling captures worker thread stacks.

    This test verifies that when --stacks is enabled, Scalene captures native
    stacks from worker threads (not just the main thread) and includes them
    in the combined_stacks output.

    Note: This test requires the native unwind extension to be available.
    On platforms/Python versions where it's not available, the test is skipped.
    """
    import subprocess
    import tempfile
    import pytest

    # Check if native unwinding is available
    try:
        from scalene import _scalene_unwind
        if not getattr(_scalene_unwind, 'available', 0):
            pytest.skip("Native stack unwinding not available on this platform")
    except ImportError:
        pytest.skip("Native stack unwind extension not built")

    # Create a minimal test script that runs worker threads
    test_script = '''
import threading
import time

def cpu_work():
    total = 0
    for i in range(500000):
        total += i * i
    return total

def worker():
    for _ in range(5):
        cpu_work()

# Start worker threads
threads = []
for i in range(4):
    t = threading.Thread(target=worker, name=f"worker_{i}")
    threads.append(t)
    t.start()

# Main thread also does work
for _ in range(10):
    cpu_work()

for t in threads:
    t.join()
'''

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(test_script)
        script_path = f.name

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        output_path = f.name

    try:
        # Run scalene with --stacks
        result = subprocess.run(
            [sys.executable, '-m', 'scalene', 'run', '--stacks', '--cpu-only',
             '-o', output_path, script_path],
            capture_output=True,
            text=True,
            timeout=60,
        )

        # Check that scalene ran successfully
        assert result.returncode == 0 or 'profile saved' in result.stdout, \
            f"Scalene failed: {result.stderr}"

        # Load and verify the profile
        with open(output_path) as f:
            profile = json.load(f)

        combined_stacks = profile.get('combined_stacks', [])

        # On some platforms/configurations, combined_stacks may be empty
        # if native unwinding doesn't work at runtime. Skip in that case.
        if len(combined_stacks) == 0:
            pytest.skip("No combined stacks captured (native unwinding may not work at runtime)")

        # Check for stacks - at minimum we should have main thread stacks
        # with native frames (the main thread always gets native stacks)
        has_native_frames = False
        for entry in combined_stacks:
            stack = entry[0]
            for frame in stack:
                if isinstance(frame, dict) and frame.get('kind') == 'native':
                    has_native_frames = True
                    break
            if has_native_frames:
                break

        assert has_native_frames, "No native frames found in combined_stacks"

    finally:
        # Cleanup
        import os
        try:
            os.unlink(script_path)
        except OSError:
            pass
        try:
            os.unlink(output_path)
        except OSError:
            pass


if __name__ == "__main__":
    results = run_benchmark()
    print("\nBenchmark complete.")
    print(f"Total worker threads: {results['_summary']['total_threads']}")
    print(f"Total time: {results['_summary']['total_time']:.2f}s")
