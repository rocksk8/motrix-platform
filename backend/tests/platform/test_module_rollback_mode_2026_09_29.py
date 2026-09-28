# -*- coding: utf-8 -*-
"""apply_module_update.ps1 的回滾模式（B55F-M1，主持裁示①；2026-09-29 A）。

① module_apply_steps.rollback_check（唯讀預檢）：用真的 module_update 在合成安裝目錄上套用後判——回哪一份備份、
   回到哪一版、那次套用新增了哪些 migration；沒有備份／找不到／紀錄壞掉各回 §10 的 code。
② ps1 回滾那一段（靜態）：鎖 → 唯讀預檢 → 新增 migration 而沒帶資料庫旗標 ⇒ 拒絕（停服之前）→ 確認 → 停服 →
   module_update rollback →（兩個旗標都給才）資料庫還原 → 重啟 → 健檢；一個檔都沒動的拒絕 ⇒ 照原樣重啟、不停用；
   其餘 ⇒ F13。實際在正式機條件跑一場由 B 的演練工具場次 D 負責。
"""
import json
import re

import pytest

from tests.platform.test_module_update import (  # noqa: F401  （src、_licensed 是 fixture）
    MU, _build, _commit, _install, _licensed, _module, _write, src)
from tests.platform.test_apply_module_update_ps1_2026_09_28 import (
    NEW, _code, _fn, _ps_list, _rollback_flow, _src, _statuses, _dashboard_domain)
from tests.platform.test_module_apply_steps_2026_09_28 import S as MAS

KEY = "zz"


def _upgrade(src, tmp_path, with_new_migration=False):
    root = _install(tmp_path)
    MU.apply(root, _build(src, tmp_path, "v1"))
    _module(src, "1.1.0", extra="NEW = 1\n")
    if with_new_migration:
        _write(src / "backend" / "modules" / KEY / "migrations" / "0002_add_col.py", "def up(conn):\n    pass\n")
    _commit(src, "v1.1")
    rec, _ = MU.apply(root, _build(src, tmp_path, "v11"))
    return root, rec


# ── ① rollback_check ─────────────────────────────────────────────────────────

def test_check_picks_the_latest_backup_and_the_version_to_go_back_to(src, tmp_path):
    root, rec = _upgrade(src, tmp_path)
    got = MAS.rollback_check(root, KEY, mu=MU)
    assert got["stamp"] == MU.backups(root, KEY)[-1] == rec["applied_at"]
    assert got["version"] == "1.0.0" and got["applied_version"] == "1.1.0"
    assert got["migrations_added"] == [], "沒有新增 migration"


def test_check_reports_migrations_the_applied_version_added(src, tmp_path):
    root, _ = _upgrade(src, tmp_path, with_new_migration=True)
    got = MAS.rollback_check(root, KEY, mu=MU)
    assert got["migrations_added"] == ["backend/modules/zz/migrations/0002_add_col.py"]


def test_reverse_control_migration_present_before_the_apply_is_not_counted(src, tmp_path):
    """套用前就有的 migration（舊版已跑過）不算新增 ⇒ 只回程式照常可以。"""
    _write(src / "backend" / "modules" / KEY / "migrations" / "0001_base.py", "def up(conn):\n    pass\n")
    _commit(src, "v1 with base migration")
    root, _ = _upgrade(src, tmp_path)
    assert MAS.rollback_check(root, KEY, mu=MU)["migrations_added"] == []


def test_check_with_an_explicit_backup_uses_that_one(src, tmp_path):
    root, _ = _upgrade(src, tmp_path)
    first = MU.backups(root, KEY)[0]
    got = MAS.rollback_check(root, KEY, backup=first, mu=MU)
    assert got["stamp"] == first and got["version"] is None, "第一份是從「沒有這個模組」套上 1.0.0"


@pytest.mark.parametrize("case, code", [("none", "no_backup"), ("missing", "backup_not_found"), ("corrupt", "backup_corrupt")])
def test_check_refusals_use_the_s10_codes(src, tmp_path, case, code):
    if case == "none":
        root = _install(tmp_path)
        with pytest.raises(MAS.CheckFail) as e:
            MAS.rollback_check(root, KEY, mu=MU)
    else:
        root, _ = _upgrade(src, tmp_path)
        if case == "corrupt":
            (root / MU.BACKUP_DIR / KEY / MU.backups(root, KEY)[-1] / "apply.json").write_text("{壞", encoding="utf-8")
        with pytest.raises(MAS.CheckFail) as e:
            MAS.rollback_check(root, KEY, backup="20990101_000000" if case == "missing" else None, mu=MU)
    assert e.value.code == code


