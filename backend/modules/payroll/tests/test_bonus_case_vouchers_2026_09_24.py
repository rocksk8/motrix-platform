# -*- coding: utf-8 -*-
"""獎金分潤 → 傳票草稿（SPEC-BONUS §11.8，2026-09-24 使用者裁示）。

```
進入待發放   轉帳傳票草稿：借 薪資支出 6111／貸 應付薪資 2191，摘要帶案號
標記已發放   支出傳票草稿：借 2191／貸 銀行存款（出納選，預設 1113）
             ＋一行代扣稅款貸 2252（U4 起依法規參數自動計算；未達起扣為 0）
退回         轉帳草稿還沒送審 ⇒ 作廢；已送審 ⇒ 不動，回應帶提示
```
- 一律只產生**草稿**，走傳票自己的簽核（JV30），不自動過帳。
- 科目以 `account_items` 為準、**不寫死**：存在設定裡（預設 6111／2191／2252／1113），
  設定值不存在或已停用 ⇒ 設定頁擋；已存的科目後來被停用 ⇒ 不產生傳票並提示（不猜科目）。
"""
import pytest

from modules.payroll.tests.test_bonus_case_api_2026_09_24 import (  # noqa: F401
    people, _seed_case, _create, _members_spec, _auth)
from modules.payroll.tests._bonus_insure import insure_all  # noqa: E402

ACCOUNTS = "/api/bonus/cases/voucher-accounts"


def _db():
    import db
    return db.get_db()


def _award(no):
    conn = _db()
    try:
        return dict(conn.execute("SELECT * FROM bonus_case_awards WHERE quote_no=?", (no,)).fetchone())
    finally:
        conn.close()


def _voucher(vid):
    conn = _db()
    try:
        v = dict(conn.execute("SELECT * FROM vouchers_all WHERE id=?", (vid,)).fetchone())
        v["lines"] = [dict(r) for r in conn.execute(
            "SELECT account_code, summary, debit, credit FROM voucher_lines WHERE voucher_id=?"
            " ORDER BY line_no", (vid,))]
        return v
    finally:
        conn.close()


def _paid_total(no):
    conn = _db()
    try:
        return conn.execute(
            "SELECT SUM(l.amount) FROM bonus_case_award_lines l JOIN bonus_case_awards a ON a.id=l.award_id"
            " WHERE a.quote_no=?", (no,)).fetchone()[0]
    finally:
        conn.close()


def _to_payout(client, people, no, net=100000):
    _seed_case(no, net=net)
    assert _create(client, people["bc_sa"], no, members=_members_spec()).status_code == 200
    assert client.post("/api/bonus/cases/%s/submit" % no, headers=_auth(people["bc_sa"])).status_code == 200
    return client.post("/api/bonus/cases/%s/approve" % no, headers=_auth(people["bc_sa2"]))


# ── 進入待發放 ⇒ 轉帳傳票草稿 ─────────────────────────────────────────────────

def test_payout_creates_an_accrual_draft_voucher(client, people):
    r = _to_payout(client, people, "MQ-AC3-001")
    assert r.status_code == 200 and r.json()["status"] == "待發放", r.text
    a = _award("MQ-AC3-001")
    assert a["accrual_voucher_id"], "進入待發放要產生一張傳票草稿並記住它"
    v = _voucher(a["accrual_voucher_id"])
    total = _paid_total("MQ-AC3-001")
    assert total > 0
    assert v["status"] == "草稿" and v["voided_at"] == ""
    assert v["category"] == "轉"
    assert "MQ-AC3-001" in v["summary"]
    assert [(l["account_code"], l["debit"], l["credit"]) for l in v["lines"]] == [
        ("6111", total, 0), ("2191", 0, total)]
    assert r.json()["voucher"]["voucher_no"] == v["voucher_no"]


def test_a_middle_approval_tier_does_not_create_a_voucher(client, people):
    """多層簽核：還沒簽完（仍是待審核）⇒ 不產生。"""
    from modules.payroll.tests.test_bonus_case_api_2026_09_24 import _set_flow
    _set_flow(["bc_sa2"])
    import db
    conn = db.get_db()
    try:
        import json
        conn.execute("UPDATE system_settings SET value_json=? WHERE key='bonus_approval_flow'", (json.dumps(
            {"includeSubmitterManagerTier": False, "tiers": [
                {"order": 0, "approvers": [{"username": "bc_sa2", "display_name": "x"}]},
                {"order": 1, "approvers": [{"username": "bc_sa2", "display_name": "x"}]}]}),))
        conn.commit()
    finally:
        conn.close()
    r = _to_payout(client, people, "MQ-AC3-002")
    assert r.json()["status"] == "待審核", r.text
    assert not _award("MQ-AC3-002")["accrual_voucher_id"]


