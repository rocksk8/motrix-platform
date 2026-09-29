# -*- coding: utf-8 -*-
"""總帳 P1 · 會計期間、結帳鎖定、稽核軌跡（proposal-gl/03-periods-close.md）。

守門的對象是「三層鎖定」：API 友善訊息、DB 觸發器、稽核軌跡只增不改。
每一層都附反向控制（拿掉那一層，對應的題必須紅）——用「刪掉觸發器後同一個動作居然成功」證明是觸發器在擋。
"""
import sqlite3

import pytest

import db
from modules.accounting.ledger import periods as P

LINES = [{"account_code": "1113", "debit": 1000, "credit": 0}, {"account_code": "4111", "debit": 0, "credit": 1000}]


def _login(client, make_user, username, role="superadmin", modules=("finance",)):
    u, p = make_user(username=username, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def conn(client):
    """`client` 讓測試庫先完成啟動與 migration；稽核軌跡不可刪（觸發器），題間靠不同年度隔離。"""
    c = db.get_db()
    yield c
    c.close()


_YEAR = [2100]


def _fresh_year(conn):
    """每題用不同年度（稽核軌跡與期間不清理，避免題間干擾）。"""
    _YEAR[0] += 1
    y = _YEAR[0]
    P.create_year(conn, y, "t")
    conn.commit()
    return y


def _voucher(conn, date, status="已核准", lines=LINES, kind="manual", no=None):
    no = no or "%s-%s" % (date.replace("-", ""), conn.execute("SELECT COUNT(*) FROM vouchers_all").fetchone()[0] + 900)
    cur = conn.execute(
        "INSERT INTO vouchers_all(voucher_no, voucher_date, category, summary, status, created_by, created_at, updated_at, kind)"
        " VALUES (?,?, '轉', 't', ?, 't', 'n', 'n', ?)", (no, date, "已核准" if status == "已過帳" else status, kind))
    vid = cur.lastrowid
    for i, ln in enumerate(lines, 1):
        conn.execute("INSERT INTO voucher_lines(voucher_id,line_no,account_code,debit,credit) VALUES (?,?,?,?,?)",
                     (vid, i, ln["account_code"], ln["debit"], ln["credit"]))
    if status == "已過帳":
        conn.execute("UPDATE vouchers_all SET status='已過帳' WHERE id=?", (vid,))
    conn.commit()
    return vid


def _period(conn, year, no):
    return dict(conn.execute("SELECT * FROM gl_periods WHERE year=? AND period_no=?", (year, no)).fetchone())


# ── 年度與期間 ────────────────────────────────────────────────────────────

def test_create_year_makes_twelve_contiguous_periods(conn):
    y = _fresh_year(conn)
    ps = conn.execute("SELECT * FROM gl_periods WHERE year=? ORDER BY period_no", (y,)).fetchall()
    assert len(ps) == 12
    assert ps[0]["start_date"] == "%d-01-01" % y and ps[-1]["end_date"] == "%d-12-31" % y
    for a, b in zip(ps, ps[1:]):
        import datetime as dt
        assert dt.date.fromisoformat(b["start_date"]) - dt.date.fromisoformat(a["end_date"]) == dt.timedelta(days=1)
    with pytest.raises(P.PeriodError):
        P.create_year(conn, y, "t")                      # 重複建立


def test_past_years_can_be_created_for_backfill(conn):
    P.create_year(conn, 1999, "t") if not conn.execute("SELECT 1 FROM gl_fiscal_years WHERE year=1999").fetchone() else None
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM gl_periods WHERE year=1999").fetchone()[0] == 12


def test_non_calendar_fiscal_year(conn):
    s, e = P.year_bounds(2030, 7)
    assert (s, e) == ("2030-07-01", "2031-06-30")


def test_no_period_data_means_everything_open(conn):
    assert P.lock_error(conn, "1500-01-01") is None      # 沒有任何期間涵蓋 ⇒ 開放（舊部署行為不變）


# ── 結帳／重開／鎖定 ──────────────────────────────────────────────────────

def test_close_records_hash_and_log_and_blocks_second_close(conn):
    y = _fresh_year(conn)
    p = _period(conn, y, 1)
    _voucher(conn, "%d-01-15" % y, status="已過帳")
    h = P.close_period(conn, p["id"], "acc", accept_warnings=True)
    conn.commit()
    row = _period(conn, y, 1)
    assert row["status"] == "closed" and row["tb_hash"] == h and row["closed_by"] == "acc"
    assert P.read_log(conn, y)[0]["action"] == "close"
    with pytest.raises(P.PeriodError):
        P.close_period(conn, p["id"], "acc", accept_warnings=True)


def test_close_refuses_unposted_vouchers_without_acknowledgement(conn):
    y = _fresh_year(conn)
    _voucher(conn, "%d-02-10" % y, status="草稿")
    p = _period(conn, y, 2)
    with pytest.raises(P.PeriodError) as ei:
        P.close_period(conn, p["id"], "acc")
    assert "未過帳" in str(ei.value)
    P.close_period(conn, p["id"], "acc", accept_warnings=True)      # 明確確認後可結
    conn.commit()


def test_close_refuses_when_books_do_not_balance(conn):
    y = _fresh_year(conn)
    bad = [{"account_code": "1113", "debit": 500, "credit": 0}, {"account_code": "4111", "debit": 0, "credit": 400}]
    _voucher(conn, "%d-03-05" % y, status="已過帳", lines=bad)
    p = _period(conn, y, 3)
    with pytest.raises(P.PeriodError) as ei:
        P.close_period(conn, p["id"], "acc", accept_warnings=True)  # 不平衡是硬擋，warnings 也放不過
    assert "不平衡" in str(ei.value)
    # 清掉這張壞帳，避免影響同庫其他題的平衡檢查
    conn.execute("UPDATE vouchers_all SET voided_at='x', voided_by='t', void_reason='t' WHERE voucher_date=?", ("%d-03-05" % y,))
    conn.commit()


def test_reopen_needs_reason_and_marks_later_periods_stale(conn):
    y = _fresh_year(conn)
    p1, p2 = _period(conn, y, 1), _period(conn, y, 2)
    P.close_period(conn, p1["id"], "acc", accept_warnings=True)
    P.close_period(conn, p2["id"], "acc", accept_warnings=True)
    conn.commit()
    with pytest.raises(P.PeriodError):
        P.reopen_period(conn, p1["id"], "acc", "  ")
    later = P.reopen_period(conn, p1["id"], "acc", "補一張漏的傳票")
    conn.commit()
    assert later >= 1
    assert _period(conn, y, 1)["status"] == "open" and _period(conn, y, 2)["stale"] == 1
    assert P.read_log(conn, y)[0]["action"] == "reopen" and P.read_log(conn, y)[0]["reason"] == "補一張漏的傳票"
    P.close_period(conn, p1["id"], "acc", accept_warnings=True)     # 重新結帳會清掉自己的 stale
    conn.commit()


def test_locked_period_cannot_reopen_until_unlocked(conn):
    y = _fresh_year(conn)
    p = _period(conn, y, 4)
    P.close_period(conn, p["id"], "acc", accept_warnings=True)
    P.lock_period(conn, p["id"], "root")
    with pytest.raises(P.PeriodError):
        P.reopen_period(conn, p["id"], "acc", "想改")
    with pytest.raises(P.PeriodError):
        P.unlock_period(conn, p["id"], "root", "")
    P.unlock_period(conn, p["id"], "root", "會計師要求")
    P.reopen_period(conn, p["id"], "acc", "補登")
    conn.commit()
    assert [r["action"] for r in P.read_log(conn, y)][:3] == ["reopen", "unlock", "lock"]


def test_period_log_is_append_only(conn):
    y = _fresh_year(conn)
    assert P.read_log(conn, y)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE gl_period_log SET reason='x' WHERE year=?", (y,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM gl_period_log WHERE year=?", (y,))
    conn.rollback()


