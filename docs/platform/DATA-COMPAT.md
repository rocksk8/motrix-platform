# 既有資料相容性盤點（DATA-COMPAT，初版 2026-09-25）

> 視窗 C 產出。只讀盤點，未改產品碼。行號取自 `platform` 分支 HEAD `30336130`＋當時工作樹（`main.py`、`email_notify.py` 他人改動中，行號可能漂移，以符號名為準）。
> 正式機一律未連線；需要實況的列在 §7「待查」。

## 0. 結論

1. **推薦 A（原地讀取）為預設，確認主持人傾向**；B 不建議當成「升級時一次搬」，改成「A 上線穩定後，由 L1 路徑解析層提供可選的單項搬遷」。理由三條，皆有程式碼證據：
   - DB 內存的檔案路徑**都是相對路徑**（uploads 相對 `UPLOADS_ROOT`、PDF 版本相對各自 base）⇒ A 不需改任何資料列；B 也不需改資料列，但要搬的是檔案本身（uploads＋6 個 PDF 目錄，可能在網路碟）與雲端鏡像，失敗面大、回滾貴。
   - V9 的 migration 計數器只有一列（`schema_version.id=1`）。新版若**不動這一列**、模組版本另存新表，V9 程式碼回退後照常啟動 ⇒ A 的回滾＝換回舊程式碼即可。
   - 真正的風險不在「資料在哪」，而在**模組化搬檔會讓 `__file__` 算出來的路徑靜默換位置**（§2）。那正是 A 的 L1 路徑解析層要解決的事——A 不是妥協，是必要工作。
