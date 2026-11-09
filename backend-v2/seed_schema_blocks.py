"""Сиды библиотеки блоков схемы: ПС 35/6, БКРУ-1, КТП, ЯКНО-6, опоры.

Запуск:
    .\\venv\\Scripts\\python seed_schema_blocks.py
"""

from __future__ import annotations

import sys

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import AssetType, SchemaBlock


def node(key, role, label, type_code, x, y, **params):
    return {
        "key": key,
        "role": role,
        "label": label,
        "type_code": type_code,
        "x": x,
        "y": y,
        "params": params,
    }


def ports(*items):
    return [
        {"code": code, "label": label, "kind": kind, "voltage_kv": kv}
        for code, label, kind, kv in items
    ]


# --- ПС 35/6 кВ -------------------------------------------------------------
# Вводы — от трансформаторов Т-1/Т-2 35/6 кВ (КРУ с QF VD4), СВ на границе
# секций (яч. 15/16). На каждом фидере QF + ТТ + ОПН + Wh.
SUBSTATION = {
    "nodes": [
        node("in1", "incoming", "Ввод 1 · Т-1 35/6 кВ · QF VD4 (яч. 2)", "cell", 40, 40),
        node("in2", "incoming", "Ввод 2 · Т-2 35/6 кВ · QF VD4 (яч. 17)", "cell", 40, 300),
        node("sv", "section", "СВ · QF VD4 630A · граница яч. 15/16", "cell", 160, 170),
        node("sec1", "busbar", "I секция шин 6.3 кВ (яч. 1–15)", "bus_section", 160, 110),
        node("sec2", "busbar", "II секция шин 6.3 кВ (яч. 16–30)", "bus_section", 160, 320),
        node("tn1", "tt", "ТН 6 кВ · I секция", "cell", 430, 40),
        node("opn1", "opn", "ОПН 6 кВ · I секция", "cell", 510, 40),
        node("zn1", "znv", "ЗН · I секция", "cell", 590, 40),
        node("opn2", "opn", "ОПН 6 кВ · II секция", "cell", 510, 300),
        node("zn2", "znv", "ЗН · II секция", "cell", 590, 300),
        node(
            "f7", "outgoing",
            "ф.7к · QF VD4 630A · ТТ 600/5 0.5S · Wh (яч. 5)",
            "cell", 420, 400,
            qf="VD4 630A", ct="ТТ 600/5 0.5S/0.5/10P", meter="Wh", opn="ОПН 6 кВ",
            cable="СБ-3×95", cell="яч. 5", power_kw=320,
        ),
        node(
            "f16", "outgoing",
            "ф.16к · QF VD4 630A · ТТ 600/5 · Wh (яч. 9)",
            "cell", 540, 400,
            qf="VD4 630A", ct="ТТ 600/5 0.5S/0.5/10P", meter="Wh", opn="ОПН 6 кВ",
            cable="СИП-3 3×120", cell="яч. 9", power_kw=150,
        ),
        node(
            "f21", "outgoing",
            "ф.21к · QF VD4 630A · ТТ 600/5 · Wh (яч. 12)",
            "cell", 660, 400,
            qf="VD4 630A", ct="ТТ 600/5 0.5S/0.5/10P", meter="Wh", opn="ОПН 6 кВ",
            cable="СИП-3 3×120", cell="яч. 12", power_kw=200,
        ),
    ],
    "links": [
        ["in1", "sec1"], ["in2", "sec2"],
        ["sv", "sec1"], ["sv", "sec2"],
        ["tn1", "sec1"], ["opn1", "sec1"], ["zn1", "sec1"],
        ["opn2", "sec2"], ["zn2", "sec2"],
        ["sec1", "f7"], ["sec1", "f16"], ["sec2", "f21"],
    ],
    "external_ports": ports(
        ("IN-1", "Ввод 1 · Т-1 35/6 кВ", "in", 6),
        ("IN-2", "Ввод 2 · Т-2 35/6 кВ", "in", 6),
        ("OUT-1", "ф.7к", "out", 6),
        ("OUT-2", "ф.16к", "out", 6),
        ("OUT-3", "ф.21к", "out", 6),
    ),
}

