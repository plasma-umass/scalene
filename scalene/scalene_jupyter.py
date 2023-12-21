import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from typing import Any, Optional


class ScaleneJupyter:
    @staticmethod
    def find_available_port(start_port: int, end_port: int) -> Optional[int]:
        """
        Finds an available port within a given range.

        Parameters:
        - start_port (int): the starting port number to search from
        - end_port (int): the ending port number to search up to (inclusive)

        Returns:
        - int: the first available port number found in the given range, or None if no ports are available
        """

        for port in range(start_port, end_port + 1):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(("", port))
                    return port
            except OSError:
                continue
        return None

    @staticmethod
    def display_profile(port: int, profile_fname: str) -> None:
        # Display the profile in a cell. Starts a webserver to host the iframe holding the profile.html file,
        # which lets JavaScript run (can't do this with `display`, which strips out JavaScript), and then
        # tears down the server.
        from IPython.core.display import display
        from IPython.display import IFrame

        class RequestHandler(BaseHTTPRequestHandler):
            def _send_response(self, content: str) -> None:
                self.send_response(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write(bytes(content, "utf8"))

            def log_message(self, format: str, *args: Any) -> None:
                """overriding log_message to disable all messages from webserver"""
                pass

            def do_GET(self) -> None:
                if self.path == "/":
                    try:
                        with open(profile_fname) as f:
                            content = f.read()
                        self._send_response(content)
                    except FileNotFoundError:
                        print("Scalene error: profile file not found.")
                elif self.path == "/shutdown":
                    self.server.should_shutdown = True # type: ignore
                    self.send_response(204)
                    # self._send_response("Server is shutting down...")
                else:
                    self.send_response(404)

        class MyHTTPServer(HTTPServer):
            """Redefine to check `should_shutdown` flag."""

            def serve_forever(self, poll_interval: float = 0.5) -> None:
                self.should_shutdown = False
                while not self.should_shutdown:
                    # Poll interval currently disabled below to avoid
                    # interfering with existing functionality.
                    # time.sleep(poll_interval)
                    self.handle_request()

        class local_server:
            def run_server(self) -> None:
                try:
                    server_address = ("", port)
                    self.httpd = MyHTTPServer(server_address, RequestHandler)
                    self.httpd.serve_forever()
                except BaseException as be:
                    print("server failure", be)
                    pass

        the_server = local_server()
        server_thread = Thread(target=the_server.run_server)
        server_thread.start()

        # Display the profile and then shutdown the server.
        display(
            IFrame(src=f"http://localhost:{port}", width="100%", height="400")
        )
        Thread(target=lambda: server_thread.join()).start()

        # Wait 2 seconds to ensure that the page is rendered, then kill the cell.
        import time

        time.sleep(2)
        import sys

        sys.exit()
