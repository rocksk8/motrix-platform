# -*- coding: utf-8 -*-
"""總帳 B4 · 現金流量表，間接法（proposal-gl/04-reports.md §5）。

核心守門（雙式簿記恆等式）：營業＋投資＋籌資 ＝ 現金淨變動；期初現金＋淨變動 ＝ 資產負債表期末現金；淨利＝損益表淨利。
反向控制：把有變動的科目清掉分類 ⇒ 必須被指出（unclassified、checks.balanced=False）；壞帳、期間內期初傳票、手工結轉都有對應的說明。
"""
import pytest

import db
from modules.accounting.ledger import cashflow as CF
from modules.accounting.ledger import roles as ROLES

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


def _book_jan(conn, y):
    _v(conn, "%d-01-05" % y, [("1113", 100000, 0), ("3111", 0, 100000)])                       # 籌資：現金增資
    _v(conn, "%d-01-08" % y, [("1231", 6000, 0), ("2171", 0, 6000)])                           # 進貨（賒購）
    _v(conn, "%d-01-10" % y, [("1191", 10500, 0), ("4111", 0, 10000), ("2204", 0, 500)])       # 銷售（賒銷）
    _v(conn, "%d-01-15" % y, [("5111", 4000, 0), ("1231", 0, 4000)])                           # 銷貨成本
    _v(conn, "%d-01-20" % y, [("6112", 1000, 0), ("1113", 0, 1000)])                           # 租金（現金）


def _sec(res, key):
    return next(s for s in res["sections"] if s["key"] == key)


def _line(sec, label):
    return next(l for l in sec["lines"] if l["label"] == label)


def test_indirect_method_amounts_and_identity(conn):
    _book_jan(conn, 2400)
    r = CF.cash_flow_statement(conn, "2400-01-01", "2400-01-31")
    op, inv, fin = _sec(r, "operating"), _sec(r, "investing"), _sec(r, "financing")
    assert _line(op, "本期淨利")["amount"] == 5000
    assert _line(op, "應收帳款淨額")["amount"] == -10500 and _line(op, "存貨")["amount"] == -2000
    assert _line(op, "應付帳款")["amount"] == 6000 and _line(op, "其他應付款")["amount"] == 500
    assert op["total"] == -1000 and inv["total"] == 0 and fin["total"] == 100000
    assert r["cash_change"] == 99000 == r["net_change"]
    assert (r["cash_opening"], r["cash_closing"]) == (0, 99000)
    assert r["checks"] == {"activities_equal_cash_change": True, "cash_reconciles_to_balance_sheet": True,
                           "net_income_matches_income_statement": True, "no_unclassified_accounts": True, "balanced": True}


def test_depreciation_addback_capex_and_loan(conn):
    _book_jan(conn, 2401)
    _v(conn, "2401-02-01", [("1431", 30000, 0), ("1113", 0, 30000)])                            # 購置設備：投資
    _v(conn, "2401-02-28", [("6125", 500, 0), ("1432", 0, 500)])                                # 折舊（非現金）
    _v(conn, "2401-02-10", [("1113", 20000, 0), ("2112", 0, 20000)])                            # 銀行借款：籌資
    r = CF.cash_flow_statement(conn, "2401-02-01", "2401-02-28")
    op, inv, fin = _sec(r, "operating"), _sec(r, "investing"), _sec(r, "financing")
    assert _line(op, "本期淨利")["amount"] == -500
    assert _line(op, "折舊、攤銷、減損及備抵（累計科目變動）")["amount"] == 500              # 淨利扣了折舊，這裡加回
    assert op["total"] == 0 and _line(inv, "不動產、廠房及設備")["amount"] == -30000 and inv["total"] == -30000
    assert fin["total"] == 20000 and r["cash_change"] == -10000 == r["net_change"]
    assert r["cash_opening"] == 99000 and r["cash_closing"] == 89000 and r["checks"]["balanced"]


def test_dividend_is_financing_and_closing_entries_are_not_cash_events(conn):
    _book_jan(conn, 2402)
    _v(conn, "2402-06-30", [("3351", 2000, 0), ("2201", 0, 2000)])                              # 宣告股利（未付）
    _v(conn, "2402-07-15", [("2201", 2000, 0), ("1113", 0, 2000)])                              # 支付股利
    _v(conn, "2402-12-31", [("4111", 10000, 0), ("5111", 0, 4000), ("6112", 0, 1000), ("3353", 0, 5000)], kind="closing")
    _v(conn, "2402-12-31", [("3353", 5000, 0), ("3351", 0, 5000)], kind="closing")
    r = CF.cash_flow_statement(conn, "2402-01-01", "2402-12-31")
    fin = _sec(r, "financing")
    assert _line(fin, "股本")["amount"] == 100000
    assert _line(fin, "保留盈餘（累積盈虧）")["amount"] == -2000                                # 股利支付＝籌資流出；結轉的 +5,000 不在其中
    assert _line(_sec(r, "operating"), "本期淨利")["amount"] == 5000                           # 結轉傳票不重複算淨利
    assert r["cash_change"] == 99000 - 2000 == r["net_change"] and r["checks"]["balanced"]


