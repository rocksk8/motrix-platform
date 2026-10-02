# -*- coding: utf-8 -*-
"""遷移 0005（31-B S1）：重建 contractor_payment_vouchers，拿掉 dispatch_id UNIQUE、加款別／分期欄位。**合成資料**演練（正式機只有 4 筆：全已核准、2 已付、1 筆零稅率、1 筆含個人點工）。
RK6：舊列逐欄不變、新欄預設值、UNIQUE 拿掉但部分唯一索引守住舊行為、冪等、失敗整支撤回、AUTOINCREMENT 序號不回頭、完整性檢查。
反向控制：搬資料時改掉一個欄位值 ⇒ 遷移丟例外、舊表原封不動（見 test_rk6_a_corrupting_copy_is_detected_and_rolled_back）。"""
import importlib
import json
import sqlite3

import pytest

M = importlib.import_module("modules.subcontract.migrations.0005_remit_kinds_voucher_rebuild")

#: 正式機 A1 回報的表結構（含後加欄）；dispatch_id 內嵌 UNIQUE
OLD_DDL = """CREATE TABLE contractor_payment_vouchers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    voucher_no    TEXT    UNIQUE NOT NULL,
    dispatch_id   INTEGER UNIQUE NOT NULL REFERENCES contractor_dispatches(id),
    quote_no      TEXT    NOT NULL,
    vendor_id     INTEGER REFERENCES vendor_contractors(id),
    status        TEXT    NOT NULL DEFAULT '草稿',
    snapshot_json TEXT    NOT NULL DEFAULT '{}',
    data_json     TEXT    NOT NULL DEFAULT '{}',
    is_paid       INTEGER NOT NULL DEFAULT 0,
    paid_by       TEXT    DEFAULT '',
    paid_at       TEXT    DEFAULT '',
    paid_log      TEXT    NOT NULL DEFAULT '[]',
    export_count  INTEGER DEFAULT 0,
    export_log    TEXT    DEFAULT '[]',
    created_by    TEXT    DEFAULT '',
    created_at    TEXT,
    updated_at    TEXT,
    paid_bank_account_name TEXT NOT NULL DEFAULT '',
    paid_bank_account_code TEXT NOT NULL DEFAULT '',
    remit_actual REAL,
    remit_fee REAL NOT NULL DEFAULT 0,
    remit_review TEXT NOT NULL DEFAULT '',
    remit_review_by TEXT NOT NULL DEFAULT '',
    remit_review_at TEXT NOT NULL DEFAULT '',
    remit_review_note TEXT NOT NULL DEFAULT '')"""


def _old_db(rows=4, delete_some=False):
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("CREATE TABLE vendor_contractors (id INTEGER PRIMARY KEY, name TEXT)")
    c.execute("CREATE TABLE contractor_dispatches (id INTEGER PRIMARY KEY, quote_no TEXT)")
    c.execute(OLD_DDL)
    c.execute("CREATE INDEX idx_cpv_quote_no ON contractor_payment_vouchers(quote_no)")
    c.execute("CREATE INDEX idx_cpv_status ON contractor_payment_vouchers(status)")
    c.execute("INSERT INTO vendor_contractors VALUES (1, 'v')")
    for i in range(1, rows + 2):
        c.execute("INSERT INTO contractor_dispatches VALUES (?, 'Q-1')", (i,))
    for i in range(1, rows + 1):
        snap = {"totalAmount": 1000 * i, "taxRate": 0.0 if i == 3 else 0.05, "personnelTotal": 500 if i == 4 else 0, "grandTotal": 1050 * i}
        c.execute("INSERT INTO contractor_payment_vouchers (voucher_no, dispatch_id, quote_no, vendor_id, status, snapshot_json, is_paid, paid_at, remit_actual,"
                  " remit_fee, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  ("PV-%04d" % i, i, "Q-1", 1, "已核准", json.dumps(snap, ensure_ascii=False), 1 if i <= 2 else 0, "2026-09-0%d" % i if i <= 2 else "",
                   None if i != 1 else 1050.0 * i, 15 if i == 1 else 0, "admin", "2026-09-01T00:00:00", "2026-09-02T00:00:00"))
    if delete_some:
        c.execute("DELETE FROM contractor_payment_vouchers WHERE id=?", (rows,))          # 留下 sqlite_sequence 比 max(id) 大的狀況
    c.commit()
    return c