# --- БКРУ-1: две секции, СВ, два ввода -------------------------------------
BKRU = {
    "nodes": [
        node("in1", "incoming", "Ввод 1 · QF+ТТ+ОПН (яч. 1) · от ф.21к", "cell", 40, 40),
        node("in2", "incoming", "Ввод 2 · QF+ТТ+ОПН (яч. 2) · от ф.7к / ЯКНО-1/1к", "cell", 40, 300),
        node("sv", "section", "СВ · QF VD4 (яч. 3) · между секциями", "cell", 170, 170),
        node("bus1", "busbar", "Секция I БКРУ-1 6 кВ", "bus_section", 170, 110),
        node("bus2", "busbar", "Секция II БКРУ-1 6 кВ", "bus_section", 170, 320),
        node("tn1", "tt", "ТН 6 кВ · секция I", "cell", 430, 40),
        node("opn1", "opn", "ОПН 6 кВ · секция I", "cell", 520, 40),
        node("opn2", "opn", "ОПН 6 кВ · секция II", "cell", 520, 300),
        node("f2", "outgoing", "ф.2 · QF+ТТ (яч. 4)", "cell", 420, 400,
             qf="QF 630A", ct="ТТ 300/5", cable="СБ-3×95", power_kw=120),
        node("f3", "outgoing", "ф.3 · QF+ТТ (яч. 5)", "cell", 540, 400,
             qf="QF 630A", ct="ТТ 300/5", cable="СБ-3×95", power_kw=150),
        node("f5", "outgoing", "ф.5 · QF+ТТ (яч. 6)", "cell", 660, 400,
             qf="QF 630A", ct="ТТ 300/5", cable="СБ-3×70", power_kw=110),
    ],
    "links": [
        ["in1", "bus1"], ["in2", "bus2"],
        ["sv", "bus1"], ["sv", "bus2"],
        ["tn1", "bus1"], ["opn1", "bus1"], ["opn2", "bus2"],
        ["bus1", "f2"], ["bus1", "f3"], ["bus2", "f5"],
    ],
    "external_ports": ports(
        ("IN-1", "Ввод 1 · от ф.21к", "in", 6),
        ("IN-2", "Ввод 2 · от ф.7к", "in", 6),
        ("OUT-1", "ф.2", "out", 6),
        ("OUT-2", "ф.3", "out", 6),
        ("OUT-3", "ф.5", "out", 6),
    ),
}

# --- КТП 6/0.4 кВ, 400 кВА --------------------------------------------------
KTP = {
    "nodes": [
        node("in1", "incoming", "Ввод 6 кВ · QS+QF+ТТ+ОПН", "cell", 40, 40),
        node("tr", "transformer", "ТР 6/0.4 кВ · 400 кВА", "cell", 170, 40, power_kva=400),
        node("out1", "outgoing", "Л-1 0.4 кВ · QF 250А · ТТ", "cell", 320, 200,
             qf="QF 250А", ct="ТТ 300/5", cable="АВБбШв 4×95", power_kw=90),
        node("out2", "outgoing", "Л-2 0.4 кВ · QF 160А · ТТ", "cell", 420, 200,
             qf="QF 160А", ct="ТТ 200/5", cable="АВБбШв 4×50", power_kw=60),
        node("out3", "outgoing", "Л-3 0.4 кВ · QF 100А · резерв", "cell", 520, 200,
             qf="QF 100А", cable="АВБбШв 4×25", reserve=True),
        node("out4", "outgoing", "Л-4 0.4 кВ · QF 100А · резерв", "cell", 620, 200,
             qf="QF 100А", cable="АВБбШв 4×25", reserve=True),
    ],
    "links": [
        ["in1", "tr"],
        ["tr", "out1"], ["tr", "out2"], ["tr", "out3"], ["tr", "out4"],
    ],
    "external_ports": ports(
        ("IN-1", "Ввод 6 кВ", "in", 6),
        ("OUT-1", "Л-1 0.4 кВ", "out", 0.4),
        ("OUT-2", "Л-2 0.4 кВ", "out", 0.4),
        ("OUT-3", "Л-3 резерв", "out", 0.4),
        ("OUT-4", "Л-4 резерв", "out", 0.4),
    ),
}

# --- ЯКНО-6: шесть ячеек, нагрузки ЭКГ -------------------------------------
YAKNO6 = {
    "nodes": [
        node("in1", "incoming", "Ввод 6 кВ · QF+ТТ", "cell", 40, 40),
        node("c1", "outgoing", "Ячейка №1 · QF+ТТ", "cell", 300, 40, qf="QF 400A"),
        node("c2", "outgoing", "Ячейка №2 · QF+ТТ", "cell", 300, 140, qf="QF 400A"),
        node("c3", "outgoing", "Ячейка №3 · QF+ТТ", "cell", 300, 240, qf="QF 400A"),
        node("c4", "outgoing", "Ячейка №4 · резерв", "cell", 300, 340, reserve=True),
        node("c5", "outgoing", "Ячейка №5 · резерв", "cell", 300, 440, reserve=True),
        node("c6", "outgoing", "Ячейка №6 · резерв", "cell", 300, 540, reserve=True),
        node("l1", "load", "ЭКГ-12К/1 · 960 кВт · Iр=71.7 А", "dmp", 520, 40, power_kw=960),
        node("l2", "load", "ЭКГ-12К/2 · 960 кВт · Iр=71.7 А", "dmp", 520, 140, power_kw=960),
        node("l3", "load", "ЭКГ-15М · 1500 кВт · Iр=112.1 А", "dmp", 520, 240, power_kw=1500),
    ],
    "links": [
        ["in1", "c1"], ["in1", "c2"], ["in1", "c3"],
        ["c1", "l1"], ["c2", "l2"], ["c3", "l3"],
    ],
    "external_ports": ports(("IN-1", "Ввод 6 кВ · ф.16к", "in", 6)),
}