def test_other_comprehensive_income_is_a_noncash_adjustment(conn):
    _book_jan(conn, 2403)
    _v(conn, "2403-01-25", [("1131", 300, 0), ("8711", 0, 300)])                                # 金融資產評價利益（非現金）
    r = CF.cash_flow_statement(conn, "2403-01-01", "2403-01-31")
    assert _line(_sec(r, "operating"), "其他綜合損益（非現金）")["amount"] == 300
    assert r["cash_change"] == 99000 and r["checks"]["balanced"]                                # 評價變動與 OCI 相抵，不影響現金


def test_reverse_control_unclassified_account_with_movement_is_flagged(conn):
    # ensure_meta 會把「推得出預設」的空分類補回，所以用推不出預設的新科目（不在任何已知群組下）造真實破口
    conn.execute("INSERT INTO account_items(code, level, name, parent_code, source) VALUES ('1996', 4, '測試無分類科目', NULL, 'statutory')")
    conn.commit()
    ROLES.ensure_meta(conn)
    conn.commit()
    _book_jan(conn, 2404)
    _v(conn, "2404-02-05", [("1996", 800, 0), ("1113", 0, 800)])
    r = CF.cash_flow_statement(conn, "2404-02-01", "2404-02-28")
    assert [u["code"] for u in r["unclassified"]] == ["1996"]
    assert r["checks"]["no_unclassified_accounts"] is False and r["checks"]["balanced"] is False
    assert r["checks"]["activities_equal_cash_change"] is False                                 # 缺的 800 讓三大活動少於現金淨變動


def test_reverse_control_unbalanced_books_are_flagged(conn):
    _v(conn, "2405-05-10", [("1113", 500, 0), ("3111", 0, 400)])
    r = CF.cash_flow_statement(conn, "2405-05-01", "2405-05-31")
    assert r["checks"]["balanced"] is False


def test_opening_voucher_inside_period_reconciles_or_is_flagged_never_silent(conn):
    from modules.accounting.ledger import periods as P, opening as O
    P.create_year(conn, 2191, "t")
    conn.commit()
    res = O.create_batch(conn, 2191, "2191-03-01", [{"account_code": "1113", "debit": 9000}, {"account_code": "3111", "credit": 9000}], [], "", "t")
    conn.execute("UPDATE vouchers_all SET status='已過帳' WHERE id=?", (res["voucher_id"],))
    conn.commit()
    r = CF.cash_flow_statement(conn, "2191-03-01", "2191-03-31")
    assert r["cash_closing"] == 9000 and r["checks"]["cash_reconciles_to_balance_sheet"] is True
    assert _line(_sec(r, "financing"), "股本")["amount"] == 9000                                # 期初傳票的現金與股本以籌資呈現，仍對得上


def test_refuses_cross_year_and_reversed_range_and_drafts_toggle(conn):
    with pytest.raises(ValueError):
        CF.cash_flow_statement(conn, "2407-12-01", "2408-01-31")
    with pytest.raises(ValueError):
        CF.cash_flow_statement(conn, "2407-02-01", "2407-01-01")
    _v(conn, "2409-01-10", [("1113", 700, 0), ("3111", 0, 700)], status="草稿")
    assert CF.cash_flow_statement(conn, "2409-01-01", "2409-01-31")["cash_change"] == 0
    assert CF.cash_flow_statement(conn, "2409-01-01", "2409-01-31", include_drafts=True)["cash_change"] == 700


def test_api_cash_flow(client, make_user, conn):
    hdr = _login(client, make_user, "gl_b4_a")
    none = _login(client, make_user, "gl_b4_none", role="staff", modules=())
    _book_jan(conn, 2410)
    url = "/api/ledger/cash-flow?start=2410-01-01&end=2410-01-31"
    assert client.get(url, headers=none).status_code == 403
    r = client.get(url, headers=hdr)
    assert r.status_code == 200 and r.json()["checks"]["balanced"] and r.json()["net_change"] == 99000
    assert client.get("/api/ledger/cash-flow?start=2410-12-01&end=2411-01-31", headers=hdr).status_code == 400
    assert client.get("/api/ledger/cash-flow?start=x&end=y", headers=hdr).status_code == 400
