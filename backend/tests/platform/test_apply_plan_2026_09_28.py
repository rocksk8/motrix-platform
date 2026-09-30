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
import re
from pathlib import Path

import pytest

from core import upgrade as _upgrade

_SPEC = importlib.util.spec_from_file_location(
    "apply_plan", Path(__file__).resolve().parents[2] / "tools" / "apply_plan.py")
ap = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ap)
ap._upgrade = _upgrade          # 測試用 repo 的 core.upgrade（正式機用新包裡那一份）
PG = ap.PAGES_REL               # 安裝包裡的頁面目錄（相對路徑；不寫死，test_page_paths_centralized）

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


def _lock(kind="full_package", excluded=("b",), removed_pages=(PG + "/b.html",)):
    return json.dumps({"lock_version": 1, "kind": kind, "product": "t", "modules": {"a": {}},
                       "excluded": list(excluded), "removed_pages": list(removed_pages)})


@pytest.fixture
def env(tmp_path):
    pkg, root = tmp_path / "pkg", tmp_path / "root"
    for rel in ("backend/main.py", "backend/modules/a/module.json", "backend/modules/a/x.py",
                PG + "/keep.html", PG + "/new-name.html", "tools/platform/upgrade.py",
                "product/full.json", "backend/brand_new.py"):
        _w(pkg, rel, "new")
    _w(pkg, "backend/autostart.bat", "package default")
    _w(pkg, "backend/modules.lock.json", _lock())
    _w(pkg, "deploy_manifest.json", json.dumps({"commit": "c2"}))
    for rel in ("backend/main.py", "backend/old.py", "backend/modules/a/module.json", "backend/modules/a/x.py",
                "backend/modules/b/module.json", "backend/modules/b/y.py", "backend/modules/c/module.json",
                PG + "/keep.html", PG + "/old-name.html", PG + "/b.html",
                "tools/platform/upgrade.py", "tools/platform/old_tool.py", "backend/modules.lock.json"):
        _w(root, rel, "old")
    _w(root, "backend/modules/b/__pycache__/y.cpython-312.pyc")
    _w(root, "backend/modules/c/__pycache__/z.cpython-312.pyc")
    _w(root, "backend/modules/b/notes.db")                 # 模組資料夾裡的資料檔：不刪
    for rel in DATA_FILES:
        _w(root, rel, "data")
    baseline = ["backend/main.py", "backend/old.py", PG + "/old-name.html",
                "tools/platform/old_tool.py"] + DATA_FILES     # 惡意／錯誤 baseline：列了資料檔
    _w(root, ap.BASELINE_REL, json.dumps({"commit": "c1", "files": baseline}))
    # b（lock 排除）、c（孤兒）預設都當成「未授權」⇒ 只停用不刪（使用者裁示 DO3）；要驗授權有的情況，題目自己換
    ap._license_check = lambda manifest: (False, "未授權（測試）")
    yield str(root), str(pkg)
    ap._license_check = None


EXPECTED_DELETE = {
    "backend/old.py": "baseline", PG + "/old-name.html": "baseline",
    "tools/platform/old_tool.py": "baseline",
    PG + "/b.html": "lock_removed_page",
    # 2026-09-28 使用者裁示（DO3）：模組資料夾 b、c 不刪——未授權只停用；授權有而包沒有 ⇒ 拒絕套用
}


