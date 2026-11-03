"""Топология Спринта 3: секции шин, ячейки, опоры, линии и связи.

Запуск после seed_gis.py:  python seed_topology.py
Повторный запуск безопасен: объекты ищутся по коду, связи — по паре портов.
"""

from __future__ import annotations

import sys
import uuid

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Asset, AssetPort, AssetType, Line, Link, Pit


def ports_list(items: list[tuple[str, str, str, float | None]]) -> dict:
    return {
        "ports": [
            {"code": code, "name": name, "kind": kind, "voltage_kv": voltage, "sort_order": i}
            for i, (code, name, kind, voltage) in enumerate(items)
        ]
    }


NEW_TYPES = [
    {
        "code": "bus_section",
        "name": "Секция шин",
        "category": "equipment",
        "icon": "▤",
        "color": "#4C9AFF",
        "port_template": ports_list(
            [
                ("IN-1", "Ввод от источника", "in", 6.0),
                ("OUT-1", "Отходящая 1", "out", 6.0),
                ("OUT-2", "Отходящая 2", "out", 6.0),
                ("OUT-3", "Отходящая 3", "out", 6.0),
                ("IO-1", "Перемычка", "io", 6.0),
            ]
        ),
        "sort_order": 15,
        "description": "Секция сборных шин подстанции",
    },
    {
        "code": "cell",
        "name": "Ячейка (КРУ/КСО)",
        "category": "equipment",
        "icon": "▭",
        "color": "#2FBF71",
        "port_template": ports_list(
            [
                ("IN-1", "Ввод (шины)", "in", 6.0),
                ("OUT-1", "Отходящая", "out", 6.0),
            ]
        ),
        "sort_order": 25,
        "description": "Ячейка распределительного устройства с выключателем",
    },
    {
        "code": "pole",
        "name": "Опора ВЛ",
        "category": "pole",
        "icon": "🗼",
        "color": "#9FB0C0",
        "port_template": ports_list(
            [
                ("IN-1", "Провод (вход)", "io", None),
                ("OUT-1", "Провод (выход)", "io", None),
            ]
        ),
        "sort_order": 120,
        "description": "Опора воздушной линии: пролёты соединяются в цепочку",
    },
]

# (код, имя, тип, x, y, статус, родитель)
HIERARCHY = [
    ("PS-356-SEC1", "Секция шин 1 (ПС-35/6)", "bus_section", 300, 380, "on", "PS-356"),
    ("PS-356-SEC2", "Секция шин 2 (ПС-35/6)", "bus_section", 300, 420, "on", "PS-356"),
    ("BKRU1-IN1", "Ввод №1 (БКРУ-1)", "cell", 420, 310, "on", "BKRU-1"),
    ("BKRU1-IN2", "Ввод №2 (БКРУ-1)", "cell", 420, 350, "off", "BKRU-1"),
    ("BKRU1-SEC", "Секционный (БКРУ-1)", "cell", 420, 330, "off", "BKRU-1"),
    ("BKRU1-OUT1", "Отходящая 1 (БКРУ-1)", "cell", 470, 300, "on", "BKRU-1"),
    ("BKRU1-OUT2", "Отходящая 2 (БКРУ-1)", "cell", 470, 340, "on", "BKRU-1"),
    ("BKRU1-OUT3", "Отходящая 3 (БКРУ-1)", "cell", 470, 380, "on", "BKRU-1"),
    ("POLE-1", "Опора ВЛ-1", "pole", 330, 300, "on", None),
    ("POLE-2", "Опора ВЛ-2", "pole", 380, 280, "on", None),
    ("POLE-3", "Опора ВЛ-3", "pole", 430, 260, "on", None),
]

LINES = [
    ("ф.21К", "Фидер 21К (ПС → БКРУ-1)", "cable", 6.0, "СБ-3×95", 320),
    ("ф.7К", "Фидер 7К (ПС → БКРУ-1, резерв)", "cable", 6.0, "СБ-3×95", 310),
    ("ВЛ-6кВ-4", "Воздушная линия 6 кВ №4", "overhead", 6.0, "АС-70", 180),
]

