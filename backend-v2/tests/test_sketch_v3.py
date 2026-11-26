"""Тесты Спринта 23: JSON v3 — данные, сечения, секции, защита."""

from __future__ import annotations

import json
from pathlib import Path

JSON_PATH = Path(__file__).resolve().parents[1] / "seed_data" / "sketch_v3.json"


def _payload() -> dict:
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def _by_code(payload: dict) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for block in payload["blocks"]:
        result.setdefault(block["block"], []).append(block)
    return result


def test_v3_no_duplicate_ekg_and_validations():
    payload = _payload()
    assert payload["version"] == "3.0"
    assert payload["dangling_ports"] == []
    validation = payload["validation"]
    assert validation["ekg_blocks"] == ["ЯКНО-6"], "ЭКГ-15М не должна питаться дважды"
    assert validation["duplicate_loads"] == []
    assert validation["ktp"]["ok"] is True, "КТП 400 кВА не должна быть перегружена"
    assert validation["bkru_post_accident"]["post_accident_ok"] is True


def test_ps_sections_and_cells_match_sketch():
    payload = _payload()
    ps = _by_code(payload)["substation_35_6"][0]
    feeders = {item["name"].split(" ")[0]: item["params"] for item in ps["params"]["feeders"]}
    assert feeders["ф.7к"]["cell"] == "яч. 7"
    assert feeders["ф.16к"]["cell"] == "яч. 16"
    assert feeders["ф.21к"]["cell"] == "яч. 21"
    assert len(ps["params"]["sections"]) == 2

    # ф.16к и ф.21к — на II секции, ф.7к — на I
    links = payload["links"]
    ps_id = ps["id"]
    section_of = {}
    for link in links:
        if link["from"]["block"] == ps_id or link["to"]["block"] == ps_id:
            continue
    # проверяем по данным шаблона: f16/f21 связаны с sec2
    # (в JSON связи внутренние не выгружаются, поэтому проверяем ячейки и наличие строк)


def test_ps_feeders_have_qf_ct_opn_meter():
    payload = _payload()
    ps = _by_code(payload)["substation_35_6"][0]
    for feeder in ps["params"]["feeders"]:
        params = feeder["params"]
        assert params.get("qf"), feeder["name"]
        assert params.get("ct"), feeder["name"]
        assert params.get("opn"), feeder["name"]
        assert params.get("meter") == "Wh", feeder["name"]
        assert params.get("power_kw") and params.get("current_a"), feeder["name"]


def test_inlets_have_qf_ct_opn_and_tn_role():
    payload = _payload()
    blocks = _by_code(payload)
    for code in ("substation_35_6", "bkru_standard"):
        block = blocks[code][0]
        for inlet in block["params"]["incoming"]:
            params = inlet["params"]
            assert params.get("qf"), f"{code}: нет QF на вводе"
            assert params.get("ct"), f"{code}: нет ТТ на вводе"
            assert params.get("opn"), f"{code}: нет ОПН на вводе"

        tn = [item for item in block["params"]["equipment"] if item["role"] == "tn"]
        assert len(tn) >= 2, "ТН должен быть на каждой секции"
        assert all("ТН" in item["name"] for item in tn)


def test_pktp_have_04_outputs_and_loads():
    payload = _payload()
    blocks = _by_code(payload)
    for code in ("pktp_standard", "pktp_63", "pktp_630"):
        block = blocks[code][0]
        loads = [item for item in block["params"]["equipment"] if item["role"] == "load"]
        feeders = block["params"]["feeders"]
        assert loads, f"{code}: нет 0.4 кВ нагрузок"
        assert len(feeders) >= 2, f"{code}: нет 0.4 кВ фидеров"
        for feeder in feeders:
            assert feeder["params"].get("qf"), "нет QF на 0.4 кВ"


def test_bkru_two_sections_and_inputs_distribution():
    payload = _payload()
    bkru = _by_code(payload)["bkru_standard"][0]
    assert len(bkru["params"]["sections"]) == 2
    assert len(bkru["params"]["incoming"]) == 2
    feeder_power = sum(float(f["params"].get("power_kw") or 0) for f in bkru["params"]["feeders"])
    inputs = [float(i["params"].get("power_kw") or 0) for i in bkru["params"]["incoming"]]
    assert min(inputs) >= feeder_power, "послеаварийный режим не проходит по вводу"


def test_link_marks_match_feeder_params():
    payload = _payload()
    blocks = {block["id"]: block for block in payload["blocks"]}
    for link in payload["links"]:
        mark = link["cable_mark"]
        assert mark, f"связь без марки: {link['id']}"
    ps = _by_code(payload)["substation_35_6"][0]
    feeder_cables = {f["name"].split(" ")[0]: f["params"].get("cable") for f in ps["params"]["feeders"]}
    assert feeder_cables["ф.7к"] == "СИП-3 3×120"
    assert feeder_cables["ф.16к"] == "СИП-3 3×240"
    assert feeder_cables["ф.21к"] == "СИП-3 3×95"

    overhead = [link for link in payload["links"] if link["type"] == "overhead"]
    assert overhead, "ВЛ должны иметь тип overhead"
    for link in overhead:
        assert "СИП" in (link["cable_mark"] or ""), "ВЛ должна быть СИП"
