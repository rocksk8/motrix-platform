# -*- coding: utf-8 -*-
"""歷史紀錄分層搜尋＋失敗紀錄（使用者 2026-09-30：「人員的紀錄或是操作紀錄可以分層依模組、案件等搜尋，或是紀錄中有失敗能快速查詢的功能」）。

涵蓋：欄位派生（純函式）、migration v3（回填／可重入／索引／與寫入端同規則）、API 篩選＋keyset＋權限、
失敗鉤子（狀態碼／GET 不記／限流／每小時上限／不記請求內容）、登入失敗、分層樹計數、100k 列效能。"""
import json
import sqlite3
import time

import pytest

from helpers import audit as A


@pytest.fixture(autouse=True)
def _clean_fail_state():
    A._FAIL_LAST.clear()
    A._FAIL_HOUR.clear()
    yield
    A._FAIL_LAST.clear()
    A._FAIL_HOUR.clear()


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _rows(where="1=1", params=()):
    from db import get_db
    c = get_db()
    try:
        return [dict(r) for r in c.execute(f"SELECT * FROM audit_log WHERE {where} ORDER BY id", params).fetchall()]
    finally:
        c.close()


def _insert(**kw):
    from db import get_db
    row = dict(at="2026-09-01T10:00:00", user_id=1, username="u1", display_name="甲", action="quotation.create",
               target_type="quotation", target_id="MQ-202609-001", target_label="", detail="{}",
               module="quotation", case_no="MQ-202609-001", ref_no="", result="ok", reason_code="", status_code=0)
    row.update(kw)
    c = get_db()
    try:
        cols = ",".join(row)
        c.execute(f"INSERT INTO audit_log ({cols}) VALUES ({','.join('?' * len(row))})", list(row.values()))
        c.commit()
    finally:
        c.close()


# ── 1. 欄位派生 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("args,expect", [
    (("quotation.approve", "quotation", "MQ-202609-001", "", {}), ("quotation", "MQ-202609-001", "")),
    (("voucher.create", "vouchers", "V-2609-0001", "", {"quoteNo": "MQ-202608-012"}), ("voucher", "MQ-202608-012", "V-2609-0001")),
    (("payslip.pay", "payslip", "PS-1", "勞報 MQ-202601-999 張三", {}), ("payslip", "MQ-202601-999", "PS-1")),
    (("settings.update", "settings", "x", "", {"a": 1}), ("settings", "", "")),
    (("case.update", "case", "MQ-202609-002", "", "MQ-202609-003"), ("case", "MQ-202609-002", "")),
    (("", "", "", "", None), ("", "", "")),
    (("user.create", "user", "MQ-20260-01", "", {}), ("user", "", "")),          # 格式不符＝不猜
])
def test_derive_fields_table(args, expect):
    d = A._derive_fields(*args)
    assert (d["module"], d["case_no"], d["ref_no"]) == expect


# ── 2. migration v3 ─────────────────────────────────────────────────────────

def _old_db(path):
    c = sqlite3.connect(path)
    c.executescript("""CREATE TABLE audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, user_id INTEGER, username TEXT,
        display_name TEXT, action TEXT, target_type TEXT, target_id TEXT, target_label TEXT, detail TEXT);""")
    return c


