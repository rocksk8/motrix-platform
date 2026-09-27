# -*- coding: utf-8 -*-
"""migrate_like_startup（H12 乾跑／轉換）的「模組化那一支」（稽核 D DS2／A AH-S6；B，2026-09-28）。

要在 ModuleSpec.migrations（CORE 1.58，wip/b-payreq）與 helpers/module_startup.py 都在的樹上才驗得到：
① 有 helpers/module_startup.py ⇒ 照啟動規則載入（load_modules_like_startup，停用清單讀第一個 --db）；沒有 ⇒ 不載入（舊包）
② 模組載入失敗 ⇒ 問題清單有它
③ 停用清單讀不到（全部暫不載入）⇒ 問題清單有它（驗不到那些模組的 migration，不可以當通過）
④ incomplete：None ⇒ 失敗、非空 ⇒ 失敗、空 ⇒ 通過
P2m 整合：tmp 安裝＋一個 migration 會丟例外、一個會回原因的假模組 ⇒ run() 回非空問題、主庫版號不前進；正常模組照樣前進
①～④ 用替身換掉 init_db／incomplete，只驗工具自己的判斷；P2m 跑真的 init_db。
"""
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from core import loader, migrations, registry

BACKEND = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("_migrate_like_startup", BACKEND / "tools" / "migrate_like_startup.py")
MLS = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MLS)


@pytest.fixture
def iso(monkeypatch):
    """登錄表、migration 登記、demo 缺席表隔離；授權閘門關掉；合成套件不留在 sys.modules。"""
    import helpers.licensing as lic
    from helpers import module_startup as ms
    snap = registry.snapshot()
    registry._reset()
    monkeypatch.setattr(migrations, "_REGISTRY", dict(migrations._REGISTRY))    # 保留 core 自己的登記
    monkeypatch.setattr(migrations, "_INCOMPLETE", {})
    monkeypatch.setattr(ms, "_DEMO_ABSENT", {})
    monkeypatch.setattr(lic, "LICENSE_GATE_ENABLED", False)
    yield
    registry.restore(snap)
    for k in [k for k in sys.modules if k.startswith("zzmls_")]:
        del sys.modules[k]


