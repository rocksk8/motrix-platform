# -*- coding: utf-8 -*-
"""backend/tools/apply_module_update.ps1（B55 單一模組更新包 §1.3；S5）的靜態守門。

照 test_apply_plan 的做法（函式本體逐項驗、逐字比對、值域雙向）：
① DB-S1＝U-M1②：共用函式與 apply_update.ps1 逐字相同（改一個字元 ⇒ 紅）；Emit-Result 只多「補模組欄位」那一行；
   server.log 掃描核心逐字相同；$ProdRoot／$Port 與 apply_update 相同、沒有演練繞過分支。
② 順序：鎖 → 預檢 → DB 快照 → 乾跑（疊加樹，finally 刪）→ 停服 → 換檔 → 重啟 → 健檢（ping＋載入狀態＋log）；
   回滾：停服 → 模組回滾 → DB 另存再寫回 → 重啟；F13 先停用模組才重啟、停用失敗不重啟。
③ status 全在儀表板值域；設計 §2 的新 status 都有出口；每個 Fail 都給了 status（不靠預設 unknown）。
④ AH-O7：腳本內容雜湊與 apply_module_update.version.json 一致。
"""
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_TOOLS = Path(__file__).resolve().parents[2] / "tools"
NEW = "apply_module_update.ps1"
SHARED = ("Test-Ping", "Fail", "Info", "Warn", "Ok", "Enter-InstallLock", "Exit-InstallLock", "Write-ResultFile",
          "Backup-DatabasesOnline", "Invoke-Py", "Stop-InstallService", "Start-InstallService")
NEW_STATUSES = {"module_preflight_failed", "module_load_dryrun_failed", "module_copy_failed",
                "module_unhealthy_rolled_back", "module_restore_failed"}


def _src(name):
    return (_TOOLS / name).read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def _fn(text, name):
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("function %s" % name) and (len(line) == len("function %s" % name) or line[len("function %s" % name)] in " ("):
            if line.rstrip().endswith("}"):
                return line
            for j in range(i + 1, len(lines)):
                if lines[j] == "}":
                    return "\n".join(lines[i:j + 1])
    return None


def _code(text):
    return "\n".join(l for l in text.split("\n") if not l.lstrip().startswith("#"))


# ── ① 逐字 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", SHARED)
def test_shared_functions_are_verbatim_copies_of_apply_update(name):
    a, n = _fn(_src("apply_update.ps1"), name), _fn(_src(NEW), name)
    assert a is not None and n is not None, "%s 在其中一支找不到（改名要兩邊一起改）" % name
    assert a == n, "%s：apply_module_update.ps1 與 apply_update.ps1 不同步（DB-S1 逐字複製）" % name


def test_emit_result_differs_only_by_the_module_fields_line():
    a, n = _fn(_src("apply_update.ps1"), "Emit-Result"), _fn(_src(NEW), "Emit-Result")
    assert "    Add-ModuleResultFields" in n.split("\n")
    assert a == "\n".join(l for l in n.split("\n") if l != "    Add-ModuleResultFields")


def test_log_scan_core_is_verbatim():
    start = "    $cleanedLines = New-Object System.Collections.Generic.List[string]"
    end = '    $logErrors = $cleanedLines | Select-String -Pattern "Traceback|ERROR" -SimpleMatch:$false'

    def seg(t):
        i = t.index(start)
        return t[i:t.index(end, i) + len(end)]
    assert seg(_src("apply_update.ps1")) == seg(_src(NEW))


def test_prod_root_and_port_are_the_same_lines_and_there_is_no_bypass():
    a, n = _src("apply_update.ps1"), _src(NEW)
    for pat in (r'^\$ProdRoot = .*$', r'^\$Port = .*$'):
        assert re.search(pat, a, re.M).group(0) == re.search(pat, n, re.M).group(0)
    code = _code(n)
    assert "$env:MOTRIX" not in code, "不可以用環境變數改正式機路徑（演練走複製改寫兩行，§7）"
    assert not re.search(r"\[string\]\$ProdRoot|\[int\]\$Port", code), "不可以把正式機路徑／port 做成參數"


def test_rc_the_extractor_sees_a_one_character_drift():
    n = _src(NEW)
    fa = _fn(n, "Stop-InstallService")
    assert fa and _fn(n.replace("$hops -lt 6", "$hops -lt 7", 1), "Stop-InstallService") != fa


# ── ② 順序 ──────────────────────────────────────────────────────────────

def _main_flow():
    code = _code(_src(NEW))
    return code[code.index('Write-Host "::PROTOCOL:: v=2"'):]


def test_main_flow_order():
    m = _main_flow()
    marks = ["Enter-InstallLock", '"preflight"', "Backup-DatabasesOnline $dbSnapDir", '"overlay"',
             "--expect-module", "Stop-InstallService", '"apply"', "Start-InstallService", "Test-ModuleHealth"]
    idx = [m.index(x) for x in marks]
    assert idx == sorted(idx), list(zip(marks, idx))


