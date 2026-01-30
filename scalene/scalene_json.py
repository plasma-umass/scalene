import copy
import linecache
import math
import random
import re
from collections import defaultdict
from enum import Enum
from operator import itemgetter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from pydantic import (
    BaseModel,
    Field,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
    StrictBool,
    ValidationError,
    model_validator,
)

from scalene.scalene_analysis import ScaleneAnalysis
from scalene.scalene_leak_analysis import ScaleneLeakAnalysis
from scalene.scalene_statistics import (
    Filename,
    LineNumber,
    ScaleneStatistics,
    StackStats,
)


class GPUDevice(str, Enum):
    nvidia = "GPU"
    neuron = "Neuron"
    no_gpu = ""


class FunctionDetail(BaseModel):
    line: str
    lineno: LineNumber
    memory_samples: List[List[Any]]
    n_avg_mb: NonNegativeFloat
    n_copy_mb_s: NonNegativeFloat
    n_core_utilization: float = Field(..., ge=0, le=1)
    cpu_samples_list: List[float]
    n_cpu_percent_c: float = Field(..., ge=0, le=100)
    n_cpu_percent_python: float = Field(..., ge=0, le=100)
    n_gpu_avg_memory_mb: NonNegativeFloat
    n_gpu_peak_memory_mb: NonNegativeFloat
    n_gpu_percent: float = Field(..., ge=0, le=100)
    n_growth_mb: NonNegativeFloat
    n_peak_mb: NonNegativeFloat
    n_malloc_mb: NonNegativeFloat
    n_mallocs: NonNegativeInt
    n_python_fraction: float = Field(..., ge=0, le=1)
    n_sys_percent: float = Field(..., ge=0, le=100)
    n_usage_fraction: float = Field(..., ge=0, le=1)

    @model_validator(mode="after")
    def check_cpu_percentages(self) -> Any:
        total_cpu_usage = math.floor(
            self.n_cpu_percent_c + self.n_cpu_percent_python + self.n_sys_percent
        )
        if total_cpu_usage > 100:
            raise ValueError(
                f"The sum of n_cpu_percent_c, n_cpu_percent_python, and n_sys_percent must be <= 100 but is {total_cpu_usage}"
            )
        return self

    @model_validator(mode="after")
    def check_gpu_memory(self) -> Any:
        if self.n_gpu_avg_memory_mb > self.n_gpu_peak_memory_mb:
            raise ValueError(
                "n_gpu_avg_memory_mb must be less than or equal to n_gpu_peak_memory_mb"
            )
        return self

    @model_validator(mode="after")
    def check_cpu_memory(self) -> Any:
        if self.n_avg_mb > self.n_peak_mb:
            raise ValueError("n_avg_mb must be less than or equal to n_peak_mb")
        return self


class LineDetail(FunctionDetail):
    start_outermost_loop: PositiveInt
    end_outermost_loop: PositiveInt
    start_region_line: PositiveInt
    end_region_line: PositiveInt
    start_function_line: NonNegativeInt = 0
    end_function_line: NonNegativeInt = 0


class LeakInfo(BaseModel):
    likelihood: NonNegativeFloat
    velocity_mb_s: NonNegativeFloat


class FileDetail(BaseModel):
    functions: List[FunctionDetail]
    imports: List[str]
    leaks: Dict[str, LeakInfo]
    lines: List[LineDetail]
    percent_cpu_time: NonNegativeFloat


class ScaleneJSONSchema(BaseModel):
    alloc_samples: NonNegativeInt
    args: Optional[List[str]] = None
    elapsed_time_sec: NonNegativeFloat
    start_time_absolute: NonNegativeFloat
    start_time_perf: NonNegativeFloat
    entrypoint_dir: str
    filename: str
    files: Dict[str, FileDetail]
    gpu: StrictBool
    gpu_device: GPUDevice
    growth_rate: float
    max_footprint_fname: Optional[str]
    max_footprint_lineno: Optional[PositiveInt]
    max_footprint_mb: NonNegativeFloat
    max_footprint_python_fraction: NonNegativeFloat
    memory: StrictBool
    program: str
    samples: List[List[NonNegativeFloat]]
    stacks: List[List[Any]]