def _pkg(tmp_path, monkeypatch, name, modules):
    """modules：{key: __init__.py 原始碼}。"""
    pkg = tmp_path / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    for key, src in modules.items():
        d = pkg / key
        d.mkdir()
        (d / "module.json").write_text(json.dumps({"key": key, "name": key, "version": "0.0.1", "core": ">=1.0,<2.0"}),
                                       encoding="utf-8")
        (d / "__init__.py").write_text(src, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(loader, "MODULES_DIR", str(pkg))
    monkeypatch.setattr(loader, "MODULES_PACKAGE", name)
    return pkg


OK_MODULE = "from core.registry import ModuleSpec\nMODULE = ModuleSpec(key=%r)\n"


def _settings_db(path, disabled=()):
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE system_settings (key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT)")
        conn.execute("INSERT INTO system_settings VALUES ('modules_disabled', ?, '2026-09-28T00:00:00')",
                     (json.dumps(list(disabled)),))
        conn.commit()
    finally:
        conn.close()
    return str(path)


def _stub_init_db(monkeypatch, inc_by_path):
    """init_db 不動庫；incomplete 依路徑回給定值（None／dict）。"""
    import db
    seen = []
    monkeypatch.setattr(db, "init_db", lambda p=None: seen.append(p))
    monkeypatch.setattr(migrations, "incomplete", lambda p: inc_by_path.get(p, {}))
    return seen


# ── ① 照啟動規則載入 ──────────────────────────────────────────────────────────

def test_modular_tree_loads_like_startup_with_the_first_db(tmp_path, monkeypatch, iso):
    from helpers import module_startup
    assert MLS.has_module_startup(), "這棵樹有 helpers/module_startup.py，工具要看得到"
    calls = []
    monkeypatch.setattr(module_startup, "load_modules_like_startup", lambda db_path=None: calls.append(db_path))
    main_db, demo_db = str(tmp_path / "main.db"), str(tmp_path / "demo.db")
    seen = _stub_init_db(monkeypatch, {})
    assert MLS.run([main_db, demo_db]) == []
    assert calls == [main_db], "停用清單要讀第一個 --db（被試跑的主庫），而且只載一次"
    assert seen == [main_db, demo_db]


def test_reverse_control_old_package_does_not_load_modules_or_ask_incomplete(tmp_path, monkeypatch, iso):
    from helpers import module_startup
    monkeypatch.setattr(MLS, "has_module_startup", lambda backend=None: False)
    calls = []
    monkeypatch.setattr(module_startup, "load_modules_like_startup", lambda db_path=None: calls.append(db_path))
    _stub_init_db(monkeypatch, {str(tmp_path / "main.db"): None})       # 舊包不看 incomplete ⇒ None 也不算
    assert MLS.run([str(tmp_path / "main.db")]) == [] and calls == []


# ── ② 模組載入失敗 ────────────────────────────────────────────────────────────

def test_a_module_that_fails_to_load_is_a_problem(tmp_path, monkeypatch, iso):
    _pkg(tmp_path, monkeypatch, "zzmls_fail", {"zz_ok": OK_MODULE % "zz_ok", "zz_broken": "raise RuntimeError('壞掉的模組')\n"})
    main_db = _settings_db(tmp_path / "main.db")
    _stub_init_db(monkeypatch, {main_db: {}})
    problems = MLS.run([main_db])
    assert [p for p in problems if "zz_broken" in p and "載入失敗" in p], problems
    assert not [p for p in problems if "zz_ok" in p], problems


# ── ③ 停用清單讀不到 ──────────────────────────────────────────────────────────

def test_unreadable_disabled_list_is_a_problem(tmp_path, monkeypatch, iso):
    import helpers.module_switches as sw
    _pkg(tmp_path, monkeypatch, "zzmls_unread", {"zz_ok": OK_MODULE % "zz_ok"})
    bad = tmp_path / "main.db"
    bad.write_bytes(b"not a sqlite database" * 64)
    monkeypatch.setattr(sw, "READ_ATTEMPTS", 1)
    monkeypatch.setattr(sw, "READ_TIMEOUT_SECONDS", 0.1)
    _stub_init_db(monkeypatch, {str(bad): {}})
    problems = MLS.run([str(bad)])
    assert [p for p in problems if "zz_ok" in p and sw.UNREADABLE_REASON in p], problems


def test_reverse_control_a_readable_disabled_list_that_disables_a_module_is_not_a_problem(tmp_path, monkeypatch, iso):
    """管理者停用（讀得到）是正常狀態，不是問題——只有「讀不到」才算。"""
    _pkg(tmp_path, monkeypatch, "zzmls_off", {"zz_ok": OK_MODULE % "zz_ok", "zz_off": OK_MODULE % "zz_off"})
    main_db = _settings_db(tmp_path / "main.db", disabled=["zz_off"])
    _stub_init_db(monkeypatch, {main_db: {}})
    assert MLS.run([main_db]) == []


# ── ④ incomplete 的三種結果 ───────────────────────────────────────────────────

@pytest.mark.parametrize("inc,fails", [
    (None, True),                                 # 沒有結果＝run_all 沒有對這個庫執行 ⇒ 不可以當通過
    ({"zz_ok": (1, "表還沒建好")}, True),
    ({}, False),
])
def test_incomplete_none_or_nonempty_fails_and_empty_passes(tmp_path, monkeypatch, iso, inc, fails):
    _pkg(tmp_path, monkeypatch, "zzmls_inc", {"zz_ok": OK_MODULE % "zz_ok"})
    main_db = _settings_db(tmp_path / "main.db")
    _stub_init_db(monkeypatch, {main_db: inc})
    assert bool(MLS.run([main_db])) is fails


# ── P2m 整合：真的 init_db ────────────────────────────────────────────────────

MIG_MODULE = ("from core.registry import ModuleSpec\n"
              "def v1(conn):\n%s\n"
              "MODULE = ModuleSpec(key=%r, migrations=[(1, v1)])\n")


def test_p2m_a_raising_or_reason_migration_fails_the_dry_run_and_does_not_advance(tmp_path, monkeypatch, iso):
    _pkg(tmp_path, monkeypatch, "zzmls_p2m", {
        "zz_boom": MIG_MODULE % ("    conn.execute('CREATE TABLE zz_boom_half (id INTEGER)')\n"
                                 "    conn.execute('SELECT * FROM no_such_table_p2m')", "zz_boom"),
        "zz_later": MIG_MODULE % ("    return '前提不成立，下次再補'", "zz_later"),
        "zz_fine": MIG_MODULE % ("    conn.execute('CREATE TABLE IF NOT EXISTS zz_fine_t (id INTEGER)')", "zz_fine"),
    })
    main_db = str(tmp_path / "install" / "motrix_erp.db")
    (tmp_path / "install").mkdir()
    problems = MLS.run([main_db])
    assert [p for p in problems if "zz_boom" in p and "例外" in p], problems
    assert [p for p in problems if "zz_later" in p and "前提不成立" in p], problems
    assert not [p for p in problems if "zz_fine" in p], problems
    conn = sqlite3.connect(main_db)
    try:
        ver = dict(conn.execute("SELECT module, version FROM module_schema_versions").fetchall())
        assert ver.get("zz_boom", 0) == 0 and ver.get("zz_later", 0) == 0, ver
        assert ver.get("zz_fine") == 1, ver
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='zz_boom_half'").fetchone(), "例外之前的寫入要被撤回"
    finally:
        conn.close()
    assert MLS.main(["--db", main_db]) == 2                    # CLI 失敗 exit 2
