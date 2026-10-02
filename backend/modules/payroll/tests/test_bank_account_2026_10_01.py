# -*- coding: utf-8 -*-
"""員工收款帳號（payroll v3 `user_bank_accounts`）：驗證、遮蔽矩陣、IDOR、稽核不含全碼、快照、提供者 reveal 必帶 token。

設計：D:\\開發測試檔\\expense-forms-design-ae.md 切片 1。
"""
import json

import pytest

from modules.payroll import bank_account as ba

NUM = "0011223344556"            # 13 碼（測試帳號）
GOOD = {"bankCode": "004", "bankName": "臺灣銀行", "bankBranch": "台中分行", "accountName": "王小明", "accountNumber": "0011-2233 44556"}


def _login(client, u):
    r = client.post("/api/auth/login", json={"username": u[0], "password": u[1]})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _uid(username):
    import db
    c = db.get_db()
    try:
        return c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        c.close()


def _audit_rows(action=None):
    import db
    c = db.get_db()
    try:
        q = "SELECT action, target_id, detail, target_label FROM audit_log" + (" WHERE action=?" if action else "")
        return [dict(r) for r in c.execute(q, (action,) if action else ())]
    finally:
        c.close()


def _no_full_number_anywhere():
    """稽核表所有欄位都不可出現帳號全碼。"""
    import db
    c = db.get_db()
    try:
        blob = json.dumps([dict(r) for r in c.execute("SELECT * FROM audit_log")], ensure_ascii=False)
    finally:
        c.close()
    assert NUM not in blob, "稽核紀錄含帳號全碼"


# ── 純函式 ────────────────────────────────────────────────
def test_validate_accepts_spaces_and_hyphens_and_normalises():
    f = ba.validate(GOOD)
    assert f["account_number"] == NUM and f["bank_code"] == "004" and f["account_name"] == "王小明"


@pytest.mark.parametrize("patch,expect", [
    ({"bankCode": "4"}, "3 位數字"), ({"bankCode": "abc"}, "3 位數字"), ({"bankCode": ""}, "銀行代碼"),
    ({"accountNumber": "12345"}, "6～16"), ({"accountNumber": "1" * 17}, "6～16"), ({"accountNumber": "12ab5678"}, "只能是數字"),
    ({"accountNumber": ""}, "帳號"), ({"accountName": ""}, "戶名"), ({"accountName": "王\x00明"}, "不合法"),
    ({"bankName": "x" * 41}, "太長"),
])
def test_validate_rejects(patch, expect):
    with pytest.raises(ba.Invalid) as e:
        ba.validate({**GOOD, **patch})
    assert expect in str(e.value)
    assert NUM not in str(e.value) and "12ab5678" not in str(e.value)        # 錯誤訊息不回帳號值


def test_mask_number_boundaries():
    assert ba.mask_number(NUM) == "****4556"
    assert ba.mask_number("1234") == "****" and ba.mask_number("12") == "****"
    assert ba.mask_number("") == "" and ba.mask_number(None) == ""


# ── migration ─────────────────────────────────────────────
def test_migration_is_idempotent_and_keeps_one_active_row_per_user():
    import sqlite3
    import importlib
    m = importlib.import_module("modules.payroll.migrations.0003_user_bank_accounts")
    conn = sqlite3.connect(":memory:")
    m.up(conn)
    m.up(conn)                                          # 重跑不壞
    conn.execute("INSERT INTO user_bank_accounts (user_id, username, active) VALUES (1, 'a', 1)")
    with pytest.raises(sqlite3.IntegrityError):         # 同一人第二個有效列 ⇒ 被擋
        conn.execute("INSERT INTO user_bank_accounts (user_id, username, active) VALUES (1, 'a', 1)")
    conn.execute("INSERT INTO user_bank_accounts (user_id, username, active) VALUES (1, 'a', 0)")   # 歷史列可多筆


