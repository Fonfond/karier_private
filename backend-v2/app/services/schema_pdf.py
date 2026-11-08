"""Печать однолинейной схемы в PDF: рамка, штамп, узлы и связи (A3)."""

from __future__ import annotations

import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset, Pit
from app.services import gis, topology
from app.services.reports import FONT_CANDIDATES, _FONT_NAME, _register_font

NODE_W = 42
NODE_H = 26
PAD = 24


def _symbol_text(symbol: str) -> str:
    return {
        "breaker": "QF",
        "disconnector": "QS",
        "busbar": "ШИНЫ",
        "load": "M",
        "generator": "G",
        "source": "ПС",
        "line": "ОП",
        "ct": "TA",
        "arrester": "ОПН",
    }.get(symbol, "M")


def schema_pdf(db: Session, pit: Pit) -> bytes:
    font = _register_font()
    frame = gis.get_schema_frame(db, pit)
    graph = topology.graph_payload(db, pit.id)

    buffer = io.BytesIO()
    page = landscape(A3)
    pdf = canvas.Canvas(buffer, pagesize=page)
    width, height = page

    # рамка листа
    pdf.setLineWidth(1.6)
    pdf.setStrokeColor(colors.HexColor("#111111"))
    pdf.rect(12, 12, width - 24, height - 24)
    pdf.setLineWidth(0.5)
    pdf.rect(16, 16, width - 32, height - 32)

    # штамп (правый нижний угол)
    stamp_w, stamp_h = 190, 60
    sx, sy = width - 16 - stamp_w, 16
    pdf.setLineWidth(0.8)
    pdf.rect(sx, sy, stamp_w, stamp_h)
    pdf.setFont(font, 7)
    rows = [
        (frame["organization"], frame["department"]),
        (frame["object_name"], f"{frame['sheet']} · {frame['scale']}"),
        (f"Разработал: {frame['developed_by'] or '—'}", f"Проверил: {frame['checked_by'] or '—'}"),
        (f"Утвердил: {frame['approved_by'] or '—'}", frame["date"]),
    ]
    row_h = stamp_h / len(rows)
    for index, (left, right) in enumerate(rows):
        y = sy + stamp_h - (index + 1) * row_h
        pdf.line(sx, y, sx + stamp_w, y)
        pdf.line(sx + stamp_w / 2, y, sx + stamp_w / 2, y + row_h)
        pdf.drawString(sx + 3, y + row_h - 9, str(left)[:48])
        pdf.drawString(sx + stamp_w / 2 + 3, y + row_h - 9, str(right)[:48])

    # координаты узлов: сохранённые или сетка
    assets = list(
        db.scalars(
            select(Asset).where(Asset.pit_id == pit.id, Asset.deleted_at.is_(None))
        ).unique().all()
    )
    positions: dict = {}
    for index, asset in enumerate(assets):
        if asset.schema_x is not None and asset.schema_y is not None:
            positions[asset.id] = (float(asset.schema_x), float(asset.schema_y))
        else:
            positions[asset.id] = ((index % 7) * 170.0, (index // 7) * 120.0)

    xs = [p[0] for p in positions.values()] or [0]
    ys = [p[1] for p in positions.values()] or [0]
    min_x, max_x = min(xs), max(xs) + NODE_W
    min_y, max_y = min(ys), max(ys) + NODE_H
    scale = min(
        (width - 2 * PAD - 40) / max(max_x - min_x, 1),
        (height - 2 * PAD - 120) / max(max_y - min_y, 1),
    )

    def to_page(point: tuple[float, float]) -> tuple[float, float]:
        x = PAD + (point[0] - min_x) * scale
        y = height - PAD - 70 - (point[1] - min_y) * scale
        return x, y

    # связи
    pdf.setStrokeColor(colors.HexColor("#333333"))
    pdf.setLineWidth(0.9)
    for edge in graph["edges"]:
        start = positions.get(edge["from_asset_id"])
        end = positions.get(edge["to_asset_id"])
        if not start or not end:
            continue
        x1, y1 = to_page(start)
        x2, y2 = to_page(end)
        pdf.line(x1 + NODE_W * scale / 2, y1, x2 + NODE_W * scale / 2, y2)

    # узлы
    for asset in assets:
        position = positions.get(asset.id)
        if position is None:
            continue
        x, y = to_page(position)
        w = NODE_W * scale
        h = NODE_H * scale
        symbol = asset.asset_type.schema_symbol or "load"
        if symbol == "busbar":
            pdf.setLineWidth(2.4)
            pdf.line(x - 8, y + h / 2, x + w + 8, y + h / 2)
        else:
            pdf.setLineWidth(0.7)
            pdf.rect(x, y, w, h)
            pdf.setFont(font, 7)
            pdf.drawString(x + 3, y + h - 9, _symbol_text(symbol))
        pdf.setFont(font, 6)
        pdf.drawString(x, y - 8, asset.code[:18])

    pdf.setFont(font, 8)
    pdf.drawString(20, height - 28, f"{frame['object_name']} · {pit.name}")
    pdf.setFont(font, 7)
    pdf.drawRightString(
        width - 20,
        height - 28,
        datetime.now(timezone.utc).astimezone().strftime("%d.%m.%Y %H:%M"),
    )

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
