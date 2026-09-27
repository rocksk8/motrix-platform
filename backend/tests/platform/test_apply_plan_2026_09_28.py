# -*- coding: utf-8 -*-
"""backend/tools/apply_plan.py：日常更新（platform 安裝套 platform 包）的刪除／新增計畫（2026-09-28）。

守的事：
- 只刪「舊版包有、新版包沒有」（baseline）、lock 排除的模組與頁面、安裝目錄裡新包沒有的模組資料夾；
- 資料／DB／設定／uploads／PDF／autostart.bat 就算被寫進 baseline 也不刪（反向控制：惡意 baseline）；
- 超過上限 ⇒ 一個檔都不動；沒有 baseline ⇒ 其他候選只列出不刪；
- 回滾刪掉的是「這次新增的」且只有那些；module_update 包拒絕。
"""
import importlib.util
import json
import os
from pathlib import Path

import pytest

from core import upgrade as _upgrade

_SPEC = importlib.util.spec_from_file_location(
    "apply_plan", Path(__file__).resolve().parents[2] / "tools" / "apply_plan.py")
ap = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ap)
ap._upgrade = _upgrade          # 測試用 repo 的 core.upgrade（正式機用新包裡那一份）

DATA_FILES = [
    "backend/motrix_erp.db", "backend/motrix_erp_demo.db", "backend/export_archive/2026/x.pdf",
    "backend/_demo_pdf_archive/d.pdf", "backend/heartbeat_config.json", "backend/autostart.bat",
    "uploads/u.jpg", "報價單PDF/q.pdf", "backend/db_backups/2026-09-27/motrix_erp.db",
]


def _w(root, rel, text="x"):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _lock(kind="full_package", excluded=("b",), removed_pages=("frontend/pages/b.html",)):
    return json.dumps({"lock_version": 1, "kind": kind, "product": "t", "modules": {"a": {}},
                       "excluded": list(excluded), "removed_pages": list(removed_pages)})


@pytest.fixture
def env(tmp_path):
    pkg, root = tmp_path / "pkg", tmp_path / "root"
    for rel in ("backend/main.py", "backend/modules/a/module.json", "backend/modules/a/x.py",
                "frontend/pages/keep.html", "frontend/pages/new-name.html", "tools/platform/upgrade.py",
                "product/full.json", "backend/brand_new.py"):
        _w(pkg, rel, "new")
    _w(pkg, "backend/autostart.bat", "package default")
    _w(pkg, "backend/modules.lock.json", _lock())
    _w(pkg, "deploy_manifest.json", json.dumps({"commit": "c2"}))
    for rel in ("backend/main.py", "backend/old.py", "backend/modules/a/module.json", "backend/modules/a/x.py",
                "backend/modules/b/module.json", "backend/modules/b/y.py", "backend/modules/c/module.json",
                "frontend/pages/keep.html", "frontend/pages/old-name.html", "frontend/pages/b.html",
                "tools/platform/upgrade.py", "tools/platform/old_tool.py", "backend/modules.lock.json"):
        _w(root, rel, "old")
    _w(root, "backend/modules/b/__pycache__/y.cpython-312.pyc")
    _w(root, "backend/modules/c/__pycache__/z.cpython-312.pyc")
    _w(root, "backend/modules/b/notes.db")                 # 模組資料夾裡的資料檔：不刪
    for rel in DATA_FILES:
        _w(root, rel, "data")
    baseline = ["backend/main.py", "backend/old.py", "frontend/pages/old-name.html",
                "tools/platform/old_tool.py"] + DATA_FILES     # 惡意／錯誤 baseline：列了資料檔
    _w(root, ap.BASELINE_REL, json.dumps({"commit": "c1", "files": baseline}))
    return str(root), str(pkg)


EXPECTED_DELETE = {
    "backend/old.py": "baseline", "frontend/pages/old-name.html": "baseline",
    "tools/platform/old_tool.py": "baseline",
    "backend/modules/b/module.json": "lock_excluded", "backend/modules/b/y.py": "lock_excluded",
    "backend/modules/c/module.json": "orphan_module", "frontend/pages/b.html": "lock_removed_page",
}


