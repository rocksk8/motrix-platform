# -*- coding: utf-8 -*-
"""升級轉換與回滾的端到端演練（CORE-SPEC §9b）：V9 程式取 c83dae6e、新版取 HEAD，
轉換 → 驗證（新版啟動 ping）→ 寫入新資料 → 回滾 → 雜湊逐一相等 → V9 啟動 ping 200。

兩種模式都跑：
- code：只回程式，轉換後寫入的新資料**要保留**
- full：程式＋DB＋設定還原，轉換後寫入的新資料**要消失**（反向控制：同一筆資料兩種模式結果相反）

每題約 30–60 秒（git archive＋兩次 uvicorn 啟動）。演練目錄在 %TEMP%，結束即刪。
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "platform"))


def _has_v9_base():
    r = subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", "c83dae6e^{commit}"], capture_output=True)
    return r.returncode == 0


pytestmark = pytest.mark.skipif(not _has_v9_base(), reason="沒有 V9 基準 commit c83dae6e（非本 repo 的 clone）")


#: 連線只打 127.0.0.1 上**本題自己起的** uvicorn 子行程（/api/ping），不連任何外部位址。
@pytest.mark.allow_outbound
@pytest.mark.parametrize("mode", ["code", "full"])
def test_convert_then_rollback_restores_v9(mode):
    import upgrade_drill
    rep = upgrade_drill.drill(mode)
    s = rep["steps"]
    assert s["preflight"]["ok"], s["preflight"]
    assert s["backup_verify"] == [], s["backup_verify"]
    assert s["convert"]["migrate"]["ok"], s["convert"]["migrate"]
    assert s["convert"]["settings_added"] == {"payslip_archive_path": ""}
    assert s["verify"] == [], s["verify"]
    assert s["rows_added_before_rollback"].get("customers") == 1
    assert s["rollback"] == [], s["rollback"]              # 程式（兩種）＋DB／設定（full）雜湊逐一相等
    assert s["v9_start"]["ok"], s["v9_start"]              # V9 可以啟動（ping 200）
    assert s["new_row_kept"] is (mode == "code")
    assert rep["ok"]
