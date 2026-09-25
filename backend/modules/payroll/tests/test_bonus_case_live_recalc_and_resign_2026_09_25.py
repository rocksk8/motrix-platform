"""獎金分潤：即時重算預覽、簽核中可改（改了要重簽）、調整人員不回寫案件。

使用者（2026-09-25）：「獎金分潤改%數要能即時同步，並且已經帶入的業務跟專案，需要能調整人員」；
可調狀態選「核准前都能改」——草稿與簽核中（＝待審核）可改，簽核中改了 ⇒ 已簽的作廢、需重新簽；
待發放以後不可改。hichan-0a 裁：預覽走後端同一個算式（不在前端複製）；改了維持待審核、清空簽核重簽；
沒有人簽過就直接存、不要求確認，但照記 edit_log。

傳票（AC3）只在最後一層簽完、進入待發放時才開 ⇒ 可以改的狀態結構上沒有傳票；每一題仍數傳票筆數。
"""
import json

import pytest

from modules.payroll.tests.test_bonus_case_api_2026_09_24 import (  # noqa: F401
    people, _seed_case, _create, _members_spec, _auth, _login, _set_flow)
from modules.payroll.tests._bonus_insure import insure_all  # noqa: E402

SPLIT = {"sales": 5000, "project": 3000, "admin": 2000}


def _db():
    import db
    return db.get_db()


def _award(no):
    conn = _db()
    try:
        a = dict(conn.execute("SELECT * FROM bonus_case_awards WHERE quote_no=?", (no,)).fetchone())
        a["appr"] = json.loads(a["approval_json"] or "{}")
        a["lines"] = {(r["category"], r["username"]): r["amount"] for r in conn.execute(
            "SELECT category, username, amount FROM bonus_case_award_lines WHERE award_id=?", (a["id"],))}
        a["log"] = [(r["action"], json.loads(r["changes_json"] or "null")) for r in conn.execute(
            "SELECT action, changes_json FROM bonus_case_award_edit_log WHERE award_id=? ORDER BY id", (a["id"],))]
        return a
    finally:
        conn.close()


def _voucher_count():
    conn = _db()
    try:
        return conn.execute("SELECT COUNT(*) FROM vouchers_all").fetchone()[0]
    finally:
        conn.close()


def _two_tier_flow():
    _set_flow(["bc_sa2"])
    conn = _db()
    try:
        conn.execute("UPDATE system_settings SET value_json=? WHERE key='bonus_approval_flow'", (json.dumps(
            {"includeSubmitterManagerTier": False, "tiers": [
                {"order": 0, "approvers": [{"username": "bc_sa2", "display_name": "bc_sa2"}]},
                {"order": 1, "approvers": [{"username": "bc_sa3", "display_name": "bc_sa3"}]}]}),))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def sa3(client, make_user):
    u = make_user(username="bc_sa3", role="superadmin")
    return _login(client, u[0], u[1])


def _draft(client, people, no, net=100000):
    _seed_case(no, net=net)
    r = _create(client, people["bc_sa"], no, members=_members_spec())
    assert r.status_code == 200, r.text


def _submit(client, people, no):
    r = client.post("/api/bonus/cases/%s/submit" % no, headers=_auth(people["bc_sa"]))
    assert r.status_code == 200, r.text


def _put(client, tok, no, **body):
    return client.put("/api/bonus/cases/%s" % no, headers=_auth(tok), json=body)


def _preview(client, tok, no, **body):
    return client.post("/api/bonus/cases/%s/preview" % no, headers=_auth(tok), json=body)


# ── ① 即時重算：預覽＝存檔 ─────────────────────────────────────────────────────

CHANGED = dict(rate_bp=1200, split_bp={"sales": 6000, "project": 2500, "admin": 1500},
               members={"sales": [{"username": "bc_s1"}, {"username": "bc_other"}],
                        "project": [{"username": "bc_p2"}],
                        "admin": [{"username": "bc_a1"}, {"username": "bc_a2"}]})


def test_preview_is_exactly_what_saving_stores(client, people):
    no = "MQ-LR-001"
    _draft(client, people, no, net=123457)          # 除不盡：floor 平均、尾差留公司都走得到
    p = _preview(client, people["bc_sa"], no, **CHANGED)
    assert p.status_code == 200, p.text
    pv = p.json()
    assert _put(client, people["bc_sa"], no, **CHANGED).status_code == 200
    a = _award(no)
    got = {(c, l["username"]): l["amount"] for c, cat in pv["categories"].items() for l in cat["lines"]}
    assert got == a["lines"], "預覽顯示的每人金額必須等於存下去的"
    assert pv["pool"] == a["pool_amount"]
    assert pv["remainder"] == pv["pool"] - sum(got.values()) and pv["remainder"] > 0   # 尾差留公司
    # 同類平均取 floor（§11.7）：業務 2 人平均
    s_amt = pv["categories"]["sales"]["amount"]
    assert got[("sales", "bc_s1")] == got[("sales", "bc_other")] == s_amt // 2


