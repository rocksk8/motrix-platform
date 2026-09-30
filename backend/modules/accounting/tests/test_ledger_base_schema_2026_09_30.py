# -*- coding: utf-8 -*-
"""總帳底層一次到位：B～C 全部批次會用到的表／欄位／觸發器都在同一支 migration（使用者裁示：之後各批只改 accounting 程式，不再新增 migration）。

守門：①每個批次需要的表與關鍵欄位都在（缺一個＝那批之後要再開 migration，違反裁示）②每張表都能寫入（DDL 沒手誤）
③只增不改的表真的擋 UPDATE／DELETE，且有反向控制 ④module.json 的資料分類涵蓋全部新表 ⑤功能旗標預設全關、只有 superadmin 能開關。
"""
import importlib
import json
import re
from pathlib import Path

import pytest

import db

MIG = "modules.accounting.migrations.0001_ledger_base"

#: 批次 → 需要的 (表, 關鍵欄位)。新增批次需求時先加在這裡；表或欄位不在 migration ⇒ 這題紅。
REQUIRED = {
    "A/B 期間與報表": {
        "gl_settings": ["key", "value"], "gl_account_meta": ["cashflow_class", "fs_line", "postable"],
        "gl_account_roles": ["role", "account_code"], "gl_fiscal_years": ["opening_mode"], "gl_periods": ["status", "stale", "tb_hash"],
        "gl_period_log": ["action", "reason"], "gl_opening_batches": ["voucher_id"], "gl_opening_balances": ["debit"],
        "gl_opening_items": ["party_key"], "gl_fs_lines": ["statement", "kind"], "gl_balance_snapshot": ["period_id"],
        "gl_statement_snapshots": ["payload_json", "frozen"]},
    "C1 引擎與銷項": {
        "gl_source_events": ["source_type", "source_key", "event_code", "rev", "content_hash", "status", "voucher_id", "payload_json"],
        "gl_engine_runs": ["notices_json"], "gl_confirm_batches": ["action", "detail_json"], "gl_cursors": ["name", "value"],
        "gl_source_annotations": ["source_type", "source_key", "field", "value"], "gl_category_map": ["source", "category", "account_code"]},
    "C2/C3 應付與人事": {"gl_withholding_items": ["kind", "gross", "amount", "period_ym", "remit_voucher_id"]},
    "C4 存貨": {"gl_inv_moves": ["part_no", "move_type", "qty", "amount", "qty_after", "value_after", "links_move_id"],
              "gl_inv_parts": ["qty", "value"]},
    "C5 營業稅": {"gl_tax401_map": ["tax_code", "invoice_kind", "field_amt"],
                "gl_tax_settlements": ["output_tax", "input_tax", "carry_prev", "payable", "carry_new", "refund_amount"]},
    "C6 固定資產": {"fa_categories": ["cost_account", "accum_account"],
                 "fa_assets": ["cost", "input_tax", "life_years", "salvage", "tax_life_years", "tax_capitalized", "refund_flag", "status"],
                 "fa_revisions": ["effective_month"], "fa_depr_runs": ["ym", "tax_total"], "fa_depr_lines": ["tax_amount", "accum_after"]},
    "C7 建構器與折讓": {"gl_custom_field_map": ["module_key", "field_key", "debit_account"],
                    "gl_invoice_adjustments": ["invoice_no", "adj_type", "pretax", "tax", "cert_no"]},
    "C8 補登": {"gl_backfill_runs": ["range_start", "counts_json"]},
}
NEW_VOUCHER_COLS = {"voucher_lines": ["case_no", "party_key", "tax_code", "doc_no"],
                    "vouchers_all": ["kind", "reverses_no", "is_backfill", "origin", "gl_event_id"]}


@pytest.fixture
def conn(client):
    c = db.get_db()
    yield c
    c.close()


def _cols(conn, table):
    return {r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)}


@pytest.mark.parametrize("batch", sorted(REQUIRED))
def test_every_batch_has_its_tables_and_key_columns(conn, batch):
    for table, cols in REQUIRED[batch].items():
        have = _cols(conn, table)
        assert have, "%s：表 %s 不在 migration 裡（那一批之後得再開 migration）" % (batch, table)
        assert set(cols) <= have, "%s：表 %s 缺欄位 %s" % (batch, table, sorted(set(cols) - have))


def test_voucher_columns_for_all_batches_exist(conn):
    for table, cols in NEW_VOUCHER_COLS.items():
        assert set(cols) <= _cols(conn, table), (table, sorted(set(cols) - _cols(conn, table)))


