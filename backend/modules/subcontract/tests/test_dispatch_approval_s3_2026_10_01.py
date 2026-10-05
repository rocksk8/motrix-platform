# -*- coding: utf-8 -*-
"""31-A S3：第一段（派發審核）端點——送審／核准／退回／撤回；沒設簽核層＝直接核准；核准釘 approved_hash；
舊單（approval_status=''）不能走送審（只在實質編輯後回草稿才送審）；作業狀態不被簽核端點動到。"""
import json

import pytest

import db
from modules.subcontract import dispatch_flow as F
from modules.subcontract.tests.test_dispatch_approval_s2_2026_10_01 import _body, _login, _mk, _row, W  # noqa: F401

pytestmark = pytest.mark.no_dispatch_shim


def _tiers(*tiers):
    """tiers＝[[username,…],…]：每個內層 list 是一層（同層多人依序簽）。"""
    from helpers import _set_setting
    _set_setting("unified_approval_flow", {"includeSubmitterManagerTier": False, "tiers": [
        {"order": i, "approvers": [{"username": u, "displayName": u} for u in us]} for i, us in enumerate(tiers)]})


@pytest.fixture
def S(client, make_user, W):                                                                      # noqa: F811
    c, h = W
    h.update({n: _login(c, *make_user(username=n, role="user")) for n in ("da_u1", "da_u2")})
    return c, h


def _post(c, h, who, did, path, body=None):
    return c.post("/api/contractor-dispatches/%s/%s" % (did, path), json=body or {}, headers=h[who])


def _appr(did):
    return json.loads(_row(did)["approval_json"])


# ── 沒設層：直接核准 ───────────────────────────────────────────────────────

def test_submit_without_tiers_auto_approves_and_pins_hash(S):
    c, h = S
    from helpers import _set_setting
    _set_setting("unified_approval_flow", {"includeSubmitterManagerTier": False, "tiers": []})
    did = _mk()
    r = _post(c, h, "da_a", did, "submit")
    assert r.status_code == 200, r.text
    assert r.json()["approvalStatus"] == F.APPROVED and r.json()["autoApproved"] is True
    row = _row(did)
    assert row["approval_status"] == F.APPROVED and row["status"] == "draft"                        # 作業狀態不動
    assert row["approved_at"] and row["approved_hash"] == F.substantive_hash(row["vendor_id"], row["items_json"], row["personnel_json"], row["tax_rate"])
    assert _appr(did)["autoApproved"] is True


# ── 兩層簽核全流程 ─────────────────────────────────────────────────────────

def test_two_tier_flow_to_approved(S):
    c, h = S
    _tiers(["da_u1"], ["da_u2"])
    did = _mk()
    assert _post(c, h, "da_a", did, "submit").json()["approvalStatus"] == F.PENDING
    assert _row(did)["submitted_by"] == "da_a"
    assert _post(c, h, "da_u2", did, "approve").status_code in (400, 403)                           # 還沒輪到第二層
    r = _post(c, h, "da_u1", did, "approve")
    assert r.status_code == 200 and r.json()["approvalStatus"] == F.IN_PROGRESS
    assert _post(c, h, "da_u1", did, "approve").status_code in (400, 403, 409)                      # 同一人不能重簽
    r = _post(c, h, "da_u2", did, "approve")
    assert r.json()["approvalStatus"] == F.APPROVED
    row = _row(did)
    assert row["approved_hash"] and row["approved_at"] and row["status"] == "draft"
    assert [x["action"] for x in _appr(did)["history"]] == ["approve", "approve"]


def test_non_approver_cannot_approve_or_reject(S):
    c, h = S
    _tiers(["da_u1"])
    did = _mk()
    _post(c, h, "da_a", did, "submit")
    assert _post(c, h, "da_u2", did, "approve").status_code in (400, 403)
    assert _post(c, h, "da_u2", did, "reject", {"reason": "x"}).status_code in (400, 403)
    assert _row(did)["approval_status"] == F.PENDING


# ── 退回與再送 ─────────────────────────────────────────────────────────────

