import copy
import linecache
from pathlib import Path
from typing import Any, Callable, Dict, List

from scalene.scalene_statistics import Filename, LineNumber, ScaleneStatistics


class ScaleneJSON:

    # Default threshold for percent of CPU time to report a file.
    cpu_percent_threshold = 1

    # Default threshold for number of mallocs to report a file.
    malloc_threshold = 1  # 100

    def __init__(self) -> None:
        # where we write profile info
        self.output_file = ""

        # if we are on a GPU or not
        self.gpu = False

    # Profile output methods
    def output_profile_line(
        self,
        *,
        fname: Filename,
        fname_print: Filename,
        line_no: LineNumber,
        stats: ScaleneStatistics,
        profile_this_code: Callable[[Filename, LineNumber], bool],
        profile_memory: bool = False,
        force_print: bool = False,
    ) -> Dict[str, Any]:
        """Print at most one line of the profile (true == printed one)."""
        if not force_print and not profile_this_code(fname, line_no):
            return {}
        # Prepare output values.
        n_cpu_samples_c = stats.cpu_samples_c[fname][line_no]
        # Correct for negative CPU sample counts. This can happen
        # because of floating point inaccuracies, since we perform
        # subtraction to compute it.
        if n_cpu_samples_c < 0:
            n_cpu_samples_c = 0
        n_cpu_samples_python = stats.cpu_samples_python[fname][line_no]
        n_gpu_samples = stats.gpu_samples[fname][line_no]

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
            0
            if not n_malloc_mb
            else n_python_malloc_mb / stats.total_memory_malloc_samples
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
        n_sys_percent = n_cpu_percent * (1.0 - mean_cpu_util)
        n_cpu_percent_python *= mean_cpu_util
        n_cpu_percent_c *= mean_cpu_util
        del mean_cpu_util

        n_copy_b = stats.memcpy_samples[fname][line_no]
        if stats.elapsed_time:
            n_copy_mb_s = n_copy_b / (1024 * 1024 * stats.elapsed_time)
        else:
            n_copy_mb_s = 0

        samples = stats.per_line_footprint_samples[fname][line_no] # FIXME
        #if not any(samples):
        #    samples = []
        return {
            "lineno": line_no,
            "line": linecache.getline(fname, line_no),
            "n_cpu_percent_c": n_cpu_percent_c,
            "n_cpu_percent_python": n_cpu_percent_python,
            "n_sys_percent": n_sys_percent,
            "n_gpu_percent": n_gpu_percent,
            "n_peak_mb": n_peak_mb,
            "n_growth_mb": n_peak_mb,  # For backwards compatibility
            "n_avg_mb": n_avg_mb,
            "n_mallocs": n_mallocs,
            "n_malloc_mb": n_malloc_mb,
            "n_usage_fraction": n_usage_fraction,
            "n_python_fraction": n_python_fraction,
            "n_copy_mb_s": n_copy_mb_s,
            "memory_samples": samples,
        }

    def output_profiles(
        self,
        stats: ScaleneStatistics,
        pid: int,
        profile_this_code: Callable[[Filename, LineNumber], bool],
        python_alias_dir: Path,
        profile_memory: bool = True,
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
            samples = stats.memory_footprint_samples
            # Compute growth rate (slope), between 0 and 1.
            if stats.allocation_velocity[1] > 0:
                growth_rate = (
                    100.0
                    * stats.allocation_velocity[0]
                    / stats.allocation_velocity[1]
                )
        else:
            samples = []

        output: Dict[str, Any] = {
            "elapsed_time_sec": stats.elapsed_time,
            "growth_rate": growth_rate,
            "samples": samples,
            "max_footprint_mb": stats.max_footprint,
            "files": {},
            "gpu": self.gpu,
            "memory": profile_memory
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
                    100 * stats.cpu_samples[fname] / stats.total_cpu_samples
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
            return {}

        if len(report_files) == 0:
            return {}

        for fname in report_files:

            # If the file was actually a Jupyter (IPython) cell,
            # restore its name, as in "[12]".
            fname_print = fname
            import re

            result = re.match("<ipython-input-([0-9]+)-.*>", fname_print)
            if result:
                fname_print = Filename("[" + result.group(1) + "]")

            # Print header.
            if not stats.total_cpu_samples:
                percent_cpu_time = 0
            else:
                percent_cpu_time = (
                    100 * stats.cpu_samples[fname] / stats.total_cpu_samples
                )

            # Print out the the profile for the source, line by line.
            with open(fname, "r", encoding="utf-8") as source_file:
                code_lines = source_file.readlines()
                
                output["files"][fname_print] = {
                    "percent_cpu_time": percent_cpu_time,
                    "lines": [],
                }
                for line_no, line in enumerate(code_lines, start=1):
                    o = self.output_profile_line(
                        fname=fname,
                        fname_print=fname_print,
                        line_no=LineNumber(line_no),
                        stats=stats,
                        profile_this_code=profile_this_code,
                        profile_memory=profile_memory,
                        force_print=False,
                    )
                    # o["percent_cpu_time"] = percent_cpu_time
                    # o["elapsed_time"] = stats.elapsed_time
                    # Only output if the payload for the line is non-zero.
                    if o:
                        o_copy = copy.copy(o)
                        del o_copy["line"]
                        del o_copy["lineno"]
                        if any(o_copy.values()):
                            output["files"][fname_print]["lines"].append(o)
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
                    o = self.output_profile_line(
                        fname=fn_name,
                        fname_print=fn_name,
                        # line 1 is where function stats are
                        # accumulated; see
                        # ScaleneStatistics.build_function_stats
                        line_no=LineNumber(1),
                        stats=fn_stats,
                        profile_this_code=profile_this_code,
                        profile_memory=profile_memory,
                        force_print=True,
                    )
                    if o:
                        # Change the source code to just the function name.
                        o["line"] = fn_name
                        # Fix the line number to point to the first line of the function.
                        o["lineno"] = stats.firstline_map[fn_name]
                        output["files"][fname_print]["functions"].append(o)

        return output
