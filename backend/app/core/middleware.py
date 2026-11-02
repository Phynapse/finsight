"""Cross-cutting HTTP middleware: correlation IDs, access logs, body limits."""

from __future__ import annotations

import re

import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import PayloadTooLargeError
from app.core.logging import get_logger, new_request_id, reset_request_id, set_request_id

logger = get_logger(__name__)


_REQUEST_ID_RE = re.compile(r"^[a-zA-Z0-9\-_]{1,64}$")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request ID, expose it on the response, and log the outcome."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-request-id", "")
        if incoming and _REQUEST_ID_RE.match(incoming):
            request_id = incoming
        else:
            request_id = new_request_id()
        token = set_request_id(request_id)
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            reset_request_id(token)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        logger.info(
            "request %s %s -> %s in %sms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            extra={
                "http_method": request.method,
                "http_path": request.url.path,
                "http_status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response


class BodySizeLimitMiddleware:
    """Reject oversized request bodies before they are fully buffered.

    ``Content-Length`` is checked first, which rejects the common case before a
    single body byte is read. When a client streams a body without declaring a
    length, the ASGI ``receive`` callable counts bytes as they arrive and aborts
    with :class:`PayloadTooLargeError` as soon as the cap is passed, so the
    process never holds an unbounded request in memory.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = self._declared_length(scope)
        if declared is not None and declared > self.max_bytes:
            await self._reject(send, declared)
            return
        if declared is None and self._is_streamed_body(scope):
            received = 0

            async def counting_receive() -> Message:
                nonlocal received
                message = await receive()
                if message["type"] == "http.request":
                    received += len(message.get("body", b""))
                    if received > self.max_bytes:
                        raise PayloadTooLargeError(
                            details={"max_bytes": self.max_bytes, "received_bytes": received}
                        )
                return message

            try:
                await self.app(scope, counting_receive, send)
            except PayloadTooLargeError as error:
                await self._reject(send, int(error.details.get("received_bytes", 0)))
            return

        await self.app(scope, receive, send)

    @staticmethod
    def _declared_length(scope: Scope) -> int | None:
        for key, value in scope.get("headers", []):
            if key.decode("latin-1").lower() != "content-length":
                continue
            try:
                return int(value)
            except ValueError:
                return -1
        return None

    @staticmethod
    def _is_streamed_body(scope: Scope) -> bool:
        transfer_encoding = ""
        for key, value in scope.get("headers", []):
            if key.decode("latin-1").lower() == "transfer-encoding":
                transfer_encoding = value.decode("latin-1").lower()
        return "chunked" in transfer_encoding

    async def _reject(self, send: Send, received: int) -> None:
        error = PayloadTooLargeError(
            details={"max_bytes": self.max_bytes, "received_bytes": received}
        )
        response = JSONResponse(status_code=error.status_code, content={"error": error.to_payload()})
        await response(self._dummy_scope, _never_receive, send)

    _dummy_scope: Scope = {"type": "http", "method": "POST", "path": "/", "headers": []}


async def _never_receive() -> Message:
    return {"type": "http.disconnect"}