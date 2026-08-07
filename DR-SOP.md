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

1. 🔴 **`setup_autostart_task.ps1` / `setup_heartbeat_task.ps1` 只存在於正式機，開發機的 git repo 沒有這兩個檔案**（QUICK §0 已知落差第 2 筆，記錄於 2026-08-01，至今仍是「⏳ 待處理」）。這代表如果正式機的硬碟連同這兩支腳本一起報銷，**沒有任何地方留著能重新註冊這兩個排程工作的腳本**——重建時只能憑記憶重寫。
   **行動**：下次能接觸正式機時，把這兩個檔案複製回開發機並 commit 進 git（跟 `setup_backup_task.ps1` 放在一起），比照 §14 跨機核對流程。（仍待處理，優先度最高）
2. ✅ ~~`uploads/`（專案照片）目前沒有離線／雲端備份機制~~——**2026-08-08 已解決**：`archive.py` 新增 `_mirror_uploads()`，`_daily_backup()` 每天執行時會把 `uploads/` 底下的檔案（依大小+修改時間判斷是否需要複製，避免同一批照片被複製 365 份）同步到雲端 `H:\我的雲端硬碟\系統存檔\上傳檔案鏡像\`；demo 隔離目錄（`_demo_projects` 等）故意排除，鏡像只增不減。還原時見 §4 Step 3。
   **仍未涵蓋**：各類 PDF 存檔（報價單/出貨單/勞報單）目前仍不在備份範圍內，之後可考慮用同一套 `_mirror_uploads()` 機制擴充。

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
3. 還原 PDF 存檔目錄（`backend/_demo_pdf_archive` 等不需要，正式的 PDF 輸出目錄看 `pdf_gen.py`/`system_settings["pdf_base_path"]`——**仍是已知缺口，見 §3 第 2 點「仍未涵蓋」**，這步驟目前可能沒有離線副本可還原）
4. **Migration 驗證**：比照 `apply_update.ps1` 既有的乾跑機制，先在資料庫「副本」上跑一次 `db.init_db()` 確認新版 schema 能正常套用，再套用到正式檔案

### Step 4 — 環境設定

1. 依 [`AUTOLOGON-FIX.md`](AUTOLOGON-FIX.md) 設定 `AutoAdminLogon`（若要延用開機自動登入這個機制）
2. 註冊三個排程工作：
   - `MOTRIX ERP Server Autostart`：目前缺對應腳本，見 §3 第 1 點——這一步在缺口補上前無法照抄，需要人工依 QUICK §1.1 描述的行為重寫
   - `MOTRIX ERP Daily Backup`：執行 `backend\setup_backup_task.ps1`（已修正為動態偵測 Python 路徑，兩台機器都能直接用）
   - `MOTRIX ERP Heartbeat`：同樣缺對應腳本，見 §3 第 1 點
3. 確認 `main.py` 的 CORS `allow_origins` 白名單是否需要更新（新機器 IP 若跟舊的 `172.16.10.177` 不同，需要改 code 重新部署——見 QUICK §11 已知風險）

### Step 5 — 驗證

1. 手動啟動（不透過排程）：`backend\start.bat`，確認 `http://127.0.0.1:666/api/ping` 回應正常
2. 用一個非 demo 帳號登入，確認能看到還原後的真實資料（挑幾筆熟悉的報價單/客戶核對）
3. 確認 `demo`/`60575481` 登入仍然正常隔離（不會影響剛還原的正式資料）
4. 確認 `heartbeat_config.json` 的 `ping_url` 設定還在，讓 healthchecks.io 恢復收到打卡
5. 觀察 `backend/logs/server.log` 至少 10 分鐘，確認沒有異常錯誤

## 5 · 待改進（讓下次重建更快）

| 項目 | 說明 |
|------|------|
| 補回 `setup_autostart_task.ps1`/`setup_heartbeat_task.ps1` | 見 §3 第 1 點，優先度最高，唯一還沒解決的項目 |
| ~~`uploads/` 納入備份範圍~~ | ✅ 2026-08-08 已完成，見 §3 第 2 點 |
| PDF 存檔納入備份範圍 | 見 §3 第 2 點「仍未涵蓋」，可沿用 `_mirror_uploads()` 同一套機制擴充 |
| CORS 白名單改用環境變數 | 避免換機器/換 IP 就要改 code 重新部署（呼應顧問審視時提過的一般性建議） |
| 找第二台機器（哪怕只是備用硬體，不必常駐開機）| 把「全新環境安裝」這件事的時間從「臨時採購+安裝」壓縮到「開機+還原資料」|

## 6 · 演練紀錄

> 每次實際演練（哪怕只是部分步驟）都在這裡留紀錄，累積下來才知道 RTO 到底準不準。

| 日期 | 演練範圍 | 結果 | 花費時間 | 發現的新問題 |
|------|---------|------|---------|-------------|
| （尚未演練） | — | — | — | — |