def _dump(c, table="contractor_payment_vouchers", cols=None):
    cols = cols or [r[1] for r in c.execute("PRAGMA table_info(%s)" % table)]
    return [tuple(r) for r in c.execute("SELECT %s FROM %s ORDER BY id" % (",".join(cols), table))]


def test_rk6_paid_rows_with_null_remit_actual_stay_null_after_rebuild():
    """正式機回報：已付申請的 remit_actual 全為 NULL（舊式整筆，實付＝grandTotal）。遷移不得補 0 或改值；讀取端回退用應付金額。"""
    c = _old_db()
    assert c.execute("SELECT is_paid, remit_actual FROM contractor_payment_vouchers WHERE voucher_no='PV-0002'").fetchone() == (1, None)
    assert M.up(c) is None
    assert c.execute("SELECT is_paid, remit_actual FROM contractor_payment_vouchers WHERE voucher_no='PV-0002'").fetchone() == (1, None)


def test_rk6_rebuild_keeps_every_old_column_value_and_adds_defaulted_new_columns():
    c = _old_db()
    old_cols = [r[1] for r in c.execute("PRAGMA table_info(contractor_payment_vouchers)")]
    before = _dump(c)
    assert M.up(c) is None
    after_cols = [r[1] for r in c.execute("PRAGMA table_info(contractor_payment_vouchers)")]
    assert after_cols[:len(old_cols)] == old_cols and after_cols[len(old_cols):] == [n for n, _ in M._NEW_COLS]
    assert _dump(c, cols=old_cols) == before                                                    # 舊欄逐列逐欄不變
    row = c.execute("SELECT kind, kind_name, kinds_version, seq, ratio, pretax_amount, inv_no, inv_date, inv_files_json, void_reason, voided_at, voided_by"
                    " FROM contractor_payment_vouchers WHERE id=1").fetchone()
    assert tuple(row) == ("", "", 0, 0, None, None, "", "", "[]", "", "", "")                   # 舊列＝舊式整筆申請
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok" and c.execute("PRAGMA foreign_key_check").fetchall() == []


def test_rk6_dispatch_unique_is_gone_but_partial_indexes_keep_the_old_behaviour():
    c = _old_db()
    assert M._has_dispatch_unique(c) is True
    M.up(c)
    assert M._has_dispatch_unique(c) is False                                                   # 單欄 UNIQUE 拿掉了
    ins = "INSERT INTO contractor_payment_vouchers (voucher_no, dispatch_id, quote_no, kind, seq, voided_at) VALUES (?,?,?,?,?,?)"
    # 舊式（kind=''）：同派發第二張未作廢 ⇒ 擋（與舊行為一致）
    with pytest.raises(sqlite3.IntegrityError):
        c.execute(ins, ("PV-X1", 1, "Q-1", "", 0, ""))
    c.execute(ins, ("PV-X2", 1, "Q-1", "", 0, "2026-10-02T00:00:00"))                           # 已作廢的不佔位置
    # 分期：同派發不同款別／不同期 ⇒ 可以；同款別同期 ⇒ 擋；作廢後可重開
    c.execute(ins, ("PV-D1", 5, "Q-1", "deposit", 1, ""))
    c.execute(ins, ("PV-P1", 5, "Q-1", "progress", 1, ""))
    c.execute(ins, ("PV-P2", 5, "Q-1", "progress", 2, ""))
    with pytest.raises(sqlite3.IntegrityError):
        c.execute(ins, ("PV-P1b", 5, "Q-1", "progress", 1, ""))
    c.execute("UPDATE contractor_payment_vouchers SET voided_at='2026-10-02T00:00:00' WHERE voucher_no='PV-P1'")
    c.execute(ins, ("PV-P1c", 5, "Q-1", "progress", 1, ""))
    with pytest.raises(sqlite3.IntegrityError):                                                 # voucher_no 仍唯一
        c.execute(ins, ("PV-D1", 5, "Q-1", "completion", 1, ""))
    names = {r[1] for r in c.execute("PRAGMA index_list(contractor_payment_vouchers)")}
    assert {"idx_cpv_quote_no", "idx_cpv_status", "idx_cpv_dispatch", "idx_cpv_dispatch_legacy", "idx_cpv_dispatch_kind_seq"} <= names


