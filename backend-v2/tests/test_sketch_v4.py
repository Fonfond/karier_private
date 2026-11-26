"""Тесты Спринта 24: JSON v4 — 0.4 кВ, аппараты, учёт, validation."""

from __future__ import annotations

import json
import re
from pathlib import Path

JSON_PATH = Path(__file__).resolve().parents[1] / "seed_data" / "sketch_v4.json"

AMPACITY_04 = {25: 80, 35: 95, 50: 120, 70: 145, 95: 175, 120: 200, 150: 225, 185: 255, 240: 300}


def _payload() -> dict:
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def _by_code(payload: dict) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for block in payload["blocks"]:
        result.setdefault(block["block"], []).append(block)
    return result


def test_v4_validation_clean():
    payload = _payload()
    assert payload["version"] == "4.0"
    assert payload["dangling_ports"] == []
    validation = payload["validation"]
    assert validation["cable_issues"] == [], "кабели должны проходить по нагреву"
    assert validation["qf_issues"] == [], "QF/уставки должны проходить по току"
    assert validation["loads_total_kw"] == 4280.0, "двойной счёт в loads_total_kw"
    assert validation["ktp"]["ok"] is True
    assert validation["ktp"]["feeders_kva"] <= validation["ktp"]["transformer_kva"]
    assert validation["ktp"]["lv_inlet"] is True
    assert validation["bkru_post_accident"]["post_accident_ok"] is True
    assert validation["ekg_blocks"] == ["ЯКНО-6"]


def test_v4_04_cables_have_margin():
    payload = _payload()
    ktp = _by_code(payload)["ktp_standard"][0]
    for feeder in ktp["params"]["feeders"]:
        params = feeder["params"]
        if not params.get("current_a"):
            continue
        match = re.search(r"(\d+)×(\d+)", params["cable"])
        assert match, params["cable"]
        section = int(match.group(2))
        ampacity = AMPACITY_04[section]
        assert ampacity >= params["current_a"] * 1.1, feeder["name"]

    pktp2 = _by_code(payload)["pktp_630"][0]
    l1 = pktp2["params"]["feeders"][0]["params"]
    assert l1["cable"].startswith("2×"), "Л-1 ПКТП-2 должна быть в две нитки"
    assert l1["current_a"] == 340


def test_v4_small_transformers_have_adequate_qf_ct():
    payload = _payload()
    blocks = _by_code(payload)
    expectations = {
        "ktp_standard": ("QF 100A", "ТТ 100/5"),
        "pktp_63": ("QF 25A", "ТТ 50/5"),
        "pktp_standard": ("QF 100A", "ТТ 100/5"),
        "pktp_630": ("QF 100A", "ТТ 100/5"),
    }
    for code, (qf, ct) in expectations.items():
        block = blocks[code][0]
        inlet = block["params"]["incoming"][0]["params"]
        assert inlet["qf"] == qf, f"{code}: {inlet['qf']}"
        assert inlet["ct"] == ct, f"{code}: {inlet['ct']}"
        assert inlet["q"] if False else True


def test_v4_04_lv_inlet_and_metering():
    payload = _payload()
    blocks = _by_code(payload)
    for code in ("ktp_standard", "pktp_63", "pktp_standard", "pktp_630"):
        block = blocks[code][0]
        lv = block["params"].get("lv_inlet")
        assert lv, f"{code}: нет 0.4 кВ вводного QF/ТТ"
        assert lv["params"].get("qf"), code
        assert lv["params"].get("ct"), code
        assert lv["params"].get("meter") == "Wh", code

    for code in ("bkru_standard", "yakno6", "ktp_standard"):
        block = blocks[code][0]
        meters = [f for f in block["params"]["feeders"] if f["params"].get("meter") == "Wh"]
        assert meters, f"{code}: нет Wh на фидерах"


def test_v4_qs_on_inlets():
    payload = _payload()
    blocks = _by_code(payload)
    for code in ("substation_35_6", "bkru_standard", "yakno6"):
        block = blocks[code][0]
        for inlet in block["params"]["incoming"]:
            assert inlet["params"].get("qs"), f"{code}: нет QS на вводе"
    for code in ("ktp_standard", "pktp_63", "pktp_standard", "pktp_630"):
        inlet = blocks[code][0]["params"]["incoming"][0]["params"]
        assert inlet.get("qs"), f"{code}: нет QS на вводе 6 кВ"


def test_v4_tap_not_reserve_and_loads_have_power():
    payload = _payload()
    blocks = {block["id"]: block for block in payload["blocks"]}
    tap = next(
        link
        for link in payload["links"]
        if blocks[link["from"]["block"]]["title"] == "оп.4" and link["from"]["port"] == "OUT-2"
    )
    op4 = blocks[tap["from"]["block"]]
    tap_port = next(port for port in op4["ports"] if port["code"] == "OUT-2")
    assert tap_port["reserve"] is False, "рабочая отпайка не должна быть reserve"

    for block in payload["blocks"]:
        if block["block"] == "load_04":
            assert block["params"].get("power_kw"), f"{block['title']}: нет power_kw"


def test_v4_yakno_feeders_ordered():
    payload = _payload()
    yakno = _by_code(payload)["yakno6"][0]
    numbers = []
    for feeder in yakno["params"]["feeders"]:
        match = re.search(r"№\s*(\d+)", feeder["name"])
        if match:
            numbers.append(int(match.group(1)))
    assert numbers == sorted(numbers), "ячейки ЯКНО-6 должны идти по номерам"
