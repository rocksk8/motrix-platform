# V9 → 新版 升級轉換與回滾 操作手冊（UPGRADE-RUNBOOK）

> 規格：CORE-SPEC §9b。工具：`tools/platform/upgrade.py`（核心 `backend/core/upgrade.py`）。
> 🔴 **對正式機執行是使用者的動作。** 本手冊的每一步都由人在正式機上手動執行、逐步確認；工具不連任何遠端、不猜路徑。
> 下文 `<ROOT>` ＝ V9 安裝根目錄（含 `backend\`、`frontend\` 的那一層），`<BK>` ＝ 備份目錄，`<NEW>` ＝ 新版程式目錄。

## 0. 事前準備（升級前一天以前）

| # | 動作 | 為什麼 |
|---|---|---|
| 0.1 | 在雲端硬碟「我的雲端硬碟」底下手動建立 `系統存檔_個資`，右鍵 → Google 雲端硬碟 → 共用，收窄權限（DR-SOP §3a） | 新版的整庫備份與個資只放這裡；不存在 ⇒ 雲端沒有整庫備份（會告警，但不會自動建） |
| 0.2 | 準備 `<NEW>`：解開新版部署包到**安裝目錄以外**的位置 | 工具拒絕放在 `<ROOT>` 裡的來源 |
| 0.3 | 準備 `<BK>`：一個**新的空目錄**，在安裝目錄以外、空間 ≥ 資料庫大小×3＋程式目錄大小 | 工具拒絕非空或在 `<ROOT>` 裡的備份目錄 |
| 0.4 | 確認 `<ROOT>` **沒有** `.no_email_send`、`.no_cloud_archive` | 有的話轉換後不寄信／不上雲（預檢會擋） |
| 0.5 | 確認 V9 最近一次每日備份正常（本機 `backend\db_backups\<今天或昨天>\.done`）、`backup_alerts\BACKUP_ALERT.txt` 不存在 | 〈出修補包前先查正式機健康〉：有問題先處理，不要疊在升級上 |

## 1. 停服務（轉換與回滾都用這一段）

排程工作（docs/quick §1.1）：`MOTRIX ERP Server Autostart`、`MOTRIX ERP Daily Backup`、`MOTRIX ERP Heartbeat`。

- **Heartbeat 也要停**：轉換期間它會把「服務沒有回應」當成故障發告警。
- 只 Disable 不夠：Autostart 的執行個體是一個「掛掉 5 秒後重啟」的迴圈，要 `Stop-ScheduledTask` 結束它。
- 行程只停 python 系列（比照 `restart.bat`：停正在聽 port 的那一個）。

以系統管理員身分開 PowerShell：

```powershell
$Tasks = @('MOTRIX ERP Server Autostart', 'MOTRIX ERP Daily Backup', 'MOTRIX ERP Heartbeat')
$Port  = 666

# ① 停排程（先 Disable 防止再被觸發，再 Stop 結束正在跑的執行個體）
foreach ($t in $Tasks) {
    Disable-ScheduledTask -TaskName $t | Out-Null
    Stop-ScheduledTask    -TaskName $t -ErrorAction SilentlyContinue
}
Get-ScheduledTask -TaskName $Tasks | Select-Object TaskName, State      # 三個都要是 Disabled

