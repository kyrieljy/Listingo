from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.app.core.storage.base import StorageUnavailableError

class IPBlockMiddleware:
    """Reject requests from process-local blocked IP records before routing."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        application = scope.get("app")
        limiter = getattr(getattr(application, "state", None), "rate_limiter", None)
        try:
            blocked = limiter.is_ip_blocked(client_ip_from_scope(scope)) if limiter is not None else False
        except StorageUnavailableError:
            blocked = False
            response: Any = JSONResponse(
                status_code=503,
                content={"detail": "防护存储暂不可用，请稍后再试"},
            )
            await response(scope, receive, send)
            return

        if blocked:
            response: Any = JSONResponse(
                status_code=403,
                content={"detail": "当前 IP 因异常登录行为已被暂时限制"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def client_ip_from_scope(scope: Scope) -> str:
    """Read the same forwarded-client field used by HTTP request handling."""
    headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
    forwarded = headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()[:80]
    client = scope.get("client")
    return ((client[0] if client else "") or "")[:80]
