from __future__ import annotations

import os
import pathlib
import pickle
import time
from collections import defaultdict
from pydantic import PositiveInt
from typing import (
    Any,
    Dict,
    List,
    NewType,
    Optional,
    Set,
    Tuple,
    TypeVar,
    Union,
)

import cloudpickle

from scalene.runningstats import RunningStats

Address = NewType("Address", str)
Filename = NewType("Filename", str)
LineNumber = NewType("LineNumber", PositiveInt)
ByteCodeIndex = NewType("ByteCodeIndex", int)
T = TypeVar("T")

class ProfilingSample:
    def __init__(
        self,
        action: str,
        alloc_time: int,
        count: float,
        python_fraction: float,
        pointer: "Address",
        filename: "Filename",
        lineno: "LineNumber",
        bytecode_index: "ByteCodeIndex",
    ) -> None:
        self.action = action
        self.alloc_time = alloc_time
        self.count = count
        self.python_fraction = python_fraction
        self.pointer = pointer
        self.filename = filename
        self.lineno = lineno
        self.bytecode_index = bytecode_index

class MemcpyProfilingSample:
    def __init__(
        self,
        memcpy_time: int,
        count: float,
        filename: "Filename",
        lineno: "LineNumber",
        bytecode_index: "ByteCodeIndex",
    ) -> None:
        self.memcpy_time = memcpy_time
        self.count = count
        self.filename = filename
        self.lineno = lineno
        self.bytecode_index = bytecode_index

    def __lt__(self, other: 'MemcpyProfilingSample') -> bool:
        """Compare based on memcpy_time for sorting."""
        return self.memcpy_time < other.memcpy_time

    def __eq__(self, other: object) -> bool:
        """Compare equality based on all fields."""
        if not isinstance(other, MemcpyProfilingSample):
            return NotImplemented
        return (self.memcpy_time == other.memcpy_time and
                self.count == other.count and
                self.filename == other.filename and
                self.lineno == other.lineno and
                self.bytecode_index == other.bytecode_index)

class StackFrame:
    """Represents a single frame in the stack."""
    def __init__(self, filename: str, function_name: str, line_number: int) -> None:
        self.filename = filename
        self.function_name = function_name
        self.line_number = line_number

    def __repr__(self) -> str:
        return f"{self.filename} {self.function_name}:{self.line_number};"
    
    def __hash__(self) -> int:
        return hash((self.filename, self.function_name, self.line_number))

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, StackFrame):
            return False
        return (self.filename == other.filename and 
                self.function_name == other.function_name and 
                self.line_number == other.line_number)

class StackStats:
    """Represents statistics for a stack."""
    def __init__(self, count: int, python_time: float, c_time: float, cpu_samples: float) -> None:
        self.count = count
        self.python_time = python_time
        self.c_time = c_time
        self.cpu_samples = cpu_samples

    def __repr__(self) -> str:
        return f" {self.count}"

class CPUStatistics:
    """Statistics related to CPU usage."""
    def __init__(self) -> None:
        # CPU samples for each location in the program spent in the interpreter
        self.cpu_samples_python: Dict[Any, Dict[Any, float]] = defaultdict(lambda: defaultdict(float))

        # CPU samples for each location in the program spent in C / libraries / system calls
        self.cpu_samples_c: Dict[Any, Dict[Any, float]] = defaultdict(lambda: defaultdict(float))

        # Running stats for the fraction of time running on the CPU
        self.cpu_utilization: Dict[Any, Dict[Any, RunningStats]] = defaultdict(lambda: defaultdict(RunningStats))

        # Running stats for core utilization
        self.core_utilization: Dict[Any, Dict[Any, RunningStats]] = defaultdict(lambda: defaultdict(RunningStats))

        # Running count of total CPU samples per file. Used to prune reporting
        self.cpu_samples: Dict[Any, float] = defaultdict(float)

        # How many CPU samples have been collected
        self.total_cpu_samples: float = 0.0

    def clear(self) -> None:
        """Reset all CPU statistics."""
        self.cpu_samples_python.clear()
        self.cpu_samples_c.clear()
        self.cpu_utilization.clear()
        self.core_utilization.clear()
        self.cpu_samples.clear()
        self.total_cpu_samples = 0.0

