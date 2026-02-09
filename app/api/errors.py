from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def _default_code(status_code: int) -> str:
    mapping = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        429: "rate_limited",
        500: "internal_error",
    }
    return mapping.get(status_code, f"http_{status_code}")


def _build_error_payload(status_code: int, detail: Any) -> dict[str, Any]:
    if isinstance(detail, dict) and "error" in detail and isinstance(detail["error"], dict):
        return detail

    if isinstance(detail, dict):
        code = str(detail.get("code") or _default_code(status_code))
        message = str(detail.get("message") or detail.get("detail") or "Request failed")
        extra = detail.get("details")
    else:
        code = _default_code(status_code)
        message = str(detail) if detail else "Request failed"
        extra = None

    payload: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
        }
    }
    if extra is not None:
        payload["error"]["details"] = extra
    return payload


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
        payload = _build_error_payload(exc.status_code, exc.detail)
        return JSONResponse(status_code=exc.status_code, content=payload)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        payload = {
            "error": {
                "code": "validation_error",
                "message": "Request validation failed",
                "details": exc.errors(),
            }
        }
        return JSONResponse(status_code=422, content=payload)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
        payload = {
            "error": {
                "code": "internal_error",
                "message": str(exc) or "Internal server error",
            }
        }
        return JSONResponse(status_code=500, content=payload)
