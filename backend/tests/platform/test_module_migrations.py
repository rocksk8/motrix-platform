# -*- coding: utf-8 -*-
"""模組自己的 migration（CORE-SPEC §6；2026-09-27 請款流程順勢補上，主持裁示）。

- `ModuleSpec.migrations=[(版號, 函式)]`，loader 在模組**載入時**才交給 `core.migrations.register`：
  停用／未授權 ⇒ 不登記 ⇒ 不建表不加欄。
- 版本記在 `module_schema_versions`（以模組為單位）：停用 → 再啟用，從記錄的版本往後補跑，已跑過的不重跑。
- 版號不是從 1 起連續、重複、項目形狀不對 ⇒ 那個模組載入失敗（原因進狀態表），其他模組照常。
- 凍住的歷史：`modules/*/migrations/*.py` 不准 import 會演進的程式碼（模組的 api／helpers、L1…），SQL 寫在檔裡。
"""
import ast
import re
import sqlite3
import sys
from pathlib import Path

import pytest

from core import loader, migrations, registry
from tests.platform.test_core_loader import _make_pkg

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture
def iso(monkeypatch):
    """登錄表與 migration 登記都隔離（不動到真正的產品登記）。"""
    snap = registry.snapshot()
    registry._reset()
    monkeypatch.setattr(migrations, "_REGISTRY", {})
    yield
    registry.restore(snap)


def _mod(key, migs_src):
    src = ("from core.registry import ModuleSpec\n"
           "import sqlite3\n"
           "def v1(conn):\n"
           "    conn.execute('CREATE TABLE IF NOT EXISTS hits (module TEXT, v INTEGER)')\n"
           "    conn.execute('INSERT INTO hits VALUES (?, 1)', (%r,))\n"
           "def v2(conn):\n"
           "    conn.execute('INSERT INTO hits VALUES (?, 2)', (%r,))\n"
           "MODULE = ModuleSpec(key=%r, migrations=%s)\n") % (key, key, key, migs_src)
    return ({"key": key, "core": ">=1.0,<2.0"}, src)


def _purge(pkg):
    for k in list(sys.modules):
        if k.startswith(pkg):
            del sys.modules[k]


def _db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "m.db"))
    import db
    db._ensure_module_schema_versions(conn)
    return conn


def _hits(conn):
    try:
        return sorted(conn.execute("SELECT module, v FROM hits").fetchall())
    except sqlite3.OperationalError:
        return []


def test_loaded_module_registers_and_disabled_one_does_not(tmp_path, monkeypatch, iso):
    pkg = "fake_mig_a"
    root = _make_pkg(tmp_path, pkg, {"on": _mod("on", "[(1, v1)]"), "off": _mod("off", "[(1, v1)]")})
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        loader.load_all(str(root), pkg, disabled={"off"})
        assert migrations.registered() == {"on": [1]}
        conn = _db(tmp_path)
        migrations.run_all(conn)
        assert _hits(conn) == [("on", 1)]                                  # 停用的沒建表、沒跑
        assert migrations.current_version(conn, "off") == 0
    finally:
        _purge(pkg)


def test_disable_then_enable_resumes_from_recorded_version_and_never_reruns(tmp_path, monkeypatch, iso):
    pkg = "fake_mig_b"
    conn = _db(tmp_path)
    root = _make_pkg(tmp_path, pkg, {"m": _mod("m", "[(1, v1)]")})
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        loader.load_all(str(root), pkg)                                      # ① 啟用：跑 v1
        migrations.run_all(conn)
        assert _hits(conn) == [("m", 1)] and migrations.current_version(conn, "m") == 1
        monkeypatch.setattr(migrations, "_REGISTRY", {})                     # ② 停用（重啟）：不登記，版本留著
        registry._reset()
        loader.load_all(str(root), pkg, disabled={"m"})
        assert migrations.run_all(conn) == {} and migrations.current_version(conn, "m") == 1
        monkeypatch.setattr(migrations, "_REGISTRY", {})                     # ③ 再啟用、模組升級帶 v2：只補 v2
        registry._reset()
        _purge(pkg)
        (root / "m" / "__init__.py").write_text(_mod("m", "[(1, v1), (2, v2)]")[1], encoding="utf-8")
        loader.load_all(str(root), pkg)
        assert migrations.run_all(conn) == {"m": (1, 2)}
        migrations.run_all(conn)                                             # 再跑一次：什麼都不做
        assert _hits(conn) == [("m", 1), ("m", 2)]
    finally:
        _purge(pkg)


@pytest.mark.parametrize("migs,why", [
    ("[(1, v1), (1, v2)]", "重複"),
    ("[(2, v1)]", "不從 1 起"),
    ("[(1, v1), (3, v2)]", "不連續"),
    ("[('1', v1)]", "版號不是 int"),
    ("[(True, v1)]", "bool 不算 int"),
    ("[(1, 'v1')]", "不是函式"),
    ("[1]", "不是 (版號, 函式)"),
])
def test_bad_versions_block_that_module_only(tmp_path, monkeypatch, iso, migs, why):
    pkg = "fake_mig_c_%d" % abs(hash(migs))
    root = _make_pkg(tmp_path, pkg, {"bad": _mod("bad", migs), "good": _mod("good", "[(1, v1)]")})
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        got = loader.load_all(str(root), pkg)
        assert [m.key for m in got] == ["good"], why
        assert "migrations" in registry.failed().get("bad", ""), (why, registry.failed())
        assert migrations.registered() == {"good": [1]}, why
    finally:
        _purge(pkg)


