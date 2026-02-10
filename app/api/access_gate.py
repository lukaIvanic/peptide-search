from __future__ import annotations

import base64
import binascii
import secrets
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


def _unauthorized_response() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "error": {
                "code": "unauthorized",
                "message": "Authentication required",
            }
        },
        headers={"WWW-Authenticate": 'Basic realm="Peptide Search", charset="UTF-8"'},
    )


def _parse_basic_auth(header_value: str | None) -> tuple[str, str] | None:
    if not header_value or not header_value.startswith("Basic "):
        return None
    token = header_value[6:].strip()
    if not token:
        return None
    try:
        decoded = base64.b64decode(token).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    if ":" not in decoded:
        return None
    username, password = decoded.split(":", 1)
    return username, password


class AccessGateMiddleware(BaseHTTPMiddleware):
    """App-wide HTTP Basic auth gate for demo deployments."""

    def __init__(self, app, *, username: str, password: str) -> None:
        super().__init__(app)
        self._username = username
        self._password = password

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Response],
    ) -> Response:
        credentials = _parse_basic_auth(request.headers.get("Authorization"))
        if credentials is None:
            return _unauthorized_response()
        username, password = credentials
        if not (
            secrets.compare_digest(username, self._username)
            and secrets.compare_digest(password, self._password)
        ):
            return _unauthorized_response()
        return await call_next(request)
