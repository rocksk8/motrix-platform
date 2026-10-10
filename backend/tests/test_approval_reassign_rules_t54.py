# -*- coding: utf-8 -*-
"""第 54 班（使用者裁示 2026-10-10）：轉簽不能變成自核的後門。

`POST /api/approval-queue/reassign`：操作者不得是送審人、轉給的對象不得是送審人；原簽核人與其他在職最高管理者都要收到通知（不只新的簽核人）；
稽核 `approval.reassign` 與換人在同一個交易裡寫（強制）；原因仍必填。規則在 L1 端點，所有 `approval.reassign` 提供者（報價單、請款單、開票申請、
承攬商匯款、派發、完工單、傳票…）一體適用。
"""
import json

from tests._requires import requires_module  # noqa: E402
from tests.test_approval_reassign_history_2026_09_14 import _approval_of, _auth, _login, _seed_quote_pending

pytestmark = requires_module("case", "本檔以報價單為轉簽對象（M01 的資料）")


def _post(client, hdr, quote_no, to, reason="原簽核人出差"):
    return client.post("/api/approval-queue/reassign", headers=hdr,
                       json={"type": "quotation", "id": quote_no, "to_username": to, "reason": reason})


def _q(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _slot(quote_no):
    return _approval_of(quote_no)["tiers"][0]["approvers"][0]["username"]


def test_the_submitter_cannot_reassign_their_own_submission(client, make_user):
    su, sp = make_user(username="sales_x", role="superadmin")                       # 送審人（_seed_quote_pending 的 requestedBy）本身是最高管理者
    make_user(username="rr_old", role="admin")
    make_user(username="rr_new", role="admin")
    _seed_quote_pending("MQ-RR-001", "rr_old")
    r = _post(client, _auth(_login(client, su, sp)), "MQ-RR-001", "rr_new")
    assert r.status_code == 403 and "送審人" in r.text
    assert _slot("MQ-RR-001") == "rr_old" and not _q("SELECT 1 FROM audit_log WHERE action='approval.reassign'")


def test_nobody_can_hand_the_tier_to_the_submitter(client, make_user):
    su, sp = make_user(username="rr_super", role="superadmin")
    make_user(username="sales_x", role="admin")                                     # 送審人
    make_user(username="rr_old", role="admin")
    _seed_quote_pending("MQ-RR-002", "rr_old")
    r = _post(client, _auth(_login(client, su, sp)), "MQ-RR-002", "sales_x")
    assert r.status_code == 400 and "送審人" in r.text
    assert _slot("MQ-RR-002") == "rr_old" and not _q("SELECT 1 FROM audit_log WHERE action='approval.reassign'")


def test_other_superadmin_can_still_reassign_with_a_reason_and_everyone_relevant_is_told(client, make_user):
    su, sp = make_user(username="rr_super", role="superadmin")
    make_user(username="rr_super2", role="superadmin")
    make_user(username="rr_super3", role="superadmin")
    make_user(username="rr_old", role="admin")                                       # 原簽核人（非最高管理者也要被通知）
    make_user(username="rr_new", role="admin")
    _seed_quote_pending("MQ-RR-003", "rr_old")
    assert _post(client, _auth(_login(client, su, sp)), "MQ-RR-003", "rr_new", reason="  ").status_code == 400    # 原因仍必填
    r = _post(client, _auth(_login(client, su, sp)), "MQ-RR-003", "rr_new", reason="原簽核人出差兩週")
    assert r.status_code == 200 and _slot("MQ-RR-003") == "rr_new"
    rows = _q("SELECT username, display_name, detail, target_id, module FROM audit_log WHERE action='approval.reassign'")
    assert len(rows) == 1 and rows[0]["username"] == su and rows[0]["target_id"] == "MQ-RR-003"
    d = json.loads(rows[0]["detail"])
    assert d["from"] == "rr_old" and d["to"] == "rr_new" and d["reason"] == "原簽核人出差兩週" and d["requestedBy"] == "sales_x"
    told = {n["username"]: n["type"] for n in _q("SELECT username, type FROM notifications WHERE ref_id=?", ("MQ-RR-003",))}
    assert told["rr_new"] == "approval_request"                                      # 新簽核人（原行為）
    assert told["rr_old"] == "approval_reassigned"                                   # 原簽核人
    assert told["rr_super2"] == "approval_reassigned" and told["rr_super3"] == "approval_reassigned"   # 其他在職最高管理者
    assert su not in told                                                            # 操作者本人不必收


def test_reassigned_away_approver_loses_the_slot_and_cannot_sign(client, make_user):
    su, sp = make_user(username="rr_super", role="superadmin")
    old, op = make_user(username="rr_old", role="superadmin")
    make_user(username="rr_new", role="admin")
    _seed_quote_pending("MQ-RR-004", "rr_old")
    assert _post(client, _auth(_login(client, su, sp)), "MQ-RR-004", "rr_new").status_code == 200
    assert _slot("MQ-RR-004") == "rr_new"
    assert _approval_of("MQ-RR-004")["reassignLog"][-1]["to"] == "rr_new"


# ── 1d 稽核跟進（fail-closed、自行接手留痕、雙人控管、稽核欄位）──

def _edit_approval(quote_no, fn):
    import db
    c = db.get_db()
    try:
        d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()["data_json"])
        fn(d["approval"])
        c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), quote_no))
        c.commit()
    finally:
        c.close()


