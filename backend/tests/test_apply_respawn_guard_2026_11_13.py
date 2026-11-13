# -*- coding: utf-8 -*-
"""T82 事故（2026-11-13）：停服後服務被拉回來／第一次啟動讀到半新半舊的程式，core migration 13／14 沒跑而 ping 照過。

T84 修法（本檔逐一釘住）：
① `apply_update.ps1` 複製完成後、啟動前各掃一次（Stop-RespawnedService）：有服務在跑 ⇒ 再停；
② 健檢通過後用**已安裝的新程式**唯讀比對「庫內 module_schema_versions」與「程式登記的最高 migration 版號」
   （`tools/migrate_like_startup.py --verify-schema` ＋ ps1 的 Invoke-SchemaVerify）：不一致 ⇒ 重啟一次再驗；
   仍不一致 ⇒ `unhealthy_not_rolled_back`（**不自動回滾**，回滾會還原資料庫）；驗不到 ⇒ 只警告。

🔴 這份測試**驗不到**「autostart 迴圈真的在殺掉服務後 5 秒拉起、與 robocopy 重疊」這件事——那段沒有真實環境可測：
   本檔只測腳本結構（順序、出口）、ps1 函式在替身下的分支、以及 python 檢查工具的判定。
"""
import importlib.util
import json
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


# ── ① 結構：順序與出口 ──────────────────────────────────────────────────────

def test_respawn_scan_runs_after_copy_and_before_every_start():
    t = _src()
    i_applied = t.index('$script:ProdState = "applied"')
    i_scan1 = t.index('Stop-RespawnedService "複製後"')
    i_pip = t.index("[4/6] 安裝/更新 Python 依賴")
    i_scan2 = t.index('Stop-RespawnedService "啟動前"')
    i_start = t.index("[4b/6] 重新啟動服務")
    assert i_applied < i_scan1 < i_pip < i_scan2 < i_start, "複製完成（新程式碼完整在磁碟上）之後掃一次、啟動之前再掃一次"
    assert t.count("Stop-RespawnedService \"") == 2, "只在這兩處呼叫；其他位置（回滾路徑）不該被這個掃描影響"
    assert t.index("function Stop-RespawnedService") < i_scan1, "函式要先定義"


def test_schema_verify_sits_between_health_loop_and_log_scan_and_never_auto_rolls_back():
    t = _src()
    i_loop = t.index("[5/6] 等待伺服器恢復並健康檢查")
    i_block = t.index("$schemaVerify = \"skipped\"")
    i_log = t.index("\n$logErrors = @()\n")
    assert i_loop < i_block < i_log, "要在讀 log 之前（它可能重啟服務，之後讀到的才是最後一次啟動）"
    block = t[i_block:i_log]
    assert "Restart-InstallServiceAndWait" in block and "Invoke-SchemaVerify" in block
    assert block.count("Invoke-SchemaVerify") == 2, "第一次＋重啟後再驗一次，不是迴圈"
    assert '"unhealthy_not_rolled_back"' in block, "重啟後仍不一致 ⇒ 用既有出口值（儀表板值域封閉，沒有新值）"
    for bad in ("robocopy", "Backup-Databases", "rollbackDir", "Restore-"):
        assert bad not in block, "不一致不可以在這裡就回滾／動資料庫：%s" % bad
    # 驗不到（工具缺／當掉）只警告，不 Fail：外層 elseif（ok／其餘）之後不得再有 Fail
    assert "Fail " not in block.split('elseif ($sv.State -eq "ok")')[-1]


