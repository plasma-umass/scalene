import copy
import os
import random
import re
import sys

from collections import OrderedDict, defaultdict
from operator import itemgetter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from scalene.scalene_leak_analysis import ScaleneLeakAnalysis
from scalene.scalene_statistics import Filename, LineNumber, ScaleneStatistics
from scalene.scalene_analysis import ScaleneAnalysis

if sys.platform != "win32":
    from scalene.crdp import rdp


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

    def compress_samples(
        self, samples: List[Any], max_footprint: float
    ) -> Any:
        if len(samples) <= self.max_sparkline_samples:
            return samples
        # Try to reduce the number of samples with the
        # Ramer-Douglas-Peucker algorithm, which attempts to
        # preserve the shape of the graph. If that fails to bring
        # the number of samples below our maximum, randomly
        # downsample (epsilon calculation from
        # https://stackoverflow.com/questions/57052434/can-i-guess-the-appropriate-epsilon-for-rdp-ramer-douglas-peucker)
        epsilon = (len(samples) / (3 * self.max_sparkline_samples)) * 2
        # print("BEFORE len = ", len(samples))
        new_samples = rdp(samples, epsilon=epsilon)
        # print("AFTER len = ", len(new_samples))
        if len(new_samples) > self.max_sparkline_samples:
            # We still didn't get enough compression; randomly downsample.
            new_samples = sorted(
                random.sample(new_samples, self.max_sparkline_samples)
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

        if not force_print and not profile_this_code(fname, line_no):
            return {
                "lineno": line_no,
                "line": line,
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
        n_cpu_samples_c = stats.cpu_samples_c[fname][line_no]
        # Correct for negative CPU sample counts. This can happen
        # because of floating point inaccuracies, since we perform
        # subtraction to compute it.
        n_cpu_samples_c = max(0, n_cpu_samples_c)
        n_cpu_samples_python = stats.cpu_samples_python[fname][line_no]
        n_gpu_samples = stats.gpu_samples[fname][line_no]
        n_gpu_mem_samples = stats.gpu_mem_samples[fname][line_no]

        # Compute percentages of CPU time.
        if stats.total_cpu_samples:
            n_cpu_percent_c = n_cpu_samples_c * 100 / stats.total_cpu_samples
            n_cpu_percent_python = (
                n_cpu_samples_python * 100 / stats.total_cpu_samples
            )
        else:
            n_cpu_percent_c = 0
            n_cpu_percent_python = 0

        if stats.total_gpu_samples:
            n_gpu_percent = n_gpu_samples * 100 / stats.total_gpu_samples
        else:
            n_gpu_percent = 0

        # Now, memory stats.
        # Total volume of memory allocated.
        n_malloc_mb = stats.memory_malloc_samples[fname][line_no]
        # Number of distinct allocation calls (those from the same line are counted as 1).
        n_mallocs = stats.memory_malloc_count[fname][line_no]
        # Total volume of memory allocated by Python (not native code).
        n_python_malloc_mb = stats.memory_python_samples[fname][line_no]

        n_usage_fraction = (
            0
            if not stats.total_memory_malloc_samples
            else n_malloc_mb / stats.total_memory_malloc_samples
        )
        n_python_fraction = (
            0 if not n_malloc_mb else n_python_malloc_mb / n_malloc_mb
        )

        # Average memory consumed by this line.
        n_avg_mb = (
            stats.memory_aggregate_footprint[fname][line_no]
            if n_mallocs == 0
            else stats.memory_aggregate_footprint[fname][line_no] / n_mallocs
        )

        # Peak memory consumed by this line.
        n_peak_mb = stats.memory_max_footprint[fname][line_no]

        # Force the reporting of average to be no more than peak.
        # In principle, this should never happen, but...
        # assert n_avg_mb <= n_peak_mb
        if n_avg_mb > n_peak_mb:
            n_avg_mb = n_peak_mb

        n_cpu_percent = n_cpu_percent_c + n_cpu_percent_python

        # Adjust CPU time by utilization.
        mean_cpu_util = stats.cpu_utilization[fname][line_no].mean()
        mean_core_util = stats.core_utilization[fname][line_no].mean()
        n_sys_percent = n_cpu_percent * (1.0 - mean_cpu_util)
        n_cpu_percent_python *= mean_cpu_util
        n_cpu_percent_c *= mean_cpu_util
        del mean_cpu_util

        n_copy_b = stats.memcpy_samples[fname][line_no]
        if stats.elapsed_time:
            n_copy_mb_s = n_copy_b / (1024 * 1024 * stats.elapsed_time)
        else:
            n_copy_mb_s = 0

        stats.per_line_footprint_samples[fname][
            line_no
        ] = self.compress_samples(
            stats.per_line_footprint_samples[fname][line_no],
            stats.max_footprint,
        )

        return {
            "lineno": line_no,
            "line": line,
            "n_core_utilization": mean_core_util,
            "n_cpu_percent_c": n_cpu_percent_c,
            "n_cpu_percent_python": n_cpu_percent_python,
            "n_sys_percent": n_sys_percent,
            "n_gpu_percent": n_gpu_percent,
            "n_gpu_avg_memory_mb": n_gpu_mem_samples.mean(),
            "n_gpu_peak_memory_mb": n_gpu_mem_samples.peak(),
            "n_peak_mb": n_peak_mb,
            "n_growth_mb": n_peak_mb,  # For backwards compatibility
            "n_avg_mb": n_avg_mb,
            "n_mallocs": n_mallocs,
            "n_malloc_mb": n_malloc_mb,
            "n_usage_fraction": n_usage_fraction,
            "n_python_fraction": n_python_fraction,
            "n_copy_mb_s": n_copy_mb_s,
            "memory_samples": stats.per_line_footprint_samples[fname][line_no],
        }

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
            not stats.total_cpu_samples
            and not stats.total_memory_malloc_samples
            and not stats.total_memory_free_samples
        ):
            # Nothing to output.
            return {}
        # Collect all instrumented filenames.
        all_instrumented_files: List[Filename] = list(
            set(
                list(stats.cpu_samples_python.keys())
                + list(stats.cpu_samples_c.keys())
                + list(stats.memory_free_samples.keys())
                + list(stats.memory_malloc_samples.keys())
            )
        )
        if not all_instrumented_files:
            # We didn't collect samples in source files.
            return {}
        growth_rate = 0.0
        if profile_memory:
            stats.memory_footprint_samples = self.compress_samples(
                stats.memory_footprint_samples, stats.max_footprint
            )

            # Compute growth rate (slope), between 0 and 1.
            if stats.allocation_velocity[1] > 0:
                growth_rate = (
                    100.0
                    * stats.allocation_velocity[0]
                    / stats.allocation_velocity[1]
                )
        else:
            stats.memory_footprint_samples = []

        # Adjust the program name if it was a Jupyter cell.
        result = re.match(r"_ipython-input-([0-9]+)-.*", program)
        if result:
            program = Filename("[" + result.group(1) + "]")

        # Process the stacks to normalize by total number of CPU samples.
        for stk in stats.stacks.keys():
            (count, python_time, c_time, cpu_samples) = stats.stacks[stk]
            stats.stacks[stk] = (count,
                                 python_time / stats.total_cpu_samples,
                                 c_time / stats.total_cpu_samples,
                                 cpu_samples / stats.total_cpu_samples)
            
        # Convert stacks into a representation suitable for JSON dumping.
        stks = []
        for stk in stats.stacks.keys():
            this_stk: List[str] = []
            this_stk.extend(stk)
            stks.append((this_stk, stats.stacks[stk]))

        output: Dict[str, Any] = {
            "program": program,
            "entrypoint_dir": entrypoint_dir,
            "args": program_args,
            "filename": program_path,
            "alloc_samples": stats.alloc_samples,
            "elapsed_time_sec": stats.elapsed_time,
            "growth_rate": growth_rate,
            "max_footprint_mb": stats.max_footprint,
            "max_footprint_python_fraction" : stats.max_footprint_python_fraction,
            "max_footprint_fname": stats.max_footprint_loc[0]
            if stats.max_footprint_loc
            else None,
            "max_footprint_lineno": stats.max_footprint_loc[1]
            if stats.max_footprint_loc
            else None,
            "files": {},
            "gpu": self.gpu,
            "memory": profile_memory,
            "samples": stats.memory_footprint_samples,
            "stacks": stks,
        }

        # Build a list of files we will actually report on.
        report_files: List[Filename] = []
        # Sort in descending order of CPU cycles, and then ascending order by filename
        for fname in sorted(
            all_instrumented_files,
            key=lambda f: (-(stats.cpu_samples[f]), f),
        ):
            fname = Filename(fname)
            try:
                percent_cpu_time = (
                    100
                    * stats.cpu_samples[fname]
                    / stats.elapsed_time
                    # 100 * stats.cpu_samples[fname] / stats.total_cpu_samples
                )
            except ZeroDivisionError:
                percent_cpu_time = 0

            # Ignore files responsible for less than some percent of execution time and fewer than a threshold # of mallocs.
            if (
                stats.malloc_samples[fname] < self.malloc_threshold
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
            for line_no in stats.bytei_map[fname]:
                n_malloc_mb = stats.memory_aggregate_footprint[fname][line_no]
                count = stats.memory_malloc_count[fname][line_no]
                if count:
                    avg_mallocs[line_no] = n_malloc_mb / count
                else:
                    # Setting to n_malloc_mb addresses the edge case where this allocation is the last line executed.
                    avg_mallocs[line_no] = n_malloc_mb

            avg_mallocs = OrderedDict(
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

            for (leak_lineno, leak_likelihood, leak_velocity) in leaks:
                reported_leaks[str(leak_lineno)] = {
                    "likelihood": leak_likelihood,
                    "velocity_mb_s": leak_velocity / stats.elapsed_time,
                }

            # Print header.
            if not stats.total_cpu_samples:
                percent_cpu_time = 0
            else:
                percent_cpu_time = (
                    100 * stats.cpu_samples[fname] / stats.total_cpu_samples
                )

            # Print out the the profile for the source, line by line.
            full_fname = fname
            try:
                with open(full_fname, "r", encoding="utf-8") as source_file:
                    code_lines = source_file.readlines()

            except (FileNotFoundError, OSError):
                continue
            # Find all enclosing regions (loops or function defs) for each line of code.

            code_str = "".join(code_lines)

            enclosing_regions = ScaleneAnalysis.find_regions(code_str)
            outer_loop = ScaleneAnalysis.find_outermost_loop(code_str)
            imports = ScaleneAnalysis.get_native_imported_modules(code_str)

            output["files"][fname_print] = {
                "percent_cpu_time": percent_cpu_time,
                "lines": [],
                "leaks": reported_leaks,
                "imports": imports,
            }
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
                    profile_line["start_region_line"] = enclosing_regions[
                        lineno
                    ][0]
                    profile_line["end_region_line"] = enclosing_regions[
                        lineno
                    ][1]
                    profile_line["start_outermost_loop"] = outer_loop[lineno][
                        0
                    ]
                    profile_line["end_outermost_loop"] = outer_loop[lineno][1]
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
            all_samples |= set(fn_stats.cpu_samples_python.keys())
            all_samples |= set(fn_stats.cpu_samples_c.keys())
            all_samples |= set(fn_stats.memory_malloc_samples.keys())
            all_samples |= set(fn_stats.memory_free_samples.keys())
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
                        output["files"][fname_print]["functions"].append(
                            profile_line
                        )

        return output
