# -*- coding: utf-8 -*-
"""請款流程（CORE-SPEC「請款流程（下一版）」，2026-09-27 使用者裁示）：M01 這一側。

- 發票類附件：核准後只有 kind=invoice 可以直接補上傳（稽核動作 extra_expense.invoice_after_approval）；其他類與刪除照舊上鎖；
  舊附件沒有 kind（＝其他），不回填。
- 發票號碼（case v1 migration 的 invoice_no）：選填、長度上限、已核准也可以補。
- 請款頁的兩支查詢：挑案件（只列看得到的）、我的請款（只列自己的）。
- IP-100 提供者：只列已核准且付款日空白；mark_paid 寫回付款日 ⇒ 消失。
- 月支出：草稿與已駁回不計（權責、現金兩種口徑）；送審中照計（pending）；現金口徑有付款日就用付款日、不是暫用。
本檔在 M05（出納）不在的安裝包裡照樣要過（請款不依賴出納）：不 import、不打任何 M05 的東西。
"""
import io
import json

import pytest

from tests._requires import requires_module, skip_module_unless

skip_module_unless("case", "本檔全部是 M01 的額外支出／請款")

from core import registry  # noqa: E402

NO = "MQ-PR-001"
BASE = "/api/quotations/%s/extra-expenses" % NO


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _x(sql, args=()):
    import db
    conn = db.get_db()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _uid(username):
    return _q("SELECT id FROM users WHERE username=?", (username,))[0]["id"]


def _case(no=NO, assigned=()):
    _x("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
       " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
       (no, "已送出", "請款客", "請款專案", 100000, 95238, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00",
        "2026-01-01T00:00:00", "已成案", "", json.dumps(list(assigned))))


