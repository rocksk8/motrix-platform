# -*- coding: utf-8 -*-
"""server.log 輪替 × 套用健康檢查的競態（2026-11-13，T81 正式機 #22② 實況；T83 工單 fix/log-rotate-boot-race）。

實況：套用後 `archive._daily_backup` 第一輪在**啟動後 30 秒**跑，第一件事是 `_rotate_server_log_if_large`；原檔 ≥50 MB ⇒
清成 0 byte、啟動行（`MOTRIX ERP starting`／`Uvicorn running on`／`模組 X 已載入`）搬去 `server.log.1`。
`apply_update.ps1`／`apply_module_update.ps1` 的健康檢查正好在這個時間窗內讀 server.log 的最後 200 行：
找不到本次啟動的起點（開關／模組載入驗不到）、或掃到空檔（錯誤掃描假綠）、模組更新路徑還可能假回滾。

修法三件（本檔逐一釘住）：
① 開機 120 秒內、或 `backend/.apply.lock` 在（未過期）時 archive 不輪替，延到下一個 tick；
② 共用 helper `Get-ServerLogTail`（apply_update／apply_module_update 逐字相同）：現行檔找不到啟動範圍就往前接 server.log.1；
   `_prod_health_facts.ps1`／`_dashboard_remote.ps1`（deploy_dashboard 的 log-tail）同樣往前讀 .1；
③ 步驟檔範本 #22② 接受 server.log／server.log.1／app.log（見 TEMPLATE-apply.md，本檔不測散文）。

「輪替發生在健檢窗口內」的證明方式：用**真的** `archive._rotate_server_log_if_large` 在開機後輪替一份含啟動行的 log，
再**實際執行** ps1 的函式讀它。修之前：helper 不存在 ⇒ 紅；對照組（舊的只讀 server.log）確實找不到啟動範圍 ⇒ 競態是真的。
"""
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import archive

_TOOLS = Path(__file__).resolve().parents[1] / "tools"
_PS = shutil.which("powershell.exe") or shutil.which("powershell")
needs_ps = pytest.mark.skipif(not _PS, reason="需要 Windows PowerShell（apply_update.ps1 的執行環境）")

BOOT = [
    "[2026/11/13 週五 10:13:20.10] MOTRIX ERP starting... ",
    "INFO:core.loader:模組 tender_radar 1.5.13 已載入",
    "INFO:     Started server process [4242]",
    "INFO:     Application startup complete.",
    "INFO:     Uvicorn running on https://0.0.0.0:666 (Press CTRL+C to quit)",
]
FILLER = ["old traffic line %05d padding padding padding padding" % i for i in range(400)]
AFTER = ["INFO:     later line %d" % i for i in range(5)]


def _write(path, lines):
    Path(path).write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))


def _src(name):
    return (_TOOLS / name).read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def _fn(text, name):
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("function %s" % name):
            for j in range(i + 1, len(lines)):
                if lines[j] == "}":
                    return "\n".join(lines[i:j + 1])
    return None


def _ps_run(tmp_path, body):
    script = tmp_path / "harness.ps1"
    script.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
    r = subprocess.run([_PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)], capture_output=True, timeout=90)
    out = r.stdout.decode("utf-8", "replace")
    line = [l for l in out.splitlines() if l.startswith("RESULT ")]
    assert r.returncode == 0 and line, (r.returncode, out, r.stderr.decode("utf-8", "replace"))
    return json.loads(line[-1][len("RESULT "):])


def _q(p):
    return str(p).replace("'", "''")


def _rotated_log_in_boot_window(tmp_path):
    """真的跑一次 archive 輪替：log 已含啟動行與一堆流量（超過門檻），輪替後現行檔只剩輪替後寫的幾行、啟動行在 .1。"""
    log = tmp_path / "logs" / "server.log"
    log.parent.mkdir(exist_ok=True)
    _write(log, FILLER + BOOT)      # 真實順序：啟動行是檔案最後面（剛啟動就輪替）
    assert archive._rotate_server_log_if_large(str(log), max_bytes=100, keep=3) is True
    assert log.stat().st_size == 0 and (tmp_path / "logs" / "server.log.1").exists()
    with open(log, "ab") as f:                       # 輪替後行程繼續寫
        f.write(("\r\n".join(AFTER) + "\r\n").encode("utf-8"))
    return log


