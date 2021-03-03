from collections import defaultdict, OrderedDict
from typing import Dict, NewType, Set, Tuple, Type, TypeVar
from scalene.runningstats import RunningStats
from scalene import sparkline
from scalene.adaptive import Adaptive

Address = NewType("Address", str)
Filename = NewType("Filename", str)
# FunctionName = NewType("FunctionName", str)
LineNumber = NewType("LineNumber", int)
ByteCodeIndex = NewType("ByteCodeIndex", int)

class ScaleneStatistics:
    # Statistics counters:
    #

    # total time spent in program being profiled
    elapsed_time: float = 0

    #   CPU samples for each location in the program
    #   spent in the interpreter
    cpu_samples_python: Dict[Filename, Dict[LineNumber, float]] = defaultdict(
        lambda: defaultdict(float)
    )

    #   CPU samples for each location in the program
    #   spent in C / libraries / system calls
    cpu_samples_c: Dict[Filename, Dict[LineNumber, float]] = defaultdict(
        lambda: defaultdict(float)
    )

    # Running stats for the fraction of time running on the CPU.
    cpu_utilization: Dict[
        Filename, Dict[LineNumber, RunningStats]
    ] = defaultdict(lambda: defaultdict(RunningStats))

    # Running count of total CPU samples per file. Used to prune reporting.
    cpu_samples: Dict[Filename, float] = defaultdict(float)

    # Running count of malloc samples per file. Used to prune reporting.
    malloc_samples: Dict[Filename, float] = defaultdict(float)

    # malloc samples for each location in the program
    memory_malloc_samples: Dict[
        Filename, Dict[LineNumber, Dict[ByteCodeIndex, float]]
    ] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))

    # number of times samples were added for the above
    memory_malloc_count: Dict[
        Filename, Dict[LineNumber, Dict[ByteCodeIndex, int]]
    ] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

    # the last malloc to trigger a sample (used for leak detection)
    last_malloc_triggered: Tuple[Filename, LineNumber, Address] = (
        Filename(""),
        LineNumber(0),
        Address("0x0"),
    )

    # mallocs attributable to Python, for each location in the program
    memory_python_samples: Dict[
        Filename, Dict[LineNumber, Dict[ByteCodeIndex, float]]
    ] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))

    # free samples for each location in the program
    memory_free_samples: Dict[
        Filename, Dict[LineNumber, Dict[ByteCodeIndex, float]]
    ] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))

    # number of times samples were added for the above
    memory_free_count: Dict[
        Filename, Dict[LineNumber, Dict[ByteCodeIndex, int]]
    ] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

    # memcpy samples for each location in the program
    memcpy_samples: Dict[Filename, Dict[LineNumber, int]] = defaultdict(
        lambda: defaultdict(int)
    )

    # leak score tracking
    leak_score: Dict[
        Filename, Dict[LineNumber, Tuple[int, int]]
    ] = defaultdict(lambda: defaultdict(lambda: ((0, 0))))

    allocation_velocity: Tuple[float, float] = (0.0, 0.0)

    # how many CPU samples have been collected
    total_cpu_samples: float = 0.0

    # "   "    malloc "       "    "    "
    total_memory_malloc_samples: float = 0.0

    # "   "    free   "       "    "    "
    total_memory_free_samples: float = 0.0

    # the current memory footprint
    current_footprint: float = 0.0

    # the peak memory footprint
    max_footprint: float = 0.0

    # memory footprint samples (time, footprint), using 'Adaptive' sampling.
    memory_footprint_samples = Adaptive(27)

    # same, but per line
    per_line_footprint_samples: Dict[str, Dict[int, Adaptive]] = defaultdict(
        lambda: defaultdict(lambda: Adaptive(9))
    )

    # maps byte indices to line numbers (collected at runtime)
    # [filename][lineno] -> set(byteindex)
    bytei_map: Dict[
        Filename, Dict[LineNumber, Set[ByteCodeIndex]]
    ] = defaultdict(lambda: defaultdict(lambda: set()))

    # maps filenames and line numbers to functions (collected at runtime)
    # [filename][lineno] -> function name
    function_map: Dict[Filename, Dict[LineNumber, Filename]] = defaultdict(
        lambda: defaultdict(lambda: Filename(""))
    )

    @classmethod
    def clear(cls) -> None:
        cls.cpu_samples_python.clear()
        cls.cpu_samples_c.clear()
        cls.cpu_utilization.clear()
        cls.cpu_samples.clear()
        cls.malloc_samples.clear()
        cls.memory_malloc_samples.clear()
        cls.memory_python_samples.clear()
        cls.memory_free_samples.clear()
        cls.memory_free_count.clear()
        cls.total_cpu_samples = 0.0
        cls.total_memory_malloc_samples = 0.0
        cls.total_memory_free_samples = 0.0
        # Not clearing current footprint
        # Not clearing max footprint
        # FIXME: leak score, leak velocity

    def build_function_stats(self, fname: Filename) -> ScaleneStatistics:
        fn_stats = ScaleneStatistics()
        fn_stats.elapsed_time = self.elapsed_time
        fn_stats.total_cpu_samples = self.total_cpu_samples
        fn_stats.total_memory_malloc_samples = (
            self.total_memory_malloc_samples
        )
        first_line_no = LineNumber(1)
        for line_no in self.function_map[fname]:
            fn_name = self.function_map[fname][line_no]
            if fn_name == "<module>":
                continue
            fn_stats.cpu_samples_c[fn_name][
                first_line_no
            ] += self.cpu_samples_c[fname][line_no]
            fn_stats.cpu_samples_python[fn_name][
                first_line_no
            ] += self.cpu_samples_python[fname][line_no]
            fn_stats.per_line_footprint_samples[fn_name][
                first_line_no
            ] += self.per_line_footprint_samples[fname][line_no]
            for index in self.bytei_map[fname][line_no]:
                fn_stats.bytei_map[fn_name][first_line_no].add(
                    ByteCodeIndex(0)
                )
                fn_stats.memory_malloc_count[fn_name][first_line_no][
                    ByteCodeIndex(0)
                ] += self.memory_malloc_count[fname][line_no][index]
                fn_stats.memory_free_count[fn_name][first_line_no][
                    ByteCodeIndex(0)
                ] += self.memory_free_count[fname][line_no][index]
                fn_stats.memory_malloc_samples[fn_name][first_line_no][
                    ByteCodeIndex(0)
                ] += self.memory_malloc_samples[fname][line_no][index]
                fn_stats.memory_python_samples[fn_name][first_line_no][
                    ByteCodeIndex(0)
                ] += self.memory_python_samples[fname][line_no][index]
                fn_stats.memory_free_samples[fn_name][first_line_no][
                    ByteCodeIndex(0)
                ] += self.memory_free_samples[fname][line_no][index]
            fn_stats.memcpy_samples[fn_name][
                first_line_no
            ] += self.memcpy_samples[fname][line_no]
            fn_stats.leak_score[fn_name][first_line_no] = (
                fn_stats.leak_score[fn_name][first_line_no][0]
                + self.leak_score[fname][line_no][0],
                fn_stats.leak_score[fn_name][first_line_no][1]
                + self.leak_score[fname][line_no][1],
            )
        return fn_stats
        