# ── API：本人 ─────────────────────────────────────────────
def test_owner_saves_and_reads_own_full_account_and_history_keeps_old_rows(client, make_user):
    a = make_user(username="ba_a", role="viewer", modules=[])
    h = _login(client, a)
    assert client.get("/api/me/bank-account", headers=h).json()["account"] == {"status": "none"}
    r = client.put("/api/me/bank-account", json=GOOD, headers=h)
    assert r.status_code == 200 and set(r.json()["changed"]) == set(ba.FIELDS), r.text
    acc = client.get("/api/me/bank-account", headers=h).json()["account"]
    assert acc["status"] == "ok" and acc["accountNumber"] == NUM and acc["masked"] is False and acc["last4"] == "4556"
    # 沒變更 ⇒ changed 空
    assert client.put("/api/me/bank-account", json=GOOD, headers=h).json()["changed"] == []
    # 改帳號 ⇒ 舊列留歷史、只有一個有效
    r = client.put("/api/me/bank-account", json={**GOOD, "accountNumber": "99887766"}, headers=h)
    assert r.json()["changed"] == ["accountNumber"]
    import db
    c = db.get_db()
    try:
        rows = c.execute("SELECT active, account_number FROM user_bank_accounts WHERE username='ba_a' ORDER BY id").fetchall()
    finally:
        c.close()
    assert [(x["active"], x["account_number"]) for x in rows] == [(0, NUM), (1, "99887766")]
    upd = _audit_rows("user.bank_account.update")
    assert len(upd) == 2
    d = json.loads(upd[1]["detail"])
    assert d["before_last4"] == "4556" and d["after_last4"] == "7766" and d["fields"] == ["accountNumber"] and d["byAdmin"] is False
    assert d["changedBy"] == "ba_a" and isinstance(d["userId"], int)                           # 誰改誰（只有 id／帳號名，沒有帳號全碼）
    _no_full_number_anywhere()


def test_invalid_input_is_400_and_nothing_is_written(client, make_user):
    h = _login(client, make_user(username="ba_bad", role="viewer", modules=[]))
    r = client.put("/api/me/bank-account", json={**GOOD, "accountNumber": "12ab"}, headers=h)
    assert r.status_code == 400 and "12ab" not in r.text
    assert client.get("/api/me/bank-account", headers=h).json()["account"] == {"status": "none"}


def test_unauthenticated_is_rejected(client):
    assert client.get("/api/me/bank-account").status_code in (401, 403)
    assert client.put("/api/me/bank-account", json=GOOD).status_code in (401, 403)
    assert client.get("/api/bank-accounts").status_code in (401, 403)


# ── API：他人（遮蔽矩陣／IDOR） ───────────────────────────
def _seed_owner(client, make_user):
    a = make_user(username="ba_owner", role="viewer", modules=[])
    assert client.put("/api/me/bank-account", json=GOOD, headers=_login(client, a)).status_code == 200
    return a, _uid("ba_owner")


def test_plain_users_and_approvers_cannot_see_others_at_all(client, make_user):
    _a, uid = _seed_owner(client, make_user)
    other = _login(client, make_user(username="ba_plain", role="viewer", modules=[]))
    admin = _login(client, make_user(username="ba_adm", role="admin", modules=["case_manage"]))       # admin 但沒有 finance／cashier
    for h in (other, admin):
        assert client.get("/api/bank-accounts/%d" % uid, headers=h).status_code == 404
        assert client.get("/api/bank-accounts", headers=h).status_code == 404
        assert client.get("/api/bank-accounts/%d/history" % uid, headers=h).status_code == 404
        assert client.put("/api/bank-accounts/%d" % uid, json={**GOOD, "accountNumber": "55555555"}, headers=h).status_code == 404


def test_cashier_sees_masked_by_default_reveals_with_audit_and_cannot_edit(client, make_user):
    _a, uid = _seed_owner(client, make_user)
    cash = _login(client, make_user(username="ba_cash", role="viewer", modules=["cashier"]))
    r = client.get("/api/bank-accounts/%d" % uid, headers=cash)
    acc = r.json()["account"]
    assert r.status_code == 200 and acc["masked"] is True and acc["accountNumber"] == "" and acc["accountNumberMasked"] == "****4556"
    assert NUM not in r.text and r.json()["canEdit"] is False
    assert _audit_rows("user.bank_account.reveal") == []
    r = client.get("/api/bank-accounts/%d?reveal=1" % uid, headers=cash)
    assert r.json()["account"]["accountNumber"] == NUM and r.json()["account"]["masked"] is False
    rev = _audit_rows("user.bank_account.reveal")
    assert len(rev) == 1 and json.loads(rev[0]["detail"]) == {"last4": "4556", "purpose": "profile"}
    _no_full_number_anywhere()
    # 出納看清單：只有末四碼
    lst = client.get("/api/bank-accounts", headers=cash)
    assert lst.status_code == 200 and NUM not in lst.text and "4556" in lst.text and lst.json()["canEdit"] is False
    # 出納不能改別人的、也不能看歷史
    assert client.put("/api/bank-accounts/%d" % uid, json={**GOOD, "accountNumber": "55555555"}, headers=cash).status_code == 404
    assert client.get("/api/bank-accounts/%d/history" % uid, headers=cash).status_code == 404


