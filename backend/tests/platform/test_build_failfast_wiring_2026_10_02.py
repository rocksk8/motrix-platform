# -*- coding: utf-8 -*-
"""建包優化 2 項 1 接進 build_deploy_package.ps1 的靜態守門（逐條有反向控制：突變腳本文字 ⇒ 轉紅）。

重點只有一件：**fail-fast 提前停止的那一段不可能被「偶發重跑」放行成綠**。停止時該段沒跑完——若紅的題（已登記偶發）重跑通過就放行，
沒跑的題就被悄悄略過。所以：兩段都要在進 Invoke-FlakyRetry 之前檢查 `FAIL-FAST:` 並跳過；兩個 pytest 呼叫都帶 `@ffArgs`；
有 `-NoFailFast` 回退開關；環境變數收尾時移除；MOTRIX_FAILFAST* 不進測試指紋（否則 modtest／獨立跑與建包的指紋會不相等）。
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PS1 = REPO / "backend" / "tools" / "build_deploy_package.ps1"
if not PS1.is_file():
    pytest.skip("build_deploy_package.ps1 不在這個安裝包", allow_module_level=True)
TEXT = PS1.read_text(encoding="utf-8-sig")


def _check(text):
    """⇒ 問題清單（空＝通過）。純函式，反向控制用突變過的文字呼叫它。"""
    bad = []
    if not re.search(r"\[switch\]\$NoFailFast\b", text):
        bad.append("沒有 -NoFailFast 回退開關")
    calls = re.findall(r"& \$pyExe -m pytest [^\n]*?(?:-m \"not e2e\"|-m \"e2e\")[^\n]*", text)
    if len(calls) != 2 or not all("@ffArgs" in c for c in calls):
        bad.append("兩個 pytest 呼叫（非 e2e／e2e）都要帶 @ffArgs：%r" % calls)
    for stage, exitvar in (("not_e2e", "testExit"), ("e2e", "e2eExit")):
        m = re.search(r'\$ffStopped\["%s"\] = \[bool\]\(' % stage, text)
        if not m:
            bad.append("%s：沒有偵測 FAIL-FAST 停止" % stage)
            continue
        gate = re.search(r"if \(\$%s -ne 0 -and -not \$ffStopped\[\"%s\"\]\) \{\s*\$retry = Invoke-FlakyRetry \"%s\"" % (exitvar, stage, stage), text)
        if not gate:
            bad.append("%s：停止的段仍可能進 Invoke-FlakyRetry 被放行" % stage)
        elif gate.start() < m.start():
            bad.append("%s：偵測要在偶發重跑之前" % stage)
    if not re.search(r'\$ffArgs = @\("-p", "failfast"\)', text):
        bad.append("沒有載入 failfast plugin")
    if not re.search(r"Remove-Item Env:\\MOTRIX_FAIL_STREAM_RUN[^\n]*Env:\\MOTRIX_FAILFAST\b[^\n]*Env:\\MOTRIX_FAILFIRST_BASE", text):
        bad.append("收尾沒有移除 MOTRIX_FAILFAST*／MOTRIX_FAILFIRST* 環境變數")
    return bad


def test_wiring_is_complete_and_a_stopped_stage_can_never_be_released_by_flaky_retry():
    assert _check(TEXT) == []


@pytest.mark.parametrize("old,new,expect", [
    ('-and -not $ffStopped["not_e2e"]', "", "non-e2e retry gate"),
    ('-and -not $ffStopped["e2e"]', "", "e2e retry gate"),
    ("@fsArgs @ffArgs 2>&1", "@fsArgs 2>&1", "pytest args"),
    ("[switch]$NoFailFast", "[switch]$NoFailFastX", "switch"),
    ('$ffArgs = @("-p", "failfast")', '$ffArgs = @()', "plugin"),
])
def test_reverse_control_mutated_script_text_is_caught(old, new, expect):
    assert old in TEXT, "突變錨點不在腳本裡（腳本改了、這題要跟著改）：" + old
    assert _check(TEXT.replace(old, new, 1)), "突變沒被抓到：" + expect


def test_failfast_env_vars_do_not_enter_the_test_fingerprint():
    import sys
    sys.path.insert(0, str(REPO / "backend" / "tools"))
    import build_test_reuse as btr
    for k in ("MOTRIX_FAILFAST", "MOTRIX_FAILFAST_N", "MOTRIX_FAILFAST_QUIET_MIN", "MOTRIX_FAILFAST_FLAKES",
              "MOTRIX_FAILFIRST", "MOTRIX_FAILFIRST_BASE", "MOTRIX_FAILFIRST_HISTORY", "MOTRIX_FAILFIRST_RECORDS"):
        assert k in btr._ENV_IGNORE, k
    assert "MOTRIX_SOMETHING_ELSE" not in btr._ENV_IGNORE                               # 反向：不是整個前綴都忽略
