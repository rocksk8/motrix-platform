# -*- coding: utf-8 -*-
"""31-A S4：第二段（完工審核）——`completed` 只能由完工審核通過設定（舊單也一樣）；申請完工要 accepted；
審核中作業狀態維持 accepted、實質欄位凍結；退回可修正再申請；撤回回空白。"""
import json

import pytest

from modules.subcontract import dispatch_flow as F
from modules.subcontract.tests.test_dispatch_approval_s2_2026_10_01 import _body, _login, _mk, _row, W  # noqa: F401
from modules.subcontract.tests.test_dispatch_approval_s3_2026_10_01 import S, _tiers  # noqa: F401

pytestmark = pytest.mark.no_dispatch_shim


def _p(c, h, who, did, path, body=None):
    return c.post("/api/contractor-dispatches/%s/completion/%s" % (did, path), json=body or {}, headers=h[who])


def _acc(**kw):
    return _mk(status="accepted", approval=kw.pop("approval", F.APPROVED), **kw)


def test_request_requires_accepted_status(S):
    c, h = S
    _tiers(["da_u1"])
    for st in ("draft", "sent", "confirmed", "pending_acceptance", "completed", "cancelled"):
        did = _mk(status=st, approval=F.APPROVED)
        assert _p(c, h, "da_a", did, "request").status_code == 409, st
        assert _row(did)["completion_status"] == ""


def test_two_tier_completion_sets_completed_only_at_the_end(S):
    c, h = S
    _tiers(["da_u1"], ["da_u2"])
    did = _acc()
    assert _p(c, h, "da_a", did, "request").json()["approvalStatus"] == F.PENDING
    row = _row(did)
    assert row["status"] == "accepted" and row["completion_requested_by"] == "da_a" and row["approval_status"] == F.APPROVED
    assert _p(c, h, "da_u1", did, "approve").json()["approvalStatus"] == F.IN_PROGRESS
    assert _row(did)["status"] == "accepted"
    assert _p(c, h, "da_u2", did, "approve").json()["approvalStatus"] == F.APPROVED
    row = _row(did)
    assert row["status"] == "completed" and row["completion_status"] == F.APPROVED and row["completion_approved_at"]
    assert row["approval_status"] == F.APPROVED                                                       # 兩段互不覆蓋
    assert json.loads(row["approval_json"]) != json.loads(row["completion_approval_json"])


def test_no_tiers_auto_completes(S):
    c, h = S
    _tiers()
    did = _acc()
    r = _p(c, h, "da_a", did, "request")
    assert r.json()["autoApproved"] is True
    assert _row(did)["status"] == "completed"


def test_legacy_row_still_needs_completion_approval(S):
    """舊單（approval_status=''）：第一段免補審，但完工同樣要走完工審核；直接 completed 仍被擋。"""
    c, h = S
    _tiers(["da_u1"])
    did = _acc(approval="")
    r = c.post("/api/contractor-dispatches/%s/status" % did, json={"target": "completed"}, headers=h["da_a"])
    assert r.status_code == 409 and _row(did)["status"] == "accepted"
    assert _p(c, h, "da_a", did, "request").status_code == 200
    _p(c, h, "da_u1", did, "approve")
    row = _row(did)
    assert row["status"] == "completed" and row["approval_status"] == ""                              # 舊單仍是舊單


def test_reject_keeps_accepted_then_resubmit(S):
    c, h = S
    _tiers(["da_u1"])
    did = _acc()
    _p(c, h, "da_a", did, "request")
    assert _p(c, h, "da_u1", did, "reject", {}).status_code == 400
    r = _p(c, h, "da_u1", did, "reject", {"reason": "照片不足"})
    assert r.json()["approvalStatus"] == F.RETURNED
    row = _row(did)
    assert row["status"] == "accepted" and row["completion_status"] == F.RETURNED
    assert _p(c, h, "da_a", did, "request").json()["approvalStatus"] == F.PENDING
    _p(c, h, "da_u1", did, "approve")
    assert _row(did)["status"] == "completed"


def test_withdraw_returns_to_blank_and_can_rerequest(S):
    c, h = S
    _tiers(["da_u1"])
    did = _acc()
    assert _p(c, h, "da_a", did, "withdraw").status_code == 409
    _p(c, h, "da_a", did, "request")
    assert _p(c, h, "da_b", did, "withdraw").status_code == 403
    assert _p(c, h, "da_a", did, "withdraw").status_code == 200
    assert _row(did)["completion_status"] == "" and _row(did)["status"] == "accepted"
    assert _p(c, h, "da_a", did, "request").status_code == 200


def test_non_approver_cannot_approve_completion_and_stage_state_isolated(S):
    c, h = S
    _tiers(["da_u1"])
    did = _acc()
    _p(c, h, "da_a", did, "request")
    assert _p(c, h, "da_u2", did, "approve").status_code in (400, 403)
    # 第二段送審中，第一段的 approve 端點不受影響地拒絕（第一段已核准、不在簽核中）
    assert c.post("/api/contractor-dispatches/%s/approve" % did, json={}, headers=h["da_u1"]).status_code == 409
    assert _row(did)["status"] == "accepted"


def test_edit_frozen_while_completion_pending_and_substantive_edit_after_completed(S):
    c, h = S
    _tiers(["da_u1"])
    did = _acc()
    _p(c, h, "da_a", did, "request")
    assert c.put("/api/contractor-dispatches/%s" % did, json=_body(), headers=h["da_a"]).status_code == 409
    _p(c, h, "da_u1", did, "reject", {"reason": "x"})
    assert c.put("/api/contractor-dispatches/%s" % did, json=_body(), headers=h["da_a"]).status_code == 200


def test_completed_row_cannot_request_again_and_audit(S):
    c, h = S
    _tiers(["da_u1"])
    did = _acc()
    _p(c, h, "da_a", did, "request")
    _p(c, h, "da_u1", did, "approve")
    assert _p(c, h, "da_a", did, "request").status_code == 409
    import db
    cn = db.get_db()
    try:
        acts = [r["action"] for r in cn.execute("SELECT action FROM audit_log WHERE action LIKE 'vendor.dispatch.completion.%' ORDER BY id").fetchall()]
    finally:
        cn.close()
    assert acts == ["vendor.dispatch.completion.submit", "vendor.dispatch.completion.approve"]