# ── 標記已發放 ⇒ 支出傳票草稿 ─────────────────────────────────────────────────

def test_mark_paid_creates_a_payment_draft_with_a_withholding_line(client, people):
    insure_all()   # U4：撥付前名單上每個人都要有投保金額（tests/_bonus_insure.py）
    _to_payout(client, people, "MQ-AC3-010")
    r = client.post("/api/bonus/cases/MQ-AC3-010/mark-paid", headers=_auth(people["bc_cash"]))
    assert r.status_code == 200 and r.json()["status"] == "已發放", r.text
    a = _award("MQ-AC3-010")
    v = _voucher(a["payment_voucher_id"])
    total = _paid_total("MQ-AC3-010")
    assert v["status"] == "草稿" and v["category"] == "支"
    assert "MQ-AC3-010" in v["summary"]
    assert [(l["account_code"], l["debit"], l["credit"]) for l in v["lines"]] == [
        ("2191", total, 0), ("1113", 0, total), ("2252", 0, 0)]
    assert "代扣稅款" in v["lines"][2]["summary"]
    assert v["created_by"] == "bc_cash", "製票人是按下已發放的出納"


def test_cashier_chooses_the_bank_account(client, people):
    insure_all()   # U4：撥付前名單上每個人都要有投保金額（tests/_bonus_insure.py）
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT OR IGNORE INTO account_items (code, level, name, parent_code, source, is_active)"
                     " VALUES ('11139', 4, '測試第二銀行', '111', 'custom', 1)")
        conn.commit()
    finally:
        conn.close()
    _to_payout(client, people, "MQ-AC3-011")
    r = client.post("/api/bonus/cases/MQ-AC3-011/mark-paid", headers=_auth(people["bc_cash"]),
                    json={"bank_account_code": "11139"})
    assert r.status_code == 200, r.text
    v = _voucher(_award("MQ-AC3-011")["payment_voucher_id"])
    assert v["lines"][1]["account_code"] == "11139"


def test_a_bad_bank_account_is_refused_before_anything_changes(client, people):
    insure_all()   # U4：撥付前名單上每個人都要有投保金額（tests/_bonus_insure.py）
    _to_payout(client, people, "MQ-AC3-012")
    r = client.post("/api/bonus/cases/MQ-AC3-012/mark-paid", headers=_auth(people["bc_cash"]),
                    json={"bank_account_code": "99999"})
    assert r.status_code == 400, r.text
    a = _award("MQ-AC3-012")
    assert a["status"] == "待發放" and not a["payment_voucher_id"]


# ── 退回 ─────────────────────────────────────────────────────────────────────

def test_return_voids_the_accrual_draft_if_not_yet_submitted(client, people):
    _to_payout(client, people, "MQ-AC3-020")
    vid = _award("MQ-AC3-020")["accrual_voucher_id"]
    r = client.post("/api/bonus/cases/MQ-AC3-020/return", headers=_auth(people["bc_sa"]),
                    json={"reason": "比例要調"})
    assert r.status_code == 200, r.text
    v = _voucher(vid)
    assert v["voided_at"], "還沒送審的傳票草稿要作廢"
    assert "比例要調" in v["void_reason"]
    assert not _award("MQ-AC3-020")["accrual_voucher_id"], "作廢之後不再指向它（下次進入待發放另開一張）"


def test_return_leaves_a_submitted_voucher_alone_and_says_so(client, people):
    _to_payout(client, people, "MQ-AC3-021")
    vid = _award("MQ-AC3-021")["accrual_voucher_id"]
    conn = _db()
    try:
        conn.execute("UPDATE vouchers_all SET status='待審核' WHERE id=?", (vid,))
        conn.commit()
    finally:
        conn.close()
    r = client.post("/api/bonus/cases/MQ-AC3-021/return", headers=_auth(people["bc_sa"]),
                    json={"reason": "x"})
    assert r.status_code == 200, r.text
    v = _voucher(vid)
    assert v["voided_at"] == "" and v["status"] == "待審核", "已送審的傳票不動"
    assert v["voucher_no"] in r.json()["notice"]


def test_return_from_pending_approval_has_no_voucher_to_touch(client, people):
    _seed_case("MQ-AC3-022", net=100000)
    _create(client, people["bc_sa"], "MQ-AC3-022", members=_members_spec())
    client.post("/api/bonus/cases/MQ-AC3-022/submit", headers=_auth(people["bc_sa"]))
    r = client.post("/api/bonus/cases/MQ-AC3-022/return", headers=_auth(people["bc_sa"]), json={"reason": "x"})
    assert r.status_code == 200 and not r.json().get("notice"), r.text


