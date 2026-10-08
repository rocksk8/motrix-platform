# -*- coding: utf-8 -*-
"""第 47 班（第 46 班獨立稽核 S4/S5 + 補測）：預定付款日提供者的寫鎖、「沒變」也對齊行事曆、叫料匯款同值路徑、行事曆重新對齊工具。"""
import os
import sqlite3
import sys

import pytest

from tests._requires import requires_module, skip_module_unless

skip_module_unless("case", "預定付款日提供者在 M01")
from modules.case.tests.test_cashier_planned_pay_date_t45 import _hdr, _row, _seed, _url  # noqa: E402,F401
from modules.case.tests.test_material_payment_planned_t45 import (  # noqa: E402,F401
    _approve, _create, _planned, _url as _mp_url, world)

_MAKE_USER_DEFAULT_ROLE = "superadmin"


# ── S5：沒變也照做（冪等的）行事曆對齊，稽核與通知照樣略過 ─────────────────────────────────────────
@requires_module("arap", "出納端點在 M05")
def test_unchanged_date_still_runs_the_idempotent_calendar_hook_but_skips_audit(client, make_user, monkeypatch):
    from core import registry
    eid = _seed(planned="2031-06-10")
    h = _hdr(client, make_user, "t47_fin_cal", role="finance")
    p = registry.providers("payables.pending")["case"]
    calls = []
    monkeypatch.setattr(p, "planned_changed", lambda key: calls.append(str(key)), raising=False)
    import db
    c = db.get_db()
    try:
        before = c.execute("SELECT COUNT(*) FROM audit_log WHERE action='cashier.planned_pay_date'").fetchone()[0]
    finally:
        c.close()
    r = client.patch(_url(eid), headers=h, json={"plannedPayDate": "2031-06-10"})
    assert r.status_code == 200 and r.json().get("unchanged") is True, r.text
    assert calls == [str(eid)], "沒變也要對齊行事曆（上次背景推送失敗時，重按一次能修復）"
    c = db.get_db()
    try:
        after = c.execute("SELECT COUNT(*) FROM audit_log WHERE action='cashier.planned_pay_date'").fetchone()[0]
    finally:
        c.close()
    assert after == before, "沒變 ⇒ 不稽核"
    r = client.patch(_url(eid), headers=h, json={"plannedPayDate": "2031-06-20"})          # 真的改了：hook 與稽核都有
    assert r.status_code == 200 and "unchanged" not in r.json() and calls == [str(eid), str(eid)]


# ── 叫料匯款提供者：同值路徑（補測；稽核 S3 原本只測了額外支出與承攬商）──────────────────────────────────
@requires_module("arap", "出納端點在 M05")
def test_material_payment_same_value_is_unchanged_and_writes_nothing(client, world):
    pid = _create(client, world, plannedPayDate="2031-06-10").json()["payment"]["id"]
    _approve(client, world, pid)
    import db
    c = db.get_db()
    try:
        stamp = c.execute("SELECT updated_at FROM case_material_payments WHERE id=?", (pid,)).fetchone()[0]
    finally:
        c.close()
    r = client.patch(_mp_url(pid), json={"plannedPayDate": "2031-06-10"}, headers=world["fin"])
    assert r.status_code == 200 and r.json().get("unchanged") is True, r.text
    assert _planned(pid) == "2031-06-10"
    c = db.get_db()
    try:
        assert c.execute("SELECT updated_at FROM case_material_payments WHERE id=?", (pid,)).fetchone()[0] == stamp      # 沒變 ⇒ 沒寫
    finally:
        c.close()


# ── 寫鎖：三個提供者都必須在讀之前拿寫鎖（spy）────────────────────────────────────────────────────
@pytest.mark.parametrize("which", ["case", "material"])
def test_case_and_material_providers_take_the_write_lock_first(monkeypatch, client, which):
    import core.txn as txn
    import db
    from modules.case import material_payment_cashier as mpc
    from modules.case import payables
    cls = payables._Payables if which == "case" else mpc._Payables
    seen = []
    real = txn.begin_write
    monkeypatch.setattr(txn, "begin_write", lambda conn: (seen.append("begin_write"), real(conn))[1])      # 提供者在函式內才 import ⇒ 換這裡有效
    conn = db.get_db()
    try:
        with pytest.raises(LookupError):
            cls.set_planned_pay_date(conn, "999999", "2031-06-10", {"username": "x"})
    finally:
        conn.close()
    assert seen == ["begin_write"], "讀之前必須先拿寫鎖"


@requires_module("subcontract", "承攬商匯款提供者在 M04")
def test_voucher_provider_takes_the_write_lock_before_reading(monkeypatch, client):
    import db
    from modules.subcontract.api import contractor_vouchers as cv
    order = []
    monkeypatch.setattr(cv, "begin_write", lambda conn: order.append("begin_write"))
    conn = db.get_db()
    try:
        with pytest.raises(LookupError):
            cv.set_planned_pay_date(conn, "NO-SUCH-VOUCHER", "2031-06-10", {"username": "x"})
    finally:
        conn.close()
    assert order == ["begin_write"], "讀之前必須先拿寫鎖（稽核 S4）"


# ── 行事曆重新對齊工具 ───────────────────────────────────────────────────────────────────────────
def _tool():
    path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "tools")
    if path not in sys.path:
        sys.path.insert(0, path)
    import importlib
    return importlib.import_module("payable_calendar_resync")


def test_resync_continues_after_one_failure_and_reports_it(monkeypatch, capsys):
    tool = _tool()
    from modules.case import payable_calendar as PC
    monkeypatch.setattr(tool, "eligible_ids", lambda conn: [1, 2, 3])
    done = []

    def sync(i):
        if i == 2:
            raise RuntimeError("Google 暫時錯誤")
        done.append(i)
    monkeypatch.setattr(PC, "sync", sync)
    rc = tool.main(["--apply", "--sleep", "0"])
    out = capsys.readouterr().out
    assert done == [1, 3], "第 2 筆失敗不可中斷整批"
    assert rc == 1 and "失敗 1 筆" in out and "2" in out


def test_resync_db_path_with_special_characters_opens(tmp_path, capsys):
    tool = _tool()
    p = tmp_path / "a%41b#c d.db"
    sqlite3.connect(str(p)).close()
    assert tool.main(["--db", str(p)]) == 0                    # 沒有額外支出資料表 ⇒ 「無事可做」，但必須先打得開
    out = capsys.readouterr().out
    assert "讀不到資料庫" not in out and "unable to open" not in out and "no such table" in out      # 開得到檔、只是沒有表
