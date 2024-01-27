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

def launch_browser_insecure(url):
    if platform.system() == 'Windows':
        chrome_path = 'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe'
    elif platform.system() == 'Linux':
        chrome_path = '/usr/bin/google-chrome'
    elif platform.system() == 'Darwin':
        chrome_path = '/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome'


    # Try to get the path for the Chrome browser
    #chrome_path = webbrowser.get('chrome').name
    #if chrome_path == "":  # Fallback if the path is not found
    # FIXME Mac
    # chrome_path = '/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome'
    # webbrowser.get("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe %s").open("http://google.com")

    # Create a temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a command with the required flags
        chrome_cmd = f'{chrome_path} %s --disable-web-security --user-data-dir="{temp_dir}"'

        print(chrome_cmd)

        # Register the new browser type
        webbrowser.register('chrome_with_flags', None, webbrowser.Chrome(chrome_cmd), preferred=True)

        # Open a URL using the new browser type
        # url = 'https://cnn.com'  # Replace with your desired URL
        webbrowser.get(chrome_cmd).open(url)
        # webbrowser.get('chrome_with_flags').open(url)
        

PORT = 11235 # 8000
HOST = 'localhost'
shutdown_requested = False
last_heartbeat = time.time()
server_running = True

class CustomHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        global last_heartbeat
        if self.path == '/heartbeat':
            last_heartbeat = time.time()
            self.send_response(200)
            self.end_headers()
            return
        else:
            return http.server.SimpleHTTPRequestHandler.do_GET(self)

def monitor_heartbeat():
    global server_running
    while server_running:
        if time.time() - last_heartbeat > 5:  # 5 seconds timeout
            print("No heartbeat received, shutting down server...")
            server_running = False
            os._exit(0)
        time.sleep(1)

def serve_forever(httpd):
    while server_running:
        httpd.handle_request()

def run_server(host, port):
    with socketserver.TCPServer((host, port), CustomHandler) as httpd:
        print(f"Serving at http://{host}:{port}")
        serve_forever(httpd)

def is_port_available(port):
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

def start(filename, port):
    while not is_port_available(port):
        port += 1
        
    cwd = os.getcwd()
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
    print(sys.argv)
    if len(sys.argv) > 2:
        filename = sys.argv[1]
        port = int(sys.argv[2])
        start(filename, port)
    else:
        print("Need to supply filename and port arguments.")

