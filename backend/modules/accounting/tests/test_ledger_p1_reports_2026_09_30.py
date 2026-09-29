# -*- coding: utf-8 -*-
"""總帳 P1 · 帳簿報表（試算表、總分類帳、明細帳、序時帳簿）、期初餘額、科目屬性與角色（proposal-gl/01、03、04）。

正對照：一張已知的過帳傳票必須在總帳、明細帳、試算表、日記簿四處都出現。
反向控制：塞一張不平衡的過帳傳票（繞過 API）⇒ 試算表必須說 balanced=False，不可被「以前年度損益」補列吸收。
"""
import pytest

import db
from modules.accounting.ledger import opening as O
from modules.accounting.ledger import periods as P
from modules.accounting.ledger import reports as R
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
    """直接寫入傳票（繞過 API）。lines: (科目, 借, 貸[, {維度}])。"""
    _SEQ[0] += 1
    no = "%s-%03d" % (date.replace("-", ""), _SEQ[0])
    cur = conn.execute(
        "INSERT INTO vouchers_all(voucher_no, voucher_date, category, summary, status, created_by, created_at, updated_at, kind)"
        " VALUES (?,?, '轉', 's', ?, 't','n','n', ?)", (no, date, "已核准" if status == "已過帳" else status, kind))
    vid = cur.lastrowid
    for i, ln in enumerate(lines, 1):
        dim = ln[3] if len(ln) > 3 else {}
        conn.execute("INSERT INTO voucher_lines(voucher_id,line_no,account_code,debit,credit,party_key,case_no,doc_no)"
                     " VALUES (?,?,?,?,?,?,?,?)", (vid, i, ln[0], ln[1], ln[2], dim.get("party_key", ""),
                                                    dim.get("case_no", ""), dim.get("doc_no", "")))
    if status == "已過帳":
        conn.execute("UPDATE vouchers_all SET status='已過帳' WHERE id=?", (vid,))
    conn.commit()
    return vid, no


def _row(tb, code):
    return next((r for r in tb["rows"] if r["code"] == code), None)


# ── 試算表 ────────────────────────────────────────────────────────────────

def test_trial_balance_columns_and_positive_control(conn):
    _v(conn, "2110-01-10", [("1113", 1000, 0), ("4111", 0, 1000)])
    _v(conn, "2110-02-10", [("1113", 500, 0), ("4111", 0, 500)])
    tb = R.trial_balance(conn, "2110-02-01", "2110-02-28")
    cash, rev = _row(tb, "1113"), _row(tb, "4111")
    assert (cash["opening_debit"], cash["period_debit"], cash["closing_debit"]) == (1000, 500, 1500)
    # 損益科目換年度歸零、但同年度內累計：1 月的收入是 2 月的期初
    assert (rev["opening_credit"], rev["period_credit"], rev["closing_credit"]) == (1000, 500, 1500)
    assert tb["balanced"] and tb["totals"]["closing_debit"] == tb["totals"]["closing_credit"]
    assert cash["name"] == "銀行存款"


def test_drafts_only_count_when_asked(conn):
    _v(conn, "2111-03-10", [("1113", 300, 0), ("4111", 0, 300)], status="草稿")
    assert _row(R.trial_balance(conn, "2111-03-01", "2111-03-31"), "1113") is None
    assert _row(R.trial_balance(conn, "2111-03-01", "2111-03-31", include_drafts=True), "1113")["period_debit"] == 300


def test_voided_and_closing_vouchers_are_excluded(conn):
    vid, _ = _v(conn, "2112-03-10", [("1113", 700, 0), ("4111", 0, 700)], status="草稿")
    conn.execute("UPDATE vouchers_all SET voided_at='n', voided_by='t', void_reason='t' WHERE id=?", (vid,))
    _v(conn, "2112-12-31", [("4111", 999, 0), ("3353", 0, 999)], kind="closing")
    conn.commit()
    tb = R.trial_balance(conn, "2112-01-01", "2112-12-31", include_drafts=True)
    assert _row(tb, "1113") is None and _row(tb, "3353") is None      # 結轉傳票預設不計
    assert R.trial_balance(conn, "2112-01-01", "2112-12-31", include_closing=True)["rows"]


def test_prior_year_pl_row_keeps_trial_balance_balanced_until_closing(conn):
    _v(conn, "2113-06-10", [("1113", 1000, 0), ("4111", 0, 1000)])
    _v(conn, "2114-02-10", [("1113", 200, 0), ("4111", 0, 200)])
    tb = R.trial_balance(conn, "2114-02-01", "2114-02-28")
    prior = _row(tb, "")
    assert prior and prior["name"].startswith("以前年度損益") and prior["opening_credit"] == 1000
    assert _row(tb, "4111")["opening_credit"] == 0 and _row(tb, "4111")["closing_credit"] == 200   # 損益換年度歸零
    assert _row(tb, "1113")["closing_debit"] == 1200 and tb["balanced"]


