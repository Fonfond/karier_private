"""Расчёт питания по графу связей и валидация топологии.

Модель:
  * узел графа — порт объекта (`gis.asset_ports`);
  * ребро — участок связи (`gis.links`) со своим состоянием;
  * внутри объекта порты связаны, если объект «проводит» (включён и не заземлён).

Обход идёт от включённых источников (подстанция, ДГУ) по включённым связям.
"""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import ApiError, conflict
from app.models import Asset, AssetPort, Link
from app.services.gis import get_pit

CONDUCTING_STATUSES = {"on"}


# --- загрузка графа --------------------------------------------------------

@dataclass
class GraphData:
    assets: dict[uuid.UUID, Asset]
    ports: dict[uuid.UUID, AssetPort]
    asset_ports: dict[uuid.UUID, list[AssetPort]]
    links: list[Link]
    adjacency: dict[uuid.UUID, list[tuple[Link, uuid.UUID]]]


def load_graph(db: Session, pit_id: uuid.UUID) -> GraphData:
    assets = (
        db.scalars(
            select(Asset)
            .where(Asset.pit_id == pit_id, Asset.deleted_at.is_(None))
            .options(selectinload(Asset.ports))
        )
        .unique()
        .all()
    )
    links = list(
        db.scalars(
            select(Link).where(Link.pit_id == pit_id, Link.deleted_at.is_(None))
        ).all()
    )

    asset_map = {a.id: a for a in assets}
    port_map: dict[uuid.UUID, AssetPort] = {}
    by_asset: dict[uuid.UUID, list[AssetPort]] = {}
    for asset in assets:
        by_asset[asset.id] = list(asset.ports)
        for port in asset.ports:
            port_map[port.id] = port

    adjacency: dict[uuid.UUID, list[tuple[Link, uuid.UUID]]] = {}
    for link in links:
        adjacency.setdefault(link.from_port_id, []).append((link, link.to_port_id))
        adjacency.setdefault(link.to_port_id, []).append((link, link.from_port_id))

    return GraphData(asset_map, port_map, by_asset, links, adjacency)


def is_conducting(asset: Asset) -> bool:
    return asset.status in CONDUCTING_STATUSES and not asset.grounded


def is_source(asset: Asset) -> bool:
    """Источник: категория «source» или объект, у которого есть только выходы.

    Вторая ветка нужна для мобильных генераторов («кукушка»), которые
    в справочнике лежат в категории «mobile», но физически выдают питание.
    """
    if asset.asset_type and asset.asset_type.category == "source":
        return True
    ports = list(asset.ports)
    if not ports:
        return False
    return all(port.kind == "out" for port in ports)


# --- обход -----------------------------------------------------------------

@dataclass
class Energization:
    energized: set[uuid.UUID] = field(default_factory=set)  # id объектов под напряжением
    source_by_asset: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)
    prev_port: dict[uuid.UUID, uuid.UUID | None] = field(default_factory=dict)
    entry_link: dict[uuid.UUID, uuid.UUID | None] = field(default_factory=dict)
    visited_ports: set[uuid.UUID] = field(default_factory=set)
    sources: list[uuid.UUID] = field(default_factory=list)
    graph: GraphData | None = None

    def path_to(self, asset_id: uuid.UUID) -> list[tuple[uuid.UUID, uuid.UUID | None]]:
        """Путь до объекта: [(asset_id, link_id_входа), …] от источника."""
        if self.graph is None:
            return []
        asset = self.graph.assets.get(asset_id)
        if asset is None:
            return []

        # стартовый порт: предпочитаем ввод, затем любой посещённый
        start_port: uuid.UUID | None = None
        for port in self.graph.asset_ports.get(asset_id, []):
            if port.id in self.visited_ports:
                start_port = port.id
                if port.kind in ("in", "io"):
                    break
        if start_port is None:
            return []

        chain: list[tuple[uuid.UUID, uuid.UUID | None]] = []
        port: uuid.UUID | None = start_port
        guard = 0
        while port is not None and guard < 256:
            guard += 1
            port_obj = self.graph.ports.get(port)
            if port_obj is None:
                break
            link_id = self.entry_link.get(port)
            if chain and chain[-1][0] == port_obj.asset_id:
                # внутренний переход: сохраняем ссылку на связь, если она есть
                if link_id is not None:
                    chain[-1] = (port_obj.asset_id, link_id)
            else:
                chain.append((port_obj.asset_id, link_id))
            port = self.prev_port.get(port)

        chain.reverse()
        return chain


