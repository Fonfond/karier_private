"""Karier GIS API — Спринт 1: доступ, роли, аудит."""

from __future__ import annotations

import json
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.middleware import AuditMiddleware
from app.api.routers import (
    audit,
    auth,
    cables,
    defects,
    documents,
    employees,
    gis,
    health,
    inspections,
    map_layers,
    me,
    media,
    moves,
    reports,
    schema_blocks,
    sync,
)
from app.core.config import settings
from app.core.errors import ApiError, api_error_handler, problem_response

# Windows-консоль по умолчанию в cp866: русские сообщения в логах превращались
# в мусор и по ним нельзя было найти причину 422. Пишем журнал в UTF-8.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - поток может быть уже перенаправлен
        pass

logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("karier.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Karier API запущен: env=%s", settings.ENV)
    if not settings.is_dev and not settings.COOKIE_SECURE:
        logger.warning(
            "ENV=%s, но COOKIE_SECURE=false — refresh-cookie будет передаваться по HTTP. "
            "Для продакшена выставьте COOKIE_SECURE=true",
            settings.ENV,
        )
    if not settings.is_dev and settings.SECRET_KEY.startswith("dev-"):
        logger.warning("SECRET_KEY выглядит как дев-значение — замените его перед продакшеном")
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


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Базовые защитные заголовки для API и отдаваемых файлов."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    # S-5: CSP для ответов API (в dev и prod одинаково). Для SPA-страниц
    # (Vite в dev, nginx в prod) тот же заголовок должен добавлять reverse-proxy —
    # это часть конфигурации деплоя (Docker/nginx), а не кода приложения.
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; object-src 'none'; frame-ancestors 'self'",
    )
    # SAMEORIGIN, а не DENY: PDF-паспорт и фото открываются в iframe того же домена
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault(
        "Permissions-Policy", "geolocation=(self), camera=(self), microphone=()"
    )
    if not settings.is_dev:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


FIELD_LABELS = {
    "name": "Название",
    "type_code": "Тип",
    "status": "Состояние",
    "code": "Код",
    "x": "X",
    "y": "Y",
    "z": "Z",
    "lat": "Широта",
    "lon": "Долгота",
    "location_text": "Расположение",
    "parent_id": "Родительский объект",
    "attrs": "Атрибуты",
    "lifecycle": "Жизненный цикл",
    "is_mobile": "Признак мобильности",
    "count": "Количество",
    "start": "Стартовый номер",
}

# Русские подписи живут отдельно от машинных ключей: клиент сопоставляет ошибку
# с полем формы по `fields` (name, type_code, x…), а `field_labels` — только
# для человекочитаемого текста в `detail`.
_MESSAGES_RU = (
    ("json decode error", "не удалось разобрать JSON — обновите страницу и повторите"),
    ("field required", "обязательное поле"),
    ("at least 2 characters", "минимум 2 символа"),
    ("at least", "слишком короткое значение"),
    ("at most", "слишком длинное значение"),
    ("input should be 'on'", "недопустимое состояние"),
    ("valid number", "ожидается число"),
    ("valid uuid", "некорректный идентификатор"),
    ("valid boolean", "ожидается да/нет"),
    ("valid string", "ожидается строка"),
    ("valid integer", "ожидается целое число"),
    ("valid list", "ожидается список"),
    ("none is not an allowed value", "значение не может быть пустым"),
)


def _ru_validation_message(message: str) -> str:
    lowered = message.lower()
    for needle, translated in _MESSAGES_RU:
        if needle in lowered:
            return translated
    return message


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    fields: dict[str, str] = {}
    field_labels: dict[str, str] = {}
    for error in exc.errors():
        loc = ".".join(str(part) for part in error.get("loc", []) if part != "body")
        key = loc or "body"
        fields[key] = _ru_validation_message(error.get("msg", "Некорректное значение"))
        field_labels[key] = FIELD_LABELS.get(key, key)

    logger.warning(
        "Отклонена валидация: %s %s fields=%s content_length=%s content_type=%s",
        request.method,
        request.url.path,
        ", ".join(fields) or "—",
        request.headers.get("content-length", "?"),
        request.headers.get("content-type", "?"),
    )

    parts = [f"{field_labels[key]}: {message}" for key, message in fields.items()]
    detail = parts[0] if parts else "Проверьте введённые данные"
    if len(parts) > 1:
        detail = f"{detail} (и ещё {len(parts) - 1})"
    # `field_labels` — дополнение именно для ошибок валидации: общий
    # problem_response() отдаёт только машинные `fields`. Тело берём у него же
    # (единый формат problem+json) и добавляем подписи рядом, не подменяя ключи.
    response = problem_response(
        request,
        status=422,
        code="validation.failed",
        detail=detail,
        fields=fields,
    )
    body = json.loads(response.body)
    body["field_labels"] = field_labels
    return JSONResponse(
        status_code=422,
        content=body,
        media_type="application/problem+json",
        headers={"X-Request-ID": response.headers.get("X-Request-ID", "")},
    )


api = settings.API_PREFIX
app.include_router(health.router, prefix=api)
app.include_router(auth.router, prefix=api)
app.include_router(me.router, prefix=api)
app.include_router(employees.router, prefix=api)
app.include_router(audit.router, prefix=api)
app.include_router(gis.router, prefix=api)
app.include_router(cables.router, prefix=api)
app.include_router(documents.router, prefix=api)
app.include_router(map_layers.router, prefix=api)
app.include_router(media.router, prefix=api)
app.include_router(inspections.router, prefix=api)
app.include_router(defects.router, prefix=api)
app.include_router(moves.router, prefix=api)
app.include_router(sync.router, prefix=api)
app.include_router(reports.router, prefix=api)
app.include_router(schema_blocks.router, prefix=api)


@app.get("/", tags=["health"])
def root() -> dict:
    return {
        "service": "karier-api",
        "version": "0.1.0",
        "docs": "/docs",
        "api": api,
    }