def test_plan_and_execute_delete_exactly_the_old_program_files(env):
    root, pkg = env
    plan = ap.make_plan(root, pkg, 200)
    assert {d["rel"]: d["reason"] for d in plan["delete"]} == EXPECTED_DELETE
    assert set(plan["added"]) == {PG + "/new-name.html", "product/full.json", "backend/brand_new.py"}
    assert "backend/autostart.bat" not in plan["package_files"]
    removed, errors = ap.execute(root, pkg, plan)
    assert not errors and set(removed) == set(EXPECTED_DELETE)
    for rel in DATA_FILES + ["backend/modules/b/notes.db", "backend/main.py", PG + "/keep.html"]:
        assert os.path.isfile(os.path.join(root, rel)), rel
    assert plan["module_dirs"] == [] and {m["key"] for m in plan["kept_modules"]} == {"b", "c"}
    for rel in ("backend/modules/b/module.json", "backend/modules/b/y.py", "backend/modules/c/module.json"):
        assert os.path.isfile(os.path.join(root, rel)), rel                   # 未授權：只停用不刪


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
    assert {"backend/old.py", PG + "/old-name.html", "tools/platform/old_tool.py"} <= set(
        plan["no_baseline_candidates"])
    assert not set(DATA_FILES) & set(plan["no_baseline_candidates"])
    assert not [r for r in plan["no_baseline_candidates"] if r.startswith(("backend/modules/b/", "backend/modules/c/"))]


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
_SYNCED_FUNCS = ("Invoke-Py", "Stop-InstallService", "Start-InstallService",
                 "Enter-InstallLock", "Exit-InstallLock", "Write-ResultFile")


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
# 模組路徑（有 helpers/module_startup.py、模組 migration 未完成 ⇒ 失敗）的整合題在
#   test_migrate_like_startup_modular_2026_09_28.py（B41 與本包同班合回，第十四班）。

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
    import re
    code = "\n".join(l for l in ps1.splitlines() if not l.lstrip().startswith("#"))   # 註解同一串字不算
    assert re.search(r'^\s*\$dryRunTool\s*=\s*Join-Path\s+\$PackagePath\s+"backend\\tools\\migrate_like_startup\.py"',
                     code, re.M), "乾跑沒有指到新包裡的 migrate_like_startup.py"
    assert re.search(r'^\s*if\s*\(Test-Path\s+\$dryRunTool\)', code, re.M)
    assert "'--license'" in code
    up = (Path(__file__).resolve().parents[3] / "tools" / "platform" / "upgrade.py").read_text(encoding="utf-8")
    body = up.split("def run_migrations", 1)[1].split("\ndef ", 1)[0]
    body = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
    assert 'os.path.join(backend, "tools", "migrate_like_startup.py")' in body and "MIGRATE_OK" in body
    # 成功字樣只在工具 exit 0 時印（不可以無條件印）
    assert "if e.code == 0" in body and "if e.code == 0" in code


def test_mls_without_module_startup_is_plain_init_db(tmp_path, monkeypatch):
    # 第十四班起樹上有 helpers/module_startup.py（B41）⇒ 原本的絆線（pytest.fail）拿掉；
    # 以替身模擬「舊包沒有 module_startup」保留「舊包只跑真的 init_db」這條覆蓋，模組路徑由 modular 題檔負責。
    monkeypatch.setattr(mls, "has_module_startup", lambda backend=None: False)
    p = str(tmp_path / "x.db")
    assert mls.run([p]) == []
    import sqlite3
    with sqlite3.connect(p) as c:
        assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0] > 10


def test_pages_rel_matches_the_real_install_layout():
    """D5-S1：本檔題目全用 PG＝ap.PAGES_REL ⇒ 常數被改錯（例 "frontend/page"）題目照樣綠，而正式機的 removed_pages
    會全被拒、DO3 protected_pages 對不到真實路徑。期望值取自獨立來源 core.paths（不用字面、不用被測物）。"""
    import os
    from core import paths
    assert ap.PAGES_REL == os.path.relpath(paths.FRONTEND_PAGES_DIR, paths.INSTALL_ROOT).replace("\\", "/")


def test_ahm1_case_only_rename_is_not_deleted(env):
    """AH-M1：baseline 有 Foo.html、新包改名 foo.html ⇒ Windows 上是同一個檔，不可以列刪除（否則刪掉剛寫入的新檔）。"""
    root, pkg = env
    _w(pkg, PG + "/foo-case.html", "new")
    _w(root, PG + "/Foo-Case.html", "old")
    _w(root, PG + "/gone-too.html", "old")
    base = json.loads(Path(root, ap.BASELINE_REL).read_text(encoding="utf-8"))
    base["files"] += [PG + "/Foo-Case.html", PG + "/gone-too.html"]
    Path(root, ap.BASELINE_REL).write_text(json.dumps(base), encoding="utf-8")
    plan = ap.make_plan(root, pkg, 200)
    deleted = {d["rel"] for d in plan["delete"]}
    assert PG + "/Foo-Case.html" not in deleted
    assert PG + "/gone-too.html" in deleted          # 反向控制：真的沒了的照刪
    plan["delete"].append({"rel": PG + "/FOO-CASE.html", "reason": "baseline"})   # 計畫被塞了也不刪
    ap.execute(root, pkg, plan)
    assert Path(root, PG + "/foo-case.html").exists() or Path(root, PG + "/Foo-Case.html").exists()
    assert not Path(root, PG + "/gone-too.html").exists()


