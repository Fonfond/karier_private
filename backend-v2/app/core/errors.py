"""Ошибки API в формате RFC 7807 (application/problem+json)."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """Доменная ошибка с машиночитаемым кодом."""

    def __init__(
        self,
        status: int,
        code: str,
        detail: str,
        *,
        fields: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.fields = fields or {}
        self.headers = headers or {}


def problem_response(
    request: Request,
    *,
    status: int,
    code: str,
    detail: str,
    fields: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"https://karier.local/errors/{code}",
        "title": detail,
        "status": status,
        "code": code,
        "detail": detail,
        "instance": request.url.path,
        "request_id": getattr(request.state, "request_id", None),
    }
    if fields:
        body["fields"] = fields
    return JSONResponse(
        status_code=status,
        content=body,
        media_type="application/problem+json",
        headers={**(headers or {}), "X-Request-ID": getattr(request.state, "request_id", "")},
    )


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return problem_response(
        request,
        status=exc.status,
        code=exc.code,
        detail=exc.detail,
        fields=exc.fields or None,
        headers=exc.headers,
    )


# Часто используемые ошибки
def unauthorized(detail: str = "Требуется вход") -> ApiError:
    return ApiError(401, "auth.unauthorized", detail)


def forbidden(detail: str = "Недостаточно прав") -> ApiError:
    return ApiError(403, "perm.denied", detail)


def not_found(detail: str = "Не найдено") -> ApiError:
    return ApiError(404, "resource.not_found", detail)


def conflict(detail: str, code: str = "resource.conflict") -> ApiError:
    return ApiError(409, code, detail)
