# -*- coding: utf-8 -*-
"""一次性重新對齊「付款待辦」事件的工具（tools/payable_calendar_resync.py；第 45 班稽核 S4）：預設 dry-run、只列 id、--apply 才呼叫 sync、不接受 --db。"""
import os
import sqlite3
import sys

from tests._requires import requires_module

pytestmark = [requires_module("case", "付款待辦事件在 M01")]

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tools"))
import payable_calendar_resync as RS  # noqa: E402

NO = "MQ-RESYNC-001"


def _seed(planned="", status="已核准", paid=""):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
                     " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (NO, "已送出", "客", "案", 1, 1, "{}", "2031-01-01T00:00:00", "2031-01-01T00:00:00", "已成案", "", "[]"))
        cur = conn.execute("INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, expense_date,"
                           " files_json, created_by, created_by_name, payer_name, created_at, updated_at, status, paid_date, kind, planned_pay_date)"
                           " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (NO, "材料", "線材", 1, "", 1200, 1200, "2031-05-01", "[]", "rs_eng", "工程師", "材料行", "2031-05-01", "2031-05-01",
                            status, paid, "", planned))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _copy(tmp_path):
    import db
    src = db.get_db()
    dst = sqlite3.connect(str(tmp_path / "rs.db"))
    src.backup(dst)
    dst.close()
    src.close()
    return str(tmp_path / "rs.db")


def test_dry_run_lists_only_currently_eligible_rows_and_never_calls_sync(client, tmp_path, monkeypatch, capsys):
    from modules.case import payable_calendar as PC
    ok1 = _seed(planned="2031-06-10")
    ok2 = _seed(planned="2031-06-11")
    _seed(planned="")                                   # 沒預定日
    _seed(planned="2031-06-12", paid="2031-06-13")      # 已付款
    _seed(planned="2031-06-14", status="草稿")          # 未核准
    calls = []
    monkeypatch.setattr(PC, "sync", lambda i: calls.append(i))
    path = _copy(tmp_path)
    assert RS.main(["--db", path]) == 0
    out = capsys.readouterr().out
    assert "會重新對齊 2 筆" in out and str(ok1) in out and str(ok2) in out and "dry-run" in out
    assert calls == []
    assert "線材" not in out and "1200" not in out, "輸出只有 id，不含名稱或金額"


def test_apply_calls_sync_for_each_eligible_row_with_limit_and_refuses_db(client, tmp_path, monkeypatch, capsys):
    from modules.case import payable_calendar as PC
    a = _seed(planned="2031-06-10")
    b = _seed(planned="2031-06-11")
    calls = []
    monkeypatch.setattr(PC, "sync", lambda i: calls.append(i))
    assert RS.main(["--apply", "--sleep", "0"]) == 0
    assert calls == [a, b]
    calls.clear()
    assert RS.main(["--apply", "--sleep", "0", "--limit", "1"]) == 0
    assert calls == [a]
    calls.clear()
    assert RS.main(["--apply", "--db", _copy(tmp_path)]) == 2 and calls == []         # --apply 不接受 --db
    capsys.readouterr()
