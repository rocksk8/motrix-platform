# -*- coding: utf-8 -*-
"""33-M2b：材料申請變更申請的端點、簽核佇列／詳情提供者、通知、`use_change_request` 守門。狀態機本身見 test_material_change_core_2026_10_03。"""
import json

import pytest

import db
from helpers import tiered_approval as TA
from modules.case import material_approval as MA
from modules.case import material_change as MC
from modules.case.api import material_changes as API
from modules.case.tests.test_material_change_core_2026_10_03 import (  # noqa: F401
    IID, LINE1, LINE2, NO, W, _cp, _flow, _one_tier, _order, _order_now, _setup, reg, ENG, BOSS)

BASE = "/api/quotations/%s/material-orders/%s" % (NO, IID)


@pytest.fixture
def fake_proposal(monkeypatch):
    """案件側提案（2e 的 change_proposal）以假函式代替：qty 3、小計 3000、涵蓋兩行。"""
    def fn(conn, quote_no, item_id, proposed):
        cp = _cp()
        if "quantity" in (proposed or {}):
            cp["after"]["quantity"] = float(proposed["quantity"])
            cp["after"]["totalPrice"] = 1000.0 * float(proposed["quantity"])
        if "notes" in (proposed or {}):
            cp["after"]["notes"] = proposed["notes"]
        return cp
    monkeypatch.setattr(MC, "PROPOSAL_FN", fn)
    return fn


def _post(c, h, path, body=None):
    return c.post(path, headers=h, json=body or {})


def test_create_list_submit_auto_approve_and_apply_over_http(W, reg, fake_proposal):
    c, h = W
    _flow([])
    _setup(received="2026-10-04")
    r = _post(c, h, BASE + "/changes", {"reason": "追加一台"})
    assert r.status_code == 200, r.text
    ch = r.json()["change"]
    assert ch["status"] == "草稿" and ch["docCode"].startswith("MC-") and [d["field"] for d in ch["diff"]] == ["quantity", "totalPrice", "poSnapshot"]
    assert _order_now(db.get_db())["quantity"] == 2                                              # 草稿：原版不動
    lst = c.get(BASE + "/changes", headers=h).json()["changes"]
    assert [x["id"] for x in lst] == [ch["id"]]
    s = _post(c, h, "/api/quotations/%s/material-changes/%d/submit" % (NO, ch["id"]))
    assert s.status_code == 200 and s.json()["autoApproved"] and s.json()["applied"], s.text
    cn = db.get_db()
    try:
        assert _order_now(cn)["quantity"] == 3.0 and MA.get(cn, NO, IID)["version"] == 2 and MA.get(cn, NO, IID)["received_on"] == "2026-10-04"
    finally:
        cn.close()
    assert c.get(BASE + "/changes", headers=h).json()["changes"][0]["status"] == "已核准"


def test_create_rejects_amount_fields_missing_reason_and_unavailable_proposal(W, reg, monkeypatch, fake_proposal):
    c, h = W
    _setup()
    for body, code in (({"reason": "x", "totalPrice": 1}, 400), ({"reason": "x", "unitPrice": 1}, 400), ({}, 400), ({"reason": "  "}, 400)):
        assert _post(c, h, BASE + "/changes", body).status_code == code, body
    assert db.get_db().execute("SELECT COUNT(*) FROM case_material_changes").fetchone()[0] == 0
    monkeypatch.setattr(MC, "PROPOSAL_FN", None)
    monkeypatch.setattr(MC, "_proposal_fn", lambda: None)
    r = _post(c, h, BASE + "/changes", {"reason": "x"})
    assert r.status_code == 501 and c.get(BASE + "/change-proposal", headers=h).status_code == 501


def test_preview_proposal_passes_quantity_and_notes_and_is_read_only(W, reg, fake_proposal):
    c, h = W
    _setup()
    r = c.get(BASE + "/change-proposal?quantity=5&notes=hi", headers=h)
    assert r.status_code == 200 and r.json()["after"]["quantity"] == 5.0 and r.json()["after"]["notes"] == "hi"
    assert db.get_db().execute("SELECT COUNT(*) FROM case_material_changes").fetchone()[0] == 0


def test_wrong_quote_wrong_change_and_withdraw_over_http(W, reg, fake_proposal):
    c, h = W
    _one_tier()
    _setup()
    ch = _post(c, h, BASE + "/changes", {"reason": "追加"}).json()["change"]
    assert _post(c, h, "/api/quotations/NOPE/material-changes/%d/submit" % ch["id"]).status_code == 404
    assert _post(c, h, "/api/quotations/%s/material-changes/9999/submit" % NO).status_code == 404
    assert _post(c, h, "/api/quotations/%s/material-changes/%d/withdraw" % (NO, ch["id"])).json()["status"] == "已撤回"
    r = _post(c, h, "/api/quotations/%s/material-changes/%d/approve" % (NO, ch["id"]))
    assert r.status_code == 409                                                                  # 已撤回不能核准


