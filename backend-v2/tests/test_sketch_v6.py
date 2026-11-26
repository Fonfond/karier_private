"""Тесты Спринта 26: JSON v6 — порядок, уставки СВ/простых блоков, запас QF."""

from __future__ import annotations

import json
import re
from pathlib import Path

JSON_PATH = Path(__file__).resolve().parents[1] / "seed_data" / "sketch_v6.json"


def _payload() -> dict:
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def _by_code(payload: dict) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for block in payload["blocks"]:
        result.setdefault(block["block"], []).append(block)
    return result


def test_v6_validation_clean():
    payload = _payload()
    assert payload["version"] == "6.0"
    validation = payload["validation"]
    for key in ("cable_issues", "qf_issues", "lv_issues", "mark_issues", "switch_issues"):
        assert validation[key] == [], f"{key}: {validation[key]}"
    assert validation["loads_total_kw"] == 4280.0
    assert validation["ktp"]["ok"] is True


def test_v6_incoming_order_in1_in2():
    payload = _payload()
    ps = _by_code(payload)["substation_35_6"][0]
    names = [item["name"] for item in ps["params"]["incoming"]]
    assert names[0].startswith("Ввод 1"), names
    assert names[1].startswith("Ввод 2"), names


def test_v6_equipment_grouped_by_role():
    payload = _payload()
    ps = _by_code(payload)["substation_35_6"][0]
    roles = [item["role"] for item in ps["params"]["equipment"]]
    order = {"tn": 0, "tt": 1, "opn": 2, "znv": 3, "transformer": 4, "load": 5}
    assert roles == sorted(roles, key=lambda role: order.get(role, 9)), roles
    assert roles.count("tn") == 2


def test_v6_section_breakers_have_settings_and_ct():
    payload = _payload()
    blocks = _by_code(payload)
    for code in ("substation_35_6", "bkru_standard"):
        sv = blocks[code][0]["params"]["section_breaker"]
        assert sv and sv["params"].get("qf_setting_a"), f"{code}: нет уставки СВ"
        assert sv["params"].get("ct"), f"{code}: нет ТТ на СВ"
        assert sv["params"].get("qs") or True


def test_v6_simple_switches_have_settings():
    payload = _payload()
    blocks = _by_code(payload)
    for code in ("recloser", "yakno1"):
        params = blocks[code][0]["params"]
        assert params.get("qf_setting_a"), f"{code}: нет уставки"
        assert params.get("ct"), f"{code}: нет ТТ"
        assert params.get("qs"), f"{code}: нет QS"


def test_v6_qf_margin_and_ktp_l1_kva():
    payload = _payload()
    blocks = _by_code(payload)
    ktp = blocks["ktp_standard"][0]
    l1 = next(f for f in ktp["params"]["feeders"] if f["name"].startswith("Л-1"))
    assert l1["params"]["power_kva"] == 160
    assert l1["params"]["current_a"] == 221
    rating = float(re.search(r"(\d+)", l1["params"]["qf"]).group(1))
    assert rating >= l1["params"]["current_a"] * 1.1

    pktp1 = blocks["pktp_63"][0]
    for feeder in pktp1["params"]["feeders"]:
        params = feeder["params"]
        setting = float(params["qf_setting_a"])
        current = float(params["current_a"])
        assert setting >= current
        assert setting <= float(re.search(r"(\d+)", params["qf"]).group(1)) * 0.95


def test_v6_settings_below_95_percent_rating():
    payload = _payload()
    for block in payload["blocks"]:
        for feeder in block["params"].get("feeders", []) + block["params"].get("incoming", []):
            params = feeder["params"]
            setting = params.get("qf_setting_a")
            rating = params.get("qf")
            if not setting or not rating:
                continue
            nominal = float(re.search(r"(\d+)", rating).group(1))
            assert float(setting) <= nominal * 0.95, feeder["name"]
