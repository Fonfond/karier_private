"""Генерация JSON-описания демо-схемы (karier.sketch/v1, version 3.0)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Asset, Link

DEMO = "sketch_v3"
VERSION = "3.0"

LAYOUT = {
    "Т-1 35/6 кВ": (30, 30),
    "Т-2 35/6 кВ": (30, 150),
    "ПС 35/6 кВ «Карьер»": (210, 30),
    "оп.1": (420, 20),
    "оп.2": (520, 20),
    "оп.3": (620, 20),
    "оп.4": (720, 20),
    "Реклоузер": (820, 20),
    "КТП №4 · 400 кВА": (930, 20),
    "ЯКНО-1/1к": (720, 130),
    "ЯКНО-6": (210, 320),
    "БКРУ-1": (470, 320),
    "ПКТП-3 · 400 кВА": (780, 300),
    "ПКТП-1 · 63 кВА": (780, 380),
    "ПКТП-2 · 630 кВА": (780, 460),
    "Буровая установка · 130 кВт": (960, 170),
    "Насосная · 80 кВт": (960, 240),
    "Освещение · 50 кВт": (960, 310),
}

RESERVE_MARKERS = ("резерв", "отпайка")


def is_reserve(label: str) -> bool:
    return any(marker in (label or "").lower() for marker in RESERVE_MARKERS)


def block_code(asset: Asset, children: list[Asset]) -> str | None:
    stored = (asset.attrs or {}).get("block_code")
    if stored:
        return stored
    simple = (asset.attrs or {}).get("simple_block")
    if simple:
        return simple
    roles = {child.schema_role for child in children}
    if "transformer" in roles:
        return "ktp_standard"
    if "load" in roles and "incoming" in roles and "outgoing" in roles:
        return "yakno6"
    if sum(1 for c in children if c.schema_role == "busbar") >= 2:
        return "substation_35_6"
    if "busbar" in roles:
        return "bkru_standard"
    return None


def main() -> int:
    db = SessionLocal()
    assets = [
        asset
        for asset in db.scalars(
            select(Asset).where(Asset.schema_role == "block", Asset.deleted_at.is_(None))
        ).all()
        if (asset.attrs or {}).get("demo") == DEMO
    ]
    if not assets:
        print("Нет демо-схемы sketch_v3 — выполните seed_demo_sketch.py")
        return 1

    order = {name: index for index, name in enumerate(LAYOUT)}
    assets.sort(key=lambda a: (order.get(a.name, 999), float(a.schema_x or 0)))

    blocks = []
    by_asset = {}
    for index, asset in enumerate(assets):
        bid = f"b{index}"
        by_asset[asset.id] = bid
        children = list(
            db.scalars(
                select(Asset).where(
                    Asset.schema_block_id == asset.id, Asset.deleted_at.is_(None)
                )
            ).all()
        )
        params: dict = {"label": asset.name}
        if (asset.attrs or {}).get("pole_no"):
            params["pole_no"] = asset.attrs["pole_no"]

        if children:
            params["sections"] = [c.name for c in children if c.schema_role == "busbar"]
            params["incoming"] = [
                {"name": c.name, "params": c.attrs or {}}
                for c in children
                if c.schema_role == "incoming"
            ]
            params["section_breaker"] = next(
                (
                    {"name": c.name, "params": c.attrs or {}}
                    for c in children
                    if c.schema_role == "section"
                ),
                None,
            )
            params["feeders"] = [
                {"name": c.name, "params": c.attrs or {}}
                for c in children
                if c.schema_role == "outgoing"
            ]
            params["equipment"] = [
                {"name": c.name, "role": c.schema_role, "params": c.attrs or {}}
                for c in children
                if c.schema_role in ("tn", "tt", "opn", "znv", "transformer", "load")
            ]

        blocks.append(
            {
                "id": bid,
                "block": block_code(asset, children),
                "title": asset.name,
                "position": {
                    "x": float(LAYOUT.get(asset.name, (asset.schema_x or 40, asset.schema_y or 40))[0]),
                    "y": float(LAYOUT.get(asset.name, (asset.schema_x or 40, asset.schema_y or 40))[1]),
                },
                "params": params,
                "ports": [
                    {
                        "code": port.code,
                        "kind": port.kind,
                        "label": port.name,
                        "voltage_kv": float(port.nominal_voltage_kv)
                        if port.nominal_voltage_kv is not None
                        else None,
                        "reserve": is_reserve(port.name),
                    }
                    for port in sorted(asset.ports, key=lambda p: p.code)
                ],
            }
        )

    links = []
    connected: set[tuple[str, str]] = set()
    for link in db.scalars(select(Link)).all():
        source = next(
            (a for a in assets if any(p.id == link.from_port_id for p in a.ports)), None
        )
        target = next(
            (a for a in assets if any(p.id == link.to_port_id for p in a.ports)), None
        )
        if source is None or target is None:
            continue
        src_port = next(p for p in source.ports if p.id == link.from_port_id)
        dst_port = next(p for p in target.ports if p.id == link.to_port_id)
        connected.add((by_asset[source.id], src_port.code))
        connected.add((by_asset[target.id], dst_port.code))
        links.append(
            {
                "id": str(link.id),
                "from": {"block": by_asset[source.id], "port": src_port.code},
                "to": {"block": by_asset[target.id], "port": dst_port.code},
                "type": link.link_type,
                "cable_mark": link.cable_mark,
                "length_m": float(link.length_m) if link.length_m is not None else None,
                "state": link.state,
            }
        )

    dangling = []
    for block in blocks:
        for port in block["ports"]:
            if (block["id"], port["code"]) in connected:
                continue
            if port["reserve"] or port["kind"] == "in":
                continue
            dangling.append(f"{block['title']}.{port['code']}")

    # --- проверки сходимости ------------------------------------------------
    loads: list[tuple[str, float]] = []
    for block in blocks:
        label = block["title"]
        for feeder in block["params"].get("feeders", []):
            pw = feeder["params"].get("power_kw")
            if pw:
                loads.append((f"{label} / {feeder['name'].split(' ·')[0]}", float(pw)))
        for equip in block["params"].get("equipment", []):
            if equip["role"] == "load" and equip["params"].get("power_kw"):
                loads.append((f"{label} / {equip['name'].split(' ·')[0]}", float(equip["params"]["power_kw"])))

    duplicate_loads = sorted(
        {name for name, _ in loads if sum(1 for other, _ in loads if other.split(" / ")[0] == name) > 1}
    )
    # ЭКГ не должен встречаться в двух блоках
    ekg_blocks = sorted(
        {
            block["title"]
            for block in blocks
            for equip in block["params"].get("equipment", [])
            if equip["role"] == "load" and "ЭКГ" in equip["name"]
        }
        | {
            block["title"]
            for block in blocks
            if "ЭКГ" in block["title"] or "ЭКГ" in json.dumps(block["params"].get("feeders", []), ensure_ascii=False)
        }
    )

    ktp = next((b for b in blocks if b["block"] == "ktp_standard"), None)
    ktp_check = None
    if ktp:
        tr = next(
            (e["params"].get("power_kva") for e in ktp["params"].get("equipment", []) if e["role"] == "transformer"),
            None,
        )
        total_kva = sum(
            float(f["params"].get("power_kva") or 0) for f in ktp["params"].get("feeders", [])
        )
        ktp_check = {
            "transformer_kva": tr,
            "feeders_kva": round(total_kva, 1),
            "ok": bool(tr) and total_kva <= float(tr),
        }

    bkru = next((b for b in blocks if b["block"] == "bkru_standard"), None)
    bkru_check = None
    if bkru:
        feeders_kw = sum(float(f["params"].get("power_kw") or 0) for f in bkru["params"].get("feeders", []))
        inputs = [float(i["params"].get("power_kw") or 0) for i in bkru["params"].get("incoming", [])]
        bkru_check = {
            "feeders_kw": feeders_kw,
            "inputs_kw": inputs,
            "post_accident_ok": bool(inputs) and min(inputs) >= feeders_kw,
        }

    payload = {
        "format": "karier.sketch/v1",
        "version": VERSION,
        "name": "Схема по эскизу: ПС 35/6 — БКРУ-1 / КТП №4 / ЯКНО-6 (v3)",
        "description": (
            "Фрагмент 6 кВ. Питание от Т-1/Т-2 35/6. ПС: I секция (яч. 1–15) — ф.7к (яч. 7); "
            "II секция (яч. 16–30) — ф.16к (яч. 16) → ЯКНО-6 и ф.21к (яч. 21) → БКРУ-1. "
            "СВ на границе яч. 15/16. БКРУ-1: I секция яч. 1–3, СВ яч. 4, II секция яч. 5–6; "
            "ввод 1 от ф.21к, ввод 2 от ф.7к через ЯКНО-1/1к. QF+ТТ+ОПН+Wh на фидерах, "
            "ТН/ОПН/ЗН на секциях. Нагрузки: КТП №4 400 кВА (0.4 кВ), ЯКНО-6 (ЭКГ), ПКТП-1/2/3."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "canvas": {"width": 1024, "height": 576, "units": "layout_px"},
        "library": sorted({b["block"] for b in blocks if b["block"]}),
        "blocks": blocks,
        "links": links,
        "dangling_ports": dangling,
        "validation": {
            "duplicate_loads": duplicate_loads,
            "ekg_blocks": ekg_blocks,
            "ktp": ktp_check,
            "bkru_post_accident": bkru_check,
            "loads_total_kw": round(sum(p for _, p in loads), 1),
        },
    }

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    for path in (
        Path(r"C:\karier\backend-v2\seed_data\sketch_v3.json"),
        Path(r"C:\karier\docs\sketches\sketch-v3.json"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    print("blocks:", len(blocks), "| links:", len(links), "| dangling:", dangling or "нет")
    print("ЭКГ в блоках:", ekg_blocks, "| КТП:", ktp_check, "| БКРУ:", bkru_check)
    for item in blocks:
        print(f"  {item['id']:3} {str(item['block']):16} {item['title']}")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
