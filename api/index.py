"""Vercel adapter for the existing Dark System HTTP backend.

The application logic remains in server.py. This adapter translates a Vercel
request into the existing handler contract so the established UI/API behavior
is preserved while running as a Vercel Python function.
"""
import io
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from fastapi import FastAPI, Request
from fastapi.responses import Response

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server  # noqa: E402

app = FastAPI(title="Dark System Backend", docs_url=None, redoc_url=None)
database_ready = False

def ensure_database() -> None:
    """Initialize persistence once per warm Vercel function instance."""
    global database_ready
    if database_ready:
        return
    server.init_db()
    database_ready = True


class CaptureHandler(server.Handler):
    """A lightweight Handler instance backed by an in-memory request/response."""
    pass

def invoke_existing_backend(request: Request, body: bytes) -> Response:
    h = CaptureHandler.__new__(CaptureHandler)
    h.path = request.url.path
    if request.url.query:
        h.path += "?" + request.url.query
    h.headers = {k: v for k, v in request.headers.items()}
    h.headers["Host"] = request.headers.get("host", "")
    h.headers["Content-Length"] = str(len(body))
    h.rfile = io.BytesIO(body)
    h.wfile = io.BytesIO()
    h.server = SimpleNamespace(server_address=(request.url.hostname or "vercel", 443 if request.url.scheme == "https" else 80))
    client_host = request.client.host if request.client else "0.0.0.0"
    client_port = request.client.port if request.client else 0
    h.client_address = (client_host, client_port)
    h.request_version = "HTTP/1.1"
    h.command = request.method
    h._status = 200
    h._headers = []

    def send_response(status, message=None):
        h._status = int(status)
    def send_header(key, value):
        h._headers.append((key, str(value)))
    def end_headers():
        return None
    def log_message(fmt, *args):
        return None

    h.send_response = send_response
    h.send_header = send_header
    h.end_headers = end_headers
    h.log_message = log_message

    h.route(request.method)
    payload = h.wfile.getvalue()
    # Avoid duplicate headers that can be emitted by legacy paths.
    headers = {}
    for key, value in h._headers:
        if key.lower() == "content-length":
            headers[key] = value
        elif key not in headers:
            headers[key] = value
        else:
            headers[key] = headers[key] + ", " + value
    media_type = None
    for key, value in headers.items():
        if key.lower() == "content-type":
            media_type = value
            break
    return Response(content=payload, status_code=h._status, headers=headers, media_type=media_type)

@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"])
async def catch_all(request: Request, full_path: str):
    body = await request.body()
    path = request.url.path
    try:
        # Health and static files do not depend on the database. Keeping them
        # available makes configuration failures diagnosable instead of
        # crashing the complete serverless function during startup.
        if path.startswith("/api/") and path != "/api/health":
            if server.SESSION_SECRET == "change-this-in-production":
                return Response(
                    content=b'{"error":"Server configuration is incomplete."}',
                    status_code=503,
                    media_type="application/json",
                )
            ensure_database()
        return invoke_existing_backend(request, body)
    except Exception:
        logging.exception("Dark System request failed: %s %s", request.method, path)
        return Response(
            content=b'{"error":"The backend database is temporarily unavailable."}',
            status_code=503,
            media_type="application/json",
        )