2. **🔴 最高風險（搬檔前必須先處理）**：`db.py` 若搬進 `core/`，`DB_PATH` 會指到 `backend/core/motrix_erp.db`，`sqlite3.connect` 會**建一個新的空庫**並從 v1 跑到 v116 ⇒ 系統「正常啟動、資料全空」。不是報錯，是成功。
3. **🔴 第二高**：`email_notify._is_production_install()` 以安裝路徑含 `\V9.0\` 判定正式機（`helpers/email_notify.py:20-25`）。新版裝在任何其他路徑 ⇒ **正式機所有通知信靜默不寄**。這違反既有記憶〈不可以用安裝路徑猜正式機〉；`quotations.py:548` 已改掉同一問題，`email_notify` 沒改。
4. 派工單的兩處前提需更正（§8）：PDF 輸出目錄是 **6 個不是 4 個**；CORE-SPEC §6 寫的「v1~v84」實際是 **v1~v116**。

## 1. 資料位置總表

「決定方式」代號：**B**＝相對 `backend/`（`dirname(__file__)`）、**R**＝相對專案根（`dirname(dirname(__file__))` 或 `backend/..`）、**S**＝`system_settings` 可覆寫、**E**＝環境變數、**C**＝相對工作目錄（啟動腳本 `cd backend`）、**W**＝寫死、**D**＝執行期偵測。

### 1.1 資料庫

| 項目 | 位置 | 方式 | 程式碼 | 擁有者 |
|---|---|---|---|---|
| 主庫 | `backend/motrix_erp.db` | B | `db.py:16`、連線 `db.py:170-183` | L1 core:db |
| WAL／SHM | `backend/motrix_erp.db-wal`、`-shm` | 隨主庫 | `db.py:174`（`journal_mode=WAL`） | L1 core:db |
| demo 庫（＋WAL） | `backend/motrix_erp_demo.db` | B | `db.py:17`、重建 `db.py:249-297` | L1 core:db |
| migration 計數 | 表 `schema_version`（單列 id=1） | — | `db.py:428`、`_get_version db.py:795-837`、`_set_version db.py:840` | L1 core:db |
| 會計科目靜態檔（v94 讀） | `backend/data/account_items_112.json` | B | `db.py:4318-4326` | 凍結 migration（資料屬 M06） |
| 舊庫名（無讀寫者） | `backend/motrix.db` | — | 只出現在 `.gitignore`、`tools/verify_package.py:157` | 遺留，待查 |

### 1.2 使用者檔案

| 項目 | 位置 | 方式 | 程式碼 | 擁有者 |
|---|---|---|---|---|
| 上傳根目錄 | `<根>/uploads/` | R（**5 處各自計算**） | `helpers/uploads.py:20`、`routers/uploads.py:19`、`photos.py:10`、`archive.py:115`、`db.py:25-26` | L1 helper:uploads |
| 　子目錄寫入者 | `uploads/<subfolder>/<doc_no>/` | 呼叫端給 subfolder | 寫：`helpers/uploads.py:96-120`；搬移：`routers/quotations.py:2847-2860`（M01）；附件：`helpers/voucher_attachments.py:268-273`（M06）；刪：`routers/dev_crm.py:954`（M02）、`routers/quotations.py:2835,5556`（M01） | 根 L1；子目錄屬各 L2 |
| 案件／工作日誌照片 | `uploads/projects/…` | R | `photos.py:10-20`、`routers/system.py:564-579` | L1 core:photos |
| DB 內的上傳路徑 | 相對 `UPLOADS_ROOT` | — | `routers/quotations.py:2833`、`routers/system.py:579`（`projects/worklog_…`） | — |
| demo 上傳／照片 | `uploads/_demo_uploads/`、`uploads/_demo_projects/` | R | `db.py:25-26`、`helpers/uploads.py:31` | L1 core:db |

### 1.3 PDF 輸出（6 個，全部 R 預設＋S 可覆寫）

| 單據 | 預設目錄（專案根下） | 設定鍵 | 程式碼 | 業務擁有者 |
|---|---|---|---|---|
| 報價單 | `報價單PDF/` | `pdf_base_path` | `pdf_gen.py:18-36` | M01 case |
| 出貨單 | `出貨單PDF/` | `shipping_pdf_base_path` | `pdf_gen.py:23-43` | M03 supply |
| 承攬商匯款申請 | `承攬商匯款申請PDF/` | `contractor_voucher_pdf_base_path` | `pdf_gen.py:45-61` | M04 subcontract |
| 開票申請憑據 | `開票申請憑據PDF/` | `invoice_voucher_pdf_base_path` | `pdf_gen.py:50-68` | M05 arap |
| 請款單 | `請款單PDF/` | `payment_request_pdf_base_path` | `pdf_gen.py:70-81` | M05 arap |
| 結案報表 | `結案報表PDF/` | `case_closing_pdf_base_path` | `pdf_gen.py:83-94` | M01 case |
| 勞報單存檔（第 7 個，另一套） | `backend/export_archive/` | **B，無設定鍵** | `routers/payslips.py:31-45,359,425` | M07 payroll |
| demo 對應 7 目錄 | `backend/_demo_*_archive/` | B | `db.py:27-37` | L1 core:db |
| DB 內的 PDF 路徑 | 報價單 docVersions 存相對 base；**跨磁碟機時退回只存檔名** | — | `pdf_gen.py:433-454`、解析 `routers/quotations.py:5744-5760` | — |

產生器 `pdf_gen.py` 是 L1（core:pdf_gen），目錄歸屬是各業務模組 ⇒ 見 §4 A-3。
其餘 PDF／Excel（傳票、網規、報表、`wb.save(buf)` 類）一律走 `tempfile` 或記憶體回傳，不落地（`helpers/voucher_pdf.py:390-410`、`network_plan_export.py:398-421`、`routers/reports.py:2313-2332`）。

### 1.4 備份與雲端

| 項目 | 位置 | 方式 | 程式碼 | 擁有者 |
|---|---|---|---|---|
| 本機 DB 快照 | `backend/db_backups/YYYY-MM-DD/` | B | `archive.py:113,991-1006`（Online Backup API）、清理 `archive.py:1223-1287` | L1 core:archive |
| 部署前快照 | `backend/db_backups/pre_update_<ts>/` | B | `tools/apply_update.ps1:242-260` | 部署工具 |
| 程式碼回滾快照 | `backend/rollback_snapshots/<ts>/` | B | `tools/apply_update.ps1:344-358`、`tools/rollback_update.ps1:141` | 部署工具 |
| 備份告警 | `<根>/backup_alerts/`（`BACKUP_ALERT.txt`＋日誌） | R | `archive.py:114,415-460` | L1 core:archive |
| 雲端存檔根 | `<任一磁碟機>:\我的雲端硬碟\系統存檔` | **D（掃 A-Z，取第一個）** | `archive.py:59-82` | L1 core:archive |
| 　子目錄 | 即時／每日／週／月備份、上傳檔案鏡像、PDF存檔鏡像/<6 類> | D | `archive.py:86-107,1109-1145` | L1 core:archive |
| 雲端所有權標記 | `<雲端根>/.motrix_archive_owner` ↔ `system_settings.archive_instance_id` | D＋S | `archive.py:207-276` | L1 core:archive |
| 本機不上雲標記 | `<根>/.no_cloud_archive` | R；`MOTRIX_CLOUD_ARCHIVE`（E）優先 | `archive.py:157-176` | L1 core:archive |
| S3 後端 | `system_settings.cloud_backup_target`；金鑰走 boto3 環境鏈 | S＋E | `cloud_storage.py:3-24,52` | L1 core:cloud_storage |
| 保留天數 | `system_settings.backup_retention` | S | `archive.py:53` | L1 core:archive |

### 1.5 設定檔、憑證、身分檔

| 項目 | 位置 | 方式 | 程式碼 | 擁有者 |
|---|---|---|---|---|
| 心跳設定 | `backend/heartbeat_config.json` | B | `heartbeat_job.py:14,31` | L1 core:heartbeat_job |
| 授權金鑰 | `backend/license.key` | B | `helpers/licensing.py:58-61,303`；機器指紋 `:540-558` | L1 helper:licensing |
| TLS 憑證 | `backend/certs/cert.pem`、`key.pem` | **C**（啟動腳本）＋B（到期檢查） | `start.bat:25`、`restart.bat:38`、`autostart.bat:29`；讀 `routers/daily_tasks.py:1285-1306` | L0 啟動／M12 讀 |
| 初始帳密 | `backend/.initial_admin_credentials.txt`、`.initial_demo_credentials.txt` | B | `helpers/auth.py:37,116`、`helpers/startup.py:156` | L1 helper:auth／startup |
| 打包 SHA | `backend/.build_commit` | B | `helpers/build_info.py:43-53` | L1 helper:build_info |
| 已套用版本 | `backend/.deployed_commit.json`（`apply_update.ps1` 寫） | B | `routers/auth.py:329-346` | L1 router:auth |
| 版本清單 | `backend/version_manifest.json`（隨程式碼出貨，非資料） | B | `helpers/startup.py:361-374`、`routers/auth.py:290-320` | L1 |
| Edge 路徑 | `system_settings.edge_path`，否則寫死兩個 Program Files 路徑 | S＋W | `helpers/startup.py:23-35` | L1 helper:startup |
| 字型 | `C:\Windows\Fonts\msjh*.ttc` | W | `routers/contractors.py:17-19`、`photos.py:99` | M04／L1 |
| `.env` | **無讀取者**（grep `dotenv`／`.env` 0 筆）；只在 `.gitignore` | — | — | — |
| 其他設定 | 全在 `system_settings`（SMTP、Google 行事曆 OAuth 等） | S | `archive.py:1575-1585`（備份時剝除密鑰） | L1 helper:settings |

### 1.6 Log 與暫存

| 項目 | 位置 | 方式 | 程式碼 | 擁有者 |
|---|---|---|---|---|
| 伺服器 log | `backend/logs/server.log`（輪替 5 代×50MB） | 啟動腳本重導（**寫死正式機絕對路徑**）＋B | `autostart.bat:20-32`；輪替 `archive.py:1169-1214` | L0 |
| 備份排程 log | `backend/logs/backup_job.log` | B | `backup_job.py:15-26` | L1 core:backup_job |
| 心跳 log | `backend/logs/heartbeat_job.log` | B | `heartbeat_job.py:15-19` | L1 core:heartbeat_job |
| Edge PDF 暫存 | 系統 `%TEMP%` | `tempfile` | `pdf_gen.py:516-519` 等 | L1 core:pdf_gen |

### 1.7 派工單列的但程式碼沒有的

| 項目 | 結論 |
|---|---|
| `exports/` | `.gitignore` 有，**產品碼 0 個寫入者**（Excel 匯出全是 `wb.save(buf)` 記憶體回傳）。遺留目錄，正式機是否存在待查 |

## 2. 模組化搬檔的 `__file__` 風險

規則：`dirname(__file__)` 算的是「這支檔案在哪」，不是「資料在哪」。搬檔深度 +1 ⇒ 所有相對路徑往下偏一層。CORE-SPEC §3 的 `modules/<key>/api/` 是 backend 下 **3 層**，現在 `routers/`、`helpers/` 是 **1 層**。

失敗型態：**響**＝啟動或呼叫就報錯；**靜**＝照常運作但讀寫到新的空位置（最危險）。

| 檔案:行 | 現在指向 | 預計搬到 | 搬後指向 | 型態 | 後果 |
|---|---|---|---|---|---|
| `db.py:16-17` | `backend/*.db` | `core/db.py` | `backend/core/*.db` | **靜** | 🔴 建新空庫、跑 v1→v116，資料全空而系統正常 |
| `db.py:25-37` | demo 目錄 | `core/` | 下偏一層 | 靜 | demo 檔案落到新位置（demo 會重建，影響小） |
| `db.py:4318` | `backend/data/…json` | `core/` | `backend/core/data/` | 響（只在全新安裝） | v94 `raise`；只有「全新安裝／災難還原」那條路會踩到 |
| `pdf_gen.py:18-84` | 專案根 | `core/pdf_gen.py` | `backend/` | **靜**（僅未設定 `*_pdf_base_path` 時） | 新 PDF 寫到 `backend/報價單PDF/`；舊版本下載 404；雲端 PDF 鏡像改鏡像新空目錄 |
| `archive.py:111-115` | `backend/`、根 | `core/archive.py` | `backend/core/`、`backend/` | **靜** | 本機快照換目錄（舊的不再被清理）；`uploads` 鏡像來源變不存在目錄 ⇒ `_mirror_directory_incremental` 回 0 不報錯 |
| `archive.py:157` | `<根>/.no_cloud_archive` | 同上 | `backend/.no_cloud_archive` | **靜** | 🔴 開發機標記失效 ⇒ 預設允許 ⇒ **開發機開始往雲端寫**（盲側：它擋不到的那一側） |
| `photos.py:10` | `<根>/uploads/projects` | `core/` | `backend/uploads/projects` | 靜 | 新照片寫到錯處；舊照片仍由 `UPLOADS_ROOT` 服務，新照片 404 |
| `routers/payslips.py:31` | `backend/export_archive` | `modules/payroll/api/` | `backend/modules/payroll/export_archive` | **靜** | 新勞報單存到模組內；舊的下載失敗；**刪除模組資料夾＝刪掉勞報單存檔**（牴觸 CORE-SPEC §9-5 反向控制） |
| `routers/daily_tasks.py:1285` | `backend/certs/cert.pem` | `modules/daily_tasks/api/` | `backend/modules/daily_tasks/certs/` | 靜 | 回 `None`＝「純 HTTP 模式」⇒ 憑證到期提醒永遠不觸發 |
| `helpers/uploads.py:20`、`routers/uploads.py:19` | `<根>/uploads` | `core/`（同深度） | 不變 | — | 若改放 `core/<sub>/` 則下偏 |
| `helpers/auth.py:37`、`startup.py:156,361`、`build_info.py:43`、`licensing.py:58`、`routers/auth.py:290,329` | `backend/` | `core/`（同深度） | 不變 | — | 同上：只要進 `core/` 下一層就全偏 |
| `backup_job.py:15`、`heartbeat_job.py:13` | `backend/` | `core/` | `backend/core/` | 響＋靜 | `sys.path` 插錯 ⇒ import 失敗（響）；排程工作指到舊檔路徑（`setup_*_task.ps1`） |
| `main.py:39` | `<根>/frontend` | `platform/` | 偏移 | 響 | 前端 404 |
| `core/loader.py:17`、`core/source_tree.py:10` | `backend/modules` | 已在位 | — | — | 已正確 |
| `email_notify.py:20-25` | 看安裝路徑字樣 | 不論搬不搬 | — | **靜** | 🔴 新版不裝在 `\V9.0\` ⇒ 正式機不寄信（與深度無關，與安裝路徑有關） |

**M11 標案雷達案例**：搬移前後 `__file__` 皆 0 筆（`git show c83dae6e:backend/routers/tender_radar.py`、`helpers/tender_source.py` 驗過），模組不擁有任何檔案位置，只用 DB 表 ⇒ **搬移安全，但它證明不了任何路徑風險**——它是本表的空集合，不是正對照。另：`module.json` key 為 `tender_radar`，`modules.json` 為 `tender`，兩者不一致（守門是否比對待 B 確認）。

## 3. 資料庫

| 項目 | 值／證據 |
|---|---|
| V9 基準 `c83dae6e` 的 `CURRENT_VERSION` | **116**（`db.py:133`）；V9 原版 repo HEAD 同為 `c83dae6e`、116 |
| 本分支 | 116（只改了 7 支選型 migration 的 import 路徑，`db.py:2205-3259`） |
| 引擎 | `schema_version(id=1, version)` 單列；`_run_migrations` 從 `current+1` 跑到 116（`db.py:849-895`）；庫比程式碼新 ⇒ 只記 WARNING 不擋 |
| 正式機實際版本 | 待查（§7） |

**接法（提案）**：

1. `core` 基準＝V9 的 `_MIGRATIONS` 1~116 原封不動，**繼續用同一列 `schema_version` 計數**，並把 116 凍結為 `V9_BASELINE`。
2. 模組 migration 用**另一張表**記版本；CORE-SPEC §6 的名稱 `schema_versions` 與既有 `schema_version` 只差一個 s，建議改名 `module_schema_versions`，避免手寫 SQL 打錯表。
3. 啟動順序：跑基準到 116 → 基準不等於 116 就**拒絕跑任何模組 migration**：
   - `< 116`：先補跑基準（V9 舊庫的正常升級路徑）
   - `> 116`：代表 V9 在基準凍結後又加了 migration 而新版不認得 ⇒ **拒絕，不是 WARNING**（現行引擎的「只記 log」前提是「只加不改」，跨兩條產品線無法保證）
4. 模組的第一支 migration 一律是「認領既有表」（`IF NOT EXISTS`，對 V9 庫是 no-op）。
5. 模組 migration 同樣只能加不改（沿用 `test_u5c_no_migration_makes_a_column_disappear` 的規則）⇒ 回退 V9 程式碼時，V9 看到 `schema_version=116`、不認得的表不讀，照常啟動。

**V9 庫直接升上來的路**：V9 庫（≤116）→ 新版啟動 → 補跑基準到 116 → 各模組 `0001_adopt` → 模組新 migration。資料與檔案都不動。

**要裁示的衝突（2 項）**：
- CORE-SPEC §6「模組未安裝 ⇒ 不建表」與「基準＝V9 1~116」互斥：全新安裝時基準會建出所有 V9 表（含已遺棄的選型表與未安裝模組的表）。
- V9 原版持續維護期間若新增 v117+，新版基準必須同號同內容跟進，否則第 3 點會把升級擋下。需要一條規則：切換日前 V9 新 migration 雙寫，或切換日凍結 V9 schema。

## 4. 方案比較

### A 原地讀取（推薦預設）

資料位置一律不動；L1 新增唯一的路徑解析層（例：`core.paths`），所有位置從它取，錨點是**安裝根目錄**而不是呼叫者的 `__file__`。

| | 內容 |
|---|---|
| 優點 | 資料零搬移；DB 零改寫；V9 部署工具（`apply_update.ps1` 的排除清單、`db_backups/`、`rollback_snapshots/`）原樣可用；雲端所有權 `archive_instance_id` 在同一個庫裡 ⇒ 雲端寫入不中斷 |
| 前置工作 | A-1 路徑解析層取代 §2 表中所有 `__file__` 路徑，並加守門：產品碼（除 `core/paths`）出現 `dirname(__file__)`＋資料名稱即紅；A-2 `email_notify` 改明確旗標；A-3 `export_archive/` 納入 L1、加設定鍵，與其餘 6 個 PDF 同一規則；A-4 `uploads` 根的 5 處定義收斂成 1 處 |
| 風險 | 路徑解析層本身是單點——錨點算錯＝全部一起錯。對策：啟動時比對「DB 檔存在且 `schema_version` 可讀」，不存在就**拒絕啟動**而不是建新庫（全新安裝要明確旗標） |
| 回滾 | 換回 V9 程式碼即可；前提是模組 migration 只加不改（§3-5） |

### B 升級時一次轉移

升級腳本把 DB、uploads、7 類 PDF、備份目錄搬進新結構（例：`data/`、`modules/<key>/files/`）。

| | 內容 |
|---|---|
| 優點 | 目錄結構與模組對齊；刪模組時可一併處理其檔案 |
| 缺點 | PDF 目錄可能被設定到網路碟（`*_pdf_base_path`），搬移跨機器；報價單跨磁碟機的歷史版本只存了檔名（`pdf_gen.py:433-435`），搬後無法可靠還原到正確子目錄；雲端鏡像（`上傳檔案鏡像`、`PDF存檔鏡像`）結構要跟著變或重傳；`apply_update.ps1` 的排除清單要重寫，否則下一次部署會覆蓋新位置 |
| 風險 | 搬到一半失敗＝兩邊各有一半；WAL 模式下直接搬 `.db` 會漏 `-wal` 內的交易（必須用 Online Backup API，比照 `archive.py:1002-1006`） |
| 回滾 | 需反向搬回＋還原 DB 快照；升級後產生的新檔要另外合併 ⇒ **時間越久越難回** |

### 推薦

**A 為預設，確認**。B 改成「A 之後、由路徑解析層逐項開放可選的搬遷目標」（先改設定、再搬一類、驗證、下一類），而不是升級時一次搬。證據：DB 內路徑已是相對路徑、V9 計數器單列可保留、`__file__` 風險無論選 A 或 B 都必須先修——B 在 A 的前置工作之上再加一層搬遷風險，沒有換到 A 做不到的東西。

## 5. 正對照（清單沒漏的依據）

1. **寫入點全掃**：腳本掃 `backend/` 產品碼（排除 `tests/ tools/ scripts/ migrations_frozen/`）的 `open( makedirs mkdir shutil.* os.replace/rename/remove/unlink rmdir write_text/bytes sqlite3.connect _connect( FileHandler NamedTemporaryFile .save( FileResponse StaticFiles listdir scandir walk .backup(`：**183 處／30 檔**。逐檔追到路徑來源，每一處都落在 §1 某一列或屬「記憶體／暫存不落地」。
2. **路徑來源全掃**：`__file__` 54 處（產品碼 39 處，皆已歸入 §2；`helpers/build_info.py:79,145` 為 git 的 cwd，非資料路徑）；`os.environ`／`getenv` 全部——唯一影響資料位置的是 `MOTRIX_CLOUD_ARCHIVE`；寫死磁碟機字母：`C:\Windows\Fonts`、Edge、`autostart.bat`／`*.ps1` 的正式機路徑（`grep V9\.0` 共 11 檔）。
3. **反向對照 `.gitignore`**：它列的是「執行期會長出來、不進版控」的東西。逐條比對，全在 §1；多出來的 `exports/`、`motrix.db` 找不到寫入者（§1.7、§1.1），`tools/.guide_sync_config.json` 屬已遺棄的選型庫。
4. **反向對照部署工具**：`apply_update.ps1:358,445` 的 `/XD`／`/XF` 保護清單（它是「正式機上不可覆蓋的東西」），全在 §1。
5. **已知漏網**：本盤點**不含**前端（`frontend/` 無持久寫入）與 `tools/`、`scripts/`（開發工具，不在正式機執行路徑上——但 `tools/apply_update.ps1` 等部署腳本已列入）。

⚠ 限制：掃描是語法比對，動態組字串的路徑（例：`os.path.join(base, var)`）只能追到 `base` 的來源；正對照證明的是「每個寫入點的 base 都在清單裡」，不是「每個檔名都列出來」。

## 6. 對 CORE-SPEC 的影響（建議，未改規格）

- §6 補：基準＝v116、`V9_BASELINE` 精確比對、模組版本表改名、全新安裝建表範圍待裁示。
- §9 遷移步驟在「2 改相依」與「3 搬檔」之間插入：**改路徑為 `core.paths`，並以守門驗證模組內沒有 `__file__` 資料路徑**。
- §9-5 反向控制「刪掉模組資料夾」前提：模組資料夾內不得有資料檔（`export_archive` 案例）。

## 7. 待查（需正式機實況，本盤點未連線）

| # | 項目 | 為什麼要知道 |
|---|---|---|
| 1 | 正式機 `schema_version` 實際值 | 決定升級要補跑幾支基準 migration |
| 2 | 6 個 `*_pdf_base_path` 是否有設定、指向哪 | 未設定者受 §2 `pdf_gen` 偏移影響；指網路碟者 B 方案要跨機器搬 |
| 3 | 雲端存檔根目前在哪個磁碟機、backend 是 local_drive 還是 s3 | 確認 `archive_instance_id` 延續 |
| 4 | `exports/`、`backend/motrix.db` 是否存在、有無內容 | 決定可否列為遺留不處理 |
| 5 | `uploads/`、7 個 PDF 目錄、`db_backups/` 的容量 | B 方案的搬遷時間與空間 |
| 6 | `.no_cloud_archive` 是否只存在開發機 | 確認 §2 盲側風險的影響面 |

## 7b. 待裁示

| # | 項目 | 現況 | 為什麼要裁示 |
|---|---|---|---|
| 1 | 勞報單存檔（`export_archive/`）上雲端鏡像 | V9 起就**不在** PDF 鏡像清單（`archive.py:1126-1131` 只列 6 類）⇒ 只有本機一份 | 勞報單含個人資料（身分證字號等），上雲前需使用者裁示（主持 2026-09-25） |
| 1→ | ✅ 裁示：進雲端，放獨立、權限更窄的 `系統存檔_個資`（人建、程式不建根目錄，不存在就告警） | 新版實作：`archive._mirror_pii_archives`；設定頁顯示狀態 | — |
| 2 | ~~承攬人員身分證／存摺影像 base64 每天進一般每日 JSON~~（C 18:3x 回報，**錯**） | ❌ 錯：V9 的 `_export_table_json_set` 已對每列做 `_strip_inline_images`（2026-09-14），影像換成佔位字串。C 只看了 `archive.py:1603` 的 `SELECT *`，沒看匯出函式 | 更正後的描述由主持轉給使用者並重新取得裁示 |
| 2→ | 實際曝險：**整庫 `.db`** 每日／每月複製到一般 `系統存檔\每日備份`、`月備份`（含全部 F2 影像與 F3 祕密）；另 `payslips.data_json` 的身分證字號／地址／電話／Email 是純文字，會進一般每日 JSON | ✅ 裁示 (a)：整庫 `.db` 只放 `系統存檔_個資`；一般每日 JSON 排除 F2 欄位（`archive._F2_FIELDS`），完整列另存個資資料夾；還原以 `merge_general_and_pii` 合回（DR-SOP §3a）。V9 不修（使用者接受的風險，CORE-SPEC K2） | — |
| 3 | 歷史雲端每日備份（已含整庫 `.db`） | 裁示：保留不動，不盤點、不刪除 | — |
| 4 | `contractors` 的 `id_number`／`phone`／`email`／`address`／銀行帳號是純文字個資，**仍在一般每日 JSON**（裁示①只點名三個影像欄） | 未處理 | 與 `payslips.data_json` 的同類欄位處置不一致，需要使用者決定是否一併列為 F2 |

## 7c. 實作進度（2026-09-25 第二輪）

| 項目 | commit |
|---|---|
| A-1 `core/paths.py`＋契約測試＋主庫不存在拒絕（`MOTRIX_CREATE_NEW_DB`） | `bef3e25d`、`41151687` |
| A-2 email 改明確旗標（`.no_email_send`／`MOTRIX_EMAIL_SEND=off`，預設寄） | wip/c-email |
| A-3 `export_archive` 設定鍵 `payslip_archive_path` | `41151687` |
| A-4 uploads 根收斂 | `41151687` |
| §3 V9 基準比對＋`module_schema_versions` | `c057832a` |
| F2 個資資料夾（勞報單鏡像、整庫 `.db`、F2 完整列、合回、守門） | wip/c-payslip-cloud |
| 守門：`__file__` 資料路徑、`V9.0` 字樣（正對照：對 `c83dae6e` 原版報出 59 處／1 處） | wip/c-email |

## 8. 更正（保留錯的那一列）

| 原寫法 | 實際 | 證據 |
|---|---|---|
| 派工單「四種 PDF 輸出目錄」 | 6 個 `pdf_gen` 目錄＋1 個勞報單 `export_archive`＝7 | `pdf_gen.py:18-94`、`routers/payslips.py:31` |
| CORE-SPEC §6「v1~v84 的歷史凍結」 | v1~v116 | `db.py:133` |
| 派工單「已搬的 tender_radar 當第一個案例」 | 可當案例，但它是空集合（無 `__file__`、無檔案位置），不是風險的正對照 | §2 末段 |