def _ps_code(name):
    src = (_TOOLS / name).read_text(encoding="utf-8-sig")
    return "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))


def test_ahm2_script_refuses_when_not_the_package_copy_before_touching_anything():
    """AH-M2：跑到的腳本與包裡那份版本不同 ⇒ 在任何備份／停服之前就拒絕。"""
    code = _ps_code("apply_update.ps1")
    import re
    m = re.search(r'^\$ApplyScriptVersion = "([^"]+)"', code, re.M)
    assert m, "腳本沒有 $ApplyScriptVersion"
    check = code.index('Fail $verMsg "script_not_from_package"')
    assert check < code.index("[1/6]"), "版本比對要在套用前檢查（[1/6]）之前"
    assert re.search(r'if \(\$pkgVer -ne \$ApplyScriptVersion\)', code)


def test_ahm3_after_stop_failures_restart_the_service_first():
    """AH-M3／AH-S7：停服之後的 4 個失敗出口都經 Fail-AfterStop。
    複製失敗：先寫回快照（失敗就不啟動、直接 Fail）→ 啟動 → Fail；刪除失敗：先啟動 → Fail。"""
    code = _ps_code("apply_update.ps1")
    fn = _ps_function(code, "Fail-AfterStop")
    assert fn
    copy_branch, rest = fn.split('if ($status -like "copy_failed*") {', 1)[1].split("\n    }\n", 1)
    r, st, fail_restore, last_fail = (copy_branch.index("Restore-ProgramAfterCopyFailure"),
                                      copy_branch.index("Start-InstallService"),
                                      copy_branch.index("Fail ("), copy_branch.rindex("Fail ("))
    assert r < fail_restore < st < last_fail, "複製失敗：寫回快照 → （失敗就 Fail、不啟動）→ 啟動 → Fail"
    assert rest.index("Start-InstallService") < rest.index("Fail ("), "刪除失敗：先啟動再 Fail"
    restore = _ps_function(code, "Restore-ProgramAfterCopyFailure")
    assert restore and restore.index('$script:ProdState = "restoring"') < restore.index('"cleanup-snapshot"') \
        < restore.index("robocopy"), "restoring 要在任何寫回之前設；先刪快照沒有的檔再寫回快照"
    assert code.index("function Restore-ProgramAfterCopyFailure") < code.index('"copy_failed_backend"'), \
        "函式要在第一個呼叫點之前定義（PowerShell 執行到才認得）"
    for status in ("copy_failed_backend", "copy_failed_frontend", "copy_failed_root_dirs", "delete_failed"):
        lines = [l for l in code.splitlines() if '"%s"' % status in l]
        assert len(lines) == 1 and "Fail-AfterStop" in lines[0], (status, lines)


def _ps1_digest(raw: bytes) -> str:
    import hashlib
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def test_aho7_script_change_requires_a_version_decision():
    """AH-O7：改了 apply_update.ps1 卻沒更新 apply_update.version.json ⇒ 紅（逼人決定要不要升 $ApplyScriptVersion）。"""
    import re
    reg = json.loads((_TOOLS / "apply_update.version.json").read_text(encoding="utf-8"))
    raw = (_TOOLS / "apply_update.ps1").read_bytes()
    code = raw.decode("utf-8-sig")
    m = re.search(r'^\$ApplyScriptVersion = "([^"]+)"', code, re.M)
    assert m and m.group(1) == reg["version"], "登記的版本與腳本裡的 $ApplyScriptVersion 不同"
    assert _ps1_digest(raw) == reg["sha256"], (
        "apply_update.ps1 內容變了：行為有變 ⇒ 升 $ApplyScriptVersion；只改註解 ⇒ 版本不動。"
        "兩種都要把 apply_update.version.json 的 sha256 更新成 %s" % _ps1_digest(raw))
    # 反向控制：換行與 BOM 不影響（git 在 Windows 取出成 CRLF 也一樣），內容差一個字就不同
    assert _ps1_digest(b"\xef\xbb\xbfa\r\nb") == _ps1_digest(b"a\nb") != _ps1_digest(b"a\nc")


@pytest.mark.parametrize("name", ("apply_update.ps1", "rollback_update.ps1"))
def test_every_robocopy_has_a_retry_limit(name):
    """robocopy 預設 /R:1000000 /W:30：被占用的檔會讓套用／回滾卡住數天而不是失敗（AH-S7 的出口走不到）。"""
    import re
    code = _ps_code(name)
    calls = [l for l in code.splitlines() if re.search(r"(^|[=\s])robocopy\s", l)]
    assert len(calls) >= 3, "robocopy 一行都沒抓到 ⇒ 量法壞了"
    bad = [l.strip() for l in calls if not (re.search(r"/R:\d+\b", l) and re.search(r"/W:\d+\b", l))]
    assert not bad, bad