def test_dry_run_temp_trees_are_removed_in_finally():
    m = _main_flow()
    seg = m[m.index('"overlay"'):m.index("Stop-InstallService")]
    fin = seg[seg.index("} finally {"):]
    assert "Remove-Item $ovDir -Recurse" in fin and "Remove-Item $ovDbDir -Recurse" in fin


def test_auto_rollback_order():
    m = _main_flow()
    rb = m[m.index('Info "[7/7] 自動回滾..."'):]
    marks = ["Stop-InstallService", "Invoke-ModuleRollback", "Restore-Databases $dbSnapDir", "Start-InstallService"]
    idx = [rb.index(x) for x in marks]
    assert idx == sorted(idx), list(zip(marks, idx))


def test_db_restore_saves_pre_rollback_before_overwriting():
    f = _fn(_src(NEW), "Restore-Databases")
    assert f.index("Backup-DatabasesOnline") < f.index("Copy-Item $snap $dst")
    assert "return $false" in f[:f.index("Copy-Item $snap $dst")], "另存失敗 ⇒ 不覆寫"


def test_f13_disables_the_module_before_restarting_and_does_not_restart_when_disable_fails():
    f = _fn(_src(NEW), "Fail-RestoreCorrupt")
    assert f.index('"disable"') < f.index("Start-InstallService"), "先停用才重啟（DB-S5）"
    fail_idx = f.index('"module_restore_failed"')
    assert fail_idx < f.index("Start-InstallService"), "停用寫入失敗的出口在重啟之前（不重啟）"
    assert 'Wait-ModuleState $script:ModuleKey $null "disabled"' in f


def test_health_check_has_both_layers_beyond_ping():
    f = _fn(_src(NEW), "Test-ModuleHealth")
    assert f.index("Test-Ping") < f.index('Wait-ModuleState $key $version "loaded"') < f.index("Get-LogCheck")


def test_rollback_passes_this_run_stamp():
    n = _code(_src(NEW))
    assert '"--stamp", $script:ModStamp' in n
    assert '"--backup", $script:ModStamp' in _fn(_src(NEW), "Invoke-ModuleRollback")


# ── ③ status ────────────────────────────────────────────────────────────

def _dashboard_domain():
    import ast
    tree = ast.parse((_TOOLS / "deploy_dashboard.py").read_text(encoding="utf-8"))
    domain = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") in ("_STATUS_SUCCEEDED", "_STATUS_FAILED")
                                                for t in node.targets):
            domain |= {c.value for c in ast.walk(node.value) if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    return domain


def _statuses():
    code = _code(_src(NEW))
    # Fail／Emit-Result 的字面 status，加上「$變數 = if (…) { "a" } else { "b" }」再交給 Fail 的那兩處
    lit = set(re.findall(r'(?:Fail\s+.*?|Emit-Result\s+)"([a-z_]+)"', code))
    for a, b in re.findall(r'\$(?:failStatus|st) = if \(.*?\) \{ "([a-z_]+)" \} else \{ "([a-z_]+)" \}', code):
        lit |= {a, b}
    return lit


def test_every_status_is_in_the_dashboard_domain_and_every_new_one_has_an_exit():
    domain, st = _dashboard_domain(), _statuses()
    assert {"success", "unhandled_exception"} <= st and len(st) >= 12, sorted(st)
    assert not (st - domain), sorted(st - domain)
    assert NEW_STATUSES <= st, "設計 §2 的新 status 沒有出口：%s" % sorted(NEW_STATUSES - st)
    assert NEW_STATUSES <= domain
    assert "made_up_status" not in domain                          # 反向控制


def test_every_fail_call_names_its_status():
    code = _code(_src(NEW))
    body = code[code.index("function Fail-RestoreCorrupt"):]
    bad = [l.strip() for l in body.split("\n")
           if re.match(r'\s*(if .*\{\s*)?Fail\s+"', l) and not re.search(r'"\s+(\$[a-zA-Z]+|"[a-z_]+")\s*\}?\s*$', l)]
    assert not bad, "Fail 沒給 status（會變 unknown）：%s" % bad


# ── ④ 版本登記 ──────────────────────────────────────────────────────────

def test_script_change_requires_a_version_decision():
    reg = json.loads((_TOOLS / "apply_module_update.version.json").read_text(encoding="utf-8"))
    raw = (_TOOLS / NEW).read_bytes()
    code = raw.decode("utf-8-sig")
    m = re.search(r'^\$ApplyModuleScriptVersion = "([^"]+)"', code, re.M)
    assert m and m.group(1) == reg["version"]
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    digest = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
    assert digest == reg["sha256"], "apply_module_update.ps1 內容變了：更新 version.json 的 sha256 成 %s" % digest


@pytest.mark.skipif(not shutil.which("powershell"), reason="沒有 Windows PowerShell")
def test_script_parses_without_errors():
    ps = ("$e=$null;$t=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$t,[ref]$e);"
          "Write-Output $e.Count") % str(_TOOLS / NEW)
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=120)
    assert r.stdout.strip().splitlines()[-1] == "0", r.stdout + r.stderr