# ② 停掉仍在聽 port 的 python 行程（只停 python 系列）
$c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($p in ($c.OwningProcess | Sort-Object -Unique)) {
    $proc = Get-Process -Id $p -ErrorAction SilentlyContinue
    if ($proc -and $proc.ProcessName -match '^(python|pythonw|uvicorn)') { Stop-Process -Id $p -Force }
    elseif ($proc) { Write-Warning "port $Port 由 $($proc.ProcessName)（PID $p）佔用，不是 python —— 先確認再處理" }
}
Start-Sleep 3
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { Write-Warning "port $Port 仍被佔用" }
```

### 1b. 恢復服務（轉換驗證通過後，或回滾驗證通過後）

- 順序：先服務、確認回應、**最後開心跳**。
- 🔴 **等不到回應也照開心跳**（最多等 240 秒）：服務真的起不來時，心跳告警就是該響的那一聲，不可以讓它一起沉默。輸出會標示失敗，由人決定是否回滾（§6）。
- ping 用 `backend	ools\_healthcheck_ping.py`（Python＋OpenSSL，接受 HTTPS 自簽憑證；`apply_update.ps1` 用的也是它）。exit 0＝收到 200。PS 5.1 的 `Invoke-WebRequest` 對自簽憑證會失敗，不要用。
- 與部署儀表板升級精靈的啟停步驟一致（c61e8c75）。

在 `<ROOT>ackend	ools` 底下，以系統管理員身分開 PowerShell：

```powershell
$Tasks   = @('MOTRIX ERP Server Autostart', 'MOTRIX ERP Daily Backup', 'MOTRIX ERP Heartbeat')
$PingUrl = 'https://127.0.0.1:666/api/ping'      # HTTP 安裝改 http://
$MaxWait = 240                                   # 秒

# ① 服務與備份排程
foreach ($t in $Tasks | Where-Object { $_ -notlike '*Heartbeat*' }) {
    Enable-ScheduledTask -TaskName $t | Out-Null
    if ($t -like '*Autostart*') { Start-ScheduledTask -TaskName $t }
}

# ② 等服務回應（最多 $MaxWait 秒）
$ok = $false; $t0 = Get-Date
while (((Get-Date) - $t0).TotalSeconds -lt $MaxWait) {
    & python .\_healthcheck_ping.py $PingUrl 5 | Out-Null
    if ($LASTEXITCODE -eq 0) { $ok = $true; break }
    Start-Sleep 5
}
if ($ok) { Write-Host "服務已回應 200" } else { Write-Warning "服務 $MaxWait 秒內沒有回應 —— 心跳照開（它會告警）；請決定是否回滾（§6）" }

