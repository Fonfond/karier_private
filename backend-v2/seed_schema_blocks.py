"""Сиды библиотеки блоков схемы (v3): ПС 35/6, БКРУ-1, КТП 400, ЯКНО-6, ПКТП.

Расчёты: I = P / (√3 · U · cosφ), cosφ = 0.85.
    ПС ф.16к: 3420 кВт → 387 А → СИП-3 3×240, QF 630A, ТТ 600/5
    ПС ф.21к:  874 кВт →  99 А → СИП-3 3×95,  QF 630A, ТТ 300/5
    ПС ф.7к:  1194 кВт → 135 А → СИП-3 3×120, QF 630A, ТТ 300/5
    БКРУ ввод: 874 кВт →  99 А → СБ-3×95, QF 630A, ТТ 300/5 (послеаварийный — ОК)
    КТП 400 кВА: Л-1 160 кВА/231 А, Л-2 100 кВА/144 А, Л-3 63 кВА/91 А

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
    result = []
    for item in items:
        code, label, kind, kv = item[:4]
        reserve = item[4] if len(item) > 4 else False
        result.append({"code": code, "label": label, "kind": kind, "voltage_kv": kv, "reserve": reserve})
    return result


# --- ПС 35/6 кВ -------------------------------------------------------------
SUBSTATION = {
    "nodes": [
        node("in1", "incoming", "Ввод 1 · Т-1 35/6 · QF 1000A + ТТ 800/5 (яч. 2)",
             "cell", 40, 40, qs="QS 1000A", qf="QF 1000A", qf_setting_a=700, ct="ТТ 800/5", opn="ОПН 6 кВ",
             cable="2×СБ-3×185", power_kw=5488, current_a=621),
        node("in2", "incoming", "Ввод 2 · Т-2 35/6 · QF 1000A + ТТ 800/5 (яч. 17)",
             "cell", 40, 300, qs="QS 1000A", qf="QF 1000A", qf_setting_a=700, ct="ТТ 800/5", opn="ОПН 6 кВ",
             cable="2×СБ-3×185", power_kw=5488, current_a=621),
        node("sv", "section", "СВ · QF VD4 630A · граница яч. 15/16", "cell", 160, 170,
             qf="VD4 630A", ct="ТТ 300/5"),
        node("sec1", "busbar", "I секция шин 6.3 кВ (яч. 1–15)", "bus_section", 160, 110),
        node("sec2", "busbar", "II секция шин 6.3 кВ (яч. 16–30)", "bus_section", 160, 320),
        node("tn1", "tn", "ТН 6 кВ · I секция", "cell", 430, 40),
        node("opn1", "opn", "ОПН 6 кВ · I секция", "cell", 510, 40),
        node("zn1", "znv", "ЗН · I секция", "cell", 590, 40),
        node("tn2", "tn", "ТН 6 кВ · II секция", "cell", 430, 300),
        node("opn2", "opn", "ОПН 6 кВ · II секция", "cell", 510, 300),
        node("zn2", "znv", "ЗН · II секция", "cell", 590, 300),
        node("f7", "outgoing", "ф.7к · QF 630A (уст. 160А) · ТТ 300/5 · ОПН · Wh (яч. 7)",
             "cell", 420, 400, qf="QF 630A", qf_setting_a=160, ct="ТТ 300/5", opn="ОПН 6 кВ", meter="Wh",
             cable="СИП-3 3×120", cell="яч. 7", power_kw=1194, current_a=135),
        node("f16", "outgoing", "ф.16к · QF 630A (уст. 410А) · ТТ 600/5 · ОПН · Wh (яч. 16)",
             "cell", 540, 400, qf="QF 630A", qf_setting_a=410, ct="ТТ 600/5", opn="ОПН 6 кВ", meter="Wh",
             cable="2×СИП-3 3×240", cell="яч. 16", power_kw=3420, current_a=387),
        node("f21", "outgoing", "ф.21к · QF 630A (уст. 125А) · ТТ 300/5 · ОПН · Wh (яч. 21)",
             "cell", 660, 400, qf="QF 630A", qf_setting_a=125, ct="ТТ 300/5", opn="ОПН 6 кВ", meter="Wh",
             cable="СИП-3 3×95", cell="яч. 21", power_kw=874, current_a=99),
    ],
    "links": [
        ["in1", "sec1"], ["in2", "sec2"],
        ["sv", "sec1"], ["sv", "sec2"],
        ["tn1", "sec1"], ["opn1", "sec1"], ["zn1", "sec1"],
        ["tn2", "sec2"], ["opn2", "sec2"], ["zn2", "sec2"],
        ["sec1", "f7"], ["sec2", "f16"], ["sec2", "f21"],
    ],
    "external_ports": ports(
        ("IN-1", "Ввод 1 · Т-1 35/6", "in", 6),
        ("IN-2", "Ввод 2 · Т-2 35/6", "in", 6),
        ("OUT-1", "ф.7к", "out", 6),
        ("OUT-2", "ф.16к", "out", 6),
        ("OUT-3", "ф.21к", "out", 6),
    ),
}

# --- БКРУ-1: I секция яч.1–3, СВ яч.4, II секция яч.5–6 ----------------------
BKRU = {
    "nodes": [
        node("in1", "incoming", "Ввод 1 · QS+QF 630A (уст. 160А)+ТТ 300/5+ОПН (яч. 1) · от ф.21к",
             "cell", 40, 40, qs="QS 630A", qf="QF 630A", qf_setting_a=160, ct="ТТ 300/5", opn="ОПН 6 кВ",
             cable="СБ-3×95", power_kw=874, current_a=99),
        node("in2", "incoming", "Ввод 2 · QS+QF 630A (уст. 160А)+ТТ 300/5+ОПН (яч. 6) · от ф.7к / ЯКНО-1/1к",
             "cell", 40, 300, qs="QS 630A", qf="QF 630A", qf_setting_a=160, ct="ТТ 300/5", opn="ОПН 6 кВ",
             cable="СБ-3×95", power_kw=874, current_a=99),
        node("sv", "section", "СВ · QF (яч. 4) · между секциями", "cell", 170, 170, qf="QF 630A"),
        node("bus1", "busbar", "Секция I БКРУ-1 6 кВ (яч. 1–3)", "bus_section", 170, 110),
        node("bus2", "busbar", "Секция II БКРУ-1 6 кВ (яч. 4–6)", "bus_section", 170, 320),
        node("tn1", "tn", "ТН 6 кВ · секция I", "cell", 430, 40),
        node("tn2", "tn", "ТН 6 кВ · секция II", "cell", 430, 300),
        node("opn1", "opn", "ОПН 6 кВ · секция I", "cell", 510, 40),
        node("opn2", "opn", "ОПН 6 кВ · секция II", "cell", 510, 300),
        node("zn1", "znv", "ЗН · секция I", "cell", 590, 40),
        node("zn2", "znv", "ЗН · секция II", "cell", 590, 300),
        node("f2", "outgoing", "ф.2 · QF 250A · ТТ 100/5 (яч. 2)",
             "cell", 420, 400, qf="QF 250A", qf_setting_a=63, ct="ТТ 100/5", opn="ОПН 6 кВ", meter="Wh",
             cable="СБ-3×70", cell="яч. 2", power_kw=320, current_a=36),
        node("f3", "outgoing", "ф.3 · QF 100A · ТТ 50/5 (яч. 3)",
             "cell", 540, 400, qf="QF 100A", qf_setting_a=16, ct="ТТ 50/5", opn="ОПН 6 кВ", meter="Wh",
             cable="СБ-3×70", cell="яч. 3", power_kw=50, current_a=6),
        node("f5", "outgoing", "ф.5 · QF 250A · ТТ 150/5 (яч. 5)",
             "cell", 660, 400, qf="QF 250A", qf_setting_a=100, ct="ТТ 150/5", opn="ОПН 6 кВ", meter="Wh",
             cable="СБ-3×70", cell="яч. 5", power_kw=504, current_a=57),
    ],
    "links": [
        ["in1", "bus1"], ["in2", "bus2"],
        ["sv", "bus1"], ["sv", "bus2"],
        ["tn1", "bus1"], ["opn1", "bus1"], ["zn1", "bus1"],
        ["tn2", "bus2"], ["opn2", "bus2"], ["zn2", "bus2"],
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
        node("in1", "incoming", "Ввод 6 кВ · QS+QF 100A (уст. 80А)+ТТ 100/5+ОПН", "cell", 40, 40,
             qs="QS 100A", qf="QF 100A", qf_setting_a=80, ct="ТТ 100/5", opn="ОПН 6 кВ",
             power_kva=400, current_a=38),
        node("tr", "transformer", "ТР 6/0.4 кВ · 400 кВА", "cell", 170, 40, power_kva=400),
        node("lv", "section", "Ввод 0.4 кВ · QF 630A (уст. 400А) + ТТ 600/5", "cell", 300, 120,
             qf="QF 630A", qf_setting_a=400, ct="ТТ 600/5", meter="Wh"),
        node("out1", "outgoing", "Л-1 0.4 кВ · 130 кВт · QF 250А · ТТ 300/5", "cell", 420, 220,
             qf="QF 250А", qf_setting_a=230, ct="ТТ 300/5", cable="АВБбШв 4×185",
             power_kw=130, power_kva=160, current_a=221, meter="Wh"),
        node("out2", "outgoing", "Л-2 0.4 кВ · 80 кВт · QF 160А · ТТ 200/5", "cell", 520, 220,
             qf="QF 160А", qf_setting_a=145, ct="ТТ 200/5", cable="АВБбШв 4×95",
             power_kw=80, power_kva=100, current_a=136, meter="Wh"),
        node("out3", "outgoing", "Л-3 0.4 кВ · 50 кВт · QF 100А · ТТ 100/5", "cell", 620, 220,
             qf="QF 100А", qf_setting_a=90, ct="ТТ 100/5", cable="АВБбШв 4×35",
             power_kw=50, power_kva=63, current_a=85, meter="Wh"),
        node("out4", "outgoing", "Л-4 0.4 кВ · QF 100А · резерв", "cell", 720, 220,
             qf="QF 100А", qf_setting_a=63, cable="АВБбШв 4×35", reserve=True),
    ],
    "links": [
        ["in1", "tr"], ["tr", "lv"],
        ["lv", "out1"], ["lv", "out2"], ["lv", "out3"], ["lv", "out4"],
    ],
    "external_ports": ports(
        ("IN-1", "Ввод 6 кВ", "in", 6),
        ("OUT-1", "Л-1 0.4 кВ", "out", 0.4),
        ("OUT-2", "Л-2 0.4 кВ", "out", 0.4),
        ("OUT-3", "Л-3 0.4 кВ", "out", 0.4),
        ("OUT-4", "Л-4 резерв", "out", 0.4, True),
    ),
}

# --- ЯКНО-6: 6 ячеек, ЭКГ на ф.16к ------------------------------------------
YAKNO6 = {
    "nodes": [
        node("in1", "incoming", "Ввод 6 кВ · QS+QF 630A (уст. 400А) + ТТ 600/5 + ОПН + ЗН", "cell", 40, 40,
             qs="QS 630A", qf="QF 630A", qf_setting_a=400, ct="ТТ 600/5", opn="ОПН 6 кВ", zn="ЗН"),
        node("c1", "outgoing", "Ячейка №1 · QF 400A · ТТ 300/5 · ЗН", "cell", 300, 40,
             qf="QF 400A", qf_setting_a=125, ct="ТТ 150/5", zn="ЗН", meter="Wh",
             cable="СБ-3×70", power_kw=960, current_a=109),
        node("c2", "outgoing", "Ячейка №2 · QF 400A · ТТ 300/5 · ЗН", "cell", 300, 140,
             qf="QF 400A", ct="ТТ 300/5", zn="ЗН", power_kw=960, current_a=109),
        node("c3", "outgoing", "Ячейка №3 · QF 400A · ТТ 300/5 · ЗН", "cell", 300, 240,
             qf="QF 400A", qf_setting_a=180, ct="ТТ 200/5", zn="ЗН", meter="Wh",
             cable="СБ-3×95", power_kw=1500, current_a=170),
        node("c4", "outgoing", "Ячейка №4 · резерв", "cell", 300, 340, reserve=True),
        node("c5", "outgoing", "Ячейка №5 · резерв", "cell", 300, 440, reserve=True),
        node("c6", "outgoing", "Ячейка №6 · резерв", "cell", 300, 540, reserve=True),
        node("l1", "load", "ЭКГ-12К/1 · 960 кВт · Iр=109 А", "dmp", 520, 40, power_kw=960),
        node("l2", "load", "ЭКГ-12К/2 · 960 кВт · Iр=109 А", "dmp", 520, 140, power_kw=960),
        node("l3", "load", "ЭКГ-15М · 1500 кВт · Iр=170 А", "dmp", 520, 240, power_kw=1500),
    ],
    "links": [
        ["in1", "c1"], ["in1", "c2"], ["in1", "c3"],
        ["c1", "l1"], ["c2", "l2"], ["c3", "l3"],
    ],
    "external_ports": ports(("IN-1", "Ввод 6 кВ · ф.16к", "in", 6)),
}

# --- ПКТП 6/0.4 кВ с 0.4 кВ вводным QF/ТТ и нагрузками ----------------------
def pktp_template(
    *,
    power_kva: int,
    load1_kw: int,
    load2_kw: int,
    in_qf: str,
    in_setting: int,
    in_ct: str,
    lv_qf: str,
    lv_setting: int,
    lv_ct: str,
    l1_qf: str,
    l1_setting: int,
    l1_ct: str,
    l1_cable: str,
    l1_current: int,
    l2_qf: str,
    l2_setting: int,
    l2_ct: str,
    l2_cable: str,
    l2_current: int,
) -> dict:
    return {
        "nodes": [
            node("in1", "incoming", f"Ввод 6 кВ · QS+{in_qf} (уст. {in_setting}А)+{in_ct}+ОПН",
                 "cell", 40, 40, qs="QS", qf=in_qf, qf_setting_a=in_setting, ct=in_ct,
                 opn="ОПН 6 кВ", power_kva=power_kva),
            node("tr", "transformer", f"ТР 6/0.4 кВ · {power_kva} кВА", "cell", 170, 40,
                 power_kva=power_kva),
            node("lv", "section", f"Ввод 0.4 кВ · {lv_qf} (уст. {lv_setting}А) + {lv_ct}",
                 "cell", 300, 120, qf=lv_qf, qf_setting_a=lv_setting, ct=lv_ct, meter="Wh"),
            node("out1", "outgoing",
                 f"Л-1 0.4 кВ · {load1_kw} кВт · {l1_qf} · {l1_ct}", "cell", 420, 220,
                 qf=l1_qf, qf_setting_a=l1_setting, ct=l1_ct, cable=l1_cable,
                 power_kw=load1_kw, current_a=l1_current, meter="Wh"),
            node("load1", "load", f"Буровая установка · {load1_kw} кВт", "dmp", 560, 220,
                 power_kw=load1_kw),
            node("out2", "outgoing",
                 f"Л-2 0.4 кВ · {load2_kw} кВт · {l2_qf} · {l2_ct}", "cell", 420, 340,
                 qf=l2_qf, qf_setting_a=l2_setting, ct=l2_ct, cable=l2_cable,
                 power_kw=load2_kw, current_a=l2_current, meter="Wh"),
            node("load2", "load", f"Насосная · {load2_kw} кВт", "dmp", 560, 340,
                 power_kw=load2_kw),
        ],
        "links": [
            ["in1", "tr"], ["tr", "lv"],
            ["lv", "out1"], ["lv", "out2"],
            ["out1", "load1"], ["out2", "load2"],
        ],
        "external_ports": ports(("IN-1", "Ввод 6 кВ", "in", 6)),
    }


PKTP_63 = pktp_template(
    power_kva=63, load1_kw=20, load2_kw=20,
    in_qf="QF 25A", in_setting=16, in_ct="ТТ 50/5",
    lv_qf="QF 100A", lv_setting=63, lv_ct="ТТ 100/5",
    l1_qf="QF 40A", l1_setting=36, l1_ct="ТТ 50/5", l1_cable="АВБбШв 4×25", l1_current=34,
    l2_qf="QF 40A", l2_setting=36, l2_ct="ТТ 50/5", l2_cable="АВБбШв 4×25", l2_current=34,
)

PKTP_400 = pktp_template(
    power_kva=400, load1_kw=130, load2_kw=80,
    in_qf="QF 100A", in_setting=80, in_ct="ТТ 100/5",
    lv_qf="QF 630A", lv_setting=400, lv_ct="ТТ 600/5",
    l1_qf="QF 250А", l1_setting=230, l1_ct="ТТ 300/5", l1_cable="АВБбШв 4×185", l1_current=221,
    l2_qf="QF 160А", l2_setting=145, l2_ct="ТТ 200/5", l2_cable="АВБбШв 4×95", l2_current=136,
)

PKTP_630 = pktp_template(
    power_kva=630, load1_kw=200, load2_kw=150,
    in_qf="QF 100A", in_setting=80, in_ct="ТТ 100/5",
    lv_qf="QF 1000A", lv_setting=800, lv_ct="ТТ 1000/5",
    l1_qf="QF 400A", l1_setting=350, l1_ct="ТТ 400/5", l1_cable="2×АВБбШв 4×185", l1_current=340,
    l2_qf="QF 320A", l2_setting=270, l2_ct="ТТ 300/5", l2_cable="АВБбШв 4×240", l2_current=255,
)

# --- простые блоки ----------------------------------------------------------
SIMPLE_BLOCKS = [
    ("pole", "Опора ВЛ", "pole", "line", "Опора ВЛ · ЗУ", "🪵",
     ports(("IN-1", "ВЛ", "in", 6), ("OUT-1", "ВЛ", "out", 6), ("OUT-2", "отпайка", "out", 6))),
    ("recloser", "Реклоузер", "cell", "incoming", "Реклоузер · QS+QF+ЗН", "🔁",
     ports(("IN-1", "ВЛ", "in", 6), ("OUT-1", "ВЛ", "out", 6))),
    ("yakno1", "ЯКНО-1/1к", "yaku", "incoming", "ЯКНО-1/1к · QS+QF 630A+ТТ 300/5+ЗН", "▭",
     ports(("IN-1", "Ввод", "in", 6), ("OUT-1", "К БКРУ", "out", 6))),
    ("rlnd", "РЛНД", "cell", "section", "РЛНД · разъединитель с ЗН", "⏚",
     ports(("IN-1", "Ввод", "in", 6), ("OUT-1", "Выход", "out", 6))),
    ("source_35", "Т-1 35/6 кВ", "substation", "source", "Т-1 35/6 кВ · 6.3 МВА", "🏭",
     ports(("OUT-1", "6 кВ", "out", 6))),
    ("load_04", "Нагрузка 0.4 кВ", "dmp", "load", "Нагрузка 0.4 кВ", "🔌",
     ports(("IN-1", "0.4 кВ", "in", 0.4))),
]

BLOCKS = [
    ("substation_35_6", "ПС 35/6 кВ «Карьер»", "substation", "🏭", 10, SUBSTATION),
    ("bkru_standard", "БКРУ-1", "bkru", "🔌", 20, BKRU),
    ("ktp_standard", "КТП 6/0.4 кВ · 400 кВА", "ktp", "⚡", 30, KTP),
    ("yakno6", "ЯКНО-6 (6 ячеек, ЭКГ)", "yaku", "▭", 25, YAKNO6),
    ("pktp_standard", "ПКТП-3 · 400 кВА", "ktp", "🔻", 35, PKTP_400),
    ("pktp_63", "ПКТП-1 · 63 кВА", "ktp", "🔻", 36, PKTP_63),
    ("pktp_630", "ПКТП-2 · 630 кВА", "ktp", "🔻", 37, PKTP_630),
]


def upsert(db, code, name, type_code, icon, order, template, block_type="composite"):
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
            if code == "load_04":
                template_node["params"] = {"power_kw": 50}
            upsert(
                db,
                code,
                name,
                type_code,
                icon,
                40,
                {"nodes": [template_node], "links": [], "external_ports": ports_spec},
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
