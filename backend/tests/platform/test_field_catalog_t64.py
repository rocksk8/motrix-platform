# -*- coding: utf-8 -*-
"""T64 F7 S0：共用欄位目錄（`helpers/field_catalog.py`）——『衍生清單＝今天的清單』金標＋與匯出／版面登記互核。

零行為變更：`financial_mask` 的 6 份清單改由目錄衍生，本檔把**切片前的字面值**寫死在這裡（改目錄卻動到今天的鍵名／順序 ⇒ 紅）。
"""
import json
from pathlib import Path

from helpers import export_templates as ET
from helpers import field_catalog as FC
from helpers import financial_mask as FM
import modules.analytics.api.reports  # noqa: F401  登記匯出
import modules.arap.api.cashier  # noqa: F401
import modules.arap.api.invoice_vouchers  # noqa: F401
import modules.case.api.quotations  # noqa: F401
import modules.case.completion_pdf  # noqa: F401
import modules.daily_tasks.api  # noqa: F401
import modules.subcontract.api.contractors  # noqa: F401
import helpers.clause_titles  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]

# ── 切片前的字面值（2026-10-15，origin/train/t63-int 26a0a07d4 的 financial_mask）──
TODAY_QUOTATION_MONEY_COLS = ("total", "pretax", "direct_margin_pct", "net_margin_pct", "project_margin_pct")
TODAY_ITEM_MONEY_KEYS = ("cost", "margin", "unitPrice", "amount")
TODAY_QUOTE_MONEY_KEYS = ("discount", "freight", "indirectLogistics", "indirectInstallation",
                          "indirectTravel", "indirectWarranty", "indirectOther", "tot", "overheadPct")
TODAY_PAYMENT_MONEY_KEYS = ("amount", "pct", "actualAmount", "feeAmount", "feeNote", "invoicePretax", "invoiceTax")
TODAY_MATERIAL_ORDER_MONEY_KEYS = ("unitPrice", "totalPrice", "paidAmount", "totalAmount")
TODAY_HISTORY_MONEY_FIELDS = {"含稅總額", "未稅金額", "直接毛利率", "淨利率", "營業利益率", "管銷分攤比率"}


def test_derived_mask_lists_equal_todays_lists_exactly():
    assert FM.QUOTATION_MONEY_COLS == TODAY_QUOTATION_MONEY_COLS
    assert FM.ITEM_MONEY_KEYS == TODAY_ITEM_MONEY_KEYS
    assert FM.QUOTE_MONEY_KEYS == TODAY_QUOTE_MONEY_KEYS
    assert FM.PAYMENT_MONEY_KEYS == TODAY_PAYMENT_MONEY_KEYS
    assert FM.MATERIAL_ORDER_MONEY_KEYS == TODAY_MATERIAL_ORDER_MONEY_KEYS
    assert FM.HISTORY_MONEY_FIELDS == TODAY_HISTORY_MONEY_FIELDS
    for v in (FM.QUOTATION_MONEY_COLS, FM.ITEM_MONEY_KEYS, FM.QUOTE_MONEY_KEYS, FM.PAYMENT_MONEY_KEYS, FM.MATERIAL_ORDER_MONEY_KEYS):
        assert isinstance(v, tuple)                                     # 型別也與今天相同（元組，順序有意義）
    assert isinstance(FM.HISTORY_MONEY_FIELDS, set)


def test_the_catalog_is_internally_consistent():
    assert FC.problems() == []


def test_positive_control_problems_catches_a_broken_catalog(monkeypatch):
    broken = list(FC.FIELDS) + [dict(FC.FIELDS[0]), dict(FC.FIELDS[0], id="x.y", family="nope", ceiling="nope", derivedFrom=("zzz",))]
    monkeypatch.setattr(FC, "FIELDS", tuple(broken))
    msgs = " | ".join(FC.problems())
    assert "欄位代號重複" in msgs and "家族不在清單內" in msgs and "天花板不在清單內" in msgs and "derivedFrom 指向不存在" in msgs


def test_margin_fields_depend_on_cost():
    """家族規則的地基：每個毛利類欄位都要宣告反推來源（之後政策才擋得住『毛利比成本寬』）。"""
    for f in FC.FIELDS:
        if f["family"] == "margin":
            assert f["derivedFrom"], f["id"]


def test_export_registry_and_catalog_agree_both_directions():
    assert FC.export_problems(ET.registered()) == []


def test_positive_control_export_check_catches_both_directions():
    reg = ET.registered()
    missing_entry = {k: dict(v) for k, v in reg.items()}
    missing_entry["x:new"] = {"columns": [{"id": "cost", "label": "成本", "money": True}], "sheets": []}
    assert any("沒有登記在欄位目錄" in m for m in FC.export_problems(missing_entry))
    no_such = {k: v for k, v in reg.items() if k != "case:case-batch"}
    assert any("沒有登記" in m for m in FC.export_problems(no_such))
    not_money = {k: dict(v) for k, v in reg.items()}
    not_money["case:case-batch"] = dict(reg["case:case-batch"], columns=[dict(c, money=False) for c in reg["case:case-batch"]["columns"]])
    assert any("不是含金額" in m for m in FC.export_problems(not_money))


def _case_points():
    m = json.loads((ROOT / "modules" / "case" / "module.json").read_text(encoding="utf-8"))
    pts = []
    for entity, flist in (m.get("customization", {}).get("fields") or {}).items():
        for f in flist:
            pts.append({"id": "case:%s/%s" % (entity, f["key"]), "kind": "field", "entity": entity, "field": f["key"]})
    return pts


def test_layout_field_points_named_by_the_catalog_exist():
    assert FC.screen_problems(_case_points()) == []


def test_positive_control_screen_check_catches_a_missing_point():
    pts = [p for p in _case_points() if not (p["entity"] == "case" and p["field"] == "amount")]
    assert any("case/case/amount" in m for m in FC.screen_problems(pts))


def test_returned_fields_are_copies():
    a = FC.fields()
    a[0]["label"] = "被改了"
    a[0]["api"] = None
    assert FC.fields()[0]["label"] == "含稅總額" and FC.api_keys("quotation_cols") == TODAY_QUOTATION_MONEY_COLS
    assert FC.by_id("nope") is None and FC.by_id("quote_item.cost")["family"] == "cost"
