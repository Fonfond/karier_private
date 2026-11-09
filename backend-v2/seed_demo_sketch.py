"""Демо-схема по эскизу главного энергетика.

Создаёт:
    ПС 35/6 «Карьер» (2 секции шин, СВ, 4 фидера)
    → ф.7к → Реклоузер → оп.14 → оп.13 → оп.12 → КТП №4
    → ф.16к → БКРУ-2 → ЯКНО-1

Запуск из backend-v2:
    .\\venv\\Scripts\\python seed_demo_sketch.py
"""

from __future__ import annotations

import sys

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Asset, SchemaBlock
from app.schemas.gis import LinkCreate
from app.services import gis, links as links_service
from app.services import schema_blocks as blocks_service

DEMO = "sketch_v1"


def _block(db, code: str) -> SchemaBlock:
    return blocks_service.get_block(db, code)


def _cleanup(db) -> None:
    parents = [
        asset
        for asset in db.scalars(select(Asset).where(Asset.schema_role == "block")).all()
        if (asset.attrs or {}).get("demo") == DEMO and asset.deleted_at is None
    ]
    for parent in parents:
        for child in db.scalars(
            select(Asset).where(Asset.schema_block_id == parent.id, Asset.deleted_at.is_(None))
        ).all():
            gis.soft_delete(db, child, actor=parent.created_by and _actor(db) or _actor(db))
        gis.soft_delete(db, parent, actor=_actor(db))
    db.commit()


def _actor(db):
    from app.models import Employee, Role

    admin = db.scalar(select(Employee).where(Employee.tab_no == "000001"))
    if admin is not None:
        return admin
    role = db.scalar(select(Role).where(Role.code == "admin"))
    return Employee(tab_no="000000", full_name="Seed", role_id=role.id, otp_channel="manual")


def _place(db, code: str, name: str, x: float, y: float):
    block = _block(db, code)
    result = blocks_service.instantiate(db, block, _actor(db), x=x, y=y, name=name)
    asset = db.get(Asset, __import__("uuid").UUID(result["asset_id"]))
    asset.attrs = {**(asset.attrs or {}), "demo": DEMO}
    db.commit()
    db.refresh(asset)
    return asset


def _port(asset: Asset, code: str):
    for port in asset.ports:
        if port.code == code:
            return port
    raise RuntimeError(f"У {asset.code} нет порта {code}")


def _link(db, source: Asset, source_port: str, target: Asset, target_port: str, mark: str) -> None:
    links_service.create_link(
        db,
        source.pit_id,
        LinkCreate(
            from_port_id=_port(source, source_port).id,
            to_port_id=_port(target, target_port).id,
            link_type="cable",
            cable_mark=mark,
            length_m=120,
        ),
        actor=_actor(db),
    )


def main() -> int:
    db = SessionLocal()
    try:
        _cleanup(db)

        ps = _place(db, "substation_35_6", "ПС 35/6 кВ «Карьер»", 30, 40)
        recloser = _place(db, "recloser", "Реклоузер", 300, 60)
        pole14 = _place(db, "pole", "оп.14", 420, 60)
        pole13 = _place(db, "pole", "оп.13", 540, 60)
        pole12 = _place(db, "pole", "оп.12", 660, 60)
        ktp4 = _place(db, "ktp_standard", "КТП №4", 780, 40)
        bkru2 = _place(db, "bkru_standard", "БКРУ-2", 300, 400)
        yakno1 = _place(db, "yakno", "ЯКНО-1", 600, 420)

        _link(db, ps, "OUT-1", recloser, "IN-1", "СБ-3×185")
        _link(db, recloser, "OUT-1", pole14, "IN-1", "СИП-3 3×120")
        _link(db, pole14, "OUT-1", pole13, "IN-1", "СИП-3 3×120")
        _link(db, pole13, "OUT-1", pole12, "IN-1", "СИП-3 3×120")
        _link(db, pole12, "OUT-1", ktp4, "IN-1", "СИП-3 3×70")

        _link(db, ps, "OUT-2", bkru2, "IN-1", "СБ-3×95")
        _link(db, bkru2, "OUT-1", yakno1, "IN-1", "СБ-3×70")

        print("Демо-схема создана:")
        for label, asset in [
            ("ПС", ps), ("Реклоузер", recloser), ("оп.14", pole14),
            ("оп.13", pole13), ("оп.12", pole12), ("КТП №4", ktp4),
            ("БКРУ-2", bkru2), ("ЯКНО-1", yakno1),
        ]:
            print(f"  {label:12} {asset.code:22} id={asset.id}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