def _no_tiers():
    _x("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
       ("unified_approval_flow", json.dumps({"tiers": [], "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))


def _png():
    return ("a.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 64), "image/png")


@pytest.fixture
def req(client, make_user):
    """一位被指派到案件的工程師（非 admin）＋一筆已送審、自動核准的請款（沒有簽核層 ⇒ 送審即核准）。"""
    u, p = make_user(username="pr_eng", role="sales")
    _case(assigned=[_uid(u)])
    _no_tiers()
    h = _login(client, u, p)
    r = client.post(BASE, json={"category": "差旅", "description": "北上安裝", "qty": 1, "unitCost": 3200, "expenseDate": "2031-03-05"},
                    headers=h)
    assert r.status_code in (200, 201), r.text
    eid = r.json()["id"]
    r = client.post(BASE + "/%d/files" % eid, files={"files": _png()}, headers=h)          # 沒帶 kind ⇒ other
    assert r.status_code == 201, r.text
    return {"h": h, "id": eid, "user": u}


def _approve(client, req):
    r = client.post(BASE + "/%d/submit" % req["id"], headers=req["h"])
    assert r.status_code == 200 and r.json()["status"] == "已核准", r.text


def test_after_approval_only_invoice_uploads_and_is_audited(client, req):
    _approve(client, req)
    r = client.post(BASE + "/%d/files" % req["id"], files={"files": _png()}, headers=req["h"])
    assert r.status_code == 409 and "發票可由填寫人、管理員或出納補上傳" in r.json()["detail"], r.text        # 其他類照舊上鎖
    r = client.post(BASE + "/%d/files" % req["id"], files={"files": _png()}, data={"kind": "invoice"}, headers=req["h"])
    assert r.status_code == 201, r.text
    files = json.loads(_q("SELECT files_json FROM case_extra_expenses WHERE id=?", (req["id"],))[0]["files_json"])
    assert [f.get("kind") for f in files] == ["other", "invoice"]
    fid = files[1]["id"]
    assert client.delete(BASE + "/%d/files/%s" % (req["id"], fid), headers=req["h"]).status_code == 409   # 刪除照舊上鎖
    acts = [r["action"] for r in _q("SELECT action FROM audit_log WHERE target_id=? ORDER BY id", (NO,))]
    assert "extra_expense.invoice_after_approval" in acts, acts


def test_after_approval_a_case_reader_who_is_not_the_requester_cannot_add_invoice(client, make_user, req):
    """§G5-14 另一個方向：「本人可補」這條分支，用**看得到案件、但不是填寫人、沒有 admin／出納**的人測 ⇒ 403、內容不變、沒有稽核紀錄。
    （上一題的填寫人也是一般 sales ⇒ 放行的確實是「本人」，不是一般權限。）"""
    _approve(client, req)
    u2, p2 = make_user(username="pr_peer", role="sales")
    _x("UPDATE quotations SET assigned_user_ids=? WHERE quote_no=?", (json.dumps([_uid(req["user"]), _uid(u2)]), NO))
    h2 = _login(client, u2, p2)
    assert client.get(BASE, headers=h2).status_code == 200                                  # 看得到案件：擋下的是本人規則，不是案件可見
    before = _q("SELECT files_json FROM case_extra_expenses WHERE id=?", (req["id"],))[0]["files_json"]
    r = client.post(BASE + "/%d/files" % req["id"], files={"files": _png()}, data={"kind": "invoice"}, headers=h2)
    assert r.status_code == 403, r.text
    r = client.patch(BASE + "/%d/dates" % req["id"], json={"invoiceNo": "ZZ00000000"}, headers=h2)
    assert r.status_code == 403, r.text
    row = _q("SELECT files_json, invoice_no FROM case_extra_expenses WHERE id=?", (req["id"],))[0]
    assert row["files_json"] == before and row["invoice_no"] == ""
    acts = [r["action"] for r in _q("SELECT action FROM audit_log WHERE target_id=? ORDER BY id", (NO,))]
    assert "extra_expense.invoice_after_approval" not in acts, acts


def test_unknown_kind_rejected_and_legacy_files_without_kind_are_not_backfilled(client, req):
    r = client.post(BASE + "/%d/files" % req["id"], files={"files": _png()}, data={"kind": "receipt"}, headers=req["h"])
    assert r.status_code == 400
    _x("UPDATE case_extra_expenses SET files_json=? WHERE id=?", (json.dumps([{"id": "old1", "filename": "舊.pdf"}]), req["id"]))
    got = client.get(BASE, headers=req["h"]).json()
    row = [e for e in got["items"] if e["id"] == req["id"]][0]
    assert row["files"] == [{"id": "old1", "filename": "舊.pdf"}]                               # 沒有 kind ⇒ 原樣（畫面當其他）


def test_case_v1_without_the_table_holds_the_version_and_adds_the_column_later(tmp_path, monkeypatch):
    """case v1（0001）：表不在 ⇒ 回原因（未完成）、不建表、版號停在 0、incomplete 有它；表建好再跑 ⇒ 補上欄位、記 v1、incomplete 清空。
    （2026-09-28 使用者裁示「該補就補」：原本什麼都不做卻照樣記 v1 ⇒ 之後永遠不會補。）"""
    import importlib
    import sqlite3
    import db
    from core import migrations
    up = importlib.import_module("modules.case.migrations.0001_extra_expense_invoice_no").up
    monkeypatch.setattr(migrations, "_REGISTRY", {})
    monkeypatch.setattr(migrations, "_INCOMPLETE", {})
    migrations.register("case", 1, up)
    path = tmp_path / "bare.db"
    conn = sqlite3.connect(str(path))
    try:
        db._ensure_module_schema_versions(conn)
        migrations.run_all(conn)
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='case_extra_expenses'").fetchall(), "不可以自己建表"
        assert migrations.current_version(conn, "case") == 0
        assert migrations.incomplete(str(path))["case"][0] == 1
        conn.execute("CREATE TABLE case_extra_expenses (id INTEGER PRIMARY KEY, quote_no TEXT)")
        conn.commit()
        migrations.run_all(conn)
        assert "invoice_no" in {r[1] for r in conn.execute("PRAGMA table_info(case_extra_expenses)").fetchall()}
        assert migrations.current_version(conn, "case") == 1 and migrations.incomplete(str(path)) == {}
        assert up(conn) is None                                                              # 冪等：欄位已在
    finally:
        conn.close()


def test_invoice_no_is_optional_capped_and_can_be_added_after_approval(client, req):
    assert "invoice_no" in {r[1] for r in _q("PRAGMA table_info(case_extra_expenses)")}      # case v1 migration 跑過
    _approve(client, req)
    r = client.patch(BASE + "/%d/dates" % req["id"], json={"invoiceNo": "X" * 41}, headers=req["h"])
    assert r.status_code == 400
    r = client.patch(BASE + "/%d/dates" % req["id"], json={"invoiceNo": " AB12345678 "}, headers=req["h"])
    assert r.status_code == 200 and r.json()["invoiceNo"] == "AB12345678", r.text
    assert _q("SELECT invoice_no FROM case_extra_expenses WHERE id=?", (req["id"],))[0]["invoice_no"] == "AB12345678"


def test_payreq_case_picker_and_mine_only_show_what_the_user_may_see(client, make_user, req):
    _case("MQ-PR-HIDDEN")                                                                    # 沒指派 ⇒ 看不到
    cases = client.get("/api/extra-expenses/cases?q=MQ-PR", headers=req["h"]).json()
    assert [c["quoteNo"] for c in cases] == [NO], cases
    mine = client.get("/api/extra-expenses/mine", headers=req["h"]).json()
    assert [(e["id"], e["quoteNo"], e["customerName"]) for e in mine] == [(req["id"], NO, "請款客")]
    u2, p2 = make_user(username="pr_other", role="sales")
    assert client.get("/api/extra-expenses/mine", headers=_login(client, u2, p2)).json() == []


def test_case_picker_filters_visibility_before_limiting(client, req):
    """先過濾可見再取前 N 筆：比它新的 501 筆看不到的同名案件，不可以把較舊、看得到的那一筆擠掉（原本先 LIMIT 500 再過濾）。"""
    import db
    conn = db.get_db()
    try:
        conn.executemany(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
            " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [("MQ-PR-N%03d" % i, "已送出", "別人的客", "別人的案", 1, 1, "{}", "2026-06-01T00:00:00", "2026-06-01T00:00:00",
              "已成案", "", "[]") for i in range(501)])
        conn.commit()
    finally:
        conn.close()
    cases = client.get("/api/extra-expenses/cases?q=MQ-PR", headers=req["h"]).json()
    assert [c["quoteNo"] for c in cases] == [NO], [c["quoteNo"] for c in cases][:5]


def test_case_picker_treats_like_wildcards_literally(client, req):
    """`%`、`_` 照字面比對（ESCAPE）：輸入 `%` 只找得到名稱裡真的有 % 的案件，不是「全部」。"""
    _case("MQ-PR-PCT", assigned=[_uid(req["user"])])
    _x("UPDATE quotations SET project_name='九折 50% 專案' WHERE quote_no='MQ-PR-PCT'")

    def got(q):
        r = client.get("/api/extra-expenses/cases", params={"q": q}, headers=req["h"])
        return sorted(c["quoteNo"] for c in r.json())

    assert got("MQ-PR") == sorted([NO, "MQ-PR-PCT"])                                         # 正對照：兩筆都看得到
    assert got("%") == ["MQ-PR-PCT"]
    assert got("_") == []
    assert got("MQ_PR") == []                                                                  # `_` 不當成任一字元


def test_provider_lists_approved_unpaid_and_mark_paid_writes_back(client, req):
    prov = registry.providers("payables.pending")["case"]
    import db
    conn = db.get_db()
    try:
        assert [i["key"] for i in prov.pending(conn) if i["quoteNo"] == NO] == []           # 已核准才列（現在是草稿）
    finally:
        conn.close()
    _approve(client, req)
    conn = db.get_db()
    try:
        items = [i for i in prov.pending(conn) if i["quoteNo"] == NO]
        assert [(i["key"], i["amount"], i["customerName"]) for i in items] == [(str(req["id"]), 3200.0, "請款客")]
        prov.mark_paid(conn, str(req["id"]), "2031-03-20", {"username": "cashier_x"})
        conn.commit()
        assert [i for i in prov.pending(conn) if i["quoteNo"] == NO] == []                  # 登錄付款 ⇒ 消失
        with pytest.raises(ValueError):
            prov.mark_paid(conn, str(req["id"]), "2031-03-21", {"username": "cashier_x"})    # 不重複登錄
        with pytest.raises(LookupError):
            prov.mark_paid(conn, "999999", "2031-03-21", {"username": "cashier_x"})
    finally:
        conn.close()
    assert _q("SELECT paid_date FROM case_extra_expenses WHERE id=?", (req["id"],))[0]["paid_date"] == "2031-03-20"


def _peer(client, make_user, req, username, role="sales", cashier=False):
    """看得到這個案件（被指派）、但不是填寫人的使用者；cashier=True ⇒ 另加出納模組（保留角色預設模組）。"""
    u, p = make_user(username=username, role=role)
    if cashier:
        mods = json.loads(_q("SELECT modules FROM users WHERE username=?", (u,))[0]["modules"] or "[]")
        _x("UPDATE users SET modules=? WHERE username=?", (json.dumps(sorted(set(mods) | {"cashier"})), u))
    ids = json.loads(_q("SELECT assigned_user_ids FROM quotations WHERE quote_no=?", (NO,))[0]["assigned_user_ids"] or "[]")
    _x("UPDATE quotations SET assigned_user_ids=? WHERE quote_no=?", (json.dumps(ids + [_uid(u)]), NO))
    return _login(client, u, p)


def _pending_keys():
    import db
    conn = db.get_db()
    try:
        return [i["key"] for i in registry.providers("payables.pending")["case"].pending(conn) if i["quoteNo"] == NO]
    finally:
        conn.close()


def _paid(req):
    return _q("SELECT paid_date FROM case_extra_expenses WHERE id=?", (req["id"],))[0]["paid_date"] or ""


def _acts():
    return [r["action"] for r in _q("SELECT action FROM audit_log WHERE target_id=? ORDER BY id", (NO,))]


def test_requester_cannot_set_or_clear_the_paid_date_but_other_dates_still_work(client, make_user, req):
    """稽核 A AB-M1：付款日＝出納待付款的判準 ⇒ 填寫人（一般 sales）設／清付款日 ⇒ 403、資料與待付款不變；
    發票日期、發票號碼照舊本人可登（AC2 不變）。"""
    _approve(client, req)
    dates = BASE + "/%d/dates" % req["id"]
    r = client.patch(dates, json={"paidDate": "2031-03-09"}, headers=req["h"])
    assert r.status_code == 403 and "出納或管理員" in r.json()["detail"], r.text
    assert _paid(req) == "" and _pending_keys() == [str(req["id"])]                        # 沒有繞過出納
    r = client.patch(dates, json={"invoiceDate": "2031-03-08", "invoiceNo": "AB00000001"}, headers=req["h"])
    assert r.status_code == 200, r.text
    row = _q("SELECT invoice_date, invoice_no FROM case_extra_expenses WHERE id=?", (req["id"],))[0]
    assert (row["invoice_date"], row["invoice_no"]) == ("2031-03-08", "AB00000001")
    _x("UPDATE case_extra_expenses SET paid_date='2031-03-10' WHERE id=?", (req["id"],))      # 出納已付
    r = client.patch(dates, json={"paidDate": ""}, headers=req["h"])
    assert r.status_code == 403, r.text
    assert _paid(req) == "2031-03-10" and _pending_keys() == []                              # 沒有重回待付款


def test_cashier_sets_the_paid_date_but_only_admin_changes_or_clears_it_with_its_own_audit(client, make_user, req):
    """AB-M1 另一方向：出納設 ⇒ 200、從待付款消失；出納改已付的日期 ⇒ 403；admin 清除 ⇒ 200、重回待付款、
    稽核有專用動作 extra_expense.paid_date_override（只在更正時出現，第一次登錄沒有）。"""
    _approve(client, req)
    hc = _peer(client, make_user, req, "pr_cash", cashier=True)
    dates = BASE + "/%d/dates" % req["id"]
    r = client.patch(dates, json={"paidDate": "2031-03-12"}, headers=hc)
    assert r.status_code == 200, r.text
    assert _paid(req) == "2031-03-12" and _pending_keys() == []
    assert "extra_expense.paid_date_override" not in _acts()
    r = client.patch(dates, json={"paidDate": "2031-03-13"}, headers=hc)
    assert r.status_code == 403 and "只限管理員" in r.json()["detail"], r.text
    assert _paid(req) == "2031-03-12"
    ha = _peer(client, make_user, req, "pr_boss", role="admin")
    r = client.patch(dates, json={"paidDate": ""}, headers=ha)
    assert r.status_code == 200, r.text
    assert _paid(req) == "" and _pending_keys() == [str(req["id"])]
    assert _acts().count("extra_expense.paid_date_override") == 1


def test_cashier_who_can_see_the_case_may_add_invoice_after_approval(client, make_user, req):
    """稽核 A AB-S5：「或出納」那一條放行——看得到案件、不是填寫人、角色一般 sales＋出納模組 ⇒ 補發票 201、發票號碼 200。
    （同一個人拿掉出納模組就是前面 403 那一題 ⇒ 放行的確實是「出納」這一條。）"""
    _approve(client, req)
    hc = _peer(client, make_user, req, "pr_cash2", cashier=True)
    r = client.post(BASE + "/%d/files" % req["id"], files={"files": _png()}, data={"kind": "invoice"}, headers=hc)
    assert r.status_code == 201, r.text
    r = client.patch(BASE + "/%d/dates" % req["id"], json={"invoiceNo": "CS00000001"}, headers=hc)
    assert r.status_code == 200, r.text
    assert "extra_expense.invoice_after_approval" in _acts()


def test_paid_date_only_after_approval_for_cashier_and_admin_alike(client, make_user, req):
    """AB-S8（使用者裁示）：未核准（草稿）設付款日 ⇒ 409 並說明、資料不變——出納、admin 都一樣；核准後 ⇒ 200。"""
    dates = BASE + "/%d/dates" % req["id"]
    hc = _peer(client, make_user, req, "pr_cash3", cashier=True)
    ha = _peer(client, make_user, req, "pr_boss3", role="admin")
    for h in (hc, ha):
        r = client.patch(dates, json={"paidDate": "2031-03-15"}, headers=h)
        assert r.status_code == 409 and "還沒核准" in r.json()["detail"], r.text
    assert _paid(req) == ""
    _approve(client, req)
    r = client.patch(dates, json={"paidDate": "2031-03-15"}, headers=hc)
    assert r.status_code == 200, r.text
    assert _paid(req) == "2031-03-15"


def _demo_login(client):
    """demo 帳號的密碼是隨機產生的 ⇒ 直接改成已知值（同 tests/test_upload_demo_isolation 的做法）。"""
    import db
    from helpers.auth import _hash_pw
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET password_hash=? WHERE username='demo'", (_hash_pw("Demo-Pass-123"),))
        conn.commit()
    finally:
        conn.close()
    return _login(client, "demo", "Demo-Pass-123")


def test_demo_mode_says_the_module_is_absent_while_real_users_are_unaffected(client, make_user, monkeypatch):
    """AB-S7（使用者裁示）：只有示範庫的 migration 沒完成 ⇒ 正式請求照常 200；demo token ⇒ 404＋明說原因。
    反向控制：示範缺席表清空 ⇒ demo 照常 200（證明 404 來自這張表，不是 demo 本來就打不到）。"""
    from helpers import module_startup as ms
    why = "示範資料的資料庫升級未完成（case v1），示範模式暫不提供這個模組：測試"
    monkeypatch.setattr(ms, "_DEMO_ABSENT", {"case": why})
    h = _login(client, *make_user(username="pr_real", role="admin"))
    assert client.get("/api/quotations", headers=h).status_code == 200
    hd = _demo_login(client)
    r = client.get("/api/quotations", headers=hd)
    assert r.status_code == 404 and r.json()["detail"] == why, r.text
    monkeypatch.setattr(ms, "_DEMO_ABSENT", {})
    assert client.get("/api/quotations", headers=hd).status_code == 200


def test_second_cashier_gets_already_paid_and_does_not_overwrite(client, req):
    """稽核 A AB-S1：mark_paid 是帶條件的 UPDATE（付款日空白才寫）⇒ 後到的出納拿到「已被登錄」、不蓋掉前者的付款日。"""
    _approve(client, req)
    import db
    prov = registry.providers("payables.pending")["case"]
    conn = db.get_db()
    try:
        prov.mark_paid(conn, str(req["id"]), "2031-04-01", {"username": "cash_a"})
        conn.commit()
        with pytest.raises(ValueError, match="已被登錄"):
            prov.mark_paid(conn, str(req["id"]), "2031-04-02", {"username": "cash_b"})
        conn.commit()
    finally:
        conn.close()
    assert _paid(req) == "2031-04-01"


def _other(client, h, basis):
    r = client.get("/api/reports/expenses-monthly?year=2031&basis=%s" % basis, headers=h)
    assert r.status_code == 200, r.text
    return [(d["date"], d["amount"], d.get("pending"), d.get("provisional")) for d in r.json()["expenses"]["details"]["other"]
            if d["quoteNo"] == NO]


@requires_module("analytics", "月支出報表（M08）")
def test_monthly_expenses_exclude_draft_and_rejected_in_both_bases_and_cash_uses_paid_date(client, make_user, seed_extra_expense):
    _case()
    for st, amt in (("草稿", 111), ("已駁回", 222), ("待審核", 333), ("簽核中", 444), ("已核准", 555)):
        seed_extra_expense(NO, total_cost=amt, description=st, expense_date="2031-04-02", status=st)
    au, ap = make_user(username="pr_admin", role="superadmin")
    h = _login(client, au, ap)
    for basis in ("accrual", "cash"):
        got = sorted(a for _d, a, _p, _v in _other(client, h, basis))
        assert got == [333, 444, 555], (basis, got)                                          # 草稿、已駁回不計
    pend = {a: p for _d, a, p, _v in _other(client, h, "cash")}
    assert pend == {333: True, 444: True, 555: False}                                        # 送審中照計、標待定
    eid = _q("SELECT id FROM case_extra_expenses WHERE quote_no=? AND total_cost=555", (NO,))[0]["id"]
    assert [(d, v) for d, a, _p, v in _other(client, h, "cash") if a == 555] == [("2031-04-02", True)]   # 未付款：憑證日、暫用
    _x("UPDATE case_extra_expenses SET paid_date='2031-06-15' WHERE id=?", (eid,))
    assert [(d, v) for d, a, _p, v in _other(client, h, "cash") if a == 555] == [("2031-06-15", False)]  # 付款日、不是暫用
