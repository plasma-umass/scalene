import os
import random
import sys
import tempfile
from collections import OrderedDict, defaultdict
from operator import itemgetter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from scalene import sparkline
from scalene.scalene_json import ScaleneJSON
from scalene.scalene_leak_analysis import ScaleneLeakAnalysis
from scalene.scalene_statistics import Filename, LineNumber, ScaleneStatistics
from scalene.syntaxline import SyntaxLine


class ScaleneOutput:

    # Maximum entries for sparklines, per file
    max_sparkline_len_file = 27

    # Maximum entries for sparklines, per line
    max_sparkline_len_line = 9

    # Threshold for highlighting lines of code in red.
    highlight_percentage = 33

    # Color for highlighted text (over the threshold of CPU time)
    highlight_color = "bold red"

    # Color for memory consumption
    memory_color = "dark_green"

    # Color for GPU activity
    gpu_color = "yellow4"

    # Color for copy volume
    copy_volume_color = "yellow4"

    def __init__(self) -> None:
        # where we write profile info
        self.output_file = ""

        # if we output HTML or not
        self.html = False

        # if we are on a GPU or not
        self.gpu = False

    # Profile output methods

    def output_top_memory(
        self, title: str, console: Console, mallocs: Dict[LineNumber, float]
    ) -> None:
        if mallocs:
            printed_header = False
            number = 1
            # Print the top N lines by memory consumption, as long
            # as they are above some threshold MB in size.
            print_top_mallocs_count = 5
            print_top_mallocs_threshold_mb = 1
            for malloc_lineno, value in mallocs.items():
                # Don't print lines with less than the threshold MB allocated.
                if value <= print_top_mallocs_threshold_mb:
                    break
                # Only print the top N.
                if number > print_top_mallocs_count:
                    break
                # Print the header only if we are printing something (and only once).
                if not printed_header:
                    console.print(title)
                    printed_header = True
                output_str = f"({str(number)}) {malloc_lineno:5.0f}: {(mallocs[malloc_lineno]):5.0f} MB"
                console.print(Markdown(output_str, style=self.memory_color))
                number += 1

    def output_profile_line(
        self,
        json: ScaleneJSON,
        fname: Filename,
        line_no: LineNumber,
        line: SyntaxLine,
        console: Console,
        tbl: Table,
        stats: ScaleneStatistics,
        profile_this_code: Callable[[Filename, LineNumber], bool],
        force_print: bool = False,
        suppress_lineno_print: bool = False,
        is_function_summary: bool = False,
        profile_memory: bool = False,
        reduced_profile: bool = False,
    ) -> bool:
        """Print at most one line of the profile (true == printed one)."""
        obj = json.output_profile_line(
            fname=fname,
            fname_print=fname,
            line_no=line_no,
            line=str(line),
            stats=stats,
            profile_this_code=profile_this_code,
            force_print=force_print,
        )
        if not obj:
            return False
        if -1 < obj["n_peak_mb"] < 1:
            # Don't print out "-0" or anything below 1.
            obj["n_peak_mb"] = 0

        # Finally, print results.
        n_cpu_percent_c_str: str = (
            ""
            if obj["n_cpu_percent_c"] < 1
            else f"{obj['n_cpu_percent_c']:5.0f}%"
        )

        n_gpu_percent_str: str = (
            "" if obj["n_gpu_percent"] < 1 else f"{obj['n_gpu_percent']:3.0f}%"
        )

        n_cpu_percent_python_str: str = (
            ""
            if obj["n_cpu_percent_python"] < 1
            else f"{obj['n_cpu_percent_python']:5.0f}%"
        )
        n_growth_mem_str = ""
        if obj["n_peak_mb"] < 1024:
            n_growth_mem_str = (
                ""
                if (not obj["n_peak_mb"] and not obj["n_usage_fraction"])
                else f"{obj['n_peak_mb']:5.0f}M"
            )
        else:
            n_growth_mem_str = (
                ""
                if (not obj["n_peak_mb"] and not obj["n_usage_fraction"])
                else f"{(obj['n_peak_mb'] / 1024):5.2f}G"
            )

        # Only report utilization where there is more than 1% CPU total usage.
        sys_str: str = (
            "" if obj["n_sys_percent"] < 1 else f"{obj['n_sys_percent']:4.0f}%"
        )
        if not is_function_summary:
            print_line_no = "" if suppress_lineno_print else str(line_no)
        else:
            print_line_no = (
                ""
                if fname not in stats.firstline_map
                else str(stats.firstline_map[fname])
            )
        if profile_memory:
            spark_str: str = ""
            # Scale the sparkline by the usage fraction.
            samples = obj["memory_samples"]
            # Randomly downsample to ScaleneOutput.max_sparkline_len_line.
            if len(samples) > ScaleneOutput.max_sparkline_len_line:
                random_samples = sorted(
                    random.sample(
                        samples, ScaleneOutput.max_sparkline_len_line
                    )
                )
            else:
                random_samples = samples
            sparkline_samples = [
                random_samples[i][1] * obj["n_usage_fraction"]
                for i in range(len(random_samples))
            ]

            if random_samples:
                _, _, spark_str = sparkline.generate(
                    sparkline_samples, 0, stats.max_footprint
                )

            # Red highlight
            ncpps: Any = ""
            ncpcs: Any = ""
            nufs: Any = ""
            ngpus: Any = ""

            n_usage_fraction_str: str = (
                ""
                if obj["n_usage_fraction"] < 0.01
                else f"{(100 * obj['n_usage_fraction']):4.0f}%"
            )
            if (
                obj["n_usage_fraction"] >= self.highlight_percentage
                or (
                    obj["n_cpu_percent_c"]
                    + obj["n_cpu_percent_python"]
                    + obj["n_gpu_percent"]
                )
                >= self.highlight_percentage
            ):
                ncpps = Text.assemble(
                    (n_cpu_percent_python_str, self.highlight_color)
                )
                ncpcs = Text.assemble(
                    (n_cpu_percent_c_str, self.highlight_color)
                )
                nufs = Text.assemble(
                    (spark_str + n_usage_fraction_str, self.highlight_color)
                )
                ngpus = Text.assemble(
                    (n_gpu_percent_str, self.highlight_color)
                )
            else:
                ncpps = n_cpu_percent_python_str
                ncpcs = n_cpu_percent_c_str
                ngpus = n_gpu_percent_str
                nufs = spark_str + n_usage_fraction_str

            if reduced_profile and not ncpps + ncpcs + nufs + ngpus:
                return False

            n_python_fraction_str: str = (
                ""
                if obj["n_python_fraction"] < 0.01
                else f"{(obj['n_python_fraction'] * 100):4.0f}%"
            )
            n_copy_mb_s_str: str = (
                ""
                if obj["n_copy_mb_s"] < 0.5
                else f"{obj['n_copy_mb_s']:6.0f}"
            )

            if self.gpu:
                tbl.add_row(
                    print_line_no,
                    ncpps,  # n_cpu_percent_python_str,
                    ncpcs,  # n_cpu_percent_c_str,
                    sys_str,
                    ngpus,
                    n_python_fraction_str,
                    n_growth_mem_str,
                    nufs,  # spark_str + n_usage_fraction_str,
                    n_copy_mb_s_str,
                    line,
                )
            else:
                tbl.add_row(
                    print_line_no,
                    ncpps,  # n_cpu_percent_python_str,
                    ncpcs,  # n_cpu_percent_c_str,
                    sys_str,
                    n_python_fraction_str,
                    n_growth_mem_str,
                    nufs,  # spark_str + n_usage_fraction_str,
                    n_copy_mb_s_str,
                    line,
                )
        else:

            # Red highlight
            if (
                obj["n_cpu_percent_c"]
                + obj["n_cpu_percent_python"]
                + obj["n_gpu_percent"]
            ) >= self.highlight_percentage:
                ncpps = Text.assemble(
                    (n_cpu_percent_python_str, self.highlight_color)
                )
                ncpcs = Text.assemble(
                    (n_cpu_percent_c_str, self.highlight_color)
                )
                ngpus = Text.assemble(
                    (n_gpu_percent_str, self.highlight_color)
                )
            else:
                ncpps = n_cpu_percent_python_str
                ncpcs = n_cpu_percent_c_str
                ngpus = n_gpu_percent_str

            if reduced_profile and not ncpps + ncpcs + ngpus:
                return False
            if self.gpu:
                tbl.add_row(
                    print_line_no,
                    ncpps,  # n_cpu_percent_python_str,
                    ncpcs,  # n_cpu_percent_c_str,
                    sys_str,
                    ngpus,  # n_gpu_percent_str
                    line,
                )
            else:
                tbl.add_row(
                    print_line_no,
                    ncpps,  # n_cpu_percent_python_str,
                    ncpcs,  # n_cpu_percent_c_str,
                    sys_str,
                    line,
                )

        return True

    def output_profiles(
        self,
        column_width: int,
        stats: ScaleneStatistics,
        pid: int,
        profile_this_code: Callable[[Filename, LineNumber], bool],
        python_alias_dir: Path,
        program_path: Filename,
        program_args: Optional[List[str]],
        profile_memory: bool = True,
        reduced_profile: bool = False,
    ) -> bool:
        """Write the profile out."""
        # Get the children's stats, if any.
        json = ScaleneJSON()
        json.gpu = self.gpu
        if not pid:
            stats.merge_stats(python_alias_dir)
        # If we've collected any samples, dump them.
        if (
            not stats.total_cpu_samples
            and not stats.total_memory_malloc_samples
            and not stats.total_memory_free_samples
        ):
            # Nothing to output.
            return False
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
            return False
        mem_usage_line: Union[Text, str] = ""
        growth_rate = 0.0
        if profile_memory:
            samples = stats.memory_footprint_samples
            if len(samples) > 0:
                # Randomly downsample samples
                if len(samples) > ScaleneOutput.max_sparkline_len_file:
                    random_samples = sorted(
                        random.sample(
                            samples, ScaleneOutput.max_sparkline_len_file
                        )
                    )
                else:
                    random_samples = samples
                sparkline_samples = [item[1] for item in random_samples]
                # Output a sparkline as a summary of memory usage over time.
                _, _, spark_str = sparkline.generate(
                    sparkline_samples[: ScaleneOutput.max_sparkline_len_file],
                    0,
                    stats.max_footprint,
                )
                # Compute growth rate (slope), between 0 and 1.
                if stats.allocation_velocity[1] > 0:
                    growth_rate = (
                        100.0
                        * stats.allocation_velocity[0]
                        / stats.allocation_velocity[1]
                    )
                mem_usage_line = Text.assemble(
                    "Memory usage: ",
                    ((spark_str, self.memory_color)),
                    (
                        f" (max: {ScaleneJSON.memory_consumed_str(stats.max_footprint)}, growth rate: {growth_rate:3.0f}%)\n"
                    ),
                )

        null = tempfile.TemporaryFile(mode="w+")

        console = Console(
            width=column_width,
            record=True,
            force_terminal=True,
            file=null,
            force_jupyter=False,
        )
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
                stats.malloc_samples[fname] < ScaleneJSON.malloc_threshold
                and percent_cpu_time < ScaleneJSON.cpu_percent_threshold
            ):
                continue
            report_files.append(fname)

        # Don't actually output the profile if we are a child process.
        # Instead, write info to disk for the main process to collect.
        if pid:
            stats.output_stats(pid, python_alias_dir)
            return True

        if not report_files:
            return False

        for fname in report_files:

            # If the file was actually a Jupyter (IPython) cell,
            # restore its name, as in "[12]".
            fname_print = fname
            import re

            if result := re.match("_ipython-input-([0-9]+)-.*", fname_print):
                fname_print = Filename(f"[{result.group(1)}]")

            # Print header.
            percent_cpu_time = (
                (100 * stats.cpu_samples[fname] / stats.total_cpu_samples)
                if stats.total_cpu_samples
                else 0
            )

            new_title = mem_usage_line + (
                f"{fname_print}: % of time = {percent_cpu_time:6.2f}% ({ScaleneJSON.time_consumed_str(percent_cpu_time / 100.0 * stats.elapsed_time * 1e3)}) out of {ScaleneJSON.time_consumed_str(stats.elapsed_time * 1e3)}."
            )
            # Only display total memory usage once.
            mem_usage_line = ""

            tbl = Table(
                box=box.MINIMAL_HEAVY_HEAD,
                title=new_title,
                collapse_padding=True,
                width=column_width - 1,
            )

            tbl.add_column(
                Markdown("Line", style="dim"),
                style="dim",
                justify="right",
                no_wrap=True,
                width=4,
            )
            tbl.add_column(
                Markdown("Time  " + "\n" + "_Python_", style="blue"),
                style="blue",
                no_wrap=True,
                width=6,
            )
            tbl.add_column(
                Markdown("––––––  \n_native_", style="blue"),
                style="blue",
                no_wrap=True,
                width=6,
            )
            tbl.add_column(
                Markdown("––––––  \n_system_", style="blue"),
                style="blue",
                no_wrap=True,
                width=6,
            )
            if self.gpu:
                tbl.add_column(
                    Markdown("––––––  \n_GPU_", style=self.gpu_color),
                    style=self.gpu_color,
                    no_wrap=True,
                    width=6,
                )

            other_columns_width = 0  # Size taken up by all columns BUT code

            if profile_memory:
                tbl.add_column(
                    Markdown("Memory  \n_Python_", style=self.memory_color),
                    style=self.memory_color,
                    no_wrap=True,
                    width=7,
                )
                tbl.add_column(
                    Markdown("––––––  \n_peak_", style=self.memory_color),
                    style=self.memory_color,
                    no_wrap=True,
                    width=6,
                )
                tbl.add_column(
                    Markdown(
                        "–––––––––––  \n_timeline_/%", style=self.memory_color
                    ),
                    style=self.memory_color,
                    no_wrap=True,
                    width=15,
                )
                tbl.add_column(
                    Markdown("Copy  \n_(MB/s)_", style=self.copy_volume_color),
                    style=self.copy_volume_color,
                    no_wrap=True,
                    width=6,
                )
                other_columns_width = 75 + (6 if self.gpu else 0)
            else:
                other_columns_width = 37 + (5 if self.gpu else 0)
            tbl.add_column(
                "\n" + fname_print,
                width=column_width - other_columns_width,
                no_wrap=True,
            )
            # Print out the the profile for the source, line by line.
            if fname == "<BOGUS>":
                continue
            if not fname:
                continue
            # Print out the profile for the source, line by line.
            full_fname = os.path.normpath(os.path.join(program_path, fname))
            try:
                with open(full_fname, "r") as source_file:
                    code_lines = source_file.read()
            except (FileNotFoundError, OSError):
                continue

            # We track whether we should put in ellipsis (for reduced profiles)
            # or not.
            did_print = True  # did we print a profile line last time?
            # Generate syntax highlighted version for the whole file,
            # which we will consume a line at a time.
            # See https://github.com/willmcgugan/rich/discussions/965#discussioncomment-314233
            syntax_highlighted = Syntax(
                code_lines,
                "python",
                theme="default" if self.html else "vim",
                line_numbers=False,
                code_width=None,
            )
            capture_console = Console(
                width=column_width - other_columns_width,
                force_terminal=True,
            )
            formatted_lines = [
                SyntaxLine(segments)
                for segments in capture_console.render_lines(
                    syntax_highlighted
                )
            ]
            for line_no, line in enumerate(formatted_lines, start=1):
                old_did_print = did_print
                did_print = self.output_profile_line(
                    json=json,
                    fname=fname,
                    line_no=LineNumber(line_no),
                    line=line,
                    console=console,
                    tbl=tbl,
                    stats=stats,
                    profile_this_code=profile_this_code,
                    profile_memory=profile_memory,
                    force_print=False,
                    suppress_lineno_print=False,
                    is_function_summary=False,
                    reduced_profile=reduced_profile,
                )
                if old_did_print and not did_print:
                    # We are skipping lines, so add an ellipsis.
                    tbl.add_row("...")
                old_did_print = did_print

            # Potentially print a function summary.
            fn_stats = stats.build_function_stats(fname)
            print_fn_summary = False
            # Check CPU samples and memory samples.
            all_samples = set()
            all_samples |= set(fn_stats.cpu_samples_python.keys())
            all_samples |= set(fn_stats.cpu_samples_c.keys())
            all_samples |= set(fn_stats.memory_malloc_samples.keys())
            all_samples |= set(fn_stats.memory_free_samples.keys())
            for fn_name in all_samples:
                if fn_name == fname:
                    continue
                print_fn_summary = True
                break

            if print_fn_summary:
                try:
                    tbl.add_row(None, end_section=True)
                except TypeError:  # rich < 9.4.0 compatibility
                    tbl.add_row(None)
                txt = Text.assemble(
                    f"function summary for {fname_print}", style="bold italic"
                )
                if profile_memory:
                    if self.gpu:
                        tbl.add_row("", "", "", "", "", "", "", "", "", txt)
                    else:
                        tbl.add_row("", "", "", "", "", "", "", "", txt)
                elif self.gpu:
                    tbl.add_row("", "", "", "", "", txt)
                else:
                    tbl.add_row("", "", "", "", txt)

                for fn_name in sorted(
                    fn_stats.cpu_samples_python,
                    key=lambda k: stats.firstline_map[k],
                ):
                    if fn_name == fname:
                        continue
                    syntax_highlighted = Syntax(
                        fn_name,
                        "python",
                        theme="default" if self.html else "vim",
                        line_numbers=False,
                        code_width=None,
                    )
                    # force print, suppress line numbers
                    self.output_profile_line(
                        json=json,
                        fname=fn_name,
                        line_no=LineNumber(1),
                        line=syntax_highlighted,  # type: ignore
                        console=console,
                        tbl=tbl,
                        stats=fn_stats,
                        profile_this_code=profile_this_code,
                        profile_memory=profile_memory,
                        force_print=True,
                        suppress_lineno_print=True,
                        is_function_summary=True,
                        reduced_profile=reduced_profile,
                    )

            console.print(tbl)

            # Compute AVERAGE memory consumption.
            avg_mallocs: Dict[LineNumber, float] = defaultdict(float)
            for line_no in stats.bytei_map[fname]:
                n_malloc_mb = stats.memory_aggregate_footprint[fname][line_no]
                if count := stats.memory_malloc_count[fname][line_no]:
                    avg_mallocs[line_no] = n_malloc_mb / count
                else:
                    # Setting to n_malloc_mb addresses the edge case where this allocation is the last line executed.
                    avg_mallocs[line_no] = n_malloc_mb

            avg_mallocs = OrderedDict(
                sorted(avg_mallocs.items(), key=itemgetter(1), reverse=True)
            )

            # Compute (really, aggregate) PEAK memory consumption.
            peak_mallocs: Dict[LineNumber, float] = defaultdict(float)
            for line_no in stats.bytei_map[fname]:
                peak_mallocs[line_no] = stats.memory_max_footprint[fname][
                    line_no
                ]

            peak_mallocs = OrderedDict(
                sorted(peak_mallocs.items(), key=itemgetter(1), reverse=True)
            )

            # Print the top N lines by AVERAGE memory consumption, as long
            # as they are above some threshold MB in size.
            self.output_top_memory(
                "Top AVERAGE memory consumption, by line:",
                console,
                avg_mallocs,
            )

            # Print the top N lines by PEAK memory consumption, as long
            # as they are above some threshold MB in size.
            self.output_top_memory(
                "Top PEAK memory consumption, by line:", console, peak_mallocs
            )

            # Only report potential leaks if the allocation velocity (growth rate) is above some threshold.
            leaks = ScaleneLeakAnalysis.compute_leaks(
                growth_rate, stats, avg_mallocs, fname
            )

            if len(leaks) > 0:
                # Report in descending order by least likelihood
                for leak in sorted(leaks, key=itemgetter(1), reverse=True):
                    output_str = f"Possible memory leak identified at line {str(leak[0])} (estimated likelihood: {(leak[1] * 100):3.0f}%, velocity: {(leak[2] / stats.elapsed_time):3.0f} MB/s)"
                    console.print(output_str)

        if self.html:
            # Write HTML file.
            md = Markdown(
                "generated by the [scalene](https://github.com/plasma-umass/scalene) profiler"
            )
            console.print(md)
            if not self.output_file:
                self.output_file = "/dev/stdout"
            console.save_html(self.output_file, clear=False)
        elif self.output_file:
            # Don't output styles to text file.
            console.save_text(self.output_file, styles=False, clear=False)
        else:
            # No output file specified: write to stdout.
            sys.stdout.write(console.export_text(styles=True))
        return True
