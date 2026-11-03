"""Наполнение ГИС-реестра (Спринт 2).

Создаёт: карьер, подложку карты, справочник типов оборудования и 16 объектов
с координатами в метрах — чтобы карта сразу была не пустой.

Запуск:  python seed_gis.py   (из каталога backend-v2)
Повторный запуск безопасен: записи ищутся по коду и обновляются.
"""

from __future__ import annotations

import sys
import uuid

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import Asset, AssetPort, AssetType, MapLayer, Pit

PIT_CODE = "zapadny1"
PIT_NAME = "Западный №1"
MAP_IMAGE = "/karier-map.jpg"
MAP_W_PX, MAP_H_PX = 2048, 1152
METERS_PER_PIXEL = 0.5  # 2048 px → 1024 м, 1152 px → 576 м

# --- типы объектов ---------------------------------------------------------

def port(code: str, name: str, kind: str, voltage: float) -> dict:
    return {"code": code, "name": name, "kind": kind, "voltage_kv": voltage}


def ports_list(specs: list[dict]) -> dict:
    return {
        "ports": [
            {**spec, "sort_order": spec.get("sort_order", index)}
            for index, spec in enumerate(specs)
        ]
    }


def ports(*items: tuple[str, str, str, float]) -> dict:
    return ports_list([port(*item) for item in items])


def out_ports(count: int, voltage: float = 0.4) -> list[tuple[str, str, str, float]]:
    return [(f"OUT-{i}", f"Отходящая {i}", "out", voltage) for i in range(1, count + 1)]


