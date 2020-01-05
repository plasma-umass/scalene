![scalene](https://github.com/emeryberger/scalene/raw/master/docs/scalene-image.png)

# scalene: a high-performance CPU and memory profiler for Python

by [Emery Berger](https://emeryberger.com)

------------

# About Scalene

Scalene is a high-performance CPU *and* memory profiler for Python that does a few things that other Python profilers do not and cannot do.  It runs orders of magnitude faster than other profilers while delivering far more detailed information.

1. Scalene is _fast_. It uses sampling instead of instrumentation or relying on Python's tracing facilities. Its overhead is typically no more than 10-20% (and often less).
1. Scalene is _precise_. Unlike most other Python profilers, Scalene performs CPU profiling _at the line level_, pointing to the specific lines of code that are responsible for the execution time in your program. This level of detail can be much more useful information than the function-level profiles returned by most profilers.
1. Scalene _profiles memory usage_. In addition to tracking CPU usage, Scalene also points to the specific lines of code responsible for memory growth. It accomplishes this via an included specialized memory allocator.

## Installation

Scalene is distributed as a `pip` package. You can install it as follows:
```
  % pip install scalene
```

_NOTE_: Currently, installing Scalene in this way does not install its memory profiling library, so you will only be able to use it to perform CPU profiling. To take advantage of its memory profiling capability, you will need to download this repository.

# Usage

The following command will run Scalene to only perform line-level CPU profiling on a provided example program.

```
  % python -m scalene test/testme.py
```

To perform both line-level CPU and memory profiling, you first need to build the specialized memory allocator by running `make`:

```
  % make
```

Profiling on a Mac OS X system:
```
  % DYLD_INSERT_LIBRARIES=$PWD/libcheaper.dylib PYTHONMALLOC=malloc python -m scalene test/testme.py
``` 

Profiling on a Linux system:
```
  % LD_PRELOAD=$PWD/libcheaper.so PYTHONMALLOC=malloc python -m scalene test/testme.py
``` 
# Comparison to Other Profilers

Below is a table comparing various profilers to `scalene`, running on an example Python program (`benchmarks/julia1_nopil.py`) from the book _High Performance Python_, by Gorelick and Ozsvald. All of these were run on a 2016 MacBook Pro. 

|                            | time (s) | slowdown | granularity    | cpu? | memory? | works on unmodified code?       |
| :--- | ---: | ---: | :---: | :---: | :---: | :---: |
|----------------------------|----------|----------|----------------|------|---------|---------------------|
| _original program_             | _7.76_     | _1.00_     |               |     |        |                    |
| `cProfile`                   | 11.17    | 1.44     | function-level | yes  | no      | yes                |
| `Profile`                    | 278.19   | 35.86    | function-level | yes  | no      | yes                |
| `yappi`                      | 143.78   | 18.53    | function-level | yes  | no      | yes                |
| `line_profiler` | 93.27    | 12.02    | line-level     | yes  | no      | no: needs `@profile` decorators |
| `memory_profiler`            | _aborted after 30 minutes_ | 232.02   | line-level     | no   | yes     | no: needs `@profile` decorators |
| **`scalene`** _(CPU only)_         | 8.31     | **1.07**     | **line-level**     | **yes**  | **no**      | **yes**               |
| **`scalene`** _(CPU + memory)_     | 9.11     | **1.17**     | **line-level**     | **yes**  | **yes**     | **yes**                |