def test_reject_needs_reason_then_resubmit(S):
    c, h = S
    _tiers(["da_u1"])
    did = _mk()
    _post(c, h, "da_a", did, "submit")
    assert _post(c, h, "da_u1", did, "reject", {}).status_code == 400
    assert _post(c, h, "da_u1", did, "reject", {"reason": "  "}).status_code == 400
    assert _row(did)["approval_status"] == F.PENDING
    r = _post(c, h, "da_u1", did, "reject", {"reason": "金額不對"})
    assert r.status_code == 200 and r.json()["approvalStatus"] == F.RETURNED
    assert _appr(did)["rejectReason"] == "金額不對"
    # 已退回 → 可再送；版本號遞增、歷程保留
    assert _post(c, h, "da_a", did, "submit").json()["approvalStatus"] == F.PENDING
    a = _appr(did)
    assert a["version"] == 2 and [x["action"] for x in a["history"]] == ["reject"]


# ── 撤回 ───────────────────────────────────────────────────────────────────

def test_withdraw_only_pending_by_requester_or_superadmin(S):
    c, h = S
    _tiers(["da_u1"], ["da_u2"])
    did = _mk()
    assert _post(c, h, "da_a", did, "withdraw").status_code == 409                                  # 草稿不能撤回
    _post(c, h, "da_a", did, "submit")
    assert _post(c, h, "da_b", did, "withdraw").status_code == 403                                  # 別的 admin 不行
    r = _post(c, h, "da_a", did, "withdraw")
    assert r.status_code == 200 and _row(did)["approval_status"] == F.DRAFT
    _post(c, h, "da_a", did, "submit")
    assert _post(c, h, "da_sa", did, "withdraw").status_code == 200                                 # 最高管理者可
    _post(c, h, "da_a", did, "submit")
    _post(c, h, "da_u1", did, "approve")
    assert _post(c, h, "da_a", did, "withdraw").status_code == 409                                  # 簽核中不能撤回
    assert _row(did)["approval_status"] == F.IN_PROGRESS


# ── 送審的前置條件 ─────────────────────────────────────────────────────────

def test_submit_state_and_role_gates(S):
    c, h = S
    _tiers(["da_u1"])
    d1 = _mk(approval=F.PENDING)
    assert _post(c, h, "da_a", d1, "submit").status_code == 409                                     # 待審核不可重送
    d2 = _mk(approval=F.APPROVED)
    assert _post(c, h, "da_a", d2, "submit").status_code == 409                                     # 已核准不可重送
    d3 = _mk(status="cancelled", approval=F.DRAFT)
    assert _post(c, h, "da_a", d3, "submit").status_code == 409                                     # 已取消
    d4 = _mk()
    assert _post(c, h, "da_u1", d4, "submit").status_code == 403                                    # 非 admin
    assert _row(d4)["approval_status"] == F.DRAFT
    assert _post(c, h, "da_a", 987654, "submit").status_code == 404


def test_legacy_row_cannot_be_submitted_and_endpoints_do_not_touch_it(S):
    """舊單（''）：不能送審（它本來就不需要；實質編輯後才回草稿）；approve／reject／withdraw 也都 409，列不變。"""
    c, h = S
    _tiers(["da_u1"])
    did = _mk(approval="")
    before = dict(_row(did))
    for path, body in (("submit", None), ("approve", None), ("reject", {"reason": "x"}), ("withdraw", None)):
        assert _post(c, h, "da_a" if path in ("submit", "withdraw") else "da_u1", did, path, body).status_code == 409, path
    assert dict(_row(did)) == before


def test_vendor_or_personnel_required_to_submit(S):
    c, h = S
    _tiers(["da_u1"])
    cn = db.get_db()
    cn.execute("INSERT INTO contractor_dispatches (quote_no, status, items_json, personnel_json, total_amount, tax_rate, created_by, created_at, updated_at, approval_status, doc_code)"
               " VALUES ('MQ-DA-1','draft','[]','[]',0,0.05,'da_a','2026-10-01T10:00:00','2026-10-01T10:00:00','草稿','DP-20261001-9990')")
    cn.commit()
    did = cn.execute("SELECT id FROM contractor_dispatches WHERE doc_code='DP-20261001-9990'").fetchone()["id"]
    cn.close()
    assert _post(c, h, "da_a", did, "submit").status_code == 400


