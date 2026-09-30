# -*- coding: utf-8 -*-
"""總帳 B2 · 資產負債表與綜合損益表（proposal-gl/04-reports.md）。

對帳守門：資產＝負債＋權益（結轉前後、含反向科目、含以前年度損益）；損益表淨利＝試算表損益類淨額；
兩張表的「未結轉損益」互相一致。反向控制：壞帳（不平衡）、有餘額卻沒有報表列的科目、停用仍有科目的列——都必須被指出，不可被吸收。
"""
import pytest

import db
from modules.accounting.ledger import roles as ROLES
from modules.accounting.ledger import statements as ST

_SEQ = [0]


@pytest.fixture
def conn(client):
    c = db.get_db()
    ROLES.ensure_meta(c)
    c.commit()
    yield c
    c.close()


def _login(client, make_user, username, role="superadmin", modules=("finance",)):
    u, p = make_user(username=username, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _v(conn, date, lines, status="已過帳", kind="manual"):
    _SEQ[0] += 1
    cur = conn.execute(
        "INSERT INTO vouchers_all(voucher_no, voucher_date, category, summary, status, created_by, created_at, updated_at, kind)"
        " VALUES (?,?, '轉','s',?, 't','n','n', ?)", ("%s-%03d" % (date.replace("-", ""), _SEQ[0]), date,
                                                        "已核准" if status == "已過帳" else status, kind))
    for i, (code, d, c) in enumerate(lines, 1):
        conn.execute("INSERT INTO voucher_lines(voucher_id,line_no,account_code,debit,credit) VALUES (?,?,?,?,?)", (cur.lastrowid, i, code, d, c))
    if status == "已過帳":
        conn.execute("UPDATE vouchers_all SET status='已過帳' WHERE id=?", (cur.lastrowid,))
    conn.commit()


def _book(conn, y):
    """一個小公司的一月：資本、進貨、銷售（含稅）、出貨成本、租金。"""
    _v(conn, "%d-01-05" % y, [("1113", 100000, 0), ("3111", 0, 100000)])
    _v(conn, "%d-01-08" % y, [("1231", 6000, 0), ("2171", 0, 6000)])
    _v(conn, "%d-01-10" % y, [("1191", 10500, 0), ("4111", 0, 10000), ("2204", 0, 500)])
    _v(conn, "%d-01-15" % y, [("5111", 4000, 0), ("1231", 0, 4000)])
    _v(conn, "%d-01-20" % y, [("6112", 1000, 0), ("1113", 0, 1000)])


def _item(section, code):
    return next((i for i in section["items"] if i["code"] == code), None)


# ── 資產負債表 ───────────────────────────────────────────────────────────

def test_balance_sheet_balances_and_amounts_are_right(conn):
    _book(conn, 2200)
    bs = ST.balance_sheet(conn, "2200-01-31")
    s = bs["sections"]
    assert _item(s["current_assets"], "BS_CA_CASH")["amount"] == 99000
    assert _item(s["current_assets"], "BS_CA_AR")["amount"] == 10500
    assert _item(s["current_assets"], "BS_CA_INV")["amount"] == 2000
    assert bs["totals"]["assets"] == 111500
    assert _item(s["current_liabilities"], "BS_CL_AP")["amount"] == 6000
    assert _item(s["current_liabilities"], "BS_CL_OTHER_AP")["amount"] == 500          # 銷項稅額掛其他應付款
    assert bs["totals"]["liabilities"] == 6500
    assert _item(s["equity"], "BS_EQ_CAPITAL")["amount"] == 100000
    assert bs["current_pl"] == 5000 and any(i["label"].startswith("本期損益") and i["amount"] == 5000 for i in s["equity"]["items"])
    assert bs["totals"]["equity"] == 105000 and bs["checks"]["balanced"] and bs["checks"]["diff"] == 0


def test_balance_sheet_before_any_activity_is_empty_and_balanced(conn):
    bs = ST.balance_sheet(conn, "2205-03-31")
    assert bs["totals"]["assets"] == 0 and bs["checks"]["balanced"] and not bs["unmapped"]


def test_contra_accounts_net_into_their_line(conn):
    _v(conn, "2206-01-05", [("1113", 100000, 0), ("3111", 0, 100000)])
    _v(conn, "2206-01-06", [("1431", 30000, 0), ("1113", 0, 30000)])
    _v(conn, "2206-01-31", [("6125", 500, 0), ("1432", 0, 500)])
    bs = ST.balance_sheet(conn, "2206-01-31")
    ppe = _item(bs["sections"]["noncurrent_assets"], "BS_NCA_PPE")
    assert ppe["amount"] == 29500 and {a["code"]: a["amount"] for a in ppe["accounts"]} == {"1431": 30000, "1432": -500}
    assert bs["checks"]["balanced"]


def test_prior_year_unclosed_pl_keeps_the_sheet_balanced(conn):
    _book(conn, 2207)
    bs = ST.balance_sheet(conn, "2208-01-31")
    assert bs["prior_pl"] == 5000 and bs["current_pl"] == 0 and bs["checks"]["balanced"]
    assert any(i["label"].startswith("以前年度損益") for i in bs["sections"]["equity"]["items"])


def test_closing_entries_move_pl_into_retained_earnings_and_sheet_still_balances(conn):
    _book(conn, 2209)
    before = ST.balance_sheet(conn, "2209-12-31")
    assert before["current_pl"] == 5000 and before["checks"]["balanced"]
    # 損益結轉（kind='closing'）：收入、成本、費用歸零，差額入 3353 本期損益，再轉 3351 累積盈虧
    _v(conn, "2209-12-31", [("4111", 10000, 0), ("5111", 0, 4000), ("6112", 0, 1000), ("3353", 0, 5000)], kind="closing")
    _v(conn, "2209-12-31", [("3353", 5000, 0), ("3351", 0, 5000)], kind="closing")
    after = ST.balance_sheet(conn, "2209-12-31")
    assert after["current_pl"] == 0 and after["prior_pl"] == 0 and after["checks"]["balanced"]
    assert after["totals"] == before["totals"], "結轉前後資產負債表的總額不可變"
    assert _item(after["sections"]["equity"], "BS_EQ_RE")["amount"] == 5000
    nxt = ST.balance_sheet(conn, "2210-01-31")                                         # 隔年：已結轉 ⇒ 沒有以前年度損益列
    assert nxt["prior_pl"] == 0 and nxt["checks"]["balanced"] and nxt["totals"]["assets"] == 111500


def test_reverse_control_unmapped_balance_is_reported_not_absorbed(conn):
    conn.execute("INSERT INTO account_items(code, level, name, parent_code, source) VALUES ('1997', 4, '測試無歸屬科目', NULL, 'statutory')")
    conn.commit()
    ROLES.ensure_meta(conn)
    conn.commit()
    _v(conn, "2211-02-01", [("1997", 700, 0), ("3111", 0, 700)])
    bs = ST.balance_sheet(conn, "2211-02-28")
    assert [u["code"] for u in bs["unmapped"]] == ["1997"] and bs["checks"]["balanced"] is False
    assert bs["checks"]["diff"] == -700                                                # 資產少列了 700：差額被指出


def test_reverse_control_inactive_line_hides_accounts_and_is_flagged(conn):
    _book(conn, 2212)
    conn.execute("UPDATE gl_fs_lines SET is_active=0 WHERE code='BS_CA_INV'")
    conn.commit()
    try:
        bs = ST.balance_sheet(conn, "2212-01-31")
        assert [u["code"] for u in bs["unmapped"]] == ["1231"] and bs["checks"]["balanced"] is False
    finally:
        conn.execute("UPDATE gl_fs_lines SET is_active=1 WHERE code='BS_CA_INV'")
        conn.commit()


def test_reverse_control_unbalanced_books_are_flagged(conn):
    _v(conn, "2213-05-10", [("1113", 500, 0), ("4111", 0, 400)])
    bs = ST.balance_sheet(conn, "2213-05-31")
    assert bs["checks"]["balanced"] is False and bs["checks"]["trial_balance_balanced"] is False


def test_drafts_only_with_flag_and_lines_hide_zero_unless_asked(conn):
    _v(conn, "2214-01-10", [("1113", 300, 0), ("3111", 0, 300)], status="草稿")
    assert ST.balance_sheet(conn, "2214-01-31")["totals"]["assets"] == 0
    assert ST.balance_sheet(conn, "2214-01-31", include_drafts=True)["totals"]["assets"] == 300
    assert len(ST.balance_sheet(conn, "2214-01-31", show_zero=True)["sections"]["current_assets"]["items"]) >= 1


def test_treasury_stock_reduces_equity_and_the_sheet_still_balances(conn):
    """回歸（B3 測試時發現）：庫藏股票是借方餘額的權益科目，必須以負數扣減權益，不是加進權益。"""
    _book(conn, 2222)
    _v(conn, "2222-01-28", [("3511", 500, 0), ("1113", 0, 500)])
    bs = ST.balance_sheet(conn, "2222-01-31")
    tr = _item(bs["sections"]["equity"], "BS_EQ_TREASURY")
    assert tr["amount"] == -500 and bs["totals"]["equity"] == 104500 and bs["totals"]["assets"] == 111000
    assert bs["checks"]["balanced"] and bs["checks"]["diff"] == 0


# ── 綜合損益表 ───────────────────────────────────────────────────────────

def _line(inc, code):
    return next(l for l in inc["lines"] if l["code"] == code)


def test_income_statement_computed_lines_and_ytd(conn):
    _book(conn, 2215)
    _v(conn, "2215-02-10", [("1191", 21000, 0), ("4111", 0, 20000), ("2204", 0, 1000)])
    _v(conn, "2215-02-12", [("4114", 500, 0), ("1191", 0, 500)])                       # 銷貨折讓（減項）
    _v(conn, "2215-02-15", [("7243", 30, 0), ("1113", 0, 30)])                         # 營業外費損（手續費）
    _v(conn, "2215-02-28", [("8211", 700, 0), ("2211", 0, 700)])                       # 所得稅費用
    feb = ST.income_statement(conn, "2215-02-01", "2215-02-28")
    assert _line(feb, "IS_REV")["period"] == 20000 and _line(feb, "IS_REV")["ytd"] == 30000
    assert _line(feb, "IS_REV_ALLOW")["period"] == 500 and _line(feb, "IS_GP")["period"] == 19500
    assert _line(feb, "IS_GP")["ytd"] == 30000 - 500 - 4000 and _line(feb, "IS_OP")["period"] == 19500
    assert _line(feb, "IS_NONOP_EXP")["period"] == 30 and _line(feb, "IS_PBT")["period"] == 19470
    assert _line(feb, "IS_TAX")["period"] == 700 and _line(feb, "IS_NI")["period"] == 18770
    assert feb["net_income"] == {"period": 18770, "ytd": 18770 + 5000, "tci_period": 18770, "tci_ytd": 23770}
    assert feb["checks"]["balanced"] and feb["checks"]["ni_equals_trial_balance"]
    jan = ST.income_statement(conn, "2215-01-01", "2215-01-31")
    assert jan["net_income"]["period"] == 5000 == jan["net_income"]["ytd"]


def test_income_statement_excludes_closing_entries_and_refuses_cross_year(conn):
    _book(conn, 2216)
    _v(conn, "2216-12-31", [("4111", 10000, 0), ("5111", 0, 4000), ("6112", 0, 1000), ("3353", 0, 5000)], kind="closing")
    inc = ST.income_statement(conn, "2216-01-01", "2216-12-31")
    assert inc["net_income"]["ytd"] == 5000 and inc["checks"]["balanced"]              # 結轉傳票不進損益表
    with pytest.raises(ValueError):
        ST.income_statement(conn, "2216-12-01", "2217-01-31")


def test_income_statement_unmapped_pl_account_is_flagged(conn):
    conn.execute("UPDATE gl_account_meta SET fs_line='' WHERE code='6112'")
    conn.commit()
    try:
        _v(conn, "2217-03-05", [("6112", 90, 0), ("1113", 0, 90)])
        inc = ST.income_statement(conn, "2217-03-01", "2217-03-31")
        assert [u["code"] for u in inc["unmapped"]] == ["6112"] and inc["checks"]["balanced"] is False
    finally:
        conn.execute("UPDATE gl_account_meta SET fs_line='IS_OPEX' WHERE code='6112'")
        conn.commit()


def test_cross_statement_consistency(conn):
    _book(conn, 2218)
    c = ST.check_consistency(conn, "2218-01-31")
    assert c == {"bs_balanced": True, "is_balanced": True, "current_pl_matches": True, "closed_in_year": False}
    _v(conn, "2218-12-31", [("4111", 10000, 0), ("5111", 0, 4000), ("6112", 0, 1000), ("3353", 0, 5000)], kind="closing")
    c = ST.check_consistency(conn, "2218-12-31")
    assert c["closed_in_year"] and c["current_pl_matches"] and c["bs_balanced"]


# ── API ─────────────────────────────────────────────────────────────────

def test_api_statements_permissions_validation_and_compare(client, make_user, conn):
    hdr = _login(client, make_user, "gl_b2_a")
    none = _login(client, make_user, "gl_b2_none", role="staff", modules=())
    _book(conn, 2219)
    bs = "/api/ledger/balance-sheet?as_of=2219-01-31"
    inc = "/api/ledger/income-statement?start=2219-01-01&end=2219-01-31"
    for u in (bs, inc, "/api/ledger/statements/check?as_of=2219-01-31"):
        assert client.get(u, headers=none).status_code == 403, u
        assert client.get(u, headers=hdr).status_code == 200, u
    r = client.get(bs + "&compare_as_of=2218-12-31", headers=hdr).json()
    assert r["totals"]["assets"] == 111500 and r["compare"]["totals"]["assets"] == 0 and r["checks"]["balanced"]
    r = client.get(inc + "&compare_start=2218-01-01&compare_end=2218-12-31", headers=hdr).json()
    assert r["net_income"]["ytd"] == 5000 and r["compare"]["net_income"]["ytd"] == 0
    assert client.get("/api/ledger/balance-sheet?as_of=2219-13-01", headers=hdr).status_code == 400
    assert client.get("/api/ledger/income-statement?start=2219-12-01&end=2220-01-31", headers=hdr).status_code == 400   # 跨年度
    assert client.get("/api/ledger/income-statement?start=2219-02-01&end=2219-01-01", headers=hdr).status_code == 400
