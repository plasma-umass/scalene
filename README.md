![scalene](https://github.com/emeryberger/scalene/raw/master/docs/scalene-image.png)

# scalene: a high-performance CPU and memory profiler for Python

by [Emery Berger](https://emeryberger.com)

------------

# About Scalene

Scalene is a high-performance CPU *and* memory profiler for Python that does a few things that other Python profilers do not and cannot do.  It runs orders of magnitude faster than other profilers while delivering far more detailed information.

1. Scalene is _fast_. It uses sampling instead of instrumentation or relying on Python's tracing facilities. Its overhead is typically no more than 10-20% (and often less).
1. Scalene is _precise_. Unlike most other Python profilers, Scalene performs CPU profiling _at the line level_, pointing to the specific lines of code that are responsible for the execution time in your program. This level of detail can be much more useful than the function-level profiles returned by most profilers.
1. Scalene separates out time spent running in Python from time spent in native code (including libraries).*
1. Scalene _profiles memory usage_. In addition to tracking CPU usage, Scalene also points to the specific lines of code responsible for memory growth. It accomplishes this via an included specialized memory allocator.

## Installation

Scalene is distributed as a `pip` package and works on Linux and Mac OS X platforms. You can install it as follows:
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
  % DYLD_INSERT_LIBRARIES=$PWD/libscalene.dylib PYTHONMALLOC=malloc python -m scalene test/testme.py
``` 

Profiling on a Linux system:
```
  % LD_PRELOAD=$PWD/libscalene.so PYTHONMALLOC=malloc python -m scalene test/testme.py
``` 
# Comparison to Other Profilers

## Performance and Features

Below is a table comparing various profilers to scalene, running on an example Python program (`benchmarks/julia1_nopil.py`) from the book _High Performance Python_, by Gorelick and Ozsvald. All of these were run on a 2016 MacBook Pro.

|                            | Time (seconds) | Slowdown | Line-level?    | CPU? | Python vs. C? | Memory? | Unmodified code? |
| :--- | ---: | ---: | :---: | :---: | :---: | :---: |
| _original program_ | 6.71s | **1.0x** | | | | | |
|               |     |        |                    | |
| `cProfile` | 11.04s | **1.65x** | function-level | :heavy_check_mark: |  |  | :heavy_check_mark: |
| `Profile` | 202.26s | **30.14x** | function-level | :heavy_check_mark: |  |  | :heavy_check_mark: |
| `pyinstrument` | 9.83s | **1.46x** | function-level | :heavy_check_mark: |  |  | :heavy_check_mark: |
| `line_profiler` | 78.0s | **11.62x** | :heavy_check_mark: | :heavy_check_mark: |  |  | needs `@profile` decorators |
| `yappi` _(CPU)_ | 127.53s | **19.01x** | function-level | :heavy_check_mark: |  |  | :heavy_check_mark: |
| `yappi` _(wallclock)_ | 21.45s | **3.2x** | function-level | :heavy_check_mark: |  |  | :heavy_check_mark: |
| `scalene` _(CPU only)_ | 6.98s | **1.04x** | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |  | :heavy_check_mark: |
| `scalene` _(CPU + memory)_ | 7.68s | **1.14x** | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: | :heavy_check_mark: |

## Output

Scalene prints annotated source code for the program being profiled and any modules it uses in the same directory or subdirectories. Here is a snippet from `pystone.py`, just using CPU profiling:

```
benchmarks/pystone.py: % of CPU time =  98.78% out of   3.47s.
         | CPU %    | CPU %    | 
  Line   | (Python) | (C)      | [benchmarks/pystone.py]
--------------------------------------------------------------------------------
  [... lines omitted ...]
   137   |   0.87%  |   0.13%  | def Proc1(PtrParIn):
   138   |   1.46%  |   0.36%  |     PtrParIn.PtrComp = NextRecord = PtrGlb.copy()
   139   |          |          |     PtrParIn.IntComp = 5
   140   |   0.87%  |   0.04%  |     NextRecord.IntComp = PtrParIn.IntComp
   141   |   1.46%  |   0.30%  |     NextRecord.PtrComp = PtrParIn.PtrComp
   142   |   2.33%  |   0.26%  |     NextRecord.PtrComp = Proc3(NextRecord.PtrComp)
   143   |   1.46%  |  -0.00%  |     if NextRecord.Discr == Ident1:
   144   |   0.29%  |   0.04%  |         NextRecord.IntComp = 6
   145   |   1.75%  |   0.40%  |         NextRecord.EnumComp = Proc6(PtrParIn.EnumComp)
   146   |   1.75%  |   0.29%  |         NextRecord.PtrComp = PtrGlb.PtrComp
   147   |   0.58%  |   0.12%  |         NextRecord.IntComp = Proc7(NextRecord.IntComp, 10)
   148   |          |          |     else:
   149   |          |          |         PtrParIn = NextRecord.copy()
   150   |   0.87%  |   0.15%  |     NextRecord.PtrComp = None
   151   |          |          |     return PtrParIn
```

And here is an example with memory profiling enabled, running the Julia benchmark.

```
benchmarks/julia1_nopil.py: % of CPU time =  99.22% out of  12.06s.
         | CPU %    | CPU %    | Memory (MB) |
  Line   | (Python) | (C)      |             | [benchmarks/julia1_nopil.py]
--------------------------------------------------------------------------------
     1   |          |          |             | # Pasted from Chapter 2, High Performance Python - O'Reilly Media;
     2   |          |          |             | # minor modifications for Python 3 by Emery Berger
     3   |          |          |             | 
     4   |          |          |             | """Julia set generator without optional PIL-based image drawing"""
     5   |          |          |             | import time
     6   |          |          |             | # area of complex space to investigate
     7   |          |          |             | x1, x2, y1, y2 = -1.8, 1.8, -1.8, 1.8
     8   |          |          |             | c_real, c_imag = -0.62772, -.42193
     9   |          |          |             | 
    10   |          |          |             | #@profile
    11   |          |          |             | def calculate_z_serial_purepython(maxiter, zs, cs):
    12   |          |          |             |     """Calculate output list using Julia update rule"""
    13   |   0.08%  |   0.02%  |      0.06   |     output = [0] * len(zs)
    14   |   0.25%  |   0.01%  |      9.50   |     for i in range(len(zs)):
    15   |          |          |             |         n = 0
    16   |   1.34%  |   0.05%  |     -9.88   |         z = zs[i]
    17   |   0.50%  |   0.01%  |     -8.44   |         c = cs[i]
    18   |   1.25%  |   0.04%  |             |         while abs(z) < 2 and n < maxiter:
    19   |  68.67%  |   2.27%  |     42.50   |             z = z * z + c
    20   |  18.46%  |   0.74%  |    -33.62   |             n += 1
    21   |          |          |             |         output[i] = n
    22   |          |          |             |     return output
```

Positive memory numbers indicate total memory allocation in megabytes;
negative memory numbers indicate memory reclamation. Note that because
of the way Python's memory management works, frequent allocation and
de-allocation (as in lines 19-20 above) show up as high positive
memory on one line followed by an (approximately) corresponding
negative memory on the following line(s).

# Acknowledgements

Logo created by [Sophia Berger](https://www.linkedin.com/in/sophia-berger/).
