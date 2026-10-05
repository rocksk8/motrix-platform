# -*- coding: utf-8 -*-
"""使用者裁示（第 32 班 S-1）：舊單（approval_status=''）實質編輯後**維持舊單**，不重設為草稿；寫稽核列、記修改人與時間、
畫面警示「舊單已修改」；成本（營運報表應計）、總帳 E04、匯款申請照舊不掉。已核准的派發實質編輯仍回草稿重審（不變）。"""
import json
import re

import pytest

import db
from modules.subcontract import dispatch_flow as F
from modules.subcontract.tests.test_dispatch_approval_s2_2026_10_01 import _body, _mk, _row, W  # noqa: F401

pytestmark = pytest.mark.no_dispatch_shim




def _put(c, h, did, **kw):
    return c.put("/api/contractor-dispatches/%d" % did, headers=h["da_sa"], json=_body(**kw))      # 第42班（Q5）：改金額＝財務角色／superadmin


def _audit_rows(action):
    cn = db.get_db()
    try:
        return [json.loads(r["detail"] or "{}") for r in cn.execute("SELECT detail FROM audit_log WHERE action=? ORDER BY id", (action,)).fetchall()]
    finally:
        cn.close()


def test_legacy_substantive_edit_stays_legacy_and_is_marked(W):
    c, h = W
    did = _mk(status="sent", approval="")
    before = _row(did)
    r = _put(c, h, did, status="sent", items_json=[{"description": "改了品項", "amount": 9999}])
    assert r.status_code == 200 and r.json()["needsResubmit"] is False and r.json()["legacyModified"] is True
    row = _row(did)
    assert row["approval_status"] == "" and row["doc_code"] == "" and row["status"] == "sent"              # 仍是舊單，沒有重設、沒有發單號
    m = json.loads(row["approval_json"])["legacyModified"]
    assert m["by"] == "da_sa" and m["count"] == 1 and m["at"] and m["firstAt"] == m["at"]
    _put(c, h, did, status="sent", items_json=[{"description": "再改", "amount": 1}])
    m2 = json.loads(_row(did)["approval_json"])["legacyModified"]
    assert m2["count"] == 2 and m2["firstAt"] == m["firstAt"]
    assert before["approved_hash"] == _row(did)["approved_hash"] == ""


def test_legacy_non_substantive_edit_has_no_marker_and_no_extra_audit(W):
    c, h = W
    did = _mk(status="sent", approval="")
    r = _put(c, h, did, status="sent", notes="只改備註", invoice_no="AB12345678")
    assert r.status_code == 200 and "legacyModified" not in r.json()
    assert json.loads(_row(did)["approval_json"]) == {} and _audit_rows("vendor.dispatch.legacy_edit") == []


def test_row_view_exposes_the_warning_only_for_modified_legacy_rows(W):
    c, h = W
    modified, plain, approved = _mk(approval=""), _mk(approval=""), _mk(approval=F.APPROVED)
    _put(c, h, modified, items_json=[{"description": "x", "amount": 5}])
    rows = {r["id"]: r for r in c.get("/api/contractor-dispatches", headers=h["da_a"], params={"quote_no": "MQ-DA-1"}).json()}
    assert rows[modified]["legacy"] is True and rows[modified]["legacyModified"] is True and rows[modified]["legacyModifiedAt"]
    assert rows[plain]["legacyModified"] is False and rows[plain]["legacyModifiedAt"] == ""
    assert rows[approved]["legacyModified"] is False
    assert rows[modified]["displayStatus"] == rows[plain]["displayStatus"]                    # 人話狀態不變（只多警示徽章）


def test_audit_row_records_before_and_after_totals(W):
    c, h = W
    did = _mk(approval="")
    _put(c, h, did, items_json=[{"description": "x", "amount": 5000}])
    det = _audit_rows("vendor.dispatch.legacy_edit")
    assert len(det) == 1 and det[0]["totalBefore"] == 1000 and det[0]["totalAfter"] == 5000


def test_cost_gl_and_voucher_do_not_drop_after_a_legacy_edit(W):
    """成本不掉：營運報表應計成本、總帳 E04、匯款申請對修改過的舊單與修改前一樣可用（金額＝新金額）。"""
    from modules.case import recognition as R
    from modules.subcontract import gl_events as G
    c, h = W
    did = _mk(status="accepted", approval="")
    cn = db.get_db()
    cn.execute("UPDATE contractor_dispatches SET invoice_date='2026-09-15', invoice_no='AB12345678' WHERE id=?", (did,))
    cn.commit()
    cn.close()
    _put(c, h, did, status="accepted", items_json=[{"description": "x", "amount": 2000}], invoice_date="2026-09-15", invoice_no="AB12345678")
    assert _row(did)["approval_status"] == ""
    cn = db.get_db()
    try:
        ent = {e["dispatchId"]: e for e in R.dispatch_entries(cn, "accrual")}
    finally:
        cn.close()
    assert did in ent and ent[did]["amount"] == 2000 + 100 and ent[did]["approvalPending"] is False          # 品項 2000＋人員 100
    ev = [e for e in G.gl_events("2026-09-01", "2026-09-30")["events"] if e["source_key"] == str(did) and e["event_code"] == "E04"]
    assert ev and sum(l["amount"] for l in ev[0]["lines"] if l["side"] == "D") > 0
    r = c.post("/api/contractor-vouchers", json={"dispatch_id": did}, headers=h["da_sa"])
    assert r.status_code in (200, 201), r.text


def test_approved_dispatch_still_resets_to_draft_on_substantive_edit(W):
    c, h = W
    did = _mk(status="sent", approval=F.APPROVED)
    r = _put(c, h, did, status="sent", items_json=[{"description": "x", "amount": 9999}])
    assert r.json()["needsResubmit"] is True and "legacyModified" not in r.json()
    row = _row(did)
    assert row["approval_status"] == F.DRAFT and re.match(r"^DP-\d{8}-\d{4}$", row["doc_code"])
    assert "legacyModified" not in json.loads(row["approval_json"])


def test_front_end_has_the_legacy_modified_warning():
    import os
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "frontend")
    html = open(os.path.join(root, "pages", "case-management.html"), encoding="utf-8").read()
    js = open(os.path.join(root, "js", "case-management-dispatch.js"), encoding="utf-8").read()
    assert 'data-testid="dispatch-legacy-modified-badge"' in html and "舊單已修改" in html
    assert "saved.legacyModified" in js
