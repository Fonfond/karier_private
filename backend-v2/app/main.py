"""Karier GIS API — Спринт 1: доступ, роли, аудит."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.middleware import AuditMiddleware
from app.api.routers import (
    audit,
    auth,
    defects,
    documents,
    employees,
    gis,
    health,
    inspections,
    me,
    media,
)
from app.core.config import settings
from app.core.errors import ApiError, api_error_handler, problem_response

logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("karier.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Karier API запущен: env=%s", settings.ENV)
    yield
    logger.info("Karier API остановлен")


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    description=(
        "Спринт 1: закрытая регистрация по табельному номеру, пароль (Argon2id), "
        "2FA (TOTP), роли и журнал аудита."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Response-Time"],
)
app.add_middleware(AuditMiddleware)

app.add_exception_handler(ApiError, api_error_handler)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    fields = {}
    for error in exc.errors():
        loc = ".".join(str(part) for part in error.get("loc", []) if part != "body")
        fields[loc or "body"] = error.get("msg", "Некорректное значение")
    first = next(iter(fields.values()), "Проверьте введённые данные")
    return problem_response(
        request,
        status=422,
        code="validation.failed",
        detail=first,
        fields=fields,
    )


api = settings.API_PREFIX
app.include_router(health.router, prefix=api)
app.include_router(auth.router, prefix=api)
app.include_router(me.router, prefix=api)
app.include_router(employees.router, prefix=api)
app.include_router(audit.router, prefix=api)
app.include_router(gis.router, prefix=api)
app.include_router(documents.router, prefix=api)
app.include_router(media.router, prefix=api)
app.include_router(inspections.router, prefix=api)
app.include_router(defects.router, prefix=api)


@app.get("/", tags=["health"])
def root() -> dict:
    return {
        "service": "karier-api",
        "version": "0.1.0",
        "docs": "/docs",
        "api": api,
    }