# ── 鎖定的三層：友善訊息＋DB 觸發器，及反向控制 ────────────────────────────

def _close(conn, y, no):
    P.close_period(conn, _period(conn, y, no)["id"], "acc", accept_warnings=True)
    conn.commit()


def test_db_trigger_blocks_posting_into_closed_period(conn):
    y = _fresh_year(conn)
    vid = _voucher(conn, "%d-05-10" % y, status="已核准")
    _close(conn, y, 5)
    with pytest.raises(sqlite3.IntegrityError) as ei:
        conn.execute("UPDATE vouchers_all SET status='已過帳' WHERE id=?", (vid,))
    assert "已結帳" in str(ei.value)
    conn.rollback()


def test_db_trigger_blocks_voiding_posted_voucher_in_closed_period(conn):
    y = _fresh_year(conn)
    vid = _voucher(conn, "%d-06-10" % y, status="已過帳")
    _close(conn, y, 6)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE vouchers_all SET voided_at='n', voided_by='t', void_reason='r' WHERE id=?", (vid,))
    conn.rollback()
    # 草稿不受影響（帳上沒有它）
    d = _voucher(conn, "%d-06-11" % y, status="草稿")
    conn.execute("UPDATE vouchers_all SET voided_at='n', voided_by='t', void_reason='r' WHERE id=?", (d,))
    conn.commit()


def test_posted_voucher_is_immutable_everywhere(conn):
    y = _fresh_year(conn)                                # 期間開放也一樣：已過帳不可改日期與分錄
    vid = _voucher(conn, "%d-07-10" % y, status="已過帳")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE vouchers_all SET voucher_date=? WHERE id=?", ("%d-08-01" % y, vid))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO voucher_lines(voucher_id,line_no,account_code,debit,credit) VALUES (?,9,'1113',1,0)", (vid,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE voucher_lines SET debit=5 WHERE voucher_id=? AND line_no=1", (vid,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM voucher_lines WHERE voucher_id=?", (vid,))
    conn.rollback()


