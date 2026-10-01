# -*- coding: utf-8 -*-
"""31-A S1：subcontract 0003 migration（冪等、不動舊列）與 `_dispatch_row` 新欄位、合併狀態文字。"""
import hashlib
import importlib
import json
import sqlite3

import pytest

from modules.subcontract import dispatch_flow as F

MIG = importlib.import_module("modules.subcontract.migrations.0003_dispatch_approval")
NEW = {c for c, _ in MIG._COLS}


def _old_db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE contractor_dispatches (id INTEGER PRIMARY KEY AUTOINCREMENT, quote_no TEXT NOT NULL, vendor_id INTEGER, status TEXT DEFAULT 'draft',"
              " total_amount REAL DEFAULT 0, items_json TEXT DEFAULT '[]', invoice_no TEXT DEFAULT '')")
    c.executemany("INSERT INTO contractor_dispatches(quote_no, vendor_id, status, total_amount, items_json, invoice_no) VALUES (?,?,?,?,?,?)",
                  [("Q1", 1, "completed", 1000, "[]", "AB12345678"), ("Q2", None, "draft", 0, "[]", ""), ("Q3", 2, "accepted", 500.5, '[{"amount":5}]', "")])
    c.commit()
    return c


def _digest(c, cols):
    rows = c.execute("SELECT %s FROM contractor_dispatches ORDER BY id" % ",".join(cols)).fetchall()
    return hashlib.sha256(json.dumps([list(r) for r in rows], ensure_ascii=False).encode()).hexdigest()


def test_migration_adds_columns_keeps_old_rows_and_is_idempotent():
    c = _old_db()
    old_cols = ["id", "quote_no", "vendor_id", "status", "total_amount", "items_json", "invoice_no"]
    before = _digest(c, old_cols)
    assert MIG.up(c) is None
    cols1 = [(r[1], r[2], r[4]) for r in c.execute("PRAGMA table_info(contractor_dispatches)")]
    assert NEW <= {x[0] for x in cols1}
    assert _digest(c, old_cols) == before                                                         # 舊列逐欄不變
    rows = c.execute("SELECT approval_status, completion_status, doc_code, approval_json, approved_hash FROM contractor_dispatches").fetchall()
    assert all(tuple(r) == ("", "", "", "{}", "") for r in rows)                                  # 舊單＝空字串（不溯及既往）
    c.commit()
    assert MIG.up(c) is None                                                                       # 第二次：零例外
    assert [(r[1], r[2], r[4]) for r in c.execute("PRAGMA table_info(contractor_dispatches)")] == cols1      # schema 逐欄相同
    assert _digest(c, old_cols) == before
    idx = {r[1] for r in c.execute("PRAGMA index_list(contractor_dispatches)")}
    assert {"idx_dispatch_doc_code", "idx_dispatch_approval"} <= idx


def test_doc_code_unique_only_when_filled():
    c = _old_db()
    MIG.up(c)
    c.execute("UPDATE contractor_dispatches SET doc_code='DP-20261001-0001' WHERE id=1")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("UPDATE contractor_dispatches SET doc_code='DP-20261001-0001' WHERE id=2")     # 重複單號被擋（反向控制）
    c.execute("UPDATE contractor_dispatches SET doc_code='' WHERE id=1")                            # 空字串不受限：舊單多筆
    assert c.execute("SELECT COUNT(*) FROM contractor_dispatches WHERE doc_code=''").fetchone()[0] == 3


def test_missing_table_reports_instead_of_raising():
    c = sqlite3.connect(":memory:")
    assert isinstance(MIG.up(c), str)


def test_fresh_database_has_the_columns_and_dispatch_row_exposes_them(client):
    import db
    from modules.subcontract.api import vendor_contractors as V
    conn = db.get_db()
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(contractor_dispatches)")}
        assert NEW <= cols
        conn.execute("INSERT INTO contractor_dispatches (quote_no, vendor_id, status, created_by, created_at, updated_at) VALUES ('Q-S1', NULL, 'draft', 'x', 'n', 'n')")
        conn.execute("INSERT INTO contractor_dispatches (quote_no, vendor_id, status, approval_status, doc_code, created_by, created_at, updated_at)"
                     " VALUES ('Q-S1', NULL, 'draft', '草稿', 'DP-20261001-0001', 'x', 'n', 'n')")
        conn.commit()
        rows = conn.execute("SELECT d.*, NULL AS vendor_name FROM contractor_dispatches d WHERE quote_no='Q-S1' ORDER BY id").fetchall()
    finally:
        conn.close()
    old, new = V._dispatch_row(rows[0]), V._dispatch_row(rows[1])
    assert old["legacy"] is True and old["approvalStatus"] == "" and old["docCode"] == "" and old["displayStatus"] == "草稿"
    assert new["legacy"] is False and new["approvalStatus"] == "草稿" and new["docCode"] == "DP-20261001-0001" and new["displayStatus"] == "草稿（尚未送審）"


@pytest.mark.parametrize("row, want", [
    ({"status": "draft", "approval_status": ""}, "草稿"),                                                  # 舊單：照舊顯示作業狀態
    ({"status": "accepted", "approval_status": ""}, "已驗收"),
    ({"status": "draft", "approval_status": "草稿"}, "草稿（尚未送審）"),
    ({"status": "draft", "approval_status": "待審核"}, "派發審核中"),
    ({"status": "draft", "approval_status": "簽核中"}, "派發審核中"),
    ({"status": "draft", "approval_status": "已退回"}, "派發被退回"),
    ({"status": "sent", "approval_status": "已核准"}, "已送出"),
    ({"status": "accepted", "approval_status": "已核准", "completion_status": "待審核"}, "完工審核中"),
    ({"status": "accepted", "approval_status": "已核准", "completion_status": "已退回"}, "完工被退回（已驗收）"),
    ({"status": "completed", "approval_status": "已核准", "completion_status": "已核准"}, "完工"),
    ({"status": "cancelled", "approval_status": "待審核"}, "已取消"),
])
def test_display_status_is_one_human_word(row, want):
    assert F.display_status(row) == want
