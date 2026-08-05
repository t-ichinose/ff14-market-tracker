import http.server
import socketserver
import os

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
    with socketserver.TCPServer(("", PORT), NoCacheHTTPRequestHandler) as httpd:
        print(f"Zero-Cache Dev Server running at http://localhost:{PORT}")
        httpd.serve_forever()

if __name__ == "__main__":
    run_dev_server()