def test_finance_and_superadmin_can_maintain_others_and_it_is_audited_as_by_admin(client, make_user):
    _a, uid = _seed_owner(client, make_user)
    fin = _login(client, make_user(username="ba_fin", role="viewer", modules=["finance"]))
    r = client.put("/api/bank-accounts/%d" % uid, json={**GOOD, "accountNumber": "44332211"}, headers=fin)
    assert r.status_code == 200 and r.json()["changed"] == ["accountNumber"]
    last = _audit_rows("user.bank_account.update")[-1]
    assert json.loads(last["detail"])["byAdmin"] is True
    hist = client.get("/api/bank-accounts/%d/history" % uid, headers=fin).json()["history"]
    assert [h["active"] for h in hist] == [True, False] and all(NUM not in json.dumps(h) and "44332211" not in json.dumps(h) for h in hist)
    sup = _login(client, make_user(username="ba_sup", role="superadmin", modules=[]))
    assert client.put("/api/bank-accounts/%d" % uid, json={**GOOD, "accountNumber": "66778899"}, headers=sup).status_code == 200
    assert client.put("/api/bank-accounts/999999", json=GOOD, headers=sup).status_code == 404        # 不存在的人
    _no_full_number_anywhere()


def test_a_user_can_use_the_admin_path_for_themselves_only(client, make_user):
    a = make_user(username="ba_self", role="viewer", modules=[])
    h = _login(client, a)
    uid = _uid("ba_self")
    assert client.put("/api/bank-accounts/%d" % uid, json=GOOD, headers=h).status_code == 200
    r = client.get("/api/bank-accounts/%d" % uid, headers=h)
    assert r.status_code == 200 and r.json()["account"]["accountNumber"] == NUM and r.json()["canEdit"] is True
    assert _audit_rows("user.bank_account.reveal") == []                 # 本人看自己的不寫 reveal


# ── 提供者與快照 ──────────────────────────────────────────
def test_provider_reveal_requires_an_audit_token_and_is_masked_for_everyone_else(client, make_user):
    import db
    _a, uid = _seed_owner(client, make_user)
    cash = make_user(username="ba_cash2", role="viewer", modules=["cashier"])
    cash_h = _login(client, cash)
    tok = cash_h["Authorization"].split(" ", 1)[1]
    conn = db.get_db()
    try:
        def viewer(name):
            r = conn.execute("SELECT id, username, role, modules FROM users WHERE username=?", (name,)).fetchone()
            return dict(r)
        v_cash, v_owner = viewer("ba_cash2"), viewer("ba_owner")
        # 沒帶 token ⇒ 不給全碼
        out = ba.payee_bank_profile(conn, "ba_owner", v_cash, reveal=True)
        assert out["masked"] is True and out["accountNumber"] == "" and "revealRefused" in out
        assert _audit_rows("user.bank_account.reveal") == []
        # 帶 token ⇒ 全碼＋稽核
        out = ba.payee_bank_profile(conn, "ba_owner", v_cash, reveal=True, audit_token=tok, purpose="payout")
        assert out["accountNumber"] == NUM and out["masked"] is False
        rev = _audit_rows("user.bank_account.reveal")
        assert len(rev) == 1 and json.loads(rev[0]["detail"]) == {"last4": "4556", "purpose": "payout"}
        # 沒資格者（簽核人）reveal ⇒ 照遮蔽，不寫稽核
        appr = {"id": 0, "username": "some_approver", "role": "admin", "modules": json.dumps(["case_manage"])}
        out = ba.payee_bank_profile(conn, "ba_owner", appr, reveal=True, audit_token=tok)
        assert out["masked"] is True and out["accountNumber"] == "" and out["accountNumberMasked"] == "****4556"
        assert len(_audit_rows("user.bank_account.reveal")) == 1
        # 本人看自己：完整，不寫稽核
        assert ba.payee_bank_profile(conn, "ba_owner", v_owner)["accountNumber"] == NUM
        assert len(_audit_rows("user.bank_account.reveal")) == 1
        # 沒登錄 ⇒ status none
        assert ba.payee_bank_profile(conn, "nobody", v_cash) == {"status": "none"}
        # 快照：只有遮蔽版，不含全碼
        snap = ba.snapshot(conn, "ba_owner", appr)
        assert snap["status"] == "ok" and snap["last4"] == "4556" and NUM not in json.dumps(snap, ensure_ascii=False) and "accountNumber" not in snap
        assert ba.snapshot(conn, "nobody", appr) == {"status": "none"}
    finally:
        conn.close()
    _no_full_number_anywhere()


def test_provider_is_registered_under_the_documented_capability():
    from core import registry
    prov = registry.providers("payee.bank_profile")
    assert "payroll" in prov and prov["payroll"] is ba.payee_bank_profile
