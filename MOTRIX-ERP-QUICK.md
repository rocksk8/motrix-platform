# MOTRIX ERP — 開發快速參考

> 允碩整合集創（統編 60575481）｜ Tel: 04-3610-6566 ｜ info@miactw.com  
> 文件版本：**2026-08-20**（承攬商匯款申請＋發票開立簽核單，DB v45/v46，見 §12）
> **2026-09-10 新增互補文件**：[`WEEKLY-AUDIT-2026-09-07_2026-09-10.md`](WEEKLY-AUDIT-2026-09-07_2026-09-10.md)——本週 82 個 commit 的逐模組拆解、異常時間軸（含每個異常的起點 commit 與根因檔案:行號）、12 項排查排程 checklist、已驗證缺陷清冊、未部署差異。**正式機出事時先看那份定位，再回來這裡看行為規格。**
>
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
| GET | /quotations/{no}/finance-summary | 案件財務「應收應付總覽」彙總（2026-09-09）：應收/已收/未收＋承攬商匯款申請的已核准未匯款/已匯款/簽核中＋開票申請/請款單唯讀清單＋精算額外支出小計。**後三者刻意不併入合計**，理由見端點 docstring |
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

### §7.19 · 採購建議（2026-09-07，架構地圖 §6.6）

| Method | Path | 說明 |
|--------|------|------|
| GET | /inventory/purchase-suggestions | 依安全庫存缺口自動生成，僅回傳紅/黃燈且已設定安全庫存的料號 |

回傳 `{items, count, totalEstimatedCost}`。**跟架構地圖 §6.6 原始建議的落差**：該條建議寫「資料已齊備」，但系統其實完全沒有追蹤供應商前置時間，所以刻意不做 ETA 預估，只算「該補多少、上次跟誰買、大概要花多少」：

```
建議採購量 = ceil(安全庫存 × 1.5) − 目前在庫（補到黃燈門檻，不是只補到剛好等於安全庫存，
             否則採購完成後燈號會立刻變黃再被同一張清單抓到一次）
供應商/單價 = 該料號最近一筆 stock_batches 進貨紀錄；查無紀錄則供應商留空、單價退回 parts.cost
排序 = 紅燈優先於黃燈，同燈號內依預估金額由高到低
```

前端 `inventory.html`：工具列新增「採購建議」按鈕（`lowStockCount > 0` 才顯示，跟既有「低於安全庫存」篩選 chip 同一組判斷條件），開啟 Modal 顯示清單與預估總金額；純唯讀，不含下單/標記已處理等狀態追蹤（v1 刻意收斂範圍）。

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
    PDF存檔鏡像\{類別}\    （2026-09-07 新增，報價單/出貨單/承攬商匯款申請/開票申請憑據/請款單/
                            結案報表 6 類，_mirror_pdf_archives() 同一套增量同步邏輯；跟隨
                            system_settings 裡各自 pdf_base_path 的實際設定值，非固定預設路徑）

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
| ✅ | ~~PDF 存檔（報價單/出貨單/勞報單）未納入雲端備份範圍~~（2026-09-07 新增 `archive.py::_mirror_pdf_archives()`，沿用 `_mirror_uploads()` 抽出的共用鏡像邏輯，涵蓋 6 類 PDF：報價單/出貨單/承攬商匯款申請/開票申請憑據/請款單/結案報表，見 §8.1） |
| 🟢 | CORS 白名單寫死 IP，未改用環境變數，換機器/換 IP 需改 code 重新部署，見 `DR-SOP.md` §5 |
| 🟢 | `routers/projects.py`（592行）自 2026-08-26 專案併入案件管理後已無任何前端流程掛載，是否整個移除尚未決定 |
| 🟡 | 多分公司架構＋自動核版更新規劃中，未列入排程，見 `MULTI-BRANCH-AUTO-UPDATE-DESIGN.md`（2026-08-31，4 項待決事項） |
| 🟢 | 災難復原（DR）從未實際演練過，`DR-SOP.md` §6 演練紀錄表完全空白，RTO 目前僅為估計值 |
| ✅ | ~~QR 登入手機端免密碼~~（2026-09-08 已實作，見 §12 同日條目——手機瀏覽器已有效 session 時自動核准，沒有則退回既有密碼手動輸入／瀏覽器自動填入密碼兩層） |
| ✅ | ~~`build_deploy_package.ps1` 打包關卡用 `pytest-xdist` 平行化~~（2026-09-09 已實作，見 §12 同日條目——動手前先驗證序列/`-n auto` 兩邊 470 題非 e2e 測試 pass/fail 清單完全一致，序列 390 秒→平行 166 秒，約 2.35 倍加速） |
| ✅ | ~~WebAuthn/Passkey 裝置綁定登入~~（**2026-09-09 已實作**，見 §12 同日「深夜」條目——後端新表＋端點、`login.html` 登入按鈕、`change-password.html` 裝置管理卡片；2026-09-10 `f8198e9` 再把 RP ID／Origin 改成 `system_settings` 可設定，未設定時四個端點回 503。**⚠️ 正式機目前仍不可用**：唯一的設定入口 `company-profile-settings.html` 在 `aeefcc6`，尚未部署，見 `WEEKLY-AUDIT-2026-09-07_2026-09-10.md` §F）。以下保留當初的設計討論紀錄：<br>**（原待開發內容）**——使用者原始需求是想綁定電腦/手機 MAC 位址做「認得這台裝置、快速放行」，查證後瀏覽器沒有任何 JS API 能讀取 MAC（隱私限制，非我們沒做），且 MAC 軟體層可偽造本來就不可靠。改用業界正規解法：裝置的安全晶片（Face ID/指紋/TPM）產生一組無法匯出/複製的金鑰跟帳號綁定，之後那台裝置生物辨識一下即可登入或核准 QR 請求，比 MAC 位址安全非常多。**尚未評估技術方案細節**——前端需串接瀏覽器 WebAuthn API（`navigator.credentials.create/get`），後端需新增 credential 註冊/驗證端點與公鑰儲存（新表，例如 `webauthn_credentials`），且要設計跟現有密碼／TOTP／QR session 三種登入路徑如何並存、要不要能列出/命名/撤銷已註冊裝置。下次要動手前應先進 Plan Mode 完整設計，比照 QR 核准功能與 TOTP 當初的作法（見 [[feedback_check_existing_before_building]]，認證流程設計優先權高於一般功能）。 |
| ✅ | ~~案件財務新增獨立「應收應付」模組＋精算雜支單號欄位~~（2026-09-09 已實作，見 §12 同日條目與 §7.16——新增 `GET /api/quotations/{quote_no}/finance-summary` 彙總端點，未新增任何資料表/欄位；精算「額外支出」新增 `docNo` 欄位，因 settlement 整包存 `data_json` 故後端零改動） |
| ✅ | ~~案件執行期限與超期提醒通知~~（**2026-09-10 已實作**，見 §12 同日條目——`caseRecord.projectTimeline` 存 data_json 無 schema 異動；`daily_tasks.py:1092-1135::_check_case_project_timeline_deadline()` 沿用既有每日排程而非另起 job；通知對象為所有 admin/superadmin；**重寄週期實作為每 7 天，非當初討論的 10 天**，計時點為超期天數分桶 `days_overdue // 7`）。以下保留當初的需求討論紀錄：<br>**（原待開發內容）**——案件管理「案件資訊」分頁需要新增「案件執行日期區間」欄位（start_date / end_date，類似預計交期的概念），當案件實際進度超過設定期限時自動觸發通知流程：(1) **超期當天寄一次電郵通知**給該案件的超級管理員與專案執行人；(2) **之後每 10 天重複寄一次**提醒尚未完結，直到案件狀態改為已結案為止。**背景需求**：實務上案件常因客戶延遲或內部進度調整而超期，長期無人追蹤就容易成為幽靈案件，需要一個被動提醒機制。**細節待評估**：(1) 日期欄位是否要新增到資料表或繼續存在 `data_json`（後者零改動，但搜尋/聚合較麻煩）；(2) 通知的「執行人」欄位定義（是 `executor`、還是 `assigned_user_ids` 任一人、還是需要新增一個獨立的 `deadline_notify_users` 欄位）；(3) 10 天的計時點是「案件建立時」、「超期當天」還是「上一次寄信」（影響時間複雜度與誤發機率）；(4) 通知內容格式與語言；(5) 是否需要在案件頁面顯示「距離期限剩餘天數」的倒數。排程觸發機制可沿用既有 `heartbeat_job.py`（正式機每 5 分鐘執行一次），或另起一個獨立的 `deadline_check_job.py`（見 §1.1）。**計劃**：先釐清上述需求細節，再評估是否需 DB migration。 |
| ✅ | ~~營運報表當月與當年度數據獨立分開顯示~~（**2026-09-09 已實作**：`56e52b3` 當月/當年度應收獨立檢視、不再跟隨 period-bar，新增 `test_reports_receivables_monthly.py`；`6bfcafb` 首頁當月收支完整修正＋部門篩選；2026-09-10 `f8198e9` 補上月支出頁籤徽章依 scope 顯示（`reports.html:434`）。同一批連帶修掉「首頁與營運報表對同一個數字有兩套歸月邏輯」的分岔，見 §12 2026-09-09）。以下保留當初的需求討論紀錄：<br>**（原待開發內容）**——目前營運報表的應收未收、已收已支等數字似乎是當年度與當月混在一起（或至少沒有明確區隔），需求是把「當月」的應收未收／已收已支獨立顯示，跟「當年度」的數字做出區隔，不要混算或混排在一起。**併同影響**：營運報表下方的分頁（tabs）內容也要一併比照，跟當年度視圖分開顯示，而不是共用同一份彙總。**細節待評估**（目前 `frontend/js/reports.js` 現有的月/年篩選邏輯、後端 `routers/reports.py` 對應的查詢與彙總方式），token 足夠時再展開設計，先記錄需求方向。 |

**📖 2026-09-01 新增：`MOTRIX-ERP-ARCHITECTURE-MAP.md`**（專案根目錄）——依實際程式碼盤點（非僅依賴本文件）產出的架構地圖，涵蓋 18 組模組的檔案:行號索引、DB v1→v68 完整演進索引、13 條踩坑教訓彙整、依專業軟體慣例的分優先序建議清單。**與本文件互補、不取代**：本文件仍是行為規格與逐日 changelog 的權威來源；架構地圖是「哪個功能在哪個檔案哪一行」的快速定位索引＋外部視角建議。本次盤點也發現本文件 §7/§13 的 router／migration 數量記載落後實際程式碼，已於本輪一併補齊（見下方 §7.12–§7.15、§13）。

---

## §12 · 變更摘要（最新兩版）

> 完整版本歷史請見 [`CHANGELOG.md`](CHANGELOG.md)（根目錄）
>
> **2026-09-10 補記**：本節曾一度停在 2026-09-09 15:57（`f935119`），其後 28 個 commit
> 未紀錄；同期間 `CHANGELOG.md` 09-08／09-09 兩天完全空白。已於本日補回，並新增
> [`WEEKLY-AUDIT-2026-09-07_2026-09-10.md`](WEEKLY-AUDIT-2026-09-07_2026-09-10.md)
> ——帶「模組／檔案:行號／是否在正式機」座標的本週稽核索引，出事時先看那份。

### 2026-09-10（本輪稽核）— 補回落後文件＋修掉四項已上正式機的缺陷（DB 無異動）