class MemoryStatistics:
    """Statistics related to memory usage."""
    def __init__(self) -> None:
        # Total allocation samples taken
        self.alloc_samples: int = 0

        # Running count of malloc samples per file. Used to prune reporting
        self.malloc_samples: Dict[Any, float] = defaultdict(float)

        # malloc samples for each location in the program
        self.memory_malloc_samples: Dict[Any, Dict[Any, float]] = defaultdict(lambda: defaultdict(float))

        # number of times samples were added for the above
        self.memory_malloc_count: Dict[Any, Dict[Any, int]] = defaultdict(lambda: defaultdict(int))

        # the current footprint for this line
        self.memory_current_footprint: Dict[Any, Dict[Any, float]] = defaultdict(lambda: defaultdict(float))

        # the max footprint for this line
        self.memory_max_footprint: Dict[Any, Dict[Any, float]] = defaultdict(lambda: defaultdict(float))

        # the current high watermark for this line
        self.memory_current_highwater_mark: Dict[Any, Dict[Any, float]] = defaultdict(lambda: defaultdict(float))

        # the aggregate footprint for this line (sum of all final "current"s)
        self.memory_aggregate_footprint: Dict[Any, Dict[Any, float]] = defaultdict(lambda: defaultdict(float))

        # the last malloc to trigger a sample (used for leak detection)
        self.last_malloc_triggered = (Filename(""), LineNumber(0), Address("0x0"))

        # mallocs attributable to Python, for each location in the program
        self.memory_python_samples: Dict[Any, Dict[Any, float]] = defaultdict(lambda: defaultdict(float))

        # free samples for each location in the program
        self.memory_free_samples: Dict[Any, Dict[Any, float]] = defaultdict(lambda: defaultdict(float))

        # number of times samples were added for the above
        self.memory_free_count: Dict[Any, Dict[Any, int]] = defaultdict(lambda: defaultdict(int))

        # memcpy samples for each location in the program
        self.memcpy_samples: Dict[Any, Dict[Any, int]] = defaultdict(lambda: defaultdict(int))

        # leak score tracking
        self.leak_score: Dict[Any, Dict[Any, Tuple[int, int]]] = defaultdict(lambda: defaultdict(lambda: ((0, 0))))

        self.allocation_velocity: Tuple[float, float] = (0.0, 0.0)

        # Total memory samples
        self.total_memory_malloc_samples: float = 0.0
        self.total_memory_free_samples: float = 0.0

        # Memory footprint
        self.current_footprint: float = 0.0
        self.max_footprint: float = 0.0
        self.max_footprint_python_fraction: float = 0
        self.max_footprint_loc: Optional[Tuple["Filename", "LineNumber"]] = None

        # Memory footprint samples (time, footprint)
        self.memory_footprint_samples: List[Tuple[float, float]] = []

        # Same, but per line
        self.per_line_footprint_samples: Dict[Any, Dict[Any, List[Any]]] = defaultdict(lambda: defaultdict(list))

    def clear(self) -> None:
        """Reset all memory statistics except for memory footprint."""
        self.alloc_samples = 0
        self.malloc_samples.clear()
        self.memory_malloc_samples.clear()
        self.memory_malloc_count.clear()
        self.memory_current_footprint.clear()
        self.memory_max_footprint.clear()
        self.memory_current_highwater_mark.clear()
        self.memory_aggregate_footprint.clear()
        self.memory_python_samples.clear()
        self.memory_free_samples.clear()
        self.memory_free_count.clear()
        self.memcpy_samples.clear()
        self.total_memory_malloc_samples = 0.0
        self.total_memory_free_samples = 0.0
        self.current_footprint = 0.0
        self.leak_score.clear()
        self.last_malloc_triggered = (Filename(""), LineNumber(0), Address("0x0"))
        self.allocation_velocity = (0.0, 0.0)
        self.per_line_footprint_samples.clear()
        # Not clearing current footprint
        # Not clearing max footprint

    def clear_all(self) -> None:
        """Clear all memory statistics."""
        self.clear()
        self.current_footprint = 0
        self.max_footprint = 0
        self.max_footprint_loc = None
        self.per_line_footprint_samples.clear()

class GPUStatistics:
    """Statistics related to GPU usage."""
    def __init__(self) -> None:
        # GPU samples for each location in the program
        self.gpu_samples: Dict[Any, Dict[Any, float]] = defaultdict(lambda: defaultdict(float))

        # Number of GPU samples taken (actually weighted by elapsed wallclock time)
        self.n_gpu_samples: Dict[Any, Dict[Any, float]] = defaultdict(lambda: defaultdict(float))

        # GPU memory samples for each location in the program
        self.gpu_mem_samples: Dict[Any, Dict[Any, RunningStats]] = defaultdict(lambda: defaultdict(RunningStats))

        # How many GPU samples have been collected
        self.total_gpu_samples: float = 0.0

    def clear(self) -> None:
        """Reset all GPU statistics."""
        self.gpu_samples.clear()
        self.n_gpu_samples.clear()
        self.gpu_mem_samples.clear()
        self.total_gpu_samples = 0.0

