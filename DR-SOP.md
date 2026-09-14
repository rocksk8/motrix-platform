# MOTRIX ERP — 災難復原 SOP（Disaster Recovery）

> 建立日期：2026-08-07
> 適用範圍：正式機（`Motrix` 帳號，`C:\Users\Motrix\Desktop\V9.0`）整體不可用時的復原流程
> 與 [`MOTRIX-ERP-QUICK.md`](MOTRIX-ERP-QUICK.md) §0/§1/§8 搭配閱讀——本文件只處理「機器掛了怎麼辦」，
> 日常開發/部署仍以 QUICK 文件為準

---

## 1 · 為什麼需要這份文件

目前正式環境是**一台常駐的 Windows 桌機**，沒有備援機器、沒有虛擬化、沒有異地熱備援。
備份機制本身已經做得不錯（見 QUICK §8：雙層排程 + 原子寫入 + 雲端/本機雙副本），
但「備份存在」跟「真的能在可接受時間內重建整套可運作的系統」是兩件事——後者從未演練過。
這份 SOP 就是要把「重建」這件事寫成可以照著做的步驟，而不是等真的出事才臨時想辦法。

## 2 · 現況評估（RTO / RPO）

| 情境 | 現況 RPO（可能遺失多少資料） | 現況 RTO（估計恢復時間） |
|------|------------------------------|--------------------------|
| ERP 服務程序當掉，機器本身正常 | 0（autostart crash-restart 迴圈接手） | ≤ 5 秒（見 QUICK §1.1） |
| Windows 需要重開機，機器本身正常 | 0 | 開機後 90 秒（autostart 排程延遲）+ 開機時間 |
| SQLite 檔案損毀，機器硬體正常 | ≤ 24 小時（上次每日備份，部分模組如報價單有即時 JSON，接近 0） | 未演練，估計 30–60 分鐘（人工還原） |
| **整台機器硬體故障（本文件重點）** | 同上（取決於雲端 H: 是否可用） | **未知——從未演練過，是本文件要補的洞** |

**結論**：前三種情境現有機制已經覆蓋得不錯；最後一種（整機掛掉）是目前唯一沒有被驗證過的情境，也是本文件的主要內容。

## 3 · 已知阻塞點（寫這份 SOP 時發現）

在能真正照著 §4 走之前，以下缺口會讓復原流程卡住：

1. ✅ ~~`setup_autostart_task.ps1` / `setup_heartbeat_task.ps1` 原本只存在於正式機，開發機 git repo 沒有~~（QUICK §0 已知落差第 2 筆，記錄於 2026-08-01）。**2026-08-08 已解決**：使用者透過 RDP 連上正式機、將兩個原始檔案改名為 `.orig` 保留後把內容貼回，逐行 diff 校正一致：
   - `setup_autostart_task.ps1`：正式機版本用 `$env:WINDIR\System32\wscript.exe` 絕對路徑（不是裸 `wscript.exe`）、action 有帶 `WorkingDirectory`、trigger 用 `$env:COMPUTERNAME\$env:USERNAME` 完整帳號、`Settings` 明確帶 `RunOnlyIfNetworkAvailable=$false`、沒有另外建立 `$principal` 物件、`Register-ScheduledTask` 帶 `-ErrorAction Stop`——都已對齊。
   - `setup_heartbeat_task.ps1`：Python 路徑正式機是寫死 `pythonw.exe`（不是動態偵測、也不是 `python.exe`）、同樣沒有額外建立 `$principal`（原本猜測用 SYSTEM 帳號是錯的）、`RepetitionDuration` 用 `New-TimeSpan -Days 3650` 而非 `[TimeSpan]::MaxValue`、`ExecutionTimeLimit` 是 3 分鐘不是 2 分鐘、有明確設定 `MultipleInstances=IgnoreNew`——都已對齊。
   - 兩支唯一刻意保留的差異：額外加的「只能在正式機路徑執行」身分守門，正式機原始版本都沒有這段，是重建過程中額外補上的防呆，不影響正式機實際行為。
   **重建過程中意外發現一個額外的坑**（已修復，見 QUICK.md §1.1）：這台開發機的 Windows PowerShell 5.1 在沒有 UTF-8 BOM 時會用系統預設編碼（此機器是 Shift-JIS）誤讀 `.ps1` 裡的中文，導致「只能在正式機執行」的身分守門邏輯本身在解析階段就被打亂、`exit 1` 沒有真的執行——**測試這兩支重建腳本時曾經在開發機上實際觸發過這個問題**（結果沒有真的註冊出東西，因為程式繼續往下跑時用到的變數同樣被編碼問題污染成空值而失敗），已確認事後開發機上沒有殘留任何錯誤註冊的排程工作，且已修正 `setup_backup_task.ps1`/`setup_autostart_task.ps1`/`setup_heartbeat_task.ps1` 三個檔案存成帶 BOM。