- **背景**：使用者要求把本週（09-07~09-10，82 個 commit）的更新逐模組拆解、標出每個異常從哪裡開始、有沒有上正式機，並把排查排程全部跑一遍。盤點過程中發現的東西比預期嚴重，整理成 `WEEKLY-AUDIT-2026-09-07_2026-09-10.md`（§A~§H），本條目只記處置。
- **正式機實測現況**：`GET /api/system/deployed-version` → `9b0ad79`（2026-09-10 11:32:13 套用）；明文 HTTP 已關閉、只剩 HTTPS；HEAD `aeefcc6` 尚未部署。
- **叫料 API（`routers/material_orders.py`，09-10 09:35 新增、11:32 上正式機）六個缺陷**，其中最外層那個會遮蔽其餘：①**漏 `conn.commit()`**——`db.py:119` 非 autocommit，`finally` 直接 `close()` 把交易丟掉，端點回 200 但資料庫一個字都沒寫（已用 sqlite 最小重現驗證機制）②`save_quotation_json()` 參數錯位，`user["id"]` 被當成 `status`、中文說明被當成 `updated_at`，補上 commit 之後會直接污染報價單狀態欄位③`_audit(conn, ...)` 傳錯簽名，例外被 audit 內部 `try` 吞掉、稽核從來沒寫成功④已結案守門讀 `data_json['deal_tag']`，但那裡的鍵叫 `dealTag`、權威來源是資料表欄位，等於死碼⑤**兩支端點都沒有擁有者檢查**，`quote_no` 可列舉 ⇒ IDOR，正是 2026-08-24 安全審查修過的同一類問題⑥GET 直接索引 `o["totalPrice"]`，舊資料會 500。
- **`_check_quotation_owner()` 抽到 `helpers/quotations.py`**：叫料是第三個呼叫點，比照 `summarize_payment_items()`／`settlement_extra_expenses()` 的既有慣例，之後任何「用 quote_no 直接取單筆」的新端點直接引用即可，不必再各自重寫或忘記寫。`routers/quotations.py` 三處呼叫點行為不變。
- **打包測試關卡長期失效（兩個獨立原因疊在一起）**：①`build_deploy_package.ps1` 用裸 `python` 呼叫 pytest，`where python` 這台機器有 **4 個**，儀表板子行程解析到 `pythoncore-3.14-64`，那支沒裝 `python-multipart` ⇒ 所有 Form/File 端點測試在 fixture 階段 `RuntimeError`，整套幾乎全 E ②`%TEMP%\pytest-of-hichan\pytest-current` 是一個目標讀不到的損壞 reparse point，`os.stat()` 回 `WinError 5` 而不是「找不到」，pytest `cleanup_dead_symlinks` 在 session 收尾整個炸掉——**測試全過也會回非 0**。後果：09-10 10:44 打包 FAIL 之後的兩份部署包沒走儀表板（`deploy_logs` 沒有對應 log），其中 `9b0ad79` 直接上了正式機，`CHANGELOG` 自述「已通過**基本語法檢查**」——即這次上線的版本沒跑過 pytest。
- **`requirements.txt` 缺 `python-multipart`**（09-07 `90c6f31`「補齊缺漏套件」漏了它）：正式機能跑純粹因為環境早就裝過，任何依 requirements 重建的環境（DR 還原、換機、`apply_update.ps1` 的 pip install）都會缺，症狀是**服務啟動成功、只有上傳類端點 500**，很難第一時間聯想。已補。
- **`test_webauthn_basic.py` 3 題失敗隨部署上線**：`f8198e9` 把 RP ID/Origin 改成未設定回 503，沒同步改測試；因為關卡已經全紅所以沒被擋下。已加 `webauthn_config` fixture，另補一題正面驗證 503 這個新行為；順手修掉 `routers/auth.py:730-749` 兩處 docstring 寫「fall back to localhost」但實際回 `""` 的落差。
- **修掉 `ee4664a` 當時繞過的 flaky 測試本身**：`test_daily_backup_writes_to_s3_and_marker_prevents_rerun` 原本斷言「整個 fake S3 物件總數不變」，會被同一 worker 上較早測試留下、還沒結束的背景備份執行緒干擾（實測 501 != 500，單獨跑 18/18 穩定）。改成只比對每日備份前綴——那才是這題真正要證明的規格。在打包腳本裡跳過它等於把關卡挖洞，`build_deploy_package.ps1` 那行現在可以移除。
- **驗證**：全套非 e2e **502 passed / exit 0**（本週第一次完全綠燈）。新增 `test_material_orders_2026_09_10.py`（7 題，每題都從資料庫讀回來核對而不是只看 HTTP 200——回應本身正是當初最會騙人的東西）。
- **⚠️ 尚未部署**：這批修復與 `aeefcc6` 都還在開發機。**`aeefcc6` 沒上正式機代表 Passkey 目前不可用**——後端已經會在 RP ID 未設定時回 503，而唯一的設定入口就在那支未部署的頁面裡。
- **教訓（本週第 4 次踩到同一個模式）**：「PATH 上有多個同名執行檔」已經害過 `tar`（09-08 `549d319`）跟現在的 `python`。凡是在腳本裡呼叫裸執行檔名，都要先問「在別的呼叫環境下會解析到哪一支」，並且**在關卡前面加一道會印出實際路徑的前置檢查**——缺套件的症狀是「470 題全部 E」，要往下捲三千行才看得到真正的 `RuntimeError`。

### 2026-09-10（後續修復）— 打包關卡補上直譯器守門＋清掉四個 P2（DB 無異動）

- **`build_deploy_package.ps1` 新增 Step 2.5「釘住 Python 直譯器並驗證依賴齊全」**：`Get-Command python` 解析出實際路徑→印出路徑與版本→跑一次涵蓋 `requirements.txt` 全部套件的 `import` 檢查，缺任何一個直接 `Fail` 並指名「哪一支直譯器、缺什麼、兩種修法」。之後所有 pytest 呼叫改用 `& $pyExe -m pytest`，不再用裸 `python`。**已用壞/好兩種直譯器各實測一次**（3.14 缺 multipart → exit 1 擋下並印出完整指引；PATH 第一順位 3.11.15 → exit 0 放行），兩次都在 `$ErrorActionPreference="Stop"` 下跑，確認這段沒有用 `2>&1`、不會踩到本專案已知的 PS 5.1 `NativeCommandError` 地雷。
- **移除 `ee4664a` 對 flaky 測試的 `--deselect`**：測試本身已修好（斷言範圍太寬，改成只比對每日備份前綴），不該再從關卡挖洞。
- **pytest 加 `--basetemp`**（每次一個時間戳目錄）：繞開 `%TEMP%\pytest-of-hichan\pytest-current` 那個損壞的 reparse point——`os.stat()` 回 `WinError 5` 讓 pytest 收尾拋 `PermissionError`，**測試全過也會回非 0**。⚠️ 這只是繞開，根治要用系統管理員權限 `rd` 掉那個連結（一般權限 `Remove-Item`/`rd`/`del`/`icacls` 全部 Access denied，已實測）。
- **`version_manifest_latest` 不再靜默變 null**：原本檔案找不到時連 `[WARN]` 都沒有（`Test-Path` 為假就整段跳過），事後無法分辨是「沒找到」還是「解析失敗」。現在三種結果（成功/空陣列/找不到/例外）都會印出來。
- **BOM 防禦補到第二、三處**：`routers/auth.py::system_version()` 與 `helpers/startup.py::_sync_module_versions()` 都是用純 `utf-8` 讀 `version_manifest.json`，只要有人用 PowerShell（PS 5.1 的 `Set-Content -Encoding UTF8` 會加 BOM）重寫該檔，前者讓登入頁版本號變空白、後者讓模組版本同步靜默停擺，兩處的例外都被 `except` 吞掉。已改 `utf-8-sig`——這是 `1c8f2e8`（`deployed-version` 端點）修過的同一個陷阱的第二、三份副本，屬本專案反覆出現的「同一段邏輯有多份副本」型態。
- **`reports.html:434` 月支出徽章**：原本 `x-show` 拿金額當真值，當月支出剛好 0 時整個徽章消失，看起來像功能壞掉。改成 `x-show="!!expensesData"`（依資料載入與否判斷），$0 正常顯示成 $0。
- **清掉誤入 repo 的 `backend/.commit_msg_webauthn.txt`**（`0527524` 連同 commit message 草稿一起提交），`.gitignore` 加 `**/.commit_msg*.txt` 防再犯。
- **更新 `build_deploy_package.ps1` 檔頭過時說明**：仍寫「這台開發機的 git repo 根目錄是整個使用者家目錄」，但專案已於 `e6bf102` 拆成獨立 repo、`$relPath` 恆為空字串（所以打包時「Project path:」印出空白是正常的，不是壞掉）。
- 驗證：全套非 e2e **502 passed / exit 0**；`build_deploy_package.ps1` 改完後 BOM（`EF BB BF`）與 CRLF 皆保留、PSParser 語法檢查 0 errors。**這批同樣尚未部署。**

### 2026-09-10 — 月支出頁籤、WebAuthn 可設定化、案件專案期間超期通知（DB 無異動）

- **營運報表月支出頁籤**：`reports.html:434` 徽章寫死年度總額（`expensesTotals.total`），跟同頁其他地方的 `expensesScope` 月/年切換邏輯不一致。改為 `expensesScope==='month' ? monthExpenseTotal : expensesTotals.total`。
- **WebAuthn RP ID／Origin 改為系統可設定**：原本寫死在環境變數、預設 `localhost`／`http://localhost:5000`，正式機用 IP 服務會讓瀏覽器丟 invalid domain。改存 `system_settings`：`routers/auth.py:730-749` 新增 `_webauthn_rp_id()`／`_webauthn_origin()`，四個 WebAuthn 端點未設定時回 **503**（刻意不留 localhost fallback——錯的 RP ID 會讓錯誤看起來像前端壞掉）；新增 `PATCH/GET /api/settings/webauthn-config`（`routers/system.py:708-741`，superadmin）與公開的 `GET /api/system/webauthn-config-status`（`routers/system.py:1081`，`main.py:62` 加入白名單）；前端未設定時隱藏 Passkey 按鈕。設定 UI 在 `aeefcc6`（`company-profile-settings.html`）。
- **案件「專案期間」＋超期通知**：`caseRecord.projectTimeline = {startDate, endDate, status}` 存 data_json，無 schema 異動。前端 `case-management.js:680-682`（`ensureCaseRecord()` 預設值）、`case-management.html:824-837`（區塊＋倒數/超期天數）；後端 `routers/daily_tasks.py:1092-1135` 新增 `_check_case_project_timeline_deadline()`，超期當天寄一次、之後每 7 天一次（guard key `caseproj_notif.{quote_no}.{days_overdue // 7}`），已掛進 `_daily_run()` 與 `_startup_catchup()` 兩處；通知 `helpers/email_notify.py:1370-1404::notify_case_project_overdue()` 寄給所有 admin/superadmin。
- **踩坑**：`f8198e9` 漏了 `helpers/__init__.py` 的匯出，`daily_tasks.py` import 直接炸掉，隔 4 分鐘用 `9b0ad79` 補上——這種「新增 helper 函式忘記加進 `__init__.py`」在本專案不是第一次，新增 `helpers/` 函式後請一併檢查 import 與 `__all__` 兩處。
- **使用者操作**：WebAuthn 需以 superadmin 進 `company-profile-settings.html` 填入內部 DNS 網域（需先把 DNS 指向 172.16.10.177）；案件超期沿用既有每日排程，無需額外設定。

### 2026-09-10（上午）— 叫料（材料訂購）後端 API＋PDF 返回碼修正（DB 無異動）

- 新增 `backend/routers/material_orders.py`：`PATCH/GET /api/quotations/{quote_no}/material-orders`，叫料清單存 `caseRecord.materialOrders`（data_json，無 schema 異動），欄位結構見 `backend/db_migration_plan.md:9-11`。`83c0a1a` 補上寫入權限檢查（admin+ 或 `project_manage`）。
- **這批上線時零測試、零前端**，且有六個缺陷（見本日「本輪稽核」條目），已於同日修復並補上 7 題測試。前端 UI 仍未做。
- `3a9332d` 修 `network_plan_export.py` PDF 生成失敗時的返回碼邏輯。
- `7c2a276` 一併新增的 `backend/tools/diagnose.ps1` 因編碼問題（本專案已知的 `.ps1` BOM 陷阱）先修語法（`cf5a4d2`）後直接移除（`00f1224`），淨變動為零。

### 2026-09-09（深夜）— 首頁與營運報表「當月收支」一晚六輪修正＋Passkey 前端完成（DB 無異動）

- **當月收支**（17:42→22:51，`frontend/js/reports.js` 改 4 次、`routers/reports.py` 2 次、`routers/dashboard.py` 1 次）：`3f9755f` 應收應付卡片改可點選＋當月收支獨立顯示 → `c063a72` 補初始化時自動載入 → `3e29ba7` 點選後自動捲動到對應細節 → `c5a5d11` **日期格式 bug 導致跨月污染** → `da88433` 邏輯統一＋未收 → `6bfcafb` 完整修正＋部門篩選。底層原因是同日稍早 `c15ef84` 已經記載的那件事：**首頁與營運報表對同一個數字本來就有兩套歸月邏輯**，共用邏輯抽出來之後前端才開始一路對齊。
- `56e52b3` 營運報表「當月/當年度應收」獨立檢視（不再跟隨 period-bar），對應 §11 2026-09-09 待開發項；新增 `test_reports_receivables_monthly.py`。
- **WebAuthn/Passkey V1**（`efdb06f`→`0527524`→`4f14c68`→`cce89fe`，17:11~23:19）：後端新表＋端點（`routers/auth.py`，`requirements.txt` 加 `webauthn>=2.1.0`）、`login.html` 登入按鈕、`change-password.html` 裝置管理卡片、challenge 編碼檢查。`0527524` 同時修掉 `auth.py` 的**用戶枚舉漏洞**。對應 §11 2026-09-08 待開發項。
- `d03f453` 收款標記強制填寫收款日期（`case-management.js`）；`aaeffb2` 業務開發頁面暗黑模式左側列表白底（`dev-crm.html`）。
- `0257fe7` 啟動伺服器改成純 PowerShell（`start_server.ps1`），可在檔案總管直接點擊執行。
- `1935c3c`／`942e3c4` 打包腳本兩次修正：git archive 語法錯誤、解壓改回用 Git 內建的 Unix tar（**注意這是 09-08 `549d319` 的反向操作**，前因後果見 `WEEKLY-AUDIT` §C-2，下次動這段之前先讀）。

### 2026-09-09（稍晚）— 修復：精算未完結的額外支出完全不算進月支出（首頁與營運報表都漏，DB 無異動）