def test_plan_and_execute_delete_exactly_the_old_program_files(env):
    root, pkg = env
    plan = ap.make_plan(root, pkg, 200)
    assert {d["rel"]: d["reason"] for d in plan["delete"]} == EXPECTED_DELETE
    assert "backend/modules/b/notes.db" in plan["kept_non_program"]
    assert set(plan["added"]) == {"frontend/pages/new-name.html", "product/full.json", "backend/brand_new.py"}
    assert "backend/autostart.bat" not in plan["package_files"]
    removed, errors = ap.execute(root, pkg, plan)
    assert not errors and set(removed) == set(EXPECTED_DELETE)
    for rel in DATA_FILES + ["backend/modules/b/notes.db", "backend/main.py", "frontend/pages/keep.html"]:
        assert os.path.isfile(os.path.join(root, rel)), rel
    assert not os.path.exists(os.path.join(root, "backend/modules/c"))            # 只剩 __pycache__ ⇒ 整個移除
    assert not os.path.exists(os.path.join(root, "backend/modules/b/__pycache__"))
    assert not os.path.isfile(os.path.join(root, "backend/modules/b/module.json"))  # 載入器不會再載 b


def test_data_config_and_state_paths_are_never_deletable():
    # 正對照：程式檔可刪；反向：資料／DB／設定／工具狀態檔不可刪
    assert ap.deletable("backend/modules/x/y.py", _upgrade)
    assert ap.deletable("tools/platform/upgrade.py", _upgrade)
    for rel in DATA_FILES + [ap.BASELINE_REL, "backend/.deployed_commit.json", "backend/certs/key.pem",
                             "backend/license.key", "docs/x.md", "backend/../x.py"]:
        assert not ap.deletable(rel, _upgrade), rel


def test_over_limit_touches_nothing(env, tmp_path):
    root, pkg = env
    out = tmp_path / "plan.json"
    rc = ap.main(["plan", "--root", root, "--pkg", pkg, "--out", str(out), "--max", "3"])
    assert rc == 3
    assert json.loads(out.read_text(encoding="utf-8"))["over_limit"] is True
    for rel in EXPECTED_DELETE:
        assert os.path.isfile(os.path.join(root, rel)), rel


def test_without_baseline_only_lock_and_module_folders_are_deleted(env):
    root, pkg = env
    os.remove(os.path.join(root, ap.BASELINE_REL))
    plan = ap.make_plan(root, pkg, 200)
    assert plan["baseline_present"] is False
    got = {d["rel"] for d in plan["delete"]}
    assert got == {r for r, why in EXPECTED_DELETE.items() if why != "baseline"}
    assert {"backend/old.py", "frontend/pages/old-name.html", "tools/platform/old_tool.py"} <= set(
        plan["no_baseline_candidates"])
    assert not set(DATA_FILES) & set(plan["no_baseline_candidates"])


def test_cleanup_added_removes_only_what_this_apply_added(env):
    root, pkg = env
    plan = ap.make_plan(root, pkg, 200)
    for rel in plan["package_files"]:                 # 模擬 robocopy 套用
        _w(root, rel, "new")
    _w(root, "backend/__pycache__/brand_new.cpython-312.pyc")
    removed, errors = ap.cleanup_added(root, pkg, plan)
    assert not errors and set(removed) == set(plan["added"])
    assert os.path.isfile(os.path.join(root, "backend/main.py"))
    assert not os.path.exists(os.path.join(root, "product/full.json"))
    assert not os.path.exists(os.path.join(root, "backend/brand_new.py"))
    for rel in DATA_FILES:
        assert os.path.isfile(os.path.join(root, rel)), rel


def test_module_update_package_is_refused(env):
    root, pkg = env
    _w(pkg, "backend/modules.lock.json", _lock(kind="module_update"))
    with pytest.raises(ap.Refuse):
        ap.make_plan(root, pkg, 200)


def test_bad_lock_entries_are_refused(env):
    root, pkg = env
    _w(pkg, "backend/modules.lock.json", _lock(excluded=("../../x",)))
    with pytest.raises(ap.Refuse):
        ap.make_plan(root, pkg, 200)
    _w(pkg, "backend/modules.lock.json", _lock(excluded=(), removed_pages=("backend/db.py",)))
    with pytest.raises(ap.Refuse):
        ap.make_plan(root, pkg, 200)


def test_verify_snapshot_reports_files_the_snapshot_cannot_restore(env, tmp_path):
    root, pkg = env
    plan = ap.make_plan(root, pkg, 200)
    snap = tmp_path / "snap"
    for d in plan["delete"][1:]:
        _w(snap, d["rel"])
    assert ap.verify_snapshot(plan, str(snap)) == [plan["delete"][0]["rel"]]
    _w(snap, plan["delete"][0]["rel"])
    assert ap.verify_snapshot(plan, str(snap)) == []


def test_baseline_written_is_the_package_file_list(env):
    root, pkg = env
    plan = ap.make_plan(root, pkg, 200)
    ap.write_baseline(root, plan)
    data = json.loads(Path(root, ap.BASELINE_REL).read_text(encoding="utf-8"))
    assert data["commit"] == "c2" and data["files"] == plan["package_files"]