def test_migration_backfills_matches_writer_rules_and_is_reentrant(tmp_path):
    from core import migrations as M
    c = _old_db(str(tmp_path / "o.db"))
    samples = [("quotation.approve", "quotation", "MQ-202609-001", "", "{}"),
               ("voucher.create", "vouchers", "V-1", "", json.dumps({"quoteNo": "MQ-202608-012"})),
               ("settings.update", "settings", "k", "", "not json"),
               ("payslip.pay", "payslip", "PS-9", "MQ-202601-999", "{}")]
    n = 12000                                                          # 跨過 5000 一批的邊界
    for i in range(n):
        s = samples[i % len(samples)]
        c.execute("INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,target_id,target_label,detail) "
                  "VALUES ('2026-09-01',1,'u','U',?,?,?,?,?)", s)
    c.commit()
    assert M._core_v6_audit_search(c) is None
    assert M._core_v6_audit_search(c) is None                          # 可重入
    idx = {r[1] for r in c.execute("PRAGMA index_list(audit_log)")}
    assert {"idx_audit_module", "idx_audit_case", "idx_audit_ref", "idx_audit_result", "idx_audit_user",
            "idx_audit_at", "idx_audit_action"} <= idx
    bad = 0
    total = 0
    for r in c.execute("SELECT action,target_type,target_id,target_label,detail,module,case_no,ref_no,result FROM audit_log"):
        total += 1
        try:
            det = json.loads(r[4] or "{}")
        except ValueError:
            det = r[4]
        d = A._derive_fields(r[0], r[1], r[2], r[3], det)
        if (d["module"], d["case_no"], d["ref_no"]) != (r[5], r[6], r[7]) or r[8] != "ok":
            bad += 1
    assert total == n and bad == 0, "凍結副本與 helpers.audit._derive_fields 算出不同結果"


def test_audit_insert_falls_back_when_columns_missing(client):
    """欄位還沒建的庫，_audit 不可以因此寫不進去。"""
    import db
    c = db.get_db()
    for i in ("idx_audit_module",):
        c.execute(f"DROP INDEX IF EXISTS {i}")
    c.execute("ALTER TABLE audit_log DROP COLUMN module")
    c.commit()
    c.close()
    before = len(_rows())
    A._audit(None, "quotation.create", "quotation", "MQ-202609-001", "x", {})
    assert len(_rows()) == before + 1


# ── 3. API：篩選／keyset／權限 ───────────────────────────────────────────────

@pytest.fixture()
def auditor(client, make_user):
    u, p = make_user(username="auditor", role="superadmin", modules=[])
    return _login(client, u, p)


def test_filters_each_and_combined(client, auditor):
    _insert(username="u1", display_name="甲", module="quotation", case_no="MQ-202609-001")
    _insert(username="u2", display_name="乙", module="voucher", case_no="MQ-202609-002", ref_no="V-1", action="voucher.create",
            at="2026-09-05T10:00:00")
    _insert(username="u2", display_name="乙", module="voucher", case_no="MQ-202609-002", ref_no="V-1", action="fail.POST",
            result="fail", reason_code="conflict", status_code=409, at="2026-09-06T10:00:00")

    def get(**q):
        r = client.get("/api/audit-log", params=q, headers=auditor)
        assert r.status_code == 200, r.text
        return r.json()["items"]
    assert {i["username"] for i in get(module="voucher")} == {"u2"}
    assert len(get(case_no="MQ-202609-002")) == 2
    assert len(get(ref_no="V-1")) == 2
    assert {i["username"] for i in get(user="乙")} == {"u2"}
    assert len(get(action="voucher.create")) == 1
    assert len(get(date_from="2026-09-05", date_to="2026-09-05")) == 1
    fails = get(result="fail")
    assert len(fails) == 1 and fails[0]["reason_label"] == "狀態衝突"
    assert len(get(module="voucher", result="ok")) == 1
    assert len(get(module="other")) == 0


def test_keyset_no_dupes_no_gaps_and_limit_cap(client, auditor):
    base = len(_rows())
    for i in range(45):
        _insert(target_label=f"t{i}")
    seen, before = [], None
    while True:
        q = {"limit": 10}
        if before:
            q["before_id"] = before
        j = client.get("/api/audit-log", params=q, headers=auditor).json()
        seen += [i["id"] for i in j["items"]]
        before = j["next_before_id"]
        if not before:
            break
    assert len(seen) == len(set(seen)) == 45 + base and seen == sorted(seen, reverse=True)
    assert len(client.get("/api/audit-log", params={"limit": 99999}, headers=auditor).json()["items"]) <= 200


@pytest.mark.parametrize("path", ["/api/audit-log", "/api/audit-log/tree?level=module", "/api/audit-log/failures/summary"])
def test_permission_needs_audit_log_module(client, make_user, path):
    u, p = make_user(username="noaudit", role="admin", modules=[])
    assert client.get(path, headers=_login(client, u, p)).status_code == 403
    u2, p2 = make_user(username="hasaudit", role="admin", modules=["audit_log"])
    assert client.get(path, headers=_login(client, u2, p2)).status_code == 200


