import http.server
import inspect
import os
import pathlib
import sys
import shutil
import socketserver
import subprocess
import tempfile
import webbrowser


from jinja2 import Environment, FileSystemLoader
from types import CodeType, FrameType
from typing import Any, Callable, Dict, List, Optional, Tuple, cast
from scalene.scalene_statistics import Filename, LineNumber
from scalene.scalene_version import scalene_version, scalene_date

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


def add_stack(
    frame: FrameType,
    should_trace: Callable[[Filename, str], bool],
    stacks: Dict[Any, int],
) -> None:
    """Add one to the stack starting from this frame."""
    stk: List[Tuple[str, str, int]] = list()
    f: Optional[FrameType] = frame
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
        fn_name = Filename(frame.f_code.co_qualname)  # type: ignore
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


def flamegraph_format(stacks: Dict[Tuple[Any], int]) -> str:
    """Converts stacks to a string suitable for input to Brendan Gregg's flamegraph.pl script."""
    output = ""
    for stk in stacks.keys():
        for item in stk:
            (fname, fn_name, lineno) = item
            output += f"{fname} {fn_name}:{lineno};"
        output += " " + str(stacks[stk])
        output += "\n"
    return output


def generate_html(profile_fname: Filename, output_fname: Filename) -> None:
    """Apply a template to generate a single HTML payload containing the current profile."""

    try:
        # Load the profile
        profile_file = pathlib.Path(profile_fname)
        profile = profile_file.read_text()
    except FileNotFoundError:
        return

    # Load the GUI JavaScript file.
    scalene_dir = os.path.dirname(__file__)
    gui_fname = os.path.join(scalene_dir, "scalene-gui", "scalene-gui.js")
    gui_file = pathlib.Path(gui_fname)
    gui_js = gui_file.read_text()

    # Put the profile and everything else into the template.
    environment = Environment(
        loader=FileSystemLoader(os.path.join(scalene_dir, "scalene-gui"))
    )
    template = environment.get_template("index.html.template")
    rendered_content = template.render(
        profile=profile,
        gui_js=gui_js,
        scalene_version=scalene_version,
        scalene_date=scalene_date,
    )

    # Write the rendered content to the specified output file.
    try:
        with open(output_fname, "w", encoding="utf-8") as f:
            f.write(rendered_content)
    except OSError:
        pass


def start_server(port, directory):
    try:
        handler = http.server.SimpleHTTPRequestHandler
        with socketserver.TCPServer(("", port), handler) as httpd:
            os.chdir(directory)
            # print(f"Serving at port {port}")
            httpd.serve_forever()
    except OSError as e:
        # print(f"Port {port} is already in use. Please try a different port.")
        pass

def show_browser(file_path, port, orig_python='python3'):
    temp_dir = tempfile.gettempdir()

    # Copy file to the temporary directory
    shutil.copy(file_path, os.path.join(temp_dir, 'index.html'))

    # Open web browser in a new subprocess
    url = f'http://localhost:{port}/'
    curr_dir = os.getcwd()
    try:
        os.chdir(temp_dir)
        subprocess.Popen([orig_python, '-m', 'http.server', f"{port}"],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        # Start server in a new thread
        #server_thread = Thread(target=start_server, args=(port, temp_dir))
        #server_thread.daemon = True
        #server_thread.start()
    
        # Open web browser to local server
        webbrowser.open(f'http://localhost:{port}/')
    except:
        pass
    finally:
        os.chdir(curr_dir)
