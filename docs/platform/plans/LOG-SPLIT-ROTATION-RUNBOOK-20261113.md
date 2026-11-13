# 日誌分流與輪替 交付說明（給步驟檔用，2026-11-13）

作者：hichan-2。起因：正式機 `logs\server.log` 53 MB 且持續增長，每次備份都在 `archive.py` 的 `open(path,'r+b')` 出現 `PermissionError`；使用者（jeff）要求「日誌必須分流和輪替，不可以無限變大」。
程式在分支 `fix/backlog-bugs-20261113`。設計全文見 `backend/helpers/log_setup.py` 檔頭；本文只講**套用後的樣子與要確認的事**。

## 0. 這次改了什麼（一頁）

| 層 | 內容 |
|---|---|
| 分流 | server 行程自己用 `RotatingFileHandler` 寫 `logs\access.log`（uvicorn access）與 `logs\app.log`（應用程式、uvicorn error、其他全部，含 ERROR／Traceback）。**單檔 15 MB、保留 10 份**；滿了輪替成 `access.log.1.gz`…（背景 gzip，不卡請求）。行程內輪替，不經任何外部 handle ⇒ 不會被鎖。 |
| server.log 兜底 | 仍是 `autostart.bat` 的 `>>`（**autostart.bat 一個字都不用改**）。但只剩：① 開機那一段 INFO（到「Uvicorn running on」為止）② WARNING 以上 ③ `print`／其他 stdout。分流之後應該只有少量內容。超過 50 MB 仍由 `archive._rotate_server_log_if_large` 用 ftruncate 清（上一個 commit 已修掉 PermissionError 與掉資料的洞）。 |
| 為什麼開機那一段要留在 server.log | `apply_update.ps1`／`apply_module_update.ps1` 的健康檢查**讀 server.log**：找 `MOTRIX ERP starting`＋`Uvicorn running on`＋`模組 X 版本 已載入`＋開關行 `MOTRIX_GEO=1`，再掃之後有沒有 `Traceback|ERROR`。這些都保留；ERROR 兩邊都寫。 |
| 保留期 | 輪替出來的舊檔（`access.log.N.gz`、`app.log.N.gz`、舊的 `server.log.N`）超過 `retention.log_keep_days`（設定中心 →「保存期限」→「系統日誌保留天數」，**預設 30**，7～3650）每天備份時自動刪。現行檔永遠不刪。 |
| 噪音 | `ConnectionResetError [WinError 10054]`（`_ProactorBasePipeTransport._call_connection_lost`）：Windows asyncio proactor 在**客戶端突然斷線**（關分頁、手機換網路、隧道重連）時的已知現象，CPython 無法在應用層避免，無害。現在**只計數、不寫 traceback**（累計次數在每日備份的 log 裡印一行）。別種例外照舊完整記錄。部署腳本原本就會濾掉這個區塊，行為相容。 |
| 同批順手確認 | 正式機上 `404 /pages/undefined/settings/company-profile`（14 次）與 `404 /settings/company-profile`（10 次）＝**D1／D2**（案件管理據點清單打錯網址、簽核佇列少了 `/api`），同一分支已修（commit：`fix(case-management)`／`fix(approval-queue)`），套用後這兩種 404 應不再出現。 |

行為不變的承諾：資料庫、API、畫面都沒動；只多兩個 log 檔與一個設定項。開不了檔（磁碟滿、權限）⇒ **整個分流自動不啟用**，維持舊的單一 server.log，不會因此起不來。

## 步驟 1 套用前（唯讀，記下基準）

```powershell
$b = "<ROOT>\backend\logs"
Get-ChildItem $b -File | Sort-Object LastWriteTime | Select-Object Name, @{n='MB';e={[math]::Round($_.Length/1MB,1)}}, LastWriteTime | Format-Table -AutoSize
```

記下 `server.log` 的大小（MB）。

## 步驟 2 套用（照既有的更新流程；不需要改 autostart.bat、不需要手動停啟）

照 `UPDATE-DELIVERY.md` 的標準流程套用本分支所在的列車。**更新程序本身會重啟服務**，不另外做事。

## 步驟 3 套用後要確認（全部都要過）

```powershell
$b = "<ROOT>\backend\logs"
# 3.1 新的 log 檔已出現，而且在長大
Get-ChildItem $b -File -Filter "access.log*", "app.log*" | Select-Object Name, Length, LastWriteTime | Format-Table -AutoSize
# 3.2 開機那一段仍在 server.log（健康檢查靠它）
Get-Content "$b\server.log.1","$b\server.log" -Tail 400 -Encoding UTF8 -ErrorAction SilentlyContinue | Select-String -Pattern "MOTRIX ERP starting","Uvicorn running on","已載入" | Select-Object -Last 6   # server.log 若剛被輪替（≥50 MB 清空），啟動行在 server.log.1
# 3.3 server.log 不再被 access 灌：開機之後不應該有 `"GET /... HTTP/1.1" 200` 這種行
(Get-Content "$b\server.log" -Tail 2000 -Encoding UTF8 | Select-String -Pattern 'HTTP/1\.1" \d{3}').Count
# 3.4 沒有 PermissionError（備份／輪替那一步）
Get-Content "$b\app.log", "$b\server.log" -Tail 5000 -Encoding UTF8 | Select-String -Pattern "PermissionError" | Select-Object -Last 5
# 3.5 沒有 WinError 10054 的 traceback
(Get-Content "$b\app.log", "$b\server.log" -Tail 5000 -Encoding UTF8 | Select-String -Pattern "WinError 10054").Count
```

判定：

| 檢查 | 預期 |
|---|---|
| 3.1 | 有 `access.log`、`app.log`，修改時間是現在；有人操作後 `access.log` 會長大 |
| 3.2 | 找得到最近一次的 `MOTRIX ERP starting`、`Uvicorn running on`、`模組 … 已載入` |
| 3.3 | 開機之後的行數 **0**（或僅開機前後暫時性的少數） |
| 3.4 | **沒有輸出** |
| 3.5 | **0** |
| 舊的 `server.log` | **開始變小**：第一次每日備份（或下一輪備份）之後，若超過 50 MB 會被清空並產生 `server.log.1`；之後它只會緩慢成長（只有開機 INFO＋WARNING 以上） |

### 3.6 設定中心確認
最高管理者 → 設定中心 → 「保存期限」群組：看到「系統日誌保留天數」＝30（進階欄位在「顯示進階」裡）。

### 3.7 一週後複查（選做）
`Get-ChildItem <ROOT>\backend\logs`：`access.log.N.gz`、`app.log.N.gz` 各不超過 10 份；`server.log` 仍是小檔。

## 步驟 4 回退（只在需要時）

只想**暫時關掉分流**（回到單一 server.log）：在 `autostart.bat` 的 `cd /d` 之前加一行 `set MOTRIX_FILE_LOGS=0`，重啟排程工作（不是只重啟 uvicorn）。不需要還原程式；已經產生的 `access.log*`／`app.log*` 留著，超過保留天數會自動清（或手動刪）。
