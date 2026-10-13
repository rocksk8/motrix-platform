# -*- coding: utf-8 -*-
"""U0a 回滾演練腳本（tools/platform/u0a_rollback_drill.py）的純函式與端到端冒煙。含正對照：故意破壞的升級結果，差異檢查必須報 FAIL。"""
import importlib.util
import shutil
import sqlite3
from pathlib import Path

import pytest

from core import migrations as M

REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("u0a_drill", REPO / "tools" / "platform" / "u0a_rollback_drill.py")
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)

LISTS = {"owner": list(M.U0A_OWNER_UNIT_TABLES), "unit": list(M.U0A_UNIT_ID_TABLES), "legal": list(M.U0A_LEGAL_ENTITY_TABLES),
         "scope": list(D.PERM_SCOPE_TABLES)}


def _build(path):
    c = sqlite3.connect(str(path))
    c.executescript("""
        CREATE TABLE schema_version (id INTEGER PRIMARY KEY CHECK (id=1), version INTEGER NOT NULL DEFAULT 0, applied_at TEXT NOT NULL DEFAULT '');
        INSERT INTO schema_version (id, version) VALUES (1, 118);
        CREATE TABLE module_schema_versions (module TEXT PRIMARY KEY, version INTEGER NOT NULL, applied_at TEXT NOT NULL DEFAULT '');
        INSERT INTO module_schema_versions (module, version) VALUES ('core', 9), ('case', 3);
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT);
        INSERT INTO users (username) VALUES ('a'), ('b');
        CREATE TABLE quotations (id INTEGER PRIMARY KEY, quote_no TEXT UNIQUE NOT NULL);
        INSERT INTO quotations (quote_no) VALUES ('MQ-1'), ('MQ-2');
        CREATE TABLE payslips (id INTEGER PRIMARY KEY, slip_no TEXT UNIQUE NOT NULL);
        INSERT INTO payslips (slip_no) VALUES ('PS-2610-001');
        CREATE TABLE vouchers_all (id INTEGER PRIMARY KEY, voucher_no TEXT, voided_at TEXT NOT NULL DEFAULT '');
        CREATE VIEW vouchers AS SELECT * FROM vouchers_all WHERE voided_at = '';
        INSERT INTO vouchers_all (voucher_no) VALUES ('20261001-001');
        CREATE TABLE quote_seq (month TEXT PRIMARY KEY, seq INTEGER NOT NULL DEFAULT 0);
        INSERT INTO quote_seq VALUES ('202610', 2);
        CREATE INDEX idx_q ON quotations(quote_no);
    """)
    c.commit()
    c.close()


def _upgrade(path):
    c = sqlite3.connect(str(path))
    assert M._core_next_org_units(c) is None
    c.commit()
    c.close()


@pytest.fixture
def pair(tmp_path):
    before, after = tmp_path / "before.db", tmp_path / "after.db"
    _build(before)
    shutil.copyfile(before, after)
    _upgrade(after)
    b = D.snapshot(before)
    cols = D.old_cols(b)
    return tmp_path, before, after, D.snapshot(before, cols), D.snapshot(after, cols)


def _failed(res):
    return sorted(n for n, ok, _ in res if not ok)


def test_module_version_bumps_are_allowed_only_for_the_expected_modules(pair, tmp_path):
    _, before, after, b, _ = pair
    cols = D.old_cols(D.snapshot(before))
    p = tmp_path / "bump.db"
    shutil.copyfile(after, p)
    c = sqlite3.connect(str(p))
    c.execute("UPDATE module_schema_versions SET version=2, applied_at='x' WHERE module='case'")
    c.commit(); c.close()
    s = D.snapshot(p, cols)
    assert "其他模組的 migration 版號不變（預期前進：無）" in _failed(D.diff_upgrade(b, s, LISTS, 118, bumps={}))
    assert not [n for n in _failed(D.diff_upgrade(b, s, LISTS, 118, bumps={"case": 2})) if n.startswith("其他模組")]
    assert any(n.startswith("其他模組") for n in _failed(D.diff_upgrade(b, s, LISTS, 118, bumps={"case": 5})))