class ScaleneStatistics:
    def __init__(self) -> None:
        # time the profiling started
        self.start_time: float = 0

        # total time spent in program being profiled
        self.elapsed_time: float = 0

        # full stacks taken during CPU samples, together with number of hits
        self.stacks: Dict[Any, StackStats] = defaultdict(lambda: StackStats(0, 0.0, 0.0, 0.0))

        # Initialize statistics classes
        self.cpu_stats = CPUStatistics()
        self.memory_stats = MemoryStatistics()
        self.gpu_stats = GPUStatistics()

        # maps byte indices to line numbers (collected at runtime)
        # [filename][lineno] -> set(byteindex)
        self.bytei_map: Dict[Any, Dict[Any, Set["ByteCodeIndex"]]] = defaultdict(lambda: defaultdict(lambda: set()))

        # maps filenames and line numbers to functions (collected at runtime)
        # [filename][lineno] -> function name
        self.function_map: Dict[Any, Dict[Any, "Filename"]] = defaultdict(lambda: defaultdict(lambda: Filename("")))
        self.firstline_map: Dict[Any, "LineNumber"] = defaultdict(lambda: LineNumber(1))

    def clear(self) -> None:
        """Reset all statistics except for memory footprint."""
        self.start_time = 0
        self.elapsed_time = 0
        self.stacks.clear()
        self.cpu_stats.clear()
        self.memory_stats.clear()
        self.gpu_stats.clear()
        self.bytei_map.clear()

    def clear_all(self) -> None:
        """Clear all statistics."""
        self.clear()
        self.memory_stats.clear_all()

    def start_clock(self) -> None:
        """Start the timer."""
        self.start_time = time.time()

    def stop_clock(self) -> None:
        """Stop the timer."""
        if self.start_time > 0:
            self.elapsed_time += time.time() - self.start_time
        self.start_time = 0

    def build_function_stats(self, filename: "Filename") -> "ScaleneStatistics":
        """Produce aggregated statistics for each function."""
        fn_stats = ScaleneStatistics()
        fn_stats.elapsed_time = self.elapsed_time
        fn_stats.cpu_stats.total_cpu_samples = self.cpu_stats.total_cpu_samples
        fn_stats.gpu_stats.total_gpu_samples = self.gpu_stats.total_gpu_samples
        fn_stats.gpu_stats.n_gpu_samples = self.gpu_stats.n_gpu_samples
        fn_stats.memory_stats.total_memory_malloc_samples = self.memory_stats.total_memory_malloc_samples
        first_line_no = LineNumber(1)
        fn_stats.function_map = self.function_map
        fn_stats.firstline_map = self.firstline_map
        for line_no in self.function_map[filename]:
            fn_name = self.function_map[filename][line_no]
            if fn_name == "<module>":
                continue

            fn_stats.cpu_stats.cpu_samples_c[fn_name][
                first_line_no
            ] += self.cpu_stats.cpu_samples_c[filename][line_no]
            fn_stats.cpu_stats.cpu_samples_python[fn_name][
                first_line_no
            ] += self.cpu_stats.cpu_samples_python[filename][line_no]
            fn_stats.gpu_stats.gpu_samples[fn_name][first_line_no] += self.gpu_stats.gpu_samples[
                filename
            ][line_no]
            fn_stats.gpu_stats.n_gpu_samples[fn_name][
                first_line_no
            ] += self.gpu_stats.n_gpu_samples[filename][line_no]
            fn_stats.gpu_stats.gpu_mem_samples[fn_name][
                first_line_no
            ] += self.gpu_stats.gpu_mem_samples[filename][line_no]
            fn_stats.cpu_stats.cpu_utilization[fn_name][
                first_line_no
            ] += self.cpu_stats.cpu_utilization[filename][line_no]
            fn_stats.cpu_stats.core_utilization[fn_name][
                first_line_no
            ] += self.cpu_stats.core_utilization[filename][line_no]
            fn_stats.memory_stats.per_line_footprint_samples[fn_name][
                first_line_no
            ] += self.memory_stats.per_line_footprint_samples[filename][line_no]
            fn_stats.memory_stats.memory_malloc_count[fn_name][
                first_line_no
            ] += self.memory_stats.memory_malloc_count[filename][line_no]
            fn_stats.memory_stats.memory_free_count[fn_name][
                first_line_no
            ] += self.memory_stats.memory_free_count[filename][line_no]
            fn_stats.memory_stats.memory_malloc_samples[fn_name][
                first_line_no
            ] += self.memory_stats.memory_malloc_samples[filename][line_no]
            fn_stats.memory_stats.memory_python_samples[fn_name][
                first_line_no
            ] += self.memory_stats.memory_python_samples[filename][line_no]
            fn_stats.memory_stats.memory_free_samples[fn_name][
                first_line_no
            ] += self.memory_stats.memory_free_samples[filename][line_no]
            for index in self.bytei_map[filename][line_no]:
                fn_stats.bytei_map[fn_name][first_line_no].add(
                    ByteCodeIndex(index)  # was 0
                )
            fn_stats.memory_stats.memcpy_samples[fn_name][
                first_line_no
            ] += self.memory_stats.memcpy_samples[filename][line_no]
            fn_stats.memory_stats.leak_score[fn_name][first_line_no] = (
                fn_stats.memory_stats.leak_score[fn_name][first_line_no][0]
                + self.memory_stats.leak_score[filename][line_no][0],
                fn_stats.memory_stats.leak_score[fn_name][first_line_no][1]
                + self.memory_stats.leak_score[filename][line_no][1],
            )
            fn_stats.memory_stats.memory_max_footprint[fn_name][first_line_no] = max(
                fn_stats.memory_stats.memory_max_footprint[fn_name][first_line_no],
                self.memory_stats.memory_max_footprint[filename][line_no],
            )
            fn_stats.memory_stats.memory_aggregate_footprint[fn_name][
                first_line_no
            ] += self.memory_stats.memory_aggregate_footprint[filename][line_no]

        return fn_stats

    payload_contents = [
        "max_footprint",
        "max_footprint_loc",
        "current_footprint",
        "elapsed_time",
        "alloc_samples",
        "stacks",
        "total_cpu_samples",
        "cpu_samples_c",
        "cpu_samples_python",
        "bytei_map",
        "cpu_samples",
        "cpu_utilization",
        "core_utilization",
        "memory_malloc_samples",
        "memory_python_samples",
        "memory_free_samples",
        "memcpy_samples",
        "memory_max_footprint",
        "per_line_footprint_samples",
        "total_memory_free_samples",
        "total_memory_malloc_samples",
        "memory_footprint_samples",
        "function_map",
        "firstline_map",
        "gpu_samples",
        "n_gpu_samples",
        "gpu_mem_samples",
        "total_gpu_samples",
        "memory_malloc_count",
        "memory_free_count",
    ]
    # To be added: __malloc_samples

    def output_stats(self, pid: int, dir_name: pathlib.Path) -> None:
        """Output statistics for a particular process to a given directory."""
        payload: List[Any] = [
            getattr(self, n) for n in ScaleneStatistics.payload_contents
        ]

        # Create a file in the Python alias directory with the relevant info.
        out_filename = os.path.join(
            dir_name, f"scalene{pid}-{str(os.getpid())}"
        )
        with open(out_filename, "wb") as out_file:
            cloudpickle.dump(payload, out_file)

    @staticmethod
    def increment_per_line_samples(
        dest: Dict["Filename", Dict["LineNumber", T]],
        src: Dict["Filename", Dict["LineNumber", T]],
    ) -> None:
        """Increment single-line dest samples by their value in src."""
        for filename in src:
            for lineno in src[filename]:
                v = src[filename][lineno]
                dest[filename][lineno] += v  # type: ignore

    @staticmethod
    def increment_cpu_utilization(
        dest: Dict["Filename", Dict["LineNumber", RunningStats]],
        src: Dict["Filename", Dict["LineNumber", RunningStats]],
    ) -> None:
        """Increment CPU utilization."""
        for filename in src:
            for lineno in src[filename]:
                dest[filename][lineno] += src[filename][lineno]

    @staticmethod
    def increment_core_utilization(
        dest: Dict["Filename", Dict["LineNumber", RunningStats]],
        src: Dict["Filename", Dict["LineNumber", RunningStats]],
    ) -> None:
        """Increment core utilization."""
        for filename in src:
            for lineno in src[filename]:
                dest[filename][lineno] += src[filename][lineno]

    def merge_stats(self, the_dir_name: pathlib.Path) -> None:
        """Merge all statistics in a given directory."""
        the_dir = pathlib.Path(the_dir_name)
        for f in list(the_dir.glob(os.path.join("**", "scalene*"))):
            # Skip empty files.
            if os.path.getsize(f) == 0:
                continue
            with open(f, "rb") as file:
                unpickler = pickle.Unpickler(file)
                try:
                    value = unpickler.load()
                except EOFError:
                    # Empty file for some reason.
                    continue
                x = ScaleneStatistics()
                for i, n in enumerate(ScaleneStatistics.payload_contents):
                    setattr(x, n, value[i])
                if x.memory_stats.max_footprint > self.memory_stats.max_footprint:
                    self.memory_stats.max_footprint = x.memory_stats.max_footprint
                    self.memory_stats.max_footprint_loc = x.memory_stats.max_footprint_loc
                self.memory_stats.current_footprint = max(
                    self.memory_stats.current_footprint, x.memory_stats.current_footprint
                )
                self.cpu_stats.cpu_utilization.update(x.cpu_stats.cpu_utilization)
                self.cpu_stats.core_utilization.update(x.cpu_stats.core_utilization)
                self.elapsed_time = max(self.elapsed_time, x.elapsed_time)
                self.memory_stats.alloc_samples += x.memory_stats.alloc_samples
                self.stacks.update(x.stacks)
                self.cpu_stats.total_cpu_samples += x.cpu_stats.total_cpu_samples
                self.gpu_stats.total_gpu_samples += x.gpu_stats.total_gpu_samples
                
                # Restore per-line sample increments
                self.increment_per_line_samples(
                    self.cpu_stats.cpu_samples_c, x.cpu_stats.cpu_samples_c
                )
                self.increment_per_line_samples(
                    self.cpu_stats.cpu_samples_python, x.cpu_stats.cpu_samples_python
                )
                self.increment_per_line_samples(
                    self.gpu_stats.gpu_samples, x.gpu_stats.gpu_samples
                )
                self.increment_per_line_samples(
                    self.gpu_stats.n_gpu_samples, x.gpu_stats.n_gpu_samples
                )
                self.increment_per_line_samples(
                    self.gpu_stats.gpu_mem_samples, x.gpu_stats.gpu_mem_samples
                )
                self.increment_per_line_samples(
                    self.memory_stats.memcpy_samples, x.memory_stats.memcpy_samples
                )
                self.increment_per_line_samples(
                    self.memory_stats.per_line_footprint_samples,
                    x.memory_stats.per_line_footprint_samples,
                )
                # Sorting each of the per_line_footprint_sample lists by time
                for filename in self.memory_stats.per_line_footprint_samples:
                    for lineno in self.memory_stats.per_line_footprint_samples[filename]:
                        self.memory_stats.per_line_footprint_samples[filename][lineno].sort(
                            key=lambda x: x[0]
                        )
                self.increment_per_line_samples(
                    self.memory_stats.memory_malloc_count, x.memory_stats.memory_malloc_count
                )
                self.increment_per_line_samples(
                    self.memory_stats.memory_malloc_samples, x.memory_stats.memory_malloc_samples
                )
                self.increment_per_line_samples(
                    self.memory_stats.memory_python_samples, x.memory_stats.memory_python_samples
                )
                self.increment_per_line_samples(
                    self.memory_stats.memory_free_samples, x.memory_stats.memory_free_samples
                )
                self.increment_per_line_samples(
                    self.memory_stats.memory_free_count, x.memory_stats.memory_free_count
                )

                # Restore bytei_map and memory_max_footprint handling
                for filename in x.bytei_map:
                    for lineno in x.bytei_map[filename]:
                        v = x.bytei_map[filename][lineno]
                        self.bytei_map[filename][lineno] |= v
                        self.memory_stats.memory_max_footprint[filename][lineno] = max(
                            self.memory_stats.memory_max_footprint[filename][lineno],
                            x.memory_stats.memory_max_footprint[filename][lineno],
                        )

                # Restore cpu_samples handling
                for filename in x.cpu_stats.cpu_samples:
                    self.cpu_stats.cpu_samples[filename] += x.cpu_stats.cpu_samples[filename]

                self.memory_stats.total_memory_free_samples += x.memory_stats.total_memory_free_samples
                self.memory_stats.total_memory_malloc_samples += x.memory_stats.total_memory_malloc_samples
                self.memory_stats.memory_footprint_samples += x.memory_stats.memory_footprint_samples
                self.memory_stats.memory_footprint_samples.sort(key=lambda x: x[0])

                # Restore careful function_map handling
                for k, val in x.function_map.items():
                    if k in self.function_map:
                        self.function_map[k].update(val)
                    else:
                        self.function_map[k] = val
                self.firstline_map.update(x.firstline_map)
            os.remove(f)
