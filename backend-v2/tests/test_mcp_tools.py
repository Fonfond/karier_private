"""Тесты инструментов MCP (они же — сервисный слой ИИ-агента)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.errors import ApiError
from app.db.session import SessionLocal
from app.models import Asset, Employee, Link, Role
from app.services import ai_tools, gis


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _admin(db) -> Employee:
    return db.scalar(select(Employee).where(Employee.tab_no == "000001"))


def _asset(db, type_code: str) -> Asset:
    pit = gis.get_pit(db)
    items = list(
        db.scalars(
            select(Asset)
            .join(Asset.asset_type)
            .where(Asset.pit_id == pit.id, Asset.deleted_at.is_(None))
            .where(Asset.asset_type.has(code=type_code))
            .order_by(Asset.code)
        )
    )
    # предпочитаем объект с координатами: в базе могут быть объекты, созданные без них
    return next((item for item in items if item.x is not None and item.y is not None), items[0])


def test_list_assets_returns_ports_and_coordinates(db):
    assets = ai_tools.list_assets(db, _admin(db))
    assert len(assets) >= 20
    sample = next(item for item in assets if item["code"] == "BKRU-1")
    assert sample["x"] is not None
    assert sample["ports"], "у объекта должны быть порты"
    assert {"id", "code", "kind", "voltage_kv"} <= set(sample["ports"][0])


def test_list_links_returns_serialized_links(db):
    links = ai_tools.list_links(db, _admin(db))
    assert len(links) >= 10
    assert {"from_asset", "to_asset", "from_port", "to_port", "state"} <= set(links[0])


def test_create_link_validates_direction_and_voltage(db):
    admin = _admin(db)
    from app.models import AssetPort

    ports = db.scalars(select(AssetPort).limit(400)).all()
    linked = {
        (link.from_port_id, link.to_port_id)
        for link in db.scalars(select(Link).where(Link.deleted_at.is_(None))).all()
    }

    pair = None
    for out in ports:
        if out.kind != "out":
            continue
        for inp in ports:
            if inp.kind != "in" or inp.asset_id == out.asset_id:
                continue
            if (out.nominal_voltage_kv or 0) != (inp.nominal_voltage_kv or 0):
                continue
            if (out.id, inp.id) in linked or (inp.id, out.id) in linked:
                continue
            pair = (out, inp)
            break
        if pair:
            break

    if pair is None:
        pytest.skip("в демо-данных не осталось свободной пары портов")
    out, inp = pair

    created = ai_tools.create_link(
        db,
        admin,
        from_port_id=out.id,
        to_port_id=inp.id,
        cable_mark="АВБбШв 4×25",
        link_type="cable",
    )
    try:
        assert created["cable_mark"] == "АВБбШв 4×25"
        assert created["from_port"] == out.code

        # повторная связь запрещена валидацией
        with pytest.raises(ApiError):
            ai_tools.create_link(
                db, admin, from_port_id=out.id, to_port_id=inp.id, cable_mark=None, link_type="cable"
            )
    finally:
        link = db.scalar(
            select(Link).where(Link.from_port_id == out.id, Link.to_port_id == inp.id)
        )
        if link is not None:
            db.delete(link)
            db.commit()


def test_create_link_rejects_in_to_in(db):
    admin = _admin(db)
    in_ports = [
        port
        for port in db.scalars(select(__import__("app.models", fromlist=["AssetPort"]).AssetPort)).all()
        if port.kind == "in"
    ]
    first, second = in_ports[0], in_ports[1]
    with pytest.raises(ApiError):
        ai_tools.create_link(
            db, admin, from_port_id=first.id, to_port_id=second.id, cable_mark=None, link_type="cable"
        )


def test_check_topology_returns_issues(db):
    issues = ai_tools.check_topology(db, _admin(db))
    assert isinstance(issues, list)
    if issues:
        assert {"level", "code", "message"} <= set(issues[0])


def test_move_asset_stationary_updates_coordinates(db):
    admin = _admin(db)
    asset = _asset(db, "ktp")
    original = (float(asset.x), float(asset.y))

    result = ai_tools.move_asset(db, admin, asset_id=asset.id, x=505.0, y=305.0, note="тест ИИ")
    assert result["x"] == 505.0 and result["y"] == 305.0
    assert result["kind"] == "patch"

    db.refresh(asset)
    assert float(asset.x) == 505.0

    # возвращаем
    ai_tools.move_asset(db, admin, asset_id=asset.id, x=original[0], y=original[1], note="откат")


def test_move_asset_mobile_writes_history(db):
    admin = _admin(db)
    asset = _asset(db, "dmo")
    assert asset.is_mobile is True
    original = (float(asset.x), float(asset.y))

    result = ai_tools.move_asset(db, admin, asset_id=asset.id, x=640.0, y=480.0, note="ИИ переставил")
    assert result["kind"] == "move"
    assert result["history_entry"]

    ai_tools.move_asset(db, admin, asset_id=asset.id, x=original[0], y=original[1], note="откат")


def test_viewer_has_no_access(db):
    viewer = db.scalar(
        select(Employee).join(Role).where(Role.code == "viewer", Employee.status == "active").limit(1)
    )
    if viewer is None:
        employee = Employee(
            id=uuid.uuid4(),
            tab_no=f"V{uuid.uuid4().hex[:6].upper()}",
            full_name="Наблюдатель ИИ",
            role_id=db.scalar(select(Role).where(Role.code == "viewer")).id,
            status="active",
            otp_channel="manual",
        )
        db.add(employee)
        db.commit()
        viewer = employee
        cleanup = True
    else:
        cleanup = False

    try:
        with pytest.raises(ApiError) as exc:
            ai_tools.list_assets(db, viewer)
        assert exc.value.code == "mcp.forbidden"
    finally:
        if cleanup:
            db.delete(viewer)
            db.commit()


def test_unknown_actor_rejected(db):
    with pytest.raises(ApiError):
        ai_tools.resolve_actor(db, "999999")