- **使用者回報**：「尚未精算完結，只要當月有填寫，就要彙整進去」。查證屬實且比預期嚴重——`dashboard.py::dashboard_expenses_monthly()`（首頁支出趨勢）與 `reports.py::_collect_expenses()`（營運報表月支出）**兩處都只撈 `settlement.status='finalized'` 的案件**，精算還在草稿階段填的額外支出完全不會出現在任何月度支出數字裡。實際作業順序是「支出當下就先填進精算表單，案件整個結束後才做精算完結」，中間可能隔好幾個月，這段期間當月已經花掉的錢在報表與首頁上等於憑空消失。
- **同時發現兩處邏輯早已分岔**：reports.py 在 2026-09-02 已改成優先用 `expenseDate`（憑證日期）歸月，dashboard.py 卻還停在「一律用精算完結時間歸月」，所以首頁「本月支出」跟營運報表同一個數字本來就對不起來（沒有人發現，因為兩邊都少了草稿那批，錯得很一致）。
- **修法**：抽出 `helpers/quotations.py::settlement_extra_expenses()` 給兩處共用，不再要求精算完結；歸月日期依序取 `expenseDate` →精算完結時間→**最後一次精算存檔時間**（草稿也有，對應使用者說的「當月有填寫」），三者都沒有才略過（真的無從判斷月份，硬塞會污染月報）。每筆帶 `pending` 旗標（精算尚未完結），營運報表支出明細會顯示「精算未完結」小標籤——這些金額已經計入當月，但還可能被改動，看報表的人要知道。
- 順手修掉明細列的既有小 bug：`desc` 取 `it.get("name") or it.get("desc")`，但精算表單實際存的欄位是 `description`，所以說明欄長年只顯示類別名稱；一併把新的單號帶進明細（`說明（單號 XXX）`），會計才對得回實體憑證。
- 新增 `test_settlement_extra_expenses_pending_2026_09_09.py`（5 題：草稿要算、已完結不回歸、沒憑證日期退回存檔時間、完全沒日期要略過、首頁與報表數字必須一致）。
- **同一輪順帶**：案件財務「應收應付總覽」新增第三個可展開明細「精算額外支出明細」（含單號／類別／憑證日期，草稿精算也照樣列），原本只顯示一個總數無從核對；`selectCase()` 把 `activeTab='biz'` 移到兩個 await 之前，修掉「剛點開案件的瞬間切分頁會被彈回案件資訊」（新案件要連打 5 次建立階段 API，那段期間特別容易中）。
- **踩坑**：加這個明細時漏寫了 `finExtraItems()` getter，`x-show` 呼叫到不存在的方法時 **Alpine 只會靜靜當成 false、按鈕整個不出現**，後端測試全綠也完全看不出來——是靠人工截圖驗收才發現。已把「點開明細看得到單號」補進 e2e smoke test，這類錯只有真的開瀏覽器才擋得住。

### 2026-09-09 — 案件財務新增「應收應付總覽」＋精算額外支出單號欄位（DB 無異動）

- **需求**：專案管理－案件－財務底下要有一個能一次看完該案件所有會計相關內容（應收/應付/未收/未付）的獨立區塊；精算表單的雜支（＝「額外支出」）要能填單號。
- **不新增任何資料表/欄位**：這些資料本來就都在（應收在 `data_json.caseRecord.payment.items[]`、應付在 `contractor_payment_vouchers`、開票申請/請款單各有其表），缺的只是一個把它們並排看的視圖。新增 `GET /api/quotations/{quote_no}/finance-summary` 彙總端點（`routers/quotations.py`），權限比照同批資料的既有端點（只要求登入，財務可見性由前端 `canSeeFinancial()` 把關——同一份資料透過既有端點本來就拿得到，只擋這一支是假的安全感）。
- **應收/已收/未收的判斷抽成共用函式** `helpers/quotations.py::summarize_payment_items()`：這個邏輯原本在 `case-management.js` 的 getter 群與 `reports.py::_collect()` 各自算過一次，這是第三個呼叫點，抽出來避免再寫第三份（金額一律走既有 `payment_item_amounts()`，含 taxExempt 沖銷折算）。
- **刻意不算進合計的東西**（最容易重複計算的地方，測試裡有對應的規格化測項）：開票申請／請款單只做唯讀清單，不併入應收（跟收款排程期別非一對一對應）；精算額外支出只回小計供參考，不當應付（這個清單根本沒有已付/未付狀態欄位）；簽核中的匯款申請只計筆數，不進未付合計。
- **精算額外支出新增 `docNo`（單號）**：`settlement.html` 表格加一欄輸入框＋`addExtra()` 初始物件加 key，後端 `PUT /settlement` 是整包 dict 存檔、無欄位白名單，**零改動**；案件財務 Tab 的額外支出唯讀顯示與結案報表 PDF（`pdf_gen.py`，欄位數 5→6）一併顯示單號——會計對帳要靠它回頭找實體憑證，只能編輯不能列印等於沒用。
- **測試**：新增 `test_case_finance_summary_2026_09_09.py`（6 題，含「哪些東西刻意不併入合計」的規格化測項），非 e2e 476/476 全過；另在 e2e 檔新增 `test_case_finance_summary_smoke`，用真實瀏覽器驗證新的 Alpine getter 在 `financeSummary` 還是 null 時不會炸頁。**踩坑（兩個，都值得記）**：①這題第一版斷言用整頁 `body` 文字找金額，實際上是**假性通過**——案件標題列 KPI 與左側案件清單卡本來就會顯示同一批金額（合約金額/已收款/未收款），財務分頁根本沒展開也照樣「找得到」。已改成給總覽區塊一個 `id="fin-ar-ap-overview"`，所有斷言都鎖定這個區塊內的文字。②單獨跑穩定通過、跟其他 3 題 e2e 連跑時偶發失敗（約 1/10），原因是頁面初始化期間分頁點擊偶爾沒生效：`selectCase()` 在兩個 await 之後才設 `activeTab='biz'`，分頁列卻更早就渲染出來，**剛點開案件的瞬間切分頁會被彈回「案件資訊」**（既有行為，非本次改動造成，未修）。測試改成等總覽以 `state="attached"` 進 DOM（`x-if` 只在 `financeSummary` 載入後渲染，而該載入排在 `activeTab='biz'` 那行之後）＋分頁沒切過去就重點一次（最多 3 次），之後連跑 8 輪整套 e2e 全過。另記一個寫測試時的陷阱：不要用 `Alpine.$data(document.querySelector('[x-data]'))` 讀頁面狀態，`sidebar.js` 會另外注入自己的 x-data 元件，DOM 裡第一個 `[x-data]` 不保證是頁面主元件。

### 2026-09-09 — `build_deploy_package.ps1` 打包測試改用 `pytest-xdist` 平行化（DB 無異動）

- 待開發清單（§11）2026-09-08 討論項目：非 e2e 測試（470 題）序列跑約 6.5 分鐘，改用 `pytest -n auto` 加速打包關卡。
- 動手前先驗證 `backend/tests/conftest.py` 的隔離機制（`_app` session fixture + `client` function fixture 全靠 `tmp_path`/`tmp_path_factory` 做臨時檔案，無寫死路徑/port）撐不撐得住多 process 平行跑：實測序列跑一次（390 秒，470 passed）、`-n auto` 跑一次（166 秒，470 passed），兩邊 pass/fail 清單逐題 diff 完全一致，約 2.35 倍加速。確認無阻擋因素後才正式套用，不是常態雙跑。
- `backend/requirements-dev.txt` 新增 `pytest-xdist>=3.5.0`；`build_deploy_package.ps1` 非 e2e 測試那行加 `-n auto`（L135 附近）；e2e 那 3 題（真實瀏覽器）維持序列，不平行化。

### 2026-09-08（中午）— QR 登入新增手機端免密碼核准（DB 無異動）

- 使用者要求：手機掃 QR 核准登入時，如果這支手機瀏覽器自己已經是登入狀態，不要再要求手動輸入一次密碼。三層漸進式方案，同一份表單自然涵蓋，不用另外設計三套邏輯：①手機已有效 session → 自動核准，零操作；②沒有 session 但瀏覽器/系統有存密碼（Apple 鑰匙圈／Android 自動填入）→ 密碼欄位本來就有 `autocomplete="current-password"`，瀏覽器可跳出生物辨識一鍵帶入，零後端改動；③都沒有 → 退回手動輸入密碼（既有行為不變）。
- `QrApproveIn` 新增可選欄位 `session_token`；`login_qr_approve()`（`routers/auth.py`）新增分流：帶 `session_token` 時查 `sessions` 表驗證未過期，且該 session 的 `user_id` 必須跟這次核准請求鎖定的目標帳號完全相同才核准，避免「手機上隨便哪個已登入帳號」核准別人的登入請求；核對失敗回 401，但**刻意不計入**跟密碼/驗證碼共用的 `pending["fails"]` 鎖定計數器——session token 是 32-byte 隨機值不像密碼可被暴力猜測，比照「猜測型失敗才算鎖定」的既有原則。
- `login-qr-approve.html`：`init()` 拿到 `qr-info` 後，先讀 `localStorage.motrix_session` 有沒有現成 token，有就安靜嘗試一次 `session_token` 核准（畫面顯示「正在用這支手機目前的登入狀態核准…」），失敗才顯示手動密碼表單——失敗不當成錯誤顯示，因為「這支手機沒登入過這個帳號」是正常情況。
- 新增 5 題後端測試（`test_totp_qr_push_2026_09_08.py`）：同帳號 session 核准成功、不同帳號 session 被拒絕且不消耗 challenge、假 session token 被拒絕、兩者都沒帶回 400、錯誤 session token 不計入共用鎖定計數器（連錯 6 次後仍能用正確密碼核准）。既有 e2e QR 核准測試（`test_login_qr_approve_smoke`，模擬全新瀏覽器 context 沒有既有 session）重跑仍過，確認退回手動密碼表單這條既有路徑沒有回歸。pytest 470/470（不含e2e）＋ 3/3 e2e 全過。
- **尚未部署正式機**（跟這批一起提交，下次自然部署會帶上，這次沒有特地為此再跑一次打包/部署循環）。

### 2026-09-08（上午，重大根因發現）— apply_update.ps1 一整晚都在跑套用前就已凍結的舊版本，今晚對它做的內部邏輯修復從未真正執行過

- **背景**：`-SkipAutoRollback`（見上一條目）第一次真實使用時，直接報 `找不到符合參數名稱 'SkipAutoRollback' 的參數`——但這個參數當天早些時候已經寫進 `apply_update.ps1` 並打包進部署包。往下查發現一個影響整晚所有部署嘗試的根本問題。
- **根因**：`_dashboard_remote.ps1` 呼叫的是正式機**既有安裝路徑**的 `apply_update.ps1`（`$Root\backend\tools\apply_update.ps1`，`$Root` 固定指向 `C:\Users\Motrix\Desktop\V9.0`），不是剛推送過去那份新部署包裡的版本——因為 `apply_update.ps1` 自己有身分守門機制（Step 0：偵測執行路徑必須等於 `$ProdRoot`，防止不小心從錯誤位置執行部署腳本本身），沒辦法直接改成從套件路徑呼叫。PowerShell 腳本一旦開始執行，用的是啟動當下讀進記憶體的內容，Step 3 複製新程式碼進去只是覆蓋磁碟檔案，不影響「這次正在跑的進程」本身；而只要這次部署因健康檢查失敗被自動回滾，Step 3 剛複製進去的新檔案又會被回滾邏輯用套用前快照蓋回去。**代表只要今晚沒有任何一次部署真正成功套用過，`$Root` 這份 `apply_update.ps1` 就會一直凍結在「最後一次成功套用」當下的版本**——回推今晚的部署歷史，這代表今晚對 `apply_update.ps1` 內部邏輯做的所有修復（05:27 的健檢逐次記錄、05:38 起的多輪健康檢查機制調整、今早的良性 ConnectionResetError 雜訊過濾、Test-Ping 不再吞掉 stderr 等）**全部從未真正執行過一次**，因為每次呼叫的都是同一份凍結在更早版本的舊腳本。這也解釋了幾個先前無法解釋的異常：①「健檢第 N/20 次」這行 log 從 05:27 寫進去後就沒在任何一次部署 log 裡出現過②健康檢查失敗原因的 `Warn` 訊息一直看不到內容③這次 `-SkipAutoRollback` 直接參數不存在。
- **修復**：`_dashboard_remote.ps1` 在呼叫既有安裝路徑的 `apply_update.ps1` 之前，先把套件裡 `backend/tools/` 整個資料夾同步覆蓋到正式機既有位置（`Copy-Item -Recurse -Force`，只加不刪，不影響 `.guide_sync_config.json`／`deploy_logs/` 等未追蹤內容，兩者皆已 gitignore、不在套件內）。身分守門仍然通過（還是從 `$Root` 執行），但實際執行內容變成套件裡已經過 pytest／語法檢查驗證的最新版。**這是這一整晚部署工具鏈問題裡影響範圍最大的一個**——不是某個健康檢查判斷邏輯寫錯，而是「怎麼修都測不到自己剛寫的程式碼」，難怪同一類誤判要花好幾輪才「修好」一次又冒出下一種。
- **Why 這個問題直到現在才被發現**：`_dashboard_remote.ps1` 呼叫外部 `.ps1` 檔案的方式（`powershell -File "$Root\..."`）本身完全合理，是很容易忽略的細節——「部署包已經複製過去了」很直覺會讓人以為「所以套用的就是新版」，但套用的定義是「這次執行的腳本進程」而不是「磁碟上此刻的檔案內容」，這個時間點/範疇的落差不容易在複查程式碼時想到，只有在需要用到一個「舊版腳本根本不存在的新參數」時才會用最直接的方式暴露出來。
- **尚未驗證**：這批修復本身尚未經過真實部署驗證——下一次套用如果順利完成（不管健康檢查是否誤判，`-SkipAutoRollback` 至少要能被正確辨識），才算真正確認這個根因解讀正確。

