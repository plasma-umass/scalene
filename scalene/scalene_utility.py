import functools
import http.server
import os
import pathlib
import shutil
import signal
import socketserver
import subprocess
import sys
import tempfile
import threading
import webbrowser


from jinja2 import Environment, FileSystemLoader
from types import BuiltinFunctionType, FrameType, FunctionType, ModuleType
from typing import Any, Callable, Dict, List, Optional, Tuple, Union, cast

from scalene.scalene_statistics import (
    Filename,
    LineNumber,
    StackFrame,
    StackStats,
    ScaleneStatistics,
)
from scalene.scalene_config import scalene_version, scalene_date


def enter_function_meta(
    frame: FrameType,
    should_trace: Callable[[Filename, str], bool],
    stats: ScaleneStatistics,
) -> None:
    """Update tracking info so we can correctly report line number info later."""
    fname = Filename(frame.f_code.co_filename)
    lineno = LineNumber(frame.f_lineno)

    f = frame
    try:
        while "<" in Filename(f.f_code.co_name):
            f = cast(FrameType, f.f_back)
            # Handle case where the function with the name wrapped
            # in triangle brackets is at the bottom of the stack
            if f is None:
                return
    except Exception:
        return
    if not should_trace(Filename(f.f_code.co_filename), f.f_code.co_name):
        return

    fn_name = get_fully_qualified_name(f)
    firstline = f.f_code.co_firstlineno

    stats.function_map[fname][lineno] = fn_name
    stats.firstline_map[fn_name] = LineNumber(firstline)


def compute_frames_to_record(
    should_trace: Callable[[Filename, str], bool],
) -> List[Tuple[FrameType, int, FrameType]]:
    """Collect all stack frames that Scalene actually processes.
    Returns final frame (up to a line in a file we are profiling), the
    thread identifier, and the original frame.
    """
    frames: List[Tuple[FrameType, int]] = [
        (
            cast(
                FrameType,
                sys._current_frames().get(cast(int, t.ident), None),
            ),
            cast(int, t.ident),
        )
        for t in threading.enumerate()
        if t != threading.main_thread()
    ]
    # Put the main thread in the front.

    tid = cast(int, threading.main_thread().ident)
    frames.insert(
        0,
        (
            sys._current_frames().get(tid, cast(FrameType, None)),
            tid,
        ),
    )
    # Process all the frames to remove ones we aren't going to track.
    new_frames: List[Tuple[FrameType, int, FrameType]] = []
    for frame, tident in frames:
        orig_frame = frame
        if not frame:
            continue
        fname = frame.f_code.co_filename
        func = frame.f_code.co_name
        # Record samples only for files we care about.
        if not fname:
            # 'eval/compile' gives no f_code.co_filename.  We have
            # to look back into the outer frame in order to check
            # the co_filename.
            back = cast(FrameType, frame.f_back)
            fname = Filename(back.f_code.co_filename)
            func = back.f_code.co_name
        while not should_trace(Filename(fname), func):
            # Walk the stack backwards until we hit a frame that
            # IS one we should trace (if there is one).  i.e., if
            # it's in the code being profiled, and it is just
            # calling stuff deep in libraries.
            if frame:
                frame = cast(FrameType, frame.f_back)
            else:
                break
            if frame:
                fname = frame.f_code.co_filename
                func = frame.f_code.co_name
        if frame:
            new_frames.append((frame, tident, orig_frame))
    del frames[:]
    return new_frames


def add_stack(
    frame: FrameType,
    should_trace: Callable[[Filename, str], bool],
    stacks: Dict[Tuple[StackFrame, ...], StackStats],
    python_time: float,
    c_time: float,
    cpu_samples: float,
) -> None:
    """Add one to the stack starting from this frame."""
    stk: List[StackFrame] = list()
    f: Optional[FrameType] = frame
    while f:
        if should_trace(Filename(f.f_code.co_filename), f.f_code.co_name):
            stk.insert(
                0,
                StackFrame(
                    filename=str(f.f_code.co_filename),
                    function_name=str(get_fully_qualified_name(f)),
                    line_number=int(f.f_lineno),
                ),
            )
        f = f.f_back
    stack_tuple = tuple(stk)
    if stack_tuple not in stacks:
        stacks[stack_tuple] = StackStats(1, python_time, c_time, cpu_samples)
    else:
        prev_stats = stacks[stack_tuple]
        stacks[stack_tuple] = StackStats(
            prev_stats.count + 1,
            prev_stats.python_time + python_time,
            prev_stats.c_time + c_time,
            prev_stats.cpu_samples + cpu_samples,
        )


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
    if sys.version_info >= (3, 11):
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


