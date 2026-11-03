"""Отчёты: Excel-выгрузки и PDF-паспорт объекта."""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Asset, Defect, Employee, Inspection, InspectionItem, Media, Pit, SwitchingOp
from app.services import gis, storage as storage_module
from app.services import topology

STATUS_LABEL = {
    "on": "включено",
    "off": "отключено",
    "standby": "резерв",
    "maintenance": "ремонт",
    "decommissioned": "списано",
}

SEVERITY_LABEL = {
    "low": "низкая",
    "medium": "средняя",
    "high": "высокая",
    "critical": "критичная",
}

DEFECT_STATUS_LABEL = {
    "open": "открыт",
    "in_progress": "в работе",
    "fixed": "устранён",
    "accepted": "принят",
    "rejected": "отклонён",
}

HEADER_FILL = PatternFill("solid", fgColor="1F3B57")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)


def _autosize(worksheet, widths: dict[str, int]) -> None:
    for column, width in widths.items():
        worksheet.column_dimensions[column].width = width


def _prepare_sheet(worksheet, headers: list[str], widths: list[int]) -> None:
    worksheet.append(headers)
    for index, _ in enumerate(headers, start=1):
        cell = worksheet.cell(row=1, column=index)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        worksheet.column_dimensions[get_column_letter(index)].width = widths[index - 1]
    worksheet.freeze_panes = "A2"
    worksheet.row_dimensions[1].height = 24


def _workbook_bytes(workbook: Workbook) -> bytes:
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# --- Excel -----------------------------------------------------------------

def assets_xlsx(db: Session, pit: Pit) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Реестр оборудования"
    _prepare_sheet(
        sheet,
        [
            "Код",
            "Название",
            "Тип",
            "Статус",
            "Мобильный",
            "Заземлено",
            "Родитель",
            "X, м",
            "Y, м",
            "Расположение",
            "Атрибуты",
            "Обновлён",
        ],
        [16, 34, 28, 14, 11, 11, 18, 10, 10, 26, 40, 18],
    )

    assets = db.scalars(
        select(Asset)
        .where(Asset.pit_id == pit.id, Asset.deleted_at.is_(None))
        .order_by(Asset.code)
    ).unique().all()

    for asset in assets:
        sheet.append(
            [
                asset.code,
                asset.name,
                asset.asset_type.name if asset.asset_type else "",
                STATUS_LABEL.get(asset.status, asset.status),
                "да" if asset.is_mobile else "нет",
                "да" if asset.grounded else "нет",
                asset.parent.code if asset.parent else "",
                float(asset.x) if asset.x is not None else "",
                float(asset.y) if asset.y is not None else "",
                asset.location_text or "",
                ", ".join(f"{key}={value}" for key, value in (asset.attrs or {}).items()),
                asset.updated_at.strftime("%d.%m.%Y %H:%M") if asset.updated_at else "",
            ]
        )

    sheet.auto_filter.ref = sheet.dimensions
    return _workbook_bytes(workbook)


def defects_xlsx(db: Session, pit: Pit) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Дефекты"
    _prepare_sheet(
        sheet,
        [
            "Код объекта",
            "Объект",
            "Критичность",
            "Статус",
            "Категория",
            "Описание",
            "Обнаружен",
            "Кто обнаружил",
            "Устранён",
            "Кто устранил",
            "Фото до",
            "Фото после",
        ],
        [14, 30, 14, 12, 14, 50, 18, 26, 18, 26, 12, 12],
    )

    defects = db.scalars(
        select(Defect).where(Defect.pit_id == pit.id).order_by(Defect.detected_at.desc())
    ).all()

    for defect in defects:
        sheet.append(
            [
                defect.asset.code if defect.asset else "",
                defect.asset.name if defect.asset else "",
                SEVERITY_LABEL.get(defect.severity, defect.severity),
                DEFECT_STATUS_LABEL.get(defect.status, defect.status),
                defect.category or "",
                defect.description,
                defect.detected_at.strftime("%d.%m.%Y %H:%M") if defect.detected_at else "",
                db.get(Employee, defect.detected_by).full_name if defect.detected_by else "",
                defect.fixed_at.strftime("%d.%m.%Y %H:%M") if defect.fixed_at else "",
                db.get(Employee, defect.fixed_by).full_name if defect.fixed_by else "",
                str(defect.photo_before_id) if defect.photo_before_id else "",
                str(defect.photo_after_id) if defect.photo_after_id else "",
            ]
        )

    sheet.auto_filter.ref = sheet.dimensions
    return _workbook_bytes(workbook)


