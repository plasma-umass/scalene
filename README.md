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

## Performance and Features

Below is a table comparing various profilers to scalene, running on an example Python program (`benchmarks/julia1_nopil.py`) from the book _High Performance Python_, by Gorelick and Ozsvald. All of these were run on a 2016 MacBook Pro. 

|                            | time (s) | slowdown | granularity    | cpu? | memory? | works on unmodified code?       |
| :--- | ---: | ---: | :---: | :---: | :---: | :---: |
| _original program_             | _7.76_     | _1.00x_     | |  |  |  |  |  |  |
|               |     |        |                    |
| `cProfile`                   | 11.17    | 1.44x     | function-level | yes  | no      | yes                |
| `Profile`                    | 278.19   | 35.86x    | function-level | yes  | no      | yes                |
| `yappi`                      | 143.78   | 18.53x    | function-level | yes  | no      | yes                |
| `line_profiler` | 93.27    | 12.02x    | line-level     | yes  | no      | no: needs `@profile` decorators |
| `memory_profiler`            | _aborted after 30 minutes_ | >232x   | line-level     | no   | yes     | no: needs `@profile` decorators |
| |  |  |  |  |  |  |
| **`scalene`** _(CPU only)_         | 8.31     | **1.07x**     | **line-level**     | **yes**  | **no**      | **yes**               |
| **`scalene`** _(CPU + memory)_     | 9.11     | **1.17x**     | **line-level**     | **yes**  | **yes**     | **yes**                |


## Output

Scalene prints annotated source code for the program being profiled and any modules it uses in the same directory or subdirectories. Here is a snippet from `pystone.py`, just using CPU profiling:

```
benchmarks/pystone.py: % of CPU time =  88.34% out of   3.46s.
  Line	 | CPU %    |            benchmarks/pystone.py
  [... lines omitted ...]
   137	 |   0.65%  | 	def Proc1(PtrParIn):
   138	 |   1.96%  | 	    PtrParIn.PtrComp = NextRecord = PtrGlb.copy()
   139	 |   0.65%  | 	    PtrParIn.IntComp = 5
   140	 |   2.61%  | 	    NextRecord.IntComp = PtrParIn.IntComp
   141	 |   0.98%  | 	    NextRecord.PtrComp = PtrParIn.PtrComp
   142	 |   2.94%  | 	    NextRecord.PtrComp = Proc3(NextRecord.PtrComp)
   143	 |   0.65%  | 	    if NextRecord.Discr == Ident1:
   144	 |   0.33%  | 	        NextRecord.IntComp = 6
   145	 |   3.27%  | 	        NextRecord.EnumComp = Proc6(PtrParIn.EnumComp)
   146	 |   0.33%  | 	        NextRecord.PtrComp = PtrGlb.PtrComp
   147	 |   2.29%  | 	        NextRecord.IntComp = Proc7(NextRecord.IntComp, 10)
   148	 |          | 	    else:
   149	 |          | 	        PtrParIn = NextRecord.copy()
   150	 |   0.33%  | 	    NextRecord.PtrComp = None
   151	 |          | 	    return PtrParIn
 ```

And here is an example with memory profiling enabled, running the Julia benchmark.

```
benchmarks/julia1_nopil.py: % of CPU time =  96.23% out of   9.03s.
  Line	 | CPU %    | Memory (MB)| benchmarks/julia1_nopil.py
     1	 |          |         	 | 	# Pasted from Chapter 2, High Performance Python - O'Reilly Media;
     2	 |          |         	 | 	# minor modifications for Python 3 by Emery Berger
     3	 |          |         	 | 	
     4	 |          |         	 | 	"""Julia set generator without optional PIL-based image drawing"""
     5	 |          |         	 | 	import time
     6	 |          |         	 | 	# area of complex space to investigate
     7	 |          |         	 | 	x1, x2, y1, y2 = -1.8, 1.8, -1.8, 1.8
     8	 |          |         	 | 	c_real, c_imag = -0.62772, -.42193
     9	 |          |         	 | 	
    10	 |          |         	 | 	#@profile
    11	 |          |      0.12	 | 	def calculate_z_serial_purepython(maxiter, zs, cs):
    12	 |          |         	 | 	    """Calculate output list using Julia update rule"""
    13	 |          |      0.12	 | 	    output = [0] * len(zs)
    14	 |   0.35%  |     25.00	 | 	    for i in range(len(zs)):
    15	 |          |         	 | 	        n = 0
    16	 |   0.23%  |    -24.75	 | 	        z = zs[i]
    17	 |   0.46%  |    -27.75	 | 	        c = cs[i]
    18	 |  17.84%  |         	 | 	        while abs(z) < 2 and n < maxiter:
    19	 |  50.86%  |    998.12	 | 	            z = z * z + c
    20	 |  23.01%  |   -968.00	 | 	            n += 1
    21	 |   0.23%  |         	 | 	        output[i] = n
    22	 |          |         	 | 	    return output
```

Positive memory numbers indicate memory consumption in megabytes;
negative memory numbers indicate memory reclamation. Note that because
of the way Python's memory management works, frequent allocation and
de-allocation (as in lines 19-20 above) show up as high positive
memory on one line followed by an (approximately) corresponding
negative memory on the following line(s).