def flamegraph_format(stacks: Dict[Tuple[StackFrame], StackStats]) -> str:
    """Converts stacks to a string suitable for input to Brendan Gregg's flamegraph.pl script."""
    output = ""
    for stk in stacks:
        for frame in stk:
            output += f"{frame.filename} {frame.function_name}:{frame.line_number};"
        output += " " + str(stacks[stk].count)
        output += "\n"
    return output


def generate_html(profile_fname: Filename, output_fname: Filename) -> None:
    """Apply a template to generate a single HTML payload containing the current profile."""

    def read_file_content(directory: str, subdirectory: str, filename: str) -> str:
        file_path = os.path.join(directory, subdirectory, filename)
        file_content = ""
        try:
            file_content = pathlib.Path(file_path).read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            # Create a new error with just the custom message
            raise UnicodeDecodeError(
                "utf-8",
                b"",
                0,
                0,
                f"Failed to decode file {file_path}. Ensure the file is UTF-8 encoded.",
            ) from e
        return file_content

    try:
        # Load the profile
        profile_file = pathlib.Path(profile_fname)
        profile = ""
        try:
            profile = profile_file.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            # Create a new error with just the custom message
            raise UnicodeDecodeError(
                "utf-8",
                b"",
                0,
                0,
                f"Failed to decode file {profile_file}. Ensure the file is UTF-8 encoded.",
            ) from e

    except FileNotFoundError:
        assert profile_fname == "demo"
        profile = ""
        # return

    # Load the GUI JavaScript file.
    scalene_dir = os.path.dirname(__file__)

    file_contents = {
        "scalene_gui_js_text": read_file_content(
            scalene_dir, "scalene-gui", "scalene-gui-bundle.js"
        ),
        "prism_css_text": read_file_content(scalene_dir, "scalene-gui", "prism.css"),
    }

    # Put the profile and everything else into the template.
    environment = Environment(
        loader=FileSystemLoader(os.path.join(scalene_dir, "scalene-gui"))
    )
    template = environment.get_template("index.html.template")
    rendered_content = template.render(
        profile=profile,
        gui_js=file_contents["scalene_gui_js_text"],
        prism_css=file_contents["prism_css_text"],
        scalene_version=scalene_version,
        scalene_date=scalene_date,
    )

    # Write the rendered content to the specified output file.
    try:
        with open(output_fname, "w", encoding="utf-8") as f:
            f.write(rendered_content)
    except OSError:
        pass


def start_server(port: int, directory: str) -> None:
    try:
        handler = http.server.SimpleHTTPRequestHandler
        with socketserver.TCPServer(("", port), handler) as httpd:
            os.chdir(directory)
            httpd.serve_forever()
    except OSError:
        # print(f"Port {port} is already in use. Please try a different port.")
        pass


def show_browser(file_path: str, port: int, orig_python: str = "python3") -> None:
    temp_dir = tempfile.gettempdir()

    # Copy file to the temporary directory
    shutil.copy(file_path, os.path.join(temp_dir, "index.html"))

    # Open web browser in a new subprocess
    curr_dir = os.getcwd()
    try:
        os.chdir(temp_dir)
        subprocess.Popen(
            [
                orig_python,
                os.path.join(os.path.dirname(__file__), "launchbrowser.py"),
                file_path,
                f"{port}",
            ]
        )
        # Open web browser to local server
        webbrowser.open(f"http://localhost:{port}/")
    except (FileNotFoundError, PermissionError, OSError):
        pass
    except webbrowser.Error:
        pass
    finally:
        os.chdir(curr_dir)


def patch_module_functions_with_signal_blocking(
    module: ModuleType, signal_to_block: signal.Signals
) -> None:
    """Patch all functions in the given module to block the specified signal during execution."""

    def signal_blocking_wrapper(func: Union[BuiltinFunctionType, FunctionType]) -> Any:
        """Wrap a function to block the specified signal during its execution."""

        @functools.wraps(func)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            # Block the specified signal temporarily
            original_sigmask = signal.pthread_sigmask(
                signal.SIG_BLOCK, [signal_to_block]
            )
            try:
                return func(*args, **kwargs)
            finally:
                # Restore original signal mask
                signal.pthread_sigmask(signal.SIG_SETMASK, original_sigmask)

        return wrapped

    # Iterate through all attributes of the module
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if isinstance(attr, (BuiltinFunctionType, FunctionType)):
            wrapped_attr = signal_blocking_wrapper(attr)
            setattr(module, attr_name, wrapped_attr)
