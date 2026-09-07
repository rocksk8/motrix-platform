# MOTRIX ERP — 開發快速參考

> 允碩整合集創（統編 60575481）｜ Tel: 04-3610-6566 ｜ info@miactw.com  
> 文件版本：**2026-08-20**（承攬商匯款申請＋發票開立簽核單，DB v45/v46，見 §12）
> **§2/§7/§11/§13 已於 2026-09-01 依實際程式碼盤點（`db.py` CURRENT_VERSION=68、`git log` 最新 commit `8f40e4e`）補齊落後內容，§12 逐日 changelog 本身仍是最新的**（本文件是持續累積的活文件，不是單一時間點快照）；同日新增互補文件 `MOTRIX-ERP-ARCHITECTURE-MAP.md`（架構地圖＋建議＋踩坑索引）

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
| 2026-08-20 | 開發機當時無法連線，承攬商匯款申請／發票開立簽核單功能（DB v45/v46，見 §12）直接在正式機開發，開發機完全沒有這批程式碼 | ✅ 2026-08-23 已回推：`verify_manifest.py` 核對 43/43 相符、開發機本機啟動 server 驗證 `/api/ping`＋schema_version=52 正常後 `git commit`（累計至第 42 輪 2026-08-23q，DB 已到 v52，非僅 v45/v46） |

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
| `db.py` | 連線、`init_db()`、PRAGMA WAL、熱路徑欄位／索引；**2026-09-01 更正：CURRENT_VERSION=68**（本行長期未同步更新，之前記載的 46 已過時；v47–v68 詳細主題見 `MOTRIX-ERP-ARCHITECTURE-MAP.md` §4「資料庫演進索引」，含請款單/組織架構/案件階段正規化/專案併入案件管理/網路架構規劃書/自動化系統選型導覽/安全庫存/簽核代理人等；v32/v33 交換器選型導覽 `switch_guide` 表結構由正式機備份還原重建，詳見 db.py `_m032_switch_guide` 註解） |
| `helpers/` | 密碼、session、audit、notify、settings、弱密碼標記、`save_quotation_json()` |
| `archive.py` | 即時／每日／週備份；本機 SQLite 快照；**原子 JSON 寫入**（`_atomic_json_write`）；G: fallback |
| `backup_job.py` | 獨立備份腳本（Windows 工作排程器，不依賴 server） |
| `pdf_gen.py` | Edge Headless PDF；路徑讀 `system_settings["pdf_base_path"]`；**2026-09-07 起**所有 Edge 子行程呼叫（含 `network_plan_export.py`／`routers/reports.py`）共用 `helpers.EDGE_PDF_SEMAPHORE`（`BoundedSemaphore(3)`）限制同時執行數量，避免短時間多人觸發匯出時單機被一堆 Edge 行程拖垮 |
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
| 白名單 | `/api/ping` · `/api/auth/login` · `/api/auth/login/totp` · `/api/auth/logout` · `/api/system/version` |
| 其餘 `/api/**` | 需 `Authorization: Bearer {token}` |
| 回應標頭 | `X-Content-Type-Options` · `X-Frame-Options` · `Referrer-Policy` |
| **登入暴力破解** | per-IP rate limiting；5 次失敗鎖 15 分鐘；HTTP 429 含倒數；**鎖定狀態持久化** `login_rate_limit` 表（DB v11），重啟不失效 |

### §3.3b · TOTP 兩步驟驗證（自助啟用，DB v72，2026-09-07）

架構地圖 §6.2 建議事項——`users` 目前只有密碼＋Bearer token 單因子。採**自助啟用而非強制**：正式機 superadmin 是 jeff/corbin 兩位真人業主，若做成下次登入強制進入設定流程，部署當下他們手邊沒先裝好驗證 App 會直接被鎖在外面，屬於會中斷真實業務的風險（決策見 db.py `_m072_totp()` docstring）。任何角色皆可自助到「修改密碼」頁（`change-password.html`）啟用；`notif.js` 對 admin/superadmin 未啟用時顯示提醒 banner（`sessionStorage` 節流每分頁一次，純提醒不阻擋操作）。

```
setup（POST /api/auth/totp/setup）→ 產生密鑰，totp_enabled 仍是 0
  → enable（POST /api/auth/totp/enable，需輸入一次正確驗證碼）→ totp_enabled=1
    → 產生 10 組一次性救援碼，明文只在這次回應出現，DB 只存雜湊
登入：/api/auth/login 密碼正確但 totp_enabled=1 時不核發 session，
      回傳 {totpRequired, challengeToken}（process-global 記憶體，5分鐘過期，非 DB）
  → /api/auth/login/totp 送驗證碼或救援碼核實後才真正核發 session
      （6 位數字視為 TOTP code；其餘視為救援碼，比對雜湊後即時作廢）
```

| 項目 | 說明 |
|------|------|
| `users.totp_secret`/`totp_enabled`/`totp_recovery_codes` | DB v72，見 `_m072_totp()` |
| 停用 | 需重新輸入目前密碼確認（比照既有敏感操作慣例），不需再帶驗證碼 |
| 登入第二階段防暴力破解 | 每個 challenge 最多 5 次錯誤即作廢（需重新輸入密碼），錯誤同時也計入既有 per-IP 登入鎖定 |
| Demo 帳號 | 不支援（`auth_login()` 的 demo 分支在檢查 totp 之前就已回傳，設計上就不會走到） |

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
                   notification_muted（JSON 陣列，已退訂的 email 通知事件 key，DB v43，見 §12）,
                   department_id FK→departments(id)(nullable)（DB v48，見 §12 2026-08-22d）
divisions       -- 處（DB v48）：id, name UNIQUE, sort_order,
                   manager_user_id FK→users(id)(nullable)（處級主管，DB v49，見 §12 2026-08-22e）
departments     -- 部門（DB v48）：id, division_id FK→divisions(id), name（同處內 UNIQUE）,
                   sort_order, manager_user_id FK→users(id)(nullable)
                   ✅ 2026-09-01 更正：本欄位**已經**接進簽核邏輯（此處舊註記過時）——
                   `helpers/tiered_approval.py` 的 `resolve_department_manager()`/
                   `resolve_division_manager()` 會動態解析部門/處主管為額外簽核路徑，
                   四個 approval-settings 頁面與案件代辦事項簽核皆已套用，見 §12
                   2026-08-22g／2026-08-23d。
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
                         [{id,name,amount,note}]，DB v36，見 §5.7），invoice_no（發票號碼，DB v44），
                         files_json（承攬商報價/估價文件附件，DB v60，2026-08-25，見 §5.9）

contractor_payment_vouchers -- 承攬商匯款申請（DB v45，見 §5.9，2026-08-20）
  id, voucher_no PK（PV-YYYYMM-NNN）, dispatch_id FK→contractor_dispatches(id) UNIQUE（強制 1:1，
  且僅完工派發可產生）, quote_no, vendor_id FK→vendor_contractors(id)(nullable),
  status('草稿'|'待審核'|'簽核中'|'已核准'), snapshot_json（建立當下凍結：承攬商名稱/統編/
  銀行帳戶/存簿影本（讀自 vendor_contractors.data_json）＋每位外包名單人員各自的銀行
  帳戶/存簿影本（建立當下另外查 contractors 表，2026-08-20 起）＋派發品項/金額，不隨
  來源異動回頭改變）, data_json（approval{tiers...}，獨立簽核流程，
  system_settings key 'contractor_voucher_approval_flow'）,
  is_paid/paid_by/paid_at/paid_log（財務「已匯款」標記，獨立於 status，比照出貨單「已核准」
  跟「已回簽」是兩個獨立狀態）, export_count, export_log, created_by, created_at, updated_at

