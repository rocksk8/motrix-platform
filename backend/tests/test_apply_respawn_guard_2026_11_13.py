# -*- coding: utf-8 -*-
"""T82 事故（2026-11-13）：停服後服務被「看不見的迴圈」0.3 秒拉回來、與 robocopy 重疊，第一次啟動讀到半新半舊的程式，
core migration 13／14 沒跑而 ping 照過。

正式機證據（正式機回報\\20261113_T82根因證據）：迴圈是 `cmd /c …\\backend\\autostart_guard.bat`（排程 → wscript autostart_guard.vbs → bat → call
autostart.bat 的 :loop），行程鏈 python.exe → uvicorn.exe → cmd.exe(guard) → cloudflared.exe → services.exe；另有 3 個父行程已不在、
沒有 uvicorn 子行程的殭屍 guard 迴圈（各帶 conhost＋timeout）。舊 Stop-InstallService 只認命令列含 `autostart.bat` ⇒ 全部漏掉。

T84 修法（本檔逐一釘住）：
① `Stop-InstallService`（apply_update／apply_module_update／rollback_update 逐字相同）：認所有 autostart*.bat 的迴圈（含殭屍），
   沿 port listener 的父行程鏈找 cmd，每輪先殺迴圈再殺服務，重掃到沒有目標；`-ListOnly` 只列不殺。
② `Stop-RespawnedService`：停服後、複製後、啟動前核對沒有迴圈／服務活著；apply_update 與 apply_module_update 都有。
③ `Invoke-SchemaGate`（apply_update）：啟動後兜底——服務行程比程式複製完成早、或庫內 module_schema_versions 落後 ⇒ 重啟再驗；
   仍不過 ⇒ `unhealthy_not_rolled_back`（exit 1，**不自動回滾**，回滾會還原資料庫）；驗不到 ⇒ 只警告。

🔴 這份測試用正式機的行程鏈當替身（PowerShell 替身函式餵 Get-CimInstance／Get-NetTCPConnection／Stop-Process），實際執行**真的**
   Stop-InstallService／Stop-RespawnedService／Invoke-SchemaGate。**驗不到**的只有一件事：迴圈真的在殺掉服務後 0.3 秒內重生、
   與 robocopy 重疊——那一段沒有真實環境可測；替身只能模擬「殺掉某行程時某迴圈還活著 ⇒ 立刻長出新服務」的因果。
"""
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

_TOOLS = Path(__file__).resolve().parents[1] / "tools"
_PS = shutil.which("powershell.exe") or shutil.which("powershell")
needs_ps = pytest.mark.skipif(not _PS, reason="需要 Windows PowerShell（apply_update.ps1 的執行環境）")


def _src(name="apply_update.ps1"):
    return (_TOOLS / name).read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def _fn(text, name):
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("function %s" % name):
            for j in range(i + 1, len(lines)):
                if lines[j] == "}":
                    return "\n".join(lines[i:j + 1])
    return None


