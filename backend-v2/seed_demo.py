"""Демо-данные для защиты проекта: фото, дефекты, обход, перемещения.

Запуск после seed_gis.py и seed_topology.py:
    python seed_demo.py

Повторный запуск ничего не дублирует: проверяется наличие демо-дефектов.
"""

from __future__ import annotations

import io
import sys
import uuid
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Asset, Defect, Employee, Media
from app.schemas.ops import DefectCreate, DefectUpdate, InspectionCreate, ItemResultIn
from app.schemas.sync import MoveIn
from app.services import defects as defects_service
from app.services import inspections as inspections_service
from app.services import moves as moves_service
from app.services.storage import storage

DEMO_TAG = "ДЕМО: "
WATERMARK_AUTHOR = "Администраторов Админ Админович · таб. 000001"


def demo_photo(code: str, coords: str, caption: str) -> bytes:
    """Сгенерировать «фото объекта» с водяным знаком, как в приложении."""
    width, height = 1200, 900
    image = Image.new("RGB", (width, height), (18, 22, 26))
    draw = ImageDraw.Draw(image)

    for y in range(height):
        shade = int(26 + (y / height) * 38)
        draw.line([(0, y), (width, y)], fill=(shade, shade + 6, shade + 10))

    draw.polygon(
        [(0, 640), (220, 520), (430, 610), (700, 470), (980, 560), (1200, 500), (1200, 900), (0, 900)],
        fill=(58, 56, 52),
    )
    draw.polygon(
        [(0, 720), (260, 650), (520, 705), (820, 620), (1200, 690), (1200, 900), (0, 900)],
        fill=(44, 42, 39),
    )
    draw.ellipse([420, 300, 780, 520], fill=(52, 66, 74))
    draw.rectangle([520, 520, 690, 640], fill=(96, 104, 108))
    draw.rectangle([560, 560, 650, 600], fill=(120, 150, 170))

    bar = 150
    draw.rectangle([0, height - bar, width, height], fill=(8, 12, 16))
    draw.rectangle([0, height - bar, 8, height], fill=(76, 154, 255))
    draw.text((24, height - bar + 16), f"{caption}", fill=(255, 255, 255))
    draw.text((24, height - bar + 62), coords, fill=(200, 214, 224))
    draw.text((24, height - bar + 100), WATERMARK_AUTHOR, fill=(160, 176, 190))

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=84)
    return buffer.getvalue()


def add_photo(
    db,
    asset: Asset,
    actor: Employee,
    *,
    purpose: str,
    caption: str,
    coords: str,
    geo_source: str = "device",
    lat: float | None = 56.2321,
    lon: float | None = 101.8123,
    captured_at: datetime | None = None,
) -> Media:
    media_id = uuid.uuid4()
    data = demo_photo(asset.code, coords, caption)
    key = f"{asset.pit_id}/{media_id}.jpg"
    stored = storage.save(data, key=key)

    media = Media(
        id=media_id,
        pit_id=asset.pit_id,
        asset_id=asset.id,
        kind="photo",
        purpose=purpose,
        storage_path=key,
        mime="image/jpeg",
        size_bytes=stored.size,
        width=1200,
        height=900,
        sha256=stored.sha256,
        captured_at=captured_at or datetime.now(timezone.utc),
        lat=lat,
        lon=lon,
        accuracy_m=6.5,
        geo_source=geo_source,
        author_id=actor.id,
        author_tab_no=actor.tab_no,
        author_name=actor.full_name,
        watermark_applied=f"{caption} · {coords} · {WATERMARK_AUTHOR}",
        exif={"Make": "Google", "Model": "Pixel 7", "DateTimeOriginal": (captured_at or datetime.now(timezone.utc)).isoformat()},
        sync_state="ready",
    )
    db.add(media)
    db.commit()
    db.refresh(media)
    return media


