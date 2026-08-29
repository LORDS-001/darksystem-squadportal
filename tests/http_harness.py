import asyncio
import hmac
import ipaddress
import io
import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlsplit, urlunsplit

import server
from fastapi import Request


_MISSING = object()
_TARGET_QUERY_OPTIONS = {
    "dbname",
    "host",
    "hostaddr",
    "load_balance_hosts",
    "port",
    "service",
    "servicefile",
    "target_session_attrs",
    "user",
    "password",
}
_TARGET_LIBPQ_ENVIRONMENT = {
    "PGDATABASE",
    "PGHOST",
    "PGHOSTADDR",
    "PGLOADBALANCEHOSTS",
    "PGPORT",
    "PGSERVICE",
    "PGSERVICEFILE",
    "PGSYSCONFDIR",
    "PGTARGETSESSIONATTRS",
    "PGUSER",
}
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_NUMERIC_HOST_ALIAS = re.compile(
    r"^(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*$"
)
_SUPABASE_PROJECT_REF = re.compile(r"^[a-z0-9]{20}$")
_SUPABASE_DIRECT_HOST = re.compile(
    r"^db\.([a-z0-9]{20})\.supabase\.co$"
)
_DATABASE_CONFIRMATION = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_DATABASE_MARKER_NAME = "dark-system-owner-release-gate-v1"
_DATABASE_MARKER_QUERY = (
    "SELECT confirmation "
    "FROM public.dark_system_disposable_test_marker "
    "WHERE marker_name=%s"
)
_ENABLE_DATABASE_WRITES_QUERY = "SET default_transaction_read_only=off"


@dataclass(frozen=True)
class _PostgresTarget:
    host: str
    port: int
    database: str
    username: str
    supabase_project: str


@dataclass(frozen=True)
class PostgreSQLTestGate:
    database_url: str = field(repr=False)
    confirmation: str = field(repr=False)


def _psycopg_conninfo(database_url):
    try:
        from psycopg.conninfo import conninfo_to_dict
    except ImportError:
        return {}
    try:
        return conninfo_to_dict(database_url)
    except Exception:
        return None


def _canonical_postgres_host(host):
    decoded = unquote(str(host)).lower()
    if decoded.endswith("."):
        decoded = decoded[:-1]
    if not decoded or decoded.endswith("."):
        return None
    try:
        address = ipaddress.ip_address(decoded)
    except ValueError:
        if _NUMERIC_HOST_ALIAS.fullmatch(decoded):
            return None
        labels = decoded.split(".")
        if len(decoded) > 253 or any(
            not label or not _DNS_LABEL.fullmatch(label) for label in labels
        ):
            return None
        return decoded
    if getattr(address, "scope_id", None):
        return None
    if address.version == 6 and address.ipv4_mapped is not None:
        return None
    return address.compressed


def _supabase_project_for_target(host, username):
    direct_match = _SUPABASE_DIRECT_HOST.fullmatch(host)
    if direct_match:
        return direct_match.group(1)
    if host == "supabase.co" or host.endswith(".supabase.co"):
        return None
    if host == "pooler.supabase.com" or host.endswith(".pooler.supabase.com"):
        role, separator, project_ref = username.rpartition(".")
        if (
            not separator
            or not role
            or not _SUPABASE_PROJECT_REF.fullmatch(project_ref)
        ):
            return None
        return project_ref
    if host == "supabase.com" or host.endswith(".supabase.com"):
        return None
    return ""


def _postgres_database_target(database_url, require_user=False):
    try:
        parsed = urlsplit(database_url)
        query_options = {
            str(key).lower()
            for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
        }
        host = _canonical_postgres_host(parsed.hostname or "")
        parsed_port = parsed.port
        port = 5432 if parsed_port is None else parsed_port
        username = unquote(parsed.username or "")
    except (TypeError, ValueError):
        return None
    if (
        parsed.scheme.lower() not in ("postgres", "postgresql")
        or not host
        or not (1 <= port <= 65535)
        or parsed.fragment
        or parsed.netloc.count("@") > 1
        or "," in host
        or query_options.intersection(_TARGET_QUERY_OPTIONS)
        or (require_user and not username)
    ):
        return None
    if not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return None
    database_name = unquote(parsed.path[1:]).strip()
    if not database_name or "/" in database_name:
        return None
    normalized = _psycopg_conninfo(database_url)
    if normalized is None:
        return None
    if normalized:
        if normalized.get("service") or normalized.get("servicefile"):
            return None
        normalized_host = _canonical_postgres_host(normalized.get("host", host))
        normalized_port = str(normalized.get("port", port))
        normalized_database = str(normalized.get("dbname", database_name))
        normalized_username = str(normalized.get("user", username))
        if (
            not normalized_host
            or "," in normalized_host
            or "," in normalized_port
        ):
            return None
        try:
            port = int(normalized_port)
        except ValueError:
            return None
        if not (1 <= port <= 65535):
            return None
        host = normalized_host
        database_name = normalized_database
        username = normalized_username
    if require_user and not username:
        return None
    supabase_project = _supabase_project_for_target(host, username)
    if supabase_project is None:
        return None
    return _PostgresTarget(
        host=host,
        port=port,
        database=database_name,
        username=username,
        supabase_project=supabase_project,
    )