def test_check_is_read_only(src, tmp_path):
    root, _ = _upgrade(src, tmp_path, with_new_migration=True)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    MAS.rollback_check(root, KEY, mu=MU)
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_cli_prints_one_machine_line(src, tmp_path, monkeypatch, capsys):
    root, _ = _upgrade(src, tmp_path)
    monkeypatch.setattr(MAS, "_load_module_update", lambda r: MU)
    assert MAS.main(["rollback-check", "--root", str(root), "--key", KEY]) == 0
    line = [l for l in capsys.readouterr().out.splitlines() if l.startswith("ROLLBACK_CHECK_")][-1]
    assert line.startswith("ROLLBACK_CHECK_OK ") and json.loads(line.split(" ", 1)[1])["version"] == "1.0.0"
    assert MAS.main(["rollback-check", "--root", str(root), "--key", KEY, "--backup", "20990101_000000"]) == 2
    assert "ROLLBACK_CHECK_FAIL backup_not_found" in capsys.readouterr().out


# ── ② ps1 回滾那一段（靜態）───────────────────────────────────────────────────

def _idx(seg, s):
    assert s in seg, "回滾模式裡找不到：%s" % s
    return seg.index(s)


def test_rollback_flow_order():
    r = _rollback_flow()
    order = ['Enter-InstallLock "apply_module_update"', '"rollback-check"', '"needs_database"', 'Read-Host',
             "Stop-InstallService", "Invoke-ModuleRollback", "Restore-Databases $dbSnapDir",
             "Test-ModuleHealth $RollbackKey $script:ToVersion", 'Emit-Result "module_rollback_ok" 0']
    pos = [_idx(r, s) for s in order]
    assert pos == sorted(pos), list(zip(order, pos))
    # 最後一次啟動（正常路徑）在資料庫還原之後、健檢之前（拒絕那一支的重啟在回滾之前，另有題）
    last_start = r.rindex("Start-InstallService")
    assert pos[order.index("Restore-Databases $dbSnapDir")] < last_start < pos[order.index("Test-ModuleHealth $RollbackKey $script:ToVersion")]


def test_database_is_kept_unless_both_flags_are_given():
    r = _rollback_flow()
    assert "[bool]$IncludeDatabase -ne [bool]$ConfirmDatabaseOverwrite" in r
    assert r.count("Restore-Databases") == 1
    assert re.search(r'\n    if \(\$IncludeDatabase\) \{\n[^\n]*\n\s*\$dbRestored = Restore-Databases \$dbSnapDir\n', r), \
        "資料庫還原要緊接在 if ($IncludeDatabase) 之下（預設只回程式、資料庫保留；使用者 DM1）"
    assert "-Yes 不算數" in r


def test_new_migration_without_database_flags_is_refused_before_stopping():
    """主持 2026-09-29：那次套用新增了 migration ⇒ 只回程式時舊版程式要跑在新 schema 上，判斷不了 ⇒ 停服之前就拒絕。"""
    r = _rollback_flow()
    i = _idx(r, "if ($migAdded.Count -gt 0 -and -not $IncludeDatabase)")
    assert i < _idx(r, "Stop-InstallService")
    assert '"module_rollback_refused"' in r[i:i + 600]


def test_untouched_refusals_restart_as_is_and_the_rest_disable_the_module():
    r = _rollback_flow()
    code = _code(_src(NEW))
    m = re.search(r'^\$RollbackUntouchedCodes = \$RollbackRefusedCodes \+ @\((.*?)\)', code, re.M)
    assert m and set(re.findall(r'"([a-z_]+)"', m.group(1))) == {"backup_corrupt", "no_backup", "backup_not_found"}
    assert {"module_changed", "state_changed", "base_changed", "interrupted_not_latest"} <= _ps_list("RollbackRefusedCodes")
    i = _idx(r, "if ($RollbackUntouchedCodes -contains $rb.Code) {")
    untouched = r[i:r.index("Fail-DisableModule $rb.Code", i)]
    assert "Start-InstallService" in untouched and "disable" not in untouched, "一個檔都沒動 ⇒ 照原樣重啟、不停用"
    assert '"module_rollback_refused"' in untouched
    assert r.index("Fail-DisableModule $rb.Code") > i, "其餘（restore_mismatch／unexpected／沒有結果行）⇒ F13"