def _tail_body(text, log, not_before=None):
    nb = "([datetime]'%s')" % not_before.strftime("%Y-%m-%d %H:%M:%S") if not_before else "$null"
    return "\n".join([
        "$ErrorActionPreference = 'Stop'",
        _fn(text, "Get-StartupRange"),
        _fn(text, "Get-ServerLogTail"),
        "$t = Get-ServerLogTail '%s' 200 %s" % (_q(log), nb),
        "$r = Get-StartupRange $t",
        "Write-Output ('RESULT ' + (@{ count = @($t).Count; boot = [bool]$r; last = [string]$t[-1] } | ConvertTo-Json -Compress))",
    ])


# ── ① archive：開機寬限＋套用鎖 ─────────────────────────────────────────────

def test_gate_defers_inside_boot_grace_and_allows_after(tmp_path, monkeypatch):
    t0 = 1000.0
    monkeypatch.setattr(archive, "_PROCESS_STARTED_MONO", t0)
    lock = str(tmp_path / ".apply.lock")
    assert archive._server_log_rotation_deferred_reason(now_mono=t0 + 30, lock_path=lock)         # 第一輪就是啟動後 30 秒
    assert archive._server_log_rotation_deferred_reason(now_mono=t0 + archive._ROTATE_BOOT_GRACE_SECONDS - 1, lock_path=lock)
    assert archive._server_log_rotation_deferred_reason(now_mono=t0 + archive._ROTATE_BOOT_GRACE_SECONDS + 1, lock_path=lock) == ""


def test_gate_defers_while_apply_lock_exists_but_not_a_stale_one(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "_PROCESS_STARTED_MONO", time.monotonic() - 3600)               # 已跑很久，只剩鎖的因素
    lock = tmp_path / ".apply.lock"
    assert archive._server_log_rotation_deferred_reason(lock_path=str(lock)) == ""                # 沒鎖
    lock.write_text("{}", encoding="utf-8")
    assert archive._server_log_rotation_deferred_reason(lock_path=str(lock)), "套用／回滾進行中不可輪替"
    old = time.time() - archive._APPLY_LOCK_MAX_AGE_SECONDS - 60
    os.utime(lock, (old, old))
    assert archive._server_log_rotation_deferred_reason(lock_path=str(lock)) == "", "殘留的舊鎖不可以讓輪替永遠不跑"


def test_daily_backup_does_not_rotate_inside_boot_window_but_rotates_after(client, monkeypatch, tmp_path):
    """競態本身：行程剛啟動（第一輪 tick 在 30 秒）⇒ 不輪替；跑過寬限 ⇒ 照常輪替（不是把輪替整個關掉）。"""
    calls = []
    monkeypatch.setattr(archive, "_rotate_server_log_if_large", lambda *a, **k: calls.append(1) or False)
    monkeypatch.setattr(archive, "_archive_base", lambda: "")
    monkeypatch.setattr(archive, "_apply_lock_path", lambda: str(tmp_path / ".apply.lock"))   # 不看真的 .apply.lock
    monkeypatch.setattr(archive, "_PROCESS_STARTED_MONO", time.monotonic() - 30)
    archive._daily_backup()
    assert calls == [], "開機 30 秒就輪替 ⇒ 健康檢查讀到被清空的 server.log"
    monkeypatch.setattr(archive, "_PROCESS_STARTED_MONO", time.monotonic() - 3600)
    archive._daily_backup()
    assert calls == [1]


