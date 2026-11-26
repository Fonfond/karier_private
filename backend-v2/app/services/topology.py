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
from app.models import Asset, AssetPort, Line, Link
from app.schemas.gis import FeederRefOut
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


# --- фидеры (отходящие линии) ----------------------------------------------

@dataclass
class FeederView:
    """Принадлежность объектов фидерам карьера (линиям питания)."""

    lines: dict[uuid.UUID, Line]
    by_code: dict[str, Line]
    ids_by_line: dict[uuid.UUID, set[uuid.UUID]]
    refs_by_asset: dict[uuid.UUID, list[FeederRefOut]]

    def ref(self, line: Line | None) -> FeederRefOut | None:
        return feeder_ref(line) if line is not None else None


def feeder_ref(line: Line) -> FeederRefOut:
    return FeederRefOut(
        id=line.id, code=line.code, name=line.name, kind=line.kind, state=line.state
    )


def feeder_asset_ids(graph: GraphData, line: Line) -> set[uuid.UUID]:
    """Объекты фидера: начала связей линии + всё достижимое вниз по потоку.

    Границы (см. docs/team/15-s8-feeders.md):
      * идём только вниз по потоку (по `from_port` → `to_port`), не поднимаемся к источнику;
      * не входим в связи, помеченные другой линией, — объекты второго карьера,
        подключённые своим фидером, не смешиваются с первым;
      * связи без линии (`line_id IS NULL`) считаются продолжением текущего фидера.
    """
    seeds: set[uuid.UUID] = set()
    for link in graph.links:
        if link.line_id != line.id:
            continue
        to_port = graph.ports.get(link.to_port_id)
        if to_port is not None and to_port.asset_id in graph.assets:
            seeds.add(to_port.asset_id)

    reached = set(seeds)
    queue: deque[uuid.UUID] = deque(seeds)
    while queue:
        asset_id = queue.popleft()
        for port in graph.asset_ports.get(asset_id, []):
            if port.kind not in ("out", "io"):
                continue
            for link, other_port_id in graph.adjacency.get(port.id, []):
                if link.from_port_id != port.id:
                    continue
                if link.line_id is not None and link.line_id != line.id:
                    continue
                other_port = graph.ports.get(other_port_id)
                if other_port is None:
                    continue
                other_asset_id = other_port.asset_id
                if other_asset_id in reached or other_asset_id not in graph.assets:
                    continue
                reached.add(other_asset_id)
                queue.append(other_asset_id)
    return reached


def feeder_view(db: Session, pit_id: uuid.UUID, *, graph: GraphData | None = None) -> FeederView:
    """Собрать карту «объект → фидеры» по всем активным линиям карьера.

    Результат кешируется на время запроса (`Session.info`): реестр, карточка и
    граф в одном запросе не пересчитывают обход графа повторно.
    """
    cache: dict[uuid.UUID, FeederView] = db.info.setdefault("karier.feeder_view", {})
    if pit_id in cache:
        return cache[pit_id]
    graph = graph or load_graph(db, pit_id)
    lines = list(
        db.scalars(
            select(Line)
            .where(Line.pit_id == pit_id, Line.deleted_at.is_(None))
            .order_by(Line.code)
        ).all()
    )
    ids_by_line: dict[uuid.UUID, set[uuid.UUID]] = {}
    refs_by_asset: dict[uuid.UUID, list[FeederRefOut]] = {}
    for line in lines:
        ids = feeder_asset_ids(graph, line)
        ids_by_line[line.id] = ids
        ref = feeder_ref(line)
        for asset_id in ids:
            refs_by_asset.setdefault(asset_id, []).append(ref)
    for refs in refs_by_asset.values():
        refs.sort(key=lambda ref: ref.code)
    view = FeederView(
        lines={line.id: line for line in lines},
        by_code={line.code.strip().lower(): line for line in lines},
        ids_by_line=ids_by_line,
        refs_by_asset=refs_by_asset,
    )
    cache[pit_id] = view
    return view


def resolve_feeder(
    view: FeederView, *, line_id: uuid.UUID | None = None, feeder: str | None = None
) -> Line | None:
    """Найти линию по id (приоритет) или по коду. Неизвестная — None (пустой фильтр)."""
    if line_id is not None:
        return view.lines.get(line_id)
    if feeder:
        return view.by_code.get(feeder.strip().lower())
    return None


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
