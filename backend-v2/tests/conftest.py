"""Pytest-фикстуры: клиент API поверх тестовой БД."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402


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
