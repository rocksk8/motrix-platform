"""獎金分潤簽核：同一層有多位簽核人時，要**全部簽完**才換層。

☠️ 2026-09-25（hichan-8d 讀 BN22 時找到，hichan-0a 裁定為真缺陷）：`approve_case_bonus` 在當層第一個沒有
`approvedAt` 的人寫入簽核後**立刻** `currentTier+1` ⇒ 第二位以後永遠不用簽，這一層就過了。
共用規則 `tiered_approval.resolve_tier_approvers` 明寫「同一層可以放多筆（依陣列順序輪流簽）」，
而 `first_pending_approver`／`check_approve_permission` 看的是 `status`——bonus 從來不寫它。
（其他單據的標準寫法：payment_requests.py `first_pending["status"] = "approved"`，當層全數 approved 才換層。）
"""
import json

import pytest

from tests.test_bonus_case_api_2026_09_24 import (  # noqa: F401
    people, _seed_case, _create, _members_spec, _auth, _login)


def _db():
    import db
    return db.get_db()


def _award(no):
    conn = _db()
    try:
        a = dict(conn.execute("SELECT * FROM bonus_case_awards WHERE quote_no=?", (no,)).fetchone())
        a["appr"] = json.loads(a["approval_json"] or "{}")
        return a
    finally:
        conn.close()


def _vouchers_for(no):
    conn = _db()
    try:
        return conn.execute("SELECT COUNT(*) FROM vouchers_all WHERE summary LIKE ?", ("%" + no + "%",)).fetchone()[0]
    finally:
        conn.close()


def _flow(*tiers):
    conn = _db()
    try:
        conn.execute("UPDATE system_settings SET value_json=? WHERE key='bonus_approval_flow'", (json.dumps(
            {"includeSubmitterManagerTier": False, "tiers": [
                {"order": i, "approvers": [{"username": u, "display_name": u} for u in t]}
                for i, t in enumerate(tiers)]}),))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def sa3(client, make_user):
    u = make_user(username="bc_sa3", role="superadmin")
    return _login(client, u[0], u[1])


def _submit(client, people, no):
    _seed_case(no, net=100000)
    assert _create(client, people["bc_sa"], no, members=_members_spec()).status_code == 200
    r = client.post("/api/bonus/cases/%s/submit" % no, headers=_auth(people["bc_sa"]))
    assert r.status_code == 200, r.text


def test_both_approvers_in_one_tier_must_sign(client, people, sa3):
    from tests.test_bonus_case_api_2026_09_24 import _set_flow
    _set_flow(["bc_sa2"])          # 讓設定列存在，再覆寫成「一層兩人」
    _flow(["bc_sa2", "bc_sa3"])
    no = "MQ-MAT-001"
    _submit(client, people, no)

    r = client.post("/api/bonus/cases/%s/approve" % no, headers=_auth(people["bc_sa2"]))
    assert r.status_code == 200, r.text
    a = _award(no)
    assert a["status"] == "待審核", "同層第二位還沒簽，這一層不可以過：%s" % a["status"]
    assert int(a["appr"].get("currentTier") or 0) == 0
    first, second = a["appr"]["tiers"][0]["approvers"]
    assert first.get("status") == "approved" and first.get("approvedAt")
    assert second.get("status") != "approved" and not second.get("approvedAt")
    assert not a["accrual_voucher_id"] and _vouchers_for(no) == 0, "還沒簽完不可以開傳票"

    r = client.post("/api/bonus/cases/%s/approve" % no, headers=_auth(sa3))
    assert r.status_code == 200, r.text
    a = _award(no)
    assert a["status"] == "待發放"
    assert all(x.get("status") == "approved" for x in a["appr"]["tiers"][0]["approvers"])
    assert a["accrual_voucher_id"] and _vouchers_for(no) == 1, "簽完才開、而且只開一張"


def test_second_approver_cannot_sign_before_the_first(client, people, sa3):
    from tests.test_bonus_case_api_2026_09_24 import _set_flow
    _set_flow(["bc_sa2"])
    _flow(["bc_sa2", "bc_sa3"])
    no = "MQ-MAT-002"
    _submit(client, people, no)
    r = client.post("/api/bonus/cases/%s/approve" % no, headers=_auth(sa3))
    assert r.status_code == 403, r.text          # 簽核順序固定（check_approve_permission）
    assert _award(no)["status"] == "待審核"


def test_two_single_approver_tiers_still_advance_one_per_signature(client, people, sa3):
    """回歸：一層一人時行為不變（每簽一次換一層，最後一層簽完才待發放）。"""
    from tests.test_bonus_case_api_2026_09_24 import _set_flow
    _set_flow(["bc_sa2"])
    _flow(["bc_sa2"], ["bc_sa3"])
    no = "MQ-MAT-003"
    _submit(client, people, no)
    assert client.post("/api/bonus/cases/%s/approve" % no, headers=_auth(people["bc_sa2"])).status_code == 200
    a = _award(no)
    assert a["status"] == "待審核" and int(a["appr"]["currentTier"]) == 1 and not a["accrual_voucher_id"]
    assert client.post("/api/bonus/cases/%s/approve" % no, headers=_auth(sa3)).status_code == 200
    assert _award(no)["status"] == "待發放"