# ③ 心跳最後開（不論 ② 成敗）
Enable-ScheduledTask -TaskName 'MOTRIX ERP Heartbeat' | Out-Null
Start-ScheduledTask  -TaskName 'MOTRIX ERP Heartbeat'
Start-Sleep 10
Get-ScheduledTaskInfo -TaskName 'MOTRIX ERP Heartbeat' | Select-Object LastRunTime, LastTaskResult
```

- 最後確認 **Heartbeat 打卡恢復**：`LastRunTime` 更新、`LastTaskResult` 為 0，外部監控（healthchecks 類）顯示恢復。② 失敗時心跳會報「服務沒有回應」——那是預期的告警，不是誤報。

## 2. 預檢（不改任何東西）

```
python <NEW>\tools\platform\upgrade.py preflight --root <ROOT> --v9-port <正式 port>
```

- 輸出 `"ok": true` 才往下。任一 `problems` ⇒ 處理後重跑。
- 檢查項目：安裝目錄結構、主庫存在、`schema_version ≤ 116`、磁碟空間 ≥ DB×3、最近快照 `.done`（今天或昨天）、無備份告警、服務已停、無開發機標記。
- `system_settings` 的 `*_pdf_base_path` 指到安裝目錄以外（例如網路碟）時，預檢的 `facts.external_pdf_dirs` 會列出來。這些目錄**只記摘要不算雜湊**（路徑、檔案數、總大小、最新 mtime；主持裁示 2026-09-25），工具不寫它們。

## 3. 備份（＋自動試還原）

```
python <NEW>\tools\platform\upgrade.py backup --root <ROOT> --backup-dir <BK>
```

- 主庫與 demo 庫用 SQLite Online Backup API；程式目錄與設定／身分檔（heartbeat_config、license、憑證、`.env` 類、初始帳密檔）逐檔複製；資料目錄（uploads、7 類 PDF、db_backups…）**原地不動，只記清單與雜湊**。
- 完成後自動把備份還原到暫存位置、逐檔比對 SHA256、主庫 integrity_check 與各表列數。**不通過 ⇒ exit 2，不可以往下。**
- 產出：`<BK>\upgrade_manifest.json`（每個備份檔的雜湊）、`<BK>\backup_verify.json`。

## 4. 轉換

```
python <NEW>\tools\platform\upgrade.py convert --root <ROOT> --backup-dir <BK> --new-source <NEW>
```

- 沒有通過驗證的備份就拒絕執行。
- 刪掉 V9 程式檔、換上新版程式檔；資料、DB、設定一律不動。
- 用新版的 `init_db` 補跑基準 migration 到 v116，並建 `module_schema_versions`。
- 設定只補缺的鍵（目前只有 `payslip_archive_path`＝空字串，意思是用預設目錄）；既有值不改。
- 公司資料只補空值：`company_profile` 缺公司名／英文名／統編／電話／email 時，補上 V9 原本寫死在報表與網路規劃的值（只在看得出是本公司安裝時補；已有值的欄位不動）；補了哪些欄位記在 `conversion_log.json` 的 `company_profile.filled`。
- 產出：`<BK>\conversion_log.json`。

## 5. 驗證

```
python <NEW>\tools\platform\upgrade.py verify --root <ROOT> --backup-dir <BK> --port <正式以外的 port，例如 6671>
```

- 先比資料：各表列數與轉換前相同、既有設定逐項相同、只多出宣告過的新設定鍵、資料目錄清單相同。
- 外部 PDF 目錄：只比「檔案數與總大小沒有變少」（變多可以）。連不到 ⇒ 印「警告（不擋升級）：無法確認…」，記在 `verify_log.json` 的 `warnings`；人工確認網路碟恢復後再看一次即可。
- 再在**非正式 port** 啟動新版、`/api/ping` 200、停掉；啟動後既有設定仍不得被改寫。
- 通過 ⇒ 用正常方式在正式 port 啟動新版（排程工作）。不通過 ⇒ exit 3 ⇒ 進 §6。

## 6. 回滾（出問題時）

| 模式 | 指令 | 效果 | 何時用 |
|---|---|---|---|
| **只回程式**（建議先用） | `upgrade.py rollback --root <ROOT> --backup-dir <BK> --mode code` | 換回 V9 程式；**保留**轉換後寫入的資料 | 新版有問題，但資料要留著 |
| **完整回滾** | `upgrade.py rollback --root <ROOT> --backup-dir <BK> --mode full [--yes]` | 程式＋DB＋設定還原成備份時的樣子（雜湊逐一相等）；轉換後才出現的設定檔會刪掉 | 資料本身有疑慮，要回到升級前那一刻 |

- 完整回滾前工具會列出「轉換後新增的列數」；沒有 `--yes` 不執行。**那些列會消失。**
- 兩種模式都會逐檔比對雜湊（程式；完整回滾另比 DB 與設定），不一致 ⇒ exit 5。
- 回滾前：服務必須是 §1 停止後的狀態（轉換失敗時通常還是；若已經 §1b 恢復過，先再做一次 §1）。
- 回滾完：在非正式 port 啟動 V9 確認 `/api/ping` 200，再做 §1b 恢復服務，最後確認 Heartbeat 打卡恢復。
- 「只回程式」成立的前提：新版對 DB 只做新增（CORE-SPEC §6）。演練已驗證 V9 讀得了新版寫過的庫並正常啟動。

## 6b. 用儀表板操作時的兩種異常（稽核 B-2，2026-09-25）

**① 某一步「逾時」（狀態顯示 timeout，或畫面出現「解除鎖定」）**

- 意思是：**本機等太久了，正式機上的動作可能仍在進行**。儀表板沒有中止它：部署、回滾、停／啟服務、備份、轉換這類會改正式機的步驟，中止只會讓它停在一半。
- **不要重按同一步。** 依序確認：
  1. 儀表板「4. 查看正式機最近 log」：看最後幾行是不是還在動，或者已經印出結束訊息。
  2. 在正式機上看 python／powershell 行程是否還在跑（例如轉換期間的 `upgrade.py`）。
  3. 看 `<BK>` 底下的產出檔。⚠ **檔案存在不代表成功**：這三個檔在失敗時也會寫出來，一定要看內容（稽核 B-2a 更正；原句「檔案存在並寫完，代表那一步其實已經完成」是錯的）：
     - 備份：`backup_verify.json` 的 `problems` 是空的，才算通過。
     - 轉換：`conversion_log.json` 的 `migrate.ok` 是 `true`，**而且**有 `settings_added`（只有成功路徑會寫這一欄）。
     - 驗證：`verify_log.json` 的 `problems` 是空的。
     - 內容不符合，或檔案不存在 ⇒ 當成那一步沒有完成。
- 確認正式機**已經停下來**之後，按「解除鎖定」，並寫明原因（例如「log 顯示轉換已完成，conversion_log.json 已產生」）。這個動作會記進歷史。
- 解除之後，依確認到的實際狀態決定下一步：做完了就接下一步；做一半就依 §6 回滾。

**② 升級紀錄讀不出來（畫面顯示「升級紀錄檔讀不出來」）**

- 儀表板會把讀不出來當成「不確定」，而不是「沒有」，所以不會讓你開新的一輪：開新的一輪會失去舊備份的指向。
- 處理步驟：
  1. 打開 `backend\tools\upgrade_session.json`（開發機上），找出原本這一輪的 `stamp`，也就是正式機 `Desktop\MOTRIX-UPGRADE-BACKUP\<stamp>`。
  2. 確認那一份備份還在正式機上。
  3. 在儀表板按「封存讀不懂的升級紀錄」，並寫明原因（寫下你確認到的備份時間戳）。原檔會改名成 `upgrade_session.corrupt-<時間>.json` 保留，不會刪除。
  4. 如果原本那一輪的回滾還沒做完，**不要從儀表板開新的一輪**：改在正式機上照 §6 手動執行（稽核 B-2b 更正：原句少了 `--root` 與 `--mode`，照打會被擋下）：
     - 只回程式：`python <NEW>\tools\platform\upgrade.py rollback --root <ROOT> --backup-dir <原本的 BK> --mode code`
     - 完整回滾：`python <NEW>\tools\platform\upgrade.py rollback --root <ROOT> --backup-dir <原本的 BK> --mode full --yes`（會丟掉轉換後寫入的資料）

## 7. 事後

- `<BK>` 保留到新版穩定運作為止（建議至少一個月的月備份已產生在 `系統存檔_個資\月備份\`）。
- 設定頁「雲端備份目標」確認「個資存檔（勞報單）雲端資料夾：已就緒」。

## 附：開發機演練（不碰正式機）

```
python tools/platform/upgrade_drill.py --mode both [--source-db <開發機 V9 測試庫>]
```

- 在 `%TEMP%` 建 V9 形狀的安裝目錄（程式取 `c83dae6e`），跑 預檢 → 備份＋試還原 → 轉換 → 驗證 → 寫入一筆新資料 → 回滾 → V9 啟動 ping。
- 演練路徑不可以含 `V9.0`（V9 的寄信判定看安裝路徑）；啟動一律 `MOTRIX_DISABLE_SCHEDULERS=1`、`MOTRIX_CLOUD_ARCHIVE=off`、`MOTRIX_EMAIL_SEND=off`，並放 `.no_cloud_archive`。
- `--source-db` 以 Online Backup API 唯讀複製，來源檔不變（2026-09-25 實測雜湊前後相同）。
- 自動化測試：`backend/tests/test_upgrade_drill_2026_09_25.py`（兩種模式）、`backend/tests/platform/test_core_upgrade.py`（純函式）。
