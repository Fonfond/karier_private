"""Pytest-фикстуры: клиент API поверх тестовой БД."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from sqlalchemy import text  # noqa: E402


@pytest.fixture(autouse=True)
def heal_topology():
    """Перед каждым тестом возвращаем схему в эталонное состояние.

    Тесты переключают ячейки и связи, поэтому без этого они влияли бы друг на друга.
    """
    db = SessionLocal()
    try:
        db.execute(
            text(
                "update gis.assets set status='on', grounded=false "
                "where code in ('BKRU1-IN1','BKRU1-OUT1','BKRU1-OUT2','BKRU1-OUT3')"
            )
        )
        db.execute(
            text("update gis.assets set status='off', grounded=false where code in ('BKRU1-IN2','BKRU1-SEC')")
        )
        db.execute(
            text("update gis.assets set status='on', grounded=false where code='KTP-14'")
        )
        db.execute(text("update gis.links set state='connected' where deleted_at is null"))
        db.execute(
            text(
                "update gis.links set state='open' "
                "where deleted_at is null and (link_type='jumper' or feed_role='backup')"
            )
        )
        db.commit()
    finally:
        db.close()
    yield


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def admin_tokens(client: TestClient) -> dict:
    response = client.post("/api/auth/login", json={"tab_no": "000001", "password": "admin"})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(scope="session")
def admin_headers(admin_tokens: dict) -> dict:
    return {"Authorization": f"Bearer {admin_tokens['access_token']}"}


@pytest.fixture(scope="session")
def operator_secret() -> str:
    return os.environ.get("TEST_TOTP_SECRET", "VIKFSSCEEHU4M2CQCPAQYCZAMMUYCZIH")
