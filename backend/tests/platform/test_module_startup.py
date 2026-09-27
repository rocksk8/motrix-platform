# -*- coding: utf-8 -*-
"""helpers/module_startup.load_modules_like_startup（B，2026-09-28，主持派工；CORE 1.58 模組 migration 的前提）。

模組 migration 只在 loader.load_all 登記過才會被 init_db 的 core.migrations.run_all 跑到 ⇒ 乾跑 migration（apply_update）、
V9→新版轉換（upgrade.py）這種只做 init_db 的工具，要先用**與 main.py 同一段**載入模組；而停用清單要讀**被試跑的那個庫**。

① main.py 只經這支載入模組（不再自己呼叫 load_all／read_disabled_list）；反向控制：在 main 的複本多一行 load_all ⇒ 抓得到。
② 停用清單讀 db_path 那個庫、不讀 db.DB_PATH：兩個庫各停用不同模組，帶 db_path ⇒ 照它；正對照：不帶 ⇒ 照 db.DB_PATH（證明兩者分得出來）。
③ 同一次呼叫裡，停用的模組其 migration 不登記、載入的才登記（乾跑時跑到的就是正式啟動會跑的那一批）。
"""
import ast
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from core import loader, migrations, registry

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture
def iso(monkeypatch):
    """登錄表與 migration 登記都隔離；授權閘門關掉（本檔只驗停用清單的來源）。"""
    import helpers.licensing as lic
    snap = registry.snapshot()
    registry._reset()
    monkeypatch.setattr(migrations, "_REGISTRY", {})
    monkeypatch.setattr(lic, "LICENSE_GATE_ENABLED", False)
    yield
    registry.restore(snap)
    for k in [k for k in sys.modules if k.startswith("zzstart_")]:        # 合成套件不留在 sys.modules
        del sys.modules[k]


# ── ① main.py 只經這支 ────────────────────────────────────────────────────────

def startup_loader_calls(src):
    """main.py 原始碼裡三種呼叫各出現幾次（屬性呼叫與直接呼叫都算）。"""
    got = {"load_modules_like_startup": 0, "load_all": 0, "read_disabled_list": 0}
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if name in got:
                got[name] += 1
    return got


def test_main_loads_modules_only_through_the_shared_function():
    src = (BACKEND / "main.py").read_text(encoding="utf-8")
    assert startup_loader_calls(src) == {"load_modules_like_startup": 1, "load_all": 0, "read_disabled_list": 0}


def test_reverse_control_a_direct_load_all_in_main_is_caught():
    src = (BACKEND / "main.py").read_text(encoding="utf-8") + "\nmodule_loader.load_all()\n"
    assert startup_loader_calls(src)["load_all"] == 1


# ── ②③ 停用清單的來源、migration 登記 ─────────────────────────────────────────

def _db_disabling(path, keys):
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE system_settings (key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT)")
        conn.execute("INSERT INTO system_settings VALUES ('modules_disabled', ?, '2026-09-28T00:00:00')", (json.dumps(keys),))
        conn.commit()
    finally:
        conn.close()
    return str(path)


def _pkg(tmp_path, pkg_name, names):
    """合成模組樹：每個模組各帶一支 v1 migration。每題用不同的套件名（同名套件會讀到 sys.modules 裡的舊檔）。"""
    pkg = tmp_path / pkg_name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    for n in names:
        d = pkg / n
        d.mkdir()
        (d / "module.json").write_text(json.dumps({"key": n, "name": n, "version": "0.0.1", "core": ">=1.0,<2.0"}),
                                       encoding="utf-8")
        (d / "__init__.py").write_text("from core.registry import ModuleSpec\n"
                                       "def v1(conn):\n    pass\n"
                                       "MODULE = ModuleSpec(key=%r, migrations=[(1, v1)])\n" % n, encoding="utf-8")
    return pkg


def _run(db_path=None):
    from helpers import module_startup
    registry._reset()
    migrations._REGISTRY.clear()
    module_startup.load_modules_like_startup(db_path)
    return ({s["key"]: s["state"] for s in registry.module_states()}, sorted(migrations.registered()),
            registry.disabled_list().get("source"))


def test_disabled_list_comes_from_the_given_db_and_only_loaded_modules_register_migrations(tmp_path, monkeypatch, iso):
    import db
    pkg = _pkg(tmp_path, "zzstart_src", ["zz_a", "zz_b"])
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(loader, "MODULES_DIR", str(pkg))
    monkeypatch.setattr(loader, "MODULES_PACKAGE", "zzstart_src")
    (tmp_path / "main").mkdir()
    (tmp_path / "copy").mkdir()
    monkeypatch.setattr(db, "DB_PATH", _db_disabling(tmp_path / "main" / "motrix.db", ["zz_a"]))   # 「正式庫」
    copy_db = _db_disabling(tmp_path / "copy" / "motrix.db", ["zz_b"])                            # 被試跑的複本

    states, regs, source = _run(copy_db)
    assert states == {"zz_a": "loaded", "zz_b": "disabled"} and source == "db", states
    assert regs == ["zz_a"], "停用的模組不可以登記 migration；載入的要登記：%s" % regs

    states, regs, _ = _run()                                                       # 正對照：不帶 ⇒ db.DB_PATH
    assert states == {"zz_a": "disabled", "zz_b": "loaded"} and regs == ["zz_b"], (states, regs)


def test_unreadable_disabled_list_without_cache_loads_nothing(tmp_path, monkeypatch, iso):
    """P-SW-05 照舊（逐字搬家，行為不變）：讀不到停用清單、也沒有快取 ⇒ 全部暫不載入、沒有任何 migration 登記。"""
    import helpers.module_switches as ms
    pkg = _pkg(tmp_path, "zzstart_unread", ["zz_c"])
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(loader, "MODULES_DIR", str(pkg))
    monkeypatch.setattr(loader, "MODULES_PACKAGE", "zzstart_unread")
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not a sqlite database" * 64)
    monkeypatch.setattr(ms, "READ_ATTEMPTS", 1)
    monkeypatch.setattr(ms, "READ_TIMEOUT_SECONDS", 0.1)
    states, regs, source = _run(str(bad))
    assert states == {"zz_c": "disabled"} and regs == [] and source == ms.SOURCE_UNREADABLE, (states, regs, source)
