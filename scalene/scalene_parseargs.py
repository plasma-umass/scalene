import argparse
import contextlib
import os
import re
import sys
from textwrap import dedent
from typing import Any, List, NoReturn, Optional, Tuple, Union

import yaml
from rich.text import Text as RichText

from scalene.find_browser import find_browser
from scalene.scalene_arguments import ScaleneArguments
from scalene.scalene_config import scalene_date, scalene_version
from scalene.scalene_statistics import Filename
from scalene.scalene_utility import generate_html

scalene_gui_url = (
    f'file:{os.path.join(os.path.dirname(__file__), "scalene-gui", "index.html")}'
)


def _colorize_help_for_rich(text: str) -> str:
    """Apply Python 3.14-style argparse colors using Rich markup.

    Python 3.14 argparse color scheme:
    - usage: bold blue
    - prog: bold magenta
    - heading (options:): bold blue
    - long options (--foo): bold cyan
    - short options (-h): bold green
    - metavars (FOO): bold yellow
    """
    # Color "usage:" at the start
    text = re.sub(
        r"^(usage:)",
        r"[bold blue]\1[/bold blue]",
        text,
        flags=re.MULTILINE,
    )

    # Color "options:" and similar headings
    text = re.sub(
        r"^(options:|positional arguments:|optional arguments:)",
        r"[bold blue]\1[/bold blue]",
        text,
        flags=re.MULTILINE,
    )

    # Color program name after "usage:" - matches "scalene" or "python3 -m scalene"
    text = re.sub(
        r"(\[bold blue\]usage:\[/bold blue\] )(\S+)",
        r"\1[bold magenta]\2[/bold magenta]",
        text,
    )

    # Color long options (--something) in the options section
    # Match at start of line with indent, or after ", " (like "-h, --help")
    text = re.sub(
        r"(^  |, )(--[a-zA-Z][a-zA-Z0-9_-]*)",
        r"\1[bold cyan]\2[/bold cyan]",
        text,
        flags=re.MULTILINE,
    )

    # Color short options like -h in the options section
    text = re.sub(
        r"(^  )(-[a-zA-Z])(,|\s)",
        r"\1[bold green]\2[/bold green]\3",
        text,
        flags=re.MULTILINE,
    )

    # Color metavars (ALL_CAPS words) that follow options
    text = re.sub(
        r"(\[/bold cyan\] )([A-Z][A-Z0-9_]*)\b",
        r"\1[bold yellow]\2[/bold yellow]",
        text,
    )

    return text