def test_spanning_fiscal_years_is_refused(conn):
    with pytest.raises(ValueError):
        R.trial_balance(conn, "2115-12-01", "2116-01-31")


def test_reverse_control_unbalanced_books_are_reported_not_absorbed(conn):
    _v(conn, "2117-05-10", [("1113", 500, 0), ("4111", 0, 400)])          # 繞過 API 塞進來的壞帳
    tb = R.trial_balance(conn, "2117-05-01", "2117-05-31")
    assert tb["balanced"] is False
    assert tb["totals"]["period_debit"] - tb["totals"]["period_credit"] == 100


def test_positive_control_one_voucher_appears_everywhere(conn):
    vid, no = _v(conn, "2118-04-10", [("1191", 1050, 0, {"party_key": "12345678", "case_no": "Q1", "doc_no": "AB12345678"}),
                                      ("4111", 0, 1000, {"case_no": "Q1"}), ("2204", 0, 50, {"case_no": "Q1"})])
    assert _row(R.trial_balance(conn, "2118-04-01", "2118-04-30"), "1191")["closing_debit"] == 1050
    gl = R.general_ledger(conn, "1191", "2118-04-01", "2118-04-30")
    assert gl["lines"][0]["voucher_no"] == no and gl["closing"] == 1050
    sub = R.subledger(conn, "1191", "party_key", "2118-04-01", "2118-04-30")
    assert sub["rows"] == [{"key": "12345678", "opening": 0, "period_debit": 1050, "period_credit": 0, "closing": 1050}]
    assert R.subledger(conn, "4111", "case_no", "2118-04-01", "2118-04-30")["rows"][0]["closing"] == -1000
    j = R.journal(conn, "2118-04-01", "2118-04-30")
    assert any(v["voucher_no"] == no and len(v["lines"]) == 3 for v in j["vouchers"])


# ── 總分類帳 ──────────────────────────────────────────────────────────────

def test_general_ledger_running_balance_and_opening(conn):
    _v(conn, "2119-01-05", [("1113", 100, 0), ("4111", 0, 100)])
    _v(conn, "2119-02-05", [("1113", 50, 0), ("4111", 0, 50)])
    _v(conn, "2119-02-20", [("6111", 30, 0), ("1113", 0, 30)])
    gl = R.general_ledger(conn, "1113", "2119-02-01", "2119-02-28")
    assert gl["opening"] == 100
    assert [x["balance"] for x in gl["lines"]] == [150, 120] and gl["closing"] == 120
    assert (gl["period_debit"], gl["period_credit"]) == (50, 30)
    assert R.general_ledger(conn, "9999", "2119-01-01", "2119-12-31") is None


def test_general_ledger_includes_child_accounts(conn):
    conn.execute("INSERT INTO account_items(code, level, name, parent_code, source) VALUES ('1113-91', 5, '測試銀行', '1113', 'custom')")
    conn.commit()
    ROLES.ensure_meta(conn)
    conn.commit()
    _v(conn, "2120-03-10", [("1113-91", 400, 0), ("4111", 0, 400)])
    assert R.general_ledger(conn, "1113", "2120-03-01", "2120-03-31")["closing"] == 400      # 上層科目含子科目


def test_general_ledger_dimension_filter(conn):
    _v(conn, "2121-03-10", [("1191", 100, 0, {"party_key": "A"}), ("4111", 0, 100)])
    _v(conn, "2121-03-11", [("1191", 70, 0, {"party_key": "B"}), ("4111", 0, 70)])
    gl = R.general_ledger(conn, "1191", "2121-03-01", "2121-03-31", dimension="party_key", key="B")
    assert gl["closing"] == 70
    with pytest.raises(ValueError):
        R.general_ledger(conn, "1191", "2121-03-01", "2121-03-31", dimension="account_code; DROP", key="x")


# ── 期初餘額 ──────────────────────────────────────────────────────────────

_OPEN_ROWS = [{"account_code": "1113", "debit": "5,000", "credit": ""}, {"account_code": "3111", "debit": "", "credit": 5000}]