def energize(db: Session, pit_id: uuid.UUID) -> Energization:
    graph = load_graph(db, pit_id)
    result = Energization(graph=graph)
    queue: deque[uuid.UUID] = deque()

    for asset in graph.assets.values():
        if not is_source(asset) or not is_conducting(asset):
            continue
        result.sources.append(asset.id)
        result.energized.add(asset.id)
        result.source_by_asset.setdefault(asset.id, asset.id)
        for port in graph.asset_ports.get(asset.id, []):
            if port.kind in ("out", "io") and port.id not in result.visited_ports:
                result.visited_ports.add(port.id)
                result.prev_port[port.id] = None
                result.entry_link[port.id] = None
                queue.append(port.id)

    while queue:
        port_id = queue.popleft()
        port = graph.ports.get(port_id)
        if port is None:
            continue
        asset = graph.assets.get(port.asset_id)
        source_id = result.source_by_asset.get(port.asset_id)
        if asset is None:
            continue

        # внутри объекта: порты связаны, если объект проводит
        if is_conducting(asset):
            for other in graph.asset_ports.get(asset.id, []):
                if other.id == port_id or other.id in result.visited_ports:
                    continue
                result.visited_ports.add(other.id)
                result.prev_port[other.id] = port_id
                result.entry_link[other.id] = None
                if source_id is not None:
                    result.source_by_asset.setdefault(asset.id, source_id)
                queue.append(other.id)

        # по связям наружу
        for link, other_port_id in graph.adjacency.get(port_id, []):
            if link.state != "connected":
                continue
            other_port = graph.ports.get(other_port_id)
            if other_port is None or other_port_id in result.visited_ports:
                continue
            other_asset = graph.assets.get(other_port.asset_id)
            if other_asset is None or other_asset.grounded:
                continue
            result.visited_ports.add(other_port_id)
            result.prev_port[other_port_id] = port_id
            result.entry_link[other_port_id] = link.id
            if source_id is not None:
                result.source_by_asset.setdefault(other_asset.id, source_id)
            if other_asset.status in CONDUCTING_STATUSES:
                result.energized.add(other_asset.id)
            queue.append(other_port_id)

        if source_id is not None and is_conducting(asset):
            result.energized.add(asset.id)

    return result


def power_path(db: Session, asset: Asset) -> dict:
    """Ответ для GET /assets/{id}/power-path: реальный путь по графу."""
    energization = energize(db, asset.pit_id)
    chain_raw = energization.path_to(asset.id)
    graph = energization.graph
    links_by_id = {link.id: link for link in graph.links} if graph else {}

    nodes: list[dict] = []
    for asset_id, link_id in chain_raw:
        node_asset = graph.assets[asset_id]  # type: ignore[index]
        nodes.append(
            {"asset": node_asset, "link": links_by_id.get(link_id) if link_id else None}
        )

    energized = asset.id in energization.energized
    source_id = energization.source_by_asset.get(asset.id)
    source_asset = graph.assets.get(source_id) if source_id and graph else None

    return {
        "energized": energized,
        "source": source_asset,
        "nodes": nodes,
        "reason": None if energized else _explain_no_power(asset, nodes),
    }