def test_a_correct_additive_upgrade_passes_every_check(pair):
    _, _, _, b, a = pair
    res = D.diff_upgrade(b, a, LISTS, 118, bumps={})
    assert _failed(res) == [], [r for r in res if not r[1]]
    assert len(res) >= 15


def test_dropping_a_column_is_caught(pair, tmp_path):
    _, before, after, b, _ = pair
    bad = tmp_path / "bad.db"
    shutil.copyfile(after, bad)
    c = sqlite3.connect(str(bad))
    c.executescript(
        "ALTER TABLE payslips RENAME TO p_old; CREATE TABLE payslips (id INTEGER PRIMARY KEY, owner_unit_id INTEGER NOT NULL DEFAULT 1, legal_entity_id INTEGER NOT NULL DEFAULT 1);"
        "INSERT INTO payslips (id) SELECT id FROM p_old; DROP TABLE p_old;")
    c.commit(); c.close()
    res = D.diff_upgrade(b, D.snapshot(bad, D.old_cols(D.snapshot(before))), LISTS, 118)
    assert "既有欄位沒有被刪" in _failed(res)


def test_changed_row_count_and_changed_content_are_caught(pair, tmp_path):
    _, before, after, b, _ = pair
    cols = D.old_cols(D.snapshot(before))
    bad = tmp_path / "bad2.db"
    shutil.copyfile(after, bad)
    c = sqlite3.connect(str(bad))
    c.execute("DELETE FROM quotations WHERE quote_no='MQ-2'")
    c.execute("UPDATE payslips SET slip_no='PS-X'")
    c.commit(); c.close()
    failed = _failed(D.diff_upgrade(b, D.snapshot(bad, cols), LISTS, 118))
    assert "既有每表列數相同" in failed and "原有欄位的內容雜湊相同（排除新欄位）" in failed


def test_missing_default_unexpected_column_changed_quote_seq_and_version_are_caught(pair, tmp_path):
    _, before, after, b, _ = pair
    cols = D.old_cols(D.snapshot(before))

    def broken(name, sql):
        p = tmp_path / name
        shutil.copyfile(after, p)
        c = sqlite3.connect(str(p))
        c.executescript(sql)
        c.commit(); c.close()
        return D.snapshot(p, cols)
    # 新欄位沒有預設值：重建 quotations 時不給預設
    s1 = broken("nodef.db", "ALTER TABLE quotations RENAME TO q_old; CREATE TABLE quotations (id INTEGER PRIMARY KEY, quote_no TEXT UNIQUE NOT NULL, owner_unit_id INTEGER NOT NULL);"
                            "INSERT INTO quotations (id, quote_no, owner_unit_id) SELECT id, quote_no, 1 FROM q_old; DROP TABLE q_old;")
    assert "新欄位 NOT NULL DEFAULT 1（scope_json 可為空）" in _failed(D.diff_upgrade(b, s1, LISTS, 118))
    s2 = broken("extra.db", "ALTER TABLE users ADD COLUMN sneaky TEXT")
    assert "只多出清單上的新欄位" in _failed(D.diff_upgrade(b, s2, LISTS, 118))
    s3 = broken("seq.db", "DROP TABLE quote_seq; CREATE TABLE quote_seq (entity INTEGER, month TEXT, seq INTEGER, PRIMARY KEY(entity, month));")
    assert "quote_seq 的 DDL 逐字相同" in _failed(D.diff_upgrade(b, s3, LISTS, 118))
    s4 = broken("ver.db", "UPDATE schema_version SET version=119")
    assert "schema_version 不變" in _failed(D.diff_upgrade(b, s4, LISTS, 118))
    s5 = broken("idx.db", "DROP INDEX idx_q")
    assert "既有索引逐字相同" in _failed(D.diff_upgrade(b, s5, LISTS, 118))
    s6 = broken("view.db", "DROP VIEW vouchers; CREATE VIEW vouchers AS SELECT id FROM vouchers_all")
    assert "VIEW 逐字相同（vouchers 不重建）" in _failed(D.diff_upgrade(b, s6, LISTS, 118))


