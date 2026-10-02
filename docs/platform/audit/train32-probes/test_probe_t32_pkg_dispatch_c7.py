# -*- coding: utf-8 -*-
"""第 32 包稽核（c7）獨立探針：派發舊單編輯不重設（S-1）縫隙、取消審核中（S-2）、舊單完工補單號與 migration 0004 的互動。
只補作者測試（test_dispatch_legacy_*／test_dispatch_cancel_*）沒打的縫；印出實測值。不隨產品出貨。"""
import json
import threading

import pytest

import db
from modules.subcontract import dispatch_flow as F
from modules.subcontract.tests.test_dispatch_approval_s2_2026_10_01 import _body, _mk, _row, W  # noqa: F401
from modules.subcontract.tests.test_dispatch_approval_s3_2026_10_01 import S, _tiers  # noqa: F401

pytestmark = pytest.mark.no_dispatch_shim


def _put(c, h, did, who="da_a", **kw):
    return c.put("/api/contractor-dispatches/%d" % did, headers=h[who], json=_body(**kw))


def _audits(action):
    cn = db.get_db()
    try:
        return [dict(r) for r in cn.execute("SELECT username, detail FROM audit_log WHERE action=? ORDER BY id", (action,)).fetchall()]
    finally:
        cn.close()


def test_c3_marker_cannot_be_forged_through_the_put_body(W):
    c, h = W
    did = _mk(status="sent", approval="")
    forged = {"legacyModified": {"at": "x", "by": "someone", "count": 99, "firstAt": "x"}}
    r = _put(c, h, did, status="sent", notes="只改備註", approval_json=json.dumps(forged), approval_status="已核准", doc_code="DP-FORGED-0001",
             legacyModified=True, approved_hash="x")
    row = _row(did)
    print("C3 ->", r.status_code, "| approval_status=%r doc_code=%r approval_json=%r" % (row["approval_status"], row["doc_code"], row["approval_json"]))
    assert r.status_code == 200 and row["approval_status"] == "" and row["doc_code"] == "" and json.loads(row["approval_json"] or "{}") == {}
    assert "legacyModified" not in r.json()


def test_c3b_legacy_with_a_payment_voucher_still_cannot_be_edited(W):
    c, h = W
    did = _mk(status="sent", approval="", voucher=True)
    r = _put(c, h, did, status="sent", items_json=[{"description": "改", "amount": 1}])
    print("C3b ->", r.status_code, r.text[:80])
    assert r.status_code == 409 and json.loads(_row(did)["approval_json"] or "{}") == {}


def test_c2_approved_substantive_edit_still_resets_and_leaves_no_legacy_marker(W):
    c, h = W
    did = _mk(status="sent", approval=F.APPROVED)
    r = _put(c, h, did, status="sent", items_json=[{"description": "改", "amount": 5}])
    row = _row(did)
    assert r.status_code == 200 and r.json()["needsResubmit"] is True and "legacyModified" not in r.json()
    assert row["approval_status"] == F.DRAFT and "legacyModified" not in (row["approval_json"] or "")
    assert _audits("vendor.dispatch.legacy_edit") == []


def test_c1_concurrent_legacy_edits_do_not_lose_count(W):
    """兩個同時的舊單實質編輯：marker 是讀—改—寫（沒持寫鎖）⇒ count 應為 2；少算＝稽核軌跡遺失。"""
    c, h = W
    did = _mk(status="sent", approval="")
    res = []

    def go(n):
        res.append(_put(c, h, did, status="sent", items_json=[{"description": "並發%d" % n, "amount": n}]).status_code)
    ts = [threading.Thread(target=go, args=(i,)) for i in (7, 8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    m = json.loads(_row(did)["approval_json"] or "{}").get("legacyModified") or {}
    print("C1 codes=%s marker=%s audits=%d" % (sorted(res), m, len(_audits("vendor.dispatch.legacy_edit"))))
    assert sorted(res) == [200, 200] and len(_audits("vendor.dispatch.legacy_edit")) == 2
    assert m.get("count") == 2, "稽核列有 2 筆但 marker.count=%s（讀改寫競態）" % m.get("count")


def test_c1b_legacy_edit_then_completion_request_keeps_the_marker_and_the_code_is_issued(S):
    c, h = S
    _tiers(["da_u1"])
    did = _mk(status="accepted", approval="")
    assert _put(c, h, did, who="da_a", status="accepted", items_json=[{"description": "改", "amount": 5}]).json().get("legacyModified") is True
    r = c.post("/api/contractor-dispatches/%d/completion/request" % did, json={}, headers=h["da_a"])
    row = _row(did)
    print("C1b ->", r.status_code, "| doc_code=%r approval_json=%r" % (row["doc_code"], row["approval_json"]))
    assert r.status_code == 200 and row["doc_code"].startswith("DP-")
    assert json.loads(row["approval_json"] or "{}").get("legacyModified"), "完工送審不應洗掉舊單修改記號"


def test_c4_cancel_while_in_review_closes_the_review_and_leaves_the_queue(S):
    c, h = S
    _tiers(["da_u1"])
    did = _mk(status="draft", approval=F.DRAFT)
    assert c.post("/api/contractor-dispatches/%d/submit" % did, json={}, headers=h["da_a"]).status_code == 200
    q0 = c.get("/api/approval-queue/count", headers=h["da_u1"]).json().get("count")
    r = c.post("/api/contractor-dispatches/%d/status" % did, json={"target": "cancelled", "reason": "不做了"}, headers=h["da_a"])
    print("C4 cancel ->", r.status_code, r.text[:100], "| count before=%s after=%s" % (q0, c.get("/api/approval-queue/count", headers=h["da_u1"]).json().get("count")))
    row = _row(did)
    ok = c.post("/api/contractor-dispatches/%d/approve" % did, json={}, headers=h["da_u1"])
    print("C4 approve after cancel ->", ok.status_code, ok.text[:100], "| row status=%s approval=%s" % (row["status"], row["approval_status"]))
    assert r.status_code == 200 and row["status"] == "cancelled" and ok.status_code in (400, 409)
    assert c.get("/api/approval-queue/count", headers=h["da_u1"]).json().get("count") == 0