class RichArgParser(argparse.ArgumentParser):
    """ArgumentParser that uses Rich for colored output on Python < 3.14."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if sys.version_info < (3, 14):
            from rich.console import Console

            self._console: Optional[Any] = Console()
        else:
            self._console = None
        super().__init__(*args, **kwargs)

    def _print_message(self, message: Optional[str], file: Any = None) -> None:
        if message:
            if self._console is not None:
                # Python < 3.14: Use Rich to emulate 3.14+ colors
                colored = _colorize_help_for_rich(message)
                self._console.print(colored, highlight=False)
            else:
                # Python 3.14+: Use native argparse colors
                print(message, end="", file=file)


class StopJupyterExecution(Exception):
    """NOP exception to enable clean exits from within Jupyter notebooks."""

    def _render_traceback_(self) -> None:
        pass


class ScaleneParseArgs:
    # Mapping from YAML config keys to argparse dest names
    # This allows users to use either style in their config files
    _CONFIG_KEY_MAP = {
        # Basic options
        "outfile": "outfile",
        "output": "outfile",
        "cpu-only": "cpu",
        "cpu_only": "cpu",
        # Profiling scope
        "profile-all": "profile_all",
        "profile_all": "profile_all",
        "profile-only": "profile_only",
        "profile_only": "profile_only",
        "profile-exclude": "profile_exclude",
        "profile_exclude": "profile_exclude",
        # What to profile
        "gpu": "gpu",
        "memory": "memory",
        "stacks": "stacks",
        "profile-interval": "profile_interval",
        "profile_interval": "profile_interval",
        "use-virtual-time": "use_virtual_time",
        "use_virtual_time": "use_virtual_time",
        # Thresholds and sampling
        "cpu-percent-threshold": "cpu_percent_threshold",
        "cpu_percent_threshold": "cpu_percent_threshold",
        "cpu-sampling-rate": "cpu_sampling_rate",
        "cpu_sampling_rate": "cpu_sampling_rate",
        "allocation-sampling-window": "allocation_sampling_window",
        "allocation_sampling_window": "allocation_sampling_window",
        "malloc-threshold": "malloc_threshold",
        "malloc_threshold": "malloc_threshold",
        # Other
        "program-path": "program_path",
        "program_path": "program_path",
        "memory-leak-detector": "memory_leak_detector",
        "memory_leak_detector": "memory_leak_detector",
        "profile-system-libraries": "profile_system_libraries",
        "profile_system_libraries": "profile_system_libraries",
        # JIT control
        "disable-jit": "disable_jit",
        "disable_jit": "disable_jit",
        # On/off
        "on": "on",
        "off": "off",
    }

    @staticmethod
    def _load_config_file(config_path: str) -> dict[str, Any]:
        """Load and parse a YAML configuration file.

        Args:
            config_path: Path to the YAML config file

        Returns:
            Dictionary of configuration options

        Raises:
            SystemExit: If file not found or invalid YAML
        """
        if not os.path.exists(config_path):
            print(f"Scalene: config file '{config_path}' not found.", file=sys.stderr)
            sys.exit(1)

        try:
            with open(config_path, encoding="utf-8") as f:
                config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            print(f"Scalene: invalid YAML in config file: {e}", file=sys.stderr)
            sys.exit(1)

        if config is None:
            return {}

        if not isinstance(config, dict):
            print(
                f"Scalene: config file must contain a YAML mapping (got {type(config).__name__})",
                file=sys.stderr,
            )
            sys.exit(1)

        return config

    @staticmethod
    def _apply_config_to_args(args: argparse.Namespace, config: dict[str, Any]) -> None:
        """Apply configuration from a YAML file to parsed arguments.

        Config file values are used as defaults - command line arguments take precedence.

        Args:
            args: The argparse Namespace to update
            config: Dictionary of configuration options from YAML file
        """
        for key, value in config.items():
            # Map config key to argparse dest name
            dest = ScaleneParseArgs._CONFIG_KEY_MAP.get(key)
            if dest is None:
                print(
                    f"Scalene: warning: unknown config option '{key}' (ignored)",
                    file=sys.stderr,
                )
                continue

            # Only apply if the argument wasn't explicitly set on command line
            # For boolean flags stored as None (like cpu, gpu, memory), None means not set
            current_value = getattr(args, dest, None)

            # Handle special cases for boolean options
            if dest == "cpu" and value is True:
                # cpu-only: true in config means set cpu=True
                if current_value is None:
                    setattr(args, dest, True)
            elif dest in ("gpu", "memory"):
                # These are also stored as None when not set
                if current_value is None and value is True:
                    setattr(args, dest, True)
            elif dest in ("on", "off"):
                # Mutually exclusive booleans
                if value is True:
                    setattr(args, dest, True)
            elif dest in (
                "profile_all",
                "stacks",
                "use_virtual_time",
                "memory_leak_detector",
                "profile_system_libraries",
            ):
                # Regular boolean flags with defaults
                if value is True:
                    setattr(args, dest, True)
            else:
                # For non-boolean options, check if they have their default value
                # If the current value looks like a default, apply config value
                if current_value is None or (
                    dest == "outfile" and current_value == "scalene-profile.json"
                ):
                    setattr(args, dest, value)

    @staticmethod
    def clean_exit(code: object = 0) -> NoReturn:
        """Replacement for sys.exit that exits cleanly from within Jupyter notebooks."""
        raise StopJupyterExecution

    @staticmethod
    def _add_run_arguments(
        parser: argparse.ArgumentParser, defaults: ScaleneArguments
    ) -> None:
        """Add profiling arguments for the run subcommand."""
        # Check if --help-advanced is in the arguments
        show_advanced = "--help-advanced" in sys.argv

        # When showing advanced options, hide basic options and vice versa
        basic_help = argparse.SUPPRESS if show_advanced else None
        advanced_help = argparse.SUPPRESS if not show_advanced else None

        # Basic options (hidden when --help-advanced is used)
        parser.add_argument(
            "-o",
            "--outfile",
            type=str,
            default=defaults.outfile,
            help=(
                "output file (default: scalene-profile.json)"
                if not show_advanced
                else basic_help
            ),
        )
        parser.add_argument(
            "--cpu-only",
            dest="cpu",
            action="store_const",
            const=True,
            default=None,
            help=(
                "only profile CPU time (no memory/GPU)"
                if not show_advanced
                else basic_help
            ),
        )
        parser.add_argument(
            "-c",
            "--config",
            dest="config_file",
            type=str,
            default=None,
            help=(
                "load options from YAML config file"
                if not show_advanced
                else basic_help
            ),
        )

        # --help-advanced flag (always visible in basic help, hidden in advanced help)
        parser.add_argument(
            "--help-advanced",
            action="store_true",
            help="show advanced options" if not show_advanced else argparse.SUPPRESS,
        )

        # Advanced options (hidden unless --advanced is specified)

        # Profiling scope options
        parser.add_argument(
            "--profile-all",
            dest="profile_all",
            action="store_true",
            default=defaults.profile_all,
            help=(
                "profile all code, not just the target program"
                if show_advanced
                else advanced_help
            ),
        )
        parser.add_argument(
            "--profile-only",
            dest="profile_only",
            type=str,
            default=defaults.profile_only,
            help=(
                "only profile files containing these strings (comma-separated)"
                if show_advanced
                else advanced_help
            ),
        )
        parser.add_argument(
            "--profile-exclude",
            dest="profile_exclude",
            type=str,
            default=defaults.profile_exclude,
            help=(
                "exclude files containing these strings (comma-separated)"
                if show_advanced
                else advanced_help
            ),
        )

        # What to profile
        parser.add_argument(
            "--gpu",
            dest="gpu",
            action="store_const",
            const=True,
            default=None,
            help="profile GPU time and memory" if show_advanced else advanced_help,
        )
        parser.add_argument(
            "--memory",
            dest="memory",
            action="store_const",
            const=True,
            default=None,
            help="profile memory usage" if show_advanced else advanced_help,
        )
        parser.add_argument(
            "--stacks",
            dest="stacks",
            action="store_true",
            default=defaults.stacks,
            help="collect stack traces" if show_advanced else advanced_help,
        )
        parser.add_argument(
            "--profile-interval",
            type=float,
            default=defaults.profile_interval,
            help=(
                f"output profiles every so many seconds (default: {defaults.profile_interval})"
                if show_advanced
                else advanced_help
            ),
        )
        parser.add_argument(
            "--use-virtual-time",
            dest="use_virtual_time",
            action="store_const",
            const=True,
            default=defaults.use_virtual_time,
            help=(
                f"measure only CPU time, not time spent in I/O or blocking (default: {defaults.use_virtual_time})"
                if show_advanced
                else advanced_help
            ),
        )
        parser.add_argument(
            "--cpu-percent-threshold",
            dest="cpu_percent_threshold",
            type=float,
            default=defaults.cpu_percent_threshold,
            help=(
                f"only report profiles with at least this percent of CPU time (default: {defaults.cpu_percent_threshold}%%)"
                if show_advanced
                else advanced_help
            ),
        )
        parser.add_argument(
            "--cpu-sampling-rate",
            dest="cpu_sampling_rate",
            type=float,
            default=defaults.cpu_sampling_rate,
            help=(
                f"CPU sampling rate (default: every {defaults.cpu_sampling_rate}s)"
                if show_advanced
                else advanced_help
            ),
        )
        parser.add_argument(
            "--allocation-sampling-window",
            dest="allocation_sampling_window",
            type=int,
            default=defaults.allocation_sampling_window,
            help=(
                f"Allocation sampling window size, in bytes (default: {defaults.allocation_sampling_window} bytes)"
                if show_advanced
                else advanced_help
            ),
        )
        parser.add_argument(
            "--malloc-threshold",
            dest="malloc_threshold",
            type=int,
            default=defaults.malloc_threshold,
            help=(
                f"only report profiles with at least this many allocations (default: {defaults.malloc_threshold})"
                if show_advanced
                else advanced_help
            ),
        )
        parser.add_argument(
            "--program-path",
            dest="program_path",
            type=str,
            default="",
            help=(
                "The directory containing the code to profile (default: the path to the profiled program)"
                if show_advanced
                else advanced_help
            ),
        )
        parser.add_argument(
            "--memory-leak-detector",
            dest="memory_leak_detector",
            action="store_true",
            default=defaults.memory_leak_detector,
            help=(
                f"EXPERIMENTAL: report likely memory leaks (default: {defaults.memory_leak_detector})"
                if show_advanced
                else advanced_help
            ),
        )
        parser.add_argument(
            "--profile-system-libraries",
            dest="profile_system_libraries",
            action="store_true",
            default=defaults.profile_system_libraries,
            help=(
                "profile Python system libraries and installed packages (default: skip them)"
                if show_advanced
                else advanced_help
            ),
        )
        parser.add_argument(
            "--use-legacy-tracer",
            dest="use_legacy_tracer",
            action="store_true",
            default=defaults.use_legacy_tracer,
            help=(
                "use legacy PyEval_SetTrace for line tracing instead of sys.monitoring (Python 3.12+)"
                if show_advanced
                else advanced_help
            ),
        )
        parser.add_argument(
            "--use-python-callback",
            dest="use_python_callback",
            action="store_true",
            default=defaults.use_python_callback,
            help=(
                "use Python callback for sys.monitoring instead of C callback (Python 3.13+)"
                if show_advanced
                else advanced_help
            ),
        )
        parser.add_argument(
            "--disable-jit",
            dest="disable_jit",
            action="store_true",
            default=defaults.disable_jit,
            help=(
                "disable PyTorch and JAX JIT for Python-level profiling (may break torch.jit.load)"
                if show_advanced
                else advanced_help
            ),
        )
        if sys.platform != "win32":
            # Turning profiling on and off from another process is currently not supported on Windows.
            group = parser.add_mutually_exclusive_group(required=False)
            group.add_argument(
                "--on",
                action="store_true",
                help=(
                    "start with profiling on (default)"
                    if show_advanced
                    else advanced_help
                ),
            )
            group.add_argument(
                "--off",
                action="store_true",
                help="start with profiling off" if show_advanced else advanced_help,
            )

        # Internal/hidden options (always hidden)
        parser.add_argument(
            "--ipython",
            dest="ipython",
            action="store_const",
            const=True,
            default=False,
            help=argparse.SUPPRESS,
        )
        # --reduced-profile for Jupyter magic (display option, hidden in run)
        parser.add_argument(
            "--reduced-profile",
            dest="reduced_profile",
            action="store_true",
            default=False,
            help=argparse.SUPPRESS,
        )
        # the PID of the profiling process (for internal use only)
        parser.add_argument("--pid", type=int, default=0, help=argparse.SUPPRESS)
        # collect all arguments after "---", which Scalene will ignore
        parser.add_argument(
            "---",
            dest="unused_args",
            default=[],
            help=argparse.SUPPRESS,
            nargs=argparse.REMAINDER,
        )

    # Colors matching scalene_output.py
    highlight_color = "bold red"
    memory_color = "dark_green"
    gpu_color = "yellow4"
    copy_volume_color = "yellow4"
    highlight_percentage = 33

    @staticmethod
    def _display_profile_cli(
        profile_data: dict[str, Any],
        column_width: int = 132,
        reduced_profile: bool = False,
    ) -> None:
        """Display a profile in the terminal using Rich, matching the original Scalene output format."""
        import shutil

        from rich import box
        from rich.console import Console
        from rich.markdown import Markdown
        from rich.syntax import Syntax
        from rich.table import Table
        from rich.text import Text

        from scalene.scalene_json import ScaleneJSON
        from scalene.syntaxline import SyntaxLine

        # Auto-detect terminal width if possible
        with contextlib.suppress(Exception):
            column_width = shutil.get_terminal_size().columns

        console = Console(width=column_width, force_terminal=True)

        elapsed_time = profile_data.get("elapsed_time_sec", 0) * 1000  # Convert to ms
        max_footprint = profile_data.get("max_footprint_mb", 0)
        growth_rate = profile_data.get("growth_rate", 0)

        # Check what was profiled
        has_memory = profile_data.get("memory", False)
        has_gpu = profile_data.get("gpu", False)

        files = profile_data.get("files", {})
        if not files:
            console.print("[yellow]No profile data found in the file.[/yellow]")
            return

        # Memory usage line (shown once at the top)
        mem_usage_line: Any = ""
        if has_memory and max_footprint > 0:
            mem_usage_line = Text.assemble(
                "Memory usage: ",
                (
                    f"(max: {ScaleneJSON.memory_consumed_str(max_footprint)}, growth rate: {growth_rate:3.0f}%)\n",
                    ScaleneParseArgs.memory_color,
                ),
            )

        for filename, file_data in files.items():
            lines = file_data.get("lines", [])
            functions = file_data.get("functions", [])
            percent_cpu_time = file_data.get("percent_cpu_time", 0)

            # If percent_cpu_time not in profile, calculate it
            if not percent_cpu_time:
                percent_cpu_time = sum(
                    line.get("n_cpu_percent_python", 0) + line.get("n_cpu_percent_c", 0)
                    for line in lines
                )

            # Build header matching original format
            time_str = ScaleneJSON.time_consumed_str(
                percent_cpu_time / 100.0 * elapsed_time
            )
            total_time_str = ScaleneJSON.time_consumed_str(elapsed_time)

            if mem_usage_line:
                new_title = mem_usage_line + Text(
                    f"{filename}: % of time = {percent_cpu_time:6.2f}% ({time_str}) out of {total_time_str}."
                )
                mem_usage_line = ""  # Only show once
            else:
                new_title = Text(
                    f"{filename}: % of time = {percent_cpu_time:6.2f}% ({time_str}) out of {total_time_str}."
                )

            # Calculate column widths matching scalene_output.py
            if has_memory:
                other_columns_width = 75 + (6 if has_gpu else 0)
            else:
                other_columns_width = 37 + (5 if has_gpu else 0)
            code_width = column_width - other_columns_width

            # Create table matching original styling
            tbl = Table(
                box=box.MINIMAL_HEAVY_HEAD,
                title=new_title,
                collapse_padding=True,
                width=column_width - 1,
            )

            # Add columns matching scalene_output.py format
            tbl.add_column(
                Markdown("Line", style="dim"),
                style="dim",
                justify="right",
                no_wrap=True,
                width=4,
            )
            tbl.add_column(
                Markdown("Time  \n_Python_", style="blue"),
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

            if has_gpu:
                tbl.add_column(
                    Markdown("––––––  \n_GPU_", style=ScaleneParseArgs.gpu_color),
                    style=ScaleneParseArgs.gpu_color,
                    no_wrap=True,
                    width=6,
                )

            if has_memory:
                tbl.add_column(
                    Markdown("Memory  \n_Python_", style=ScaleneParseArgs.memory_color),
                    style=ScaleneParseArgs.memory_color,
                    no_wrap=True,
                    width=7,
                )
                tbl.add_column(
                    Markdown("––––––  \n_peak_", style=ScaleneParseArgs.memory_color),
                    style=ScaleneParseArgs.memory_color,
                    no_wrap=True,
                    width=6,
                )
                tbl.add_column(
                    Markdown(
                        "–––––––––––  \n_timeline_/%",
                        style=ScaleneParseArgs.memory_color,
                    ),
                    style=ScaleneParseArgs.memory_color,
                    no_wrap=True,
                    width=15,
                )
                tbl.add_column(
                    Markdown(
                        "Copy  \n_(MB/s)_", style=ScaleneParseArgs.copy_volume_color
                    ),
                    style=ScaleneParseArgs.copy_volume_color,
                    no_wrap=True,
                    width=6,
                )

            tbl.add_column(
                "\n" + filename,
                width=code_width,
                no_wrap=True,
            )

            # Process lines with syntax highlighting
            did_print = True
            for line_info in lines:
                lineno = line_info.get("lineno", 0)
                line_text = line_info.get("line", "").rstrip("\n")
                python_pct = line_info.get("n_cpu_percent_python", 0)
                native_pct = line_info.get("n_cpu_percent_c", 0)
                sys_pct = line_info.get("n_sys_percent", 0)
                gpu_pct = line_info.get("n_gpu_percent", 0)
                peak_mb = line_info.get("n_peak_mb", 0)
                copy_mb = line_info.get("n_copy_mb_s", 0)
                usage_frac = line_info.get("n_usage_fraction", 0)
                python_frac = line_info.get("n_python_fraction", 0)

                # Format values matching scalene_output.py
                python_str: Union[str, RichText] = (
                    f"{python_pct:5.0f}%" if python_pct >= 1 else ""
                )
                native_str: Union[str, RichText] = (
                    f"{native_pct:5.0f}%" if native_pct >= 1 else ""
                )
                sys_str: Union[str, RichText] = (
                    f"{sys_pct:4.0f}%" if sys_pct >= 1 else ""
                )
                gpu_str: Union[str, RichText] = (
                    f"{gpu_pct:3.0f}%" if gpu_pct >= 1 else ""
                )

                # Memory formatting
                if peak_mb < 1024:
                    growth_mem_str = (
                        f"{peak_mb:5.0f}M" if (peak_mb or usage_frac) else ""
                    )
                else:
                    growth_mem_str = (
                        f"{(peak_mb / 1024):5.2f}G" if (peak_mb or usage_frac) else ""
                    )
                python_frac_str = (
                    f"{(python_frac * 100):4.0f}%" if python_frac >= 0.01 else ""
                )
                usage_frac_str: Union[str, RichText] = (
                    f"{(usage_frac * 100):4.0f}%" if usage_frac >= 0.01 else ""
                )
                copy_str = f"{copy_mb:6.0f}" if copy_mb >= 0.5 else ""

                # Check if we should print this line
                has_activity = (
                    python_pct >= 1
                    or native_pct >= 1
                    or sys_pct >= 1
                    or gpu_pct >= 1
                    or usage_frac >= 0.01
                )

                if reduced_profile and not has_activity:
                    if did_print:
                        tbl.add_row("...")
                    did_print = False
                    continue

                did_print = True

                # Apply highlighting for hot lines
                total_pct = python_pct + native_pct + gpu_pct + sys_pct
                if has_memory and (
                    usage_frac * 100 >= ScaleneParseArgs.highlight_percentage
                    or total_pct >= ScaleneParseArgs.highlight_percentage
                ):
                    python_str = (
                        Text(str(python_str), style=ScaleneParseArgs.highlight_color)
                        if python_str
                        else ""
                    )
                    native_str = (
                        Text(str(native_str), style=ScaleneParseArgs.highlight_color)
                        if native_str
                        else ""
                    )
                    usage_frac_str = (
                        Text(
                            str(usage_frac_str), style=ScaleneParseArgs.highlight_color
                        )
                        if usage_frac_str
                        else ""
                    )
                    gpu_str = (
                        Text(str(gpu_str), style=ScaleneParseArgs.highlight_color)
                        if gpu_str
                        else ""
                    )
                elif total_pct >= ScaleneParseArgs.highlight_percentage:
                    python_str = (
                        Text(str(python_str), style=ScaleneParseArgs.highlight_color)
                        if python_str
                        else ""
                    )
                    native_str = (
                        Text(str(native_str), style=ScaleneParseArgs.highlight_color)
                        if native_str
                        else ""
                    )
                    gpu_str = (
                        Text(str(gpu_str), style=ScaleneParseArgs.highlight_color)
                        if gpu_str
                        else ""
                    )
                    sys_str = (
                        Text(str(sys_str), style=ScaleneParseArgs.highlight_color)
                        if sys_str
                        else ""
                    )

                # Syntax highlight the code line
                syntax = Syntax(
                    line_text,
                    "python",
                    theme="vim",
                    line_numbers=False,
                    code_width=None,
                )
                capture_console = Console(width=code_width, force_terminal=True)
                with capture_console.capture() as capture:
                    capture_console.print(syntax, end="")
                highlighted_line = Text.from_ansi(capture.get().rstrip())

                # Build row based on what was profiled
                row: list[Any] = [str(lineno), python_str, native_str, sys_str]

                if has_gpu:
                    row.append(gpu_str)

                if has_memory:
                    row.extend(
                        [python_frac_str, growth_mem_str, usage_frac_str, copy_str]
                    )

                row.append(highlighted_line)
                tbl.add_row(*row)

            console.print(tbl)

            # Display function summaries matching original format
            if functions:
                fn_with_activity = [
                    f
                    for f in functions
                    if f.get("n_cpu_percent_python", 0) + f.get("n_cpu_percent_c", 0)
                    > 0
                ]
                if fn_with_activity:
                    console.print("\n[bold]Function summaries:[/bold]")
                    for func in fn_with_activity:
                        func_name = func.get("line", "unknown")
                        func_lineno = func.get("lineno", 0)
                        func_python = func.get("n_cpu_percent_python", 0)
                        func_native = func.get("n_cpu_percent_c", 0)
                        console.print(
                            f"  {func_name} [bold]([/bold]line [cyan]{func_lineno}[/cyan][bold])[/bold]: "
                            f"[cyan]{func_python:.0f}[/cyan]% Python, [cyan]{func_native:.0f}[/cyan]% native"
                        )
            console.print()

    @staticmethod
    def _handle_view_command(args: argparse.Namespace) -> None:
        """Handle the 'view' subcommand to view an existing profile."""
        import json
        import subprocess

        import scalene.scalene_config

        profile_file = args.profile_file
        output_file = "scalene-profile.html"

        # Check if the profile file exists
        if not os.path.exists(profile_file):
            print(f"Scalene: profile file '{profile_file}' not found.", file=sys.stderr)
            sys.exit(1)

        # If --cli mode, display in terminal
        if args.cli:
            try:
                with open(profile_file, encoding="utf-8") as f:
                    profile_data = json.load(f)
                ScaleneParseArgs._display_profile_cli(
                    profile_data,
                    reduced_profile=args.reduced_profile,
                )
            except json.JSONDecodeError as e:
                print(f"Scalene: invalid JSON in profile file: {e}", file=sys.stderr)
                sys.exit(1)
            except Exception as e:
                print(f"Scalene: error reading profile: {e}", file=sys.stderr)
                sys.exit(1)
            sys.exit(0)

        # Generate HTML from the profile
        generate_html(
            profile_fname=Filename(profile_file),
            output_fname=Filename(output_file),
            standalone=args.standalone,
        )

        # If --html or --standalone was specified, just save the file without opening browser
        if args.html_only or args.standalone:
            print(f"Profile saved to: {output_file}")
        else:
            # Open the browser
            if find_browser():
                dir = os.path.dirname(__file__)
                subprocess.Popen(
                    [
                        sys.executable,
                        f"{dir}{os.sep}launchbrowser.py",
                        os.path.abspath(output_file),
                        str(scalene.scalene_config.SCALENE_PORT),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                print("Scalene: could not open a browser.", file=sys.stderr)
                print(f"Profile saved to: {output_file}", file=sys.stderr)

        sys.exit(0)

    @staticmethod
    def parse_args() -> Tuple[argparse.Namespace, List[str]]:
        # In IPython, intercept exit cleanly (because sys.exit triggers a backtrace).
        with contextlib.suppress(BaseException):
            from IPython import get_ipython

            if get_ipython():  # type: ignore[no-untyped-call,unused-ignore]
                sys.exit = ScaleneParseArgs.clean_exit
                sys._exit = ScaleneParseArgs.clean_exit  # type: ignore
        defaults = ScaleneArguments()
        return ScaleneParseArgs._parse_args_impl(defaults)

    @staticmethod
    def _parse_args_impl(
        defaults: ScaleneArguments,
    ) -> Tuple[argparse.Namespace, List[str]]:
        """Parse command-line arguments using subcommands."""
        main_usage = dedent(
            rf"""Scalene: a high-precision CPU and memory profiler, version {scalene_version} ({scalene_date})