def _explain_no_power(asset: Asset, nodes: list[dict]) -> str:
    if asset.grounded:
        return "Объект заземлён — питание снято"
    if asset.status != "on":
        return "Объект отключён (статус не «включено»)"
    if not nodes:
        return "Объект не связан с источником питания: нет включённого пути по связям"
    return "Путь питания разомкнут: на маршруте есть отключённая связь или объект"


# --- валидация связей ------------------------------------------------------

def _directed_main_edges(graph: GraphData) -> dict[uuid.UUID, list[uuid.UUID]]:
    edges: dict[uuid.UUID, list[uuid.UUID]] = {}
    for link in graph.links:
        if link.state != "connected" or link.feed_role != "main":
            continue
        from_port = graph.ports.get(link.from_port_id)
        to_port = graph.ports.get(link.to_port_id)
        if from_port is None or to_port is None:
            continue
        if from_port.asset_id == to_port.asset_id:
            continue
        edges.setdefault(from_port.asset_id, []).append(to_port.asset_id)
    return edges


def _has_path(edges: dict[uuid.UUID, list[uuid.UUID]], start: uuid.UUID, target: uuid.UUID) -> bool:
    stack = [start]
    seen = {start}
    while stack:
        node = stack.pop()
        if node == target:
            return True
        for nxt in edges.get(node, []):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False


def validate_new_link(
    db: Session,
    *,
    from_port: AssetPort,
    to_port: AssetPort,
    link_type: str,
    feed_role: str = "main",
) -> list[str]:
    """Проверить новую связь. Возвращает предупреждения, при ошибке бросает ApiError."""
    if from_port.id == to_port.id:
        raise ApiError(400, "link.same_port", "Нельзя соединить порт сам с собой")
    if from_port.asset_id == to_port.asset_id:
        raise ApiError(
            400, "link.same_asset", "Соединять порты одного объекта нельзя — используйте вложенность"
        )
    if from_port.kind not in ("out", "io"):
        raise ApiError(
            400, "link.bad_direction", "Связь начинается только с выхода (OUT) или двунаправленного порта"
        )
    if to_port.kind not in ("in", "io"):
        raise ApiError(
            400,
            "link.bad_direction",
            "Связь заканчивается только на вводе (IN) или двунаправленном порте",
        )

    if link_type != "internal":
        v_from = float(from_port.nominal_voltage_kv) if from_port.nominal_voltage_kv else None
        v_to = float(to_port.nominal_voltage_kv) if to_port.nominal_voltage_kv else None
        if v_from is not None and v_to is not None and abs(v_from - v_to) > 0.001:
            # 6 кВ и 0,4 кВ соединяются только через трансформатор внутри КТП,
            # внешней связью — нельзя
            raise ApiError(
                422,
                "link.voltage_mismatch",
                f"Несовпадение напряжения портов: {v_from:g} кВ и {v_to:g} кВ",
                fields={"from_port": f"{v_from:g} кВ", "to_port": f"{v_to:g} кВ"},
            )

    duplicate = db.scalar(
        select(Link).where(
            Link.from_port_id == from_port.id,
            Link.to_port_id == to_port.id,
            Link.deleted_at.is_(None),
        )
    )
    if duplicate is not None:
        raise conflict("Такая связь уже существует", "link.duplicate")

    # цикл в основной схеме питания
    if feed_role == "main":
        pit_id = _pit_of(db, from_port.asset_id)
        graph = load_graph(db, pit_id)
        edges = _directed_main_edges(graph)
        if _has_path(edges, to_port.asset_id, from_port.asset_id):
            raise ApiError(
                422,
                "link.cycle",
                "Связь создаёт замкнутый контур в основной схеме питания",
            )

    warnings: list[str] = []
    if to_port.asset_id:
        target_asset = db.get(Asset, to_port.asset_id)
        if target_asset is not None and not is_source(target_asset):
            has_inlet = db.scalar(
                select(Link.id)
                .join(AssetPort, Link.to_port_id == AssetPort.id)
                .where(
                    AssetPort.asset_id == target_asset.id,
                    Link.state == "connected",
                    Link.deleted_at.is_(None),
                )
                .limit(1)
            )
            if has_inlet is None:
                warnings.append("У объекта не было ввода — эта связь станет первым")
    return warnings