def _tool():
    spec = importlib.util.spec_from_file_location("migrate_like_startup_t84", _TOOLS / "migrate_like_startup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 結構：順序與出口 ────────────────────────────────────────────────────────

def test_apply_update_scans_after_stop_after_copy_and_before_start():
    t = _src()
    i_stop = t.index("[2/6] 停止伺服器")
    i_scan0 = t.index('Stop-RespawnedService "停服後"')
    i_copy = t.index("[3/6] 套用新程式碼")
    i_applied = t.index('$script:ProdState = "applied"')
    i_done = t.index("$script:CopyDoneTime = Get-Date")
    i_scan1 = t.index('Stop-RespawnedService "複製後"')
    i_pip = t.index("[4/6] 安裝/更新 Python 依賴")
    i_scan2 = t.index('Stop-RespawnedService "啟動前"')
    i_start = t.index("[4b/6] 重新啟動服務")
    assert i_stop < i_scan0 < i_copy < i_applied < i_done < i_scan1 < i_pip < i_scan2 < i_start
    assert t.count('Stop-RespawnedService "') == 3, "只在這三處呼叫"
    assert t.index("function Stop-RespawnedService") < i_scan0, "函式要先定義"


def test_apply_module_update_has_the_same_guard_but_not_the_schema_gate():
    t = _src("apply_module_update.ps1")
    i_stop = t.index("[4/7] 停止服務")
    i_scan0 = t.index('Stop-RespawnedService "停服後"')
    i_swap = t.index("[5/7] 替換模組")
    i_applied = t.index('$script:ProdState = "applied"')
    i_scan2 = t.index('Stop-RespawnedService "啟動前"')
    i_start = t.index("Start-InstallService\n$hc = Test-ModuleHealth $script:ModuleKey $script:ToVersion")
    assert i_stop < i_scan0 < i_swap < i_applied < i_scan2 < i_start
    assert "function Invoke-SchemaGate" not in t, "模組更新的 Test-ModuleHealth 已驗載入版本；兜底閘門只在 apply_update.ps1"
    assert '$ApplyModuleScriptVersion = "2026-11-13c"' in t


def test_schema_gate_sits_between_health_loop_and_log_scan_and_never_auto_rolls_back():
    t = _src()
    i_loop = t.index("[5/6] 等待伺服器恢復並健康檢查")
    i_block = t.index('$schemaVerify = "skipped"')
    i_log = t.index("\n$logErrors = @()\n")
    assert i_loop < i_block < i_log, "要在讀 log 之前（它可能重啟服務，之後讀到的才是最後一次啟動）"
    block = t[i_block:i_log]
    assert "Invoke-SchemaGate" in block and '"unhealthy_not_rolled_back"' in block
    assert block.count("Fail (") == 1 and "if ($gate.FailMsg)" in block
    for bad in ("robocopy", "Backup-Databases", "Restore-", "Fail-AfterStop"):
        assert bad not in block, "不一致不可以在這裡就回滾／動資料庫：%s" % bad
    assert "$rollbackDir" in block and "$dbBackupDir" in block and "-SnapshotTimestamp $timestamp" in block, "Fail 訊息要給回滾快照與手動回滾指令（B5）"
    gate = _fn(t, "Invoke-SchemaGate")
    for bad in ("Fail ", "Restore-", "robocopy", "Fail-AfterStop"):
        assert bad not in gate, "Invoke-SchemaGate 只回結果，不決定要不要回滾：%s" % bad


def test_schema_gate_documents_the_tradeoff_against_the_log_errors_rollback():
    t = _src()
    assert "與既有 $logErrors 自動回滾的取捨" in t and "留在原地、不回滾" in t


def test_stop_install_service_is_identical_in_all_three_scripts_and_knows_guard_loops():
    a, m, r = (_fn(_src(n), "Stop-InstallService") for n in ("apply_update.ps1", "apply_module_update.ps1", "rollback_update.ps1"))
    assert a and a == m == r
    assert "autostart[a-z0-9_-]*\\.bat" in a, "要認 autostart_guard.bat，不只 autostart.bat"
    assert "$hops -lt 6" in a and "-ListOnly" in a
    assert "break" in a and "$round -lt 5" in a, "要有收斂輪數上限"


def test_scripts_parse_and_versions_registered():
    if _PS:
        for n in ("apply_update.ps1", "apply_module_update.ps1", "rollback_update.ps1"):
            cmd = ('$e=$null;$t=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('
                   '"%s",[ref]$t,[ref]$e);$e.Count' % (_TOOLS / n))
            r = subprocess.run([_PS, "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=120)
            assert r.stdout.strip() == "0", n + r.stdout + r.stderr
    for n, ver in (("apply_update", "2026-11-13c"), ("apply_module_update", "2026-11-13c")):
        reg = json.loads((_TOOLS / ("%s.version.json" % n)).read_text(encoding="utf-8-sig"))
        assert reg["version"] == ver
    assert '$ApplyScriptVersion = "2026-11-13c"' in _src()


# ── ps1 函式實跑（替身：行程表、port、Stop-Process） ─────────────────────────

_PRELUDE = r'''
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = "Stop"
$Port = 666
$BackendDir = "C:\Users\Motrix\Desktop\V9.0\backend"
$PingUrl = "http://127.0.0.1:666/api/ping"
$script:calls = New-Object System.Collections.Generic.List[string]
$script:killed = New-Object System.Collections.Generic.List[int]
$script:batches = New-Object System.Collections.Generic.List[int]
$script:procs = New-Object System.Collections.ArrayList
$script:listen = @()
function Warn($m) { $script:calls.Add("warn") }
function Info($m) { }
function Ok($m) { $script:calls.Add("ok") }
function Start-Sleep { }
$AutostartTaskName = "MotrixAutostart"
function Get-ScheduledTask { param($TaskName) $null }   # 預設沒有排程工作（Suspend-AutostartTask 什麼都不做）；要測排程工作的題目在 body 裡覆寫
function Add-P($id, $pp, $name, $cmd) {
    [void]$script:procs.Add([pscustomobject]@{ ProcessId = [uint32]$id; ParentProcessId = [uint32]$pp; Name = $name; CommandLine = $cmd; CreationDate = (Get-Date) })
}
function Get-CimInstance {
    param($ClassName, $Filter)
    if ($Filter -and $Filter -match 'ProcessId=(\d+)') { $want = [int]$Matches[1]; return $script:procs.ToArray() | Where-Object { [int]$_.ProcessId -eq $want } }
    return $script:procs.ToArray()
}
function Get-NetTCPConnection {
    $alive = @($script:procs.ToArray() | ForEach-Object { [int]$_.ProcessId })
    foreach ($l in $script:listen) { if ($alive -contains [int]$l) { [pscustomobject]@{ OwningProcess = [uint32]$l } } }
}
function Stop-Process {
    param($Id)
    $script:batches.Add(@($Id).Count)
    foreach ($one in @($Id)) {
        $script:killed.Add([int]$one)
        $victim = $script:procs.ToArray() | Where-Object { [int]$_.ProcessId -eq [int]$one }
        if ($victim) { $script:procs.Remove($victim) }
        if (Get-Command Stop-Process-Hook -ErrorAction SilentlyContinue) { Stop-Process-Hook ([int]$one) }
    }
}
'''

# 正式機證據的行程鏈（證據.txt (b)／行程表，命令列與 PID 逐字取自證據；父行程 21188／14044／19336 在證據取樣時不在行程表內）
_PROD_CHAIN = r'''
$B = "C:\Users\Motrix\Desktop\V9.0\backend"
$guardCmd = '"C:\Windows\System32\cmd.exe" /c "C:\Users\Motrix\Desktop\V9.0\backend\autostart_guard.bat"'
$uv = '"C:\Users\Motrix\AppData\Local\Programs\Python\Python312\Scripts\uvicorn.exe"  main:app --port 666 --host 0.0.0.0 --log-level info --ssl-keyfile=certs\key.pem --ssl-certfile=certs\cert.pem'
Add-P 4 0 "System" $null
Add-P 1620 4 "services.exe" $null
Add-P 16944 1620 "cloudflared.exe" $null
Add-P 11916 16944 "cmd.exe" $guardCmd
Add-P 19544 11916 "uvicorn.exe" $uv
Add-P 23376 19544 "python.exe" ('"C:\Users\Motrix\AppData\Local\Programs\Python\Python312\python.exe"  ' + $uv.Replace('"C:\Users\Motrix\AppData\Local\Programs\Python\Python312\Scripts\uvicorn.exe"  ', '"C:\Users\Motrix\AppData\Local\Programs\Python\Python312\Scripts\uvicorn.exe" '))
$script:listen = @(23376)
'''
_ZOMBIES = r'''
foreach ($z in @(@(23148, 21188), @(24764, 14044), @(19892, 19336))) {
    Add-P $z[0] $z[1] "cmd.exe" $guardCmd
    Add-P ($z[0] + 1) $z[0] "conhost.exe" '\??\C:\Windows\system32\conhost.exe 0x4'
    Add-P ($z[0] + 2) $z[0] "timeout.exe" 'timeout  /t 5 /nobreak'
}
'''
_OTHER_INSTALL = r'''
Add-P 5000 90000 "cmd.exe" '"C:\Windows\System32\cmd.exe" /c "D:\OtherInstall\backend\autostart_guard.bat"'
Add-P 5001 5000 "python.exe" 'D:\Other\python.exe -m uvicorn main:app --port 8000'
'''
_ZOMBIE_IDS = "23148,23149,23150,24764,24765,24766,19892,19893,19894"
_PROD_TARGETS = "11916,19544,23376," + _ZOMBIE_IDS
_PROD_LOOPS = "11916,23148,24764,19892"


def _run_ps(body, tmp_path, funcs=("Stop-InstallService",), src="apply_update.ps1"):
    t = _src(src)
    parts = []
    funcs = tuple(funcs)
    if "Stop-InstallService" in funcs:   # Stop-InstallService 會呼叫排程工作的停用／恢復（T84 一次殺光所有迴圈）
        funcs += tuple(x for x in ("Suspend-AutostartTask", "Restore-AutostartTask") if x not in funcs)
    for n in funcs:
        f = _fn(t, n)
        assert f, "找不到函式 %s" % n
        parts.append(f)
    ps1 = tmp_path / "t.ps1"
    ps1.write_bytes(b"\xef\xbb\xbf" + (_PRELUDE + "\n".join(parts) + "\n" + body).replace("\n", "\r\n").encode("utf-8"))
    r = subprocess.run([_PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout.replace("\r", "")


def _ids(out, key):
    m = re.search(r"%s=([0-9,]*)" % key, out)
    assert m, out
    return set(int(x) for x in m.group(1).split(",") if x)


_LIST = r'''
$info = Stop-InstallService -ListOnly
"targets=$(($info.Targets | Sort-Object) -join ',')"
"loops=$(($info.Loops | Sort-Object) -join ',')"
'''


@needs_ps
@pytest.mark.parametrize("script", ["apply_update.ps1", "apply_module_update.ps1", "rollback_update.ps1"])
def test_prod_chain_all_four_guard_loops_and_their_trees_are_targets_unrelated_install_is_not(tmp_path, script):
    out = _run_ps(_PROD_CHAIN + _ZOMBIES + _OTHER_INSTALL + _LIST, tmp_path, src=script)
    assert _ids(out, "targets") == {int(x) for x in _PROD_TARGETS.split(",")}, out
    assert _ids(out, "loops") == {int(x) for x in _PROD_LOOPS.split(",")}, "含沒有 uvicorn 子行程的 3 個殭屍迴圈：" + out
    for must_not in (16944, 1620, 4, 5000, 5001):
        assert must_not not in _ids(out, "targets"), "不可動 cloudflared／services／別的安裝（路徑不同）的迴圈：%d" % must_not


@needs_ps
def test_loop_found_by_walking_up_from_the_listener_when_cmdline_has_no_backend_path(tmp_path):
    """排程工作若用相對路徑啟動（cmd /c autostart_guard.bat），命令列沒有 $BackendDir ⇒ 只能靠 listener 往上的父行程鏈找到它。"""
    old_guard = r"""$guardCmd = '"C:\Windows\System32\cmd.exe" /c "C:\Users\Motrix\Desktop\V9.0\backend\autostart_guard.bat"'"""
    assert old_guard in _PROD_CHAIN
    chain = _PROD_CHAIN.replace(old_guard, r"""$guardCmd = '"C:\Windows\System32\cmd.exe" /c autostart_guard.bat'""")
    other = r'''
Add-P 5000 90000 "cmd.exe" '"C:\Windows\System32\cmd.exe" /c autostart_guard.bat'
'''
    out = _run_ps(chain + other + _LIST, tmp_path)
    assert _ids(out, "loops") == {11916}, "只有 listener 鏈上的那個；別的安裝的相對路徑迴圈不能被當成我們的：" + out
    assert _ids(out, "targets") == {11916, 19544, 23376}


@needs_ps
def test_list_only_kills_nothing_and_old_autostart_bat_loop_is_still_recognised(tmp_path):
    chain = _PROD_CHAIN.replace("autostart_guard.bat", "autostart.bat")
    out = _run_ps(chain + _LIST + '"killed=$($script:killed.Count)"', tmp_path)
    assert _ids(out, "loops") == {11916} and "killed=0" in out


@needs_ps
def test_kill_order_loop_first_then_service_and_nothing_respawns(tmp_path):
    out = _run_ps(_PROD_CHAIN + _ZOMBIES + r'''
function Stop-Process-Hook($id) {
    if ($id -eq 23376 -and ($script:procs.ToArray() | Where-Object { [int]$_.ProcessId -eq 11916 })) {
        Add-P 13000 11916 "python.exe" 'C:\Python312\python.exe -m uvicorn main:app --port 666'
        $script:listen = @(13000)
        $script:calls.Add("respawned")
    }
}
$n = Stop-InstallService
"n=$n"
"order=$($script:killed -join ',')"
"left=$(($script:procs.ToArray() | ForEach-Object { $_.ProcessId } | Sort-Object) -join ',')"
"calls=$($script:calls -join ',')"
''', tmp_path)
    order = [int(x) for x in re.search(r"order=([0-9,]+)", out).group(1).split(",")]
    assert order.index(11916) < order.index(19544) < order.index(23376), "先殺迴圈再殺服務：" + out
    assert "respawned" not in out, "迴圈先死 ⇒ 殺服務時不會再長出新的：" + out
    assert "n=12" in out
    left = _ids(out, "left")
    assert left == {4, 1620, 16944}, "只剩 System／services／cloudflared：" + out


@needs_ps
def test_all_loops_die_in_one_batch_before_any_service_so_a_surviving_loop_cannot_grab_the_port(tmp_path):
    """T83 正式機實證（23:45:01）：逐一結束迴圈時，還活著的迴圈在 port 一釋放就用舊程式把 uvicorn 拉起。
    替身：服務（23376）被殺時只要還有任何一個迴圈活著，就立刻長出新的 uvicorn。正對照：先殺服務再殺迴圈，替身確實會重生。"""
    hook = r'''
function Stop-Process-Hook($id) {
    $loopAlive = @($script:procs.ToArray() | Where-Object { $_.Name -eq "cmd.exe" -and $_.CommandLine -match 'autostart[a-z0-9_-]*\.bat' })
    if ($id -eq 23376 -and $loopAlive.Count -gt 0) {
        Add-P 13000 $loopAlive[0].ProcessId "python.exe" 'C:\Python312\python.exe -m uvicorn main:app --port 666'
        $script:listen = @(13000)
        $script:calls.Add("respawned")
    }
}
'''
    ctrl = _run_ps(_PROD_CHAIN + _ZOMBIES + hook + r'''
Stop-Process -Id 23376
"calls=$($script:calls -join ',')"
''', tmp_path)
    assert "respawned" in ctrl, "正對照：替身要能重現「先殺服務、迴圈還活著 ⇒ 被拉起」：" + ctrl
    out = _run_ps(_PROD_CHAIN + _ZOMBIES + hook + r'''
$n = Stop-InstallService
"batches=$($script:batches -join ',')"
"order=$($script:killed -join ',')"
"calls=$($script:calls -join ',')"
"left=$(($script:procs.ToArray() | ForEach-Object { $_.ProcessId } | Sort-Object) -join ',')"
''', tmp_path)
    assert "respawned" not in out, "迴圈要一次全殺完才碰服務：" + out
    batches = [int(x) for x in re.search(r"batches=([0-9,]+)", out).group(1).split(",")]
    assert batches[0] == len(_PROD_LOOPS.split(",")), "第一個 Stop-Process 呼叫就要帶全部迴圈：" + out
    order = [int(x) for x in re.search(r"order=([0-9,]+)", out).group(1).split(",")]
    first_service = min(order.index(i) for i in (19544, 23376))
    assert all(order.index(int(i)) < first_service for i in _PROD_LOOPS.split(",")), out
    assert _ids(out, "left") == {4, 1620, 16944}, out


_TASK_PS = r'''
$AutostartTaskName = "MotrixAutostart"
$script:taskState = "Ready"
$script:taskOps = New-Object System.Collections.Generic.List[string]
function Get-ScheduledTask { param($TaskName) [pscustomobject]@{ TaskName = $TaskName; State = $script:taskState } }
function Disable-ScheduledTask { param($TaskName) $script:taskOps.Add("disable"); $script:taskState = "Disabled" }
function Enable-ScheduledTask { param($TaskName) $script:taskOps.Add("enable"); $script:taskState = "Ready" }
'''


@needs_ps
def test_scheduled_task_is_disabled_while_stopping_and_restored_exactly_once(tmp_path):
    out = _run_ps(_TASK_PS + _PROD_CHAIN + r'''
$null = Stop-InstallService -ListOnly
"after_list=$($script:taskOps -join ',')"
$n = Stop-InstallService
"after_stop=$($script:taskOps -join ',')|state=$($script:taskState)"
$n = Stop-InstallService
"after_second_stop=$($script:taskOps -join ',')"
Restore-AutostartTask
Restore-AutostartTask
"after_restore=$($script:taskOps -join ',')|state=$($script:taskState)"
''', tmp_path, funcs=("Stop-InstallService", "Suspend-AutostartTask", "Restore-AutostartTask"))
    assert re.search(r"^after_list=$", out, re.M), "-ListOnly 不動排程工作：" + out
    assert "after_stop=disable|state=Disabled" in out, out
    assert re.search(r"^after_second_stop=disable$", out, re.M), "再停一次不重複停用：" + out
    assert "after_restore=disable,enable|state=Ready" in out, "恢復只做一次：" + out


@needs_ps
def test_scheduled_task_that_was_already_disabled_is_left_alone(tmp_path):
    out = _run_ps(_TASK_PS + r'''
$script:taskState = "Disabled"
Suspend-AutostartTask
Restore-AutostartTask
"ops=$($script:taskOps -join ',')|state=$($script:taskState)"
''', tmp_path, funcs=("Suspend-AutostartTask", "Restore-AutostartTask"))
    assert "ops=|state=Disabled" in out, "管理者本來就停用的不要替他啟用：" + out


def test_restore_happens_before_start_and_on_every_exit_in_all_three_scripts():
    for n in ("apply_update.ps1", "apply_module_update.ps1", "rollback_update.ps1"):
        s = _src(n)
        for fn in ("Suspend-AutostartTask", "Restore-AutostartTask", "Start-InstallService", "Exit-InstallLock"):
            assert _fn(s, fn), (n, fn)
        assert _fn(s, "Start-InstallService").split(chr(10))[1].strip().startswith("Restore-AutostartTask"), n
        assert "Restore-AutostartTask" in _fn(s, "Exit-InstallLock"), n
        assert "Suspend-AutostartTask" in _fn(s, "Stop-InstallService"), n
    parts = [(_fn(_src(n), "Suspend-AutostartTask"), _fn(_src(n), "Restore-AutostartTask"), _fn(_src(n), "Exit-InstallLock"), _fn(_src(n), "Start-InstallService"))
             for n in ("apply_update.ps1", "apply_module_update.ps1", "rollback_update.ps1")]
    assert parts[0] == parts[1] == parts[2], "四個函式在三支腳本逐字相同"


@needs_ps
def test_converges_when_a_hidden_launcher_creates_a_new_loop_right_after_the_kill(tmp_path):
    """殺掉 guard 迴圈的當下，排程工作又長出一個新的 guard＋服務（guard 的 netstat 檢查與停服競態）⇒ 第二輪要認出並殺掉。"""
    out = _run_ps(_PROD_CHAIN + r'''
$script:once = $false
function Stop-Process-Hook($id) {
    if ($id -eq 11916 -and -not $script:once) {
        $script:once = $true
        Add-P 14000 16944 "cmd.exe" $guardCmd
        Add-P 14100 14000 "python.exe" 'C:\Python312\python.exe -m uvicorn main:app --port 666'
        $script:listen = @(14100)
    }
}
$n = Stop-InstallService
"left=$(($script:procs.ToArray() | ForEach-Object { $_.ProcessId } | Sort-Object) -join ',')"
"killed=$($script:killed -join ',')"
''', tmp_path)
    assert _ids(out, "left") == {4, 1620, 16944}, out
    assert 14000 in _ids(out, "killed") and 14100 in _ids(out, "killed"), out


@needs_ps
def test_unattributable_autostart_cmd_is_warned_not_killed(tmp_path):
    """命令列含 autostart*.bat 但不在本安裝路徑、也不在 listener 鏈上（別的安裝／相對路徑啟動的殭屍）⇒ 不動它，但要大聲說有它。"""
    out = _run_ps(_OTHER_INSTALL + r'''
Add-P 5100 90000 "cmd.exe" '"C:\Windows\System32\cmd.exe" /c autostart_guard.bat'
$n = Stop-InstallService
"n=$n killed=$($script:killed.Count) calls=$($script:calls -join ',')"
''', tmp_path)
    assert "n=0 killed=0 calls=warn" in out, out


@needs_ps
def test_never_kills_itself_or_its_ancestors_even_when_run_under_a_loop(tmp_path):
    """apply 若是從迴圈底下開的主控台執行：自己（$PID）與祖先（迴圈 cmd）不殺，其餘照殺，並警告。"""
    out = _run_ps(_PROD_CHAIN + r'''
Add-P $PID 11916 "powershell.exe" 'powershell -File apply_update.ps1'
$n = Stop-InstallService
"killed=$($script:killed -join ',')"
"self=$PID"
"calls=$($script:calls -join ',')"
''', tmp_path)
    killed = _ids(out, "killed")
    me = int(re.search(r"self=(\d+)", out).group(1))
    assert me not in killed and 11916 not in killed, "不殺自己與祖先：" + out
    assert {19544, 23376} <= killed, "服務行程照殺：" + out
    assert "warn" in out.split("calls=")[1]


@needs_ps
@pytest.mark.parametrize("backend_spelling", [
    r"C:\Users\Motrix\Desktop\V9.0\backend\\",                    # 結尾反斜線
    r"c:\USERS\motrix\desktop\v9.0\backend",                       # 大小寫不同
    r"C:\Users\Motrix\Desktop\V9.0\tools\..\backend",             # 含 .. 的寫法
])
def test_backend_dir_spelling_does_not_change_which_loops_are_found(tmp_path, backend_spelling):
    out = _run_ps(_PROD_CHAIN + _ZOMBIES + _OTHER_INSTALL + "\n$BackendDir = '%s'\n" % backend_spelling + _LIST, tmp_path)
    assert _ids(out, "loops") == {int(x) for x in _PROD_LOOPS.split(",")}, out


@needs_ps
def test_short_8dot3_path_in_the_command_line_is_matched(tmp_path):
    """命令列用短檔名（C:\\PROGRA~1\\…），$BackendDir 是長路徑：靠 FileSystemObject 取出短路徑變體；磁碟沒開 8.3 時跳過。"""
    long_dir = tmp_path / "A Long Install Directory" / "backend"
    long_dir.mkdir(parents=True)
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    ctypes.windll.kernel32.GetShortPathNameW(str(long_dir), buf, 1024)
    short = buf.value
    if not short or short.lower() == str(long_dir).lower():
        pytest.skip("這個磁碟沒有 8.3 短檔名")
    out = _run_ps(r'''
Add-P 11916 16944 "cmd.exe" '"C:\Windows\System32\cmd.exe" /c "@@SHORT@@\autostart_guard.bat"'
$BackendDir = '@@LONG@@'
'''.replace("@@SHORT@@", short).replace("@@LONG@@", str(long_dir)) + _LIST, tmp_path)
    assert _ids(out, "loops") == {11916}, out


@needs_ps
def test_non_python_listener_is_not_killed(tmp_path):
    out = _run_ps(r'''
Add-P 800 4 "System" $null
Add-P 900 800 "nginx.exe" 'C:\nginx\nginx.exe'
$script:listen = @(900)
$n = Stop-InstallService
"n=$n killed=$($script:killed.Count) calls=$($script:calls -join ',')"
''', tmp_path)
    assert "n=0 killed=0" in out and "warn" in out, "port 被別的程式佔用 ⇒ 只警告，不動它：" + out


@needs_ps
def test_test_install_service_running_uses_the_same_target_rules(tmp_path):
    funcs = ("Stop-InstallService", "Test-InstallServiceRunning")
    out = _run_ps(_OTHER_INSTALL + '"other=$(Test-InstallServiceRunning)"\n', tmp_path, funcs)
    assert "other=False" in out, "別的安裝路徑的迴圈不算我們的"
    out = _run_ps(_PROD_CHAIN + '"chain=$(Test-InstallServiceRunning)"\n', tmp_path, funcs)
    assert "chain=True" in out
    out = _run_ps(_PROD_CHAIN + _ZOMBIES + '$null = Stop-InstallService\n"after=$(Test-InstallServiceRunning)"\n', tmp_path, funcs)
    assert "after=False" in out
    # 只有殭屍迴圈（沒有任何服務在聽）也算「還有東西會把服務拉回來」
    guard_only = _PROD_CHAIN.split("Add-P 4 0")[0]          # 只取 $B／$guardCmd 兩行，不建服務行程
    out = _run_ps(guard_only + _ZOMBIES + '"zombie_only=$(Test-InstallServiceRunning)"\n', tmp_path, funcs)
    assert "zombie_only=True" in out


_RESPAWN_FUNCS = ("Stop-InstallService", "Test-InstallServiceRunning", "Wait-PortFreed", "Write-InstallServiceDiag", "Stop-RespawnedService")


@needs_ps
def test_stop_respawned_service_noop_when_clean(tmp_path):
    out = _run_ps(r'''
$script:RespawnDetected = $false
$r = Stop-RespawnedService "複製後"
"result=$r detected=$($script:RespawnDetected) killed=$($script:killed.Count)"
''', tmp_path, _RESPAWN_FUNCS)
    assert "result=False detected=False killed=0" in out and "::NOTE::" not in out


@needs_ps
def test_stop_respawned_service_finds_and_stops_zombie_loops_and_reports_evidence(tmp_path):
    out = _run_ps(_PROD_CHAIN + _ZOMBIES + r'''
$script:RespawnDetected = $false
function Info($m) { Write-Host $m }
$r = Stop-RespawnedService "停服後"
"result=$r detected=$($script:RespawnDetected) left=$(($script:procs.ToArray() | ForEach-Object { $_.ProcessId } | Sort-Object) -join ',')"
''', tmp_path, _RESPAWN_FUNCS)
    assert "result=True detected=True" in out and "::NOTE:: respawn_detected stage=停服後" in out
    assert "respawn_unresolved" not in out
    assert _ids(out, "left") == {4, 1620, 16944}
    assert "PID 23148 | cmd.exe" in out and "父行程已不在" in out, "要印出 PID／父行程／建立時間（事後找啟動器的證據）"


@needs_ps
def test_stop_respawned_service_is_bounded_and_says_so_when_nothing_can_be_killed(tmp_path):
    out = _run_ps(_PROD_CHAIN + r'''
$script:RespawnDetected = $false
function Stop-Process { param($Id) foreach ($one in @($Id)) { $script:killed.Add([int]$one) } }   # 殺不掉（權限不足）；一次可帶多個 PID
$r = Stop-RespawnedService "啟動前"
"result=$r killed=$($script:killed.Count)"
''', tmp_path, _RESPAWN_FUNCS)
    assert "::NOTE:: respawn_unresolved stage=啟動前" in out and "result=True" in out


# ── Invoke-PyTimed（真的跑 python） ──────────────────────────────────────────

@needs_ps
def test_invoke_py_timed_returns_output_exit_code_and_kills_on_timeout(tmp_path):
    py = sys.executable.replace("'", "''")
    out = _run_ps(r'''
$BackendDir = '@@TMP@@'
$r = Invoke-PyTimed @("-c", "print('hello-t84')") 60 '@@PY@@'
"ok_text=$($r.Text.Trim()) exit=$($r.Exit) timedout=$($r.TimedOut)"
$r = Invoke-PyTimed @("-c", "import sys; sys.exit(3)") 60 '@@PY@@'
"exit3=$($r.Exit)"
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$r = Invoke-PyTimed @("-c", "import time; time.sleep(120)") 2 '@@PY@@'
"timedout=$($r.TimedOut) fast=$($sw.Elapsed.TotalSeconds -lt 30)"
'''.replace("@@TMP@@", str(tmp_path)).replace("@@PY@@", py), tmp_path, ("Invoke-PyTimed",))
    assert "ok_text=hello-t84 exit=0 timedout=False" in out and "exit3=3" in out
    assert "timedout=True fast=True" in out


# ── Invoke-SchemaVerify：工具輸出 → 狀態 ─────────────────────────────────────

@needs_ps
@pytest.mark.parametrize("text,state", [
    ("note x\nSCHEMA_VERIFY_OK\n", "ok"),
    ("  （demo 庫，只警告）p：模組 core 庫內版號 12，這份程式登記到 14\nSCHEMA_VERIFY_DEMO_BEHIND 1\nSCHEMA_VERIFY_OK\n", "ok"),
    ("  p：模組 core 庫內版號 12，這份程式登記到 14\nSCHEMA_VERIFY_MISMATCH 1\n", "mismatch"),
    ("Traceback ...\nModuleNotFoundError\n", "unverifiable"),
    ("SCHEMA_VERIFY_UNVERIFIABLE RuntimeError: 舊包\n", "unverifiable"),
    ("timeout after 120s", "unverifiable"),
])
def test_invoke_schema_verify_maps_tool_output_to_state(tmp_path, text, state):
    backend = tmp_path / "backend"
    (backend / "tools").mkdir(parents=True)
    (backend / "tools" / "migrate_like_startup.py").write_text("# stub", encoding="utf-8")
    (backend / "motrix_erp.db").write_bytes(b"")
    (backend / "motrix_erp_demo.db").write_bytes(b"")
    out = _run_ps(r'''
$BackendDir = '@@B@@'
function Invoke-PyTimed([string[]]$PyArgs, [int]$TimeoutSec = 120, [string]$Python = "python") { $script:lastArgs = $PyArgs -join ' '; return @{ Text = @'
@@T@@
'@; Exit = 0; TimedOut = $false } }
$v = Invoke-SchemaVerify
"state=$($v.State)"
"args=$script:lastArgs"
'''.replace("@@B@@", str(backend)).replace("@@T@@", text), tmp_path, ("Invoke-SchemaVerify",))
    assert "state=%s\n" % state in out, out
    assert "--verify-schema" in out and out.count("--db") == 2, "主庫在前、demo 在後"
    assert out.index("motrix_erp.db") < out.index("motrix_erp_demo.db")


@needs_ps
def test_invoke_schema_verify_without_tool_or_db_is_unverifiable_not_ok(tmp_path):
    backend = tmp_path / "backend"
    (backend / "tools").mkdir(parents=True)
    body = r'''
$BackendDir = '@@B@@'
$v = Invoke-SchemaVerify
"state=$($v.State) text=$($v.Text)"
'''.replace("@@B@@", str(backend))
    out = _run_ps(body, tmp_path, ("Invoke-SchemaVerify",))
    assert "state=unverifiable" in out and "tool_missing" in out
    (backend / "tools" / "migrate_like_startup.py").write_text("# stub", encoding="utf-8")
    out = _run_ps(body, tmp_path, ("Invoke-SchemaVerify",))
    assert "state=unverifiable" in out and "no_db" in out


# ── Get-ServiceStartedBeforeCopy ────────────────────────────────────────────

@needs_ps
def test_service_started_before_copy_done_is_flagged(tmp_path):
    body = r'''
function Get-NetTCPConnection { [pscustomobject]@{ OwningProcess = [uint32]100 } }
function Get-CimInstance { param($ClassName, $Filter) [pscustomobject]@{ Name = "python.exe"; CreationDate = (Get-Date).AddSeconds(@@OFFSET@@) } }
$script:CopyDoneTime = @@DONE@@
$r = Get-ServiceStartedBeforeCopy
"r=[$r]"
'''
    out = _run_ps(body.replace("@@OFFSET@@", "-30").replace("@@DONE@@", "Get-Date"), tmp_path, ("Get-ServiceStartedBeforeCopy",))
    assert "r=[PID 100" in out, "比複製完成早 30 秒 ⇒ 是停服後被拉起、與複製重疊的那個：" + out
    out = _run_ps(body.replace("@@OFFSET@@", "30").replace("@@DONE@@", "Get-Date"), tmp_path, ("Get-ServiceStartedBeforeCopy",))
    assert "r=[]" in out, "複製完成之後才起來 ⇒ 正常"
    out = _run_ps(body.replace("@@OFFSET@@", "-30").replace("@@DONE@@", "$null"), tmp_path, ("Get-ServiceStartedBeforeCopy",))
    assert "r=[]" in out, "還沒到複製完成（CopyDoneTime 未設）⇒ 不判"


# ── Invoke-SchemaGate：每條分支 ─────────────────────────────────────────────

def _gate(tmp_path, verifies, early="$null", restart_ok="$true"):
    seq = "\n".join('$script:vq.Enqueue(@{ State = "%s"; Text = "%s" })' % v for v in verifies)
    return _run_ps(r'''
$script:vq = New-Object System.Collections.Queue
@@SEQ@@
$script:early = @@EARLY@@
$script:restartOk = @@RESTART@@
function Invoke-SchemaVerify { return $script:vq.Dequeue() }
function Get-ServiceStartedBeforeCopy { return $script:early }
function Restart-InstallServiceAndWait { $script:calls.Add("restart"); return $script:restartOk }
$r = Invoke-SchemaGate
"healthy=$($r.Healthy) schema=$($r.Schema) fail=$([bool]$r.FailMsg) calls=$($script:calls -join ',')"
if ($r.FailMsg) { "msg=$($r.FailMsg)" }
'''.replace("@@SEQ@@", seq).replace("@@EARLY@@", early).replace("@@RESTART@@", restart_ok), tmp_path, ("Invoke-SchemaGate",))


@needs_ps
def test_gate_ok_does_not_restart(tmp_path):
    out = _gate(tmp_path, [("ok", "SCHEMA_VERIFY_OK")])
    assert "healthy=True schema=ok fail=False calls=ok" in out and "restart" not in out


@needs_ps
def test_gate_demo_behind_only_warns(tmp_path):
    out = _gate(tmp_path, [("ok", "SCHEMA_VERIFY_DEMO_BEHIND 1 SCHEMA_VERIFY_OK")])
    assert "healthy=True schema=ok fail=False" in out and "calls=warn,ok" in out and "restart" not in out


@needs_ps
def test_gate_unverifiable_only_warns_and_does_not_restart(tmp_path):
    out = _gate(tmp_path, [("unverifiable", "timeout after 120s")])
    assert "healthy=True schema=unverifiable fail=False calls=warn" in out and "restart" not in out


@needs_ps
def test_gate_mismatch_then_restart_fixes_it(tmp_path):
    out = _gate(tmp_path, [("mismatch", "m"), ("ok", "SCHEMA_VERIFY_OK")])
    assert "healthy=True schema=ok_after_restart fail=False" in out and "restart" in out


@needs_ps
def test_gate_mismatch_survives_restart_fails_without_rollback(tmp_path):
    out = _gate(tmp_path, [("mismatch", "m"), ("mismatch", "m")])
    assert "healthy=True schema=mismatch_after_restart fail=True" in out and "不自動回滾" in out
    assert "restart" in out.split("calls=")[1].splitlines()[0], "重啟過一次才判定失敗，不是第一次不一致就放棄"


@needs_ps
def test_gate_restart_unhealthy_fails_without_rollback_and_reports_down(tmp_path):
    out = _gate(tmp_path, [("mismatch", "m")], restart_ok="$false")
    assert "healthy=False schema=restart_unhealthy fail=True" in out and "不自動回滾" in out


@needs_ps
def test_gate_service_older_than_copy_restarts_even_when_schema_looks_fine(tmp_path):
    """沒有新 migration 的版本，schema 檢查看不出來；行程早於複製完成本身就是證據。"""
    out = _gate(tmp_path, [("ok", "SCHEMA_VERIFY_OK"), ("ok", "SCHEMA_VERIFY_OK")], early='"PID 100 earlier"')
    assert "restart" in out and "schema=ok_after_restart" in out and "fail=False" in out


@needs_ps
def test_gate_after_restart_unverifiable_is_warning_only(tmp_path):
    out = _gate(tmp_path, [("mismatch", "m"), ("unverifiable", "x")])
    assert "schema=unverifiable_after_restart fail=False" in out


# ── python 工具：唯讀比對 ────────────────────────────────────────────────────

def _make_db(path, versions, wal=False):
    conn = sqlite3.connect(str(path))
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE module_schema_versions (module TEXT PRIMARY KEY, version INTEGER NOT NULL, applied_at TEXT)")
    for m, v in versions.items():
        conn.execute("INSERT INTO module_schema_versions VALUES (?,?,'x')", (m, v))
    conn.commit()
    conn.close()


@pytest.fixture
def tool(monkeypatch):
    mod = _tool()
    from helpers import module_startup
    from core import migrations
    monkeypatch.setattr(module_startup, "load_modules_like_startup", lambda db_path=None: [])
    monkeypatch.setattr(mod, "has_module_startup", lambda backend=None: True)
    monkeypatch.setattr(migrations, "registered", lambda: {"core": [1, 2, 3, 4], "case": [1, 2], "empty": []})
    return mod


def test_verify_schema_ok_when_db_reaches_registered_top(tool, tmp_path):
    p = tmp_path / "a.db"
    _make_db(p, {"core": 4, "case": 2})
    assert tool.verify_schema([str(p)]) == ([], [], [])


def test_verify_schema_mismatch_lists_every_module_behind(tool, tmp_path):
    p = tmp_path / "a.db"
    _make_db(p, {"core": 2})            # core 落後；case 根本沒有列 ⇒ 0
    mism, demo, notes = tool.verify_schema([str(p)])
    assert sorted((m, got, top) for _p, m, got, top in mism) == [("case", 0, 2), ("core", 2, 4)]
    assert demo == [] and notes == []


def test_verify_schema_db_ahead_of_code_is_a_note_not_a_mismatch(tool, tmp_path):
    p = tmp_path / "a.db"
    _make_db(p, {"core": 9, "case": 2})
    mism, demo, notes = tool.verify_schema([str(p)])
    assert mism == [] and demo == [] and len(notes) == 1 and "core" in notes[0]


def test_verify_schema_main_db_behind_is_mismatch_but_demo_behind_only_warns(tool, tmp_path, capsys):
    ok, behind = tmp_path / "ok.db", tmp_path / "demo.db"
    _make_db(ok, {"core": 4, "case": 2})
    _make_db(behind, {"core": 3, "case": 2})
    mism, demo, _ = tool.verify_schema([str(ok), str(behind)])
    assert mism == [] and [(Path(p).name, m) for p, m, _g, _t in demo] == [("demo.db", "core")]
    assert tool.main(["--verify-schema", "--db", str(ok), "--db", str(behind)]) == 0
    out = capsys.readouterr().out
    assert "SCHEMA_VERIFY_DEMO_BEHIND 1" in out and "SCHEMA_VERIFY_OK" in out
    # 反過來：主庫落後 ⇒ 不一致（即使 demo 到位）
    assert tool.main(["--verify-schema", "--db", str(behind), "--db", str(ok)]) == 3


def test_verify_schema_is_read_only_and_never_creates_a_db(tool, tmp_path):
    p = tmp_path / "a.db"
    _make_db(p, {"core": 2, "case": 2})
    before = p.read_bytes()
    tool.verify_schema([str(p)])
    assert p.read_bytes() == before
    missing = tmp_path / "nope.db"
    with pytest.raises(sqlite3.OperationalError):
        tool.verify_schema([str(missing)])
    assert not missing.exists(), "唯讀開啟不可以建出一個空庫"


def test_read_versions_ro_only_swallows_missing_table(tool, tmp_path):
    empty = tmp_path / "empty.db"
    c = sqlite3.connect(str(empty))
    c.execute("CREATE TABLE other (x)")
    c.commit()
    c.close()
    assert tool._read_versions_ro(str(empty)) == {}, "沒有 module_schema_versions 表＝一個 migration 都沒跑"
    garbage = tmp_path / "garbage.db"
    garbage.write_bytes(b"this is not a database" * 100)
    with pytest.raises(sqlite3.DatabaseError):
        tool._read_versions_ro(str(garbage))


def test_read_versions_ro_locked_db_is_unverifiable_not_zeroes(tool, tmp_path):
    p = tmp_path / "locked.db"
    _make_db(p, {"core": 4, "case": 2})
    writer = sqlite3.connect(str(p), isolation_level=None)
    try:
        writer.execute("BEGIN EXCLUSIVE")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            tool._read_versions_ro(str(p), timeout=0.2)
    finally:
        writer.execute("ROLLBACK")
        writer.close()


def test_read_versions_ro_reads_a_live_wal_db(tool, tmp_path):
    p = tmp_path / "wal.db"
    _make_db(p, {"core": 4, "case": 2}, wal=True)
    writer = sqlite3.connect(str(p))
    try:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("UPDATE module_schema_versions SET version=5 WHERE module='core'")
        writer.commit()                                  # 變更還在 -wal 檔裡、沒有 checkpoint
        assert tool._read_versions_ro(str(p)) == {"core": 5, "case": 2}
    finally:
        writer.close()


def test_main_exit_codes_and_markers(tool, tmp_path, capsys):
    good, bad = tmp_path / "g.db", tmp_path / "b.db"
    _make_db(good, {"core": 4, "case": 2})
    _make_db(bad, {"core": 2, "case": 2})
    assert tool.main(["--verify-schema", "--db", str(good)]) == 0
    assert "SCHEMA_VERIFY_OK" in capsys.readouterr().out
    assert tool.main(["--verify-schema", "--db", str(bad)]) == 3
    out = capsys.readouterr().out
    assert "SCHEMA_VERIFY_MISMATCH 1" in out and "模組 core 庫內版號 2，這份程式登記到 4" in out
    assert tool.main(["--verify-schema", "--db", str(tmp_path / "nope.db")]) == 4
    assert "SCHEMA_VERIFY_UNVERIFIABLE" in capsys.readouterr().out


def test_old_package_without_module_startup_is_unverifiable_not_ok(monkeypatch, tmp_path, capsys):
    mod = _tool()
    monkeypatch.setattr(mod, "has_module_startup", lambda backend=None: False)
    p = tmp_path / "a.db"
    _make_db(p, {"core": 1})
    assert mod.main(["--verify-schema", "--db", str(p)]) == 4
    assert "SCHEMA_VERIFY_UNVERIFIABLE" in capsys.readouterr().out


def test_verify_schema_does_not_run_init_db(tool, tmp_path, monkeypatch):
    import db
    monkeypatch.setattr(db, "init_db", lambda *a, **k: (_ for _ in ()).throw(AssertionError("--verify-schema 不可以跑 init_db")))
    p = tmp_path / "a.db"
    _make_db(p, {"core": 4, "case": 2})
    assert tool.main(["--verify-schema", "--db", str(p)]) == 0


# ── 真實路徑：不 mock 載入器與 migration 登記（子行程跑真的工具） ─────────────────

def test_real_tool_full_run_then_verify_ok_then_mismatch_when_core_is_rolled_back(tmp_path):
    """T82 的形狀：庫的 core 版號比程式登記的低 ⇒ --verify-schema 要報不一致（exit 3）；到位時 exit 0；全程不寫庫。"""
    db_path = tmp_path / "t84.db"
    env = dict(os.environ, PYTHONUTF8="1")
    tool = str(_TOOLS / "migrate_like_startup.py")

    def run(*args):
        return subprocess.run([sys.executable, tool, *args], capture_output=True, text=True, encoding="utf-8", env=env, timeout=600)

    r = run("--db", str(db_path))
    assert r.returncode == 0, r.stdout + r.stderr
    r = run("--verify-schema", "--db", str(db_path))
    assert r.returncode == 0 and "SCHEMA_VERIFY_OK" in r.stdout, r.stdout + r.stderr
    conn = sqlite3.connect(str(db_path))
    top = conn.execute("SELECT version FROM module_schema_versions WHERE module='core'").fetchone()
    assert top and top[0] >= 3, "core 要有 migration 登記，否則這題驗不到東西：%r" % (top,)
    conn.execute("UPDATE module_schema_versions SET version = version - 2 WHERE module='core'")
    conn.commit()
    conn.close()
    before = db_path.read_bytes()
    r = run("--verify-schema", "--db", str(db_path))
    assert r.returncode == 3 and "SCHEMA_VERIFY_MISMATCH" in r.stdout and "模組 core" in r.stdout, r.stdout + r.stderr
    assert db_path.read_bytes() == before, "--verify-schema 不可寫庫"