def _postgres_target_identity(target):
    if target.supabase_project:
        return ("supabase", target.supabase_project, target.database)
    return ("postgresql", target.host, target.port, target.database)


def _explicit_postgres_url(database_url, target):
    parsed = urlsplit(database_url)
    encoded_user = quote(target.username, safe="")
    encoded_password = ""
    if parsed.password is not None:
        encoded_password = f":{quote(unquote(parsed.password), safe='')}"
    userinfo = f"{encoded_user}{encoded_password}@"
    try:
        host_literal = ipaddress.ip_address(target.host)
    except ValueError:
        uri_host = quote(target.host, safe=".-")
    else:
        uri_host = (
            f"[{host_literal.compressed}]"
            if host_literal.version == 6
            else str(host_literal)
        )
    return urlunsplit(
        (
            "postgresql",
            f"{userinfo}{uri_host}:{target.port}",
            f"/{quote(target.database, safe='')}",
            parsed.query,
            "",
        )
    )


def _valid_database_confirmation(confirmation):
    return bool(
        isinstance(confirmation, str)
        and _DATABASE_CONFIRMATION.fullmatch(confirmation)
    )


def connect_validated_test_database(
    psycopg_module,
    database_url,
    confirmation,
    *,
    autocommit=False,
    **connect_options,
):
    """Open one target connection only after its read-only marker matches."""
    if not _valid_database_confirmation(confirmation):
        raise RuntimeError("Disposable PostgreSQL marker validation failed.")
    connection = None
    try:
        connection = psycopg_module.connect(
            database_url,
            autocommit=False,
            options="-c default_transaction_read_only=on",
            **connect_options,
        )
        row = connection.execute(
            _DATABASE_MARKER_QUERY,
            (_DATABASE_MARKER_NAME,),
        ).fetchone()
        if isinstance(row, dict):
            stored_confirmation = row.get("confirmation")
        elif row:
            stored_confirmation = row[0]
        else:
            stored_confirmation = None
        if not (
            isinstance(stored_confirmation, str)
            and hmac.compare_digest(stored_confirmation, confirmation)
        ):
            raise RuntimeError("Disposable PostgreSQL marker validation failed.")
        connection.rollback()
        connection.read_only = False
        connection.autocommit = True
        connection.execute(_ENABLE_DATABASE_WRITES_QUERY)
        connection.autocommit = autocommit
        return connection
    except Exception:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        raise RuntimeError("Disposable PostgreSQL marker validation failed.") from None


def resolve_test_database_gate(environment=None):
    """Return the explicit disposable PostgreSQL gate without falling back."""
    source = os.environ if environment is None else environment
    test_database_url = str(source.get("TEST_DATABASE_URL", "")).strip()
    if not test_database_url:
        return None
    if any(variable in source for variable in _TARGET_LIBPQ_ENVIRONMENT):
        raise RuntimeError(
            "Target-affecting libpq environment variables must be unset for the PostgreSQL test gate."
        )
    confirmation = source.get("TEST_DATABASE_CONFIRMATION", "")
    if not _valid_database_confirmation(confirmation):
        raise RuntimeError(
            "TEST_DATABASE_CONFIRMATION is required for the disposable PostgreSQL test gate."
        )
    test_target = _postgres_database_target(test_database_url, require_user=True)
    if test_target is None:
        raise RuntimeError(
            "TEST_DATABASE_URL must be a single explicit PostgreSQL URI whose target can be safely verified."
        )
    production_database_url = str(source.get("DATABASE_URL", "")).strip()
    production_target = _postgres_database_target(production_database_url)
    if production_database_url and production_target is None:
        raise RuntimeError(
            "DATABASE_URL cannot be safely compared with TEST_DATABASE_URL."
        )
    if production_database_url and (
        test_database_url == production_database_url
        or (
            production_target is not None
            and _postgres_target_identity(test_target)
            == _postgres_target_identity(production_target)
        )
    ):
        raise RuntimeError(
            "The disposable PostgreSQL test database must differ from DATABASE_URL."
        )
    explicit_test_database_url = _explicit_postgres_url(
        test_database_url,
        test_target,
    )
    if explicit_test_database_url is None:
        raise RuntimeError(
            "TEST_DATABASE_URL cannot be converted to an explicit safe PostgreSQL target."
        )
    return PostgreSQLTestGate(
        database_url=explicit_test_database_url,
        confirmation=confirmation,
    )


def resolve_test_database_url(environment=None):
    """Return the explicit disposable PostgreSQL URL without falling back."""
    gate = resolve_test_database_gate(environment)
    return None if gate is None else gate.database_url


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
