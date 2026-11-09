"""Генерация JSON-описания демо-схемы (karier.sketch/v1), версия 2."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Asset, Link

DEMO = "sketch_v2"
VERSION = "2.0"

LAYOUT = {
    "Т-1 35/6 кВ": (30, 30),
    "Т-2 35/6 кВ": (30, 130),
    "ПС 35/6 кВ «Карьер»": (210, 30),
    "оп.1": (420, 20),
    "оп.2": (520, 20),
    "оп.3": (620, 20),
    "оп.4": (720, 20),
    "Реклоузер": (820, 20),
    "КТП №4 · 400 кВА": (930, 20),
    "ЯКНО-1/1к": (720, 120),
    "ЯКНО-6": (210, 300),
    "БКРУ-1": (470, 300),
    "ПКТП-3 · 400 кВА": (780, 300),
    "ЭКГ-15М · 1500 кВт": (780, 380),
    "ПКТП-4 · 400 кВА": (780, 460),
    "ПКТП-1 · 63 кВА": (930, 210),
    "ПКТП-2 · 630 кВА": (930, 280),
}


def block_code(asset: Asset, children: list[Asset]) -> str | None:
    stored = (asset.attrs or {}).get("block_code")
    if stored:
        return stored
    simple = (asset.attrs or {}).get("simple_block")
    if simple:
        return simple
    roles = {child.schema_role for child in children}
    busbars = sum(1 for child in children if child.schema_role == "busbar")
    if "transformer" in roles:
        return "ktp_standard"
    if "load" in roles and busbars == 0 and "incoming" in roles:
        return "yakno6"
    if busbars >= 2:
        return "substation_35_6"
    if "busbar" in roles and "incoming" in roles:
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
    order = {name: index for index, name in enumerate(LAYOUT)}
    assets.sort(key=lambda a: (order.get(a.name, 999), float(a.schema_x or 0)))
    if not assets:
        print("Нет демо-схемы sketch_v2 — выполните seed_demo_sketch.py")
        return 1

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
                ({"name": c.name, "params": c.attrs or {}} for c in children if c.schema_role == "section"),
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
                if c.schema_role in ("tt", "opn", "znv", "transformer", "load")
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
                    }
                    for port in sorted(asset.ports, key=lambda p: p.code)
                ],
            }
        )

    links = []
    connected_ports: set[tuple[str, str]] = set()
    for link in db.scalars(select(Link)).all():
        source = next(
            (a for a in assets if any(p.id == link.from_port_id for p in a.ports)), None
        )
        target = next(
            (a for a in assets if any(p.id == link.to_port_id for p in a.ports)), None
        )
        if source is None or target is None:
            continue
        src_port = next(p.code for p in source.ports if p.id == link.from_port_id)
        dst_port = next(p.code for p in target.ports if p.id == link.to_port_id)
        connected_ports.add((by_asset[source.id], src_port))
        connected_ports.add((by_asset[target.id], dst_port))
        links.append(
            {
                "id": str(link.id),
                "from": {"block": by_asset[source.id], "port": src_port},
                "to": {"block": by_asset[target.id], "port": dst_port},
                "type": link.link_type,
                "cable_mark": link.cable_mark,
                "length_m": float(link.length_m) if link.length_m is not None else None,
                "state": link.state,
            }
        )

    dangling = []
    for block in blocks:
        for port in block["ports"]:
            if (block["id"], port["code"]) in connected_ports:
                continue
            label = port.get("label", "")
            if port["kind"] == "out" and ("резерв" in label or "отпайка" in label):
                continue
            dangling.append(f"{block['title']}.{port['code']}")

    payload = {
        "format": "karier.sketch/v1",
        "version": VERSION,
        "name": "Схема по эскизу: ПС 35/6 — БКРУ-1 / КТП №4 / ЯКНО-6",
        "description": (
            "Фрагмент 6 кВ: питание от Т-1/Т-2 35/6 кВ, две секции ПС с СВ, "
            "ВЛ ф.7к (оп.1–4, реклоузер, КТП №4), отпайка на ЯКНО-1/1к → БКРУ-1, "
            "ф.16к → ЯКНО-6, ф.21к → БКРУ-1; QF+ТТ+ОПН+Wh на присоединениях"
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "canvas": {"width": 1024, "height": 576, "units": "layout_px"},
        "library": sorted({b["block"] for b in blocks if b["block"]}),
        "blocks": blocks,
        "links": links,
        "dangling_ports": dangling,
    }

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    for path in (
        Path(r"C:\karier\backend-v2\seed_data\sketch_v2.json"),
        Path(r"C:\karier\docs\sketches\sketch-v2.json"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    print("blocks:", len(blocks), "| links:", len(links), "| dangling:", dangling or "нет")
    for item in blocks:
        print(f"  {item['id']:3} {str(item['block']):16} {item['title']}")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
