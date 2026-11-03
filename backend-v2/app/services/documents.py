"""Документы объекта: загрузка, выдача файла, удаление."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ApiError, not_found
from app.core.security import create_document_token
from app.models import Asset, Document
from app.services import audit

ALLOWED_MIME = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/svg+xml",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
    "application/zip",
}

DOC_TYPE_LABEL = {
    "schematic": "Электросхема",
    "settings": "Уставки",
    "manual": "Инструкция",
    "other": "Прочее",
}


def storage_root() -> Path:
    path = Path(settings.DOCUMENTS_DIR)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_name(name: str) -> str:
    cleaned = "".join(ch for ch in name if ch.isalnum() or ch in " ._-()").strip()
    return cleaned[:120] or "document"


def save_document(
    db: Session,
    asset: Asset,
    *,
    upload: UploadFile,
    doc_type: str,
    title: str | None,
    actor,
) -> Document:
    mime = (upload.content_type or "application/octet-stream").split(";")[0].strip()
    if mime not in ALLOWED_MIME:
        raise ApiError(
            415,
            "document.bad_type",
            "Такой тип файла не поддерживается. Разрешены PDF, изображения, Word, Excel, ZIP",
        )

    document_id = uuid.uuid4()
    suffix = Path(upload.filename or "").suffix.lower()[:10]
    directory = storage_root() / str(asset.pit_id)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{document_id}{suffix}"

    digest = hashlib.sha256()
    size = 0
    limit = settings.MAX_DOCUMENT_MB * 1024 * 1024
    with target.open("wb") as handle:
        while chunk := upload.file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                handle.close()
                target.unlink(missing_ok=True)
                raise ApiError(
                    413,
                    "document.too_large",
                    f"Файл больше {settings.MAX_DOCUMENT_MB} МБ",
                )
            digest.update(chunk)
            handle.write(chunk)

    if size == 0:
        target.unlink(missing_ok=True)
        raise ApiError(400, "document.empty", "Файл пустой")

    document = Document(
        id=document_id,
        pit_id=asset.pit_id,
        asset_id=asset.id,
        doc_type=doc_type,
        title=(title or upload.filename or "Документ").strip()[:255],
        file_name=_safe_name(upload.filename or "document"),
        mime=mime,
        size_bytes=size,
        storage_path=str(target),
        sha256=digest.hexdigest(),
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    audit.add(
        "document.uploaded",
        entity="document",
        entity_id=document.id,
        detail=f"{DOC_TYPE_LABEL.get(doc_type, doc_type)}: {document.title} → {asset.code}",
        payload={"size": size, "mime": mime},
    )
    return document


def list_documents(db: Session, asset_id: uuid.UUID) -> list[Document]:
    return list(
        db.scalars(
            select(Document)
            .where(Document.asset_id == asset_id, Document.deleted_at.is_(None))
            .order_by(Document.doc_type, Document.created_at.desc())
        ).all()
    )


def get_document(db: Session, document_id: uuid.UUID) -> Document:
    document = db.get(Document, document_id)
    if document is None or document.deleted_at is not None:
        raise not_found("Документ не найден")
    return document


def file_path(document: Document) -> Path:
    root = storage_root().resolve()
    path = Path(document.storage_path).resolve()
    if root not in path.parents and path != root:
        raise ApiError(403, "document.forbidden_path", "Некорректный путь к файлу")
    if not path.exists():
        raise not_found("Файл документа отсутствует в хранилище")
    return path


def delete_document(db: Session, document: Document, *, actor) -> None:
    document.deleted_at = datetime.now(timezone.utc)
    document.deleted_by = actor.id
    db.commit()
    Path(document.storage_path).unlink(missing_ok=True)
    audit.add(
        "document.deleted",
        entity="document",
        entity_id=document.id,
        detail=f"Удалён документ «{document.title}»",
    )


def document_out(db: Session, document: Document, *, employee_id: str) -> dict:
    token = create_document_token(str(document.id), employee_id=employee_id)
    return {
        "id": document.id,
        "asset_id": document.asset_id,
        "doc_type": document.doc_type,
        "doc_type_label": DOC_TYPE_LABEL.get(document.doc_type, document.doc_type),
        "title": document.title,
        "file_name": document.file_name,
        "mime": document.mime,
        "size_bytes": document.size_bytes,
        "version": document.version,
        "created_at": document.created_at,
        "content_url": f"/api/documents/{document.id}/file?token={token}",
        "sha256": document.sha256,
    }
