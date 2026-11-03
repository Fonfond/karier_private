"""HTTP-middleware: request_id, контекст аудита, запись журнала."""

from __future__ import annotations

import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.errors import ApiError, problem_response
from app.core.rate_limit import client_ip
from app.db.session import SessionLocal
from app.services import audit

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

# Пути, для которых не нужен «технический» след, если нет доменного события
SKIP_AUDIT_PATHS = {"/health/live", "/health/ready", "/openapi.json", "/docs", "/redoc"}


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id

        audit.reset_context(
            ip=client_ip(request),
            user_agent=request.headers.get("user-agent"),
            request_id=request_id,
            method=request.method,
            path=str(request.url.path),
        )

        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{(time.perf_counter() - started) * 1000:.0f}ms"

        if request.method in MUTATING and request.url.path not in SKIP_AUDIT_PATHS:
            ctx = audit.get_context()
            if not ctx.entries:
                audit.add(
                    f"http.{request.method.lower()}",
                    entity="http",
                    entity_id=str(request.url.path),
                    result="ok" if response.status_code < 400 else "error",
                    detail=f"HTTP {response.status_code}",
                )

        # журнал пишется отдельной сессией: он должен сохраниться даже при
        # откате бизнес-транзакции
        db = SessionLocal()
        try:
            audit.flush(db)
        except Exception:  # noqa: BLE001 — журнал не должен ломать ответ
            db.rollback()
        finally:
            db.close()

        return response


async def api_error_middleware(request: Request, call_next):  # pragma: no cover
    try:
        return await call_next(request)
    except ApiError as exc:
        return problem_response(
            request, status=exc.status, code=exc.code, detail=exc.detail, fields=exc.fields
        )
