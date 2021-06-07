import cloudpickle
import os
import pathlib
import pickle
import time

from collections import defaultdict
from typing import (
    Any,
    Dict,
    Generic,
    List,
    NewType,
    Set,
    Tuple,
    TypeVar,
    Union,
)
from scalene.runningstats import RunningStats
from scalene.adaptive import Adaptive

Address = NewType("Address", str)
Filename = NewType("Filename", str)
# FunctionName = NewType("FunctionName", str)
LineNumber = NewType("LineNumber", int)
ByteCodeIndex = NewType("ByteCodeIndex", int)
T = TypeVar("T")


class ScaleneStatistics:
    # Statistics counters:
    #
    def __init__(self) -> None:
        # time the profiling started
        self.start_time: float = None

        # total time spent in program being profiled
        self.elapsed_time: float = 0

        #   CPU samples for each location in the program
        #   spent in the interpreter
        self.cpu_samples_python: Dict[
            Filename, Dict[LineNumber, float]
        ] = defaultdict(lambda: defaultdict(float))

        #   CPU samples for each location in the program
        #   spent in C / libraries / system calls
        self.cpu_samples_c: Dict[
            Filename, Dict[LineNumber, float]
        ] = defaultdict(lambda: defaultdict(float))

        #   GPU samples for each location in the program
        self.gpu_samples: Dict[
            Filename, Dict[LineNumber, float]
        ] = defaultdict(lambda: defaultdict(float))

        # Running stats for the fraction of time running on the CPU.
        self.cpu_utilization: Dict[
            Filename, Dict[LineNumber, RunningStats]
        ] = defaultdict(lambda: defaultdict(RunningStats))

        # Running count of total CPU samples per file. Used to prune reporting.
        self.cpu_samples: Dict[Filename, float] = defaultdict(float)

        # Running count of malloc samples per file. Used to prune reporting.
        self.malloc_samples: Dict[Filename, float] = defaultdict(float)

        # malloc samples for each location in the program
        self.memory_malloc_samples: Dict[
            Filename, Dict[LineNumber, Dict[ByteCodeIndex, float]]
        ] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))

        # number of times samples were added for the above
        self.memory_malloc_count: Dict[
            Filename, Dict[LineNumber, Dict[ByteCodeIndex, int]]
        ] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

        # the last malloc to trigger a sample (used for leak detection)
        self.last_malloc_triggered: Tuple[Filename, LineNumber, Address] = (
            Filename(""),
            LineNumber(0),
            Address("0x0"),
        )

        # mallocs attributable to Python, for each location in the program
        self.memory_python_samples: Dict[
            Filename, Dict[LineNumber, Dict[ByteCodeIndex, float]]
        ] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))

        # free samples for each location in the program
        self.memory_free_samples: Dict[
            Filename, Dict[LineNumber, Dict[ByteCodeIndex, float]]
        ] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))

        # number of times samples were added for the above
        self.memory_free_count: Dict[
            Filename, Dict[LineNumber, Dict[ByteCodeIndex, int]]
        ] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

        # memcpy samples for each location in the program
        self.memcpy_samples: Dict[
            Filename, Dict[LineNumber, int]
        ] = defaultdict(lambda: defaultdict(int))

        # leak score tracking
        self.leak_score: Dict[
            Filename, Dict[LineNumber, Tuple[int, int]]
        ] = defaultdict(lambda: defaultdict(lambda: ((0, 0))))

        self.allocation_velocity: Tuple[float, float] = (0.0, 0.0)

        # how many CPU samples have been collected
        self.total_cpu_samples: float = 0.0

        # how many GPU samples have been collected
        self.total_gpu_samples: float = 0.0

        # "   "    malloc "       "    "    "
        self.total_memory_malloc_samples: float = 0.0

        # "   "    free   "       "    "    "
        self.total_memory_free_samples: float = 0.0

        # the current memory footprint
        self.current_footprint: float = 0.0

        # the peak memory footprint
        self.max_footprint: float = 0.0

        # memory footprint samples (time, footprint), using 'Adaptive' sampling.
        self.memory_footprint_samples = Adaptive(27)

        # same, but per line
        self.per_line_footprint_samples: Dict[
            Filename, Dict[LineNumber, Adaptive]
        ] = defaultdict(lambda: defaultdict(lambda: Adaptive(9)))

        # maps byte indices to line numbers (collected at runtime)
        # [filename][lineno] -> set(byteindex)
        self.bytei_map: Dict[
            Filename, Dict[LineNumber, Set[ByteCodeIndex]]
        ] = defaultdict(lambda: defaultdict(lambda: set()))

        # maps filenames and line numbers to functions (collected at runtime)
        # [filename][lineno] -> function name
        self.function_map: Dict[
            Filename, Dict[LineNumber, Filename]
        ] = defaultdict(lambda: defaultdict(lambda: Filename("")))
        self.firstline_map: Dict[Filename, LineNumber] = defaultdict(
            lambda: LineNumber(1)
        )

    def clear(self) -> None:
        self.start_time = 0
        self.elapsed_time = 0
        self.cpu_samples_python.clear()
        self.cpu_samples_c.clear()
        self.cpu_utilization.clear()
        self.cpu_samples.clear()
        self.gpu_samples.clear()
        self.malloc_samples.clear()
        self.memory_malloc_samples.clear()
        self.memory_malloc_count.clear()
        self.memory_python_samples.clear()
        self.memory_free_samples.clear()
        self.memory_free_count.clear()
        self.memcpy_samples.clear()
        self.total_cpu_samples = 0.0
        self.total_gpu_samples = 0.0
        self.total_memory_malloc_samples = 0.0
        self.total_memory_free_samples = 0.0
        self.current_footprint = 0.0
        self.leak_score.clear()
        self.last_malloc_triggered = (
            Filename(""),
            LineNumber(0),
            Address("0x0"),
        )
        self.allocation_velocity = (0.0, 0.0)
        self.per_line_footprint_samples.clear()
        self.bytei_map.clear()
        # Not clearing current footprint
        # Not clearing max footprint
        # FIXME: leak score, leak velocity

    def clear_all(self) -> None:
        self.clear()
        self.current_footprint = 0
        self.max_footprint = 0
        self.per_line_footprint_samples.clear()

    def start_clock(self) -> None:
        self.start_time = time.perf_counter()

    def stop_clock(self) -> None:
        self.elapsed_time += time.perf_counter() - self.start_time
        self.start_time = None

    def build_function_stats(self, filename: Filename):  # type: ignore
        fn_stats = ScaleneStatistics()
        fn_stats.elapsed_time = self.elapsed_time
        fn_stats.total_cpu_samples = self.total_cpu_samples
        fn_stats.total_gpu_samples = self.total_gpu_samples
        fn_stats.total_memory_malloc_samples = self.total_memory_malloc_samples
        first_line_no = LineNumber(1)
        fn_stats.function_map = self.function_map
        fn_stats.firstline_map = self.firstline_map
        for line_no in self.function_map[filename]:
            fn_name = self.function_map[filename][line_no]
            if fn_name == "<module>":
                continue
            fn_stats.cpu_samples_c[fn_name][
                first_line_no
            ] += self.cpu_samples_c[filename][line_no]
            fn_stats.cpu_samples_python[fn_name][
                first_line_no
            ] += self.cpu_samples_python[filename][line_no]
            fn_stats.gpu_samples[fn_name][first_line_no] += self.gpu_samples[
                filename
            ][line_no]
            fn_stats.cpu_utilization[fn_name][
                first_line_no
            ] += self.cpu_utilization[filename][line_no]
            fn_stats.per_line_footprint_samples[fn_name][
                first_line_no
            ] += self.per_line_footprint_samples[filename][line_no]
            for index in self.bytei_map[filename][line_no]:
                fn_stats.bytei_map[fn_name][first_line_no].add(
                    ByteCodeIndex(0)
                )
                fn_stats.memory_malloc_count[fn_name][first_line_no][
                    ByteCodeIndex(0)
                ] += self.memory_malloc_count[filename][line_no][index]
                fn_stats.memory_free_count[fn_name][first_line_no][
                    ByteCodeIndex(0)
                ] += self.memory_free_count[filename][line_no][index]
                fn_stats.memory_malloc_samples[fn_name][first_line_no][
                    ByteCodeIndex(0)
                ] += self.memory_malloc_samples[filename][line_no][index]
                fn_stats.memory_python_samples[fn_name][first_line_no][
                    ByteCodeIndex(0)
                ] += self.memory_python_samples[filename][line_no][index]
                fn_stats.memory_free_samples[fn_name][first_line_no][
                    ByteCodeIndex(0)
                ] += self.memory_free_samples[filename][line_no][index]
            fn_stats.memcpy_samples[fn_name][
                first_line_no
            ] += self.memcpy_samples[filename][line_no]
            fn_stats.leak_score[fn_name][first_line_no] = (
                fn_stats.leak_score[fn_name][first_line_no][0]
                + self.leak_score[filename][line_no][0],
                fn_stats.leak_score[fn_name][first_line_no][1]
                + self.leak_score[filename][line_no][1],
            )
        return fn_stats

    payload_contents = [
        "max_footprint",
        "elapsed_time",
        "total_cpu_samples",
        "cpu_samples_c",
        "cpu_samples_python",
        "bytei_map",
        "cpu_samples",
        "cpu_utilization",
        "memory_malloc_samples",
        "memory_python_samples",
        "memory_free_samples",
        "memcpy_samples",
        "per_line_footprint_samples",
        "total_memory_free_samples",
        "total_memory_malloc_samples",
        "memory_footprint_samples",
        "function_map",
        "firstline_map",
        "gpu_samples",
        "total_gpu_samples",
        "memory_malloc_count",
        "memory_free_count",
    ]
    # To be added: __malloc_samples

    def output_stats(self, pid: int, dir_name: Filename) -> None:
        payload: List[Any] = []
        for n in ScaleneStatistics.payload_contents:
            payload.append(getattr(self, n))

        # Create a file in the Python alias directory with the relevant info.
        out_filename = os.path.join(
            dir_name,
            "scalene" + str(pid) + "-" + str(os.getpid()),
        )
        with open(out_filename, "wb") as out_file:
            cloudpickle.dump(payload, out_file)

    @staticmethod
    def increment_per_line_samples(
        dest: Dict[Filename, Dict[LineNumber, T]],
        src: Dict[Filename, Dict[LineNumber, T]],
    ) -> None:
        for filename in src:
            for lineno in src[filename]:
                v = src[filename][lineno]
                dest[filename][lineno] += v  # type: ignore

    @staticmethod
    def increment_cpu_utilization(
        dest: Dict[Filename, Dict[LineNumber, RunningStats]],
        src: Dict[Filename, Dict[LineNumber, RunningStats]],
    ) -> None:
        for filename in src:
            for lineno in src[filename]:
                dest[filename][lineno] += src[filename][lineno]

    @staticmethod
    def increment_per_bytecode_samples(
        dest: Dict[Filename, Dict[LineNumber, Dict[ByteCodeIndex, T]]],
        src: Dict[Filename, Dict[LineNumber, Dict[ByteCodeIndex, T]]],
    ) -> None:
        for filename in src:
            for lineno in src[filename]:
                for ind in src[filename][lineno]:
                    dest[filename][lineno][ind] += src[  # type: ignore
                        filename
                    ][lineno][ind]

    def merge_stats(self, the_dir_name: Filename) -> None:
        the_dir = pathlib.Path(the_dir_name)
        for f in list(the_dir.glob("**/scalene*")):
            # Skip empty files.
            if os.path.getsize(f) == 0:
                continue
            with open(f, "rb") as file:
                unpickler = pickle.Unpickler(file)
                value = unpickler.load()
                x = ScaleneStatistics()
                for i, n in enumerate(ScaleneStatistics.payload_contents):
                    setattr(x, n, value[i])
                self.max_footprint = max(self.max_footprint, x.max_footprint)
                self.increment_cpu_utilization(
                    self.cpu_utilization, x.cpu_utilization
                )
                self.elapsed_time = max(self.elapsed_time, x.elapsed_time)
                self.total_cpu_samples += x.total_cpu_samples
                self.total_gpu_samples += x.total_gpu_samples
                self.increment_per_line_samples(
                    self.cpu_samples_c, x.cpu_samples_c
                )
                self.increment_per_line_samples(
                    self.cpu_samples_python, x.cpu_samples_python
                )
                self.increment_per_line_samples(
                    self.gpu_samples, x.gpu_samples
                )
                self.increment_per_line_samples(
                    self.memcpy_samples, x.memcpy_samples
                )
                self.increment_per_line_samples(
                    self.per_line_footprint_samples,
                    x.per_line_footprint_samples,
                )
                self.increment_per_bytecode_samples(
                    self.memory_malloc_samples, x.memory_malloc_samples
                )
                self.increment_per_bytecode_samples(
                    self.memory_python_samples, x.memory_python_samples
                )
                self.increment_per_bytecode_samples(
                    self.memory_free_samples, x.memory_free_samples
                )
                self.increment_per_bytecode_samples(
                    self.memory_malloc_count, x.memory_malloc_count
                )
                self.increment_per_bytecode_samples(
                    self.memory_free_count, x.memory_free_count
                )
                for filename in x.bytei_map:
                    for lineno in x.bytei_map[filename]:
                        v = x.bytei_map[filename][lineno]
                        self.bytei_map[filename][lineno] |= v
                for filename in x.cpu_samples:
                    self.cpu_samples[filename] += x.cpu_samples[filename]
                self.total_memory_free_samples += x.total_memory_free_samples
                self.total_memory_malloc_samples += (
                    x.total_memory_malloc_samples
                )
                self.memory_footprint_samples += x.memory_footprint_samples
                for k, val in x.function_map.items():
                    if k in self.function_map:
                        self.function_map[k].update(val)
                    else:
                        self.function_map[k] = val
                self.firstline_map.update(x.firstline_map)
            os.remove(f)