def main() -> int:
    db = SessionLocal()
    try:
        existing = db.scalar(select(Defect).where(Defect.description.like(f"{DEMO_TAG}%")))
        if existing is not None:
            print("Демо-данные уже есть — пропускаем")
            return 0

        admin = db.scalar(select(Employee).where(Employee.tab_no == "000001"))
        if admin is None:
            print("Сначала выполните seed.py")
            return 1

        def asset(code: str) -> Asset:
            row = db.scalar(select(Asset).where(Asset.code == code))
            if row is None:
                raise SystemExit(f"Нет объекта {code} — выполните seed_gis.py и seed_topology.py")
            return row

        now = datetime.now(timezone.utc)
        ktp = asset("KTP-14")
        bkru = asset("BKRU-1")
        ekg = asset("EKG-10")
        dmo = asset("DMO-1")
        cuckoo = asset("CUCKOO-7")

        # --- фото по объектам ------------------------------------------------
        ktp_photo = add_photo(
            db, ktp, admin,
            purpose="inspection",
            caption="КТП-14 · осмотр",
            coords="56.232100, 101.812300 ±7 м",
            captured_at=now - timedelta(days=2, hours=3),
        )
        ekg_photo = add_photo(
            db, ekg, admin,
            purpose="inspection",
            caption="ЭКГ-10 · кабельная разделка",
            coords="56.228700, 101.806900 ±9 м",
            captured_at=now - timedelta(days=2, hours=1),
        )
        bkru_photo = add_photo(
            db, bkru, admin,
            purpose="passport",
            caption="БКРУ-1 · общий вид",
            coords="56.235400, 101.809100 ±5 м",
            captured_at=now - timedelta(days=9),
        )
        add_photo(
            db, dmo, admin,
            purpose="move_proof",
            caption="ДМО-1 · новое место",
            coords="56.221900, 101.801200 ±12 м",
            captured_at=now - timedelta(days=1),
        )

        # --- дефекты ---------------------------------------------------------
        fixed_defect = defects_service.create_defect(
            db,
            ktp.pit_id,
            admin,
            DefectCreate(
                asset_id=ktp.id,
                severity="high",
                description=f"{DEMO_TAG}повреждена кабельная разделка ввода 6 кВ, требуется замена наконечника",
                category="electrical",
                photo_before_id=ktp_photo.id,
            ),
        )
        after_photo = add_photo(
            db, ktp, admin,
            purpose="defect",
            caption="КТП-14 · после устранения",
            coords="56.232100, 101.812300 ±7 м",
            captured_at=now - timedelta(hours=6),
        )
        defects_service.update_defect(
            db,
            fixed_defect,
            DefectUpdate(status="fixed", photo_after_id=after_photo.id, note="Наконечник заменён"),
            actor=admin,
        )

        critical_defect = defects_service.create_defect(
            db,
            ktp.pit_id,
            admin,
            DefectCreate(
                asset_id=ekg.id,
                severity="critical",
                description=f"{DEMO_TAG}перегрев контактного соединения на вводе ЭКГ-10, требуется отключение",
                category="electrical",
                photo_before_id=ekg_photo.id,
            ),
        )
        db.add(
            Defect(
                id=uuid.uuid4(),
                pit_id=ktp.pit_id,
                asset_id=bkru.id,
                severity="medium",
                status="open",
                category="mechanical",
                description=f"{DEMO_TAG}повреждена дверца ячейки, замок не фиксируется",
                detected_at=now - timedelta(days=4),
                detected_by=admin.id,
                photo_before_id=bkru_photo.id,
            )
        )
        db.commit()

        # --- обход -----------------------------------------------------------
        inspection = inspections_service.create_inspection(
            db,
            ktp.pit_id,
            admin,
            InspectionCreate(
                kind="walk",
                title="Плановый обход: северный борт",
                asset_ids=[ktp.id, bkru.id, ekg.id, dmo.id],
            ),
        )
        for asset_row, result, comment in (
            (ktp, "ok", "без замечаний"),
            (bkru, "defect", "дверца ячейки повреждена"),
            (ekg, "critical", "перегрев контактного соединения"),
            (dmo, "ok", "работает по графику"),
        ):
            inspections_service.set_item_result(
                db,
                inspection,
                ItemResultIn(asset_id=asset_row.id, result=result, comment=comment),
            )
        inspections_service.submit_inspection(db, inspection)

        # --- перемещения «кукушек» ------------------------------------------
        moves_service.move_asset(
            db,
            dmo,
            MoveIn(x=640, y=486, note="переставили ближе к забою, гор. +90", client_ts=now - timedelta(days=1)),
            actor=admin,
        )
        moves_service.move_asset(
            db,
            cuckoo,
            MoveIn(x=905, y=505, note="подключили к насосной на гор. +75", client_ts=now - timedelta(days=5)),
            actor=admin,
        )

        print("\n" + "=" * 62)
        print("  Демо-данные готовы — можно показывать систему")
        print("=" * 62)
        print("  фото: 5 · дефекты: 3 (1 устранён) · обход: 1 с 4 объектами")
        print("  перемещения: ДМО-1 и Кукушка-7")
        print("  вход: 000001 / admin")
        print("=" * 62 + "\n")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