https://github.com/plasma-umass/scalene

commands:
  run     Profile a Python program (saves to scalene-profile.json)
  view    View an existing profile in browser or terminal

examples:
  % scalene run your_program.py              # profile, save to scalene-profile.json
  % scalene view                             # view scalene-profile.json in browser
  % scalene view --cli                       # view profile in terminal

in Jupyter, line mode:
  %scrun [options] statement

in Jupyter, cell mode:
  %%scalene [options]
   your code here
"""
        )

        main_parser = RichArgParser(
            prog="scalene",
            description=main_usage,
            formatter_class=argparse.RawTextHelpFormatter,
            allow_abbrev=False,
        )
        main_parser.add_argument(
            "--version",
            action="version",
            version=f"Scalene version {scalene_version} ({scalene_date})",
        )
        subparsers = main_parser.add_subparsers(
            dest="command", help="Available commands"
        )

        # 'run' subcommand - profile a program
        show_advanced = "--help-advanced" in sys.argv
        if show_advanced:
            run_usage = dedent("""Advanced options for scalene run:

background profiling:
  Use --off to start with profiling disabled, then control it from another terminal:
    % scalene run --off prog.py          # start with profiling off
    % python3 -m scalene.profile --on  --pid <PID>   # resume profiling
    % python3 -m scalene.profile --off --pid <PID>   # suspend profiling