### 2026-09-08（早上）— 修好結束碼判定後第一次真實套用又抓到第三種健康檢查誤判：良性 asyncio 雜訊被算成錯誤（commit `2ea87e8`）

- 前一批（`6ee3a6d`）修好「假成功」判定後，09:13 真的重新套用一次，這次判定結果變成真的失敗（`success:false`，符合實際情況），但複查貼出的 `server.log` 發現這次「healthy=False, log 錯誤筆數=6」本身又是誤判：新程式碼實際運作 24 秒完全正常（`/api/ping`／`deployed-version`／QR 登入流程皆 200），中途出現兩次 Windows asyncio 眾所皆知的良性 `ConnectionResetError`（`_ProactorBasePipeTransport._call_connection_lost`），舊版 `"Traceback|ERROR"` 不分大小寫掃描連這個字本身都算命中，兩次雜訊貢獻剛好 6 行。已改用逐行狀態機整段跳過這個已知良性區塊。
- **誠實記錄：這次還額外真的觀察到服務 crash 一次重啟**（`exit code -1`，crash-restart 迴圈 5 秒後拉起），發生時機跟這兩次雜訊重疊，但目前沒有證據能確認因果關係，**沒有宣稱已修好**，只做了一個合理的降風險動作：`/ws/prod-status`（本次一併新增的正式機狀態 WebSocket）在有 deploy/rollback job 進行中時暫停實際查詢，避免額外疊加連線負擔在服務最脆弱的重啟時刻。下次若又發生真的 crash，需要另外找時間查 uvicorn/asyncio 在 Windows 自簽憑證下是否有已知的 proactor+SSL 邊界問題。
- 同一輪也修好了更根本的判定邏輯 bug（`6ee3a6d`）：`_dashboard_remote.ps1` 呼叫遠端 `apply_update.ps1`／`rollback_update.ps1` 從不檢查其結束碼，導致 WinRM 連線本身沒斷就一律回報成功——這正是先前連續五次 `deploy_dashboard_history.json` 顯示 `success:true` 但實際上使用者觀察到失敗的根因，加上健康檢查失敗原因先前被 `2>$null` 整個吞掉的另一個獨立 bug，詳見上方「2026-09-08（清晨）」條目。

### 2026-09-08（清晨）— 修復儀表板「假成功」判定＋健康檢查失敗原因被吞掉兩個核心 bug；新增正式機狀態 WebSocket 即時推送（尚未 commit）

- **背景**：連續多次部署後使用者回報「畫面顯示成功，但實際上失敗」，複查 `deploy_dashboard_history.json` 發現連續五筆 `success:true` 裡完全沒有 `47d0cca` 已新增的 `logPath` 欄位——代表當晚整段測試期間實際在跑的 `deploy_dashboard.py` 進程根本是 03:41 剛寫完、從未重啟過的舊版，中間十個修復 commit 都沒被真正驗證到。已先重啟一次儀表板進程。
- **根因一（判定邏輯本身就是假的）**：`_dashboard_remote.ps1` 呼叫遠端 `apply_update.ps1`／`rollback_update.ps1` 時只是單純 `Invoke-Command { powershell -File ... }`，從不檢查巢狀 powershell 的 `$LASTEXITCODE`。`apply_update.ps1` 健康檢查失敗觸發自動回滾時確實有 `exit 1`，但這個結束碼被 `Invoke-Command` 完全吞掉、從不傳回開發機——只要 WinRM 連線本身沒斷，`_dashboard_remote.ps1` 就會正常結束、回傳碼永遠 0，`deploy_dashboard.py::_run_job()` 的 `success = proc.returncode == 0` 因此無論正式機那邊實際成功或失敗都判定成功。已修復：遠端 ScriptBlock 內額外印出 `===EXITCODE=N===` 標記行，本機端用 `Invoke-Command | ForEach-Object` 串流解析（不能改成 `$x = Invoke-Command ...` 賦值寫法，那樣會讓即時 log 整段變成部署跑完才一次噴出，弄丟即時滾動的體驗），非 0 才真的 `Fail`。`deploy_dashboard.py::_run_job()` 也加一道獨立防線：即使結束碼判定成功，仍掃輸出文字有沒有出現「更新失敗」／「已自動回滾」／`[FAIL]`，兩者矛盾一律視為失敗。
- **根因二（真正的健康檢查失敗原因全程被吞掉）**：使用者複查時貼出的 `-CheckOnly` 診斷輸出顯示 curl.exe 直接呼叫／巢狀呼叫都拿到 `200`、port 666 有正常監聽的 python 進程，但 D 段新版健康檢查腳本（`_healthcheck_ping.py`）卻回報 `exit_code=1`——服務其實是健康的，是這支新腳本本身有問題導致誤判。往下查發現 `apply_update.ps1`／`rollback_update.ps1` 的 `Test-Ping` 呼叫這支腳本時用 `2>$null` 把例外訊息整個丟掉，`_dashboard_remote.ps1` 的 `-CheckOnly` D 段測試也是同樣寫法——每次失敗都只看得到「healthy=False」，完全看不到 Python 那邊真正的例外是什麼，這正是這一晚反覆盲目猜測根因、來回熱修好幾輪的主因之一。**尚未查出 `_healthcheck_ping.py` 這次失敗的確切例外內容**（沒有正式機帳密無法在這次對話中重新觸發診斷），已做防禦性修復：兩支呼叫端改用 `2>&1` 合併輸出＋失敗時用 `Warn` 印出腳本回報的原因；`_healthcheck_ping.py` 本身把例外訊息改印到 stdout（不是 stderr），不管未來呼叫端會不會又不小心用 `2>$null`，這行都能被撈到；順便把 `resp.status` 加上 `resp.getcode()` 的 fallback（跨 Python 版本相容性防禦，不確定是否為這次真正根因）。**下次健康檢查再失敗時，Warn 那一行會直接印出 Python 的例外內容，才有機會真正定位根因**，這次是誠實承認還沒抓到真正原因，只是讓下次失敗時看得見。
- **新增（使用者要求）：正式機狀態 WebSocket 即時雙向連線**：新端點 `GET /ws/prod-status`，連線期間伺服器每 4 秒主動推一次 `{healthy, deployed, checkedAt}`；前端任何時候送一個字串（例如部署/回滾 job 剛結束時）可以立即觸發一次重查，不用等下一個 4 秒週期——雙向、即時。分頁關閉/重新整理時 WebSocket 自然斷線，伺服器背景檢查迴圈跟著結束，不會留下孤兒輪詢；連線意外中斷但分頁還開著時前端會自動 5 秒後重連。`deploy_dashboard.html` 新增連線狀態指示燈。已用 Python `websockets` client 實測：連線後立即收到狀態、送 `refresh` 觸發立即重查皆正常。
- **這批修復尚未 commit**（`git status` 目前 dirty），下次要重新打包部署前記得先 commit，`build_deploy_package.ps1` 才會放行。

### 2026-09-08（凌晨，8 小時排查）— 部署儀表板連續三次真實部署健康檢查誤判失敗；改健康檢查機制＋儀表板安全性補強

- **背景**：延續 §12 同日「凌晨後」條目修好 tar／migration 乾跑防護之後，用部署儀表板對正式機做這一大批新功能（QR 登入、部署儀表板本身、多項修復，commit 一路到 `ebd182f`）**第一次真正的完整部署**。連續三次套用後健康檢查都判定失敗（`healthy=False`，一次真的抓到 6 筆 log 錯誤、兩次是 0 筆），每次都自動觸發回滾；第二次回滾後複驗甚至也判定失敗（「仍異常，需要人工介入！」），但用獨立管道（開發機 Python `requests` 直接打正式機、儀表板背景輪詢）查證當下正式機其實一直是健康的——三次都是健康檢查機制本身的偽陽性，不是新程式碼真的壞掉或服務真的中斷。
- **排查過程（依序試過、依序被推翻的假設）**：
  1. 疑點：健康檢查逾時太短（3 秒）——拉寬成 5 秒＋迴圈次數 15→20，第三次還是失敗，推翻。
  2. 疑點：WinRM 巢狀執行（`Invoke-Command` 裡面又跑一層 `powershell -File`）本身讓 `curl.exe` 打 loopback 出問題——額外寫了一個診斷動作，直接在正式機上用一模一樣的巢狀深度重測 `curl.exe`，每次都正常回應 200，推翻。
  3. 疑點：連續反覆停/啟服務留下孤兒 TCP 監聽 socket（這台專案先前在開發機真的踩過的坑）——查 `Get-NetTCPConnection -LocalPort 666`，每次都只有一個乾淨的 listener，推翻。
  - 三個假設都被獨立測試推翻後，唯一剩下的解釋是「curl.exe 在 Windows 上走 Schannel，實測 `-v` 輸出可見自簽憑證連線會發生兩次 TLS renegotiation，這個機制本身在這台正式機的某些時刻不穩定」；同一段時間開發機用 Python `requests` 打同一支端點的背景輪詢每次都正確回報真實狀態，形成明顯對照。
- **處置（合理猜測，非證實根因）**：新增 `backend/tools/_healthcheck_ping.py`（Python 內建 `ssl` 模組，走 OpenSSL、不經過 Schannel），`apply_update.ps1::Test-Ping` 改呼叫這支腳本統一 HTTP/HTTPS 兩種情境，取代 curl.exe。**老實承認這是根據當晚證據做的合理猜測，不是已經證實的根因**——程式碼註解裡也這樣寫。**下次部署時要特別留意**：如果健康檢查仍然誤判，下一個該懷疑的方向是「部署當下 port 666 重新綁定那個瞬間」本身的競態，不是健康檢查呼叫的實作細節（前三個假設都已排除，這是唯一還沒獨立驗證過的剩餘可能）。
- **健康檢查逐次記錄**：`apply_update.ps1` 的健檢迴圈原本只印最終結論，現在每一次嘗試都印「第幾次／經過幾秒／成功或無回應」，比對到的 log 錯誤行內容也直接印出來；回滾後複驗若仍不健康，額外自動印出 port 666 目前監聽狀態，協助判斷是真的服務中斷還是健康檢查本身又誤判，不用再事後另外跑診斷工具。
- **部署儀表板新增三項安全/資訊補強**（`deploy_dashboard.py`/`.html`）：①同一時間只允許一個 deploy/rollback job 在跑，第二個請求直接 409 拒絕（當晚複查發現完全沒有這層防護，有連續按好幾次部署、兩個 WinRM session 同時搶 port 666 的風險）②job 完整輸出落地存檔到 `backend/tools/deploy_logs/`（原本只存在記憶體，當晚儀表板本身重啟好幾次都把即時輸出洗掉），歷史紀錄新增 `logPath` 欄位③二次確認卡片會先查上一筆歷史紀錄，如果是 15 分鐘內的失敗就多印一行紅字警告（當晚實際發生連續盲目重試好幾次都沒先看清楚上一次發生什麼事）。同時新增兩個唯讀診斷端點 `/api/log-tail`（讀正式機 `server.log` 最後 N 行）與 `/api/check-only`（直接在 WinRM session 內測 `curl.exe`／port 666 監聽狀態），修正了 PS Remoting 對回傳字串陣列每個元素加簽 `PSComputerName` 等屬性、導致 `ConvertTo-Json` 序列化成物件（前端 `join` 出一串 `[object Object]`）的問題（遠端 scriptblock 內先 join 成單一字串再回傳）。
- **附帶發現（虛驚一場，非真的 bug）**：其中一次回滾後，使用者回報「輸入密碼→驗證 2FA→跳回登入頁面」，一度懷疑是真的登入機制壞掉。查證 server.log 發現瀏覽器打的 `/api/system/deployed-version`／`/api/auth/login/qr-status` 兩支新端點回 401——這兩支路由只存在於被回滾掉的新版程式碼，代表**瀏覽器分頁還停留在剛才短暫上線時載入的新版 `login.html`（有 QR 輪詢邏輯），沒有真正重新整理過**，跟正式機當下實際跑的舊版後端對不上，前端把 API 401 當成未登入全域攔截、彈回登入頁。硬性重新整理分頁後正常。**下次部署後如果有人回報登入異常，先請對方重新整理分頁再排查，不要直接當成真的認證 bug。**
- **當晚代價**：對正式機做了三次真實的停/啟服務循環（皆已確認安全回滾、資料庫皆有還原），沒有造成資料遺失，但重複三次仍是不必要的風險。這批修復尚未實際部署驗證過（下次部署本身就是驗證這批 Python 健康檢查是否真的解決問題的第一次機會）。
- **收尾複查又抓到兩個真實問題**（使用者要求「反芻」整套部署工具鏈找邏輯/安全/穩定性問題）：①`rollback_update.ps1`（手動回滾用，健康檢查通過但功能邏輯有問題時才會用到）有自己一份獨立的 `Test-Ping`，還停留在 curl.exe 舊版，跟 `apply_update.ps1` 當晚已經改用 `_healthcheck_ping.py` 沒同步——已同步修好，逾時/迴圈次數/逐次記錄/失敗印 port 666 狀態全部對齊。②`build_deploy_package.ps1` 原本在 pytest（跑 6+ 分鐘）跑完後才記錄 commit hash，如果打包過程中 repo 又有新 commit 進來，archive 出來的內容可能不是「剛剛真正跑過 pytest 驗證」的那個版本——這不是憑空想像的風險，當晚背景跑打包的同時另一個對話動作確實做過新 commit，只是那次剛好被既有 flaky 測試提前擋下沒有真的產出型別不一致的部署包。已改成 pytest 開始前就先釘住 commit hash。**這兩個問題都屬於「同一套邏輯有兩份副本、改一份忘記改另一份」或「操作順序恰好留了一個時間窗」的模式，跟這個專案已知的其他教訓（[[feedback_check_existing_before_building]]）同一類，下次新增/修改部署工具腳本時，值得養成先 grep 一下是否有姊妹腳本（`apply_update.ps1`⇄`rollback_update.ps1`）沒同步改到的習慣。**

