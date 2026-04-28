"""Tracing and filtering logic for Scalene profiler."""

from __future__ import annotations

import functools
import os
import pathlib
import re
import site
import sys
import sysconfig
from collections import defaultdict
from typing import Any, Callable

from scalene.scalene_arguments import ScaleneArguments
from scalene.scalene_statistics import Filename


class ScaleneTracing:
    """Handles tracing decisions and file filtering for the profiler."""

    def __init__(
        self,
        args: ScaleneArguments,
        profiler_base: str,
        program_path: Filename,
    ) -> None:
        """Initialize the tracing module.

        Args:
            args: Scalene arguments.
            profiler_base: Base path of the profiler (to exclude from profiling).
            program_path: Path of the program being profiled.
        """
        self._args = args
        # Use resolved Path for proper cross-platform path comparison
        self._profiler_base_path = pathlib.Path(profiler_base).resolve()
        self._program_path = program_path
        self._system_lib_paths: tuple[str, ...] = ()
        self._files_to_profile: set[Filename] = set()
        self._functions_to_profile: dict[Filename, set[Any]] = defaultdict(set)

    def set_args(self, args: ScaleneArguments) -> None:
        """Update the arguments."""
        self._args = args
        # Clear the cache when args change
        self.should_trace.cache_clear()

    def set_program_path(self, program_path: Filename) -> None:
        """Update the program path."""
        self._program_path = program_path
        # Clear the cache when program path changes
        self.should_trace.cache_clear()

    def add_file_to_profile(self, filename: Filename) -> None:
        """Add a file to the set of files to profile (for @profile decorator)."""
        self._files_to_profile.add(filename)
        self.should_trace.cache_clear()

    def add_function_to_profile(self, filename: Filename, func: Any) -> None:
        """Add a function to profile (for @profile decorator)."""
        self._functions_to_profile[filename].add(func)
        self.should_trace.cache_clear()

    @property
    def files_to_profile(self) -> set[Filename]:
        """Get the set of files to profile."""
        return self._files_to_profile

    @property
    def functions_to_profile(self) -> dict[Filename, set[Any]]:
        """Get the dict of functions to profile."""
        return self._functions_to_profile

    # Using lru_cache on instance method is safe here since ScaleneTracing
    # is a singleton-like object that lives for the profiler's lifetime.
    @functools.lru_cache(maxsize=None)  # noqa: B019
    def should_trace(self, filename: Filename, func: str) -> bool:
        """Return true if we should trace this filename and function."""
        if not filename:
            return False
        # Use proper path comparison to exclude Scalene's own modules.
        # This handles cross-platform path separators and case sensitivity correctly.
        try:
            resolved_path = pathlib.Path(filename).resolve()
            if resolved_path.is_relative_to(self._profiler_base_path):
                return False
        except (OSError, ValueError):
            # If we can't resolve the path, fall back to string comparison
            if str(self._profiler_base_path) in filename:
                return False

        # Check if this function is specifically decorated for profiling
        if self._should_trace_decorated_function(filename, func):
            return True
        elif self._functions_to_profile and filename in self._functions_to_profile:
            return False

        # Check exclusion rules
        if not self._passes_exclusion_rules(filename):
            return False

        # Handle special Jupyter cell case
        if self._handle_jupyter_cell(filename):
            return True

        # Check profile-only patterns
        if not self._passes_profile_only_rules(filename):
            return False

        # Handle special non-file cases
        # Allow exec/eval virtual filenames through (e.g., <exec@myfile.py:42>)
        if (
            filename[0] == "<"
            and filename[-1] == ">"
            and not (filename.startswith("<exec@") or filename.startswith("<eval@"))
        ):
            return False

        # Final decision: profile-all or program directory check
        return self._should_trace_by_location(filename)

    def _should_trace_decorated_function(self, filename: Filename, func: str) -> bool:
        """Check if this function is decorated with @profile."""
        if self._functions_to_profile and filename in self._functions_to_profile:
            return func in {
                fn.__code__.co_name for fn in self._functions_to_profile[filename]
            }
        return False

    def _passes_exclusion_rules(self, filename: Filename) -> bool:
        """Check if filename passes exclusion rules (libraries, exclude patterns)."""
        try:
            resolved_filename = str(pathlib.Path(filename).resolve())
        except OSError:
            return False

        if not self._args.profile_all:
            for n in sysconfig.get_scheme_names():
                for p in sysconfig.get_path_names():
                    the_path = sysconfig.get_path(p, n)
                    if the_path:
                        libdir = str(pathlib.Path(the_path).resolve())
                        if libdir in resolved_filename:
                            return False

        # Check explicit exclude patterns
        profile_exclude_list = self._args.profile_exclude.split(",")
        return not any(prof in filename for prof in profile_exclude_list if prof != "")

    def _handle_jupyter_cell(self, filename: Filename) -> bool:
        """Handle special Jupyter cell profiling."""
        if filename.startswith("_ipython-input-"):
            import IPython

            if result := re.match(r"_ipython-input-([0-9]+)-.*", filename):
                cell_contents = IPython.get_ipython().history_manager.input_hist_raw[  # type: ignore[no-untyped-call,unused-ignore]
                    int(result[1])
                ]
                with open(filename, "w+") as f:
                    f.write(cell_contents)
                return True
        return False

    def _passes_profile_only_rules(self, filename: Filename) -> bool:
        """Check if filename passes profile-only patterns."""
        profile_only_set = set(self._args.profile_only.split(","))
        return not (
            profile_only_set and all(prof not in filename for prof in profile_only_set)
        )

    def _init_system_lib_paths(self) -> None:
        """Initialize the list of system library paths to exclude from profiling."""
        if self._system_lib_paths:
            return

        paths = set()

        # Standard library location
        stdlib_path = sysconfig.get_path("stdlib")
        if stdlib_path:
            paths.add(os.path.normpath(stdlib_path))

        # Site-packages locations
        try:
            for sp in site.getsitepackages():
                paths.add(os.path.normpath(sp))
            user_site = site.getusersitepackages()
            if user_site:
                paths.add(os.path.normpath(user_site))
        except Exception:
            pass

        # Python prefix paths
        for prefix in (sys.prefix, sys.base_prefix, sys.exec_prefix):
            if prefix:
                paths.add(os.path.normpath(prefix))

        # Platform-specific library path
        for path_name in ("platstdlib", "purelib", "platlib"):
            path = sysconfig.get_path(path_name)
            if path:
                paths.add(os.path.normpath(path))

        self._system_lib_paths = tuple(sorted(paths, key=len, reverse=True))

    def _is_system_library(self, filename: str) -> bool:
        """Check if a file is part of Python's system libraries or installed packages."""
        if not self._system_lib_paths:
            self._init_system_lib_paths()

        normalized = os.path.normpath(filename)
        return any(normalized.startswith(path) for path in self._system_lib_paths)

    def _should_trace_by_location(self, filename: Filename) -> bool:
        """Determine if we should trace based on file location."""
        if self._args.profile_all:
            return True

        # Always trace exec/eval virtual filenames (e.g., <exec@myfile.py:42>)
        # These represent dynamically executed code from the user's program
        if filename.startswith("<exec@") or filename.startswith("<eval@"):
            return True

        # Skip system libraries unless explicitly requested
        if not self._args.profile_system_libraries and self._is_system_library(
            filename
        ):
            return False

        # Use proper path comparison for cross-platform compatibility.
        # Check if the file is in the same directory tree as the program being profiled.
        try:
            file_path = pathlib.Path(filename).resolve()
            program_path = pathlib.Path(self._program_path).resolve()
            # Check if file is in program's directory or a subdirectory
            return (
                file_path.is_relative_to(program_path)
                or file_path.parent == program_path.parent
            )
        except (OSError, ValueError):
            # Fall back to string comparison if path resolution fails
            normalized_filename = Filename(
                os.path.normpath(os.path.join(self._program_path, filename))
            )
            return self._program_path in normalized_filename


def create_should_trace_func(
    tracing: ScaleneTracing,
) -> Callable[[Filename, str], bool]:
    """Create a should_trace function bound to a ScaleneTracing instance.

    This is useful for passing to other modules that need the should_trace logic.
    """
    return tracing.should_trace
