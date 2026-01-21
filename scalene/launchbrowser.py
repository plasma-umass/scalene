import http.server
import os
import pathlib
import platform
import shutil
import socket
import socketserver
import sys
import tempfile
import threading
import time
import webbrowser
from typing import Any, NewType

from jinja2 import Environment, FileSystemLoader


def launch_browser_insecure(url: str) -> None:
    if platform.system() == "Windows":
        chrome_path = "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe"
    elif platform.system() == "Linux":
        chrome_path = "/usr/bin/google-chrome"
    elif platform.system() == "Darwin":
        chrome_path = "/Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome"

    # Create a temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a command with the required flags
        chrome_cmd = (
            f'{chrome_path} %s --disable-web-security --user-data-dir="{temp_dir}"'
        )

        # Register the new browser type
        webbrowser.register(
            "chrome_with_flags",
            None,
            webbrowser.Chrome(chrome_cmd),
            preferred=True,
        )

        # Open a URL using the new browser type
        webbrowser.get(chrome_cmd).open(url)


HOST = "localhost"
shutdown_requested = False
last_heartbeat = time.time()
server_running = True


class CustomHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self) -> Any:
        global last_heartbeat
        if self.path == "/heartbeat":
            last_heartbeat = time.time()
            self.send_response(200)
            self.end_headers()
            return
        else:
            return http.server.SimpleHTTPRequestHandler.do_GET(self)


def monitor_heartbeat() -> None:
    global server_running
    while server_running:
        if time.time() - last_heartbeat > 60:  # 60 seconds timeout
            print("No heartbeat received, shutting down server...")
            server_running = False
            os._exit(0)
        time.sleep(1)


def serve_forever(httpd: Any) -> None:
    while server_running:
        httpd.handle_request()


def run_server(host: str, port: int) -> None:
    with socketserver.TCPServer((host, port), CustomHandler) as httpd:
        print(f"Serving at http://{host}:{port}")
        serve_forever(httpd)


def is_port_available(port: int) -> bool:
    """
    Check if a given TCP port is available to start a server on the local machine.

    :param port: Port number as an integer.
    :return: True if the port is available, False otherwise.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("localhost", port))
            return True
        except OSError:
            return False


Filename = NewType("Filename", str)
LineNumber = NewType("LineNumber", int)


def generate_html(profile_fname: Filename, output_fname: Filename) -> None:
    """Apply a template to generate a single HTML payload containing the current profile."""

    try:
        # Load the profile
        profile_file = pathlib.Path(profile_fname)
        profile = profile_file.read_text()
    except FileNotFoundError:
        assert profile_fname == "demo"
        profile = "{}"
        # return

    scalene_dir = os.path.dirname(__file__)

    # Put the profile and everything else into the template.
    environment = Environment(
        loader=FileSystemLoader(os.path.join(scalene_dir, "scalene-gui"))
    )
    template = environment.get_template("index.html.template")
    try:
        import scalene_config
    except ModuleNotFoundError:
        import scalene.scalene_config as scalene_config
    rendered_content = template.render(
        profile=profile,
        scalene_version=scalene_config.scalene_version,
        scalene_date=scalene_config.scalene_date,
        api_keys={},
    )

    # Write the rendered content to the specified output file.
    try:
        with open(output_fname, "w", encoding="utf-8") as f:
            f.write(rendered_content)
    except OSError:
        pass


def start(filename: str, port: int) -> None:
    while not is_port_available(port):
        port += 1

    cwd = os.getcwd()
    if filename == "demo":
        generate_html(Filename("demo"), Filename("demo.html"))
        filename = "demo.html"
    temp_dir = tempfile.gettempdir()
    shutil.copy(filename, os.path.join(temp_dir, "index.html"))

    # Copy vendored assets for offline support (issue #982)
    scalene_gui_dir = os.path.join(os.path.dirname(__file__), "scalene-gui")
    for asset in [
        "favicon.ico",
        "scalene-image.png",
        "jquery-3.6.0.slim.min.js",
        "bootstrap.min.css",
        "bootstrap.bundle.min.js",
        "prism.css",
        "scalene-gui-bundle.js",
    ]:
        src = os.path.join(scalene_gui_dir, asset)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(temp_dir, asset))

    os.chdir(temp_dir)
    server_thread = threading.Thread(target=run_server, args=[HOST, port])
    server_thread.start()
    threading.Thread(target=monitor_heartbeat).start()

    webbrowser.open_new(f"http://{HOST}:{port}/")
    server_thread.join()

    os.chdir(cwd)

    # Optional: a delay to ensure all resources are released
    time.sleep(1)
    os._exit(0)  # Forcefully stops the program


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 2:
        filename = sys.argv[1]
        port = int(sys.argv[2])
        start(filename, port)
    else:
        print("Need to supply filename and port arguments.")
