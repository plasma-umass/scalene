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

import __future__

import builtins
import linecache
import os
import sys
from types import FrameType
from typing import Any, Dict, Optional

from scalene.scalene_profiler import Scalene

# Bitmask covering all __future__ compiler flags. compile() inherits these
# from the calling frame when dont_inherit=False, but our wrappers break
# that inheritance chain. We extract them from the real caller's co_flags
# to propagate them explicitly. This is the same approach CPython's doctest
# module uses and covers all past and future __future__ features.
_FUTURE_FLAGS_MASK = 0
for _name in __future__.all_feature_names:
    _FUTURE_FLAGS_MASK |= getattr(__future__, _name).compiler_flag
del _name


def _caller_future_flags(frame: FrameType) -> int:
    """Extract __future__ compiler flags from a frame's code object."""
    return frame.f_code.co_flags & _FUTURE_FLAGS_MASK


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
        /,
        globals: Optional[Dict[str, Any]] = None,
        locals: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        """Replacement for exec() that tracks source code.

        When given a string, we compile it with a unique virtual filename
        and register the source in linecache for profiling.

        Note: In Python 3.14+, exec() accepts globals/locals as keyword arguments,
        plus a keyword-only 'closure' parameter. We use 'globals' and 'locals'
        as parameter names (shadowing builtins) to match the built-in signature.
        """
        # Get caller frame - needed both for virtual filename and for
        # getting globals/locals when not provided
        caller_frame = sys._getframe(1)

        if isinstance(__source, str):
            virtual_filename = _make_virtual_filename("exec", caller_frame)
            _register_source_in_linecache(virtual_filename, __source)
            # Propagate the caller's __future__ flags (e.g. annotations)
            # so that code compiled here behaves the same as if exec()
            # compiled it directly in the caller's context.
            flags = _caller_future_flags(caller_frame)
            code_obj = orig_compile(
                __source, virtual_filename, "exec",
                flags=flags, dont_inherit=True,
            )
            __source = code_obj

        # When globals/locals are not specified, exec() uses the caller's frame.
        # Since we're wrapping exec, we need to explicitly get the caller's frame.
        if globals is None:
            globals = caller_frame.f_globals
            if locals is None:
                locals = caller_frame.f_locals

        if locals is None:
            orig_exec(__source, globals, **kwargs)
        else:
            orig_exec(__source, globals, locals, **kwargs)

    def eval_replacement(
        __source: Any,
        /,
        globals: Optional[Dict[str, Any]] = None,
        locals: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Replacement for eval() that tracks source code.

        When given a string, we compile it with a unique virtual filename
        and register the source in linecache for profiling.

        Note: In Python 3.14+, eval() accepts globals/locals as keyword arguments.
        We use 'globals' and 'locals' as parameter names (shadowing builtins)
        to match the built-in signature exactly.
        """
        # Get caller frame - needed both for virtual filename and for
        # getting globals/locals when not provided
        caller_frame = sys._getframe(1)

        if isinstance(__source, str):
            virtual_filename = _make_virtual_filename("eval", caller_frame)
            _register_source_in_linecache(virtual_filename, __source)
            flags = _caller_future_flags(caller_frame)
            code_obj = orig_compile(
                __source, virtual_filename, "eval",
                flags=flags, dont_inherit=True,
            )
            __source = code_obj

        # When globals/locals are not specified, eval() uses the caller's frame.
        # Since we're wrapping eval, we need to explicitly get the caller's frame.
        if globals is None:
            globals = caller_frame.f_globals
            if locals is None:
                locals = caller_frame.f_locals

        if locals is None:
            return orig_eval(__source, globals)
        else:
            return orig_eval(__source, globals, locals)

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

        if not dont_inherit:
            # The real compile() would inherit __future__ flags from its
            # caller's frame. Since our wrapper is now the immediate caller,
            # we must manually propagate flags from the real caller.
            caller_frame = sys._getframe(1)
            flags |= _caller_future_flags(caller_frame)
            dont_inherit = True

        return orig_compile(
            source, filename, mode, flags, dont_inherit, optimize, **kwargs
        )

    builtins.exec = exec_replacement  # type: ignore[assignment]
    builtins.eval = eval_replacement  # type: ignore[assignment]
    builtins.compile = compile_replacement  # type: ignore[assignment]
