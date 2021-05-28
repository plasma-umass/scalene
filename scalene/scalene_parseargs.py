from scalene.scalene_arguments import ScaleneArguments
from scalene.scalene_version import scalene_version

from typing import (
    List,
    Tuple,
)
from textwrap import dedent
import argparse
import sys


class StopJupyterExecution(Exception):
    """NOP exception to enable clean exits from within Jupyter notebooks."""

    def _render_traceback_(self) -> None:
        pass


class ScaleneParseArgs:
    @staticmethod
    def clean_exit(code: int) -> None:
        """Replacement for sys.exit that exits cleanly from within Jupyter notebooks."""
        raise StopJupyterExecution

    @staticmethod
    def parse_args() -> Tuple[argparse.Namespace, List[str]]:
        # In IPython, intercept exit cleanly (because sys.exit triggers a backtrace).
        try:
            from IPython import get_ipython

            if get_ipython():
                sys.exit = clean_exit  # type: ignore
        except:
            pass
        defaults = ScaleneArguments()
        usage = dedent(
            f"""Scalene: a high-precision CPU and memory profiler, version {scalene_version}
https://github.com/plasma-umass/scalene


command-line:
   % scalene [options] yourprogram.py
or
   % python3 -m scalene [options] yourprogram.py

in Jupyter, line mode:
   %scrun [options] statement

in Jupyter, cell mode:
   %%scalene [options]
   code...
   code...
"""
        )
        epilog = dedent(
            """When running Scalene in the background, you can suspend/resume profiling
for the process ID that Scalene reports. For example:

   % python3 -m scalene [options] yourprogram.py &
 Scalene now profiling process 12345
   to suspend profiling: python3 -m scalene.profile --off --pid 12345
   to resume profiling:  python3 -m scalene.profile --on  --pid 12345
"""
        )

        parser = argparse.ArgumentParser(
            prog="scalene",
            description=usage,
            epilog=epilog,
            formatter_class=argparse.RawTextHelpFormatter,
            allow_abbrev=False,
        )
        parser.add_argument(
            "--version",
            dest="version",
            action="store_const",
            const=True,
            help="prints the version number for this release of Scalene and exits",
        )
        parser.add_argument(
            "--outfile",
            type=str,
            default=defaults.outfile,
            help="file to hold profiler output (default: "
            + ("stdout" if not defaults.outfile else defaults.outfile)
            + ")",
        )
        parser.add_argument(
            "--html",
            dest="html",
            action="store_const",
            const=True,
            default=defaults.html,
            help="output as HTML (default: "
            + str("html" if defaults.html else "text")
            + ")",
        )
        parser.add_argument(
            "--reduced-profile",
            dest="reduced_profile",
            action="store_const",
            const=True,
            default=defaults.reduced_profile,
            help=f"generate a reduced profile, with non-zero lines only (default: {defaults.reduced_profile})",
        )
        parser.add_argument(
            "--profile-interval",
            type=float,
            default=defaults.profile_interval,
            help=f"output profiles every so many seconds (default: {defaults.profile_interval})",
        )
        parser.add_argument(
            "--cpu-only",
            dest="cpu_only",
            action="store_const",
            const=True,
            default=defaults.cpu_only,
            help="only profile CPU time (default: profile "
            + ("CPU only" if defaults.cpu_only else "CPU, memory, and copying")
            + ")",
        )
        parser.add_argument(
            "--profile-all",
            dest="profile_all",
            action="store_const",
            const=True,
            default=defaults.profile_all,
            help="profile all executed code, not just the target program (default: "
            + (
                "all code"
                if defaults.profile_all
                else "only the target program"
            )
            + ")",
        )
        parser.add_argument(
            "--profile-only",
            dest="profile_only",
            type=str,
            default=defaults.profile_only,
            help="profile only code in files matching the given strings, separated by commas (default: "
            + (
                "no restrictions"
                if not defaults.profile_only
                else defaults.profile_only
            )
            + ")",
        )
        parser.add_argument(
            "--use-virtual-time",
            dest="use_virtual_time",
            action="store_const",
            const=True,
            default=defaults.use_virtual_time,
            help=f"measure only CPU time, not time spent in I/O or blocking (default: {defaults.use_virtual_time})",
        )
        parser.add_argument(
            "--cpu-percent-threshold",
            dest="cpu_percent_threshold",
            type=int,
            default=defaults.cpu_percent_threshold,
            help=f"only report profiles with at least this percent of CPU time (default: {defaults.cpu_percent_threshold}%%)",
        )
        parser.add_argument(
            "--cpu-sampling-rate",
            dest="cpu_sampling_rate",
            type=float,
            default=defaults.cpu_sampling_rate,
            help=f"CPU sampling rate (default: every {defaults.cpu_sampling_rate}s)",
        )
        parser.add_argument(
            "--malloc-threshold",
            dest="malloc_threshold",
            type=int,
            default=defaults.malloc_threshold,
            help=f"only report profiles with at least this many allocations (default: {defaults.malloc_threshold})",
        )

        parser.add_argument(
            "--program-path",
            dest="program_path",
            type=str,
            default="",
            help="The directory that the code to profile is located in (default: the directory that the profiled program is in)",
        )
        group = parser.add_mutually_exclusive_group(required=False)
        group.add_argument(
            "--on",
            action="store_true",
            help="start with profiling on (default)",
        )
        group.add_argument(
            "--off", action="store_true", help="start with profiling off"
        )
        # the PID of the profiling process (for internal use only)
        parser.add_argument(
            "--pid", type=int, default=0, help=argparse.SUPPRESS
        )
        parser.add_argument(
            "---",
            dest="unused_args",
            default=[],
            help=argparse.SUPPRESS,
            nargs=argparse.REMAINDER,
        )
        # Parse out all Scalene arguments and jam the remaining ones into argv.
        # https://stackoverflow.com/questions/35733262/is-there-any-way-to-instruct-argparse-python-2-7-to-remove-found-arguments-fro
        args, left = parser.parse_known_args()
        left += args.unused_args
        # If the user did not enter any commands (just `scalene` or `python3 -m scalene`),
        # print the usage information and bail.
        if len(sys.argv) + len(left) == 1:
            parser.print_help(sys.stderr)
            sys.exit(-1)
        if args.version:
            print(f"Scalene version {scalene_version}")
            sys.exit(-1)
        return args, left
