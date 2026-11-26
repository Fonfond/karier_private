"""MCP-сервер топологии карьера.

Запуск (stdio, для подключения к Claude Desktop, Cursor и другим MCP-клиентам):

    .\\venv\\Scripts\\python -m mcp_server

HTTP (SSE) — если нужен сетевой доступ:

    .\\venv\\Scripts\\python -m mcp_server --http --port 8020

Инструменты работают от служебной учётной записи (по умолчанию 000001 — админ):
переменная окружения KARIER_MCP_TAB_NO. Роль должна быть admin или operator.
Сервер использует те же сервисы, что и REST API, поэтому валидация OUT→IN,
напряжения и прав доступа — общая.
"""

from __future__ import annotations

import sys
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.db.session import SessionLocal
from app.services import ai_tools

SERVICE_TAB_NO = "000001"
mcp = FastMCP("karier-topology")


def _actor(db):
    import os

    return ai_tools.resolve_actor(db, os.environ.get("KARIER_MCP_TAB_NO", SERVICE_TAB_NO))


@mcp.tool()
def list_assets() -> list[dict[str, Any]]:
    """Список объектов карьера: код, тип, статус, координаты на карте и схеме, порты."""
    db = SessionLocal()
    try:
        return ai_tools.list_assets(db, _actor(db))
    finally:
        db.close()


@mcp.tool()
def list_links() -> list[dict[str, Any]]:
    """Все связи между портами: объекты, порты, тип связи, состояние, марка кабеля."""
    db = SessionLocal()
    try:
        return ai_tools.list_links(db, _actor(db))
    finally:
        db.close()


@mcp.tool()
def create_link(
    from_port_id: str,
    to_port_id: str,
    cable_mark: str = "",
    link_type: str = "cable",
) -> dict[str, Any]:
    """Создать связь портов (OUT→IN, одинаковое напряжение). Возвращает созданную связь."""
    db = SessionLocal()
    try:
        return ai_tools.create_link(
            db,
            _actor(db),
            from_port_id=uuid.UUID(from_port_id),
            to_port_id=uuid.UUID(to_port_id),
            cable_mark=cable_mark or None,
            link_type=link_type,
        )
    finally:
        db.close()


@mcp.tool()
def move_asset(asset_id: str, x: float, y: float, note: str = "") -> dict[str, Any]:
    """Переместить объект в координаты X/Y (метры карьера). Мобильные — с историей."""
    db = SessionLocal()
    try:
        return ai_tools.move_asset(
            db, _actor(db), asset_id=uuid.UUID(asset_id), x=x, y=y, note=note or None
        )
    finally:
        db.close()


@mcp.tool()
def check_topology() -> list[dict[str, Any]]:
    """Проблемы схемы: объекты без ввода, кольца, несовпадение напряжения, висящие связи."""
    db = SessionLocal()
    try:
        return ai_tools.check_topology(db, _actor(db))
    finally:
        db.close()


def main() -> None:
    if "--http" in sys.argv:
        port = 8020
        if "--port" in sys.argv:
            port = int(sys.argv[sys.argv.index("--port") + 1])
        mcp.settings.port = port
        mcp.run(transport="sse")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