def test_rollback_only_params_are_refused_on_the_apply_path():
    code = _code(_src(NEW))
    assert "if ($RollbackKey -or $Backup -or $IncludeDatabase -or $ConfirmDatabaseOverwrite) {" in code
    p = _code(_fn(_src(NEW), "Invoke-ModuleRollback"))
    assert '"--backup", $script:ModStamp' in p, "回滾模式用預檢選定的那一份（與 rollback-check 同一個 stamp）"


def test_rollback_statuses_are_in_the_dashboard_domain():
    st = set(re.findall(r'"(module_rollback_[a-z_]+)"', _code(_src(NEW))))
    assert st == {"module_rollback_ok", "module_rollback_refused", "module_rollback_unhealthy"}
    assert st <= _dashboard_domain() and st <= _statuses()


# ── ③ 實際執行（B 場次 D 抓到：靜態題看不到 PS 變數不分大小寫的遮蔽）───────────────────────
#
# `-ModuleKey` 原本綁在 `$ModuleKey`，而腳本初始化 `$script:ModuleKey = $null`（結果欄位）在 script 範圍就是
# 同一個變數 ⇒ 傳入值被清空 ⇒ 回滾一律 bad_args。這裡把 ps1 複製到暫存安裝目錄（只改寫 $ProdRoot 那一行，
# 同演練工具）真的跑：參數要能活到回滾那一段（之後因為沒有 module_update 而在唯讀預檢被拒，正式機什麼都沒有）。

import shutil as _shutil
import subprocess as _subprocess
from pathlib import Path as _Path

_PS = _shutil.which("powershell.exe") or _shutil.which("powershell")
_TOOLS = _Path(__file__).resolve().parents[2] / "tools"


def _run_ps1(tmp_path, *args):
    if not _PS:
        pytest.skip("需要 Windows PowerShell")
    root = tmp_path / "root"
    tools = root / "backend" / "tools"
    tools.mkdir(parents=True)
    raw = (_TOOLS / NEW).read_bytes()
    text = raw.decode("utf-8-sig")
    line = re.search(r'^\$ProdRoot = ".*"\r?$', text, re.M)
    assert line, "ps1 沒有 `$ProdRoot = \"…\"` 那一行"
    text = text[:line.start()] + '$ProdRoot = "%s"\r' % str(root) + text[line.end():]
    (tools / NEW).write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    _shutil.copy2(_TOOLS / "module_apply_steps.py", tools / "module_apply_steps.py")
    # 主控台輸出編碼設成 UTF-8（重導向時預設是系統 codepage ⇒ 中文訊息解不出來）
    cmd = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; & '%s' %s" % (
        str(tools / NEW).replace("'", "''"), " ".join("'%s'" % a.replace("'", "''") if not a.startswith("-") else a for a in args))
    r = _subprocess.run([_PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                        capture_output=True, timeout=120)
    out = r.stdout.decode("utf-8", "replace")
    m = re.search(r"^::RESULT:: v=2 status=(\S+)", out, re.M)
    assert m, out[-1500:]
    return m.group(1), out


def test_executed_module_key_reaches_the_rollback_branch(tmp_path):
    status, out = _run_ps1(tmp_path, "-Rollback", "-ModuleKey", "zz", "-Yes")
    assert "需要 -ModuleKey" not in out, "傳入的 -ModuleKey 被清空了（$script:ModuleKey 遮蔽參數）"
    assert status == "module_rollback_refused", (status, out[-800:])


def test_executed_rollback_without_module_key_is_bad_args(tmp_path):
    status, out = _run_ps1(tmp_path, "-Rollback", "-Yes")
    assert status == "bad_args" and "需要 -ModuleKey" in out


def test_executed_apply_path_refuses_the_rollback_only_parameter(tmp_path):
    status, out = _run_ps1(tmp_path, "-PackagePath", str(tmp_path / "nope"), "-ModuleKey", "zz", "-Yes")
    assert status == "bad_args" and "只用於 -Rollback" in out, (status, out[-800:])
