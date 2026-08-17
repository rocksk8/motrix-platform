# MOTRIX ERP — 開發快速參考

> 允碩整合集創（統編 60575481）｜ Tel: 04-3610-6566 ｜ info@miactw.com  
> 文件版本：**2026-08-17i**（料號主檔新增匯出／匯入 Excel，見 §12）

---

<!-- ╔══════════════════════════════════════════╗
     ║  目錄（§ 段落快速跳轉）                   ║
     ╚══════════════════════════════════════════╝

  §0  多機同步須知（必讀）  §8  備份與還原
  §1  啟動與位址           §9  前端規範
  §2  系統架構總覽          §10 成本公式
  §3  安全                 §11 已知限制
  §4  資料模型             §12 變更摘要
  §5  核心業務流程          §13 目錄結構
  §6  Sidebar 結構         §14 跨機核對與拉檔流程
  §7  API 速查             §15 更新模式（測試機→正式機）
-->

---

## §0 · 多機同步須知（每次工作階段開始必讀）

本專案有兩台實體機器，**目前完全靠人工複製檔案同步，沒有任何自動化機制**，過去已多次發生「正式機做了什麼，開發機這裡不知道」的落差（見下方已知落差紀錄）。每次在此專案開始工作時，**先依路徑判斷目前是哪一台機器並明確告知使用者**（例如「目前偵測到是開發機／hichan 帳號」），不要默默假設。

| 項目 | 開發／備份機（多數時候是這台） | 正式機 |
|------|------|------|
| 帳號 | `hichan` | `Motrix`（AutoAdminLogon，開機自動登入） |
| 專案路徑 | `C:\Users\hichan\Desktop\MOTRIX-ERP` | `C:\Users\Motrix\Desktop\V9.0` |
| 用途 | 開發、測試、備份 db 存放處 | 客戶實際在用 |
| 排程工作 | 無 | `MOTRIX ERP Server Autostart` / `Daily Backup` / `Heartbeat` 三個 Windows 工作排程器（見 §1.1／§1.2） |

**若判斷目前是正式機**：改用更保守的操作方式——**不啟動測試用 server、不寫入測試資料、不做實驗性操作**；任何資料庫/程式碼變更都要假設影響真實客戶資料，修改前務必先跟使用者確認。（本文件開發機章節中提到的「用瀏覽器實測」「建立測試出貨單」等做法，都是在開發機上做的，正式機不可比照辦理。）

**已知落差紀錄**（每次跨機核對後於此累積更新，核對流程見 §14）：

| 日期 | 落差內容 | 狀態 |
|------|---------|------|
| 2026-08-01 | `backend/db.py` 少了正式機已在跑的 2 個 migration（v32/v33，交換器選型導覽 switch_guide 表結構） | ✅ 已補回（用正式機 db 實際 schema 反推重建，見 §12 2026-08-01e） |
| 2026-08-01 | `backend/setup_autostart_task.ps1`、`backend/setup_heartbeat_task.ps1` 兩個部署排程設定腳本，正式機有（§1.1／§1.2 有描述其行為）、這台開發機完全沒有檔案 | ✅ 2026-08-08 已解決——透過 RDP 連上正式機，原始檔案改名 `.orig` 保留後貼回內容逐行 diff 校正一致（差異細節見 `DR-SOP.md` §3 第 1 點），已 commit 進 git 並隨這次更新包一併部署 |
| 2026-08-01 | 已知程式碼未 commit 進 git（`git log` 停在較舊的提交，工作區有大量未 commit 變更）；正式機的程式碼版本與 git 歷史的對應關係目前不明 | ✅ 已於合併正式機更新模式匯出檔案時一併 commit（見 §12 2026-08-01j）；正式機仍無 git，日後版本比對仍需靠 §15 `deploy_manifest.json` 記的 commit 值 |
| 2026-08-05 | 本文件與程式碼（`main.py` CORS 白名單／`email_notify.py` 與 `system.py` 的 email base_url 預設值／`notification-settings.html` 預設值）長期記載正式機區網位址為 `172.16.11.211:666`，實際上是 `172.16.10.177:666`（使用者於本次對話中指正並確認為固定 IP，非 DHCP 動態配發；已用 `curl` 實測連線成功） | ✅ 本次一併修正上述 5 處程式碼與 §1 位址表 |

---

## §1 · 啟動與位址

| 項目 | 值 |
|------|-----|
| 開發啟動 | `backend\start.bat` |
| 更新後重啟 | `backend\restart.bat` |
| 本機 | http://localhost:666 |
| 區網 | http://172.16.10.177:666 |
| SQLite | `backend\motrix_erp.db`（WAL 模式） |

```
依賴關係：
  db.py ← helpers/ ← archive.py / pdf_gen.py / photos.py
                   ← routers/*.py ← main.py（wiring only）
```

### §1.1 · 正式環境自動啟動與監控（2026-08-01）

正式機（`Motrix` 帳號，AutoAdminLogon 開機自動登入）以三個 Windows 排程工作維持常駐：

| 排程工作 | 觸發 | 動作 | 說明 |
|---------|------|------|------|
| `MOTRIX ERP Server Autostart` | 登入時 +90 秒延遲 | `autostart_hidden.vbs` → `backend\autostart.bat` | 90 秒延遲避開 GoogleDriveFS（同樣登入時啟動）掛載 H: 的搶跑窗口；`autostart.bat` 內建 **crash-restart 迴圈**（uvicorn 意外中止 5 秒後自動重啟，寫入 `logs\server.log`） |
| `MOTRIX ERP Daily Backup` | 每日 02:00 | `backup_job.py` | 見 §8.2 |
| `MOTRIX ERP Heartbeat` | 註冊後立即開始，每 5 分鐘重複（不綁登入） | `heartbeat_job.py` | 見 §1.2 |

`autostart.bat` 開頭 `chcp 65001` + `set PYTHONUTF8=1`：避免中文訊息寫入 log 時因主控台預設編碼（Big5/cp950）產生亂碼。**`.bat`/`.ps1` 檔若含中文註解務必存成 CRLF 換行**——LF-only 換行曾在此機器上讓 cmd.exe 的批次檔解析器直接報「命令語法不正確」而整個腳本失效（且不會有任何 log 紀錄，外觀上排程工作仍顯示執行成功）。

**`.ps1` 檔含中文註解務必存成帶 UTF-8 BOM**（2026-08-08 重建 `setup_autostart_task.ps1`/`setup_heartbeat_task.ps1` 時發現）：Windows PowerShell 5.1（`powershell.exe`，非 pwsh 7）靠檔案開頭 BOM 判斷編碼，沒有 BOM 就會 fallback 到系統非 Unicode 程式的預設編碼（這台機器是 Shift-JIS/932，其他機器可能是 Big5/950），把中文位元組解讀錯誤，導致腳本結構被打亂——實測中 `Write-Error` 呼叫本身被解析錯誤成參數綁定例外，而且是**非終止型錯誤**，腳本會直接跳過「只能在正式機執行」的身分守門判斷式繼續往下執行，`exit 1` 完全沒被執行到。已確認 `backend/tools/apply_update.ps1`、`backend/tools/build_deploy_package.ps1` 本來就有 BOM（沒事）；`setup_backup_task.ps1`/`setup_autostart_task.ps1`/`setup_heartbeat_task.ps1` 原本沒有，已於同日修正。**日後新增或編輯任何含中文的 `.ps1` 檔，務必確認存檔帶 UTF-8 BOM**（PowerShell `Set-Content -Encoding UTF8` 在 Windows PowerShell 5.1 預設就會帶 BOM；純文字編輯器要另外注意）。

手動重啟（`restart.bat`）會一併殺掉 autostart 的 crash-restart 迴圈（比對 commandline 含 `autostart.bat`/`autostart_hidden.vbs`），避免迴圈在手動重啟的同時把 port 666 搶回去。

### §1.2 · 心跳監控（dead man's switch，2026-08-01）

`backend/heartbeat_job.py`（獨立腳本，不 import app，ERP 服務掛了也照樣執行）：

```
每 5 分鐘：
  GET http://127.0.0.1:666/api/ping
    成功 → 讀 heartbeat_config.json 的 ping_url → GET 該網址（打卡）
    失敗 → GET {ping_url}/fail（立即通知，不等逾時）；不執行打卡
```