# --- простые блоки ----------------------------------------------------------
SIMPLE_BLOCKS = [
    ("pole", "Опора ВЛ", "pole", "line", "Опора ВЛ", "🪵",
     ports(("IN-1", "ВЛ", "in", 6), ("OUT-1", "ВЛ", "out", 6), ("OUT-2", "отпайка", "out", 6))),
    ("recloser", "Реклоузер", "cell", "incoming", "Реклоузер · QS+QF+ЗН", "🔁",
     ports(("IN-1", "ВЛ", "in", 6), ("OUT-1", "ВЛ", "out", 6))),
    ("yakno1", "ЯКНО-1/1к", "yaku", "incoming", "ЯКНО-1/1к · QF+ТТ", "▭",
     ports(("IN-1", "Ввод", "in", 6), ("OUT-1", "К БКРУ", "out", 6))),
    ("rlnd", "РЛНД", "cell", "section", "РЛНД · разъединитель с ЗН", "⏚",
     ports(("IN-1", "Ввод", "in", 6), ("OUT-1", "Выход", "out", 6))),
    ("source_35", "Т-1 35/6 кВ", "substation", "source", "Т-1 35/6 кВ · 6.3 МВА", "🏭",
     ports(("OUT-1", "6 кВ", "out", 6))),
    ("pktp", "ПКТП 6/0.4 кВ", "ktp", "load", "ПКТП 6/0.4 кВ", "🔻",
     ports(("IN-1", "6 кВ", "in", 6))),
    ("ekg", "ЭКГ", "dmp", "load", "ЭКГ", "⛏",
     ports(("IN-1", "6 кВ", "in", 6))),
    ("pktp_04", "ПКТП 0.4 кВ", "ktp", "load", "ПКТП 0.4 кВ", "🔻",
     ports(("IN-1", "0.4 кВ", "in", 0.4))),
    ("load_04", "Нагрузка 0.4 кВ", "dmp", "load", "Нагрузка 0.4 кВ", "🔌",
     ports(("IN-1", "0.4 кВ", "in", 0.4))),
]

BLOCKS = [
    ("substation_35_6", "ПС 35/6 кВ «Карьер»", "substation", "🏭", 10, SUBSTATION),
    ("bkru_standard", "БКРУ-1", "bkru", "🔌", 20, BKRU),
    ("ktp_standard", "КТП 6/0.4 кВ · 400 кВА", "ktp", "⚡", 30, KTP),
    ("yakno6", "ЯКНО-6 (6 ячеек, ЭКГ)", "yaku", "▭", 25, YAKNO6),
]


def upsert(db, code, name, type_code, icon, order, template, block_type="composite", ports_spec=None):
    asset_type = db.scalar(select(AssetType).where(AssetType.code == type_code))
    if asset_type is None:
        print(f"! тип {type_code} не найден для блока {code}")
        return
    block = db.scalar(select(SchemaBlock).where(SchemaBlock.code == code))
    if block is None:
        block = SchemaBlock(id=__import__("uuid").uuid4(), code=code)
        db.add(block)
    block.name = name
    block.icon = icon
    block.block_type = block_type
    block.asset_type_id = asset_type.id
    block.template_json = template
    block.sort_order = order
    block.is_active = True


def main() -> int:
    db = SessionLocal()
    try:
        for code, name, type_code, icon, order, template in BLOCKS:
            upsert(db, code, name, type_code, icon, order, template)

        for code, name, type_code, role, label, icon, ports_spec in SIMPLE_BLOCKS:
            template_node = node("main", role, label, type_code, 0, 0)
            if code == "ekg":
                template_node["params"] = {"power_kw": 1500}
            upsert(
                db,
                code,
                name,
                type_code,
                icon,
                40,
                {
                    "nodes": [template_node],
                    "links": [],
                    "external_ports": ports_spec,
                },
                block_type="simple",
            )

        db.commit()
        total = db.query(SchemaBlock).count()
        print(f"Библиотека блоков готова: {total} шаблонов")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