def _pit_of(db: Session, asset_id: uuid.UUID) -> uuid.UUID:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise ApiError(404, "asset.not_found", "Объект не найден")
    return asset.pit_id


# --- проверки схемы --------------------------------------------------------

def topology_issues(db: Session, pit_id: uuid.UUID) -> list[dict]:
    graph = load_graph(db, pit_id)
    energization = energize(db, pit_id)
    issues: list[dict] = []

    inlets: dict[uuid.UUID, int] = {}
    for link in graph.links:
        if link.state != "connected":
            continue
        to_port = graph.ports.get(link.to_port_id)
        if to_port is not None:
            inlets[to_port.asset_id] = inlets.get(to_port.asset_id, 0) + 1

    for asset in graph.assets.values():
        if not is_source(asset) and inlets.get(asset.id, 0) == 0:
            issues.append(
                {
                    "level": "warning",
                    "code": "asset.no_inlet",
                    "asset_id": asset.id,
                    "message": f"{asset.name}: нет ввода (объект не подключён к питанию)",
                }
            )
        if not graph.asset_ports.get(asset.id):
            issues.append(
                {
                    "level": "warning",
                    "code": "asset.no_ports",
                    "asset_id": asset.id,
                    "message": f"{asset.name}: у объекта нет портов",
                }
            )

    # кольца в основной схеме: есть ли путь от любого преемника обратно к узлу
    edges = _directed_main_edges(graph)
    cycle_assets: set[uuid.UUID] = set()
    for asset in graph.assets.values():
        for successor in edges.get(asset.id, []):
            if _has_path(edges, successor, asset.id):
                cycle_assets.add(asset.id)
                break
    for asset_id in cycle_assets:
        asset = graph.assets[asset_id]
        issues.append(
            {
                "level": "error",
                "code": "topology.cycle",
                "asset_id": asset.id,
                "message": f"{asset.name}: замкнутый контур в основной схеме",
            }
        )

    for link in graph.links:
        from_port = graph.ports.get(link.from_port_id)
        to_port = graph.ports.get(link.to_port_id)
        if from_port is None or to_port is None:
            continue
        v1 = float(from_port.nominal_voltage_kv) if from_port.nominal_voltage_kv else None
        v2 = float(to_port.nominal_voltage_kv) if to_port.nominal_voltage_kv else None
        if v1 and v2 and abs(v1 - v2) > 0.001 and link.link_type != "internal":
            issues.append(
                {
                    "level": "error",
                    "code": "link.voltage_mismatch",
                    "link_id": link.id,
                    "message": f"Связь {from_port.code}→{to_port.code}: {v1:g} кВ и {v2:g} кВ",
                }
            )

    return issues


def graph_payload(db: Session, pit_id: uuid.UUID) -> dict:
    """Данные для однолинейной схемы: узлы, связи, уровни."""
    graph = load_graph(db, pit_id)
    energization = energize(db, pit_id)

    nodes = []
    for asset in graph.assets.values():
        nodes.append(
            {
                "asset": asset,
                "energized": asset.id in energization.energized,
                "is_source": is_source(asset),
            }
        )

    edges = []
    for link in graph.links:
        from_port = graph.ports.get(link.from_port_id)
        to_port = graph.ports.get(link.to_port_id)
        if from_port is None or to_port is None:
            continue
        edges.append(
            {
                "link": link,
                "from_asset_id": from_port.asset_id,
                "to_asset_id": to_port.asset_id,
                "from_port": from_port,
                "to_port": to_port,
            }
        )

    return {"nodes": nodes, "edges": edges, "energized": energization.energized}