2. ✅ ~~`uploads/`（專案照片）目前沒有離線／雲端備份機制~~——**2026-08-08 已解決**：`archive.py` 新增 `_mirror_uploads()`，`_daily_backup()` 每天執行時會把 `uploads/` 底下的檔案（依大小+修改時間判斷是否需要複製，避免同一批照片被複製 365 份）同步到雲端 `H:\我的雲端硬碟\系統存檔\上傳檔案鏡像\`；demo 隔離目錄（`_demo_projects` 等）故意排除，鏡像只增不減。還原時見 §4 Step 3。
   **✅ 2026-09-07 已補齊**：新增 `archive.py::_mirror_pdf_archives()`，沿用 `_mirror_uploads()` 抽出的共用鏡像邏輯，把報價單/出貨單/承攬商匯款申請/開票申請憑據/請款單/結案報表這 6 類 PDF 存檔一併納入每日雲端備份，鏡像位置在 `上傳檔案鏡像` 旁邊的 `PDF存檔鏡像\{類別}\`。呼叫的是 `pdf_gen.py` 各自的 `_get_*_pdf_base()` getter（跟隨 superadmin 可能改到的自訂路徑），不是硬猜預設資料夾。

## 4 · 完整重建 SOP（最壞情境：正式機硬體故障，需要換一台全新機器）

執行前提：手上至少要有其中一份資料庫來源——優先序照 QUICK §8.4：
**舊硬碟還能讀的本機 `db_backups`** → **雲端 H: 的 `motrix_erp.db` 副本** → **JSON 重建（最後手段）**。

### Step 1 — 準備新機器環境

1. 全新 Windows 機器，建立本機帳號（帳號名稱是否延用 `Motrix` 不影響功能，但延用可以少改一些寫死路徑的地方——見 §5 待辦）
2. 安裝 Python（版本比照 `backend/requirements.txt`）、安裝相依套件：
   ```powershell
   pip install -r backend\requirements.txt
   ```
3. 安裝 Microsoft Edge（`pdf_gen.py` 產生 PDF 依賴 Edge headless）、確認路徑在 `_EDGE_CANDIDATES` 涵蓋範圍內（`helpers/startup.py`），否則要用 §3.1 提到的 `edge-path` 設定 API 手動指定
4. 安裝 ffmpeg（若有用到相關功能）

### Step 2 — 取得程式碼

- 優先：`git clone` 正式的 GitHub repo（`origin/master`），確認版本跟最後已知的 `deploy_manifest.json`／`.deployed_commit.json` 記錄的 commit 一致
- 次要：如果 git 暫時拿不到，用最近一份 `deploy_packages/` 底下的部署包（開發機留存）

### Step 3 — 還原資料庫與檔案

1. 把還原來源的 `motrix_erp.db`（含 `-wal`/`-shm` 如果有）複製到 `backend/`
2. 還原 `uploads/`：從雲端 `H:\我的雲端硬碟\系統存檔\上傳檔案鏡像\` 整份複製到專案根目錄的 `uploads/`（2026-08-08 起每日自動同步，見 §3 第 2 點）
3. 還原 PDF 存檔目錄（`backend/_demo_pdf_archive` 等不需要，正式的 PDF 輸出目錄看 `pdf_gen.py`/`system_settings["pdf_base_path"]`——**2026-09-07 起有雲端鏡像可還原**，見 §3 第 2 點：從雲端 `PDF存檔鏡像\{類別}\` 對應複製回各自的 PDF base 目錄即可，跟 uploads/ 是同一套機制）
4. **Migration 驗證**：比照 `apply_update.ps1` 既有的乾跑機制，先在資料庫「副本」上跑一次 `db.init_db()` 確認新版 schema 能正常套用，再套用到正式檔案

### Step 4 — 環境設定

1. 依 [`AUTOLOGON-FIX.md`](AUTOLOGON-FIX.md) 設定 `AutoAdminLogon`（若要延用開機自動登入這個機制）
2. 註冊三個排程工作：
   - `MOTRIX ERP Server Autostart`：目前缺對應腳本，見 §3 第 1 點——這一步在缺口補上前無法照抄，需要人工依 QUICK §1.1 描述的行為重寫
   - `MOTRIX ERP Daily Backup`：執行 `backend\setup_backup_task.ps1`（已修正為動態偵測 Python 路徑，兩台機器都能直接用）
   - `MOTRIX ERP Heartbeat`：同樣缺對應腳本，見 §3 第 1 點
3. 確認 CORS 白名單（**2026-09-11 起不用再改 code**）：新機器 IP 若跟舊的 `172.16.10.177` 不同，設環境變數 `MOTRIX_CORS_ORIGINS`（逗號分隔）即可，不必重新打包。⚙️ **一旦設了就完全取代預設清單、不是附加**，設錯會讓前端打不到自己的 API；不設則沿用原本寫死的六筆（行為跟以前完全一樣）。見 `main.py::_resolve_cors_origins()`

### Step 5 — 驗證

1. 手動啟動（不透過排程）：`backend\start.bat`，確認 `http://127.0.0.1:666/api/ping` 回應正常
2. 用一個非 demo 帳號登入，確認能看到還原後的真實資料（挑幾筆熟悉的報價單/客戶核對）
3. 確認 `demo`/`60575481` 登入仍然正常隔離（不會影響剛還原的正式資料）
4. 確認 `heartbeat_config.json` 的 `ping_url` 設定還在，讓 healthchecks.io 恢復收到打卡
5. 觀察 `backend/logs/server.log` 至少 10 分鐘，確認沒有異常錯誤