def test_unresolved_manager_blocks_submit_state_unchanged(S):
    c, h = S
    from helpers import _set_setting
    _set_setting("unified_approval_flow", {"includeSubmitterManagerTier": False, "tiers": [{"order": 0, "approvers": [{"sourceType": "department_manager", "departmentId": 99999}]}]})
    did = _mk()
    r = _post(c, h, "da_a", did, "submit")
    assert r.status_code == 400
    assert _row(did)["approval_status"] == F.DRAFT


# ── 簽核不動作業狀態；審核中不能編輯；核准後的推進 ──────────────────────────

def test_approved_unlocks_work_status_and_pending_blocks_edit(S):
    c, h = S
    _tiers(["da_u1"])
    did = _mk()
    r = c.post("/api/contractor-dispatches/%s/status" % did, json={"target": "sent"}, headers=h["da_a"])
    assert r.status_code == 409                                                                     # 草稿未核准 → 擋（S2 閘）
    _post(c, h, "da_a", did, "submit")
    assert _row(did)["status"] == "draft"
    assert c.put("/api/contractor-dispatches/%s" % did, json=_body(), headers=h["da_a"]).status_code == 409
    _post(c, h, "da_u1", did, "approve")
    r = c.post("/api/contractor-dispatches/%s/status" % did, json={"target": "sent"}, headers=h["da_a"])
    assert r.status_code == 200 and _row(did)["status"] == "sent"


def test_substantive_edit_after_approval_resets_then_resubmit_repins_hash(S):
    c, h = S
    _tiers(["da_u1"])
    did = _mk()
    _post(c, h, "da_a", did, "submit")
    _post(c, h, "da_u1", did, "approve")
    h1 = _row(did)["approved_hash"]
    r = c.put("/api/contractor-dispatches/%s" % did, headers=h["da_f"],          # 第42班（Q5）：改金額＝財務角色
              json=_body(items_json=[{"description": "y", "amount": 5}]))
    assert r.status_code == 200 and r.json().get("needsResubmit") is True
    assert _row(did)["approval_status"] == F.DRAFT and _row(did)["approved_hash"] == ""
    _post(c, h, "da_a", did, "submit")
    _post(c, h, "da_u1", did, "approve")
    h2 = _row(did)["approved_hash"]
    assert h2 and h2 != h1


# ── 稽核與註冊 ─────────────────────────────────────────────────────────────

def test_audit_rows_written_for_each_action(S):
    c, h = S
    _tiers(["da_u1"])
    did = _mk()
    _post(c, h, "da_a", did, "submit")
    _post(c, h, "da_u1", did, "reject", {"reason": "再議"})
    _post(c, h, "da_a", did, "submit")
    _post(c, h, "da_u1", did, "approve")
    _post(c, h, "da_a", _mk(), "submit")
    cn = db.get_db()
    try:
        acts = [r["action"] for r in cn.execute("SELECT action FROM audit_log WHERE action LIKE 'vendor.dispatch.%' ORDER BY id").fetchall()]
    finally:
        cn.close()
    assert acts[:4] == ["vendor.dispatch.submit", "vendor.dispatch.reject", "vendor.dispatch.submit", "vendor.dispatch.approve"]


def test_doc_type_registered_once_and_unified_default():
    from helpers import APPROVAL_DOC_TYPES, DEFAULT_UNIFIED_DOC_TYPES, APPROVAL_DOC_TYPE_LABELS
    assert APPROVAL_DOC_TYPES.count("contractor_dispatch") == 1
    assert "contractor_dispatch" in DEFAULT_UNIFIED_DOC_TYPES
    assert APPROVAL_DOC_TYPE_LABELS["contractor_dispatch"] == "承攬商派發"