def test_queue_items_and_detail_provider_show_the_diff(W, reg, fake_proposal):
    c, h = W
    _one_tier()
    _setup()
    ch = _post(c, h, BASE + "/changes", {"reason": "追加一台"}).json()["change"]
    assert API.queue_items(db.get_db()) == []                                                    # 草稿不進佇列
    assert _post(c, h, "/api/quotations/%s/material-changes/%d/submit" % (NO, ch["id"])).json()["status"] == "待審核"
    cn = db.get_db()
    try:
        items = API.queue_items(cn)
        assert len(items) == 1
        it = items[0]
        assert it["type"] == "material_change" and it["docCode"] == ch["docCode"] and it["typeLabel"] == "材料申請變更"
        assert it["approveUrl"].endswith("/material-changes/%d/approve" % ch["id"]) and it["rejectField"] == "reason" and "原 2.0 → 變更後 3.0" in it["projectName"]
        d = API.detail(cn, ch["docCode"])
        vals = {f["label"]: f["value"] for f in d["fields"]}
        assert vals["數量"] == "2 台 → 3 台" and vals["小計"] == "2,000 → 3,000" and "PO-2 #1" in vals["涵蓋採購單行"] and vals["變更原因"] == "追加一台"
        with pytest.raises(Exception):
            API.detail(cn, "MC-NOPE")
    finally:
        cn.close()


def test_view_hides_money_for_users_without_finance_view():
    row = {"id": 1, "doc_code": "MC-1", "quote_no": NO, "item_id": IID, "status": "草稿", "base_version": 1, "reason": "x", "created_by": "u", "created_at": "", "submitted_at": "",
           "approved_at": "", "applied_at": "", "approval_json": "{}",
           "diff_json": json.dumps([{"field": "quantity", "old": 2, "new": 3, "money": False}, {"field": "totalPrice", "old": 2000, "new": 3000, "money": True}]),
           "proposal_json": json.dumps({"quantity": 3, "unitPrice": 1000, "totalPrice": 3000, "poSnapshot": [{"poDocCode": "PO-1", "line": 1, "qty": 3, "amount": 3000}]}),
           "base_json": json.dumps({"quantity": 2, "unitPrice": 1000, "totalPrice": 2000, "poSnapshot": []})}
    v = API._view(row, False)
    assert v["diff"][0]["new"] == 3 and v["diff"][1]["new"] is None and v["diff"][1]["hidden"]
    assert "totalPrice" not in v["proposal"] and "amount" not in v["proposal"]["poSnapshot"][0] and v["proposal"]["quantity"] == 3
    assert API._view(row, True)["proposal"]["totalPrice"] == 3000


def test_notifications_fire_for_every_event_without_raising(W, reg, monkeypatch):
    sent = []
    from helpers import email_notify as EN
    monkeypatch.setattr(EN, "send_registered", lambda key, **k: sent.append(key) or True)
    from modules.case import material_notify as MN
    info = {"docCode": "MC-1", "quoteNo": NO, "itemName": "交換器"}
    for ev, kw in (("submitted", {"approvers": ["a"]}), ("next_tier", {"approvers": ["a"], "tier_no": 2, "total_tiers": 3}),
                   ("approved", {"requester": "r"}), ("returned", {"requester": "r", "reason": "不對"})):
        assert MN.fire_change(ev, info, **kw)
    assert sent == ["material_change_submitted", "material_change_next_tier", "material_change_approved", "material_change_returned"]


# ── use_change_request 守門 ───────────────────────────────────────────

def test_direct_edit_of_an_approved_post_rule_request_is_refused_but_non_substantive_edits_pass(W, reg):
    c, h = W
    _setup()
    f = json.dumps(_order_now(db.get_db()), sort_keys=True)
    r = c.patch("/api/quotations/%s/material-orders" % NO, headers=h, json={"materialOrders": [_order(quantity=3, totalPrice=3000)]})
    assert r.status_code == 200 and [x["code"] for x in r.json()["rejected"]] == ["use_change_request"]
    assert json.dumps(_order_now(db.get_db()), sort_keys=True) == f and MA.status_of(db.get_db(), NO, IID) == "已核准"      # 資料不變、狀態不變（沒有被打回草稿）
    r = c.patch("/api/quotations/%s/material-orders" % NO, headers=h, json={"materialOrders": [_order(notes="只是備註")]})
    assert r.status_code == 200 and not r.json().get("rejected") and _order_now(db.get_db())["notes"] == "只是備註"


def test_grandfathered_and_pre_rule_approved_requests_still_fall_back_to_draft_on_edit(W, reg):
    c, h = W
    for kw in ({"grandfathered": True}, {"created_at": "2026-09-20T00:00:00"}):
        _setup(**kw)
        r = c.patch("/api/quotations/%s/material-orders" % NO, headers=h, json={"materialOrders": [_order(quantity=3, totalPrice=3000)]})
        assert r.status_code == 200 and not r.json().get("rejected"), (kw, r.text)
        assert MA.status_of(db.get_db(), NO, IID) == "草稿" and _order_now(db.get_db())["quantity"] == 3     # 舊行為不變（改了回草稿）


def test_doc_type_is_registered_with_the_case_package_and_follows_the_unified_flow():
    assert MC.DOC_TYPE in TA.APPROVAL_DOC_TYPES and MC.DOC_TYPE in TA.DEFAULT_UNIFIED_DOC_TYPES and TA.APPROVAL_DOC_TYPE_LABELS[MC.DOC_TYPE] == "材料申請變更"
