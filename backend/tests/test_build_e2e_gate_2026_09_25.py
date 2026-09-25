"""建包的 e2e 判定：逾時也擋下打包（2026-09-25）。

原本「全部都是逾時 ⇒ 警告、繼續打包」：逾時的題沒有驗到任何東西，放行＝靜默少驗。
規則在 backend/tools/_e2e_gate.ps1::Get-E2eGateResult（build_deploy_package.ps1 呼叫）；
以 Windows PowerShell 5.1 實跑。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="部署腳本只在 Windows 上跑")

TOOLS = Path(__file__).resolve().parents[1] / "tools"
GATE = TOOLS / "_e2e_gate.ps1"
BUILD = TOOLS / "build_deploy_package.ps1"

T1 = "FAILED tests/test_e2e_a.py::test_x - playwright._impl._errors.TimeoutError: Timeout 15000ms exceeded."
A1 = "FAILED tests/test_e2e_b.py::test_y[1440] - AssertionError: 應左右並排"


def _gate(exit_code, lines):
    ps = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
          f". '{GATE}'; "
          # PS 5.1 的 ConvertFrom-Json 把整個陣列當成一個物件輸出 ⇒ 要展開，否則函式收到一個字串
          f"$l = @('{json.dumps(lines)}' | ConvertFrom-Json | ForEach-Object {{ $_ }}); "
          f"$r = Get-E2eGateResult -ExitCode {exit_code} -Lines $l -PyExe 'py'; "
          "ConvertTo-Json -InputObject $r -Compress -Depth 4")
    out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                         capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_all_green_passes():
    r = _gate(0, ["300 passed in 900s"])
    assert r["Ok"] is True and r["Message"] in ([], None)


def test_timeouts_only_now_block_the_package():
    r = _gate(1, ["x", T1, "1 failed, 299 passed"])
    assert r["Ok"] is False, "逾時＝沒驗到，不可以出包"
    assert r["Timeouts"] == ["tests/test_e2e_a.py::test_x"]
    msg = "\n".join(r["Message"])
    assert "逾時 1 題" in msg and 'py -m pytest "tests/test_e2e_a.py::test_x" -v' in msg


def test_assertion_failures_block_and_are_listed_apart_from_timeouts():
    r = _gate(1, [T1, A1])
    assert r["Ok"] is False
    assert r["Failures"] == ["tests/test_e2e_b.py::test_y[1440]"] and r["Timeouts"] == ["tests/test_e2e_a.py::test_x"]
    msg = "\n".join(r["Message"])
    assert msg.index("斷言失敗") < msg.index("逾時"), "斷言失敗要列在前面"
    assert 'py -m pytest "tests/test_e2e_b.py::test_y[1440]" -v' in msg


def test_nonzero_exit_without_any_failed_line_is_still_blocked():
    # 收集錯誤、行程被殺、輸出被截斷：認不出 FAILED 行 ⇒ fail closed
    r = _gate(2, ["ERROR collecting tests/test_e2e_c.py", "Interrupted: 1 error during collection"])
    assert r["Ok"] is False and "認不出任何 FAILED 行" in "\n".join(r["Message"])


def test_the_build_script_parses_and_no_longer_lets_timeouts_through():
    ps = ("$e = $null; $t = $null; "
          f"[void][System.Management.Automation.Language.Parser]::ParseFile('{BUILD}', [ref]$t, [ref]$e); $e.Count")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "0", ("build_deploy_package.ps1 語法錯誤", out.stdout, out.stderr)
    src = BUILD.read_text(encoding="utf-8-sig")
    assert "_e2e_gate.ps1" in src and "Get-E2eGateResult" in src
    assert "e2eTimeoutOnly" not in src and "繼續打包，建議事後單獨重跑" not in src, "舊的逾時放行路徑還在"
    assert GATE.read_bytes()[:3] == b"\xef\xbb\xbf" and BUILD.read_bytes()[:3] == b"\xef\xbb\xbf", ".ps1 要有 BOM"


def test_a_hard_cap_kill_is_listed_as_a_timeout_only_once():
    """逐題上限（conftest `_e2e_hard_cap`）結束 worker 時，輸出有兩行 FAILED：xdist 自己那行（被截成 `- w...`、
    不含 Timeout）＋主控補的 `- Timeout: e2e 逐題上限…`。同一題只能算一次，而且要算在「逾時」。"""
    xd = "FAILED tests/test_e2e_z.py::test_stuck - w..."
    cap = "FAILED tests/test_e2e_z.py::test_stuck - Timeout: e2e 逐題上限 120s（堆疊見上方）"
    r = _gate(1, [cap, "=== short test summary info ===", xd, "1 failed, 5 passed"])
    assert r["Ok"] is False
    assert r["Timeouts"] == ["tests/test_e2e_z.py::test_stuck"], r
    assert r["Failures"] in ([], None), "同一題被逐題上限結束，不可以再算成斷言失敗：%r" % r
    assert "\n".join(r["Message"]).count('py -m pytest "tests/test_e2e_z.py::test_stuck" -v') == 1
