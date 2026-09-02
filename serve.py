"""Serve the dashboard locally and open it in the browser.

Browsers refuse to fetch tenders.json from a file:// page, so the dashboard
needs to be served over HTTP. This does that, and nothing else.

    python serve.py            # http://127.0.0.1:8777/dashboard.html
    python serve.py 9000       # custom port
"""
import http.server
import os
import socketserver
import sys
import threading
import webbrowser

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8777


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *a):        # keep the console quiet
        pass


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.exists("tenders.json"):
        print("tenders.json not found -- run  python scraper.py  first.\n")

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
        url = f"http://127.0.0.1:{PORT}/dashboard.html"
        print(f"Dashboard: {url}\nPress Ctrl+C to stop.")
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