### 2026-09-08（凌晨後）— 部署儀表板第一次真實使用抓到兩個部署工具真實 bug

- **背景**：用部署儀表板（§14.3c）第一次真的觸發「打包」，畫面顯示成功，但套用到正式機時 Migration 乾跑驗證階段炸掉，只印出 `python.exe : Traceback (most recent call last):` 一行就中止（`apply_update.ps1:167`），完整錯誤內容被吞掉。
- **根因 1（`build_deploy_package.ps1`）**：透過儀表板（Python subprocess 啟動）觸發打包時，腳本裡的 `tar -xf` 解析到 **Git for Windows 內建的 Unix 風格 `tar`**（PATH 順序問題，跟使用者自己開的終端機環境不同），不是 Windows 內建的 BSD `tar.exe`——Unix tar 把 `C:\Users\...` 路徑開頭的 `C:` 誤判成「要連線的遠端主機」（老式 tar 的 `-f host:path` 遠端磁帶機語法），直接印 `Cannot connect to C: resolve failed` 解壓失敗。**更嚴重的是這一行呼叫完全沒檢查 exit code**，腳本照樣往下跑完印出綠字「完成！」，產出的部署包資料夾裡**只有 `deploy_manifest.json`，backend/frontend 完全是空的**——這個問題不只影響儀表板，理論上任何 PATH 順序不同的呼叫環境都可能踩到。已修復：改用完整路徑 `$env:SystemRoot\System32\tar.exe` 徹底避開 PATH 解析歧義，並補上 `git archive`／`tar` 兩處的 exit code 檢查＋額外驗證解壓後真的有 `backend/`／`frontend/` 目錄，三層防護取代原本完全沒檢查的狀態。
- **根因 2（`apply_update.ps1`）**：Migration 乾跑驗證階段真正在測的是「新版 db.py 在裝了壞掉部署包（只有 manifest 沒有程式碼）的情況下當然會 `ModuleNotFoundError: No module named 'db'`」——這本身是根因 1 造成的必然結果，但揭露了 `apply_update.ps1` 另一個獨立的既有缺陷：跟 db 備份（第191行）／migration 乾跑驗證（第223行）這兩處 `& python ... 2>&1` 呼叫，都沒有比照 pip install（2026-09-07 修過）加上 `$ErrorActionPreference = "Continue"` 的防護——只要 Python 腳本往 stderr 印任何東西（含它自己一個真正的 Traceback），在 `$ErrorActionPreference = "Stop"` 底下會被包成 `NativeCommandError` 直接中止整支腳本，且只看得到 Traceback 第一行，看不到完整錯誤內容，也看不到腳本原本設計好的「Migration 乾跑驗證失敗，中止套用（正式庫完全未被觸碰）」這行說明訊息。已補上同款防護。
- **教訓**：這是同一類「Windows PowerShell 5.1 對原生執行檔 stderr 輸出的地雷」第三次在這個專案不同地方被踩到（pip install、tar、db備份/migration乾跑），已知這個模式後，下次新增任何 `& <原生執行檔> ... 2>&1` 呼叫時應該直接預設加上這層防護，不要等踩到才修一次。用便宜的方式（抽出 git archive/tar 那一小段、跳過完整 pytest）透過跟儀表板完全一樣的 subprocess 呼叫方式在本機重現＋驗證修復，避免又讓使用者對正式機盲測一次。
- **當下影響**：只有 db 快照被建立（`db_backups/pre_update_20260908_041209/`），正式機的服務／程式碼／資料庫完全沒被觸碰（crash 發生在 Step 1，Step 2 停服都還沒開始）。已刪除兩個壞掉的部署包資料夾（`20260908_035627_bc73efe`／`20260908_041017_8d83021`），修復後需要重新打包一次乾淨的部署包再重試。

### 2026-09-08（最晚）— 新增本機部署儀表板（含手動回滾），見 §14.3c

- **背景**：今天套用 QR 登入功能到正式機時，反覆卡在操作型摩擦（`Get-Credential` 圖形視窗不彈出、密碼誤打進聊天視窗）。已建立的 WinRM 直連通道（§14.3b）目前只能用一長串手動 PowerShell 指令操作。新增 `backend/tools/deploy_dashboard.py`——本機 FastAPI 小工具（只綁 `127.0.0.1`），瀏覽器打開後可以按鈕點選完成「打包→推送→套用」，密碼用一般網頁輸入框輸入，完全避開 Windows 原生憑證視窗的問題。
- **新增檔案**：`rollback_update.ps1`（照抄 `apply_update.ps1` 自動回滾邏輯，參數化成可手動指定要回滾到哪個時間戳的快照）、`_dashboard_remote.ps1`（實際透過 WinRM 對正式機執行 deploy/rollback/list-snapshots 三種動作，寫死在檔案裡不是 Python 動態組字串，避免注入風險；密碼從 STDIN 讀，不出現在指令列參數）、`deploy_dashboard.py`／`deploy_dashboard.html`（FastAPI app + 前端頁面）。
- **關鍵設計決策**：`apply_update.ps1`／`rollback_update.ps1` 的互動確認提示（`Read-Host "...(y/N)"`）是在 `Invoke-Command -ComputerName` 遠端 script block 內執行——**WinRM 不支援事後對正在跑的遠端 script block 注入互動輸入**，所以儀表板改用網頁 UI 自己的兩段式確認（顯示摘要卡片→按【確認套用】才真的送出）當作等價的人工安全關卡，遠端呼叫本身帶 `-Yes` 跳過腳本自己的提示。已同步更新 `apply_update.ps1` 檔頭註解，避免以後看到 `-Yes` 被使用誤判成繞過安全機制。
- **新增公開端點** `GET /api/system/deployed-version`（`routers/auth.py`，讀 `backend/.deployed_commit.json`）：讓儀表板查詢正式機目前部署版本不需要 WinRM 帳密。**已知限制**：正式機要等這批工具套用過去之後這個端點才存在，第一次查詢會顯示「未知」。
- **踩坑**：新 `.ps1` 檔案用 Write 工具建立時預設沒有 UTF-8 BOM，這台機器的 PowerShell 5.1 會用系統非 Unicode 編碼猜測讀檔，把中文註解讀亂連帶炸掉後面的引號/大括號配對——這是專案已知的編碼陷阱（見 `feedback_windows_locale_encoding_pitfall` 記憶），這次新建 `.ps1` 檔案時又踩到一次，已手動補 BOM 修復。另外 `deploy_manifest.json` 是 PowerShell 寫的也帶 BOM，Python 讀取要用 `utf-8-sig` 不能用 `utf-8`（純 utf-8 遇到 BOM 直接丟 `JSONDecodeError`，這次用真實瀏覽器 Playwright 檢查時才發現套件清單資料整個是空的）。
- 用 Playwright 直接開這個工具的頁面實測（開發機/正式機狀態卡正確顯示、套件下拉選單正確載入 4 筆、部署兩段式確認流程能正常跳出）；新增 pytest 測試 `test_deployed_version_endpoint_2026_09_08.py`（2題）。完整回歸 pytest 466/467（1 個已知 flaky 測試無關，單獨重跑穩定）。**尚未實際用真實正式機帳密跑過一次完整部署/回滾**，下次需要部署時就會是這個工具的第一次真實使用。

### 2026-09-08（更晚）— TOTP 登入新增「手機掃 QR 核准」並行選項（DB 無異動）

- **需求**：既有 TOTP 兩步驟驗證（2026-09-07 上線）登入時只能手動輸入驗證 App 的 6 位數字。使用者要求並行新增第二種選項：手機相機掃描登入頁面上的 QR code → 開啟確認頁面 → 輸入密碼核准 → 電腦端自動偵測到核准並完成登入，不需要在電腦上手動輸入任何東西。兩種方式並存，使用者自己選，互不影響。
- **實作**：沿用既有的 `_totp_pending` 記憶體 dict（不新增資料表），多存一個 `"approved": False` 欄位。`auth_login()` 的 `totp_enabled` 分支額外用 `qrcode.make()`（沿用 `totp_setup()` 既有手法）產生一張 QR，內容是動態組出的確認頁面網址（`{scheme}://{host}/pages/login-qr-approve.html?challenge=...`，不寫死 IP），回應多一個 `qrCodePng` 欄位。新增三個公開端點（`_PUBLIC_API_PATHS` 加入）：`GET qr-info`（給手機看遮蔽後的帳號名稱）、`POST qr-approve`（手機送密碼核准，只翻轉 `approved` 旗標，**不**在這裡發 session）、`GET qr-status`（電腦端每 2 秒輪詢，偵測到 `approved=True` 才真正彈出 pending、呼叫既有 `_issue_session()`，回應形狀跟 `/api/auth/login/totp` 成功時完全一致，前端直接重用同一支 `_storeSessionAndRedirect()`）。`qr-approve` 密碼錯誤刻意共用同一個 `pending["fails"]` 計數器（不是另開一組獨立上限），避免同一張 challenge 變相有兩倍可猜次數。
- 新增頁面 `frontend/pages/login-qr-approve.html`（獨立、無需登入即可開啟的手機確認頁）；`login.html` 的 `totpStep` 表單並列顯示 QR code＋新增輪詢邏輯（全站第一個用到 `setInterval` 輪詢的前端頁面）。
- 新增測試 `test_totp_qr_push_2026_09_08.py`（8 題，含跨路徑共用失敗計數器的交叉驗證、單次有效性驗證），pytest 464/464 全過。另在 `test_e2e_playwright_2026_09_07.py` 新增 `test_login_qr_approve_smoke`——用兩個獨立瀏覽器 context 模擬「桌面登入＋手機另開頁面掃 QR 核准」的真實流程（桌面讀 Alpine `challengeToken` 狀態模擬相機解碼，手機 context 開確認頁輸入密碼核准），驗證桌面在輪詢週期內確實會自動完成登入、不需要任何手動操作——首次執行即通過，證明功能端到端真的可行，不只是 API 層級的假設。
- 這次先進入 Plan Mode 完整設計後才動手（新增認證流程，安全性影響大，值得先確認方向），已用 Explore agent 蒐集現有 challenge-token 機制／session 發放機制／`qrcode` 產生慣例的精確程式碼位置後才落筆設計。

### 2026-09-08（稍晚）— 正式機真實套用事故：`apply_update.ps1` HTTPS 健康檢查誤判觸發不必要的回滾

