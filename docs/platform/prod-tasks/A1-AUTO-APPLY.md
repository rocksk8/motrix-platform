# A1 M1：正式機半自動套用（操作與設計摘要）

> 範圍：只有我們自己的正式機（M1）。客戶主機版本、跳台、更新中樞（M2）尚未開工，設計全文在 `D:\Claude-pm\t87-design\A1-auto-apply.md`。
> 程式：`backend/tools/auto_apply.py`；接線：`backend/tools/deploy_dashboard.py`（「6. 套用更新」卡片）。
> 測試：`backend/tests/platform/test_a1_auto_apply_2026_11_14.py`。

## 它取代了什麼

步驟檔（例如 `20261114-t86-apply.md`）的「步驟 0 記錄套用前狀態」與「步驟 3 套用後驗收」原本由人手工做。M1 把這兩段做成程式，並在套用前多一道**預演**。
套用本身沒有改：仍是 `delivery.apply_staged`，備份、乾跑、停服、複製、重啟、健康檢查與**腳本內建的自動回滾**都照舊。

## 操作流程（儀表板「6. 套用更新」）

1. 選包，按「準備」：複製到安裝目錄外、驗簽章與逐檔雜湊（與以前相同）。畫面多一行預估耗時。
2. 按「預演」：在正式資料庫的**線上備份副本**上，用新包的 `migrate_like_startup.py` 跑一遍，畫面列出預期的資料庫變更。預演只讀正式庫，不需要密碼。
3. 確認內容後輸入本機最高管理者帳密，按「套用」。**沒有通過預演、預演超過 12 小時、暫存的包在預演後被換過、或畫面上看到的預演結果與目前有效的不同，都會被拒絕**（且在要求密碼之前就拒絕）。
4. 套用後系統自動驗證，畫面逐項列出結果；同時寫 `backend\logs\a1_report_<時間戳>.md／.json`。

## 事後驗證項目

| 項目 | 通過條件 |
|---|---|
| 健康檢查 | `/api/ping` 回 200 |
| 資料庫完整性 | `PRAGMA integrity_check` ＝ ok |
| 資料庫變更與預演相符 | 結構差異（物件、欄位、模組 schema 版號、設定鍵名）與預演預期一致；多出或缺少都失敗；多出的設定鍵若是 `migration_*` 失敗，其他只警告 |
| 模組載入 | `logs\module_states.json` 是這次啟動寫的，且每個已載入模組的版號＝磁碟 `module.json` |
| server.log | 最後一次啟動標記之後沒有 Traceback 與包指定的禁止字串 |
| 已部署 commit | `.deployed_commit.json` 與包的 commit 一致 |
| 包專屬項目 | 包內選用檔 `backend\a1_expectations.json`（`pages`、`auth_required`、`files`、`log_forbid`、`watch_settings`）；沒有這個檔就只做上列通用項目，並在報告注記 |

## 驗證失敗時

- 只停下來、產生報告、顯示回滾指令的**文字**；系統**不會**執行回滾（PM 裁示 D1）。
- 套用腳本自己的健康檢查／公司資料閘門失敗所觸發的內建自動回滾不受影響，結果照舊在 `rolled_back` 欄。
- 寫回交付資料夾的 `results\<包名>.result.json`：事後驗證沒過一律記 `failed`；細節在旁檔 `results\<包名>.a1.json`（白名單欄位，不含路徑、設定、報告全文）。

## 稽核

- `backend\logs\a1_audit.jsonl`：每筆含前一筆雜湊，單筆被改或刪除可偵測（`auto_apply.audit_chain_problems`）。
- ERP `audit_log` 補一列 `system_update_apply`（套用者、包名、結果、驗證失敗項目的 id）。這是 A1 唯一寫正式庫的地方，寫在事後驗證**之後**；寫入失敗不影響套用結果。
- 報告與稽核不含密碼、token、設定值、資料列內容。

## 已知限制（M1 刻意不做）

- 不做登入後的功能煙霧測試（需要憑證，留給 M2 或另案）。
- 實際停機時間以每 2 秒一次的 `/api/ping` 量測，是下限加一個輪詢間隔。
- 預估耗時來自歷次成功的 `apply_update_*.result.json`，含套用前備份與乾跑，並非只有服務停止的時間。
- `REQUIRE_REHEARSAL` 是程式常數（`deploy_dashboard.py`），不做成設定值；關閉它等於回到沒有預演的舊流程，需要改程式並走審查。
- `a1_expectations.json` 目前沒有出包流程自動產生；要用的包由作者手動放進 `backend\`。
