"""Демо-схема по эскизу (v2): ПС → ВЛ/КЛ → КТП, БКРУ, ЯКНО-6.

Топология по эскизу и замечаниям главного энергетика:
    Т-1/Т-2 35/6 → ПС 35/6 (2 секции, СВ, QF+ТТ+Wh на фидерах)
    ф.7к  → оп.1 → оп.2 → оп.3 → оп.4 → реклоузер → КТП №4 (400 кВА) → 0.4 кВ
    оп.4  → ЯКНО-1/1к → Ввод 2 БКРУ-1
    ф.16к → ЯКНО-6 (6 ячеек, ЭКГ-12К/1, ЭКГ-12К/2, ЭКГ-15М)
    ф.21к → Ввод 1 БКРУ-1
    БКРУ-1: 2 секции + СВ, фидеры ф.2/ф.3/ф.5

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

DEMO = "sketch_v2"


def _actor(db):
    from app.models import Employee, Role

    admin = db.scalar(select(Employee).where(Employee.tab_no == "000001"))
    if admin is not None:
        return admin
    role = db.scalar(select(Role).where(Role.code == "admin"))
    return Employee(tab_no="000000", full_name="Seed", role_id=role.id, otp_channel="manual")


def _cleanup(db) -> None:
    actor = _actor(db)
    for parent in db.scalars(select(Asset).where(Asset.schema_role == "block")).all():
        if (parent.attrs or {}).get("demo") in (DEMO, "sketch_v1") and parent.deleted_at is None:
            for child in db.scalars(
                select(Asset).where(Asset.schema_block_id == parent.id, Asset.deleted_at.is_(None))
            ).all():
                gis.soft_delete(db, child, actor=actor)
            gis.soft_delete(db, parent, actor=actor)
    db.commit()


def _place(db, code: str, name: str, x: float, y: float) -> Asset:
    block: SchemaBlock = blocks_service.get_block(db, code)
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
    raise RuntimeError(f"У {asset.code} ({asset.name}) нет порта {code}")


def _link(
    db,
    source: Asset,
    source_port: str,
    target: Asset,
    target_port: str,
    *,
    mark: str,
    length: float,
    link_type: str = "cable",
) -> None:
    links_service.create_link(
        db,
        source.pit_id,
        LinkCreate(
            from_port_id=_port(source, source_port).id,
            to_port_id=_port(target, target_port).id,
            link_type=link_type,
            cable_mark=mark,
            length_m=length,
        ),
        actor=_actor(db),
    )


def main() -> int:
    db = SessionLocal()
    try:
        _cleanup(db)

        t1 = _place(db, "source_35", "Т-1 35/6 кВ", 30, 30)
        t2 = _place(db, "source_35", "Т-2 35/6 кВ", 30, 130)
        ps = _place(db, "substation_35_6", "ПС 35/6 кВ «Карьер»", 210, 30)

        op1 = _place(db, "pole", "оп.1", 420, 20)
        op2 = _place(db, "pole", "оп.2", 520, 20)
        op3 = _place(db, "pole", "оп.3", 620, 20)
        op4 = _place(db, "pole", "оп.4", 720, 20)
        for pole in (op1, op2, op3):
            for port in list(pole.ports):
                if port.code == "OUT-2":
                    db.delete(port)
        db.commit()
        recloser = _place(db, "recloser", "Реклоузер", 820, 20)
        ktp4 = _place(db, "ktp_standard", "КТП №4 · 400 кВА", 930, 20)

        yakno1 = _place(db, "yakno1", "ЯКНО-1/1к", 720, 120)
        yakno6 = _place(db, "yakno6", "ЯКНО-6", 210, 300)
        bkru1 = _place(db, "bkru_standard", "БКРУ-1", 470, 300)

        pktp_f2 = _place(db, "pktp", "ПКТП-3 · 400 кВА", 780, 300)
        ekg_f3 = _place(db, "ekg", "ЭКГ-15М · 1500 кВт", 780, 380)
        pktp_f5 = _place(db, "pktp", "ПКТП-4 · 400 кВА", 780, 460)

        load_l1 = _place(db, "pktp_04", "ПКТП-1 · 63 кВА", 930, 210)
        load_l2 = _place(db, "pktp_04", "ПКТП-2 · 630 кВА", 930, 280)

        _link(db, t1, "OUT-1", ps, "IN-1", mark="35 кВ ввод Т-1", length=30, link_type="cable")
        _link(db, t2, "OUT-1", ps, "IN-2", mark="35 кВ ввод Т-2", length=30, link_type="cable")

        _link(db, ps, "OUT-1", op1, "IN-1", mark="СИП-3 3×120", length=60, link_type="overhead")
        _link(db, op1, "OUT-1", op2, "IN-1", mark="СИП-3 3×120", length=70, link_type="overhead")
        _link(db, op2, "OUT-1", op3, "IN-1", mark="СИП-3 3×120", length=70, link_type="overhead")
        _link(db, op3, "OUT-1", op4, "IN-1", mark="СИП-3 3×120", length=80, link_type="overhead")
        _link(db, op4, "OUT-1", recloser, "IN-1", mark="СИП-3 3×120", length=40, link_type="overhead")
        _link(db, recloser, "OUT-1", ktp4, "IN-1", mark="СИП-3 3×70", length=50, link_type="overhead")
        _link(db, op4, "OUT-2", yakno1, "IN-1", mark="СБ-3×95", length=120, link_type="cable")
        _link(db, yakno1, "OUT-1", bkru1, "IN-2", mark="СБ-3×95", length=40, link_type="cable")

        _link(db, ps, "OUT-2", yakno6, "IN-1", mark="СИП-3 3×120", length=140, link_type="overhead")
        _link(db, ps, "OUT-3", bkru1, "IN-1", mark="СИП-3 3×120", length=280, link_type="overhead")

        _link(db, bkru1, "OUT-1", pktp_f2, "IN-1", mark="СБ-3×70", length=80, link_type="cable")
        _link(db, bkru1, "OUT-2", ekg_f3, "IN-1", mark="СБ-3×95", length=120, link_type="cable")
        _link(db, bkru1, "OUT-3", pktp_f5, "IN-1", mark="СБ-3×70", length=150, link_type="cable")

        _link(db, ktp4, "OUT-1", load_l1, "IN-1", mark="АВБбШв 4×95", length=60, link_type="cable")
        _link(db, ktp4, "OUT-2", load_l2, "IN-1", mark="АВБбШв 4×70", length=40, link_type="cable")

        print("Демо-схема v2 создана:")
        for label, asset in [
            ("Т-1", t1), ("Т-2", t2), ("ПС", ps),
            ("оп.1", op1), ("оп.2", op2), ("оп.3", op3), ("оп.4", op4),
            ("Реклоузер", recloser), ("КТП №4", ktp4), ("ЯКНО-1/1к", yakno1),
            ("ЯКНО-6", yakno6), ("БКРУ-1", bkru1),
            ("ПКТП-3", pktp_f2), ("ЭКГ-15М", ekg_f3), ("ПКТП-4", pktp_f5),
            ("ПКТП-1", load_l1), ("ПКТП-2", load_l2),
        ]:
            print(f"  {label:12} {asset.code:18} id={asset.id}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