- **背景**：套用 commit `305511e` 部署包（no-cache 修復＋flaky 測試診斷探針）時，`[4/6] pip install` 步驟順利通過（084eb78 的修復生效），但 `[5/6]` 健康檢查回報 `healthy=False, log 錯誤筆數=0` 觸發自動回滾。**回滾流程本身也正常完成**（程式碼／db 皆已還原）
- **關鍵線索**：使用者提供的 `server.log` 顯示新程式碼（PID 7392）與回滾後的舊程式碼（PID 25180）**兩次都正常啟動成功**（`Application startup complete`／`Uvicorn running on https://0.0.0.0:666`／各項排程檢查皆正常跑完），代表這次回滾是被誤判觸發，新程式碼原本沒問題
- **根因（第一次誤判：TLS12）**：正式機先前已經（在本文件記載之外、未同步更新 §0/§11 認知）實際執行過 `https_setup.ps1` 切換成 HTTPS。第一輪懷疑是 `ServicePointManager.SecurityProtocol` 預設不含 `Tls12` 導致 TLS handshake 失敗，加了 `SecurityProtocol = Tls12` 後請使用者手動熱修重試——**仍然失敗，同一組症狀**
- **真正根因（第二輪，已用 `curl.exe -k` 直接連線＋帶完整例外訊息的診斷腳本確認）**：原本的 `[System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }` 用 PowerShell **指令碼區塊**當委派方法，但 .NET 在 TLS handshake 階段是從**背景執行緒**呼叫這個委派，該執行緒沒有 PowerShell Runspace 可以執行指令碼區塊——InnerException 明確寫著「沒有 Runspace 可在這個執行緒中用來執行指令碼」。這個委派從一開始（2026-08-27 引入 HTTPS 健康檢查時）就是不可靠的，只是這是第一次真正在已切換 HTTPS 的正式機跑到這條路徑；TLS12 從頭到尾都不是問題所在
- **修復**：改用 Windows 內建原生執行檔 `curl.exe -k`（不經過 .NET `ServicePointManager`，沒有 Runspace 委派問題）取代 HTTPS 情境下的 `Invoke-WebRequest`，新增 `Test-Ping` 共用函式，三處健康檢查（套用前記錄／套用後主檢查／回滾後再驗證）統一呼叫；HTTP 情境維持原本 `Invoke-WebRequest` 不變（本來就沒壞過）。已用 `curl.exe -k -s -o NUL -w "%{http_code}"` 這個確切呼叫形式對真實 HTTPS 網站測過，回傳乾淨的 `200` 字串
- **當下處置**：由於回滾流程會把 `apply_update.ps1` 自己也還原回升級前版本，每次重跑都會用回舊（有 bug 的）健康檢查邏輯，兩輪熱修嘗試都必須繞過這個限制才能生效
- **附帶發現／文件修正**：§0/§11 先前記載「正式機尚未實際執行 mkcert 產證＋重啟」已過時——正式機顯然已經在本文件不知情的情況下轉為 HTTPS，是本次事故的間接成因（見 §0 一貫提醒的「正式機做了什麼，開發機不知道」情境再次發生）
- **附帶改善**：§15.3 的操作指令範例改為建議一律使用絕對路徑（`-File` 用絕對路徑不影響腳本行為，純粹減少一步 `cd`／避免目錄錯誤；`-PackagePath` 本來就該給絕對路徑），因為這次套用過程中使用者連續踩到「忘了 `powershell` 前綴」與「當前目錄不是專案根目錄導致相對路徑找不到檔案」兩個操作型錯誤
- 這批純粹是部署工具腳本修復＋文件更正，不在 pytest 覆蓋範圍內，未新增測試

### 2026-09-08 — 修復 `no_cache_static` middleware 誤傷 vendor 函式庫快取（flaky 測試放大因子之一）

- **背景**：延續 2026-09-07（最末之四）條目的排查，架構複查發現 `main.py::no_cache_static()` 對所有 `.html`/`.css`/`.js` 一律加 `Cache-Control: no-store`——這條規則是為了讓開發中頁面永遠拿到最新版而設計，CDN 自架前沒事（外部函式庫由 jsdelivr 自己另外設定長效快取，且是不同 origin），但 2026-09-07「外部函式庫全面自架」之後，`frontend/static/vendor/` 底下版本號釘死在檔名裡（如 `alpine-3.17.1.min.js`）、內容保證不變的第三方函式庫也被這條規則誤傷，變成每次換頁都要向本機同一個 uvicorn process 重新要一次
- **影響**：不只是測試環境的問題——正式機使用者平常在系統內換頁，理論上也在不必要地重複下載 Alpine.js 等函式庫，徒增每次換頁的延遲與伺服器負載；也是 `test_login_create_submit_approve_smoke` 在整套 pytest 跑到中段時偶發卡在 `wait_for_selector(timeout=30000)` 的放大因子之一（同源請求量增加，疊加整套跑到中段時單一 Python process 已累積的物件/GC 壓力）——單獨跑該測試 5/5 穩定通過（~11 秒），只有整套跑時才會卡，符合「位置相依、非測試邏輯本身問題」的診斷
- **修復**：`/static/vendor/` 底下的檔案改為 `Cache-Control: public, max-age=31536000, immutable`（一年＋不可變），其餘 `.html`/`.css`/`.js`（頁面程式碼、`sidebar.js`/`notif.js` 等）維持原本 `no-store` 不變——版本升級一定會改檔名，同名檔案內容保證不變，長效快取安全無虞
- 新增迴歸測試 `test_vendor_cache_headers_2026_09_08.py`（3 題，驗證 vendor 長快取／其餘頁面 JS／HTML 仍是 no-store）
- **尚待驗證**：這個修復能否讓整套 pytest 跑穩仍待下次 `build_deploy_package.ps1` 實測確認；「整套跑到中段 GC/物件累積壓力」目前仍是未經證實的假設，若修復後整套跑依然偶發逾時，代表放大因子還有其他來源，需要繼續排查（而非再次單純加大等待時限）

### 2026-09-07（最末之四）— 排查 `test_login_create_submit_approve_smoke` flaky 根因：排除執行緒資源洩漏

- **背景**：這條已知 flaky 測試（見 §12 2026-09-07j 條目起持續加大等待時限的記錄）今晚連續 4 次在整套打包流程的 pytest 全跑（`build_deploy_package.ps1`）中卡在同一個逾時點（`page2.wait_for_selector('button:has-text("預覽後簽核")', timeout=30000)`），但單獨只跑這個檔案時 3/3 穩定通過，直接卡住緊急部署（pip install 修復包）的收尾
- **原本懷疑**：整套 400+ 測試裡有大量 `db.spawn_bg_thread()`（報價單/客戶/供應商測試建立時觸發的背景備份寫檔執行緒）沒有被回收，累積到第 243 個測試（`test_e2e_playwright` 在整體排序中的位置）時造成系統資源競爭，拖慢這個測試依賴的真實 uvicorn server 回應速度
- **實測排除**：在逾時點前後插入 `threading.active_count()` 診斷探針，跑一次完整套件（診斷程式碼跑完即還原，未進 git）——**等待期間執行緒數量全程維持 13 個、完全沒有變化**，直接推翻「背景執行緒累積競爭」這個假設；`spawn_bg_thread()` 產生的背景執行緒是短命的 fire-and-forget 寫檔工作，正常情況下不會累積存活
- **目前推測**（未證實）：比較可能是這台開發機在跑完整 6 分鐘測試套件期間，被 OS 層級的其他活動（防毒即時掃描、雲端硬碟同步、本機其他 AI 工具或軟體）偶發搶走 CPU/IO 資源，導致瀏覽器渲染或 API 回應短暫變慢超出 30 秒視窗——這類環境層級干擾不是應用程式碼或測試邏輯本身的問題，程式碼層面修不了
- **下一步**：使用者先重開機排除背景程式干擾後重試整套打包；若重開機後仍然只在整套跑時才會逾時、單獨跑不會，會更支持「環境資源競爭」的推測。長期若要徹底解決，可考慮把 `@pytest.mark.e2e` 的測試從 `build_deploy_package.ps1` 的主要 pytest 關卡中獨立出來另外跑（不影響部署阻擋關卡的穩定性），而不是持續加大等待時限治標

### 2026-09-07（最末之三）— 修復 pip install 步驟本身在 PowerShell 5.1 下的崩潰 bug

- **事故**：套用 `66a414f` 部署包時，Step 4（前一輪新增的 pip install 步驟）本身直接讓整支腳本崩潰報錯 `NativeCommandError`，卡在 Step 3（新程式碼已複製）與 Step 5（健康檢查）之間，沒跑完健康檢查也沒觸發自動回滾
- **根因**：Windows PowerShell 5.1 對「原生執行檔 + `2>&1`」有個已知地雷——只要該執行檔往 stderr 寫任何內容（就算成功也一樣），在 `$ErrorActionPreference = "Stop"`（本檔開頭就設定）底下會被包裝成 `NativeCommandError` 直接中止腳本。`pip install` 即使成功也常態性往 stderr 印提示（例如這次的「有新版 pip 可更新」），因此每次都會炸；先前 db 備份／migration 乾跑那兩段同樣寫法的 `python ... 2>&1` 沒事，是因為那兩支腳本成功時完全不寫 stderr，這次新增的 pip install 才第一次踩到這個地雷
- **修復**：pip install 呼叫期間暫時把 `$ErrorActionPreference` 改成 `Continue`，執行完立刻用 `finally` 還原，不影響腳本其餘部分既有的錯誤處理行為；已用 `cmd /c "echo x & echo y 1>&2"` 做最小重現＋驗證修復前會崩潰、修復後能存活
- **當下實際影響**：正式機執行到這步之前，使用者已經手動在正式機跑過一次 `pip install -r requirements.txt`（依照當時建議先手動補裝），代表套件在腳本內部這次多餘的 pip install 執行前就已經裝好，新程式碼與 autostart 迴圈理論上已經正常運作，只是腳本本身沒跑完後續健康檢查與版本紀錄——不是回滾情境，是腳本自己中途摔倒
- **教訓**：這是同一天連續第二次在「正式機真實套用」這個情境才第一次踩到的地雷（第一次是缺套件，這次是修缺套件本身用的寫法又踩了另一個雷），`apply_update.ps1` 目前完全沒有自己的單元測試或語法驗證關卡，`build_deploy_package.ps1` 也只檢查 `git status` 乾淨、不檢查 `.ps1` 語法或邏輯——之後如果部署工具本身的改動頻率提高，值得評估要不要至少加一層基本語法檢查

### 2026-09-07（最末之二）— 拉回正式機 Claude 直接修復的兩個部署工具 bug

- **背景**：19:16 那次自動回滾後，開發機這邊已先修好 pip install 缺步驟的問題並準備重新打包，但正式機當下另有 Claude session 直接在正式機上排查、也各自修好了兩個獨立問題——這正是 §0 一直提醒的「正式機做了什麼，開發機不知道」情境，這次是部署工具本身先撞到
- **`apply_update.ps1`｜根目錄文件回滾落差**：健康檢查失敗回滾時，原本只回滾 `backend/`／`frontend/`／db，沒回滾根目錄文件（`MOTRIX-ERP-QUICK.md`／`CHANGELOG.md` 等）——但 Step 3 複製新程式碼時，根目錄文件是在健康檢查「之前」就先覆蓋過去，回滾若不處理，會變成「文件內容已經是新版、實際跑的程式碼卻被還原成舊版」的落差，19:16 那次事故裡實際發生過。修復：套用前多存一份 `rollback_snapshots/<timestamp>/root_docs/` 快照，回滾時一併還原
- **`https_setup.ps1`｜`.Source` 屬性缺失**：找 `mkcert.exe` 時若命中系統 PATH（`Get-Command`），回傳的 `ApplicationInfo` 有 `.Source`；若命中 `backend/tools/` 本機路徑（`Get-Item`），回傳的 `FileInfo` 沒有這個屬性，讀到 `$null`，後面 `& $mkcert.Source ...` 直接炸掉「運算元後面的運算式產生的資料類型無效」。修復：統一在找到當下就轉成路徑字串 `$mkcertPath`，不再混用兩種物件型別
- **已拉回開發機**：兩支腳本內容已與正式機這份逐位元組核對一致（`diff` 確認），並各自過語法檢查
- 這次沒有新增/修改任何測試——兩處都是部署/憑證設定腳本本身，不在 pytest 覆蓋範圍內（`build_deploy_package.ps1` 目前也不檢查 `.ps1` 語法，僅檢查 `git status` 乾淨），日後如果這類部署工具 bug 再發生，可以考慮補一支獨立的 `Test-Path`／語法層級檢查腳本

### 2026-09-07（最末之一，正式機部署事故）— `apply_update.ps1` 新增 pip install 步驟

- **事故**：19:16 在正式機套用當天累積的 12 個 commit（TOTP／S3備份／CDN自架／PDF並發限制／log輪替／依賴掃描／採購建議）部署包時，套用後健康檢查失敗（`healthy=False`，log 錯誤筆數=9）觸發自動回滾。回滾機制運作正常，正式機資料與舊版程式碼皆未受影響
- **根因**：`ModuleNotFoundError: No module named 'pyotp'`——TOTP 功能（見下方 2026-09-07（稍晚）條目）用到的 `pyotp` 早已正確補進 `requirements.txt`（見 2026-09-07（末）條目），但 `apply_update.ps1` 的部署流程從頭到尾只複製程式碼檔案，**從未執行過 `pip install`**，正式機 Python 環境從沒裝過這個套件，新程式碼一 import 就炸，autostart crash-restart 迴圈重試多次皆失敗
- **修復**：`apply_update.ps1` 在「套用新程式碼」與「健康檢查」之間新增 Step「安裝/更新 Python 依賴」（`python -m pip install -q -r requirements.txt`），步驟總數改為 6 步；pip install 本身失敗不中止流程（維持既有健康檢查作為最終安全網，若真缺套件仍會被抓到並觸發回滾）
- **待辦**：正式機需先手動 `python -m pip install -r backend\requirements.txt` 補裝 `pyotp` 等套件，再重新套用同一個部署包（`.deployed_commit.json` 未更新，版本比對仍視為新版，不需 `-Force`）

