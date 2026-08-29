import asyncio
import io
import json
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

import server
from fastapi import Request


_MISSING = object()


def _postgres_database_identity(database_url):
    try:
        parsed = urlsplit(database_url)
        port = parsed.port or 5432
    except (TypeError, ValueError):
        return None
    if parsed.scheme not in ("postgres", "postgresql") or not parsed.hostname:
        return None
    database_name = unquote(parsed.path.lstrip("/")).strip()
    if not database_name:
        return None
    return (
        parsed.hostname.lower(),
        port,
        database_name,
    )


def resolve_test_database_url(environment=None):
    """Return the explicit disposable PostgreSQL URL without falling back."""
    source = os.environ if environment is None else environment
    test_database_url = str(source.get("TEST_DATABASE_URL", "")).strip()
    if not test_database_url:
        return None
    if str(source.get("TEST_DATABASE_DISPOSABLE", "")).strip() != "1":
        raise RuntimeError(
            "PostgreSQL integration requires explicit disposable test database confirmation."
        )
    test_identity = _postgres_database_identity(test_database_url)
    if test_identity is None:
        raise RuntimeError("TEST_DATABASE_URL must identify a PostgreSQL database.")
    production_database_url = str(source.get("DATABASE_URL", "")).strip()
    production_identity = _postgres_database_identity(production_database_url)
    if production_database_url and (
        test_database_url == production_database_url
        or (production_identity is not None and test_identity == production_identity)
    ):
        raise RuntimeError(
            "The disposable PostgreSQL test database must differ from DATABASE_URL."
        )
    return test_database_url


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
    OWNER_SETUP_SECRET = "test-owner-setup-secret"

    def __init__(self):
        self._original_db_path = server.DB_PATH
        self._original_database_url = server.DATABASE_URL
        self._original_session_secret = server.SESSION_SECRET
        self._original_owner_setup_secret = getattr(server, "OWNER_SETUP_SECRET", _MISSING)
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
            server.OWNER_SETUP_SECRET = self.OWNER_SETUP_SECRET
            server.init_db()
        except Exception:
            try:
                server.DB_PATH = self._original_db_path
                server.DATABASE_URL = self._original_database_url
                server.SESSION_SECRET = self._original_session_secret
                self._restore_owner_setup_secret()
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

    def adapter_request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        cookie: str = "",
        forwarded_proto: str = "https",
    ):
        from api import index as adapter

        body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        headers = [(b"host", b"test.local")]
        if forwarded_proto:
            headers.append((b"x-forwarded-proto", forwarded_proto.encode("ascii")))
        if cookie:
            headers.append((b"cookie", cookie.encode("ascii")))
        if payload is not None:
            headers.extend(
                (
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                )
            )
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "https" if forwarded_proto == "https" else "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 50000),
            "server": ("test.local", 443 if forwarded_proto == "https" else 80),
        }

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        request = Request(scope, receive)
        return asyncio.run(adapter.catch_all(request, path.lstrip("/")))

    def close(self):
        if self._closed:
            return
        try:
            server.DB_PATH = self._original_db_path
            server.DATABASE_URL = self._original_database_url
            server.SESSION_SECRET = self._original_session_secret
            self._restore_owner_setup_secret()
            self._temporary_directory.cleanup()
        finally:
            self._closed = True
            with BackendHarness._active_lock:
                BackendHarness._active = False

    def _restore_owner_setup_secret(self):
        if self._original_owner_setup_secret is _MISSING:
            if hasattr(server, "OWNER_SETUP_SECRET"):
                delattr(server, "OWNER_SETUP_SECRET")
        else:
            server.OWNER_SETUP_SECRET = self._original_owner_setup_secret

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