TYPES: list[dict] = [
    {
        "code": "substation",
        "name": "Подстанция 35/6 кВ",
        "category": "source",
        "icon": "🏭",
        "color": "#F5A524",
        "port_template": ports(("OUT-1", "Фидер 1", "out", 6.0), ("OUT-2", "Фидер 2", "out", 6.0),
                               ("OUT-3", "Фидер 3", "out", 6.0), ("OUT-4", "Фидер 4", "out", 6.0)),
        "sort_order": 10,
        "description": "Источник питания карьера",
    },
    {
        "code": "bkru",
        "name": "БКРУ (блок комплектный распределительного устройства)",
        "category": "equipment",
        "icon": "🔌",
        "color": "#4C9AFF",
        "port_template": ports(
            ("IN-1", "Ввод №1", "in", 6.0),
            ("IN-2", "Ввод №2", "in", 6.0),
            ("OUT-1", "Отходящая 1", "out", 6.0),
            ("OUT-2", "Отходящая 2", "out", 6.0),
            ("OUT-3", "Отходящая 3", "out", 6.0),
        ),
        "sort_order": 20,
    },
    {
        "code": "ksr",
        "name": "КСР (комплектное распределительное устройство)",
        "category": "equipment",
        "icon": "🎛",
        "color": "#3D8BFD",
        "port_template": ports(("IN-1", "Ввод", "in", 6.0), ("OUT-1", "Отходящая 1", "out", 0.4),
                               ("OUT-2", "Отходящая 2", "out", 0.4)),
        "sort_order": 30,
    },
    {
        "code": "yaku",
        "name": "ЯКУ (ячейка комплектная наружной установки)",
        "category": "equipment",
        "icon": "🧰",
        "color": "#2FBF71",
        "port_template": ports(("IN-1", "Ввод", "in", 6.0), ("OUT-1", "Отходящая", "out", 6.0)),
        "sort_order": 40,
    },
    {
        "code": "yaku_1t",
        "name": "ЯКУ-1Т",
        "category": "equipment",
        "icon": "🧰",
        "color": "#2FBF71",
        "port_template": ports(("IN-1", "Ввод", "in", 6.0), ("OUT-1", "Отходящая", "out", 6.0)),
        "sort_order": 45,
    },
    {
        "code": "ktp",
        "name": "КТП (комплектная трансформаторная подстанция)",
        "category": "equipment",
        "icon": "⚡",
        "color": "#F2545B",
        "port_template": ports_list([
            {"code": "IN-1", "name": "Ввод 6 кВ", "kind": "in", "voltage_kv": 6.0},
            {"code": "OUT-1", "name": "Отходящая 1 (0,4 кВ)", "kind": "out", "voltage_kv": 0.4},
            {"code": "OUT-2", "name": "Отходящая 2 (0,4 кВ)", "kind": "out", "voltage_kv": 0.4},
            {"code": "OUT-3", "name": "Отходящая 3 (0,4 кВ)", "kind": "out", "voltage_kv": 0.4},
            {"code": "OUT-4", "name": "Отходящая 4 (0,4 кВ)", "kind": "out", "voltage_kv": 0.4},
        ]),
        "attr_schema": {
            "power_kva": {"type": "number"},
            "voltage_in_kv": {"type": "number"},
            "voltage_out_kv": {"type": "number"},
        },
        "sort_order": 50,
    },
    {
        "code": "dmo",
        "name": "ДМО (дробильно-сортировочный комплекс мобильный)",
        "category": "mobile",
        "icon": "🏗",
        "color": "#A56BFF",
        "port_template": ports(("IN-1", "Ввод 0,4 кВ", "in", 0.4), ("OUT-1", "Привод 1", "out", 0.4),
                               ("OUT-2", "Привод 2", "out", 0.4)),
        "attr_schema": {"power_kw": {"type": "number"}, "drive_type": {"type": "string"}},
        "required_attrs": ["power_kw"],
        "is_mobile_default": True,
        "sort_order": 60,
    },
    {
        "code": "dmp",
        "name": "ДМП (дробильная мобильная передвижная установка)",
        "category": "mobile",
        "icon": "⛏",
        "color": "#A56BFF",
        "port_template": ports(("IN-1", "Ввод 0,4 кВ", "in", 0.4), ("OUT-1", "Привод", "out", 0.4)),
        "attr_schema": {"power_kw": {"type": "number"}, "drive_type": {"type": "string"}},
        "required_attrs": ["power_kw"],
        "is_mobile_default": True,
        "sort_order": 65,
    },
    {
        "code": "bmp",
        "name": "БМП (буровой мобильный комплекс)",
        "category": "mobile",
        "icon": "🛠",
        "color": "#A56BFF",
        "port_template": ports(("IN-1", "Ввод 0,4 кВ", "in", 0.4), ("OUT-1", "Привод 1", "out", 0.4),
                               ("OUT-2", "Привод 2", "out", 0.4)),
        "attr_schema": {"power_kw": {"type": "number"}, "drive_type": {"type": "string"}},
        "required_attrs": ["power_kw"],
        "is_mobile_default": True,
        "sort_order": 70,
    },
    {
        "code": "gen_diesel",
        "name": "ДГУ (дизель-генератор)",
        "category": "source",
        "icon": "🔋",
        "color": "#F5A524",
        "port_template": ports(("OUT-1", "Выход 0,4 кВ", "out", 0.4)),
        "attr_schema": {"power_kw": {"type": "number"}, "fuel_type": {"type": "string"}},
        "sort_order": 80,
    },
    {
        "code": "gen_petrol",
        "name": "Генератор бензиновый",
        "category": "source",
        "icon": "⛽",
        "color": "#F5A524",
        "port_template": ports(("OUT-1", "Выход 0,4 кВ", "out", 0.4)),
        "attr_schema": {"power_kw": {"type": "number"}, "fuel_type": {"type": "string"}},
        "sort_order": 85,
    },
    {
        "code": "ekg",
        "name": "ЭКГ (экскаватор)",
        "category": "equipment",
        "icon": "🚜",
        "color": "#2FBF71",
        "port_template": ports(("IN-1", "Ввод 6 кВ", "in", 6.0)),
        "attr_schema": {"bucket_m3": {"type": "number"}, "drive_type": {"type": "string"}},
        "sort_order": 90,
    },
    {
        "code": "cuckoo",
        "name": "Кукушка (передвижной ДГУ)",
        "category": "mobile",
        "icon": "🚚",
        "color": "#F5A524",
        "port_template": ports(("OUT-1", "Выход 0,4 кВ", "out", 0.4)),
        "attr_schema": {"power_kw": {"type": "number"}, "fuel_type": {"type": "string"}},
        "is_mobile_default": True,
        "sort_order": 95,
    },
    {
        "code": "mast",
        "name": "Мачта освещения",
        "category": "lighting",
        "icon": "💡",
        "color": "#E6EDF3",
        "port_template": ports(("IN-1", "Ввод 0,4 кВ", "in", 0.4)),
        "attr_schema": {"power_kw": {"type": "number"}},
        "sort_order": 100,
    },
    {
        "code": "pump",
        "name": "Насос",
        "category": "aux",
        "icon": "💧",
        "color": "#4C9AFF",
        "port_template": ports(("IN-1", "Ввод 0,4 кВ", "in", 0.4)),
        "attr_schema": {"power_kw": {"type": "number"}},
        "sort_order": 110,
    },
]

