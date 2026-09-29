# AUDIT-D：wip/cloud-startup-timing（2fb9d6f1，基底 70ec2523）

2026-09-29｜依 8c34f08a：只跑探針與突變。**必修 0 項；建議 1 項。**

## 已驗
- 記錄出錯不影響啟動：`_startup_step`／`_startup_total` 全包 `try/except Exception: pass`；`basicConfig` 之前的段暫存、之後一併印。自做突變（把 except 改成只接 ZeroDivisionError）⇒ `test_startup_step_swallows_logging_failures` 紅 ✔（已還原）；新檔 4 題＋`test_geocode_warm_async` 共 10 過（自跑）
- `test_geocode_warm_async` 逐字執行的排程閘門區塊：`_startup_step("schedulers")` 放在區塊**外**（if／else 之後），區塊內部未動；`test_startup_step_calls_are_top_level` 守「所有呼叫都在頂層」✔
- **對 apply_update／apply_module_update 的 `Get-StartupRange` 的影響**：範圍＝「最後一個 `Uvicorn running on` 往前最近的 `MOTRIX ERP starting`」到 tail 末端，tail＝最後 200 行。新增的 30 行（29 段＋TOTAL）全印在 `Uvicorn running on` **之前**，所以：①起點仍找得到（估算 `MOTRIX ERP starting` 到 `Uvicorn` 之間約 13 個模組載入行＋既有雜項＋30 行 ⇒ 約 60～80 行，加上健檢期間的存取紀錄仍遠低於 200）②錯誤掃描只看 `Uvicorn running on` 之後，新行不參與；即使退回全 tail 掃描，步驟名（如 `fail_incomplete_modules`）不含 `Traceback|ERROR` ③開關檢查比對 `<SWITCH>=1`、模組檢查比對 `模組 <key> <版本> 已載入`，都不會被新行誤命中 ✔
- 新行格式固定（`STARTUP_STEP <名稱> <毫秒>ms`、`STARTUP_TOTAL <毫秒>ms steps=<段數>`），守門檢查缺段／缺 TOTAL ✔

## 建議
### D-startup-S1 200 行 tail 的餘裕沒有守門
本包讓「起點到 Uvicorn」多了 30 行；日後模組變多（每個 +1 行）或啟動期多出 WARNING 時，`MOTRIX ERP starting` 可能被擠出最後 200 行 ⇒ `Get-StartupRange` 回 `$null`（其設計是「驗不到」，不會假綠，但套用會被報成驗不到／失敗）。建議加一題：以本次守門記的 `steps` 數＋已載入模組數估算，斷言小於 200 的一半；或把 tail 改為 400（改動小）。