# (from: код объекта, порт, to: код объекта, порт, тип, роль, состояние, линия, марка, длина)
LINKS = [
    ("PS-356", "OUT-1", "PS-356-SEC1", "IN-1", "cable", "main", "connected", "ф.21К", "СБ-3×95", 40),
    ("PS-356", "OUT-2", "PS-356-SEC2", "IN-1", "cable", "main", "connected", "ф.7К", "СБ-3×95", 40),
    ("PS-356-SEC1", "OUT-1", "BKRU1-IN1", "IN-1", "cable", "main", "connected", "ф.21К", "СБ-3×95", 260),
    ("PS-356-SEC2", "OUT-1", "BKRU1-IN2", "IN-1", "cable", "reserve", "connected", "ф.7К", "СБ-3×95", 250),
    # перемычка между секциями: позволяет запитать вторую секцию при аварии
    ("PS-356-SEC1", "IO-1", "PS-356-SEC2", "IO-1", "jumper", "reserve", "open", None, "Шина-перемычка", 12),
    ("BKRU1-IN1", "OUT-1", "BKRU-1", "IN-1", "busbar", "main", "connected", None, "Шина БКРУ", 3),
    ("BKRU1-IN2", "OUT-1", "BKRU-1", "IN-2", "busbar", "reserve", "connected", None, "Шина БКРУ", 3),
    ("BKRU-1", "OUT-1", "BKRU1-OUT1", "IN-1", "busbar", "main", "connected", None, "Шина БКРУ", 3),
    ("BKRU-1", "OUT-2", "BKRU1-OUT2", "IN-1", "busbar", "main", "connected", None, "Шина БКРУ", 3),
    ("BKRU-1", "OUT-3", "BKRU1-OUT3", "IN-1", "busbar", "main", "connected", None, "Шина БКРУ", 3),
    ("BKRU1-OUT1", "OUT-1", "KTP-14", "IN-1", "cable", "main", "connected", None, "СБ-3×50", 180),
    ("BKRU1-OUT2", "OUT-1", "KTP-15", "IN-1", "cable", "main", "connected", None, "СБ-3×50", 210),
    ("BKRU1-OUT3", "OUT-1", "KS-3", "IN-1", "cable", "main", "connected", None, "СБ-3×35", 150),
    ("KTP-14", "OUT-1", "DMO-1", "IN-1", "cable", "main", "connected", None, "КГ-3×25", 60),
    ("KTP-14", "OUT-2", "EKG-10", "IN-1", "cable", "main", "connected", None, "КГ-3×35", 90),
    ("KTP-14", "OUT-3", "MAST-4", "IN-1", "cable", "main", "connected", None, "КГ-3×16", 45),
    ("KTP-15", "OUT-1", "DMP-2", "IN-1", "cable", "main", "connected", None, "КГ-3×25", 70),
    ("KS-3", "OUT-1", "BMP-1", "IN-1", "cable", "main", "connected", None, "КГ-3×25", 80),
    ("KS-3", "OUT-2", "YAKU-3", "IN-1", "cable", "main", "connected", None, "КГ-3×25", 65),
    ("YAKU-3", "OUT-1", "YAKU1T-7", "IN-1", "cable", "main", "connected", None, "КГ-3×25", 55),
    ("KTP-15", "OUT-2", "EKG-12", "IN-1", "cable", "main", "connected", None, "КГ-3×35", 110),
    # резервный источник: ДГУ 0,4 кВ питает мачту освещения (связь разомкнута)
    ("DGU-5", "OUT-1", "MAST-4", "IN-1", "cable", "backup", "open", None, "КГ-3×16", 60),
    # воздушная линия по опорам
    ("PS-356", "OUT-4", "POLE-1", "IN-1", "overhead", "main", "connected", "ВЛ-6кВ-4", "АС-70", 50),
    ("POLE-1", "OUT-1", "POLE-2", "IN-1", "overhead", "main", "connected", "ВЛ-6кВ-4", "АС-70", 55),
    ("POLE-2", "OUT-1", "POLE-3", "IN-1", "overhead", "main", "connected", "ВЛ-6кВ-4", "АС-70", 48),
]


def ensure_types(db) -> dict[str, AssetType]:
    result = {t.code: t for t in db.scalars(select(AssetType)).all()}
    for spec in NEW_TYPES:
        existing = result.get(spec["code"])
        if existing is None:
            existing = AssetType(
                id=uuid.uuid4(),
                code=spec["code"],
                name=spec["name"],
                category=spec["category"],
                icon=spec["icon"],
                color=spec["color"],
                port_template=spec["port_template"],
                attr_schema={},
                required_attrs=[],
                is_mobile_default=False,
                sort_order=spec["sort_order"],
                description=spec.get("description"),
                is_active=True,
            )
            db.add(existing)
            db.flush()
            result[spec["code"]] = existing
        else:
            existing.name = spec["name"]
            existing.icon = spec["icon"]
            existing.color = spec["color"]
    db.commit()
    return result


def ensure_assets(db, pit: Pit, types: dict[str, AssetType]) -> dict[str, Asset]:
    assets = {
        a.code: a
        for a in db.scalars(
            select(Asset).where(Asset.pit_id == pit.id, Asset.deleted_at.is_(None))
        ).all()
    }
    for code, name, type_code, x, y, status, parent_code in HIERARCHY:
        if code in assets:
            continue
        asset_type = types[type_code]
        parent = assets.get(parent_code) if parent_code else None
        asset = Asset(
            id=uuid.uuid4(),
            pit_id=pit.id,
            asset_type_id=asset_type.id,
            parent_asset_id=parent.id if parent else None,
            code=code,
            name=name,
            status=status,
            lifecycle="installed",
            is_mobile=False,
            x=x,
            y=y,
            attrs={},
            version=1,
        )
        db.add(asset)
        db.flush()
        for index, port in enumerate(asset_type.port_template.get("ports", [])):
            db.add(
                AssetPort(
                    id=uuid.uuid4(),
                    asset_id=asset.id,
                    code=port["code"],
                    name=port["name"],
                    kind=port["kind"],
                    nominal_voltage_kv=port.get("voltage_kv"),
                    sort_order=port.get("sort_order", index),
                )
            )
        assets[code] = asset
    db.commit()
    return assets


