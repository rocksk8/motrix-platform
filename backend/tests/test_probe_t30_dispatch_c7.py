# -*- coding: utf-8 -*-
"""第 30 班稽核（c7）：承攬商派發兩段審核——獨立探針。不重複作者的測試（modules/subcontract/tests/test_dispatch_approval_s1～s6）；
這裡只打作者沒涵蓋的縫：舊單被實質編輯、取消與審核交會、簽核詳情存取、自簽、重複送審、核准雜湊的實際作用、下游讀者一致性。
每題的斷言是「應該怎樣」；紅燈＝發現。題名前綴 FINDING 的是已知要回報的行為（以 xfail 之外的方式記錄實測值，見最後的輸出）。"""
import json

import pytest

import db
from modules.subcontract import dispatch_flow as F
from modules.subcontract.tests.test_dispatch_approval_s2_2026_10_01 import _body, _login, _mk, _row, W  # noqa: F401

pytestmark = pytest.mark.no_dispatch_shim


def _tiers(*tiers):
    from helpers import _set_setting
    _set_setting("unified_approval_flow", {"includeSubmitterManagerTier": False, "tiers": [
        {"order": i, "approvers": [{"username": u, "displayName": u} for u in us]} for i, us in enumerate(tiers)]})


@pytest.fixture
def S(client, make_user, W):                                                                      # noqa: F811
    c, h = W
    h.update({n: _login(c, *make_user(username=n, role="user")) for n in ("da_u1", "da_u2", "da_plain")})
    return c, h


def _post(c, h, who, did, path, body=None):
    return c.post("/api/contractor-dispatches/%s/%s" % (did, path), json=body or {}, headers=h[who])


def _cost_view_ids(client, h, who, quote="MQ-DA-1"):
    from modules.subcontract.api.vendor_contractors import dispatch_cost_for_case
    return [r["id"] for r in dispatch_cost_for_case(quote, h[who]["Authorization"])]


def _gl_dispatch_ids():
    import importlib
    gl = importlib.import_module("modules.subcontract.gl_events")
    conn = db.get_db()
    try:
        fn = next(getattr(gl, n) for n in dir(gl) if n.endswith("events") and callable(getattr(gl, n)) and not n.startswith("_"))
        out = fn(conn, {}) if fn.__code__.co_argcount >= 2 else fn(conn)
        return out
    finally:
        conn.close()


# ── F1：舊單（approval_status=''）被實質編輯 ⇒ 回「草稿」＝從成本／總帳消失 ────────────────────────────────

def test_f1_legacy_accepted_row_edit_flips_to_draft_and_leaves_the_cost_view(S):
    c, h = S
    did = _mk(status="accepted", approval="")                       # 舊單：已驗收、尚未開匯款申請
    assert did in _cost_view_ids(c, h, "da_sa"), "舊單照舊計入成本檢視（前置）"
    r = c.put("/api/contractor-dispatches/%d" % did, json=_body(items_json=[{"description": "改過", "amount": 1}]), headers=h["da_a"])
    assert r.status_code == 200, r.text
    row = _row(did)
    print("F1 needsResubmit=%s approval_status=%r status=%r" % (r.json().get("needsResubmit"), row["approval_status"], row["status"]))
    in_view = did in _cost_view_ids(c, h, "da_sa")
    print("F1 still in cost view after substantive edit of an ACCEPTED legacy row: %s" % in_view)
    # 作者的設計是「實質編輯 ⇒ 要重新送審」，所以這裡只記錄實測；是否合理由主持／使用者裁示。
    assert row["status"] == "accepted"


# ── F2：取消與審核交會 ──────────────────────────────────────────────────────────────────────────────────────

def test_f2_cancel_while_pending_leaves_a_ghost_in_the_approvers_queue_and_can_still_be_approved(S):
    c, h = S
    _tiers(["da_u1"])
    did = _mk()
    assert _post(c, h, "da_a", did, "submit").status_code == 200
    r = c.post("/api/contractor-dispatches/%d/status" % did, json={"target": "cancelled", "reason": "不做了"}, headers=h["da_a"])
    print("F2 cancel while pending → %s %s" % (r.status_code, r.text[:80]))
    row = _row(did)
    from modules.subcontract.api import dispatch_approval as DA
    conn = db.get_db()
    try:
        queued = [i for i in DA.queue_items(conn) if i.get("dispatchId") == did]
    finally:
        conn.close()
    ap = _post(c, h, "da_u1", did, "approve")
    print("F2 status=%s approval=%s queued=%d approve→%s" % (row["status"], row["approval_status"], len(queued), ap.status_code))
    if r.status_code == 200:
        assert not queued, "已取消的派發不應留在簽核人的待簽佇列"
        assert ap.status_code != 200, "已取消的派發不應能被核准"


# ── 自簽：申請人本人也在簽核層 ───────────────────────────────────────────────────────────────────────────

def test_selfsign_requester_in_tier_is_not_a_free_pass(S):
    c, h = S
    _tiers(["da_a"], ["da_u1"])                                      # 申請人 da_a 同時是第一層
    did = _mk()
    r = _post(c, h, "da_a", did, "submit")
    st = _row(did)["approval_status"]
    ap = _post(c, h, "da_a", did, "approve")
    print("selfsign submit=%s status=%s approve=%s %s → %s" % (r.status_code, st, ap.status_code, ap.text[:80], _row(did)["approval_status"]))
    # 若第一層只有申請人，核准後仍須等第二層（da_u1）；絕不可單憑自簽直接變「已核准」
    assert _row(did)["approval_status"] != F.APPROVED


