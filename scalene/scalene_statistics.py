import cloudpickle
import os
import pathlib
import pickle

from collections import defaultdict
from typing import Any, Dict, List, NewType, Set, Tuple
from scalene.runningstats import RunningStats
from scalene.adaptive import Adaptive

Address = NewType("Address", str)
Filename = NewType("Filename", str)
# FunctionName = NewType("FunctionName", str)
LineNumber = NewType("LineNumber", int)
ByteCodeIndex = NewType("ByteCodeIndex", int)


class ScaleneStatistics:
    # Statistics counters:
    #
    def __init__(self):
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
            str, Dict[int, Adaptive]
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

    def build_function_stats(self, fname: Filename):  # type: ignore
        fn_stats = ScaleneStatistics()
        fn_stats.elapsed_time = self.elapsed_time
        fn_stats.total_cpu_samples = self.total_cpu_samples
        fn_stats.total_gpu_samples = self.total_gpu_samples
        fn_stats.total_memory_malloc_samples = self.total_memory_malloc_samples
        first_line_no = LineNumber(1)
        fn_stats.function_map = self.function_map
        fn_stats.firstline_map = self.firstline_map
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
            fn_stats.gpu_samples[fn_name][first_line_no] += self.gpu_samples[
                fname
            ][line_no]
            fn_stats.cpu_utilization[fn_name][
                first_line_no
            ] += self.cpu_utilization[fname][line_no]
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

    def output_stats(self, pid: int, dir_name: Filename) -> None:
        payload: List[Any] = []
        payload = [
            self.max_footprint,
            self.elapsed_time,
            self.total_cpu_samples,
            self.cpu_samples_c,
            self.cpu_samples_python,
            self.bytei_map,
            self.cpu_samples,
            self.memory_malloc_samples,
            self.memory_python_samples,
            self.memory_free_samples,
            self.memcpy_samples,
            self.per_line_footprint_samples,
            self.total_memory_free_samples,
            self.total_memory_malloc_samples,
            self.memory_footprint_samples,
            self.function_map,
            self.firstline_map,
            self.gpu_samples,
            self.total_gpu_samples,
        ]
        # To be added: __malloc_samples

        # Create a file in the Python alias directory with the relevant info.
        out_fname = os.path.join(
            dir_name,
            "scalene" + str(pid) + "-" + str(os.getpid()),
        )
        with open(out_fname, "wb") as out_file:
            cloudpickle.dump(payload, out_file)

    def merge_stats(self, the_dir_name: Filename) -> None:
        the_dir = pathlib.Path(the_dir_name)
        for f in list(the_dir.glob("**/scalene*")):
            # Skip empty files.
            if os.path.getsize(f) == 0:
                continue
            with open(f, "rb") as file:
                unpickler = pickle.Unpickler(file)
                value = unpickler.load()
                self.max_footprint = max(self.max_footprint, value[0])
                self.elapsed_time = max(self.elapsed_time, value[1])
                self.total_cpu_samples += value[2]
                self.total_gpu_samples += value[18]
                del value[:3]
                for dict, index in [
                    (self.cpu_samples_c, 0),
                    (self.cpu_samples_python, 1),
                    (self.gpu_samples, 14),
                    (self.memcpy_samples, 7),
                    (self.per_line_footprint_samples, 8),
                ]:
                    for fname in value[index]:
                        for lineno in value[index][fname]:
                            v = value[index][fname][lineno]
                            dict[fname][lineno] += v  # type: ignore
                for dict, index in [
                    (self.memory_malloc_samples, 4),
                    (self.memory_python_samples, 5),
                    (self.memory_free_samples, 6),
                ]:
                    for fname in value[index]:
                        for lineno in value[index][fname]:
                            for ind in value[index][fname][lineno]:
                                dict[fname][lineno][ind] += value[index][
                                    fname
                                ][lineno][ind]
                for fname in value[2]:
                    for lineno in value[2][fname]:
                        v = value[2][fname][lineno]
                        self.bytei_map[fname][lineno] |= v
                for fname in value[3]:
                    self.cpu_samples[fname] += value[3][fname]
                self.total_memory_free_samples += value[9]
                self.total_memory_malloc_samples += value[10]
                self.memory_footprint_samples += value[11]
                for k, v in value[12].items():
                    if k in self.function_map:
                        self.function_map[k].update(v)
                    else:
                        self.function_map[k] = v
                self.firstline_map.update(value[13])
            os.remove(f)
