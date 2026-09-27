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
    monkeypatch.setattr(migrations, "_INCOMPLETE", {})
    from helpers import module_startup as _ms
    monkeypatch.setattr(_ms, "_DEMO_ABSENT", {})
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


# ── ④ migration 沒完成的模組：init_db 之後改記 failed、不掛路由（稽核 A AB-S3）──────────────────

def test_main_fails_incomplete_modules_after_init_db_and_before_mounting():
    src = (BACKEND / "main.py").read_text(encoding="utf-8")
    lines = {}
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if name in ("init_db", "fail_incomplete_modules", "mount_modules"):
                lines.setdefault(name, []).append(node.lineno)
    assert len(lines.get("fail_incomplete_modules", [])) == 1, lines
    assert max(lines["init_db"]) < lines["fail_incomplete_modules"][0] < min(lines["mount_modules"]), lines
    call = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
                and getattr(n.func, "attr", None) == "fail_incomplete_modules")
    assert len(call.args) == 2, "主庫、demo 庫分開傳（AB-S7：主庫決定上下線）：%s" % ast.unparse(call)


def test_main_answers_demo_requests_for_demo_absent_modules_after_the_session_check():
    """AB-S7：auth middleware 在 session 驗過之後（沒登入的照舊 401）、call_next 之前，demo token 才問 demo_absent_reason。"""
    src = (BACKEND / "main.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "auth_middleware")
    body = ast.unparse(fn)
    assert "demo_absent_reason(path)" in body and "DEMO_TOKEN_PREFIX" in body
    assert body.index("FROM sessions s JOIN users u") < body.index("demo_absent_reason(path)") < body.index("call_next(request)\n    _record_request_trail")


_V1_NEEDS_READY = ("from core.registry import ModuleSpec\n"
                   "def v1(conn):\n"
                   "    if %s and not conn.execute(\"SELECT 1 FROM sqlite_master WHERE name='zz_ready'\").fetchone():\n"
                   "        return 'zz 表還沒建好'\n"
                   "MODULE = ModuleSpec(key=%r, migrations=[(1, v1)])\n")


def _inc_setup(tmp_path, monkeypatch, main_ready, demo_ready):
    """zz_ok（migration 永遠完成）＋zz_wait（庫裡沒有 zz_ready 表就回原因）；主庫、demo 庫各跑一次 run_all。"""
    import db
    from helpers import module_startup
    pkg = tmp_path / "zzstart_inc"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    for n, gate in (("zz_ok", "False"), ("zz_wait", "True")):
        d = pkg / n
        d.mkdir()
        (d / "module.json").write_text(json.dumps({"key": n, "name": n, "version": "0.0.1", "core": ">=1.0,<2.0",
                                                   "provides": {"api_prefixes": ["/api/" + n.replace("_", "-")]}}),
                                       encoding="utf-8")
        (d / "__init__.py").write_text(_V1_NEEDS_READY % (gate, n), encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(loader, "MODULES_DIR", str(pkg))
    monkeypatch.setattr(loader, "MODULES_PACKAGE", "zzstart_inc")
    paths = {}
    for name, ready in (("main", main_ready), ("demo", demo_ready)):
        paths[name] = _db_disabling(tmp_path / (name + ".db"), [])
        conn = sqlite3.connect(paths[name])
        try:
            db._ensure_module_schema_versions(conn)
            if ready:
                conn.execute("CREATE TABLE zz_ready (id INTEGER)")
                conn.commit()
        finally:
            conn.close()
    registry._reset()
    module_startup.load_modules_like_startup(paths["main"])
    for name in ("main", "demo"):
        conn = sqlite3.connect(paths[name])
        try:
            migrations.run_all(conn)
        finally:
            conn.close()
    return module_startup, paths


def _loaded_keys():
    return [m.key for m in registry.loaded()]


def test_main_db_incomplete_takes_the_module_offline_with_the_migration_reason(tmp_path, monkeypatch, iso):
    ms, paths = _inc_setup(tmp_path, monkeypatch, main_ready=False, demo_ready=True)
    out = ms.fail_incomplete_modules(paths["main"], paths["demo"])
    assert list(out["offline"]) == ["zz_wait"] and "zz 表還沒建好" in out["offline"]["zz_wait"] and out["demo_absent"] == {}
    assert _loaded_keys() == ["zz_ok"], "主庫未完成的模組要移出已載入清單（路由不掛、提供者不在）"
    st = {s["key"]: s for s in registry.module_states()}
    assert st["zz_wait"]["state"] == "failed" and "zz 表還沒建好" in st["zz_wait"]["reason"]
    assert st["zz_ok"]["state"] == "loaded"


def test_only_demo_db_incomplete_keeps_the_module_online_and_says_so_in_demo_mode(tmp_path, monkeypatch, iso):
    """AB-S7：主庫完成、demo 未完成 ⇒ 不下線（正式使用者照常）；demo 模式打到它的 API 前綴 ⇒ 原因；別的前綴、相近的字 ⇒ None。"""
    ms, paths = _inc_setup(tmp_path, monkeypatch, main_ready=True, demo_ready=False)
    out = ms.fail_incomplete_modules(paths["main"], paths["demo"])
    assert out["offline"] == {} and list(out["demo_absent"]) == ["zz_wait"], out
    assert _loaded_keys() == ["zz_ok", "zz_wait"]
    why = ms.demo_absent_reason("/api/zz-wait/items")
    assert why and "示範" in why and "zz 表還沒建好" in why
    assert ms.demo_absent_reason("/api/zz-wait") == why
    assert ms.demo_absent_reason("/api/zz-ok/items") is None
    assert ms.demo_absent_reason("/api/zz-waitlist") is None


def test_both_incomplete_goes_offline_and_nothing_is_left_for_demo(tmp_path, monkeypatch, iso):
    ms, paths = _inc_setup(tmp_path, monkeypatch, main_ready=False, demo_ready=False)
    out = ms.fail_incomplete_modules(paths["main"], paths["demo"])
    assert list(out["offline"]) == ["zz_wait"] and out["demo_absent"] == {}
    assert _loaded_keys() == ["zz_ok"] and ms.demo_absent_reason("/api/zz-wait/items") is None


def test_reverse_control_both_complete_changes_nothing(tmp_path, monkeypatch, iso):
    ms, paths = _inc_setup(tmp_path, monkeypatch, main_ready=True, demo_ready=True)
    out = ms.fail_incomplete_modules(paths["main"], paths["demo"])
    assert out == {"offline": {}, "demo_absent": {}}
    assert _loaded_keys() == ["zz_ok", "zz_wait"] and ms.demo_absent_reason("/api/zz-wait/items") is None
    out = ms.fail_incomplete_modules(paths["main"])                 # 沒給 demo 庫 ⇒ 不談 demo
    assert out == {"offline": {}, "demo_absent": {}}


def test_main_db_without_any_record_fails_closed(tmp_path, monkeypatch, iso):
    """稽核 D PO1：主庫查不到 run_all 的紀錄（路徑對不上、或沒跑）⇒ 不知道升級有沒有完成 ⇒ 所有已載入模組下線（fail-closed）。
    〔更正（B，2026-09-28）：原本這一格是「沒跑過的庫不算」＝ fail-open，與乾跑工具「None＝失敗」方向相反〕"""
    ms, paths = _inc_setup(tmp_path, monkeypatch, main_ready=True, demo_ready=True)
    out = ms.fail_incomplete_modules(str(tmp_path / "never.db"), paths["demo"])
    assert sorted(out["offline"]) == ["zz_ok", "zz_wait"] and "查不到升級紀錄" in out["offline"]["zz_ok"], out
    assert _loaded_keys() == []


def test_demo_db_without_any_record_makes_every_module_absent_in_demo_only(tmp_path, monkeypatch, iso):
    ms, paths = _inc_setup(tmp_path, monkeypatch, main_ready=True, demo_ready=True)
    out = ms.fail_incomplete_modules(paths["main"], str(tmp_path / "never.db"))
    assert out["offline"] == {} and sorted(out["demo_absent"]) == ["zz_ok", "zz_wait"], out
    assert _loaded_keys() == ["zz_ok", "zz_wait"], "demo 庫查不到紀錄不可以讓正式使用者的模組下線"
    assert ms.demo_absent_reason("/api/zz-ok/items") and ms.demo_absent_reason("/api/zz-wait")


# ── 稽核 D PS1：main.py 的 demo 缺席接線（middleware 真的呼叫 demo_absent_reason 並回 404）───────────
# 不依賴任何 L2 模組：造一個假的已載入模組，把 L1 端點 /api/auth/me 當成它的前綴。

def _login_headers(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _demo_headers(client):
    import db
    from helpers.auth import _hash_pw
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET password_hash=? WHERE username='demo'", (_hash_pw("Demo-Pass-123"),))
        conn.commit()
    finally:
        conn.close()
    return _login_headers(client, "demo", "Demo-Pass-123")


def test_middleware_answers_demo_requests_for_a_demo_absent_module(client, make_user, monkeypatch):
    from helpers import module_startup as ms
    fake = registry.LoadedModule(key="zzdemo", manifest={"provides": {"api_prefixes": ["/api/auth/me"]}},
                                 spec=registry.ModuleSpec(key="zzdemo"))
    real_loaded = registry.loaded
    monkeypatch.setattr(registry, "loaded", lambda: real_loaded() + [fake])
    why = "示範資料的資料庫升級未完成（zzdemo v1），示範模式暫不提供這個模組：測試"
    monkeypatch.setattr(ms, "_DEMO_ABSENT", {"zzdemo": why})
    real = _login_headers(client, *make_user(username="ps1_real", role="admin"))
    assert client.get("/api/auth/me", headers=real).status_code == 200            # 正式 token 照常
    demo = _demo_headers(client)
    r = client.get("/api/auth/me", headers=demo)
    assert r.status_code == 404 and r.json()["detail"] == why, r.text
    monkeypatch.setattr(ms, "_DEMO_ABSENT", {})                                    # 反向控制：表清空 ⇒ demo 照常
    assert client.get("/api/auth/me", headers=demo).status_code == 200

