"""Replacement for exec/eval/compile to track dynamically executed code.

This module intercepts exec(), eval(), and compile() to capture source code
that would otherwise be invisible to the profiler. When code is executed via
exec() or eval() with a string source, Python normally uses '<string>' as the
filename, making it impossible to show line-by-line profiling.

By wrapping these builtins, we:
1. Generate unique virtual filenames that include the caller's location
2. Store the source in linecache so it can be retrieved during profiling output
3. Compile/execute using our virtual filename so profiler samples reference it
"""

import builtins
import linecache
import os
import sys
from types import FrameType
from typing import Any, Dict, Optional

from scalene.scalene_profiler import Scalene


def _is_synthetic_filename(filename: str) -> bool:
    """Check if a filename is a Python synthetic name like '<string>'."""
    return filename.startswith("<") and filename.endswith(">")


def _register_source_in_linecache(filename: str, source: str) -> None:
    """Register source code in linecache for later retrieval."""
    lines = source.splitlines(keepends=True)
    # Ensure the last line has a newline
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    # linecache entry format: (size, mtime, lines, fullname)
    # mtime=None indicates the source won't change
    linecache.cache[filename] = (len(source), None, lines, filename)


def _make_virtual_filename(kind: str, caller_frame: FrameType) -> str:
    """Create a virtual filename encoding the caller's location.

    Format: <exec@filename:lineno> or <eval@filename:lineno>
    """
    caller_filename = caller_frame.f_code.co_filename
    caller_lineno = caller_frame.f_lineno
    # Use basename to keep the filename short
    basename = os.path.basename(caller_filename)
    return f"<{kind}@{basename}:{caller_lineno}>"


@Scalene.shim
def replacement_exec(scalene: Scalene) -> None:  # noqa: ARG001
    """Replace exec(), eval(), and compile() to track dynamic code execution."""
    orig_exec = builtins.exec
    orig_eval = builtins.eval
    orig_compile = builtins.compile

    def exec_replacement(
        __source: Any,
        __globals: Optional[Dict[str, Any]] = None,
        __locals: Optional[Dict[str, Any]] = None,
        /,
        **kwargs: Any,
    ) -> None:
        """Replacement for exec() that tracks source code.

        When given a string, we compile it with a unique virtual filename
        and register the source in linecache for profiling.
        """
        # Get caller frame - needed both for virtual filename and for
        # getting globals/locals when not provided
        caller_frame = sys._getframe(1)

        if isinstance(__source, str):
            virtual_filename = _make_virtual_filename("exec", caller_frame)
            _register_source_in_linecache(virtual_filename, __source)
            code_obj = orig_compile(__source, virtual_filename, "exec")
            __source = code_obj

        # When globals/locals are not specified, exec() uses the caller's frame.
        # Since we're wrapping exec, we need to explicitly get the caller's frame.
        if __globals is None:
            __globals = caller_frame.f_globals
            if __locals is None:
                __locals = caller_frame.f_locals

        if __locals is None:
            orig_exec(__source, __globals)
        else:
            orig_exec(__source, __globals, __locals, **kwargs)

    def eval_replacement(
        __source: Any,
        __globals: Optional[Dict[str, Any]] = None,
        __locals: Optional[Dict[str, Any]] = None,
        /,
    ) -> Any:
        """Replacement for eval() that tracks source code.

        When given a string, we compile it with a unique virtual filename
        and register the source in linecache for profiling.
        """
        # Get caller frame - needed both for virtual filename and for
        # getting globals/locals when not provided
        caller_frame = sys._getframe(1)

        if isinstance(__source, str):
            virtual_filename = _make_virtual_filename("eval", caller_frame)
            _register_source_in_linecache(virtual_filename, __source)
            code_obj = orig_compile(__source, virtual_filename, "eval")
            __source = code_obj

        # When globals/locals are not specified, eval() uses the caller's frame.
        # Since we're wrapping eval, we need to explicitly get the caller's frame.
        if __globals is None:
            __globals = caller_frame.f_globals
            if __locals is None:
                __locals = caller_frame.f_locals

        if __locals is None:
            return orig_eval(__source, __globals)
        else:
            return orig_eval(__source, __globals, __locals)

    def compile_replacement(
        source: Any,
        filename: str,
        mode: str,
        flags: int = 0,
        dont_inherit: bool = False,
        optimize: int = -1,
        **kwargs: Any,
    ) -> Any:
        """Replacement for compile() that tracks source code.

        When the filename is a synthetic name like '<string>' and we have
        a string source, we register it in linecache with the given filename.
        This handles cases where users call compile() directly.
        """
        if isinstance(source, str) and _is_synthetic_filename(filename):
            _register_source_in_linecache(filename, source)

        return orig_compile(
            source, filename, mode, flags, dont_inherit, optimize, **kwargs
        )

    builtins.exec = exec_replacement  # type: ignore[assignment]
    builtins.eval = eval_replacement  # type: ignore[assignment]
    builtins.compile = compile_replacement  # type: ignore[assignment]
