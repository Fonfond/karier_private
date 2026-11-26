"""Сборка ответа «граф схемы» — один источник для API и для снимков.

Раньше логика жила прямо в роутере `GET /api/topology/graph`. Она понадобилась
ещё и снимкам (нужен ровно тот же слепок, что видит редактор), поэтому вынесена
в сервис: и живой граф, и снимок строятся одной функцией и не расходятся.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Pit
from app.schemas.gis import (
    GraphBlockChildOut,
    GraphBlockOut,
    GraphEdgeOut,
    GraphJumperOut,
    GraphNodeOut,
    PortRefOut,
    TopologyGraphOut,
)
from app.services import links as links_service
from app.services import topology


def build_graph_out(db: Session, pit: Pit) -> TopologyGraphOut:
    """Граф для редактора схемы: узлы, связи и комплектные блоки."""
    data = topology.graph_payload(db, pit.id)

    blocks_map: dict = {}
    # Контур — блок без обязательных детей: он попадает в blocks по attrs.block_code,
    # иначе после рисования прямоугольника на схеме ничего бы не появилось.
    for item in data["nodes"]:
        asset = item["asset"]
        if asset.schema_block_id is None and (asset.attrs or {}).get("block_code"):
            blocks_map.setdefault(asset.id, {"parent": None, "children": []})
    for item in data["nodes"]:
        asset = item["asset"]
        if asset.schema_block_id is not None:
            block = blocks_map.setdefault(
                asset.schema_block_id,
                {"parent": None, "children": []},
            )
            block["children"].append(
                GraphBlockChildOut(
                    id=asset.id,
                    code=asset.code,
                    name=asset.name,
                    role=asset.schema_role,
                    local_x=float(asset.schema_local_x) if asset.schema_local_x is not None else None,
                    local_y=float(asset.schema_local_y) if asset.schema_local_y is not None else None,
                    type_name=asset.asset_type.name if asset.asset_type else None,
                    params=asset.attrs or {},
                )
            )

    nodes = [
        GraphNodeOut(
            id=item["asset"].id,
            code=item["asset"].code,
            name=item["asset"].name,
            type_code=item["asset"].asset_type.code,
            type_name=item["asset"].asset_type.name,
            type_icon=item["asset"].asset_type.icon,
            type_color=item["asset"].asset_type.color,
            category=item["asset"].asset_type.category,
            schema_symbol=item["asset"].asset_type.schema_symbol,
            status=item["asset"].status,
            grounded=item["asset"].grounded,
            energized=item["energized"],
            is_source=item["is_source"],
            parent_id=item["asset"].parent_asset_id,
            schema_x=float(item["asset"].schema_x) if item["asset"].schema_x is not None else None,
            schema_y=float(item["asset"].schema_y) if item["asset"].schema_y is not None else None,
            ports=[
                PortRefOut(
                    id=p.id,
                    code=p.code,
                    name=p.name,
                    kind=p.kind,
                    voltage_kv=float(p.nominal_voltage_kv) if p.nominal_voltage_kv else None,
                    schema_x=float(p.schema_x) if p.schema_x is not None else None,
                    schema_y=float(p.schema_y) if p.schema_y is not None else None,
                )
                for p in item["asset"].ports
            ],
        )
        for item in data["nodes"]
        if item["asset"].schema_block_id is None
    ]
    edges = [
        GraphEdgeOut(
            id=item["link"].id,
            from_asset_id=item["from_asset_id"],
            to_asset_id=item["to_asset_id"],
            label=links_service.link_label(item["link"]),
            link_type=item["link"].link_type,
            state=item["link"].state,
            feed_role=item["link"].feed_role,
            cable_mark=item["link"].cable_mark,
            length_m=float(item["link"].length_m) if item["link"].length_m else None,
            cross_section_mm2=(
                float(item["link"].cross_section_mm2) if item["link"].cross_section_mm2 else None
            ),
            cores=item["link"].cores,
            version=item["link"].version,
        )
        for item in data["edges"]
    ]

    blocks = []
    for block_id, bucket in blocks_map.items():
        parent_asset = next(
            (item["asset"] for item in data["nodes"] if item["asset"].id == block_id), None
        )
        if parent_asset is None:
            continue
        children_ids = {child.id for child in bucket["children"]}
        port_owner: dict = {}
        for item in data["nodes"]:
            asset = item["asset"]
            for port in asset.ports:
                if asset.id in children_ids:
                    port_owner[port.id] = asset.id

        jumpers: list = []
        for edge_item in data.get("edges", []):
            link = edge_item["link"]
            if getattr(link, "link_type", None) != "jumper":
                continue
            source = port_owner.get(link.from_port_id)
            target = port_owner.get(link.to_port_id)
            if source and target and source != target:
                jumpers.append(
                    GraphJumperOut(
                        id=link.id,
                        from_cell_id=source,
                        to_cell_id=target,
                        label=link.cable_mark,
                    )
                )

        blocks.append(
            GraphBlockOut(
                asset_id=parent_asset.id,
                kind=(parent_asset.attrs or {}).get("block_code"),
                width=(
                    float(parent_asset.attrs["contour_w"])
                    if (parent_asset.attrs or {}).get("contour_w") is not None
                    else None
                ),
                height=(
                    float(parent_asset.attrs["contour_h"])
                    if (parent_asset.attrs or {}).get("contour_h") is not None
                    else None
                ),
                code=parent_asset.code,
                name=parent_asset.name,
                block_code=(parent_asset.attrs or {}).get("block_code"),
                schema_x=float(parent_asset.schema_x) if parent_asset.schema_x is not None else None,
                schema_y=float(parent_asset.schema_y) if parent_asset.schema_y is not None else None,
                collapsed=bool((parent_asset.attrs or {}).get("collapsed")),
                jumpers=jumpers,
                children=bucket["children"],
            )
        )

    return TopologyGraphOut(nodes=nodes, edges=edges, blocks=blocks)


def build_snapshot_payload(db: Session, pit: Pit) -> dict:
    """Полный слепок схемы для снимка: граф + рамка/штамп + метаданные."""
    from datetime import datetime, timezone

    from app.schemas.gis import SchemaFrameOut

    graph = build_graph_out(db, pit)
    frame = SchemaFrameOut(**(pit.schema_frame or {})).model_dump()

    return {
        "schema_version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "pit": {
            "id": str(pit.id),
            "code": pit.code,
            "name": pit.name,
            "crs_name": pit.crs_name,
        },
        "frame": frame,
        "graph": graph.model_dump(mode="json"),
        "counts": {
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "blocks": len(graph.blocks),
        },
    }


def snapshot_counts(payload: dict) -> dict[str, int]:
    """Счётчики из слепка — с запасом на старые снимки без блока `counts`."""
    counts = payload.get("counts") if isinstance(payload, dict) else None
    if isinstance(counts, dict):
        return {
            "nodes": int(counts.get("nodes") or 0),
            "edges": int(counts.get("edges") or 0),
            "blocks": int(counts.get("blocks") or 0),
        }
    graph = payload.get("graph") if isinstance(payload, dict) else {}
    graph = graph if isinstance(graph, dict) else {}
    return {
        "nodes": len(graph.get("nodes") or []),
        "edges": len(graph.get("edges") or []),
        "blocks": len(graph.get("blocks") or []),
    }


__all__ = [
    "build_graph_out",
    "build_snapshot_payload",
    "snapshot_counts",
]