def test_daily_backup_does_not_rotate_while_apply_lock_exists(client, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(archive, "_rotate_server_log_if_large", lambda *a, **k: calls.append(1) or False)
    monkeypatch.setattr(archive, "_archive_base", lambda: "")
    monkeypatch.setattr(archive, "_apply_lock_path", lambda: str(tmp_path / ".apply.lock"))
    monkeypatch.setattr(archive, "_PROCESS_STARTED_MONO", time.monotonic() - 3600)
    (tmp_path / ".apply.lock").write_text("{}", encoding="utf-8")
    archive._daily_backup()
    assert calls == []


# ── ② ps1：輪替發生在健檢窗口內，helper 仍找得到啟動範圍 ────────────────────────

@needs_ps
def test_control_reading_only_server_log_misses_the_start_after_rotation(tmp_path):
    """對照組：舊的讀法（只讀 server.log 最後 200 行）在輪替之後找不到本次啟動的起點——競態是真的，不是測試編的。"""
    log = _rotated_log_in_boot_window(tmp_path)
    text = _src("apply_update.ps1")
    body = "\n".join([
        "$ErrorActionPreference = 'Stop'", _fn(text, "Get-StartupRange"),
        "$t = @(Get-Content '%s' -Tail 200 -Encoding UTF8)" % _q(log),
        "Write-Output ('RESULT ' + (@{ boot = [bool](Get-StartupRange $t) } | ConvertTo-Json -Compress))",
    ])
    assert _ps_run(tmp_path, body) == {"boot": False}


@needs_ps
@pytest.mark.parametrize("name", ["apply_update.ps1", "apply_module_update.ps1"])
def test_helper_finds_the_start_in_server_log_1_after_rotation_in_the_boot_window(tmp_path, name):
    """修之前：沒有 Get-ServerLogTail ⇒ 紅。修之後：現行檔沒有啟動範圍 ⇒ 往前接 .1，找到「MOTRIX ERP starting … Uvicorn running on」，
    而且順序正確（.1 的在前、輪替後寫的在後）。"""
    log = _rotated_log_in_boot_window(tmp_path)
    text = _src(name)
    assert _fn(text, "Get-ServerLogTail"), "%s 沒有 Get-ServerLogTail" % name
    d = _ps_run(tmp_path, _tail_body(text, log))
    assert d["boot"] is True, d
    assert d["last"].endswith(AFTER[-1]), "接起來的順序要是時間順序（最後一行是輪替後寫的）：%s" % d
    assert d["count"] == 200 + len(AFTER), d


@needs_ps
def test_helper_does_not_touch_server_log_1_when_current_file_has_the_start(tmp_path):
    """現行檔就有啟動範圍（沒被輪替）⇒ 只讀現行檔，不接 .1（.1 是更早的行程，接了會把舊行程的行混進來）。"""
    log = tmp_path / "logs" / "server.log"
    log.parent.mkdir()
    _write(log, BOOT + AFTER)
    _write(tmp_path / "logs" / "server.log.1", ["STALE previous generation"])
    d = _ps_run(tmp_path, _tail_body(_src("apply_update.ps1"), log))
    assert d["boot"] is True and d["count"] == len(BOOT) + len(AFTER), d


@needs_ps
def test_helper_ignores_a_server_log_1_older_than_this_apply(tmp_path):
    """$notBefore：.1 的修改時間早於本次套用開始 ⇒ 是上一個行程的舊檔、不是本次輪替出來的 ⇒ 不接。
    否則回滾後的檢查會把上一個行程印過的啟動行當成本次（假綠，Get-StartupRange 的設計就是為了擋這個）。"""
    log = tmp_path / "logs" / "server.log"
    log.parent.mkdir()
    _write(log, ["[2026/11/13 週五 10:15:00.00] MOTRIX ERP starting... "] + AFTER)   # 新行程：還沒 Uvicorn running on
    prev = tmp_path / "logs" / "server.log.1"
    _write(prev, FILLER + BOOT)                                                       # 舊行程的完整啟動
    started = datetime.now()
    old = (started - timedelta(days=3)).timestamp()
    os.utime(prev, (old, old))
    text = _src("apply_update.ps1")
    d = _ps_run(tmp_path, _tail_body(text, log, not_before=started))
    assert d["boot"] is False and d["count"] == 1 + len(AFTER), "舊的 .1 被接進來了 ⇒ 會把舊行程的啟動當成本次：%s" % d
    new = (started + timedelta(seconds=30)).timestamp()                              # 本次套用之後才輪替出來的 .1 ⇒ 要接
    os.utime(prev, (new, new))
    d = _ps_run(tmp_path, _tail_body(text, log, not_before=started))
    assert d["boot"] is True, d


@needs_ps
def test_module_log_check_sees_loaded_line_and_errors_across_the_rotation(tmp_path):
    """apply_module_update 的 Get-LogCheck：輪替後「已載入」在 .1 仍判載入（修之前判驗不到 ⇒ 模組更新路徑可能假回滾）；
    啟動之後的錯誤行即使落在 .1 也要掃得到（修之前掃空檔 ⇒ 假綠）。"""
    text = _src("apply_module_update.ps1")
    logs = tmp_path / "logs"
    logs.mkdir()
    err = ["ERROR:    Traceback (most recent call last):", "RuntimeError: boom after startup"]
    _write(logs / "server.log", FILLER + BOOT + err)
    assert archive._rotate_server_log_if_large(str(logs / "server.log"), max_bytes=100, keep=3) is True
    _write(logs / "server.log", AFTER)

    def run():
        body = "\n".join([
            "$ErrorActionPreference = 'Stop'", "function Info($msg) { }",
            _fn(text, "Get-StartupRange"), _fn(text, "Get-ServerLogTail"), _fn(text, "Get-LogCheck"),
            "$BackendDir = '%s'" % _q(tmp_path),
            "$lc = Get-LogCheck 'tender_radar' '1.5.13'",
            "Write-Output ('RESULT ' + (@{ loaded = [bool]$lc.Loaded; boot = [bool]$lc.Boot; errors = @($lc.Errors).Count } | ConvertTo-Json -Compress))",
        ])
        return _ps_run(tmp_path, body)

    d = run()
    assert d["loaded"] is True and d["boot"] is True, d
    assert d["errors"] >= 1, "啟動之後、輪替之前的錯誤在 .1，也要算進這次的錯誤掃描：%s" % d


def test_both_apply_scripts_carry_the_identical_helper_and_call_it():
    a, m = _src("apply_update.ps1"), _src("apply_module_update.ps1")
    assert _fn(a, "Get-ServerLogTail") and _fn(a, "Get-ServerLogTail") == _fn(m, "Get-ServerLogTail"), "兩份要逐字相同（同 Get-StartupRange 的規矩）"
    assert "Get-ServerLogTail $logPath 200 $script:StartedAtTime" in a and "Get-ServerLogTail $logPath 200 $script:StartedAtTime" in m
    assert "$script:StartedAtTime = Get-Date" in a and "$script:StartedAtTime = Get-Date" in m
    assert "-Encoding UTF8" in _fn(a, "Get-ServerLogTail"), "server.log 是 UTF-8 無 BOM，PS 5.1 預設 ANSI 讀會讓中文比對不到"


def test_apply_script_versions_were_bumped_and_registered():
    """行為變了就要升版並更新 version.json 的 sha（AH-O7）；T83 整合時由整合者統一版號。"""
    import sys
    sys.path.insert(0, str(_TOOLS))
    import delivery
    for ps1, reg, var in (("apply_update.ps1", "apply_update.version.json", "$ApplyScriptVersion"),
                          ("apply_module_update.ps1", "apply_module_update.version.json", "$ApplyModuleScriptVersion")):
        raw = (_TOOLS / ps1).read_bytes()
        r = json.loads((_TOOLS / reg).read_text(encoding="utf-8-sig"))
        assert r["version"] == "2026-11-13c", (reg, r["version"])
        assert delivery.ps1_digest(raw) == r["sha256"], "%s 的雜湊與 %s 不符" % (ps1, reg)
        assert '%s = "2026-11-13c"' % var in raw.decode("utf-8-sig")


# ── ③ 遠端唯讀腳本：往前讀 .1 ───────────────────────────────────────────────

@needs_ps
def test_dashboard_tail_log_fills_from_server_log_1_when_current_is_short(tmp_path):
    """部署儀表板「看 log」：輪替後現行檔只有幾行 ⇒ 用 .1 補滿 N 行（修之前只回那幾行，診斷看不到啟動）。"""
    text = _src("_dashboard_remote.ps1")
    i = text.index("            param($Root, $N)")
    j = text.index("\n        }\n", i)
    block = text[i:j]
    logs = tmp_path / "backend" / "logs"
    logs.mkdir(parents=True)
    _write(logs / "server.log", AFTER)
    _write(logs / "server.log.1", ["old %d" % k for k in range(50)])
    body = "\n".join([
        "$ErrorActionPreference = 'Stop'",
        "$sb = { %s }" % block,
        "$o = & $sb '%s' 20" % _q(tmp_path),
        "$lines = @($o -split \"`n\")",
        "Write-Output ('RESULT ' + (@{ n = $lines.Count; first = $lines[0]; last = $lines[-1] } | ConvertTo-Json -Compress))",
    ])
    d = _ps_run(tmp_path, body)
    assert d["n"] == 20 and d["first"] == "old 35" and d["last"].endswith(AFTER[-1]), d


@needs_ps
def test_prod_health_facts_module_lines_come_from_server_log_1_after_rotation(tmp_path):
    """健康事實腳本（_prod_health_facts.ps1）收「模組 X 已載入」：輪替後那幾行在 .1，要讀得到、順序是 .1 在前。"""
    text = _src("_prod_health_facts.ps1")
    i = text.index("$modLog = @()")
    j = text.index("\n}\n", text.index("$modLog = @(", i + 20)) + 3
    block = text[i:j]
    logs = tmp_path / "logs"
    logs.mkdir()
    _write(logs / "server.log", AFTER)                                           # 輪替後：現行檔沒有模組行
    _write(logs / "server.log.1", FILLER + BOOT)                                 # .1 有
    body = "\n".join([
        "$ErrorActionPreference = 'Stop'", "$b = '%s'" % _q(tmp_path), block,
        "Write-Output ('RESULT ' + (@{ n = @($modLog).Count; hit = [bool](@($modLog | Where-Object { $_ -like '*tender_radar 1.5.13*' }).Count -gt 0) } | ConvertTo-Json -Compress))",
    ])
    d = _ps_run(tmp_path, body)
    assert d == {"n": 1, "hit": True}, d
