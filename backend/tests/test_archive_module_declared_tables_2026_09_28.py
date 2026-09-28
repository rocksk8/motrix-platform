# -*- coding: utf-8 -*-
"""L1 archive：已載入模組宣告 T1 的表自動進每日／月 JSON 匯出（主持裁示 2026-09-28；LODGING-NEARBY §3.3a）。

用合成的已載入模組（registry snapshot/restore），不綁任何真的 L2 模組（MODULE-GUIDE §7）。
- 宣告 T1 ⇒ 列；T2（含祕密欄位）／T3 ⇒ 不列；非法表名 ⇒ 不列並記 ERROR；已在寫死清單 ⇒ 不重複。
- 模組未載入（停用、未授權、不在包內）⇒ 不列 ⇒ 表不存在也不會變成 "error"（不誤報 daily_partial）。
- 正對照：載入中而表不存在 ⇒ 會列 ⇒ 匯出那張是 "error"（證明接點真的生效，不是永遠空的）。
"""
import logging

import pytest

import archive
from core import registry
from core.registry import LoadedModule, ModuleSpec

SYN_KEY = "zz_synthetic_backup"


def _manifest(tables):
    return {"key": SYN_KEY, "data": {"tables": tables, "files": []}}


@pytest.fixture()
def registry_snapshot():
    snap = registry.snapshot()
    yield
    registry.restore(snap)


def _load(tables):
    registry.register(LoadedModule(key=SYN_KEY, manifest=_manifest(tables), spec=ModuleSpec(key=SYN_KEY)))


def _mine(tables_dict):
    return {k: v for k, v in tables_dict.items() if k.startswith(archive.MODULE_BACKUP_PREFIX + SYN_KEY + "-")}


def test_only_declared_t1_with_valid_names_are_listed(registry_snapshot, caplog):
    _load([{"name": "zz_syn_t1", "class": "T1"},
           {"name": "zz_syn_t2", "class": "T2"},
           {"name": "zz_syn_t3", "class": "T3"},
           {"name": "bad name; DROP TABLE users", "class": "T1"},
           {"name": "Upper", "class": "T1"},
           {"name": "quotations", "class": "T1"}])            # 已在寫死清單
    with caplog.at_level(logging.ERROR, logger="archive"):
        tables = archive._daily_backup_tables()
        archive.backed_up_table_names()
    mine = _mine(tables)
    assert mine == {archive.MODULE_BACKUP_PREFIX + SYN_KEY + "-zz_syn_t1": "SELECT * FROM zz_syn_t1 ORDER BY rowid"}
    assert "zz_syn_t1" in archive.backed_up_table_names()
    assert sum(1 for sql in tables.values() if archive._BACKUP_TABLE_RE.findall(sql) == ["quotations"]) == 1
    assert caplog.text == "", "取清單（一輪會呼叫好幾次）不記 log；只有彙總檔固定欄位那一次記（E3-S1）"


def test_skipped_t2_goes_into_the_summary_and_is_logged_once_per_round(registry_snapshot, caplog):
    """E3-S1：宣告 T2 而沒匯出的表寫進彙總檔 `skipped_t2`（產物看得到），ERROR 每輪一次。"""
    _load([{"name": "zz_syn_t1", "class": "T1"}, {"name": "zz_syn_t2", "class": "T2"},
           {"name": "bad name", "class": "T1"}])
    with caplog.at_level(logging.ERROR, logger="archive"):
        header = archive._daily_backup_summary_header("2026-09-28", "now")
        archive._daily_backup_tables()
        archive._daily_backup_tables()
    assert SYN_KEY + ".zz_syn_t2" in header["skipped_t2"]
    assert caplog.text.count("zz_syn_t2") == 1 and caplog.text.count("'bad name'") == 1
    # 反向控制：模組未載入 ⇒ 不在 skipped_t2
    registry._LOADED.pop(SYN_KEY)
    assert SYN_KEY + ".zz_syn_t2" not in archive._daily_backup_summary_header()["skipped_t2"]


def test_not_loaded_module_is_not_listed_and_export_has_no_error(client, registry_snapshot, tmp_path, monkeypatch):
    import db
    monkeypatch.setattr(archive, "_cloud_write_json", lambda *a, **k: None)
    _load([{"name": "zz_syn_missing", "class": "T1"}])            # 載入中、表不存在（正對照）
    conn = db.get_db()
    try:
        s = archive._export_table_json_set(conn, str(tmp_path), "x", "now")
        key = archive.MODULE_BACKUP_PREFIX + SYN_KEY + "-zz_syn_missing"
        assert s[key] == "error"                                   # 接點真的生效
        registry._LOADED.pop(SYN_KEY)                              # 停用／未載入
        s2 = archive._export_table_json_set(conn, str(tmp_path), "x", "now")
        assert key not in s2
        assert not [k for k, v in s2.items() if v == "error" and k.startswith(archive.MODULE_BACKUP_PREFIX)]
    finally:
        conn.close()


def test_loaded_declared_table_is_exported_with_rows(client, registry_snapshot, tmp_path, monkeypatch):
    import db
    written = {}
    monkeypatch.setattr(archive, "_cloud_write_json", lambda p, k, data: written.setdefault(k, data))
    conn = db.get_db()
    try:
        conn.execute("CREATE TABLE zz_syn_rows (id INTEGER PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO zz_syn_rows (v) VALUES ('a'), ('b')")
        conn.commit()
        _load([{"name": "zz_syn_rows", "class": "T1"}])
        s = archive._export_table_json_set(conn, str(tmp_path), "pre", "now")
    finally:
        conn.close()
    key = archive.MODULE_BACKUP_PREFIX + SYN_KEY + "-zz_syn_rows"
    assert s[key] == 2
    assert [r["v"] for r in written["pre/%s.json" % key]["data"]] == ["a", "b"]
