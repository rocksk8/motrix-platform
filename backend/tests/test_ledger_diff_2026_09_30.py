# -*- coding: utf-8 -*-
"""『與總帳差異』（MONEY-FLOWS §9 L4 / Part B）：`ledger.month_totals` 提供者＋`GET /api/reports/ledger-diff`。

驗：提供者的彙總（已過帳／未過帳草稿／手工／獎金／稅額、不含結轉與作廢）；差額＝分桶加總（含 residual，恆等式）；
權限（無報表權限 403、沒有財務檢視 403、未登入 401）；總帳模組不在 ⇒ `glAvailable:false` 說明而不是 0。"""
import pytest

import db
from modules.accounting.ledger import roles as ROLES

Y = 2200
_SEQ = [0]


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def conn(client):
    c = db.get_db()
    ROLES.ensure_meta(c)
    c.commit()
    yield c
    c.close()


def _v(conn, date, lines, status="已過帳", kind="manual", origin="", voided=False):
    _SEQ[0] += 1
    cur = conn.execute(
        "INSERT INTO vouchers_all(voucher_no, voucher_date, category, summary, status, created_by, created_at, updated_at, kind, origin)"
        " VALUES (?,?, '轉','s',?, 't','n','n', ?, ?)", ("%s-%03d" % (date.replace("-", ""), _SEQ[0]), date,
                                                            "已核准" if status == "已過帳" else status, kind, origin))
    for i, (code, d, c) in enumerate(lines, 1):
        conn.execute("INSERT INTO voucher_lines(voucher_id,line_no,account_code,debit,credit) VALUES (?,?,?,?,?)", (cur.lastrowid, i, code, d, c))
    if status == "已過帳":
        conn.execute("UPDATE vouchers_all SET status='已過帳' WHERE id=?", (cur.lastrowid,))
    if voided:
        conn.execute("UPDATE vouchers_all SET voided_at='2200-02-28T00:00:00' WHERE id=?", (cur.lastrowid,))
    conn.commit()


def _book(conn):
    # 二月：手工已過帳收入 1000（銷項稅 50）；引擎已過帳費用 500＋進項稅 25（來源 E04）；引擎草稿收入 200；手工已過帳費用 100；
    _v(conn, "%d-02-05" % Y, [("1113", 1050, 0), ("4111", 0, 1000), ("2204", 0, 50)])
    _v(conn, "%d-02-06" % Y, [("5811", 500, 0), ("1268", 25, 0), ("2171", 0, 525)], origin="gl:E04", kind="auto")
    _v(conn, "%d-02-07" % Y, [("1191", 200, 0), ("4111", 0, 200)], status="草稿", origin="gl:E03", kind="auto")
    _v(conn, "%d-02-08" % Y, [("6112", 100, 0), ("1113", 0, 100)])
    # 不該計入：結轉、作廢、別的年度
    _v(conn, "%d-02-09" % Y, [("4111", 9999, 0), ("3353", 0, 9999)], kind="closing")
    _v(conn, "%d-02-10" % Y, [("1113", 7777, 0), ("4111", 0, 7777)], voided=True)
    _v(conn, "%d-02-11" % (Y + 1), [("1113", 5555, 0), ("4111", 0, 5555)])


def test_provider_aggregates_by_group_and_excludes_closing_voided_other_year(conn):
    from modules.accounting.ledger import month_totals as MT
    _book(conn)
    r = MT.month_totals(conn, Y)
    assert r["available"] is True
    m = r["months"]["%d-02" % Y]
    assert m["manual_posted"]["revenue"] == 1000 and m["manual_posted"]["tax_out"] == 50 and m["manual_posted"]["expense"] == 100
    assert m["engine_posted"]["expense"] == 500 and m["engine_posted"]["tax_in"] == 25 and m["engine_posted"]["revenue"] == 0
    assert m["engine_unposted"]["revenue"] == 200
    assert m["by_origin_posted"] == {"gl:E04": 500, "": 100}
    assert "bonus_posted" not in m
    assert ("%d-02" % (Y + 1)) not in r["months"]


def test_provider_counts_pending_events_and_bonus_group(conn):
    from modules.accounting.ledger import month_totals as MT
    _v(conn, "%d-03-01" % Y, [("6111", 300, 0), ("2191", 0, 300)], origin="bonus_accrual")
    for st in ("drift", "orphan", "blocked_closed", "posted"):
        conn.execute("INSERT INTO gl_source_events (source_type, source_key, event_code, rev, event_date, status) VALUES ('t', ?, 'E99', 1, ?, ?)",
                     ("k-" + st, "%d-03-10" % Y, st))
    conn.commit()
    r = MT.month_totals(conn, Y)
    assert r["months"]["%d-03" % Y]["bonus_posted"]["expense"] == 300
    assert r["events"]["%d-03" % Y] == {"drift": 1, "orphan": 1, "blocked": 1}          # posted 不算待處理