""")
            run_epilog = ""
        else:
            run_usage = dedent("""Profile a Python program with Scalene.

examples:
  % scalene run prog.py                 # profile, save to scalene-profile.json
  % scalene run -o my.json prog.py      # save to custom file
  % scalene run --cpu-only prog.py      # profile CPU only (faster)
  % scalene run -c scalene.yaml prog.py # load options from config file
  % scalene run prog.py --- --arg       # pass args to program
  % scalene run --help-advanced         # show advanced options
""")
            run_epilog = ""
        run_parser = subparsers.add_parser(
            "run",
            help="Profile a Python program",
            description=run_usage,
            epilog=run_epilog if sys.platform != "win32" else "",
            formatter_class=argparse.RawTextHelpFormatter,
            add_help=False,  # We'll add help manually to control its visibility
        )
        # Add help manually so we can hide it in advanced mode
        run_parser.add_argument(
            "-h",
            "--help",
            action="help",
            default=argparse.SUPPRESS,
            help=(
                "show this help message and exit"
                if not show_advanced
                else argparse.SUPPRESS
            ),
        )
        ScaleneParseArgs._add_run_arguments(run_parser, defaults)

        # 'view' subcommand - view an existing profile
        view_usage = dedent("""View an existing Scalene profile.

examples:
  % scalene view                    # open in browser
  % scalene view --cli              # view in terminal
  % scalene view --html             # save to scalene-profile.html
  % scalene view --standalone       # save as single self-contained HTML file
  % scalene view myprofile.json     # open specific profile in browser
