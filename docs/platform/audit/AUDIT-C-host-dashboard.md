# 稽核：主持的部署儀表板修正（C 稽核，2026-09-25）

> 依 PLAYBOOK §E。對象：commit `7be69753`（S-CP01／S-CP02／S-CU01／S-CU06，STATES-DATA-OPS 編號）。
> 稽核範圍只有這四項修正；儀表板其餘部分（D2／D4／D6、modtest 等）的稽核另開一份。
> 分級：**必修**（不修不能關）／**建議**／**觀察**。關閉規則：被稽核者回覆後，由 C 確認才關。
> 路徑前綴 `backend/`；`DD`＝`tools/deploy_dashboard.py`、`DI`＝`tools/deploy_insights.py`、`PHF`＝`tools/_prod_health_facts.ps1`。

## 0. 結論

- 四項修正的主要缺陷都已修好，也有測試；S-CP02 的 `.done` 規則突變後會轉紅（C 實測）。
- **必修 3 項**：
  1. A-1：回滾的逾時比轉換短，逾時後會把回滾砍到一半。
  2. A-2：健康檢查的磁碟判斷只認 C:，S-CP02 的一半還沒修。
  3. A-3：一支新測試在 C 的環境是紅的，原因是 PowerShell 輸出編碼沒有固定。
- 建議 3 項、觀察 3 項。
- 驗證：`tests/platform/test_deploy_dashboard_{jobs,health_facts,upgrade,health,gates}.py` 在 C 的環境 **48 passed、1 failed**（A-3）。

## 1. 逐項驗收

| 項目 | 規格（STATES「應有行為」） | 驗收 | 證據 |
|---|---|---|---|
| S-CP01 歷史寫入 | 修正變數；補一題不 mock `_run_job` 的測試 | ✅ | DD:582 改用 `outcome == "succeeded"`；`test_deploy_job_writes_history_even_when_it_fails` 真的跑 `_run_job`（以 python 子行程代替 PowerShell） |
| S-CP02 D1 假綠燈 | 以最新 `YYYY-MM-DD/.done` 為準；**磁碟未知不放行** | ⚠ 一半 | `.done` ✅（PHF:14-24）。C 實測：只有 `pre_update_*`＋沒有 `.done` 的日期資料夾 ⇒ `latestDbBackup: null`；補上 `.done` ⇒ 取到。**磁碟那一半未改**，見 A-2 |
| S-CU01 WinRM 掛住 | 每步有逾時；逾時標 failed、放鎖、明說狀態未知 | ⚠ | 機制 ✅（DD:478-499）；`test_hung_upgrade_job_is_killed_and_reported` 驗到失敗、放鎖、訊息。但上限值有問題，見 A-1 |
| S-CU06 時間戳 | 伺服器記住備份目錄、可選既有備份 | ✅（可選既有備份未做） | `upgrade_session.json`（DD:1131-1208）；頁面從伺服器讀（deploy_dashboard.html:224）；步驟的時間戳要和進行中那一輪相同，否則 409（DD:1219-1223）；讀不懂的時候不當成沒有 |

## 2. 發現

### 必修

**A-1　回滾的逾時比轉換短：逾時會把回滾砍到一半**
- 位置：DD:478-481。`_JOB_TIMEOUT_MIN` 只列了 build／deploy／rollback／upgrade-push／backup／convert。`upgrade-rollback-code`、`upgrade-rollback-full`、`verify`、`start-services` 都落到預設的 20 分鐘，但 `upgrade-convert` 是 45 分鐘。
- 為什麼是必修：
  - 回滾複製的量不比轉換少（full 另外還還原 DB）。
  - 逾時後 `taskkill /T` 會砍掉本機的 PowerShell 與 WinRM 連線，正式機上的回滾很可能停在一半。
  - C 在 STATES 的 S-CU07【實測 R3】證明回滾不是原子的：中斷後新舊程式檔混在一起，重跑同一個回滾才會收斂。
- 重現：`python -c "import sys;sys.path.insert(0,'backend/tools');import deploy_dashboard as d;print({k:d._JOB_TIMEOUT_MIN.get(k,d._JOB_TIMEOUT_DEFAULT_MIN) for k in ['upgrade-convert','upgrade-rollback-code','upgrade-rollback-full']})"`，得到 `{convert:45, rollback-code:20, rollback-full:20}`。
- 建議修法：
  - 不可逆的步驟（convert、rollback-*）上限至少與 convert 相同，或更長。
  - 逾時訊息依步驟區分：回滾逾時要明說「回滾可能只做了一半——等正式機恢復後重跑同一個回滾（可以收斂）」。