# ── 轉換寫 baseline（2026-09-28）：V9→新版轉換後的第一次日常更新就有刪除依據 ──

def _load_platform_upgrade():
    spec = importlib.util.spec_from_file_location(
        "platform_upgrade_tool", Path(__file__).resolve().parents[3] / "tools" / "platform" / "upgrade.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_convert_writes_the_apply_baseline_from_the_new_source(env, tmp_path):
    _root, pkg = env
    fresh = tmp_path / "converted"
    (fresh / "backend").mkdir(parents=True)
    rel = _load_platform_upgrade().write_apply_baseline(str(fresh), pkg)
    assert rel == ap.BASELINE_REL
    data = json.loads((fresh / rel).read_text(encoding="utf-8"))
    assert data["commit"] == "c2"
    assert data["files"] == ap.package_files(pkg, _upgrade)
    assert "backend/autostart.bat" not in data["files"]          # 設定預設檔不進清單（不會被當舊程式刪）
    assert "backend/modules/a/x.py" in data["files"]             # 正對照：程式檔在


# ── apply_update.ps1 與 rollback_update.ps1 的停服／啟動函式必須逐字相同 ──
# 兩支各留一份（rollback 那支不能依賴共用檔，理由見 rollback_update.ps1 的註解）；
# 先前 Test-Ping 就是兩份各自維護而漂移（2026-09-08）。

_TOOLS = Path(__file__).resolve().parents[2] / "tools"
_SYNCED_FUNCS = ("Invoke-Py", "Stop-InstallService", "Start-InstallService")


def _ps_function(text, name):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("function %s" % name):
            for j in range(i + 1, len(lines)):
                if lines[j] == "}":
                    return "\n".join(lines[i:j + 1])
    return None


@pytest.mark.parametrize("name", _SYNCED_FUNCS)
def test_rollback_script_carries_the_same_service_functions(name):
    a = (_TOOLS / "apply_update.ps1").read_text(encoding="utf-8-sig")
    r = (_TOOLS / "rollback_update.ps1").read_text(encoding="utf-8-sig")
    fa, fr = _ps_function(a, name), _ps_function(r, name)
    assert fa is not None and fr is not None, "%s 在其中一支找不到（改名要兩邊一起改）" % name
    assert fa == fr, "%s：apply_update.ps1 與 rollback_update.ps1 不同步" % name


def test_rc_function_extractor_sees_a_one_character_drift():
    a = (_TOOLS / "apply_update.ps1").read_text(encoding="utf-8-sig")
    fa = _ps_function(a, "Stop-InstallService")
    drifted = a.replace("$hops -lt 6", "$hops -lt 7", 1)
    assert fa and _ps_function(drifted, "Stop-InstallService") != fa


# ── 乾跑／轉換照啟動規則跑 migration（migrate_like_startup，2026-09-28）──
# ⚠ 模組路徑（有 helpers/module_startup.py、模組 migration 未完成 ⇒ 失敗）的整合題
#   等 B41（ModuleSpec.migrations＋module_startup）合回時在同一班補上：RUN-PLAN 月台列的合回條件。

_MLS_SPEC = importlib.util.spec_from_file_location(
    "migrate_like_startup", Path(__file__).resolve().parents[2] / "tools" / "migrate_like_startup.py")
mls = importlib.util.module_from_spec(_MLS_SPEC)
_MLS_SPEC.loader.exec_module(mls)


def test_mls_detects_module_startup_by_file(tmp_path):
    assert not mls.has_module_startup(str(tmp_path))
    _w(tmp_path, "helpers/module_startup.py", "")
    assert mls.has_module_startup(str(tmp_path))


def test_dry_run_and_convert_both_go_through_migrate_like_startup():
    ps1 = (_TOOLS / "apply_update.ps1").read_text(encoding="utf-8-sig")
    assert r'backend\tools\migrate_like_startup.py' in ps1
    assert "--license" in ps1
    up = (Path(__file__).resolve().parents[3] / "tools" / "platform" / "upgrade.py").read_text(encoding="utf-8")
    body = up.split("def run_migrations", 1)[1].split("\ndef ", 1)[0]
    assert "migrate_like_startup.py" in body and "MIGRATE_OK" in body
    # 反向控制：成功字樣只在工具 exit 0 時印（不可以無條件印）
    assert "if e.code == 0" in body and "if e.code == 0" in ps1


def test_mls_without_module_startup_is_plain_init_db(tmp_path):
    if mls.has_module_startup():
        pytest.fail("這棵樹已有 helpers/module_startup.py：本題要換成模組路徑的整合題（見上方註解）")
    p = str(tmp_path / "x.db")
    assert mls.run([p]) == []
    import sqlite3
    with sqlite3.connect(p) as c:
        assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0] > 10
