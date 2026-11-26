"""Тесты Спринта 25: JSON v5 — уставки 0.4 кВ, селективность, ЯКНО №2, 2× ф.16к."""

from __future__ import annotations

import json
import re
from pathlib import Path

JSON_PATH = Path(__file__).resolve().parents[1] / "seed_data" / "sketch_v5.json"


def _payload() -> dict:
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def _by_code(payload: dict) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for block in payload["blocks"]:
        result.setdefault(block["block"], []).append(block)
    return result


def test_v5_validation_clean():
    payload = _payload()
    assert payload["version"] == "5.0"
    validation = payload["validation"]
    assert validation["cable_issues"] == []
    assert validation["qf_issues"] == []
    assert validation["lv_issues"] == [], "уставки 0.4 кВ вводов должны проходить по сумме фидеров"
    assert validation["mark_issues"] == [], "марки связей должны совпадать с params"
    assert validation["loads_total_kw"] == 4280.0
    assert validation["ktp"]["ok"] is True
    assert validation["ktp"]["lv_inlet"] is True


def test_v5_04_inlet_settings_above_feeders():
    payload = _payload()
    blocks = _by_code(payload)
    for code in ("ktp_standard", "pktp_63", "pktp_standard", "pktp_630"):
        block = blocks[code][0]
        lv = block["params"]["lv_inlet"]["params"]
        currents = sum(
            float(f["params"].get("current_a") or 0) for f in block["params"]["feeders"]
        )
        setting = float(lv["qf_setting_a"])
        assert setting >= currents * 1.05, f"{code}: {setting} < {currents}"
        rating = float(re.search(r"(\d+)", lv["qf"]).group(1))
        assert setting <= rating, f"{code}: уставка выше номинала"

    ktp_lv = blocks["ktp_standard"][0]["params"]["lv_inlet"]["params"]
    assert ktp_lv["qf_setting_a"] >= 520
    pktp63_lv = blocks["pktp_63"][0]["params"]["lv_inlet"]["params"]
    assert pktp63_lv["qf_setting_a"] >= 85


def test_v5_yakno_cell_2_complete():
    payload = _payload()
    yakno = _by_code(payload)["yakno6"][0]
    feeders = yakno["params"]["feeders"]
    cell2 = next(item for item in feeders if item["name"].startswith("Ячейка №2"))
    params = cell2["params"]
    assert params.get("cable"), "у ячейки №2 нет кабеля"
    assert params.get("meter") == "Wh"
    assert params.get("qf_setting_a") == 125

    cell1 = next(item for item in feeders if item["name"].startswith("Ячейка №1"))
    cell3 = next(item for item in feeders if item["name"].startswith("Ячейка №3"))
    assert "ТТ 150/5" in cell1["name"] and cell1["params"]["ct"] == "ТТ 150/5"
    assert "ТТ 200/5" in cell3["name"] and cell3["params"]["ct"] == "ТТ 200/5"


def test_v5_feeder16_has_two_circuits_mark():
    payload = _payload()
    blocks = {block["id"]: block for block in payload["blocks"]}
    ps = _by_code(payload)["substation_35_6"][0]
    feeder = next(f for f in ps["params"]["feeders"] if f["name"].startswith("ф.16к"))
    assert feeder["params"]["cable"] == "2×СИП-3 3×240"

    link = next(
        link
        for link in payload["links"]
        if blocks[link["from"]["block"]]["title"].startswith("ПС")
        and link["cable_mark"] == "2×СИП-3 3×240"
    )
    assert link["type"] == "overhead"


def test_v5_ktp_l1_has_kva_margin():
    payload = _payload()
    ktp = _by_code(payload)["ktp_standard"][0]
    l1 = next(f for f in ktp["params"]["feeders"] if f["name"].startswith("Л-1"))
    assert l1["params"]["power_kva"] == 180
    assert l1["params"]["power_kva"] >= l1["params"]["power_kw"] / 0.8
    assert ktp["params"]["feeders"] and sum(
        float(f["params"].get("power_kva") or 0) for f in ktp["params"]["feeders"]
    ) == 343


def test_v5_simple_blocks_have_params():
    payload = _payload()
    blocks = _by_code(payload)
    recloser = blocks["recloser"][0]["params"]
    assert recloser.get("qs") and recloser.get("qf") and recloser.get("zn")
    pole = blocks["pole"][0]["params"]
    assert pole.get("grounding") == "ЗУ"
    yakno1 = blocks["yakno1"][0]["params"]
    assert yakno1.get("qs") and yakno1.get("ct")
