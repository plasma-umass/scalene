from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

class ScaleneJupyter:

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

            def log_message(self, format, *args):
                """overriding log_message to disable all messages from webserver"""
                pass
            
            def do_GET(self) -> None:
                if self.path == "/":
                    with open(profile_fname) as f:
                      content = f.read()
                    self._send_response(content)
                elif self.path == "/shutdown":
                    self.server.should_shutdown = True
                    self.send_response(204)
                    # self._send_response("Server is shutting down...")
                else:
                    self.send_response(404)

        class MyHTTPServer(HTTPServer):
            """Redefine to check `should_shutdown` flag."""
            def serve_forever(self) -> None:
                self.should_shutdown = False
                while not self.should_shutdown:
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
        display(IFrame(src=f"http://localhost:{port}", width="100%", height="400"))
        Thread(target=lambda: server_thread.join()).start()

        # Wait 5 seconds to ensure that the page is rendered, then kill the cell.
        import time
        time.sleep(2)
        import sys
        sys.exit()

    
