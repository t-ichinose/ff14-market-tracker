import http.server
import socketserver
import os
import sys

PORT = 8000
DIRECTORY = "docs"

class NoCacheHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def end_headers(self):
        # HTML/JS/CSS には no-cache、大容量 data.json.gz には条件付きキャッシュを許可して無駄な全件転送を防止
        if self.path.endswith('.gz') or self.path.endswith('.json'):
            self.send_header("Cache-Control", "public, max-age=300")
        else:
            self.send_header("Cache-Control", "no-cache, must-revalidate")
        super().end_headers()

def run_dev_server():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    port = PORT
    max_attempts = 5

    for attempt in range(max_attempts):
        try:
            ServerClass = getattr(http.server, "ThreadingHTTPServer", socketserver.TCPServer)
            ServerClass.allow_reuse_address = True
            with ServerClass(("127.0.0.1", port), NoCacheHTTPRequestHandler) as httpd:
                print(f"Private Localhost Server running at http://127.0.0.1:{port} (Strictly Isolated to this PC)")
                httpd.serve_forever()
        except OSError as e:
            if "Address already in use" in str(e) or e.errno == 10048:  # 10048 = Windows WSAEADDRINUSE
                port += 1
                print(f"Port {port - 1} is in use, trying port {port}...")
                if attempt == max_attempts - 1:
                    print(f"Error: Could not find an available port after {max_attempts} attempts.")
                    sys.exit(1)
            else:
                raise

if __name__ == "__main__":
    run_dev_server()
