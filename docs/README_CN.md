![scalene](https://github.com/emeryberger/scalene/raw/master/docs/scalene-image.png)

# Scalene: 一个 Python 的高性能 CPU，GPU 和 内存分析器

by [Emery Berger](https://emeryberger.com)

------------

# 关于 Scalene

Scalene 是一个 Python 的高性能 CPU，GPU *和* 内存分析器，它可以做到很多其他Python分析器不能做到的事情。它在能提供更多详细信息的同时，比其他的分析器要快几个数量级。

1. Scalene 是 _很快的_。 它使用采样的方式而不是直接测量或者依靠Python的追踪工具。它的开销一般不超过10-20% (通常更少)。
1. Scalene 是 _精确的_。和大部分其他的Python分析器不同，Scalene 在 _行级别_ 下执行CPU分析，在你的程序中指出对应代码行的执行时间。和大多数分析器所返回的功能级分析结果相比，这种程度的细节可能会更有用。
1. Scalane 可以区分在Python中运行的时间和在native代码(包括库)中花费的时间。大多数的Python程序员并不会去优化native代码(通常在Python实现中或者所依赖的外部库)，所以区分这两种运行时间，有助于开发者能够将优化的工作专注于他们能够实际改善的代码上。
1. Scalene 可以 _分析内存使用情况_。除了追踪CPU使用情况，Scalene还指出对应代码行的内存增长。这是通过指定内存分配器来实现的。
1. **NEW!** Scalene 会生成 _每行_ 的内存分析，以此更容易的追踪内存泄露。
1. **NEW!** Scalene 会分析 _内存拷贝量_, 从而易于发现意外的内存拷贝。特别是因为跨越Python和底层库的边界导致的意外 (例如：意外的把 `numpy` 数组转化成了Python数组，反之亦然)。

## 安装

Scalene 通过 pip 包的形式进行分发，可以运行在Mac OS X和Linux平台(包括在[Windows WSL2](docs.microsoft.com/en-us/windows/wsl/wsl2-index)中运行的Ubuntu)。 

你可以通过下面的方式安装：
```
  % pip install scalene
```

或者
```
  % python -m pip install scalene
```

_注意_: 现在这样安装Scalene，是不会安装内存分析的库，所以你只能用它来执行CPU的分析。如果要使用它的内存分析能力，你需要下载这个代码仓库。

**NEW**: 你现在可以通过以下命令，在 Mac OS X 上使用 brew 安装内存分析的部分：

```
  % brew tap emeryberger/scalene
  % brew install --head libscalene
```

这将会安装一个你可以使用的 `scalene` 脚本（下面会提到）。

# 使用

下面的命令会让 Scalene 在提供的示例程序上执行 行级别的CPU分析。

```
  % scalene test/testme.py
```

如果你使用Homebrew安装 Scalene 库，你只需要执行 `scalene` 就可以执行行级别的CPU和内存分析：

```
  % scalene test/testme.py
```

否则，你需要运行 `make` 来先构建一个指定的内存分配器：

```
  % make
```

在 Mac OS X 系统上进行分析(不使用Homebrew安装)：
```
  % DYLD_INSERT_LIBRARIES=$PWD/libscalene.dylib PYTHONMALLOC=malloc scalene test/testme.py
``` 

在Linux系统上分析：
```
  % LD_PRELOAD=$PWD/libscalene.so PYTHONMALLOC=malloc scalene test/testme.py
``` 

执行时增加 `--help` 来查看全部配置：

    % scalene --help
    usage: scalene [-h] [-o OUTFILE] [--profile-interval PROFILE_INTERVAL]
                   [--wallclock]
                   prog
    
    Scalene: a high-precision CPU and memory profiler.
                https://github.com/emeryberger/Scalene
    
                    for CPU profiling only:
                % scalene yourprogram.py
                    for CPU and memory profiling (Mac OS X):
                % DYLD_INSERT_LIBRARIES=$PWD/libscalene.dylib PYTHONMALLOC=malloc scalene yourprogram.py
                    for CPU and memory profiling (Linux):
                % LD_PRELOAD=$PWD/libscalene.so PYTHONMALLOC=malloc scalene yourprogram.py
    
    positional arguments:
      prog                  program to be profiled
    
    optional arguments:
      -h, --help            show this help message and exit
      -o OUTFILE, --outfile OUTFILE
                            file to hold profiler output (default: stdout)
      --profile-interval PROFILE_INTERVAL
                            output profiles every so many seconds.
      --wallclock           use wall clock time (default: virtual time)

# 对比其他分析器

## 性能和功能

下面的表格把 scalene 和不同分析器的**性能**做了比较。运行的示例程序  (`benchmarks/julia1_nopil.py`) 来自于 Gorelick 和 Ozsvald 的 _《高性能Python编程》_。所有的这些结果都是在 2016款 MacBook Pro上运行的。


| Profiler                           | Time | Slowdown |
| :--- | ---: | ---: |
| _original program_ | 6.71s | 1.0x |
|                    |     |        |
| `cProfile`      | 11.04s  | 1.65x  |
| `Profile`       | 202.26s | 30.14x |
| `pyinstrument`  | 9.83s   | 1.46x  |
| `line_profiler` | 78.0s   | 11.62x |
| `pprofile` _(deterministic)_ | 403.67s | 60.16x |
| `pprofile` _(statistical)_ | 7.47s | 1.11x |
| `yappi` _(CPU)_ | 127.53s | 19.01x |
| `yappi` _(wallclock)_ | 21.45s | 3.2x |
| `py-spy` | 7.25s | 1.08x |
| `memory_profiler`     | _> 2 hours_ | **>1000x**|
|               |     |        |                    | |  | |
| `scalene` _(CPU only)_     | 6.98s | **1.04x** |
| `scalene` _(CPU + memory)_ | 7.68s | **1.14x** |

这个表格是其他分析器 vs. Scalene 的**功能**比较。

| Profiler | Line-level?    | CPU? | Wall clock vs. CPU time? | Python vs. native? | Memory? | Unmodified code? | Threads? |
| ---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `cProfile`                   |   | ✔ | wall clock  |   |   | ✔ |   |
| `Profile`                    |   | ✔ | CPU time    |   |   | ✔ |   |
| `pyinstrument`               |   | ✔ | wall clock  |   |   | ✔ |   |
| `line_profiler`              | ✔ | ✔ | wall clock  |   |   |   |   |
| `pprofile` _(deterministic)_ | ✔ | ✔ | wall clock  |   |   | ✔ | ✔ | 
| `pprofile` _(statistical)_   | ✔ | ✔ | wall clock  |   |   | ✔ | ✔ |
| `yappi` _(CPU)_              |   | ✔ | CPU time    |   |   | ✔ | ✔ |
| `yappi` _(wallclock)_        |   | ✔ | wall clock  |   |   | ✔ | ✔ |
| `py-spy`                     | ✔ | ✔ | **both**    |   |   | ✔ | ✔ |
| `memory_profiler`            | ✔ |   |             |   | ✔ |   |   |
|                              |   |   |             |   |   |   |   |
| `scalene` _(CPU only)_       | ✔ | ✔ | **both**    | ✔ |   | ✔ | ✔ |
| `scalene` _(CPU + memory)_   | ✔ | ✔ | **both**    | ✔ | ✔ | ✔ | ✔ |


## 输出

Scalene 打印被分析程序中带注释的源代码，以及程序在同目录和子目录使用到的任何模块。下面是一个来自 pystone.py `pystone.py` 的片段，只使用了CPU分析：

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

下面是一个启用了内存分析的示例，运行的是Julia的基准测试。第一行是一个“sparkline”，总结了一段时间内的内存消耗。

```
    Memory usage: ▁▁▄▇█▇▇▇█▇█▇█▇█▇█▇▇▇▇█▇▇█▇█▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇█ (max: 105.73MB)
    benchmarks/julia1_nopil.py: % of CPU time = 100.00% out of   9.11s.
          	 |     CPU % |     CPU % | Avg memory  | Memory      | 
      Line	 |  (Python) |  (native) | growth (MB) | usage (%)   | [benchmarks/julia1_nopil.py]
    --------------------------------------------------------------------------------
         1	 |           |           |             |             | import sys
    [... lines omitted ...]
        30	 |           |           |             |             | def calculate_z_serial_purepython(maxiter, zs, cs):
        31	 |           |           |             |             |     """Calculate output list using Julia update rule"""
        32	 |           |           |          18 |       0.74% |     output = [0] * len(zs)
        33	 |     0.44% |     0.06% |          16 |       1.32% |     for i in range(len(zs)):
        34	 |           |           |             |             |         n = 0
        35	 |     0.22% |     0.04% |         -16 |             |         z = zs[i]
        36	 |     0.22% |     0.07% |             |             |         c = cs[i]
        37	 |    26.12% |     5.57% |             |             |         while abs(z) < 2 and n < maxiter:
        38	 |    36.04% |     7.74% |          16 |      85.09% |             z = z * z + c
        39	 |    12.01% |     2.70% |         -16 |       3.96% |             n += 1
        40	 |     0.33% |     0.10% |             |             |         output[i] = n
        41	 |           |           |             |             |     return output
        42	 |           |           |             |             | 
```

正的内存数代表内存的分配量(以MB为单位)，负的内存数代表内存的回收量。
内存的使用率代表特定行中总内存分配的活动。

# 致谢

Logo由 [Sophia Berger](https://www.linkedin.com/in/sophia-berger/) 创作。