def test_parity_between_fresh_and_upgraded(pair, tmp_path):
    _, before, after, _, a = pair
    fresh = tmp_path / "fresh.db"
    _build(fresh)
    _upgrade(fresh)
    assert _failed(D.parity(D.snapshot(fresh), a)) == []
    c = sqlite3.connect(str(fresh))
    c.execute("ALTER TABLE users ADD COLUMN extra TEXT")
    c.execute("CREATE INDEX idx_extra ON users(username)")
    c.commit(); c.close()
    failed = _failed(D.parity(D.snapshot(fresh), a))
    assert "每表欄位（名稱／型別／NOT NULL／預設／主鍵）相同" in failed and "索引（名稱與 SQL）相同" in failed


def test_old_style_inserts_are_accepted_after_a_correct_upgrade_and_refused_for_a_bad_column(pair, tmp_path):
    _, _, after, _, _ = pair
    res = D.check_old_inserts(after, ["quotations", "payslips"])
    assert res and all(ok for _, ok, _ in res), res
    bad = tmp_path / "badins.db"
    shutil.copyfile(after, bad)
    c = sqlite3.connect(str(bad))
    c.executescript("ALTER TABLE users RENAME TO u_old; CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, owner_unit_id INTEGER NOT NULL);"
                    "INSERT INTO users (id, username, owner_unit_id) SELECT id, username, 1 FROM u_old; DROP TABLE u_old;")
    c.commit(); c.close()
    res = D.check_old_inserts(bad, ["users"])
    assert res and not res[0][1] and "owner_unit_id" in res[0][2]


def test_tool_lists_match_the_migration():
    assert D.NEW_TABLES == {"org_units", "org_unit_closure", "user_units", "system_settings_unit", "seq_by_entity"}
    assert set(D.INTERNAL) == {"owner_unit_id", "unit_id", "legal_entity_id", "scope_json"}


def test_probe_old_style_inserts_really_inserts_and_lands_on_the_root_unit(pair, tmp_path):
    _, _, after, _, _ = pair
    res = D.probe_old_style_inserts(after, ["quotations", "payslips", "vouchers_all"])
    assert len(res) == 3 and all(ok for _, ok, _ in res), res
    assert all("皆為 1" in d for _, _, d in res)
    c = sqlite3.connect(str(after))
    assert c.execute("SELECT COUNT(*) FROM quotations").fetchone()[0] == 2, "探測不留痕跡（SAVEPOINT 已 ROLLBACK）"
    c.close()
    bad = tmp_path / "badprobe.db"
    shutil.copyfile(after, bad)
    c = sqlite3.connect(str(bad))
    c.executescript("ALTER TABLE users RENAME TO u_old; CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, owner_unit_id INTEGER NOT NULL);"
                    "INSERT INTO users (id, username, owner_unit_id) SELECT id, username, 1 FROM u_old; DROP TABLE u_old;"
                    "ALTER TABLE payslips RENAME TO p_old; CREATE TABLE payslips (id INTEGER PRIMARY KEY, slip_no TEXT UNIQUE NOT NULL, owner_unit_id INTEGER NOT NULL DEFAULT 7);"
                    "DROP TABLE p_old;")
    c.commit(); c.close()
    res = dict((t, (ok, d)) for t, ok, d in D.probe_old_style_inserts(bad, ["users", "payslips"]))
    assert not res["users"][0] and "owner_unit_id" in res["users"][0 + 1]       # 新欄位拒絕舊式 INSERT
    assert not res["payslips"][0] and "不是根單位" in res["payslips"][1]        # 預設不是 1 ⇒ 落在別的單位


def test_seed_tool_builds_rows_and_scales_a_table(tmp_path):
    seed = D._seeder()
    p = tmp_path / "s.db"
    _build(p)
    n = seed.bulk(p, "quotations", 120)
    assert n == 120
    c = sqlite3.connect(str(p))
    assert c.execute("SELECT COUNT(DISTINCT quote_no) FROM quotations").fetchone()[0] == 120, "唯一鍵欄位要加序號"
    c.close()