def test_every_table_in_the_migration_is_covered_by_this_list(conn):
    src = Path(importlib.import_module(MIG).__file__).read_text(encoding="utf-8")
    created = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", src))
    listed = {t for tables in REQUIRED.values() for t in tables}
    assert created <= listed, "migration 有表沒列入需求清單（清單要跟著長）：%s" % sorted(created - listed)


def test_module_json_declares_every_new_table_with_a_data_class(conn):
    d = json.loads((Path(importlib.import_module(MIG).__file__).parents[1] / "module.json").read_text(encoding="utf-8"))
    src = Path(importlib.import_module(MIG).__file__).read_text(encoding="utf-8")
    created = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", src))
    classed = {t["name"] for t in d["data"]["tables"]}
    assert created <= set(d["tables"]) and created <= classed, sorted(created - (set(d["tables"]) & classed))


# ── 每張表都能寫入（DDL 沒手誤）＋唯一鍵 ──────────────────────────────────

def test_smoke_insert_into_every_new_table(conn):
    q = [
        "INSERT INTO gl_source_events(source_type,source_key,event_code,event_date) VALUES ('t','k','E01','2026-10-01')",
        "INSERT INTO gl_engine_runs(started_by) VALUES ('t')",
        "INSERT INTO gl_confirm_batches(action) VALUES ('post')",
        "INSERT INTO gl_cursors(name,value) VALUES ('c','1')",
        "INSERT INTO gl_category_map(source,category,account_code) VALUES ('extra','材料','5811')",
        "INSERT INTO gl_custom_field_map(module_key,field_key,debit_account,credit_account) VALUES ('m','f','6134','2171')",
        "INSERT INTO gl_source_annotations(source_type,source_key,field,value) VALUES ('dispatch','1','invoice_tax','500')",
        "INSERT INTO gl_backfill_runs(range_start,range_end) VALUES ('2025-01-01','2025-12-31')",
        "INSERT INTO gl_tax401_map(tax_code,invoice_kind,field_amt) VALUES ('OUT-5','einvoice','5')",
        "INSERT INTO gl_tax_settlements(period_start,period_end) VALUES ('2026-09-01','2026-10-31')",
        "INSERT INTO gl_invoice_adjustments(invoice_no,adj_type,adj_date) VALUES ('AB12345678','allowance','2026-10-05')",
        "INSERT INTO gl_withholding_items(kind,source_type,source_key) VALUES ('income_tax','payslip','PS-1')",
        "INSERT INTO gl_inv_moves(part_no,move_at,move_type,qty,amount,qty_after,value_after,ref_type,ref_key) VALUES ('P1','t','receipt',1,100,1,100,'batch','B1')",
        "INSERT INTO gl_inv_parts(part_no) VALUES ('P1')",
        "INSERT INTO fa_categories(code,name) VALUES ('PC','電腦')",
        "INSERT INTO fa_assets(asset_no,name,acquired_on,in_service_on) VALUES ('FA-1','筆電','2026-10-01','2026-10-01')",
        "INSERT INTO fa_revisions(asset_id,effective_month,life_years,salvage) VALUES (1,'2027-01',4,0)",
        "INSERT INTO fa_depr_runs(ym) VALUES ('2026-10')",
        "INSERT INTO fa_depr_lines(ym,asset_id) VALUES ('2026-10',1)",
        "INSERT INTO gl_statement_snapshots(kind,fy) VALUES ('balance_sheet',2026)",
    ]
    for sql in q:
        conn.execute(sql)
    conn.commit()


def test_unique_keys_prevent_duplicate_events_and_inventory_moves(conn):
    import sqlite3
    conn.execute("INSERT INTO gl_source_events(source_type,source_key,event_code,event_date) VALUES ('u','k1','E01','2026-10-01')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO gl_source_events(source_type,source_key,event_code,event_date) VALUES ('u','k1','E01','2026-10-02')")
    conn.execute("INSERT INTO gl_source_events(source_type,source_key,event_code,rev,event_date) VALUES ('u','k1','E01',2,'2026-10-02')")   # 新版本 rev+1 可
    conn.execute("INSERT INTO gl_inv_moves(part_no,move_at,move_type,qty,amount,qty_after,value_after,ref_type,ref_key) VALUES ('U1','t','issue',-1,-50,0,0,'note','N1')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO gl_inv_moves(part_no,move_at,move_type,qty,amount,qty_after,value_after,ref_type,ref_key) VALUES ('U1','t2','issue',-1,-50,0,0,'note','N1')")
    conn.rollback()


# ── 只增不改的表：觸發器與反向控制 ─────────────────────────────────────────

