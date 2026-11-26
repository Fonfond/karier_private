"""Импорт схемы из JSON-описания (karier.sketch/v1).

    .\\venv\\Scripts\\python import_sketch_json.py seed_data/sketch_v1.json
    .\\venv\\Scripts\\python import_sketch_json.py seed_data/sketch_v1.json --dry-run
    .\\venv\\Scripts\\python import_sketch_json.py seed_data/sketch_v1.json --clean

Формат: блоки библиотеки + внешние порты + связи между портами.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Asset, SchemaBlock
from app.schemas.gis import LinkCreate
from app.services import gis, links as links_service
from app.services import schema_blocks as blocks_service


def _actor(db):
    from app.models import Employee

    return db.scalar(select(Employee).where(Employee.tab_no == "000001"))


def _port(asset: Asset, code: str):
    for port in asset.ports:
        if port.code == code:
            return port
    raise SystemExit(f"У блока «{asset.name}» нет порта {code}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Импорт схемы из JSON")
    parser.add_argument("path", nargs="?", default="seed_data/sketch_v1.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    payload = json.loads(Path(args.path).read_text(encoding="utf-8"))
    fmt = payload.get("format")
    if fmt != "karier.sketch/v1":
        raise SystemExit(f"Неизвестный формат: {fmt}")

    db = SessionLocal()
    try:
        actor = _actor(db)
        if actor is None:
            raise SystemExit("Нет администратора 000001 — выполните seed.py")

        blocks = payload.get("blocks") or []
        links = payload.get("links") or []
        print(f"Схема: {payload.get('name')}")
        print(f"Блоков: {len(blocks)}, связей: {len(links)}")

        codes = {item["block"] for item in blocks}
        missing = [
            code
            for code in codes
            if db.scalar(select(SchemaBlock).where(SchemaBlock.code == code)) is None
        ]
        if missing:
            raise SystemExit(f"Нет шаблонов блоков: {missing}")

        if args.dry_run:
            for item in blocks:
                print(f"  [dry] {item['block']:18} {item['title']:30} x={item['position']['x']} y={item['position']['y']}")
            for link in links:
                print(f"  [dry] {link['from']['block']}.{link['from']['port']} -> {link['to']['block']}.{link['to']['port']} {link.get('cable_mark') or ''}")
            print("Проверка пройдена, база не изменялась.")
            return 0

        if args.clean:
            marker = f"json:{fmt}"
            old = [
                a
                for a in db.scalars(select(Asset).where(Asset.schema_role == "block")).all()
                if (a.attrs or {}).get("demo") == marker and a.deleted_at is None
            ]
            for parent in old:
                for child in db.scalars(
                    select(Asset).where(Asset.schema_block_id == parent.id, Asset.deleted_at.is_(None))
                ).all():
                    gis.soft_delete(db, child, actor=actor)
                gis.soft_delete(db, parent, actor=actor)
            db.commit()
            print(f"Удалено прошлых импортов: {len(old)}")

        created: dict[str, Asset] = {}
        for item in blocks:
            px = float(item["position"]["x"])
            py = float(item["position"]["y"])
            if not (0 <= px <= 1024 and 0 <= py <= 576):
                raise SystemExit(
                    f"Блок «{item['title']}» вне карты: x={px}, y={py} (допустимо 0…1024, 0…576)"
                )
            block = blocks_service.get_block(db, item["block"])
            result = blocks_service.instantiate(
                db,
                block,
                actor,
                x=float(item["position"]["x"]),
                y=float(item["position"]["y"]),
                name=item["title"],
            )
            asset = db.get(Asset, __import__("uuid").UUID(result["asset_id"]))
            asset.attrs = {
                **(asset.attrs or {}),
                "demo": f"json:{fmt}",
                "sketch_id": item["id"],
                "params": item.get("params") or {},
            }
            db.commit()
            db.refresh(asset)
            created[item["id"]] = asset
            print(f"  + {item['block']:18} {item['title']}")

        for index, link in enumerate(links, start=1):
            source = created[link["from"]["block"]]
            target = created[link["to"]["block"]]
            links_service.create_link(
                db,
                source.pit_id,
                LinkCreate(
                    from_port_id=_port(source, link["from"]["port"]).id,
                    to_port_id=_port(target, link["to"]["port"]).id,
                    link_type=link.get("type") or "cable",
                    cable_mark=link.get("cable_mark"),
                    length_m=link.get("length_m"),
                    state=link.get("state") or "connected",
                ),
                actor=actor,
            )
            print(f"  → связь {index}: {source.name} → {target.name}")

        print("Импорт завершён.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