def test_reverse_control_without_triggers_the_same_actions_succeed(conn):
    """反向控制：證明上面幾題是『觸發器』在擋，不是別的東西。"""
    y = _fresh_year(conn)
    vid = _voucher(conn, "%d-09-10" % y, status="已核准")
    _close(conn, y, 9)
    names = ("gl_period_no_post", "gl_period_no_void", "gl_posted_no_redate", "gl_posted_lines_no_insert",
             "gl_posted_lines_no_delete", "gl_posted_lines_no_update")
    saved = {n: conn.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (n,)).fetchone()[0] for n in names}
    try:
        for n in names:
            conn.execute("DROP TRIGGER %s" % n)
        conn.execute("UPDATE vouchers_all SET status='已過帳' WHERE id=?", (vid,))   # 拿掉觸發器 ⇒ 可以過帳到已結帳期間
        conn.execute("UPDATE vouchers_all SET voucher_date=? WHERE id=?", ("%d-10-01" % y, vid))
        conn.execute("UPDATE vouchers_all SET voided_at='x', voided_by='t', void_reason='t' WHERE id=?", (vid,))
        conn.commit()
    finally:
        for n, sql in saved.items():
            conn.execute(sql)
        conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'gl_%'").fetchone()[0] >= 8


def test_migration_is_idempotent_and_no_op_when_run_twice(conn):
    import importlib
    m = importlib.import_module("modules.accounting.migrations.0001_ledger_base")
    assert m.up(conn) is None and m.up(conn) is None
    n = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'gl_%'").fetchone()[0]
    assert n == 8, "重跑不可重複建觸發器：%d" % n


# ── API：訊息、權限 ───────────────────────────────────────────────────────

def test_api_post_into_closed_period_gives_friendly_message(client, make_user, conn):
    hdr = _login(client, make_user, "gl_p1_a")
    y = _fresh_year(conn)
    r = client.post("/api/vouchers", headers=hdr, json={"summary": "p1", "voucher_date": "%d-11-10" % y, "lines": LINES})
    assert r.status_code == 200, r.text
    vid = r.json()["id"]
    for step in ("submit", "approve", "approve"):
        assert client.post("/api/vouchers/%d/%s" % (vid, step), headers=hdr).status_code == 200
    _close(conn, y, 11)
    r = client.post("/api/vouchers/%d/post" % vid, headers=hdr)
    assert r.status_code == 400 and "結帳" in r.json()["detail"], r.text
    # 重開後可以過帳；過帳後再結帳，作廢被友善訊息擋下（409），且傳票確實沒被作廢
    P.reopen_period(conn, _period(conn, y, 11)["id"], "acc", "測試")
    conn.commit()
    assert client.post("/api/vouchers/%d/post" % vid, headers=hdr).status_code == 200
    _close(conn, y, 11)
    r = client.post("/api/vouchers/%d/void" % vid, headers=hdr, json={"reason": "想作廢"})
    assert r.status_code == 409 and "沖轉" in r.json()["detail"], r.text
    assert conn.execute("SELECT voided_at FROM vouchers_all WHERE id=?", (vid,)).fetchone()[0] == ""


def test_api_permissions(client, make_user, conn):
    fin = _login(client, make_user, "gl_p1_fin", role="staff", modules=("finance",))
    cash = _login(client, make_user, "gl_p1_cash", role="staff", modules=("cashier",))
    sup = _login(client, make_user, "gl_p1_sup", role="superadmin", modules=())
    none = _login(client, make_user, "gl_p1_none", role="staff", modules=())
    y = _fresh_year(conn)
    pid = _period(conn, y, 12)["id"]
    assert client.get("/api/ledger/years", headers=none).status_code == 403
    assert client.get("/api/ledger/years", headers=cash).status_code == 200            # cashier 可讀
    assert client.post("/api/ledger/periods/%d/close" % pid, headers=cash, json={"accept_warnings": True}).status_code == 403
    r = client.post("/api/ledger/periods/%d/close" % pid, headers=fin, json={"accept_warnings": True})
    assert r.status_code == 200, r.text
    assert client.post("/api/ledger/periods/%d/lock" % pid, headers=fin).status_code == 403   # 鎖定只有 superadmin
    assert client.post("/api/ledger/periods/%d/lock" % pid, headers=sup).status_code == 200
    r = client.post("/api/ledger/periods/%d/reopen" % pid, headers=fin, json={"reason": "x"})
    assert r.status_code == 400 and "鎖定" in r.json()["detail"]
    assert client.post("/api/ledger/periods/%d/unlock" % pid, headers=sup, json={"reason": "會計師"}).status_code == 200
    assert client.post("/api/ledger/periods/%d/reopen" % pid, headers=fin, json={}).status_code == 400   # 缺理由
