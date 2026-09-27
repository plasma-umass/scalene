import functools
import http.server
import json
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
from typing import Any, Dict, NewType, Optional, Tuple

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


# GUI field -> environment variable(s), first non-empty wins. Served only
# with `scalene view --api-keys-from-env`; see CustomHandler.
ENV_API_KEY_VARIABLES: Dict[str, Tuple[str, ...]] = {
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "azure": ("AZURE_OPENAI_API_KEY",),
    "azureUrl": ("AZURE_OPENAI_ENDPOINT",),
    "awsAccessKey": ("AWS_ACCESS_KEY_ID",),
    "awsSecretKey": ("AWS_SECRET_ACCESS_KEY",),
    "awsRegion": ("AWS_DEFAULT_REGION", "AWS_REGION"),
}

ENV_API_KEYS_PATH = "/env-api-keys.json"


def read_env_api_keys() -> Dict[str, str]:
    """Return the AI provider credentials set in the environment."""
    keys: Dict[str, str] = {}
    for field, variables in ENV_API_KEY_VARIABLES.items():
        for variable in variables:
            value = os.environ.get(variable, "")
            if value:
                keys[field] = value
                break
    return keys


class CustomHandler(http.server.SimpleHTTPRequestHandler):
    # Set by start() when the user passed --api-keys-from-env.
    serve_env_api_keys = False

    def do_GET(self) -> Any:
        global last_heartbeat
        if self.path == "/heartbeat":
            last_heartbeat = time.time()
            self.send_response(200)
            self.end_headers()
            return
        elif self.path.split("?", 1)[0] == ENV_API_KEYS_PATH:
            self.send_env_api_keys()
            return
        else:
            return http.server.SimpleHTTPRequestHandler.do_GET(self)

    def is_same_origin_request(self) -> bool:
        """Reject requests that other websites could make on the user's behalf.

        Keys are served as JSON with no CORS headers, so a page from another
        origin can't read the response. Two checks cover the remaining
        routes: the Host header must name this server, which defeats DNS
        rebinding (another domain resolving to 127.0.0.1), and browsers that
        send Sec-Fetch-Site must report a same-origin request.
        """
        address = self.server.server_address
        if not isinstance(address, tuple):
            return False
        port = address[1]
        allowed_hosts = {f"localhost:{port}", f"127.0.0.1:{port}"}
        if self.headers.get("Host", "") not in allowed_hosts:
            return False
        fetch_site = self.headers.get("Sec-Fetch-Site")
        return fetch_site is None or fetch_site in ("same-origin", "none")

    def send_env_api_keys(self) -> None:
        """Serve environment credentials from memory; they never touch disk."""
        if not self.is_same_origin_request():
            self.send_response(403)
            self.end_headers()
            return
        keys = read_env_api_keys() if self.serve_env_api_keys else {}
        body = json.dumps(keys).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def list_directory(self, path: Any) -> None:
        """Never list directories; serve only the files start() copied in."""
        self.send_error(404)
        return None


def monitor_heartbeat() -> None:
    global server_running
    while server_running:
        if time.time() - last_heartbeat > 60:  # 60 seconds timeout
            print("No heartbeat received, shutting down server...")
            server_running = False
            remove_serve_dir()
            os._exit(0)
        time.sleep(1)


def serve_forever(httpd: Any) -> None:
    while server_running:
        httpd.handle_request()


def run_server(host: str, port: int, directory: Optional[str] = None) -> None:
    handler = functools.partial(CustomHandler, directory=directory)
    with socketserver.TCPServer((host, port), handler) as httpd:
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
    )

    # Write the rendered content to the specified output file.
    try:
        with open(output_fname, "w", encoding="utf-8") as f:
            f.write(rendered_content)
    except OSError:
        pass


# Vendored assets the page loads, served alongside it for offline use (#982).
GUI_ASSETS = (
    "favicon.ico",
    "scalene-image.png",
    "jquery-3.6.0.slim.min.js",
    "bootstrap.min.css",
    "bootstrap.bundle.min.js",
    "prism.css",
    "scalene-gui-bundle.js",
)

# The directory the server exposes; see prepare_serve_dir().
serve_dir: Optional[str] = None


def prepare_serve_dir(filename: str) -> str:
    """Copy the page and its assets into a fresh private directory to serve.

    Serving the shared system temp directory would expose every file in it
    to anything that can reach localhost, and on a multi-user machine
    another user could pre-plant a symlink at its fixed index.html path.
    mkdtemp creates a new owner-only (0700) directory instead.
    """
    global serve_dir
    serve_dir = tempfile.mkdtemp(prefix="scalene-gui-")
    shutil.copy(filename, os.path.join(serve_dir, "index.html"))
    scalene_gui_dir = os.path.join(os.path.dirname(__file__), "scalene-gui")
    for asset in GUI_ASSETS:
        src = os.path.join(scalene_gui_dir, asset)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(serve_dir, asset))
    return serve_dir


def remove_serve_dir() -> None:
    """Delete the served copy. Called explicitly: os._exit skips atexit."""
    if serve_dir is not None:
        shutil.rmtree(serve_dir, ignore_errors=True)


def start(filename: str, port: int, api_keys_from_env: bool = False) -> None:
    CustomHandler.serve_env_api_keys = api_keys_from_env
    while not is_port_available(port):
        port += 1

    if filename == "demo":
        generate_html(Filename("demo"), Filename("demo.html"))
        filename = "demo.html"
    directory = prepare_serve_dir(filename)

    server_thread = threading.Thread(target=run_server, args=[HOST, port, directory])
    server_thread.start()
    threading.Thread(target=monitor_heartbeat).start()

    webbrowser.open_new(f"http://{HOST}:{port}/")
    server_thread.join()

    remove_serve_dir()

    # Optional: a delay to ensure all resources are released
    time.sleep(1)
    os._exit(0)  # Forcefully stops the program


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 2:
        filename = sys.argv[1]
        port = int(sys.argv[2])
        start(filename, port, api_keys_from_env="--api-keys-from-env" in sys.argv[3:])
    else:
        print("Need to supply filename and port arguments.")
