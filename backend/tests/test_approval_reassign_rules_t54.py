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
