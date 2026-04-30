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

## Stack-Sample Outputs (`--stacks`)

When run with `--stacks`, Scalene records three top-level stack views in the JSON profile. They share the same CPU samples but expose different slices of each one:

- **`stacks`** — Python-only call chains, filtered to user-traceable frames.
- **`native_stacks`** — C/C++ frames from the interrupted thread, captured by Scalene's signal-handler unwinder. Each entry is a list of `[module, symbol, ip, offset]` frames (innermost-first), trimmed to drop Scalene's own handler frames at the leaf and CPython interpreter / process-entry frames at the root.
- **`combined_stacks`** — Stitched Python + native chains for the same sample. Each frame is a structured dict so the seam is explicit:

```json
{"kind": "py",     "display_name": "hot",         "filename_or_module": "/app/work.py",     "line": 42, "ip": null,    "offset": null}
{"kind": "native", "display_name": "cblas_dgemm", "filename_or_module": "/lib/libBLAS.so",  "line": null, "ip": 140735, "offset": 32}
```

Frames are stored outermost-first (caller → callee). The Python segment runs from the program entry point down through user functions; the native segment picks up where Python called into C and runs to the actual interrupted leaf. The seam between the two ends with the deepest user-traceable Python frame and starts with the first native frame outside CPython's interpreter loop.

**How to read it:**

- A stack with only `py` frames means the sample landed in pure Python — no native code was running at the moment of interrupt.
- A stack ending in a `native` frame from a known library (numpy, BLAS, lxml, etc.) means time was actually spent in that library's C code, called from the listed Python frame. This is information `stacks` alone cannot show — the Python eval loop has already returned by the time the Python signal handler runs.
- Multiple `combined_stacks` entries with the same Python prefix and different native leaves are normal: the same Python call site routes work into different C functions.

**When `combined_stacks` adds information beyond `n_cpu_percent_c`:** the per-line `n_cpu_percent_c` tells you *how much* of a line's time is in C. `combined_stacks` tells you *which* C function. If a line shows 85% C time, the stitched stack is what shows whether it's BLAS, regex, JSON parsing, or something else.

**Caveats:**
- `combined_stacks` is best-effort: if multiple native stacks are drained for one Python sample, each is attached to the same Python anchor (v1 policy). Hit counts are reliable; the per-stack breakdown is approximate.
- Native frames whose symbols couldn't be resolved by `dladdr` show empty `display_name` / `filename_or_module` and a non-zero `ip`.
- Not yet collected on Windows (the native unwinder is a stub there); `combined_stacks` will be empty.

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
