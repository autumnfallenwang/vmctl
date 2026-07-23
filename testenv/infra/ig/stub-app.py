#!/usr/bin/env python3
"""Trivial upstream that PingGateway reverse-proxies to. Serves a small JSON body
on any path, on :8081. Holds no state and does no auth — it exists only so IG has
something real to proxy, which produces genuine IG access logs."""

import json
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer

HOST = socket.gethostname()


class Handler(BaseHTTPRequestHandler):
    def _respond(self) -> None:
        body = json.dumps(
            {"app": "stub", "host": HOST, "path": self.path, "method": self.command}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._respond()

    def do_POST(self) -> None:
        self._respond()

    def log_message(self, fmt, *args) -> None:  # noqa: ARG002 - silence default stderr logging
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8081), Handler).serve_forever()