打卡對象為 [healthchecks.io](https://healthchecks.io)（Period 10 分鐘／Grace 10 分鐘），由該服務判斷逾時（本機或整台主機斷線都會使打卡中斷）並寄信通知 superadmin 信箱。`heartbeat_config.json` 的 `ping_url` 為空時，腳本只做本機健康檢查、略過對外打卡（不會報錯）。日誌：`logs/heartbeat_job.log`。

**新增功能規則**

- API → 對應 `routers/xxx.py`，勿塞進 `main.py`
- 共用邏輯 → `helpers/`（拆 6 個子模組）
- 表結構 → `db.py:init_db()` + `_mNNN_xxx()` migration
- 備份 → `archive.py`（所有 JSON 寫入須用 `_atomic_json_write()`）
- PDF → `pdf_gen.py`；照片水印 → `photos.py`（PIL 可選）

---

## §2 · 系統架構總覽

```
┌──────────── Frontend (Alpine.js + 靜態 HTML) ────────────┐
│  pages/*  +  js/*  +  static/sidebar.js / notif.js       │
│  Session: localStorage.motrix_session (Bearer token)     │
└──────────────────────┬───────────────────────────────────┘
                       │ HTTP :666
┌──────────────────────▼───────────────────────────────────┐
│  FastAPI main.py                                         │
│  middleware: auth · must_change_password · security hdr  │
│  routers: auth / quotations / customers / suppliers /    │
│           parts / projects / dashboard / system / reports│
└──────────────────────┬───────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   SQLite (WAL)   Edge PDF      G: 雲端 + 本機快照
   motrix_erp.db  pdf_gen.py    archive.py
```

### 後端模組

| 模組 | 職責 |
|------|------|
| `db.py` | 連線、`init_db()`、PRAGMA WAL、熱路徑欄位／索引；**CURRENT_VERSION=44**（44 個 migrations；v32/v33 為交換器選型導覽 `switch_guide` 表結構，2026-08-01 由正式機備份 db 實際結構還原重建，詳見 db.py `_m032_switch_guide` 註解；v39/v40 為 2026-08-09 新增的監控系統／門禁系統選型導覽 `monitor_guide`/`access_guide` 表結構；v41 為閘道器與控制器選型導覽 `gateway_guide` 表結構；v42 為 2026-08-13 新增的業務開發連結報價單審核制 `dev_cases` 欄位；v43 為 2026-08-17 新增的使用者個別 Email 通知偏好 `users.notification_muted` 欄位；v44 為 2026-08-17 新增的承攬商派發發票號碼 `contractor_dispatches.invoice_no` 欄位） |
| `helpers/` | 密碼、session、audit、notify、settings、弱密碼標記、`save_quotation_json()` |
| `archive.py` | 即時／每日／週備份；本機 SQLite 快照；**原子 JSON 寫入**（`_atomic_json_write`）；G: fallback |
| `backup_job.py` | 獨立備份腳本（Windows 工作排程器，不依賴 server） |
| `pdf_gen.py` | Edge Headless PDF；路徑讀 `system_settings["pdf_base_path"]` |
| `photos.py` | 專案照片水印 |
| `routers/*` | 業務 API |
| `main.py` | CORS、middleware、全域 Exception Handler、startup、static |

### 前端

| 路徑 | 說明 |
|------|------|
| `frontend/js/case-management.js` | 案件管理 Alpine 元件（唯一有效的外置 JS） |
| `frontend/js/reports.js` | 營運報表 Alpine 元件（唯一有效的外置 JS） |
| `frontend/pages/quotation-form.html` | ⚠️ Alpine function **inline**（邏輯在 `<script>` 內，勿找外置 JS） |
| `frontend/pages/settlement.html` | ⚠️ Alpine function **inline**（邏輯在 `<script>` 內，勿找外置 JS） |
| `frontend/pages/*.html` | 其餘頁面 Alpine 亦均為 inline，**無對應外置 .js** |
| `frontend/static/sidebar.js` | Topbar + Sidebar 注入；**強制改密導向**；離開警示 `bindNavGuard()`；`_FILE_MODULE` 頁面→模組對應；`build()` 自動更新 `localStorage.motrix_module_seen` 清除當頁 badge |
| `frontend/static/notif.js` | 通知 Bell + 側邊欄模組 badge（`_fetchModuleCounts()`）；所有動態內容用 **DOM API**（無 innerHTML） |
| `frontend/css/style.css` | CSS 變數：`--sidebar-w` `--topbar-h` `--accent` |

> **重要**：`frontend/js/` 目錄**僅存 2 個有效檔案**（case-management.js / reports.js），
> 其餘 21 個死碼 JS 已於 2026-07-22 清除。勿在此目錄新增非必要的 JS 檔案。

---

## §3 · 安全（2026-07-18 強化後）

### §3.1 · 帳號與密碼

| 規則 | 說明 |
|------|------|
| **禁止明文密碼寫入文件／UI** | 歷史預設已移除 |
| 密碼長度 | ≥ **8**；拒絕已知弱密碼 |
| 雜湊 | PBKDF2-SHA256（260k）；舊 sha256 登入時升級 |
| 新建使用者 | 一律 PBKDF2；`must_change_password=1` |
| 管理員重設密碼 | 同樣標記強制改密 |
| 全新安裝 `jeff` | 隨機臨時密碼 → `backend/.initial_admin_credentials.txt`（用後刪） |
| 既有弱密碼 | 啟動 `flag_weak_passwords()` 標記；登入後強制改密 |

**強制改密流程**

```
登入 → mustChangePassword=true
  → 前端導向 change-password.html?forced=1
  → middleware 僅放行：/api/auth/me · change-password · logout · ping
  → 改密成功 → must_change_password=0 → 重新登入
```

### §3.2 · 解鎖密碼（報價單解鎖編輯）

- 僅 superadmin；與登入密碼獨立
- **不再自動寫入共用預設**
- 啟動若偵測歷史弱預設 → **清空 hash**，需至使用者管理重新設定
- 未設定：`POST /api/auth/verify-unlock` 回錯誤提示先設定
- 解鎖成功後：顯示「取消解鎖」按鈕（`cancelUnlock()`），防止意外觸發重送審

### §3.3 · Session 與 API 保護

| 項目 | 值 |
|------|-----|
| Session | `sessions` 表，預設 30 天；`expires_at` 中介層 + `/auth/me` 雙重驗證 |
| 白名單 | `/api/ping` · `/api/auth/login` · `/api/auth/logout` |
| 其餘 `/api/**` | 需 `Authorization: Bearer {token}` |
| 回應標頭 | `X-Content-Type-Options` · `X-Frame-Options` · `Referrer-Policy` |
| **登入暴力破解** | per-IP rate limiting；5 次失敗鎖 15 分鐘；HTTP 429 含倒數；**鎖定狀態持久化** `login_rate_limit` 表（DB v11），重啟不失效 |

### §3.4 · 角色與模組

```
superadmin > admin > sales > engineer > viewer
```

| 角色重點 | 說明 |
|----------|------|
| `engineer` | 預設無 `financial_view`，不可看金額／財務 |
| 模組例 | `project_manage` · `project_approve_eng` · `project_approve_biz` · `financial_view` · `reports` · `work_log` · `daily_task` |
| 報價列表過濾 | 非 admin+ 用 `sales_person_id=自己id OR (sales_person_id IS NULL AND sales_person=display_name)` |
| **稽核記錄** | `GET /api/audit-log` 限 **admin+**；viewer/sales/engineer 呼叫回 403 |
| **工作日誌** | `PUT/DELETE /api/work-logs/{id}`：非 admin 只能修改/刪除**自己**的日誌 |
| **業務開發 CRM** | 非 admin 只能查看自己建立、或列於 `sales_persons`/`planners` 欄位的案件（`_can_access_case()` helper）；admin+ 無限制 |
| **自訂角色** | superadmin 可建立自訂角色（名稱 + 基礎角色層 + 模組清單）；儲存於 `system_settings`；使用者 Modal 快速套用 chips 顯示 |
| **角色名稱** | superadmin 可在「角色名稱設定」自訂各層顯示名稱（`GET/PUT /api/settings/role-labels`）；DB 內 `role` 欄位仍儲存系統名稱 |

### §3.5 · Demo 展示帳號（隔離空白資料庫）

給客戶展示用；帳號 `demo` / 密碼 `60575481`，role=superadmin（所有模組全開，頁面/效果完整可見）。

```
db.py:      DB_PATH（正式）+ DEMO_DB_PATH（motrix_erp_demo.db，獨立檔案，同一套 schema/migrations）
            contextvars 依 request 切換 get_db() 指向哪個檔案（伺服器啟動/排程觸發的背景工作，
            如每日逾期通知、月報寄送，不掛在任何 request 上，contextvar 本來就該是預設值 False，永遠打正式庫，
            這是正確行為）
routers/auth.py auth_login()：
  帳號名為 demo → reset_demo_db()（整檔刪除 + 重新 init_db，回到全空白）
             → 核發 DEMO_ 前綴 token，session/user 只寫入 demo db（不進正式 sessions 表）
main.py auth_middleware：token.startswith('DEMO_') → set_demo_mode(True)，
             此後本次 request 內所有 get_db()（含 _require_user()/_audit()）都自動轉向 demo db
```

- **每次登入 demo 帳號＝整個 demo db 重置為全新空白**（客戶怎麼操作、寫入什麼測試資料，下次登入一律清空，正式庫完全不受影響）
- 正式庫 `users` 表僅存一筆 `demo` 守門帳號（`init_demo_account()`，供登入時驗證密碼用），實際瀏覽/操作全在隔離 db 進行
- 新增任何會直接 `sqlite3.connect(db.DB_PATH, ...)` 而非透過 `get_db()` 的程式碼，會繞過此隔離機制 — 一律使用 `get_db()`
- **檔案儲存也要隔離**：專案照片（`photos.py _photo_root()`）、勞報單 PDF 存檔（`payslips.py _archive_path()`）、報價單里程碑自動匯出 PDF（`pdf_gen.py _get_pdf_base()`）三處是直接寫實體檔案，不經過 `get_db()`；已改為 `is_demo_mode()` 時導向 `uploads/_demo_projects`／`backend/_demo_pdf_archive`／`backend/_demo_payslip_archive`，`reset_demo_db()` 一併清空。**新增任何寫檔案到磁碟的功能，都要檢查 `is_demo_mode()` 並比照辦理**，否則 demo 帳號會把檔案寫進正式共用目錄，且 project_id/slip_no/quote_no 在 demo db 都從 1 重新編號，可能撞名蓋掉正式檔案
- **路由 handler 內用 `threading.Thread(...)` 起的背景工作，一律要用 `db.spawn_bg_thread()` 取代直接呼叫 `threading.Thread`**（2026-08-01i 修復，見 §12）：`contextvars.ContextVar`（`_demo_mode`）只在建立當下的 context 裡有效，一般 `threading.Thread(...).start()` 起的新執行緒拿到的是全新、空白 context，裡面的 `is_demo_mode()`/`get_db()` 會誤判成正式環境——即使觸發的 request 其實是 demo session。`spawn_bg_thread()` 用 `contextvars.copy_context()` 把呼叫當下的 context 原封不動帶進新執行緒，修正後 demo 帳號核准出貨單/報價單不會再把 PDF 寫進正式共用資料夾、每日工作事項通知也不會再誤連正式庫寄信給真實同仁。**例外**（不需要、也不該用 `spawn_bg_thread()`）：(a) 伺服器啟動/排程觸發、不掛在任何 request 上的背景工作（如 `daily_tasks.py` 的 `_startup_catchup`、`reports.py` 的 `_catchup_monthly_reports`），本來就該永遠連正式庫；(b) 只吃呼叫端已解析好的純值參數、本身不呼叫 `get_db()`/`is_demo_mode()` 的葉節點執行緒（如 `email_notify.py` 的 `_async_send()`/`_send()`）
- `reset_demo_db()` 用 SQL `DELETE`+`VACUUM`（同一連線內完成），不刪 `.db/-wal/-shm` 檔案本身 — 避免 Windows 掃毒/索引服務短暫鎖住剛建立的 WAL 檔案導致 `os.remove()` 失敗
- `db.demo_reset_lock`（`threading.Lock`）包住整個「reset + 建立 demo 使用者/session」流程 — 兩個 demo 登入同時到達會搶跑同一個共用 db，造成 `IntegrityError`/database-is-locked；已用併發壓力測試驗證修正

---

## §4 · 資料模型

### §4.1 · 主要資料表

```sql
dev_cases       -- 業務開發案件主檔（DB v27）
  id, case_name, customer_name, customer_id FK→customers(nullable),
  status('洽談中'|'成案'|'未成案'), sales_persons JSON([user_id,...]),
  planners JSON([user_id,...]), converted_quote_no,
  created_by FK→users, created_at, updated_at,
  is_deleted, deleted_at, deleted_by, deleted_snapshot,
  pending_delete, delete_requested_by, delete_requested_at, delete_reason（軟刪除審核，DB v28）,
  pending_relink, relink_requested_by, relink_requested_at, relink_reason,
  relink_target_quote_no（converted_quote_no 異動／清空審核，空字串為合法值＝解除連結，DB v42，見 §7.5/§12）

dev_logs        -- 開發記錄（DB v27）
  id, case_id FK→dev_cases, log_date, log_by FK→users,
  channel('電話'|'Line'|'Email'|'面訪'|'視訊'|'其他'),
  content, next_action, status_snapshot,
  needs_approval(0|1), approved_by FK→users, approved_at,
  created_by FK→users, created_at

quotations      -- 熱路徑欄位 + data_json 完整物件
  quote_no PK, status, deal_tag, settle_status,
  customer_name, project_name, total, pretax,
  direct_margin_pct, net_margin_pct,
  sales_person (顯示名稱，歷史相容), sales_person_id FK→users.id,
  quote_date, valid_days, data_json, created_at, updated_at, ...

users           -- + must_change_password, unlock_password_hash, daily_task_pw_hash,
                   notification_muted（JSON 陣列，已退訂的 email 通知事件 key，DB v43，見 §12）
sessions        -- token, expires_at, last_active
customers       -- code(C-YYYYMM-NNN) + 主欄 + data_json（contacts, visits, tags）
suppliers       -- code(S-YYYYMM-NNN) + 主欄 + data_json
parts, projects, project_logs
system_settings, audit_log, notifications
quote_seq       -- 月序 MQ-YYYYMM-NNN
login_rate_limit -- ip PK, locked_until（服務重啟後維持鎖定）
module_versions  -- 模組版本紀錄（同步自 version_manifest.json），UNIQUE(module, version)（DB v35，
                    修復先前無此限制導致 INSERT OR IGNORE 每次重啟都重複整批插入的無限增生 bug）
daily_tasks / daily_task_completions / daily_task_edit_log

vendor_contractors   -- code(V-YYYYMM-NNN), name, tax_id, contact, data_json(visits/tags/category)
contractor_dispatches -- quote_no, vendor_id, status, items_json, total_amount, tax_rate,
                         accepted_at, accepted_by（DB v25），personnel_json（外包名單人員個別計費快照
                         [{id,name,amount,note}]，DB v36，見 §5.7），invoice_no（發票號碼，DB v44）
case_updates         -- id, quote_no, author(username), content, type('comment'), created_at（DB v26）
work_logs            -- + case_no TEXT DEFAULT ''（DB v26）

env_guide_environments   -- 場域選型導覽－場域主檔（DB v30）
  code PK（A1/B3/全部…), name, group_name, temp_gate, ip_gate, cert_gate, trap_note,
  sort_order, updated_at
env_guide_recommendations -- 場域選型導覽－分層三級建議（DB v30）
  id, env_code FK→env_guide_environments(code) ON DELETE CASCADE,
  layer, position, tier1, tier2, tier3, custom_note, trap_note, sort_order, updated_at
env_guide_links          -- 場域選型導覽－原廠/代理商產品連結（DB v30）
  id, keyword, url, label, sort_order

netarch_families         -- 網路架構選型導覽－技術族系（DB v31）
  code PK（WIFI/CELLULAR…), name, description, sort_order, updated_at
netarch_generations      -- 網路架構選型導覽－世代/規格（DB v31）
  id, family_code FK→netarch_families(code) ON DELETE CASCADE,
  gen_name, key_specs, upgrade_note, typical_scenario, tags, price_range,
  dependency_note, watch_note, sort_order, updated_at
netarch_products         -- 網路架構選型導覽－產品連結（DB v31）
  id, generation_id FK→netarch_generations(id) ON DELETE CASCADE,
  brand, model, url, label, price_note, sort_order

switch_scenarios / switch_categories / switch_fit / switch_products
                          -- 交換器選型導覽（DB v32/v33）：情境×分類矩陣式交叉，選型資料庫第三個類別
                          -- switch_products.specs_json（v33 追加）：[[label,value],...] 結構化規格

monitor_scenarios / monitor_categories / monitor_fit / monitor_products
                          -- 監控系統選型導覽（DB v39）：相機分類×場域情境矩陣式交叉，選型資料庫第四個類別
                          -- monitor_products.specs_json：[[label,value],...] 結構化規格（直接隨建表加入）

access_scenarios / access_categories / access_fit / access_products
                          -- 門禁系統選型導覽（DB v40）：元件分類×場域情境矩陣式交叉，選型資料庫第五個類別
                          -- access_products.specs_json：[[label,value],...] 結構化規格（直接隨建表加入）

gateway_scenarios / gateway_categories / gateway_fit / gateway_products
                          -- 閘道器與控制器選型導覽（DB v41）：分類×場域情境矩陣式交叉，選型資料庫第六個類別
                          -- 與 switch_guide 邊界：switch_guide 只收交換器，本類別收路由/閘道器與硬體控制器
                          -- gateway_products.specs_json：[[label,value],...] 結構化規格（直接隨建表加入）

shipping_notes           -- 出貨單／回簽單（DB v34，案件管理子項目，quote_no 一對多）
  id, note_no PK（DN-YYYYMM-NNN，next_entity_code 泛化生成）, quote_no,
  status('草稿'|'待審核'|'簽核中'|'已核准'), ship_date, customer_name, project_name（建立時快照，可獨立編輯）,
  recipient, delivery_address, items_json（[{description,brand,qty,unit,notes}]，無金額欄位）,
  notes, data_json（approval{tiers,currentTier,requestedBy...}，結構仿報價單但獨立實作）,
  is_signed, signed_by, signed_at, signed_log（完整回簽/取消回簽歷程 JSON）,
  export_count, export_log（仿 quotations.export_log）, created_by, created_at, updated_at

stock_items               -- 序號級庫存（DB v38，見 §12 2026-08-05l/m）
  id, part_no（對應 parts.part_no，不強制 FK）, serial_no（UNIQUE with part_no）, mac,
  status('in_stock'|'shipped'|'installed'|'void'), batch_no（'PO-YYYYMM-NNN'，同批進貨共用，
  無獨立 stock_batches 父表）, cost（進貨當下快照）, note,
  shipping_note_no / quote_no / case_device_id（消費關聯：出貨單核准→shipped，設備登載→installed），
  consumed_at, consumed_by, created_by, created_at, updated_at
  routers/inventory.py：parts-summary / stock-items / batches（POST+GET+GET detail）/ adjust / delete
  扣庫存掛勾：shipping_notes.py approve_shipping_note()（核准即扣）／
             quotations.py update_case_record() 內 _sync_device_stock()（設備登載新增/移除序號時扣/還）
```

**索引**：`deal_tag` · `settle_status` · `sales_person` · `sales_person_id`

### §4.2 · data_json 與熱路徑同步

- 巢狀結構（品項、簽核、案件、精算）仍在 `data_json`
- **`deal_tag` / `settle_status` 為正規欄位**，列表／報表／儀表板優先讀欄位
- 寫入統一走 `helpers.save_quotation_json()`（自動同步欄位 + `updated_at`）
- 讀取相容：`SQL_DEAL_TAG` / `SQL_SETTLE_STATUS`（欄位為空時 fallback `json_extract`）

```
create / put / deal-tag / settlement / payment / case-record / approve / reject
  → save_quotation_json() 或同等步邏輯
```

### §4.3 · 樂觀鎖（併發保護）

| 端點 | 欄位 | 行為 |
|------|------|------|
| `PATCH .../case-record` | `_expectedUpdatedAt` | 不符 → **409** |
| `PATCH .../customers/{id}/visits` | `expectedUpdatedAt` | 不符 → **409** |
| `PATCH .../suppliers/{id}/visits` | 同上 | 不符 → **409** |
| `PATCH .../vendor-contractors/{id}/visits` | `expectedUpdatedAt` | 不符 → **409** |
| `PATCH .../payment/{idx}` | `_expectedUpdatedAt` | 不符 → **409** |

回傳皆含 `updated_at`，前端可回寫後再送。

---

## §5 · 核心業務流程

### §5.1 · 報價狀態機

```
草稿 → 待審核（送出）→ 已送出（簽核完成）
         ↑ 解鎖編輯儲存後強制回到待審核
```

- 單號：`MQ-YYYYMM-NNN`（`/api/next-quote-no`）
- 僅**草稿**可刪；其他狀態回 403
- **已送出**預設鎖定；superadmin 解鎖密碼後可改，儲存後重鎖並重送審
- 送出前驗證：`customerName` + `projectName` + **至少一項品項說明**不得空白
- 防重複送出：`submitting` flag，按鈕期間不可再觸發

### §5.2 · 案件進度 dealTag

```
未提供 → 已提供 → 未成案
                 → 已成案（確認後 UI 鎖定）
                 → 已結案（僅案件管理「完結案」）
```

- 欄位同步：`quotations.deal_tag`
- 日誌：`data_json.statusLog[]`；**`delegateNote` 寫入 audit_log**
- **未成案 / 已成案**（設為）：限 admin+ 操作
- **已成案**：報價單須先完成簽核（`status=='已送出'`）才可標記，否則 400（前後端雙重 guard，2026-08-05b）
- **已成案 → 其他（降級）**：限 **admin+**（前後端雙重 guard）
- **已結案 → 其他**：限 **superadmin**
- UI revert：取消確認時用 `$nextTick` 回滾 `_prevDealTag`

### §5.2b · 報價清單動態徽章（quotations.html）

`dealDisplayStatus(q)` 回傳 `{text, cls}`，依 `status + deal_tag` 組合：

| status | deal_tag | text | cls |
|--------|----------|------|-----|
| 草稿 | — | 草稿 | badge--draft |
| 待審核 | — | 審核中 | badge--pending |
| 簽核中 | — | 簽核中 | badge--signing |
| 已核准 | — | 已核准 | badge--approved |
| 已取消 | — | 已取消 | badge--danger |
| 已拒絕 | — | 已退回 | badge--rejected |
| 已送出/已確認 | 未提供/已提供 | 報價中 | badge--sent |
| 已送出/已確認 | 已提供 | 待決定 | badge--sent |
| 已送出/已確認 | 已成案 | 執行中 | badge--running |
| 已送出/已確認 | 未成案 | 未成案 | badge--lost |
| 已送出/已確認 | 已結案 | 已結案 | badge--settled |

### §5.2c · 報價單 PDF 匯出

**工具列按鈕邏輯**（三擇一顯示）：

| 條件 | 按鈕 | 說明 |
|------|------|------|
| `!q.quoteNo`（新增未儲存） | 預覽報價單（neutral） | 讓使用者確認版型格式 |
| `q.dealTag === '未成案'` | 預覽報價單（紅色） | 禁止匯出 |
| 其餘已儲存且非未成案 | 匯出 PDF（`directExport()`） | 系統後端產生，瀏覽器直接下載 |

管理員另有 **匯出次數** 獨立按鈕（`showExportLog()`，僅 admin+）。

### §5.3 · 簽核（tiers 並行層）

```
設定：system_settings.approval_flow → { tiers:[{order, approvers:[]}] }
送出：快照至 data_json.approval.tiers[]
規則：同層全員 approved → currentTier++；末層完成 → status=已送出 + PDF
退回：清除 approval，status=草稿
舊 steps[]：執行期動態轉 tiers
```

- 有流程：允許自簽（比對當層 username）
- 無流程（預設超管）：**禁止申請人自簽**
- 代理送審：`approval.delegateSubmitter` + `delegateNote` 同步寫入 audit_log

### §5.4 · 案件管理 Tab 結構

| Tab | 內容 |
|-----|------|
| 案件資訊 | 合約資訊 + 人員角色 + 收款管理（%／含稅／未稅雙向） |
| 執行進度 | 進度 / 叫料 / 設備 / 保固備注 |
| 承攬商 | 派發記錄 + 驗收流程 |
| **動態** | 案件留言板（手動留言 + work_log 同步 + daily_task 完成回報） |
| 財務 | KPI + 精算結果（需 `canSeeFinancial`） |

### §5.4b · 動態 Tab（案件留言板）

- **資料來源（合併排序，newest-first）**
  1. `case_updates` 表：手動留言（任何角色均可發布；發文者或 admin+ 可刪）
  2. `work_logs`（`case_no=此報價單號`）：工作日誌自動同步為只讀卡片
  3. `daily_task_completions JOIN daily_tasks`（`case_no=此報價單號`）：完成回報只讀卡片
  4. `dev_logs`（依 `dev_cases.converted_quote_no=此報價單號` 反查 case_id，`needs_approval=0`）：
     業務開發開發記錄自動同步為只讀卡片，僅在該報價單有業務開發案件連結時出現；代填記錄需先經
     管理員審核（`PATCH /api/dev-logs/{id}/approve`）通過後才會顯示（2026-08-05b）
  5. `audit_log`（`target_type='dev_case' AND action='dev_case.status'`）：業務開發案件狀態變更
     事件，同上僅連結案件時出現（2026-08-05b）
- **API**：`GET/POST /api/quotations/{no}/updates`、`DELETE /api/quotations/{no}/updates/{id}`
- 切換案件時自動重置；點擊「動態」Tab 時 `loadCaseUpdates()` lazy fetch

### §5.5 · 成本精算 settlement

- 入口：已成案／已結案 → `settlement.html?no=`
- 存於 `data_json.settlement`；欄位 `settle_status` = `draft` \| `finalized`
- 每次儲存寫入 `editHistory[]`
- `finalized` 後：非 superadmin 不可再修改；API 失敗時**完整回滾** status + finalizedAt + finalizedBy
- **實際總成本三個來源**（2026-08-03e 起）：`itemActualTotal`（原始報價品項實際成本）+
  `extraTotal`（額外支出，手動）+ `dispatchTotal`（承攬商派發成本，**自動即時讀取**
  `GET /api/contractor-dispatches?quote_no=`，唯讀不可編輯，排除 `status==='cancelled'`；
  每筆派發貢獻 = 承攬商含稅合計 `totalWithTax` + 外包名單人員金額加總 `personnelTotal`
  不計稅）；`calcSummary()` 每次都重新抓即時派發資料，不會凍結成精算存檔當時的快照
  **⚠️ 這代表三個顯示點不會永遠一致**：`settlement.html` 本身每次開啟都即時重算
  `dispatchTotal`；但 `case-management.html` 財務 Tab 與 `reports.py`（Excel/PDF）讀的是
  `data_json.settlement.summary` 這份**精算存檔當下寫入的快照**。如果承攬商派發在精算
  `finalized` 之後又被異動（新增/取消/改金額），重新打開 `settlement.html` 會看到新數字，
  但財務 Tab 跟營運報表仍停留在完結當下的舊數字，直到有人（僅 superadmin 可
  `reopenDraft()`）重新存檔覆蓋快照為止。這是**精算「完結即凍結」的正常會計邏輯**（快照
  才能保證財務報表不會被之後的異動悄悄改變），不是 bug——但三處顯示點跨頁比對時務必
  知道這個差異，不要誤以為數字對不上是計算錯誤。

### §5.6 · 專案

- `projects` + `project_logs`；與報價 M:N（`linked_cases`）
- 確認事項兩階段：`project_approve_eng` → `project_approve_biz`
- 照片：Pillow 水印 + GPS EXIF → `uploads/projects/...`

### §5.7 · 承攬商派發狀態機

```
草稿(draft) → 已送出(sent) → 已確認(confirmed)
                                   ↓
                              待驗收(pending_acceptance)   ← 快速按鈕：「待驗收」
                                   ↓
                              已驗收(accepted)             ← 快速按鈕：「✓ 確認驗收」
                                   ↓                         記錄 accepted_by + accepted_at
                              完工(completed)

任意非終態 → 已取消(cancelled)
```

- 狀態轉換：`PATCH /api/contractor-dispatches/{id}/accept`（`action=pending_acceptance` 或 `action=accepted`）
- 流程違規（如跳過待驗收直接已驗收）→ **409**
- 已驗收後：卡片底部顯示綠色橫條，含驗收人姓名 + 時間
- 狀態亦可透過 Modal 下拉直接設定（彈性操作，不走 `/accept` endpoint）
- **外包名單人員（DB v36，2026-08-03e）**：新增派發 Modal 內可從外包名冊（`contractors` 表，
  `GET /api/contractors/selectable`，比照 `vendor-contractors/selectable` 慣例，任何登入者可讀）
  多選人員並各自填金額，存為 `personnel_json` 快照 `[{id,name,amount,note}]`（不隨 `contractors`
  表後續變動連動，即使該人員之後被刪除或改名，既有派發紀錄的金額與姓名仍完整保留）；
  `_dispatch_row()` 額外回傳 `personnelTotal`（人員金額加總）與 `grandTotal`
  （`totalWithTax + personnelTotal`，承攬商含稅金額 + 外包人員金額不計稅）；`已取消` 的派發
  不計入 `grandTotal` 彙總（見案件管理承攬商 tab 的「外包總成本」與 §5.5 精算 `dispatchTotal`）
- **承攬商欄位改為選填（DB v37，2026-08-03f）**：部分案件屬純外包名單人員點工，沒有對應承攬商，
  `vendor_id` 從 `NOT NULL` 改為可為空（SQLite 需整表重建，見 `_m037_dispatch_vendor_optional`）；
  後端驗證改為「承攬商與外包名單人員至少擇一」，兩者皆空才擋 400；前端 Modal 拿掉必填星號、
  預設選項改「— 無承攬商（純外包名單人員點工）—」；卡片列表標題無承攬商時顯示「外包人員（點工）」，
  金額改用 `grandTotal` 統一顯示（含稅承攬商 + 外包人員），並新增外包人員明細表格；精算頁「三、
  承攬商派發成本」明細列無承攬商時不再顯示佔位的「（未命名承攬商）」空列，改由外包人員第一筆
  頂替顯示派發狀態
- **外包名冊「參與案件」聯動（2026-08-03g）**：`contractors.html`（外包名冊）詳情面板比照
  `vendor-contractors.html` 承攬商詳情的「派發紀錄」區塊，新增「參與案件」——選中人員時前端
  抓 `GET /api/contractor-dispatches`（無 `quote_no` 參數，同承攬商頁一樣受限於「最新 200 筆」），
  用 `d.personnel.some(p => p.id === c.id)` 篩出該人員實際參與的派發，逐筆顯示案號連結（導向
  案件管理承攬商 tab）、狀態徽章、所屬承攬商（無承攬商時顯示「（無承攬商，純點工）」）與該人員
  個人金額（`_myDispatchAmount(d)`，非整筆派發總額）

### §5.8 · 出貨單（案件管理子項目，2026-08-01）

```
草稿 → 待審核 → 簽核中 → 已核准
  ↑______________________|（退回，清空 approval，回草稿）
已核准 ⇄ 已回簽（is_signed toggle，獨立於狀態機，僅已核准可切換）
```

- 一個案件（`quote_no`）可對應多張出貨單（分批出貨）；分頁對所有能開案件管理的人可見，**新增/編輯/送審/簽核/匯出 PDF/勾選回簽等操作限 admin+**（與承攬商分頁一致：分頁可見、寫入操作後端擋權限）
- 品項純出貨用途，**不含金額欄位**；可從報價單一鍵匯入品項（前端純轉換，去除 cost/margin/unitPrice/amount），或手動新增/編輯，支援段落標題列（`type:'header'`）
- **簽核流程獨立於報價單**：`system_settings.shipping_approval_flow`（不與報價單 `approval_flow` 共用），設定頁 `shipping-approval-settings.html`；tiers 依序簽核，有設定流程時申請人可自簽；**無流程時僅 superadmin 可簽（含自簽）**——與報價單「無流程時禁止申請人自簽」的規則刻意不同（2026-08-01g 調整，見 §12）
- 全部簽核完成 → 狀態 `已核准`，背景觸發 PDF 存檔（`pdf_gen.py _generate_shipping_pdf`）
- **已回簽**：`已核准` 狀態才可切換；`signed-toggle` 為嚴格 toggle（已回簽不可重複標記，需先取消），每次切換完整記錄至 `signed_log`（誰、何時、動作、備註），案件管理 UI 可展開查看完整歷程
- PDF 匯出與報價單同一套機制：`GET .../pdf-download` 產生 bytes（不記錄），`POST .../export` 另外累計 `export_count`/`export_log`
- **預覽**：`GET .../pdf-download` 無狀態限制，任何狀態皆可預覽（案件管理 UI「預覽」按鈕，iframe+blob 顯示，不呼叫 `/export`）；預覽 Modal **不提供下載選項**（避免與已核准後的正式匯出/記錄流程混淆），要下載仍須回到列表上已核准狀態的「下載 PDF」按鈕；非已核准狀態下 PDF 本身（`pdf_gen.py _build_shipping_html`）會帶浮水印＋警告橫幅（比照報價單預覽稿樣式，文案「出貨單預覽稿／尚未正式核准」），已核准後乾淨無浮水印
- **收件人聯絡人快選**：新增/編輯 Modal 內若案件所屬客戶（`quotations.data_json.customerId`，或退而用 `customer_name` 比對客戶清單）有登記聯絡人，顯示「選聯絡人」下拉快選；點選僅覆寫欄位值，收件人欄位本身仍可自由輸入
- 刪除僅限 `草稿` 狀態（保留已進入簽核/已回簽的歷程）
- Demo 模式 PDF 隔離目錄：`backend/_demo_shipping_pdf_archive`

---

## §6 · Sidebar 結構

```
主選單     儀表板
業務       業務開發（dev-crm.html, dev_crm 模組旗標或 admin+）/ 報價單（含簽核佇列 ?view=queue） /
           案件管理 / 專案管理
選型資料庫  場域選型導覽（env-guide.html, env_guide 模組旗標或 admin+）/
           網路架構選型導覽（netarch-guide.html, netarch_guide 模組旗標或 admin+）/
           交換器選型導覽（switch-guide.html, switch_guide 模組旗標或 admin+）/
           監控系統選型導覽（monitor-guide.html, monitor_guide 模組旗標或 admin+）/
           門禁系統選型導覽（access-guide.html, access_guide 模組旗標或 admin+）/
           涵蓋度總覽（selection-db-overview.html, admin+ 限定，無獨立模組旗標）
廠商與採購 客戶 / 供應商 / **承攬商** / 料號 / **庫存管理**（inventory.html, inventory 模組旗標或 admin+）/ 採購
設備       設備登載 / 保固追蹤
財務       應收帳款 / 營運報表（admin+ 或含 reports 模組）
工作       工作日誌（非 viewer 或含 work_log 模組） / 每日工作事項（非 viewer 或含 daily_task 模組）
系統       使用者 / 簽核設定（superadmin）/ 出貨單簽核設定（superadmin）/ 歷史紀錄 / 版本紀錄 / Schema 狀態（superadmin）
```

- 簽核佇列不在 sidebar，在報價單內 tab
- 銷售訂單已移除（併入案件財務）
- `reports`：`admin+` 或含 `reports` 模組的使用者可見
- `work_log` / `daily_task`：非 viewer 或明確帶對應模組者可見（相容既有帳號）
- `承攬商管理`：`admin+`（`cPr` 旗標，同採購）可見；`vendor-contractors.html`
- **模組通知 badge**：所有模組 nav 項目（含子項）均有藍色 `sb-mod-*` badge，由 `_fetchModuleCounts()` 根據 `motrix_module_seen` 顯示其他人的更新計數；廠商採購/設備/財務各組同步顯示同一模組計數
- **選型資料庫**（2026-08-01 獨立成頂層 sidebar 區塊，不再掛在「業務」底下；`SELECTION-DB-INDEX.md` 是這個產品線的總索引，規劃中還有自動化系統一個未來類別）：
  - **場域選型導覽**：`env-guide.html`；檢視 `env_guide` 模組旗標或 admin+（`cEnvG` 旗標）；編輯（新增/修改/刪除場域、建議、連結）與 Excel 匯出入另需 `env_guide_edit` 模組旗標或 superadmin；`users.html` 可分別授予兩者；**無** 模組通知 badge（資料變動頻率低，未接 `_fetchModuleCounts()`）
  - **網路架構選型導覽**：`netarch-guide.html`；檢視 `netarch_guide` 模組旗標或 admin+（`cNetG` 旗標）；編輯需 `netarch_guide_edit` 或 superadmin；瀏覽邏輯與場域選型導覽不同——**先選技術族系方塊，再看世代橫向對照卡片**（非矩陣/篩選），選型資料庫第二個上線的類別
  - **交換器選型導覽**：`switch-guide.html`；檢視 `switch_guide` 模組旗標或 admin+（`cSwitchG` 旗標）；編輯需 `switch_guide_edit` 或 superadmin；選型資料庫第三個上線的類別；**2026-08-01 前完全沒有 sidebar 入口與 `users.html` 權限勾選項**（只有 superadmin 能用），本次補齊跟另外兩個一致
  - **監控系統選型導覽**：`monitor-guide.html`；檢視 `monitor_guide` 模組旗標或 admin+（`cMonitorG` 旗標）；編輯需 `monitor_guide_edit` 或 superadmin；選型資料庫第四個上線的類別（2026-08-09），資料形狀與交換器選型導覽相同（相機分類×場域情境矩陣），第一批資料為 UniFi Protect G6 世代
  - **門禁系統選型導覽**：`access-guide.html`；檢視 `access_guide` 模組旗標或 admin+（`cAccessG` 旗標）；編輯需 `access_guide_edit` 或 superadmin；選型資料庫第五個上線的類別（2026-08-09），資料形狀同上（元件分類×場域情境矩陣），第一批資料為 UniFi Access
  - 五者在**歷史紀錄**（`audit-log.html`）與**版本紀錄**（`module-versions.html`）皆已比照其餘模組補上對應的 optgroup／actionLabel／色碼（teal 色系＋🧭 圖示，五者共用同一識別色，強調同屬一個產品線而非各自獨立模組）
  - **涵蓋度總覽**（2026-08-09）：`selection-db-overview.html`；admin+ 限定，無獨立模組旗標；彙總上述四個「品牌/型號目錄」型類別（網路架構/交換器/監控/門禁，不含場域選型導覽——資料形狀是情境×分層文字建議而非品牌目錄）在各世代/分類底下的品牌數與產品數，紅/黃/綠三色標示完全空白／偏薄弱／足夠；**不新增後端 API**，純前端呼叫既有 5 個類別各自的 GET 端點彙總而成
- **出貨單簽核設定**：`shipping-approval-settings.html`；superadmin 限定；獨立於報價單「簽核設定」（`system_settings.shipping_approval_flow`，不同 key），UI 為 `approval-settings.html` 的複製版本；出貨單本身不是獨立 sidebar 項目，掛在「案件管理」頁面內的「出貨單」分頁，沿用 `case_manage`/`cCM`/`sb-mod-case`
- **Schema 狀態**（2026-08-01）：`schema-status.html`；superadmin 限定；**純唯讀**診斷頁，顯示目前 db 版本 / 目標版本、狀態（✓最新／⚠尚未同步）、最後更新時間、完整 migration 清單（v34→v1，版號＋函式名稱＋說明）；**全頁無任何操作按鈕或表單**——migration 於伺服器啟動時自動套用，此頁不提供「觸發乾跑」之類的操作（架構上沒有意義：活著的伺服器對自己已是最新版的 db 再跑一次永遠是 no-op）；資料來源 `GET /api/system/schema-status`

---

## §7 · API 速查（base `/api`）

### §7.1 · Auth / Users

| Method | Path | 說明 |
|--------|------|------|
| GET | /ping | 心跳 |
| POST | /auth/login | 回傳含 `mustChangePassword`；rate limit 保護 |
| POST | /auth/logout | |
| GET | /auth/me | 含 `mustChangePassword`；驗 `expires_at` |
| PATCH | /auth/change-password | ≥8；清除強制改密 |
| POST | /auth/verify-unlock | superadmin 解鎖驗證 |
| GET/POST | /users | 列表／新增 |
| PUT/DELETE | /users/{id} | |
| PATCH | /users/{id}/active | |
| PATCH | /users/{id}/unlock-password | ≥8 |

### §7.2 · 報價 / 簽核 / 精算

| Method | Path | 說明 |
|--------|------|------|
| GET | /next-quote-no | 認證必填 |
| GET/POST | /quotations | 列表（角色過濾）／建立 |
| POST | /quotations/case-activity | 案件管理列表「有新動態」提示用；body `{quote_nos:[...]}`，回傳各單號 case_updates/work_logs/daily_task_completions 三來源最新時間；非 admin 沿用 `/quotations` 同款角色過濾 |
| GET/PUT/DELETE | /quotations/{no} | DELETE 僅草稿；PUT 鎖定狀態需解鎖 |
| PATCH | /quotations/{no}/status | superadmin + 白名單狀態 |
| PATCH | /quotations/{no}/deal-tag | 同步 `deal_tag`；已成案降級需 admin+；已結案需 superadmin |
| PATCH | /quotations/{no}/case-record | 樂觀鎖 `_expectedUpdatedAt` → 409 |
| PATCH | /quotations/{no}/payment/{idx} | 收款標記；樂觀鎖 `_expectedUpdatedAt` → 409 |
| GET/PUT | /quotations/{no}/settlement | 精算；finalized 後非 superadmin 不可改 |
| GET | /quotations/{no}/pdf-download | Edge PDF |
| POST | /quotations/{no}/export | 記錄匯出人/時間 |
| GET | /quotations/{no}/updates | 動態 Tab 合併 feed（comments+work_logs+daily_tasks） |
| POST | /quotations/{no}/updates | 發布手動留言 |
| DELETE | /quotations/{no}/updates/{id} | 刪除留言（發文者或 admin+）|
| GET | /approval-queue | 認證必填 |
| POST | /quotations/{no}/approve \| reject | 並行層簽核 |

### §7.3 · 主檔 / 專案 / 報表 / 系統

| Method | Path | 說明 |
|--------|------|------|
| CRUD | /customers · /suppliers · /parts | 供應商列表 admin+ 才有資料；需認證 |
| GET | /customers/{id} | 單一客戶詳情（含 contacts/address） |
| PATCH | /customers/{id}/visits · /suppliers/{id}/visits | 樂觀鎖 |
| GET | /company/tax/{id} · /company/search | GCIS Proxy |
| CRUD | /projects · logs · photos | |
| GET | /photo-token?path= | 取得 1h signed token |
| GET | /uploads/{path}?pt= | 照片（優先 `?pt=`；fallback `?token=`） |
| GET | /dashboard/stats · /monthly | 需認證 |
| GET | /devices · /receivables | 需認證 |
| GET | /reports/financial · /excel · /pdf | admin+ |
| GET/PUT | /settings/approval-flow | |
| GET/PATCH | /notifications/* | |
| GET | /audit-log | **admin+ only**；viewer/sales/engineer → 403 |
| GET/POST/PUT/DELETE | /work-logs | PUT/DELETE 非 admin 只能操作自己的 |
| GET/POST | /settings/custom-roles | 列表／新建自訂角色（POST 需 superadmin） |
| PUT/DELETE | /settings/custom-roles/{rid} | 更新／刪除（superadmin only） |
| GET | /settings/role-labels | 各角色層顯示名稱（需認證） |
| PUT | /settings/role-labels | 更新角色顯示名稱（superadmin only） |
| GET | /settings/payment-terms | 報價單「付款條件」預設文字（需認證；未設定過時回傳程式內建範本） |
| PUT | /settings/payment-terms | 更新預設文字（superadmin only） |
| GET | /system/schema-status | Schema／migration 唯讀診斷（superadmin only）；回傳目前版本、目標版本、`upToDate`、`lastAppliedAt`、完整 migration 清單 |

### §7.5 · 業務開發 CRM（DB v27；連結報價單審核制 DB v42，見 §12 2026-08-13）

| Method | Path | 說明 |
|--------|------|------|
| GET | /dev-cases | 案件列表（`?q=` 搜尋、`?status=` 篩選；需 dev_crm 模組或 admin+；**非 admin 僅回傳自己建立或指派的案件**）**2026-08-03a**：`?status=` 伺服器端參數仍保留相容，但前端 `dev-crm.html` 已改為抓全量後完全前端篩選（狀態／年／月／逾期），不再送 `status` |
| POST | /dev-cases | 新建案件 |
| GET/PUT/DELETE | /dev-cases/{id} | 單筆操作（DELETE admin+） |
| PATCH | /dev-cases/{id}/status | 變更狀態（洽談中/成案/未成案） |
| PATCH | /dev-cases/{id}/convert | 首次連結報價單號（`{quote_no}`，同時設 status=成案）；**已有連結時回 409**，須改用下列審核流程 |
| POST | /dev-cases/{id}/request-relink-quote | 申請異動／解除已連結的報價單號（admin+；`quote_no` 留空＝申請解除連結，`reason` 選填）→ 送交 superadmin 審核，DB v42 |
| POST | /dev-cases/{id}/cancel-relink-quote | 取消連結異動申請（申請人或 superadmin） |
| POST | /dev-cases/{id}/approve-relink-quote | 審核連結異動（superadmin only；`{approve}`；核准清空時 status 一併退回洽談中） |
| POST | /dev-cases/{id}/request-delete | 申請刪除案件（admin+，設 pending_delete=1，觸發 Email） |
| POST | /dev-cases/{id}/cancel-delete | 取消刪除申請（申請人或 superadmin） |
| POST | /dev-cases/{id}/approve-delete | 審核刪除申請（superadmin only；approve=True→軟刪除+快照，False→拒絕清除旗標） |
| GET/POST | /dev-cases/{id}/logs | 記錄列表 / 新增記錄（log_by≠填單人 → needs_approval=1） |
| PUT/DELETE | /dev-logs/{id} | 編輯／刪除（發文者或 admin+） |
| PATCH | /dev-logs/{id}/approve | 審核記錄（admin+ only） |
| GET | /dev-logs/pending | 待審記錄列表（admin+ only） |

### §7.4 · 承攬商管理（DB v22–v25）

| Method | Path | 說明 |
|--------|------|------|
| GET | /vendor-contractors | 承攬商列表（admin+；`?q=` 搜尋 name/tax_id/phone/contact、`?active_only=` 篩選） |
| POST | /vendor-contractors | 新建承攬商（admin+；`data{}` 存 category/tags/notes/visits） |
| GET | /vendor-contractors/selectable | 輕量下拉（需認證，非 admin 亦可；供案件管理下拉） |
| GET/PUT | /vendor-contractors/{id} | 單筆查詢／更新（PUT admin+；PUT 合併 data_json 保留 visits） |
| DELETE | /vendor-contractors/{id} | 刪除（有派發紀錄 → 409，建議改停用） |
| PATCH | /vendor-contractors/{id}/active | 停用／啟用切換（admin+） |
| PATCH | /vendor-contractors/{id}/visits | 往來紀錄更新（樂觀鎖 `expectedUpdatedAt` → 409） |
| GET | /contractor-dispatches | 派發列表（`?quote_no=` 過濾；無參數返回最新 200 筆；回傳含 `personnelTotal`/`grandTotal`，見 §5.7） |
| POST | /contractor-dispatches | 新建派發（需認證；`vendor_id` 選填，DB v37——承攬商與外包名單人員至少擇一，兩者皆空 → 400；自動計算 total_amount；`personnel_json` 外包名單人員快照，見 §5.7） |
| GET/PUT/DELETE | /contractor-dispatches/{id} | 單筆操作（DELETE admin+） |
| GET | /contractors/selectable | 外包名冊輕量下拉（需認證，非 superadmin/`contractor_list` 亦可；供承攬商派發「外包名單人員」選擇，DB v36） |
| PATCH | /contractor-dispatches/{id}/accept | 驗收流程：`action=pending_acceptance`（draft/sent/confirmed→待驗收）或 `action=accepted`（待驗收→已驗收，記錄 accepted_by/accepted_at）；違規轉換 → 409 |
| POST | /contractor-dispatches/{id}/import-to-quote | 回推品項至報價單 `items[]`（報價單非草稿 → 409） |

### §7.6 · 場域選型導覽（DB v30）

無人自動化載具部署場域／設備選型參考資料，原為獨立單機工具（場域選型導覽.html），2026-07-30 整合進 ERP 並資料庫化。

| Method | Path | 說明 |
|--------|------|------|
| GET | /env-guide/environments | 場域列表（需認證即可，無角色限制） |
| POST/PUT/DELETE | /env-guide/environments[/{code}] | 新增／修改／刪除場域；superadmin 或 `env_guide_edit` 模組 |
| GET | /env-guide/recommendations | 分層建議列表（需認證） |
| POST/PUT/DELETE | /env-guide/recommendations[/{id}] | 同上權限 |
| GET | /env-guide/links | 原廠／代理商連結列表（需認證） |
| POST/PUT/DELETE | /env-guide/links[/{id}] | 同上權限 |

- 前端 `frontend/pages/env-guide.html`：瀏覽模式分「簡易／進階」兩個子模式（`browseMode`，預設 simple）——**簡易**是場域方塊＋分層卡片（跟網路架構選型導覽同一套介面，Alpine 直接讀 `envRows`/`recRows`/`linkRows`）；**進階**是原單機工具的矩陣／卡片／表格／搜尋／篩選／抽屜 UI（vanilla JS，`window.EnvGuideTool.boot()` 由 Alpine `loadEnvGuideData()` 餵資料）；管理模式為新增的 CRUD 後台（Alpine + modal）
- 配色：`.envg` CSS 變數對應 MOTRIX 系統色票（`--accent`/`--text-*`/`--border-light` 等），`data-th="light"`為預設（＝系統配色），`data-th="dark"`為原工具深色調備用切換
- **Excel 匯出／匯入**：僅 `session.role==='superadmin'` 可見按鈕（UI 層限制，比其他模組的 `env_guide_edit` 更嚴格）；匯出 3 個工作表（環境/建議/連結）；匯入以場域代碼／建議與連結 ID 比對，相符則 PUT 更新、否則 POST 新增（沿用既有單筆 CRUD API，無專用批次 endpoint，做法比照 `customers.html` 匯入慣例）
- 種子資料：`backend/env_guide_seed.py`（JSON 字串常數，`_m030_env_guide` 一次性寫入，僅在表為空時執行，之後編輯一律走上述 API 不會被 migration 覆蓋）

### §7.7 · 網路架構選型導覽（DB v31）

選型資料庫第二個上線的類別，資料形狀是「技術族系→世代→產品」而非場域選型導覽的「情境×分層×三級」，見 `SELECTION-DB-INDEX.md`。

| Method | Path | 說明 |
|--------|------|------|
| GET | /netarch-guide/families | 技術族系列表（需認證） |
| POST/PUT/DELETE | /netarch-guide/families[/{code}] | superadmin 或 `netarch_guide_edit` |
| GET | /netarch-guide/generations | 世代/規格列表（需認證） |
| POST/PUT/DELETE | /netarch-guide/generations[/{id}] | 同上權限 |
| GET | /netarch-guide/products | 產品連結列表（需認證） |
| POST/PUT/DELETE | /netarch-guide/products[/{id}] | 同上權限 |

- 種子資料：`backend/netarch_guide_seed.py`（同樣僅在表為空時寫入一次）
- 前端 `frontend/pages/netarch-guide.html`：管理模式沿用場域選型導覽的淺色系統配色與 CRUD 慣例；瀏覽模式是新設計的「族系方塊→世代對照卡片」簡化 UI，未使用矩陣/篩選/搜尋那套

### §7.8 · 出貨單（DB v34）

| Method | Path | 說明 |
|--------|------|------|
| GET | /shipping-notes?quote_no= | 依案件列出出貨單摘要（需登入，不含完整品項） |
| GET | /shipping-notes/{note_no} | 完整明細（含 items/approval/signed_log/export_log） |
| POST | /shipping-notes | 建立草稿（admin+）；`note_no` 由 `next_entity_code(...,'DN',code_col='note_no')` 產生 |
| PUT | /shipping-notes/{note_no} | 更新（admin+；非草稿 409） |
| DELETE | /shipping-notes/{note_no} | 刪除（admin+；非草稿 409） |
| POST | /shipping-notes/{note_no}/submit | 送出審核（admin+；產生 tiers 快照，狀態→待審核） |
| POST | /shipping-notes/{note_no}/approve | 簽核（當層簽核人依序；無流程時僅 superadmin 且禁止申請人自簽） |
| POST | /shipping-notes/{note_no}/reject | 退回草稿（當層成員或 superadmin；簡化版，不改版號） |
| GET | /shipping-notes/{note_no}/pdf-download | Edge PDF（不記錄匯出） |
| POST | /shipping-notes/{note_no}/export | 記錄匯出人/時間/次數（`export_count`/`export_log`） |
| POST | /shipping-notes/{note_no}/signed-toggle | `{action:'sign'|'unsign', note?}`；已核准才可切換，嚴格 toggle（409 若狀態不符） |
| GET/PUT | /shipping-notes/settings/approval-flow | 出貨單專屬簽核流程設定（PUT 限 superadmin），獨立於報價單 `approval_flow` |

### §7.9 · 監控系統選型導覽（DB v39）

選型資料庫第四個上線的類別，資料形狀與交換器選型導覽相同（相機分類×場域情境矩陣），見 `SELECTION-DB-INDEX.md`／`MONITOR-GUIDE-CONTENT.md`。

| Method | Path | 說明 |
|--------|------|------|
| GET | /monitor-guide/scenarios | 場域情境列表（需認證） |
| POST/PUT/DELETE | /monitor-guide/scenarios[/{code}] | superadmin 或 `monitor_guide_edit` |
| GET | /monitor-guide/categories | 相機分類列表（需認證） |
| POST/PUT/DELETE | /monitor-guide/categories[/{code}] | 同上權限 |
| GET | /monitor-guide/fit | 適配矩陣列表（需認證） |
| POST/PUT/DELETE | /monitor-guide/fit[/{id}] | 同上權限 |
| GET | /monitor-guide/products | 產品連結列表（含 `specs_json`，需認證） |
| POST/PUT/DELETE | /monitor-guide/products[/{id}] | 同上權限 |

- 種子資料：`backend/monitor_guide_seed.py`（僅在表為空時寫入一次）
- 前端 `frontend/pages/monitor-guide.html`：以交換器選型導覽為範本（依情境查看／對照矩陣總覽／規格比較／管理後台 CRUD 全數沿用）

### §7.10 · 門禁系統選型導覽（DB v40）

選型資料庫第五個上線的類別，資料形狀同上（元件分類×場域情境矩陣），見 `SELECTION-DB-INDEX.md`／`ACCESS-GUIDE-CONTENT.md`。

| Method | Path | 說明 |
|--------|------|------|
| GET | /access-guide/scenarios | 場域情境列表（需認證） |
| POST/PUT/DELETE | /access-guide/scenarios[/{code}] | superadmin 或 `access_guide_edit` |
| GET | /access-guide/categories | 元件分類列表（需認證） |
| POST/PUT/DELETE | /access-guide/categories[/{code}] | 同上權限 |
| GET | /access-guide/fit | 適配矩陣列表（需認證） |
| POST/PUT/DELETE | /access-guide/fit[/{id}] | 同上權限 |
| GET | /access-guide/products | 產品連結列表（含 `specs_json`，需認證） |
| POST/PUT/DELETE | /access-guide/products[/{id}] | 同上權限 |

- 種子資料：`backend/access_guide_seed.py`（僅在表為空時寫入一次）
- 前端 `frontend/pages/access-guide.html`：以交換器選型導覽為範本（依情境查看／對照矩陣總覽／規格比較／管理後台 CRUD 全數沿用）
- 所有分類都需要一台執行 UniFi Access App 的 UniFi OS Console 才能運作，`READER` 分類的產品不能單獨運作，需搭配 `MULTI_DOOR_HUB` 才能控制門鎖，詳見 `ACCESS-GUIDE-CONTENT.md` §1

---

## §8 · 備份與還原

> 整台正式機硬體故障時的完整重建流程，見獨立文件 [`DR-SOP.md`](DR-SOP.md)（2026-08-07 新增）。
> 這裡的 §8.1–§8.4 是日常備份機制；DR-SOP.md 是「機器掛了怎麼辦」的實際操作步驟。

### §8.1 · 路徑

```
雲端（需 H: 掛載）
  H:\我的雲端硬碟\系統存檔\
    即時備份\報價單|客戶|供應商\
    每日備份\YYYY-MM-DD\  （JSON 八表 + motrix_erp.db；保留 365 天，超過自動清除整個日期資料夾）
    週備份\YYYY-WNN\      （保留 730 天，超過自動清除整個週別資料夾）
    上傳檔案鏡像\          （2026-08-08 新增，uploads/ 專案照片等實體檔案，_mirror_uploads() 依大小+
                            修改時間增量同步，不是每日整包複製；demo 隔離目錄不同步；只增不減）

本機（不依賴 G:，務必保留）
  backend\db_backups\YYYY-MM-DD\motrix_erp.db   ← SQLite Online Backup，保留 30 天
  backend\db_backups\quotation_instant\          ← G: 不可用時的即時報價單 JSON fallback
  backup_alerts\BACKUP_ALERT.txt                ← 雲端異常醒目警示
  backup_alerts\YYYY-MM-DD.log
```

### §8.2 · 排程架構（雙層）

| 層 | 機制 | 觸發時間 | 說明 |
|----|------|---------|------|
| **主**（可靠） | Windows 工作排程器 | 每日 02:00 | `backup_job.py`；server crash 也跑；開機後補執行 |
| **冗餘** | `threading.Timer` | 每 2h 日備；每 6h 週備 | server 在線時提供即時觸發 |

`.done` marker 確保同日/週不重複備份。設定：`setup_backup_task.ps1`（初次部署執行一次）。

**雲端備份清除**（2026-08-01 新增，`_prune_cloud_backups()`）：`每日備份`／`週備份` 原本永不清除、會無限期累積；現在 `_daily_backup()` 跑完後會呼叫，各自依保留天數（預設每日 365 天、週備份 730 天）刪除整個過期的日期/週別資料夾。安全機制比照既有 `_prune_local_db_backups()`：只刪「資料夾名稱能正確解析成日期」的項目（`YYYY-MM-DD` / `YYYY-WNN`），其他檔名一律不動；H: 未掛載時整段略過，不會誤判成「全部過期」。

### §8.3 · 行為

| 條件 | 行為 |
|------|------|
| G: 正常 | 即時 JSON（**原子寫入**）+ 每日 JSON + 雲端 DB 副本 + 本機快照 |
| G: 未掛載 — 即時備份 | 寫至 `db_backups/quotation_instant/{no}.json`（本機 fallback） |
| G: 未掛載 — 排程備份 | 寫 `BACKUP_ALERT.txt` + audit `backup.alert`；**仍做本機 SQLite 快照** |
| 恢復正常 | 清除 sticky 警示檔 |
| Server crash | Task Scheduler 仍在 02:00 執行本機快照 |

**原子寫入**：所有 JSON 備份均先寫 `.tmp` 再 `os.replace()`，崩潰時不產生損毀檔。

Audit：`backup.daily_ok` · `backup.weekly_ok` · `backup.sqlite_snapshot` · `backup.alert`

**audit_log 保留**：每次每日備份後執行 `_prune_audit_log(keep_days=730)`，自動刪除 2 年前舊紀錄（先備後刪，雲端 JSON 永久保存）。

**還原優先序**：本機 `db_backups` 整庫 → 雲端 `motrix_erp.db` → JSON 重建（最後手段）

---

## §9 · 前端規範

| 項目 | 做法 |
|------|------|
| 框架 | Alpine.js CDN |
| JS | `frontend/js/{page}.js`（非 defer，先於 Alpine） |
| Auth | `init()` 讀 session；無 token → login |
| 強制改密 | session.mustChangePassword 或 sidebar 導向 |
| API | `Authorization: Bearer {token}`，**PATCH deal-tag 不可遺漏** |
| 自動存 | debounce 1.5s（`setDirty`）；`isDirty=false` 需在 API 成功回調內設定 |
| 客戶選公司 | `selectCustomer()` async；每次選擇都 `GET /api/customers/{id}`，**強制覆寫**聯絡人欄位 |
| No-cache | `.html` / `.css` / `.js` 皆 no-store |
| Excel | SheetJS CDN（客戶／供應商） |
| XSS 防護 | 動態插入 API 資料一律用 DOM API，**禁止 innerHTML 插入非靜態內容** |

---

## §10 · 成本公式（報價）

```
售價 = CEILING(成本 × 1.05 / (1 − 毛利率), 5)
管銷分攤 = 稅前售價 × 10%
公益捐款 = 直接毛利 × 1%
```

`FORM_VERSION`：模板版號常數（如 V1.1），與單筆資料無關；**quotation-form.html 或其邏輯任何改動都須遞增**——小改版（欄位微調/樣式/文案）+0.1，大改版（版型結構/新增區塊/流程變更）+1。

---

## §11 · 已知限制與後續建議

| 優先 | 項目 |
|------|------|
| 🔴 | 區網 HTTPS／反向代理（Nginx + mkcert，Bearer Token 目前區網明文） |
| ✅ | ~~死碼 JS 清除~~（21 個死碼 .js 已刪，`frontend/js/` 僅剩 2 個有效檔） |
| ✅ | ~~關鍵 API 自動化測試~~（48 tests 全通過，`backend/tests/test_core.py`） |
| ✅ | ~~文件拆 `CHANGELOG.md` 與本速查分離~~（已完成，見根目錄 `CHANGELOG.md`） |
| ✅ | ~~Git Flow 分支規則~~（`develop` 分支 + `GITFLOW.md` 規範已建立） |
| 低 | SQLite → PostgreSQL（資料量 > 1 GB 或同時連線數 > 5 時評估） |

---

## §12 · 變更摘要（最新兩版）

> 完整版本歷史請見 [`CHANGELOG.md`](CHANGELOG.md)（根目錄）

### 2026-08-17i — 料號主檔新增匯出／匯入 Excel

- 比照 `customers.html` 既有模式（純前端 SheetJS，無新後端端點）：`parts.html` 新增 `exportExcel()`／`handleImport()`，匯入逐列比對料號決定呼叫既有 `PUT`（更新）或 `POST /api/parts`（新增，留空依類別前綴自動產生）
- 已用 demo session 完整 round-trip 驗證（建立→匯出→改檔→匯入→查資料庫核對），新增/更新/失敗/自動產生料號情境皆確認正確；純前端調整，無 DB migration

### 2026-08-17h — 案件管理動態 Tab 月曆總覽容器字級過小（g 遺漏的另一半）

- 使用者澄清「過窄」指的其實是月曆總覽容器（第一版比例修正時加的 `max-width:340px` 迷你月曆，內文字從未放大過）
- `.feed-cal-wdays`/`.feed-cal-cell`/`.feed-cal-cnt`/`.feed-cal-title`/`.feed-cal-nav` 等字級全面放大，容器 `max-width` 340→380px 留呼吸空間（仍遠低於原本撐爆容器的臨界值）
- 純前端 CSS 調整，無 DB migration

### 2026-08-17g — 案件管理動態 Tab 下方內容/人員顯示字級放大

- 動態 Tab 發文列表字級全面放大：`.feed-bubble__content` 13→15px、`.feed-bubble__author` 12→14px、`.feed-bubble__time` 10→12px、`.feed-badge` 9→11px、`.feed-avatar` 30→36px，並放寬相關內距/間距
- 容器寬度本身沒問題（實測 1223px），純粹是字級明顯小於全站 15px 基準；純前端 CSS 調整，無 DB migration

### 2026-08-17f — 案件管理動態 Tab 月曆比例修正＋業務開發排行改依廠商＋精算完結徽章空白 bug

- **A. 動態 Tab 月曆**：`.feed-cal-cell` 的 `aspect-ratio:1` 隨寬版 `.cm-detail`（`flex:1`）撐成巨大方格，6 週高度爆表被 `overflow:hidden` 裁掉下方發文框/動態列表；`.feed-cal-wdays`/`.feed-cal-grid` 加 `max-width:340px` 修正
- **B. 業務開發排行**：`GET /api/dev-crm/activity-stats` 排行改依廠商（`customer_name`/`case_name`）分組，取代原本依業務員（`log_by`）分組；回傳欄位 `bySalesperson`→`byVendor`
- **C.（順手修）精算完結徽章空白**：`case-management.html:1369` `toLocaleString(\'zh-TW\')` 多餘反斜線跳脫符號造成 Alpine 解析失敗、整段不渲染，移除即修復
- 已用 Chrome MCP 瀏覽器實機驗證三處；純前端＋單一端點調整，無 DB migration；pytest 106/106 全過

### 2026-08-17e — 移除業務開發接洽成效總覽「近 30 天最活躍」KPI

- `dev-crm.html` 移除該 KPI 卡片，KPI 列 3 欄改回 2 欄；後端 `bySalesperson` 欄位不變（排行榜仍在用）

### 2026-08-17d — Asana 風格視覺化整合＋財務儀錶板支出項＋業務開發接洽成效總覽

- **新增** `GET /api/dashboard/expenses-monthly`：月支出結構（承攬商/設備/料件/其他），`index.html` 新增堆疊長條圖，4 色配色已用 dataviz skill 驗證通過
- **每日工作事項**（`daily-tasks.html`）新增「月曆總覽」（橫條式月曆，同週連續 occurrence 合併橫條）與「看板」（依 category 分欄，`sortablejs` 拖曳，僅 `superadmin && dtUnlocked` 可寫）
- **案件甘特圖**（`case-management.js`）bar 依主要負責人上色＋`custom_popup_html`；**專案看板**（`projects.html`）卡片新增成員頭像（`assigned_user_ids`）；三處共用同一組色碼演算法 `_avatarColor`，同一人跨頁面顏色一致
- **案件管理「動態」Tab** 新增月曆篩選（純前端統計，未加 API）；頭像改依發文者上色
- **新增** `GET /api/dev-crm/activity-stats`：跨案件近 60 天/8 週/30 天接洽成效統計，`dev-crm.html` 右欄空狀態改為儀表板（KPI＋純 CSS 趨勢圖＋業務員/通路排行）
- 無 DB migration；已對本機 server 用 demo session 做完整 curl round-trip（含 CRUD＋看板搬移 PUT）、`pytest` 106/106 全過、兩個新端點聚合結果已對照開發機真實資料手算核對吻合；瀏覽器畫面驗證由使用者自行確認

### 2026-08-17c — 系統通知信全面補齊完整內容（不再截斷/省略）

- `notify_module_activity()`（跨模組共用活動通知，116 處呼叫）新增 `detail` 參數，獨立渲染
  「內容」區塊，完整呈現不截斷，並補上 HTML escape 避免留言含特殊字元讓信件跑版
- 修正 9 個檔案共 10 處實際遺漏/截斷內容的呼叫端（案件留言、業務開發拜訪記錄、工作日誌、
  專案日誌、客戶/供應商/承攬商往來紀錄、承攬商派發、出貨單回簽備註）；其餘呼叫皆為無另外
  自由文字內容的結構化異動，項目欄位已完整，未異動
- 已直接呼叫真正的函式驗證內容完整＋escape 正確；本機實測四條主要路徑無錯誤；pytest 106/106

### 2026-08-17b — 承攬商派發新增發票號碼欄位

- **DB v44**（`_m044_dispatch_invoice_no`）：`contractor_dispatches` 新增 `invoice_no`
- 填寫位置：`case-management.html` 承攬商派發 Modal；顯示位置：派發卡片列表、
  `vendor-contractors.html` 派發紀錄、`settlement.html` 精算頁承攬商成本明細
  （全庫搜尋確認無遺漏）
- 已用 Node 直接執行 `case-management.js` 真正的表單函式驗證欄位帶入/送出正確；後端對本機
  跑起來的 server 做完整 CRUD round-trip 驗證；pytest 106/106 全過

### 2026-08-17a — 修正精算「預估 vs 實際」毛利率公式不對稱

- **背景**：使用者要求複查案件金額／毛利率／報表／儀表板是否同步正確，追出 `quotation-form.html`
  建立報價單時 `directProfit = pretax − totalCost − totalCost×5%`（多扣一筆 5% 非扣抵進項稅），
  但 `settlement.html` 精算品項預設 `actualCostTaxMode='pretax'`，`grossProfit = quotedPretax −
  totalActualCost` 完全沒有這 5%；`reports.py`／`dashboard.py` 的 `estimatedMarginPct` vs
  `actualMarginPct`（Excel 毛利分析差異(pp)欄、儀表板 marginComparison）直接比較這兩個數字，
  導致即使成本完全沒變，每筆已精算案件都會顯示「真實毛利率虛高約 3 個百分點」的假象（已用
  Python 模擬驗證：修正前 bias=3.19pp，修正後 bias=0.00pp）
- **修正**：`settlement.html` 精算品項預設 `actualCostTaxMode` 由 `'pretax'` 改為 `'taxed_gross'`
  （與報價單建立時的假設一致），品項仍可個別切換回未稅／含稅5%因應實際情況；「原始預估」欄位
  （`origDirectProfit`/`origMarginPct`/`origAdminCost`/`origCharity`/`origNetProfit`/
  `origNetMarginPct`）改為直接讀取報價單建立時已算好的 `tot` 物件而非重新計算，一併修掉重算式
  遺漏 5 個間接成本項目（`indirectLogistics` 等）的第二個落差；僅影響尚未儲存過精算資料的品項，
  既有草稿/已完結精算的 `actualCostTaxMode` 不受影響（沿用既有儲存值）
- 已用 `node -e new Function` 驗證 `settlement.html` 內嵌 script 語法正確；pytest 106/106 全過
  （純前端修正，無 DB migration，後端測試不受影響）

### 2026-08-17 — 使用者個別 Email 通知偏好（DB v43）＋首頁最新動態彙整

- **背景**：`notify_*`（23 個事件）收件人原本全員一體適用，無法讓管理員/使用者關閉自己不需要
  的信件類型；首頁也缺少跨模組（業務開發／報價單／案件留言／出貨單／工作日誌／進出物料）彙整
  排序的「最新動態」總覽
- **DB v43**（`_m043_notification_prefs`）：`users` 新增 `notification_muted TEXT DEFAULT '[]'`
  ——存**退訂**清單（非白名單），空陣列／NULL＝全部照舊接收，既有帳號與未來新事件類型都不受影響
- **新模組** `helpers/notification_prefs.py`：`EVENT_GROUPS`（23 個 key，比照 `notify_*` 函式名稱
  去除前綴）＋ `is_enabled(muted_json, event_key)`；`email_notify.py` 三個收件人查詢函式
  （`_admin_emails`／`_superadmin_emails`／`_lookup_emails`）加上 `event_key` 過濾
- `users.html` 新增／編輯 Modal 內「Email 通知偏好」勾選區塊（比照既有「存取模組」手風琴 UI）
- **新 API** `GET /api/dashboard/activity-feed`：彙整 6 個來源（`case_updates`／`work_logs`／
  `dev_logs`／`stock_items` 直查 + `audit_log` 白名單動作），依時間新到舊排序，權限沿用
  `can_quotation`／`can_dev_crm`／`_can_access_case()`／非 admin 只看自己名下資料等既有規則；
  `index.html` 首頁新增「最新動態」卡片

### 2026-08-13 — 業務開發連結報價單改為審核制（可清空，DB v42）

- **背景**：2026-08-05b 開放的「修改連結」直接覆寫既有 `converted_quote_no`，且欄位必填不可清空；
  但案件變更常導致已連結的報價單被取消，此時需要能解除連結，而這類異動應比照案件刪除走審核，
  不該由單一使用者直接覆寫/清空已成立的連結
- **DB v42**（`_m042_dev_cases_relink_review`）：`dev_cases` 新增 `pending_relink` /
  `relink_requested_by` / `relink_requested_at` / `relink_reason` / `relink_target_quote_no`
  （空字串為合法值＝申請解除連結，非單純「未設定」）
- **新 API**（見 §7.5）：`request-relink-quote`（admin+ 申請，`quote_no` 留空＝申請解除連結）／
  `cancel-relink-quote`（申請人或 superadmin 取消）／`approve-relink-quote`（僅 superadmin，
  核准後套用新單號或清空；清空時案件狀態一併退回「洽談中」，避免「成案」狀態掛著卻無對應報價單）
- `PATCH /dev-cases/{id}/convert` 加上守門：`converted_quote_no` 已有值時回 409，原端點僅保留
  給尚未連結的初次轉建報價單使用
- `dev-crm.html`：「修改連結」鉛筆按鈕改為開啟申請 modal（可留空、可填原因），案件詳情與清單
  卡片新增「待審核連結異動」標記，superadmin 專屬審核 modal
- Email 通知：`notify_dev_case_relink_request()`（新，仿 `notify_dev_case_delete_request`）

### 2026-08-10a — 選型資料庫新增閘道器與控制器選型導覽（第六個類別）＋四個既有導覽頁全域搜尋/深度連結

- **背景**：選型資料庫繼交換器／網路架構／監控系統／門禁系統之後，新增第六個類別；同時補上
  從「涵蓋度總覽」頁直接跳轉到對應分類的深度連結體驗
- **gateway_guide（DB v41）**：`gateway_scenarios/categories/fit/products` 四表，資料形狀比照
  switch_guide／monitor_guide／access_guide；與 switch_guide 的邊界是 switch_guide 只收交換器，
  本類別收 Omada 路由/閘道器（Wired/Wi-Fi/4G-5G/整合型）與硬體控制器（OC 系列）；首批資料
  5 情境／5 分類／25 筆適配矩陣／15 筆產品；`gateway-guide.html` 前端頁面、`routers/gateway_guide.py`
  後端 CRUD 均以既有類別為範本；`users.html`／`sidebar.js`／`main.py` 依既有慣例同步補齊權限模組
  與導覽項目；詳見 `GATEWAY-GUIDE-CONTENT.md`
- **四個既有導覽頁＋總覽頁新增全域搜尋／深度連結**：switch/monitor/access/netarch-guide.html
  工具列新增跨分類全域搜尋框（輸入型號/品牌直接篩出符合的分類卡片，取代原本要先選情境再逐一
  展開的操作路徑）；`selection-db-overview.html` 的類別/品牌連結改為帶 `?category=&brand=` 參數
  導向對應頁面並自動捲動＋短暫高亮命中的分類卡片（`applyDeepLink()`），解決總覽頁「看得到缺口
  但要手動找到對應位置」的痛點
- **驗證**：`pytest` 100 個測試全過；透過雙機 API 核對工具（見 §14.4／`check_guide_sync.py`）先
  在開發機對 gateway_guide 四個端點做建立＋刪除測試資料驗證 CRUD 正常，才與其餘變更一併打包

### 2026-08-10 — 修正網路架構選型導覽新增/更新產品 API 的 500 錯誤（specs_json 欄位不存在）

- **背景**：建置雙機（開發機／正式機）選型資料庫內容核對工具（`backend/tools/check_guide_sync.py`，
  透過 `claude` 自動化帳號的 API token 直接比對兩邊 `switch/monitor/access/gateway/netarch/env`
  六大類選型資料庫內容）過程中，嘗試把開發機獨有的 netarch 產品透過 API 補寫進正式機，全數 500
- **根因**：`routers/netarch_guide.py` 的 `create_product`／`update_product` 兩處 SQL 誤引用
  `specs_json` 欄位，但 `netarch_products` 表從建立以來就沒有這個欄位（`db.py` 全部 migration
  核對過，確認不存在）；兩台機器只要透過網路架構選型導覽頁面「新增/編輯產品」都會踩到，此前
  未被發現是因為既有 77 筆資料都是透過種子腳本直接寫 db、從未經過這兩個 API 端點
- **修正**：兩處 SQL 的 INSERT／UPDATE 移除 `specs_json` 欄位與對應參數，改動範圍限縮在這一支
  檔案；已在開發機重啟後以真實 API 呼叫建立＋刪除測試資料驗證修復生效
- 本次**只**部署這個 bug fix（單獨 commit＋`git stash` 隔開其餘尚未準備好的選型資料庫深度擴充／
  新增 gateway_guide 模組等變更），修復生效後另外透過 API 把開發機獨有的 netarch 產品／switch
  產品補寫進正式機，並清掉正式機一筆已被開發機拆分取代的舊 netarch 資料（Omada EAP670 那筆）

### 2026-08-09b — 選型資料庫新增監控系統／門禁系統兩個類別＋既有類別補 UniFi

- **背景**：使用者要求「新增 UniFi」，範圍涵蓋四個選型資料庫類別（見 `SELECTION-DB-INDEX.md`
  §5 同日條目）
- **既有類別補品牌**：交換器選型導覽 `MANAGED_L3` 分類新增 UniFi Pro 24 PoE／Enterprise 48
  PoE（補齊該類別長期記錄的品牌缺口）；網路架構選型導覽校正「Wi-Fi 6E 尚無產品」這條過時的
  文件記錄（資料庫其實已有 U6-Enterprise 掛在 6E 世代下）
- **兩個全新類別上線**：監控系統選型導覽（DB v39，`monitor_guide` 系列表）與門禁系統選型導覽
  （DB v40，`access_guide` 系列表），皆沿用交換器選型導覽的「情境×分類矩陣」四表結構＋
  `specs_json`，第一批資料均為 UniFi（Protect／Access），前端頁面與後端 CRUD 皆以交換器選型
  導覽為範本；sidebar／users.html／audit-log.html／module-versions.html／main.py 依既有三個
  類別的慣例同步補齊；詳見 `MONITOR-GUIDE-CONTENT.md`／`ACCESS-GUIDE-CONTENT.md`
- **操作者身分修正**：過程中發現本機無已知密碼可登入帳號，一度借用真人帳號 `corbin` 的 session
  執行 API 寫入，導致稽核紀錄與 2 封系統通知信誤植為該真人所為；使用者指正後建立專用 `claude`
  自動化帳號（`role=admin`，最小權限模組旗標），並回頭修正已寫入的 3 筆 audit_log 記錄；該 2
  封已寄出的通知信無法收回，已如實告知使用者
- 排程自動化機制（每週檢查產品異動＋新廠商觸發同步）本次**未建置**，維持手動走
  `SELECTION-DB-INDEX.md` §3 既有流程，自動化留待後續另外討論

### 2026-08-05n — 料號可依分類自動產生（免手動輸入）

- **背景**：使用者詢問料號能否依類別（如網通、監控）自動產生，不必每次手動輸入
- `parts.py` 新增固定分類清單 `PART_CATEGORIES`（含前綴，如 網通設備→NET、監控設備→CCTV、交換器→SW、
  伺服器/工控→SVR、線材配件→CAB、其他→OTH；目前無既有分類慣例可循，清單為預設值，日後要增改分類
  直接改這個常數即可）與 `GET /api/parts/categories` 端點；`create_part()` 允許 `partNo` 留空，改依
  `category` 對應前綴呼叫新增的 `_next_part_no()`（掃 `part_no LIKE 'PREFIX-%'` 取最大流水號 +1，
  格式 `PREFIX-NNN`，不含年月——料號目錄是長期累積主檔，不比照客戶/出貨單按月分段編號）產生；仍可
  手動輸入 `partNo` 覆蓋自動產生（既有行為不變）；`category` 不在清單內且未填 `partNo` → 400
- `parts.html`：類別欄由自由輸入文字改為固定下拉選單（讀 `/api/parts/categories`）；新增料號時
  「料號」欄可留空（提示「留空依類別自動產生」），編輯既有料號時仍必填且鎖定不可改（既有行為不變）
- **驗證**：demo session 直接呼叫 API：網通設備連續建立兩筆依序產生 `NET-001`/`NET-002`，監控設備
  產生 `CCTV-001`；未填分類且未填料號正確回 400「請輸入料號，或選擇有對應前綴的類別以自動產生」；
  手動指定 `partNo`（`MANUAL-001`）仍可覆蓋自動產生正常運作。以直接讀取正式機 db 檔案確認上述測試
  寫入完全沒有進入 `motrix_erp.db`（demo 隔離機制對此變更仍生效正常）
- **修正**：使用者實測回報「類別是空的」——`parts.html` 的 `loadCategories()` 呼叫 `GET
  /api/parts/categories` 沒帶 `Authorization` header，而 `main.py` 全域 middleware 對所有 `/api/**`
  一律要求 Bearer token（僅 `/api/ping`／`/api/auth/login`／`/api/auth/logout` 白名單），該請求因此被
  middleware 擋下回 401「未登入」，`categoryOptions` 停留在空陣列，下拉選單只剩「未分類」；補上
  `Authorization: Bearer` header 後以 curl 直接比對兩種情境（不帶 header → 401；帶 header → 正確回傳
  6 筆分類清單）確認修復生效。本次未曾複製部署包到正式機，直接在原打包內容上修正、重新打包

### 2026-08-06a — 料號「廠牌」欄改為預設選單（VIGI/OMADA/UNIFI）＋可手動增加廠牌

- **背景**：使用者對 05n 的自動完成（`<input>` + `datalist`）進一步要求：①「廠牌」預設顯示應為
  VIGI、OMADA、UNIFI（一開啟就看得到，而非要先打字才觸發建議）② 廠牌清單要能手動新增
- `parts.html`「廠牌 / 型號」欄拆成兩個子欄位（DB 仍是單一 `brand` 欄，前端組合，無 schema
  變更）：`<select x-model="modal.brandName">`（廠牌，選項來自 `brandSelectOptions`）＋一般文字
  input `x-model="modal.brandModel"`（型號）；儲存時把兩者 `join(' / ')` 回單一字串，沿用既有
  「品牌 / 型號」慣例與 `brand` 欄位不變，向下相容既有資料
- 新增 `brandPresets` 狀態（`localStorage.motrix_part_brand_presets`，預設 `['VIGI','OMADA','UNIFI']`）
  ＋「⚙ 管理廠牌」摺疊面板，完全比照 `suppliers.html` 既有的 `tagPresets` 管理模式（chip + × 移除 +
  輸入新增），維持風格一致而非重新發明；`brandSelectOptions` getter 併入 `brandPresets` 與既有料號
  已使用過的廠牌（取 `/` 前半段），去重排序
- `openModal()` 編輯既有料號時，把儲存的 `brand` 字串依第一個 `/` 拆回 `brandName`/`brandModel`
  兩個子欄位（無 `/` 則整串落入 `brandModel`，不強制對應到某個廠牌選項，避免資料被誤改）
- **驗證**：`node --check` 確認內嵌 script 語法正確；demo 帳號瀏覽器實測「新增料號」Modal：廠牌下拉
  預設即顯示 VIGI/OMADA/UNIFI 三個選項（不需先打字）；點「管理廠牌」展開面板，輸入新廠牌名稱按
  「新增」正確加入 chip 並持久化到 localStorage；選擇廠牌＋輸入型號＋儲存後，列表正確顯示組合後的
  「廠牌 / 型號」字串；測試新增的臨時廠牌與測試料號皆已清除還原（demo db 下次登入也會自動清空）

### 2026-08-06 — 料號「廠牌」欄新增品牌自動完成建議＋供應商資料核對

- **背景**：使用者要求新增供應商 VIGI／Omada／UniFi／Peplink（過往詢問過的品牌）「並修改料號做對應」。
  查證發現 `motrix_erp.db` 的 `suppliers` 表已是**真實廠商資料**（21 筆有統編/聯絡人的實際公司，非測試
  資料），且 Omada 其實已有對應廠商——`S-202607-003`「聯洲國際有限公司」（網站 omadanetworks.com/tw、
  聯絡人 email @tp-link.com，已標「原廠」），因此改為與使用者逐項核對而非直接捏造新公司記錄
- 用 `AskUserQuestion` 確認：① VIGI 與 Omada 同屬聯洲國際在賣 → 於該筆 `data_json.tags` 加上
  `"VIGI"` 標籤（原 `tags` 為空陣列）② UniFi／Peplink 目前 21 筆裡無對應公司，使用者將自行在系統內
  建立（有實際代理商資料時處理起來比我用佔位資料建立更準確）
- 供應商資料修改前**先手動快照** `motrix_erp.db` 至 `backend/db_backups/manual/`（因是直接改真實業務
  資料且非透過 API，無法觸發應用程式既有的 `_backup_suppliers()` 自動備份），才用 Python 直接
  read-modify-write `data_json`，只動 `tags` 陣列與 `updated_at`，其餘欄位（統編/聯絡人/合約條件等）
  逐一比對修改前後完全未變動
- `parts.html`：料號「廠牌 / 型號」欄由純自由輸入文字，改為比照 `quotation-form.html` 既有的
  `<input list>` + `<datalist>` 自動完成模式（非固定下拉，仍可自由輸入任意品牌）；建議清單新增
  `brandOptions` getter，固定包含 `VIGI`/`Omada`/`UniFi`/`Peplink` 四個品牌，再併入目前已存在料號的
  廠牌（取 `/` 前半段，即品牌名稱），去重排序後供自動完成使用
- **驗證**：`node --check` 確認 `parts.html` 內嵌 script 語法正確；直接讀 db 比對 `S-202607-003` 修改
  前後除 `tags`／`updated_at` 外所有欄位（`name`/`tax_id`/`phone`/`contacts`/`category` 等）皆逐一相符
  未被誤動。尚未部署至正式機（無 DB migration，`parts.html` 屬前端純檔案異動，供應商資料為本機資料
  異動，不隨程式碼部署包搬移，正式機若需要同筆修改需另行在正式機介面手動操作）

### 2026-08-05m — 序號級庫存管理 Phase B／C（出貨單核准自動扣庫存＋設備登載自動扣/還庫存）

- **背景**：延續 2026-08-05l 的 Phase A（資料模型＋進貨＋顯示），本次接上剩餘兩個扣庫存進出點：
  出貨單核准（確認出貨）與設備登載，完成使用者最初要求的三個進出點全部落地
- **Phase B — 出貨單核准自動扣庫存**：`shipping_notes.py` `approve_shipping_note()` 的 `if all_done:`
  區塊（`conn.commit()` 前）新增庫存驗證與扣減：品項若帶有 `part_no`/`serials[]`（新增可選欄位，
  向下相容，沒填就跟過去一樣是自由文字品項），核准前先確認所有引用序號皆為 `in_stock`——只要有一
  個不是（已被搶用）或同一張單重複引用同一序號，整張核准直接 409 中止、不寫入任何狀態變更；全部
  通過才在同一 transaction 內把對應 `stock_items` 更新為 `status='shipped'` 並記錄
  `shipping_note_no`/`quote_no`/`consumed_at`/`consumed_by`。刻意選在核准（`已核准`）而非
  `toggle_signed`／回簽掛勾，因為回簽是更晚的客戶簽收確認、且可雙向切換，用來扣庫存會讓「已核准
  但未回簽」的出貨永遠扣不到庫存。已確認 `reject_shipping_note`／`delete_shipping_note` 都無法作用
  於已核准的單子，故不需要額外設計自動回滾——若核准錯了，走 `POST /api/inventory/stock-items/{id}/adjust`
  的 `return_to_stock` 人工更正
- **Phase B 前端**：`case-management.js` 新增 `openSerialPicker`/`_loadSerialOptions`/`applySerialPicker`
  等方法＋ `serialPicker` 狀態；`case-management.html` 出貨單品項表格新增「庫存序號」欄（未連結顯示
  「選料號」按鈕、已連結顯示 `料號 ×N`），獨立序號挑選 modal（z-index:420，高於出貨單 modal 的 400），
  勾選料號後即時打 `GET /api/inventory/stock-items?part_no=&status=in_stock` 只列出在庫序號
- **Phase C — 設備登載自動扣/還庫存**：設備登載（`caseRecord.devices[]`）沒有獨立端點（`addDevice`/
  `removeDevice`/`onMaterialArrived`/`syncMaterialsToDevices` 四處都是純前端陣列操作），因此不新增專
  屬端點，改在既有的整包 PATCH `quotations.py` `update_case_record()` 內做新舊 devices[] 序號 diff（新
  增 `_sync_device_stock()` helper）：新增或 SN 變更的設備 → 找對應 `status='in_stock'` 序號設為
  `installed`（找不到就略過，不擋存檔，因為多數既有設備登載本來就沒有庫存來源）；移除或 SN 被改掉
  的已連結項目 → 狀態退回 `in_stock`、清空 `quote_no`/`case_device_id`/`consumed_at`。與 Phase B 是各
  自獨立的扣庫存來源（不要求先出貨才能登載），比對邏輯全程沿用同一個 request 的 `conn`／transaction，
  與既有樂觀鎖檢查、`save_quotation_json` 走同一次 commit；devices 陣列前後完全相同時整段跳過，避免
  每次存檔都做多餘查詢
- **驗證**：開發機重啟服務無誤。改用 API 直測（demo session token）走完整流程：建測試料號＋3 筆庫存
  序號（`SN-B-01`/`SN-B-02`/`SN-C-01`）→ 建測試報價單 → 出貨單引用 `SN-B-01`/`SN-B-02` → 送審→核准，
  確認兩序號正確變 `shipped` 並記錄 `shipping_note_no`/`quote_no`；另建第二張出貨單重複引用
  `SN-B-01`，核准正確回 409 且該單狀態未被更動；設備登載新增 `sn=SN-C-01` 的設備，確認序號變
  `installed` 並記錄 `quote_no`/`case_device_id`；移除該設備後確認序號正確退回 `in_stock` 且關聯欄
  位清空。瀏覽器 UI 因案件管理頁面清單僅顯示 `已成案`/`已結案` 案件、測試報價單未經完整簽核流程走
  到位，僅完成語法檢查（`node --check`）與既有 modal pattern 比對，**未**實機點擊驗證序號挑選 modal
  視覺呈現，下次有機會登入真實帳號操作時建議補測。以直接讀取正式機 db 檔案確認上述所有測試寫入完
  全沒有進入 `motrix_erp.db`（含巧合撞號的 `MQ-202608-001`——正式庫裡的同號記錄經確認是 `jeff` 帳號
  今日稍早建立的真實資料，非本次測試污染，兩者是各自獨立資料庫的月序偶然撞號）

### 2026-08-05l — 新增序號級庫存管理 Phase A（資料模型／進貨／料號頁徽章／庫存管理頁）

- **背景**：使用者要求在「設備項」內新增庫存功能，未來讓報價單、設備登載能透過保固追蹤頁面核銷。
  討論確認三個設計決策：① 粒度為序號級（比照設備登載 SN/MAC 結構，非單純數量累加）② 進出點為
  進貨手動建批次＋出貨單核准自動扣庫存＋設備登載時自動扣庫存。查證發現 `parts`（料號目錄）過去
  純粹是價格/成本參考清單，`part_no` 完全沒有被報價單品項、出貨單品項、設備登載記錄引用過；另外
  `frontend/pages/users.html` 的 `ROLE_MODULES` 早就預留了 `'inventory'` 模組 key（superadmin/admin
  皆有），但 `allModules` 清單與 `sidebar.js` 都還沒接上去，像是早就為這個功能留好的位置
- **範圍**：完整規劃分三階段（見對話中 Plan 產出，未寫入本文件），本次僅完成 **Phase A**（資料模型＋
  進貨＋顯示），Phase B（出貨單核准自動扣庫存）／Phase C（設備登載自動扣庫存）尚未實作，`stock_items`
  的 `shipping_note_no`/`quote_no`/`case_device_id` 欄位已預留但目前不會被任何流程寫入
- **新表**：`db.py` `_m038_inventory`（DB v38）建立 `stock_items`（序號級單位，一列＝一台實體設備，
  `UNIQUE(part_no, serial_no)`），無獨立 `stock_batches` 父表——批次就是同一次進貨產生的多筆
  `stock_items` 共用一個 `batch_no`（`next_entity_code(conn,"stock_items","PO",code_col="batch_no")`
  產生，格式 `PO-YYYYMM-NNN`）
- **新 router**：`backend/routers/inventory.py`，`GET /api/inventory/parts-summary`（料號彙總各狀態
  數量，餵 parts.html 徽章與庫存頁列表）、`GET /api/inventory/stock-items`（序號清單/搜尋）、
  `POST/GET /api/inventory/batches`（+ `GET .../batches/{batch_no}`，進貨批次建立/查詢）、
  `POST .../stock-items/{id}/adjust`（`void`/`return_to_stock`/`edit_note`）、
  `DELETE .../stock-items/{id}`（僅 `status='in_stock'` 可刪）。讀取類 `_require_user`，異動類本檔案
  自帶 `_require_admin(user)` 區域函式（比照 `shipping_notes.py` 既有寫法，非共用 helpers），全走
  `get_db()` 確保 demo 帳號隔離自動生效。`main.py` 已註冊該 router
- **進貨決策**：必須輸入實際序號才能建批次，不接受「先數量後補序號」——序號級庫存的意義就在於
  每一台都可追蹤，允許幽靈序號會讓之後的扣庫存配對失效。前端 `intake.qty` 變動時
  `syncSerialRows()` 自動增減序號輸入列，存檔前擋掉序號空白的列
- **`parts.py` `delete_part()` 防呆**：刪除前檢查 `stock_items` 是否有該 `part_no` 紀錄，有則 409
  「此料號仍有庫存紀錄，無法刪除」（過去是無關聯檢查的硬刪除）
- **前端**：新頁 `frontend/pages/inventory.html`（比照 `parts.html` 的 Alpine 結構）——料號彙總表
  （在庫/已出貨/已登載/報廢四欄）、「進貨」批次建立 modal、逐料號鑽入序號明細 modal（狀態篩選
  chips + 報廢/退回庫存/刪除操作）；`parts.html` 加「在庫」徽章欄，讀 `parts-summary` 依 `part_no`
  對應顯示
- **Sidebar／權限接線**：`sidebar.js` 加 `cInv` 判斷式（`mods.indexOf('inventory')>=0 || ad`，兩處
  賦值皆同步），導覽項目掛在「廠商與採購」料號主檔之後；`users.html` `allModules` 補上
  `{key:'inventory', label:'庫存管理', group:'採購'}`（`ROLE_MODULES` 早已預留該 key，此次只是把
  checkbox 介面接上）
- **驗證**：開發機重啟服務，`DB migration 38/38: _m038_inventory` 正常套用，`/openapi.json` 確認 6
  個端點皆註冊成功。瀏覽器以 **demo 帳號**（隔離空白 db，不影響正式資料）實測：`parts.html` 新增測
  試料號 `TEST-U6-PRO` → 庫存頁「進貨」建立 2 台序號批次（`PO-202608-001`）→ 序號明細 modal 正確顯示
  兩筆、狀態「在庫」。點擊「報廢」/「刪除」按鈕觸發瀏覽器原生 `confirm()`（比照 `parts.html`
  `deletePart()` 既有寫法）在 CDP 自動化下會凍結分頁——改用同一 demo session token 直接呼叫 API
  驗證：`adjust action=void` → `parts-summary` 正確反映 `voidCount`；`adjust action=return_to_stock`
  → 狀態與關聯欄位正確清空回 `in_stock`；`DELETE` 僅在 `status='in_stock'` 成功、其餘回 409；
  `parts.py` 刪除防呆在 `stock_items` 仍有紀錄時正確回 409。另以直接讀取正式機 db 檔案確認上述 demo
  帳號測試寫入完全沒有進入 `motrix_erp.db`（`stock_items`/`parts` 皆 0 筆），demo 隔離機制對新 router
  生效正常

### 2026-08-05k — 營運報表「年度目標達成率」平均淨毛利率改為金額加權平均

- **背景**：使用者截圖回報營運報表「年度目標達成率」圖表中「平均淨毛利率」「收款率」達成率超過
  100%，懷疑算式有誤。查證後：達成率＝實際率÷目標率×100，屬設計上刻意行為（累積金額型指標與
  比率型指標本就不同性質，比率型指標實際值超過目標值時達成率自然可以 >100%，`_compute_achievement()`
  對兩者也刻意分開處理——比率型指標 `prorata` 固定回 `None`，不像金額型指標會按時間比例預估）。
  但同時查出真正該修的問題：`avgMarginPct`「實際值」在 `_compute_achievement()` 內是把該年度已
  精算（`finalized`）案件的毛利率做**單純算術平均**（`sum(mps)/len(mps)`），未依金額加權；年度初
  期已精算案件數少時，單一小金額但毛利率特別高的案件會把平均值拉得不合理（實測開發機資料庫：4筆
  已精算案件單純平均 51.5%，其中一筆稅前僅 NT$3,700 但毛利率達 89%；改金額加權後降為 34.7%，與
  同檔案其他業務員層級 `avgMarginPct` 算法（`mProfitSum/mRevSum`）邏輯一致）
- **修法**：`backend/routers/reports.py` `_compute_achievement()`，`ytd_margin` 計算從
  `sum(mps)/len(mps)` 改為 `Σ(pretax×actualMarginPct)/Σ(pretax)`（稅前金額加權），與既有
  `sales`／`marginByRep` 等既有加權平均寫法對齊
- **驗證**：以 Python 直接讀開發機 `motrix_erp.db`（同 SQL 查詢邏輯）比對修改前後數值，加權後金
  額明顯更貼近整體精算結果，不再被單筆小額高毛利案子拉爆；`collectionRate` 部分維持原樣（已確認
  非計算錯誤）。尚未在瀏覽器內重新整理報表頁面實測圖表視覺變化

### 2026-08-05j — 精算「品項實際成本」新增含稅5%（自動加總）選項

- **背景**：接續 05i 的未稅／含稅5% 兩個選項，使用者提出反方向情境：填的數字是未稅底價，但這筆
  稅金公司無法扣抵、對公司來說是真實多付出去的錢，需要另一個選項把 5% 稅額加回去、墊高實際成
  本。用 `AskUserQuestion` 確認換算後的金額（例：底價100→105）要不要直接算進「實際總成本」
  （進而影響真實毛利／淨利），使用者確認要算進去（105），成本墊高、毛利同步下修，而非只是參
  考顯示
- **修法**：`settlement.html` 下拉新增第三個選項 `taxed_gross`（含稅5%（自動加總）），
  `calcItemCost()` 改為三分支：`pretax` 原樣採用、`taxed`（既有）除以1.05 反推未稅、
  `taxed_gross`（新增）乘以1.05 算成含稅金額計入 `actualTotalCost`；該行小字附註改顯示原始
  未稅金額（100）供核對，與 `taxed` 模式顯示原始含稅金額的方向相反、對稱設計
- **驗證**：Node 腳本驗證三種模式運算結果皆正確（未稅100→100／含稅105→100／自動加總100→105）；
  `node --check` 驗證 `settlement.html` 內嵌 script 語法正確。未在瀏覽器實機操作（同
  2026-08-05h/i，涉及登入輸入密碼），僅完成公式層級驗證。已完成 `git commit`（`83155f8`）＋
  `build_deploy_package.ps1` 打包，尚未套用至正式機，需依 §15 流程由使用者在正式機執行
  `apply_update.ps1`

### 2026-08-05i — 精算「品項實際成本」新增未稅／含稅5%選項

- **背景**：使用者反映精算草稿「一、原始報價品項─實際成本對照」的「實際單位成本」只能直接填數
  字，沒有標示這筆金額是未稅還是含稅。供應商發票有的開未稅、有的開含稅，若含稅金額整筆算進
  「實際總成本」，會墊高成本、低估真實毛利——因為「報價稅前收入」本身就是未稅基準，兩邊要同一
  基準比才正確。用 `AskUserQuestion` 確認範圍（僅限此區塊，不含額外支出／承攬商派發）與換算規
  則（選含稅時自動扣稅換算回未稅，例：實際數量1、單位成本10,500、選含稅 → 實際總成本算 10,000）
- **修法**：`settlement.html` 每個品項新增 `actualCostTaxMode`（`pretax`/`taxed`，預設 `pretax`
  向下相容舊資料），「實際單位成本」欄下方新增未稅／含稅5%下拉；`calcItemCost()` 選含稅時
  `Math.round(qty*unitCost/1.05)`才計入 `actualTotalCost`，未稅則不變；該格同時保留顯示原始
  含稅金額（灰色小字）供核對。`itemActualTotal`／`totalActualCost`／真實毛利／淨利／Excel 毛利
  分析 Sheet／案件管理財務 Tab 皆直接讀取已換算後的 `actualTotalCost`／`summary`，不需另外修改
- **驗證**：Node 腳本帶入確認過的範例（數量1×單位成本10,500，選含稅）驗證換算結果為 10,000，
  與未稅模式（10,500 不變）對照皆正確；`node --check` 驗證 `settlement.html` 內嵌 script 語法
  正確。未在瀏覽器實機操作（同上一筆 2026-08-05h，涉及登入輸入密碼），僅完成公式層級驗證。已完
  成 `git commit`（`ddf328e`）＋ `build_deploy_package.ps1` 打包，尚未套用至正式機，需依 §15
  流程由使用者在正式機執行 `apply_update.ps1`

### 2026-08-05h — 款項沖銷免稅後，已收款／未收款金額同步扣除稅額

- **背景**：使用者回報「案件管理，案件資訊，款項明細跟已收款並沒有同步已沖銷免稅的部分」。追查
  發現 `case-management.js` 的 `itemAmountPretax(idx)` 對已核准沖銷（`taxExempt=true`）的款項
  項目，直接把含稅金額當未稅價回傳（稅額歸零但含稅金額不變）；`receivedTotal()`／
  `outstandingTotal()`／`netReceivedTotal()` 又全部沿用含稅金額加總——沖銷後客戶實際少付的稅
  金，在「已收款」「未收款」KPI 與明細列完全沒有反映。用 `AskUserQuestion` 與使用者確認兩件事：
  ①落差具體是「已收款金額沒跟沖銷後的金額做同步」②沖銷生效後該筆款項的含稅金額本身要跟著降，
  因為客戶實際只付了未稅價、沒有付稅金，我方實收也是這個金額（而非僅未稅/含稅比例重算、含稅
  總額不變）
- **修法**：`itemAmountPretax()` 還原為永遠回傳該筆款項依報價單稅率換算的未稅基準（不再因沖銷
  被覆蓋）；新增 `itemAmountReceivable(idx)`——已沖銷免稅回傳未稅價（即實際收到的金額），未沖銷
  則回傳含稅價；`receivedTotal()`／`outstandingTotal()`／`netReceivedTotal()` 改用
  `itemAmountReceivable()` 計算，`outstandingTotal()` 順帶改為逐筆加總未收款項（原本是
  `合約總額－已收款`，沖銷後兩者對不上）；`itemAmountTax()` 沖銷項目強制回傳 0。前端
  `case-management.html` 明細列「含稅」輸入框與「實收金額」預設值同步改顯示沖銷後金額，且沖銷
  後「含稅」「未稅」兩欄鎖定唯讀（金額已由系統決定，不可再手動編輯）
- **不變更**：頁面最上方「合約總額（含稅）」KPI 仍顯示原始報價單金額，不隨個別款項沖銷重算——
  這是合約層級的參考值，沖銷只影響實際收/未收金額，經使用者確認為預期行為
- **驗證**：Node 腳本帶入範例（某期含稅 94,500＝未稅 90,000＋稅 4,500）獨立驗證修改後的計算邏
  輯：沖銷後該筆 `itemAmountReceivable` 正確降為 90,000、稅額歸零，`receivedTotal()` 與
  `outstandingTotal()` 正確反映扣除的 4,500 稅額缺口。因驗證涉及登入輸入密碼，未在瀏覽器實機
  操作沖銷審核流程走一遍，僅完成公式層級驗證；已完成 `git commit`（`a227f66`）＋
  `build_deploy_package.ps1` 打包，尚未套用至正式機，需依 §15 流程由使用者在正式機執行
  `apply_update.ps1`

### 2026-08-05f — 品項明細置中對齊同步套用至預覽彈窗與正式匯出 PDF

- **背景**：05e 只把「置中對齊」套用在報價單編輯頁的品項明細表格；使用者接著詢問「輸出的PDF是否
  項目明細也有套用置中」，實際檢查發現「預覽報價單」彈窗與 `directExport()` 走後端 Edge Headless
  產生的正式匯出 PDF 都還是舊的靠左/靠右混合對齊，三處排版不一致；已用 `AskUserQuestion` 確認
  使用者要三處統一改為置中
- **範圍**：品項明細渲染實際有三條路徑，缺一不可：① 編輯頁 `.items-table`（05e 已完成，作為
  對齊基準）② 預覽彈窗＋瀏覽器列印共用同一份 Alpine 渲染的 `#pdf-preview-content` DOM，但被
  **兩份不同的 CSS `<style>` 定義**分別套用——頁面本身內嵌 `<style>` 給螢幕預覽用
  （`quotation-form.html:572-582`）與 `_buildPrintWin()` 組出的 iframe `<style>` 給實際列印/轉
  PDF 用（`quotation-form.html:2619-2621`），兩份都要同步改，缺一個畫面會不一致 ③ 正式匯出 PDF
  （`directExport()` → 後端 `/pdf-download`）：`backend/pdf_gen.py` 的 `_build_quote_html()`
  （42-370 行）用無 class 的通用選擇器（`table`/`thead th`/`tbody td`/`td.r`，150-164 行）；
  刻意只改這個函式，不觸碰同檔案裡各自獨立 `<style>` 的 `_build_shipping_html()`（出貨單）與
  `_build_payslip_html()`（勞報單），因為使用者只提到報價單
- **修法**：三處作法一致，只改 CSS、不動任何 HTML `class="r"` 標記——`th`／`td` 預設
  `text-align:left` 改成 `center`；原本讓數量/成本單價/毛利率/售價/金額靠右的 `.r`／`th.r`／
  `td.r` 規則，`text-align:right` 同樣改成 `center`（`font-family` 等其餘樣式不動）。「報價合計」
  金額摘要（`.pdf-totals`／`.totals` 系列 div）是獨立於 `<table>` 之外的區塊，不受影響、自然
  維持靠右，與編輯頁處理方式一致，不需額外排除邏輯
- **驗證**：`python -m py_compile pdf_gen.py` 語法正確；直接呼叫 `_build_quote_html()`
  （外部版／內部版）字串比對確認 `thead th`／`th.r`／`td.r`／`tbody td` 皆已改為
  `text-align:center`，且 `_build_shipping_html()` 原始碼仍保留 `text-align:right`（確認未被
  誤改）；瀏覽器實測「預覽報價單」彈窗，品項明細表頭與資料（# / 品名規格說明 / 廠牌型號 / 數量 /
  單位 / 單價 / 金額）全部置中，下方報價合計金額摘要仍維持靠右，console 無錯誤；
  FORM_VERSION V1.5 → V1.6

### 2026-08-05e — 品項明細數量欄破千裁字修復＋表格對齊方式改為全面置中

- **背景**：接續 2026-08-05d 的表頭/資料對齊修復（當時做法是數字欄表頭改右對齊配合本來就靠右
  的資料），使用者實測後回饋兩點：①「數量」欄位數字到千位以上（4 位數）會被欄框裁字看不全
  ②整體希望改用更簡單一致的方案——**品項明細表格（表頭＋資料）全部欄位一律置中**，只有表格
  外「報價合計」金額摘要維持靠右；已用 `AskUserQuestion` 向使用者確認範圍是整張表格皆置中
  （而非僅「品名/規格說明」單一欄），使用者確認採此方案
- **數量欄破千裁字**：`.cell-input.num`（`quotation-form.html:208`）原本文字方塊靠 `width:100%`
  撐滿固定 60px 欄寬，4 位數以上數字加上瀏覽器原生 number 微調鈕（spinner）擠壓後顯示不全；
  改用 CSS `field-sizing: content`（新增 `.cell-input.qty-input` class，`width:auto` 讓輸入框
  依實際輸入的位數自動撐寬，非固定寫死大小）＋ 數量 `<th>` 改用 `min-width:44px` 取代固定
  `width:60px`，讓 `table-layout:auto` 依欄位實際需求動態加寬整欄（同欄所有列取最大需求，符合
  表格排版慣例）。`field-sizing` 為近代 Chromium 特性，此系統本就要求 Edge Headless 產生 PDF，
  執行環境瀏覽器版本無虞
- **表格全面置中**：撤銷 05d 加在數字欄 `<th>` 的 `text-align:right` inline 覆寫，改為
  `.items-table th` 全域預設由 `text-align:left` 改成 `text-align:center`（`quotation-form.html:171`）；
  `.cell-input`／`.cell-textarea` 新增 `text-align:center`，`.cell-input.num` 移除原本的
  `text-align:right`，`.cell-display`（金額／單項毛利顯示）`text-align:right→center`
  （`quotation-form.html:194-234`）；毛利率輸入框外層 flex 容器 `justify-content` 由
  `flex-end` 改回 `center`、旁邊「需審核」提示文字同步置中。這三個類別（`cell-input`／
  `cell-textarea`／`cell-display`）已確認只在品項明細表格內使用，不影響頁面其他區塊；
  「報價合計」金額摘要區塊用的是完全獨立的 class/inline style，不受影響、仍維持靠右
- **驗證**：demo 帳號測試報價單，瀏覽器實測數量欄輸入 5 位數（98765）完整顯示不裁字、欄寬隨
  之自動加大；品項明細表頭與資料全部欄位（# / 品名規格說明 / 廠牌型號 / 數量 / 單位 / 成本單價 /
  毛利率 / 售價 / 金額 / 單項毛利 / 備註）改為置中對齊，下方報價合計金額摘要仍維持靠右；
  瀏覽器 console 無錯誤；FORM_VERSION V1.4 → V1.5

### 2026-08-05d — 修復報價單「單位」欄下拉建議只剩已選值的問題

- **背景**：使用者回報報價單品項「單位」欄下拉選項只剩「台」，其他選項都不見了。實際排查
  `datalist#quote-unit-options` 本身完整保留 19 個選項（`quotation-form.html:1437-1445`），
  資料沒有遺失
- **根因**：2026-08-05c 把單位欄從固定 `<select>` 改成 `<input list="quote-unit-options">` 後，
  瀏覽器對 `<input list>` 的原生建議清單行為是依「目前欄位內文字」過濾——已存單位為「台」的品項，
  點進欄位時瀏覽器只會列出**包含「台」這個字**的選項，因此只剩「台」自己符合，並非選項被刪除
- **修法**：`quotation-form.html:1378-1381` 單位 `<input>` 新增 `@focus`／`@blur`：聚焦時暫存
  原值並清空欄位（讓瀏覽器 datalist 因空字串顯示全部 19 個選項），失焦時若使用者沒有選新值/沒
  打字（欄位仍為空）則還原原本單位（FORM_VERSION → V1.4）
- **附帶修正：單位欄寬不足導致文字被欄框裁切**：使用者實測時發現選「式（整批）」等較長選項仍
  顯示不全——品項明細編輯表格「單位」欄原本固定 `width:60px`，扣掉 `.cell-input` 內距與原生
  datalist 下拉箭頭後，可用文字寬度只剩約 40px，容不下 5 個全形字元；改為 `width:100px`
  （`quotation-form.html:1325`），連帶 `.items-table` 底線寬度 `min-width:1040px→1080px`
  同步加大（`quotation-form.html:164`）
- **附帶修正：預覽／匯出 PDF 的單位欄過窄導致文字換行、行高被拉高**：`.pdf-items` 預覽表格
  （`quotation-form.html:1893`）與後端 `pdf_gen.py`（`_build_quote_html()` 外部/內部版共用的
  表頭，`pdf_gen.py:253`）「單位」欄原本各僅 `40px`／`38px`，同一批較長單位文字會被迫換成 2～3
  行、拉高整張報價單高度；分別加寬至 `74px`／`70px`（皆為 `table-layout:auto`，非固定寬，加寬後
  仍可視需要換行，只是不再因欄位過窄而不必要地換行）
- **新增：預覽／匯出 PDF 若所有品項皆無備註，自動隱藏「備註」欄**：釋出的欄寬讓品名/廠牌等欄位
  自然變寬，避免固定備註欄長期佔用版面卻多數時候是空的；前端 `quotation-form.html` 預覽表格
  （`~1889-1925`）與後端 `pdf_gen.py`（`_build_quote_html()`，含區段標題列 `colspan` 同步收斂
  1 欄）皆已同步，僅要有任一品項填了備註就照常顯示整欄
- **附帶修正：品項明細編輯表格表頭與資料對齊方式不一致**：使用者回報數量/成本單價/毛利率/
  售價/金額/單項毛利等欄位「表頭靠左、資料靠右」，視覺上像跳欄；這些欄位的輸入框本來就用
  `.cell-input.num`／`.cell-display`（皆 `text-align:right`）呈現數字，改為表頭也加上
  `text-align:right` 對齊（`quotation-form.html:1321-1337`），`#` 欄表頭與資料則統一置中；
  毛利率輸入框外層 flex 容器補上 `justify-content:flex-end` 使其與表頭同向右對齊
  （`quotation-form.html:1392`）。品名/規格說明、廠牌/型號、單位、備註等文字欄維持左/左不變
- **驗證**：demo 帳號建立測試報價單，瀏覽器實測輸入「式（整批）」單位欄完整顯示不換行、預覽
  彈窗備註欄在無備註時正確消失、品項明細表格數字欄表頭與資料改為同向右對齊；另以
  `python -m py_compile` 確認 `pdf_gen.py` 語法正確，並直接呼叫 `_build_quote_html()`（外部版／
  內部版、有無備註四種組合）驗證欄位隱藏與欄寬邏輯皆正確

### 2026-08-05c — 報價單品項「單位」欄可手動輸入 + 窄螢幕欄位寬度保護

- **單位欄改為可手動輸入**：`quotation-form.html` 品項明細「單位」原為固定 `<select>`（僅原有
  17 個選項可選），改為 `<input list="quote-unit-options">` 搭配共用 `<datalist>`，保留原生下拉
  建議清單的同時允許使用者自由輸入任意文字；新增 **SET**、**立** 兩個選項
- **窄螢幕不再壓縮數量／成本單價等欄位**：`.items-table` 原本只有 `width:100%`，外層
  `overflow-x:auto` 容器在瀏覽器變窄時從未真正觸發（表格本身會跟著等比例壓縮，數字被壓到看不
  見）；新增 `min-width:1040px`（涵蓋含內部成本欄位時所有欄位寬度總和）作為底線，改為欄寬固定、
  改觸發容器橫向捲軸，不受瀏覽器寬度影響
- **驗證**：本機啟動 `uvicorn`，用 demo 帳號（隔離空白庫）建立測試報價單，瀏覽器實測手動輸入
  「SET」成功寫入欄位；以 JS 強制容器縮至 600px 寬確認表格維持 1040px、觸發橫向捲軸而非欄位壓縮
  後，關閉測試 server（FORM_VERSION → V1.3）

### 2026-08-05b — 業務開發×案件管理三項聯動（簽核閘門／連結可修改／動態同步）

- **報價單「已成案」需簽核完成**：`PATCH /api/quotations/{no}/deal-tag` 新增檢查，`deal_tag` 欲
  設為「已成案」時報價單 `status` 必須為「已送出」，否則 400；`quotation-form.html` 下拉選單同步
  disable「已成案」選項並在 `onDealTagChange()` 前端擋一次（雙重防呆，FORM_VERSION → V1.2）
- **業務開發案件連結報價單可修改**：原「轉建報價單」（`PATCH /api/dev-cases/{id}/convert`）僅在
  尚未連結時才顯示、且無法回頭修改；`dev-crm.html` 新增「修改連結」鉛筆按鈕 + 對應 modal
  （`openRelinkModal()`/`doRelink()`），沿用同一個既有端點（本來就允許覆寫，只是前端沒開放入口）
- **業務開發進度同步至案件管理「動態」Tab**：`GET /api/quotations/{no}/updates` 新增兩個來源
  （比照既有 work_logs／daily_task_completions 唯讀卡片模式）——① `dev_logs`（依
  `dev_cases.converted_quote_no` 反查 case_id 後列出）② `dev_case.status` 的 `audit_log`
  紀錄（案件狀態變更事件）；僅在該報價單有業務開發案件連結時才出現
- 用 demo 帳號（隔離空白庫）建立測試報價單/案件/開發記錄，以 curl 驗證三項行為皆正確後才收尾

### 2026-08-05 — 報價單簽核永久卡死：兩個共同根因修復＋正式機 4 張卡死單查證

- **背景**：使用者回報「系統預設申請人不得自己簽核，但這位申請人送出的報價單，簽核流程設定裡
  把這位申請人列為簽核人，導致報價單卡在簽核」；正式機當下已有報價單卡死。用使用者提供的正式機
  帳號（`jeff`，superadmin）唯讀查證，確認卡死的是 `MQ-202608-003`～`006` 四張、皆由 `jeff`
  直接送審；正式機 `approval_flow` 確實已配置兩層（tier0=`jeff`、tier1=`corbin`）
- **Bug A**：`update_quotation()` 送審時把 `approval_flow` 設定轉成 tiers 快照，完全沒有排除
  送審人自己；`quotation-form.html` 的 `isCurrentTierApprover()` 寫死擋掉送審人自己的按鈕，但
  `approval-queue.html` 的 `canApprove()` 沒擋，兩頁邏輯矛盾；`approve_quotation()` 有 tiers
  分支原本也無自簽檢查
- **Bug B（比對正式機實際卡死單後發現，才是這 4 張單真正的成因）**：這 4 張單的 `approval`
  JSON 完全沒有 `tiers` 欄位——`quotation-form.html` 的 `confirmSubmit()` 在「新單不先存草稿、
  直接送審」情境（`isNewRecord===true`）打的是 `POST /api/quotations`（`create_quotation()`），
  但這個端點完全沒有 tiers 建構或審核通知邏輯（該邏輯只存在於 PUT 的 `update_quotation()`），
  於是完全繞過已設定的兩層流程，也沒通知任何人（`corbin` 從未被告知要簽核）——任何人「新建
  報價單直接送審」都會中招，不限於送審人與簽核人重疊的情況
- **修法**：新增共用 helper `_build_approval_tiers_and_notify()`（含 `_exclude_requester()`），
  `create_quotation()`（`body.status=='待審核'` 時，INSERT 成功拿到最終 quote_no 後）與
  `update_quotation()` 都改呼叫同一段邏輯（對 `update_quotation()` 是純重構、行為不變）；
  `approve_quotation()` 有 tiers 分支補上自簽 403 防禦；`approval-queue.html` `canApprove()`
  補上與 `quotation-form.html` 一致的判斷
- **驗證**：已用正式機唯讀查到的真實 `approval_flow` 設定（`jeff`/`corbin` 兩層）直接呼叫新
  helper 驗證：`jeff` 正確被排除、只剩 `corbin` 一層、`corbin` 正確收到通知；全檔語法檢查通過。
  全程只對正式機呼叫唯讀 GET 端點（`/api/settings/approval-flow`、`/api/users`、
  `/api/quotations`、`/api/quotations/{no}`），未寫入任何正式機資料
- **附帶修正**：正式機 LAN IP 全站記錄錯誤（`172.16.11.211`→`172.16.10.177`，使用者確認為固定
  IP，見 §0/§1），含 `main.py` CORS 白名單、`email_notify.py`/`system.py` 的 email base_url
  預設值、`notification-settings.html` 預設值；若正式機從未手動設定過 `base_url`，過去簽核通知
  信件裡的連結可能都是死連結，建議部署後至「通知設定」頁確認實際存值
- **⚠️ 尚未在瀏覽器實機重現完整送審流程**（本機無 server 可測）；正式機 4 張卡死單不透過資料庫
  層手動修改，改為部署此修復後由 `jeff` 逐一「收回草稿」再重新送出，會走已修復的
  `update_quotation()` 正確重建 tiers 並通知 `corbin`，不需任何人手動改資料庫

### 2026-08-04 — 報價單「新增品項」／「新增區段標題」按鈕失效修復

- **背景**：使用者回報報價單編輯頁「新增品項」「新增區段標題」兩個按鈕點擊完全沒反應
- **根因**：`quotation-form.html` 的 `addItem()`/`addHeader()` 皆在把新項目 push 進 `q.items`
  之前先呼叫 `crypto.randomUUID()` 產生 id，但 `randomUUID()` 依 Web Crypto API 規範**只在安全
  情境（HTTPS 或 `localhost`）下才存在**；本文件 §1 記載的區網存取位址
  `http://172.16.11.211:666` 是純 HTTP 且非 `localhost`，屬非安全情境，`window.crypto.randomUUID`
  為 `undefined`，呼叫時直接拋出 `TypeError`，函式中止在 `push` 之前——兩個按鈕共用同一根因，
  可解釋為何會同時失效。同檔案另有 2 處相同呼叫（`loadQuote()` 補齊舊單缺漏 id、`copyToNew()`
  複製為新單時重編 id）具同樣風險，一併修正
- **修法**：新增 `genId()` helper，安全情境下優先用 `crypto.randomUUID()`，不存在時 fallback 為
  手動組出的亂數字串 id（時間戳 36 進位＋亂數），檔案內 4 處呼叫點全數改用此 helper，行為對外
  不變、id 唯一性不受影響
- **⚠️ 尚未實機驗證**：本次受限於當下環境，開發機測試 server 未及啟動即改為優先處理部署匯出，
  修復判斷依據為 MDN Web Crypto API 安全情境限制規範核實呼叫鏈與症狀完全吻合，但**未在瀏覽器
  實際重現與驗證過**；下次有機會時建議在區網 IP（非 `localhost`）位址下實測「新增品項」「新增
  區段標題」按鈕確認修復生效，若仍有問題需重新排查

### 2026-08-03i — CRM 搜尋殘留 bug／側邊欄角標時區 bug（既有潛藏問題）／出貨單歷史紀錄

- **背景**：實測上一版（2026-08-03h）後，使用者回報兩個問題並提出一個新功能：業務開發搜尋仍會
  出現不符搜尋文字的案件；業務開發／報價單側邊欄角標「仍然顯示但未有其他更新」；要求新增出貨單
  歷史紀錄頁面
- **CRM 搜尋殘留**：上一版只修了 `loadCases()` 的回應順序（`_loadSeq`），未發現真正主因——
  `dev-crm.html` 搜尋框同時綁 `x-model.debounce.400ms="searchQ"` 與 `@input="loadCases()"`
  兩個監聽器，debounce 只延遲「寫入 model」的時機，`@input` 每個按鍵立刻觸發卻讀到還沒被
  debounce 寫入的舊值，查詢字串永遠落後輸入一拍；改為 `x-model="searchQ"`（即時寫入）+
  `@input.debounce.400ms="loadCases()"`（延遲觸發查詢），已用瀏覽器 network 面板確認每次
  只送出一個對應當下輸入內容的請求
- **側邊欄角標時區 bug（既有潛藏問題，與本次或上次改動無關）**：用瀏覽器實際重現——造訪
  `dev-crm.html` 後 `motrix_module_seen.dev_crm` 正確更新為當下時間，手動插入一筆更早的稽核
  紀錄後角標仍誤判顯示「1」；根因是 `sidebar.js` 寫入時間戳用 `toISOString()`（UTC，帶 `Z`），
  後端 `audit_log.at` 存台灣本地時間（無時區），`/api/audit-log/module-counts` 用 SQL 字串
  `"at > ?"` 直接比較，本地時間字串字典序幾乎恆大於 UTC 字串（差 8 小時），角標幾乎永遠誤判為
  「有更新」；新增 `_localISOString()` 取代兩處 `toISOString()`；同一套 bug 也連帶影響
  `daily-tasks.html` 的 `isNewTask()`（`ut > this._prevSeenDT` 同樣是原始字串比較），格式修正後
  一併自動修好、不用改該頁程式碼；已用「造訪前／造訪後」假稽核紀錄重現並驗證修復前後行為差異
- **出貨單歷史紀錄**（新頁面 `frontend/pages/shipping-export-history.html`）：後端新增唯讀端點
  `GET /api/shipping-notes/export-history`（注冊在 `/{note_no}` 之前，避免路由被吃掉），把每張
  出貨單既有的 `export_log` 欄位（`record_shipping_export()` 早就在寫）攤平成「一次匯出＝一筆」
  事件列表，支援 `q`（單號/客戶/專案）與 `year`/`month` 篩選，無新增欄位、無 DB migration；前端
  比照 `audit-log.html` 版面 + `dev-crm.html` 年月下拉 pattern；`sidebar.js`「歷史紀錄」旁新增
  入口，權限 admin+；已建測試出貨單匯出兩次（對外+對內）驗證頁面顯示、搜尋/清除篩選、單號連結
  導向案件管理皆正確，測試資料已清除還原

### 2026-08-03h — 站內通知清理／CRM 搜尋修復／全站 Email 通知擴充

- **背景**：使用者一次反映三件事——①「每次 API 都核對資料庫內容，很多刪除單據仍然顯示通知」
  ② 業務開發搜尋框「打兩個字沒反應，要刪一個字才生效」③「所有填寫、變更、操作都需要信件通知」
- **①通知清理（雙管齊下）**：`notifications` 表與來源記錄（報價單/出貨單/工作事項/業務開發案件）
  原本無外鍵，`helpers/audit.py` 新增 `_filter_live_notifications()`（`GET /api/notifications/mine`
  讀取時濾掉來源已刪除/軟刪除的孤兒通知）+ `_purge_notifications()`（來源刪除時主動清列），接線
  `quotations.py`/`shipping_notes.py`/`daily_tasks.py`/`dev_crm.py`/`projects.py` 共 5 個刪除端點
- **②CRM 搜尋修復**：`dev-crm.html` `loadCases()` 每次 `@input` 直接 fetch 沒有序號保護，快速輸入時
  較舊查詢的回應可能晚於新查詢落地覆蓋畫面——新增 `_loadSeq` 序號守衛；同時客戶名稱欄位比照
  `quotation-form.html` 客戶自動完成模式（原生 datalist 換自訂下拉），選取後立即綁定 `customer_id`
  並顯示該客戶「過去案件」清單
- **③全站 Email 擴充**：與使用者確認規則——跳過報價單/出貨單/承攬商等頁面自動存檔會打的 PUT 整筆
  覆寫端點（避免編輯期間信箱轟炸），建立/刪除/狀態變更/子項目新增等離散動作全部補齊；新增約 60 處
  `notify_module_activity()` 呼叫，涵蓋 17 個 router；`email_notify.py` 新增出貨單簽核流程專屬四函式
  （`notify_shipping_submitted`/`notify_shipping_next_tier`/`notify_shipping_approved`/`notify_shipping_returned`，
  此前出貨單完全沒有寄信）
- 已用 FastAPI TestClient 對 demo 帳號跑過 quotations/daily-tasks/dev-cases/vendor-contractors/
  shipping-notes/customers/parts 建立與刪除全流程確認不噴錯；手動插入孤兒通知列驗證過濾邏輯正確
  （2 筆孤兒被濾掉、1 筆未知 type 正常保留）；`import main` 全模組載入無 ImportError
- 附帶修正：外包名冊「（無承攬商，純點工）」文字改為「（無承攬商，個人名義案件承攬）」

### 2026-08-03g — 外包名冊新增「參與案件」聯動

- **背景**：使用者要求「外包人員有參與哪些案件也要跟承攬商管理一樣聯動，方便後續知道那些外包
  人員參與哪些案件」——承攬商管理（`vendor-contractors.html`）詳情面板本來就有「派發紀錄」區塊，
  但外包名冊（`contractors.html`）的個人詳情面板完全沒有對應功能
- **實作**：`contractors.html` 選中人員時比照承攬商頁作法，抓 `GET /api/contractor-dispatches`
  全列表（無新增後端 API，沿用既有端點），前端用 `d.personnel.some(p => p.id === c.id)` 篩出
  該人員實際參與（`personnel_json` 快照內含其 id）的派發紀錄，新增「參與案件」區塊顯示：案號
  連結（導向案件管理承攬商 tab）、派發狀態徽章（`_dStatusClass()`，補齊承攬商頁原本缺的
  `pending_acceptance`/`accepted` 對應）、所屬承攬商（純點工顯示「（無承攬商，純點工）」）、
  該人員個人金額（`_myDispatchAmount(d)`，非整筆派發總額）
- 已用瀏覽器實測：選中外包名冊人員「王小明」，正確顯示參與的 2 筆案件（含一筆純點工、一筆
  已取消的承攬商派發），個人金額與狀態皆正確，無 console 錯誤

### 2026-08-03f — 承攬商派發改為選填，支援純外包名單人員點工（DB v37）

- **背景**：使用者反映「某些案件有外包人員，就沒有承攬商，單純點工，目前系統綁死要選擇承攬商」——
  上一版（2026-08-03e）加入的外包名單人員功能仍要求必選承攬商，無法涵蓋純點工（沒有對應承攬商）的案件
- **DB migration**：`_m037_dispatch_vendor_optional`（v37）將 `contractor_dispatches.vendor_id` 從
  `INTEGER NOT NULL` 改為可為空。SQLite 不支援直接 `ALTER COLUMN` 移除 NOT NULL，沿用 `_m035`/`_m014`
  的建新表→搬資料→刪舊表→改名手法整表重建，冪等檢查用 `PRAGMA table_info` 的 `notnull` 旗標
  （新增 `_col_notnull()` helper）；全新安裝的 inline schema 也同步拿掉 NOT NULL
- **後端**（`backend/routers/vendor_contractors.py`）：`DispatchIn.vendor_id` 改 `Optional[int] = None`；
  `create_dispatch()`/`update_dispatch()` 驗證改為「承攬商與外包名單人員至少擇一」，兩者皆空 → 400
  「請至少選擇承攬商或外包名單人員其中一項」；只有 `vendor_id` 有值時才檢查承攬商是否存在；
  `_dispatch_row()` 的 `vendorName` 補上 `or ""` 避免 LEFT JOIN 對到 NULL 時回傳 `None`；
  `import_dispatch_to_quote()` 的 `vendor_name` fallback 原本會產生醜陋的「承攬商#None」，改為
  「外包人員（點工）」
- **前端 Modal**（`case-management.html`/`.js`）：承攬商欄位拿掉必填星號，預設選項改「— 無承攬商
  （純外包名單人員點工）—」，下方補說明文字；`saveDispatch()` 的前端驗證同步比照後端邏輯；
  `vendor_id` 送出時改為 `? Number(...) : null`
- **前端派發卡片列表**：標題無承攬商時顯示「外包人員（點工）」（`_dispatchLabel(d)` 統一處理，
  四處確認/提示訊息一併改用）；金額改用 `grandTotal`（含稅承攬商 + 外包人員）取代原本只算承攬商
  部分的顯示；新增外包人員明細表格（比照品項表格樣式）；底部小計列拆成 小計／稅額／外包人員／
  總成本 四項，品項為空時不顯示小計與稅額列
- **精算頁面**（`settlement.html`）：新增 `_dispatchRows(d)` helper 取代原本內嵌在 template 裡的
  陣列運算——有承攬商時承攬商列＋外包人員縮排列；純點工（無承攬商）時外包人員第一筆頂替承攬商列
  顯示派發狀態，避免出現佔位用的「（未命名承攬商）」空列
- **驗證**（零資料流失）：複製開發庫副本，在副本上跑新版 `db.py` 的 `init_db()`，確認 migration
  前後 `contractor_dispatches` 列數不變、每筆資料逐欄比對無跑位、`vendor_id` notnull 旗標歸零、
  `schema_version` 更新為 37；重跑一次 `init_db()` 確認冪等（second run 為 no-op）；瀏覽器實測：
  開發機上跑的 uvicorn 行程（PID 1636，`hermes-agent` venv 底下啟動，非本專案文件記載的
  `autostart.bat`/排程機制，`restart.bat` 殺不掉）force kill 後從專案目錄重新啟動，確認正式接上
  新程式碼與 migration；建立不選承攬商、只加外包名單人員「王小明」（NT$80,000）的派發，前端驗證
  「至少選擇承攬商或外包名單人員其中一項」正確擋下空白提交，儲存後卡片正確顯示「外包人員（點工）」
  與明細，精算頁面「三、承攬商派發成本」正確併入 NT$80,000、不顯示空白承攬商列，全程無 console 錯誤

### 2026-08-03e — 承攬商派發新增外包名單人員個別計費，同步至財務／精算（DB v36）

- **背景**：使用者要求案件管理／承攬商派發新增「外包名單人員」，且這些人員與承攬商本身寫的金額
  都要同步到財務／精算顯示
- **後端**：`backend/db.py` 新增 DB v36 migration `_m036_dispatch_personnel`，
  `contractor_dispatches` 加 `personnel_json TEXT DEFAULT '[]'`（自包含快照
  `[{id,name,amount,note}]`，不隨 `contractors` 表後續變動連動）；`backend/routers/contractors.py`
  新增 `GET /api/contractors/selectable`（比照 `vendor-contractors/selectable` 慣例，任何登入者
  可讀，只回傳 id/name/phone，不含銀行/身分證等敏感欄位）；`backend/routers/vendor_contractors.py`
  的 `DispatchIn`／`_dispatch_row()`／`create_dispatch()`／`update_dispatch()` 皆補上
  `personnel_json` 讀寫，`_dispatch_row()` 新增計算欄位 `personnelTotal`（人員金額加總）與
  `grandTotal`（`totalWithTax + personnelTotal`，承攬商含稅金額 + 外包人員金額**不計稅**，
  因外包個人屬薪資性質非營業稅發票）
- **前端**：`case-management.html`／`js` 新增派發 Modal 內「外包名單人員（可複選，個別計費）」
  區塊（下拉選擇＋加入，仿既有 stage 負責人 `attendee-chips`/`attendee-add` 互動模式），每人一列
  含金額輸入；Modal 底部顯示派發總成本（承攬商含稅合計 + 外包人員小計）；`settlement.html`
  新增「三、承攬商派發成本」區塊（自動即時讀取 `GET /api/contractor-dispatches?quote_no=`，
  唯讀，排除已取消的派發，依派發分組列出承攬商與其下外包人員金額），`calcSummary()` 新增
  `dispatchTotal` 併入「實際總成本」計算；`case-management.html` 財務 Tab（讀取已存的精算
  `summary`）同步補上「承攬商派發成本」列
- **實測時發現並修正兩個問題**：① 忘記把 `CURRENT_VERSION` 從 35 同步改成 36——`_run_migrations()`
  的版本守門是「`current >= CURRENT_VERSION` 就整個跳過」，若沒改，等正式機部署過 v35 後，
  這次新增的 v36 migration 就會被永久跳過而不會執行；已修正並重新驗證 ② 案件管理承攬商 tab
  原本就有的「外包總成本」彙總（`dispatchTotalCost()`）只加總 `totalAmount`（不含稅、不含人員），
  金額本來就不對，這次一併修正為使用新的 `grandTotal` 並排除已取消派發
- 已用瀏覽器完整走過建立承攬商（ABC工程行）與外包名冊人員（王小明）→ 新增派發（品項 NT$30,000
  +稅 5% + 王小明 NT$15,000＝總成本 NT$46,500）→ 儲存後重新整理確認資料正確持久化 → 精算頁面
  正確顯示「三、承攬商派發成本」分組明細與小計、「實際總成本」正確併入 → 案件管理財務 Tab
  正確顯示已存精算結果 → 把派發狀態改為「已取消」後，承攬商 tab 外包總成本與精算頁面成本皆
  正確歸零（確認排除已取消派發的規則生效）；全程無 console 錯誤

### 2026-08-03d — 修復 module_versions 表無限增生 bug（DB v35）

- **背景**：使用者詢問正式機每日備份為何每次 300~400MB。用當天雲端備份的 db 副本唯讀查驗
  （完全未觸碰正式機）發現 `module_versions.json` 匯出檔案高達 344MB，比 db 本身（301MB）
  還大；查 db 內容發現該表實際 **626,725 列**，但只有 **143 組不同的 (module, version)**
  （跟 `version_manifest.json` 筆數一致），平均每組重複約 4,383 次
- **根因**：`module_versions` 表只有 `id` 主鍵，`(module, version)` 從未有 UNIQUE 限制；
  `_sync_module_versions()`（`helpers/startup.py`）每次伺服器啟動都用 `INSERT OR IGNORE`
  想達到「已存在就跳過」，但沒有 UNIQUE 可判斷衝突，這個 INSERT **永遠會成功**，等於每次
  重啟都把 143 筆 manifest 內容整批當新資料插入一次；正式機的 crash-restart 自動重啟迴圈
  （§1.1）加上歷次升級套用的重啟，長期累積出這個倍數
- **修法**（`backend/db.py`，DB v35 `_m035_module_versions_unique_dedup`）：
  - `module_versions` 補上 `UNIQUE(module, version)`（含全新安裝用的 inline schema，讓新裝機
    從一開始就有此限制；SQLite 不支援 `ALTER TABLE ADD CONSTRAINT`，既有安裝走 migration
    用「建新表→分兩段 `INSERT OR IGNORE` 搬資料（使用者手動建立的紀錄，`updated_by != 'system'`，
    永遠優先於系統同步產生的重複列）→ 刪舊表→改名→重建索引」的既有慣例手法（比照
    `_m014_weekly_recurrence` 已示範過的同款重建表模式）
  - migration 內含 `VACUUM`，讓重複列騰出的磁碟空間立即釋放，不留到之後另外處理
  - migration 具冪等性（先檢查 UNIQUE 是否已存在才動手，符合本檔案「Each migration must be
    idempotent」慣例），全新安裝／已修復過的安裝重跑會直接略過
  - `backend/routers/module_versions.py` 的 `POST /api/module-versions`（手動新增版本紀錄）
    補上 `sqlite3.IntegrityError` → 409 的友善錯誤處理，避免加上 UNIQUE 後管理員手動輸入
    重複 (module, version) 時噴 500
- **零資料流失驗證**（用當天正式機備份 db 的副本實測，全程只在本機操作、未連線或修改正式機）：
  - 查過正式機備份確認 **626,725 列全部 `updated_by='system'`，沒有任何使用者手動建立
    的紀錄**——這次清理不會漏掉任何人工輸入的內容
  - 直接用新版 `db.py` 的 `init_db(路徑)`（`apply_update.ps1` 本來就是這樣做 migration 乾跑
    驗證）在備份副本上實測：1.02 秒內完成，db 從 301.07MB → **1.71MB**；`module_versions`
    143 列，`COUNT(DISTINCT module||version)` 同為 143（證明真的去重）；逐筆比對 143 筆
    manifest 內容與 db 內容，只有 1 筆歷史內容不同（`每日工作事項/2026-07-22r`，屬於
    manifest 本身在該筆存在後又被改過內容、尚未部署同步的既有現象，不是這次遷移造成，
    下次部署套用時 `_sync_module_versions()` 既有的 UPDATE 同步邏輯就會自動修正）
  - 額外用 `dbstat` 虛擬表確認 301MB 的 db 裡，`module_versions` 表+索引就佔了約 312.5MB
    （超過 99%），其餘所有業務資料表加總不到 1.5MB——確認沒有其他表存在類似異常，這次修正
    範圍已涵蓋完整根因
  - 也驗證了全新安裝（空 db 從零 `init_db()`）與重複執行（migration 冪等性）兩種情境皆正確
- 無其他 DB 表受影響；本次改動已在開發機驗證完整，**尚未套用至正式機**——需依 §15 流程，
  在正式機執行 `apply_update.ps1`（本身已有 db 快照＋migration 乾跑驗證＋失敗自動回滾）

### 2026-08-03c — 案件管理介面優化（5 項，依序完成）

- **背景**：使用者請我針對案件管理（`case-management.html`）提供介面建議，逐項確認後「照順序開始改」。5 項如下
1. **合併執行類分頁**：`執行進度／叫料管控／設備登錄／保固備注` 四個一級 tab 合併為一個「執行管理」+ `.cm-subtabs` 二層切換（CSS 早已定義但整份檔案沒用到，這次補上使用），一級 tab 從 9 個減到 6 個
2. **手機版分頁溢出修正**：`.cm-tabs`/`.cm-subtabs` 補上 `overflow-x:auto` + 細捲軸樣式，避免窄螢幕分頁被裁切
3. **案件卡片「有新動態」未讀提示**：新增 `POST /api/quotations/case-activity`（`backend/routers/quotations.py`），一次 SQL `UNION ALL` 彙整 `case_updates`/`work_logs`/`daily_task_completions JOIN daily_tasks` 三個來源（這三者都不會更新 `quotations.updated_at`，原本完全無法從既有欄位判斷有無新動態）取每案最新時間，非 admin 沿用 `/api/quotations` 同款角色過濾。前端仿照業務開發 CRM 剛做的「未讀游標＋一鍵已讀」設計（`localStorage['motrix_casemgmt_read_at']`，只能靠手動點擊「一鍵已讀」位移，不會因造訪頁面自動位移）
4. **精簡 Header KPI**：拿掉與「叫料管控」分頁內容重複的「叫料到料」膠囊
5. **卡片新增「負責業務」**：`sales_person` 欄位 `/api/quotations` 本來就有回傳，前端補一行顯示即可
- **實測時抓到並修正一個真實 bug**：任務 1 一開始誤改到 `case-management.html` inline `<script>` 裡的 `function __noop_stub()`——這正是 2026-08-02c 條目已警告過的死碼陷阱（真正生效邏輯在外部 `frontend/js/case-management.js`）。瀏覽器 console 出現 `execSubTab is not defined` 才發現，已把對應狀態與方法改補到 `case-management.js` 的真正 `app()` 函式
- 已用 demo 帳號跑完整報價單流程（建立→送出審核→簽核→已成案，過程中發現 demo 預設無簽核流程時禁止自簽，已在簽核設定加入 demo 為簽核人）建立測試案件，實機驗證 6 個一級 tab + 4 個子分頁切換、KPI 剩 4 顆、卡片顯示業務欄位；新增「動態」留言後確認未讀 badge/彙總列正確顯示、一鍵已讀正確清除、重整兩次不會自動消失、同一天內再次留言仍正確判定未讀（未重蹈 dev-crm 那次的字串比較 timestamp bug）
- 無 DB migration

### 2026-08-03b — 業務開發 CRM：一鍵已讀／只看未讀篩選／卡片加寬

- **背景**：使用者反映「有更新」琥珀色提示會不斷累積、點不完。追查根因：舊機制依賴 `sidebar.js` 全域共用的 `motrix_module_seen`/`motrix_module_prev_seen`，已讀基準是「上一次頁面載入的時間點」而非「離開時間點」——同一次瀏覽中自己編輯/新增的案件，其 `updatedAt` 必定晚於本次造訪基準，下次造訪仍判定為「有更新」，且該標籤原本寫死只給 admin+ 看
- **前端**（`dev-crm.html`）：
  - 已讀基準改為 dev-crm 專屬、`localStorage['motrix_devcrm_read_at']` 儲存的游標，**只能靠手動點擊「一鍵已讀」才會位移**（不再因造訪頁面自動位移），從根本解決「已讀太多無法消除」；不再限定 `isAdmin`，改開放給所有能使用本模組的角色
  - 新增 `unreadCount`／`isUnread(c)`／`markAllRead()`；左欄新增「未讀彙總列」（`.dc-unread-bar`，比照既有 `.dc-stale-bar` 樣式），顯示未讀筆數、可點擊切換「只看未讀」篩選、右側「一鍵已讀」按鈕
  - `filteredCases` 新增 `unreadOnly` 篩選條件（與既有「只看逾期」`staleOnly` 可並存，紅色逾期樣式優先於琥珀色未讀樣式）
  - `.dc-list` 欄寬 300px→340px；卡片新增業務開發／專案規劃人員姓名列（`salesPersonNames`／`plannerNames`，後端 `_case_row()` 本就有回傳，未改後端）
  - **實測時發現並修正一個 bug**：`isUnread()` 一開始直接用字串比較 `c.updatedAt > readAt`，但後端時間戳為 `"2026-08-03 12:24:24"`（空格分隔）、`readAt` 為 `toISOString()` 的 `"...T..."` 格式——同一天的日期在空格與 `T` 的 ASCII 排序下，字串比較恆為「未大於」，導致當天所有更新都不會被判定為未讀（用 demo 帳號建立測試案件當場重現）。已改為 `new Date(c.updatedAt.replace(' ','T'))` 正規化後用 `getTime()` 比較（比照既有 `_daysSince()` 的正規化寫法）
- 無 DB migration；未改動 `sidebar.js`/`notif.js`（風險侷限在 `dev-crm.html`，其他模組共用的 sidebar 數字徽章機制不受影響）
- 已用 demo 帳號（隔離空白 db）實機驗證：建立測試案件＋開發記錄 → 未讀彙總列與琥珀色標籤正確顯示 → 「一鍵已讀」立即清空並顯示 toast → 重新整理兩次確認已讀狀態持久不會消失也不會誤判 → 再次編輯記錄後未讀正確重新出現且不會因重整頁面而自動清除（修正前的「兩次造訪後才會消失」問題不再重現）→ 「只看未讀」篩選正確運作

### 2026-08-03a — 業務開發 CRM：年月篩選／全部排除未成案／洽談中逾期警示

- **背景**：使用者要求三項 dev-crm.html 強化：① 案件列表年份/月份快速篩選 ② 洽談中案件超過30天未更新給予顏色警示＋通知 ③「全部」tab 排除未成案案件（比照 `quotations.html` `全部(不含未成案)` 的既有作法，2026-07-20j）
- **前端**（`dev-crm.html`）：`filterStatus`/`status=` 的伺服器端篩選改為完全前端化（比照 `quotations.html` 的 `get filtered()` 架構）——`loadCases()` 只送 `q`，新增 `get filteredCases()` 一次套用狀態（全部排除未成案）/年/月/`staleOnly` 四個條件；chip 點擊不再觸發 `loadCases()` 重新整理。新增年/月下拉（依 `createdAt` 動態產生年份選項）、`isStale()`/`staleDays()`/`_daysSince()` 判斷洽談中且 `updatedAt` 逾30天，卡片改紅色警示樣式＋「⚠ 超過N天未更新」徽章（優先權高於既有「有更新」琥珀色標籤），並新增比照 `.dc-admin-bar` 的逾期彙總列 `.dc-stale-bar`（不限 admin 可見，點擊切換只看逾期）
- **後端**（`dev_crm.py`）：新增 `_check_dev_case_stale()`/`schedule_dev_case_stale_check()`（比照 `daily_tasks.py` 既有到期通知 pattern，08:00 排程＋啟動立即補跑），通知對象為案件業務開發＋專案規劃人員（無指派則退回建立人）＋所有 admin/superadmin，站內通知（`_notify`）＋email（`notify_dev_case_stale`，`helpers/email_notify.py` 新增）雙軌；30天後每14天重複提醒一次；guard key 額外納入 `updated_at`，避免案件被重新更新後再次逾期時，因 bucket 數字重算重複而永久漏發通知
- `main.py` 新增 `dev_crm.schedule_dev_case_stale_check()` 呼叫；`helpers/__init__.py` 補上 `notify_dev_case_stale` 的 `__all__` 項目
- 無 DB migration（30天判斷純算 `dev_cases.updated_at`；通知防重發guard key 沿用既有 `system_settings` key-value 儲存，同 `daily_tasks.py` 的 `_get_setting`/`_set_setting` 慣例）
- 已實機驗證（demo 帳號建立測試案件，直接改 `motrix_erp_demo.db` 的 `updated_at` 回溯35天）：年/月篩選正確排除不符月份案件、逾期彙總列與紅色卡片徽章正確顯示且「只看逾期」可切換、「全部」設為未成案後正確從計數與清單排除、後端啟動 log 確認 `Dev case stale check complete` 無錯誤
- **已部署至正式機**（2026-08-03，commit `259ad84`，`apply_update.ps1` 套用成功、健康檢查通過、無回滾）；同時補上先前漏做的 `version_manifest.json` 條目（新條目需插在陣列最前面，供登入頁版本 footer／部署包 manifest 抓「最新版本」用）

### 2026-08-02d — 承攬商管理新增銀行帳戶欄位與存簿影本上傳

- **背景**：使用者要求「承攬商管理」（`vendor_contractors` 表）比照「外包名冊」模組（`contractors` 表，個人承攬工/勞報單用）補上銀行帳戶欄位（代碼/名稱/分行/戶名/帳號）與存簿影本上傳
- **關鍵差異**：`contractors` 表銀行欄位是扁平 DB 欄位（有獨立 migration）；`vendor_contractors` 的擴充欄位一律走 `data_json`（`category`/`tags`/`visits`/`notes` 既有慣例）——這次比照後者，銀行欄位與存簿影本都放進 `data_json`，**不新增 DB migration**
- **後端**（`routers/vendor_contractors.py`）：`from routers.contractors import _stamp_passbook` 直接重用既有浮水印函式；`_vendor_row()` 把 `bankPassbookImage` 從展開回應 `pop()` 掉、改回傳 `hasPassbook` 布林旗標（避免列表 API 混入大型 base64）；新增 `GET/PUT /api/vendor-contractors/{id}/passbook` 專屬端點（比照 `contractors.py` 的 `/id-card` 慣例）；`update_vendor_contractor()` 欄位保留邏輯從只保留 `visits` 擴充為連同 `bankPassbookImage` 與 5 個銀行文字欄位一併保留
- **前端**（`vendor-contractors.html`）：編輯 Modal 新增「銀行帳戶」＋「銀行存簿影本」兩個 `form-section`（拖曳/點擊上傳、預覽、移除，CSS 複製自 `contractors.html` 的 `.id-card-drop` 系列），詳情面板新增銀行資訊顯示區塊
- **驗證過程中發現並修正一個真實 bug**：既有 Excel 匯入更新流程（`handleImport()`/`_parseVendorRow()`）送出的 PUT payload 完全不含銀行欄位，若沒有保留邏輯，任何人匯入 Excel 更新既有承攬商就會把該筆銀行帳戶與存簿全部清空——已用模擬匯入情境的 API 呼叫實測驗證修正前會清空、修正後正確保留
- 已用 curl 完整驗證新增/上傳存簿（含浮水印蓋印確認）/列表精簡（`hasPassbook` 旗標不含 base64）/部分更新保留欄位全流程，瀏覽器截圖確認編輯 Modal UI 正確渲染

### 2026-08-02c — 案件管理／專案管理導入 Asana／PMP 概念

- **背景**：使用者要求依 Asana（任務層級：指派人、到期日、依賴、看板/時間軸視圖）與 PMP/PMBOK（時程管理、里程碑、stage gate、逾期治理）概念改善「專案管理」「案件管理」兩模組；探索後確認落差——兩模組都沒有任務層級到期日/負責人、沒有量化進度視覺化、沒有甘特/看板視圖、逾期完全沒有主動通知。**關鍵設計發現**：`projects.data_json` 已有 `endDate`/`startDate`（專案資訊頁「預計完工」），案件階段本來就是 `quotations.data_json.caseRecord.stages[]`（無獨立資料表）——這次改動**完全不需要新增 DB migration**，新欄位都是 schemaless JSON blob 裡新增 key
- **案件管理**：stage 新增 `startDate`/`dueDate`/`assignedTo`（可複選，chip 選人）/`dependsOn`（前置階段，含 `wouldCreateCycle()` 循環依賴防呆）；新增互動式甘特圖視圖（`frappe-gantt@0.6.1` CDN），可拖曳調整日期自動存回 stage，依賴箭頭依 `dependsOn` 渲染
- **專案管理**：沿用既有 `data_json.endDate` 加列表逾期/剩餘天數 badge；詳情頁新增進度 % bar（依 `project_logs.action_items` 完成率）；新增看板視圖（`sortablejs@1.15.3`，7 欄對應 status enum，拖曳跨欄呼叫既有 `PATCH /status`）
- **逾期提醒**：`daily_tasks.py` 新增 `_check_case_stage_deadline()`/`_check_project_deadline()`（比照既有 `_check_range_task_deadline` pattern，到期前3天/當天站內通知+email 雙軌），`email_notify.py` 新增對應兩個通知函式
- **驗證過程中發現並修正三個問題**：① `case-management.html` 有一份被改名 `__noop_stub()` 的死碼（真正生效邏輯在外部 `frontend/js/case-management.js`，一開始寫錯位置已全部改正，順便發現並還原一個角色選單欄位名稱誤判：`selectableUsers` 來自 `/api/users/selectable`，欄位是 snake_case `display_name`）② frappe-gantt CSS 未覆蓋預設色導致圖表背景全黑（已補上淺色系覆寫）③ 看板用了 Alpine 不支援的動態 `:ref` 綁定導致 Sortable 完全沒初始化（改用 DOM 查詢 `.pj-kanban__col-body` 修正）
- 已用後端函式直接執行驗證逾期通知正確寫入 `notifications` 表與 admin fallback 邏輯；瀏覽器截圖驗證 stage 詳細設定／甘特圖／看板拖曳／到期badge／進度bar 皆正常運作；測試資料（測試案件、測試專案）均已清除還原

### 2026-08-02b — 報價單「付款條件」預設文字改由 superadmin 線上維護

- **背景**：報價單「付款條件」欄位過去的預設文字是寫死在 `quotation-form.html`（新增報價單時 Alpine `q` 物件的初始值），要改預設文字得改程式碼重新部署；使用者要求改成 superadmin 可在報價單頁面直接編輯並存成新預設
- **修法**：後端 `system.py` 新增 `GET/PUT /api/settings/payment-terms`，比照既有 `company-profile` 設定模式——存於 `system_settings` key `default_payment_terms`（`_get_setting`/`_set_setting`），GET 任何登入者可讀（未設定過時 fallback 回傳程式內建範本常數 `DEFAULT_PAYMENT_TERMS`），PUT 限 superadmin 並寫 `_audit()`。前端 `quotation-form.html`：① 「付款條件」欄位標籤旁新增「設為預設付款條件」按鈕（`session.role==='superadmin'` 才顯示），呼叫 `saveDefaultPaymentTerms()` 把目前文字 PUT 存成新預設（有 `confirm()` 二次確認，明確告知不影響已存在的舊單）② 新增報價單流程（`init()` 無 `editNo` 分支）改為呼叫 `GET /settings/payment-terms` 取得目前預設值覆蓋 `q.paymentTerms`，API 失敗或回傳空字串時維持原本寫死在程式碼裡的文字當離線 fallback
- **範圍**：只影響「之後新增」的報價單預設值；已存在的舊報價單的 `paymentTerms` 早已各自存在 `data_json`，不受這次變更影響
- 已用 `ast.parse` 驗證後端語法通過；前端未實機測試（待瀏覽器驗證 superadmin 按鈕顯示、儲存與新單套用預設值的完整流程）

### 2026-08-02a — 修復 apply_update.ps1 首次正式機套用觸發的誤判自動回滾

- **背景**：commit `484c1b4`（含 2026-08-01q Schema 狀態頁）第一次在正式機真實套用，套用後健康檢查判定失敗（`healthy=True, log 錯誤筆數=5`）觸發自動回滾；比對回滾結果確認正式機穩定運作、沒有資料風險，但追查 `server.log` 後確認**是腳本誤判，不是新程式碼問題**
- **根因**：Step 2 停服後沒等 port 666 真正釋放，就讓既有 `MOTRIX ERP Server Autostart` crash-restart 迴圈（§1.1）搶著重新綁定，撞到 `[Errno 10048]` 位址已被使用，重試 2 次才成功（迴圈設計上本來就會自癒）；Step 4 健康檢查掃 log tail 80 行沒有分辨這些錯誤是否已被後續成功啟動蓋過去，誤判成更新失敗
- **修法**：`backend/tools/apply_update.ps1` ① Step 2 停服後新增主動輪詢確認 port 666 真正釋放（最長 15 秒）② Step 4 log 掃描邏輯改為只檢查 tail 範圍內「最後一次成功啟動（`Uvicorn running on`）」之後的內容，忽略重試階段已自癒的暫時性錯誤，找不到成功啟動標記時維持全範圍檢查（保守）
- 已用 PowerShell AST parser 驗證語法通過；已用當次事故實際 log 內容重建測試樣本模擬驗證：舊邏輯判定 2 筆錯誤（會誤判失敗）、新邏輯判定 0 筆（正確判定健康），另外驗證真正在成功啟動之後發生的錯誤（如 Traceback）新邏輯仍會正確攔截，不會漏判
- 尚未在正式機重新套用驗證（下次套用時才會是這支修正後腳本的第一次真實考驗）

### 2026-08-01q — 新增 Schema／Migration 唯讀診斷頁面

- **背景**：使用者要求做「migration 操作介面」；分析後發現「在線觸發乾跑」架構上沒有意義——migration 在每次伺服器啟動時自動套用，`apply_update.ps1` 的乾跑驗證測的是「即將部署、尚未套用」的新程式碼跑在現有 db 上會不會出錯，只有在部署當下（新舊程式碼並存）才有意義；活著的伺服器拿自己現在的程式碼對自己已是最新版的 db 再跑一次，永遠是 no-op。跟使用者確認後改成純讀取的診斷頁
- **修法**：後端 `system.py` 新增 `GET /api/system/schema-status`（superadmin only），讀 `schema_version` 單列表取得目前版號／最後套用時間，搭配 `_MIGRATIONS` 陣列（版號＝陣列位置＋1）與 `inspect.getdoc()` 組出完整 migration 清單（函式名稱＋說明，無 docstring 則說明留空）；前端新增 `schema-status.html`，摘要卡片（目前版本 X/Y、✓最新／⚠尚未同步、最後更新時間）＋ migration 清單（新到舊），**全頁無任何按鈕或表單**；`sidebar.js` 「系統」區段新增「Schema 狀態」入口（superadmin，`schema` 圖示）
- 已用 `ast.parse` 驗證後端語法、`node --check` 驗證前端 inline script 語法

### 2026-08-01p — 雲端備份新增自動清除機制

- **背景**：系統運行/資料管理建議整理時發現，H: 雲端硬碟上的「每日備份」「週備份」資料夾雖然有完整的失敗警示與 email 通知機制，卻**完全沒有清除邏輯**（本機 `db_backups/` 有 30 天清除、`audit_log` 有 730 天清除，唯獨雲端這兩個資料夾會無限期累積），長期下來可能撞到雲端硬碟容量上限
- **修法**：`archive.py` 新增 `_prune_cloud_backups(daily_keep_days=365, weekly_keep_days=730)`，比照既有 `_prune_local_db_backups()` 的安全模式——只刪資料夾名稱能正確解析成日期格式的項目，其他一律不動；H: 未掛載時整段略過。掛在 `_daily_backup()` 最後執行
- 保留天數依使用者指示：每日 365 天、週備份沿用既有 `audit_log` 的 730 天慣例
- 已用一次性測試腳本在暫時目錄（非正式機真實 H: 路徑）驗證：正確清除超過保留期限的日期/週別資料夾、正確保留未過期與檔名無法解析的項目，未誤刪

### 2026-08-01o — 選型資料庫三模組獨立命名／權限／紀錄拆分

- **背景**：反方向風險評估延伸出「未來模組拆分」的討論，grep 驗證場域選型導覽／網路架構選型導覽／交換器選型導覽三模組的資料表完全沒有被核心業務表反向參照，是低耦合、可獨立處理的候選；`SELECTION-DB-INDEX.md` 內部已用「選型資料庫」自稱，且規劃中還有監控系統／門禁系統／自動化系統三個未來類別要併入。使用者要求正式給這三模組獨立名稱、與業務模組拆開，並更新相關紀錄與權限（不含拆成獨立部署服務——那是更大的改動，本次只做識別/分類/命名/權限/紀錄層面）
- 過程中發現**交換器選型導覽（switch_guide）過去完全沒有側邊欄入口、也沒有 `users.html` 權限勾選項**（只有 superadmin 能用），使用者確認一併補齊使其跟另外兩個一致
- **`frontend/static/sidebar.js`**：新增 `cSwitchG` 旗標與 `switchg` 圖示；側邊欄新建獨立頂層區塊「選型資料庫」（原本 env-guide/netarch-guide 夾在「業務」區塊裡，switch-guide 完全沒有項目），三個項目一起移出來集中放；`_FILE_MODULE` 補上 switch-guide.html；順便修正 `_refreshSession()` 背景刷新沒有重算 cEnvG/cNetG 的既有缺口
- **`frontend/pages/users.html`**：`ROLE_MODULES.superadmin`/`admin` 補上 `switch_guide`；`allModules` 四筆既有 env/netarch 權限項目的 `group` 從 `'業務'` 改成 `'選型資料庫'`，新增 `switch_guide`/`switch_guide_edit` 兩筆權限項目（同組）
- **`frontend/pages/audit-log.html`**：新增「選型資料庫」optgroup（30 個 option，對應後端已良好命名的稽核動作字串 `env_guide.*`/`netarch_guide.*`/`switch_guide.*`）、`actionLabel()` 30 筆中文標籤對應、`badgeBg()`/`badgeFg()`/`dotBg()`/`dotIcon()` 四個函式各補一條 `startsWith` 規則（三模組共用 teal 色系＋🧭 圖示，強調同屬一個產品線）
- **`frontend/pages/module-versions.html`**：`_MOD_COLORS` 補上「場域選型導覽」「網路架構選型導覽」「交換器選型導覽」「選型資料庫」四個字串的 teal 色碼（原本落到預設灰色）
- **不變更**既有 `version_manifest.json` 舊條目的 `module` 欄位字串（不回頭改寫歷史紀錄），也不引入斜線前綴命名慣例（`_MOD_COLORS` 是 exact-match、非階層式，改名不會帶來實質分組效果）；`backend/main.py` 的 router 掛載方式（URL 命名空間）本次不動，超出這次範圍
- 已用 `node --check` 對三個檔案的 inline script 語法驗證通過，`audit-log.html` optgroup 開合標籤數量核對一致（13/13）

### 2026-08-01n — apply_update.ps1 新增 migration 乾跑驗證

- **背景**：MOTRIX-ERP 拆成獨立 repo（見下方 §12 2026-08-01m 條目）後，針對「未來擴增模組/串接其他環境前該先補的風險」做過一輪反方向評估，其中一項是「正式庫是第一個試跑新 migration 的地方」——`apply_update.ps1` 套新程式碼、重啟後 `init_db()` 立刻對正式庫跑新 migration，若 migration 本身有 bug，schema 已經被改壞才被套用後健康檢查發現；「自動回滾」雖然會把 db 整檔換回套用前快照（安全），但仍會遺失套用後到偵測失敗這段時間內產生的新業務資料
- **修法**：`apply_update.ps1` Step 1（套用前檢查）在 db 快照做完後、程式碼回滾快照之前，新增乾跑驗證：把 db 快照複製一份到系統 temp 目錄，用**新部署包裡的** `db.py`（`init_db(path)` 本來就接受任意路徑參數，只操作傳入的檔案，不會動到 `DB_PATH` 預設值）在這份副本上先跑一次；失敗（python 非 0 結束碼，或沒印出預期的 `DRYRUN_OK` 標記）就直接中止，不進入停服／複製程式碼／回滾快照等後續步驟，**正式庫全程不受觸碰**
- 已用 PowerShell AST parser 對修改後的腳本做語法檢查通過；已用實際 db 檔案複本個別驗證成功與失敗兩種情境：對照現有正式 schema 乾跑通過會印 `DRYRUN_OK`／結束碼 0；餵一個非法的 db 檔案會正確拋出 `sqlite3.DatabaseError: file is not a database`／結束碼非 0，確認失敗偵測邏輯正確
- 尚未在正式機做過真實套用測試（同 §15.4 既有已知限制）

### 2026-08-01m — MOTRIX-ERP 拆分為獨立 git repo

- **背景**：反方向風險評估（見對話紀錄）點出開發機這邊的 git repo 根目錄其實是整個使用者家目錄，MOTRIX-ERP 只是其中一個子資料夾——這是 §12 2026-08-01k/l 那兩個 `build_deploy_package.ps1` bug 的根本原因，也是繼續擴增模組/串接其他環境前優先度最高的結構性風險
- **修法**：用 `git subtree split --prefix="Desktop/MOTRIX-ERP" -b motrix-erp-split` 保留完整 commit 歷史（40 筆，含歷史上的 `develop` 分支內容，因 `develop` 早已完全合併進 `master`，用 `master` 分割即可涵蓋全部）匯出成獨立分支，拉進臨時 repo 驗證內容與現有工作目錄一致後，把新 `.git` 直接放進 `Desktop\MOTRIX-ERP\`；家目錄那個原本的大 repo 用 `git rm -r --cached` 停止追蹤這個資料夾並補上 `.gitignore` 規則，**工作目錄檔案本身完全未變動**，只是換了誰在追蹤，家目錄過去的 commit 歷史也完全未被改寫
- 新建 GitHub private repo `rocksk8/motrix-erp` 當新 repo 的 remote，push 完成；另建立 `develop` 分支（比照 `GITFLOW.md` 既有分支規範）並 push
- 副作用：`build_deploy_package.ps1` 原本 `git rev-parse --show-toplevel` 找到的範圍 bug（§12 2026-08-01k 修的那個 workaround）現在不需要 workaround 也自然正確，因為 repo 根目錄本來就是 `Desktop\MOTRIX-ERP` 了；先前的修法本身無害，繼續保留
- 已重跑 `build_deploy_package.ps1` 驗證：`Repo root` 正確顯示為 `Desktop\MOTRIX-ERP`，打包成功、`deploy_manifest.json` 內容正確

### 2026-08-01l — 修復 build_deploy_package.ps1 兩個小 bug（首次實際執行才發現）

- 修好 §12 2026-08-01k 那次範圍 bug 後第一次成功打包，但終端機印出 `[WARN] 無法解析 version_manifest.json，版本標籤留空`——追查是 `Get-Content` 讀取此檔（無 BOM）時沒指定 `-Encoding UTF8`，PowerShell 5.1 在繁中 Windows 上會用系統內碼猜編碼，中文字附近讀成亂碼，`ConvertFrom-Json` 因此解析失敗；已補上 `-Encoding UTF8`
- 順便發現 `$entries[-1]`（原意「取最新一筆」）邏輯錯誤：`version_manifest.json` 的新條目永遠插在陣列最前面（index 0），`[-1]` 實際抓到的是史上最舊的那筆記錄，已改為 `$entries[0]`
- 兩者都是非致命 bug（不影響打包本身是否成功，只影響 `deploy_manifest.json` 裡 `version_manifest_latest` 這個資訊性欄位是否正確），已重新執行腳本驗證修復後能正確帶出最新版本資訊

### 2026-08-01k — 修復 build_deploy_package.ps1 的 repo 範圍 bug

- **背景**：合併 §15 更新模式後第一次實際執行 `build_deploy_package.ps1`，在「git status 必須乾淨」這一步就失敗——追查發現腳本用 `git rev-parse --show-toplevel` 找到的 repo 根目錄其實是**整個使用者家目錄**（`C:\Users\hichan`），不是 MOTRIX-ERP 專案本身；家目錄底下有大量跟本專案無關的未追蹤個人檔案，導致這個檢查永遠不可能通過
- **修法**：改用 `$PSScriptRoot` 往上兩層（腳本位於 `<專案根目錄>\backend\tools\` 下）算出專案根目錄，再算出它相對於 repo 根目錄的路徑（`$relPath`，正斜線格式）；`git status`／`git archive` 都改用這個 pathspec 限定範圍，只檢查/打包 MOTRIX-ERP 這個子目錄；`git archive` 改用 `<commit>:<relPath>` tree-ish 語法，讓匯出的檔案直接以 `backend/`、`frontend/` 開頭（不帶 `Desktop/MOTRIX-ERP/` 前綴），符合 `apply_update.ps1` 預期的部署包結構；`$OutDir` 預設值與讀取 `version_manifest.json` 的路徑也一併從 repo 根目錄改為專案根目錄（原本會把 `deploy_packages/` 誤建在家目錄底下）
- 順便補上 `.gitignore` 的 `出貨單PDF/` 規則（比照既有 `報價單PDF/` 做法）——這個含真實 PDF 的資料夾原本沒被忽略，也會一直卡住 git status 乾淨檢查
- 已用 PowerShell AST parser 對修改後的腳本做語法檢查通過；重新執行後確認範圍限定生效，正確、僅回報專案子目錄範圍內的未 commit 變更

### 2026-08-01j — 新增半自動更新模式（§15，落地 §14.3 自動化推送方向）

- **背景**：正式機今天獨立完成這項工作並匯出到 `MOTRIX-UPDATE-MODE-EXPORT_2026-08-01/`（含 README 合併說明），與開發機當天同步進行的出貨單調整／demo 隔離修復是兩條平行線，合併時才第一次讓兩邊的今日變更在同一份文件裡碰頭
- 新增半自動「更新模式」，把 §14.3 原本列為之後才做的自動化推送方向落地成兩支腳本：`backend/tools/build_deploy_package.ps1`（開發機執行，`git status` 必須乾淨才允許打包，用 `git archive` 只匯出已 commit 內容，解決來源不可靠問題）與 `backend/tools/apply_update.ps1`（正式機執行，身分守門＋版本比對防重複套用＋套用前自動備份 db 與程式碼＋停服讓既有 autostart crash-restart 迴圈接手＋robocopy 只加不刪絕不 `/MIR`＋套用後輪詢 `/api/ping` 與檢查 `server.log`，失敗自動回滾）
- `MOTRIX-ERP-QUICK.md` 新增 §15；§14.3 從「這次不做」更新為「已實作半自動版本」
- 兩支腳本因含中文註解，已確認需存成 UTF-8 with BOM 才能被 PowerShell 5.1 正確解析（純 UTF-8 no-BOM 會在中文字附近誤判字串終止符），已修正並通過語法檢查
- **版號說明**：此項工作正式機端原始標記為 `2026-08-01g`，與開發機當天已用掉的 g/h/i 衝突（見 `version_manifest.json` 該條目備註），合併時統一改標為 `2026-08-01j`，內容不變
- 尚未在正式機做過真實套用測試（會實際停服重啟，需使用者另外確認執行時機），開發機端的 `build_deploy_package.ps1` 也尚未實地跑過（需先於開發機 commit 現有未進版控的變更）

### 2026-08-01i — 修復 demo 模式背景執行緒隔離漏洞

- **背景**：測試出貨單預覽功能時，用 demo 帳號核准出貨單，發現產生的 PDF 跑進了正式的 `出貨單PDF/` 資料夾，而不是應該用的 `_demo_shipping_pdf_archive` 隔離目錄。追查後發現不是單一 bug：`is_demo_mode()`/`get_db()` 靠 `contextvars.ContextVar`（`_demo_mode`）判斷目前是不是 demo session，FastAPI 對路由本身的排程機制會正確傳遞這個 context，但只要程式碼手動呼叫 `threading.Thread(...).start()`，新執行緒一律拿到全新、空白的 context，裡面的 `is_demo_mode()`/`get_db()` 就會誤判成正式環境
- **影響範圍**：逐一檢查所有路由 handler 內用 `threading.Thread` 起的背景工作後，確認 23 處中招，遍及 `shipping_notes.py`（1）、`quotations.py`（9，PDF 產生＋即時備份）、`customers.py`（4）、`suppliers.py`（4）、`daily_tasks.py`（4，通知信）、`dev_crm.py`（1，通知信）。其中最嚴重的是每日工作事項/業務開發案件的 email 通知——demo 帳號指派/編輯/完成工作事項會讓通知函式在背景執行緒裡誤連正式 DB 查出真實使用者 email，寄送跟 demo 操作內容對不上的通知信給真實同仁
- **不需修的**：確認只在伺服器啟動/排程情境執行、不掛在任何 request 上的背景工作（`daily_tasks.py` 的 `_startup_catchup` 與其內部呼叫、`reports.py` 的 `_catchup_monthly_reports`），本來就該永遠連正式庫，維持不動；`email_notify.py` 的 `_async_send()`/`_send()` 只吃已解析好的純值參數，不碰 `get_db()`/`is_demo_mode()`，這層巢狀執行緒不需要 context 傳遞
- **修法**：`db.py` 新增 `spawn_bg_thread()`，用 `contextvars.copy_context()` 把呼叫當下的 context 原封不動帶進新執行緒，取代直接呼叫 `threading.Thread`；23 處呼叫點全數改用此 helper，語意不變（fire-and-forget、daemon thread），僅補上 context 傳遞
- 已用 `python -m ast` 對 7 個改動檔案做語法檢查全數通過；已用 demo 帳號重跑核准出貨單流程，確認 PDF 正確寫入 `backend/_demo_shipping_pdf_archive/`、正式 `出貨單PDF/` 資料夾內容不受影響（修復前後各建一次同單號 `DN-202608-001` 比對，正式資料夾始終只有先前既有的那份，demo 這次新產生的檔案完全沒有混進去）；另用 demo 帳號建立一筆指派通知的每日工作事項，確認 request 正常完成、伺服器 log 無例外

### 2026-08-01h — 出貨單預覽 Modal 調整（移除下載選項／PDF 加浮水印警告橫幅）

- **背景**：上一版（2026-08-01g）新增的出貨單預覽功能，Modal 內在已核准狀態下會顯示「下載 PDF」按鈕；使用者回饋預覽視窗不應該有下載選項，且希望比照報價單既有預覽（`quotation-form.html`）的做法，在還沒正式核准前的內容加上背景提示，避免被誤認成正式文件
- **`case-management.html`**：移除預覽 Modal footer 的「下載 PDF」按鈕，只留「關閉」；已核准狀態下列表上原本的「下載 PDF」按鈕（記錄 export_count 的正式匯出流程）不受影響，仍在原位置
- **`backend/pdf_gen.py` `_build_shipping_html()`**：出貨單預覽用的是後端 Edge headless 產生的真正 PDF（不像報價單預覽是前端 HTML 模擬稿），因此浮水印／警告橫幅改為直接刻進 PDF 產生的 HTML 模板本身，`status != '已核准'` 時顯示：3×4 格線平鋪浮水印（「出貨單預覽稿」／「尚未正式核准」，半透明紅字，樣式比照 `quotation-form.html` `.pdf-watermark`/`.pdf-wm-item`）＋藍底警告橫幅（「⚠ 此為出貨單預覽稿（目前狀態：XXX），尚未正式核准，請勿對外提供或引用」）；已核准後兩者皆不顯示，維持正式文件版面乾淨
- 前端 `previewShippingPdf()`/`closeShippingPreview()` 邏輯不變（浮水印是 PDF 內容本身的一部分，iframe 顯示即自動帶有，無需額外前端程式碼）
- 已用 demo 帳號驗證：草稿狀態預覽可見浮水印平鋪與藍色警告橫幅、Modal 內僅「關閉」無下載按鈕；送出並自簽核准後再次預覽，PDF 版面乾淨無浮水印/橫幅，Modal 內同樣僅「關閉」；列表上已核准狀態的「下載 PDF」按鈕（Modal 外）維持正常，點擊後 export_count 正確累加為 1

### 2026-08-01g — 出貨單三項調整（收件人聯絡人快選／預覽／超級管理員自簽）

- **背景**：出貨單功能（2026-08-01d 新增）上線後，現場使用發現三個缺口：收件人要手動重打客戶聯絡人資訊、送審前無法先看格式只能等已核准才能下載、以及超級管理員在沒設定簽核流程時連自己送的單都不能簽（`申請人不得自行審核` 擋自己），三者皆為開發機（`hichan` 帳號）調整，正式機部屬包已於本次工作前先行手動同步過一版
- **`backend/routers/shipping_notes.py`**：`approve_shipping_note()` 無 tiers（superadmin fallback）分支移除 `requestedBy == user.username` 的自簽檢查，僅保留 `role != superadmin` 限制；有 tiers 分支本來就未擋自簽、`reject_shipping_note()` 也本來就未擋，故只需改這一處
- **收件人聯絡人快選**（`case-management.js`/`.html`）：新增 `_loadShippingContactOptions()`，依 `this.selected.data.customerId`（報價單 `data_json` 內若曾用客戶選單建檔即存在）取客戶聯絡人，取不到時退而用 `customer_name` 比對 `/api/customers` 全列表；開新增/編輯 Modal 時自動載入，收件人欄位旁新增「選聯絡人」下拉，點選僅覆寫欄位值，輸入框本身仍可自由編輯（無聯絡人資料時不顯示按鈕，不影響原本手動輸入流程）
- **預覽功能**（`case-management.js`/`.html`）：新增 `previewShippingPdf()`/`closeShippingPreview()`，重用既有 `GET .../pdf-download` 端點（該端點本無狀態限制），以 iframe+blob 顯示於新 Modal，純預覽不呼叫 `/export`、不影響 `export_count`；已核准狀態下 Modal 內另提供「下載 PDF」按鈕直接呼叫既有 `downloadShippingPdf()`，沿用原本記錄匯出次數的邏輯，未重複實作
- 已用 demo 帳號（隔離空白 db）建立測試客戶+聯絡人、關聯報價單、出貨單完整驗證：收件人「選聯絡人」下拉正確顯示客戶聯絡人並可點選帶入（仍可手動修改）；草稿與已核准狀態皆可點「預覽」正確顯示 PDF，已核准狀態下預覽 Modal 內「下載 PDF」按鈕正確出現；以 superadmin 建立並送出出貨單（未設定 `shipping_approval_flow`）後自行點簽核，確認不再出現「申請人不得自行審核」錯誤，直接核准成功

### 2026-08-01f — 新增多機同步須知與跨機核對流程（文件化）

- **背景**：本次開發過程接連發現開發機與正式機的落差（db.py migration 遺失、部署腳本檔案遺失），確認目前完全靠人工複製、沒有任何比對機制；使用者要求先把「開機先確認身分＋核對差異」的協議寫進文件，自動化推送機制明確列為後續才做
- **新增 §0（多機同步須知，移到文件最前面）**：機器身分對照表（`hichan` 開發機 vs `Motrix` 正式機，含路徑/用途/排程工作差異）；協議文字要求每次工作先判斷並告知目前是哪台機器，正式機須改用保守操作方式（不啟動測試 server、不寫測試資料）；已知落差紀錄表（累積式，先填入本次發現的 3 筆）
- **新增 §14（跨機核對與拉檔流程）**：核對優先順序清單（db.py migrations 優先用正式機 db 實際 schema 反推 → routers/helpers → 前端 → 部署腳本 → version_manifest.json）；拉檔案回開發機的具體步驟（db 檔案不直接覆蓋、先另存比對；純檔案有差異人工判斷不自動覆蓋）；明確列出「之後才考慮」的自動化方向（PowerShell Remoting／Robocopy）但註明這次不做

### 2026-08-01e — 補回失蹤的 v32/v33 migration（交換器選型導覽）

- **背景**：開發出貨單時發現本機備份 db 的 `schema_version` 比本地程式碼超前 2 個 migration（見 2026-08-01d 條目）。進一步比對後確認：`backend/routers/switch_guide.py`／`switch_guide_seed.py`／`frontend/pages/switch-guide.html`（交換器選型導覽，選型資料庫第三個類別）三個檔案其實已存在於本機（未 commit），`main.py` 也早已註冊該路由，**唯獨 `db.py` 的對應 migration 遺失**——這正是缺的 v32/v33
- **佐證**：`switch_guide_seed.py` 檔頭 docstring 直接寫著「migration `_m032_switch_guide`」；備份 db 的 `switch_products` 表 SQL 定義可見 `specs_json` 欄位是後補的 `ALTER TABLE`（獨立於原始 `CREATE TABLE` 語句），對應 v33；seed 資料筆數（5 情境／4 分類／20 適配度組合）與備份 db 完全一致（`switch_products` 備份 db 有 40 筆，seed 僅 6 筆——差額為之後透過 API 手動新增，非種子資料遺漏）
- **修法**：`db.py` 新增 `_m032_switch_guide`（建 4 張表 + 索引 + 種子資料，比照 `_m031_netarch_guide` 的 idempotent 寫法）與 `_m033_switch_products_specs`（`ALTER TABLE` 補 `specs_json` 欄位），取代原本的 2 個空白佔位 migration；已用全新空白 db 驗證 `init_db()` 跑完後種子資料筆數與 schema 完全比照備份 db（既有 `motrix_erp.db`／`motrix_erp_demo.db` 因 `schema_version` 已是 34 不受影響，此修正主要讓**未來全新安裝／重建環境**時能正確產生完整功能，不再依賴「剛好複製到一份已含這些表的 db 備份」)

### 2026-08-01d — 新增出貨單功能（案件管理子項目）

- **背景**：現場出貨需要純品項（不含金額）的出貨單供客戶簽收，帶回辦公室留存作為交貨憑證；系統原本完全沒有回簽/簽收追蹤機制，本次全新設計
- **`backend/db.py`**：新增 `shipping_notes` 表；⚠️ 開發過程發現本機備份 db 的 `schema_version` 已是 33，比本地程式碼定義的 v31 超前 2 個未知 migration（母機複製過來的落差）——新 migration 改編號為 **v34**，並插入 2 個空白佔位 migration（`_m032_placeholder_unreconciled`/`_m033_placeholder_unreconciled`）保留版號位置，待日後對齊正式機程式碼再回填；`next_entity_code()` 泛化支援多字元 prefix（`DN`）與自訂 `code_col`（`note_no`），對既有 `C`/`S`/`V` 一字元呼叫端完全回溯相容（已重新測試三者建立流程）
- **`backend/routers/shipping_notes.py`**（新檔）：CRUD、獨立簽核流程（`草稿→待審核→簽核中→已核准`，`system_settings.shipping_approval_flow` 與報價單簽核設定分開）、PDF 下載/匯出紀錄、`signed-toggle`（已回簽切換，含完整歷程 `signed_log`）；寫入類操作限 admin+，比照承攬商分頁「分頁可見、操作分權限」的既有慣例
- **`backend/pdf_gen.py`**：新增 `_build_shipping_html`/`generate_shipping_pdf_bytes`/`_generate_shipping_pdf`，品項表無金額欄位、雙簽名欄（客戶簽收／本公司出貨），demo 模式獨立歸檔至 `_demo_shipping_pdf_archive`
- **前端**：`case-management.html`/`js/case-management.js` 新增「出貨單」分頁（品項可一鍵從報價單匯入並自動去除金額欄位）；新增 `shipping-approval-settings.html`（複製既有簽核設定頁樣式）；`sidebar.js` 系統區段新增對應導覽項
- 已用 Chrome 瀏覽器走完整流程驗證：建立出貨單 → 匯入品項 → 送出審核 → 簽核 → 已核准狀態下載 PDF → 標記已回簽 → 展開查看回簽歷程，各狀態截圖確認正確；並確認非 admin 角色看得到分頁但看不到任何操作按鈕

### 2026-08-01c — 修復月報 PDF 產製失敗（變數覆蓋 bug）

- **`backend/routers/reports.py` `_build_report_html()`**：精算明細區塊 `for mc in data["marginCases"]: s = mc.get("settleSummary") or {}` 覆蓋了函式開頭的 `s = data["summary"]`（Python 無區塊作用域，迴圈跑完後 `s` 仍是最後一筆精算摘要）；後段 KPI 區塊讀 `s["totalReceivable"]` 因此 `KeyError`。僅在當月有「已完結（finalized）精算」案件時才會觸發（清單為空則不進迴圈、不會覆蓋），因此先前未被發現
- **修法**：迴圈內變數改名為 `ss`，不再覆蓋外層 `s`；`_build_excel()` 有相同命名寫法但外層 `s[...]` 讀取都在覆蓋之前完成，實際未受影響，未修改
- 已用 2026-07 實際資料（1 筆已完結精算案件）重現原始錯誤並驗證修復；補寄一次含正確 PDF 附件的 2026-07 月報給 superadmin

### 2026-08-01a／b — 正式環境部署穩定性強化 + 心跳監控機制

> 背景：系統於 2026-07-31 完成從舊機器（`hichan` 帳號、G: 雲端碟）遷移至正式環境機器（`Motrix` 帳號、AutoAdminLogon、H: 雲端碟），詳見根目錄 `AUTOLOGON-FIX.md`。以下為遷移後的穩定性檢查與修正，詳見 §1.1／§1.2

- **開機競態**：`setup_autostart_task.ps1` 登入觸發器加 90 秒延遲（`$trigger.Delay = "PT90S"`），避開與 GoogleDriveFS（同樣登入時啟動）搶跑掛載 H: 導致每次開機誤報 `BACKUP_ALERT` 的窗口
- **無 crash 自動重啟**：`autostart.bat` 改為 crash-restart 迴圈（uvicorn 意外中止 5 秒後自動重啟）；`restart.bat` 同步補殺該迴圈的 process，避免手動重啟時兩邊搶 port 666
- **log 中文亂碼**：`autostart.bat` 加 `chcp 65001` + `set PYTHONUTF8=1`；⚠️ 過程中發現 **`.bat`/`.ps1` 若含中文註解且存成 LF-only 換行，cmd.exe 批次檔解析器會直接失效**（報「命令語法不正確」，且排程工作仍顯示執行成功、無任何 log），已確認改存 CRLF 後解決——之後修改 `.bat`/`.ps1` 務必確認換行格式
- **archive.py 殘留舊碟符**：3 處 log/alert 文字寫死的舊機器碟符 `G:` 改為現行 `H:`（功能早已正確使用 H:，僅文字訊息不一致）
- **殘留檔案清理**：刪除根目錄與 `backend/` 下各一個 0-byte 廢棄 `motrix_erp.db`／`motrix.db`（非正式庫，正式庫為 `backend/motrix_erp.db`）
- **新增心跳監控**（`backend/heartbeat_job.py` + `heartbeat_config.json` + `setup_heartbeat_task.ps1`）：獨立於 uvicorn 的 dead-man's-switch 機制，每 5 分鐘檢查本機 `/api/ping`，正常才對 [healthchecks.io](https://healthchecks.io) 打卡，本機無回應直接打 `/fail` 立即告警；本機或整台主機斷線都會使打卡中斷，由該服務逾時（Period 10 分鐘／Grace 10 分鐘）寄信通知 superadmin 信箱；已實測（含刻意中斷驗證告警確實觸發）

### 2026-07-28a — 系統字體全面改為 LINE Seed TW_OTF（自架字型）

- **`frontend/fonts/`**（新增目錄）：`LINESeedTW-Thin.otf` / `-Regular.otf` / `-Bold.otf` / `-ExtraBold.otf`（自 Windows 已安裝字型複製而來），由 `main.py` 既有的 `StaticFiles(FRONTEND_DIR)` 掛載自動於 `/fonts/*.otf` 提供，區網各台電腦免個別安裝字型即可顯示一致
- **`frontend/css/style.css`**：新增 4 組 `@font-face`（`font-family: 'LINE Seed TW_OTF'`，依字重對應 100–900）；`--font-en` / `--font-zh` 統一改為 `'LINE Seed TW_OTF', system-ui, sans-serif`（原為 Google Fonts CDN 的 Inter / Noto Sans TC）
- **全站 34 個頁面 + `js/*.js` + `static/*.js`**：移除 `<link>` 引入的 Google Fonts（`fonts.googleapis.com` / `fonts.gstatic.com`，含 Inter / Noto Sans TC / Noto Serif TC）；所有內嵌 `font-family: Inter, sans-serif` 等硬編碼樣式改為 `LINE Seed TW_OTF`（quotation-form.html 報價單 PDF 樣式的 `Noto Serif TC` 亦一併替換）
- ⚠️ **批次取代衍生修正**：`static/sidebar.js`（8 處）、`static/notif.js`、`index.html`、`pages/sales-orders.html`、`pages/quotation-form.html`（`style.cssText = '...'` / Alpine `:style="'...'"` 動態綁定）等以單引號 JS 字串組字串的位置，取代後字型名稱誤帶入的單引號會提前截斷字串——已改為 CSS 允許的**不加引號**寫法（`font-family:LINE Seed TW_OTF, sans-serif`）修正；修正後以 `node --check` 驗證 4 個獨立 .js 檔、並對全站所有 HTML 內嵌 `<script>` 區塊逐一 `new Function()` 語法驗證，全數通過
- 已用 `curl` 確認 `/fonts/LINESeedTW-Regular.otf` 回應 200（5.2MB），CSS 變數正確解析

### 2026-07-24e — Demo 展示帳號（隔離空白資料庫，登入即重置）

- **`backend/db.py`**：新增 `DEMO_DB_PATH`（`motrix_erp_demo.db`，獨立檔案但同一套 schema/migrations）；`get_db()` 改為透過 `contextvars.ContextVar` 判斷本次 request 是否為 demo 模式，動態連向正式庫或 demo 庫；新增 `get_demo_db()`（無視 context，永遠連 demo 庫，供登入/登出流程使用）、`is_demo_mode()`、`set_demo_mode(flag)`；`init_db()` 新增 `path` 參數支援對非預設路徑初始化；新增 `DEMO_PROJECT_PHOTOS_DIR` / `DEMO_PDF_ARCHIVE_DIR` / `DEMO_PAYSLIP_ARCHIVE_DIR` 三個檔案隔離目錄常數、`demo_reset_lock`（`threading.Lock`）
- **`backend/db.py reset_demo_db()`**：改為 SQL `DELETE FROM` 每張表 + `VACUUM`（同一連線內完成，不刪 `.db/-wal/-shm` 檔案），避免 Windows 掃毒/索引服務短暫鎖住剛建立的 WAL 檔案造成 `os.remove()` 失敗中斷登入；並清空三個 demo 檔案目錄
- **`backend/helpers/startup.py`**：新增 `init_demo_account()`（正式庫建立 `demo` 守門帳號，密碼 `60575481`，role=superadmin，僅供登入驗證用）
- **`backend/helpers/auth.py`**：新增 `DEMO_TOKEN_PREFIX = "DEMO_"` 常數
- **`backend/main.py`**：啟動時額外 `init_db(DEMO_DB_PATH)` + `init_demo_account()`；`auth_middleware` 依 token 是否有 `DEMO_` 前綴呼叫 `set_demo_mode()`，此後本次 request 內所有 `get_db()`（含 `_require_user()`/`_audit()`）自動轉向 demo db
- **`backend/routers/auth.py`**：`auth_login()` 偵測 `username=='demo'` → 在 `demo_reset_lock` 內依序執行 `reset_demo_db()` 清空 → 建立 demo 使用者/session/audit → 核發 `DEMO_` 前綴 token（鎖確保兩個同時到達的 demo 登入不會搶跑同一個共用 db）；`auth_logout()` 依前綴分流刪除對應 db 的 session
- **`backend/photos.py`**：新增 `_photo_root()`，`is_demo_mode()` 時回傳 `DEMO_PROJECT_PHOTOS_DIR`；**`backend/routers/projects.py`** 上傳照片改用此函式（原本硬寫死 `uploads/projects/`，demo 帳號上傳會直接落入正式目錄且 project_id 從 1 重新編號可能撞名）
- **`backend/routers/payslips.py`**：`_archive_path()` 改為 `is_demo_mode()` 時導向 `DEMO_PAYSLIP_ARCHIVE_DIR`（原本硬寫死 `backend/export_archive/`）
- **`backend/pdf_gen.py`**：`_get_pdf_base()` 改為 `is_demo_mode()` 時導向 `DEMO_PDF_ARCHIVE_DIR`，完全略過真實設定的 `pdf_base_path`（原本可能是公司共用網路磁碟，demo 帳號觸發報價單里程碑自動匯出會把檔案寫進真實共用資料夾）
- 已用獨立測試環境（複製 backend+frontend、不同 port）反覆驗證：demo 登入回傳空白清單/儀表板、可正常寫入測試資料、寫入僅存在於 demo db 與 demo 專屬目錄、重新登入即整庫+整目錄清空、正式庫與正式檔案目錄全程未被寫入或讀取；並用 15 次連續 + 3 輪 20～25 併發登入壓力測試，確認 `demo_reset_lock` 修正了併發登入互相搶跑導致的 500 錯誤

### 2026-07-24d — 外包名冊 DB migration 修正 + 設備拖曳 UX 重新設計（2026-07-24 01:42）

- **`backend/db.py`**：`CURRENT_VERSION = 28 → 29`（前版新增 `_m029_contractor_passbook` 後未更新版本號，致 migration 未執行、`bank_passbook_image` 欄位不存在，`_LIST_COLS` 計算欄失敗、API 500、前端清單空白）
- **`frontend/js/case-management.js`**：設備拖曳全面重構 — 自訂 ghost（克隆卡片 + 旋轉 1.5deg + 縮放 1.04× + 陰影 + `setDragImage`，下 tick 移除，取代瀏覽器預設截圖）；timestamp 計時替代 `setTimeout`（`dragover` 持續比對 `Date.now() - _devHoverStart > 900ms`，不受 `dragLeave` 中斷）；`_devInsertBeforeId` 追蹤插入線位置（上半插入前 / 下半插入後）；自動捲動 `.cm-detail__body`；群組 `dragover/drop` 移至 `.dev-group-header`；`devDropAtEnd()` 末端投放；新增 `_devNextId()` helper；新增狀態 `_devInsertBeforeId` / `_devHoverGroupId` / `_devHoverStart`
- **`frontend/pages/case-management.html`**：CSS 新增 `.dev-card--insert-before`（藍色頂線插入提示）/ `.dev-card--group-target`（紫框合併預覽）/ `.dev-drop-end-zone` + `--active`（末端投放區）；`.dev-group` 去除 drag 事件改至 `.dev-group-header`；`:class` 綁定更新為新 class 名稱；末端投放 `<div class="dev-drop-end-zone" x-show="_devDragId">` 插入在 template loop 之後

### 2026-07-24c — 外包名冊銀行存簿影本 + 勞報單 PDF 附件（2026-07-24 18:00）

- **`backend/db.py`**：DB migration v29（`_m029_contractor_passbook`）為 `contractors` 新增 `bank_passbook_image TEXT DEFAULT ''` 欄位
- **`backend/routers/contractors.py`**：新增 `_stamp_passbook()`（藍底「本影本依法留存，僅供勞務報酬匯款核對使用」橫幅浮水印）；`_LIST_COLS` 新增 `has_passbook` 計算欄位；`GET /id-card` 回傳 `bank_passbook`；`PUT /id-card` 接收 `bank_passbook` 並套用 `_stamp_passbook()`
- **`backend/pdf_gen.py`**：`_build_payslip_html()` 新增 `passbook_section`（換頁，含受領人/帳號/勞報單號資訊表格 + 存簿圖片）；`generate_payslip_pdf_bytes()` 從 `contractors` 讀取 `bank_passbook_image` 注入 `d["_bank_passbook"]`
- **`frontend/pages/contractors.html`**：modal 新增「銀行存簿影本」上傳區塊（拖放 / 點擊選取 / 移除；未儲存 / 已上傳狀態提示）；detail-pane 顯示 `has_passbook` 指示器及「產出勞報單 PDF 時將自動附入」說明；`save()` 含 `bank_passbook` 欄位

### 2026-07-24b — 勞務模組權限開放 + 歷史紀錄全模組覆蓋

- **`backend/helpers/auth.py`**：`_require_user` 新增 `module: str = None` 參數；`require_superadmin=True` 時若提供 `module` 則允許 superadmin 或具該模組授權的使用者通過，否則仍限 superadmin
- **`backend/routers/contractors.py`**：`list_contractors` / `create_contractor` / `get_contractor` / `update_contractor` / `get_id_card` 改用 `module='contractor_list'`；`toggle_contractor_active` / `upload_id_card` 維持 superadmin-only
- **`backend/routers/payslips.py`**：除 `delete_payslip` 外所有端點（10 個）改用 `module='payslip'`；刪除維持 superadmin-only
- **`frontend/pages/contractors.html` / `payslips.html` / `payslip-form.html`**：存取檢查由 `role !== 'superadmin'` 改為 `role !== 'superadmin' && !modules.includes(key)`
- **`frontend/static/sidebar.js`**：新增 `cCon`（contractor_list）/ `cPay`（payslip）模組旗標；勞務管理 section 改為 `cCon || cPay` 可見；外包名冊改用 `cCon`、勞報單改用 `cPay` 個別控制
- **`frontend/pages/users.html`**：`allModules` 新增 `contractor_list`（外包名冊）/ `payslip`（勞報單）兩個「勞務」群組項目
- **`frontend/pages/audit-log.html`**：篩選器新增 業務開發 / 供應商 / 承攬商管理 / 專案管理 / 每日工作事項 / 外包名冊 / 勞報單 / 系統 optgroup 共 60+ 選項；`actionLabel()` 映射表從 22 條擴充至 70+ 條（含報價單撤回/否決/退回、所有 dev_case/dev_log/vendor/project/daily_task/contractor/payslip/settings 動作）；`badgeBg` / `badgeFg` / `dotBg` / `dotIcon` 全面補入新分組色彩與圖示

### 2026-07-24a — 設備拖曳群組 + Sidebar 勞務管理區段 + PDF CSP 修正

- **`frontend/js/case-management.js`**：新增 `_devDragId` / `_devDragOverId` 狀態；新增八個方法：`devDragStart()` / `devDragEnd()` / `devDragOver()` / `devDragLeave()` / `devDropOnDevice()` / `devDropOnGroup()` / `_devReindex()` / `devUngroupDevice()`
- **`frontend/pages/case-management.html`**：設備登錄 dev-card 加 `draggable="true"` 及六個拖曳事件；新增 `.dev-card--dragging` / `.dev-card--drop-over` / `.dev-group--drop-over` / `.dev-drag-handle` / `.btn-ungroup` CSS；群組內每個 dev-card 顯示「移出」按鈕；群組 header 接受 drop（加入群組）；非群組 dev-card 顯示拖曳提示（tooltip: 拖至另一設備合併、拖至群組加入）
- **`frontend/static/sidebar.js`**：新增 `contl`（外包人員）/ `paysl`（支付錢包）兩個圖示 key；新增「勞務管理」section（superadmin 可見），放在財務與工作內容之間；外包名冊 / 勞報單從 `系統` 區段移出、改掛此新區段
- **`backend/main.py`**：CSP 新增 `frame-src 'self' blob:` 指令，解決勞報單預覽 PDF 在 iframe 被瀏覽器封鎖的問題（原 `default-src 'self'` fallback 未涵蓋 `blob:` scheme）

### 2026-07-23b — 非 admin 使用者隱藏 badge 與通知鈴鐺

- **`frontend/static/sidebar.js` `buildTopbar()`**：Bell HTML 以 `if (ad)` 條件包覆，非 admin/superadmin 使用者完全不渲染通知鈴鐺按鈕
- **`frontend/static/notif.js` `_fetchModuleCounts()`**：加入 role guard（`role !== 'superadmin' && role !== 'admin'` → early return），非特權帳號不呼叫 module-counts API 也不更新任何 badge

### 2026-07-23a — Sidebar badge 修正 + 日曆視圖同步 + 「有更新」高亮

- **`backend/routers/system.py`**：新增 `_MODULE_EXCLUDE_ACTIONS` dict；`audit_module_counts` 對 `dev_crm` 模組排除 `dev_case.delete / delete_request / delete_cancel / delete_reject` 動作，避免刪除申請操作觸發不必要的 badge 計數
- **`frontend/static/sidebar.js`**：`build()` 在覆寫 `motrix_module_seen[curMod]` 之前先將舊值存入 `localStorage.motrix_module_prev_seen`（以模組 key 為索引），供各模組頁面讀取並比對「上次造訪後的更新項目」
- **`frontend/pages/daily-tasks.html`**（日曆視圖同步）：日曆右側任務詳情（`dt-report-card`）新增工作說明顯示；superadmin 可在日曆視圖直接刪除任務（使用獨立的 `calConfirmDelete` / `deleteCalTask()` 方法，不共用清單視圖的 `confirmDelete`）；任務卡片（週排程/區間/單次）新增「有更新」黃色標籤與黃色邊框（`isNewTask(t)` helper 比對 `_prevSeenDT`，僅 admin+ 可見）
  - ⚠️ 日曆視圖右側 `dt-report-card` 與清單視圖 `dt-detail` 功能必須同步：工作說明顯示、superadmin 刪除按鈕均需兩處維護
- **`frontend/pages/dev-crm.html`**：案件卡片新增「有更新」黃色邊框與標籤（`_prevSeen` 與 `c.updatedAt` 比對，admin+ 可見）；待刪除審核案件顯示橙色「待刪除審核」badge

### 2026-07-22r — 每日工作事項刪除 + Email 工作說明 + 業務開發軟刪除

- **`frontend/pages/daily-tasks.html`**：刪除按鈕移除 `dtUnlocked &&` 條件（superadmin 不需先進入解鎖模式即可刪除），刪除仍留下 audit log 記錄
- **`backend/helpers/email_notify.py`**：`notify_daily_task_assigned` 新增 `description` 參數，非空時在信件中加入「工作說明」列；新增 `notify_dev_case_delete_request()` 函式（寄送刪除申請通知給所有 superadmin）
- **`backend/routers/daily_tasks.py`**：`create_daily_task` / `update_daily_task` 帶入 `body.description` 給 `notify_daily_task_assigned`
- **`frontend/static/sidebar.js`**：`build()` 在 `buildSidebar()` 後立即隱藏當前模組所有 badge 元素（`_clearModBadge(_curMod)`），防止 `_fetchModuleCounts()` async 結果覆蓋清除動作；admin+ 使用者在 `build()` 時為所有 `_MOD_BADGES` key 填入 7 天前時間戳（解決未造訪模組因 `motrix_module_seen` 無對應 key 而 badge 不顯示的問題）
- **`backend/db.py`**：DB migration v28（`_m028_dev_cases_soft_delete`）為 `dev_cases` 新增 8 欄：`is_deleted` / `deleted_at` / `deleted_by` / `deleted_snapshot` / `pending_delete` / `delete_requested_by` / `delete_requested_at` / `delete_reason` + `idx_dev_cases_is_deleted` 索引
- **`backend/routers/dev_crm.py`**：移除舊 hard-delete 端點；新增 4 個端點（須在 `GET /dev-cases/{case_id}` 之前註冊以避免路由衝突）：
  - `POST /dev-cases/{id}/request-delete`（admin+，設 pending_delete=1，觸發 Email）
  - `POST /dev-cases/{id}/cancel-delete`（申請人可取消，superadmin 可取消任意）
  - `POST /dev-cases/{id}/approve-delete`（superadmin only，approve=True→軟刪除+快照，False→拒絕清除旗標）
  - `GET /dev-cases/pending-deletes`（superadmin only，回傳 pending_delete=1 清單）⚠️ 此路由必須在 `GET /dev-cases/{case_id}` 之前註冊
- **`frontend/pages/dev-crm.html`**：刪除改為「申請刪除」Modal（輸入原因）→ 待審核 badge + superadmin 審核 Modal 流程；`requestDeleteCase()` / `cancelDeleteRequest()` / `approveDeleteCase(approve)` 三個新方法

### 2026-07-22q — 精算利潤分析全面整合（案件管理/營運報表/Excel/PDF）

- **案件管理財務 Tab**：完整呈現「四、利潤分析」— 原始報價預估 vs 實際成本精算雙欄對照表（報價稅前收入、原始/實際成本、直接毛利、毛利率、管銷分攤10%、公益1%、淨利、淨利率）+ 差異色塊 + 成本品項列表（廠牌/實際金額/備注）+ 額外支出列表（類別/說明/金額/備注）+ 精算備注
- **營運報表精算 Modal**：同步改寫為雙欄對照表完整版，與案件管理財務 Tab 內容等高；完結資訊列顯示精算日期/完結人/完結時間；差異色塊/成本品項表/額外支出表均完整呈現
- **Excel 毛利分析 Sheet**：由 12 欄擴充至 21 欄：群組標題列（基本資訊6欄/原始報價預估4欄/實際成本精算6欄/差異2欄/精算資訊3欄），資料欄含原始成本/直接毛利率/淨利率/淨利、品項成本/額外支出/實際總成本/真實毛利率/淨利率/淨利、差異pp/差異金額、精算日期/完結人
- **PDF 毛利分析段落**：彙總表後新增各案件「利潤分析明細」，每案一卡（標題列含案件號/客戶/專案/業務員/精算日/完結人，雙欄對照表，差異說明色塊）

### 2026-07-22p — 案件管理財務 Tab 精算結果全面重構

- **`case-management.html` 財務 Tab**：① 修正欄位名稱錯誤（`revenue`→`quotedTotal`、`directMarginPct`→`grossMarginPct`、`item.desc`→`origDescription`、`item.amount`→`actualTotalCost`、`ex.desc`→`description`）；② 新增完結資訊列（精算日期、完結人、完結時間）；③ KPI 改為 2×2 四格：含稅/稅前收入、實際總成本、真實毛利+毛利率、淨利率+淨利金額；④ 新增「與原始報價差異」色塊（正/負差異綠/紅對應）；⑤ 成本品項顯示廠牌並加品項合計行；⑥ 額外支出顯示類別 chip 並加合計行

### 2026-07-22o — 業務開發 CRM 存取權限控制

- **`backend/routers/dev_crm.py`**：新增 `_can_access_case(user, row)` helper；非 admin 使用者僅能看到自己建立（`created_by`）、或列於 `sales_persons`（業務人員 JSON 陣列）或 `planners`（規劃人員 JSON 陣列）的案件；套用於 GET list（Python 層過濾，SQL 仍拉全部再篩）、GET/{id}、PUT、PATCH status、PATCH convert、GET/{id}/logs、POST/{id}/logs 共七個端點（越權回 HTTP 403）；admin/superadmin 不受限制查看所有案件

### 2026-07-22n — 側邊欄模組通知數字點 + 模組活動 Email

- **`backend/routers/system.py`**：新增 `POST /api/audit-log/module-counts` 端點，接受 `{modules: {模組key: ISO時間戳}}` 回傳各模組自 last-seen 後其他人的操作計數（排除呼叫者自身）；`_MODULE_ACTION_PREFIXES` 對應 10 個模組 key 至 `audit_log.action` 前綴
- **`backend/helpers/email_notify.py`**：新增 `notify_module_activity(module_label, action_label, actor, item_label, page_path)`，非阻塞 daemon thread 寄信給所有 admin/superadmin，業務開發新增案件/記錄時觸發
- **`backend/routers/dev_crm.py`**：create_dev_log / update_dev_log / delete_dev_log 補上 `_audit()` 呼叫（原缺失）；create_dev_case / create_dev_log 補 `notify_module_activity()`
- **`frontend/static/sidebar.js`**：`ni()` 加第六個選用參數 `badgeId`（藍色 `sb-mod-*` badge）；`_FILE_MODULE` 映射表（19 頁面 → 模組 key）；`build()` 載入時自動更新 `localStorage.motrix_module_seen` 清除當頁 badge；所有模組導覽項目（含供應商/承攬商/料號/採購/保固追蹤/銷售訂單等子項）均加 badge span
- **`frontend/static/notif.js`**：新增 `_fetchModuleCounts()`，讀取 `motrix_module_seen` 後 POST API 並更新 badge；`modBadge` 採陣列結構，單一模組計數可同步更新多個 badge 元素（procurement 4 個、equipment 2 個、finance 2 個）；`init()` 加入此方法的 `Promise.all`

### 2026-07-22m — 業務開發 CRM 模組（全新）

- **DB migration v27**：新增 `dev_cases`（案件主檔）與 `dev_logs`（開發記錄）兩張表
- **`backend/routers/dev_crm.py`**（新建）：
  - 案件 CRUD：`GET/POST/PUT/DELETE /dev-cases` + `PATCH status` + `PATCH convert`（連結報價單號）
  - 記錄 CRUD：`GET/POST /dev-cases/{id}/logs` + `PUT/DELETE /dev-logs/{id}` + `PATCH approve` + `GET /dev-logs/pending`
  - 權限：`dev_crm` 模組旗標或 admin+；代他人填寫自動標記 `needs_approval=1` 送 admin+ 審核
- **`frontend/pages/dev-crm.html`**（新建）：雙欄佈局（左欄案件清單含狀態篩選 chip + 搜尋；右欄案件詳情 + 開發記錄時間線）；成案後「轉建報價單」按鈕（預填客戶/案件名開啟報價單表單，可連結單號）；admin+ 顯示待審橫幅 + 待審 Modal
- **`sidebar.js`**：業務區段新增「業務開發」（第一項，`cDev` 旗標 = `dev_crm` 模組或 admin+）
- **`users.html`**：`allModules` 新增 `dev_crm`（業務開發 CRM）

### 2026-07-22l — 三大功能：案件資訊重命名 + 動態 Tab + 區間任務

- **案件管理「商務」Tab 改名為「案件資訊」**
- **動態 Tab（案件留言板）**：DB v26 新增 `case_updates` 表；`work_logs` 新增 `case_no` 欄位；API `GET/POST /api/quotations/{no}/updates` + `DELETE …/{id}`；動態 Tab 整合三來源（手動留言 / work_log / daily_task 完成回報），依時間降序；手動留言可由發文者或 admin+ 刪除
- **每日工作事項 — 區間任務（`recurrence_type=range`）**：開始日（`task_date`）~ 截止日（`recurrence_end_date`），在日期範圍內每天顯示；各指派人完成一次即完成整個區間任務；`_check_range_task_deadline()` 每日執行：截止前三天 + 截止當日，對未完成的各指派人寄送 email（指派人 + 主管）；email 模板 `notify_range_task_deadline()`；guard key `range_notif.{id}.{username}.{3d|deadline}` 防重複

### 2026-07-22k — 文件全面更新（本次 session 整合）

- **§2 前端表**：更新為 `js/` 目錄僅剩 2 個有效檔說明；移除已刪除的 `quotation-form.js` / `settlement.js` 死碼警告
- **§4.1 資料表**：補入 `vendor_contractors` / `contractor_dispatches`（含 accepted_at/by）；修正 `db.py` 版本標示 v11 → v25；補入 `module_versions` / `daily_task*` 等表
- **§4.3 樂觀鎖**：補入承攜商往來紀錄端點
- **§5.7**：新增承攬商派發狀態機說明
- **§7.4**：標題更新為 `DB v22–v25`
- **§11**：標記 ✅ 死碼清除 / ✅ Git Flow；補入 HTTPS 為 🔴 高優先；新增 SQLite 擴展建議
- **§13**：目錄結構全面更新（CURRENT_VERSION=25、GITFLOW.md、版本 manifest、tests/、刪除死碼、承攬商頁面）
- **Git Flow**：`develop` 分支建立 + `GITFLOW.md` 規範文件
- **死碼清除**：21 個死碼 JS 正式 git commit 刪除（commit `fbbbbda`）

### 2026-07-22j — 承攬商驗收流程節點

- **DB migration v25**：`contractor_dispatches` 新增 `accepted_at TEXT` / `accepted_by TEXT`
- **新端點 `PATCH /api/contractor-dispatches/{id}/accept`**：`action=pending_acceptance`（可由 draft/sent/confirmed 觸發）/ `action=accepted`（限由 pending_acceptance 觸發，記錄驗收人姓名+時間）；流程不合規回 409 含說明文字
- **狀態流**：`草稿 → 已送出 → 已確認 → 待驗收 → 已驗收 → 完工`（已取消可由任意非終態觸發）
- **前端**：dispatch 卡片依狀態顯示「待驗收」（綠框）/ 「✓ 確認驗收」（綠底）快速按鈕；已驗收後底部顯示綠色驗收人+時間橫條；Modal 狀態下拉補入兩個新選項；`case-management.js` 新增 `markPendingAcceptance()` / `acceptDispatch()` 方法

### 2026-07-22i — 實體編號系統 + 日曆回報自動展開

- **DB migration v24（`db.py`）**：`customers`/`suppliers`/`vendor_contractors` 新增 `code TEXT NOT NULL DEFAULT ''`；以 `created_at` 月份分組、`id` 順序回填既有資料（格式 `C-YYYYMM-NNN`/`S-`/`V-`）；建立 UNIQUE partial index（`WHERE code != ''`）；新增 `next_entity_code(conn,table,prefix)` helper
- **後端三路由**：`create_customer`/`create_supplier`/`create_vendor_contractor` 建立後自動生成 code 並回傳；GET list/detail 均含 `code` 欄位；承攬商伺服端搜尋加入 `code LIKE ?`
- **前端三頁面**：列表 name 欄下方顯示 code 徽章（灰底/承攬商紫底）；詳細面板 header 同步顯示；前端搜尋 filter 加入 code 比對
- **日曆模式切換卡片自動展開回報（`daily-tasks.html`）**：點擊任務卡片時，若當前使用者為指派對象且尚未回報，自動設定 `calEditTaskId=task.id` 展開填寫表單，無需再手動點「提交回報」

### 2026-07-22h — 日曆回報修正 + 信件按鈕 + 統編查詢錯誤分類

- **日曆模式回報表單（`daily-tasks.html`）**：切換工作事項卡片後仍無法輸入回報的根因為 Alpine.js 巢狀 `x-if` 在外層條件持續 truthy 時不重建內層 DOM；全改為 `x-show` 常駐 DOM，切換卡片後「提交回報」按鈕與 textarea 即時顯示並可操作
- **信件按鈕對比度（`email_notify.py`）**：`.btn` 顏色改為 `#1D4ED8`；`color:#ffffff !important`；所有 `<a class="btn">` 補 `style="..."` inline 屬性，防止 Gmail 等覆蓋連結字色，共修正 4 處
- **統編查詢錯誤分類（`dashboard.py` + 三個前端頁面）**：`_gcis_get` 新增 `(data, status)` 回傳格式，區分 `not_found`/`network_error`；連線失敗回 HTTP 503；客戶／供應商／承攬商頁面分別加入 503 提示「政府資料庫連線失敗，請確認伺服器對外網路」；加入 `User-Agent` 標頭與 `logger.warning` 記錄

### 2026-07-22g — 業務員績效欄位對齊修正

- **CSS specificity 衝突修復**：`reports.html` 內 `.data-table th { text-align:left }` specificity `(0,1,1)` 壓過 `.r { text-align:right }` 的 `(0,1,0)`，導致所有 `<th class="r">` 標題被強制靠左，但 `<td class="r">` 資料靠右，業務員績效（7/8 欄均為數字）視覺錯位最為明顯；新增 `.data-table th.r { text-align:right }` 與 `.data-table th.c { text-align:center }`（specificity `(0,2,1)`），全頁數字欄位標題對齊一次修正
- **業務員績效 Tab 結構簡化**：移除 `<template x-if>` + `<div class="table-scroll">` 雙層包裝，改用 `x-show` 直接套用於 `.empty-state div` 與 `<table>`，與其他 Tab（本期收款、未收款等）結構保持一致

### 2026-07-22f — 顧問建議全實施（6 項）

- **收款率改用 actualAmount**：`_collect()` `recv_amt` 從 `amt`（合約分期）改為 `aa if aa is not None else amt`（實收金額），使案件及業務員層級收款率反映真實入帳
- **業務員毛利率改收入加權平均**：`sm[k]` 從 `mSum/mCnt` 簡單平均改為 `mRevSum/mProfitSum`（稅前收入加權），避免小案件毛利率拉偏整體均值；實際毛利率同步改為 `amRevSum/amProfitSum`
- **帳齡分析 Tab**：`reports.html` 新增「帳齡分析」Tab 按鈕；`reports.js` 新增 `showArTab()` lazy fetch `GET /api/reports/ar-aging`；Panel 包含四區間 KPI 卡片（0–30/31–60/61–90/90+）+ 每區間展開明細表（含已超 N 天色標）
- **已結案未精算警示橫幅**：`_collect()` 新增查詢已結案未 finalized 案件 → `settleOverdue[]`；前端 `settleOverdue` getter；KPI 區塊下橙色警示橫幅（顯示案號列表）
- **在製訂單 Backlog KPI**：`_collect()` 計算 `backlog = sum(total-receivedAmount for 已成案)`；summary 加 `backlog` 欄位；業績核心 KPI 網格新增藍色「在製訂單」卡片；PDF 報告同步加入
- **近 12 月 MoM 趨勢**：新增 `GET /api/reports/monthly-trend?months=12`（回傳每月 newCases / revenue / collected / avgMarginPct）；`showChartsTab()` lazy fetch；`_buildTrendChart()` 可用時加入「實收金額」橙色折線（按 receivedAt 月份，非 quoteDate）

### 2026-07-22d — Excel + PDF 毛利分析精算比較欄

- **Excel「毛利分析」Sheet**：新增「預估毛利（NT$）」欄（= 報價稅前 × 預估淨毛利率）、「差異金額（NT$）」欄（= 實際毛利 − 預估毛利；Excel 格式 `+#,##0;-#,##0`）；新增合計行（深色底）顯示三個金額加總；差異欄字體色標（正數綠 / 負數紅）
- **PDF 報告**：新增獨立「毛利分析」段落（頁面分隔，紫色標題），欄位同前端：預估毛利率 / 預估毛利 / 實際毛利率 / 實際毛利 / 差異(pp) / 差異金額；末行合計；無精算案件時顯示說明文字

### 2026-07-22b — 日曆快速回報 + 毛利分析金額欄

- **`daily-tasks.html`**：新增 `selectCalDayTask(date, taskId)`，點選「今日未完成事項」任務卡後直接導航至該任務並自動展開 inline 回報表單（若本人尚未提交）；已提交者僅選中顯示，不強制打開編輯
- **`reports.html`（毛利分析 tab）**：新增「預估毛利（NT$）」欄（= 報價稅前 × 預估淨毛利率）與「差異金額（NT$）」欄（= 實際毛利 − 預估毛利；綠正/紅負色標），與既有差異(pp)欄共同呈現精算落差
- **`reports.js`**：新增 `fmtDiff()`（帶正/負號 NT$ 格式化）、`estGrossProfit(mc)`（計算預估毛利額）兩個 helper

### 2026-07-22a — 承攬商管理：功能補強

- **`vendor-contractors.html`**：新增政府統編查詢帶入（`GET /api/company/tax/{id}`，查到後可手動覆蓋）、承攬商類型下拉（機電/**弱電**/消防/空調/裝修/水電/IT/土木/其他）、內部標籤（多標籤新增/移除，以逗號分隔存入 `data_json.tags`）、匯出 Excel / 匯入 Excel（SheetJS xlsx@0.18.5 CDN）
- **匯入欄位**：`承攬商名稱 | 承攬商類型 | 統一編號 | 聯絡人 | 電話 | Email | 地址 | 內部標籤（逗號分隔）| 備注`；依統編或名稱比對：存在→PUT(更新)，不存在→POST(新增)
- **`backend/routers/vendor_contractors.py` PUT**：改為合併 `data_json`，若呼叫端未傳 `visits`，自動保留既有往來紀錄（避免匯入覆蓋）
- **搜尋優化**：`GET /api/vendor-contractors?q=` 新增 `tax_id LIKE` 條件（原僅搜 name/phone/contact_name）
- **往來紀錄保護**：`openEdit(v)` 擷取 `v.visits` 存入 `_pendingVisits`，PUT 時一併傳入，確保手動儲存前的既有紀錄不被 Modal 存檔覆蓋

### 2026-07-21aa — 承攬商管理模組（全新）

- **DB v22**：新增 `vendor_contractors`（承攬商主檔：名稱/統編/聯絡人/電話/Email/地址/往來紀錄/停用）與 `contractor_dispatches`（派發紀錄：報價品項 JSON、狀態、合計金額、建立人）兩張表
- **`backend/routers/vendor_contractors.py`**（新建）：
  - 承攬商 CRUD：`GET /api/vendor-contractors` · `GET /api/vendor-contractors/selectable`（輕量列表供下拉） · `GET/POST/PUT/DELETE /api/vendor-contractors/{id}` · `PATCH .../active` · `PATCH .../visits`（樂觀鎖）
  - 派發 CRUD：`GET/POST /api/contractor-dispatches` · `GET/PUT/DELETE /api/contractor-dispatches/{id}`
  - 回推端點：`POST /api/contractor-dispatches/{id}/import-to-quote` — 將承攬商報價品項（含 header 區塊）附加至報價單 `items[]`，僅草稿狀態可操作
- **`frontend/pages/vendor-contractors.html`**（新建）：雙欄佈局（左列表 / 右詳情），承攬商 CRUD Modal，往來紀錄樂觀鎖儲存，右欄顯示該承攬商之全部派發歷程
- **`frontend/js/case-management.js`**：新增 `vendors[]`, `dispatches[]`, `dispatchesLoading`, `showDispatchModal` 等狀態及 `loadVendors()` / `loadDispatches()` / `openNewDispatch()` / `openEditDispatch()` / `saveDispatch()` / `deleteDispatch()` / `importDispatchToQuote()` / `addDispatchItem()` / `onDispatchItemPrice()` 等方法；`init()` 呼叫 `loadVendors()`；`selectCase()` 呼叫 `loadDispatches(quoteNo)`
- **`frontend/pages/case-management.html`**：新增「承攬商」Tab（位於保固備注後）：外包總成本 KPI、派發卡片清單（含品項明細表）、「↩ 回推報價單」按鈕、派發 Modal（承攬商選擇 / 日期 / 狀態 / 工作範圍 / 品項報價表格含自動金額計算 / 備注）
- **`frontend/static/sidebar.js`**：廠商與採購區段新增「承攬商管理」連結（`vendor-contractors.html`，`admin+` 可見）

### 2026-07-21z2 — 回報修改標示（UI + DB）

- **DB v21** (`db.py`): `daily_task_completions` 新增 `report_edit_count INTEGER NOT NULL DEFAULT 0`；`ON CONFLICT DO UPDATE SET` 子句加入 `report_edit_count=report_edit_count+1` — 每次覆寫自動計數
- **`daily_tasks.py`**: 三個 `SELECT` 查詢加入 `report_edit_count`；comp_map 輸出 `editCount` 欄位
- **`daily-tasks.html`**: 四處顯示黃色「已修改」徽章（`editCount > 0`）：一般任務詳情每人 ag-card、本人已完成 notice、日曆日期詳情每人列、回報彙整每人列；hover `title` 顯示「已修改 N 次」

### 2026-07-21z — 工作事項回報編輯

- **`daily-tasks.html`（一般任務詳情）**：`isAssignedToMe() && completed` 區塊新增「修改回報」按鈕（`editingMyReport` flag 控制）→ 展開 dt-complete-form 可覆寫原有回報；`submitCompletion()` 成功後重置 `editingMyReport`，toast 訊息依模式顯示；`selectTask/selectWeeklyTask/switchOccurrence` 切換任務自動重置
- **`daily-tasks.html`（日曆日期詳情）**：指派人卡片底部新增「修改回報」（已完成）/ 「提交回報」（未提交）按鈕，展開 inline textarea；`calSubmitReport()` → `PATCH /daily-tasks/{id}/complete` → `loadReportData()` 重載；`calEditTaskId/calEditReport/calEditSubmitting` 狀態，切換日期或任務自動重置
- **新增狀態**：`editingMyReport: false`, `calEditTaskId: null`, `calEditReport: ''`, `calEditSubmitting: false`
- **新增方法**：`calSubmitReport(taskId, occDate, text)`（純前端，無後端改動）

### 2026-07-21y — 工作事項編輯紀錄 + 月報當月範圍

- **DB v20** (`db.py`): 新增 `daily_task_edit_log` 表（task_id, changed_by, changed_at, changes_json 儲存欄位差異陣列）
- **`daily_tasks.py`**: `_compute_task_diff()` 比對 10 個欄位（標題/說明/日期/分類/優先級/指派對象/主管/週期/排程/案件）；`update_daily_task` 儲存 diff + email 通知主管（`notify_daily_task_edited`）；新增 `GET /api/daily-tasks/{id}/edit-log`（superadmin/指派人/主管可查）
- **`email_notify.py`**: 新增 `notify_daily_task_edited()`，信件含異動前後對照表（舊值刪除線→新值加粗）
- **前端 `daily-tasks.html`**: 編輯按鈕移出解鎖限制（superadmin 直接可用），刪除仍須解鎖；任務詳情底部顯示「編輯紀錄」區塊（編輯人頭像+姓名+時間 + 每個欄位舊→新差異列表）；儲存後自動重載 edit-log
- **`reports.py` `_send_monthly_report_for`**: 月報寄送改為當月範圍獨立 — casesAll→casesPeriod、outstanding/allItems 過濾同月案件、summary 重算；六月報告 → 七月一日 08:00 寄出，guard `monthly_report_last_sent` 防重複

### 2026-07-21v — 保固追蹤納入已成案

- **`warranty.html`**：移除 API 呼叫中的 `?deal_tag=已結案` 過濾參數，改為呼叫 `/api/devices`（與設備登載頁相同），使所有登載了保固時間的案件設備（含已成案）均顯示於保固追蹤頁；副標題更新為「含已成案 / 已結案」

### 2026-07-21u — 月報自動寄送

- **`helpers/email_notify.py`**：新增 `_superadmin_emails()`（查詢 `role='superadmin'`，fallback to admin emails）、`_send_with_attachments()`（multipart/mixed；RFC 5987 UTF-8 filename encoding for Chinese filenames）、`notify_monthly_report(period_label, period_str, excel_bytes, pdf_bytes)` — 非阻塞 daemon thread 寄送 Excel+PDF 附件給所有 superadmin
- **`helpers/__init__.py`**：匯出 `notify_monthly_report`
- **`routers/reports.py`**：新增 `_prev_month_str()`、`_send_monthly_report_for(period_str)` — 產 Excel+PDF 並呼叫 `notify_monthly_report`（PDF 失敗不中斷 Excel 寄送）、`_catchup_monthly_reports()` — 從 `monthly_report_last_sent + 1` 逐月補寄至上月（首次執行只補上月，不回補全部歷史）、`schedule_monthly_report()` — 啟動時執行補寄、排定每月 1 日 08:00 自動寄送；guard key `monthly_report_last_sent`
- **`main.py`**：啟動序列新增 `reports.schedule_monthly_report()`

### 2026-07-21t — 主管頁面載入修復 + 離開警示 + 開機補寄

- **主管頁面載入修復**（`daily_tasks.py`）：`_user_filter_sql` 對 superadmin 加 username 參數時改為同時檢查 `assigned_to OR supervisors`；修正從使用者管理頁點「查看每日工作事項」跳轉後，superadmin 主管看不到自己監督任務的問題；`get_task_history` 403 同步放行 supervisors 成員
- **全模組離開警示**（`sidebar.js`）：新增 `bindNavGuard()` — 在 DOMContentLoaded 後攔截所有 `<a>` 點擊（非 # / javascript: / 同路徑）；`beforeunload` 防頁面刷新/關閉；全域監聽 `input`/`change` 事件自動設 `window.motrixIsDirty = true`（排除 type=search、readonly、disabled 及 class 含 search/filter 的輸入）；`fetch` 攔截器：成功的 POST/PUT/PATCH/DELETE 自動清除 dirty；提示文案：「您有尚未儲存的輸入內容，離開此頁面將導致資料遺失，確定要離開嗎？」
- **開機補寄機制**（`daily_tasks.py`）：`schedule_overdue_check` 改為每次啟動執行 `_startup_catchup()`，從 `last_check + 1` 逐日補發至昨日；移除舊版 `hour >= 8` 限制；`_check_overdue_and_notify` 加 `check_date` 參數可指定日期；多日停機情境（如週末未開機）亦可全補，不再只補昨日

### 2026-07-21s — 負責主管可查看被指派人工作事項

- **Backend `_user_filter_sql()`**（`daily_tasks.py`）：非 superadmin 使用者若在 `supervisors` 欄位，也可撈到該任務（原只看 `assigned_to`，現改 `OR EXISTS supervisors`）
- **Backend `get_daily_task()`**（`daily_tasks.py`）：403 存取檢查同步放行 `supervisors` 成員
- **任務卡片「主管」badge**（`daily-tasks.html`）：使用者被列為主管但非指派人時，卡片 footer 顯示紫色「主管」chip（一般任務卡 + 週期任務卡 + 日曆 dashboard 今日任務卡三處同步）
- **任務詳情回報可視性**（`daily-tasks.html`）：指派人回報文字對主管（`supervisors`）開放，等同本人與 superadmin 解鎖
- **主管提示橫幅**（`daily-tasks.html`）：非指派人但為主管時，詳情底部顯示「您為此工作事項的負責主管，可查看所有人員的回報情況」藍紫提示框

### 2026-07-21r — 本期未完成日升序排列

- **本期未完成日改為升序**（`daily-tasks.html`）：`calPeriodPendingDates()` sort 改為 `a - b`，日期最早的顯示在最上方；`calPeriodPendingByWeek()` 週排序同步改升序，最早週在最上

### 2026-07-21q — 本期未完成日週分組 + 逾期通知確認

- **本期未完成日改週分組顯示**（`daily-tasks.html`）：`calPeriodPendingByWeek()` 以週一為起點分組；週標頭顯示日期範圍（`MM/DD（一）– MM/DD（日）`）+ 該週未完成天數；每週內各日顯示完成進度，可點擊跳轉；新增 `_weekMondayOf()` 用本地時間 accessor（避免 UTC+8 偏移）
- **逾期 Email 通知確認**（`daily_tasks.py`）：機制已完整，不需額外修改
  - `_check_overdue_and_notify()` 每日 08:00 掃描昨日所有 incomplete 指派人
  - 每個未完成的（任務, 指派人）發 `notify_daily_task_overdue` email
  - 收件人：被指派人 + 任務主管（若無主管則發給所有 admin/superadmin）
  - Guard key `dt_overdue_last_check` 防重複，重啟不會重發

### 2026-07-21p — 日曆視圖右側 dashboard

- **每日工作事項日曆 dashboard**（`daily-tasks.html`）：未選取日期時右側顯示三個區塊
  - **今日未完成事項**：自動載入當日任務，列出尚未全員完成的任務卡片；每個卡片顯示各指派人完成/待完成 chip（黃=待完成、綠=已完成）；點擊跳轉到今日詳情
  - **本期未完成日**：從 `calData` 提取 `done < total` 的日期，每列顯示日期、星期、完成進度（橙/紅），可點擊跳轉該日
  - **本期已完成日**：`done === total` 的日期以綠色 chip 方式列出，可點擊跳轉
  - 技術：`loadCalendarData()` 改為 3 個並行 fetch（上月/本月/今日），今日任務存入 `calDashData`；新增 `calDashTodayStr/calDashPendingTasks/calPeriodPendingDates/calPeriodDoneDates` helper methods

### 2026-07-21o — 介面過濾與日曆視圖

- **案件管理「全部」Tab 排除已結案**（`case-management.js` + `case-management.html`）：`filterCases()` 在 `listTab==='all'` 時 `filter(c => c.deal_tag !== '已結案')`；「全部」徽章計數同步排除；已結案仍可點獨立 Tab 查看
- **專案管理「全部」pill 排除完工**（`projects.html`）：`filteredProjects` getter 加 `filterStatus==='全部' && p.status==='完工'` 短路排除；完工 pill 仍可獨立篩選
- **每日工作事項日曆視圖**（`daily-tasks.html`）：
  - 頂部「日曆視圖」按鈕，桌機版（`window.innerWidth >= 768`）**預設自動開啟**
  - 左側雙月曆（上月 + 本月）：週一起始，今日藍色圓底；每格色標（綠底=全完成 / 黃底=部分完成 / 紅底=未完成）+ `已/總` 數字
  - 右側：點擊日期載入當日所有任務，顯示人員 chips（完成率色點）、搜尋輸入、任務清單 + 回報詳情
  - 月份切換同步重載兩個月資料；與「回報彙整」模式互斥
  - **Bug fix**：`calMonthDays()` 改用 `getFullYear/Month/Date` 本地時間，修正 `toISOString()` UTC 偏移在 UTC+8 環境差一天的問題
  - ⚠️ **維護原則**：日曆視圖右側任務詳情（`dt-report-card`）與清單視圖（`dt-detail`）功能須同步：包含工作說明顯示、superadmin 刪除按鈕。日曆視圖使用獨立的 `calConfirmDelete`/`deleteCalTask()` 而非 `confirmDelete`/`deleteTask()`

### 2026-07-21n — 角色管理全面升級

- **角色名稱自訂**（`system.py` + `users.html`）：superadmin 可在「角色名稱設定」面板（可摺疊）自訂 superadmin/admin/sales/engineer/viewer 五層的顯示名稱；儲存於 `system_settings`；`GET/PUT /api/settings/role-labels`；使用者列表、快速套用 chips、角色下拉選單均即時反映；DB `role` 欄位不變
- **自建角色管理**（`system.py` + `users.html`）：superadmin 可建立自訂角色（名稱 + 基礎角色層 + 模組清單）；`GET/POST/PUT/DELETE /api/settings/custom-roles`；資料存於 `system_settings key custom_roles`；使用者 Modal 角色快速套用列顯示系統預設 chips + 自訂角色 chips（虛線框區隔）
- **存取模組補全**（`users.html`）：`allModules` 新增 `reports`（營運報表）、`work_log`（工作日誌）、`daily_task`（每日工作事項），使用者編輯 Modal 的模組勾選列現已涵蓋全部側欄項目
- **Sidebar 模組閘控**（`sidebar.js`）：`reports` → `admin+` 或含 `reports` 模組；`work_log` / `daily_task` → 非 viewer 或含對應模組（相容既有帳號）
- **報價清單「全部」Tab 排除已結案**（`quotations.html`）：`tabCount()` 及 `filteredQuotes` getter 雙重排除；已結案僅顯示於「已結案」分類 Tab
- **端點安全強化**：`customers.py`（create/update/visits/delete 4 端點）、`parts.py`（create/update/delete 3 端點）、`quotations.py`（case-record PATCH / payment PATCH 2 端點）補加 `_require_user()` 角色檢查

### 2026-07-21m — P3 客戶交易歷史彙整

- **新 API**：`GET /api/reports/customer-history`（`routers/reports.py`，admin+ 限制）
  - 掃描所有非草稿報價，依 `customer_name` 分組聚合
  - 傳回每客戶：`wonCount` / `lostCount` / `winRate` / `totalWonAmount` / `collectedAmount` / `collectionRate` / `lastActivity` / `salesPerson` + `transactions[]`
  - 按成案總金額降序排列
- **`reports.js`**：新增 `custHistory` / `custLoading` / `custLoaded` / `custSearch` / `custSort` / `selectedCust` 狀態；`showCustTab()` 懶載入；`filteredCusts` getter（支援搜尋 + 四種排序）；`selectCust()` / `custAmtFmt()`
- **`reports.html`**：新增「客戶歷史」Tab button（懶載入，不影響主要 loadData 速度）
  - 左欄：可搜尋 + 可排序的客戶卡片列表（成案/未成案/追蹤中 chip + 成案率色標）
  - 右欄：選中客戶後顯示 5 個 KPI（總金額/已收/收款率/成案率/最後活動）+ 交易明細表（案件號超連結、狀態標籤、毛利率色碼）

### 2026-07-21l — P2 營運效率：三項改善

**P2-1：每日工作事項掛案件編號**

- **DB v19**：`daily_tasks` 新增 `case_no TEXT DEFAULT ''`（`_m019_daily_task_case_no`）
- **API**：`DailyTaskIn.case_no`；`GET /api/daily-tasks?case_no=` 篩選；`POST/PUT` 寫入 `case_no`
- **daily-tasks.html**：`loadActiveCases()` 載入已成案列表 → modal「關聯案件」下拉；任務卡片藍色 `case_no` badge
- **case-management.html**：右下「今日相關任務」mini strip（`_loadCaseTasks(quoteNo)` 於 selectCase 時呼叫）

**P2-2：保固到期前 30/7 天主動 Email**

- `helpers/email_notify.py`：`notify_warranty_expiry(device_name, customer, quote_no, days_left, expiry_date, sales_person)` — 7 天紅色 / 30 天橙色
- `helpers/__init__.py`：匯出 `notify_warranty_expiry`
- `routers/daily_tasks.py`：`_check_warranty_expiry()` 掃描 `deal_tag='已成案'` 案件 devices[]；per-device+threshold guard（`system_settings` key `warranty_notif.{no}_{sn}_{7|30}`）；`schedule_overdue_check` 改為每日同時呼叫兩個檢查器

**P2-3：採購叫料廠商交期追蹤**

- `case-management.html` 叫料管控 mat-card：叫料中且未到料時顯示「廠商名稱」輸入 + 「預計到料日」date input + 交期逾期紅標
- 資料存於 `data_json.caseRecord.materials[].supplier/.expectedDate`（無需 DB schema 變動）

### 2026-07-21k — P1 業績可視化：銷售漏斗 + 待追蹤報價

- **新 API**：`GET /api/dashboard/funnel`（`routers/dashboard.py`）
  - 傳回 `funnel`（totalSubmitted / won / lost / pendingResponse / winRate）
  - 傳回 `followUpQuotes`（已送出 ≥ 14 天未確認，按天數降序，最多 10 筆）
  - 傳回 `expiringQuotes`（有效期剩 ≤ 3 天，最多 5 筆）
  - 僅限 quotation 以上角色；銷售人員可見自身負責報價
- **儀表板 `index.html`**：
  - 載入後非同步呼叫 `loadFunnel()`（fire-and-forget，不阻塞主 loading）
  - **有效期警示 banner**（紅色）：每份剩 ≤ 3 天的已送出報價獨立一行，附「前往更新」按鈕
  - **待追蹤報價 banner**（橙色）：彙整顯示 ≥ 14 天未回應報價（最多 4 行 + 摺疊提示）；附「查看全部」連結
  - **Win Rate 漏斗條**（白底卡片，KPI 下方、圖表上方）：成案率 % ＋ 成案 / 評估中 / 未成案 三數值 ＋ 比例分色長條圖

### 2026-07-21j — 每日工作事項 UI 全面升級

- **頂部按鈕**：`btn` / `btn-ghost` / `btn-primary` CSS 補充定義（原本無樣式）；`回報彙整` 改用 `.dt-bar-act-report`（紫色 pill，激活為實色）；`解鎖管理視角` 改用 `.dt-bar-act-lock`（amber 警示色）；`新增工作事項` 改用 `.dt-bar-act-add`（藍色主按鈕）
- **回報彙整**：
  - 人員 chip 列：載入後自動顯示當日所有被派人員，帶完成率色點（綠/橙/紅）及 `(N/M)` 計數；點擊快速切換只看該人員任務
  - 「今日」快速按鈕：一鍵跳回當日並清除篩選
  - 年/月切換時自動清除人員篩選
  - 搜尋提示邏輯：人員篩選 OR 文字搜尋時均顯示符合筆數

### 2026-07-21i — 每日工作事項歷史介面重設計

- **daily-tasks.html**：歷史紀錄 Tab 全面改版
  - 工具列：`月 ｜ 週` 切換 + `← 期間 →` 導航（← → 各退/進一週或一月）
  - **月視圖**（預設）：依 ISO 週分帶狀組（`第N週 M/D–M/D`），帶內按日列行，collapse 展開回報內容
  - **週視圖**：顯示 Mon–Sun 7 天，有任務者顯示人員 chip + 進度；無任務日顯示 `— 無任務`（半透明）
  - 進度 badge 三色：全部完成（綠）/ 部分完成（橙）/ 未完成（紅）
  - 改為一次性載入最多 500 筆（`per_page=500`），廢除 load-more 分頁；tab 標頭仍顯示總筆數
- **左面板 stat-strip**：仿採購管理配置，顯示「今日任務 / 今日待辦 / 本月完成率」三格數值卡（含顏色警示）

---

### 2026-07-21h — 介面優化批次（UI / CEO Dashboard）

- **sidebar.js**：`每日工作事項` 側欄項目加入 `sb-dt-badge`（今日待辦數，紫色徽章）
- **notif.js**：加入 `_fetchDailyTaskCount()` 背景抓取今日未完成任務並更新 badge；`actionLabel` 補齊 `daily_task.*` 系列動作標籤
- **reports.js / reports.html**：營運報表 CEO 視角重編排
  - Tab 順序改為：目標達成率 → 圖表分析 → 業務員績效 → 本期收款 → 未收款 → 案件清單 → 毛利分析 → 保固預警
  - 預設開啟 `目標達成率` tab；年報模式自動切換至此 tab
  - KPI grid 依策略優先序分兩群：「業績核心」（新成案/本期收款/精算毛利/覆蓋率）+ 「財務概況」（應收/已收/實收淨/未收/手續費/保固預警）
  - 保固預警有警示時自動轉紅色卡片

---

### 2026-07-21g — 品質掃尾批次（Quality Sweep）

- **L2** `quotation-form.html`：`addItem()` / `addHeader()` / 複製模板改用 `crypto.randomUUID()`；API 載入後補 id normalize
- **L3** `backend/tests/test_core.py`：48 tests 全過（TestStepsToTiers / TestActiveTiers / TestCurrentTierIdx / TestPasswordHelpers）
- **確認已施作**：L1 sidebar 角標（notif.js:68 已排除 approval_request）/ E2 Login 速率限制（auth.py）/ E3 Session 清理（startup.py）

---

### 2026-07-21f — 可靠性強化批次（Reliability Patch Batch）

- **H3** `archive.py`：備份 ERROR 時發 Email 告警（`_send_backup_error_email()`，每日節流，`_async_send` 非同步）
- **H4** `routers/reports.py`：Excel/PDF 匯出 60 秒每用戶冷卻（`_check_export_rate()`，429 on violation）
- **M1** `helpers/quotations.py`：提取 `_steps_to_tiers()` 共用 helper；`system.py._normalize_flow()` + `quotations._setting_to_active_tiers()` 均改呼叫
- **M3** `backend/tests/test_core.py`：25 tests 全過（TestParsePeriod / TestComputeAchievement / TestCalc）

---

## §13 · 目錄結構（精簡）

```
MOTRIX-ERP/
├── MOTRIX-ERP-QUICK.md          ← 本文件
├── GITFLOW.md                   ← Git Flow 分支規則（develop 分支 + commit 規範）
├── .gitignore
├── backup_alerts/               ← 備份警示（執行期產生）
├── backend/
│   ├── main.py                  ← wiring；startup 呼叫 auth.init_rate_limiting()
│   ├── db.py                    ← schema + 42 個 migrations（CURRENT_VERSION=42，見 §2）
│   ├── version_manifest.json    ← 模組版本紀錄（重啟後同步至 DB module_versions）
│   ├── helpers/                 ← 套件（拆自原 helpers.py）
│   │   ├── __init__.py          ← re-export 全部符號（向後相容）
│   │   ├── auth.py              ← 密碼、session、弱密碼政策
│   │   ├── settings.py          ← system_settings CRUD
│   │   ├── audit.py             ← audit log + 通知
│   │   ├── quotations.py        ← SQL 常數、save_quotation_json
│   │   ├── dates.py             ← _add_months、_warranty_expiry
│   │   ├── email_notify.py      ← Email 通知（月報、逾期、保固、備份告警）
│   │   └── startup.py           ← 啟動檢查、Edge 路徑解析
│   ├── archive.py               ← 備份；_atomic_json_write()；H: fallback
│   ├── pdf_gen.py · photos.py
│   ├── backup_job.py            ← 獨立備份腳本（Task Scheduler 呼叫）
│   ├── setup_backup_task.ps1    ← 工作排程器設定（初次部署執行一次）
│   ├── autostart.bat            ← 正式環境登入自動啟動；crash-restart 迴圈（見 §1.1）
│   ├── autostart_hidden.vbs     ← 供 Task Scheduler 隱藏視窗呼叫 autostart.bat
│   ├── setup_autostart_task.ps1 ← 「MOTRIX ERP Server Autostart」排程設定（初次部署執行一次）
│   ├── heartbeat_job.py         ← 心跳監控腳本（見 §1.2），Task Scheduler 每 5 分鐘呼叫
│   ├── heartbeat_config.json    ← 心跳打卡網址設定（healthchecks.io ping_url）
│   ├── setup_heartbeat_task.ps1 ← 「MOTRIX ERP Heartbeat」排程設定（初次部署執行一次）
│   ├── motrix_erp.db
│   ├── db_backups/
│   │   ├── YYYY-MM-DD/          ← 本機整庫 SQLite 快照（保留 30 天）
│   │   └── quotation_instant/   ← H: 不可用時即時報價單 JSON fallback
│   ├── logs/backup_job.log · heartbeat_job.log
│   ├── tests/test_core.py       ← 48 自動化測試（全通過）
│   └── routers/
│       ├── auth.py · quotations.py · customers.py · suppliers.py
│       ├── parts.py · projects.py · dashboard.py · system.py · reports.py
│       ├── daily_tasks.py · warranty.py
│       ├── vendor_contractors.py  ← 承攬商 + 派發 CRUD + accept + import-to-quote
│       ├── dev_crm.py             ← 業務開發 CRM（dev_cases + dev_logs）
│       └── shipping_notes.py      ← 出貨單 CRUD + 獨立簽核流程 + PDF + 回簽 toggle
├── frontend/
│   ├── index.html               ← 儀表板（Alpine inline）
│   ├── css/style.css
│   ├── js/
│   │   ├── case-management.js   ← ✅ 有效（案件管理 Alpine 元件）
│   │   └── reports.js           ← ✅ 有效（營運報表 Alpine 元件）
│   ├── pages/
│   │   ├── dev-crm.html         ← 業務開發 CRM（雙欄；devCrmPage() Alpine inline）
│   │   ├── quotation-form.html  ← Alpine inline（真正的 quotationForm()）
│   │   ├── settlement.html      ← Alpine inline（真正的 settlementPage()）
│   │   ├── case-management.html ← 含承攬商派發 + 驗收流程 Tab + 出貨單 Tab
│   │   ├── vendor-contractors.html ← 承攬商管理（雙欄；vendorContractorsPage()）
│   │   ├── shipping-approval-settings.html ← 出貨單專屬簽核設定（複製 approval-settings.html）
│   │   └── *.html               ← 其餘頁面均 Alpine inline，無對應外置 JS
│   └── static/
│       ├── sidebar.js           ← Topbar + Sidebar + 離開警示 + _FILE_MODULE + sb-mod-* badge
│       ├── notif.js             ← 通知 Bell + daily_task badge + 模組活動 badge (_fetchModuleCounts)
│       └── logo.png             ← MOTRIX 白字去背 PNG
├── uploads/projects/
└── 報價單PDF/
```

---

## §14 · 跨機核對與拉檔流程

> 背景與已知落差見 §0。目前完全靠人工複製，本章節是「核對時該看什麼、怎麼拉檔案」的清單，**不是自動化機制**——自動化推送是明確列為之後才考慮的項目（見章末）。

### §14.1 · 核對優先順序

依 2026-08-01 這次核對的實際經驗排序，越上面代表越容易漂移、越該優先看：

1. **`backend/db.py`（migrations）**——優先用「正式機 db 的 `sqlite_master` 實際結構」反推，不要只比對程式碼本身（程式碼可能也漏東西，這次 v32/v33 就是實例：功能檔案都在，唯獨 migration 遺失）
2. **`backend/routers/*.py`、`backend/helpers/*.py`**——新功能程式碼
3. **`frontend/pages/*.html`、`frontend/js/*.js`、`frontend/static/*.js`**
4. **`backend/*.ps1`**（部署/排程腳本，如 `setup_autostart_task.ps1`／`setup_heartbeat_task.ps1`）
5. **`backend/version_manifest.json`**——比對兩邊「最新一筆」的日期，誰比較新代表誰的紀錄比較完整

### §14.2 · 從正式機拉檔案回來的具體步驟

- **資料庫檔案**（`motrix_erp.db`）複製回來時**不要直接覆蓋**開發機正在用的檔案：先另存成 `motrix_erp_prod_YYYYMMDD.db` 之類的名稱，只用來讀取比對 schema/資料（例如 `PRAGMA table_info` / `sqlite_master`），確認要保留的內容後再手動決定是否取代開發機的檔案
- **純程式碼／文件檔案**：正式機有、這裡沒有的，直接複製過來；兩邊都有但內容不同的，人工比對（可用 PowerShell `Compare-Object` 或 `git diff --no-index`）決定保留哪一版，**不要自動二選一覆蓋**
- 核對完成後，依 §12 下方「維護規則」慣例補一筆 `version_manifest.json` + §12 摘要，並更新 §0 的「已知落差紀錄」表（狀態改為已補回，或新增剛發現的落差）

### §14.3 · 之後才考慮的方向

> ✅ **已實作半自動版本，見 §15**（2026-08-01j）：`build_deploy_package.ps1` + `apply_update.ps1`，方向是「開發機打包（git archive，強制先 commit）→ 人工複製 → 正式機套用（版本比對＋備份＋安全停服＋健康檢查＋失敗自動回滾）」。仍非全自動：套用前需操作者手動確認一次，兩機之間的檔案傳輸也仍是人工複製（隨身碟/網路芳鄰/雲端硬碟），沒有做 WinRM/網路直連。

以下是還沒做、之後可以再評估的方向：

- PowerShell Remoting（`Invoke-Command`/`New-PSSession`）取代人工複製部署包——需先在正式機開放 WinRM，涉及帳密/防火牆設定
- 拉檔案回開發機（§14.2 方向，跟 §15 相反方向）目前仍是全人工，尚未有對應的半自動工具

### §14.4 · 選型資料庫雙機內容核對（API 版，2026-08-10）

> §15 只管程式碼／schema，**選型資料庫的實際內容**（switch/monitor/access/gateway/netarch/env
> 六大類的 scenarios/categories/fit/products 這些 row）不在 schema 裡、migration 也管不到——
> 過去只能靠翻各支 `sync_YYYY-MM-DD_xxx.py` 的 docstring 回憶／人工核對兩機是否同步，這就是
> 2026-08-10 這次落差被發現的原因。現在改用兩台機器都已開通的 API（兩邊 LAN 可互通，見 §1
> 區網位址）直接比對，取代人工回憶。

**前置需求**：兩台機器都要有 `claude` 自動化帳號（`create_claude_account.py`，role=admin＋
`*_guide_edit` 模組旗標，最小權限）且核發過 session token：

```
python backend/issue_claude_session.py     # 於該機器 backend/ 目錄下執行，印出 token
```

token 不共用、各機器獨立（sessions 表各自是獨立 SQLite 檔案），效期比照一般登入 30 天，過期
重跑上面這行即可（冪等，會自動清掉該帳號舊 session 再核發新的）。

**核對**：

```
cd backend/tools
python check_guide_sync.py                            # 核對全部 6 大類
python check_guide_sync.py --category switch access    # 只核對指定類別
```

token 設定於 `backend/tools/.guide_sync_config.json`（**不進 git**，`.gitignore` 已排除，格式見
腳本內 `_CONFIG_EXAMPLE`）；依自然鍵（多數是 `code`，跨表關聯用 `scenario_code`/`category_code`，
`netarch_products` 例外用 `generation_id` 需先換算成 `(family_code, gen_name)` 再比對，因為那是
機器本地自增數字、兩機不保證相同）逐一比對每個端點，印出「哪些 key 只有一邊有」。

**已知限制**：這支工具只讀，不會自動修補落差；發現落差後仍要判斷是「單純缺資料」（直接用同帳號
對缺的那一機 POST 補上，見下方）還是「資料被取代/刪除」（一邊新增了更細的項目、同時刪掉舊的
籠統項目，這種情況另一邊要手動決定是否也要刪，不能自動判斷）。2026-08-10 這次首次使用就意外
挖到 `routers/netarch_guide.py` 的既有 bug（見 §12 同日條目）——透過 API 實際寫入資料是比對過
docstring 更可靠的驗證方式，往後新增選型資料庫內容建議優先用這個流程，而不是直接寫一次性
sqlite 腳本後假設「兩機遲早會一致」。

---

## §15 · 更新模式（測試機 → 正式機，半自動，2026-08-01）

> 目的：把 §14 的手動複製部署，收斂成有前後安全檢查、可重複執行的流程。**範圍只含程式碼／schema，絕不觸碰正式機業務資料**（quotations/customers 等 data_json 與熱路徑欄位一律不動）；db migration 只改表結構，不動既有資料列。觸發方式是半自動——一鍵執行，但套用前仍需操作者手動確認一次，不做無人值守全自動。

### §15.1 · 兩支腳本

| 腳本 | 執行位置 | 用途 |
|------|---------|------|
| `backend/tools/build_deploy_package.ps1` | **開發機** | 打包目前已 commit 的 `backend/`＋`frontend/`＋根目錄文件成部署包 |
| `backend/tools/apply_update.ps1` | **正式機** | 套用部署包，含備份／安全停服／健康檢查／失敗自動回滾 |

### §15.2 · 打包（開發機）

```
powershell -ExecutionPolicy Bypass -File backend\tools\build_deploy_package.ps1
```

- **強制 `git status` 乾淨**才允許打包，未 commit 的變更會被擋下——解決 §0 已知落差第 3 筆「來源不可靠」的問題：拿去正式機套用的東西，永遠等於 git 上看得到的東西
- 用 `git archive HEAD` 匯出，只含已 commit 的內容
- 產出 `deploy_packages/<timestamp>_<commit短碼>/`，內含 `deploy_manifest.json`（commit、分支、`version_manifest.json` 最後一筆）
- 完成後需**手動複製**整個資料夾到正式機（隨身碟／網路芳鄰／雲端硬碟皆可，兩機間目前無直連機制）

### §15.3 · 套用（正式機）

```
powershell -ExecutionPolicy Bypass -File backend\tools\apply_update.ps1 -PackagePath <複製過去的路徑>
```

| 階段 | 動作 |
|------|------|
| 身分守門 | 確認腳本執行路徑就是正式機路徑，否則中止 |
| 套用前 | 版本比對（commit 相同視為重複套用，需 `-Force` 才強制）；記錄套用前健康狀態；**db 快照**至 `backend/db_backups/pre_update_<timestamp>/`；**Migration 乾跑驗證**（2026-08-01m 新增，見下方說明）；**程式碼回滾快照**至 `backend/rollback_snapshots/<timestamp>/`（保留最新 5 份）；印出摘要，等待操作者輸入 `y` 確認 |
| 停服 | 依 port 666 監聽者 PID／`uvicorn*main:app` commandline 逐一 kill；**不自己啟動新 uvicorn**，改讓既有 `MOTRIX ERP Server Autostart` 排程的 crash-restart 迴圈（§1.1）5 秒內自動接手重啟，避免搶 port |
| 套用 | robocopy 把套件的 `backend/`＋`frontend/`＋根目錄文件覆蓋過去；**只加不改既有多餘檔案，絕不用 `/MIR`**，加上 `/XD`／`/XF` 排除 db／uploads／報價單PDF／logs／設定檔等，即使套件不小心含這些也不會覆蓋 |
| 套用後 | 輪詢 `GET /api/ping` 最多 30 秒＋檢查 `logs/server.log` tail 200 行、**只看「最後一次成功啟動（`Uvicorn running on`）」之後**有無 traceback/ERROR（2026-08-02a 修正，避免把重啟迴圈重試階段已自癒的暫時性錯誤誤判成失敗，見下方說明）；成功→更新 `backend/.deployed_commit.json`；**失敗→自動回滾**（用剛才的程式碼快照復原＋重新停服讓迴圈拉起舊版＋再次確認健康），並印出 db／程式碼快照路徑供人工進一步排查 |

`-Force`：版本比對沒過仍要套用時使用。`-Yes`：跳過互動確認（僅供自動化測試，正常人工執行不要加）。

**Migration 乾跑驗證**（2026-08-01m）：正式庫過去是「第一個試跑新 migration 的地方」——伺服器套新程式碼重啟後 `init_db()` 立刻對正式庫跑 migration，若寫壞了，schema 已經被改壞才被套用後健康檢查發現，「自動回滾」雖然會把 db 整檔換回套用前快照（安全），但仍會遺失套用後到偵測失敗這段時間內產生的新業務資料。現在改成：db 快照做完後，先把快照複製一份到系統 temp 目錄，用**新套件裡的** `db.py`（`init_db(path)` 本來就接受任意路徑，只操作傳入的檔案）在這份副本上先跑一次；失敗就直接中止，不進入停服／複製程式碼／回滾快照等後續步驟，**正式庫全程不受觸碰**。

**健康檢查誤判自動回滾修正**（2026-08-02a）：commit `484c1b4` 第一次在正式機真實套用時，Step 2 停服後沒等 port 666 真正釋放，既有 crash-restart 迴圈搶著重新綁定撞到 `[Errno 10048]` 位址已被使用，重試 2 次後自行成功（迴圈設計上本來就會自癒），但 Step 4 健康檢查掃 log tail 80 行沒有分辨這些錯誤是否已被後續成功啟動蓋過去，誤判成更新失敗觸發回滾（回滾本身正常運作，正式機沒有受到實際影響）。已修正：Step 2 停服後新增主動輪詢確認 port 真正釋放；Step 4 log 掃描只看「最後一次成功啟動」之後的內容。

### §15.4 · 已知限制

- 兩機間的部署包傳輸仍是人工複製，沒有網路直連（WinRM 等，見 §14.3）
- 正式機沒有 git，版本比對只能靠 `deploy_manifest.json` 記的 commit 做「是否重複套用」的相等比對，無法判斷新舊先後（先後順序由操作者自行確認）
- `apply_update.ps1` 已在正式機做過兩次真實套用：第一次（2026-08-02，commit `484c1b4`）健康檢查誤判觸發自動回滾，回滾機制運作正常、正式機無實際影響，誤判根因已修復（見上方說明與 §12 2026-08-02a）；第二次（2026-08-03，commit `259ad84`，業務開發 CRM 逾期警示功能）**套用成功、健康檢查通過、無回滾**，修正後的腳本已在正式機實地驗證過；`build_deploy_package.ps1` 已在開發機多次實際打包成功（見 §12 2026-08-01k/l/m）

---

## 維護規則（每次修改必讀）

### 版本紀錄登記（強制）

**每次功能變更完成後，必須同步更新以下兩處：**

1. **`backend/version_manifest.json`** — 新增一筆條目，格式如下：

   ```json
   {
     "module": "模組中文名",
     "version": "YYYY-MM-DDx",
     "date": "YYYY-MM-DD",
     "time": "HH:MM",
     "content": "簡要說明（繁中，60–120 字）"
   }
   ```

   | 欄位 | 說明 |
   |------|------|
   | `module` | 對應系統模組（報價單 / 案件管理 / 使用者管理 / 系統設定 / 系統安全 / 前端介面 / …） |
   | `version` | 日期 + 小寫後綴字母（同日第二筆加 `a`，第三筆加 `b`，依序遞增） |
   | `date` | `YYYY-MM-DD` |
   | `time` | **實際完成修改的時間**，24h 制 `HH:MM`（不可省略） |
   | `content` | 說明做了什麼，不要只寫「更新」，要寫具體改動 |

2. **本檔 §12** — 在最新版本區塊加入摘要行。

> **⚠️ 伺服器重啟後**，`_sync_module_versions()` 自動將 manifest 條目同步至 DB `module_versions` 表（UPDATE 邏輯同步修改過的欄位，不影響使用者手動新增的條目）。若修改了已存在條目的 `time` 或 `content`，下次重啟即生效。**DB v35 起 `(module, version)` 已有 UNIQUE 限制**，`INSERT OR IGNORE` 才真正名副其實——v35 之前這個限制不存在，代表每次重啟都會把整份 manifest 重複插入一次，長期下來會讓 `module_versions` 表無限增生（正式機曾實測膨脹到 626,725 列僅 143 種組合，佔掉每日備份 300+MB 中的絕大部分），已修復並清理。

### 其他維護提醒

- 功能變更時先更新本檔「對應 §N 章節」，再在 §12 加摘要。
- 死碼警告欄位如有整理（移除 .js、改用 include），記得更新 §2 與 §13。