""")
        view_parser = subparsers.add_parser(
            "view",
            help="View an existing profile (JSON) in browser or terminal",
            description=view_usage,
            formatter_class=argparse.RawTextHelpFormatter,
        )
        view_parser.add_argument(
            "profile_file",
            type=str,
            nargs="?",
            default="scalene-profile.json",
            help="The JSON profile file to view (default: scalene-profile.json)",
        )
        view_parser.add_argument(
            "--cli",
            dest="cli",
            action="store_true",
            default=False,
            help="Display profile in the terminal",
        )
        view_parser.add_argument(
            "--html",
            dest="html_only",
            action="store_true",
            default=False,
            help="Save to scalene-profile.html (no browser)",
        )
        view_parser.add_argument(
            "-r",
            "--reduced",
            dest="reduced_profile",
            action="store_true",
            default=False,
            help="only show lines with activity (--cli mode)",
        )
        view_parser.add_argument(
            "--standalone",
            dest="standalone",
            action="store_true",
            default=False,
            help="Save as a single self-contained HTML file with all assets embedded (implies --html)",
        )

        # Check if user provided a .py file without a subcommand
        # This catches the common mistake of `scalene foo.py` instead of `scalene run foo.py`
        if len(sys.argv) > 1 and sys.argv[1] not in (
            "run",
            "view",
            "-h",
            "--help",
            "--version",
        ):
            # Check if any argument looks like a Python file or module
            for arg in sys.argv[1:]:
                if arg.endswith(".py") or arg == "-m":
                    print(
                        f"Scalene: error: '{arg}' is not a valid command.\n"
                        f"Did you mean: scalene run {' '.join(sys.argv[1:])}\n",
                        file=sys.stderr,
                    )
                    main_parser.print_help(sys.stderr)
                    sys.exit(1)

        args, left = main_parser.parse_known_args()

        # Handle the 'view' command immediately
        if args.command == "view":
            ScaleneParseArgs._handle_view_command(args)
            # _handle_view_command calls sys.exit, so we never reach here

        # For 'run' command, continue with normal processing
        if args.command == "run":
            # If --help-advanced was specified, print advanced help and exit
            if hasattr(args, "help_advanced") and args.help_advanced:
                run_parser.print_help()
                sys.exit(0)
            # Remove the 'command' attribute as it's not needed downstream
            delattr(args, "command")
            return ScaleneParseArgs._finalize_args(args, left, defaults)

        # If no subcommand was recognized, show help and exit
        main_parser.print_help(sys.stderr)
        sys.exit(1)

    @staticmethod
    def _finalize_args(
        args: argparse.Namespace,
        left: List[str],
        defaults: ScaleneArguments,
        parser: Optional[argparse.ArgumentParser] = None,
    ) -> Tuple[argparse.Namespace, List[str]]:
        """Finalize argument processing after parsing."""
        # Load config file if specified (before setting other defaults)
        # Config file values act as defaults - CLI args take precedence
        if hasattr(args, "config_file") and args.config_file:
            config = ScaleneParseArgs._load_config_file(args.config_file)
            ScaleneParseArgs._apply_config_to_args(args, config)

        # Set defaults for attributes that may not be present
        # (removed from CLI but still needed internally)
        if not hasattr(args, "json"):
            args.json = defaults.json
        if not hasattr(args, "html"):
            args.html = defaults.html
        if not hasattr(args, "cli"):
            args.cli = defaults.cli
        if not hasattr(args, "web"):
            args.web = defaults.web
        if not hasattr(args, "no_browser"):
            args.no_browser = defaults.no_browser
        if not hasattr(args, "reduced_profile"):
            args.reduced_profile = defaults.reduced_profile
        if not hasattr(args, "column_width"):
            args.column_width = defaults.column_width
        if not hasattr(args, "ipython"):
            args.ipython = False
        if not hasattr(args, "profile_system_libraries"):
            args.profile_system_libraries = defaults.profile_system_libraries
        if not hasattr(args, "use_legacy_tracer"):
            args.use_legacy_tracer = defaults.use_legacy_tracer
        if not hasattr(args, "use_python_callback"):
            args.use_python_callback = defaults.use_python_callback
        if not hasattr(args, "disable_jit"):
            args.disable_jit = defaults.disable_jit

        # Validate file/directory arguments
        if args.outfile and os.path.isdir(args.outfile):
            if parser:
                parser.error(f"outfile {args.outfile} is a directory")
            else:
                print(
                    f"Scalene: outfile {args.outfile} is a directory", file=sys.stderr
                )
                sys.exit(1)

        # Hack to simplify functionality for Windows platforms.
        if sys.platform == "win32":
            args.on = True
            args.pid = 0
        left += args.unused_args

        # If any of the individual profiling metrics were specified,
        # disable the unspecified ones (set as None).
        if args.cpu or args.gpu or args.memory:
            if not args.memory:
                args.memory = False
            if not args.gpu:
                args.gpu = False
        else:
            # Nothing specified; use defaults.
            args.cpu = defaults.cpu
            args.gpu = defaults.gpu
            args.memory = defaults.memory

        args.cpu = True  # Always true

        in_jupyter_notebook = len(sys.argv) >= 1 and re.match(
            r"_ipython-input-([0-9]+)-.*", sys.argv[0]
        )
        # If the user did not enter any commands (just `scalene` or `python3 -m scalene`),
        # print the usage information and bail.
        if parser and not in_jupyter_notebook and (len(sys.argv) + len(left) == 1):
            parser.print_help(sys.stderr)
            sys.exit(-1)
        if hasattr(args, "version") and args.version:
            print(f"Scalene version {scalene_version} ({scalene_date})")
            if not args.ipython:
                sys.exit(-1)
            # Clear out the namespace. We do this to indicate that we should not run further in IPython.
            for arg in list(args.__dict__):
                delattr(args, arg)
            # was:
            # args = (
            #     []
            # )  # We use this to indicate that we should not run further in IPython.
        return args, left
