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
    # 稽核 X-9b S-6：夾具是「本公司、欄位不齊」⇒ 轉換一定有補欄位（M-1 的觸發條件）
    assert set(s["convert"]["company_profile"]["filled"]) == {"company_name_en", "email"}, s["convert"]
    assert s["verify"] == [], s["verify"]
    assert s["rows_added_before_rollback"].get("customers") == 1
    # S-3：完整回滾的提示以「轉換完成當下」為基準 ⇒ 轉換本身寫的列不算，演練寫的那一筆客戶要列出來
    ch = s["changes_since_conversion"]
    assert ch["baseline"] == "post_convert" and ch["rows_added"].get("customers") == 1, ch
    assert s["rollback"] == [], s["rollback"]              # 程式（兩種）＋DB／設定（full）雜湊逐一相等
    assert s["rollback_exit"] == 0, s                      # CLI 同一條路：含自動 V9 ping
    assert "uploads/projects/1/after_upgrade.jpg" in s["rollback_info"]["data_added"], s["rollback_info"]
    if mode == "full":                                     # O-1：邏輯內容與備份時的**原檔**相同
        assert set(s["rollback_info"]["db_logical"].values()) == {"與備份時原檔的邏輯內容相同"}, s["rollback_info"]
    assert s["v9_start"]["ok"], s["v9_start"]              # V9 可以啟動（ping 200）
    assert s["new_row_kept"] is (mode == "code")
    assert s["v9_after_start_row_kept"], s
    # 稽核 X-9b S-6／M-2：轉換後寫過上傳檔與每日快照，回滾照樣要過，而且那些檔還在
    assert s["files_written_after_conversion"] and s["new_files_kept"], s
    assert rep["ok"]