def test_selfsign_only_tier_is_requester_does_it_auto_approve(S):
    c, h = S
    _tiers(["da_a"])
    did = _mk()
    _post(c, h, "da_a", did, "submit")
    ap = _post(c, h, "da_a", did, "approve")
    print("selfsign-only-tier: approve=%s %s status=%s" % (ap.status_code, ap.text[:80], _row(did)["approval_status"]))


# ── 簽核詳情的存取（IDOR）：誰讀得到派發的品項、外包人員、金額 ──────────────────────────────────────────

def test_queue_detail_access_matrix(S):
    c, h = S
    _tiers(["da_u1"])
    did = _mk()
    _post(c, h, "da_a", did, "submit")
    code = _row(did)["doc_code"]
    out = {}
    for who in ("da_sa", "da_a", "da_b", "da_u1", "da_u2", "da_plain"):
        r = c.get("/api/approval-queue/detail", params={"type": "contractor_dispatch", "id": code}, headers=h[who])
        out[who] = r.status_code
    print("detail matrix:", out)
    assert out["da_sa"] == 200 and out["da_u1"] == 200, "最高管理者與簽核人要看得到"
    assert out["da_u2"] == 404 and out["da_plain"] == 404, "與本單無關的一般使用者不可看到（同一個 404，不洩漏存在）"


def test_queue_detail_masks_money_for_a_viewer_who_cannot_see_it(S):
    c, h = S
    _tiers(["da_u1"])
    did = _mk()
    _post(c, h, "da_a", did, "submit")
    code = _row(did)["doc_code"]
    r = c.get("/api/approval-queue/detail", params={"type": "contractor_dispatch", "id": code}, headers=h["da_u1"])
    print("approver detail fields:", json.dumps(r.json().get("fields"), ensure_ascii=False)[:300], "items:", json.dumps(r.json().get("items"), ensure_ascii=False)[:200])


# ── 重複／並發 ───────────────────────────────────────────────────────────────────────────────────────────────

def test_double_submit_and_double_approve_are_rejected(S):
    c, h = S
    _tiers(["da_u1"])
    did = _mk()
    assert _post(c, h, "da_a", did, "submit").status_code == 200
    assert _post(c, h, "da_a", did, "submit").status_code == 409
    assert _post(c, h, "da_u1", did, "approve").status_code == 200
    assert _post(c, h, "da_u1", did, "approve").status_code == 409
    assert _row(did)["approval_status"] == F.APPROVED


# ── approved_hash 的實際作用（寫了，有人讀嗎？）────────────────────────────────────────────────────────

def test_approved_hash_is_only_pinned_not_verified_downstream(S):
    c, h = S
    from helpers import _set_setting
    _set_setting("unified_approval_flow", {"includeSubmitterManagerTier": False, "tiers": []})
    did = _mk()
    _post(c, h, "da_a", did, "submit")
    row = _row(did)
    assert row["approval_status"] == F.APPROVED and row["approved_hash"]
    # 繞過 PUT 直接改實質欄位（模擬任何其他寫入者）：核准狀態與下游閘都不會察覺
    conn = db.get_db()
    conn.execute("UPDATE contractor_dispatches SET items_json=?, total_amount=? WHERE id=?", (json.dumps([{"description": "被改", "amount": 999999}]), 999999, did))
    conn.commit()
    conn.close()
    after = _row(did)
    changed = F.substantive_hash(after["vendor_id"], after["items_json"], after["personnel_json"], after["tax_rate"]) != after["approved_hash"]
    print("approved_hash mismatch detectable=%s ; approval_status still %r (nobody re-checks the hash)" % (changed, after["approval_status"]))
    assert after["approval_status"] == F.APPROVED


# ── 取消後的下游：成本檢視／總帳不計 ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("approval", ["", F.APPROVED, F.DRAFT, F.PENDING, F.RETURNED])
def test_cancelled_never_counts_in_cost_view(S, approval):
    c, h = S
    did = _mk(status="cancelled", approval=approval)
    assert did not in _cost_view_ids(c, h, "da_sa")


# ── 狀態端點的輸入 ───────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("body", [{}, {"target": ""}, {"target": "COMPLETED"}, {"target": ["sent"]}, {"target": "completed"}])
def test_status_endpoint_rejects_bad_targets(S, body):
    c, h = S
    did = _mk(status="accepted", approval="")
    r = c.post("/api/contractor-dispatches/%d/status" % did, json=body, headers=h["da_a"])
    assert r.status_code in (400, 409, 422), (body, r.status_code, r.text)
    assert _row(did)["status"] == "accepted"


@pytest.mark.parametrize("who,code", [("da_u1", 403), ("da_plain", 403)])
def test_plain_role_users_cannot_drive_the_flow(S, who, code):
    c, h = S
    did = _mk()
    for path in ("submit", "approve", "reject", "withdraw", "completion/request"):
        r = _post(c, h, who, did, path, {"reason": "x"})
        assert r.status_code in (403, 409), (path, r.status_code)
        assert r.status_code != 200
    r = c.post("/api/contractor-dispatches/%d/status" % did, json={"target": "sent"}, headers=h[who])
    assert r.status_code == 403
