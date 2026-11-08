"""Сиды библиотеки блоков схемы: ПС 35/6, БКРУ-1, КТП.

Запуск:
    .\\venv\\Scripts\\python seed_schema_blocks.py
"""

from __future__ import annotations

import sys

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import AssetType, SchemaBlock


def node(key, role, label, type_code, x, y, **params):
    return {"key": key, "role": role, "label": label, "type_code": type_code, "x": x, "y": y, "params": params}


SUBSTATION = {
    "nodes": [
        node("in1", "incoming", "ЯКНО-6 №1 (ввод 1)", "cell", 40, 40),
        node("in2", "incoming", "ЯКНО-6 №2 (ввод 2)", "cell", 40, 170),
        node("sv", "section", "ШР СВ-6", "cell", 150, 40),
        node("sec1", "busbar", "I с.ш. 6.3 кВ", "bus_section", 150, 130),
        node("sec2", "busbar", "II с.ш. 6.3 кВ", "bus_section", 150, 230),
        node("tt1", "tt", "ТТ 6 кВ", "cell", 430, 40),
        node("opn1", "opn", "ОПН 6 кВ", "cell", 510, 40),
        node("znv1", "znv", "ЗНВ-6", "cell", 590, 40),
        node("out1", "outgoing", "ф.7-6", "cell", 420, 300, cable="СБ-3×185", power_kw=320),
        node("out2", "outgoing", "ф.16-6", "cell", 520, 300, cable="СБ-3×95", power_kw=150),
        node("out3", "outgoing", "ф.21-6", "cell", 620, 300, cable="СБ-3×95", power_kw=200),
        node("out4", "outgoing", "ф.5-6", "cell", 720, 300, cable="СБ-3×70", power_kw=110),
    ],
    "links": [
        ["in1", "sec1"],
        ["in2", "sec2"],
        ["sv", "sec1"],
        ["sv", "sec2"],
        ["tt1", "sec1"],
        ["opn1", "sec1"],
        ["znv1", "sec1"],
        ["sec1", "out1"],
        ["sec1", "out2"],
        ["sec2", "out3"],
        ["sec2", "out4"],
    ],
    "external_ports": [
        {"code": "IN-1", "label": "Ввод 1", "kind": "in", "voltage_kv": 6},
        {"code": "IN-2", "label": "Ввод 2", "kind": "in", "voltage_kv": 6},
        {"code": "OUT-1", "label": "ф.7-6", "kind": "out", "voltage_kv": 6},
        {"code": "OUT-2", "label": "ф.16-6", "kind": "out", "voltage_kv": 6},
        {"code": "OUT-3", "label": "ф.21-6", "kind": "out", "voltage_kv": 6},
        {"code": "OUT-4", "label": "ф.5-6", "kind": "out", "voltage_kv": 6},
    ],
}

BKRU = {
    "nodes": [
        node("in1", "incoming", "Ячейка №1 (ввод 1)", "cell", 40, 40),
        node("in2", "incoming", "Ячейка №2 (ввод 2)", "cell", 40, 160),
        node("sv", "section", "Ячейка №3 (секционная)", "cell", 140, 40),
        node("bus", "busbar", "Секция БКРУ-1 6 кВ", "bus_section", 140, 140),
        node("out1", "outgoing", "Ячейка №4 (ф.7-6)", "cell", 380, 240, cable="СБ-3×95"),
        node("out2", "outgoing", "Ячейка №5 (ф.16-6)", "cell", 480, 240, cable="СБ-3×95"),
        node("out3", "outgoing", "Ячейка №6 (ф.21-6)", "cell", 580, 240, cable="СБ-3×70"),
    ],
    "links": [
        ["in1", "bus"],
        ["in2", "bus"],
        ["sv", "bus"],
        ["bus", "out1"],
        ["bus", "out2"],
        ["bus", "out3"],
    ],
    "external_ports": [
        {"code": "IN-1", "label": "Ввод 1", "kind": "in", "voltage_kv": 6},
        {"code": "IN-2", "label": "Ввод 2", "kind": "in", "voltage_kv": 6},
        {"code": "OUT-1", "label": "ф.7-6", "kind": "out", "voltage_kv": 6},
        {"code": "OUT-2", "label": "ф.16-6", "kind": "out", "voltage_kv": 6},
        {"code": "OUT-3", "label": "ф.21-6", "kind": "out", "voltage_kv": 6},
    ],
}

KTP = {
    "nodes": [
        node("in1", "incoming", "Ввод 6 кВ", "cell", 40, 40),
        node("tr", "transformer", "ТР 6/0.4 кВ", "cell", 150, 40, power_kva=250),
        node("out1", "outgoing", "Л-1 0.4 кВ", "cell", 320, 200, cable="АВБбШв 4×25"),
        node("out2", "outgoing", "Л-2 0.4 кВ", "cell", 410, 200, cable="АВБбШв 4×16"),
        node("out3", "outgoing", "Л-3 0.4 кВ", "cell", 500, 200, cable="АВБбШв 4×16"),
        node("out4", "outgoing", "Л-4 0.4 кВ", "cell", 590, 200, cable="АВБбШв 4×10"),
    ],
    "links": [["in1", "tr"], ["tr", "out1"], ["tr", "out2"], ["tr", "out3"], ["tr", "out4"]],
    "external_ports": [
        {"code": "IN-1", "label": "Ввод 6 кВ", "kind": "in", "voltage_kv": 6},
        {"code": "OUT-1", "label": "Л-1", "kind": "out", "voltage_kv": 0.4},
        {"code": "OUT-2", "label": "Л-2", "kind": "out", "voltage_kv": 0.4},
        {"code": "OUT-3", "label": "Л-3", "kind": "out", "voltage_kv": 0.4},
        {"code": "OUT-4", "label": "Л-4", "kind": "out", "voltage_kv": 0.4},
    ],
}

BLOCKS = [
    ("substation_35_6", "ПС 35/6 кВ «Карьер»", "substation", "🏭", 10, SUBSTATION),
    ("bkru_standard", "БКРУ-1 (6 ячеек)", "bkru", "🔌", 20, BKRU),
    ("ktp_standard", "КТП 6/0.4 кВ", "ktp", "⚡", 30, KTP),
]


def main() -> int:
    db = SessionLocal()
    try:
        for code, name, type_code, icon, order, template in BLOCKS:
            asset_type = db.scalar(select(AssetType).where(AssetType.code == type_code))
            if asset_type is None:
                print(f"! тип {type_code} не найден — выполните seed_gis.py")
                continue
            block = db.scalar(select(SchemaBlock).where(SchemaBlock.code == code))
            if block is None:
                block = SchemaBlock(id=__import__("uuid").uuid4(), code=code)
                db.add(block)
            block.name = name
            block.icon = icon
            block.block_type = "composite"
            block.asset_type_id = asset_type.id
            block.template_json = template
            block.sort_order = order
            block.is_active = True
        db.commit()
        total = db.query(SchemaBlock).count()
        print(f"Библиотека блоков готова: {total} шаблонов")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
