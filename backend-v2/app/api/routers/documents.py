"""Документы: загрузка, выдача файла, удаление."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_permission
from app.core.errors import ApiError
from app.core.security import decode_token
from app.db.session import get_db
from app.models import Employee
from app.schemas.documents import DocumentOut, DocumentUpdate
from app.services import documents as documents_service
from app.services import gis

router = APIRouter(tags=["documents"])


@router.post(
    "/assets/{asset_id}/documents",
    response_model=DocumentOut,
    status_code=201,
    summary="Загрузить документ объекта",
)
def upload_document(
    asset_id: uuid.UUID,
    file: UploadFile = File(...),
    doc_type: str = Form("other"),
    title: str | None = Form(None),
    user: Employee = Depends(require_permission("document.manage")),
    db: Session = Depends(get_db),
) -> DocumentOut:
    if doc_type not in ("schematic", "settings", "manual", "other"):
        raise ApiError(400, "document.bad_type", "Неизвестный тип документа")
    asset = gis.get_asset(db, asset_id)
    document = documents_service.save_document(
        db, asset, upload=file, doc_type=doc_type, title=title, actor=user
    )
    return DocumentOut(
        **documents_service.document_out(db, document, employee_id=str(user.id))
    )


@router.get(
    "/assets/{asset_id}/documents",
    summary="Список документов объекта",
)
def list_documents(
    asset_id: uuid.UUID,
    user: Employee = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    gis.get_asset(db, asset_id)
    rows = documents_service.list_documents(db, asset_id)
    return {
        "items": [
            documents_service.document_out(db, doc, employee_id=str(user.id)) for doc in rows
        ],
        "total": len(rows),
    }


@router.get("/documents/{document_id}/file", summary="Файл документа (по короткой ссылке)")
def download_document(
    document_id: uuid.UUID,
    token: str = Query(..., description="Короткоживущий токен из content_url"),
    db: Session = Depends(get_db),
) -> FileResponse:
    document = documents_service.get_document(db, document_id)
    try:
        payload = decode_token(token, "document")
    except Exception as exc:  # noqa: BLE001
        raise ApiError(401, "document.bad_token", "Ссылка на файл истекла") from exc
    if payload.get("sub") != str(document.id):
        raise ApiError(403, "document.forbidden", "Ссылка не соответствует документу")

    path = documents_service.file_path(document)
    return FileResponse(
        path=path,
        media_type=document.mime,
        filename=document.file_name,
        content_disposition_type="inline",
    )


@router.patch(
    "/documents/{document_id}",
    response_model=DocumentOut,
    summary="Переименовать или сменить тип",
)
def patch_document(
    document_id: uuid.UUID,
    payload: DocumentUpdate,
    user: Employee = Depends(require_permission("document.manage")),
    db: Session = Depends(get_db),
) -> DocumentOut:
    document = documents_service.get_document(db, document_id)
    if payload.title is not None:
        document.title = payload.title
    if payload.doc_type is not None:
        document.doc_type = payload.doc_type
    db.commit()
    db.refresh(document)
    return DocumentOut(
        **documents_service.document_out(db, document, employee_id=str(user.id))
    )


@router.delete("/documents/{document_id}", summary="Удалить документ")
def delete_document(
    document_id: uuid.UUID,
    user: Employee = Depends(require_permission("document.manage")),
    db: Session = Depends(get_db),
) -> dict:
    document = documents_service.get_document(db, document_id)
    documents_service.delete_document(db, document, actor=user)
    return {"message": "Документ удалён", "id": str(document_id)}