def test_after_return_and_reapproval_a_fresh_accrual_is_made(client, people):
    _to_payout(client, people, "MQ-AC3-023")
    first = _award("MQ-AC3-023")["accrual_voucher_id"]
    client.post("/api/bonus/cases/MQ-AC3-023/return", headers=_auth(people["bc_sa"]), json={"reason": "x"})
    client.post("/api/bonus/cases/MQ-AC3-023/submit", headers=_auth(people["bc_sa"]))
    client.post("/api/bonus/cases/MQ-AC3-023/approve", headers=_auth(people["bc_sa2"]))
    second = _award("MQ-AC3-023")["accrual_voucher_id"]
    assert second and second != first


# ── 科目不寫死 ───────────────────────────────────────────────────────────────

def test_accounts_default_and_are_superadmin_only(client, people):
    r = client.get(ACCOUNTS, headers=_auth(people["bc_sa"]))
    assert r.status_code == 200, r.text
    assert r.json()["accounts"] == {"expense": "6111", "payable": "2191",
                                    "withholding": "2252", "nhi": "2252", "bank": "1113"}
    assert client.get(ACCOUNTS, headers=_auth(people["bc_cash"])).status_code == 403
    assert client.put(ACCOUNTS, headers=_auth(people["bc_cash"]),
                      json={"payable": "2191"}).status_code == 403


@pytest.mark.parametrize("code", ["99999", ""])
def test_settings_refuse_a_code_that_does_not_exist(client, people, code):
    r = client.put(ACCOUNTS, headers=_auth(people["bc_sa"]), json={"payable": code})
    assert r.status_code == 400, r.text
    assert client.get(ACCOUNTS, headers=_auth(people["bc_sa"])).json()["accounts"]["payable"] == "2191"


def test_settings_refuse_a_disabled_code(client, people):
    conn = _db()
    try:
        conn.execute("INSERT OR IGNORE INTO account_items (code, level, name, parent_code, source, is_active)"
                     " VALUES ('21919', 4, '停用的應付獎金', '219', 'custom', 0)")
        conn.commit()
    finally:
        conn.close()
    r = client.put(ACCOUNTS, headers=_auth(people["bc_sa"]), json={"payable": "21919"})
    assert r.status_code == 400 and "停用" in r.json()["detail"], r.text


def test_the_configured_account_is_used(client, people):
    conn = _db()
    try:
        conn.execute("INSERT OR IGNORE INTO account_items (code, level, name, parent_code, source, is_active)"
                     " VALUES ('21918', 4, '應付獎金', '219', 'custom', 1)")
        conn.commit()
    finally:
        conn.close()
    assert client.put(ACCOUNTS, headers=_auth(people["bc_sa"]), json={"payable": "21918"}).status_code == 200
    _to_payout(client, people, "MQ-AC3-030")
    v = _voucher(_award("MQ-AC3-030")["accrual_voucher_id"])
    assert v["lines"][1]["account_code"] == "21918"


def test_a_saved_account_later_disabled_means_no_voucher_and_a_notice(client, people):
    conn = _db()
    try:
        conn.execute("INSERT OR IGNORE INTO account_items (code, level, name, parent_code, source, is_active)"
                     " VALUES ('21917', 4, '應付獎金二', '219', 'custom', 1)")
        conn.commit()
    finally:
        conn.close()
    assert client.put(ACCOUNTS, headers=_auth(people["bc_sa"]), json={"payable": "21917"}).status_code == 200
    conn = _db()
    try:
        conn.execute("UPDATE account_items SET is_active=0 WHERE code='21917'")
        conn.commit()
    finally:
        conn.close()
    r = _to_payout(client, people, "MQ-AC3-031")
    assert r.status_code == 200 and r.json()["status"] == "待發放", "科目有問題不可以擋住簽核本身"
    assert not _award("MQ-AC3-031")["accrual_voucher_id"]
    assert "21917" in r.json()["notice"] and "停用" in r.json()["notice"]


# ── 看得到連結（獎金頁提示用） ─────────────────────────────────────────────────

def test_detail_lists_the_linked_vouchers(client, people):
    _to_payout(client, people, "MQ-AC3-040")
    d = client.get("/api/bonus/cases/MQ-AC3-040", headers=_auth(people["bc_sa"])).json()
    v = _voucher(_award("MQ-AC3-040")["accrual_voucher_id"])
    assert [(x["kind"], x["voucher_no"], x["status"]) for x in d["vouchers"]] == [
        ("accrual", v["voucher_no"], "草稿")]
    d = client.get("/api/bonus/cases/MQ-AC3-040", headers=_auth(people["bc_s1"])).json()
    assert "vouchers" not in d, "名單上的人看自己那一列，不給傳票資訊"