# ── UPDATE-DELIVERY §9.2 (e)：鎖與結果檔——在真的 PowerShell 裡跑那三個函式 ──

def _run_ps(tmp_path, body):
    import subprocess
    a = (_TOOLS / "apply_update.ps1").read_text(encoding="utf-8-sig")
    funcs = "\n\n".join(_ps_function(a, n) for n in ("Enter-InstallLock", "Exit-InstallLock", "Write-ResultFile", "Emit-Result"))
    backend = tmp_path / "backend"
    backend.mkdir(exist_ok=True)
    script = ("$ErrorActionPreference = 'Stop'\n"
              "function Warn($m) { Write-Host \"[WARN] $m\" }\n"
              "$BackendDir = '%s'\n" % str(backend)
              + "$script:LockHeld = $false\n$script:RunStamp = '20260928_000000'\n$script:StartedAt = 's'\n"
              "$script:ResultScript = 'apply_update'\n$script:ResultScriptVersion = 'v'\n$script:ResultPackage = 'P'\n"
              "$script:ResultCommit = 'c'\n$script:ProdState = 'not_applied'\n$script:ServiceState = 'unknown'\n"
              + funcs + "\n" + body)
    ps = tmp_path / "t.ps1"
    ps.write_text(script, encoding="utf-8-sig")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    return r, backend


def test_lock_second_holder_gets_locked_and_release_on_emit(tmp_path):
    r, backend = _run_ps(tmp_path, (
        "$a = Enter-InstallLock 'apply_update' 'P'\n"
        "Write-Host \"first=[$a] held=$script:LockHeld exists=$(Test-Path (Join-Path $BackendDir '.apply.lock'))\"\n"
        "$script:LockHeld = $false\n"                            # 模擬第二個執行：沒有鎖
        "$b = Enter-InstallLock 'rollback_update' 'S'\n"
        "Write-Host \"second=[$b]\"\n"
        "Exit-InstallLock\n"                                       # 沒拿到鎖的那一次不可以刪別人的鎖
        "Write-Host \"after_foreign_exit=$(Test-Path (Join-Path $BackendDir '.apply.lock'))\"\n"
        "$script:LockHeld = $true\n"
        "Emit-Result 'success' 0\n"
        "Write-Host \"after_emit=$(Test-Path (Join-Path $BackendDir '.apply.lock'))\"\n"))
    out = r.stdout
    assert "first=[] held=True exists=True" in out, out + r.stderr
    assert "second=[locked]" in out, out           # 持有者是活著的 powershell
    assert "after_foreign_exit=True" in out, out
    assert "after_emit=False" in out, out


def test_lock_left_by_a_dead_process_is_stale_and_not_removed(tmp_path):
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / ".apply.lock").write_text(json.dumps({"pid": 999999, "script": "apply_update"}), encoding="utf-8")
    r, _ = _run_ps(tmp_path, "$a = Enter-InstallLock 'apply_update' 'P'\nWrite-Host \"state=[$a]\"\nExit-InstallLock\n")
    assert "state=[stale]" in r.stdout, r.stdout + r.stderr
    assert (backend / ".apply.lock").exists(), "殘留鎖不自動清"


def test_result_file_first_five_fields_equal_the_result_line(tmp_path):
    r, backend = _run_ps(tmp_path, "$script:ProdState = 'restored'\n$script:ServiceState = 'up'\nEmit-Result 'copy_failed_frontend' 1\n")
    line = [l for l in r.stdout.splitlines() if l.startswith("::RESULT::")]
    assert len(line) == 1, r.stdout + r.stderr
    kv = dict(p.split("=", 1) for p in line[0].split()[1:])
    files = list((backend / "logs").glob("apply_update_20260928_000000.result.json"))
    assert len(files) == 1 and not list((backend / "logs").glob("*.tmp"))
    res = json.loads(files[0].read_text(encoding="utf-8"))
    assert res["protocol"] == 2 and str(res["protocol"]) == kv["v"]
    assert (res["status"], res["rolled_back"], res["service"], str(res["exit"])) == \
        (kv["status"], kv["rolled_back"], kv["service"], kv["exit"])
    assert res["script"] == "apply_update" and res["package"] == "P" and res["commit"] == "c"


