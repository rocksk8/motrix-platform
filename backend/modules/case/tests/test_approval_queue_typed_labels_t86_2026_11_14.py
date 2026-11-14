# -*- coding: utf-8 -*-
"""T86 #19：綁案件的費用單據（請購單／採購單…）在簽核佇列與首頁摘要要顯示單據類型與單據編號。

過去綁案件的請購單在佇列上被標成「案件支出申請」、單號顯示 `MQ-…-XE1`（沒有類型、沒有單據編號）；只有不綁案件的單據有 `typeLabel`。
驗：
- 綁案件的類型化單據：`typeLabel`＝單據類型、`displayNo`＝單據編號；`quoteNo` 不變（路由與詳情仍用它）。
- 變更申請：只補 `displayNo`（單據編號＋「改」），不把類型名稱當成變更的標籤。
- 沒有類型的舊額外支出（kind=''）：不多出任何鍵（回應與過去相同）。
- 首頁摘要（`_item_type_label`）：認案件模組自己的 `docKindLabel`；別的模組給的 `typeLabel` 仍不能覆寫內建標籤。
"""
import json

import pytest

NO = "MQ-T86-19"
APPR = {"requestedBy": "u", "requestedByDisplay": "u", "requestedAt": "2026-11-14T10:00:00",
        "tiers": [{"order": 0, "approvers": [{"username": "boss", "display_name": "b"}]}], "currentTier": 0}


def _seed(kind, doc_code, status="待審核", change=False):
    import db
    c = db.get_db()
    try:
        if not c.execute("SELECT 1 FROM quotations WHERE quote_no=?", (NO,)).fetchone():
            c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (NO, "已送出", "測客", "測專", 1000, 952, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))
        cols = "(quote_no, category, description, qty, unit, unit_cost, total_cost, expense_date, files_json, created_by_name, created_at, updated_at, status, kind, doc_code, approval_json"
        vals = [NO, "其他", "測試單", 1, "", 100, 100, "2026-11-14", "[]", "u", "2026-11-14", "2026-11-14", status, kind, doc_code, json.dumps(APPR)]
        if change:
            cols += ", change_json, change_approval_json, change_status"
            vals += [json.dumps({"description": "新說明", "totalCost": 120}), json.dumps(APPR), "待審核"]
        cur = c.execute("INSERT INTO case_extra_expenses %s) VALUES (%s)" % (cols, ",".join("?" * len(vals))), vals)
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def _items(eid):
    import db
    from modules.case.api import quotations as Q
    c = db.get_db()
    try:
        return [i for i in Q.approval_queue_items(c) if i.get("extraExpenseId") == eid]
    finally:
        c.close()


def test_case_bound_typed_doc_has_type_label_and_doc_code(client):
    eid = _seed("purchase_req", "PR-20261114-0001")
    (it,) = [i for i in _items(eid) if i["type"] == "extra_expense"]
    assert it["typeLabel"] == "請購單" and it["displayNo"] == "PR-20261114-0001"
    assert it["quoteNo"] == "%s-XE%d" % (NO, eid), "路由與詳情仍用 quoteNo，不能動"
    assert it["linkedQuoteNo"] == NO and "caseless" not in it
    assert it["docKindLabel"] == "請購單"


def test_each_kind_gets_its_own_label(client):
    for kind, label in (("purchase_order", "採購單"), ("travel", "差旅費用請款單"), ("petty_cash", "零用金支付單")):
        eid = _seed(kind, "X-%s" % kind)
        (it,) = [i for i in _items(eid) if i["type"] == "extra_expense"]
        assert it["typeLabel"] == label and it["displayNo"] == "X-%s" % kind


def test_change_request_only_gets_display_no(client):
    eid = _seed("purchase_order", "PO-20261114-0002", status="已核准", change=True)
    (it,) = [i for i in _items(eid) if i["type"] == "extra_expense_change"]
    assert it["displayNo"] == "PO-20261114-0002改"
    assert "typeLabel" not in it and "docKindLabel" not in it, "變更申請的標籤仍是「支出申請變更」"


def test_legacy_untyped_extra_expense_is_unchanged(client):
    eid = _seed("", "")
    (it,) = [i for i in _items(eid) if i["type"] == "extra_expense"]
    assert "typeLabel" not in it and "displayNo" not in it and "docKindLabel" not in it


def test_home_summary_label_uses_doc_kind_but_other_modules_cannot_override():
    from routers import approval_queue as aq
    assert aq._item_type_label({"type": "extra_expense", "docKindLabel": "請購單"}) == "請購單"
    assert aq._item_type_label({"type": "extra_expense"}) == "案件支出申請"
    assert aq._item_type_label({"type": "extra_expense", "typeLabel": "別的"}) == "案件支出申請"      # 別的模組借 typeLabel 仍覆寫不了內建
    assert aq._item_type_label({"type": "extra_expense_change", "docKindLabel": "請購單"}) == "支出申請變更"