def test_preview_writes_nothing(client, people):
    no = "MQ-LR-002"
    _draft(client, people, no)
    before = _award(no)
    assert _preview(client, people["bc_sa"], no, **CHANGED).status_code == 200
    after = _award(no)
    assert (after["updated_at"], after["rate_bp"], after["lines"], after["log"]) == \
           (before["updated_at"], before["rate_bp"], before["lines"], before["log"])


def test_preview_rejects_a_split_that_is_not_100(client, people):
    no = "MQ-LR-003"
    _draft(client, people, no)
    r = _preview(client, people["bc_sa"], no, split_bp={"sales": 6000, "project": 3000, "admin": 2000})
    assert r.status_code == 400 and "100%" in r.json()["detail"], r.text
    r = _put(client, people["bc_sa"], no, split_bp={"sales": 6000, "project": 3000, "admin": 2000})
    assert r.status_code == 400, "存檔也要擋（不是只擋按鈕）"


def test_preview_is_for_editors_only(client, people):
    """預覽回淨利推得出的金額；出納（C1）與一般人不可呼叫。"""
    no = "MQ-LR-004"
    _draft(client, people, no)
    for who in ("bc_cash", "bc_s1"):
        assert _preview(client, people[who], no, **CHANGED).status_code == 403


def test_preview_without_an_award_uses_defaults(client, people):
    """還沒建單時也能預覽（建單前調比例／名單）。"""
    no = "MQ-LR-005"
    _seed_case(no, net=100000)
    r = _preview(client, people["bc_sa"], no, members=_members_spec())
    assert r.status_code == 200, r.text
    assert r.json()["pool"] == 10000                 # 預設 10%


# ── ② 調整人員：只改獎金單、不回寫案件 ───────────────────────────────────────────

def test_changing_people_does_not_touch_the_case(client, people):
    no = "MQ-LR-010"
    _draft(client, people, no)
    conn = _db()
    try:
        before = tuple(conn.execute("SELECT sales_person, sales_person_id, data_json FROM quotations WHERE quote_no=?",
                                    (no,)).fetchone())
    finally:
        conn.close()
    assert _put(client, people["bc_sa"], no, **CHANGED).status_code == 200
    conn = _db()
    try:
        after = tuple(conn.execute("SELECT sales_person, sales_person_id, data_json FROM quotations WHERE quote_no=?",
                                   (no,)).fetchone())
    finally:
        conn.close()
    assert after == before
    a = _award(no)
    assert ("sales", "bc_other") in a["lines"] and ("project", "bc_p1") not in a["lines"]
    edits = [c for act, c in a["log"] if act == "edit"]
    assert edits and any(ch["field"] == "members" for ch in edits[-1]), "變更紀錄要有前後名單"


# ── ③ 簽核中可改 ──────────────────────────────────────────────────────────────

def test_in_review_without_signatures_saves_directly_and_logs(client, people, sa3):
    _two_tier_flow()
    no = "MQ-LR-020"
    _draft(client, people, no)
    _submit(client, people, no)
    r = _put(client, people["bc_sa"], no, rate_bp=1200)
    assert r.status_code == 200, r.text
    a = _award(no)
    assert a["status"] == "待審核" and int(a["appr"]["currentTier"]) == 0
    assert r.json().get("voidedCount", 0) == 0
    assert [act for act, _ in a["log"]][-1] == "edit"
    assert "reset_approvals" not in [act for act, _ in a["log"]]


def test_in_review_with_signatures_needs_explicit_confirmation(client, people, sa3):
    _two_tier_flow()
    no = "MQ-LR-021"
    _draft(client, people, no)
    _submit(client, people, no)
    assert client.post("/api/bonus/cases/%s/approve" % no, headers=_auth(people["bc_sa2"])).status_code == 200
    before = _award(no)
    assert int(before["appr"]["currentTier"]) == 1
    r = _put(client, people["bc_sa"], no, rate_bp=1200)
    assert r.status_code == 409 and "作廢" in r.json()["detail"], r.text
    assert _award(no)["lines"] == before["lines"] and _award(no)["rate_bp"] == before["rate_bp"], "沒確認就不可以改"


