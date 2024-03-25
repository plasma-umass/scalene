import http.server
import os
import platform
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser

import pathlib
from jinja2 import Environment, FileSystemLoader
from typing import Any, NewType

def read_file_content(directory: str, subdirectory: str, filename: str) -> str:
    file_path = os.path.join(directory, subdirectory, filename)
    return pathlib.Path(file_path).read_text()


def launch_browser_insecure(url: str) -> None:
    if platform.system() == 'Windows':
        chrome_path = 'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe'
    elif platform.system() == 'Linux':
        chrome_path = '/usr/bin/google-chrome'
    elif platform.system() == 'Darwin':
        chrome_path = '/Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome'

    # Create a temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a command with the required flags
        chrome_cmd = f'{chrome_path} %s --disable-web-security --user-data-dir="{temp_dir}"'

        # Register the new browser type
        webbrowser.register('chrome_with_flags', None,
                            webbrowser.Chrome(chrome_cmd), preferred=True)

        # Open a URL using the new browser type
        webbrowser.get(chrome_cmd).open(url)


HOST = 'localhost'
shutdown_requested = False
last_heartbeat = time.time()
server_running = True

class CustomHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self) -> Any:
        global last_heartbeat
        if self.path == '/heartbeat':
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
            s.bind(('localhost', port))
            return True
        except socket.error:
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

    # Load the GUI JavaScript file.
    scalene_dir = os.path.dirname(__file__)

    file_contents = {
        'scalene_gui_js_text': read_file_content(scalene_dir, "scalene-gui", "scalene-gui.js"),
        'prism_css_text': read_file_content(scalene_dir, "scalene-gui", "prism.css"),
        'prism_js_text': read_file_content(scalene_dir, "scalene-gui", "prism.js"),
        'tablesort_js_text': read_file_content(scalene_dir, "scalene-gui", "tablesort.js"),
        'tablesort_number_js_text': read_file_content(scalene_dir, "scalene-gui", "tablesort.number.js")
    }
    
    # Put the profile and everything else into the template.
    environment = Environment(
        loader=FileSystemLoader(os.path.join(scalene_dir, "scalene-gui"))
    )
    template = environment.get_template("index.html.template")
    try:
        import scalene_config
    except:
        import scalene.scalene_config as scalene_config
    rendered_content = template.render(
        profile=profile,
        gui_js=file_contents['scalene_gui_js_text'],
        prism_css=file_contents['prism_css_text'],
        prism_js=file_contents['prism_js_text'],
        tablesort_js=file_contents['tablesort_js_text'],
        tablesort_number_js=file_contents['tablesort_number_js_text'],
        scalene_version=scalene_config.scalene_version,
        scalene_date=scalene_config.scalene_date,
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
    shutil.copy(filename, os.path.join(tempfile.gettempdir(), 'index.html'))
    os.chdir(tempfile.gettempdir())
    server_thread = threading.Thread(target=run_server, args=[HOST, port])
    server_thread.start()
    threading.Thread(target=monitor_heartbeat).start()

    webbrowser.open_new(f'http://{HOST}:{port}/')
    server_thread.join()

    os.chdir(cwd)
    
    # Optional: a delay to ensure all resources are released
    time.sleep(1)
    os._exit(0)  # Forcefully stops the program

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 2:
        filename = sys.argv[1]
        port = int(sys.argv[2])
        start(filename, port)
    else:
        print("Need to supply filename and port arguments.")