def test_lock_is_taken_before_anything_is_touched():
    """鎖在套用前檢查（[1/6]）之前；回滾的鎖在快照驗證之前。"""
    a = _ps_code("apply_update.ps1")
    assert a.index('Enter-InstallLock "apply_update"') < a.index("[1/6]")
    assert a.index('Enter-InstallLock "apply_update"') > a.index('"script_not_from_package"')
    r = _ps_code("rollback_update.ps1")
    assert r.index('Enter-InstallLock "rollback_update"') < r.index("[1/2]")


def test_ahs11_unhandled_exception_still_reports_and_releases_the_lock(tmp_path):
    """AH-S11：沒被接住的例外 ⇒ 仍印 ::RESULT::、寫結果檔、放鎖（腳本本身的 trap 區塊原樣取出來跑）。"""
    import re
    a = (_TOOLS / "apply_update.ps1").read_text(encoding="utf-8-sig")
    m = re.search(r"^trap \{\n.*?^\}\n", a, re.M | re.S)
    assert m, "apply_update.ps1 沒有頂層 trap"
    body = (m.group(0)
            + "$x = Enter-InstallLock 'apply_update' 'P'\n"
            + "Write-Host \"locked=[$x] exists=$(Test-Path (Join-Path $BackendDir '.apply.lock'))\"\n"
            + "throw 'boom'\n")
    r, backend = _run_ps(tmp_path, body)
    assert "locked=[] exists=True" in r.stdout, r.stdout + r.stderr
    line = [l for l in r.stdout.splitlines() if l.startswith("::RESULT::")]
    assert len(line) == 1 and "status=unhandled_exception" in line[0], r.stdout
    assert not (backend / ".apply.lock").exists(), "例外之後鎖要被放掉"
    res = json.loads(next((backend / "logs").glob("*.result.json")).read_text(encoding="utf-8"))
    assert res["status"] == "unhandled_exception" and res["exit"] == 1
    assert r.returncode == 1
    rb = (_TOOLS / "rollback_update.ps1").read_text(encoding="utf-8-sig")
    assert re.search(r'^trap \{\n.*?Emit-Result "rollback_unhandled_exception" 1', rb, re.M | re.S)


def test_ahs10_snapshot_dir_and_result_file_share_the_timestamp():
    code = _ps_code("apply_update.ps1")
    assert "$timestamp = $script:RunStamp" in code
    assert code.index('$script:RunStamp = Get-Date') < code.index("$timestamp = $script:RunStamp")



# ── D 稽核 DM2：回滾以快照為準清掉「安裝目錄有、快照沒有」的程式檔 ──

def test_dm2_rollback_to_an_older_snapshot_removes_modules_added_later(tmp_path):
    """T1 快照之後，兩次套用各新增一個模組（m1、m2）；回滾到 T1 ⇒ 兩個都要清掉（只靠 T2 的 added 清不到 m1）。"""
    root, snap = tmp_path / "root", tmp_path / "snap"
    for base in (root, snap):
        _w(base, "backend/main.py", "v1")
        _w(base, "backend/modules/a/module.json", "{}")
        _w(base, PG + "/a.html", "a")
    for rel in ("backend/modules/m1/module.json", "backend/modules/m1/x.py", "backend/modules/m2/module.json",
                PG + "/m2.html"):
        _w(root, rel, "later")
    for rel in DATA_FILES + ["backend/.apply.lock", "backend/motrix_erp.db.modules_disabled.json",
                             "backend/.deployed_files.json", "backend/.deployed_commit.json", "backend/license.key",
                             "backend/certs/cert.pem", "tools/platform/only_in_root.py"]:
        _w(root, rel, "keep")
    rels = ap.not_in_snapshot(str(root), str(snap), _upgrade)
    assert rels == ["backend/modules/m1/module.json", "backend/modules/m1/x.py", "backend/modules/m2/module.json",
                    PG + "/m2.html"], rels          # 快照沒有 tools/ ⇒ tools 整個略過；狀態／設定／資料不列
    _rels, removed, errors, over = ap.cleanup_not_in_snapshot(str(root), str(tmp_path), str(snap), 500)
    assert not errors and not over and sorted(removed) == rels
    assert not (root / "backend/modules/m1").exists() and not (root / "backend/modules/m2").exists()
    for rel in DATA_FILES + ["backend/.apply.lock", "backend/license.key", "tools/platform/only_in_root.py"]:
        assert (root / rel).exists(), rel