def test_confirmed_edit_voids_signatures_and_restarts_the_chain(client, people, sa3):
    _two_tier_flow()
    no = "MQ-LR-022"
    _draft(client, people, no)
    _submit(client, people, no)
    assert client.post("/api/bonus/cases/%s/approve" % no, headers=_auth(people["bc_sa2"])).status_code == 200
    vouchers_before = _voucher_count()
    r = _put(client, people["bc_sa"], no, rate_bp=1200, confirmResetApprovals=True)
    assert r.status_code == 200, r.text
    assert r.json()["voidedCount"] == 1
    a = _award(no)
    assert a["status"] == "待審核", "維持待審核（不退回草稿、不必重新送審）"
    assert int(a["appr"]["currentTier"]) == 0
    assert all(x.get("status") != "approved" and not x.get("approvedAt")
               for t in a["appr"]["tiers"] for x in t["approvers"])
    assert a["appr"].get("requestedBy") == "bc_sa"
    resets = [c for act, c in a["log"] if act == "reset_approvals"]
    assert resets and resets[-1]["approval_before"]["currentTier"] == 1, "舊簽核要留在永久紀錄裡"
    assert _voucher_count() == vouchers_before
    # 重新簽：兩層都要再簽一次，簽完才待發放、傳票一張
    assert client.post("/api/bonus/cases/%s/approve" % no, headers=_auth(people["bc_sa2"])).status_code == 200
    assert _award(no)["status"] == "待審核"
    assert client.post("/api/bonus/cases/%s/approve" % no, headers=_auth(sa3)).status_code == 200
    a = _award(no)
    assert a["status"] == "待發放" and a["accrual_voucher_id"]
    assert _voucher_count() == vouchers_before + 1


def test_unchanged_save_in_review_keeps_signatures(client, people, sa3):
    """沒有實際變更的存檔不作廢任何簽核（不可以因為按了一下儲存就讓別人重簽）。"""
    _two_tier_flow()
    no = "MQ-LR-023"
    _draft(client, people, no)
    _submit(client, people, no)
    assert client.post("/api/bonus/cases/%s/approve" % no, headers=_auth(people["bc_sa2"])).status_code == 200
    a0 = _award(no)
    r = _put(client, people["bc_sa"], no, rate_bp=a0["rate_bp"])
    assert r.status_code == 200, r.text
    assert int(_award(no)["appr"]["currentTier"]) == 1


def test_reset_rechecks_that_the_chain_is_superadmins_only(client, people, sa3):
    """重置時重新解析簽核鏈：鏈上現在有非最高管理者 ⇒ 400、什麼都不改（W1 與送審一致）。"""
    _two_tier_flow()
    no = "MQ-LR-024"
    _draft(client, people, no)
    _submit(client, people, no)
    assert client.post("/api/bonus/cases/%s/approve" % no, headers=_auth(people["bc_sa2"])).status_code == 200
    conn = _db()
    try:
        conn.execute("UPDATE system_settings SET value_json=? WHERE key='bonus_approval_flow'", (json.dumps(
            {"includeSubmitterManagerTier": False, "tiers": [
                {"order": 0, "approvers": [{"username": "bc_s1", "display_name": "bc_s1"}]}]}),))
        conn.commit()
    finally:
        conn.close()
    before = _award(no)
    r = _put(client, people["bc_sa"], no, rate_bp=1200, confirmResetApprovals=True)
    assert r.status_code == 400, r.text
    after = _award(no)
    assert (after["rate_bp"], after["appr"], after["lines"]) == (before["rate_bp"], before["appr"], before["lines"])


def test_payout_and_paid_are_not_editable(client, people):
    insure_all()   # U4：撥付前名單上每個人都要有投保金額（tests/_bonus_insure.py）
    no = "MQ-LR-030"
    _draft(client, people, no)
    _submit(client, people, no)
    assert client.post("/api/bonus/cases/%s/approve" % no, headers=_auth(people["bc_sa2"])).status_code == 200
    assert _award(no)["status"] == "待發放"
    n = _voucher_count()
    assert _put(client, people["bc_sa"], no, rate_bp=1200, confirmResetApprovals=True).status_code == 409
    assert client.post("/api/bonus/cases/%s/mark-paid" % no, headers=_auth(people["bc_cash"])).status_code == 200
    assert _put(client, people["bc_sa"], no, rate_bp=1200, confirmResetApprovals=True).status_code == 409
    assert _voucher_count() == n + 1          # 只有 mark-paid 那一張，PUT 沒有碰傳票


def test_in_review_with_a_voucher_is_refused(client, people, sa3):
    """防禦：待審核卻已連著核定傳票（今天不會發生）⇒ 不可改，否則會留下指向舊金額的傳票。"""
    _two_tier_flow()
    no = "MQ-LR-031"
    _draft(client, people, no)
    _submit(client, people, no)
    conn = _db()
    try:
        conn.execute("UPDATE bonus_case_awards SET accrual_voucher_id=999999 WHERE quote_no=?", (no,))
        conn.commit()
    finally:
        conn.close()
    r = _put(client, people["bc_sa"], no, rate_bp=1200, confirmResetApprovals=True)
    assert r.status_code == 409 and "傳票" in r.json()["detail"], r.text