**A-2　健康檢查的磁碟只認 C:（S-CP02 未修完）**
- 位置：DI:164。`if d.get("name") == "C" and …`。清單裡沒有 C，或安裝根目錄不在 C: 時，一律放行。
- STATES S-CP02 的「應有行為」寫的是「磁碟找不到 ⇒ 未確認（不放行）」。產品會賣給客戶自架，安裝在 D: 很常見（MODULE-GUIDE／記憶〈不可以用安裝路徑猜正式機〉同一類）。
- 重現：`python -c "import sys;sys.path.insert(0,'backend/tools');import deploy_insights as i;f={'alertActive':False,'latestDbBackup':{'at':__import__('datetime').datetime.now().isoformat(timespec='seconds'),'name':'x'},'disks':[{'name':'D','freeGB':0.1}],'port666Listen':1,'devMarkers':[],'piiFolders':['x']};print(i.evaluate_health(f))"`，得到 `ok: True`（D: 只剩 0.1 GB 也放行）。
- 建議修法：
  - PHF 回傳安裝根目錄所在的磁碟代號。
  - 規則改看那一顆；找不到就列為 problem。

**A-3　`test_alert_and_dev_markers_are_collected` 在 C 的環境是紅的（輸出編碼沒固定）**
- 位置：PHF 本身沒有設定 `[Console]::OutputEncoding`。測試以 `encoding="utf-8"` 解讀 powershell 的 stdout（tests/platform/test_deploy_dashboard_health_facts.py:19-21）。
- C 的環境（系統字碼頁 cp932）得到 `alertText='�_�[�H…'`，於是 `AssertionError`。
- 同一個腳本經 `_dashboard_remote.ps1` 執行時，外層有設 UTF-8（DD:613），所以正式路徑大概沒問題。但測試的結果取決於跑的人的主控台字碼頁；B 的全量在別的環境可能是綠的，造成「你那邊綠、我這邊紅」。
- 重現：`cd backend && python -m pytest tests/platform/test_deploy_dashboard_health_facts.py::test_alert_and_dev_markers_are_collected -p no:cacheprovider --basetemp=<自己的暫存>`
- 建議修法：PHF 開頭加一行 `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8`（腳本自己決定輸出編碼，不依賴呼叫者）。

### 建議

- **B-1　部署 `_run_job` 的看門狗沒有測試**：只測了 `_run_upgrade_job` 會逾時中止；`_run_job`（deploy／rollback／build）接了同一支 `_start_watchdog`（DD:526），但沒有題目。另外成功路徑（`success=True` 寫進歷史）也沒測；目前兩題都是失敗路徑。
- **B-2　升級紀錄檔讀不懂時永遠卡住**：新開一輪與結束一輪都拒絕 `corrupt`（DD:1166-1170、1192-1193），只能人工處理 `upgrade_session.json`，但 RUNBOOK 與畫面都沒寫要怎麼處理。建議畫面顯示檔案位置與「改名成 .bad 後重新整理」這類步驟，並寫進 UPGRADE-RUNBOOK。
- **B-3　逾時後的狀態**：逾時後 job 標為 `failed`，但實際是「未知」。訊息已經說明了；建議另設一個 `timeout` 狀態，讓歷史與「15 分鐘內剛失敗」的判斷區分得出來。

### 觀察

- **C-1**：新鮮度用的是 `.done` 的修改時間，不是資料夾名稱的日期（PHF:22；DI:152）。舊日期資料夾的 `.done` 如果被重寫過，會看起來很新。實務上 `.done` 在當天寫入，影響很小。
- **C-2**：伺服器端仍然不管步驟順序，這是 STATES S-CU08（中），不在這次範圍內。
- **C-3**：一輪升級結束之後，UI 就不能再對那一份備份做回滾（步驟要求進行中的那一輪）。這是合理的，但要在畫面上提醒「回滾完成前不要結束這一輪」。

## 3. 反向控制與假綠燈檢查

- **S-CP02 突變**：拿掉 PHF 的 `.done` 條件後，`test_only_daily_snapshot_with_done_counts` 轉紅（C 實測，檔案已還原）。
- **假綠燈**：`test_evaluator_consumes_real_script_output` 驗的是「只有 pre_update 時不放行」。但 PHF 的名稱正規式本來就排除 `pre_update_*`，所以這題證明不了 `.done` 規則；證明它的是上一題。兩題要一起留著。
- **失敗路徑**：S-CU01 已測逾時。回滾路徑的逾時上限沒有測（A-1）。

