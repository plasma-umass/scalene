# Scalene Profiling Guide

## Basic Usage

```bash
python3 -m scalene --cli --json --outfile profile.json script.py
```

## Understanding Python vs C (Native) Time

Scalene's key differentiator is separating Python time from C/native time:

- **`n_cpu_percent_python`**: Time spent executing Python bytecode - **this is your optimization target**
- **`n_cpu_percent_c`**: Time spent in C extensions/native code - generally NOT optimizable at the Python level

**Critical insight**: Focus optimization efforts on code with high Python time. Code spending most of its time in C is already running native code and can only be improved by:
1. Reducing the number of calls to the C code (algorithmic changes)
2. Using the library more efficiently (e.g., batching operations)
3. Switching to a different library

For example, Python's slice reversal `perm[:k+1] = perm[k::-1]` shows high C time because it's implemented in C. Replacing it with a Python loop makes performance *worse* because it moves work from fast C code to slow Python code.

## Memory Profiling Metrics

Scalene tracks detailed memory behavior:

- **`n_malloc_mb`**: Memory allocated on this line
- **`n_peak_mb`**: Peak memory usage attributed to this line
- **`n_avg_mb`**: Average memory footprint
- **`n_growth_mb`**: Net memory growth (allocations minus frees) - useful for detecting memory leaks
- **`n_usage_fraction`**: Fraction of total memory used by this line

**When to focus on memory**:
- High `n_growth_mb` with `n_python_fraction` near 1.0 indicates Python objects accumulating (potential leak)
- High `n_peak_mb` suggests opportunities to reduce memory footprint by processing data in chunks

## Copy Volume Tracking

- **`n_copy_mb_s`**: Rate of memory copying in MB/s attributed to this line

**Why this matters**: High copy volume indicates inefficient data handling:
- Unnecessary string concatenation in loops (use `join()` or `io.StringIO`)
- Repeated array/list copies (use views, in-place operations, or pre-allocation)
- Passing large objects by value when references would suffice

Example: A line showing 100+ MB/s copy volume in a data processing loop suggests refactoring to avoid intermediate copies.

## GPU Metrics (if applicable)

- **`n_gpu_percent`**: Percentage of GPU time
- **`n_gpu_avg_memory_mb`**: Average GPU memory usage
- **`n_gpu_peak_memory_mb`**: Peak GPU memory usage

## System Time

- **`n_sys_percent`**: Time spent in system calls (I/O, etc.)

High system time may indicate:
- Excessive file I/O (batch reads/writes)
- Too many small network requests (batch API calls)
- Suboptimal disk access patterns

## Optimization Decision Tree

1. **Check Python vs C time split**
   - High Python time → Optimize the Python code
   - High C time → Consider algorithmic changes or different libraries

2. **Check memory growth**
   - Sustained growth → Look for leaks, unbounded caches, or accumulating data structures

3. **Check copy volume**
   - High copy rate → Refactor to use views, in-place operations, or pre-allocation

4. **Check system time**
   - High system time → Batch I/O operations, use async I/O, or optimize file access patterns