def test_opening_preview_reports_imbalance_and_bad_rows(conn):
    r = O.preview(conn, [{"account_code": "1113", "debit": 100}, {"account_code": "3111", "credit": 40}])
    assert r["balanced"] is False and r["diff"] == 60
    for bad in ([{"account_code": "0000", "debit": 1}], [{"account_code": "1113", "debit": 1, "credit": 1}],
                [{"account_code": "1113", "debit": "12.5"}], [], [{"account_code": "1113", "debit": 0}]):
        with pytest.raises(O.OpeningError):
            O.preview(conn, bad)


def test_opening_items_must_sum_to_account_balance(conn):
    rows = [{"account_code": "1191", "debit": 300}, {"account_code": "3111", "credit": 300}]
    O.preview(conn, rows, [{"account_code": "1191", "doc_no": "A", "amount": 100}, {"account_code": "1191", "doc_no": "B", "amount": 200}])
    with pytest.raises(O.OpeningError):
        O.preview(conn, rows, [{"account_code": "1191", "doc_no": "A", "amount": 100}])


def test_opening_batch_lifecycle_and_book_start(conn):
    y = 2130
    P.create_year(conn, y, "t")
    conn.commit()
    legacy_vid, _ = _v(conn, "%d-01-15" % y, [("1113", 111, 0), ("4111", 0, 111)])          # 開帳日之前的既有傳票
    res = O.create_batch(conn, y, "%d-03-01" % y, _OPEN_ROWS, [], "f.csv", "acc")
    conn.commit()
    v = conn.execute("SELECT * FROM vouchers_all WHERE id=?", (res["voucher_id"],)).fetchone()
    assert v["kind"] == "opening" and v["status"] == "草稿" and v["voucher_date"] == "%d-03-01" % y
    # 草稿階段：期初還沒進帳，既有傳票照舊計入（未啟用期初的舊部署行為不變）
    assert _row(R.trial_balance(conn, "%d-03-01" % y, "%d-03-31" % y), "1113")["closing_debit"] == 111
    with pytest.raises(O.OpeningError):
        O.create_batch(conn, y, "%d-03-01" % y, _OPEN_ROWS, [], "again.csv", "acc")           # 一年一批
    # 過帳後：帳簿從開帳日起算，之前的傳票視為 legacy
    conn.execute("UPDATE vouchers_all SET status='已過帳' WHERE id=?", (res["voucher_id"],))
    conn.commit()
    tb = R.trial_balance(conn, "%d-03-01" % y, "%d-03-31" % y)
    assert _row(tb, "1113")["closing_debit"] == 5000 and tb["balanced"] and tb["bases"]["bs"] == "%d-03-01" % y
    with pytest.raises(O.OpeningError):
        O.undo_batch(conn, res["batch_id"], "acc")                                              # 已過帳不可撤銷


def test_opening_undo_before_posting_restores_carry_mode(conn):
    y = 2131
    P.create_year(conn, y, "t")
    res = O.create_batch(conn, y, "%d-01-01" % y, _OPEN_ROWS, [], "", "acc")
    conn.commit()
    assert conn.execute("SELECT opening_mode FROM gl_fiscal_years WHERE year=?", (y,)).fetchone()[0] == "imported"
    O.undo_batch(conn, res["batch_id"], "acc")
    conn.commit()
    assert conn.execute("SELECT opening_mode FROM gl_fiscal_years WHERE year=?", (y,)).fetchone()[0] == "carry"
    assert conn.execute("SELECT voided_at FROM vouchers_all WHERE id=?", (res["voucher_id"],)).fetchone()[0] != ""
    O.create_batch(conn, y, "%d-01-01" % y, _OPEN_ROWS, [], "", "acc")                          # 撤銷後可重匯
    conn.commit()


def test_opening_refuses_closed_period_and_out_of_year_date(conn):
    y = 2132
    P.create_year(conn, y, "t")
    conn.commit()
    with pytest.raises(O.OpeningError):
        O.create_batch(conn, y, "%d-01-01" % (y + 1), _OPEN_ROWS, [], "", "acc")
    P.close_period(conn, conn.execute("SELECT id FROM gl_periods WHERE year=? AND period_no=1", (y,)).fetchone()[0], "acc", True)
    conn.commit()
    with pytest.raises(O.OpeningError) as ei:
        O.create_batch(conn, y, "%d-01-15" % y, _OPEN_ROWS, [], "", "acc")
    assert "重開" in str(ei.value)