def _seed_append_only(conn):
    conn.execute("INSERT OR IGNORE INTO gl_source_events(source_type,source_key,event_code,event_date) VALUES ('a','1','E01','2026-10-01')")
    conn.execute("INSERT OR IGNORE INTO gl_inv_moves(part_no,move_at,move_type,qty,amount,qty_after,value_after,ref_type,ref_key) VALUES ('AO','t','receipt',1,10,1,10,'b','1')")
    conn.execute("INSERT OR IGNORE INTO fa_revisions(asset_id,effective_month,life_years,salvage) VALUES (99,'2027-01',3,0)")
    conn.execute("INSERT INTO gl_statement_snapshots(kind,fy,frozen) VALUES ('is',2025,1)")
    conn.commit()


def test_append_only_tables_refuse_update_and_delete(conn):
    import sqlite3
    _seed_append_only(conn)
    bad = [
        "DELETE FROM gl_source_events WHERE source_key='1'",
        "UPDATE gl_inv_moves SET amount=1 WHERE part_no='AO'", "DELETE FROM gl_inv_moves WHERE part_no='AO'",
        "UPDATE fa_revisions SET life_years=9 WHERE asset_id=99", "DELETE FROM fa_revisions WHERE asset_id=99",
        "UPDATE gl_statement_snapshots SET payload_json='{}' WHERE fy=2025", "DELETE FROM gl_statement_snapshots WHERE fy=2025",
    ]
    for sql in bad:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql)
        conn.rollback()
    # 事件可以改狀態（引擎的正常操作）；未凍結的快照可改
    conn.execute("UPDATE gl_source_events SET status='drafted' WHERE source_key='1'")
    conn.execute("INSERT INTO gl_statement_snapshots(kind,fy,frozen) VALUES ('draft',2026,0)")
    conn.execute("UPDATE gl_statement_snapshots SET payload_json='{\"x\":1}' WHERE kind='draft'")
    conn.commit()


def test_reverse_control_without_the_triggers_the_same_edits_succeed(conn):
    _seed_append_only(conn)
    mig = importlib.import_module(MIG)
    names = [n for n in mig.TRIGGER_NAMES if n in ("gl_events_no_delete", "gl_inv_moves_no_update", "gl_inv_moves_no_delete",
                                                   "gl_fa_revisions_no_update", "gl_fa_revisions_no_delete",
                                                   "gl_stmt_snapshots_no_update", "gl_stmt_snapshots_no_delete")]
    assert len(names) == 7
    saved = {n: conn.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (n,)).fetchone()[0] for n in names}
    try:
        for n in names:
            conn.execute("DROP TRIGGER %s" % n)
        conn.execute("UPDATE gl_inv_moves SET amount=1 WHERE part_no='AO'")
        conn.execute("DELETE FROM gl_source_events WHERE source_key='1'")
        conn.execute("UPDATE fa_revisions SET life_years=9 WHERE asset_id=99")
        conn.execute("UPDATE gl_statement_snapshots SET payload_json='{}' WHERE fy=2025")
        conn.commit()
    finally:
        for sql in saved.values():
            conn.execute(sql)
        conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'gl_%'").fetchone()[0] == len(mig.TRIGGER_NAMES)


# ── 功能旗標 ──────────────────────────────────────────────────────────────

def _login(client, make_user, username, role="superadmin", modules=("finance",)):
    u, p = make_user(username=username, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_features_default_off_and_only_superadmin_can_toggle(client, make_user, conn):
    sup = _login(client, make_user, "gl_base_sup")
    fin = _login(client, make_user, "gl_base_fin", role="staff", modules=("finance",))
    none = _login(client, make_user, "gl_base_none", role="staff", modules=())
    assert client.get("/api/ledger/features", headers=none).status_code == 403
    feats = client.get("/api/ledger/features", headers=fin).json()["features"]
    assert {f["key"] for f in feats} >= {"engine_drafts", "inventory_cost", "tax401", "fixed_assets", "invoice_adjustments",
                                          "custom_records", "backfill", "withholding", "source_annotations"}
    assert not any(f["enabled"] for f in feats), "旗標預設必須全部關閉（未完成的功能不可對使用者露出）"
    assert client.put("/api/ledger/features/engine_drafts", headers=fin, json={"enabled": True}).status_code == 403     # finance 不能開
    assert client.put("/api/ledger/features/nope", headers=sup, json={"enabled": True}).status_code == 404
    assert client.put("/api/ledger/features/engine_drafts", headers=sup, json={"enabled": True}).status_code == 200
    got = {f["key"]: f["enabled"] for f in client.get("/api/ledger/features", headers=fin).json()["features"]}
    assert got["engine_drafts"] is True and got["fixed_assets"] is False
    assert client.put("/api/ledger/features/engine_drafts", headers=sup, json={"enabled": False}).status_code == 200
    assert not {f["key"]: f["enabled"] for f in client.get("/api/ledger/features", headers=fin).json()["features"]}["engine_drafts"]
