"""Конфигурация приложения (Sprint 1).

Все значения читаются из окружения / .env. Секреты в коде не хранятся.
"""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Значения-заглушки: реальные секреты задаются только через .env (не коммитится)
# или переменные окружения. См. docs/team/08-s1-repo-hygiene.md.
PLACEHOLDER_DB_PASSWORD = "__SET_DB_PASSWORD__"
PLACEHOLDER_SECRET_KEY = "__SET_SECRET_KEY__"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("backend-v2/.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- приложение ---
    APP_NAME: str = "Karier GIS API"
    ENV: str = "dev"  # dev | staging | prod
    DEBUG: bool = True
    API_PREFIX: str = "/api"

    # --- база данных ---
    # Пароль в коде не хранится: задайте DATABASE_URL в backend-v2/.env
    DATABASE_URL: str = (
        f"postgresql+psycopg://karier_user:{PLACEHOLDER_DB_PASSWORD}@127.0.0.1:5432/karier_db"
    )
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10

    # --- безопасность ---
    # Заглушка: рабочий ключ — только в backend-v2/.env (32+ случайных символа)
    SECRET_KEY: str = PLACEHOLDER_SECRET_KEY
    JWT_ALGORITHM: str = "HS256"

    ACCESS_TOKEN_TTL_MIN: int = 15
    REFRESH_TOKEN_TTL_DAYS: int = 30
    # Окно, в котором повторное использование предыдущего refresh-токена
    # считается гонкой вкладок, а не кражей
    REFRESH_REUSE_GRACE_SECONDS: int = 60
    MFA_CHALLENGE_TTL_MIN: int = 5
    ONBOARDING_TTL_MIN: int = 10
    PASSWORD_RESET_TTL_MIN: int = 15

    # cookie с refresh-токеном
    COOKIE_NAME: str = "karier_refresh"
    COOKIE_SECURE: bool = False  # True в prod (HTTPS)
    COOKIE_SAMESITE: str = "lax"
    COOKIE_PATH: str = "/api/auth"

    # --- политика доступа ---
    MAX_FAILED_ATTEMPTS: int = 5
    LOCKOUT_MINUTES: tuple[int, ...] = (1, 15, 60)
    RATE_LIMIT_LOGIN_PER_MINUTE: int = 10
    RATE_LIMIT_REGISTER_PER_HOUR: int = 20

    # --- CORS (dev: фронт на 5174, API на 8001; в prod — один домен) ---
    CORS_ORIGINS: str = "http://localhost:5174,http://127.0.0.1:5174"

    # --- документы ---
    # Локальное хранилище на стенде; в prod — Vercel Blob (та же абстракция storage_path)
    DOCUMENTS_DIR: str = "var/documents"
    MAX_DOCUMENT_MB: int = 25
    DOCUMENT_URL_TTL_MIN: int = 30

    # --- отчёты ---
    EXPORT_URL_TTL_MIN: int = 30
    # Публичный адрес фронтенда — нужен для QR в паспорте объекта
    PUBLIC_BASE_URL: str = "http://localhost:5174"
    # Путь к TTF с кириллицей; если пусто — ищем в системе
    PDF_FONT_PATH: str = ""

    # --- хранилище медиа ---
    # auto → vercel_blob при наличии токена, иначе local
    STORAGE_BACKEND: str = "auto"
    MEDIA_DIR: str = "var/media"
    MAX_PHOTO_MB: int = 15
    BLOB_READ_WRITE_TOKEN: str = ""
    BLOB_PUBLIC_BASE: str = ""
    MEDIA_URL_TTL_MIN: int = 120

    # --- разработка ---
    # Показывать OTP-код в ответе API (только для стенда без Telegram-бота).
    EXPOSE_OTP_CODE: bool = True
    # Печатать письма/коды в stdout вместо отправки.
    CONSOLE_NOTIFICATIONS: bool = True

    @model_validator(mode="after")
    def _require_real_secrets_in_prod(self) -> "Settings":
        """В prod без .env приложение обязано упасть, а не работать на заглушках."""
        if self.ENV != "prod":
            return self
        problems: list[str] = []
        if PLACEHOLDER_DB_PASSWORD in self.DATABASE_URL:
            problems.append(
                "DATABASE_URL: не задан пароль БД (добавьте DATABASE_URL в backend-v2/.env)"
            )
        if self.SECRET_KEY == PLACEHOLDER_SECRET_KEY or len(self.SECRET_KEY) < 32:
            problems.append(
                "SECRET_KEY: не задан или короче 32 символов "
                "(добавьте SECRET_KEY в backend-v2/.env)"
            )
        if problems:
            raise ValueError(
                "Некорректная конфигурация для ENV=prod: " + "; ".join(problems)
            )
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_dev(self) -> bool:
        return self.ENV != "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
