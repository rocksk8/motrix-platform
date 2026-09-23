"""額外支出「駁回」的當層簽核人檢查（2026-09-24）。

`reject_extra_expense()` 與 `reject_change_request()` 都呼叫了
`check_reject_permission()`，但**丟掉了它的回傳值**——它不 raise，只回
`(ok, code, msg)`。結果是任何過得了 `_guard_case()` 的人（admin 全部過得了）
都能駁回任何一層。approve 側 2026-09-15 已修同型問題，這裡補 reject 側。

觀測點刻意打在**資料列狀態**而不只是 HTTP 碼：擋下來之後單據必須仍在簽核中。
"""
import json

from .test_case_extra_expenses_api_2026_09_11 import (  # noqa: F401  (fixtures reused)
    _auth, _base, _login, _make_case, _payload,
)
from .test_xe_change_request_2026_09_11 import (
    _approved_expense, _cbase, _get_item, _single_tier_flow,
)


def _put_pending(exp_id, approver_username):
    """把一筆草稿直接改成「待審核、單層、簽核人是 approver_username」。"""
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "UPDATE case_extra_expenses SET status='待審核', approval_json=? WHERE id=?",
            (json.dumps({"requestedBy": "someone_else", "tiers": [
                {"approvers": [{"username": approver_username,
                                "display_name": approver_username}]}],
                "currentTier": 0}, ensure_ascii=False), exp_id),
        )
        conn.commit()
    finally:
        conn.close()


def _status(exp_id):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT status, change_status FROM case_extra_expenses WHERE id=?",
                            (exp_id,)).fetchone()
    finally:
        conn.close()


# ── 本體駁回 ────────────────────────────────────────────────────────────────

def test_non_tier_admin_cannot_reject_expense(client, make_user):
    approver, _ = make_user(username="xrj_ap1", role="admin")
    other, other_pw = make_user(username="xrj_ot1", role="admin")
    _make_case()
    token = _login(client, other, other_pw)
    exp_id = client.post(_base(), headers=_auth(token), json=_payload()).json()["id"]
    _put_pending(exp_id, approver)

    r = client.post(f"{_base()}/{exp_id}/reject", headers=_auth(token), json={"reason": "x"})
    assert r.status_code == 403, r.text
    assert _status(exp_id)["status"] == "待審核", "被擋下的駁回不可以改到資料列"


def test_tier_approver_can_reject_expense(client, make_user):
    approver, ap_pw = make_user(username="xrj_ap2", role="admin")
    _make_case()
    token = _login(client, approver, ap_pw)
    exp_id = client.post(_base(), headers=_auth(token), json=_payload()).json()["id"]
    _put_pending(exp_id, approver)

    r = client.post(f"{_base()}/{exp_id}/reject", headers=_auth(token), json={})
    assert r.status_code == 200, r.text
    assert _status(exp_id)["status"] == "已駁回"


def test_superadmin_outside_tier_can_still_reject_expense(client, make_user):
    """check_reject_permission() 的既有語意：superadmin 可介入退回。"""
    approver, _ = make_user(username="xrj_ap3", role="admin")
    sa, sa_pw = make_user(username="xrj_sa3", role="superadmin")
    _make_case()
    token = _login(client, sa, sa_pw)
    exp_id = client.post(_base(), headers=_auth(token), json=_payload()).json()["id"]
    _put_pending(exp_id, approver)

    r = client.post(f"{_base()}/{exp_id}/reject", headers=_auth(token), json={})
    assert r.status_code == 200, r.text


# ── 變更申請駁回 ────────────────────────────────────────────────────────────

def test_non_tier_admin_cannot_reject_change_request(client, make_user):
    author, author_pw = make_user(username="xrj_a4", role="admin")
    approver, _ = make_user(username="xrj_ap4", role="admin")
    other, other_pw = make_user(username="xrj_ot4", role="admin")
    _make_case()
    token = _login(client, author, author_pw)
    exp_id = _approved_expense(client, token)
    _single_tier_flow(approver)
    assert client.put(_cbase(exp_id), headers=_auth(token),
                      json=_payload(qty=9)).status_code == 200
    assert client.post(f"{_cbase(exp_id)}/submit", headers=_auth(token)).status_code == 200

    otoken = _login(client, other, other_pw)
    r = client.post(f"{_cbase(exp_id)}/reject", headers=_auth(otoken), json={"reason": "x"})
    assert r.status_code == 403, r.text
    assert _get_item(client, token, exp_id)["changeStatus"] == "待審核", \
        "被擋下的駁回不可以改到變更申請狀態"
