"""Печать однолинейной схемы в PDF: блоки рамками, легенда, штамп (A3)."""

from __future__ import annotations

import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset, Pit
from app.services import gis, topology
from app.services import schema_blocks as blocks_service
from app.services.reports import _register_font

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

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=landscape(A3))
    width, height = landscape(A3)

    pdf.setLineWidth(1.6)
    pdf.rect(12, 12, width - 24, height - 24)
    pdf.setLineWidth(0.5)
    pdf.rect(16, 16, width - 32, height - 32)

    # --- штамп -------------------------------------------------------------
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

    # --- легенда -----------------------------------------------------------
    legend_items = blocks_service.legend(db)
    if legend_items:
        legend_w = 190
        legend_h = 14 + 11 * len(legend_items)
        lx, ly = width - 16 - legend_w, sy + stamp_h + 8
        pdf.setLineWidth(0.6)
        pdf.rect(lx, ly, legend_w, legend_h)
        pdf.setFont(font, 7)
        pdf.drawString(lx + 4, ly + legend_h - 10, "Условные обозначения")
        for index, item in enumerate(legend_items):
            yy = ly + legend_h - 22 - index * 11
            pdf.drawString(lx + 4, yy, f"{_symbol_text(item['symbol'])} — {item['title']}"[:52])

    # --- объекты и блоки ---------------------------------------------------
    assets = list(
        db.scalars(
            select(Asset).where(Asset.pit_id == pit.id, Asset.deleted_at.is_(None))
        ).unique().all()
    )
    by_id = {asset.id: asset for asset in assets}
    blocks = [asset for asset in assets if asset.schema_role == "block"]
    children: dict = {}
    for asset in assets:
        if asset.schema_block_id is not None:
            children.setdefault(asset.schema_block_id, []).append(asset)

    # положение блоков: сохранённое или сетка
    block_pos: dict = {}
    for index, block in enumerate(blocks):
        if block.schema_x is not None and block.schema_y is not None:
            block_pos[block.id] = (float(block.schema_x), float(block.schema_y))
        else:
            block_pos[block.id] = (40.0 + (index % 2) * 430.0, 40.0 + (index // 2) * 330.0)

    used_children = {child.id for items in children.values() for child in items}
    plain = [asset for asset in assets if asset.id not in used_children and asset.schema_role != "block"]

    # связ�� между блоками
    graph = topology.graph_payload(db, pit.id)
    pdf.setStrokeColor(colors.HexColor("#333333"))
    pdf.setLineWidth(0.9)
    for edge in graph["edges"]:
        start = block_pos.get(edge["from_asset_id"])
        end = block_pos.get(edge["to_asset_id"])
        if not start or not end:
            continue
        pdf.line(start[0] + 180, start[1] + 40, end[0], end[1] + 40)

    # блоки
    for block in blocks:
        bx, by = block_pos[block.id]
        kids = children.get(block.id, [])
        collapsed = bool((block.attrs or {}).get("collapsed"))

        if collapsed:
            pdf.setLineWidth(1.0)
            pdf.rect(bx, by, 160, 46)
            pdf.setFont(font, 8)
            pdf.drawString(bx + 5, by + 28, block.name[:34])
            pdf.setFont(font, 6)
            pdf.drawString(bx + 5, by + 16, f"{len(kids)} эл. · {block.code}")
            continue

        bw, bh = 380.0, 260.0
        pdf.setLineWidth(1.2)
        pdf.setStrokeColor(colors.HexColor("#1a1a1a"))
        pdf.rect(bx, by, bw, bh)
        pdf.setFont(font, 8)
        pdf.drawString(bx + 7, by + bh - 14, block.name[:44])
        pdf.setFont(font, 6)
        pdf.drawString(bx + 7, by + bh - 24, f"{block.code} · {len(kids)} элементов")

        busbars = [item for item in kids if item.schema_role == "busbar"]
        cells = [item for item in kids if item.schema_role != "busbar"]

        for index, bus in enumerate(busbars):
            y = by + bh - 60 - index * 34
            pdf.setLineWidth(2.2)
            pdf.line(bx + 10, y, bx + bw - 10, y)
            pdf.setFont(font, 6)
            pdf.drawString(bx + 10, y + 4, bus.name[:40])

        cols = 3
        for index, cell in enumerate(cells):
            col = index % cols
            row = index // cols
            cx = bx + 12 + col * ((bw - 24) / cols)
            cy = by + bh - 92 - row * 30
            if cy < by + 12:
                break
            pdf.setLineWidth(0.5)
            pdf.rect(cx, cy, (bw - 30) / cols, 20)
            pdf.setFont(font, 5.5)
            pdf.drawString(cx + 2, cy + 12, _symbol_text("breaker"))
            pdf.drawString(cx + 2, cy + 4, cell.name[:22])

    # одиночные объекты
    for index, asset in enumerate(plain):
        x = 40 + (index % 6) * 120
        y = 140 + (index // 6) * 90
        pdf.setLineWidth(0.6)
        pdf.rect(x, y, 100, 34)
        pdf.setFont(font, 6)
        pdf.drawString(x + 3, y + 22, _symbol_text(asset.asset_type.schema_symbol or "load"))
        pdf.drawString(x + 3, y + 12, asset.code[:18])
        pdf.setFont(font, "5" if False else 5)
        pdf.drawString(x + 3, y + 4, asset.name[:24])

    pdf.setFont(font, 8)
    pdf.drawString(20, height - 28, f"{frame['object_name']} · {pit.name}")
    pdf.setFont(font, 7)
    pdf.drawRightString(
        width - 20, height - 28,
        datetime.now(timezone.utc).astimezone().strftime("%d.%m.%Y %H:%M"),
    )

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