def switching_xlsx(db: Session, pit: Pit) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Переключения"
    _prepare_sheet(
        sheet,
        ["Время", "Объект", "Действие", "Было", "Стало", "Причина", "Кто"],
        [18, 28, 18, 14, 14, 40, 26],
    )

    rows = db.scalars(
        select(SwitchingOp)
        .where(SwitchingOp.pit_id == pit.id)
        .order_by(SwitchingOp.performed_at.desc())
    ).all()

    for row in rows:
        author = db.get(Employee, row.performed_by) if row.performed_by else None
        sheet.append(
            [
                row.performed_at.strftime("%d.%m.%Y %H:%M"),
                row.asset.code if row.asset else "",
                row.action,
                row.from_state or "",
                row.to_state or "",
                row.reason or "",
                author.full_name if author else "",
            ]
        )

    sheet.auto_filter.ref = sheet.dimensions
    return _workbook_bytes(workbook)


def inspections_xlsx(db: Session, pit: Pit) -> bytes:
    workbook = Workbook()
    summary = workbook.active
    summary.title = "Обходы"
    _prepare_sheet(
        summary,
        ["Обход", "Начат", "Завершён", "Сотрудник", "Объектов", "Проверено", "Статус"],
        [30, 18, 18, 26, 11, 11, 14],
    )

    inspections = db.scalars(
        select(Inspection)
        .where(Inspection.pit_id == pit.id)
        .order_by(Inspection.started_at.desc())
    ).all()

    for inspection in inspections:
        author = db.get(Employee, inspection.employee_id) if inspection.employee_id else None
        items = db.scalars(
            select(InspectionItem).where(InspectionItem.inspection_id == inspection.id)
        ).all()
        summary.append(
            [
                inspection.title or "",
                inspection.started_at.strftime("%d.%m.%Y %H:%M"),
                inspection.finished_at.strftime("%d.%m.%Y %H:%M") if inspection.finished_at else "",
                author.full_name if author else "",
                len(items),
                sum(1 for item in items if item.result),
                inspection.status,
            ]
        )

    detail = workbook.create_sheet("Строки обходов")
    _prepare_sheet(
        detail,
        ["Обход", "Объект", "Код", "Результат", "Комментарий", "Проверен"],
        [30, 30, 14, 14, 50, 18],
    )
    for inspection in inspections:
        items = db.scalars(
            select(InspectionItem).where(InspectionItem.inspection_id == inspection.id)
        ).all()
        for item in items:
            detail.append(
                [
                    inspection.title or "",
                    item.asset.name if item.asset else "",
                    item.asset.code if item.asset else "",
                    item.result or "не проверен",
                    item.comment or "",
                    item.checked_at.strftime("%d.%m.%Y %H:%M") if item.checked_at else "",
                ]
            )

    summary.auto_filter.ref = summary.dimensions
    detail.auto_filter.ref = detail.dimensions
    return _workbook_bytes(workbook)


# --- PDF -------------------------------------------------------------------

FONT_CANDIDATES = [
    settings.PDF_FONT_PATH,
    str(Path(__file__).resolve().parents[2] / "assets" / "fonts" / "DejaVuSans.ttf"),
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
]

_FONT_NAME = "KarierSans"
_font_registered = False


def _register_font() -> str:
    global _font_registered
    if _font_registered:
        return _FONT_NAME
    for candidate in FONT_CANDIDATES:
        if candidate and Path(candidate).exists():
            pdfmetrics.registerFont(TTFont(_FONT_NAME, candidate))
            _font_registered = True
            return _FONT_NAME
    # без TTF кириллица не отрисуется — честно падаем на встроенный шрифт
    return "Helvetica"


def _qr_png(url: str) -> io.BytesIO | None:
    try:
        import qrcode
        from qrcode.image.pil import PilImage

        image = qrcode.make(url, image_factory=PilImage, box_size=8, border=1)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer
    except Exception:  # noqa: BLE001
        return None


def _photo_stream(media: Media) -> io.BytesIO | None:
    """Прочитать фото из хранилища и нормализовать в JPEG.

    Битые или недокачанные файлы пропускаем: паспорт должен собраться даже
    если одно фото повреждено.
    """
    try:
        from PIL import Image as PILImage

        data = storage_module.storage.read(media.storage_path)
        image = PILImage.open(io.BytesIO(data))
        image.load()
        image = image.convert("RGB")
        image.thumbnail((1200, 1200))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        buffer.seek(0)
        return buffer
    except Exception:  # noqa: BLE001
        return None