class ScaleneJSON:
    @staticmethod
    def memory_consumed_str(size_in_mb: float) -> str:
        """Return a string corresponding to amount of memory consumed."""
        gigabytes = size_in_mb // 1024
        terabytes = gigabytes // 1024
        if terabytes > 0:
            return f"{(size_in_mb / 1048576):3.3f} TB"
        elif gigabytes > 0:
            return f"{(size_in_mb / 1024):3.3f} GB"
        else:
            return f"{size_in_mb:3.3f} MB"

    @staticmethod
    def time_consumed_str(time_in_ms: float) -> str:
        hours = time_in_ms // 3600000
        minutes = (time_in_ms % 3600000) // 60000
        seconds = (time_in_ms % 60000) // 1000
        hours_exact = time_in_ms / 3600000
        minutes_exact = (time_in_ms % 3600000) / 60000
        seconds_exact = (time_in_ms % 60000) / 1000
        if hours > 0:
            return f"{hours_exact:.0f}h:{minutes_exact:.0f}m:{seconds_exact:3.3f}s"
        elif minutes > 0:
            return f"{minutes_exact:.0f}m:{seconds_exact:3.3f}s"
        elif seconds > 0:
            return f"{seconds_exact:3.3f}s"
        else:
            return f"{time_in_ms:3.3f}ms"

    # Default threshold for percent of CPU time to report a file.
    cpu_percent_threshold = 1

    # Default threshold for number of mallocs to report a file.
    malloc_threshold = 1  # 100

    # Fraction of the maximum footprint to use as granularity for memory timelines
    # (used for compression). E.g., 10 => 1/10th of the max.
    memory_granularity_fraction = 10

    # Maximum number of sparkline samples.
    max_sparkline_samples = 100

    def __init__(self) -> None:
        # where we write profile info
        self.output_file = ""

        # if we are on a GPU or not
        self.gpu = False
        self.gpu_device = ""

    def compress_samples(self, samples: List[Any], max_footprint: float) -> Any:
        if len(samples) <= self.max_sparkline_samples:
            return samples

        new_samples = sorted(
            random.sample(list(map(tuple, samples)), self.max_sparkline_samples)
        )
        return new_samples

    # Profile output methods
    def output_profile_line(
        self,
        *,
        fname: Filename,
        fname_print: Filename,
        line_no: LineNumber,
        line: str,
        stats: ScaleneStatistics,
        profile_this_code: Callable[[Filename, LineNumber], bool],
        profile_memory: bool = False,
        force_print: bool = False,
    ) -> Dict[str, Any]:
        """Print at most one line of the profile (true == printed one)."""

        # Check if this line has PyTorch profiler timing (for JIT-compiled code)
        torch_cpu_time_sec = stats.cpu_stats.torch_cpu_time[fname][line_no]
        torch_gpu_time_sec = stats.cpu_stats.torch_gpu_time[fname][line_no]
        has_torch_timing = torch_cpu_time_sec > 0 or torch_gpu_time_sec > 0

        if (
            not force_print
            and not profile_this_code(fname, line_no)
            and not has_torch_timing
        ):
            return {
                "lineno": line_no,
                "line": line,
                "cpu_samples_list": [],
                "n_core_utilization": 0,
                "n_cpu_percent_c": 0,
                "n_cpu_percent_python": 0,
                "n_sys_percent": 0,
                "n_gpu_percent": 0,
                "n_gpu_avg_memory_mb": 0,
                "n_gpu_peak_memory_mb": 0,
                "n_peak_mb": 0,
                "n_growth_mb": 0,
                "n_avg_mb": 0,
                "n_mallocs": 0,
                "n_malloc_mb": 0,
                "n_usage_fraction": 0,
                "n_python_fraction": 0,
                "n_copy_mb_s": 0,
                "memory_samples": [],
            }

        # Prepare output values.
        n_cpu_samples_c = stats.cpu_stats.cpu_samples_c[fname][line_no]
        # Correct for negative CPU sample counts. This can happen
        # because of floating point inaccuracies, since we perform
        # subtraction to compute it.
        n_cpu_samples_c = max(0, n_cpu_samples_c)
        n_cpu_samples_python = stats.cpu_stats.cpu_samples_python[fname][line_no]
        n_gpu_samples = stats.gpu_stats.gpu_samples[fname][line_no]
        n_gpu_mem_samples = stats.gpu_stats.gpu_mem_samples[fname][line_no]

        # torch_time_sec was already fetched above for the early return check

        # Compute percentages of CPU time (from signal-based sampling).
        if stats.cpu_stats.total_cpu_samples:
            n_cpu_percent_c = n_cpu_samples_c * 100 / stats.cpu_stats.total_cpu_samples
            n_cpu_percent_python = (
                n_cpu_samples_python * 100 / stats.cpu_stats.total_cpu_samples
            )
        else:
            n_cpu_percent_c = 0
            n_cpu_percent_python = 0

        if True:
            if stats.gpu_stats.n_gpu_samples[fname][line_no]:
                n_gpu_percent = (
                    n_gpu_samples * 100 / stats.gpu_stats.n_gpu_samples[fname][line_no]
                )  # total_gpu_samples
            else:
                n_gpu_percent = 0

        # Now, memory stats.
        # Total volume of memory allocated.
        n_malloc_mb = stats.memory_stats.memory_malloc_samples[fname][line_no]
        # Number of distinct allocation calls (those from the same line are counted as 1).
        n_mallocs = stats.memory_stats.memory_malloc_count[fname][line_no]
        # Total volume of memory allocated by Python (not native code).
        n_python_malloc_mb = stats.memory_stats.memory_python_samples[fname][line_no]

        n_usage_fraction = (
            0
            if not stats.memory_stats.total_memory_malloc_samples
            else n_malloc_mb / stats.memory_stats.total_memory_malloc_samples
        )
        n_python_fraction = 0 if not n_malloc_mb else n_python_malloc_mb / n_malloc_mb

        # Average memory consumed by this line.
        n_avg_mb = (
            stats.memory_stats.memory_aggregate_footprint[fname][line_no]
            if n_mallocs == 0
            else stats.memory_stats.memory_aggregate_footprint[fname][line_no]
            / n_mallocs
        )

        # Peak memory consumed by this line.
        n_peak_mb = stats.memory_stats.memory_max_footprint[fname][line_no]

        # Force the reporting of average to be no more than peak.
        # In principle, this should never happen, but...
        # assert n_avg_mb <= n_peak_mb
        if n_avg_mb > n_peak_mb:
            n_avg_mb = n_peak_mb

        n_cpu_percent = n_cpu_percent_c + n_cpu_percent_python

        # Adjust CPU time by utilization (for signal-based sampling).
        mean_cpu_util = stats.cpu_stats.cpu_utilization[fname][line_no].mean()
        mean_core_util = stats.cpu_stats.core_utilization[fname][line_no].mean()
        n_sys_percent = n_cpu_percent * (1.0 - mean_cpu_util)
        n_cpu_percent_python *= mean_cpu_util
        n_cpu_percent_c *= mean_cpu_util
        del mean_cpu_util

        # Add PyTorch profiler timing for lines that have NO signal-based samples.
        # This provides attribution for lines inside JIT-compiled functions that
        # the signal sampler never sees. We only add torch timing when there are
        # no signal samples to avoid double-counting (the call site already
        # accounts for the time spent in the JIT function via signal sampling).
        has_signal_samples = n_cpu_samples_c > 0 or n_cpu_samples_python > 0
        if stats.elapsed_time > 0 and torch_cpu_time_sec > 0 and not has_signal_samples:
            torch_cpu_percent = (torch_cpu_time_sec / stats.elapsed_time) * 100
            n_cpu_percent_c = min(torch_cpu_percent, 100.0)

        # Add PyTorch GPU timing for lines that have NO signal-based GPU samples.
        # Similar to CPU timing, this attributes GPU time to JIT-compiled code.
        has_gpu_signal_samples = n_gpu_samples > 0
        if (
            stats.elapsed_time > 0
            and torch_gpu_time_sec > 0
            and not has_gpu_signal_samples
        ):
            torch_gpu_percent = (torch_gpu_time_sec / stats.elapsed_time) * 100
            n_gpu_percent = min(torch_gpu_percent, 100.0)

        n_copy_b = stats.memory_stats.memcpy_samples[fname][line_no]
        if stats.elapsed_time:
            n_copy_mb_s = n_copy_b / (1024 * 1024 * stats.elapsed_time)
        else:
            n_copy_mb_s = 0

        per_line_samples = self.compress_samples(
            stats.memory_stats.per_line_footprint_samples[fname][line_no].reservoir,
            stats.memory_stats.max_footprint,
        )

        payload = {
            "line": line,
            "lineno": line_no,
            "memory_samples": per_line_samples,
            "cpu_samples_list": stats.cpu_stats.cpu_samples_list[fname][line_no],
            "n_avg_mb": n_avg_mb,
            "n_copy_mb_s": n_copy_mb_s,
            "n_core_utilization": mean_core_util,
            "n_cpu_percent_c": n_cpu_percent_c,
            "n_cpu_percent_python": n_cpu_percent_python,
            "n_gpu_avg_memory_mb": n_gpu_mem_samples.mean(),
            "n_gpu_peak_memory_mb": n_gpu_mem_samples.peak(),
            "n_gpu_percent": n_gpu_percent,
            "n_growth_mb": n_peak_mb,  # For backwards compatibility
            "n_peak_mb": n_peak_mb,
            "n_malloc_mb": n_malloc_mb,
            "n_mallocs": n_mallocs,
            "n_python_fraction": n_python_fraction,
            "n_sys_percent": n_sys_percent,
            "n_usage_fraction": n_usage_fraction,
        }
        try:
            FunctionDetail(**payload)
        except ValidationError as e:
            print("Warning: JSON failed validation:")
            print(e)
        return payload

    def output_profiles(
        self,
        program: Filename,
        stats: ScaleneStatistics,
        pid: int,
        profile_this_code: Callable[[Filename, LineNumber], bool],
        python_alias_dir: Path,
        program_path: Filename,
        entrypoint_dir: Filename,
        program_args: Optional[List[str]],
        profile_memory: bool = True,
        reduced_profile: bool = False,
    ) -> Dict[str, Any]:
        """Write the profile out."""
        # Get the children's stats, if any.
        if not pid:
            stats.merge_stats(python_alias_dir)
        # If we've collected any samples, dump them.
        if (
            not stats.cpu_stats.total_cpu_samples
            and not stats.memory_stats.total_memory_malloc_samples
            and not stats.memory_stats.total_memory_free_samples
            and not stats.gpu_stats.n_gpu_samples[program]
        ):
            # Nothing to output.
            return {}
        # Collect all instrumented filenames.
        all_instrumented_files: List[Filename] = list(
            set(
                list(stats.cpu_stats.cpu_samples_python.keys())
                + list(stats.cpu_stats.cpu_samples_c.keys())
                + list(stats.cpu_stats.torch_cpu_time.keys())
                + list(stats.cpu_stats.torch_gpu_time.keys())
                + list(stats.memory_stats.memory_free_samples.keys())
                + list(stats.memory_stats.memory_malloc_samples.keys())
                + list(stats.gpu_stats.gpu_samples.keys())
            )
        )
        if not all_instrumented_files:
            # We didn't collect samples in source files.
            return {}
        growth_rate = 0.0
        if profile_memory:
            compressed_footprint_samples = self.compress_samples(
                stats.memory_stats.memory_footprint_samples.reservoir,
                stats.memory_stats.max_footprint,
            )
            # Compute growth rate (slope), between 0 and 1.
            if stats.memory_stats.allocation_velocity[1] > 0:
                growth_rate = (
                    100.0
                    * stats.memory_stats.allocation_velocity[0]
                    / stats.memory_stats.allocation_velocity[1]
                )

        # Adjust the program name if it was a Jupyter cell.
        result = re.match(r"_ipython-input-([0-9]+)-.*", program)
        if result:
            program = Filename("[" + result.group(1) + "]")

        # Process the stacks to normalize by total number of CPU samples.
        for stk in stats.stacks:
            stack_stats = stats.stacks[stk]
            stats.stacks[stk] = StackStats(
                stack_stats.count,
                stack_stats.python_time / stats.cpu_stats.total_cpu_samples,
                stack_stats.c_time / stats.cpu_stats.total_cpu_samples,
                stack_stats.cpu_samples / stats.cpu_stats.total_cpu_samples,
            )

        # Convert stacks into a representation suitable for JSON dumping.
        stks = []
        for stk in stats.stacks:
            this_stk: List[str] = []
            this_stk.extend(str(frame) for frame in stk)
            stack_stats = stats.stacks[stk]
            # Convert StackStats to a dictionary
            stack_stats_dict = {
                "count": stack_stats.count,
                "python_time": stack_stats.python_time,
                "c_time": stack_stats.c_time,
                "cpu_samples": stack_stats.cpu_samples,
            }
            stks.append((this_stk, stack_stats_dict))

        output: Dict[str, Any] = {
            "program": program,
            "entrypoint_dir": entrypoint_dir,
            "args": program_args,
            "filename": program_path,
            "alloc_samples": stats.memory_stats.alloc_samples,
            "elapsed_time_sec": stats.elapsed_time,
            "start_time_absolute": stats.start_time_absolute,
            "start_time_perf": stats.start_time_perf,
            "growth_rate": growth_rate,
            "max_footprint_mb": stats.memory_stats.max_footprint,
            "max_footprint_python_fraction": stats.memory_stats.max_footprint_python_fraction,
            "max_footprint_fname": (
                stats.memory_stats.max_footprint_loc[0]
                if stats.memory_stats.max_footprint_loc
                else None
            ),
            "max_footprint_lineno": (
                stats.memory_stats.max_footprint_loc[1]
                if stats.memory_stats.max_footprint_loc
                else None
            ),
            "files": {},
            "gpu": self.gpu,
            "gpu_device": self.gpu_device,
            "memory": profile_memory,
            "samples": compressed_footprint_samples if profile_memory else [],
            "stacks": stks,
        }

        # Build a list of files we will actually report on.
        report_files: List[Filename] = []
        # Sort in descending order of CPU cycles, and then ascending order by filename
        for fname in sorted(
            all_instrumented_files,
            key=lambda f: (-(stats.cpu_stats.cpu_samples[f]), f),
        ):
            fname = Filename(fname)
            try:
                percent_cpu_time = (
                    100
                    * stats.cpu_stats.cpu_samples[fname]
                    / stats.elapsed_time
                    # 100 * stats.cpu_samples[fname] / stats.total_cpu_samples
                )
            except ZeroDivisionError:
                percent_cpu_time = 0

            # Ignore files responsible for less than some percent of execution time and fewer than a threshold # of mallocs.
            if (
                sum(stats.memory_stats.memory_malloc_samples[fname].values())
                < self.malloc_threshold
                and percent_cpu_time < self.cpu_percent_threshold
            ):
                continue

            report_files.append(fname)

        # Don't actually output the profile if we are a child process.
        # Instead, write info to disk for the main process to collect.
        if pid:
            stats.output_stats(pid, python_alias_dir)
            # Return a value to indicate that the stats were successfully
            # output to the proper directory
            return {"is_child": True}

        if len(report_files) == 0:
            return {}

        for fname in report_files:

            # If the file was actually a Jupyter (IPython) cell,
            # restore its name, as in "[12]".
            fname_print = fname

            result = re.match(r"_ipython-input-([0-9]+)-.*", fname_print)
            if result:
                fname_print = Filename("[" + result.group(1) + "]")

            # Leak analysis
            # First, compute AVERAGE memory consumption.
            avg_mallocs: Dict[LineNumber, float] = defaultdict(float)
            for line_no in stats.memory_stats.memory_malloc_count[fname]:
                n_malloc_mb = stats.memory_stats.memory_aggregate_footprint[fname][
                    line_no
                ]
                count = stats.memory_stats.memory_malloc_count[fname][line_no]
                if count:
                    avg_mallocs[line_no] = n_malloc_mb / count
                else:
                    # Setting to n_malloc_mb addresses the edge case where this allocation is the last line executed.
                    avg_mallocs[line_no] = n_malloc_mb

            avg_mallocs = dict(
                sorted(avg_mallocs.items(), key=itemgetter(1), reverse=True)
            )

            # Now only report potential leaks if the allocation
            # velocity (growth rate) is above some threshold.
            leaks = ScaleneLeakAnalysis.compute_leaks(
                growth_rate, stats, avg_mallocs, fname
            )

            # Sort in descending order by least likelihood
            leaks = sorted(leaks, key=itemgetter(1), reverse=True)

            reported_leaks = {}

            for leak_lineno, leak_likelihood, leak_velocity in leaks:
                reported_leaks[str(leak_lineno)] = {
                    "likelihood": leak_likelihood,
                    "velocity_mb_s": leak_velocity / stats.elapsed_time,
                }

            # Print header.
            if not stats.cpu_stats.total_cpu_samples:
                percent_cpu_time = 0
            else:
                percent_cpu_time = (
                    100
                    * stats.cpu_stats.cpu_samples[fname]
                    / stats.cpu_stats.total_cpu_samples
                )

            # Print out the the profile for the source, line by line.
            # First try to read from the filesystem
            full_fname = fname
            code_lines = None
            try:
                with open(full_fname, encoding="utf-8") as source_file:
                    code_lines = source_file.readlines()
            except (FileNotFoundError, OSError):
                # For exec'd code, the source may be in linecache
                # (e.g., files named <exec_N> or <eval_N>)
                cached_lines = linecache.getlines(fname)
                if cached_lines:
                    code_lines = cached_lines
            if code_lines is None:
                continue
            # Find all enclosing regions (loops or function defs) for each line of code.

            code_str = "".join(code_lines)

            enclosing_regions = ScaleneAnalysis.find_regions(code_str)
            outer_loop = ScaleneAnalysis.find_outermost_loop(code_str)
            function_boundaries = ScaleneAnalysis.find_functions(code_str)
            imports = ScaleneAnalysis.get_native_imported_modules(code_str)

            output["files"][fname_print] = {
                "percent_cpu_time": percent_cpu_time,
                "lines": [],
                "leaks": reported_leaks,
                "imports": imports,
            }

            # First pass: collect all line profile data
            line_profiles = []
            for lineno, line in enumerate(code_lines, start=1):
                # Protect against JS 'injection' in Python comments by replacing some characters with Unicode.
                # This gets unescaped in scalene-gui.js.
                line = line.replace("&", "\\u0026")
                line = line.replace("<", "\\u003c")
                line = line.replace(">", "\\u003e")
                profile_line = self.output_profile_line(
                    fname=fname,
                    fname_print=fname_print,
                    line_no=LineNumber(lineno),
                    line=line,
                    stats=stats,
                    profile_this_code=profile_this_code,
                    profile_memory=profile_memory,
                    force_print=False,
                )
                if profile_line:
                    profile_line["start_region_line"] = enclosing_regions[lineno][0]
                    profile_line["end_region_line"] = enclosing_regions[lineno][1]
                    profile_line["start_outermost_loop"] = outer_loop[lineno][0]
                    profile_line["end_outermost_loop"] = outer_loop[lineno][1]
                    profile_line["start_function_line"] = function_boundaries[lineno][0]
                    profile_line["end_function_line"] = function_boundaries[lineno][1]
                    line_profiles.append(profile_line)

            # Second pass: normalize CPU percentages to sum to <= 100%
            # This handles cases where torch profiler timing overlaps with
            # signal-sampled timing (e.g., JIT function internals + call site)
            total_cpu = sum(
                p.get("n_cpu_percent_c", 0)
                + p.get("n_cpu_percent_python", 0)
                + p.get("n_sys_percent", 0)
                for p in line_profiles
            )
            if total_cpu > 100.0:
                scale_factor = 100.0 / total_cpu
                for profile_line in line_profiles:
                    profile_line["n_cpu_percent_c"] *= scale_factor
                    profile_line["n_cpu_percent_python"] *= scale_factor
                    profile_line["n_sys_percent"] *= scale_factor

            # Third pass: validate and add to output
            for profile_line in line_profiles:
                try:
                    LineDetail(**profile_line)
                except ValidationError as e:
                    print("Warning: JSON failed validation:")
                    print(e)

                # When reduced-profile set, only output if the payload for the line is non-zero.
                if reduced_profile:
                    profile_line_copy = copy.copy(profile_line)
                    del profile_line_copy["line"]
                    del profile_line_copy["lineno"]
                    if not any(profile_line_copy.values()):
                        continue
                output["files"][fname_print]["lines"].append(profile_line)

            fn_stats = stats.build_function_stats(fname)
            # Check CPU samples and memory samples.
            print_fn_summary = False
            all_samples = set()
            all_samples |= set(fn_stats.cpu_stats.cpu_samples_python.keys())
            all_samples |= set(fn_stats.cpu_stats.cpu_samples_c.keys())
            all_samples |= set(fn_stats.cpu_stats.torch_cpu_time.keys())
            all_samples |= set(fn_stats.cpu_stats.torch_gpu_time.keys())
            all_samples |= set(fn_stats.memory_stats.memory_malloc_samples.keys())
            all_samples |= set(fn_stats.memory_stats.memory_free_samples.keys())
            all_samples |= set(fn_stats.gpu_stats.gpu_samples.keys())
            print_fn_summary = any(fn != fname for fn in all_samples)
            output["files"][fname_print]["functions"] = []
            if print_fn_summary:
                for fn_name in sorted(
                    all_samples,
                    key=lambda k: stats.firstline_map[k],
                ):
                    if fn_name == fname:
                        continue
                    profile_line = self.output_profile_line(
                        fname=fn_name,
                        fname_print=fn_name,
                        # line 1 is where function stats are
                        # accumulated; see
                        # ScaleneStatistics.build_function_stats
                        line_no=LineNumber(1),
                        line=fn_name,  # Set the source line to just the function name.
                        stats=fn_stats,
                        profile_this_code=profile_this_code,
                        profile_memory=profile_memory,
                        force_print=True,
                    )
                    if profile_line:
                        # Fix the line number to point to the first line of the function.
                        profile_line["lineno"] = stats.firstline_map[fn_name]
                        output["files"][fname_print]["functions"].append(profile_line)

        # Validate the schema
        try:
            ScaleneJSONSchema(**output)
        except ValidationError as e:
            print("Warning: JSON failed validation:")
            print(e)
        return output
