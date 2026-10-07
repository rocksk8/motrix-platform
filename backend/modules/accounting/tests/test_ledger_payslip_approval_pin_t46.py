# -*- coding: utf-8 -*-
"""第 46 班 M1（總帳）：勞報單新增 待審核／已核准 狀態與「已核准即可付款」之後，E06（應付）／E06b（付款）的**現況**——釘住目前行為。
**ruled B 2026-10-07（使用者裁示）**：認列時點維持已簽回／已付款；取消付款（unpay）一個已過帳／已結帳應計的勞報單**允許**，並產生沖回草稿，由會計審。
⇒ 本檔斷言就是**預期行為**（不是暫時釘住）。選項與裁示紀錄見 docs/platform/plans/PAYSLIP-LEDGER-OPTIONS-T46.md。
現況（`modules/payroll/gl_events.py`）：只有狀態 ∈ {已簽回, 已付款} 才產生 E06；E06b 只在已付款（且非匯款單付款）。
⇒ 待審核／已核准／已匯出 不入帳；沒簽回就付款的勞報單，E06 在**付款當下才出現**（認列日仍取勞報日期）；付款填錯退回（unpay）到已核准／已匯出
   ⇒ E06 與 E06b 一併消失（引擎下次執行會對已入帳的部分產生反向草稿，可能落在已結帳期間）。
若日後改採選項 A（核准時認列），這些斷言要改，那是新的使用者／會計決定。"""
import pytest

import db
from modules.accounting.ledger import roles as ROLES
from modules.payroll import gl_events as G
from modules.payroll.payslip_payables import unpay_status

_N = [0]
START, END = "2172-04-01", "2172-04-30"


@pytest.fixture
def conn(client):
    c = db.get_db()
    ROLES.ensure_meta(c)
    ROLES.ensure_default_roles(c)
    c.commit()
    yield c
    c.close()


def _slip(conn, status, signed_at="", payment_date="", export_count=0):
    _N[0] += 1
    no = "LB-T46-%d" % _N[0]
    cid = conn.execute("INSERT INTO contractors(name, id_number) VALUES (?,?)", ("王小明", "A123456789")).lastrowid
    conn.execute("INSERT INTO payslips(slip_no, contractor_id, contractor_name, income_type, gross_amount, tax_withheld, nhi_supplement, net_amount, "
                 "slip_date, status, signed_at, payment_date, export_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (no, cid, "王小明", "9A", 10000, 1000, 211, 8789, "2172-04-10", status, signed_at, payment_date, export_count))
    conn.commit()
    return no


def _codes(no):
    res = G.gl_events(START, END)
    return sorted(e["event_code"] for e in res["events"] if e["source_key"] == no)


def test_review_approved_and_exported_slips_are_not_accrued_today(conn):
    for st in ("草稿", "待審核", "已核准", "已匯出"):
        assert _codes(_slip(conn, st, export_count=1 if st == "已匯出" else 0)) == [], st


def test_signed_slip_is_accrued_and_signed_then_paid_adds_the_payment_event(conn):
    assert _codes(_slip(conn, "已簽回", signed_at="2172-04-12T09:00:00")) == ["E06"]
    assert _codes(_slip(conn, "已付款", signed_at="2172-04-12T09:00:00", payment_date="2172-04-20")) == ["E06", "E06b"]


def test_never_signed_paid_slip_is_accrued_only_from_payment_on(conn):
    """已核准直接付款（Q4）：E06 在付款當下才出現（認列日仍是勞報日期）。"""
    no = _slip(conn, "已核准")
    assert _codes(no) == []
    conn.execute("UPDATE payslips SET status='已付款', payment_date='2172-04-20' WHERE slip_no=?", (no,))
    conn.commit()
    assert _codes(no) == ["E06", "E06b"]
    ev = [e for e in G.gl_events(START, END)["events"] if e["source_key"] == no and e["event_code"] == "E06"][0]
    assert ev["event_date"] == "2172-04-10"


@pytest.mark.parametrize("signed,exported,back,expect", [
    ("", 0, "已核准", []), ("", 1, "已匯出", []), ("2172-04-12T09:00:00", 1, "已簽回", ["E06"])])
def test_unpay_regresses_the_accrual_unless_the_slip_was_signed(conn, signed, exported, back, expect):
    """付款填錯退回（unpay）後的現況：有簽回檔 ⇒ 退回已簽回、E06 保留；沒簽回 ⇒ E06／E06b 都消失（可能對已入帳期間產生反向草稿）。"""
    no = _slip(conn, "已付款", payment_date="2172-04-20", signed_at=signed, export_count=exported)
    if signed:
        conn.execute("UPDATE payslips SET signed_files_json='[{\"id\":\"a\"}]' WHERE slip_no=?", (no,))
    assert _codes(no)[:1] == ["E06"]
    row = conn.execute("SELECT signed_files_json, export_count FROM payslips WHERE slip_no=?", (no,)).fetchone()
    assert unpay_status(row) == back
    conn.execute("UPDATE payslips SET status=?, payment_date='' WHERE slip_no=?", (back, no))
    conn.commit()
    assert _codes(no) == expect