def test_script_still_parses_and_version_registered():
    if _PS:
        cmd = ('$e=$null;$t=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('
               '"%s",[ref]$t,[ref]$e);$e.Count' % (_TOOLS / "apply_update.ps1"))
        r = subprocess.run([_PS, "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=120)
        assert r.stdout.strip() == "0", r.stdout + r.stderr
    reg = json.loads((_TOOLS / "apply_update.version.json").read_text(encoding="utf-8-sig"))
    assert reg["version"] == "2026-11-13c"
    assert '$ApplyScriptVersion = "2026-11-13c"' in _src()


# ── ① ps1 函式在替身下實跑 ──────────────────────────────────────────────────

def _run_ps(body, tmp_path):
    t = _src()
    funcs = "\n".join(_fn(t, n) for n in ("Wait-PortFreed", "Stop-RespawnedService", "Invoke-SchemaVerify", "Restart-InstallServiceAndWait"))
    prelude = r'''
$ErrorActionPreference = "Stop"
$Port = 666
$PingUrl = "http://127.0.0.1:666/api/ping"
$script:calls = New-Object System.Collections.Generic.List[string]
function Warn($m) { $script:calls.Add("warn") }
function Info($m) { }
function Start-Sleep { }
function Get-NetTCPConnection { return $null }
function Stop-InstallService { $script:calls.Add("stop"); return 1 }
function Start-InstallService { $script:calls.Add("start") }
function Test-Ping { param($Url, $TimeoutSec) return $true }
'''
    ps1 = tmp_path / "t.ps1"
    ps1.write_bytes(b"\xef\xbb\xbf" + (prelude + funcs + "\n" + body).replace("\n", "\r\n").encode("utf-8"))
    r = subprocess.run([_PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


@needs_ps
def test_restart_helper_stops_then_starts_and_reports_health(tmp_path):
    out = _run_ps(r'''
$r = Restart-InstallServiceAndWait
"result=$r calls=$($script:calls -join ',')"
''', tmp_path)
    assert "result=True calls=stop,start" in out.replace("\r", ""), out


@needs_ps
def test_stop_respawned_service_noop_when_nothing_runs(tmp_path):
    out = _run_ps(r'''
$script:RespawnDetected = $false
function Test-InstallServiceRunning { return $false }
$r = Stop-RespawnedService "複製後"
"result=$r detected=$($script:RespawnDetected) calls=$($script:calls -join ',')"
''', tmp_path)
    assert "result=False detected=False calls=" in out and "stop" not in out.split("calls=")[-1]


@needs_ps
def test_stop_respawned_service_stops_once_when_it_runs_then_gone(tmp_path):
    out = _run_ps(r'''
$script:RespawnDetected = $false
$script:seq = @($true, $false)
$script:n = 0
function Test-InstallServiceRunning { $v = $script:seq[[Math]::Min($script:n, 1)]; $script:n++; return $v }
$r = Stop-RespawnedService "複製後"
"result=$r detected=$($script:RespawnDetected) calls=$($script:calls -join ',')"
''', tmp_path)
    assert "result=True detected=True calls=warn,stop" in out.replace("\r", ""), out
    assert "::NOTE:: respawn_detected stage=複製後" in out


@needs_ps
def test_stop_respawned_service_stops_twice_at_most_when_it_keeps_coming_back(tmp_path):
    out = _run_ps(r'''
$script:RespawnDetected = $false
function Test-InstallServiceRunning { return $true }
$r = Stop-RespawnedService "啟動前"
"result=$r calls=$($script:calls -join ',')"
''', tmp_path)
    tail = out.split("calls=")[-1].strip()
    assert tail == "warn,stop,warn,stop", "最多再停一次，不可無限迴圈：%s" % tail


@needs_ps
@pytest.mark.parametrize("text,state", [
    ("note x\nSCHEMA_VERIFY_OK\n", "ok"),
    ("  p：模組 core 庫內版號 12，這份程式登記到 14\nSCHEMA_VERIFY_MISMATCH 1\n", "mismatch"),
    ("Traceback ...\nModuleNotFoundError\n", "unverifiable"),
    ("SCHEMA_VERIFY_UNVERIFIABLE RuntimeError: 舊包\n", "unverifiable"),
])
def test_invoke_schema_verify_maps_tool_output_to_state(tmp_path, text, state):
    backend = tmp_path / "backend"
    (backend / "tools").mkdir(parents=True)
    (backend / "tools" / "migrate_like_startup.py").write_text("# stub", encoding="utf-8")
    (backend / "motrix_erp.db").write_bytes(b"")
    out = _run_ps(r'''
$BackendDir = "%s"
function Invoke-Py([string[]]$PyArgs) { $script:lastArgs = $PyArgs -join ' '; return @{ Text = @'
%s
'@; Exit = 0 } }
$v = Invoke-SchemaVerify
"state=$($v.State) args=$script:lastArgs"
''' % (str(backend), text), tmp_path)
    assert "state=%s " % state in out, out
    assert "--verify-schema" in out and "--db" in out


@needs_ps
def test_invoke_schema_verify_without_tool_or_db_is_unverifiable_not_ok(tmp_path):
    backend = tmp_path / "backend"
    (backend / "tools").mkdir(parents=True)
    out = _run_ps(r'''
$BackendDir = "%s"
$v = Invoke-SchemaVerify
"state=$($v.State)"
''' % str(backend), tmp_path)
    assert "state=unverifiable" in out
    (backend / "tools" / "migrate_like_startup.py").write_text("# stub", encoding="utf-8")
    out = _run_ps(r'''
$BackendDir = "%s"
$v = Invoke-SchemaVerify
"state=$($v.State) text=$($v.Text)"
''' % str(backend), tmp_path)
    assert "state=unverifiable" in out and "no_db" in out


# ── ② python 工具：唯讀比對 ─────────────────────────────────────────────────

def _make_db(path, versions):
    conn = sqlite3.connect(str(path))
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
    assert tool.verify_schema([str(p)]) == ([], [])


def test_verify_schema_mismatch_lists_every_module_behind(tool, tmp_path):
    p = tmp_path / "a.db"
    _make_db(p, {"core": 2})            # core 落後；case 根本沒有列 ⇒ 0
    mism, notes = tool.verify_schema([str(p)])
    assert sorted((m, got, top) for _p, m, got, top in mism) == [("case", 0, 2), ("core", 2, 4)]
    assert notes == []


def test_verify_schema_db_ahead_of_code_is_a_note_not_a_mismatch(tool, tmp_path):
    p = tmp_path / "a.db"
    _make_db(p, {"core": 9, "case": 2})
    mism, notes = tool.verify_schema([str(p)])
    assert mism == [] and len(notes) == 1 and "core" in notes[0]


def test_verify_schema_checks_every_db_given(tool, tmp_path):
    ok, behind = tmp_path / "ok.db", tmp_path / "behind.db"
    _make_db(ok, {"core": 4, "case": 2})
    _make_db(behind, {"core": 3, "case": 2})
    mism, _ = tool.verify_schema([str(ok), str(behind)])
    assert [(Path(p).name, m) for p, m, _g, _t in mism] == [("behind.db", "core")]


def test_verify_schema_is_read_only(tool, tmp_path):
    p = tmp_path / "a.db"
    _make_db(p, {"core": 2, "case": 2})
    before = p.read_bytes()
    tool.verify_schema([str(p)])
    assert p.read_bytes() == before
    missing = tmp_path / "nope.db"
    with pytest.raises(sqlite3.OperationalError):
        tool.verify_schema([str(missing)])
    assert not missing.exists(), "唯讀開啟不可以建出一個空庫"


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
