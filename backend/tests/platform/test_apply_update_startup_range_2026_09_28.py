# -*- coding: utf-8 -*-
"""apply_update.ps1 的「本次啟動那一段 log」（Get-StartupRange）與開關生效檢查（Get-SwitchMismatch）——**實際執行** ps1。

誤報（822286ed、54a2d6b6、3e061d6f、f04a245a 每次部署都出現「開關沒有生效：MOTRIX_GEO、MOTRIX_TENDER_RADAR」，
而 server.log 其實有那兩行）：main.py 在 import 時印開關那一行，早於「Uvicorn running on」；檢查卻只掃
「最後一次 Uvicorn running on 之後」⇒ 永遠看不到。同一根因的另一半：server.log 是 Python 寫的 UTF-8（沒有 BOM），
PS 5.1 的 Get-Content 預設用 ANSI 讀 ⇒ 中文字串（「模組 X 1.2.3 已載入」）比對不到（apply_module_update 的健檢誤判）。

題目執行的是腳本**自己的** Step 5 那幾行（逐字取出：讀 tail、算 $scanRange／$bootRange、呼叫 Get-SwitchMismatch），
不是題目重寫一份 ⇒ 把呼叫端改回 $scanRange、拿掉 -Encoding UTF8，這裡都會紅。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_PS1 = Path(__file__).resolve().parents[2] / "tools" / "apply_update.ps1"
_PS = shutil.which("powershell.exe") or shutil.which("powershell")
pytestmark = pytest.mark.skipif(not _PS, reason="需要 Windows PowerShell（apply_update.ps1 的執行環境）")

AUTOSTART_BOTH = "@echo off\r\nset MOTRIX_TENDER_RADAR=1\r\nset MOTRIX_GEO=1\r\n:loop\r\necho starting\r\n"
AUTOSTART_GEO_COMMENTED = "@echo off\r\nset MOTRIX_TENDER_RADAR=1\r\n:: set MOTRIX_GEO=1\r\n:loop\r\n"

GEO = "INFO:main:MOTRIX_GEO=1 —— 地址定位已開，這台機器會對外連線（OpenStreetMap／Nominatim）"
RADAR = "INFO:core.loader:MOTRIX_TENDER_RADAR=1 —— 標案雷達已開，這台機器會對外連線（政府電子採購網）"


def _boot(ver, switches=True):
    lines = ["[2026/09/28 週一 21:57:15.20] MOTRIX ERP starting... "]
    if switches:
        lines += [GEO]
    lines += ["INFO:core.loader:模組 tender_radar %s 已載入" % ver]
    if switches:
        lines += [RADAR]
    lines += ["INFO:     Started server process [4242]", "INFO:     Waiting for application startup.",
              "INFO:     Application startup complete.", "INFO:     Uvicorn running on https://0.0.0.0:666 (Press CTRL+C to quit)"]
    return lines


ACCESS = ['INFO:     127.0.0.1:50001 - "GET /api/ping HTTP/1.1" 200 OK'] * 3
STOPPED = ["[2026/09/28 週一 21:57:10.12] MOTRIX ERP stopped (exit code 1). restart in 5s... "]


def _src():
    return _PS1.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def _fn(text, name):
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("function %s" % name):
            for j in range(i + 1, len(lines)):
                if lines[j] == "}":
                    return "\n".join(lines[i:j + 1])
    raise AssertionError("apply_update.ps1 沒有 function %s" % name)


def _step5_segment(text):
    """Step 5：從讀 tail 到 $scanRange 算完（逐字）＋$switchNames＋呼叫 Get-SwitchMismatch 那一行（逐字）。"""
    i = text.index("    $tail = Get-Content $logPath")
    j = text.index("        $scanRange = @()\n    }\n", i) + len("        $scanRange = @()\n    }\n")
    names = re.search(r"^\s*\$switchNames = @\(.*\)$", text, re.M).group(0)
    call = re.search(r"^\s*\$sm = Get-SwitchMismatch .*$", text, re.M).group(0)
    return text[i:j], names, call


def _run(tmp_path, log_lines, autostart=AUTOSTART_BOTH, text=None):
    text = _src() if text is None else text
    log = tmp_path / "server.log"
    # Python 寫的 server.log：UTF-8、沒有 BOM
    log.write_bytes(("\r\n".join(log_lines) + "\r\n").encode("utf-8"))
    seg, names, call = _step5_segment(text)
    body = "\n".join([
        "$ErrorActionPreference = 'Stop'",
        _fn(text, "Get-StartupRange"),
        _fn(text, "Get-SwitchMismatch"),
        "$logPath = '%s'" % str(log).replace("'", "''"),
        "$autostartText = @'\n%s\n'@" % autostart.replace("\r\n", "\n"),
        seg,
        names,
        call,
        "$out = @{ boot_first = $(if ($bootRange) { [string]$bootRange[0] } else { $null });",
        "          boot_count = $(if ($bootRange) { @($bootRange).Count } else { 0 });",
        "          missing = @($sm.Missing); want = @($sm.Want);",
        "          tail_has_loaded = [bool](@($tail | Where-Object { $_ -like '*模組 tender_radar * 已載入*' }).Count -gt 0) }",
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8",
        "Write-Output ('RESULT ' + ($out | ConvertTo-Json -Compress))",
    ])
    script = tmp_path / "harness.ps1"
    script.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
    r = subprocess.run([_PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                       capture_output=True, timeout=60)
    out = r.stdout.decode("utf-8", "replace")
    line = [l for l in out.splitlines() if l.startswith("RESULT ")]
    assert r.returncode == 0 and line, (r.returncode, out, r.stderr.decode("utf-8", "replace"))
    d = json.loads(line[-1][len("RESULT "):])
    for k in ("missing", "want"):   # PS 5.1 的 ConvertTo-Json 會把單一元素陣列攤成字串
        v = d[k] or []
        d[k] = sorted([v] if isinstance(v, str) else v)
    return d


def test_switch_lines_printed_before_uvicorn_running_are_seen(tmp_path):
    """真實順序（開關行在 Uvicorn running on 之前）⇒ 不誤報。舊碼（掃 Uvicorn running on 之後）在這裡報兩個都沒生效。"""
    d = _run(tmp_path, _boot("1.3.3") + ACCESS + STOPPED + _boot("1.3.4") + ACCESS)
    assert d["want"] == ["MOTRIX_GEO", "MOTRIX_TENDER_RADAR"]
    assert d["missing"] == [], d
    assert "MOTRIX ERP starting" in d["boot_first"]


def test_reverse_control_this_start_really_without_the_switch_is_still_reported(tmp_path):
    """反向控制：上一個行程有那兩行、**這次啟動**沒有（舊環境變數的迴圈接手）⇒ 照報。退回整段 tail 的話會漏報。"""
    d = _run(tmp_path, _boot("1.3.3") + ACCESS + STOPPED + _boot("1.3.4", switches=False) + ACCESS)
    assert d["missing"] == ["MOTRIX_GEO", "MOTRIX_TENDER_RADAR"], d


def test_crash_retry_uses_the_start_that_actually_came_up(tmp_path):
    """port 還被占（Errno 10048）重試：起點是「成功那一輪」的 MOTRIX ERP starting。"""
    failed = ["[2026/09/28 週一 21:57:15.20] MOTRIX ERP starting... ", GEO, RADAR,
              "ERROR:    [Errno 10048] error while attempting to bind on address ('0.0.0.0', 666)"] + STOPPED
    d = _run(tmp_path, failed + _boot("1.3.4", switches=False) + ACCESS)
    assert d["missing"] == ["MOTRIX_GEO", "MOTRIX_TENDER_RADAR"], "失敗那一輪的行不算這次啟動"
    d = _run(tmp_path, failed + _boot("1.3.4") + ACCESS)
    assert d["missing"] == []


def test_no_start_marker_means_cannot_verify_not_whole_tail(tmp_path):
    """找不到 MOTRIX ERP starting（或還沒 Uvicorn running on）⇒ $bootRange 為空 ⇒ 呼叫端略過並說驗不到。"""
    no_marker = [l for l in _boot("1.3.4") if "MOTRIX ERP starting" not in l]
    assert _run(tmp_path, no_marker)["boot_count"] == 0
    not_up = [l for l in _boot("1.3.4") if "Uvicorn running on" not in l]
    assert _run(tmp_path, not_up)["boot_count"] == 0
    assert 'if ((Test-Path $autostartPath) -and $bootRange) {' in _src()


def test_commented_out_switch_is_not_wanted(tmp_path):
    d = _run(tmp_path, _boot("1.3.4", switches=False), autostart=AUTOSTART_GEO_COMMENTED)
    assert d["want"] == ["MOTRIX_TENDER_RADAR"] and d["missing"] == ["MOTRIX_TENDER_RADAR"]


def test_server_log_is_read_as_utf8(tmp_path):
    """server.log 是 UTF-8 無 BOM；Step 5 讀 tail 那一行要帶 -Encoding UTF8，中文才比對得到。"""
    d = _run(tmp_path, _boot("1.3.4") + ACCESS)
    assert d["tail_has_loaded"] is True, "讀 server.log 沒帶 -Encoding UTF8 ⇒ 中文（已載入）比對不到"


def test_rc_old_anchor_reproduces_the_false_alarm(tmp_path):
    """重現誤報：把呼叫端換回舊錨點（$scanRange＝Uvicorn running on 之後）⇒ 同一份真實 log 報兩個都沒生效。"""
    old = _src().replace("$sm = Get-SwitchMismatch $autostartText $bootRange", "$sm = Get-SwitchMismatch $autostartText $scanRange")
    assert old != _src()
    d = _run(tmp_path, _boot("1.3.3") + ACCESS + STOPPED + _boot("1.3.4") + ACCESS, text=old)
    assert d["missing"] == ["MOTRIX_GEO", "MOTRIX_TENDER_RADAR"], d
