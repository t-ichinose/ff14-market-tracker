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
        # ブラウザおよびサーバーのキャッシュを完全に禁止する無効化ヘッダー
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

def run_dev_server():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    port = PORT
    max_attempts = 5

    for attempt in range(max_attempts):
        try:
            socketserver.TCPServer.allow_reuse_address = True
            with socketserver.TCPServer(("127.0.0.1", port), NoCacheHTTPRequestHandler) as httpd:
                print(f"Zero-Cache Dev Server running at http://127.0.0.1:{port} (Localhost Only)")
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
