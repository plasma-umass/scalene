![scalene](https://github.com/emeryberger/scalene/raw/master/docs/scalene-image.png)

# scalene: a high-performance CPU and memory profiler for Python

by [Emery Berger](https://emeryberger.com)

![downloads per month](https://img.shields.io/pypi/dm/scalene)![Python versions](https://img.shields.io/pypi/pyversions/scalene.svg?style=flat-square)![License](https://img.shields.io/github/license/emeryberger/scalene)

------------
[中文版本 (Chinese version)](docs/README_CN.md)

# About Scalene

Scalene is a high-performance CPU *and* memory profiler for Python that does a number of things that other Python profilers do not and cannot do.  It runs orders of magnitude faster than other profilers while delivering far more detailed information.

1. Scalene is _fast_. It uses sampling instead of instrumentation or relying on Python's tracing facilities. Its overhead is typically no more than 10-20% (and often less).
1. Scalene is _precise_. Unlike most other Python profilers, Scalene performs CPU profiling _at the line level_, pointing to the specific lines of code that are responsible for the execution time in your program. This level of detail can be much more useful than the function-level profiles returned by most profilers.
1. Scalene separates out time spent running in Python from time spent in native code (including libraries). Most Python programmers aren't going to optimize the performance of native code (which is usually either in the Python implementation or external libraries), so this helps developers focus their optimization efforts on the code they can actually improve.
1. Scalene _profiles memory usage_. In addition to tracking CPU usage, Scalene also points to the specific lines of code responsible for memory growth. It accomplishes this via an included specialized memory allocator.
1. Scalene produces _per-line_ memory profiles, making it easier to track down leaks.
1. Scalene profiles _copying volume_, making it easy to spot inadvertent copying, especially due to crossing Python/library boundaries (e.g., accidentally converting `numpy` arrays into Python arrays, and vice versa).
1. **NEW!** Scalene now reports the percentage of memory consumed by Python code vs. native code.
1. **NEW!** Scalene now highlights hotspots (code accounting for significant percentages of CPU time or memory allocation) in red, making them even easier to spot.

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


## Using `scalene`

The following command runs Scalene on a provided example program.

```
  % scalene test/testme.py
```

To see all the options, run with `--help`.

    % scalene --help
    usage: scalene [-h] [--outfile OUTFILE] [--html]
                   [--profile-interval PROFILE_INTERVAL] [--wallclock]
                   [--cpu-only] [--profile-all]
                   [--cpu-percent-threshold CPU_PERCENT_THRESHOLD]
    
    Scalene: a high-precision CPU and memory profiler.
            https://github.com/emeryberger/scalene
            % scalene yourprogram.py
    
    optional arguments:
      -h, --help            show this help message and exit
      --outfile OUTFILE     file to hold profiler output (default: stdout)
      --html                output as HTML (default: text)
      --profile-interval PROFILE_INTERVAL
                            output profiles every so many seconds.
      --wallclock           use wall clock time (default: virtual time)
      --cpu-only            only profile CPU time (default: profile CPU, memory, and copying)
      --profile-all         profile all executed code, not just the target program (default: only the target program)
      --cpu-percent-threshold CPU_PERCENT_THRESHOLD
                            only report profiles with at least this percent of CPU time (default: 1%)


# Comparison to Other Profilers

## Performance and Features

Below is a table comparing the **performance and features** of various profilers to Scalene.

![Performance and feature comparison](https://github.com/emeryberger/scalene/blob/master/images/profiler-comparison.png)

- _Function-granularity_ reports information only for an entire function, while _line-granularity_ reports information for every line
- **Time** is either real (wall-clock time), CPU-only, or both.
- **Efficiency**: :green_circle: = fast, :yellow_circle: = slower, :red_circle: = slowest
- **Mem Cons.**: tracks memory consumption
- **Unmodified Code**: works on unmodified code
- **Threads**: works correctly with threads
- **Python/C**: separately attributes Python/C time and memory consumption
- **Mem Trend**: shows memory usage trends over time
- **Copy Vol.**: reports _copy volume_, the amount of megabytes being copied per second

## Output

Scalene prints annotated source code for the program being profiled and any modules it uses in the same directory or subdirectories. Here is a snippet from `pystone.py`, just using CPU profiling:

```
    benchmarks/pystone.py: % of CPU time = 100.00% out of   3.66s.
          	 |     CPU % |     CPU % |   
      Line	 |  (Python) |  (native) |  [benchmarks/pystone.py]
    --------------------------------------------------------------------------------
    [... lines omitted ...]
       137	 |     0.27% |     0.14% | def Proc1(PtrParIn):
       138	 |     1.37% |     0.11% |     PtrParIn.PtrComp = NextRecord = PtrGlb.copy()
       139	 |     0.27% |     0.22% |     PtrParIn.IntComp = 5
       140	 |     1.37% |     0.77% |     NextRecord.IntComp = PtrParIn.IntComp
       141	 |     2.47% |     0.93% |     NextRecord.PtrComp = PtrParIn.PtrComp
       142	 |     1.92% |     0.78% |     NextRecord.PtrComp = Proc3(NextRecord.PtrComp)
       143	 |     0.27% |     0.17% |     if NextRecord.Discr == Ident1:
       144	 |     0.82% |     0.30% |         NextRecord.IntComp = 6
       145	 |     2.19% |     0.79% |         NextRecord.EnumComp = Proc6(PtrParIn.EnumComp)
       146	 |     1.10% |     0.39% |         NextRecord.PtrComp = PtrGlb.PtrComp
       147	 |     0.82% |     0.06% |         NextRecord.IntComp = Proc7(NextRecord.IntComp, 10)
       148	 |           |           |     else:
       149	 |           |           |         PtrParIn = NextRecord.copy()
       150	 |     0.82% |     0.32% |     NextRecord.PtrComp = None
       151	 |           |           |     return PtrParIn
```

And here is an example with memory profiling enabled.
The "sparklines" summarize memory consumption over time (at the top, for the whole program).

```
    Memory usage: ▂▂▁▁▁▁▁▁▁▁▁▅█▅ (max: 1617.98MB)
    phylliade/test2-2.py: % of CPU time =  40.68% out of   4.60s.
           |    CPU % |    CPU % |  Net  | Memory usage   | Copy  |
      Line | (Python) | (native) |  (MB) | over time /  % | (MB/s)| [phylliade/test2-2.py]
    --------------------------------------------------------------------------------
         1 |          |          |       |                |       | import numpy as np
         2 |          |          |       |                |       | 
         3 |          |          |       |                |       | @profile
         4 |          |          |       |                |       | def main():
         5 |          |          |    92 | ▁▁▁▁▁▁▁▁▁  11% |       |     x = np.array(range(10**7))
         6 |    0.43% |   40.24% |   762 | ▁▁▄█▄      89% |   168 |     y = np.array(np.random.uniform(0, 100, size=(10**8)))
         7 |          |          |       |                |       | 
         8 |          |          |       |                |       | main()
```

Positive net memory numbers indicate total memory allocation in megabytes;
negative net memory numbers indicate memory reclamation.

The memory usage sparkline and copy volume make it easy to spot
unnecessary copying in line 6.

# Technical Information

For technical details on Scalene, please see the following paper: [Scalene: Scripting-Language Aware Profiling for Python](https://arxiv.org/abs/2006.03879).

# Success Stories

If you use Scalene to successfully debug a performance problem, please [add a comment to this issue](https://github.com/emeryberger/scalene/issues/58)!

# Acknowledgements

Logo created by [Sophia Berger](https://www.linkedin.com/in/sophia-berger/).
