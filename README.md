![scalene](https://github.com/emeryberger/scalene/raw/master/docs/scalene-image.png)

# scalene: a high-performance CPU and memory profiler for Python

by [Emery Berger](https://emeryberger.com)

![downloads per month](https://img.shields.io/pypi/dm/scalene) ![Python versions](https://img.shields.io/pypi/pyversions/scalene.svg?style=flat-square) ![License](https://img.shields.io/github/license/emeryberger/scalene)

------------
[中文版本 (Chinese version)](docs/README_CN.md)

# About Scalene

```
  % pip install -U scalene
```

Scalene is a high-performance CPU *and* memory profiler for Python that does a number of things that other Python profilers do not and cannot do.  It runs orders of magnitude faster than other profilers while delivering far more detailed information.

1. Scalene is _fast_. It uses sampling instead of instrumentation or relying on Python's tracing facilities. Its overhead is typically no more than 10-20% (and often less).
1. Scalene is _precise_. Unlike most other Python profilers, Scalene performs CPU profiling _at the line level_, pointing to the specific lines of code that are responsible for the execution time in your program. This level of detail can be much more useful than the function-level profiles returned by most profilers.
1. Scalene separates out time spent running in Python from time spent in native code (including libraries). Most Python programmers aren't going to optimize the performance of native code (which is usually either in the Python implementation or external libraries), so this helps developers focus their optimization efforts on the code they can actually improve.
1. Scalene _profiles memory usage_. In addition to tracking CPU usage, Scalene also points to the specific lines of code responsible for memory growth. It accomplishes this via an included specialized memory allocator.
1. Scalene produces _per-line_ memory profiles, making it easier to track down leaks.
1. Scalene profiles _copying volume_, making it easy to spot inadvertent copying, especially due to crossing Python/library boundaries (e.g., accidentally converting `numpy` arrays into Python arrays, and vice versa).
1. **NEW!** Scalene now reports the percentage of memory consumed by Python code vs. native code.
1. **NEW!** Scalene now highlights hotspots (code accounting for significant percentages of CPU time or memory allocation) in red, making them even easier to spot.
1. **NEW!** Scalene can produce reduced profiles (via `--reduced-profile`) that only report lines that consume more than 1% of CPU or perform at least 100 allocations.
1. **NEW!** Scalene now also supports `@profile` decorators to profile only specific functions.

# Comparison to Other Profilers

## Performance and Features

Below is a table comparing the **performance and features** of various profilers to Scalene.

![Performance and feature comparison](https://github.com/emeryberger/scalene/blob/master/images/profiler-comparison.png)

**Function-granularity profilers** report information only for an entire function, while **line-granularity profilers** (like Scalene) report information for every line

- **Time** is either real (wall-clock time), CPU-only, or both.
- **Efficiency**: :green_circle: = fast, :yellow_circle: = slower, :red_circle: = slowest
- **Mem Cons.**: tracks memory consumption
- **Unmodified Code**: works on unmodified code
- **Threads**: works correctly with threads
- **Python/C**: separately attributes Python/C time and memory consumption
- **Mem Trend**: shows memory usage trends over time
- **Copy Vol.**: reports _copy volume_, the amount of megabytes being copied per second

## Output

Scalene prints annotated source code for the program being profiled
(either as text or as HTML via the `--html` option) and any modules it
uses in the same directory or subdirectories (you can optionally have
it `--profile-all` and only include files with at least a
`--cpu-percent-threshold` of time).  Here is a snippet from
`pystone.py`. The "sparklines" summarize memory consumption over time (at the top, for the whole program).

![Example profile](https://github.com/emeryberger/scalene/blob/master/images/sample-profile-pystone.png)

Positive net memory numbers indicate total memory allocation in megabytes;
negative net memory numbers indicate memory reclamation.


## Using `scalene`

The following command runs Scalene on a provided example program.

```
  % scalene test/testme.py
```

To see all the options, run with `--help`.

    % scalene --help
    usage: scalene [-h] [--outfile OUTFILE] [--html] [--reduced-profile]
                   [--profile-interval PROFILE_INTERVAL] [--cpu-only]
                   [--profile-all] [--use-virtual-time]
                   [--cpu-percent-threshold CPU_PERCENT_THRESHOLD]
                   [--cpu-sampling-rate CPU_SAMPLING_RATE]
                   [--malloc-threshold MALLOC_THRESHOLD]
    
    Scalene: a high-precision CPU and memory profiler.
            https://github.com/emeryberger/scalene
            % scalene yourprogram.py
    
    optional arguments:
      -h, --help            show this help message and exit
      --outfile OUTFILE     file to hold profiler output (default: stdout)
      --html                output as HTML (default: text)
      --reduced-profile     generate a reduced profile, with non-zero lines only (default: False).
      --profile-interval PROFILE_INTERVAL
                            output profiles every so many seconds.
      --cpu-only            only profile CPU time (default: profile CPU, memory, and copying)
      --profile-all         profile all executed code, not just the target program (default: only the target program)
      --use-virtual-time    measure only CPU time, not time spent in I/O or blocking (default: False)
      --cpu-percent-threshold CPU_PERCENT_THRESHOLD
                            only report profiles with at least this percent of CPU time (default: 1%)
      --cpu-sampling-rate CPU_SAMPLING_RATE
                            CPU sampling rate (default: every 0.01s)
      --malloc-threshold MALLOC_THRESHOLD
                            only report profiles with at least this many allocations (default: 100)


## Installation

### pip (Mac OS X, Linux, and Windows WSL2)

Scalene is distributed as a `pip` package and works on Mac OS X and Linux platforms (including Ubuntu in [Windows WSL2](docs.microsoft.com/en-us/windows/wsl/wsl2-index)).

You can install it as follows:
```
  % pip install -U scalene
```

or
```
  % python3 -m pip install -U scalene
```

### Homebrew (Mac OS X)

As an alternative to `pip`, you can use Homebrew to install the current version of Scalene from this repository:

```
  % brew tap emeryberger/scalene
  % brew install --head libscalene
```

### ArchLinux

**NEW**: You can also install Scalene on Arch Linux via the [AUR
package](https://aur.archlinux.org/packages/python-scalene-git/). Use your favorite AUR helper, or
manually download the `PKGBUILD` and run `makepkg -cirs` to build. Note that this will place
`libscalene.so` in `/usr/lib`; modify the below usage instructions accordingly.


# Technical Information

For technical details on Scalene, please see the following paper: [Scalene: Scripting-Language Aware Profiling for Python](https://github.com/emeryberger/scalene/raw/master/scalene-paper.pdf) ([arXiv link](https://arxiv.org/abs/2006.03879)).

# Success Stories

If you use Scalene to successfully debug a performance problem, please [add a comment to this issue](https://github.com/emeryberger/scalene/issues/58)!

# Acknowledgements

Logo created by [Sophia Berger](https://www.linkedin.com/in/sophia-berger/).
