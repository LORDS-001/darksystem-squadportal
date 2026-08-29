import io
import json
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

import server


@dataclass
class BackendResponse:
    status: int
    headers: dict[str, str]
    json: dict | None
    body: bytes


class _PersistentBytesIO(io.BytesIO):
    def close(self):
        pass


class _HandlerSocket:
    def __init__(self, request: bytes):
        self.rfile = _PersistentBytesIO(request)
        self.wfile = _PersistentBytesIO()

    def makefile(self, mode, *args, **kwargs):
        return self.rfile if "r" in mode else self.wfile

    def sendall(self, data):
        self.wfile.write(data)


class _HandlerServer:
    server_address = ("test.local", 443)


class BackendHarness:
    _active_lock = threading.Lock()
    _active = False

    def __init__(self):
        self._original_db_path = server.DB_PATH
        self._original_database_url = server.DATABASE_URL
        self._original_session_secret = server.SESSION_SECRET
        self._temporary_directory = None
        self._closed = True
        with BackendHarness._active_lock:
            if BackendHarness._active:
                raise RuntimeError("Only one BackendHarness can be active at a time.")
            BackendHarness._active = True
        try:
            self._temporary_directory = tempfile.TemporaryDirectory()
            server.DB_PATH = Path(self._temporary_directory.name) / "dark-system.sqlite3"
            server.DATABASE_URL = ""
            server.SESSION_SECRET = "test-owner-session-secret"
            server.init_db()
        except Exception:
            try:
                server.DB_PATH = self._original_db_path
                server.DATABASE_URL = self._original_database_url
                server.SESSION_SECRET = self._original_session_secret
                if self._temporary_directory:
                    self._temporary_directory.cleanup()
            finally:
                with BackendHarness._active_lock:
                    BackendHarness._active = False
            raise
        self._closed = False

    def request(self, method: str, path: str, payload: dict | None = None, cookie: str = "") -> BackendResponse:
        body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        headers = [
            f"{method} {path} HTTP/1.1",
            "Host: test.local",
            "Origin: https://test.local",
            "X-Forwarded-Proto: https",
            "Connection: close",
        ]
        if cookie:
            headers.append(f"Cookie: {cookie}")
        if payload is not None:
            headers.extend(("Content-Type: application/json", f"Content-Length: {len(body)}"))
        raw_request = ("\r\n".join(headers) + "\r\n\r\n").encode("ascii") + body
        connection = _HandlerSocket(raw_request)
        server.Handler(connection, ("127.0.0.1", 50000), _HandlerServer())
        return self._parse_response(connection.wfile.getvalue())

    def close(self):
        if self._closed:
            return
        try:
            server.DB_PATH = self._original_db_path
            server.DATABASE_URL = self._original_database_url
            server.SESSION_SECRET = self._original_session_secret
            self._temporary_directory.cleanup()
        finally:
            self._closed = True
            with BackendHarness._active_lock:
                BackendHarness._active = False

    @staticmethod
    def _parse_response(raw_response: bytes) -> BackendResponse:
        raw_headers, body = raw_response.split(b"\r\n\r\n", 1)
        lines = raw_headers.decode("iso-8859-1").split("\r\n")
        status = int(lines[0].split(" ", 2)[1])
        headers = {}
        for line in lines[1:]:
            name, value = line.split(":", 1)
            headers[name] = value.strip()
        response_json = None
        if headers.get("Content-Type", "").lower().startswith("application/json"):
            response_json = json.loads(body.decode("utf-8"))
        return BackendResponse(status=status, headers=headers, json=response_json, body=body)
