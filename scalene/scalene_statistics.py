from collections import defaultdict, OrderedDict
from typing import Dict, NewType, Set, Tuple
from scalene.runningstats import RunningStats
from scalene import sparkline
from scalene.adaptive import Adaptive

Address = NewType("Address", str)
Filename = NewType("Filename", str)
FunctionName = NewType("FunctionName", str)
LineNumber = NewType("LineNumber", int)
ByteCodeIndex = NewType("ByteCodeIndex", int)


class ScaleneStatistics:
    # Statistics counters:
    #

    # total time spent in program being profiled
    __elapsed_time: float = 0

    #   CPU samples for each location in the program
    #   spent in the interpreter
    __cpu_samples_python: Dict[
        Filename, Dict[LineNumber, float]
    ] = defaultdict(lambda: defaultdict(float))

    #   CPU samples for each location in the program
    #   spent in C / libraries / system calls
    __cpu_samples_c: Dict[Filename, Dict[LineNumber, float]] = defaultdict(
        lambda: defaultdict(float)
    )

    # Running stats for the fraction of time running on the CPU.
    __cpu_utilization: Dict[
        Filename, Dict[LineNumber, RunningStats]
    ] = defaultdict(lambda: defaultdict(RunningStats))

    # Running count of total CPU samples per file. Used to prune reporting.
    __cpu_samples: Dict[Filename, float] = defaultdict(float)

    # Running count of malloc samples per file. Used to prune reporting.
    __malloc_samples: Dict[Filename, float] = defaultdict(float)

    # malloc samples for each location in the program
    __memory_malloc_samples: Dict[
        Filename, Dict[LineNumber, Dict[ByteCodeIndex, float]]
    ] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))

    # number of times samples were added for the above
    __memory_malloc_count: Dict[
        Filename, Dict[LineNumber, Dict[ByteCodeIndex, int]]
    ] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

    # the last malloc to trigger a sample (used for leak detection)
    __last_malloc_triggered: Tuple[Filename, LineNumber, Address] = (
        Filename(""),
        LineNumber(0),
        Address("0x0"),
    )

    # mallocs attributable to Python, for each location in the program
    __memory_python_samples: Dict[
        Filename, Dict[LineNumber, Dict[ByteCodeIndex, float]]
    ] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))

    # free samples for each location in the program
    __memory_free_samples: Dict[
        Filename, Dict[LineNumber, Dict[ByteCodeIndex, float]]
    ] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))

    # number of times samples were added for the above
    __memory_free_count: Dict[
        Filename, Dict[LineNumber, Dict[ByteCodeIndex, int]]
    ] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

    # memcpy samples for each location in the program
    __memcpy_samples: Dict[Filename, Dict[LineNumber, int]] = defaultdict(
        lambda: defaultdict(int)
    )

    # leak score tracking
    __leak_score: Dict[
        Filename, Dict[LineNumber, Tuple[int, int]]
    ] = defaultdict(lambda: defaultdict(lambda: ((0, 0))))

    __allocation_velocity: Tuple[float, float] = (0.0, 0.0)

    # how many CPU samples have been collected
    __total_cpu_samples: float = 0.0

    # "   "    malloc "       "    "    "
    __total_memory_malloc_samples: float = 0.0

    # "   "    free   "       "    "    "
    __total_memory_free_samples: float = 0.0

    # the current memory footprint
    __current_footprint: float = 0.0

    # the peak memory footprint
    __max_footprint: float = 0.0

    # memory footprint samples (time, footprint), using 'Adaptive' sampling.
    __memory_footprint_samples = Adaptive(27)

    # same, but per line
    __per_line_footprint_samples: Dict[str, Dict[int, Adaptive]] = defaultdict(
        lambda: defaultdict(lambda: Adaptive(9))
    )

    # maps byte indices to line numbers (collected at runtime)
    # [filename][lineno] -> set(byteindex)
    __bytei_map: Dict[
        Filename, Dict[LineNumber, Set[ByteCodeIndex]]
    ] = defaultdict(lambda: defaultdict(lambda: set()))

    # maps filenames and line numbers to functions (collected at runtime)
    # [filename][lineno] -> function name
    __function_map: Dict[
        Filename, Dict[LineNumber, FunctionName]
    ] = defaultdict(lambda: defaultdict(lambda: FunctionName("")))

    @classmethod
    def clear(cls) -> None:
        cls.__cpu_samples_python.clear()
        cls.__cpu_samples_c.clear()
        cls.__cpu_utilization.clear()
        cls.__cpu_samples.clear()
        cls.__malloc_samples.clear()
        cls.__memory_malloc_samples.clear()
        cls.__memory_python_samples.clear()
        cls.__memory_free_samples.clear()
        cls.__memory_free_count.clear()
        cls.__total_cpu_samples = 0.0
        cls.__total_memory_malloc_samples = 0.0
        cls.__total_memory_free_samples = 0.0
        # Not clearing current footprint
        # Not clearing max footprint
        # FIXME: leak score, leak velocity