# ── 4. 分層樹 ───────────────────────────────────────────────────────────────

def test_tree_counts_match_details_across_levels(client, auditor):
    for i in range(3):
        _insert(module="quotation", case_no="MQ-202609-001")
    _insert(module="voucher", case_no="MQ-202609-001", ref_no="V-1")
    _insert(module="voucher", case_no="MQ-202609-001", ref_no="V-1", result="fail", reason_code="validation", status_code=422)
    _insert(module="voucher", case_no="MQ-202609-002", ref_no="V-2")

    def t(**q):
        return client.get("/api/audit-log/tree", params=q, headers=auditor).json()["items"]
    mods = {i["key"]: i for i in t(level="module")}
    assert mods["quotation"]["count"] >= 3 and mods["voucher"]["count"] == 3 and mods["voucher"]["failCount"] == 1
    assert mods["voucher"]["label"] == "傳票"
    cases = {i["key"]: i for i in t(level="case", module="voucher")}
    assert cases["MQ-202609-001"]["count"] == 2 and cases["MQ-202609-002"]["count"] == 1
    refs = {i["key"]: i for i in t(level="ref", module="voucher", case_no="MQ-202609-001")}
    assert refs["V-1"]["count"] == 2 and refs["V-1"]["failCount"] == 1
    for k, it in mods.items():                                        # 計數＝明細
        assert it["count"] == client.get("/api/audit-log", params={"module": k, "limit": 200}, headers=auditor).json()["total"]
    assert client.get("/api/audit-log/tree?level=x", headers=auditor).status_code == 400


def test_failure_summary_top_reasons(client, auditor):
    for _ in range(3):
        _insert(result="fail", reason_code="permission_denied", status_code=403)
    _insert(result="fail", reason_code="conflict", status_code=409)
    _insert()
    j = client.get("/api/audit-log/failures/summary", headers=auditor).json()
    assert j["total"] == 4 and j["byReason"][0]["key"] == "permission_denied" and j["byReason"][0]["count"] == 3


# ── 5. 失敗鉤子 ─────────────────────────────────────────────────────────────

def test_hook_records_403_write_and_not_get(client, make_user):
    u, p = make_user(username="nomod", role="admin", modules=[])
    h = _login(client, u, p)
    r = client.post("/api/parts", headers=h, json={"partNo": "X"})
    assert r.status_code == 403
    rows = _rows("result='fail'")
    assert len(rows) == 1 and rows[0]["reason_code"] == "permission_denied" and rows[0]["status_code"] == 403
    assert rows[0]["username"] == "nomod" and rows[0]["target_label"] == "/api/parts"
    assert client.get("/api/parts", headers=h).status_code == 403     # GET 被擋不記
    assert len(_rows("result='fail'")) == 1


def test_hook_rate_limit_repeat_counter_and_no_body(client, make_user):
    u, p = make_user(username="flood", role="admin", modules=[])
    h = _login(client, u, p)
    secret = "A123456789"                                             # 身分證字號樣式：不可出現在任何欄位
    for _ in range(5):
        assert client.post("/api/parts", headers=h, json={"idNo": secret, "name": "王大明"}).status_code == 403
    rows = _rows("result='fail'")
    assert len(rows) == 1, "60 秒內同鍵應只寫一筆"
    assert json.loads(rows[0]["detail"])["repeat"] == 4
    blob = json.dumps(rows[0], ensure_ascii=False)
    assert secret not in blob and "王大明" not in blob


def test_failure_helper_window_and_hourly_cap(client):
    assert A._audit_failure(7, "x", "X", "POST", "/api/a", 403, now=1000.0) == "new"
    assert A._audit_failure(7, "x", "X", "POST", "/api/a", 403, now=1030.0) == "repeat"
    assert A._audit_failure(7, "x", "X", "POST", "/api/a", 403, now=1061.0) == "new"       # 窗口過了
    assert A._audit_failure(7, "x", "X", "GET", "/api/a", 403, now=1.0) == "skip"
    assert A._audit_failure(7, "x", "X", "POST", "/api/a", 401, now=1.0) == "skip"
    A._FAIL_LAST.clear()
    A._FAIL_HOUR.clear()
    outs = [A._audit_failure(9, "y", "Y", "POST", f"/api/r{i}", 403, now=5000.0 + i) for i in range(A._FAIL_HOURLY_CAP + 5)]
    assert outs.count("new") == A._FAIL_HOURLY_CAP and outs.count("capped") == 5


