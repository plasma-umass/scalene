"""
Code execution and tracing functionality for Scalene profiler.

This module extracts code execution and tracing functionality from the main Scalene class
to improve code organization and reduce complexity.
"""

import functools
import os
import pathlib
import re
import sys
import traceback
from typing import Any, Dict, List, Optional, Set

from scalene.scalene_statistics import Filename, LineNumber
from scalene.scalene_utility import generate_html
from scalene import launchbrowser


class ScaleneCodeExecutor:
    """Handles code execution and tracing for Scalene."""

    def __init__(self, args, files_to_profile: Set[Filename], 
                 functions_to_profile: Dict[Filename, Set[Any]],
                 program_being_profiled: Filename, 
                 program_path: Filename,
                 entrypoint_dir: Filename):
        """Initialize the code executor."""
        self.__args = args
        self.__files_to_profile = files_to_profile
        self.__functions_to_profile = functions_to_profile
        self.__program_being_profiled = program_being_profiled
        self.__program_path = program_path
        self.__entrypoint_dir = entrypoint_dir
        self.__error_message = "Error in program being profiled"

    def profile_code(
        self,
        code: str,
        the_globals: Dict[str, str],
        the_locals: Dict[str, str],
        left: List[str],
        start_func,
        stop_func,
        output_profile_func,
        stats,
        last_profiled_tuple_func,
    ) -> int:
        """Initiate execution and profiling."""
        if self.__args.memory:
            from scalene import pywhere  # type: ignore

            pywhere.populate_struct()
        # If --off is set, tell all children to not profile and stop profiling before we even start.
        if "off" not in self.__args or not self.__args.off:
            start_func()
        # Run the code being profiled.
        exit_status = 0
        try:
            exec(code, the_globals, the_locals)
        except SystemExit as se:
            # Intercept sys.exit and propagate the error code.
            exit_status = se.code if isinstance(se.code, int) else 1
        except KeyboardInterrupt:
            # Cleanly handle keyboard interrupts (quits execution and dumps the profile).
            print("Scalene execution interrupted.", file=sys.stderr)
        except Exception as e:
            print(f"{self.__error_message}:\n", e, file=sys.stderr)
            traceback.print_exc()
            exit_status = 1

        finally:
            stop_func()
            if self.__args.memory:
                pywhere.disable_settrace()
                pywhere.depopulate_struct()

        # Leaving here in case of reversion
        # sys.settrace(None)
        (last_file, last_line, _) = last_profiled_tuple_func()
        stats.memory_stats.memory_malloc_count[last_file][last_line] += 1
        stats.memory_stats.memory_aggregate_footprint[last_file][
            last_line
        ] += stats.memory_stats.memory_current_highwater_mark[last_file][last_line]
        # If we've collected any samples, dump them.
        did_output = output_profile_func(left)
        if not did_output:
            print(
                "Scalene: The specified code did not run for long enough to profile.",
                file=sys.stderr,
            )
            # Print out hints to explain why the above message may have been printed.
            if not self.__args.profile_all:
                print(
                    "To track the time spent in all files, use the `--profile-all` option.",
                    file=sys.stderr,
                )
            elif self.__args.profile_only or self.__args.profile_exclude:
                # if --profile-only or --profile-exclude were
                # specified, suggest that the patterns might be
                # excluding too many files. Collecting the
                # previously filtered out files could allow
                # suggested fixes (as in, remove foo because it
                # matches too many files).
                print(
                    "The patterns used in `--profile-only` or `--profile-exclude` may be filtering out too many files.",
                    file=sys.stderr,
                )
            else:
                # if none of the above cases hold, indicate that
                # Scalene can only profile code that runs for at
                # least one second or allocates some threshold
                # amount of memory.
                print(
                    "Scalene can only profile code that runs for at least one second or allocates at least 10MB.",
                    file=sys.stderr,
                )

            if not (
                did_output
                and self.__args.web
                and not self.__args.cli
                and not self.__args.is_child
            ):
                return exit_status

        assert did_output
        if self.__args.web or self.__args.html:
            profile_filename = self.__args.profile_filename
            if self.__args.outfile:
                profile_filename = Filename(
                    os.path.join(
                        os.path.dirname(self.__args.outfile),
                        os.path.basename(profile_filename),
                    )
                )
            # Generate HTML file
            # (will also generate a JSON file to be consumed by the HTML)
            html_output = generate_html(
                profile_filename,
                self.__args,
                stats,
                profile_metadata={},
                program_args=left,
            )

            if self.__args.web and not self.__args.cli and not self.__args.is_child:
                launchbrowser.launch_browser(html_output)

        return exit_status

    @staticmethod
    @functools.cache
    def should_trace(filename: Filename, func: str) -> bool:
        """Return true if we should trace this filename and function."""
        # Profile everything in a Jupyter notebook cell.
        if re.match(r"<ipython-input-\d+-.*>", filename):
            return True

        if ScaleneCodeExecutor._should_trace_decorated_function(filename, func):
            return True

        if not ScaleneCodeExecutor._passes_exclusion_rules(filename):
            return False

        if ScaleneCodeExecutor._handle_jupyter_cell(filename):
            return True

        if not ScaleneCodeExecutor._passes_profile_only_rules(filename):
            return False

        return ScaleneCodeExecutor._should_trace_by_location(filename)

    @staticmethod
    def _should_trace_decorated_function(filename: Filename, func: str) -> bool:
        """Check if this function is decorated with @profile."""
        # Import here to avoid circular imports
        from scalene.scalene_profiler import Scalene
        if filename in Scalene._Scalene__files_to_profile:
            # If we have specified to profile functions in this file,
            # check if this function is one of them.
            return func in Scalene._Scalene__functions_to_profile[filename]
        return False

    @staticmethod
    def _passes_exclusion_rules(filename: Filename) -> bool:
        """Check if filename passes exclusion rules (libraries, exclude patterns)."""
        # Import here to avoid circular imports
        from scalene.scalene_profiler import Scalene
        args = Scalene._Scalene__args
        
        # Don't profile Scalene itself.
        if "scalene" in filename:
            return False

        # Don't profile Python builtins/standard library.
        try:
            if not args.profile_all:
                if (
                    ("python" in filename)
                    or ("site-packages" in filename)
                    or ("<built-in>" in filename)
                    or ("<frozen" in filename)
                ):
                    return False
        except BaseException:
            return False

        # Handle --profile-exclude patterns
        if args.profile_exclude:
            for pattern in args.profile_exclude:
                if re.search(pattern, filename):
                    return False

        return True

    @staticmethod
    def _handle_jupyter_cell(filename: Filename) -> bool:
        """Handle special Jupyter cell profiling."""
        # Check for Jupyter cells
        if "<stdin>" in filename:
            return True
            
        # Profile everything in a Jupyter notebook cell.
        if re.match(r"<ipython-input-\d+-.*>", filename):
            return True
            
        return False

    @staticmethod
    def _passes_profile_only_rules(filename: Filename) -> bool:
        """Check if filename passes profile-only patterns."""
        from scalene.scalene_profiler import Scalene
        args = Scalene._Scalene__args
        
        if args.profile_only:
            for pattern in args.profile_only:
                if re.search(pattern, filename):
                    return True
            return False
        return True

    @staticmethod
    def _should_trace_by_location(filename: Filename) -> bool:
        """Determine if we should trace based on file location."""
        from scalene.scalene_profiler import Scalene
        
        # Check if the file is in our program's directory or a subdirectory.
        filename_abs = os.path.abspath(filename)
        program_path = os.path.abspath(Scalene._Scalene__program_path)
        entrypoint_dir = os.path.abspath(Scalene._Scalene__entrypoint_dir)
        
        return (
            filename_abs.startswith(program_path)
            or filename_abs.startswith(entrypoint_dir)
            or os.path.commonpath([filename_abs, program_path]) == program_path
            or os.path.commonpath([filename_abs, entrypoint_dir]) == entrypoint_dir
        )