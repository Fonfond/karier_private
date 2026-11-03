"""Конфигурация приложения (Sprint 1).

Все значения читаются из окружения / .env. Секреты в коде не хранятся.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    DATABASE_URL: str = (
        "postgresql+psycopg://karier_user:Df492357816@127.0.0.1:5432/karier_db"
    )
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10

    # --- безопасность ---
    SECRET_KEY: str = "dev-only-secret-change-me-karier-2026"
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