### 2026-09-07（緊急修復）— 修復 conftest.py 雲端備份隔離死碼，曾讓測試假資料寫進真實 G: 磁碟機

- **問題**：`backend/tests/conftest.py` 的 `_app` fixture 原本 patch `archive._ARCHIVE_BASE`／`_REALTIME_DIR`／`_WEEKLY_DIR`／`_DAILY_DIR`／`_UPLOADS_MIRROR_DIR` 這五個大寫常數，但 `archive.py` 早就改成 `_archive_base()`／`_realtime_dir()` 等會動態掃描磁碟機代號的函式（見架構地圖 §6.4／本文件 §12 2026-09-07 雲端備份可插拔條目），conftest.py 沒有跟著更新——這五行 patch 對現在的程式碼完全是死碼，什麼都沒隔離到
- **實際影響**：任何透過 API 建立/更新報價單、客戶、供應商的測試，背景執行緒呼叫的 `_backup_quotation()`/`_backup_customers()`/`_backup_suppliers()` 完全沒被隔離，會做真正的磁碟機代號掃描——在剛好掛載著真實公司雲端硬碟的開發機上，這代表測試產生的合成資料會真的寫進 `G:\我的雲端硬碟\系統存檔\即時備份\` 底下。逐一核對後確認：`報價單\` 資料夾混進約 30 份測試專用假單號（`MQ-TEST-*`／`MQ-CRGATE-*`／`MQ-CCR-*` 等，各自獨立檔案，只是新增不影響其他內容）；**較嚴重的是** `客戶\clients.json`／`供應商\suppliers.json` 這兩個全量快照檔案被整個覆寫成某次測試的合成資料，不是真實客戶/供應商清單
- **修復**：改成直接 `archive._archive_base = lambda: str(archive_base)` patch 函式本身，讓所有依賴它的 `_realtime_dir()`／`_weekly_dir()`／`_daily_dir()`／`_uploads_mirror_dir()`／`_pdf_mirror_dir()` 全部自動一併隔離，不用每個都個別 patch，也不會重蹈「`archive.py` 改了實作方式、`conftest.py` 沒跟著更新」的同一種錯誤
- **驗證**：修復前後分別記錄 G: 磁碟機 `即時備份\報價單\` 的檔案數（82），重新跑會建立報價單的測試後檔案數維持 82（沒有新增），確認修復生效；全套 pytest 454/454 全過，確認修復沒有弄壞任何既有測試
- **善後**：已對真實開發機資料庫執行一次 `archive._backup_customers()`／`_backup_suppliers()`，用目前資料庫的真實內容（13 個客戶／24 個供應商）重新整批覆寫 `clients.json`／`suppliers.json`（這兩個檔案設計上本來就是每次完整覆寫、非累加寫入，重新產生不會有合併/重複問題）；`報價單\` 資料夾裡的測試假單號殘留檔案**刻意不主動清除**，留給使用者自行決定是否要清掉（各自獨立檔案，不影響任何現有真實備份內容，純粹是雜訊）
- 這個缺口存在的時間**早於今天**（推測是先前某次把 `archive.py` 常數改成動態函式的重構沒有同步更新 conftest.py），過去所有在 G: 剛好掛載時執行過整套 pytest 的開發階段理論上都有可能留下類似殘留，只是這次剛好被系統性複查抓到

### 2026-09-07（再加開）— 庫存新增自動採購建議（架構地圖 §6.6，DB 無異動）

- 新端點 `GET /api/inventory/purchase-suggestions`，依安全庫存缺口計算建議採購量（補到黃燈門檻 = 安全庫存 × 1.5），供應商/單價取自該料號最近一筆 `stock_batches` 進貨紀錄，查無紀錄退回 `parts.cost`；只回傳目前紅/黃燈且已設定安全庫存的料號，紅燈優先排序
- **複查更正架構地圖 §6.6**：原始建議寫「資料已齊備」，但系統其實從未追蹤供應商前置時間，故刻意不做 ETA 預估，只回答「該補多少、上次跟誰買、大概多少錢」
- 前端 `inventory.html` 工具列新增「採購建議」按鈕（沿用既有 `lowStockCount` 判斷式）＋唯讀 Modal，v1 刻意不含下單/已處理狀態追蹤
- 新增後端測試 `test_purchase_suggestions_2026_09_07.py`（9 題）與一條 Playwright 前端 smoke test（`test_inventory_purchase_suggestions_modal_smoke`），驗證按鈕/Modal 這條純前端路徑真的能點得通、資料正確渲染——過程中這條新測試第一版有選錯 DOM 節點的 bug（誤抓到 Modal 開啟前就已存在的背景主表格同名料號列，而非 Modal 內的建議清單列），修正為把查詢範圍限定在 Modal 容器內
- pytest 454/454 全過

### 2026-09-07（加開）— PDF 存檔納入雲端每日備份鏡像（DB 無異動）

- 補上 §11 已知限制：報價單/出貨單/承攬商匯款申請/開票申請憑據/請款單/結案報表 6 類 PDF 各自存在專案根目錄獨立資料夾（如 `報價單PDF/`），不在 `uploads/` 底下，`_mirror_uploads()` 完全掃不到——DB 救得回來但已產出的 PDF 檔案本身從未被備份過
- 把 `_mirror_uploads()` 的增量鏡像邏輯抽成共用的 `_mirror_directory_incremental()`，新增 `_mirror_pdf_archives()` 呼叫 `pdf_gen.py` 各自的 `_get_*_pdf_base()` getter（跟隨 superadmin 可能改到的自訂路徑，不是硬猜預設資料夾），掛進 `_daily_backup()`，與 `_mirror_uploads()` 並列執行
- 同步更新 `DR-SOP.md` 三處過期記載（原本標注「仍未涵蓋」的地方）
- 新增測試 `test_pdf_archive_mirror_2026_09_07.py`（5 題）
- pytest 444/444 全過

### 2026-09-07（末）— 補齊 requirements.txt 缺漏套件＋新增弱點掃描工具（DB 無異動）

- 複查發現 `requirements.txt` 長期缺漏 `openpyxl`（`network_plan_export.py`／`routers/accounting_export.py`／`routers/reports.py` 三處 Excel 匯出核心功能）與 `Pillow`（`routers/contractors.py` 模組頂層 unconditional import——若照 `requirements.txt` 在全新機器裝環境，裝完啟動時 import 這個 router 就會讓整台伺服器起不來）。已補進 `requirements.txt`；只有工具腳本用到、伺服器本身不會 import 的 `beautifulsoup4`/`requests`（`tools/local_research_pipeline.py` 專用）改放進 `requirements-dev.txt`
- 新增 `backend/tools/check_dependencies.py`：跑 `pip-audit` 對照 PyPI 弱點資料庫分別掃 `requirements.txt`／`requirements-dev.txt`，目前掃描結果皆無已知弱點。非排程工具，比照 `check_guide_sync.py` 慣例手動執行即可，不會自動跑（新 CVE 隨時可能出現，不適合當成 pytest 套件的硬性關卡，避免無關的套件更新阻擋部署）
- **踩坑**：`requirements-dev.txt` 原本的中文註解讓 `pip-audit` 在這台機器（cp932 locale）解析時直接 `UnicodeDecodeError`——跟 `.ps1` 檔案需要 UTF-8 BOM 是同一類問題的不同變體，這裡改用純 ASCII 英文註解徹底避開編碼猜測
- pytest 439/439 全過

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

> ✅ **已實作半自動版本，見 §15**（2026-08-01j）：`build_deploy_package.ps1` + `apply_update.ps1`，方向是「開發機打包（git archive，強制先 commit）→ 人工複製 → 正式機套用（版本比對＋備份＋安全停服＋健康檢查＋失敗自動回滾）」。仍非全自動：套用前需操作者手動確認一次。
>
> ✅ **兩機 WinRM 網路直連已建立**（2026-09-08，見 §14.3b）：不用再靠人工把部署包複製到隨身碟/雲端硬碟——但**只用來讓開發機能對正式機下遠端指令／傳檔案，不是取代 §15 的部署安全機制**，`apply_update.ps1` 本身仍然要照原本方式在正式機執行（版本比對／備份／健康檢查／自動回滾一個都不能少）。

以下是還沒做、之後可以再評估的方向：

- 拉檔案回開發機（§14.2 方向，跟 §15 相反方向）目前仍是全人工，尚未有對應的半自動工具
- 部署流程全自動化（開發機一鍵打包→透過 WinRM 直接觸發正式機執行 `apply_update.ps1`，不需要人工介入複製或按 Enter 確認）——技術上現在已經有 WinRM 通道可以做到，但故意還沒做，因為 §15 的「套用前需操作者手動確認一次」是刻意保留的人工把關，避免半夜/誤觸發不小心把錯的版本套到正式機

### §14.3b · WinRM 網路直連設定（2026-09-08）

開發機（`hichan`，172.16.11.211）與正式機（`Motrix`，172.16.10.177）現在可以透過 WinRM 直接互相執行遠端指令，不需要再用隨身碟/雲端硬碟人工複製檔案。**用途僅限「輔助操作」**（傳檔案、遠端跑診斷指令、必要時直接呼叫 `apply_update.ps1`），不是要繞過 §15 既有的部署安全機制。

**兩邊各自的設定（一次性，已完成）：**

| 機器 | 設定內容 |
|------|---------|
| 兩邊都要 | `Enable-PSRemoting -Force -SkipNetworkProfileCheck`（需系統管理員權限，UAC 無法用指令繞過，一定要真人點「是」） |
| 開發機 | `Set-Item WSMan:\localhost\Client\TrustedHosts -Value "172.16.10.177" -Force`（信任正式機為遠端目標） |
| 正式機 | `New-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" -Name LocalAccountTokenFilterPolicy -PropertyType DWord -Value 1 -Force`（**工作群組環境必踩的坑**：本機系統管理員帳號遠端連線時 UAC 預設會拿到過濾後的權杖，導致需要提升權限的操作被拒絕，此登錄機值可以解除這個限制） |
| 正式機 | `Get-NetFirewallRule -DisplayGroup "Windows Remote Management" \| Set-NetFirewallRule -RemoteAddress Any`（**第二個坑**：Windows 內建的 WinRM 防火牆規則在 Public 設定檔下預設把遠端位址範圍限定成 `LocalSubnet`，即使兩機實際上在同一個實體網段，只要正式機自己的網卡設的是較窄的 `/24` 遮罩就會判定開發機「不算同子網路」而擋下——即使規則本身顯示 `Enabled: True` 也一樣會擋，因為問題出在遠端位址範圍不是啟用狀態，需要另外放寬） |

**使用方式（開發機執行）：**

```powershell
# 互動式遠端操作，像坐在正式機前面一樣（打 exit 離開）
Enter-PSSession -ComputerName 172.16.10.177 -Credential (Get-Credential -UserName "Motrix")

# 或一次性執行單一指令/腳本
$cred = Get-Credential -UserName "Motrix"
Invoke-Command -ComputerName 172.16.10.177 -Credential $cred -ScriptBlock { hostname }

# 免重複輸入密碼：先把密碼存成只有這台機器這個帳號能解開的加密檔案
Get-Credential -UserName "Motrix" | Export-Clixml -Path "$env:USERPROFILE\motrix_cred.xml"
# 之後用 Import-Clixml 讀回來當 -Credential 參數即可
```

**已知風險（刻意接受）**：正式機多了一個常駐的遠端執行入口（WinRM 服務＋開放的防火牆規則），若開發機帳密或這台機器本身被入侵，攻擊者可直接對正式機下遠端指令——這是持續性攻擊面，經使用者確認可接受這個取捨，換取部署效率。若未來要撤銷，正式機執行 `Disable-PSRemoting -Force` 並把上述防火牆規則改回 `LocalSubnet`／關閉即可還原。

### §14.3c · 本機部署儀表板（2026-09-08）

在 §14.3b 的 WinRM 通道上包了一層網頁 GUI，把「打包→推送→套用」跟「查看正式機狀態」跟「手動回滾」都變成按鈕點選，不用再手打一長串 PowerShell 指令。

**開關方式（2026-09-09 起）**：桌面捷徑「MOTRIX 部署儀表板」→ `backend/tools/deploy_dashboard_ctl.pyw`，一個 tkinter 小視窗，只有「開啟」「關閉」兩顆按鈕＋狀態燈（每 1.5 秒用 TCP 連 127.0.0.1:8765 判定，不靠任何會被系統語系影響的指令輸出）。開啟＝背景以 `pythonw.exe` 拉起 `deploy_dashboard.py`（無主控台視窗，輸出全進 `tools/deploy_dashboard_run.log`），起來後自動開瀏覽器；關閉＝二次確認後找 8765 的監聽者 `taskkill`，且**只殺 python 系列行程**，被別的程式佔用時寧可不動手也不誤殺。取代了原本的 `deploy_dashboard_start.bat`／`deploy_dashboard_stop.bat`（`91a80c8` 新增、2026-09-09 合併後刪除；改 Python GUI 順帶擺脫 .bat 檔不能寫中文的 codepage 限制，見 feedback_windows_locale_encoding_pitfall）。

