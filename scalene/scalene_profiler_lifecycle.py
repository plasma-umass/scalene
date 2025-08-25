"""
Profiler lifecycle management for Scalene profiler.

This module extracts profiler lifecycle functionality from the main Scalene class
to improve code organization and reduce complexity.
"""

import os
import sys
import time
from typing import Any, Dict, List, Optional, Set

from scalene.scalene_signals import SignumType
from scalene.scalene_statistics import Filename
from scalene.find_browser import find_browser

if sys.version_info >= (3, 11):
    from types import FrameType
else:
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        from types import FrameType
    else:
        FrameType = Any


class ScaleneProfilerLifecycle:
    """Handles profiler lifecycle management for Scalene."""

    def __init__(self, args, stats, signal_manager, output, json_output, accelerator, 
                 profile_filename):
        """Initialize the profiler lifecycle manager."""
        self.__args = args
        self.__stats = stats
        self.__signal_manager = signal_manager
        self.__output = output
        self.__json = json_output
        self.__accelerator = accelerator
        self.__profile_filename = profile_filename
        self.__initialized = False

    def set_initialized(self, value: bool) -> None:
        """Set the initialized flag."""
        self.__initialized = value

    def start(self, set_start_time_func, set_done_func) -> None:
        """Initiate profiling."""
        if not self.__initialized:
            print(
                "ERROR: Do not try to invoke `start` if you have not called Scalene using one of the methods\n"
                "in https://github.com/plasma-umass/scalene#using-scalene\n"
                "(The most likely issue is that you need to run your code with `scalene`, not `python`).",
                file=sys.stderr,
            )
            sys.exit(1)
        self.__stats.start_clock()
        self.__signal_manager.enable_signals()
        set_start_time_func(time.monotonic_ns())
        set_done_func(False)

        # Start neuron monitor if using Neuron accelerator
        if (
            hasattr(self.__accelerator, "start_monitor")
            and self.__accelerator is not None
        ):
            self.__accelerator.start_monitor()

        if self.__args.memory:
            from scalene import pywhere  # type: ignore

            pywhere.set_scalene_done_false()

    def stop(self, set_done_func, get_is_child_func, get_in_jupyter_func) -> None:
        """Complete profiling."""
        set_done_func(True)
        if self.__args.memory:
            from scalene import pywhere  # type: ignore

            pywhere.set_scalene_done_true()

        self.__signal_manager.disable_signals()
        self.__stats.stop_clock()
        if self.__args.outfile:
            self.__profile_filename = Filename(
                os.path.join(
                    os.path.dirname(self.__args.outfile),
                    os.path.basename(self.__profile_filename),
                )
            )

        if self.__args.web and not self.__args.cli and not get_is_child_func():
            # First, check for a browser.
            try:
                if not find_browser():
                    # Could not open a graphical web browser tab;
                    # act as if --web was not specified
                    self.__args.web = False
                else:
                    # Force JSON output to profile.json.
                    self.__args.json = True
                    self.__output.html = False
                    self.__output.output_file = self.__profile_filename
            except Exception:
                # Couldn't find a browser.
                self.__args.web = False

            # If so, set variables appropriately.
            if self.__args.web and get_in_jupyter_func():
                # Force JSON output to profile.json.
                self.__args.json = True
                self.__output.html = False
                self.__output.output_file = self.__profile_filename

    def is_done(self, get_done_func) -> bool:
        """Return true if Scalene has stopped profiling."""
        return get_done_func()

    def output_profile(self, program_being_profiled: Filename, 
                      stats, pid: int, profile_this_code_func,
                      python_alias_dir, program_path,
                      entrypoint_dir,
                      program_args: Optional[List[str]] = None) -> bool:
        """Output the profile. Returns true iff there was any info reported the profile."""
        if self.__args.json:
            json_output = self.__json.output_profiles(
                program_being_profiled,
                stats,
                pid,
                profile_this_code_func,
                python_alias_dir,
                program_path,
                entrypoint_dir,
                program_args,
                profile_memory=self.__args.memory,
                reduced_profile=self.__args.reduced_profile,
            )
            # Since the default value returned for "there are no samples"
            # is `{}`, we use a sentinel value `{"is_child": True}`
            # when inside a child process to indicate that there are samples, but they weren't
            # turned into a JSON file because they'll later
            # be used by the parent process
            if "is_child" in json_output:
                return True
            outfile = self.__output.output_file
            if self.__args.outfile:
                outfile = os.path.join(
                    os.path.dirname(self.__args.outfile),
                    os.path.splitext(os.path.basename(self.__args.outfile))[0]
                    + ".json",
                )
            # If there was no output file specified, print to the console.
            if not outfile:
                if sys.platform == "win32":
                    outfile = "CON"
                else:
                    outfile = "/dev/stdout"
            # Write the JSON to the output file (or console).
            import json
            with open(outfile, "w") as f:
                f.write(json.dumps(json_output, sort_keys=True, indent=4) + "\n")
            return json_output != {}

        else:
            output = self.__output
            column_width = self.__args.column_width
            if not self.__args.html:
                # Get column width of the terminal and adjust to fit.
                import contextlib
                with contextlib.suppress(Exception):
                    # If we are in a Jupyter notebook, stick with 132
                    if "ipykernel" in sys.modules:
                        column_width = 132
                    else:
                        import shutil

                        column_width = shutil.get_terminal_size().columns
            did_output: bool = output.output_profiles(
                column_width,
                stats,
                pid,
                profile_this_code_func,
                python_alias_dir,
                program_path,
                program_args,
                profile_memory=self.__args.memory,
                reduced_profile=self.__args.reduced_profile,
            )
            return did_output

    def start_signal_handler(
        self,
        signum: SignumType,
        this_frame: Optional[FrameType],
        lifecycle_disabled_ref: List[bool],
        enable_signals_func,
    ) -> None:
        """Start the profiler from a signal."""
        if lifecycle_disabled_ref[0]:
            return
        enable_signals_func()

    def stop_signal_handler(
        self,
        signum: SignumType,
        this_frame: Optional[FrameType],
        lifecycle_disabled_ref: List[bool],
        disable_signals_func,
    ) -> None:
        """Stop the profiler from a signal."""
        if lifecycle_disabled_ref[0]:
            return
        disable_signals_func()