def test_dm2_over_the_limit_touches_nothing(tmp_path):
    root, snap = tmp_path / "root", tmp_path / "snap"
    _w(snap, "backend/main.py")
    for k in range(5):
        _w(root, "backend/extra_%d.py" % k)
    rels, removed, errors, over = ap.cleanup_not_in_snapshot(str(root), str(tmp_path), str(snap), 3)
    assert over and removed == [] and len(rels) == 5 and all((root / r).exists() for r in rels)


def test_do1_lock_and_state_cache_are_never_deletable():
    for rel in ("backend/.apply.lock", "backend/motrix_erp.db.modules_disabled.json", "backend/.deployed_files.json"):
        assert not ap.deletable(rel, _upgrade), rel
    assert ap.deletable("backend/main.py", _upgrade)                 # 正對照


# ── D 稽核 DM1：覆寫資料庫之前另存回滾前的資料庫；手動回滾預設只回程式 ──

def test_dm1_auto_rollback_saves_the_database_before_overwriting_it():
    code = _ps_code("apply_update.ps1")
    i_save = code.index('Backup-DatabasesOnline (Join-Path $BackendDir "db_backups\\pre_rollback_$timestamp")')
    i_main = code.index("Copy-Item $dbBackupPath $dbPath -Force")
    i_demo = code.index("Copy-Item $demoDbBackupPath $demoDbPath -Force")
    assert i_save < i_main and i_save < i_demo
    seg = code[i_save:i_demo]
    assert "if (-not $dbSaved)" in seg and "elseif (Test-Path $dbBackupPath)" in seg, "另存失敗就不覆寫主庫"
    assert "if ($dbSaved -and (Test-Path $demoDbBackupPath))" in code, "另存失敗就不覆寫 demo 庫"


def test_dm1_manual_rollback_keeps_the_database_by_default():
    code = _ps_code("rollback_update.ps1")
    assert "[switch]$IncludeDatabase" in code and "[switch]$ConfirmDatabaseOverwrite" in code
    i_copy = code.index("Copy-Item $dbBackupPath $dbPath -Force")
    assert code.rfind("if ($IncludeDatabase) {", 0, i_copy) != -1, "資料庫覆寫只在 -IncludeDatabase 分支裡"
    i_save = code.index('Backup-DatabasesOnline (Join-Path $BackendDir "db_backups\\pre_rollback_$($script:RunStamp)")')
    assert i_save < code.index('$script:ProdState = "restoring"') < i_copy, "先另存（失敗就不動）→ 才進入還原"
    assert 'if ($Yes) { Fail "要連資料庫一起回滾，必須另外加 -ConfirmDatabaseOverwrite' in code, "-Yes 不算數"


# ── D 稽核 DS3：過去只靠演練、沒有題守的行為（突變 M1～M4、M8、M9 曾存活）──

def test_ds3_behaviours_that_only_drills_used_to_cover():
    a = _ps_code("apply_update.ps1")
    r = _ps_code("rollback_update.ps1")
    restore = _ps_function(a, "Restore-ProgramAfterCopyFailure")
    assert re.search(r'\$rd = Join-Path \$rollbackDir "root_docs"\s*\n\s*if \(Test-Path \$rd\) \{ Get-ChildItem -Path \$rd -File '
                     r'\| ForEach-Object \{ Copy-Item \$_\.FullName -Destination \$ProdRoot -Force \} \}', restore), \
        "M3：複製失敗寫回時要把根目錄文件複製回安裝根目錄（D2-S2：只驗變數指派不算）"
    assert "Copy-Item $demoDbBackupPath $demoDbPath -Force" in a, "M4：自動回滾要還原 demo 庫"
    assert a.index('Join-Path $rollbackDir "deployed_commit.before.json"') < a.index('[2/6]'), \
        "M8：套用前（停服前）把部署紀錄存進快照"
    auto = a[a.index('$script:ProdState = "restoring"', a.index("觸發自動回滾")):]
    assert auto.index('"cleanup-snapshot"') < auto.index('robocopy (Join-Path $rollbackDir "backend")'), \
        "M9：自動回滾先清快照沒有的檔再寫回"
    # D2-S2：清理失敗要真的由清理結果決定，並在啟動之前擋下（寫死成 false 要紅）
    assert '$cleanFailed = ($cleanRun.Exit -ne 0 -or ($cleanRun.Text -notmatch "APPLY_SNAPCLEAN_OK"))' in auto
    i_fail = auto.index('if ($cleanFailed) {')
    assert '"restore_cleanup_failed"' in auto[i_fail:i_fail + 400] and i_fail < auto.index("Start-InstallService")
    assert 'Copy-Item $deployedBefore (Join-Path $BackendDir ".deployed_commit.json") -Force' in r, \
        "M1：手動回滾還原部署紀錄"
    assert re.search(r'if \(-not \(Test-Path \(Join-Path \$rollbackDir "backend\\\.deployed_files\.json"\)\) '
                     r'-and \(Test-Path \$baselinePath\)\) \{\s*Remove-Item \$baselinePath', r), \
        "M2：快照沒有 baseline ⇒ 移除新版 baseline"


