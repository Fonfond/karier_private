"""Абстракция хранилища файлов.

Сейчас — локальный диск. При наличии `BLOB_READ_WRITE_TOKEN` включается
Vercel Blob: код сохранения и чтения остаётся тем же.

Переменные:
  * `STORAGE_BACKEND` — `local` | `vercel_blob` (по умолчанию определяется по токену)
  * `BLOB_READ_WRITE_TOKEN` — токен Vercel Blob
  * `BLOB_PUBLIC_BASE` — необязательный публичный префикс CDN
"""

from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings


@dataclass
class StoredFile:
    key: str
    size: int
    sha256: str
    public_url: str | None = None


class LocalStorage:
    backend = "local"

    def __init__(self, root: str) -> None:
        base = Path(root)
        if not base.is_absolute():
            base = Path(__file__).resolve().parents[2] / base
        self.root = base
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes, *, key: str) -> StoredFile:
        target = self.root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return StoredFile(
            key=key,
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )

    def path(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        if self.root.resolve() not in candidate.parents:
            raise ValueError("Некорректный путь файла")
        return candidate

    def read(self, key: str) -> bytes:
        return self.path(key).read_bytes()

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)


class VercelBlobStorage:
    """Минимальный клиент Vercel Blob (REST).

    Загрузка идёт обычным PUT, чтение — по публичному URL. Полноценный
    клиентский upload с токеном добавим, когда появится реальный бакет.
    """

    backend = "vercel_blob"

    def __init__(self, token: str) -> None:
        self.token = token

    def save(self, data: bytes, *, key: str) -> StoredFile:
        import httpx

        content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
        response = httpx.put(
            f"https://blob.vercel-storage.com/{key}",
            content=data,
            headers={
                "Authorization": f"Bearer {self.token}",
                "x-api-version": "7",
                "x-content-type": content_type,
                "x-add-random-suffix": "0",
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        return StoredFile(
            key=key,
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            public_url=payload.get("url"),
        )

    def path(self, key: str) -> Path:  # pragma: no cover - не используется
        raise NotImplementedError("Файлы в Vercel Blob не имеют локального пути")

    def read(self, key: str) -> bytes:  # pragma: no cover
        import httpx

        url = f"{settings.BLOB_PUBLIC_BASE.rstrip('/')}/{key}" if settings.BLOB_PUBLIC_BASE else key
        response = httpx.get(url, timeout=60)
        response.raise_for_status()
        return response.content

    def delete(self, key: str) -> None:  # pragma: no cover
        import httpx

        httpx.delete(
            f"https://blob.vercel-storage.com/{key}",
            headers={"Authorization": f"Bearer {self.token}", "x-api-version": "7"},
            timeout=30,
        )


def build_storage():
    if settings.STORAGE_BACKEND == "vercel_blob" or (
        settings.STORAGE_BACKEND == "auto" and settings.BLOB_READ_WRITE_TOKEN
    ):
        return VercelBlobStorage(settings.BLOB_READ_WRITE_TOKEN)
    return LocalStorage(settings.MEDIA_DIR)


storage = build_storage()