@pytest.fixture
def sa(client, make_user):
    u, p = make_user(username="ld_sa", role="superadmin", modules=[])
    return _login(client, u, p)


def _patch_report(monkeypatch, income=None, expenses=None):
    from modules.analytics.api import reports as R
    income = income or {}
    monkeypatch.setattr(R, "_collect_income_items", lambda a, b, d=None: [{"amount": income.get(a[:7], 0)}] if income.get(a[:7]) else [])
    monkeypatch.setattr(R, "_collect_expenses", lambda year, dept=None, basis="cash", conn=None: {
        "monthly": [dict({"month": "%d-%02d" % (year, m), "contractor": 0, "equipment": 0, "material": 0, "other": 0},
                         **(expenses or {}).get("%d-%02d" % (year, m), {})) for m in range(1, 13)]})


def test_diff_buckets_add_up_to_the_difference(client, conn, sa, monkeypatch):
    _book(conn)
    # 報表（現金）二月：收入 1250（含稅 1050＋草稿 200）；支出承攬商 525（含稅）＋其他 100＋獎金外的 40（無法對到的殘差）
    _patch_report(monkeypatch, income={"%d-02" % Y: 1250}, expenses={"%d-02" % Y: {"contractor": 525, "other": 140}})
    r = client.get("/api/reports/ledger-diff", params={"year": Y, "basis": "cash"}, headers=sa)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["glAvailable"] is True and len(j["months"]) == 12
    feb = next(m for m in j["months"] if m["month"] == "%d-02" % Y)
    inc, exp = feb["income"], feb["expense"]
    assert inc["report"] == 1250 and inc["gl"] == 1000 and inc["diff"] == 250
    assert inc["buckets"]["unposted"] == 200 and inc["buckets"]["tax"] == 0 and inc["buckets"]["manual"] == -1000
    assert sum(inc["buckets"].values()) == inc["diff"], inc                                # 恆等式：分桶加總＝差額（residual 補足）
    assert exp["report"] == 665 and exp["gl"] == 600 and exp["diff"] == 65
    assert exp["buckets"]["tax"] == 25 and exp["buckets"]["manual"] == -100
    assert sum(exp["buckets"].values()) == exp["diff"], exp
    cats = exp["categories"]
    assert cats["contractor"]["report"] == 525 and cats["contractor"]["gl"] == 500 and cats["contractor"]["diff"] == 25
    assert cats["other"]["report"] == 140 and cats["other"]["gl"] == 100
    assert j["totals"]["income"]["diff"] == 250 and j["totals"]["expense"]["gl"] == 600


def test_accrual_basis_has_no_tax_bucket(client, conn, sa, monkeypatch):
    from modules.analytics.api import ledger_diff as LD
    _book(conn)
    _patch_report(monkeypatch, income={"%d-02" % Y: 1000}, expenses={"%d-02" % Y: {"contractor": 500}})
    monkeypatch.setattr(LD.R, "_recognition", lambda: type("Rec", (), {"accrual_income_items": staticmethod(lambda c, a, b, d: [{"amount": 1000}] if a[:7] == "%d-02" % Y else [])})())
    j = client.get("/api/reports/ledger-diff", params={"year": Y, "basis": "accrual"}, headers=sa).json()
    feb = next(m for m in j["months"] if m["month"] == "%d-02" % Y)
    assert feb["income"]["buckets"]["tax"] == 0 and feb["expense"]["buckets"]["tax"] == 0
    assert sum(feb["expense"]["buckets"].values()) == feb["expense"]["diff"]


def test_permissions_and_validation(client, make_user, sa):
    assert client.get("/api/reports/ledger-diff").status_code == 401
    u, p = make_user(username="ld_none", role="sales", modules=[])
    assert client.get("/api/reports/ledger-diff", headers=_login(client, u, p)).status_code in (403, 404)
    assert client.get("/api/reports/ledger-diff", params={"year": 1800}, headers=sa).status_code == 400


def test_gl_provider_absent_says_so_and_shows_report_only(client, sa, monkeypatch):
    from modules.analytics.api import ledger_diff as LD
    _patch_report(monkeypatch, income={"%d-02" % Y: 1250}, expenses={})
    monkeypatch.setattr(LD._registry, "providers", lambda cap: {} if cap == "ledger.month_totals" else {})
    j = client.get("/api/reports/ledger-diff", params={"year": Y}, headers=sa).json()
    assert j["glAvailable"] is False and "會計模組" in j["glNotice"]
    feb = next(m for m in j["months"] if m["month"] == "%d-02" % Y)
    assert feb["income"]["report"] == 1250 and "gl" not in feb["income"] and "buckets" not in feb["income"]
    assert j["totals"]["income"]["diff"] is None                                          # 沒有總帳 ⇒ 不是 0，是沒有
