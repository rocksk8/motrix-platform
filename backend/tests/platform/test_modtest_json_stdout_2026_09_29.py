# -*- coding: utf-8 -*-
"""modtest --json：stdout 只有那一份 JSON，提示一律走 stderr（第二十班交會紅，2026-09-29 A 列車長）。

列車以 MOTRIX_E2E_MAX_WORKERS=3 起跑 ⇒ 子行程（module_update.ship_tests 呼叫的 `modtest --files … --dry-run --json`）繼承到它、
把「[modtest] MOTRIX_E2E_MAX_WORKERS=3（預設 2）」印進 stdout ⇒ JSON 解析失敗 ⇒ 出貨判定「選題輸出看不懂」而拒絕。
記憶〈環境變數旗標會漏進子 pytest〉同一型：呼叫端環境一變，機器可讀輸出就壞。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
MODTEST = REPO / "tools" / "platform" / "modtest.py"


def _run(env_extra):
    # --no-count：這題驗 stdout 只有 JSON，與題數無關；呼叫端 module_update.ship_tests 也是這樣呼叫（第 45 班 O5，省掉 collect 全庫）
    env = dict(os.environ, PYTHONIOENCODING="utf-8", **env_extra)
    return subprocess.run([sys.executable, str(MODTEST), "--files", "backend/tools/module_apply_steps.py", "--dry-run", "--json", "--no-count"],
                          cwd=str(REPO), capture_output=True, env=env, timeout=600)


def test_json_stdout_parses_even_when_worker_caps_are_set():
    r = _run({"MOTRIX_E2E_MAX_WORKERS": "3", "MOTRIX_PARTIAL_MAX_WORKERS": "3"})
    assert r.returncode in (0, 3), r.stderr.decode("utf-8", "replace")[-800:]
    out = r.stdout.decode("utf-8")
    data = json.loads(out)                      # 多一行提示 ⇒ 這裡丟 ValueError
    assert isinstance(data.get("tests"), list)
    err = r.stderr.decode("utf-8", "replace")
    assert "[modtest]" not in out, "提示印進了 stdout"
    assert "MOTRIX_E2E_MAX_WORKERS=3" in err or "MOTRIX_PARTIAL_MAX_WORKERS=3" in err, \
        "正對照：環境變數確實被讀到、提示確實印了（在 stderr）——否則這一題驗的是沒有提示的情況"
