"""Serve the public privacy notice and the extension's narrow API surface."""

from contextlib import closing
from http.client import HTTPConnection
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
from urllib.parse import urlsplit


PUBLIC = Path(__file__).resolve().parent.parent / "frontend" / "public"
ALLOWED = {"/privacidade.html", "/privacy.css", "/castelo-footer-logo.png"}
API_ROUTES = {
    ("GET", "/healthz"),
    ("POST", "/api/auth/extension/login"),
    ("POST", "/api/auth/extension/renew"),
    ("POST", "/api/auth/extension/logout"),
    ("GET", "/api/auth/extension/me"),
    ("POST", "/api/capture/v1/machines"),
    ("POST", "/api/capture/v1/interactions"),
    ("POST", "/api/capture/v1/artifact-metadata"),
    ("POST", "/api/capture/v1/stream-captures"),
}
MACHINE_ROUTE = re.compile(r"^/api/capture/v1/machines/[0-9a-f-]{36}(?:/assignment-request)?$")
RESPONSE_ROUTE = re.compile(r"^/api/capture/v1/interactions/[0-9a-f-]{36}/response$")
FORWARD_HEADERS = {"authorization", "content-type", "origin", "x-machine-id", "x-machine-timestamp",
                   "x-machine-nonce", "x-machine-signature", "access-control-request-method",
                   "access-control-request-headers"}


def api_allowed(method: str, path: str) -> bool:
    if method == "OPTIONS":
        return api_allowed("GET", path) or api_allowed("POST", path)
    return ((method, path) in API_ROUTES or
            (method == "GET" and bool(MACHINE_ROUTE.fullmatch(path)) and not path.endswith("/assignment-request")) or
            (method == "POST" and bool(MACHINE_ROUTE.fullmatch(path)) and path.endswith("/assignment-request")) or
            (method == "POST" and bool(RESPONSE_ROUTE.fullmatch(path))))


class PrivacyHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def do_GET(self):
        path = urlsplit(self.path).path
        if api_allowed("GET", path):
            self.proxy_api()
            return
        if path not in ALLOWED:
            self.send_error(404)
            return
        super().do_GET()

    def do_POST(self):
        if not api_allowed("POST", urlsplit(self.path).path):
            self.send_error(404)
            return
        self.proxy_api()

    def do_OPTIONS(self):
        if not api_allowed("OPTIONS", urlsplit(self.path).path):
            self.send_error(404)
            return
        self.proxy_api()

    def proxy_api(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400)
            return
        if length < 0 or length > 1_000_000 or self.headers.get("Transfer-Encoding"):
            self.send_error(413)
            return
        headers = {key: value for key, value in self.headers.items() if key.lower() in FORWARD_HEADERS}
        headers["Host"] = "app.castelotecnologia.com.br"
        try:
            with closing(HTTPConnection("127.0.0.1", 18081, timeout=15)) as connection:
                connection.request(self.command, urlsplit(self.path).path, body=self.rfile.read(length), headers=headers)
                upstream = connection.getresponse()
                body = upstream.read(1_000_001)
                if len(body) > 1_000_000:
                    self.send_error(502)
                    return
                self.send_response(upstream.status)
                for key, value in upstream.getheaders():
                    if key.lower() in {"content-type", "cache-control", "access-control-allow-origin",
                                       "access-control-allow-methods", "access-control-allow-headers", "vary"}:
                        self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        except OSError:
            self.send_error(502, "Extension API unavailable")

    def do_HEAD(self):
        if urlsplit(self.path).path not in ALLOWED:
            self.send_error(404)
            return
        super().do_HEAD()


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 18080), PrivacyHandler).serve_forever()
