"""Serve only the public privacy notice behind the existing Cloudflare Tunnel."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PUBLIC = Path(__file__).resolve().parent.parent / "frontend" / "public"
ALLOWED = {"/privacidade.html", "/privacy.css", "/castelo-footer-logo.png"}


class PrivacyHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def do_GET(self):
        if self.path.split("?", 1)[0] not in ALLOWED:
            self.send_error(404)
            return
        super().do_GET()

    def do_HEAD(self):
        if self.path.split("?", 1)[0] not in ALLOWED:
            self.send_error(404)
            return
        super().do_HEAD()


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 18080), PrivacyHandler).serve_forever()