def test_hook_skips_audit_log_own_paths(client, make_user):
    u, p = make_user(username="ownpath", role="admin", modules=[])
    h = _login(client, u, p)
    r = client.post("/api/audit-log/module-counts", headers=h, json={"modules": {"x": "y"}})
    assert r.status_code in (200, 403)
    assert _rows("result='fail'") == []


def test_hook_records_422_with_status_and_reason(client, make_user):
    u, p = make_user(username="sa422", role="superadmin", modules=[])
    h = _login(client, u, p)
    r = client.post("/api/parts", headers=h, json={"unexpected": 1})
    assert r.status_code in (409, 422, 404, 500, 400) or r.status_code < 300
    rows = _rows("result='fail'")
    if r.status_code in A._FAIL_STATUSES:
        assert len(rows) == 1 and rows[0]["status_code"] == r.status_code
        assert rows[0]["reason_code"] == A._FAIL_STATUS_REASON[r.status_code]
    else:
        assert rows == []                                              # 非清單內狀態碼（例 400）不記


# ── 6. 登入失敗 ─────────────────────────────────────────────────────────────

def test_login_failed_recorded_without_password_and_rate_limited(client):
    for _ in range(3):
        r = client.post("/api/auth/login", json={"username": "ghost", "password": "SuperSecret!1"})
        assert r.status_code == 401
    rows = _rows("action='auth.login_failed'")
    assert len(rows) == 1 and rows[0]["result"] == "fail" and rows[0]["reason_code"] == "login_failed"
    assert rows[0]["username"] == "ghost" and json.loads(rows[0]["detail"])["repeat"] == 2
    assert "SuperSecret" not in json.dumps(rows[0], ensure_ascii=False)


# ── 7. 效能（100k 列，門檻同設計書）─────────────────────────────────────────

def test_perf_100k_rows_filters_and_tree(client, auditor):
    from db import get_db
    c = get_db()
    mods = [f"m{i}" for i in range(30)]
    rows = []
    for i in range(100_000):
        rows.append(("2026-09-%02dT10:%02d:00" % (1 + i % 28, i % 60), 1, f"user{i % 20}", "U", f"{mods[i % 30]}.act",
                     "vouchers", f"V-{i % 3000}", "", "{}", mods[i % 30], "MQ-202609-%03d" % (i % 200), f"V-{i % 3000}",
                     "fail" if i % 20 == 0 else "ok", "conflict" if i % 20 == 0 else "", 409 if i % 20 == 0 else 0))
    c.executemany("INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,target_id,target_label,detail,"
                  "module,case_no,ref_no,result,reason_code,status_code) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    c.commit()
    c.close()
    combos = [dict(module="m3"), dict(case_no="MQ-202609-007"), dict(ref_no="V-77"), dict(user="user3"),
              dict(result="fail"), dict(action="m4.act"), dict(date_from="2026-09-10", date_to="2026-09-11"),
              dict(module="m3", result="fail", user="user3")]
    worst = 0.0
    for q in combos:
        t0 = time.perf_counter()
        assert client.get("/api/audit-log", params=q, headers=auditor).status_code == 200
        worst = max(worst, time.perf_counter() - t0)
    assert worst < 0.3, f"篩選查詢最慢 {worst:.3f}s（門檻 0.3s）"
    t0 = time.perf_counter()
    assert len(client.get("/api/audit-log/tree?level=module", headers=auditor).json()["items"]) >= 30
    assert time.perf_counter() - t0 < 0.5
    t0 = time.perf_counter()
    assert client.get("/api/audit-log", params={"before_id": 1000, "limit": 50}, headers=auditor).status_code == 200
    assert time.perf_counter() - t0 < 0.3