invoice_vouchers     -- 發票開立簽核單（DB v46/v47，見 §5.9，2026-08-20）
  id, voucher_no PK（IV-YYYYMM-NNN）, quote_no, scope('amount'|'items'，2026-08-20 起，取代原本
  的 'single'|'all'）, amount（REAL，DB v47 新增，這張申請要開多少錢的唯一權威數字，供
  SUM() 直接算「這張報價單已申請多少／還剩多少可申請」，不必每次解析全部 snapshot_json）,
  payment_idx（scope 改版後對新資料不再使用，欄位保留不刪）,
  status('草稿'|'待審核'|'簽核中'|'已核准'，核准即定稿）, snapshot_json（建立當下凍結：
  客戶/案件/quoteItems 報價品項參考／scope='items' 時的 selectedItems 明細）,
  data_json（approval{tiers...}，獨立簽核流程，system_settings key
  'invoice_voucher_approval_flow'）, export_count, export_log, created_by, created_at, updated_at

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
- **簽核流程**：2026-08-24 起預設與報價單／發票開立簽核單／請款單共用 `system_settings.unified_approval_flow`；2026-08-28 起可在「簽核設定」頁（`approval-settings.html`）的套用範圍選單勾掉，改成出貨單自己獨立的 `system_settings.shipping_approval_flow`（同一頁面內展開編輯，不再有獨立的 `shipping-approval-settings.html`，見 §12 2026-08-28）；tiers 依序簽核，有設定流程時申請人可自簽；**無流程時僅 superadmin 可簽（含自簽）**——與報價單「無流程時禁止申請人自簽」的規則刻意不同（2026-08-01g 調整，見 §12）
- 全部簽核完成 → 狀態 `已核准`，背景觸發 PDF 存檔（`pdf_gen.py _generate_shipping_pdf`）
- **已回簽**：`已核准` 狀態才可切換；`signed-toggle` 為嚴格 toggle（已回簽不可重複標記，需先取消），每次切換完整記錄至 `signed_log`（誰、何時、動作、備註），案件管理 UI 可展開查看完整歷程
- PDF 匯出與報價單同一套機制：`GET .../pdf-download` 產生 bytes（不記錄），`POST .../export` 另外累計 `export_count`/`export_log`
- **預覽**：`GET .../pdf-download` 無狀態限制，任何狀態皆可預覽（案件管理 UI「預覽」按鈕，iframe+blob 顯示，不呼叫 `/export`）；預覽 Modal **不提供下載選項**（避免與已核准後的正式匯出/記錄流程混淆），要下載仍須回到列表上已核准狀態的「下載 PDF」按鈕；非已核准狀態下 PDF 本身（`pdf_gen.py _build_shipping_html`）會帶浮水印＋警告橫幅（比照報價單預覽稿樣式，文案「出貨單預覽稿／尚未正式核准」），已核准後乾淨無浮水印
- **收件人聯絡人快選**：新增/編輯 Modal 內若案件所屬客戶（`quotations.data_json.customerId`，或退而用 `customer_name` 比對客戶清單）有登記聯絡人，顯示「選聯絡人」下拉快選；點選僅覆寫欄位值，收件人欄位本身仍可自由輸入
- 刪除僅限 `草稿` 狀態（保留已進入簽核/已回簽的歷程）
- Demo 模式 PDF 隔離目錄：`backend/_demo_shipping_pdf_archive`

### §5.9 · 承攬商匯款申請／發票開立簽核單（2026-08-20）

兩個獨立於報價單/出貨單的財務憑證流程，架構直接沿用 §5.8 出貨單的 tiers 簽核＋PDF＋匯出紀錄模式，`routers/contractor_vouchers.py`／`routers/invoice_vouchers.py`。

**承攬商匯款申請**（案件管理承攬商 tab，`contractor_payment_vouchers`）：

```
草稿 → 待審核 → 簽核中 → 已核准
                            ↓
                      已匯款（財務勾選，獨立於 status，比照出貨單「已核准」跟「已回簽」，
                              可取消回已核准；已匯款不可撤銷核准）
```

- `status='accepted'`（已驗收）或 `status='completed'`（完工）的派發可產生申請（2026-08-20 使用者實測後放寬，原本僅完工可申請），且**一筆派發僅能對應一張申請**（`dispatch_id` UNIQUE，雙重保護：DB 層 + API 層檢查）
- 建立當下把承攬商名稱/統編/銀行帳戶（代碼/名稱/分行/戶名/帳號/存簿影本，讀自 `vendor_contractors.data_json`）/派發品項/`invoice_no`/金額**全部快照**進 `snapshot_json`，之後來源資料異動不會回頭改變已產生的憑證
- **外包名單人員的銀行帳戶／存簿影本**（2026-08-20 起）：派發本身的 `personnel_json` 只快照 id/name/amount/note，不含銀行資訊；建立憑證當下另外查一次 `contractors` 表（外包名冊）取得每位人員目前的 `bank_code`/`bank_name`/`bank_branch`/`bank_account_name`/`bank_account_number`/`bank_passbook_image`，一併寫入 snapshot；查無資料（例如人員已被刪除）就留空，不擋建立。PDF 上每位外包人員各自一張帳戶卡片＋存簿縮圖，供財務逐一核對匯款
- `routers/vendor_contractors.py` `delete_dispatch()` 新增守門：已產生憑證的派發不可刪除，回 409（避免撞上 FK 約束產生原始 500）
- 獨立簽核設定：`system_settings.contractor_voucher_approval_flow`（`contractor-voucher-approval-settings.html`，superadmin）
- 全部簽核完成 → 狀態 `已核准`，背景觸發 PDF 存檔（`pdf_gen.py _generate_contractor_voucher_pdf`）；PDF 含銀行匯款資訊＋簽核歷程表格
- Demo 模式 PDF 隔離目錄：`backend/_demo_contractor_voucher_pdf_archive`

**發票開立簽核單**（案件管理案件資訊 tab／款項明細，`invoice_vouchers`）：

```
草稿 → 待審核 → 簽核中 → 已核准（定稿，無額外財務結案節點）
```

- **scope='amount'（自訂金額）或 scope='items'（自訂品項+數量）**（2026-08-20 重新設計，取代原本只能挑既有款項期別的 `single`/`all` 模式）：使用者反映很多案件是「先開發票才能收款」，需要能自訂任意金額或自訂品項+數量申請，不受限於報價單既有的款項排程分期
- **剩餘可申請額度追蹤，防止重複/超額請款**：`GET /invoice-vouchers/remaining?quote_no=` 即時計算「合約總額 - 這張報價單所有既有 invoice_vouchers 的 `amount` 加總（**含草稿**，草稿就鎖額度，2026-08-20 使用者明確選擇，避免同時建立造成超額，見 `routers/invoice_vouchers.py _quote_remaining()`）」= 剩餘可申請金額；`scope='items'` 額外逐品項追蹤已申請數量／剩餘數量（同樣含草稿）。建立時後端會二次驗證（金額超過剩餘 409、品項數量超過剩餘 409），不只是前端擋
- `amount`（DB v47 新增的真實 SQL 欄位）是唯一權威金額數字，不論哪種 scope 都會寫入，`_quote_remaining()` 用 `SUM(amount)` 直接算，不必解析全部 snapshot_json
- 建立當下把客戶名稱/統編/案件名稱**全部快照**進 `snapshot_json`；`scope='items'` 時額外快照 `selectedItems`（實際要開的品項+數量+金額，金額可由使用者自行調整，不強制等於數量×單價）
- **報價單品項參考**（`scope='amount'` 時顯示，`scope='items'` 時因為 `selectedItems` 本身就是實際品項不重複顯示）：`snapshot_json.quoteItems` 快照報價單 `items[]`，**只帶客戶看得到的欄位**（description/brand/qty/unit/unitPrice/amount/notes），刻意排除 `cost`/`margin`/`unitPriceOverride` 等內部機密欄位，避免成本/毛利外流到這份財務單位使用的文件；PDF 對應顯示「三、申請品項明細」（items 模式）或「三、申請金額」+「四、開票品項參考」（amount 模式）
- **簽核流程**：2026-08-24 起預設與報價單／出貨單／請款單共用 `system_settings.unified_approval_flow`；2026-08-28 起可在「簽核設定」頁套用範圍選單勾掉，改成自己獨立的 `system_settings.invoice_voucher_approval_flow`（同一頁面內展開編輯，不再有獨立的 `invoice-voucher-approval-settings.html`，見 §12 2026-08-28）
- 全部簽核完成 → 狀態 `已核准`，背景觸發 PDF 存檔（`pdf_gen.py _generate_invoice_voucher_pdf`）
- Demo 模式 PDF 隔離目錄：`backend/_demo_invoice_voucher_pdf_archive`

**共同點**：兩者的簽核 tiers 純邏輯共用 `helpers/tiered_approval.py`（2026-08-22 起，見 §12 同日 changelog）；PDF 預覽（`GET .../pdf-download`）任何狀態皆可看、未核准帶浮水印警告橫幅；下載才計入 `export_count`/`export_log`（`POST .../export`）；刪除僅限草稿狀態；`audit-log.html`／`users.html` 通知偏好已比照出貨單補齊對應項目；跟報價單一起整合進統一簽核佇列頁 `approval-queue.html`（2026-08-20j，見 §12）；`approve`/`reject` 端點不限定 admin/superadmin 角色才能操作，改成純粹依「是否為當層簽核人員」判斷（2026-08-20k 修正，比照報價單原本就有的做法）。**簽核逾期催辦**（2026-08-21b，見 §12）：三種文件共用同一套規則，卡在簽核柱列超過工作日 1/3/5 天分級寄信催辦（1/3 天各一次，3 天起同步通知 superadmin，5 天以上每個工作日重複寄），`routers/daily_tasks.py _check_approval_reminders()`，掛在既有每日 08:00 排程裡。

---

## §6 · Sidebar 結構

```
主選單     儀表板
業務       業務開發（dev-crm.html, dev_crm 模組旗標或 admin+）/ 報價單（含簽核佇列 ?view=queue） /
           案件管理（⚠️ 「專案管理」已於 2026-08-26 併入案件管理，projects.html 已刪除，不再是獨立項目）
選型資料庫  場域選型導覽 / 網路架構選型導覽 / 交換器選型導覽 / 監控系統選型導覽 /
           門禁系統選型導覽 / 自動化系統選型導覽（automation-guide.html，DB v65，2026-08-26 起第七類，
           本文件先前未記載）/ 涵蓋度總覽（selection-db-overview.html, admin+ 限定）
廠商與採購 客戶 / 供應商 / **承攬商** / 料號 / **庫存管理**（inventory.html, inventory 模組旗標或 admin+）/ 採購
設備       設備登載 / 保固追蹤 / 網路架構規劃書（network-plans.html，DB v64，可綁案件也可獨立建立，netplan_edit 模組或 superadmin，本文件先前未記載，詳見 §7.12／`NETWORK-PLAN-MODULE-DESIGN.md`）
財務       應收帳款 / 營運報表（admin+ 或含 reports 模組；**2026-08-31 起內含第 13 個頁籤「出納」**，`cashier.html` 舊網址已退役為導向 stub）
工作       工作日誌（非 viewer 或含 work_log 模組） / 每日工作事項（非 viewer 或含 daily_task 模組）
系統       使用者 / 組織架構（org-structure.html，DB v48，本文件先前未記載）/ 簽核設定（superadmin）/
           簽核代理人（approval-delegates.html，DB v67，任何人可自助設定，本文件先前未記載）/
           出貨單簽核設定（superadmin）/ 歷史紀錄 / 版本紀錄 / Schema 狀態（superadmin）
```

- 簽核佇列不在 sidebar，在報價單內 tab
- 銷售訂單已移除（併入案件財務）
- `reports`：`admin+` 或含 `reports` 模組的使用者可見
- `work_log` / `daily_task`：非 viewer 或明確帶對應模組者可見（相容既有帳號）
- `承攬商管理`：`admin+`（`cPr` 旗標，同採購）可見；`vendor-contractors.html`
- **模組通知 badge**：所有模組 nav 項目（含子項）均有藍色 `sb-mod-*` badge，由 `_fetchModuleCounts()` 根據 `motrix_module_seen` 顯示其他人的更新計數；廠商採購/設備/財務各組同步顯示同一模組計數
- **選型資料庫**（2026-08-01 獨立成頂層 sidebar 區塊，不再掛在「業務」底下；`SELECTION-DB-INDEX.md` 是這個產品線的總索引，現為**七大類**，見下）：
  - **場域選型導覽**：`env-guide.html`；檢視 `env_guide` 模組旗標或 admin+（`cEnvG` 旗標）；編輯（新增/修改/刪除場域、建議、連結）與 Excel 匯出入另需 `env_guide_edit` 模組旗標或 superadmin；`users.html` 可分別授予兩者；**無** 模組通知 badge（資料變動頻率低，未接 `_fetchModuleCounts()`）
  - **網路架構選型導覽**：`netarch-guide.html`；檢視 `netarch_guide` 模組旗標或 admin+（`cNetG` 旗標）；編輯需 `netarch_guide_edit` 或 superadmin；瀏覽邏輯與場域選型導覽不同——**先選技術族系方塊，再看世代橫向對照卡片**（非矩陣/篩選），選型資料庫第二個上線的類別
  - **交換器選型導覽**：`switch-guide.html`；檢視 `switch_guide` 模組旗標或 admin+（`cSwitchG` 旗標）；編輯需 `switch_guide_edit` 或 superadmin；選型資料庫第三個上線的類別
  - **監控系統選型導覽**：`monitor-guide.html`；檢視 `monitor_guide` 模組旗標或 admin+（`cMonitorG` 旗標）；編輯需 `monitor_guide_edit` 或 superadmin；選型資料庫第四個上線的類別（2026-08-09），資料形狀與交換器選型導覽相同（相機分類×場域情境矩陣），第一批資料為 UniFi Protect G6 世代
  - **門禁系統選型導覽**：`access-guide.html`；檢視 `access_guide` 模組旗標或 admin+（`cAccessG` 旗標）；編輯需 `access_guide_edit` 或 superadmin；選型資料庫第五個上線的類別（2026-08-09），資料形狀同上（元件分類×場域情境矩陣），第一批資料為 UniFi Access
  - **自動化系統選型導覽**：`automation-guide.html`；檢視 `automation_guide` 模組旗標或 admin+；編輯需 `automation_guide_edit` 或 superadmin；DB v65，2026-08-26 起選型資料庫第七類，資料形狀同交換器/監控/門禁（情境×分類矩陣），見 §7.14。**本文件先前完全未記載此類別，2026-09-01 補上**
  - 上述類別在**歷史紀錄**（`audit-log.html`）與**版本紀錄**（`module-versions.html`）皆已比照其餘模組補上對應的 optgroup／actionLabel／色碼（teal 色系＋🧭 圖示，共用同一識別色，強調同屬一個產品線而非各自獨立模組）
  - **涵蓋度總覽**（2026-08-09）：`selection-db-overview.html`；admin+ 限定，無獨立模組旗標；彙總「品牌/型號目錄」型類別（不含場域選型導覽——資料形狀是情境×分層文字建議而非品牌目錄）在各世代/分類底下的品牌數與產品數，紅/黃/綠三色標示完全空白／偏薄弱／足夠；**不新增後端 API**，純前端呼叫既有各類別 GET 端點彙總而成；**是否已納入自動化系統選型導覽（第七類）尚未查證，之後碰這頁時先確認**
- **簽核設定**：`approval-settings.html`；superadmin 限定；2026-08-28 起單一頁面涵蓋全部五種文件類型（報價單／出貨單／發票開立簽核單／請款單／承攬商匯款申請）——頁面上方是套用範圍多選選單，勾選的類型共用「統一簽核流程設定」，取消勾選的類型各自在同一頁展開獨立編輯區塊；不再有各自獨立的 `shipping-approval-settings.html`／`invoice-voucher-approval-settings.html`（`contractor-voucher-approval-settings.html` 仍保留獨立頁面，見 §12 2026-08-28）；出貨單本身不是獨立 sidebar 項目，掛在「案件管理」頁面內的「出貨單」分頁，沿用 `case_manage`/`cCM`/`sb-mod-case`
- **簽核代理人**（2026-08-28，DB v67）：`approval-delegates.html`；任何人可自助委託簽核權限給他人，superadmin 可代替他人設定；核心解析 `helpers/tiered_approval.py::active_delegators_for()`，見 §7.13
- **組織架構**：`org-structure.html`；DB v48，處→部門二層；`manager_user_id` 已接入簽核流程動態解析（§4.1 已更正舊註記）
- **Schema 狀態**（2026-08-01）：`schema-status.html`；superadmin 限定；**純唯讀**診斷頁，顯示目前 db 版本 / 目標版本、狀態（✓最新／⚠尚未同步）、最後更新時間、完整 migration 清單；**全頁無任何操作按鈕或表單**——migration 於伺服器啟動時自動套用，此頁不提供「觸發乾跑」之類的操作；資料來源 `GET /api/system/schema-status`

---

## §7 · API 速查（base `/api`）

### §7.1 · Auth / Users

| Method | Path | 說明 |
|--------|------|------|
| GET | /ping | 心跳 |
| POST | /auth/login | 回傳含 `mustChangePassword`；rate limit 保護；`totp_enabled` 時改回傳 `{totpRequired,challengeToken}`，不核發 session，見 §3.3b |
| POST | /auth/login/totp | 登入第二階段：`{challenge_token, code}`，`code` 為 6 位數 TOTP 或救援碼；白名單路徑（無 Bearer） |
| GET | /auth/totp/status | 目前使用者是否已啟用 TOTP（需登入） |
| POST | /auth/totp/setup | 產生新密鑰＋QR code（需登入，任何角色） |
| POST | /auth/totp/enable | `{code}` 驗證後才真正啟用，回傳 10 組一次性救援碼（僅此次可見明文） |
| POST | /auth/totp/disable | `{password}` 確認身分後停用 |
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
| GET/PUT | /settings/approval-flow | 統一簽核流程（`unified_approval_flow`），PUT 限 superadmin |
| GET/PUT | /settings/approval-flow-scope | 五種文件類型套用範圍（統一／獨立），PUT 限 superadmin，2026-08-28 |
| GET/PUT | /settings/approval-flow/{doc_type} | 該文件類型自己獨立的簽核設定（`{doc_type}_approval_flow`），doc_type ∈ quotation/shipping/invoice_voucher/payment_request/contractor_voucher，PUT 限 superadmin，2026-08-28 |
| GET/PUT | /settings/cloud-backup-target | 雲端備份目標（`local_drive`／`s3`），PUT 限 superadmin，見 §8.0，2026-09-07 |
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
| （無專屬 settings 端點） | | 簽核流程走統一設定 `/settings/approval-flow` 或（獨立時）`/settings/approval-flow/shipping`，見 §7.3／§12 2026-08-28 |

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

### §7.11 · 承攬商匯款申請／發票開立簽核單（DB v45/v46，見 §5.9，2026-08-20）

| Method | Path | 說明 |
|--------|------|------|
| GET | /contractor-vouchers?quote_no= | 依案件列出承攬商匯款申請摘要（需登入，不含 snapshot） |
| GET | /contractor-vouchers/{voucher_no} | 完整明細（含 snapshot/approval/paid_log/export_log） |
| POST | /contractor-vouchers | `{dispatch_id}` 建立草稿（admin+）；僅 `completed` 派發且尚無憑證可建立；`voucher_no` 由 `next_entity_code(...,'PV',code_col='voucher_no')` 產生 |
| DELETE | /contractor-vouchers/{voucher_no} | 刪除（admin+；非草稿 409） |
| POST | /contractor-vouchers/{voucher_no}/submit | 送出審核（admin+） |
| POST | /contractor-vouchers/{voucher_no}/approve | 簽核（當層簽核人依序；無流程時僅 superadmin） |
| POST | /contractor-vouchers/{voucher_no}/reject | 退回草稿 `{note?}` |
| POST | /contractor-vouchers/{voucher_no}/revoke-approval | 撤銷已核准 `{note?}`；已匯款不可撤銷 |
| GET | /contractor-vouchers/{voucher_no}/pdf-download | Edge PDF（不記錄匯出） |
| POST | /contractor-vouchers/{voucher_no}/export | 記錄匯出人/時間/次數 |
| POST | /contractor-vouchers/{voucher_no}/paid-toggle | `{action:'pay'|'unpay', note?}`；僅已核准可標記，獨立於 status |
| GET/PUT | /contractor-vouchers/settings/approval-flow | 專屬簽核流程設定（PUT 限 superadmin）；讀寫的 key 固定是 `contractor_voucher_approval_flow`，跟送審當下實際生效與否無關（生效與否看 §12 2026-08-28 的套用範圍設定） |
| GET | /invoice-vouchers?quote_no= | 依案件列出發票開立簽核單摘要 |
| GET | /invoice-vouchers/remaining?quote_no= | **建立申請前查剩餘額度**（含合約總額/已申請/剩餘金額＋各報價品項的已申請/剩餘數量）；⚠️ 註冊順序必須在 `/{voucher_no}` 之前，否則會被當成 voucher_no 吃掉 |
| GET | /invoice-vouchers/{voucher_no} | 完整明細（含 snapshot/approval/export_log） |
| POST | /invoice-vouchers | `{quote_no, scope:'amount'\|'items', amount?, items?:[{itemId,qty,amount}]}` 建立草稿（admin+，2026-08-20 重新設計）；金額或選取品項超過剩餘可申請額度會 409；`voucher_no` 由 `next_entity_code(...,'IV',code_col='voucher_no')` 產生 |
| DELETE | /invoice-vouchers/{voucher_no} | 刪除（admin+；非草稿 409；刪除即釋放其佔用的額度，因為剩餘額度是即時從既有列加總算出） |
| POST | /invoice-vouchers/{voucher_no}/submit | 送出審核（admin+） |
| POST | /invoice-vouchers/{voucher_no}/approve | 簽核（同上規則） |
| POST | /invoice-vouchers/{voucher_no}/reject | 退回草稿 `{note?}` |
| POST | /invoice-vouchers/{voucher_no}/revoke-approval | 撤銷已核准 `{note?}` |
| GET | /invoice-vouchers/{voucher_no}/pdf-download | Edge PDF（不記錄匯出） |
| POST | /invoice-vouchers/{voucher_no}/export | 記錄匯出人/時間/次數 |
| （無專屬 settings 端點） | | 簽核流程走統一設定 `/settings/approval-flow` 或（獨立時）`/settings/approval-flow/invoice_voucher`，見 §7.3／§12 2026-08-28 |

### §7.12 · 網路架構規劃書（DB v64，2026-08-26，見 §5 補充／`NETWORK-PLAN-MODULE-DESIGN.md`）

| Method | Path | 說明 |
|--------|------|------|
| GET | /network-plans | 列表（需登入） |
| GET | /network-plans/{plan_id} | 完整明細（10 分頁資料） |
| GET | /quotations/{quote_no}/network-plan | 依案件查詢對應規劃書 |
| POST | /network-plans | 建立（`netplan_edit` 模組或 superadmin） |
| PUT | /network-plans/{plan_id} | 更新 |
| PATCH | /network-plans/{plan_id}/status | 狀態切換 |
| DELETE | /network-plans/{plan_id} | 刪除 |
| GET | /network-plans/{plan_id}/export/excel \| /export/pdf | 匯出（10 分頁 Excel／Edge PDF，PDF 自動內嵌拓樸圖，見下） |
| POST | /network-plans/{plan_id}/import/excel | 匯入（分頁名稱＋欄位表頭比對，無法辨識分頁於 warnings 明確提示） |
| POST | /network-plans/{plan_id}/topology-preview | 拓樸圖即時預覽（不落地存檔），2026-09-04 新增，見 §12 同日條目 |

可綁 `quote_no` 也可獨立建立；**與 §7.6/§7.7 的「網路架構選型導覽」`netarch_guide` 是完全不同的兩個模組**，勿混淆。

**拓樸圖（2026-09-04）**：`backend/network_plan_topology.py::build_topology_svg()` 依「設備清單」＋「交換器 Port 對應」自動繪圖，PDF 匯出自動內嵌。獨立無狀態的「快速拓樸圖產生器」（不填規劃書、單純產圖）走另一組路由 `routers/network_plans_quick.py`（`POST /api/network-plans-quick/preview` \| `/pdf`，刻意用 `-quick` 前綴避免跟本節 `{plan_id}` 參數化路由衝突），對應頁面 `frontend/pages/topology-quick.html`，資料只存瀏覽器 localStorage、不寫入 `network_plans` 表。

### §7.13 · 簽核代理人（DB v67，2026-08-28）

| Method | Path | 說明 |
|--------|------|------|
| GET | /approval-delegates | 列表（需登入） |
| POST | /approval-delegates | 新建委託（任何人可自助設定，superadmin 可代設） |
| PATCH | /approval-delegates/{delegate_id}/deactivate | 停用委託 |

核心解析邏輯 `helpers/tiered_approval.py::active_delegators_for()`；`check_approve_permission()`/`check_reject_permission()` 新增可選 `conn` 參數才會檢查代理權，5 個 router／10 個呼叫點皆已接上。

### §7.14 · 自動化系統選型導覽（DB v65，2026-08-26 起，選型資料庫第七類）

情境×分類矩陣結構，與 switch/monitor/access/gateway 四類完全同款樣板（CRUD 端點命名/權限模式一致，`automation_guide_edit` 模組或 superadmin 可編輯）：

| Method | Path |
|--------|------|
| GET / POST / PUT / DELETE | /automation-guide/scenarios[/{code}] |
| GET / POST / PUT / DELETE | /automation-guide/categories[/{code}] |
| GET / POST / PUT / DELETE | /automation-guide/fit[/{id}] |
| GET / POST / PUT / DELETE | /automation-guide/products[/{id}] |

§6 Sidebar「選型資料庫」區塊現為**七大類**（原六類＋本類），`selection-db-overview.html` 涵蓋度總覽頁是否已納入本類需之後確認。

### §7.15 · 個人化清單偏好（DB v56）

| Method | Path | 說明 |
|--------|------|------|
| GET | /list-prefs/{list_key} | 讀取使用者個人清單偏好（欄位顯示/排序記憶） |
| PUT | /list-prefs/{list_key} | 更新 |

### §7.16 · 案件代辦事項 / 出納彙總視圖

| 模組 | Method+Path | 說明 |
|---|---|---|
| 案件代辦事項（`case_action_items.py`，DB v62 `_m062_case_project_merge`） | `GET/POST /quotations/{quote_no}/action-items`、`PUT/DELETE .../action-items/{item_id}`、`PATCH .../action-items/{item_id}/approve` | 取代舊 `project_logs.action_items` JSON blob；兩階段簽核（`stage1_approver`/`stage2_approver`），主管解析比照 `_m050_project_department()` 既有查表 pattern |
| 出納彙總（`cashier.py`） | `GET /cashier/payable-queue \| receivable-queue \| summary \| execution-history \| export` | **2026-08-31 起併入 `reports.html` 第 13 個頁籤「出納」**（`?tab=cashier` 深連結），獨立 `cashier.html`/`cashier.js` 已退役為導向 stub；本質是 §5.9 財務三憑證流的**唯讀彙總層**，非獨立資料源 |

### §7.17 · T100（鼎新）傳票批次匯出（2026-09-01，DB v69，見 §12 同日條目）

**2026-09-02 UX 調整（純前端，無 DB/API 變動）：** 使用者反映 T100 匯出/設定原本埋在「資金水位」頁籤最底下太隱蔽，改成 `reports.html` 獨立的第 14 個頁籤「T100匯出」（`showT100Tab()`，切換進來自動預覽本期待確認事件）。另外三個「標記已付款/已收款」Modal（`case-management.html`／`reports.html`出納分頁／`inventory.html`）讀取銀行帳戶清單的 `loadT100BankAccounts()` 改成每次開啟 Modal 都重新 fetch（不再 cache-once）——superadmin 在 T100 設定頁新增/修改銀行帳戶後，其他人下一次開啟任一個標記視窗就會看到最新清單，三處共用同一份設定、即時連動，不用整頁重新整理。

| Method | Path | 說明 |
|--------|------|------|
| GET | /settings/t100-export-config | 科目代號對照設定（admin+ 可查閱） |
| PUT | /settings/t100-export-config | 更新科目代號（superadmin only） |
| GET | /reports/t100-export/vouchers?start=&end= | 現金基礎傳票批次匯出 Excel（admin+），涵蓋已收款發票＋已匯款承攬商費用，刻意排除請款單；**已標記已匯入的事件自動排除** |
| GET | /reports/t100-export/preview?start=&end= | 預覽本期尚未標記已匯入的事件（JSON，非 Excel），供財務正式標記前核對筆數/金額 |
| POST | /reports/t100-export/confirm | `{start,end}`；財務確認該區間候選事件已實際匯入 T100，標記後永久排除於之後匯出/預覽（除非撤銷）；冪等 |
| GET | /reports/t100-export/confirmed?start=&end= | 已標記已匯入的事件清單（稽核／複核用） |
| POST | /reports/t100-export/unconfirm | `{sourceType,sourceKey}`；撤銷單一事件的已匯入標記（誤標記時的救援手段） |

`backend/routers/accounting_export.py`；每筆事件產生的傳票天生借貸平衡；科目代號預設全部留白，需 superadmin 依貴公司 T100 實際設定填入才具備直接匯入意義。**匯出≠已匯入**：`t100_export_confirmations` 表（DB v69）獨立追蹤「財務確認已實際匯入 T100」的事件，用 `(source_type, source_key)` 穩定識別碼（`quotation_payment` → `{quote_no}::{invoiceNo}`；`contractor_voucher` → `voucher_no`；`stock_batch` → `batch_no`），不是每次匯出重算的 AR0001/AP0002/PC0003 流水號。

**事件來源第三類：料件/設備進貨已付款（2026-09-01 同輪新增，DB v70 `stock_batches`，端點見 §7.18）**——過去 `stock_items`（序號級庫存）只有共用字串 `batch_no`，沒有獨立批次表頭，供應商/發票號/付款狀態完全沒地方放。新增 `stock_batches` 表頭，既有批次全部回填但 `is_paid` 一律預設 0（系統過去從未追蹤這件事，不能假設已付款，見 `db.py::_m070_stock_batches()` docstring）——**首次啟用這個功能時，財務需要回頭逐批確認歷史進貨是否已付款**，之後才會逐漸準確反映在 T100 匯出裡。

**科目代號分維度設定（2026-09-01 同輪擴充，DB v71）：**
- **依銀行帳戶**：設定頁維護 `bankAccounts: [{name, acctCode}]` 清單，但匯出計算**不查這份清單**——直接讀「標記已付款/已收款當下」寫進各筆交易自己身上的欄位（`contractor_payment_vouchers.paid_bank_account_name/code`、`stock_batches.paid_bank_account_name/code`、報價單款項 JSON 的 `bankAccountName/Code`，皆為 DB v71 新增，比照既有 `paidBy/paidAt` 快照精神——之後改設定頁清單不會回頭影響已標記的舊交易）。三個「標記已付款/已收款」UI（`case-management.html`「標記已匯款」Modal、`reports.html`「出納」分頁的標記已匯款/已收款 Modal、`inventory.html`「標記已付款」Modal）皆已加上銀行帳戶下拉選單（選填）。
- **依料件分類**：`inventoryExpenseAccounts: {分類名稱: 科目代號}`（鍵對應 `parts.py::PART_CATEGORIES`），這個**是**即時查表（不快照）——分類本身不會變，財務事後更正某分類科目代號，未確認的舊事件會一起套用新值。
- 其餘科目（銷貨收入/銷項稅額/承攬商費用/部門別/傳票別）維持全公司單一設定。

**銀行帳戶欄位自動帶入預設值（2026-09-02 新增，無 DB migration）：** 使用者要求「標示已匯款須帶入當時填寫或是預設的匯款帳戶」——三個標記 Modal 開啟時，銀行帳戶下拉不再一律空白「未指定」，依序嘗試：①查這個對象（承攬商/供應商/客戶）上一次標記時用的帳戶 ②查無則退回 `t100-export-config` 新增的 `defaultBankAccountCode`（系統預設帳戶，設定頁「🏦 銀行帳戶清單」卡片每列可點 ☆ 設為預設）③兩者都沒有才維持空白；使用者仍可手動改選，不是強制值。三支新端點：

| Method | Path | 說明 |
|--------|------|------|
| GET | /contractor-vouchers/last-paid-bank-account?vendor_id= | 該承攬商上次已匯款用的帳戶 |
| GET | /inventory/batches/last-paid-bank-account?supplier_id= | 該供應商上次已付款用的帳戶 |
| GET | /quotations/last-received-bank-account?customerName= | 該客戶（依 `customer_name` 熱路徑欄位比對）上次已收款用的帳戶；⚠️ 註冊在 `GET /quotations/{quote_no}` 之前，避免被當成 quote_no 吃掉 |

三支皆純讀取、需登入不需要 admin+，查無資料回傳 `{"name":"","acctCode":""}` 不噴錯。前端 `reports.js`/`case-management.js`/`inventory.html` 各自新增 `_resolveDefaultBankAccount()` helper 呼叫對應端點。

### §7.18 · 進貨批次供應商/發票/付款狀態（DB v70，2026-09-01）

| Method | Path | 說明 |
|--------|------|------|
| POST | /inventory/batches | 建立進貨批次（既有端點擴充，admin+），新接受 `supplier_id`/`invoice_no`（選填），一併寫入 `stock_batches` 表頭 |
| GET | /inventory/batches | 批次列表（既有端點擴充），新回傳 `supplier_id`/`supplier_name`/`invoice_no`/`is_paid`/`paid_by`/`paid_at`/`note`；`qty`/`total_cost` 仍即時從 `stock_items` 群組加總，不信任表頭快取 |
| GET | /inventory/batches/{batch_no} | 單批明細（既有端點擴充），新增回傳 `header`（`stock_batches` 表頭完整內容） |
| PUT | /inventory/batches/{batch_no} | 編輯批次層級屬性（供應商/發票號/備註，admin+），不動 `stock_items` 本身 |
| POST | /inventory/batches/{batch_no}/paid-toggle | `{action:'pay'\|'unpay', paid_at?}`（admin+），比照承攬商匯款申請 paid-toggle 慣例；重複標記回 409 |

前端：`inventory.html`「進貨」Modal 新增供應商/發票號欄位；新增「進貨批次」Modal（列表＋標記已付款/編輯）。

---

## §8 · 備份與還原

> 整台正式機硬體故障時的完整重建流程，見獨立文件 [`DR-SOP.md`](DR-SOP.md)（2026-08-07 新增）。
> 這裡的 §8.1–§8.4 是日常備份機制；DR-SOP.md 是「機器掛了怎麼辦」的實際操作步驟。

### §8.0 · 雲端備份目標可插拔（2026-09-07，架構地圖 §6.4）

`archive.py` 原本只支援「本機掛載的雲端硬碟磁碟機」（下方 §8.1，磁碟機代號漂移已造成過真實備份靜默失效事故）。新增 `cloud_storage.py`，可切換成 S3 相容物件儲存（AWS S3／Backblaze B2 皆可，B2 有 S3 相容端點）：

```
system_settings.cloud_backup_target = { backend: "local_drive" | "s3", s3: {bucket, endpoint_url, region, prefix} }
GET/PUT /api/settings/cloud-backup-target（superadmin only，無前端頁面，比照 edge-path 等技術設定慣例）
```

- **憑證一律不存 DB**——走 boto3 標準憑證鏈（環境變數 `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` 或 `~/.aws/credentials`），設定裡只有 bucket/endpoint/region/prefix 這類非機密值
- `archive.py` 內所有原本「寫本機掛載磁碟機路徑」的地方（即時/每日/週備份、uploads 鏡像、SQLite 快照複製、過期備份清除）都已改走 `_cloud_write_json()`/`_cloud_copy_file()`/`_cloud_stat()`/`_cloud_marker_exists()`/`_cloud_write_marker()`/`_cloud_list_top_level()`/`_cloud_delete_dir()` 這組派送層——`backend="local_drive"`（預設）時這些函式的行為與改動前逐位元組相同（本機路徑計算完全沒變，只是多繞一層），`backend="s3"` 時才會改呼叫 `cloud_storage.py`
- **目前沒有真實 S3/B2 帳號可測試**，S3 路徑只用假的記憶體 S3 client 做過完整單元測試（`tests/test_cloud_storage_2026_09_07.py`，18 題）；要在正式機真正啟用，需要①先申請一個 AWS S3 或 Backblaze B2 帳號建 bucket ②在正式機環境變數設定 access key ③呼叫上面的 PUT 端點切換 backend。切換前這些都還沒做，正式機目前**維持 §8.1 原本的本機磁碟機模式**

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

**`logs/server.log` 大小輪替**（2026-09-07 新增，`archive.py::_rotate_server_log_if_large()`）：`autostart.bat` 用 shell `>>` 把伺服器 24/7 的 stdout/stderr 直接導向這個檔案（見 §1.1），完全不是走 Python `logging` 的 handler，先前沒有任何大小上限或輪替機制，長期下來可能把磁碟塞滿（正式機曾經因為另一張表無限增生塞爆過每日備份空間，是同一類風險）。`_daily_backup()` 一開頭（不受雲端是否可用、今天是否已備份過影響）就會檢查：超過 50MB 就用 **copytruncate**（複製到 `server.log.1`，舊的 `.1~.4` 依序遞增一代，`.5` 直接砍掉）原地把 `server.log` 清空成 0 bytes，而不是改檔名——因為 `apply_update.ps1` 的健康檢查寫死讀 `logs/server.log` 這個檔名，換檔名輪替會讓那個檢查悄悄失效。**⚠️ 尚未在真正跑著 `autostart.bat` 的正式機上驗證過**（Windows 上 cmd `>>` 開檔的共用權限是否真的允許外部行程同時 truncate，這裡沒有實機測試過，失敗會直接放棄、log 檔案維持原樣繼續成長，不會比現狀更糟）——下次部署後留意 `logs/server.log` 是否真的有被清空過。

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
| 框架 | Alpine.js（2026-09-07 起自架，見下方「外部函式庫自架」） |
| JS | `frontend/js/{page}.js`（非 defer，先於 Alpine） |
| Auth | `init()` 讀 session；無 token → login |
| 強制改密 | session.mustChangePassword 或 sidebar 導向 |
| API | `Authorization: Bearer {token}`，**PATCH deal-tag 不可遺漏** |
| 自動存 | debounce 1.5s（`setDirty`）；`isDirty=false` 需在 API 成功回調內設定 |
| 客戶選公司 | `selectCustomer()` async；每次選擇都 `GET /api/customers/{id}`，**強制覆寫**聯絡人欄位 |
| No-cache | `.html` / `.css` / `.js` 皆 no-store |
| Excel | SheetJS（2026-09-07 起自架，客戶／供應商／料號／承攬商等頁面匯出入用） |
| XSS 防護 | 動態插入 API 資料一律用 DOM API，**禁止 innerHTML 插入非靜態內容** |

**外部函式庫自架（2026-09-07）**：正式機是純內網部署（172.16.10.177，無對外網路依賴設計），先前 Alpine.js／Chart.js／SortableJS／frappe-gantt／SheetJS 全部從 `cdn.jsdelivr.net` 載入，若辦公室對外網路中斷或 CDN 被擋，整套 ERP 會直接打不開——這對一個刻意做成內網系統的應用是不必要的外部單點故障。已全部改成本機靜態檔案，`frontend/static/vendor/`：

```
alpine-3.17.1.min.js        （原 alpinejs@3.x.x 浮動版號，這裡固定下來）
chart-4.4.0.umd.min.js      （reports.html 原本用浮動的 @4，一併固定）
sortable-1.15.3.min.js
frappe-gantt-0.6.1.min.js／.css
xlsx-0.18.5.full.min.js     （SheetJS）
```

`pages/*.html` 引用 `../static/vendor/...`，`index.html` 引用 `static/vendor/...`（無 `../`，維持既有其他 static 資源的相對路徑慣例）。字型（`LINE Seed TW_OTF`）本來就已經自架，不受影響。之後若要升級這些函式庫版本，直接下載新版檔案覆蓋同名檔（或改檔名+改全部引用路徑），不必再依賴 CDN。

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
| ✅ | ~~區網 HTTPS／反向代理~~（`https_setup.ps1`，uvicorn 原生 TLS 自簽憑證，2026-08-27 commit `d7b8ee9`）——**但正式機尚未實際執行 mkcert 產證＋重啟這個手動步驟**，即工具已就緒但未真正啟用，見 `HTTPS-DEPLOY-CHECKLIST.md`；下次處理前先在正式機確認 `backend/certs/` 是否有內容 |
| ✅ | ~~死碼 JS 清除~~（21 個死碼 .js 已刪，`frontend/js/` 僅剩 2 個有效檔） |
| ✅ | ~~關鍵 API 自動化測試~~（2026-09-01 更正：早已遠超 48 tests，現為 `backend/tests/` 45 個測試檔，累計 300+ 題，近期為 308/308 全過） |
| ✅ | ~~文件拆 `CHANGELOG.md` 與本速查分離~~（已完成，見根目錄 `CHANGELOG.md`） |
| ✅ | ~~Git Flow 分支規則~~（`develop` 分支 + `GITFLOW.md` 規範已建立） |
| 低 | SQLite → PostgreSQL（資料量 > 1 GB 或同時連線數 > 5 時評估） |
| ✅ | ~~簽核流程尚未整合處/部門組織架構~~（四個 approval-settings 頁面已支援「部門主管自動簽核」層，見 §12 2026-08-22g） |
| ✅ | ~~通知路由只接了「工作事項逾期未完成」一個事件~~（已擴充到案件執行進度／專案到期兩個事件，`case_stage_deadline_manager`／`project_deadline_manager`，見 §12 2026-08-22k）；報表/儀表板依部門篩選仍只涵蓋 `reports.py`／`dashboard.py`（含新增的 `projectSummary`），activity-feed 仍只有「案件留言板」區塊套用篩選 |
| 🟡 | 組織架構目前只有二層（處→部門），使用者僅能透過部門間接歸屬於處，不支援「只屬於某處、不屬於任何部門」的直接指派 |
| ✅ | ~~專案管理「確認事項」兩階段簽核尚未接上 `helpers/tiered_approval.py` 的動態解析~~（已新增部門主管/處主管動態解析為額外路徑，`project_approve_eng`/`project_approve_biz` 模組權限完全保留，見 §12 2026-08-23d） |
| ✅ | ~~caseRecord.stages 正規化進行中~~（**2026-09-07 依實際程式碼複查更正**：①②③a 早已完成，③b 前端切換與④ `quotation-form.html` 落差修正**也已經在 2026-08-23 當天完成**——`case-management.js` 全部 10 個階段操作函式已改打 `/api/quotations/{no}/stages...` 專屬端點，`quotation-form.html::ensureCaseRecord()` 也已改成空陣列＋API 建立預設階段。這批工作是在正式機斷線期間直接於正式機完成，事後用一次大批量回推 commit `2b8e7ad` 拉回開發機，當時沒有補一篇正式 changelog／§11 更新，導致本節長期誤記為「進行中」。⑤讀取點改查新表當效能優化仍非必要、維持現狀。**2026-09-07 複查時另外發現並修復的真缺口**：這批 granular 端點本身先前幾乎沒有正面路徑測試（先前 `backend/tests/` 唯一涵蓋 `/stages` 的地方只測「已結案案件鎖定」情境）——已新增 `test_case_stages_endpoints_2026_09_07.py`（11 題，涵蓋 CRUD／負責人／前置階段防環／拜訪紀錄／跨案件 id 隔離／`_sync_stages_to_json` 橋樑／鎖定案件擋下），並修正 10 個端點 docstring 裡「尚未接進任何前端頁面」的過期字樣） |
| ✅ | ~~案件執行進度沒有跨案的時間軸或看板視圖~~（新增 `case-stage-board.html`：看板五欄＋跨案時間軸，見 §12 2026-08-23c）；專案時程跨專案視覺化仍未做，`dashboard.py` 目前只有依狀態分組的專案彙總卡片（2026-08-22k） |
| ✅ | ~~案件完結案缺防呆機制~~（2026-08-25 使用者提出，2026-08-26 已施作：`update_deal_tag()` 轉入「已結案」前檢查①`case_stages` 全部完成②`payment.items` 全部收齊③關聯單據皆無待審核中，任一未達成回 400 並通知尚未完成該項的簽核人＋最高管理員，見 §12 2026-08-26） |
| 🟡 | **已結案案件解鎖/半解鎖（2026-08-26 新增，範圍刻意收斂，非完整涵蓋）**：新增 `case-unlock`/`case-lock` 讓已結案案件進入「半解鎖」狀態，僅 8 個端點（案件記錄整包存檔／款項標記收款／款項發票附件／叫料附件／叫料發票附件共 8 支）支援半解鎖期間排隊等 superadmin 審核套用；案件執行階段細項端點（10 支）與款項稅額沖銷（3 支）刻意不支援排隊，已結案時一律直接 403（不論是否半解鎖），需要修正時只能透過案件資料整體編輯或聯繫最高管理員直接校正。之後若要擴大涵蓋範圍，比照 `case_record_update` 的「暫存 payload_json、核准時重放同一段套用邏輯」模式即可，見 db.py `_m061_case_semi_unlock()` docstring。 |
| 🟢 | PDF 存檔（報價單/出貨單/勞報單）未納入雲端備份範圍，可沿用 `_mirror_uploads()` 機制擴充，見 `DR-SOP.md` §5 |
| 🟢 | CORS 白名單寫死 IP，未改用環境變數，換機器/換 IP 需改 code 重新部署，見 `DR-SOP.md` §5 |
| 🟢 | `routers/projects.py`（592行）自 2026-08-26 專案併入案件管理後已無任何前端流程掛載，是否整個移除尚未決定 |
| 🟡 | 多分公司架構＋自動核版更新規劃中，未列入排程，見 `MULTI-BRANCH-AUTO-UPDATE-DESIGN.md`（2026-08-31，4 項待決事項） |
| 🟢 | 災難復原（DR）從未實際演練過，`DR-SOP.md` §6 演練紀錄表完全空白，RTO 目前僅為估計值 |

**📖 2026-09-01 新增：`MOTRIX-ERP-ARCHITECTURE-MAP.md`**（專案根目錄）——依實際程式碼盤點（非僅依賴本文件）產出的架構地圖，涵蓋 18 組模組的檔案:行號索引、DB v1→v68 完整演進索引、13 條踩坑教訓彙整、依專業軟體慣例的分優先序建議清單。**與本文件互補、不取代**：本文件仍是行為規格與逐日 changelog 的權威來源；架構地圖是「哪個功能在哪個檔案哪一行」的快速定位索引＋外部視角建議。本次盤點也發現本文件 §7/§13 的 router／migration 數量記載落後實際程式碼，已於本輪一併補齊（見下方 §7.12–§7.15、§13）。

---

## §12 · 變更摘要（最新兩版）

> 完整版本歷史請見 [`CHANGELOG.md`](CHANGELOG.md)（根目錄）

### 2026-09-07（完）— `logs/server.log` 新增大小輪替（DB 無異動）

- `autostart.bat` 用 shell `>>` 把伺服器 24/7 的 stdout/stderr 導向 `logs/server.log`，完全不經過 Python `logging`，先前沒有任何大小上限——長期下來可能塞滿磁碟。新增 `archive.py::_rotate_server_log_if_large()`，掛在 `_daily_backup()` 最前面（不受雲端可用性/今天是否已備份影響）：超過 50MB 就用 copytruncate 輪替（原地清空＋保留最新 5 份 `.1~.5`）
- **刻意不能改檔名輪替**：`apply_update.ps1` 健康檢查寫死讀 `logs/server.log` 這個檔名，換名字會讓那個安全機制悄悄失效，這是選擇 copytruncate 而非常見的「日期戳檔名」輪替法的原因
- 新增測試 `test_log_rotation_2026_09_07.py`（6 題），含一題模擬 `autostart.bat` 用同一個 append-mode file handle 持續寫入、驗證輪替後下一次寫入正確接續在清空後的新檔案裡
- **⚠️ 尚未在真正跑著 `autostart.bat` 的正式機上驗證過**：Windows cmd `>>` 開檔的共用權限是否真的允許外部行程同時 truncate 沒有實機測試過，失敗會安靜放棄（log 繼續成長，不會比現狀更糟），下次部署後需要留意實際是否生效
- pytest 439/439 全過

### 2026-09-07（終）— PDF 產生新增並發限制（架構地圖建議事項，DB 無異動）

- 每份 PDF 匯出都各自 spawn 一個 `msedge.exe --headless` 子行程，正式機是單一 Windows 主機沒有行程池限制——短時間內多人觸發簽核完成或匯出動作，理論上可能同時開出一堆 Edge 行程吃滿單機資源。新增 `helpers.EDGE_PDF_SEMAPHORE`（`threading.BoundedSemaphore(3)`），`pdf_gen.py`（14 處）／`network_plan_export.py`（1 處）／`routers/reports.py`（1 處）共 16 個 `subprocess.run([edge, '--headless',...])` 呼叫點全部用 `with EDGE_PDF_SEMAPHORE:` 包住，三個檔案共用同一個全域物件，超過上限的呼叫排隊等待，不會失敗只是變慢
- 複查過程中發現 `routers/reports.py::_html_to_pdf()` 是先前完全沒被 §11/架構地圖記載過的第三個獨立 Edge 子行程呼叫點（原以為只有 `pdf_gen.py` 跟 `network_plan_export.py` 兩處）
- 新增測試 `test_pdf_concurrency_2026_09_07.py`（3 題）：直接測 semaphore 本身的並發上限（起 9 個執行緒搶 3 個名額，驗證同時持有數不超過上限）、可重複借還、三個檔案 import 到的是同一個物件而非各自獨立
- 順便修正一個同輪發現的既有 E2E 測試 flaky 問題：`test_login_create_submit_approve_smoke` 單獨執行很穩定，但夾在整批 400+ 測試中間跑過一次因系統負載較高逾時，把簽核相關的等待時限從 10 秒加大到 20 秒
- pytest 433/433 全過

### 2026-09-07（最晚）— 外部函式庫全面自架，移除 CDN 依賴（DB 無異動）

- 正式機是純內網部署，先前 Alpine.js／Chart.js／SortableJS／frappe-gantt／SheetJS 全部從 `cdn.jsdelivr.net` 載入，對外網路中斷或 CDN 被擋會讓整套 ERP 直接打不開——已全部下載到 `frontend/static/vendor/` 自架，詳見 §9「外部函式庫自架」
- 順便固定了兩個原本用浮動版號的引用（`alpinejs@3.x.x`、`reports.html` 的 `chart.js@4`），改成跟其餘頁面一致的明確固定版本，避免上游偷改版本卻沒人發現
- 複查 CDN 清單過程中意外發現架構地圖 §6.5「甘特圖」建議其實在該文件寫成前一週（2026-08-24）就已經用 `frappe-gantt` 做完，是繼 §6.2/§6.5 之後**第二次**盤點沒交叉核對程式碼的過期記載，已一併更正
- 字型（`LINE Seed TW_OTF`）本來就已自架，不受影響；純換 script/link 標籤的 `src`/`href`，前端邏輯零變動
- pytest 430/430 全過（本次不影響任何後端測試）

### 2026-09-07（再更晚）— 新增第一條瀏覽器端對端測試（架構地圖 §6 建議事項，DB 無異動）

- 全系統 400+ 個 pytest 都是後端 API 整合測試，前端 Alpine inline script 完全沒有測試網——但過去多次真實回歸（`x-show`/`x-if` 誤用、badge 同步漏更新、日期排序）恰好都是純前端邏輯問題，後端測試攔不下來。新增 `test_e2e_playwright_2026_09_07.py`：用 Playwright 真實瀏覽器跑「登入→新增報價單→送出審核→另一位主管登入簽核→狀態變成已送出」golden path
- 需要 `playwright`（新增 `backend/requirements-dev.txt` 記載，**刻意不放進** `requirements.txt`——正式機執行 ERP 服務不需要瀏覽器引擎），沒裝的環境會 `pytest.importorskip` 自動 skip 整個檔案，不影響 `build_deploy_package.ps1` 既有流程；新增 `pytest.ini` marker `e2e` 供之後篩選
- 開發過程中意外發現一個目前系統的真實隱性需求：簽核解析走 `helpers/tiered_approval.py::resolve_submitter_manager_chain()`（申請人部門主管自動簽核鏈），**這是動態解析、不是送審當下快照**，申請人若沒有歸屬任何部門，簽核當下才會噴錯「申請人尚未歸屬任何部門」——測試裡刻意建了一個部門把建立者掛上去、部門主管設為核准者，讓流程符合實際情境
- 這條測試本身跑起來約 8 秒（真實啟動一個 uvicorn＋一個無頭 Chromium），比其餘 API 測試慢但仍在可接受範圍
- pytest 430/430 全過（429 既有 + 這條）

### 2026-09-07（更晚）— 雲端備份目標可插拔，新增 S3 相容後端（架構地圖 §6.4，DB 無異動）

- 新模組 `backend/cloud_storage.py`：S3 相容物件儲存後端（AWS S3／Backblaze B2 皆可），憑證走 boto3 標準憑證鏈（環境變數/`~/.aws/credentials`），**一律不存 DB**；新設定 `system_settings.cloud_backup_target`（`GET/PUT /api/settings/cloud-backup-target`，superadmin only）
- `archive.py` 所有原本直接操作本機掛載磁碟機路徑的地方（即時/每日/週備份、uploads 鏡像、SQLite 快照複製到雲端、過期備份清除）改走新的 `_cloud_*()` 派送層；`backend="local_drive"`（預設）時每個函式呼叫的本機路徑計算與 os/shutil 操作跟改動前逐位元組相同，只是多繞一層——確保現有正式機行為零回歸
- **目前沒有真實 S3/B2 帳號可測試**：S3 路徑只用假的記憶體 S3 client 做過完整單元測試（`test_cloud_storage_2026_09_07.py`，18 題，涵蓋 put/stat/list/delete、`_archive_ok()` 隨後端切換、`_backup_quotation`/`_mirror_uploads`/`_daily_backup`/`_prune_cloud_backups` 在 s3 模式下的整合行為），未在真實 bucket 上驗證過。要在正式機真正啟用需要使用者自行申請帳號、設定環境變數、呼叫設定端點切換，見 §8.0
- pytest 429/429 全過（400 原有 + 11 TOTP + 18 雲端備份）

### 2026-09-07（稍晚）— 新增 TOTP 兩步驟驗證，自助啟用（DB v72）

- 架構地圖 §6.2 建議事項：`pyotp`＋`qrcode` 新增 TOTP，`users` 新增 `totp_secret`/`totp_enabled`/`totp_recovery_codes`（`db.py::_m072_totp()`）。**刻意做成自助啟用而非強制**——正式機 superadmin 是 jeff/corbin 兩位真人業主，強制流程若部署後他們手邊沒先裝好驗證 App 會直接被鎖在外面，與使用者確認後定案，見該 migration docstring
- 新端點：`/api/auth/totp/{status,setup,enable,disable}`（需登入自助操作）＋ `/api/auth/login/totp`（登入第二階段，白名單路徑）；`setup`→`enable` 需輸入一次正確驗證碼才真正生效，避免掃錯 QR code 卻直接啟用把自己鎖在外面；`enable` 成功回傳 10 組一次性救援碼（明文僅此次可見，DB 只存雜湊）
- 登入流程：密碼正確但 `totp_enabled=1` 時不核發 session，回傳短效 `challengeToken`（process-global 記憶體，5 分鐘過期）；`/auth/login/totp` 核實驗證碼或救援碼後才真正核發，每個 challenge 最多 5 次錯誤即作廢
- 前端：`login.html` 新增第二步驟輸入畫面；`change-password.html` 新增「兩步驟驗證」卡片（設定 QR code／確認啟用／顯示救援碼／停用）；`notif.js` 對 admin/superadmin 未啟用時顯示提醒 banner（`sessionStorage` 節流，純提醒不阻擋操作）
- **修復一個開發中發現的既有 bug**：`main.py` 的 `_PUBLIC_API_PATHS` 白名單原本只有 `/api/auth/login`，新端點 `/api/auth/login/totp` 沒登入前呼叫會被 `auth_middleware` 攔成 401「未登入」——這其實是任何「登入流程本身要拆兩支端點」都會踩到的通用陷阱，之後若再拆分登入步驟要記得同步檢查這份白名單
- 新增測試 `test_totp_2026_09_07.py`（11 題，涵蓋 setup/enable/disable、登入兩步驟、救援碼一次性、per-challenge 鎖定），pytest 411/411 全過；已用真實開發機 API（非 pytest 隔離 DB）跑過完整流程驗證（含瀏覽器層級的 UI 因本次環境限制無法連線本機 dev server 完成視覺驗證，已用等效 HTTP 呼叫覆蓋全流程，UI 本身建議之後補人工檢查一次）

### 2026-09-07 — 更正 caseRecord.stages 正規化狀態記載＋補齊階段端點測試（DB 無異動）

- 複查本文件 §11 發現「caseRecord.stages 正規化進行中」記載已過期：核對程式碼確認 Phase 3b（前端切換）與 Phase 4（`quotation-form.html` 落差修正）其實早在 2026-08-23 就已完成，只是當時在正式機斷線期間直接開發、事後靠一次大批量回推 commit `2b8e7ad` 拉回開發機沒有補記錄。已更正 §11，詳見該處說明
- 補上真缺口：10 個階段 CRUD 端點先前幾乎沒有正面路徑測試，新增 `test_case_stages_endpoints_2026_09_07.py`（11 題），並修正 10 個端點 docstring 裡「尚未接進任何前端頁面」的過期字樣
- pytest 400/400 全過

### 2026-09-06 — 完整版規劃書拓樸圖三輪修復＋品牌文字統一「MOTRIX 專案管理系統」（DB 無異動）

- 品牌顯示文字全面從「營運系統」統一改為「MOTRIX 專案管理系統」：分兩輪掃描共 46 檔案 53 處（44 個前端頁面 `<title>`、2 處動態 `document.title`、`email_notify.py` 5 處信件頁尾、docs 文件標題）——第一輪只精確比對「營運系統」四字漏抓「營運管理系統」（中間多「管理」二字非連續子字串），第二輪全面掃描已追蹤檔案才補齊
- 完整版「網路架構規劃書」PDF 拓樸圖區塊修復三輪：①修復原生捲軸誤植入 PDF 輸出②一般規模（5台以上交換器）不再跨頁破碎③改成有多餘寬度就多欄並排、排不下才換行，並修正連帶產生的連線標籤蓋住交換器面板 bug；寬度改跟埠位對照表對齊（`width:100%`），縮小連線標籤防裁切緩衝區（160→70px）
- 使用者實測比較「兩欄並排＋字稍小」vs「一列一台＋字較大但頁數大增（5台交換器 1 頁變 3 頁）」兩版後選定前者，維持單頁塞下優先於字體大小
- 快速拓樸圖 PDF 格式/分頁改回比照 `b1f_topology.py` 原始腳本
- pytest 389/389 全過（每輪皆用合成資料＋開發機真實 API 雙重驗證，逐版拿 PDF 實測比對）

> 2026-09-04（網路架構規劃書拓樸圖功能上線＋快速拓樸圖工具）及更早版本已移出本視窗，完整內容見 [`CHANGELOG.md`](CHANGELOG.md)。

## §13 · 目錄結構（精簡，2026-09-01 依實際程式碼盤點更正）

> **完整版含每個 router 的檔案:行號、API 前綴、資料表對照，見 `MOTRIX-ERP-ARCHITECTURE-MAP.md` §2。本節維持精簡，只列骨架＋容易漏找的項目。**

```
MOTRIX-ERP/
├── MOTRIX-ERP-QUICK.md              ← 本文件（行為規格＋逐日 changelog 權威來源）
├── MOTRIX-ERP-ARCHITECTURE-MAP.md   ← 架構地圖＋建議＋踩坑索引（2026-09-01 新增，互補本文件）
├── CHANGELOG.md                     ← §12 的精簡版本，按版本倒序
├── DR-SOP.md · GITFLOW.md · APPLY-UPDATE-CHECKLIST.md · HTTPS-DEPLOY-CHECKLIST.md
├── NETWORK-PLAN-MODULE-DESIGN.md · MULTI-BRANCH-AUTO-UPDATE-DESIGN.md（規劃中，未列入排程）
├── SELECTION-DB-INDEX.md · {ENV,NETARCH,SWITCH,MONITOR,ACCESS,GATEWAY}-GUIDE-CONTENT.md · SWITCH-BRAND-REFERENCE.md
├── .gitignore
├── backup_alerts/                   ← 備份警示（執行期產生）
├── backend/
│   ├── main.py                      ← wiring only；34 個 app.include_router()；3 層 middleware
│   ├── db.py                        ← schema + 68 個 migrations（CURRENT_VERSION=68，見 §2／完整主題索引見 ARCHITECTURE-MAP §4）
│   ├── version_manifest.json        ← 模組版本紀錄（重啟後同步至 DB module_versions）
│   ├── helpers/                     ← 11 個檔案（拆自原 helpers.py）
│   │   ├── __init__.py              ← re-export 全部符號
│   │   ├── auth.py · settings.py · audit.py · quotations.py · dates.py
│   │   ├── email_notify.py · google_calendar.py · notification_prefs.py
│   │   ├── uploads.py               ← save_document_files/delete_document_file（附件上傳共用）
│   │   ├── startup.py               ← 啟動檢查、Edge 路徑解析
│   │   └── tiered_approval.py       ← ⭐ 五種文件類型共用的簽核 tiers 展開＋權限檢查唯一事實來源
│   ├── archive.py                   ← 備份；_atomic_json_write()；G: fallback；_mirror_uploads()
│   ├── pdf_gen.py · photos.py · network_plan_export.py
│   ├── backup_job.py · heartbeat_job.py   ← 獨立排程腳本（不 import main）
│   ├── autostart.bat · autostart_hidden.vbs · setup_{backup,autostart,heartbeat}_task.ps1
│   ├── tools/                       ← build_deploy_package.ps1 · apply_update.ps1 · check_guide_sync.py ·
│   │                                   audit_account_permissions.py · https_setup.ps1 · local_research_pipeline.py
│   ├── motrix_erp.db（正式）+ motrix_erp_demo.db（demo 隔離）
│   ├── db_backups/YYYY-MM-DD/（30天）+ quotation_instant/（G: fallback）
│   ├── tests/                       ← 45 個測試檔（累計 300+ 題，近期 308/308 全過）
│   └── routers/（34 個檔案，主檔/財務/簽核/選型資料庫/系統支援五大類，完整清單與行號見 ARCHITECTURE-MAP §2）
│       ├── 主檔：auth／customers／suppliers／parts／inventory／org_structure
│       ├── 業務流程：quotations（全庫最大）／dev_crm／shipping_notes／case_action_items／daily_tasks／payslips
│       ├── 財務：contractor_vouchers／invoice_vouchers／payment_requests／cashier（2026-08-31 併入報表頁籤）
│       ├── 承攬商/採購：vendor_contractors／contractors
│       ├── 選型資料庫（七類）：env_guide／netarch_guide／switch_guide／monitor_guide／access_guide／gateway_guide／automation_guide（v65 新增）
│       ├── 其他業務：network_plans（v64）／projects（⚠️ 已不掛載，死碼保留）
│       └── 系統支援：dashboard／reports（全庫第二大）／system／approval_delegates（v67）／uploads／search／list_prefs（v56）／module_versions
├── frontend/
│   ├── index.html                   ← 儀表板（Alpine inline）
│   ├── css/style.css                ← 含全站共用 .btn/.tab/.chip 元件（2026-08-09 統一後）
│   ├── js/case-management.js · reports.js   ← ⭐ 僅有的 2 個有效外置 JS，其餘 48 頁全 inline
│   ├── pages/（50 個 .html，完整清單見本文件標頭目錄或 ARCHITECTURE-MAP §2）
│   └── static/sidebar.js · notif.js · logo.png
├── uploads/                         ← 各類附件（照片/回簽/發票等），_demo_* 前綴為 demo 隔離
└── deploy_packages/<timestamp>_<commit>/   ← build_deploy_package.ps1 產物，人工搬移到正式機
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