也可以照舊直接手動啟動：

```
cd backend
python tools/deploy_dashboard.py
```
瀏覽器打開 `http://127.0.0.1:8765`。只綁 loopback，不會被 LAN 上其他機器連到。密碼只在單次部署/回滾請求的生命週期內存在（寫進 `_dashboard_remote.ps1` 子行程的 STDIN 後立即捨棄），不落地、不進 log、不進 `deploy_dashboard_history.json`（只記錄時間/動作/成功與否，不記密碼）。

- 部署／回滾都是**兩段式確認**：填完資訊按第一次按鈕只會跳出摘要卡片，要再按一次「確認套用」/「確認回滾」才真的執行——這是網頁版的人工安全關卡，等價於 `apply_update.ps1`/`rollback_update.ps1` 原本的 `Read-Host "(y/N)"`（WinRM 遠端執行不支援事後對正在跑的遠端 script block 注入互動輸入，遠端呼叫本身帶 `-Yes` 跳過腳本自己的提示，詳見 §12 2026-09-08 條目）。
- 手動回滾：按「查詢可回滾的快照」（需帳密，因為快照清單只存在正式機上）→ 選一個時間戳 → 兩段式確認 → 執行 `rollback_update.ps1`（新檔案，照抄 `apply_update.ps1` 健康檢查失敗時的自動回滾邏輯，差別是操作者主動觸發，用於「健康檢查本身通過、但實際操作發現功能邏輯不對」這種 `apply_update.ps1` 自己不會自動回滾的情境）。
- ~~目前還沒有真正跑過一次完整的部署/回滾~~（**2026-09-10 更正**：截至 09-09 22:16 已累積 **20 次**真實部署嘗試、其中 6 次失敗，逐次因果鏈見 `WEEKLY-AUDIT-2026-09-07_2026-09-10.md` §C-1。⚠️ **但 09-10 那次真正上線的部署沒有走這個儀表板**——`deploy_dashboard_history.json` 裡查不到、`deploy_logs/` 也沒有對應的 build log，代表是直接執行腳本。用儀表板以外的方式部署會同時失去「打包測試關卡」與「歷史紀錄」兩層保障。）
- **已修復一個第一次真實嘗試就撞到的 bug**：`_ps_cmd()` 原本把參數「名稱」（`-Action`／`-Username`／`-PackagePath`）跟「值」混在同一個 list 裡統一加單引號跳脫，導致 `-Action` 被包成 `'-Action'` 純字串常值，PowerShell 認不出是參數旗標，改去綁定成 `_dashboard_remote.ps1` 第一個位置參數的值，撞上 `ValidateSet` 驗證失敗（`Cannot validate argument on parameter 'Action'`）。改成 `named_args: dict` 的介面——參數名原樣輸出（不加引號，因為是我自己寫死的固定字串）、只有值需要跳脫——並用 dry-run 對照 `ValidateSet` 的假腳本實測過確認修復（含值本身含單引號的情況）。**安全性複查那次沒抓到這個問題**：因為當時只推演了「單引號跳脫本身有沒有正確」，沒有實際跑一次生成的完整指令字串驗證參數綁定，這次靠使用者實際點擊部署按鈕才抓到——教訓是「跳脫邏輯正確」跟「整條指令實際能跑」是兩件不同的事，改動這類組指令字串的程式碼一定要跑一次真實 dry-run，不能只靠推演。

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
powershell -ExecutionPolicy Bypass -File "C:\Users\Motrix\Desktop\V9.0\backend\tools\apply_update.ps1" -PackagePath "<複製過去的絕對路徑>"
```

**建議一律用絕對路徑**（2026-09-08 起，見 §12 同日條目）：`-File` 用絕對路徑不影響腳本行為（腳本內部本來就用 `$PSScriptRoot` 反推專案根目錄，跟目前所在目錄無關），純粹是少一步 `cd`、避免在錯誤目錄下執行時「找不到檔案」；`-PackagePath` 本來就該給絕對路徑。兩者都用雙引號包起來，避免路徑含空白時出錯。

| 階段 | 動作 |
|------|------|
| 身分守門 | 確認腳本執行路徑就是正式機路徑，否則中止 |
| 套用前 | 版本比對（commit 相同視為重複套用，需 `-Force` 才強制）；記錄套用前健康狀態；**db 快照**至 `backend/db_backups/pre_update_<timestamp>/`；**Migration 乾跑驗證**（2026-08-01m 新增，見下方說明）；**程式碼回滾快照**至 `backend/rollback_snapshots/<timestamp>/`（保留最新 5 份）；印出摘要，等待操作者輸入 `y` 確認 |
| 停服 | 依 port 666 監聽者 PID／`uvicorn*main:app` commandline 逐一 kill；**不自己啟動新 uvicorn**，改讓既有 `MOTRIX ERP Server Autostart` 排程的 crash-restart 迴圈（§1.1）5 秒內自動接手重啟，避免搶 port |
| 套用 | robocopy 把套件的 `backend/`＋`frontend/`＋根目錄文件覆蓋過去；**只加不改既有多餘檔案，絕不用 `/MIR`**，加上 `/XD`／`/XF` 排除 db／uploads／報價單PDF／logs／設定檔等，即使套件不小心含這些也不會覆蓋 |
| 依賴安裝 | `python -m pip install -q -r backend\requirements.txt`（2026-09-07 新增，見下方說明）；失敗只警告不中止，靠下一步健康檢查當最終安全網 |
| 套用後 | 輪詢 `GET /api/ping` 最多 30 秒＋檢查 `logs/server.log` tail 200 行、**只看「最後一次成功啟動（`Uvicorn running on`）」之後**有無 traceback/ERROR（2026-08-02a 修正，避免把重啟迴圈重試階段已自癒的暫時性錯誤誤判成失敗，見下方說明）；成功→更新 `backend/.deployed_commit.json`；**失敗→自動回滾**（用剛才的程式碼快照復原＋重新停服讓迴圈拉起舊版＋再次確認健康），並印出 db／程式碼快照路徑供人工進一步排查 |

`-Force`：版本比對沒過仍要套用時使用。`-Yes`：跳過互動確認（僅供自動化測試，正常人工執行不要加）。`-CheckOnly`（2026-09-08 新增）：只對目前正在跑的伺服器打一次 `/api/ping`、印出結果就結束，不需要 `-PackagePath`，也不做備份／停服／複製程式碼／pip install／回滾等任何動作——專門用來驗證「健康檢查機制本身」對不對，不用每次都跑一次完整的部署+回滾循環（見下方 Runspace 崩潰條目的教訓）：
```
powershell -ExecutionPolicy Bypass -File "C:\Users\Motrix\Desktop\V9.0\backend\tools\apply_update.ps1" -CheckOnly
```

**Migration 乾跑驗證**（2026-08-01m）：正式庫過去是「第一個試跑新 migration 的地方」——伺服器套新程式碼重啟後 `init_db()` 立刻對正式庫跑 migration，若寫壞了，schema 已經被改壞才被套用後健康檢查發現，「自動回滾」雖然會把 db 整檔換回套用前快照（安全），但仍會遺失套用後到偵測失敗這段時間內產生的新業務資料。現在改成：db 快照做完後，先把快照複製一份到系統 temp 目錄，用**新套件裡的** `db.py`（`init_db(path)` 本來就接受任意路徑，只操作傳入的檔案）在這份副本上先跑一次；失敗就直接中止，不進入停服／複製程式碼／回滾快照等後續步驟，**正式庫全程不受觸碰**。

**健康檢查誤判自動回滾修正**（2026-08-02a）：commit `484c1b4` 第一次在正式機真實套用時，Step 2 停服後沒等 port 666 真正釋放，既有 crash-restart 迴圈搶著重新綁定撞到 `[Errno 10048]` 位址已被使用，重試 2 次後自行成功（迴圈設計上本來就會自癒），但 Step 4 健康檢查掃 log tail 80 行沒有分辨這些錯誤是否已被後續成功啟動蓋過去，誤判成更新失敗觸發回滾（回滾本身正常運作，正式機沒有受到實際影響）。已修正：Step 2 停服後新增主動輪詢確認 port 真正釋放；Step 4 log 掃描只看「最後一次成功啟動」之後的內容。

**缺套件導致真實部署失敗＋新增 pip install 步驟**（2026-09-07）：套用當天累積 12 個 commit 的部署包時，套用後健康檢查真的失敗（`healthy=False`，log 錯誤筆數=9），根因是 `ModuleNotFoundError: No module named 'pyotp'`——`requirements.txt` 早就正確列了新套件，但腳本從頭到尾只複製程式碼檔案，從未執行 `pip install`，正式機環境沒裝過。這次不是誤判，是腳本流程本身真的少了一步；已在「套用新程式碼」與「健康檢查」之間新增 `pip install -r requirements.txt`（詳見 §12 同日條目與 §15.3 表格），步驟數改為 6 步。

**HTTPS 健康檢查 Runspace 崩潰，造成誤判自動回滾**（2026-09-08）：正式機切換 HTTPS 後第一次真實套用，健康檢查連續兩次回報 `healthy=False, log 錯誤筆數=0` 觸發回滾，但 `server.log` 證明新程式碼其實正常啟動成功。根因：`[System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }` 用 PowerShell 指令碼區塊當委派方法，.NET 在 TLS handshake 階段從背景執行緒呼叫它，該執行緒沒有 PowerShell Runspace 可執行指令碼，丟出的例外被健康檢查迴圈的 `catch {}` 整個吞掉、完全不留痕跡。已改用 Windows 內建原生執行檔 `curl.exe -k`（不經過 .NET `ServicePointManager`，無 Runspace 問題）取代 HTTPS 情境下的 `Invoke-WebRequest`，新增 `Test-Ping` 共用函式；HTTP 情境維持不變。**這批事故也暴露一個流程性問題**：修 `apply_update.ps1` 本身的 bug，過去只能靠「真的在正式機跑一次完整部署+回滾」來驗證對不對——同一天因此被迫觸發了兩次不必要的停服/回滾。這正是新增 `-CheckOnly` 模式的動機。

### §15.3b · 正式機輔助工具的分工（2026-09-08 新增）

正式機除了 `V9.0`（實際運作目錄，混著程式碼＋db＋uploads＋logs）之外，可能還有以下輔助工具，**用途要分清楚，不要混用**：

| 工具 | 定位 | 可以做什麼 | 不能做什麼 |
|------|------|-----------|-----------|
| `motrix-erp-repo`（唯讀 git clone，建議放在跟 `V9.0` 平行的位置，例如 `C:\Users\Motrix\Desktop\motrix-erp-repo`） | 緊急單檔案取件用 | 遇到部署工具腳本本身（`apply_update.ps1`／`https_setup.ps1` 等）需要緊急修復、又還沒走完整打包流程時，`git pull` 更新這份 clone，再手動複製「單一檔案」到 `V9.0` 對應位置 | **不要**拿來部署應用程式碼（`routers/`／`frontend/` 等）——應用程式碼永遠只走 `build_deploy_package.ps1`＋`apply_update.ps1` 這套有 pytest 全過關卡＋備份＋健康檢查＋自動回滾保護的流程，直接 `git pull` 覆蓋 `V9.0` 會繞過所有這些保護 |
| 正式機上的 Claude Code session | 套用操作的執行者 | 之後要套用更新，直接請正式機本地的 Claude 執行 `apply_update.ps1`／查 log／驗證健康狀態，不要再讓開發機這邊的人工把指令貼到聊天視窗、請使用者手動轉貼到正式機——2026-09-08 那次事故裡，三次操作型失誤（漏打 `powershell` 前綴、目錄不對、多行 here-string 貼壞）全部出在「人工在兩台機器間轉貼指令」這一步，跟程式邏輯完全無關 | 不會改變 `apply_update.ps1` 本身的安全機制，仍然要照 §15.3 的方式帶 `-PackagePath` 執行，不要圖方便繞過版本比對／備份 |

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
- **新增任何 `import` 第三方套件時，記得同步補進 `backend/requirements.txt`**（2026-09-07 複查發現 `openpyxl`／`Pillow` 這兩個核心功能會直接用到的套件，先前完全沒被記載——`routers/contractors.py` 對 `PIL` 是模組頂層 unconditional import，若一台全新機器照抄 `requirements.txt` 裝環境，裝完直接啟動會在 import 這個 router 時整台伺服器起不來）；只有測試/工具腳本用到、伺服器本身不會 import 的套件（如 `tools/local_research_pipeline.py` 用的 `beautifulsoup4`/`requests`）放進 `backend/requirements-dev.txt` 即可。想確認目前有沒有已知安全弱點，跑 `python backend/tools/check_dependencies.py`（需要先 `pip install pip-audit`，見該腳本 docstring；非排程工具，建議升級套件版本或每季手動跑一次）。