def passport_pdf(db: Session, asset: Asset, *, generated_by: Employee) -> bytes:
    font = _register_font()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=16 * mm,
        title=f"Паспорт {asset.code}",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleRu", parent=styles["Title"], fontName=font, fontSize=18, spaceAfter=4)
    subtitle = ParagraphStyle("SubRu", parent=styles["Normal"], fontName=font, fontSize=11, textColor=colors.HexColor("#444444"))
    heading = ParagraphStyle("HeadRu", parent=styles["Heading2"], fontName=font, fontSize=12, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("BodyRu", parent=styles["Normal"], fontName=font, fontSize=9.5, leading=13)

    story: list = []
    story.append(Paragraph("Паспорт объекта", title_style))
    story.append(Paragraph(f"{asset.code} · {asset.name}", subtitle))
    story.append(Spacer(1, 6 * mm))

    power = topology.power_path(db, asset)
    chain = " → ".join(node["asset"].name for node in power["nodes"]) or "нет пути питания"

    rows = [
        ["Тип", asset.asset_type.name if asset.asset_type else "—"],
        ["Статус", STATUS_LABEL.get(asset.status, asset.status)],
        ["Заземление", "установлено" if asset.grounded else "нет"],
        ["Расположение", asset.location_text or "—"],
        ["Координаты", f"X {asset.x} · Y {asset.y} м" if asset.x is not None else "—"],
        ["Входит в", asset.parent.name if asset.parent else "—"],
        [
            "Питание",
            Paragraph(
                ("под напряжением" if power["energized"] else "обесточено") + f" · {chain}", body
            ),
        ],
    ]
    for key, value in (asset.attrs or {}).items():
        rows.append([str(key), str(value)])

    table = Table(rows, colWidths=[42 * mm, 120 * mm])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555555")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#DDDDDD")),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 4 * mm))

    qr_url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/asset/{asset.id}"
    qr_stream = _qr_png(qr_url)
    if qr_stream is not None:
        card = Table(
            [
                [
                    Image(qr_stream, width=30 * mm, height=30 * mm),
                    Paragraph(
                        f"QR-код ведёт на карточку объекта:<br/><font size=8>{qr_url}</font><br/><br/>"
                        f"Отчёт сформирован {datetime.now(timezone.utc).astimezone():%d.%m.%Y %H:%M}<br/>"
                        f"Сотрудник: {generated_by.full_name}, таб. {generated_by.tab_no}",
                        body,
                    ),
                ]
            ],
            colWidths=[34 * mm, 128 * mm],
        )
        card.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("FONTNAME", (0, 0), (-1, -1), font)]))
        story.append(card)

    photos = db.scalars(
        select(Media)
        .where(Media.asset_id == asset.id, Media.deleted_at.is_(None))
        .order_by(Media.captured_at.desc())
        .limit(3)
    ).all()

    photo_items: list[tuple[io.BytesIO, Media]] = []
    for media in photos:
        stream = _photo_stream(media)
        if stream is not None:
            photo_items.append((stream, media))

    if photo_items:
        story.append(Paragraph("Последние фото", heading))
        cells = [
            [
                Image(stream, width=52 * mm, height=39 * mm),
                Paragraph(
                    f"{(media.captured_at or media.received_at):%d.%m.%Y %H:%M}<br/>"
                    f"{media.author_name or ''}",
                    body,
                ),
            ]
            for stream, media in photo_items
        ]
        photo_table = Table([[cell[0] for cell in cells]], colWidths=[54 * mm] * len(cells))
        photo_table.setStyle(
            TableStyle(
                [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]
            )
        )
        story.append(photo_table)
        captions = Table([[cell[1] for cell in cells]], colWidths=[54 * mm] * len(cells))
        captions.setStyle(
            TableStyle(
                [("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 7.5)]
            )
        )
        story.append(captions)

    story.append(Spacer(1, 6 * mm))
    story.append(
        Paragraph(
            "Документ сформирован автоматически системой «Карьер · Электроснабжение». "
            "Данные актуальны на момент печати.",
            ParagraphStyle("FootRu", parent=body, fontSize=8, textColor=colors.HexColor("#777777")),
        )
    )

    doc.build(story)
    return buffer.getvalue()
