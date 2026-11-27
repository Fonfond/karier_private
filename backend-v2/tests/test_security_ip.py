"""Доверие X-Forwarded-For и ключ rate-limit (S-4).

Заголовок `X-Forwarded-For` — данные клиента, поэтому он принимается только от
адресов из `TRUSTED_PROXIES`. Иначе поддельный заголовок менял бы ключ лимита
(и IP в журнале аудита), т.е. позволял бы обойти антибрутфорс.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.rate_limit import client_ip, limiter
from app.core.config import settings


def _request(peer: str | None, xff: str | None = None):
    headers = {"x-forwarded-for": xff} if xff is not None else {}
    client = SimpleNamespace(host=peer) if peer is not None else None
    return SimpleNamespace(client=client, headers=headers)


# --- client_ip: unit-уровень ------------------------------------------------

def test_no_trusted_proxies_ignores_xff(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", "")
    assert client_ip(_request("10.0.0.5", "203.0.113.7")) == "10.0.0.5"


def test_trusted_proxy_takes_first_forwarded_ip(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", "10.0.0.5")
    request = _request("10.0.0.5", "203.0.113.7, 10.0.0.5")
    assert client_ip(request) == "203.0.113.7"


def test_trusted_proxy_by_cidr(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", "10.0.0.0/8,127.0.0.1")
    assert client_ip(_request("10.20.30.40", "198.51.100.9")) == "198.51.100.9"


def test_untrusted_peer_ignores_xff(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", "10.0.0.0/8")
    assert client_ip(_request("192.0.2.10", "203.0.113.7")) == "192.0.2.10"


def test_unknown_client_falls_back_to_unknown(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", "10.0.0.0/8")
    assert client_ip(_request(None, "203.0.113.7")) == "unknown"


def test_non_ip_entry_matches_exact(monkeypatch):
    # TestClient подключается как "testclient" — allowlist может содержать строку
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", "testclient")
    assert client_ip(_request("testclient", "203.0.113.7")) == "203.0.113.7"


# --- лимит входа: поддельный XFF не обходит ограничение ---------------------

def _login(client, tab_no: str, xff: str):
    return client.post(
        "/api/auth/login",
        json={"tab_no": tab_no, "password": "definitely-wrong"},
        headers={"X-Forwarded-For": xff},
    )


def test_forged_xff_does_not_bypass_login_limit(client, monkeypatch):
    """Без доверенного прокси все попытки идут с IP соединения → лимит срабатывает."""
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", "")
    monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN_PER_MINUTE", 2)
    limiter.reset()
    try:
        codes = [
            _login(client, f"X{i}", f"203.0.113.{i}").status_code for i in range(1, 4)
        ]
        assert codes[-1] == 429, codes
        assert codes[:2] != [429, 429]
    finally:
        limiter.reset()


def test_trusted_proxy_uses_forwarded_ip_as_limit_key(client, monkeypatch):
    """От доверенного прокси каждый XFF-IP — отдельный ключ лимита."""
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", "testclient")
    monkeypatch.setattr(settings, "RATE_LIMIT_LOGIN_PER_MINUTE", 2)
    limiter.reset()
    try:
        codes = [
            _login(client, f"Y{i}", f"198.51.100.{i}").status_code for i in range(1, 4)
        ]
        assert 429 not in codes, codes
    finally:
        limiter.reset()