def test_rk6_is_idempotent_and_a_second_run_changes_nothing():
    c = _old_db()
    M.up(c)
    snap = (_dump(c), [tuple(r) for r in c.execute("SELECT name, sql FROM sqlite_master ORDER BY name")])
    assert M.up(c) is None
    assert (_dump(c), [tuple(r) for r in c.execute("SELECT name, sql FROM sqlite_master ORDER BY name")]) == snap


def test_rk6_missing_table_returns_a_reason_instead_of_raising():
    c = sqlite3.connect(":memory:")
    assert "不存在" in M.up(c)


def test_rk6_autoincrement_sequence_is_preserved_so_deleted_ids_are_not_reused():
    c = _old_db(rows=4, delete_some=True)                                                       # id 4 被刪：sequence=4、max(id)=3
    assert c.execute("SELECT seq FROM sqlite_sequence WHERE name='contractor_payment_vouchers'").fetchone()[0] == 4
    M.up(c)
    assert c.execute("SELECT seq FROM sqlite_sequence WHERE name='contractor_payment_vouchers'").fetchone()[0] == 4
    c.execute("INSERT INTO contractor_payment_vouchers (voucher_no, dispatch_id, quote_no) VALUES ('PV-NEW', 5, 'Q-1')")
    assert c.execute("SELECT id FROM contractor_payment_vouchers WHERE voucher_no='PV-NEW'").fetchone()[0] == 5


def test_rk6_foreign_keys_still_enforced_after_the_rebuild():
    c = _old_db()
    M.up(c)
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO contractor_payment_vouchers (voucher_no, dispatch_id, quote_no) VALUES ('PV-BAD', 999, 'Q-1')")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO contractor_payment_vouchers (voucher_no, dispatch_id, quote_no, vendor_id) VALUES ('PV-BAD2', 5, 'Q-1', 99)")


def test_rk6_a_corrupting_copy_is_detected_and_rolled_back():
    """反向控制：搬資料後新表有一個欄位被改掉 ⇒ 比對抓到、丟例外；loader 的 SAVEPOINT 撤回，舊表原封不動。"""
    c = _old_db()
    before_sql = c.execute("SELECT sql FROM sqlite_master WHERE name='contractor_payment_vouchers'").fetchone()[0]
    before = _dump(c)
    c.execute("SAVEPOINT motrix_module_migration")

    class Spy:                                                                                     # 包一層：複製完成後偷偷改一個值
        def __init__(self, conn):
            self._c = conn

        def execute(self, sql, *a):
            r = self._c.execute(sql, *a)
            if sql.startswith("INSERT INTO contractor_payment_vouchers_new"):
                self._c.execute("UPDATE contractor_payment_vouchers_new SET quote_no='TAMPERED' WHERE id=2")
            return r
    with pytest.raises(RuntimeError, match="不一致"):
        M.up(Spy(c))
    c.execute("ROLLBACK TO motrix_module_migration")
    c.execute("RELEASE motrix_module_migration")
    assert c.execute("SELECT sql FROM sqlite_master WHERE name='contractor_payment_vouchers'").fetchone()[0] == before_sql
    assert _dump(c) == before and not c.execute("SELECT 1 FROM sqlite_master WHERE name='contractor_payment_vouchers_new'").fetchone()


def test_rk6_manually_added_columns_on_the_old_table_survive():
    c = _old_db()
    c.execute("ALTER TABLE contractor_payment_vouchers ADD COLUMN hand_added TEXT NOT NULL DEFAULT 'x'")
    c.execute("UPDATE contractor_payment_vouchers SET hand_added='kept' WHERE id=2")
    M.up(c)
    assert c.execute("SELECT hand_added FROM contractor_payment_vouchers WHERE id=2").fetchone()[0] == "kept"


def test_rk6_registered_as_subcontract_migration_5_and_real_app_db_has_the_new_shape(client):
    import db
    from core import migrations as CM
    assert 5 in CM.registered()["subcontract"]
    conn = db.get_db()
    try:
        assert CM.current_version(conn, "subcontract") >= 5
        cols = {r[1] for r in conn.execute("PRAGMA table_info(contractor_payment_vouchers)")}
        assert {"kind", "kind_name", "kinds_version", "seq", "ratio", "pretax_amount", "voided_at"} <= cols
        assert M._has_dispatch_unique(conn) is False
    finally:
        conn.close()