def test_api_opening_flow(client, make_user, conn):
    hdr = _login(client, make_user, "gl_p1_open")
    assert client.post("/api/ledger/years", headers=hdr, json={"year": 2140}).status_code == 200
    r = client.post("/api/ledger/opening/preview", headers=hdr, json={"rows": _OPEN_ROWS})
    assert r.status_code == 200 and r.json()["balanced"]
    r = client.post("/api/ledger/opening", headers=hdr, json={"year": 2140, "opening_date": "2140-01-01", "rows": _OPEN_ROWS})
    assert r.status_code == 200, r.text
    bid = r.json()["batch_id"]
    yrs = client.get("/api/ledger/years", headers=hdr).json()
    assert any(b["id"] == bid for b in yrs["batches"])
    bad = client.post("/api/ledger/opening", headers=hdr, json={"year": 2140, "opening_date": "2140-01-01", "rows": []})
    assert bad.status_code == 400
    assert client.post("/api/ledger/opening/%d/undo" % bid, headers=hdr).status_code == 200


def test_api_reports_and_permissions(client, make_user, conn):
    hdr = _login(client, make_user, "gl_p1_rep")
    none = _login(client, make_user, "gl_p1_rep_none", role="staff", modules=())
    _v(conn, "2141-05-05", [("1113", 10, 0), ("4111", 0, 10)])
    q = "start=2141-05-01&end=2141-05-31"
    for path in ("/api/ledger/trial-balance?" + q, "/api/ledger/journal?" + q, "/api/ledger/general-ledger?account=1113&" + q,
                 "/api/ledger/subledger?account=1191&dimension=party_key&" + q):
        assert client.get(path, headers=hdr).status_code == 200, path
        assert client.get(path, headers=none).status_code == 403, path
    assert client.get("/api/ledger/general-ledger?account=9999&" + q, headers=hdr).status_code == 404
    assert client.get("/api/ledger/trial-balance?start=2141-13-01&end=2141-05-31", headers=hdr).status_code == 400
    assert client.get("/api/ledger/trial-balance?start=2141-05-31&end=2141-05-01", headers=hdr).status_code == 400
    assert client.get("/api/ledger/subledger?account=1191&dimension=oops&" + q, headers=hdr).status_code == 400


# ── 科目屬性與角色 ────────────────────────────────────────────────────────

def test_every_postable_account_has_type_side_and_report_line(conn):
    n = conn.execute("SELECT COUNT(*) FROM gl_account_meta").fetchone()[0]
    assert n >= 547
    assert ROLES.accounts_without_fs_line(conn) == [], "這些可過帳科目沒有報表列，報表會悄悄漏算它們"
    assert conn.execute("SELECT COUNT(*) FROM gl_account_meta WHERE normal_side NOT IN ('D','C') OR acct_type=''").fetchone()[0] == 0


@pytest.mark.parametrize("code,typ,side,contra", [
    ("1111", "asset", "D", 0), ("1432", "asset", "C", 1), ("1192", "asset", "C", 1), ("2204", "liability", "C", 0),
    ("3351", "equity", "C", 0), ("3511", "equity", "D", 1), ("4111", "revenue", "C", 0), ("4114", "revenue", "D", 1),
    ("5111", "cost", "D", 0), ("5123", "cost", "C", 1), ("6125", "expense", "D", 0), ("7236", "other_income", "C", 0),
    ("7243", "other_expense", "D", 0), ("8211", "tax", "D", 0)])
def test_derived_type_side_and_contra(conn, code, typ, side, contra):
    m = conn.execute("SELECT * FROM gl_account_meta WHERE code=?", (code,)).fetchone()
    assert (m["acct_type"], m["normal_side"], m["is_contra"]) == (typ, side, contra), dict(m)


def test_fs_line_mapping_and_tax_roles(conn):
    fs = lambda c: conn.execute("SELECT fs_line FROM gl_account_meta WHERE code=?", (c,)).fetchone()[0]
    assert fs("1113") == "BS_CA_CASH" and fs("1191") == "BS_CA_AR" and fs("1231") == "BS_CA_INV" and fs("1431") == "BS_NCA_PPE"
    assert fs("2171") == "BS_CL_AP" and fs("2204") == "BS_CL_OTHER_AP" and fs("4114") == "IS_REV_ALLOW" and fs("4111") == "IS_REV"
    assert fs("5811") == "IS_COST" and fs("6133") == "IS_OPEX" and fs("7243") == "IS_NONOP_EXP" and fs("7236") == "IS_NONOP_INC"
    tr = {r[0]: r[1] for r in conn.execute("SELECT code, tax_role FROM gl_account_meta WHERE tax_role<>''")}
    assert tr == {"1268": "input_tax", "2204": "output_tax", "2194": "tax_payable", "1269": "tax_carry"}