# --- объекты ---------------------------------------------------------------


def asset(code, name, type_code, x, y, *, status="on", parent=None, attrs=None, location=None,
          mobile=None):
    return {
        "code": code,
        "name": name,
        "type_code": type_code,
        "x": x,
        "y": y,
        "status": status,
        "parent": parent,
        "attrs": attrs or {},
        "location": location,
        "mobile": mobile,
    }


ASSETS = [
    asset("PS-356", "ПС-35/6 кВ «Карьер»", "substation", 300, 380,
          attrs={"power_kva": 16000}, location="Северный борт, у въезда"),
    asset("BKRU-1", "БКРУ-1", "bkru", 420, 330, parent="PS-356",
          attrs={"section_breaker": True}, location="Гор. +120"),
    asset("KTP-14", "КТП-14", "ktp", 560, 300, parent="BKRU-1",
          attrs={"power_kva": 250, "voltage_in_kv": 6, "voltage_out_kv": 0.4},
          location="Гор. +120, борт северный"),
    asset("KTP-15", "КТП-15", "ktp", 640, 360, parent="BKRU-1", status="off",
          attrs={"power_kva": 400, "voltage_in_kv": 6, "voltage_out_kv": 0.4},
          location="Гор. +105"),
    asset("KS-3", "КСР-3", "ksr", 520, 430, parent="BKRU-1",
          attrs={"power_kw": 160}, location="Гор. +105, восточный борт"),
    asset("YAKU-3", "ЯКУ-3", "yaku", 700, 250, parent="BKRU-1",
          attrs={"power_kw": 100}, location="Гор. +135"),
    asset("YAKU1T-7", "ЯКУ-1Т-7", "yaku_1t", 760, 320, parent="BKRU-1",
          attrs={"power_kw": 100}, location="Гор. +120"),
    asset("DMO-1", "ДМО-1 (дробильный комплекс)", "dmo", 620, 470, parent="KTP-14",
          attrs={"power_kw": 250, "drive_type": "электрика"}, location="Гор. +90"),
    asset("DMP-2", "ДМП-2", "dmp", 700, 500, parent="KTP-15", status="off",
          attrs={"power_kw": 160, "drive_type": "электрика"}, location="Гор. +90, отвал"),
    asset("BMP-1", "БМП-1 (буровой комплекс)", "bmp", 810, 430, parent="KS-3",
          attrs={"power_kw": 90, "drive_type": "электрика"}, location="Гор. +75, борт восточный"),
    asset("DGU-5", "ДГУ-5", "gen_diesel", 350, 250, status="standby",
          attrs={"power_kw": 100, "fuel_type": "дизель"}, location="Склад ГСМ"),
    asset("GBP-2", "Генератор бензиновый ГБ-2", "gen_petrol", 300, 200, status="off",
          attrs={"power_kw": 5, "fuel_type": "бензин"}, location="Бытовка ИТР"),
    asset("EKG-10", "ЭКГ-10", "ekg", 480, 200, parent="KTP-14",
          attrs={"bucket_m3": 12, "drive_type": "электрика"}, location="Забой №3"),
    asset("EKG-12", "ЭКГ-12", "ekg", 860, 240, parent="YAKU1T-7", status="maintenance",
          attrs={"bucket_m3": 15, "drive_type": "электрика"}, location="Забой №7"),
    asset("CUCKOO-7", "Кукушка-7 (ДГУ передвижной)", "cuckoo", 900, 500, status="on",
          attrs={"power_kw": 30, "fuel_type": "дизель"}, location="Гор. +75, насосная"),
    asset("MAST-4", "Мачта освещения М-4", "mast", 250, 480, parent="KTP-14",
          attrs={"power_kw": 4}, location="Съезд с гор. +120"),
]


# --- наполнение ------------------------------------------------------------


def ensure_pit(db) -> Pit:
    pit = db.scalar(select(Pit).where(Pit.code == PIT_CODE))
    if pit is None:
        pit = Pit(id=uuid.uuid4(), code=PIT_CODE, name=PIT_NAME)
        db.add(pit)
        db.commit()
    return pit