## 4. 回覆欄（被稽核者填；C 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | C 確認 |
|---|---|---|---|
| A-1 | 修正。上限分開設：rollback 60、upgrade-rollback-code 60、upgrade-rollback-full 90，都比 convert 45 長。另外，會改正式機而且不是原子的動作（deploy、rollback、停／啟服務、backup、convert、兩種回滾）逾時**不自動中止**：只標記逾時、鎖不放，由人看過 log 後按「解除鎖定」並寫原因（`POST /api/jobs/{id}/release`，記歷史）。突變：deploy 移出不中止清單 ⇒ 紅 | 本回覆同一分支 || ✅ 關閉（5246caa2）。實測上限 convert 45／rollback-code 60／rollback-full 90／rollback 60；不中止清單含 8 個會改正式機的動作。**接受**「不中止、人工解除」：理由成立（本機 taskkill 殺不到遠端、中止只會製造半套），而且逾時狀態看得見、解除要寫原因並記歷史；解除時才砍本機行程樹（DD `release_timed_out_job`） |
| A-2 | 修正。PHF 回傳 `installDrive`；evaluate_health 只看安裝碟；拿不到碟代號或清單裡沒有那一顆 ⇒ 不放行。新增 3 題；突變：改回寫死 C ⇒ 紅 | 同上 || ✅ 關閉。實測：installDrive=D 且 D: 0.1 GB ⇒ problem；缺 installDrive ⇒ problem「拿不到安裝目錄所在的磁碟代號」 |
| A-3 | 修正。PHF 開頭設定 `[Console]::OutputEncoding` 為 UTF-8；測試刻意先把主控台設成 cp932 再跑。突變：拿掉那一行 ⇒ 紅 | 同上 || ✅ 關閉。C 的環境（cp932）health_facts 全綠；突變拿掉 OutputEncoding 那一行 ⇒ 紅（C 實測，已還原） |
| B-1 | 修正。補兩題：deploy 逾時不中止並且需要解除、deploy 成功路徑寫入成功歷史；另外補「沒有逾時的工作不可以解除鎖定」 | 同上 || ✅ 關閉。`test_deploy_dashboard_jobs` 59 題中含 deploy 逾時不中止／成功路徑／未逾時不可解除 |
| B-2 | 修正。`POST /api/upgrade/session/reset-corrupt`：要寫原因，原檔改名封存為 `upgrade_session.corrupt-<時間>.json`（不刪），記歷史；頁面只有在讀不懂時才顯示這顆按鈕 | 同上 || ✅ 關閉（8303fc69）。原先維持開啟的理由：B-2a 產出檔存在≠完成、B-2b 手動回滾缺 --root／--mode（見下方複核）；兩處已更正並保留原句，判讀規則與指令 C 已核對（argparse 接受 `rollback --root … --backup-dir … --mode full --yes`） |
| B-3 | 採納。新增 `timeout` 狀態（`_final_status`）；頁面在 succeeded、failed、timeout 三種狀態都會停止輪詢 | 同上 || ✅ 關閉（`_final_status`，timeout 與 failed 分開） |
| C-1 | 修正。新鮮度以「資料夾日期的隔天 0 點」為上限；補一題 | 同上 || ✅ 關閉（新鮮度上限＝資料夾日期隔天 0 點） |
| C-2 | 不在這次範圍：伺服器端步驟順序屬於 STATES S-CU08（中），列在階段 S | — || ✅ 同意移出本次（S-CU08，階段 S） |
| C-3 | 修正。「結束這一輪」按鈕旁加上提醒：結束後就不能再對這一份備份做回滾，回滾完成前不要結束 | 同上 || ✅ 關閉（頁面提醒） |

### B-2 複核（C，2026-09-25，對 `30aedef8` 的 UPGRADE-RUNBOOK §6b）

- **B-2a（必修，文件錯）**：§6b ① 第 3 點寫「檔案存在並寫完，代表那一步其實已經完成」。這句是錯的，三個檔在失敗時也會寫：
  - `backup_verify.json`：不論試還原成敗都寫（`tools/platform/upgrade.py:111`，內容是 `{"problems": [...]}`）。
  - `conversion_log.json`：migration 失敗時也寫（`:131`，內容 `migrate.ok=false`）。
  - `verify_log.json`：不論成敗都寫（`:157`）。

  正確的判讀方式：
  - `backup_verify.json` 的 `problems` 是空的；
  - `conversion_log.json` 的 `migrate.ok` 是 true，**而且**有 `settings_added` 鍵（只有成功路徑才寫，`:133-134`）；
  - `verify_log.json` 的 `problems` 是空的。

  照原文判讀的後果：migration 失敗的轉換會被當成「已完成」，然後接著做下一步。
- **B-2b（必修，指令錯）**：§6b ② 第 4 點的 `upgrade.py rollback --backup-dir <原本的 BK>` 少了必要參數，照打會被 argparse 擋下。正確是 `python <NEW>/tools/platform/upgrade.py rollback --root <ROOT> --backup-dir <原本的 BK> --mode code`，或 `--mode full --yes`，見 §6。
- 其餘內容 ✅：
  - 逾時不重按；先看 log 與行程，確認停下後才解除，並寫原因。
  - 讀不懂時不開新的一輪；封存、不刪；回滾沒做完就改在正式機手動執行。