def ensure_lines(db, pit: Pit) -> dict[str, Line]:
    result = {
        line.code: line
        for line in db.scalars(select(Line).where(Line.pit_id == pit.id)).all()
    }
    for code, name, kind, voltage, mark, length in LINES:
        if code in result:
            continue
        line = Line(
            id=uuid.uuid4(),
            pit_id=pit.id,
            code=code,
            name=name,
            kind=kind,
            voltage_kv=voltage,
            conductor_mark=mark,
            length_m=length,
            state="energized",
            status="in_service",
        )
        db.add(line)
        db.flush()
        result[code] = line
    db.commit()
    return result


def _port(db, asset: Asset, code: str) -> AssetPort:
    port = db.scalar(
        select(AssetPort).where(AssetPort.asset_id == asset.id, AssetPort.code == code)
    )
    if port is None:
        raise RuntimeError(f"У объекта {asset.code} нет порта {code}")
    return port


def ensure_voltage_consistency(db, assets: dict[str, Asset], types: dict[str, AssetType]) -> None:
    """Привести напряжения в данных к физике: ЭКГ — 0,4 кВ, у КСР есть транзит 6 кВ."""
    ekg_type = types.get("ekg")
    if ekg_type is not None:
        ekg_type.port_template = ports_list([("IN-1", "Ввод 0,4 кВ", "in", 0.4)])

    for code in ("EKG-10", "EKG-12"):
        asset = assets.get(code)
        if asset is not None:
            _port(db, asset, "IN-1").nominal_voltage_kv = 0.4

    ksr = assets.get("KS-3")
    if ksr is not None:
        _port(db, ksr, "OUT-2").nominal_voltage_kv = 6.0

    # старая связь ЯКУ-1Т → ЭКГ-12 больше не нужна (ЭКГ запитана от КТП-15)
    from app.models import Link

    def _delete_link(from_code: str, to_code: str) -> None:
        row = db.scalar(
            select(Link)
            .join(AssetPort, Link.from_port_id == AssetPort.id)
            .join(Asset, AssetPort.asset_id == Asset.id)
            .where(Asset.code == from_code, Link.deleted_at.is_(None))
        )
        # ищем точную пару по коду получателя
        candidates = db.scalars(
            select(Link)
            .join(AssetPort, Link.from_port_id == AssetPort.id)
            .where(Link.deleted_at.is_(None), AssetPort.asset_id == assets[from_code].id)
        ).all()
        for link in candidates:
            target_port = db.get(AssetPort, link.to_port_id)
            target_asset = db.get(Asset, target_port.asset_id) if target_port else None
            if target_asset is not None and target_asset.code == to_code:
                db.delete(link)

    _delete_link("YAKU1T-7", "EKG-12")
    _delete_link("DGU-5", "KS-3")
    db.commit()


def ensure_links(db, pit: Pit, assets: dict[str, Asset], lines: dict[str, Line]) -> int:
    created = 0
    for from_code, from_port, to_code, to_port, kind, role, state, line_code, mark, length in LINKS:
        from_asset = assets.get(from_code)
        to_asset = assets.get(to_code)
        if from_asset is None or to_asset is None:
            continue
        source_port = _port(db, from_asset, from_port)
        target_port = _port(db, to_asset, to_port)
        existing = db.scalar(
            select(Link).where(
                Link.from_port_id == source_port.id,
                Link.to_port_id == target_port.id,
                Link.deleted_at.is_(None),
            )
        )
        if existing is not None:
            continue
        db.add(
            Link(
                id=uuid.uuid4(),
                pit_id=pit.id,
                from_port_id=source_port.id,
                to_port_id=target_port.id,
                line_id=lines[line_code].id if line_code else None,
                link_type=kind,
                feed_role=role,
                state=state,
                cable_mark=mark,
                length_m=length,
                geometry=[],
                attrs={},
                version=1,
            )
        )
        created += 1
    db.commit()
    return created


def main() -> int:
    db = SessionLocal()
    try:
        pit = db.scalar(select(Pit).where(Pit.code == "zapadny1"))
        if pit is None:
            print("Сначала выполните seed_gis.py")
            return 1
        types = ensure_types(db)
        assets = ensure_assets(db, pit, types)
        ensure_voltage_consistency(db, assets, types)
        lines = ensure_lines(db, pit)
        created = ensure_links(db, pit, assets, lines)
        print("\n" + "=" * 60)
        print("  Топология Спринта 3 подготовлена")
        print("=" * 60)
        print(f"  объектов всего : {len(assets)}")
        print(f"  линий          : {len(lines)}")
        print(f"  новых связей   : {created}")
        print("=" * 60 + "\n")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
