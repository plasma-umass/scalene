import shutil
import sys

from collections import OrderedDict
from operator import itemgetter
from rich.console import Console
from rich.markdown import Markdown
from rich.segment import Segment
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich import box

from scalene import sparkline
from scalene.syntaxline import SyntaxLine
from scalene.scalene_statistics import *

from typing import Callable, Union

class ScaleneOutput:

    # where we write profile info
    output_file: str = ""

    # if we output HTML or not
    html: bool = False

    # Threshold for highlighting lines of code in red.
    highlight_percentage = 33

    # Default threshold for percent of CPU time to report a file.
    cpu_percent_threshold = 1

    # Default threshold for number of mallocs to report a file.
    malloc_threshold = 100

    # reduced profile?
    reduced_profile: bool = False
    
        
    # Profile output methods
    def output_profile_line(
            self,
        fname: Filename,
        line_no: LineNumber,
        line: SyntaxLine,
        console: Console,
        tbl: Table,
        stats: ScaleneStatistics,
        profile_this_code : Callable[[Filename, LineNumber], bool],
        force_print: bool = False,
        suppress_lineno_print: bool = False,
        is_function_summary: bool = False
    ) -> bool:
        """Print at most one line of the profile (true == printed one)."""
        if not force_print and not profile_this_code(fname, line_no):
            return False
        current_max = stats.max_footprint
        did_sample_memory: bool = (
            stats.total_memory_free_samples + stats.total_memory_malloc_samples
        ) > 0
        # Prepare output values.
        n_cpu_samples_c = stats.cpu_samples_c[fname][line_no]
        # Correct for negative CPU sample counts. This can happen
        # because of floating point inaccuracies, since we perform
        # subtraction to compute it.
        if n_cpu_samples_c < 0:
            n_cpu_samples_c = 0
        n_cpu_samples_python = stats.cpu_samples_python[fname][line_no]

        # Compute percentages of CPU time.
        if stats.total_cpu_samples != 0:
            n_cpu_percent_c = n_cpu_samples_c * 100 / stats.total_cpu_samples
            n_cpu_percent_python = (
                n_cpu_samples_python * 100 / stats.total_cpu_samples
            )
        else:
            n_cpu_percent_c = 0
            n_cpu_percent_python = 0

        # Now, memory stats.
        # Accumulate each one from every byte index.
        n_malloc_mb = 0.0
        n_python_malloc_mb = 0.0
        n_free_mb = 0.0
        for index in stats.bytei_map[fname][line_no]:
            mallocs = stats.memory_malloc_samples[fname][line_no][index]
            n_malloc_mb += mallocs
            n_python_malloc_mb += stats.memory_python_samples[fname][line_no][
                index
            ]
            frees = stats.memory_free_samples[fname][line_no][index]
            n_free_mb += frees

        n_usage_fraction = (
            0
            if not stats.total_memory_malloc_samples
            else n_malloc_mb / stats.total_memory_malloc_samples
        )
        n_python_fraction = (
            0
            if not n_malloc_mb
            else n_python_malloc_mb
            / stats.total_memory_malloc_samples  # was / n_malloc_mb
        )

        if False:
            # Currently disabled; possibly use in another column?
            # Correct for number of samples
            for bytei in stats.memory_malloc_count[fname][
                line_no
            ]:  # type : ignore
                n_malloc_mb /= stats.memory_malloc_count[fname][line_no][bytei]
                n_python_malloc_mb /= stats.memory_malloc_count[fname][
                    line_no
                ][bytei]
            for bytei in stats.memory_free_count[fname][line_no]:
                n_free_mb /= stats.memory_free_count[fname][line_no][bytei]

        n_growth_mb = n_malloc_mb - n_free_mb
        if -1 < n_growth_mb < 0:
            # Don't print out "-0".
            n_growth_mb = 0

        # Finally, print results.
        n_cpu_percent_c_str: str = (
            "" if n_cpu_percent_c < 1 else "%5.0f%%" % n_cpu_percent_c
        )
        n_cpu_percent_python_str: str = (
            ""
            if n_cpu_percent_python < 1
            else "%5.0f%%" % n_cpu_percent_python
        )
        n_growth_mb_str: str = (
            ""
            if (not n_growth_mb and not n_usage_fraction)
            else "%5.0f" % n_growth_mb
        )
        n_usage_fraction_str: str = (
            ""
            if n_usage_fraction < 0.01
            else "%3.0f%%" % (100 * n_usage_fraction)
        )
        n_python_fraction_str: str = (
            ""
            if n_python_fraction < 0.01
            else "%5.0f%%" % (100 * n_python_fraction)
        )
        n_copy_b = stats.memcpy_samples[fname][line_no]
        n_copy_mb_s = n_copy_b / (1024 * 1024 * stats.elapsed_time)
        n_copy_mb_s_str: str = (
            "" if n_copy_mb_s < 0.5 else "%6.0f" % n_copy_mb_s
        )

        n_cpu_percent = n_cpu_percent_c + n_cpu_percent_python
        # Only report utilization where there is more than 1% CPU total usage,
        # and the standard error of the mean is low (meaning it's an accurate estimate).
        sys_str: str = (
            ""
            if n_cpu_percent < 1
            or stats.cpu_utilization[fname][line_no].size() <= 1
            or stats.cpu_utilization[fname][line_no].sem() > 0.025
            or stats.cpu_utilization[fname][line_no].mean() > 0.99
            else "%3.0f%%"
            % (
                n_cpu_percent
                * (1.0 - (stats.cpu_utilization[fname][line_no].mean()))
            )
        )
        if not is_function_summary:
            print_line_no = "" if suppress_lineno_print else str(line_no)
        else:
            print_line_no = "" if fname not in stats.firstline_map else str(stats.firstline_map[fname])
        if did_sample_memory:
            spark_str: str = ""
            # Scale the sparkline by the usage fraction.
            samples = stats.per_line_footprint_samples[fname][line_no]
            for i in range(0, len(samples.get())):
                samples.get()[i] *= n_usage_fraction
            if samples.get():
                _, _, spark_str = sparkline.generate(
                    samples.get()[0 : samples.len()], 0, current_max
                )

            # Red highlight
            ncpps: Any = ""
            ncpcs: Any = ""
            nufs: Any = ""
            if (
                n_usage_fraction >= self.highlight_percentage
                or (n_cpu_percent_c + n_cpu_percent_python)
                >= self.highlight_percentage
            ):
                ncpps = Text.assemble((n_cpu_percent_python_str, "bold red"))
                ncpcs = Text.assemble((n_cpu_percent_c_str, "bold red"))
                nufs = Text.assemble(
                    (spark_str + n_usage_fraction_str, "bold red")
                )
            else:
                ncpps = n_cpu_percent_python_str
                ncpcs = n_cpu_percent_c_str
                nufs = spark_str + n_usage_fraction_str

            if not self.reduced_profile or ncpps + ncpcs + nufs:
                tbl.add_row(
                    print_line_no,
                    ncpps,  # n_cpu_percent_python_str,
                    ncpcs,  # n_cpu_percent_c_str,
                    sys_str,
                    n_python_fraction_str,
                    n_growth_mb_str,
                    nufs,  # spark_str + n_usage_fraction_str,
                    n_copy_mb_s_str,
                    line,
                )
                return True
            else:
                return False

        else:

            # Red highlight
            if (
                n_cpu_percent_c + n_cpu_percent_python
            ) >= self.highlight_percentage:
                ncpps = Text.assemble((n_cpu_percent_python_str, "bold red"))
                ncpcs = Text.assemble((n_cpu_percent_c_str, "bold red"))
            else:
                ncpps = n_cpu_percent_python_str
                ncpcs = n_cpu_percent_c_str

            if not self.reduced_profile or ncpps + ncpcs:
                tbl.add_row(
                    print_line_no,
                    ncpps,  # n_cpu_percent_python_str,
                    ncpcs,  # n_cpu_percent_c_str,
                    sys_str,
                    line,
                )
                return True
            else:
                return False

    def output_profiles(self,
                        stats: ScaleneStatistics,
                        pid : int,
                        profile_this_code : Callable[[Filename, LineNumber], bool],
                        python_alias_dir_name : Filename,
                        python_alias_dir : Filename
                        ) -> bool:
        """Write the profile out."""
        # Get the children's stats, if any.
        if not pid:
            stats.merge_stats(python_alias_dir_name)
            try:
                shutil.rmtree(python_alias_dir)
            except BaseException:
                pass
        current_max: float = stats.max_footprint
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
        # If I have at least one memory sample, then we are profiling memory.
        did_sample_memory: bool = (
            stats.total_memory_free_samples + stats.total_memory_malloc_samples
        ) > 0
        title = Text()
        mem_usage_line: Union[Text, str] = ""
        growth_rate = 0.0
        if did_sample_memory:
            samples = stats.memory_footprint_samples
            if len(samples.get()) > 0:
                # Output a sparkline as a summary of memory usage over time.
                _, _, spark_str = sparkline.generate(
                    samples.get()[0 : samples.len()], 0, current_max
                )
                # Compute growth rate (slope), between 0 and 1.
                if stats.allocation_velocity[1] > 0:
                    growth_rate = (
                        100.0
                        * stats.allocation_velocity[0]
                        / stats.allocation_velocity[1]
                    )
                # If memory used is > 1GB, use GB as the unit.
                if current_max > 1024:
                    mem_usage_line = Text.assemble(
                        "Memory usage: ",
                        ((spark_str, "blue")),
                        (
                            " (max: %6.2fGB, growth rate: %3.0f%%)\n"
                            % ((current_max / 1024), growth_rate)
                        ),
                    )
                else:
                    # Otherwise, use MB.
                    mem_usage_line = Text.assemble(
                        "Memory usage: ",
                        ((spark_str, "blue")),
                        (
                            " (max: %6.2fMB, growth rate: %3.0f%%)\n"
                            % (current_max, growth_rate)
                        ),
                    )

        null = open("/dev/null", "w")
        # Get column width of the terminal and adjust to fit.
        # Note that Scalene works best with at least 132 columns.
        if self.html:
            column_width = 132
        else:
            column_width = shutil.get_terminal_size().columns
        console = Console(
            width=column_width,
            record=True,
            force_terminal=True,
            file=null,
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
                stats.malloc_samples[fname] < self.malloc_threshold
                and percent_cpu_time < self.cpu_percent_threshold
            ):
                continue
            report_files.append(fname)

        # Don't actually output the profile if we are a child process.
        # Instead, write info to disk for the main process to collect.
        if pid:
            stats.output_stats(pid, python_alias_dir_name)
            return True

        for fname in report_files:
            # Print header.
            percent_cpu_time = (
                100 * stats.cpu_samples[fname] / stats.total_cpu_samples
            )
            new_title = mem_usage_line + (
                "%s: %% of time = %6.2f%% out of %6.2fs."
                % (fname, percent_cpu_time, stats.elapsed_time)
            )
            # Only display total memory usage once.
            mem_usage_line = ""

            tbl = Table(
                box=box.MINIMAL_HEAVY_HEAD,
                title=new_title,
                collapse_padding=True,
                width=column_width - 1,
            )

            tbl.add_column("Line", justify="right", no_wrap=True)
            tbl.add_column("Time %\nPython", no_wrap=True)
            tbl.add_column("Time %\nnative", no_wrap=True)
            tbl.add_column("Sys\n%", no_wrap=True)

            other_columns_width = 0  # Size taken up by all columns BUT code

            if did_sample_memory:
                tbl.add_column("Mem %\nPython", no_wrap=True)
                tbl.add_column("Net\n(MB)", no_wrap=True)
                tbl.add_column("Memory usage\nover time / %", no_wrap=True)
                tbl.add_column("Copy\n(MB/s)", no_wrap=True)
                other_columns_width = 72
                tbl.add_column(
                    "\n" + fname,
                    width=column_width - other_columns_width,
                    no_wrap=True,
                )
            else:
                other_columns_width = 36
                tbl.add_column(
                    "\n" + fname,
                    width=column_width - other_columns_width,
                    no_wrap=True,
                )

            # Print out the the profile for the source, line by line.
            with open(fname, "r") as source_file:
                # We track whether we should put in ellipsis (for reduced profiles)
                # or not.
                did_print = True  # did we print a profile line last time?
                code_lines = source_file.read()
                # Generate syntax highlighted version for the whole file,
                # which we will consume a line at a time.
                # See https://github.com/willmcgugan/rich/discussions/965#discussioncomment-314233
                syntax_highlighted = None
                if self.html:
                    syntax_highlighted = Syntax(
                        code_lines,
                        "python",
                        theme="default",
                        line_numbers=False,
                        code_width=None,
                    )
                else:
                    syntax_highlighted = Syntax(
                        code_lines,
                        "python",
                        theme="vim",
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
                        fname, LineNumber(line_no), line, console, tbl, stats, profile_this_code
                    )
                    if old_did_print and not did_print:
                        # We are skipping lines, so add an ellipsis.
                        tbl.add_row("...")
                    old_did_print = did_print

            # Potentially print a function summary.
            fn_stats = stats.build_function_stats(fname)
            print_fn_summary = False
            for fn_name in fn_stats.cpu_samples_python:
                if fn_name == fname:
                    continue
                print_fn_summary = True
                break

            if print_fn_summary:
                tbl.add_row(None, end_section=True)
                txt = Text.assemble("function summary", style="bold italic")
                if did_sample_memory:
                    tbl.add_row("", "", "", "", "", "", "", "", txt)
                else:
                    tbl.add_row("", "", "", "", txt)

                for fn_name in fn_stats.cpu_samples_python:
                    if fn_name == fname:
                        continue
                    if self.html:
                        syntax_highlighted = Syntax(
                            fn_name,
                            "python",
                            theme="default",
                            line_numbers=False,
                            code_width=None,
                        )
                    else:
                        syntax_highlighted = Syntax(
                            fn_name,
                            "python",
                            theme="vim",
                            line_numbers=False,
                            code_width=None,
                        )
                    self.output_profile_line(
                        fn_name,
                        LineNumber(1),
                        syntax_highlighted,  # type: ignore
                        console,
                        tbl,
                        fn_stats,
                        profile_this_code,
                        True,
                        True,
                        True
                    )  # force print, suppress line numbers

            console.print(tbl)

            # Report top K lines (currently 5) in terms of net memory consumption.
            net_mallocs: Dict[LineNumber, float] = defaultdict(float)
            for line_no in stats.bytei_map[fname]:
                for bytecode_index in stats.bytei_map[fname][line_no]:
                    net_mallocs[line_no] += (
                        stats.memory_malloc_samples[fname][line_no][
                            bytecode_index
                        ]
                        - stats.memory_free_samples[fname][line_no][
                            bytecode_index
                        ]
                    )
            net_mallocs = OrderedDict(
                sorted(net_mallocs.items(), key=itemgetter(1), reverse=True)
            )
            if len(net_mallocs) > 0:
                console.print("Top net memory consumption, by line:")
                number = 1
                for net_malloc_lineno in net_mallocs:
                    if net_mallocs[net_malloc_lineno] <= 1:
                        break
                    if number > 5:
                        break
                    output_str = (
                        "("
                        + str(number)
                        + ") "
                        + ("%5.0f" % (net_malloc_lineno))
                        + ": "
                        + ("%5.0f" % (net_mallocs[net_malloc_lineno]))
                        + " MB"
                    )
                    console.print(output_str)
                    number += 1

            # Only report potential leaks if the allocation velocity (growth rate) is above some threshold
            # FIXME: fixed at 1% for now.
            # We only report potential leaks where the confidence interval is quite tight and includes 1.
            growth_rate_threshold = 0.01
            leak_reporting_threshold = 0.05
            leaks = []
            if growth_rate / 100 > growth_rate_threshold:
                vec = list(stats.leak_score[fname].values())
                keys = list(stats.leak_score[fname].keys())
                for index, item in enumerate(stats.leak_score[fname].values()):
                    # See https://en.wikipedia.org/wiki/Rule_of_succession
                    frees = item[1]
                    allocs = item[0]
                    expected_leak = (frees + 1) / (frees + allocs + 2)
                    if expected_leak <= leak_reporting_threshold:
                        leaks.append(
                            (
                                keys[index],
                                1 - expected_leak,
                                net_mallocs[keys[index]],
                            )
                        )
                if len(leaks) > 0:
                    # Report in descending order by least likelihood
                    for leak in sorted(leaks, key=itemgetter(1), reverse=True):
                        output_str = (
                            "Possible memory leak identified at line "
                            + str(leak[0])
                            + " (estimated likelihood: "
                            + ("%3.0f" % (leak[1] * 100))
                            + "%"
                            + ", velocity: "
                            + ("%3.0f MB/s" % (leak[2] / stats.elapsed_time))
                            + ")"
                        )
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
        else:
            if not self.output_file:
                # No output file specified: write to stdout.
                sys.stdout.write(console.export_text(styles=True))
            else:
                # Don't output styles to text file.
                console.save_text(
                    self.output_file, styles=False, clear=False
                )
        return True
    