def test_case_v1_is_registered_by_the_real_loader_and_its_column_exists(client):
    """正對照：真的產品登記（main 載入的 M01）。M01 不在的安裝包 ⇒ 沒有登記、沒有這一欄（下一題的反向）。"""
    import db
    from core import source_tree
    if not source_tree.module_installed("modules/case/"):
        pytest.skip("M01 不在這個安裝包：由下一題驗「不登記、不建欄」")
    assert migrations.registered().get("case") == [1, 2, 3, 4, 5, 6]   # v2＝W1 匯款實付／手續費／差額審核欄位（2026-09-30）；v3＝費用單據通用欄位（A2，2026-10-01）；v4＝叫料審核疊加表、v5＝叫料匯款申請與付款明細（31-C，2026-10-02）；v6＝材料申請變更覆核表（33-M2a，2026-10-03）
    conn = db.get_db()
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(case_extra_expenses)")}
        assert "invoice_no" in cols and {"remit_actual", "remit_fee", "remit_review"} <= cols
        assert {"kind", "doc_code", "lines_json", "void_reason"} <= cols                      # v3
        assert migrations.current_version(conn, "case") == 6
    finally:
        conn.close()


def test_without_case_module_nothing_is_registered_and_no_column_is_added(client):
    """真刪 M01 的安裝包（或本機樹）：case 沒登記就沒有 invoice_no；有登記就一定有——兩者一致。"""
    import db
    conn = db.get_db()
    try:
        has_col = "invoice_no" in {r[1] for r in conn.execute("PRAGMA table_info(case_extra_expenses)")}
    finally:
        conn.close()
    assert has_col == ("case" in migrations.registered())


# ── 凍住的歷史：modules/*/migrations 不准 import 會演進的程式碼 ────────────────────────
#: 不准出現在 migration 檔的頂層套件（產品碼都在這些底下；標準庫照用）
FORBIDDEN_ROOTS = {"modules", "helpers", "routers", "core", "db", "main", "tools"}


def migration_import_problems(src: str) -> list:
    out = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names if a.name.split(".")[0] in FORBIDDEN_ROOTS]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                out.append("." * node.level + (node.module or ""))
            elif (node.module or "").split(".")[0] in FORBIDDEN_ROOTS:
                out.append(node.module)
        elif isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) in ("import_module", "__import__"):
            out.append("動態 import")
    return out


def _migration_files():
    return sorted(p for p in BACKEND.glob("modules/*/migrations/*.py") if p.name != "__init__.py")


def test_module_migrations_do_not_import_evolving_code():
    files = _migration_files()
    from core import source_tree
    if source_tree.module_installed("modules/case/"):
        assert any(p.name == "0001_extra_expense_invoice_no.py" for p in files), files   # 正對照：真的掃到了
    bad = {str(p.relative_to(BACKEND)): migration_import_problems(p.read_text(encoding="utf-8")) for p in files}
    bad = {k: v for k, v in bad.items() if v}
    assert not bad, "migration 不可以 import 會演進的程式碼（SQL 寫在檔裡）：%s" % bad


@pytest.mark.parametrize("src,flagged", [
    ("from modules.case.api import case_extra_expenses\n", True),
    ("import helpers\n", True),
    ("from helpers.uploads import x\n", True),
    ("from . import other\n", True),
    ("import db\n", True),
    ("import importlib\nimportlib.import_module('modules.case.recognition')\n", True),
    ("import json\nfrom datetime import datetime\n", False),
])
def test_import_guard_reverse_control(src, flagged):
    assert bool(migration_import_problems(src)) is flagged


# ── 模組 migration 不准自己 commit（稽核 D PM1）────────────────────────────────
# core.migrations.run_all 對 core 以外逐支包 SAVEPOINT：成功才由它 commit；丟例外或回原因 ⇒ ROLLBACK TO 撤回。
# migration 自己 commit（或 executescript——它會先隱含 COMMIT）⇒ savepoint 失效，做到一半的東西撤不回。

def migration_commit_problems(src: str) -> list:
    """原始碼裡會結束交易的呼叫：`.commit()`、`.executescript(`、SQL 字面值裡的 COMMIT／END TRANSACTION。"""
    out = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) in ("commit", "executescript"):
            out.append(node.func.attr + "()")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and re.search(
                r"(?i)^\s*(COMMIT|END(\s+TRANSACTION)?)\s*;?\s*$", node.value):
            out.append("SQL %r" % node.value.strip())
    return out


def test_module_migrations_do_not_commit_themselves():
    files = _migration_files()
    from core import source_tree
    if source_tree.module_installed("modules/case/"):
        assert any(p.name == "0001_extra_expense_invoice_no.py" for p in files), files   # 正對照：真的掃到了
    bad = {str(p.relative_to(BACKEND)): migration_commit_problems(p.read_text(encoding="utf-8")) for p in files}
    bad = {k: v for k, v in bad.items() if v}
    assert not bad, "模組 migration 不可以自己 commit（run_all 逐支 SAVEPOINT，commit 由它做）：%s" % bad


@pytest.mark.parametrize("src,flagged", [
    ("def up(conn):\n    conn.execute('ALTER TABLE t ADD COLUMN c TEXT')\n    conn.commit()\n", True),
    ("def up(conn):\n    conn.executescript('CREATE TABLE t (id INTEGER);')\n", True),
    ("def up(conn):\n    conn.execute('COMMIT')\n", True),
    ("def up(conn):\n    conn.execute('end transaction;')\n", True),
    ("def up(conn):\n    conn.execute('ALTER TABLE t ADD COLUMN committed_at TEXT')\n", False),
    ("def up(conn):\n    return 'x 表還沒建好'\n", False),
])
def test_commit_guard_reverse_control(src, flagged):
    assert bool(migration_commit_problems(src)) is flagged