def test_custom_child_inherits_and_parent_stops_being_postable(conn):
    assert conn.execute("SELECT postable FROM gl_account_meta WHERE code='1114'").fetchone()[0] == 1
    conn.execute("INSERT INTO account_items(code, level, name, parent_code, source) VALUES ('1114-90', 5, '自訂', '1114', 'custom')")
    ROLES.ensure_meta(conn)
    conn.commit()
    m = conn.execute("SELECT * FROM gl_account_meta WHERE code='1114-90'").fetchone()
    assert (m["acct_type"], m["normal_side"], m["fs_line"], m["postable"]) == ("asset", "D", "BS_CA_CASH", 1)
    assert conn.execute("SELECT postable FROM gl_account_meta WHERE code='1114'").fetchone()[0] == 0


def test_ensure_meta_never_overwrites_hand_edits(conn):
    conn.execute("UPDATE gl_account_meta SET display_name='會計師改名', fs_line='BS_CA_OTHER' WHERE code='1112'")
    conn.commit()
    assert ROLES.ensure_meta(conn) == 0
    m = conn.execute("SELECT display_name, fs_line FROM gl_account_meta WHERE code='1112'").fetchone()
    assert (m[0], m[1]) == ("會計師改名", "BS_CA_OTHER")


def test_roles_defaults_and_resolution_order(conn):
    ROLES.ensure_default_roles(conn)
    conn.commit()
    assert ROLES.resolve_role(conn, "BANK") == "1113" and ROLES.resolve_role(conn, "OUTPUT_TAX") == "2204"
    assert ROLES.resolve_role(conn, "NO_SUCH_ROLE") is None                      # 找不到就是 None，不猜
    conn.execute("INSERT INTO gl_account_roles(role,scope_type,scope_key,account_code,effective_from) VALUES ('REV_SALES','case_type','工程','4131','')")
    conn.execute("INSERT INTO gl_account_roles(role,scope_type,scope_key,account_code,effective_from) VALUES ('REV_SALES','','','4121','2200-01-01')")
    conn.commit()
    assert ROLES.resolve_role(conn, "REV_SALES", "case_type", "工程") == "4131"   # scope 精確命中優先
    assert ROLES.resolve_role(conn, "REV_SALES", "case_type", "其他") == "4111"   # 預設列
    assert ROLES.resolve_role(conn, "REV_SALES", on_date="2200-06-01") == "4121"  # 生效日之後改用新科目
    assert ROLES.resolve_role(conn, "REV_SALES", on_date="2100-06-01") == "4111"  # 之前的分錄不受影響


def test_api_accounts_and_role_validation(client, make_user, conn):
    hdr = _login(client, make_user, "gl_p1_acc")
    r = client.get("/api/ledger/accounts?q=銀行", headers=hdr)
    assert r.status_code == 200 and any(a["code"] == "1113" for a in r.json()["accounts"]) and r.json()["roles"]
    assert client.put("/api/ledger/roles", headers=hdr, json={"role": "BANK", "account_code": "111"}).status_code == 400   # 非葉節點
    assert client.put("/api/ledger/roles", headers=hdr, json={"role": "BANK", "account_code": "0000"}).status_code == 400
    assert client.put("/api/ledger/roles", headers=hdr, json={"role": "BANK", "account_code": "1113"}).status_code == 200
    assert client.patch("/api/ledger/accounts/1199", headers=hdr, json={"display_name": "備抵損失—應收款項"}).status_code == 200
    assert client.patch("/api/ledger/accounts/1199", headers=hdr, json={"acct_type": "revenue"}).status_code == 400     # 類別不開放
    assert client.patch("/api/ledger/accounts/0000", headers=hdr, json={"note": "x"}).status_code == 404


# ── voucher.draft 提供者的 origin（IP-2 追加）─────────────────────────────

def test_draft_provider_origin_is_optional_and_recorded(conn):
    from core import registry
    fn = registry.single_provider("voucher.draft")
    lines = [{"account_code": "1113", "debit": 10, "credit": 0}, {"account_code": "4111", "debit": 0, "credit": 10}]
    a = fn(conn, voucher_date="2150-01-05", summary="舊呼叫端", lines=lines, created_by="t", now="n")            # 不帶 origin＝舊行為
    b = fn(conn, voucher_date="2150-01-05", summary="有來源", lines=lines, created_by="t", now="n", origin="bonus_accrual")
    conn.commit()
    got = {r["id"]: r["origin"] for r in conn.execute("SELECT id, origin FROM vouchers_all WHERE id IN (?,?)", (a["id"], b["id"]))}
    assert got == {a["id"]: "", b["id"]: "bonus_accrual"}
    assert conn.execute("SELECT kind FROM vouchers_all WHERE id=?", (a["id"],)).fetchone()[0] == "manual"      # 預設 kind