## 5 · 待改進（讓下次重建更快）

| 項目 | 說明 |
|------|------|
| ~~補回 `setup_autostart_task.ps1`/`setup_heartbeat_task.ps1`~~ | ✅ 2026-08-08 已完成並跟正式機實際版本校對一致，見 §3 第 1 點 |
| ~~`uploads/` 納入備份範圍~~ | ✅ 2026-08-08 已完成，見 §3 第 2 點 |
| ~~PDF 存檔納入備份範圍~~ | ✅ 2026-09-07 已完成，見 §3 第 2 點 |
| ~~CORS 白名單改用環境變數~~ | ✅ **2026-09-11 已實作**：`MOTRIX_CORS_ORIGINS`，未設定時行為與改動前逐字相同；測試 `test_cors_origins_env_2026_09_11.py`（5 題，含「真的有接進 CORSMiddleware」的接線驗證） |
| 找第二台機器（哪怕只是備用硬體，不必常駐開機）| 把「全新環境安裝」這件事的時間從「臨時採購+安裝」壓縮到「開機+還原資料」|

## 6 · 演練紀錄

> 每次實際演練（哪怕只是部分步驟）都在這裡留紀錄，累積下來才知道 RTO 到底準不準。

| 日期 | 演練範圍 | 結果 | 花費時間 | 發現的新問題 |
|------|---------|------|---------|-------------|
| （尚未演練） | — | — | — | — |