def ensure_layer(db, pit: Pit) -> MapLayer:
    layer = db.scalar(select(MapLayer).where(MapLayer.pit_id == pit.id, MapLayer.name == "Схема горных работ"))
    if layer is None:
        layer = MapLayer(
            id=uuid.uuid4(),
            pit_id=pit.id,
            name="Схема горных работ",
            kind="raster",
            image_url=MAP_IMAGE,
            width_px=MAP_W_PX,
            height_px=MAP_H_PX,
            meters_per_pixel=METERS_PER_PIXEL,
            min_zoom=-2,
            max_zoom=3,
            is_active=True,
        )
        db.add(layer)
        db.commit()
    return layer


def ensure_types(db) -> dict[str, AssetType]:
    result: dict[str, AssetType] = {}
    for spec in TYPES:
        asset_type = db.scalar(select(AssetType).where(AssetType.code == spec["code"]))
        if asset_type is None:
            asset_type = AssetType(
                id=uuid.uuid4(),
                code=spec["code"],
                name=spec["name"],
                category=spec["category"],
                icon=spec["icon"],
                color=spec["color"],
                port_template=spec.get("port_template", {"ports": []}),
                attr_schema=spec.get("attr_schema", {}),
                required_attrs=spec.get("required_attrs", []),
                is_mobile_default=spec.get("is_mobile_default", False),
                sort_order=spec.get("sort_order", 100),
                description=spec.get("description"),
                is_active=True,
            )
            db.add(asset_type)
            db.flush()
        else:
            # оформление и схема атрибутов обновляются, шаблон портов не трогаем:
            # у существующих объектов порты уже материализованы
            asset_type.name = spec["name"]
            asset_type.icon = spec["icon"]
            asset_type.color = spec["color"]
            asset_type.sort_order = spec.get("sort_order", 100)
            asset_type.attr_schema = spec.get("attr_schema", {})
            asset_type.required_attrs = spec.get("required_attrs", [])
        result[spec["code"]] = asset_type
    db.commit()
    return result


def ensure_assets(db, pit: Pit, types: dict[str, AssetType]) -> None:
    created: dict[str, Asset] = {}
    # сначала объекты без родителей, затем остальные — чтобы находить parent по коду
    for spec in ASSETS:
        asset_type = types[spec["type_code"]]
        row = db.scalar(select(Asset).where(Asset.pit_id == pit.id, Asset.code == spec["code"]))
        if row is None:
            row = Asset(
                id=uuid.uuid4(),
                pit_id=pit.id,
                asset_type_id=asset_type.id,
                code=spec["code"],
                name=spec["name"],
                status=spec["status"],
                lifecycle="installed",
                is_mobile=asset_type.is_mobile_default if spec["mobile"] is None else spec["mobile"],
                x=spec["x"],
                y=spec["y"],
                location_text=spec["location"],
                attrs=spec["attrs"],
                version=1,
            )
            db.add(row)
            db.flush()
            template = asset_type.port_template or {}
            for index, port in enumerate(template.get("ports", [])):
                db.add(
                    AssetPort(
                        id=uuid.uuid4(),
                        asset_id=row.id,
                        code=port["code"],
                        name=port["name"],
                        kind=port["kind"],
                        nominal_voltage_kv=port.get("voltage_kv"),
                        sort_order=port.get("sort_order", index),
                    )
                )
        created[spec["code"]] = row

    for spec in ASSETS:
        if not spec["parent"]:
            continue
        child = created[spec["code"]]
        parent = created.get(spec["parent"])
        if parent is not None and child.parent_asset_id != parent.id:
            child.parent_asset_id = parent.id
    db.commit()


def main() -> int:
    db = SessionLocal()
    try:
        pit = ensure_pit(db)
        layer = ensure_layer(db, pit)
        types = ensure_types(db)
        ensure_assets(db, pit, types)

        assets_count = db.scalar(
            select(func.count()).select_from(Asset).where(Asset.deleted_at.is_(None))
        )
        print("\n" + "=" * 64)
        print("  ГИС-реестр наполнен")
        print("=" * 64)
        print(f"  карьер      : {pit.name} ({pit.code})")
        print(f"  подложка    : {layer.image_url}, {layer.width_px}×{layer.height_px} px, "
              f"{float(layer.meters_per_pixel)} м/px → "
              f"{layer.width_px * float(layer.meters_per_pixel):.0f}×"
              f"{layer.height_px * float(layer.meters_per_pixel):.0f} м")
        print(f"  типов       : {len(types)}")
        print(f"  объектов    : {assets_count}")
        print("=" * 64 + "\n")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
