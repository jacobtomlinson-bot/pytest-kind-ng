from collections import deque
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Deque
from typing import Generator
from typing import List
from typing import NamedTuple
from typing import Optional

import pytest


pytest_plugins = ["pytester"]


@pytest.fixture
def empty_tool_cache(monkeypatch, tmp_path) -> Path:
    monkeypatch.setenv("PYTEST_KIND_CACHE_DIR", str(tmp_path))
    return tmp_path


class QueuedResponse(NamedTuple):
    status: int
    body: bytes
    content_length: Optional[int]


class QueuedHTTPServer:
    def __init__(self) -> None:
        self.responses: Deque[QueuedResponse] = deque()
        self.requests: List[str] = []
        response_server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                response_server.requests.append(self.path)
                if not response_server.responses:
                    self.send_error(500, "No response queued")
                    return

                response = response_server.responses.popleft()
                content_length = response.content_length
                if content_length is None:
                    content_length = len(response.body)
                self.send_response(response.status)
                self.send_header("Content-Length", str(content_length))
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

    def push(
        self,
        status: int,
        body: bytes = b"",
        content_length: Optional[int] = None,
    ) -> None:
        self.responses.append(QueuedResponse(status, body, content_length))

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


@pytest.fixture
def retry_delays(monkeypatch) -> List[int]:
    delays: List[int] = []
    monkeypatch.setattr("pytest_kind.cluster.time.sleep", delays.append)
    return delays