# ── D 稽核 DS5：寫回快照不動授權、憑證、autostart、鎖、部署紀錄 ──

@pytest.mark.parametrize("name", ("apply_update.ps1", "rollback_update.ps1"))
def test_ds5_restores_never_write_back_config_files(name):
    code = _ps_code(name)
    # 寫回＝來源是快照（(Join-Path $rollbackDir …) 或 $snap）；建快照（目的地是快照）不算
    writes = [l for l in code.splitlines() if re.search(r"robocopy\s+(\(Join-Path \$rollbackDir|\$snap\s)", l)]
    assert writes, "量法壞了：沒抓到任何寫回"
    for l in writes:
        for token in ("/XD certs", "license.key", "autostart.bat", ".apply.lock", ".deployed_commit.json"):
            assert token in l, (token, l.strip())


# ── D 稽核 DS4：兩支腳本的所有狀態值都在儀表板值域裡 ──

def _ps_statuses(name):
    src = (_TOOLS / name).read_text(encoding="utf-8-sig")
    return set(re.findall(r'(?:Fail(?:-AfterStop)?\s+.*?|Emit-Result\s+)"([a-z_]+)"', src))


def test_ds4_every_script_status_is_in_the_dashboard_domain():
    import ast
    tree = ast.parse((_TOOLS / "deploy_dashboard.py").read_text(encoding="utf-8"))
    domain = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") in ("_STATUS_SUCCEEDED", "_STATUS_FAILED")
                                                for t in node.targets):
            domain |= {c.value for c in ast.walk(node.value) if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    assert {"success", "unhandled_exception", "rollback_ok"} <= domain, "量法壞了：值域沒讀到"
    for name in ("apply_update.ps1", "rollback_update.ps1"):
        st = _ps_statuses(name)
        assert len(st) >= 10, "量法壞了"
        assert not (st - domain), (name, sorted(st - domain))
    assert "made_up_status" not in domain                           # 反向控制


# ── DO3／AH-S1（使用者裁示 2026-09-28）：完整包套用不刪模組資料夾；授權有而包沒有 ⇒ 拒絕 ──

def test_do3_a_licensed_module_missing_from_the_package_refuses_the_whole_apply(env):
    root, pkg = env
    ap._license_check = lambda m: (m.get("key") == "b", "授權有" if m.get("key") == "b" else "未授權")
    with pytest.raises(ap.Refuse) as e:
        ap.make_plan(root, pkg, 200)
    assert "b" in str(e.value) and "拒絕套用" in str(e.value)
    assert os.path.isfile(os.path.join(root, "backend/modules/b/y.py"))


def test_do3_kept_module_files_listed_in_the_baseline_are_not_deleted_either(env):
    """baseline 也是一條刪除來源：舊版包帶過 c 的檔、新包沒有 ⇒ 仍不可以經 baseline 刪掉未授權而保留的模組。"""
    root, pkg = env
    base = json.loads(Path(root, ap.BASELINE_REL).read_text(encoding="utf-8"))
    base["files"] += ["backend/modules/c/module.json", "backend/modules/b/y.py"]
    Path(root, ap.BASELINE_REL).write_text(json.dumps(base), encoding="utf-8")
    plan = ap.make_plan(root, pkg, 200)
    assert not [d for d in plan["delete"] if d["rel"].startswith(("backend/modules/b/", "backend/modules/c/"))]


def test_do3_pages_declared_by_a_kept_module_are_kept(env):
    root, pkg = env
    Path(root, "backend/modules/b/module.json").write_text(json.dumps({"key": "b", "pages": ["b.html"]}),
                                                           encoding="utf-8")
    plan = ap.make_plan(root, pkg, 200)
    assert PG + "/b.html" not in {d["rel"] for d in plan["delete"]}


def test_do3_real_license_check_with_the_gate_off_treats_everything_as_licensed(env):
    """正對照（不注入）：授權閘門關閉 ⇒ 全部視為有授權 ⇒ 包少了安裝目錄的模組就拒絕。"""
    root, pkg = env
    ap._license_check = None
    from helpers import licensing
    assert licensing.LICENSE_GATE_ENABLED is False, "這一題的前提改了：授權閘門已開，請改寫成讀測試金鑰"
    with pytest.raises(ap.Refuse):
        ap.make_plan(root, pkg, 200)


# ── D 複核 D2-S1：trap 重啟與 plan_refused 分流 ──

@pytest.mark.parametrize("prod,service,expect", [
    ("applied", "down", True), ("not_applied", "down", True),
    ("restoring", "down", False), ("applied", "up", False)])
def test_d2s1_trap_restarts_only_when_it_is_safe(tmp_path, prod, service, expect):
    a = (_TOOLS / "apply_update.ps1").read_text(encoding="utf-8-sig")
    m = re.search(r"^trap \{\n.*?^\}\n", a, re.M | re.S)
    body = ("function Start-InstallService { Write-Host 'START-CALLED' }\n" + m.group(0)
            + "$script:ProdState = '%s'\n$script:ServiceState = '%s'\nthrow 'boom'\n" % (prod, service))
    r, _backend = _run_ps(tmp_path, body)
    assert ("START-CALLED" in r.stdout) is expect, r.stdout + r.stderr
    assert "status=unhandled_exception" in r.stdout


def test_d2s1_refusal_is_reported_as_plan_refused_before_plan_failed():
    code = _ps_code("apply_update.ps1")
    i_ref = code.index('if ($planRun.Text -match "APPLY_PLAN_REFUSED") {')
    assert '"plan_refused"' in code[i_ref:i_ref + 300]
    assert i_ref < code.index('"plan_failed"')
    assert '"plan_tool_missing"' in code and code.count('"plan_refused"') == 1


# ── D 複核 D2-O1：執行期會寫入的位置不可以被分類成程式檔（否則 cleanup-snapshot 會把它當「快照沒有」刪掉）──

#: core.paths 裡本來就是程式（隨包出貨）的常數
_PROGRAM_PATHS = {"BACKEND_DIR", "INSTALL_ROOT", "STATIC_DATA_DIR", "FRONTEND_DIR", "FRONTEND_PAGES_DIR",
                  "VERSION_MANIFEST", "BUILD_COMMIT_FILE", "FORM_TEMPLATES_DIR"}     # FORM_TEMPLATES_DIR：建構器內建範本（隨包出貨的 JSON，不是執行期寫入位置）


def _runtime_path_constants():
    from core import paths as P
    root = os.path.realpath(P.INSTALL_ROOT)
    out = {}
    for name in dir(P):
        if not name.isupper() or name in _PROGRAM_PATHS:
            continue
        v = getattr(P, name)
        vals = [v] if isinstance(v, str) else [d for _k, d in v.values()] if isinstance(v, dict) else []
        for i, val in enumerate(vals):
            if isinstance(val, str) and os.path.isabs(val) and os.path.realpath(val).startswith(root + os.sep):
                out["%s[%d]" % (name, i)] = os.path.relpath(os.path.realpath(val), root).replace("\\", "/")
    return out


def test_d2o1_runtime_write_locations_are_never_deletable_program_files():
    consts = _runtime_path_constants()
    assert len(consts) >= 10, "量法壞了：%r" % consts
    bad = {}
    for name, rel in consts.items():
        base = name.split("[")[0]
        is_dir = base.endswith(("_DIR", "_ROOT")) or base in ("PDF_ARCHIVES",)
        probe = rel + "/x.json" if is_dir else rel          # 目錄 ⇒ 驗它底下寫入的檔；檔 ⇒ 驗它本身
        if ap.deletable(probe, _upgrade):
            bad[name] = probe
    assert not bad, bad
    from core import paths as P
    cache = os.path.relpath(P.modules_disabled_cache(P.DB_PATH), P.INSTALL_ROOT).replace("\\", "/")
    assert not ap.deletable(cache, _upgrade)
    assert ap.deletable("backend/some_new_runtime_dir/x.json", _upgrade), "反向控制：未登記的新位置會被當成程式"

