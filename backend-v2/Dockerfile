# syntax=docker/dockerfile:1
# API «Карьер» (backend-v2): python 3.14-slim + uvicorn, один воркер.
# Конфигурация — только через окружение (см. .env.example в корне); .env в образ не копируется.

FROM python:3.14-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Europe/Moscow

WORKDIR /app

# Зависимости отдельным слоем: меняются реже исходников
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./
RUN chmod +x /app/entrypoint.sh \
    && mkdir -p /app/var/documents /app/var/media

# Миграции и запуск — через entrypoint (ждёт БД, alembic upgrade head, uvicorn)
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health/ready', timeout=4).status == 200 else 1)"

ENTRYPOINT ["/app/entrypoint.sh"]
