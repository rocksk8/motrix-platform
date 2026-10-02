# -*- coding: utf-8 -*-
"""33-A3 歷史相容（規格 §6.1 金標準）：沒有連結、沒有材料申請、沒有 offsets 的案件，新端點的 `itemActualTotal`／`extraTotal` 與舊 `calcSummary()` 逐位相同。
`legacy_*` ＝逐字照搬 settlement.html 的 `calcItemCost()`／`calcSummary()` 相關段（不經過任何新程式）。
語料：預設估計、手填實際（含稅三種）、額外支出各狀態、已存草稿缺 `adoptSystem`（正式機 3 張）、缺說明的舊品項（正式機 1 個）、已完結凍結。"""
import json

import pytest

import db
from helpers.legal_params import round_half_up
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W, _ln, _mk, _submit  # noqa: F401
from modules.case.tests.test_settlement_actuals_2026_10_03 import _get, _put_settlement


def legacy_item_cost(qty, unit_cost, mode):
    """settlement.html calcItemCost（非採用路徑）"""
    raw = round_half_up(qty or 0, unit_cost or 0)
    if mode == "taxed":
        return round_half_up(raw / 1.05)
    if mode == "taxed_gross":
        return round_half_up(raw, 1.05)
    return raw


def legacy_item_total(quotation_items, saved_items):
    """舊頁：settlement.items＝報價品項（非標題）；有存檔的取存檔 actualTotalCost，沒有的取預設（報價成本 ×1.05）；itemPoUnadopted 無連結＝0。"""
    saved = {str(i.get("id")): i for i in saved_items or [] if isinstance(i, dict)}
    tot = 0
    for it in quotation_items:
        if it.get("type") == "header":
            continue
        s = saved.get(str(it.get("id")))
        if s is not None and s.get("actualTotalCost"):                   # 頁面載入存檔：si.actualTotalCost || oi.actualTotalCost（0／空＝沒填 ⇒ 預設估計）
            tot += s["actualTotalCost"]
        else:
            tot += round_half_up((it.get("qty") or 0) * (it.get("cost") or 0), 1.05)
    return tot


def _quotation_items():
    cn = db.get_db()
    try:
        return json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])["items"]
    finally:
        cn.close()


def _legacy_extra_total(c, h):
    r = c.get("/api/quotations/%s/extra-expenses" % NO, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["totalAmount"]                                    # 舊頁 xeTotal（沒有連結列時＝extraOnlyAmount）


def _assert_parity(c, h, saved_items):
    d = _get(c, h)
    assert d["totals"]["itemActualTotal"] == legacy_item_total(_quotation_items(), saved_items)
    assert d["totals"]["extraTotal"] == _legacy_extra_total(c, h)
    assert d["totals"]["itemPoUnadopted"] == 0 and d["totals"]["materialUnassignedTotal"] == 0 and d["sources"]["po"] == 0
    return d


def test_default_estimates_nothing_saved(W):
    c, h = W
    _assert_parity(c, h, [])


@pytest.mark.parametrize("mode", ["", "taxed", "taxed_gross"])
def test_manual_actuals_in_all_three_tax_modes(W, mode):
    c, h = W
    saved = [{"id": "a", "adoptSystem": False, "actualQty": 7, "actualUnitCost": 1234.5, "actualCostTaxMode": mode,
              "actualTotalCost": legacy_item_cost(7, 1234.5, mode)},
             {"id": "b", "adoptSystem": False, "actualQty": 3, "actualUnitCost": 17, "actualCostTaxMode": mode, "actualTotalCost": legacy_item_cost(3, 17, mode)}]
    _put_settlement({"status": "draft", "items": saved})
    d = _assert_parity(c, h, saved)
    assert all(i["actual"]["source"] == "manual" for i in d["items"])      # 正對照：真的走了手填路徑，不是估計碰巧相等


def test_extra_expenses_in_several_states_equal_the_legacy_total(W):
    c, h = W
    a = _mk(c, h, "purchase_order", [_ln(None, 2, unitCost=333)]).json()
    assert _submit(c, h, a["id"]).status_code == 200
    _mk(c, h, "purchase_order", [_ln(None, 1, unitCost=999)])             # 草稿
    d = _assert_parity(c, h, [])
    assert d["totals"]["extraTotal"] == 666                                # 正對照：已核准的算、草稿不算


def test_saved_draft_without_adopt_key_matches_legacy(W):
    c, h = W
    saved = [{"id": "a", "actualTotalCost": 9000}, {"id": "b", "actualQty": 4, "actualUnitCost": 10, "actualCostTaxMode": "", "actualTotalCost": 40}]   # 第 32 班前存的（無 adoptSystem）
    _put_settlement({"status": "draft", "items": saved})
    d = _assert_parity(c, h, saved)
    assert d["legacySave"] is True and all(i["adopt"] is False for i in d["items"])


def test_old_item_without_description_or_id_is_counted_like_the_old_page(W):
    c, h = W
    cn = db.get_db()
    q = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
    q["items"] += [{"id": "n1", "description": "", "qty": 3, "cost": 100}, {"description": "無 id", "qty": 2, "cost": 70}, {"type": "header", "description": "標題"}]
    cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(q), NO))
    cn.commit()
    cn.close()
    d = _assert_parity(c, h, [])
    assert sum(1 for i in d["items"] if i["unkeyed"]) == 2


