import inspect
import sys
from types import FrameType
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    cast
)
from scalene.scalene_statistics import (
    Filename,
    LineNumber
)

# These are here to simplify print debugging, a la C.
class LineNo:
    def __str__(self) -> str:
        frame = inspect.currentframe()
        assert frame
        assert frame.f_back
        return str(frame.f_back.f_lineno)

class FileName:
    def __str__(self) -> str:
        frame = inspect.currentframe()
        assert frame
        assert frame.f_back
        assert frame.f_back.f_code
        return str(frame.f_back.f_code.co_filename)

__LINE__ = LineNo()
__FILE__ = FileName()

def add_stack(frame: FrameType,
              should_trace: Callable[[Filename, str], bool],
              stacks: Dict[Tuple[Any], int]) -> None:
    """Add one to the stack starting from this frame."""
    stk = list()
    f : Optional[FrameType] = frame
    while f:
        if should_trace(Filename(f.f_code.co_filename), f.f_code.co_name):
            stk.insert(0, (f.f_code.co_filename, f.f_code.co_name, f.f_lineno))
        f = f.f_back
    stacks[tuple(stk)] += 1

def on_stack(
    frame: FrameType, fname: Filename, lineno: LineNumber
) -> Optional[FrameType]:
    """Find a frame matching the given filename and line number, if any.

    Used for checking whether we are still executing the same line
    of code or not in invalidate_lines (for per-line memory
    accounting).
    """
    f = frame
    current_file_and_line = (fname, lineno)
    while f:
        if (f.f_code.co_filename, f.f_lineno) == current_file_and_line:
            return f
        f = cast(FrameType, f.f_back)
    return None

def get_fully_qualified_name(frame: FrameType) -> Filename:
    # Obtain the fully-qualified name.
    version = sys.version_info
    if version.major >= 3 and version.minor >= 11:
        # Introduced in Python 3.11
        fn_name = Filename(frame.f_code.co_qualname)
        return fn_name
    f = frame
    # Manually search for an enclosing class.
    fn_name = Filename(f.f_code.co_name)
    while f and f.f_back and f.f_back.f_code:
        if "self" in f.f_locals:
            prepend_name = f.f_locals["self"].__class__.__name__
            if "Scalene" not in prepend_name:
                fn_name = Filename(f"{prepend_name}.{fn_name}")
            break
        if "cls" in f.f_locals:
            prepend_name = getattr(f.f_locals["cls"], "__name__", None)
            if not prepend_name or "Scalene" in prepend_name:
                break
            fn_name = Filename(f"{prepend_name}.{fn_name}")
            break
        f = f.f_back
    return fn_name
