from collections import deque
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from threading import Thread
from typing import Deque
from typing import Generator
from typing import List
from typing import NamedTuple

import pytest


pytest_plugins = ["pytester"]


class QueuedResponse(NamedTuple):
    status: int
    body: bytes


class QueuedHTTPServer:
    def __init__(self) -> None:
        self.responses: Deque[QueuedResponse] = deque()
        self.requests: List[str] = []
        response_server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                response_server.requests.append(self.path)
                response = response_server.responses.popleft()
                self.send_response(response.status)
                self.send_header("Content-Length", str(len(response.body)))
                self.end_headers()
                self.wfile.write(response.body)

            def log_message(self, format: str, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever)

    @property
    def url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def push(self, status: int, body: bytes = b"") -> None:
        self.responses.append(QueuedResponse(status, body))

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


@pytest.fixture
def http_server() -> Generator[QueuedHTTPServer, None, None]:
    server = QueuedHTTPServer()
    server.start()
    try:
        yield server
    finally:
        server.stop()
