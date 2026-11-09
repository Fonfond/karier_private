"""Генерация JSON-описания демо-схемы по блокам (karier.sketch/v1)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Asset, Link, SchemaBlock

DEMO = "sketch_v1"


LAYOUT = {
    "ПС 35/6 кВ «Карьер»": (40, 40),
    "Реклоузер": (320, 40),
    "оп.14": (470, 40),
    "оп.13": (600, 40),
    "оп.12": (730, 40),
    "КТП №4": (860, 40),
    "БКРУ-2": (320, 320),
    "ЯКНО-1": (620, 340),
}



def block_code(db, asset: Asset, children: list[Asset]) -> str | None:
    simple = (asset.attrs or {}).get("simple_block")
    if simple:
        return simple
    stored = (asset.attrs or {}).get("block_code")
    if stored:
        return stored
    roles = {child.schema_role for child in children}
    busbars = sum(1 for child in children if child.schema_role == "busbar")
    if "transformer" in roles:
        return "ktp_standard"
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
    assets.sort(key=lambda a: (float(a.schema_y or 0), float(a.schema_x or 0)))

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
        params = {}
        if (asset.attrs or {}).get("pole_no"):
            params["pole_no"] = asset.attrs["pole_no"]
        if children:
            params["sections"] = [c.name for c in children if c.schema_role == "busbar"]
            params["incoming"] = [c.name for c in children if c.schema_role == "incoming"]
            params["feeders"] = [
                {"name": c.name, "cable": (c.attrs or {}).get("cable")}
                for c in children
                if c.schema_role == "outgoing"
            ]
            params["section_breaker"] = next(
                (c.name for c in children if c.schema_role == "section"), None
            )
            params["equipment"] = [
                c.name for c in children if c.schema_role in ("tt", "opn", "znv", "transformer")
            ]

        blocks.append(
            {
                "id": bid,
                "block": block_code(db, asset, children),
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
    for link in db.scalars(select(Link)).all():
        source = next(
            (a for a in assets if any(p.id == link.from_port_id for p in a.ports)), None
        )
        target = next(
            (a for a in assets if any(p.id == link.to_port_id for p in a.ports)), None
        )
        if source is None or target is None:
            continue
        links.append(
            {
                "id": str(link.id),
                "from": {
                    "block": by_asset[source.id],
                    "port": next(p.code for p in source.ports if p.id == link.from_port_id),
                },
                "to": {
                    "block": by_asset[target.id],
                    "port": next(p.code for p in target.ports if p.id == link.to_port_id),
                },
                "type": link.link_type,
                "cable_mark": link.cable_mark,
                "length_m": float(link.length_m) if link.length_m is not None else None,
                "state": link.state,
            }
        )

    payload = {
        "format": "karier.sketch/v1",
        "name": "Схема по эскизу: ПС 35/6 — БКРУ-2 / КТП №4",
        "description": (
            "Собрана из блоков библиотеки: ПС с двумя секциями шин, реклоузер, "
            "опоры ВЛ, КТП и БКРУ"
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "canvas": {"width": 1024, "height": 576, "units": "m"},
        "library": sorted({b["block"] for b in blocks if b["block"]}),
        "blocks": blocks,
        "links": links,
    }

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    for path in (
        Path(r"C:\karier\backend-v2\seed_data\sketch_v1.json"),
        Path(r"C:\karier\docs\sketches\sketch-v1.json"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    print("blocks:", len(blocks), "| links:", len(links))
    for item in blocks:
        print(f"  {item['id']} {item['block']:18} {item['title']}")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
