# -*- coding: utf-8 -*-
"""稽核 S-2：待審核／簽核中取消派發 ⇒ 同一個交易關閉還在審的階段（已退回＋歷程 cancelled）；之後 /approve、/reject 對已取消回 409；
簽核佇列與待簽紅點的計數同步消失；已核准／已退回的階段不動；舊單取消不受影響。"""
import json

import pytest

import db
from modules.subcontract import dispatch_flow as F
from modules.subcontract.tests.test_dispatch_approval_s2_2026_10_01 import _mk, _row, W  # noqa: F401
from modules.subcontract.tests.test_dispatch_approval_s3_2026_10_01 import S, _tiers, _post  # noqa: F401
from modules.subcontract.tests.test_dispatch_approval_s4_2026_10_01 import _acc  # noqa: F401

pytestmark = pytest.mark.no_dispatch_shim


def _cancel(c, h, who, did, reason="取消測試"):
    return c.post("/api/contractor-dispatches/%d/status" % did, json={"target": "cancelled", "reason": reason}, headers=h[who])


def _queue_ids(c, h, who):
    r = c.get("/api/approval-queue", headers=h[who])
    assert r.status_code == 200, r.text
    return [it["quoteNo"] for g in r.json()["queue"] for it in g["items"] if it["type"].startswith("contractor_dispatch")]


def _count(c, h, who):
    r = c.get("/api/approval-queue/count", headers=h[who])
    assert r.status_code == 200, r.text
    return r.json()["count"]


def test_cancel_during_pending_review_closes_the_stage_and_clears_queue_and_dot(S):
    c, h = S
    _tiers(["da_u1"])
    did = _mk()
    _post(c, h, "da_a", did, "submit")
    code = _row(did)["doc_code"]
    assert _queue_ids(c, h, "da_u1") == [code] and _count(c, h, "da_u1") == 1
    r = _cancel(c, h, "da_a", did)
    assert r.status_code == 200, r.text
    row = _row(did)
    assert row["status"] == "cancelled" and row["approval_status"] == F.RETURNED               # 同一個交易：不再是待審核
    appr = json.loads(row["approval_json"])
    assert appr["history"][-1]["action"] == "cancelled" and appr["closedByCancel"] and appr["history"][-1]["comment"] == "取消測試"
    assert _queue_ids(c, h, "da_u1") == [] and _count(c, h, "da_u1") == 0                      # 佇列與紅點同步消失
    # 簽核人再按核准／退回／撤回：409，狀態不變
    for path, body in (("approve", {}), ("reject", {"reason": "x"}), ("withdraw", {})):
        who = "da_a" if path == "withdraw" else "da_u1"
        assert _post(c, h, who, did, path, body).status_code == 409, path
    assert _row(did)["approval_status"] == F.RETURNED and _row(did)["status"] == "cancelled"


def test_cancel_in_progress_second_tier_also_closes(S):
    c, h = S
    _tiers(["da_u1"], ["da_u2"])
    did = _mk()
    _post(c, h, "da_a", did, "submit")
    _post(c, h, "da_u1", did, "approve")
    assert _row(did)["approval_status"] == F.IN_PROGRESS and _queue_ids(c, h, "da_u2")
    assert _cancel(c, h, "da_a", did).status_code == 200
    assert _row(did)["approval_status"] == F.RETURNED and _queue_ids(c, h, "da_u2") == []
    assert _post(c, h, "da_u2", did, "approve").status_code == 409


def test_cancel_during_completion_review_closes_only_the_completion_stage(S):
    c, h = S
    _tiers(["da_u1"])
    did = _acc()
    _post(c, h, "da_a", did, "completion/request")
    assert _row(did)["completion_status"] == F.PENDING
    assert _cancel(c, h, "da_a", did, reason="客戶取消").status_code == 200                       # 已驗收的取消要理由
    row = _row(did)
    assert row["status"] == "cancelled" and row["completion_status"] == F.RETURNED and row["approval_status"] == F.APPROVED    # 第一段（已核准）不動
    assert _queue_ids(c, h, "da_u1") == []
    assert _post(c, h, "da_u1", did, "completion/approve").status_code == 409
    assert _row(did)["status"] == "cancelled"                                                  # 取消後完工不會被核准成 completed


def test_cancel_without_pending_review_is_unchanged_and_legacy_rows_too(S):
    c, h = S
    _tiers(["da_u1"])
    draft, legacy, approved = _mk(), _mk(approval=""), _mk(approval=F.APPROVED)
    before = {d: dict(_row(d)) for d in (draft, legacy, approved)}
    for d in (draft, legacy, approved):
        r = _cancel(c, h, "da_a", d, reason="x")
        assert r.status_code == 200, (d, r.text)
        row = _row(d)
        assert row["status"] == "cancelled" and row["approval_status"] == before[d]["approval_status"]       # 審核欄位原樣
        assert row["approval_json"] == before[d]["approval_json"]


def test_audit_records_closed_stages_and_the_requester_is_notified(S):
    c, h = S
    _tiers(["da_u1"])
    did = _mk()
    _post(c, h, "da_a", did, "submit")
    assert _cancel(c, h, "da_a", did).status_code == 200
    cn = db.get_db()
    try:
        det = [json.loads(r["detail"] or "{}") for r in cn.execute("SELECT detail FROM audit_log WHERE action='vendor.dispatch.cancelled' ORDER BY id").fetchall()]
        notif = cn.execute("SELECT COUNT(*) AS n FROM notifications WHERE username='da_a' AND message LIKE '%已取消%'").fetchone()["n"]
    finally:
        cn.close()
    assert det and det[-1].get("closedStages") == ["approval"]
    assert notif >= 1