def test_unknown_submitter_fails_closed(client, make_user):
    su, sp = make_user(username="rr_super", role="superadmin")
    make_user(username="rr_old", role="admin")
    make_user(username="rr_new", role="admin")
    _seed_quote_pending("MQ-RR-005", "rr_old")
    _edit_approval("MQ-RR-005", lambda a: a.pop("requestedBy"))                       # 舊單：簽核資料沒嵌送審人
    r = _post(client, _auth(_login(client, su, sp)), "MQ-RR-005", "rr_new")
    assert r.status_code == 409 and "送審人" in r.text
    assert _slot("MQ-RR-005") == "rr_old" and not _q("SELECT 1 FROM audit_log WHERE action='approval.reassign'")


def test_self_assign_is_allowed_but_flagged_in_audit_and_notifications(client, make_user):
    su, sp = make_user(username="rr_super", role="superadmin")
    make_user(username="rr_super2", role="superadmin")
    make_user(username="rr_old", role="admin")
    _seed_quote_pending("MQ-RR-006", "rr_old")
    r = _post(client, _auth(_login(client, su, sp)), "MQ-RR-006", su, reason="原簽核人離職，我接手")   # 另一位最高管理者接手（使用者的『接手』情境）
    assert r.status_code == 200 and _slot("MQ-RR-006") == su
    d = json.loads(_q("SELECT detail FROM audit_log WHERE action='approval.reassign'")[0]["detail"])
    assert d["selfAssigned"] is True and d["to"] == su
    told = {n["username"]: n["message"] for n in _q("SELECT username, message FROM notifications WHERE ref_id=?", ("MQ-RR-006",))}
    assert "自行接手" in told["rr_super2"] and "自行接手" in told["rr_old"] and su not in told


def test_target_already_in_another_tier_is_refused(client, make_user):
    su, sp = make_user(username="rr_super", role="superadmin")
    for u in ("rr_a", "rr_c", "rr_later"):
        make_user(username=u, role="admin")
    _seed_quote_pending("MQ-RR-007", "rr_a")

    def two_tiers(a):                                                                # 第 1 層 rr_a 已簽、第 2 層 rr_c 待簽
        a["currentTier"] = 1
        a["tiers"] = [{"approvers": [{"username": "rr_a", "displayName": "rr_a", "status": "approved"}]},
                      {"approvers": [{"username": "rr_c", "displayName": "rr_c", "status": "pending"}]}]
    _edit_approval("MQ-RR-007", two_tiers)
    hdr = _auth(_login(client, su, sp))
    r = _post(client, hdr, "MQ-RR-007", "rr_a")                                      # 簽過第 1 層的人不能再接第 2 層
    assert r.status_code == 409 and "同一個人" in r.text and _slot_of("MQ-RR-007", 1) == "rr_c"

    def later(a):                                                                    # 目前在第 1 層（rr_a 待簽），第 2 層是 rr_later
        a["currentTier"] = 0
        a["tiers"] = [{"approvers": [{"username": "rr_a", "displayName": "rr_a", "status": "pending"}]},
                      {"approvers": [{"username": "rr_later", "displayName": "rr_later", "status": "pending"}]}]
    _edit_approval("MQ-RR-007", later)
    assert _post(client, hdr, "MQ-RR-007", "rr_later").status_code == 409            # 還沒輪到的後面層也算
    assert not _q("SELECT 1 FROM audit_log WHERE action='approval.reassign'")


def _slot_of(quote_no, tier):
    return _approval_of(quote_no)["tiers"][tier]["approvers"][0]["username"]


def test_audit_row_uses_standard_fields_and_caps_the_reason(client, make_user):
    su, sp = make_user(username="rr_super", role="superadmin")
    make_user(username="rr_old", role="admin")
    make_user(username="rr_new", role="admin")
    _seed_quote_pending("MQ-202610-808", "rr_old")
    assert _post(client, _auth(_login(client, su, sp)), "MQ-202610-808", "rr_new", reason="長" * 5000).status_code == 200
    row = _q("SELECT module, case_no, ref_no, detail FROM audit_log WHERE action='approval.reassign'")[0]
    assert row["module"] == "approval" and row["case_no"] == "MQ-202610-808"            # 與 `_audit` 同一個推導函式
    assert len(json.loads(row["detail"])["reason"]) == 500
    assert len(_approval_of("MQ-202610-808")["tiers"][0]["approvers"][0]["reassignReason"]) == 500