def test_finalized_case_keeps_the_frozen_numbers(W):
    c, h = W
    saved = [{"id": "a", "adoptSystem": False, "actualTotalCost": 12345}, {"id": "b", "adoptSystem": False, "actualTotalCost": 77}]
    _put_settlement({"status": "finalized", "items": saved, "summary": {"itemActualTotal": 12422, "extraTotal": 0, "purchasedTotal": 0}})
    d = _get(c, h)
    assert d["frozen"] is True and d["totals"]["itemActualTotal"] == 12422 == legacy_item_total(_quotation_items(), saved)


@pytest.mark.parametrize("zero", [0, "", None, 0.0])
def test_saved_actual_of_zero_or_blank_means_not_filled_like_the_page(W, zero):
    c, h = W
    saved = [{"id": "a", "adoptSystem": False, "actualTotalCost": zero}, {"id": "b", "adoptSystem": False, "actualTotalCost": 525}]
    _put_settlement({"status": "draft", "items": saved})
    d = _assert_parity(c, h, saved)
    a = [i for i in d["items"] if i["itemId"] == "a"][0]
    assert a["actual"] == {"amount": 10500, "source": "estimate", "replacedEstimate": False}     # 0 ⇒ 估計（今天頁面的 `||` 語意）；正對照：b 的 525 照用


def test_finalized_frozen_with_a_zero_item_uses_the_same_rule(W):
    c, h = W
    saved = [{"id": "a", "adoptSystem": False, "actualTotalCost": 0}, {"id": "b", "adoptSystem": False, "actualTotalCost": 525}]
    _put_settlement({"status": "finalized", "items": saved, "summary": {"itemActualTotal": 11025}})
    d = _get(c, h)
    assert d["frozen"] is True and [i for i in d["items"] if i["itemId"] == "a"][0]["actual"]["amount"] == 10500


@pytest.mark.parametrize("fields,expect_a", [
    ({"actualQty": 0, "actualUnitCost": 1000, "actualTotalCost": 777}, 777),      # 頁面載入只讀 actualTotalCost；數量／單價為 0 不影響已存的總額
    ({"actualQty": 10, "actualUnitCost": 0, "actualTotalCost": 777}, 777),
    ({"actualQty": 0, "actualUnitCost": 0, "actualTotalCost": 0}, 10500),          # 全 0 ⇒ 沒填 ⇒ 估計
    ({"actualQty": 10, "actualUnitCost": 0, "actualTotalCost": 0}, 10500),
    ({"actualQty": 0, "actualUnitCost": 1000, "actualTotalCost": 0}, 10500),
])
def test_zero_qty_or_unit_cost_in_saved_items_follow_the_pages_total_only_rule(W, fields, expect_a):
    c, h = W
    saved = [dict({"id": "a", "adoptSystem": False, "actualCostTaxMode": "taxed_gross"}, **fields)]
    _put_settlement({"status": "draft", "items": saved})
    d = _assert_parity(c, h, saved)
    assert [i for i in d["items"] if i["itemId"] == "a"][0]["actual"]["amount"] == expect_a
