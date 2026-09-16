# MOTRIX ERP — 開發快速參考

> 允碩整合集創（統編 60575481）｜ Tel: 04-3610-6566 ｜ info@miactw.com  
> 文件版本：**2026-09-16**（通行金鑰備份失敗修復＋Passkey 功能暫緩，DB 無異動，見 §12 最新兩則）
>
> **2026-09-13 新增互補文件**：[`MODULE-AUDIT-2026-09-13.md`](MODULE-AUDIT-2026-09-13.md)——模組機制的三方（權限目錄／側欄／後端）逐 key 對照，七項已修、五項待決策。**動權限／模組相關的東西之前先看那份**，§3.4 只是摘要。
> **⚪ 2026-09-11 待決策（時效性已解除）**：要不要改用 Let's Encrypt 公開憑證、把 RP ID 換成 `erp.miactw.com`——見 **§3.3c** 與 §11 對應列，計畫書 [`LETSENCRYPT-PUBLIC-CERT-PLAN.md`](LETSENCRYPT-PUBLIC-CERT-PLAN.md)。
> **2026-09-16 更新：原本的急迫性（「換 RP ID 會讓既有 Passkey 全部失效，現在只有 1～2 張是成本最低的時刻，越拖越貴」）已不再成立**——Passkey 功能本日起暫緩使用（§12 2026-09-16），沒有人在用，換 RP ID 的失效成本歸零。這件事現在可以純粹按憑證需求決定，不必再被 Passkey 的時效推著走。反過來說：**若日後要恢復 Passkey，順序應該是先把 RP ID 定案再開功能**，否則又會回到「開了之後不敢換」的局面。
>
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
| 2026-09-10 14:28 | **兩邊同時有 Claude session 在動同一個功能（WebAuthn）**：開發機這邊已打包好 `20260910_142806_625b0d6`（內含 `routers/system.py` 的 WebAuthn 設定端點改動）正要部署，使用者即時告知「正式機 Claude 正在跑 webauthn」才停手。若已套用，會直接覆蓋正式機上那個 session 正在改的檔案並重啟服務。**部署包已保留未套用**，等兩邊協調後再處理。正式機當下 `/api/system/webauthn-config-status` 仍是 `configured:false`，代表對方尚未成功寫入設定 | 🟡 **事實上已被覆蓋，但從未查證**——2026-09-10 21:49~2026-09-11 00:59 正式機又從本 repo 連續套用四輪（`37bd985`→`0da86bf`→`4ffe190`→`34e0ce1`，每輪修 Passkey 路上的一個坑，見 §3.3c）。**正式機那個 session 到底改了哪些檔案、有沒有進 git，始終沒有人去確認**；若它有未進 git 的改動，已隨這四輪 `apply_update.ps1` Step 3 一併覆蓋掉。保留未套用的 `20260910_142806_625b0d6` 部署包已無意義（內容早被後續版本涵蓋），可刪。**這正是 §14.3d 交接協定（`AGENT-HANDOFF-TEMPLATE.md`）要防的情境——當時兩邊都沒留交接檔** |
| 2026-09-11 | **正式機的 `system_settings` 有兩個關鍵值不在 git 裡**：`webauthn_rp_id`=`motrix.internal`／`webauthn_origin`=`https://motrix.internal:666`（2026-09-11 由 superadmin 於 `company-profile-settings.html` 填入）。重建環境或還原舊 db 時這兩個值會整個消失，Passkey 端點會回到 503 而看起來像壞掉 | 🟢 已記錄於此（§14 第 4 項本來就提醒過這類設定不在 git）；另**「系統網址」設定是否已改成 `https://motrix.internal:666` 仍未確認**（通知信連結讀的是它），見 `PASSKEY-CA-ROLLOUT.md` 第 8 步 |
| 2026-08-20 | 開發機當時無法連線，承攬商匯款申請／發票開立簽核單功能（DB v45/v46，見 §12）直接在正式機開發，開發機完全沒有這批程式碼 | ✅ 2026-08-23 已回推：`verify_manifest.py` 核對 43/43 相符、開發機本機啟動 server 驗證 `/api/ping`＋schema_version=52 正常後 `git commit`（累計至第 42 輪 2026-08-23q，DB 已到 v52，非僅 v45/v46） |

---

## §1 · 啟動與位址

| 項目 | 值 |
|------|-----|
| 開發啟動 | `backend\start.bat` |
| 更新後重啟 | `backend\restart.bat` |
| 本機 | http://localhost:666 |
| 區網（IP） | **https://172.16.10.177:666**（2026-09-10 起正式機已是 HTTPS，見 §3.3c；憑證 SAN 含此 IP，但**瀏覽器仍會警告簽發者不受信任**，除非該台裝了 mkcert 根 CA） |
| 區網（網域） | **https://motrix.internal:666** ← **Passkey 只在這個位址能用**（RP ID 綁的是它）；前提是該台①裝了 mkcert 根 CA ②解析得到 `motrix.internal` |
| SQLite | `backend\motrix_erp.db`（WAL 模式） |

> ⏳ **這張表的網域欄位有可能整批改掉**：`LETSENCRYPT-PUBLIC-CERT-PLAN.md` 若採用，全站改走
> `https://erp.miactw.com:666`，上面兩個 https 位址都會變成「憑證主機名不符」。決策點見 §11 與 §3.3c。

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
| `db.py` | 連線、`init_db()`、PRAGMA WAL、熱路徑欄位／索引；**2026-09-11 更正：CURRENT_VERSION=74**（本行長期未同步更新，先前記載的 46→68 皆已過時；v69–v74 為 TOTP／WebAuthn 相關，v74 見 §3.3c；v47–v68 詳細主題見 `MOTRIX-ERP-ARCHITECTURE-MAP.md` §4「資料庫演進索引」，含請款單/組織架構/案件階段正規化/專案併入案件管理/網路架構規劃書/自動化系統選型導覽/安全庫存/簽核代理人等；v32/v33 交換器選型導覽 `switch_guide` 表結構由正式機備份還原重建，詳見 db.py `_m032_switch_guide` 註解） |
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

### §3.3c · Passkey／WebAuthn 與 HTTPS 憑證（2026-09-11 起實際可用；**Passkey 已於 2026-09-16 暫緩**）

> 🔴 **2026-09-16 起 Passkey 功能暫緩使用（使用者裁示）**，本節以下描述的是
> **功能開著時**的行為規格，不是現在的畫面。總開關
> `backend/helpers/auth.py::PASSKEY_ENABLED = False`：所有 `/api/auth/webauthn/*`
> 與 `/api/settings/webauthn-config` 回 404，三個前端頁面的 Passkey 區塊都不顯示。
> **是暫停不是移除**——程式碼、`webauthn_credentials` 資料表、既有憑證列全部原樣
> 保留，改回 `True` 就整組回來（含 55 題被 skip 的測試）。細節見 §12 2026-09-16。
>
> 本節的 HTTPS／mkcert CA 部分**不受影響**，那是整站 HTTPS 的基礎，跟 Passkey 無關。

> 兩份專門文件：`PASSKEY-CA-ROLLOUT.md`（自簽 CA 那條路，**已執行完畢**）／
> `LETSENCRYPT-PUBLIC-CERT-PLAN.md`（公開憑證那條路，**規劃完成、尚未執行，是下一個決策點**）。
> 本節只寫「現在是什麼狀態」與「碰它之前要知道的事」，步驟細節看那兩份。

**目前狀態（2026-09-11 01:20 實測）**

| 項目 | 值 |
|------|-----|
| 憑證 | mkcert 自簽，SAN = `DNS:localhost, DNS:motrix.internal, IP:172.16.10.177, IP:127.0.0.1`，有效期至 2028-12-10；舊憑證備份在正式機 `backend\certs\backup_20260910_144802\` |
| 根 CA 指紋 | `A9AF974F0BD6CE35B47CDB95CAA5E2B324DAE61C`（正式機 `%LOCALAPPDATA%\mkcert\`；**`rootCA-key.pem` 絕對不能離開正式機**） |
| 已裝 CA 的機器 | **只有正式機與開發機兩台**。其他同事的電腦要用 Passkey，每台都得做兩件事：①`certutil -addstore -f Root rootCA.pem` ②能解析 `motrix.internal`（兩台的主網卡 DNS 都是 8.8.8.8，不是 Peplink，所以是加 hosts 解決的） |
| RP ID / Origin | `motrix.internal` / `https://motrix.internal:666`（存 `system_settings`，**不在 git 裡**） |
| 用戶端一鍵設定 | `backend/tools/setup_passkey_client.ps1`（裝 CA＋加 hosts，需系統管理員）；`fetch_root_ca.ps1` 從正式機取回 CA |
| 實測 | 使用者已可註冊 Passkey **並用 Passkey 登入**；自動化 e2e `backend/tests/test_e2e_passkey_2026_09_11.py`（CDP 虛擬認證器）覆蓋整條路 |
| **到期告警** | ✅ 2026-09-11 新增 `daily_tasks.py::_check_cert_expiry()`——**在那之前完全沒有任何監控**。門檻依憑證總效期自動切換（>180 天視為手動簽發 → 60/21/7 天；否則視為 ACME → 21/7/1 天），過期後每 7 天重寄。以目前這張算，第一次告警是 **2028-10-11**（到期前 60 天） |

> **2026-09-13 使用者回報的「Passkey 又失效」＝網址問題**（不是憑證、不是 RP ID、
> 也不是 Windows Hello）。當天逐項驗過開發機：mkcert 根 CA 在 LocalMachine\Root 且
> 指紋相符、hosts 有 `172.16.10.177 motrix.internal`、正式機憑證 SAN 含
> `motrix.internal` 有效到 2028、`webauthn-config-status` 為 `configured:true`、
> 正式機為該帳號存了 2 張憑證且都在現行 RP ID 下，而**本機 Windows Hello 裡那張
> `motrix.internal / jeff` 的 credentialId 與伺服器手上的第 2 張完全相同**。
> 也就是說兩邊都好好的，失敗的是入口——**只有 `https://motrix.internal:666` 這個
> origin 能用**；用 IP、`localhost` 或 `http://` 進去，瀏覽器在
> `navigator.credentials.get()` 就會擋。下次再遇到「Passkey 失效」，**先確認網址**，
> 那是成本最低也最常中的一項（通知信的 `base_url` 目前仍是 `http://172.16.10.177:666`，
> 從信裡點連結進去就會踩到）。

**❌ 已排除的替代方案（2026-09-11 決定，不要再重新評估）**

| 方案 | 為什麼不做 |
|---|---|
| **Cloudflare Origin CA 憑證** | 它的根 CA **不在任何瀏覽器／OS 信任清單裡**（設計如此，是給 Cloudflare proxy ↔ 主機那一段用的）。要用就得每台裝 Cloudflare 的根 CA，等於回到現在 mkcert 的處境、一台都沒少，還改成信任一個不是自己控制的第三方根。**解決不了原本的問題** |
| **Cloudflare Tunnel + Access** | 唯一的獨門好處是「從公司外面能用 ERP」，代價是①對外網路一斷，坐在辦公室也連不上②全部 ERP 流量在 Cloudflare 邊緣解密③正式機多一個不在 git 的常駐服務④Access 會在 ERP 登入頁之前再插一層登入。而**使用者規劃中的 VPN 解的是同一個問題**且沒有這四項代價。錢不是因素（該用的方案都在免費額度內） |

> 若之後真的要重開這個討論，前提是「VPN 確定不做」。另外注意：改走 Tunnel **不需要再換一次 RP ID**（RP ID 只認主機名、不含 port），只要改 Origin 設定，既有 Passkey 不會失效。

**⏳ 動 RP ID 之前必讀——這是本模組唯一不可逆的操作**

**一旦改動 RP ID，所有既有 Passkey 全部失效且無法救回**——綁定在瀏覽器端，不在我們手上，
沒有補救、沒有遷移，只能請每個人重新註冊。

**2026-09-11（DB v74）補上 `webauthn_credentials.rp_id`**：v73 建表時沒存這個欄位，代價是系統
**查不出哪張憑證屬於哪個 RP**——只能對使用者說「全部都可能不能用了」，而使用者在裝置清單看到
的是一張外觀完全正常、實際上永遠驗不過的殭屍憑證，登入失敗也只回一句概括的「認證失敗」。
補上之後：

| 位置 | 行為 |
|------|------|
| `login/begin` | 不把舊 RP ID 的憑證交給瀏覽器；**但對外錯誤訊息與「帳號不存在」完全相同**（照實說會洩漏帳號存在＋有註冊過 Passkey，正是 `0527524` 修掉的用戶枚舉），真相寫進 server.log |
| `login/complete` | 回**明確原因**（「此 Passkey 是在舊的系統網域下註冊的…請重新註冊」），不再是籠統的「認證失敗」。走到這一步代表對方握有真實 credential_id，不是枚舉探測 |
| 裝置清單 | 標 `stale`，`change-password.html` 顯示紅色「已失效」徽章與說明；全部失效時卡片徽章顯示「已失效」而非「已設定」 |
| `PATCH /api/settings/webauthn-config` | 回報**精準張數與人數**（原本是回報全表張數，只有一種 RP ID 時剛好等於正確答案） |

> ⚠️ **這個欄位救不回任何憑證**，它讓失效變成「可見、可通知、可清理」。別把這兩件事搞混。
>
> `rp_id=''`（v74 之前的舊資料，來源不明）的取捨是**刻意不對稱**的，兩邊都是「不確定時選傷害較小的那邊」：
> 登入路徑當成「相符」（不確定時不要把人鎖在門外）、失效張數統計則排除（不要謊報「已失效、無法復原」，
> 那句話會讓人去刪掉可能還能用的憑證）。正式環境不會有這種列——v74 回填會填好，而 RP ID 沒設定時根本註冊不了。

**❌ 「新舊網域並行過渡期」做不到——查證後放棄**

原本規劃的進階做法是：驗證時逐張比對憑證自己的 rp_id，開一段新舊網址並行的窗口，讓大家慢慢遷移。
**但這對即將要做的這次切換沒有用**：切到 Let's Encrypt 之後，憑證只涵蓋 `erp.miactw.com` 一個名字
（LE 不可能為 `motrix.internal` 這種私有名稱簽發），而 uvicorn 只能載入一張憑證——**舊網址在切換的
同一瞬間就失去有效憑證**，Passkey 在那個 origin 下本來就不會運作。換句話說並行窗口的前提不成立。

要真的並行，得讓兩個名字**同時**各有一張有效憑證（例如另起一個 port 用舊憑證服務），那是為了
1～2 張 Passkey 而增加的常駐複雜度，不划算。**結論：這次切換就是「所有人重新註冊一次」，
而 v74 讓這件事至少是說得清楚、看得見、清得掉的。**

> ~~**結論：越晚換越貴。** 現在全公司只有 1～2 張 Passkey，這是換 RP ID 成本最低的時刻。~~
> 使用者先前提過「未來會有 VPN、主機可能變更網路環境」——而 `motrix.internal` 是一個
> 只在內網有意義的名字，那個未來一到就會被迫換。
>
> **2026-09-16 修正**：Passkey 已暫緩使用，沒有人在用，**換 RP ID 的失效成本歸零**，
> 「越晚換越貴」不再成立。憑證路線現在可以純粹按 HTTPS 需求決定。
> ⚠️ 但順序有講究：**要恢復 Passkey 的話，先把 RP ID 定案再開功能**，
> 否則又會回到「開了之後不敢換」的局面。

**下一個決策點：要不要改用 Let's Encrypt 公開憑證（`LETSENCRYPT-PUBLIC-CERT-PLAN.md`）**

| | 現況（自簽 CA） | 改用 `erp.miactw.com` |
|---|---|---|
| 每台使用者要做的事 | 裝 CA＋管理員密碼＋要解析得到 `motrix.internal`（macOS 沒有對應腳本） | **什麼都不用做**，Windows/macOS/iOS/Android/Firefox 全部開箱即用 |
| 換網段／加 VPN／換辦公室 | RP ID 被迫換 → 既有 Passkey 全滅 | 不受影響（RP ID 綁主機名，不綁 IP） |
| 代價 | — | ①內網 IP `172.16.10.177` 會出現在公開 DNS ②**所有人必須改用新網址**，舊的 IP／`motrix.internal` 位址會跳憑證主機名不符 ③憑證 90 天到期，續期失敗＝全站 HTTPS 壞掉＝Passkey 全部不能用 |

技術前提都已實測確認：`miactw.com` 的 DNS 在 Cloudflare（有 API）、`erp.miactw.com` 未被佔用、
用 **DNS-01** 驗證所以正式機**不需要對外開放任何連接埠**。續期腳本 `backend/tools/letsencrypt_renew.ps1`
已寫好（比對憑證有變動才動作、用 fullchain、覆蓋前備份、`-InstallSchedule` 建每日排程）
但**尚未執行**——步驟 1、2（Cloudflare 加 A 記錄、建 API Token）與步驟 3（正式機簽憑證）都需要人操作。

> 順序不可顛倒：**先把憑證弄乾淨，最後才改 RP ID**。反過來做只會得到一個「看起來啟用了
> 但不能用」的 Passkey，比誠實地回 503 更難查。

**踩過的坑（四個根因，每一個都讓 Passkey「功能上線但從來沒真的能用」）**

| 根因 | 為什麼拖這麼久才發現 |
|------|-------------------|
| `base64.b64decode()` 解 base64url（`a1f56e9`） | 前端送的是去 padding 的 base64url，每次都丟 `Incorrect padding`，被上層 `except Exception` 收斂成籠統的「認證器驗證失敗」 |
| credential 缺 `type` 欄位（`4ffe190`） | py_webauthn 驗 `type` 必須是 `"public-key"`，前端沒送、後端模型也沒宣告，**兩邊都要改** |
| `login.html` 有兩個 `init()`（`34e0ce1`） | JS 物件實字重複鍵後者勝出且**無任何警告**，`checkWebauthnConfig()` 從來沒被呼叫，Passkey 按鈕永遠不顯示——註冊得起來卻永遠登不進去 |
| `verified.sign_count` 屬性不存在（`34e0ce1`） | py_webauthn 3.0.0 的認證結果叫 `new_sign_count`，只有註冊結果才叫 `sign_count`；每次登入丟 AttributeError 被收斂成 401 |

**共同教訓**：這四個 bug 能一路存活，是因為 Passkey 一直卡在更前面的環節（RP ID 未設、憑證未生效），
**從來沒有人真的走到那一步**——功能上線但從未被端到端驗證過的典型代價。最後是靠 CDP 虛擬認證器
把整條路自動走完才當場抓到後兩個。另外 `34e0ce1` 同時補上 W3C 7.2 的前提：只有新舊簽章計數
至少一邊不為 0 時，計數沒前進才算複製徵兆——Windows Hello 與 iCloud/Google 同步的 passkey
都不實作計數器、永遠回 0，少了這個前提它們每次登入都會被誤判成重放攻擊。

### §3.4 · 角色與模組

> **2026-09-13 全面盤點：[`MODULE-AUDIT-2026-09-13.md`](MODULE-AUDIT-2026-09-13.md)**
> ——三方（權限目錄／側欄／後端）逐 key 對照、七項已修、五項待決策。動模組機制前先看那份。

```
superadmin > admin > sales > engineer > viewer
```

**先記住這一句**：模組決定「**看得到什麼**」，角色與端點內的檢查決定「**能做什麼**」。
35 個可授權模組裡後端真的會擋的只有 19 個（含 7 個 `*_guide_edit`），其餘只影響側欄顯示；
前端沒有任何頁面層守門（`auth-guard.js` 只驗 session），**任何登入者手打網址都開得了任何頁**，
所以不該被看到的資料一定要在端點上擋。新增模組時三邊（`users.html` 目錄／`sidebar.js`／
後端檢查）要一起補，`test_module_keys_consistency_2026_09_13.py` 會擋下只補一邊的情況。

| 角色重點 | 說明 |
|----------|------|
| `engineer` | 預設無 `financial_view`，不可看金額／財務（**注意：這是前端顯示偏好，API 照樣回金額**，見稽核 §4） |
| 模組例 | `project_manage`（＝案件叫料－修改，2026-09-13 補回目錄） · `project_approve_eng` · `project_approve_biz` · `financial_view` · `reports` · `work_log` · `daily_task` |
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
- **已結案（完結案）**：限 **superadmin**（2026-09-13 使用者裁示；前端「完結案」按鈕與
  「全部進度完成」的自動提示同步只給 superadmin）。先前是 admin+，與「已結案只有
  superadmin 能降級」不對稱——按得下去的人比按得回來的人多
- **已結案 → 其他**：限 **superadmin**
- **完結案前置條件（五項，任一未達成即 400 並通知相關簽核人＋最高管理員）**：
  ①執行管理進度 100% ②款項明細全部收齊 ③相關單據簽核完成（報價單／承攬商匯款申請／
  開票申請憑據／出貨單／請款單／**完工單**）④**成本精算已完結**（`settlement.status=='finalized'`）
  ⑤**額外支出無送審中**。③的完工單與④⑤是 2026-09-13 使用者裁示「結案前要確認案件進度、
  精算等這些全數完成」時補的——完工單是 DB v77 才有的模組，當初沒跟著加進清單。
  沒有精算資料／沒有階段／沒有款項的舊案件一律視為「無需檢查」，不會因為後來才有的
  欄位而永遠結不了案
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

**系統內建組織鏈（2026-09-15 改版，`includeSubmitterManagerTier` 預設開）**

```
申請人部門主管  ──不是本人──▶ 就這一層，結束
      │本人
      ▼
處主管（該部門所屬處）──不是本人──▶ 第二層，結束
      │本人
      ▼
到頂：兩層都本人自簽 + 送出時知會其他在職 superadmin（approval_notice）
```

- 本人要簽的層標 `selfApproval:true`；`_exclude_requester()` **不剔除**這種項目
- 前端 `canApprove()`／`isCurrentTierApprover()` 有簽核層時不再排除申請人
  （排除規則只留在無簽核層的 superadmin fallback）
- 自訂層的 `department_manager`／`division_manager` 解析到申請人本人時同樣改為
  自簽（舊行為是靜默剔除 → 整層消失）
- 一次簽多層：同一人（或其代理人）連續當好幾層、且「簽下去該層就完成」時，
  前端在確認視窗講清楚並帶 `cascade:true`，後端 `cascade_self_tiers()` 一次蓋完

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

### §5.10 · 額外支出改版（2026-09-11 交辦，**已完成並上線**）

使用者要求把「額外支出」從精算頁搬到案件管理，並補上填寫人／支出人／送審等機制。
**動工前先讀完本節**，尤其最後那張「必須先確認」的表——裡面每一項猜錯都會做出不能用的東西。

**🚧 施作進度（2026-09-11）**

| 段 | 內容 | 狀態 |
|---|---|---|
| 一 | migration v75 建表＋搬資料＋回填填寫人；存取函式改名；四個讀取端改讀新表 | ✅ `1a43997` |
| 二 | CRUD／送審 API（新 router）＋`APPROVAL_DOC_TYPES` 加新類型 | ✅ `68f6a4a` |
| 三 | 案件管理新畫面（案件內選單）；精算頁那張表移除 | ✅ `ab1e696` |
| 四 | finance-summary／結案報表 PDF／附件端點／簽核設定頁／統一簽核佇列 | ✅ 本輪 |

> ✅ **四段都完成了，功能可用**（2026-09-11）。先前「資料已改從新表讀但沒有填寫入口」
> 那個不能部署的中間狀態已經解除。T100 傳票匯出查證後**不需要改**——
> `accounting_export.py` 從來沒有讀過額外支出。


**🔁 第二輪交辦（2026-09-11 晚，DB v76）：已核准後的「編輯＝變更申請」＋附件上鎖**

使用者：「額外支出上傳照片功能已核准要上鎖，增加編輯按鈕，編輯需要審核。」
並在追問時明確指定 **「原核准金額不動，核准後才生效」**。

| 段 | 內容 | 狀態 |
|---|---|---|
| 五 | DB v76（`change_status`／`change_json`／`change_approval_json`）；附件在已核准時上鎖；變更申請 6 支端點；統一簽核佇列新類型 `extra_expense_change`；案件管理變更申請面板 | ✅ 本輪 |

**⚠️ 這一輪推翻了第四段的一個刻意決定**：附件原本「已核准後仍可補傳憑證」
（理由是補憑證是會計常態），現在改成**跟金額一起上鎖**。推翻的理由是
「核准當下簽核人看到的憑證，跟事後被換掉的憑證不是同一份，等於簽核簽了一個
會變的東西」。`test_extra_expense_uploads_2026_09_11.py` 的檔頭已改寫成新規則
（同一天翻兩次，看到那支測試的人一定會困惑，所以把兩次的理由都寫在裡面）。

**最容易做錯的地方：不要用「退回草稿再改」**

最直覺的實作是「按編輯 → 狀態退回草稿 → 改完重新送審」。**那是錯的**：人一按
編輯，成本／案件財務總覽／營運報表的數字當場就變了，簽核淪為事後追認，正好
違反使用者指定的那句話。正確作法是把提議內容另外存一份：

```
本體（status / total_cost / files_json）           ← 核准前完全不動
   └─ change_status / change_json / change_approval_json   ← 變更申請自己走一輪簽核
                                                              全部層過了才由
                                                              _apply_change() 覆蓋回本體
```

`change_status` 狀態機（與本體的 `status` 是兩條獨立的線）：

```
（無）──存草稿──▶ 草稿 ──submit──▶ 待審核 ──▶ 簽核中 ──approve──▶ 套用並清空
                   ▲                             │
                   └────── 已駁回 ◀───reject──────┘
```

| 決策 | 內容與理由 |
|---|---|
| 用獨立三欄，不共用 `approval_json` | 一筆支出可能被改很多次，每次都是獨立一輪簽核。共用一欄的話，變更申請一送出就蓋掉「這筆原本是誰核准的」——那正是查帳要看的東西。歷次變更 append 進 `approval_json.changeHistory`（含前後金額與核准人） |
| 待核准附件 | 檔案在草稿階段就實際落地（同一個文件資料夾），但只記在 `change_json.addFiles`，**不進 `files_json`**——核准前案件財務與結案報表 PDF 都撈不到。撤銷／駁回後撤銷時實體檔一併刪除 |
| **不支援**「刪除已核准的既有附件」 | 已被簽核人看過、已計入成本的憑證不該被單方面移除，語意同「已核准的項目不可刪除」（要移除請找最高管理員） |
| 簽核流程沿用 `extra_expense` 這個文件類型 | 「改一筆已核准的支出」跟「新增一筆」本來就該由同一批人把關，簽核設定頁不必多一個分頁 |
| 佇列上必須是**獨立類型** `extra_expense_change` | 借用 `extra_expense` 的話，簽核人按核准會打到本體的 `/approve`，那支看到 status 已是「已核准」就回 409——**變更永遠簽不掉，畫面上只顯示一句「簽核失敗」**，沒有人查得出為什麼 |
| 沒有簽核層時送審即生效 | 同新增流程的既有理由：簽核設定是選配的，不能因為沒設定就把人永久卡住 |

**端點**（全部掛在 `/api/quotations/{quote_no}/extra-expenses/{id}/change-request`）

| 方法 | 路徑 | 說明 |
|---|---|---|
| PUT | `` | 建立／更新草稿（**只有已核准的項目**走這條；草稿與已駁回直接 PATCH 本體即可） |
| DELETE | `` | 撤銷（草稿／已駁回；送審中要撤銷請先請簽核人駁回） |
| POST | `/files` | 上傳待核准附件 |
| DELETE | `/files/{file_id}` | 刪除待核准附件 |
| POST | `/submit` | 送審 |
| POST | `/approve` | 核准當層；全過了才 `_apply_change()` |
| POST | `/reject` | 駁回 → 已駁回（本體從頭到尾沒動過，不需要回滾） |

**測試**：`test_xe_change_request_2026_09_11.py`（10 題）＋
`test_e2e_extra_expenses_ui_2026_09_11.py` 新增兩題（已核准列的鎖定與編輯入口、
瀏覽器完整來回）。六個破壞驗證全紅（把修好的行改回壞掉的樣子，確認測試會抓到）。

**⚠️ 搬資料時抓到的兩個「會讓資料無聲消失」的坑（都在實跑 db 副本時才發現）**

| 坑 | 後果 | 修法 |
|---|---|---|
| 歸月日期少了 `editHistory` 的兩層 fallback（精算完結時間／最後存檔時間） | 實測 7 筆既有資料**有 6 筆 `expenseDate` 與 `createdDate` 都是空的**，全靠那兩層歸月——少了就是 **7,990 元直接從月支出報表蒸發，而且不會有任何錯誤**。正是 2026-09-09 修過的同一類問題 | `_move_extra_items_for_quote()` 把四層 fallback 完整搬過來，並有回歸測試 |
| 品項說明少了 `name`／`desc` 這兩個舊欄位名的 fallback | 舊資料的說明整欄變空白，報表明細只剩類別、對不回實體憑證 | 同上，`description or name or desc` |

**教訓**：搬資料時「欄位對欄位」照抄不夠——**舊的讀取函式做了哪些 fallback，要一起搬**。
這兩個都不是搬移邏輯寫錯，是原本的讀取端比表面上複雜。動手前先把舊讀取函式整個讀完，
不要只看資料長什麼樣子。搬完務必**在 db 副本上實跑一次並逐筆比對**，不能只跑測試——
這兩個坑的測試資料都很乾淨，是拿真實資料跑才看出來的。

**第四段改了哪些讀取端**

| 位置 | 改動 |
|---|---|
| `quotations.py::get_finance_summary()` | 改讀新表；多回 `status`／`pending`／`payerName`。⚠️ 連帶把 `conn.close()` 移到查詢之後——原本在它之前就關，改完會變成 use-after-close |
| `pdf_gen.py::_case_closing_report_data()` | 改讀新表；結案報表多「支出人」與「狀態」兩欄——對外文件要讓看的人知道哪幾筆還沒簽完 |
| 附件端點 | 從 `/settlement/extra/{idx}/files` 搬到 `/extra-expenses/{id}/files`，**改用資料列 id 而不是陣列索引**（索引會因新增／刪除／重排指到別筆去）。檔案分類 `quotation_settlement_extra` → `case_extra_expense`。**刻意的行為改變**：已核准之後仍可補傳憑證（補憑證是會計常態，核准當下常常還沒拿到紙本發票），但金額與說明仍然鎖住 |
| `approval-settings.html` | 套用範圍多選加入「案件額外支出」，預設跟統一流程走、取消勾選即獨立 |
| 統一簽核佇列 | `/approval-queue` 與 `/approval-queue/count` 都加入；前端補 `extra_expense` 的類型標籤、核准／駁回 URL（掛在案件底下，形狀與其他類型不同）與「沒有 PDF 可預覽」的分流 |


**實作筆記（第一段）**

- 新表 `case_extra_expenses`，欄位見 `db.py::_m075_case_extra_expenses()`。
  `data_json` 裡的原陣列**刻意保留**當唯讀備份，不再被任何程式碼寫入。
- 存取函式 `settlement_extra_expenses(data)` → `case_extra_expenses(conn, quote_no)`。
  **刻意改名**：沿用舊名只改實作的話，漏改的呼叫端會安靜地拿到空陣列、
  報表數字歸零卻不報錯。改名當場就抓到一個原本沒發現的呼叫點（`reports.py:3440`）。
- `pending` 語意從「精算未完結」改成「送審未核准」。依使用者指定，
  送審中的項目**照樣算進成本**（不算會讓當月的錢消失）但標 pending。
- 搬移邏輯抽成 `db.py::_move_extra_items_for_quote()`，**測試用同一支**——
  欄位對應與日期 fallback 在測試裡另外複製一份的話，兩邊遲早會漂移。

**現況（2026-09-11 實際翻程式碼與資料庫確認，非依賴舊文件）**

| 項目 | 現況 |
|---|---|
| 位置 | `settlement.html`（精算頁）「二、額外支出」表格，`settlement.html:440-600` |
| 資料落點 | `quotations.data_json` → `settlement.extraItems[]`，**無獨立資料表、無 migration** |
| 既有欄位 | `id`(Date.now())、`category`、`description`、`qty`、`unit`、`unitCost`、`totalCost`、`note`、`expenseDate`、`createdDate`、`docNo`、`files[]`、`createdBy` |
| 類別選項 | 固定七項 `<select>`：工時／材料／差旅／運費／安裝／外包／其他（`settlement.html:492-504`） |
| 唯讀顯示 | `case-management.html` 財務分頁的「精算額外支出明細」（可展開），資料源就是同一份 `extraItems` |
| 計入方式 | `finExtrasTotal()` 只顯示總額，**刻意不計入「應付總額」**——那個數字的定義是承攬商匯款申請 |
| 送審 | **完全沒有**。精算頁存檔就生效，只有 `settlement.status` 的 draft／finalized 兩態 |

**⚠️ 已查證的兩個現行缺陷（改版時一併修掉，不要照抄舊行為）**

1. **`createdBy` 永遠是空字串**——`settlement.html:1096` 取 `this.session?.user?.display_name`，
   但這個路徑不存在；同一支檔案其他地方（`:1187`、`:1221`）用的都是
   `this.session.displayName || this.session.username`。實測開發機 db：
   **7 筆既有額外支出，`createdBy` 有值的 0 筆**。2026-09-09 新增這個欄位的目的正是
   「案件財務總覽要顯示填寫人」，結果那裡永遠顯示「填寫人：—」。
   → 這也正是使用者這次提「要自動帶入填寫人」的由來。既有 7 筆資料要決定是否回填。
2. **類別欄位寬度寫死**——`<th style="width:90px">` ＋ `select` 的 `font-size:11px`，
   中文選項（「外包」「安裝」）在某些縮放比例下會被截斷，且不隨內容自適應。
   → 使用者說的「類別太小沒有自適應」。

**使用者要求的七項**

| # | 要求 | 備註 |
|---|---|---|
| 1 | 從精算頁搬到**案件管理的案件內選單** | 精算頁那張表要保留唯讀還是整個移除，見下方待確認 |
| 2 | 類別欄位加寬、**自適應** | 連同整列在窄螢幕的排版一起處理 |
| 3 | **自動帶入填寫人**（目前的人）＋ **可選「支出人」** | 支出人是新欄位，跟填寫人是兩回事：填寫人＝誰輸入這筆，支出人＝錢實際由誰支付／代墊 |
| 4 | **填寫日期**與**更動日期** | 填寫日期≠支出日期（`expenseDate` 已存在）；更動日期要在每次編輯時更新 |
| 5 | **填寫需送審** | 接哪一套簽核見下方待確認 |
| 6 | 相關支出計算對應**都要與現有的結合** | 精算總成本、案件財務總覽、營運報表、T100 傳票匯出都讀得到這批數字 |
| 7 | 備註要寫清楚 | 即本節 |

**❓ 動工前必須先跟使用者確認（猜錯會做出不能用的東西）**

| # | 問題 | 為什麼不能猜 |
|---|---|---|
| A | 「支出人」是從**使用者清單**選、從**承攬商清單**選，還是自由文字？ | 三種的資料模型與後續統計完全不同；若要做「某人代墊多少」的彙總，就必須是 id 而非文字 |
| B | 送審接**哪一套**？現有兩套機制：`helpers/tiered_approval.py`（五種文件共用的分層簽核）或 `case_change_requests`（半解鎖的排隊重放） | 前者要新增文件類型＋簽核設定頁要多一個分頁；後者是「暫存 payload、核准時重放」，改動小但語意是「變更申請」不是「單據」 |
| C | **送審中的項目算不算進成本？** | 影響精算總成本、案件財務總覽、月支出、營運報表四處的數字。若算，核准前後金額不變、簽核形同虛設；若不算，精算頁在等待期間會少一筆，使用者可能以為資料掉了 |
| D | 精算頁的那張表**保留唯讀還是整個移除**？ | 保留＝兩個地方看得到同一份資料（要明確標示唯讀與入口在哪）；移除＝精算頁的「額外支出小計」要改成連結過去 |
| E | 已結案案件還能不能新增／編輯額外支出？ | 現有 `_deny_if_case_locked_unsupported()` 的 13 支端點一律 403，這批新端點要歸到「支援排隊審核」還是「直接擋」 |
| F | 既有 7 筆 `createdBy` 空白的資料要**回填**還是留空？ | 回填只能用猜的（沒有紀錄誰建的），留空則報表上會一直有「—」 |

**技術註記**

- 目前 `extraItems` 存在 `data_json` 裡。要做送審與「更動日期」的稽核軌跡，**建議改成獨立資料表**
  （比照 `case_stages` 從 data_json 正規化出來的前例，見 §11 相關列）；若維持 data_json，
  送審狀態與歷史版本會很難查。這是本案最大的架構決策，會決定要不要 migration。
- 金額欄位若改為「送審核准後才計入」，`routers/quotations.py::get_finance_summary()`、
  `settlement` 彙總、`accounting_export.py`（T100）三處都要同步，**不要只改畫面**。
- 送審通知沿用 `notify_module_activity()` 與 `_check_approval_reminders()` 既有機制即可，不必新寫。

---

### §5.11 · 執行進度勾選 → 兩張行事曆（2026-09-11 交辦，DB v76）

使用者：「報價單成交跟案件管理執行進度勾選進單確認、叫料出貨這些或是手動打上的
選項，只要有勾選，要同步於行事曆標註，例如當日勾選客戶驗收，行事曆要增加案件
名稱＋進度在行事曆上。」追問「行事曆」指哪一個時，回答 **「兩邊都要」**——
Google 行事曆與系統內「每日工作事項 → 月曆總覽」。

**兩條路徑各自的落點**

| 目標 | 實作 | 記在哪 |
|---|---|---|
| Google 行事曆 | `helpers/google_calendar.py::push_event_for_case_stage_done()` | `case_stages.google_calendar_done_event_id`（v76 新欄位） |
| 系統內月曆 | `helpers/case_stage_tasks.py::sync_daily_task_for_case_stage()` | `case_stages.daily_task_id`（v76 新欄位），指向一列 `daily_tasks` |

兩支都由 `routers/quotations.py::update_case_stage()` 以 `spawn_bg_thread()` 觸發
（fire-and-forget，失敗只記 log，不能擋住勾選本身）。觸發條件是 **`done` 真的翻面**，
或**已勾選的情況下改了 `done_at`**；只改標題之類的不重推（每推一次就是一趟 Google API）。

**四個一定要注意、而且做錯都不會有任何錯誤訊息的地方**

| # | 坑 | 後果 | 作法 |
|---|---|---|---|
| 1 | 完成日事件共用 `google_calendar_event_id` | 那一欄記的是**到期日**事件（v55）。共用的話，設了到期日再勾完成，後者會把前者的事件改成完成日，**到期提醒就這樣無聲消失** | v76 另開 `google_calendar_done_event_id` |
| 2 | `daily_tasks.assigned_to` 留空 | `daily_tasks.py::_user_filter_sql()` 對非 superadmin 只回「我是負責人或監督人」的任務——空的那列等於做了一個使用者**看不見**的東西 | 階段負責人優先，沒有就掛勾選的人 |
| 3 | 建立時沒有標成已完成 | `_check_overdue_and_notify()` 每天掃前一天的 `once` 任務，沒有完成紀錄就寄逾期信——**對一件已經做完的事，隔天寄信給每個負責人** | 同時寫 `daily_task_completions`（`completed=1`） |
| 4 | 取消勾選靠標題比對去找那一列 | 標題含案件名稱，案件一改名就對不上 | 用 `case_stages.daily_task_id` 記住 id；取消勾選 soft delete（`is_deleted=1`），階段被刪也一併收回 |

**事件內容格式**（使用者指定「案件名稱＋進度」）

- Google：標題 `{案件名稱}｜{進度} 完成`，日期用 **`done_at`**（勾選時前端自動帶今天，可改成實際完成日），
  說明欄含案件編號／客戶／完成日期
- 每日工作事項：`title` = `{案件名稱}｜{進度}`，`category` = `案件進度`，`task_date` = `done_at`，`case_no` = 報價單號

**順帶改掉的**：`push_event_for_quotation_won()` 的標題補上案件名稱
（原本是 `報價單成案 — {單號}（{客戶}）`，案件名稱只在說明欄裡，Google 的月檢視
只看得到標題）。使用者這次把「報價單成交」跟執行進度並列提出來，多半就是因為
在月檢視上認不出那是哪個案子。

**測試**：`test_case_stage_done_calendar_2026_09_11.py`（10 題，含「端點有沒有真的
接上這兩支」與「只改標題不該重推」）。⚠️ 該檔有一個 autouse fixture 把端點自己起的
背景執行緒關掉、改成測試裡明確同步呼叫——不關的話端點的執行緒會跟測試自己的呼叫
同時寫同一列，斷言拿到誰的結果純看排程（**實際偶發紅過一次**）。那是測試自己製造的
競態，不是產品的：正式流程一次勾選只會起一支執行緒。

---

### §5.12 · 收款資料異常：「已收款」與「收款日期」是兩個欄位（2026-09-11）

**起因**：使用者回報「案件資訊有一筆 2026/09/01 收款，沒有同步顯示於營運報表計算
當月收入」（`MQ-202607-045` 交貨款）。

**查證結果：報表的計算邏輯是對的。** 在 db 副本上把那筆設成
`received=true` / `receivedAt=2026-09-01` 之後，`_collect_income_items()`（收支報表）
與 `_collect()`（主財務報表）**兩支都撈得到**（NT$ 263,828）。所以不要去改報表。

真正的原因是那兩個欄位**各自獨立**，只填一個就會出事：

| 狀況 | 收入報表 | 未收報表 | 使用者在案件裡看到的 |
|---|---|---|---|
| `received=1`、`receivedAt` 空 | ❌ 不屬於任何月份 | ❌（已收，不算未收） | 綠色的「已收款」 |
| `receivedAt` 有值、`received=0` | ❌（未收） | ❌ 未收看的是 `expectedReceiptDate` | 收款日期欄有日期 |

**兩種都是兩邊都撈不到**——錢從所有月報表上消失，而且沒有任何錯誤訊息。跟
2026-09-09 修過的「精算未完結的額外支出被月支出漏算」、`_m075` 搬移時抓到的
「歸月日期少了兩層 fallback」是同一類坑：**資料形狀不完整時靜默丟棄**。

**作法：不修計算，改成把狀態變成看得見的**（三個地方）

| 位置 | 內容 |
|---|---|
| `routers/reports.py::_collect_payment_anomalies()` | 偵測上表兩種形狀，範圍與 `_collect_income_items()` 完全一致（`deal_tag IN ('已成案','已結案')`），金額走 `payment_item_amounts()` |
| `GET /api/reports/payment-anomalies` | 獨立端點（admin+）；`/api/reports/expenses-monthly` 的回應也帶 `paymentAnomalyItems`／`paymentAnomalyTotal` |
| `case-management.html` 款項明細 | 那一列底下直接跳提示，寫明「不會計入營運報表的當月收入」 |
| `reports.html` 收支分頁 | 最上方一張「收款資料異常」表，案件號可點過去修 |

**兩個刻意的決定**

- **不隨期別篩選**：這些款項正是因為欄位不完整而不屬於任何月份，用期別去篩等於
  再篩掉一次，那正是這一區要解決的問題本身。
- **不自動修正**（例如「有日期就當作已收」）：錢收到了沒有是人的判斷，系統替使用者
  決定，錯了會比漏算更嚴重。這裡只負責點名。

**⚠️ 開發機 db 副本（2026-09-11 11:27）實跑出來的既有異常——正式機大概率也有**：
**4 筆、合計 NT$ 1,626,990**，其中 `MQ-202608-007` 兩筆就佔 **NT$ 1,576,240** 是「已勾已收款、沒填收款日期」，
目前在任何月份的收入報表上都看不到。上線後請開營運報表 →「月支出」分頁最上方
那張表，逐筆補齊。

---


**🔁 2026-09-12 後續：分頁口徑也一起改了**

同一位使用者隔天又回報同一筆（`MQ-202607-045` 交貨款，截圖顯示已勾已收款、收款
日期 2026/09/01），但營運報表的「**已收款**」分頁還是 0。這次的根因跟上面那個
（欄位只填一半）**不是同一件事**：

「已收款／未收款」兩個分頁原本是依**成案月份**分組（2026-09-09 初版設計）。
`MQ-202607-045` 在 2026-07 成案，所以那筆 9/1 收的錢一直被算在 **7 月**——實測
7 月那頁抓得到、金額 263,828。分頁標題只寫「已收款」，看不出它問的其實是「當月
**成案**的案子收了多少」。

依使用者指示改成**收款日期口徑**：已收款看 `receivedAt`、未收款看
`expectedReceiptDate`，年／季／月三個範圍一起改。

⚠️ **改這個最危險的地方是「缺日期的會消失」**：實測開發機未收款 7 筆**全部沒填
預計收款日**，直接照日期分組會讓它們從每一個月份都撈不到。所以另外回傳
`undated*` 兩組（不隨期別篩選、**不併進月份合計**——併進去同一筆會在每個月被
重複計算），前端在兩個分頁下方各列一區並說明怎麼補。

### §5.13 · 完工單（2026-09-12 交辦，DB v77）

使用者：「在案件管理內增加完工單的選項，參考出貨單的形式跟內容建立完工單，一樣走
流程申請完工，內容先由你依據企業完工單撰寫。」

**形狀比照出貨單**：`completion_notes` 表與 `routers/completion_notes.py` 跟
`shipping_notes` 同構——一個報價單可有多張完工單（分階段／分區完工）、同一套狀態機
（草稿→待審核→簽核中→已核准）、共用 `unified_approval_flow`（文件類型
`completion`，預設走統一流程、可在簽核設定頁取消勾選改成獨立）、核准後客戶回簽並
可上傳簽回附件、PDF 匯出與匯出紀錄。單號前綴 `CN`。

**刻意跟出貨單不同的三件事**

| # | 差異 | 為什麼 |
|---|---|---|
| 1 | **不碰庫存** | 東西在出貨單那一關就出掉了。跟著抄庫存扣減會讓同一批序號被扣兩次，而且第二次扣時第一次已不是 `in_stock`，核准直接 409 ——**完工單永遠簽不掉**。有專門一題測試釘住 |
| 2 | **送審強制要有完工日期** | 保固起算與工期都以它為準，缺了這張單就沒有意義 |
| 3 | **項目有完成狀態**（完成／部分完成／未施作），且**不擋**有未完成項目的送審 | 擋下來現場只會被迫把沒做完的也填「完成」，遺留事項那欄就永遠是空的。改成把未完成數量算出來，清單、簽核佇列、送審確認視窗三處都顯示 |

**完工單內容（依台灣工程業慣例撰寫）**

客戶與施工地點（**施工地點≠送貨地址**）／工程期間與保固（開工日、完工日、工期、
保固起訖、現場負責人）／完工項目明細（含完成狀態）／施工說明／測試與檢驗結果／
**遺留事項**（PDF 上用紅框）／業主驗收與承攬商雙方簽章。

> 遺留事項那一欄最容易被省略，也最重要：**完工不等於零缺失**，沒寫清楚的缺失在
> 日後驗收爭議時沒有任何依據。所以畫面上只要有項目填「部分完成／未施作」，就會
> 跳出提示把使用者推到那一欄。

**保固**：`warranty_months` 自**完工日**起算，用既有的 `helpers/dates.py::_add_months()`。
⚠️ 刻意**不**自動建立保固追蹤紀錄——保固模組有自己的資料來源，偷塞一筆會變成兩套
來源打架。先存月數、PDF 印出起訖，要不要接進保固追蹤之後另議。

**路上抓到的一個靜默錯誤**：`_warranty_range()` 第一版把字串丟給吃 `date` 物件的
`_add_months()`，TypeError 被 `except Exception` 吞掉，保固迄日永遠是空字串、畫面
與 PDF 都只是「沒顯示」而不報錯。已改成只吞 `ValueError`（日期格式不合法，屬預期
情況），型別錯不再靜默。**這是本專案第 N 次被寬鬆的 except 藏住真錯誤。**


**🔁 2026-09-12 同日回饋：這份完工單太偏向工程**

使用者：「我們公司除了工程外還有專案、販售零組件、系統設定、網路架構、防火牆等
多項業務，這份完工單太偏向工程。」並逐一點名要能改名的欄位。改了三件事：

**① 預設用語改中性**

| 原本 | 現在 |
|---|---|
| 施工地點 | 服務地點 |
| 二、工程期間與保固 | 二、執行期間與保固 |
| 三、完工項目明細 | 三、完成項目明細 |
| 四、施工說明 | 四、執行說明 |
| 六、遺留事項 / 待改善 | 六、待辦與未完成事項 |
| 工程項目 / 規格說明 | 項目 / 規格說明 |
| 現場負責人 | 負責人 |
| 業主驗收 · 簽章蓋印 | 客戶驗收 · 簽章蓋印 |
| 承攬商 · 工程負責人 | 執行單位 · 負責人 |

有一題測試掃過**全部**預設標題，只要出現「施工／工程／承攬商／業主」就紅——
避免之後有人順手又把工程用語加回去。

**② 這 11 個標題每一張完工單都可以自己覆寫**

存在 `data_json.labels`，**刻意不開新欄位**：純粹是列印用字串、永遠整包讀寫、
不會被查詢或彙總，正是 data_json 適合放的東西。（額外支出當初要正規化出來，是因為
每一列需要各自的簽核狀態與稽核軌跡，跟這裡不是同一種需求——不要混為一談。）

- 空字串視為「沒覆寫」，不是「標題留白」：標題整個消失只會讓人以為版面壞了
- 只接受已知的鍵、每欄上限 40 字
- `labelOverrides` 另外回傳使用者真正改過的那幾欄，前端表單才不會被預設值塞滿
- ⚠️ 編輯時 data_json 一定要 **read-modify-write**，整包覆蓋會把 `approval` 洗掉
  （被駁回退回草稿的單子仍留著那段歷史）。有測試釘住

前端提供五組預設一鍵套用：工程施工／系統建置·設定／設備·零組件供應／
網路架構·資安／維運服務。

**③ 保固期間可不顯示**

比照**報價單「條件留空就不印」**的既有慣例（`pdf_gen.py::term_block()`），不另外
開顯示旗標：保固月數 0／留空 → `_warranty_range()` 連起算日都不回、PDF 整列不印。
零組件販售、系統設定那類單子常常沒有保固可言。

**④ PDF 上方第三欄從「關聯報價單」改成案件名稱**（使用者指定），案件編號移到
第二區保留可追溯性。

**⑤ 填寫介面改成獨立頁面**（使用者：「可用報價單的方式去建立，一個頁面做填寫，
多增加可切換的頁面」）

`frontend/pages/completion-note-form.html`——跟「報價單清單 → 報價單表單」同一種
分工：清單留在案件管理的完工單分頁，填寫在獨立頁面。固定工具列＋四個分頁
（基本資料／完成項目／說明與驗收／單據用語）。

> ⚠️ 這一頁刻意**沒有** `x-init="init()"`。Alpine 3 自己就會呼叫 `init()`，兩者
> 並存會跑兩遍，第二次載入的回應會把使用者改到一半的欄位蓋回去（2026-09-11 在
> `case-management.js` 與 `company-profile-settings.html` 各踩過一次）。有一題
> e2e 數請求次數釘住它。**新增頁面時請照這個寫法，不要再加 x-init。**


**🔁 2026-09-12 再一輪回饋：整合成一頁、帶入報價單資料**

| 使用者說的 | 處理 |
|---|---|
| 「公司的業務不只工程…選一組最接近的」那段說明不要 | 改成一句「依據案件類型選取適合的完工單，再視需要逐欄微調」 |
| 基本資料可拉報價單的地址包含聯絡人 | 新增時從報價單 `data_json` 拉 `deliveryAddress` → 服務地點、`contactName` → 驗收人/聯絡人、`contactPhone` → 聯絡電話（**DB v78** 新欄位），地址欄下方標明「已從報價單帶入，可直接修改」 |
| 是否能整合成一頁逐條改善下來不要有分頁 | 拿掉四個分頁，改成單一頁面由上往下填；分頁用的 CSS 與 `tab` 狀態一併移除 |

**`contact_phone` 為什麼開欄位而不是塞 `data_json`**：那是業務資料不是版面設定
（標題那組才是後者，所以放 data_json）。完工單是會交到客戶手上、之後可能要回頭
聯絡的文件，只有名字沒電話等於還要再翻報價單。

⚠️ **e2e 改寫時的一個重點**：驗「四個區塊同時可見」要用 `state="visible"`，**不能
只檢查元素存在**——分頁那一版元素也「存在」，差別只在看不看得見。另補一條
「分頁按鈕不該再存在」，避免之後有人把分頁加回來而測試照樣綠。

**測試**：`test_completion_notes_2026_09_12.py`（15 題）。PDF 用 Edge headless 實跑
產出 383KB 的真檔案驗證過，不是只有語法正確。

---

## §6 · Sidebar 結構

```
主選單     儀表板
業務       業務開發（dev-crm.html, dev_crm 模組旗標或 admin+）/ 報價單 / 簽核佇列（approval-queue.html）/
           簽核代理人（approval-delegates.html）/ 簽核歷史（approval-history.html，2026-09-14 新增）/
           案件管理（⚠️ 「專案管理」已於 2026-08-26 併入案件管理，projects.html 已刪除，不再是獨立項目）
           ※ 簽核三兄弟（佇列／代理人／歷史）共用 `quotation` 模組或 admin+ 的顯示條件
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

- ~~簽核佇列不在 sidebar，在報價單內 tab~~（已過時：2026-08-20j 整合成獨立頁 `approval-queue.html` 後就有自己的側欄項目）
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
  - **涵蓋度總覽**（2026-08-09）：`selection-db-overview.html`；admin+ 限定，無獨立模組旗標；彙總「品牌/型號目錄」型類別（不含場域選型導覽——資料形狀是情境×分層文字建議而非品牌目錄）在各世代/分類底下的品牌數與產品數，紅/黃/綠三色標示完全空白／偏薄弱／足夠；**不新增後端 API**，純前端呼叫既有各類別 GET 端點彙總而成。**2026-09-11 查證：先前確實漏了自動化系統選型導覽（第七類，2026-08-26 上線），已補**——`loadAll()` 原本只撈 netarch／switch／monitor／access／gateway 五組，而 `automation-guide.html::applyDeepLink()` 早就寫好接這頁深層連結的程式碼，只差那一組 fetch。**漏掉不會有任何錯誤訊息、頁面照常渲染**，所以新增第八類時務必同時補這頁；e2e `test_e2e_selection_overview_2026_09_11.py` 會比對六個區塊標題，漏了就紅
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
| GET | /auth/totp/status | 目前使用者是否已啟用 TOTP（需登入）；2026-09-11 新增 `recoveryCodesRemaining` 剩餘救援碼組數（只回組數、不回內容——DB 只存雜湊，明文從一開始就只在產生當下出現一次） |
| POST | /auth/totp/setup | 產生新密鑰＋QR code（需登入，任何角色） |
| POST | /auth/totp/enable | `{code}` 驗證後才真正啟用，回傳 10 組一次性救援碼（僅此次可見明文） |
| POST | /auth/totp/recovery-codes/regenerate | 重新產生 10 組救援碼（2026-09-11）；需 `{password}`（比照 disable 的敏感操作慣例，**不**再要驗證碼——會用這支的情境正是驗證 App 拿不到）；**整組換掉、舊碼全數失效**（非「補足到 10 組」，避免舊清單變成「某幾組還有效但不知道哪幾組」）；未啟用 TOTP 時回 400 |
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
| GET | /approval-queue | **admin+ 看全部；其他角色只回「自己送審的」與「簽核鏈裡有自己的」**（2026-09-15，`_queue_visible_to()`，過濾只有一處、套在組好的 items 上，新增單據類型自動被蓋到）|
| GET | /approval-queue/detail?type&id | 一筆待簽核項目的完整內容：屬於哪個案件、內容欄位、明細、**夾帶檔案**（含預覽類型）、**編修後的結果**。清單刻意不帶這些（上百筆會變慢），點開才拿 |
| POST | /quotations/{no}/approve \| reject | 並行層簽核 |
| POST | /approval-queue/reassign | **轉簽**（限 superadmin）：把一筆待簽核換人。`reason` 必填（空白→400）；只換**當層第一個尚未簽核**的人，已簽過的與後面幾層不動；非待審核／簽核中→409。支援 quotation／contractor_voucher／invoice_voucher／payment_request／shipping_note／completion_note |
| GET | /approval-history?month&q&scope&limit&offset | **簽核歷史**：建在 `audit_log` 上（不另開表）。`scope=mine` 任何人看自己、`scope=all` 限 admin+；`q` 同時比對單號／標籤（含客戶名）／備註內容／簽核人；回傳含 `months[]` 每月筆數 |

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
| GET | /online-users | **限 superadmin**：目前在線成員與人數（5 分鐘內有活動，資料源 `sessions.last_active`，不另做心跳） |
| GET | /user-activity?start&end | **限 superadmin**：每位成員的活躍時數統計（DB v79 `user_activity_daily`）。**是活躍時間不是登入時長** |
| GET | /user-activity/trail?user&start&end&limit&before_id | **限 superadmin**：逐條操作軌跡（DB v80 `user_request_log`）。每筆帶 `summary`（一句人話）／`kind`／`resultLabel`／`pageLabel`／`repeat`，翻譯規則在 `trail.py`。頁面自動發的請求不記、一次點擊的連鎖請求算一次、保留 90 天 |
| POST | /edit-presence | 回報「我在編這份文件」並取回還有誰在編（`{doc_type, doc_id}`，任何登入者）；TTL 90 秒 |
| DELETE | /edit-presence | 離開編輯畫面時釋放（選用，不送也會自然過期） |
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

### §7.20 · 叫料（材料訂購）（後端 2026-09-10、前端 2026-09-11，DB 無異動）

| Method | Path | 說明 |
|--------|------|------|
| GET | /quotations/{no}/material-orders | 回 `{quoteNo, materialOrders, totalAmount, paidAmount}`；只要求登入＋擁有者檢查 |
| PATCH | /quotations/{no}/material-orders | **整包覆蓋**（無增量更新）；需 admin+ 或 `project_manage` 模組；已結案回 400 |

資料落在 `quotations.data_json` 的 `caseRecord.materialOrders`，**沒有獨立資料表**——查不到專屬 migration 是正常的。後端逐筆驗證的三條規則（`routers/material_orders.py` 第 5 步）前端也各擋一次，只為了給看得懂的中文訊息：

```
小計必須等於 數量 × 單價（容差 0.01）  → 所以小計一律由前端算，不讓使用者手填
pending      → 已付金額必須 0、日期必須空
partial/paid → 0 ≤ 已付金額 ≤ 小計，且日期必填（paid 時已付金額 = 小計）
```

前端入口：案件管理「財務」分頁的 `#fin-material-orders` 區塊（`case-management.js` 的 `loadMaterialOrders()`／`moSave()`／`moRecalc()`／`moCanEdit()`）。**存檔刻意不併進 `saveCase()`**：那支會覆蓋整份 `data_json`，兩邊同時存會互相蓋掉，且已結案與權限的守門規則不一樣。**金額也刻意不計入財務總覽的「應付總額」**——那個數字的定義是承攬商匯款申請，混進去會跟 `/finance-summary` 算出來的對不起來。e2e `test_e2e_material_orders_2026_09_11.py`。

---

### §7.21 · 單據存檔版本與編輯紀錄（2026-09-14，DB 無異動）

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/api/quotations/{no}/versions` | 回 `{versions, history}` 兩條時間軸 |
| GET | `/api/quotations/{no}/versions/{seq}/download` | 下載該版本的**原始存檔 PDF**（不重新產生） |

- `versions` 來自 `data_json.docVersions[]`（由 `pdf_gen._record_doc_version()` 在 PDF 存檔成功後寫入），
  每筆含 `seq`／`at`／`event`（建立／修改／簽核／已簽核／結案）／`by`／`size`／`filename`／`available`。
- `available` 標示實體檔案現在還在不在——PDF 存檔目錄是 superadmin 可設定的路徑，可能被搬移或清理。
  **索引還在但檔案沒了要誠實標示**，不能讓人點下去才發現。
- `history` 就是 `data_json.editHistory`，`type` 有四種：`quote_update`（一般編輯，2026-09-14 新增）／
  `quote_edit`（解鎖編輯）／`settlement_finalized`／`settlement_draft`。
- 兩條時間軸**刻意不合併**：PDF 是完整快照（可以拿去對帳、給客戶看），編輯紀錄是欄位層級索引。
  硬合成一條會讓人以為每一筆編輯紀錄背後都有對應的 PDF，那不成立——一般編輯不產 PDF。
- 權限走 `_guard_case(..., allow_approver=True)`；下載端點另驗路徑不得越出 PDF base
  （比照 `routers/uploads.py::_resolve_upload_path()` 的既有慣例）。

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

> **⚠️ 2026-09-14 保留政策改版（使用者裁示）**：每日 60 天／週 90 天／**新增月備份永久保留**。
> 三層的角色不同，不要混在一起看——每日層是日常誤刪誤改的回溯窗口，週層是中期粗顆粒窗口，
> 月層是長期法遵與歷史查詢。改短前兩層是刻意的：舊值（每日 1825 天＝5 年、週 730 天）等於把
> 長期保存壓在「每天一份整庫 .db」上，成本隨資料庫大小線性成長，而真正需要長期保留的是月粒度。
>
> **上傳檔案鏡像與 PDF 存檔鏡像任何情況都不清除**（使用者明訂長久保留）——`_prune_cloud_backups()`
> 只走每日／週／月三個目錄，`test_backup_retention_policy_2026_09_14.py` 有一題專門守這件事，
> 不要為了「順手清一下舊照片」把鏡像目錄加進 prune 清單。
>
> ⚠️ 正式機若曾呼叫過 `PATCH /api/settings/backup-retention`，舊數字會固化在 DB 裡，
> **改預設值完全不會生效而且不會有任何錯誤訊息**（`_backup_retention()` 是 `{**預設, **DB 存的值}`）。
> 所以另外做了 **DB v83**（`db.py::_m083_backup_retention_policy`）把儲存值一併改成新政策。

```
雲端（磁碟機代號不固定，掃 A–Z 找，見下方說明）
  <任一磁碟機>:\我的雲端硬碟\系統存檔\
    .motrix_archive_owner   （2026-09-14 新增，存檔所有權標記，見 §8.1b）
    即時備份\報價單|客戶|供應商\
    每日備份\YYYY-MM-DD\  （JSON 41 表 + motrix_erp.db；**保留 60 天**，超過自動清除整個日期資料夾）
    週備份\YYYY-WNN\      （**保留 90 天**，超過自動清除整個週別資料夾）
    月備份\YYYY-MM\       （2026-09-14 新增，**永久保留**。內容與每日備份完全相同——41 張表
                            JSON ＋ 整份 motrix_erp.db，共用 `_export_table_json_set()` 同一段
                            匯出邏輯，日後新增資料表兩邊會一起有、不會只有其中一邊。
                            **執行時機是「當月第一次成功的每日備份」**，不是月底也不是 1 號——
                            綁死日期的話那天沒開機或備份失敗，整個月就沒有長期備份且沒人發現。
                            整庫 .db 一定要收：JSON 那層刻意不含憑證欄位與內嵌影像（見 §8.3），
                            長期保留的那一份如果只有 JSON，等於長期保留了一份殘缺的資料。
                            有表匯出失敗時**不寫 .done**，隔天的每日備份會再試一次——
                            寧可晚一天，也不要把一份殘缺的當成這個月的永久備份）
    上傳檔案鏡像\          （2026-08-08 新增，uploads/ 專案照片等實體檔案，_mirror_uploads() 依大小+
                            修改時間增量同步，不是每日整包複製；demo 隔離目錄不同步；只增不減）
    PDF存檔鏡像\{類別}\    （2026-09-07 新增，報價單/出貨單/承攬商匯款申請/開票申請憑據/請款單/
                            結案報表 6 類，_mirror_pdf_archives() 同一套增量同步邏輯；跟隨
                            system_settings 裡各自 pdf_base_path 的實際設定值，非固定預設路徑）

本機（不依賴雲端碟，務必保留）
  backend\db_backups\YYYY-MM-DD\motrix_erp.db   ← SQLite Online Backup，保留 30 天
  backend\db_backups\pre_update_YYYYMMDD_HHMMSS\
                                                ← apply_update.ps1 套用前整庫快照。
                                                  2026-09-14 起**按份數**保留最新 5 份。
                                                  原本完全沒被清過：清理迴圈只刪「檔名 parse
                                                  得出日期」的資料夾，`pre_update_...` 直接
                                                  跳過——開發機實測累積 49 份、db_backups 吃掉
                                                  1.8 GB，正式機只會更多（那才是真正跑套用的
                                                  地方）。用份數不用天數：這些快照的價值來自
                                                  「最近幾次部署」而不是「最近幾天」，隔三個月
                                                  才部署一次的話用天數會把唯一一份退路也刪掉
  backend\db_backups\quotation_instant\          ← 雲端碟不可用時的即時報價單 JSON fallback
  backup_alerts\BACKUP_ALERT.txt                ← 雲端異常醒目警示
  backup_alerts\YYYY-MM-DD.log
```

### §8.1b · 存檔所有權標記（2026-09-14）

**要解決的問題**：這個存檔目錄原本沒有任何「這是誰的」概念。`_detect_archive_base()` 是掃 A–Z 找第一個含 `我的雲端硬碟\系統存檔` 的磁碟機（磁碟機代號會漂移，掃描是刻意的設計），而 `main.py:414` 是**無條件**啟動 `_schedule_daily()`／`_schedule_weekly()`。所以任何跑這份程式碼、又掛著同一顆雲端碟的機器（開發機、備援機、DR 還原出來的機器、未來的分公司機）都會寫進同一組資料夾。兩個實際後果**都是靜默的**：

1. `.done` marker 在雲端。先跑的那台贏，後跑的那台走 `_clear_backup_alert_if_healthy(); return`——**還順手把警示清掉**。正式機當天沒備份，但備份頁面綠燈、沒有 audit、沒有信。
2. `_snapshot_sqlite()` 的雲端複製不看 marker，第二台會直接覆蓋當天的 `每日備份/{date}/motrix_erp.db`——那是還原優先序的**第二層**。

這不是假想：2026-09-07「conftest 雲端備份隔離死碼把測試假資料寫進真實 G: 碟」就是同一類。

**作法**：存檔根目錄放 `.motrix_archive_owner`（JSON：`instance_id`／`machine`／`claimed_at`）。`_archive_ok()` 改成「目的地連得上 **且** 所有權相符」，所有原本只問「碟掛著沒」的呼叫點都走它，一次覆蓋即時／每日／週／月備份與兩組鏡像，不用逐一改呼叫端。

- **識別碼綁在資料庫**（`system_settings.archive_instance_id`）而不是機器名——DR 換機時資料庫是跟著還原過去的，新機器應該要能接手舊機器的存檔目錄；真正要擋的是「同一個存檔目錄被兩套**不同的資料庫**寫」。
- **第一次看到沒有 marker 的目錄會自動認領**：正式機明天第一次備份就把 marker 寫下去，不需要任何人工步驟。
- **不符時整組雲端備份停寫並寄 ERROR 警示信**，但**本機 SQLite 快照照做**——停掉它等於為了防一個問題製造一個更大的問題。
- **轉移所有權**：刪掉 `.motrix_archive_owner` 再重啟即可重新認領（警示訊息裡就直接寫著這一步）。
- **讀不到／寫不進 marker 一律 fail-open**：這層是針對罕見情境的防呆，不該因為一次暫時性 IO 錯誤就把每天的備份整個停掉。
- S3 後端不做這個檢查——bucket + prefix 是明確指定的，本來就不會「掃到別人的」。
- **判定快取以「存檔根目錄路徑」為鍵**（300 秒 TTL）。不以路徑為鍵的話，磁碟機代號漂移之後會沿用上一顆碟的結論——這不是理論問題，實測時就因此讓一支無關的備份鏡像測試吃到別題留下的 False， 在掛鏡像之前就早退，**序列跑綠、平行跑紅**。

測試：`backend/tests/test_archive_ownership_2026_09_14.py`（9 題，含「別人的當日整庫備份不可以被蓋掉」與「不可以用『碟沒掛上』這個錯誤理由蓋掉真正的原因」）。

### §8.2 · 排程架構（雙層）

| 層 | 機制 | 觸發時間 | 說明 |
|----|------|---------|------|
| **主**（可靠） | Windows 工作排程器 | 每日 02:00 | `backup_job.py`；server crash 也跑；開機後補執行 |
| **冗餘** | `threading.Timer` | 每 2h 日備；每 6h 週備 | server 在線時提供即時觸發 |

`.done` marker 確保同日/週/月不重複備份。設定：`setup_backup_task.ps1`（初次部署執行一次）。

**月備份的觸發點在每日備份裡**（`_daily_backup()` 匯出成功後呼叫 `_monthly_backup()`），不是另一個排程——同月第二次之後只是一次 marker 檢查就返回，成本可以忽略。

**⚠️ 這一整套的告警全部是「備份自己回報自己壞了」**：碟掉了、表匯不出來都會寫 `BACKUP_ALERT.txt` 並寄信，但「備份**根本沒有跑**」這件事沒有任何人會講——排程被停用、Timer 執行緒沒起來、另一台機器搶先寫了當日 `.done` 害本機早退，症狀全部是**一片安靜**（伺服器活著、heartbeat 照打、備份頁面綠燈），只有真的要還原的那天才會發現最後一份是三個月前的。2026-09-14 補上兩支**外部視角**的每日檢查（掛在既有的 08:00 排程，比照 `_check_cert_expiry()`，不另起 job）：

| 檢查 | 位置 | 條件 | 通知 key |
|------|------|------|----------|
| 備份新鮮度 | `daily_tasks.py::_check_backup_freshness()` | 本機快照或雲端每日備份超過 **36 小時**沒有成功紀錄 | `backup_stale` |
| 磁碟空間 | `daily_tasks.py::_check_disk_space()` | 剩餘同時 **< 10% 且 < 20 GB**（兩個門檻都沒過才叫） | `disk_space_low` |

- 兩支各自用 `system_settings` 當 guard，**一天最多一封**；恢復正常時清掉 guard，同一天再壞叫得出來。
- 新鮮度分「本機 SQLite 快照」與「雲端每日 JSON」兩條線各自判斷：本機那條斷掉代表備份程式本身沒在跑；**本機還活著而只有雲端那條斷掉，正是「另一台機器搶先寫了 .done」的症狀**，信裡會指名是哪一層。
- `backup.daily_partial` 算「有跑」（那個情境有自己的告警，不重複叫）。
- 全新環境（一筆備份紀錄都沒有）**不告警**——那是還沒跑過第一次，不是壞掉；誤報會讓人第一天就學會忽略這封信。
- 磁碟兩個門檻取「較寬鬆的滿足就算健康」：只看百分比的話 2 TB 的碟剩 8%（164 GB）就叫太早，只看絕對 GB 的話 256 GB 的系統碟剩 20 GB 已經很緊卻還不叫。

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

**還原優先序**：本機 `db_backups` 整庫 → 雲端`每日備份` 的 `motrix_erp.db` → 雲端`月備份` 的 `motrix_erp.db`（超過 60 天的時間點只剩這一層）→ JSON 重建（最後手段）

> 2026-09-14 起每日層只保留 60 天、週層 90 天。**要還原三個月以前的狀態，去 `月備份/YYYY-MM/`**——那一層永久保留，而且含整份 `.db`（不是只有 JSON）。

> **JSON 這一層涵蓋 41/76 張表**（2026-09-14 傍晚補齊，原本只有 8 張）。
> 沒進去的 35 張是刻意的：選型資料庫七類（由 `sync_*.py` 產生、git 裡有來源）、
> 登入態與鎖、流水號、操作軌跡與時數、個人排序偏好——重建它們沒有意義。
> 清單與逐項理由在 `backend/tests/test_system_audit_2026_09_14.py`
> 的 `_NOT_IN_JSON_BACKUP`，新增資料表沒做決定那支會變紅。
>
> ⚠️ **從 JSON 還原時，使用者的憑證欄位是刻意不備份的**
> （`totp_secret`／`totp_recovery_codes`／各種 password hash）——
> 那些是可以直接拿去產生有效驗證碼的金鑰，不該出現在人看得懂的備份檔裡。
> 所以走到這一層之後：帳號、角色、模組、部門歸屬都救得回來，
> 但**所有人都要重設密碼、重新綁定 2FA 與 Passkey**。
> （前兩層是整個 .db 檔，不受此限。）
>
> ⚠️ **JSON 這一層也不收內嵌影像與線上祕密**：
> ・承攬人員的身分證正反面／存摺掃描件，以及協力廠商 `data_json`、承攬付款憑據
> 　`snapshot_json` 裡包的存摺影像，一律換成佔位字串（通則式處理，
> 　見 `archive._strip_inline_images()`）。實測每天 5.5 MB 降到 1.4 MB，
> 　重點不是省空間，是**不要每天把一疊身分證掃描件複製到雲端資料夾**。
> ・`system_settings` 的 `email_notify.smtp_password`、
> 　`google_calendar.client_secret` 與 `refresh_token` 用 `json_remove()` 挖掉，
> 　其餘設定照常保留。還原後這三個值要重新填。
> 影像與祕密在前兩層（整庫 .db）都是完整的。
>
> 另外：單張表匯出失敗現在會送 `backup.daily_partial` 並留下警示，
> 不會再像以前那樣照樣報 `backup.daily_ok`。

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
| 深色模式 | 全站色彩反轉濾鏡（不是另一套色票）。**`.topbar`／`.sidebar`／`.sidebar-overlay` 必須是 `<body>` 的直接子元素**——排除清單寫成 `body > *:not(.topbar):not(.sidebar):not(.sidebar-overlay)`，多包一層容器就對不上，整條側欄會被反轉成白底，而且容器有了 `filter` 會依 CSS 規範變成其中 `position:fixed` 元素的 containing block。新頁面照抄既有頁面骨架即可；違規由 `backend/tests/test_dark_mode_chrome_structure_2026_09_13.py` 擋下（見 §12 2026-09-13） |

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
| ✅ | ~~每日 JSON 匯出「通行金鑰」每天失敗~~（**2026-09-16 當天查明並修復**，DB 無異動）。`webauthn_credentials` 的 `credential_id`／`public_key` 是 BLOB，`SELECT *` 撈出來是 Python `bytes`，`json.dumps()` 直接 TypeError；per-table 的 `try/except` 把它吃成 `"error"`，其餘 40 張照常完成 ⇒ **這張表從進備份清單（2026-09-14）起一天都沒真的匯出過**，而每日備份照樣顯示完成。正式機 `每日備份/2026-09-16/彙總.json` 43 個鍵中只有它是 error。改成逐欄列出、略過兩個 BLOB（那兩欄匯出本來也沒意義：私鑰在使用者的認證器裡）。**既有守門測試是假綠燈**——`test_every_backup_query_actually_runs` 只做 `conn.execute(sql).fetchall()`，BLOB 的 SQL 完全跑得起來，觀測點停在失敗點的上游一步。補兩題：序列化那題照真實路徑走完 `json.dumps()`（⚠️ 只在表裡有資料時抓得到），schema 那題拿 `cursor.description` 對 `PRAGMA table_info` 的 BLOB 欄位（**這題才擋得住日後新增 BLOB 欄位**）。已用「把 bug 放回去」驗證第二題精準變紅而舊題仍綠。**連帶修掉一件沒人發現的事**：`_monthly_backup()` 只要 summary 有 error 就不寫 `.done`，通行金鑰天天失敗 ⇒ **每天重傳一次整個月備份**（41 張 JSON ＋ 8.3 MB 的 db），`月備份/2026-09/` 目錄建於 9-15 而檔案時間戳全是 9-16 00:00 |
| ⚪ | **Passkey 功能暫緩使用**（2026-09-16 使用者裁示，DB 無異動）。總開關 `backend/helpers/auth.py::PASSKEY_ENABLED = False`：9 支端點回 404、三個前端頁面的 Passkey 區塊都不顯示。**是暫停不是移除**——程式碼、資料表、既有憑證列原樣保留，改回 `True` 就整組回來（含 55 題被 `skipif` 的測試）。⚠️ **守門必須掛成 route dependency**：FastAPI 先解 dependencies、之後才驗 body，寫在函式第一行的話帶 body 的端點會先回 422 並把欄位名列出來，等於在功能關掉的情況下公布介面（已有測試釘住）。⚠️ 停用期間原本用 Passkey 登入的人只能用密碼；恢復前若變更過 RP ID，既有憑證仍然失效。詳見 §12 2026-09-16、§3.3c 開頭告示 |
| ✅ | ~~簽核佇列按下簽核後系統卡死十幾秒~~（**2026-09-15 當天查明並修復**，DB 無異動）。**實測 32.8 秒**，比回報的還久。根因正是預判的那個——而且是這個 codebase **第二次**踩到同一個坑（2026-09-10 `create_quotation` 是第一次）：`_apply_case_change_request()` 做完 `save_quotation_json(conn, ...)`（只 execute、不 commit → conn 持有寫鎖）之後直接 `_audit()`，而 `_audit()` 用 `get_db()` **另開一條連線寫入**，撞上 SQLite 單一 writer，等滿 `connect(timeout=30)` 才放棄。**更糟的是 `_audit()` 的 `except` 會把逾時例外吞掉**——畫面顯示核准成功、稽核紀錄卻不存在，事後查不到是誰核准的。修法：四處 `_audit` 改成 append 進 `deferred_audits`，由呼叫端在 commit 之後統一寫出。**32.8 秒 → 5.1 秒**（整個測試檔）。**使用者要求的「檢查別的區域有沒有一樣的狀態」已做**：新增 AST 靜態掃描守門測試`test_write_lock_deadlock_guard_2026_09_15.py`，掃 routers/helpers/main 全部函式。初掃 27 個命中，逐一核對後 26 個是誤報（`_set_setting()` 自己開自己 commit、43 支 `notify_*` 全部只讀不寫），**真正的只有這一處**，已修。守門測試已用「拿 git 上修復前的檔案直接掃」證明抓得到（4 處全中），修復後 0 處。 |
| ✅ | ~~最高管理者需要簽核的項目沒有出現在簽核佇列~~（**2026-09-15 當天查明並修復**，DB 無異動）。**佇列頁其實列得出來，是 topbar 角標是 0**——所以使用者根本不會想到要去看，症狀就表現成「沒顯示」。`/api/approval-queue` 與 `/api/approval-queue/count` 是**兩段各自獨立的查詢**，沒有任何東西在守它們一致。抓到兩個方向相反的缺陷：①**少算**：count 端點的迴圈是 `if tiers and ct_idx < len(tiers)`，**沒有簽核層設定的單據整批被跳過**——而那種情況的規則是「任一 superadmin 皆可簽核」（`approve_quotation()` 的 no-tier 分支、前端 `canApprove()` 都是這樣判）。②**多算**：已結案變更申請是 `WHERE status='pending'` 全部算，沒排除自己送的，而自己送的自己簽不掉 → **一個永遠清不掉的紅點**。新增 `test_approval_queue_badge_consistency_2026_09_15.py`（5 題），守的不變量是**角標數字必須等於佇列裡 `canApprove()` 為真的項目數**——程式碼裡已經有兩則註解在講這件事，但一直是靠人工記得補。 |
| ✅ | ~~掃一遍「給人看的畫面上有沒有原始代碼值」~~（**2026-09-15 當天掃完**，無其他問題）。起因是變更申請摘要出現「專案期間·狀態 `on_track`」——**那一處是 2026-09-14 新寫的摘要層造成的，已在當天修掉**（`_CASE_VALUE_LABELS` 值對照，未知值原樣顯示不硬猜）。**掃描方法（可重跑）**：先從資料庫撈出所有名稱含 `status` 的欄位＋報價單 `data_json` 裡所有 `*status*` 鍵的**實際 distinct 值**，篩出純 ASCII 的（＝代碼而非中文），得到 9 個；再逐一追到前端顯示端。結論是**其餘全部都有對照**：`contractor_dispatches.status`（後端給 `statusLabel`）、`case_action_items.status`（`actionItemStatusLabel()`）、`stock_items.status`（只判斷與套色）、`settle_status`／`settlement.status`（三元運算顯示「已定稿／草稿」）、`approval.status` 與 approvers `status`（只判斷）、`writeOffStatus`（只判斷）、`project_logs.log_status`（未在畫面顯示）。`network_plans`／`payslips`／`dev_cases` 的 status 本來就存中文。⚠️ `vendor-contractors.html:355` 的 `g.status` 看起來像但**不是**——那是政府統編查詢 API 回的營業狀態，外部資料。**下次新增 enum 欄位時記得同一件事**：判斷基準是「畫面上會不會出現底線命名的英文」，不是後端存什麼。 |
| ✅ | ~~模組權限要真的擋住、未開啟的連模組名稱都不顯示~~（**2026-09-14 當天施作完成**，DB v84）。`require_any_module()` 從「admin+ 直通」改成**只有 superadmin 直通**；`sidebar.js` 二十幾個 `mods.indexOf(x) >= 0 || ad` 收斂成一支 `has(x)`，另外兩種非模組放行（`|| eng`、`|| role !== 'viewer'`）也一併拿掉。分組名稱不需額外處理——`renderMainNav()` 本來就會過濾 `items` 為空的分組，所以整組沒權限時連分組名稱都不出現。**四個原本沒有 key 只能靠角色寫死的頁面，依使用者裁示『沒有對應模組 key 也建立就沒有這個問題』新建了 key**：`audit_log`／`shipping_export_log`／`module_versions`／`selection_overview`；網路架構規劃書同樣只有 `netplan_edit` 沒有檢視 key，補上 `netplan`（目錄從 35 → 40 個 key）。**DB v84 先回填再取消直通**，所以沒有人憑空少掉今天看得到的東西。詳見 §12 同日條目與 [`MODULE-AUDIT-2026-09-13.md`](MODULE-AUDIT-2026-09-13.md) §6。 |
| ✅ | ~~已結案變更申請「核准後會套用的內容」直接把 raw JSON 倒給人看~~（**2026-09-14 當天施作完成**，DB 無異動）。新增 `routers/quotations.py::_summarize_case_change()`，六種 `action_type` 各自產生可讀的 before／after（欄位中文名＋前後值），**只列有變動的欄位**；回傳形狀沿用額外支出那條路徑，前端 `approval-queue.html` 一行都不用改。**路上抓到一件比可讀性更嚴重的事**：`approve_case_change()` 對 `case_record_update` 的第一個動作是 `new_case_record["stages"] = cr.get("stages")`——**payload 裡的 stages 根本不會被套用**（階段有自己的專屬端點），而原本的畫面把它整包印在「核准後會套用的內容」底下，等於告訴審核者一件不會發生的事。摘要刻意不收 stages，並有一題測試釘住。內部欄位（`writeOffRequestedAt`、`invoiceFiles[].path`）一律不外流。**使用者要求的「其他地方也這樣顯示」已掃過**：全前端只有 `approval-queue.html:819` 一處在畫面上做 `JSON.stringify`，就是這一塊的 fallback；稽核紀錄頁根本不渲染 `detail` 欄位；額外支出變更申請本來就是逐欄對照。測試 `test_case_change_summary_2026_09_14.py`（12 題）。 |
| ✅ | ~~完工單「單據用語」與「逐欄調整」要移到頁面最上面~~（**2026-09-14 當天施作完成**）。兩張卡搬到整頁最前面，提示語改成「請先選這裡，再往下填」。**順手處理了那個「換個位置還是會發生」的問題**：`applyPreset()` 是整批覆寫不是合併，所以已經逐欄微調過的內容會被吃掉——現在偵測到有自訂值時會先 `confirm()` 問一聲（`confirm` 是這頁既有慣例，送審／預覽都在用）。純前端，無後端異動。 |
| ✅ | ~~報價單付款條件改成可切換的「條款組」~~（**2026-09-14 當天施作完成**，DB 無異動）。`system_settings.quote_terms_presets = {presets:[...], defaultKey}`，每組含名稱＋付款條件／交貨條件／驗收標準／保固條件／售後服務五段文字。報價單「報價條件」區塊上方一排方塊可切換，★ 是新增報價單時自動帶入的那組；superadmin 另有「管理條款組」可建立／改名／改內容／刪除／設預設，且可「以目前表單內容新增一組」。**報價單存的是複製過去的文字、不是指向設定的 key**——已開出去的單不會因為有人事後改了條款組而跟著變（跟同日「單據原始版本存檔」同一個判準）。`termsPresetKey` 只當「從哪一組起手」的線索，用來做「與該組不同」的提示。**`checkApproval()` 的比對基準一併改成目前選中的那組**——不改的話切到「純購料」會整組被判定成條件被改過，這功能一用就報警。測試：後端 14 題＋e2e 3 題。 |
| ✅ | ~~營運報表的業務員績效讀錯欄位~~（**2026-09-14 當天施作完成**，DB 無異動）。新增 `routers/reports.py::_case_sales_owner()`：優先 `caseRecord.roles.sales`，沒填才退回 `sales_person_id`／`sales_person`。**舊案件刻意不回填**——那個欄位當初沒人填，補一個猜測值只會製造假資料。`roles.sales` 存的是顯示名稱字串，唯一反查得到帳號就用 id 當 key（改名後仍歸同一人）；**同名的一律不猜**（`_build_name_index()` 把同名的值設成 None，退回名字分組——那至少是「兩個同名的人被合成一列」這種看得出來的錯，不是靜默算錯人）；反查不到（離職刪帳號、打錯字）仍以那個名字歸屬，不會默默掉回開單者。**年度目標達成率一併改用同一組 key**——那兩張表是並排看的，一邊算業務負責、另一邊算開單者會對不起來。測試 `test_reports_sales_owner_2026_09_14.py`（11 題）。<br>⚠️ **部門彙總與 `department_id` 篩選仍依 `sales_person_id`**，沒有跟著改：那條線會影響整份報表的取數範圍，改動面遠大於這次交辦，而且要先決定「案件的部門是跟著開單者還是跟著業務負責」。**若兩張表的部門數字對不上，原因就在這裡。** |
| 🟠 | **每案資料的 IDOR 面還沒收完**（2026-09-13 模組權限盤點，見 [`MODULE-AUDIT-2026-09-13.md`](MODULE-AUDIT-2026-09-13.md) §4）。`routers/quotations.py` 裡還有一批端點只要求登入、沒有 `_check_quotation_owner()`：案件階段（`/stages`、`/stages/{id}/visits`）、更新紀錄（`/updates`）、案件鎖定（`/case-lock`、`/case-unlock`）、款項與叫料的附件上傳／刪除、`/export`、三支 PDF 下載。**這次只修了金額面最重的 `settlement`／`finance-summary`**。其餘要一起改，前提是先確認「被指派的協作者」這條線在每個流程都成立（例如現場工程師是不是都會被指派到案件）——那是流程問題，不是技術問題 |
| 🟡 | **`financial_view` 是顯示偏好、不是權限**：全系統只在 `case-management.js:214` 被讀，`/api/sales-orders`／`settlement`／`finance-summary` 等照樣回金額。團隊已知且刻意（`get_finance_summary()` docstring：「只擋這一支會是假的安全感」）。若要讓它變成真的權限，得一次處理所有回傳金額的端點，並先決定 viewer/engineer 到底該不該看到毛利 <br>**⚠️ 2026-09-14 部分解決**：admin 直通已取消，模組檢查現在對所有非 superadmin 生效（DB v84，見 §12 第十二輪）。本列剩下的是**金額欄位**要不要也納入模組制這個未決問題——那跟「哪些頁面看得到」是兩條線。 |
| 🟡 | **`GET /api/sales-orders` 任何登入者可讀**（含 `net_margin_pct`）。頁面 2026-09-13 已改成導向頁，端點還在。要嘛比照報表加模組檢查，要嘛確認只剩內部用途後下線 <br>**⚠️ 2026-09-14 部分解決**：admin 直通已取消，模組檢查現在對所有非 superadmin 生效（DB v84，見 §12 第十二輪）。本列剩下的是**金額欄位**要不要也納入模組制這個未決問題——那跟「哪些頁面看得到」是兩條線。 |
| 🟡 | **16 個模組後端完全不讀**，等於只是側欄開關（2026-09-13 盤點）。要嘛承認它們是「介面偏好」並在 UI 上講清楚，要嘛逐一補後端檢查。現況介於兩者之間，最容易讓人誤以為「勾掉＝擋掉」 <br>**⚠️ 2026-09-14 部分解決**：admin 直通已取消，模組檢查現在對所有非 superadmin 生效（DB v84，見 §12 第十二輪）。本列剩下的是**金額欄位**要不要也納入模組制這個未決問題——那跟「哪些頁面看得到」是兩條線。 |
| ✅ | ~~區網 HTTPS／反向代理~~（`https_setup.ps1`，uvicorn 原生 TLS 自簽憑證，2026-08-27 commit `d7b8ee9`）——**2026-09-11 更正：正式機早已是 HTTPS**（本文件先前記載「尚未執行」已過時，該落差本身是 2026-09-08 事故的間接成因，見 §12 同日條目）；2026-09-10 又以 `-ExtraNames motrix.internal -Force` 重產憑證，SAN 與 CA 詳情見 **§3.3c** |
| ⚪ | **待決策（2026-09-16 起時效性已解除，見本列末）：要不要改用 Let's Encrypt 公開受信任憑證＋把 RP ID 換成 `erp.miactw.com`**，見 [`LETSENCRYPT-PUBLIC-CERT-PLAN.md`](LETSENCRYPT-PUBLIC-CERT-PLAN.md)（2026-09-11 規劃完成，**尚未執行**）。**做**：每台裝 CA／改 hosts 這件事整個消失（含 macOS、手機、Firefox），日後換網段或加 VPN 也不會讓 Passkey 全滅。**不做**：維持自簽 CA，每台新電腦都要人跑一次 `setup_passkey_client.ps1`，且未來網路環境一變動就被迫換 RP ID。**時效性來源**：換 RP ID 會讓**所有既有 Passkey 失效且無法救回**（瀏覽器端綁定，不在我們手上；DB v74 起系統至少查得出是哪幾張，見 §3.3c），目前只有 1～2 張是成本最低的時刻，累積幾十張後再換會非常痛。**卡在哪**：步驟 1～3（Cloudflare 加 A 記錄、建 API Token、正式機簽憑證）都必須由人操作；`backend/tools/letsencrypt_renew.ps1` 已寫好待用。**若決定不做，請直接在這一列寫明「決定維持自簽」與日期**，別讓它懸著。**2026-09-11 已排除 Cloudflare（Origin CA／Tunnel）兩個替代方案**，理由見 §3.3c，不要再重新評估 <br>**⚠️ 2026-09-16 時效性解除**：Passkey 功能已暫緩使用（§12 同日），沒有人在用 ⇒ **換 RP ID 的失效成本歸零**，「越拖越貴」不再成立。這件事現在可以純粹按 HTTPS／憑證維運需求決定。**但順序有講究：要恢復 Passkey 的話，先把 RP ID 定案再開功能**，否則又會回到「開了之後不敢換」的局面 |
| ✅ | ~~憑證到期完全沒有監控~~（**2026-09-11 已實作** `daily_tasks.py::_check_cert_expiry()`，門檻依憑證總效期自動切換，見 §3.3c 與 §12 同日條目）。**這是先前完全不存在的一層**：mkcert 憑證 2028-12-10（星期日）到期、不會自己更新，而 `letsencrypt_renew.ps1` 的 `[警告]` 只寫進 log 沒人會看 |
| ✅ | ~~死碼 JS 清除~~（21 個死碼 .js 已刪，`frontend/js/` 僅剩 2 個有效檔） |
| ✅ | ~~關鍵 API 自動化測試~~（2026-09-01 更正：早已遠超 48 tests，現為 `backend/tests/` 45 個測試檔，累計 300+ 題，近期為 308/308 全過） |
| ✅ | ~~文件拆 `CHANGELOG.md` 與本速查分離~~（已完成，見根目錄 `CHANGELOG.md`） |
| ✅ | ~~Git Flow 分支規則~~（`develop` 分支 + `GITFLOW.md` 規範已建立） |
| 🟠 | **手動跑 pytest 要帶 `--basetemp`，否則測試全過也會回非 0**（根因團隊已於 2026-09-10 查明並解掉，記在 `backend/tools/build_deploy_package.ps1` Step 3 註解）。`%TEMP%\pytest-of-<user>\pytest-current` 是 pytest 每次執行都會重建的符號連結，這台機器上有一個**目標讀不到的損壞 reparse point**，`os.stat()` 回 `WinError 5`（不是「找不到」），pytest 的 `cleanup_dead_symlinks` 會在 session 收尾整個炸掉——**測試全過也會回非 0，而且輸出最後一行是 PermissionError，很容易被誤讀成測試失敗**，連「N passed」那行摘要都會被吞掉。**正解**：跟打包腳本一樣加 `--basetemp=%TEMP%\motrix-pytest-<timestamp>`，可完全繞開；順便加 `-n auto`（pytest-xdist，實測 390 秒 → 166 秒）。要根治得用系統管理員權限 `rd` 掉那個連結（一般權限 Remove-Item/rd/del 全部 Access denied，已實測）。**若沒帶 --basetemp**：別用 `$?` 判成敗，也別用 `| tail -N`（traceback 有幾十行會把進度點行擠掉，而且管線的 `$?` 是 tail 的），改看第一行進度點有沒有 `F`/`E` |
| 🟠 | **測試暫存不會自己清，會吃掉整顆磁碟**（2026-09-14 記錄）。`pytest` **每跑一次**就在 `%TEMP%` 留下 1～2 GB（`motrix-pytest-*` 與自訂標籤目錄），**不會自動清**；背景 job 另外堆在 `.claude\jobs\<id>\tmp`。**2026-09-14 一次清出 190 GB**。清理規則：job 的 `state.json` 變成 `done` 之後其 `tmp` 可刪，**但 `state.json` 要留**（刪了就沒人知道那個 job 跑過什麼）。**2026-09-14 更新：容量告警已經有了**（`daily_tasks.py::_check_disk_space()`，剩餘同時低於 10% 且 20 GB 時每日寄一次信，信裡直接列出可以安全清掉的目錄），`db_backups/pre_update_*` 也已納入自動清理（保留最新 5 份）。**2026-09-15 更新（第五輪）：三件事都補上了**——①打包腳本跑完會自己清該次的 basetemp（測試失敗時保留供追查）；②新增 `_check_temp_bloat()`，`%TEMP%` 的測試暫存合計超過 20 GB 就寄信（**與剩餘空間無關**，因為 136 GB 的累積在 930 GB 的碟上永遠觸發不了剩餘空間門檻）；③剩餘空間的絕對門檻 20 → 50 GB。同輪查出一次跑掉 3～5 GB 的主因不是「暫存本來就大」，是 conftest 沒把 6 個 PDF 存檔目錄導開，測試每跑一次就把專案裡 1,617 個**真實** PDF 複製一份進暫存（已修，降到 1.5 GB／47 個 PDF）。**手動跑測試仍然要自己帶 `--basetemp` 並記得清**（打包腳本以外的路徑沒人幫你清）。2026-09-15 一次清出 136 GB |
| 🟡 | **`develop` 分支實際上已經停用**（2026-09-14 查證）：`git rev-list --left-right --count master...develop` 為 **341 / 0**——develop 落後 master 341 個 commit 且沒有任何獨有內容。下面那列「Git Flow 分支規則已建立」只是「文件寫了」，實務上 **master 才是主幹**。開新分支請直接從 master 開，**不要照 `GITFLOW.md` 寫的從 develop 開**（會把工作基在 341 個 commit 以前的老基底）。要嘛把 develop 跟上來、要嘛在 `GITFLOW.md` 註明已改用 master 主幹制 |
| 低 | SQLite → PostgreSQL（資料量 > 1 GB 或同時連線數 > 5 時評估） |
| ✅ | ~~簽核流程尚未整合處/部門組織架構~~（四個 approval-settings 頁面已支援「部門主管自動簽核」層，見 §12 2026-08-22g） |
| ✅ | ~~通知路由只接了「工作事項逾期未完成」一個事件~~（已擴充到案件執行進度／專案到期兩個事件，`case_stage_deadline_manager`／`project_deadline_manager`，見 §12 2026-08-22k）；報表/儀表板依部門篩選仍只涵蓋 `reports.py`／`dashboard.py`（含新增的 `projectSummary`），activity-feed 仍只有「案件留言板」區塊套用篩選 |
| ⏸ | **完整模組轉成手機版獨立頁面（2026-09-11 交辦，⭐先不施作、只列入排程）**。**啟動條件（使用者明訂）：等系統都改到穩定、不用再修改了才進行**。現在不動的理由很具體：手機版是同一份業務邏輯的**第二個前端實作**，每一次模組改動都變成要改兩個地方；在還在高頻改動的階段做，維護成本會比功能本身還高，而且兩邊會持續分岐（本專案已經有過`Desktop/MIAC官網(最終)/` vs `MIAC-New/` 分岐 567 行的前例）。**動工前要先確認的事**：①哪幾個模組真的需要手機版（全部或只有現場會用的：案件進度、叫料、額外支出、簽核佇列）②是另建獨立頁面還是現有頁面做 RWD（選型資料庫目前是 Alpine.js 純桌面設計，未評估過 RWD 適配程度）③登入後怎麼分流（自動偵測裝置還是使用者自己選）。 |
| 🔴 | **額外支出改版（2026-09-11 交辦，規格已寫、尚未動工）**——從精算頁搬到案件管理案件內選單、類別欄自適應、自動帶入填寫人＋可選支出人、填寫日期與更動日期、填寫需送審、支出計算與現有彙總結合。**完整規格見 §5.10**，含已查證的兩個現行缺陷（`createdBy` 因為取錯 session 路徑**永遠是空字串**，實測 7 筆既有資料 0 筆有值；類別欄寬度寫死不自適應）與**六個動工前必須先確認的設計問題**（支出人的資料型別、送審接哪一套、送審中算不算進成本、精算頁那張表去留、已結案能不能編、既有資料要不要回填）。⚠️ 最大的架構決策是 `extraItems` 要不要從 `data_json` 正規化成獨立資料表——要做送審與更動軌跡的話幾乎一定要。 |
| 🔨 | **組織架構二層 → 支援直接歸屬於處：2026-09-11 決定要做**（施作中，見同日 §12 條目）。決策當下的實測數據是「目前 12 個帳號全部都有部門歸屬、0 人卡住，真實的處只有『總經理辦公室』一個」，**即現況沒有任何實例會踩到這個限制**；使用者仍決定先做，理由是組織之後的長法由他掌握。記在這裡是為了讓日後看到這筆改動的人知道：它不是為了修一個正在痛的問題，是為了先鋪路。 |
| ✅ | ~~專案管理「確認事項」兩階段簽核尚未接上 `helpers/tiered_approval.py` 的動態解析~~（已新增部門主管/處主管動態解析為額外路徑，`project_approve_eng`/`project_approve_biz` 模組權限完全保留，見 §12 2026-08-23d） |
| ✅ | ~~caseRecord.stages 正規化進行中~~（**2026-09-07 依實際程式碼複查更正**：①②③a 早已完成，③b 前端切換與④ `quotation-form.html` 落差修正**也已經在 2026-08-23 當天完成**——`case-management.js` 全部 10 個階段操作函式已改打 `/api/quotations/{no}/stages...` 專屬端點，`quotation-form.html::ensureCaseRecord()` 也已改成空陣列＋API 建立預設階段。這批工作是在正式機斷線期間直接於正式機完成，事後用一次大批量回推 commit `2b8e7ad` 拉回開發機，當時沒有補一篇正式 changelog／§11 更新，導致本節長期誤記為「進行中」。⑤讀取點改查新表當效能優化仍非必要、維持現狀。**2026-09-07 複查時另外發現並修復的真缺口**：這批 granular 端點本身先前幾乎沒有正面路徑測試（先前 `backend/tests/` 唯一涵蓋 `/stages` 的地方只測「已結案案件鎖定」情境）——已新增 `test_case_stages_endpoints_2026_09_07.py`（11 題，涵蓋 CRUD／負責人／前置階段防環／拜訪紀錄／跨案件 id 隔離／`_sync_stages_to_json` 橋樑／鎖定案件擋下），並修正 10 個端點 docstring 裡「尚未接進任何前端頁面」的過期字樣） |
| ✅ | ~~案件執行進度沒有跨案的時間軸或看板視圖~~（新增 `case-stage-board.html`：看板五欄＋跨案時間軸，見 §12 2026-08-23c）；專案時程跨專案視覺化仍未做，`dashboard.py` 目前只有依狀態分組的專案彙總卡片（2026-08-22k） |
| ✅ | ~~案件完結案缺防呆機制~~（2026-08-25 使用者提出，2026-08-26 已施作：`update_deal_tag()` 轉入「已結案」前檢查①`case_stages` 全部完成②`payment.items` 全部收齊③關聯單據皆無待審核中，任一未達成回 400 並通知尚未完成該項的簽核人＋最高管理員，見 §12 2026-08-26） |
| 🟡 | **2026-09-11 補強：那道 403 的稽核現在記得出「是哪一支操作」**。2026-08-28 加 `case.locked_edit_denied` 的目的是「用數據而非猜測決定要不要擴大範圍」，但當時只記單號——查得出這道牆被撞了幾次，**查不出該優先開放哪幾支**，而後者才是要決定的事。13 個呼叫點現在各自帶 `op=` 標籤（「案件階段-新增」「稅額沖銷-核准」…），格式 `{單號} 已結案，此操作不支援排隊審核，直接擋下｜操作：{標籤}`，前綴不變所以舊紀錄仍可一起統計。⚠️ 訊息是寫在 `audit_log.target_label` 不是 `detail`（`_audit()` 第 5 個位置參數是 target_label，`detail` 是 dict、這批呼叫都沒傳，實際存 `{}`）——**要撈數據記得查 target_label**。統計指令：`SELECT substr(target_label, instr(target_label,'｜操作：')+4) op, COUNT(*) FROM audit_log WHERE action='case.locked_edit_denied' GROUP BY op ORDER BY 2 DESC;`（**要在正式機的 db 上跑**，開發機這份是 0 筆）。**📅 2026-09-11 決定：回頭看的日期訂在 2026-12-11**（帶標籤的紀錄從 2026-09-11 起算，累積三個月）。屆時跑上面那條指令，用實際被撞的次數與項目決定要不要擴大；若三個月後總數仍是個位數，代表這道限制根本沒有造成困擾，直接關掉這一項不要再評估。**訂日期是刻意的**——這個專案已經有太多「之後再評估」無限期掛著的項目。 |
| 🟡 | **已結案案件解鎖/半解鎖（2026-08-26 新增，範圍刻意收斂，非完整涵蓋）**：新增 `case-unlock`/`case-lock` 讓已結案案件進入「半解鎖」狀態，僅 8 個端點（案件記錄整包存檔／款項標記收款／款項發票附件／叫料附件／叫料發票附件共 8 支）支援半解鎖期間排隊等 superadmin 審核套用；案件執行階段細項端點（10 支）與款項稅額沖銷（3 支）刻意不支援排隊，已結案時一律直接 403（不論是否半解鎖），需要修正時只能透過案件資料整體編輯或聯繫最高管理員直接校正。之後若要擴大涵蓋範圍，比照 `case_record_update` 的「暫存 payload_json、核准時重放同一段套用邏輯」模式即可，見 db.py `_m061_case_semi_unlock()` docstring。 |
| ✅ | ~~PDF 存檔（報價單/出貨單/勞報單）未納入雲端備份範圍~~（2026-09-07 新增 `archive.py::_mirror_pdf_archives()`，沿用 `_mirror_uploads()` 抽出的共用鏡像邏輯，涵蓋 6 類 PDF：報價單/出貨單/承攬商匯款申請/開票申請憑據/請款單/結案報表，見 §8.1） |
| ✅ | ~~CORS 白名單寫死 IP，未改用環境變數~~（**2026-09-11 已實作**：`MOTRIX_CORS_ORIGINS`，逗號分隔；**未設定時的行為與改動前逐字相同**（預設值就是原本那六筆，不是空清單，忘了設不會把所有人擋在外面）；設了就**完全取代**預設、不是附加。見 `main.py::_resolve_cors_origins()` docstring）。ℹ️ 順帶查證：`motrix.internal`（正式機 2026-09-11 起的正式網址）**不在白名單裡**——目前沒事是因為前端跟 API 同源、CORS 根本不會介入，但若哪天前端拆到別的來源要記得補 |
| ✅ | ~~`routers/projects.py`（592行）自 2026-08-26 專案併入案件管理後已無任何前端流程掛載，是否整個移除尚未決定~~（**檔案早已在 `6bd04ca`「稽核後續三項——刪死碼」刪除，本列與架構地圖 §2.10／§5 長期記載為「仍在、尚未清理」，2026-09-11 核對檔案系統後更正**。要看內容去 git 歷史） |
| ⏸️ | **多分公司架構＋自動核版更新：2026-09-11 決定「現在不決定」，文件凍結**。那 4 項待決其實不是平行的——第 1 項（集中式 vs 分散式）是閘門，走純集中式的話第 2、3 項自動消失、整份 `MULTI-BRANCH-AUTO-UPDATE-DESIGN.md` 大部分內容不適用。而文件自己寫的起點是「使用者提出**後續系統可能**架設到分公司」——那是假設不是計畫。**替還沒發生的事決定架構，等真的要做時前提八成已經變了**，所以維持規劃書原狀不動。**觸發條件：確定要開分公司時**，先重讀該文件 §0 的決策摘要再開工。 |
| 🟢 | 災難復原（DR）從未實際演練過，`DR-SOP.md` §6 演練紀錄表完全空白，RTO 目前僅為估計值 |
| ✅ | ~~QR 登入手機端免密碼~~（2026-09-08 已實作，見 §12 同日條目——手機瀏覽器已有效 session 時自動核准，沒有則退回既有密碼手動輸入／瀏覽器自動填入密碼兩層） |
| ✅ | ~~`build_deploy_package.ps1` 打包關卡用 `pytest-xdist` 平行化~~（2026-09-09 已實作，見 §12 同日條目——動手前先驗證序列/`-n auto` 兩邊 470 題非 e2e 測試 pass/fail 清單完全一致，序列 390 秒→平行 166 秒，約 2.35 倍加速） |
| ✅ | ~~WebAuthn/Passkey 裝置綁定登入~~（**2026-09-09 已實作**；**⚪ 2026-09-16 起功能暫緩使用**，見本表頂端該列與 §3.3c 開頭告示——程式碼與資料都保留，開關一開就回來，見 §12 同日「深夜」條目——後端新表＋端點、`login.html` 登入按鈕、`change-password.html` 裝置管理卡片；2026-09-10 `f8198e9` 再把 RP ID／Origin 改成 `system_settings` 可設定，未設定時四個端點回 503。**🟢 2026-09-11 起正式機實際可用**——使用者已實測「註冊 Passkey → 用 Passkey 登入」全通；中間修掉四個讓它「上線但從來沒能用」的根因，現況、限制與 RP ID 不可逆警告一律見 **§3.3c**）。以下保留當初的設計討論紀錄：<br>**（原待開發內容）**——使用者原始需求是想綁定電腦/手機 MAC 位址做「認得這台裝置、快速放行」，查證後瀏覽器沒有任何 JS API 能讀取 MAC（隱私限制，非我們沒做），且 MAC 軟體層可偽造本來就不可靠。改用業界正規解法：裝置的安全晶片（Face ID/指紋/TPM）產生一組無法匯出/複製的金鑰跟帳號綁定，之後那台裝置生物辨識一下即可登入或核准 QR 請求，比 MAC 位址安全非常多。**尚未評估技術方案細節**——前端需串接瀏覽器 WebAuthn API（`navigator.credentials.create/get`），後端需新增 credential 註冊/驗證端點與公鑰儲存（新表，例如 `webauthn_credentials`），且要設計跟現有密碼／TOTP／QR session 三種登入路徑如何並存、要不要能列出/命名/撤銷已註冊裝置。下次要動手前應先進 Plan Mode 完整設計，比照 QR 核准功能與 TOTP 當初的作法（見 [[feedback_check_existing_before_building]]，認證流程設計優先權高於一般功能）。 |
| ✅ | ~~案件財務新增獨立「應收應付」模組＋精算雜支單號欄位~~（2026-09-09 已實作，見 §12 同日條目與 §7.16——新增 `GET /api/quotations/{quote_no}/finance-summary` 彙總端點，未新增任何資料表/欄位；精算「額外支出」新增 `docNo` 欄位，因 settlement 整包存 `data_json` 故後端零改動） |
| ✅ | ~~案件執行期限與超期提醒通知~~（**2026-09-10 已實作**，見 §12 同日條目——`caseRecord.projectTimeline` 存 data_json 無 schema 異動；`daily_tasks.py:1092-1135::_check_case_project_timeline_deadline()` 沿用既有每日排程而非另起 job；通知對象為所有 admin/superadmin；**重寄週期實作為每 7 天，非當初討論的 10 天**，計時點為超期天數分桶 `days_overdue // 7`）。以下保留當初的需求討論紀錄：<br>**（原待開發內容）**——案件管理「案件資訊」分頁需要新增「案件執行日期區間」欄位（start_date / end_date，類似預計交期的概念），當案件實際進度超過設定期限時自動觸發通知流程：(1) **超期當天寄一次電郵通知**給該案件的超級管理員與專案執行人；(2) **之後每 10 天重複寄一次**提醒尚未完結，直到案件狀態改為已結案為止。**背景需求**：實務上案件常因客戶延遲或內部進度調整而超期，長期無人追蹤就容易成為幽靈案件，需要一個被動提醒機制。**細節待評估**：(1) 日期欄位是否要新增到資料表或繼續存在 `data_json`（後者零改動，但搜尋/聚合較麻煩）；(2) 通知的「執行人」欄位定義（是 `executor`、還是 `assigned_user_ids` 任一人、還是需要新增一個獨立的 `deadline_notify_users` 欄位）；(3) 10 天的計時點是「案件建立時」、「超期當天」還是「上一次寄信」（影響時間複雜度與誤發機率）；(4) 通知內容格式與語言；(5) 是否需要在案件頁面顯示「距離期限剩餘天數」的倒數。排程觸發機制可沿用既有 `heartbeat_job.py`（正式機每 5 分鐘執行一次），或另起一個獨立的 `deadline_check_job.py`（見 §1.1）。**計劃**：先釐清上述需求細節，再評估是否需 DB migration。 |
| ✅ | ~~營運報表當月與當年度數據獨立分開顯示~~（**2026-09-09 已實作**：`56e52b3` 當月/當年度應收獨立檢視、不再跟隨 period-bar，新增 `test_reports_receivables_monthly.py`；`6bfcafb` 首頁當月收支完整修正＋部門篩選；2026-09-10 `f8198e9` 補上月支出頁籤徽章依 scope 顯示（`reports.html:434`）。同一批連帶修掉「首頁與營運報表對同一個數字有兩套歸月邏輯」的分岔，見 §12 2026-09-09）。以下保留當初的需求討論紀錄：<br>**（原待開發內容）**——目前營運報表的應收未收、已收已支等數字似乎是當年度與當月混在一起（或至少沒有明確區隔），需求是把「當月」的應收未收／已收已支獨立顯示，跟「當年度」的數字做出區隔，不要混算或混排在一起。**併同影響**：營運報表下方的分頁（tabs）內容也要一併比照，跟當年度視圖分開顯示，而不是共用同一份彙總。**細節待評估**（目前 `frontend/js/reports.js` 現有的月/年篩選邏輯、後端 `routers/reports.py` 對應的查詢與彙總方式），token 足夠時再展開設計，先記錄需求方向。 |

| ✅ | ~~使用者回報（2026-09-10）：營運報表切換「月／季／年」時，對應的財務資料不會跟著切換~~（**當天稍晚就修好了，本列長期誤記為「尚未查證」，2026-09-11 更正**）。根因與修法見 §12「2026-09-10（更晚）」條目：後端一直是對的，壞在前端 `reports.js` 的 `prevPeriod()`／`nextPeriod()`／`switchType()` 三個函式從初始 commit 起就沒跟上期別同步，修法是把同步收斂到 `loadData()` 開頭單一處（`_syncSubPeriods()`）。測試 `test_reports_quarter_scope_2026_09_10.py`（9 題）＋ e2e `test_e2e_reports_period_sync_2026_09_10.py`（1 題，已用「還原修改重跑」驗證抓得到）。同一批還修掉一個請求飛行中切期別會讓畫面永遠卡在舊月份的競態。 |

**📖 2026-09-01 新增：`MOTRIX-ERP-ARCHITECTURE-MAP.md`**（專案根目錄）——依實際程式碼盤點（非僅依賴本文件）產出的架構地圖，涵蓋 18 組模組的檔案:行號索引、DB v1→v68 完整演進索引、13 條踩坑教訓彙整、依專業軟體慣例的分優先序建議清單。**與本文件互補、不取代**：本文件仍是行為規格與逐日 changelog 的權威來源；架構地圖是「哪個功能在哪個檔案哪一行」的快速定位索引＋外部視角建議。本次盤點也發現本文件 §7/§13 的 router／migration 數量記載落後實際程式碼，已於本輪一併補齊（見下方 §7.12–§7.15、§13）。

---

## §12 · 變更摘要（最新兩版）

> 完整版本歷史請見 [`CHANGELOG.md`](CHANGELOG.md)（根目錄）
>
> **2026-09-10 補記**：本節曾一度停在 2026-09-09 15:57（`f935119`），其後 28 個 commit
> 未紀錄；同期間 `CHANGELOG.md` 09-08／09-09 兩天完全空白。已於本日補回，並新增
> [`WEEKLY-AUDIT-2026-09-07_2026-09-10.md`](WEEKLY-AUDIT-2026-09-07_2026-09-10.md)
> ——帶「模組／檔案:行號／是否在正式機」座標的本週稽核索引，出事時先看那份。

### 2026-09-16 — 通行金鑰每天備份失敗（BLOB 進不了 JSON）＋ Passkey 功能暫緩（DB 無異動）

使用者回報「每日 JSON 匯出有 1 張表失敗：通行金鑰」。雲端存檔那份彙總佐證：
`每日備份/2026-09-16/彙總.json` 共 43 個鍵，**只有「通行金鑰」是 `"error"`**。

#### 一、根因：`SELECT *` 把兩個 BLOB 欄位撈進來，`json.dumps()` 直接 TypeError

`webauthn_credentials` 的 `credential_id` / `public_key` 宣告成 BLOB，
sqlite3 取出來是 Python `bytes`。`_strip_inline_images()` 只處理 str/dict/list，
bytes 原樣放行，接著 `_cloud_write_json()` 走到 `json.dumps()` 就爆：

    TypeError: Object of type bytes is not JSON serializable

`_export_table_json_set()` 的 per-table `try/except` 把它吃成 summary 裡的一個
`"error"`，其餘 40 張照常完成——所以**從這張表進備份清單（2026-09-14）起，
它一天都沒有真的被匯出過**，而每日備份照樣顯示完成。

改成逐欄列出、略過兩個 BLOB（`archive.py::_daily_backup_tables()`）。這兩欄
匯出本來也沒有意義：Passkey 私鑰在使用者的認證器裡，備份中的公鑰與憑證 ID
不能讓任何人登入、也不能重建憑證。這張表在 §8.3 最後手段裡要回答的是
「誰原本有綁、要通知誰重綁」——`user_id + name + created_at` 就足夠。

#### 二、假綠燈：既有測試的觀測點停在「SQL 跑得起來」

`test_every_backup_query_actually_runs`（2026-09-14 為了 `stock_batches` 沒有
`id` 欄那次而補的）只做 `conn.execute(sql).fetchall()`。BLOB 的 SQL **完全跑得
起來**，所以那題一路是綠的，失敗點在它下游一步的序列化。補兩題，一起看才完整：

- `test_every_backup_export_is_json_serializable`——照 `_export_table_json_set()`
  的真實路徑走完 `_strip_inline_images()` → `json.dumps()`。
  ⚠️ 只在表裡**剛好有資料**時才抓得到，空庫是綠的。
- `test_backup_export_selects_no_blob_columns`——不看資料只看 schema，拿
  `cursor.description` 跟 `PRAGMA table_info` 的 BLOB 欄位對一次。這題才是
  擋得住「日後有人新增 BLOB 欄位」的那道。

驗證方式是把 bug 放回去再跑：第二題精準紅在
`通行金鑰: ['credential_id', 'public_key']`，而 `..._actually_runs` 仍然是綠的。

#### 三、連帶後果：月備份每天整份重傳

`_monthly_backup()` 的設計是「summary 裡有 `error` 就**不寫 `.done`**」（永久保留
的那一層，內容不完整比每日層嚴重）。通行金鑰每天固定失敗 ⇒ `.done` 永遠寫不
下去 ⇒ **每天重跑一次整個月備份**：41 張 JSON ＋ 8.3 MB 的 `motrix_erp.db`。
`月備份/2026-09/` 目錄建於 9-15，裡面每個檔案的時間戳卻是 9-16 00:00，正是這個。
修好第一節之後，當月第一次成功的每日備份就會補上 `.done`，這件事自動停止。

#### 四、Passkey 功能暫緩使用（使用者裁示）

**是暫停不是移除**：程式碼、資料表、既有憑證列全部原樣保留，總開關
`backend/helpers/auth.py::PASSKEY_ENABLED = False`，改回 `True` 就全部回來。

| 層 | 停用時的行為 |
|---|---|
| `routers/auth.py` 7 支 `/api/auth/webauthn/*` | 404 |
| `routers/system.py` `/api/settings/webauthn-config` GET／PATCH | 404 |
| `routers/system.py` `/api/system/webauthn-config-status` | 200，`configured:false, enabled:false` |
| `login.html` | 「或使用 Passkey 登入」按鈕不顯示（吃 `configured`） |
| `change-password.html` | 整張「Passkey 設備」卡片不顯示（吃 `enabled`） |
| `company-profile-settings.html` | 整張「網域設定」卡片不顯示（吃設定端點的 404） |

幾個刻意的選擇：

- **回 404 不回 403/503**。503「尚未設定」會讓前端顯示「請聯繫系統管理員填入
  WebAuthn 設定」，把使用者引去要一個現在不該開的功能；404 等同「沒有這支端點」。
- **狀態端點不回 404**。三個頁面都靠它決定要不要畫出 Passkey 區塊，得回得了 200。
  `configured` 一併壓成 false 是給舊版前端的保險（舊頁面只認得這個欄位）。
- **前端旗標預設 `false`**。停用是目前的常態，先畫出卡片再抽掉會讓人以為功能還在。
- **`enabled !== false` 而不是 `!!enabled`**。舊後端沒有這個欄位時要維持原行為。

##### ⚠️ 守門必須掛成 route dependency，不能寫在函式第一行

實測踩到：FastAPI 先解 dependencies、**之後**才驗 Pydantic body。守門寫在函式裡
的話，四支帶 body 的端點在 body 不合格時直接回 **422**，連函式都沒進去——而那個
422 會把欄位名一併列出：

    {"loc": ["body", "challengeToken"], "msg": "Field required"}, ...

等於在功能已經關掉的情況下，對外確認端點存在並公布它的介面。改掛
`dependencies=[Depends(_require_passkey_enabled)]` 之後才真的一律 404。
`test_disabled_endpoints_do_not_leak_schema_via_422` 守著不讓它退回去。

##### 測試：整檔 skipif ＋ 一檔不 skip 的反向驗證

五個既有 Passkey 測試檔（55 題）加 module 層 `skipif(not PASSKEY_ENABLED)`
——**不是刪掉、也不是 xfail**：xfail 會讓功能恢復後的真實失敗被當成預期失敗吞掉，
刪掉則是恢復時沒有東西守著。

新增 `tests/test_passkey_disabled_2026_09_16.py`（23 題），**刻意不被開關 skip**：
那五檔全 skip 之後，端點是被開關擋成 404、還是路由被改壞而不存在，沒有任何一題
分得出來。每個停用態斷言都配一題 `monkeypatch` 把開關打開的反向斷言，
包括「`/credentials/{id}` 用**真的存在**的憑證 id 測」——用 `/1` 的話，開關打開時
也是 404（查無此憑證），跟「功能被關掉」一模一樣，那題就永遠是綠的卻什麼都沒驗到。

`通行金鑰` 仍留在每日 JSON 備份清單裡（末兩題守這件事）：功能關掉了，但表裡記的
是「誰原本綁過 Passkey」，恢復時要靠它通知誰重綁，那份名單反而是停用期間唯一線索。

⚠️ 停用期間原本用 Passkey 登入的人只能改用密碼。既有憑證列不會被刪，但若停用
期間變更過 RP ID，恢復後那些憑證仍然是失效的（綁定在瀏覽器端，見 `db.py::_m074`）。

### 2026-09-15（第十一輪）— 浮水印把去背 PNG 毀掉＋部署包只留兩份（DB 無異動）

使用者回報「圖檔上傳後變成這樣」，附上自己從附件下載回來的 `f01d558c046f4c63.png`
——畫面上只剩一顆彩色圓環，中間的字整片空白。

#### 一、`photos.py` 把透明 PNG 壓平

那個檔案**內容其實是 JPEG**（magic `ff d8 ff`）、mode 是 RGB。尺寸 1792×504，跟
`frontend/static/logo-white.png` 一模一樣——白色字＋透明底的去背 logo。

`_process_project_photo()` 原本兩件事都寫死：

1. `if img.mode not in ('RGB',): img = img.convert('RGB')`
   ——**RGBA→RGB 是直接丟掉 alpha、露出底下的 RGB 值**。去背圖透明處底下通常是白的，
   白字落在白底上就整個消失。實測中段「不透明且接近白」的取樣像素 **5902 → 52**。
2. 最後一律 `save(format='JPEG')`。而存檔端（`helpers/uploads.py`、`routers/system.py`）
   沿用的是**上傳時的副檔名**，於是產生「副檔名 `.png`、內容是 JPEG」的檔案——
   這一點 09-15 第九輪就記過「順帶記下、本輪沒動」，當時判斷它不影響顯示，**錯了**：
   它跟①是同一個 `convert('RGB')` 造成的，而①會毀圖。

改成**輸出跟著來源格式走**：`src_format` 在任何 `convert()` 之前抓（convert 出來的新
影像 `.format` 是 None），PNG 進 PNG 出（alpha 保留、浮水印照壓），其餘（手機拍的
JPEG）行為逐字不變。副檔名與內容從此一致，②順帶消失。取樣對比色的那一段也要改
——RGBA 的 `getdata()` 吐 4-tuple，而且直接讀會讀到「被 alpha 遮住、根本看不見」的
顏色，所以先疊到白底再取樣。

#### 二、光是保留 alpha 還是看不見

白字去背 logo 襯在純白頁面上依然是白的。而且縮圖原本是 `object-fit: cover`，
把 1792×504 的寬 logo 裁成 68×68 **只留中段**——正好是字的位置。

縮圖改成 **棋盤格底 ＋ `object-fit: contain`**（`.att-thumb`，兩頁各一份）：
棋盤格讓白色內容看得見，也一眼看得出「這張圖本來就是透明背景」；`contain` 讓整張
圖都看得到，不再從中間裁一塊。

**⚠️ 已經上傳過的圖救不回來**——原檔在存檔當下就被壓平了，要重傳。

#### 三、測試

新增 `test_photo_watermark_formats_2026_09_15.py`（3 題）：

| 題目 | 守什麼 |
|---|---|
| 透明 PNG 內容不變 | 觀測點是**像素**（不透明且接近白的取樣數），不是格式字串——格式對了但內容被壓平一樣是毀圖 |
| JPEG 來源逐字不變 | 回歸基準。少了它，「PNG 保留 alpha」可以靠「全部存成 PNG」矇混，而那會讓每張現場照片體積暴增 |
| 副檔名與真實內容一致 | 走完整條上傳路徑，讀磁碟上的檔案回來驗 |

素材刻意做成「透明處底下的 RGB 也是白的」——那正是真實去背 PNG 的樣子，也是
「丟掉 alpha 就整個消失」的必要條件。用純透明黑底的圖**測不出這個 bug**。
前兩題已實測「還原成修復前的 `photos.py` 會紅」。

#### 四、部署包只留兩份

使用者要求：「當第三個打包檔的時候自動刪除第一個打包檔，避免重複堆積」。
`build_deploy_package.ps1` 新增 `-KeepPackages`（預設 2，`0` = 不清理）。

- **排在整個流程最後**：新包已解壓完成、通過 backend/frontend 存在性驗證、manifest
  也寫好了才清。打包中途失敗一律走 `Fail` 直接 exit，永遠不會走到這裡——
  **不會出現「新包沒做成、舊包卻被刪掉」**
- 只刪名字符合 `yyyyMMdd_HHmmss_<commit>` 的資料夾。這個目錄使用者自己會進去翻，
  手動放進來的東西（改名留存的包、筆記）不能被掃掉
- 排序用資料夾名稱不用 `LastWriteTime`——名字開頭就是時間戳，字串排序即時間排序，
  而 `LastWriteTime` 會被「複製到隨身碟」之類的動作改掉
- 已用沙盒實測：3 份包＋2 個自訂資料夾 → 只刪掉最舊那份，自訂資料夾原封不動

清理前 `deploy_packages` 有 10 份共 347 MB（每份約 35 MB）。

---

### 2026-09-15（第十輪）— 打包被一題 PDF 測試擋下：Edge 並發上限在 xdist 底下失效（DB 無異動）

打包腳本中止：`test_network_plans.py::test_export_excel_and_pdf` 倒在
`subprocess.TimeoutExpired`，1 failed / 999 passed，**992 秒**。

**那一題單獨跑 6 秒就過**——不是功能壞掉，是 Edge 被塞爆。兩層原因：

1. `EDGE_PDF_SEMAPHORE` 是 **`threading`**.BoundedSemaphore，只管得住同一個行程裡的
   執行緒。正式機是單一 uvicorn 行程，那裡「同時最多 3 個 Edge」是成立的；但
   pytest-xdist 是**多行程**，6～8 個 worker 各自持有一份自己的 semaphore，實際上限
   變成 workers×3＝最多 24 個 `msedge.exe` 同時搶 CPU。
2. `timeout=40` 量的是**牆鐘時間**。機器被吃滿時，光 Edge 冷啟動就可能耗掉大半。而
   `subprocess.TimeoutExpired` **全 repo 沒有任何一處接**——正式機真的逾時的話，
   使用者拿到的是沒有訊息的 500，log 只有一份 traceback，看不出是渲染逾時。

**改動**

| 位置 | 內容 |
|---|---|
| `helpers/startup.py` | 新增 `run_edge_pdf()`：semaphore ＋ 逾時 ＋ 逾時寫一行明確的 log。**逾時刻意吞掉不外拋**——16 個呼叫端下一行本來就都有「PDF 沒產出就 raise ValueError」，讓那道既有檢查去報錯，錯誤路徑只留一條 |
| 同上 | `EDGE_PDF_TIMEOUT_SECONDS`：40 → **120 秒**，可用 `MOTRIX_EDGE_PDF_TIMEOUT` 覆蓋。原本是散在三個檔案的 17 份字面值 |
| `pdf_gen.py`（15）／`network_plan_export.py`（1）／`routers/reports.py`（1） | 全部收斂成 `run_edge_pdf([...])`；三個檔案的 `import subprocess` 一併移除 |
| `tests/conftest.py` | xdist 底下把每個 worker 的 Edge 上限壓到 1。**刻意改測試不改產品**：跨行程上限要靠檔案鎖或具名 mutex，那會為了正式機根本不存在的情境（單行程）引進「行程被砍、鎖沒釋放」的新失敗模式 |

**`routers/reports.py` 那處差點漏掉**——第一輪用字面值 `timeout=40` 搜尋掃不到它，
它寫的是 `60`。是 `test_pdf_concurrency_2026_09_07.py` 紅了才浮出來（那題的 docstring
本來就列了三個地方）。

**順手把那道守門改成真的守得住**：原本那題比對的是「現有三處 import 的
`EDGE_PDF_SEMAPHORE` 是不是同一個物件」——**第四處冒出來時它不會紅**，這次差點漏掉
第三處就是證明。改成兩題：①三個模組走的是同一支 `run_edge_pdf`；②**靜態掃描整個
backend**，有人自己 `subprocess.run` 去跑 msedge 就紅（排除 `run_edge_pdf` 本人）。
第二題已用「種一個假的違規檔案」實測會紅。

**結果**：完整非 e2e 套件 **1001 passed / 0 failed，165 秒**——對照修復前的 992 秒。
六倍的差距就是 24 個 `msedge.exe` 互相搶 CPU 的代價。

---

### 2026-09-15（第九輪）— 業務開發／案件動態的附件從上線起每一張都是 403（DB 無異動）

使用者回報：「業務開發的上傳照片跟 pdf 功能失效」。

**上傳是好的，壞的是讀回來**。`/api/uploads/{path}` 認兩種憑證：`?pt=`（`routers/
uploads.py` 用 HMAC 簽的短效簽章，形狀是 `{expires}.{sig}`，要先跟 `/api/photo-token`
換）或 `?token=`／Bearer（session token）。2026-09-14 那批附件功能的兩處前端，把
**session token 直接當成 `pt`** 送出去：

| 位置 | 寫法 |
|---|---|
| `dev-crm.html::logFileUrl()` | `?pt=${this.token}` |
| `case-management.js::fileUrl()` | `?pt=${this.session.token}` |

`_verify_photo_token()` 第一步 `token.split(".", 1)` 就對不上（session token 是 64 個
hex、沒有點）→ **每一張附件、每一次載入，必定 403**。使用者看到的是縮圖破圖、PDF
點開跳出一段 JSON 錯誤。已在正式機（`a31603d`）用不帶登入的 curl 確認：拿一串
64-hex 當 `pt` 打一個**根本不存在**的路徑，回的是 403 而不是 404——簽章在檔案存在
與否之前就先被擋下。

**修法：沿用同頁既有的兩套慣例，不另創第三套。** 同一個檔案裡的回簽附件／憑據附件
本來就走 `previewAttachmentFile()`（點下去才換 token 再開新分頁），工作日誌照片走
`photoUrl()`（快取 pt、換到之前先回 1x1 透明圖）。動態附件改成圖片走 `photoUrl()`、
PDF 走 `previewAttachmentFile()`；`fileUrl()`／`logFileUrl()` 直接刪掉，不留一支容易
誤用的同義函式。`dev-crm.html` 原本沒有這兩支，補上（`_ptCache` 一起）。

**為什麼整套測試沒擋下來**（這格才是重點）：

1. `test_feed_attachments_2026_09_14.py` 八題全綠，但它們只驗到「POST 回傳了 path
   且該路徑的實體檔案存在」——**沒有任何一題走過讀取端點**。
2. 而且當時也寫不出來：`conftest.py` 只把 `helpers/uploads.py`（存檔）的
   `UPLOADS_ROOT` 導到 tmp，`routers/uploads.py`（讀檔）算的是**第三份**獨立的
   `UPLOADS_ROOT`，沒有被導——寫進 tmp、讀真實 `uploads/`，任何讀回來的測試都必定
   404。這個缺口本輪一併補上。

**新增測試**（兩支都實測過「還原成修復前的寫法會紅」，不是只確認修完是綠的）：

- `test_feed_attachment_serving_2026_09_15.py`（3 題）：換 pt → 讀檔，比對**磁碟上的
  實體檔**而不是上傳的原始位元組（圖片會先過浮水印重新編碼，拿原始位元組比會紅在
  浮水印上、不是紅在讀取路徑上）；另外把「session token 不能當 pt 用」釘成白紙黑字。
- `test_e2e_feed_attachment_render_2026_09_15.py`（2 題，業務開發＋案件動態各一）：
  觀測點是 **`img.naturalWidth > 0`**。元素存在不算（破圖的 `<img>` 也存在）、比對
  `src` 字串更不算（那只是把當初寫錯的那串抄進測試裡）。兩個頁面各自實作了一份附件
  顯示，所以兩邊各一題——只驗一邊，另一邊會繼續破圖而測試全綠，那正是 09-14 的情形。

**順帶記下、本輪沒動的兩點**（都不影響這次回報的症狀，不在本輪範圍內）：

- 圖片壓完浮水印後 `photos.py` 吐回來的是**重新編碼的 JPEG**，但 `save_document_files()`
  仍沿用原副檔名與原 `mime`——上傳 `.png` 會存成副檔名 `.png`、內容是 JPEG 的檔案。
  瀏覽器自己會認，`<img>` 正常顯示（e2e 已實測），只是 metadata 與實體內容不一致。
- `case-management.html` 工作日誌照片那一塊是 `<a :href="photoUrl(p.path)">`——pt 還沒
  換回來時 href 是那張 1x1 佔位圖，在那個短窗口內點下去會開到空白圖。既有行為。

---

### 2026-09-15（第八輪）— 簽核照組織流程走：身兼主管者自己簽、最高管理者只知會（DB 無異動）

使用者交辦：「當超級管理員解鎖報價單編輯，簽核要按照組織流程簽核…實際要組織流程
高晟耀他自己簽核兩次，我這邊只做知會，另外…當某位主管同時為兩層以上簽核人，只要跳
通知做確認，可直接簽核兩次以上，避免重複簽核兩次的狀態」。

**① 組織鏈不再「跳過本人換人簽」**（`helpers/tiered_approval.py::resolve_submitter_org_chain()`）

`corbin` 同時是「策略開發整合中心」部門主管與「總經理辦公室」處主管。舊規則
（2026-08-22i）是「主管是自己就往上換人，換到頂就抓一個別的 superadmin」——所以他
解鎖改版自己的報價單時，簽核落到 `jeff` 頭上，而他在組織上的那兩關**完全沒有留下
紀錄**。新規則見 §5.3 的流程圖：每一關都成立、本人簽的標 `selfApproval`，鏈到頂就
**知會**其他在職 superadmin（`notifications.type='approval_notice'`，各單據類型各自
前綴），不再把人硬塞進簽核鏈。

一般員工的鏈**完全沒變**（部門主管不是自己 → 就那一層）。測試裡第一題就是這個回歸
基準——少了它，後面「多一層」的斷言可以靠「無條件加兩層」變綠。

連帶要一起改的三個地方（少一個就是「角標有數字、點進去沒按鈕」）：

| 位置 | 改動 |
|---|---|
| `quotations.py::_exclude_requester()` | 標了 `selfApproval` 的不剔除（剔掉＝整關無聲蒸發） |
| `approval-queue.html::canApprove()` | 有簽核層時不再一律排除申請人；排除只留在無簽核層的 superadmin fallback |
| `quotation-form.html::isCurrentTierApprover()` | 同上 |

`test_approval_queue_badge_consistency_2026_09_15.py` 裡那份 `canApprove()` 的 Python
鏡像同步更新——它存在的理由就是「兩邊規則本來就必須一樣」。

**② 同一人連任多層 → 一次簽完**（`plan_self_cascade()`／`cascade_self_tiers()`）

前端算出「按下去之後還會連續輪到自己幾層」，寫進**原本就有的那個確認視窗**（不多跳
第二個），使用者確認就帶 `cascade:true`，後端重新驗證後一次蓋完，回傳 `signedTiers`
讓提示說得出「已一併完成第 1、2 層」。共用判斷在 `static/approval-cascade.js`，
七個簽核入口共用（佇列頁、報價單、請款單、案件管理的出貨單／完工單／兩種憑據）。

⚠️ **合併條件刻意保守**：只吃「簽下去這一層一定完成」的連續層——該層剩下未簽的只有
自己（或自己代理的人）。中間夾著別人、或同層還有第二位待簽，一律停在前面；跨過去
等於替別人做決定。兩題測試專門釘這個邊界。額外支出是「當層任一人簽即過層」的語意，
用同一支 `plan_self_cascade(tier_completes_on_first=True)`。

**③ 順手修掉的真 bug**（`case_extra_expenses.py`，兩支 approve 端點各一份）

- `check_approve_permission()` 的回傳值**整個被丟掉**——其他六個 router 都是
  `ok, code, msg = ...` 再 raise，這裡是裸呼叫，等於當層簽核人檢查形同虛設，
  任何過得了 `_guard_case()` 的人都簽得掉任何一層。
- `check_no_tier_self_approval()` 原本無條件套用，但它是**無簽核層時**的 fallback
  規則（其他 router 都只在 no-tier 分支呼叫）。不改的話，①的自簽層在額外支出上
  永遠簽不掉。

**測試**：新增 `test_org_chain_approval_2026_09_15.py`（10 題）。除了正向控制之外，
斷言一律挑「成功後才會被寫入的下游欄位」（DB 裡的 status／currentTier／approvedAt），
不看自己送進去的 request body。

---

### 2026-09-15（第七輪）— 開發機不上傳雲端、正式機照傳（DB 無異動）

使用者指示：「開發機的所有檔案不上傳雲端，但正式機需要上傳雲端」。

**作法**：`archive.py::cloud_archive_enabled()` 新增政策開關，在所有權檢查**之前**
生效。判斷序：環境變數 `MOTRIX_CLOUD_ARCHIVE=off/on` → 專案根目錄 `.no_cloud_archive`
檔（開發機放，已 gitignore）→ 都沒有則允許。`_archive_ok()` 是所有雲端寫入的總開關，
所以即時／每日／週／月備份與兩組鏡像一次覆蓋。

**取捨**：
- **不能只靠 2026-09-14 的所有權標記**——那是防覆蓋的碰撞防護，marker 不存在時會
  **自動認領**（Drive 同步異常／被刪／重新掛載都可能），開發機一認領就換成正式機
  被擋住、備份靜默停止；讀取失敗還 fail-open。停用時連 marker 都不碰。
- **預設是允許上傳**：兩方向風險不對稱。開發機誤傳＝雲端多垃圾（可刪）；正式機誤停
  ＝備份靜靜消失數週（2026-08-24 真的發生過）。要停的那台明確標記。
- **用 gitignore 過的檔案而不是設定值**：設定值會隨資料庫還原一起搬家，DR 換機時
  新正式機會靜靜不備份。打包走 `git archive`，這個檔案不可能跟去正式機。
- 連帶處理：不上傳的機器不再收到「雲端備份過期」假警報（本機快照那條照查）、
  不監看雲端碟容量、清掉過期的 `BACKUP_ALERT.txt`。

**現況**：本機（JEFF）已放標記檔停止上傳；G: 存檔所有權屬於 MOTRIX（正式機，
2026-09-14 23:54 認領），正式機不受影響。

**測試**：新增 `test_cloud_archive_policy_2026_09_15.py`（12 題），重點那題是
「停用狀態下不得認領所有權」。conftest 把標記路徑導到暫存目錄——否則開發機上這個
真實檔案會讓整批雲端備份測試變紅。

---

### 2026-09-15（第六輪）— 簽核佇列與「最近的變動」的可見範圍（DB 無異動）

使用者要求：「沒有權限的使用者最近的變動只能看到自己的，如果沒有就不顯示；簽核
佇列除了管理員以上都只能看到自己的簽核佇列卡在哪邊，落實權限管制的機制」。

兩個洞的共同點是**清單端點只有 `_require_user()`**：功能本身正確、每個欄位都算得
對，但「誰能拿到這份清單」從來沒被限制過。這跟 2026-09-14 那輪收掉的詳情端點
IDOR 是同一類，只是發生在清單層——而清單層更容易被漏掉，因為它「看起來只是摘要」。

**① `GET /api/approval-queue`**：任何登入者原本都拿得到**全公司**待簽核單據的客戶、
專案、**金額**、送審人與整條簽核鏈（8 種單據全部）。新增
`quotations.py::_queue_visible_to()`，非管理員只看得到兩種：

| 看得到 | 為什麼 |
|---|---|
| 自己送審的 | 他要知道自己的單卡在哪一關、卡在誰身上——這就是使用者說的「卡在哪邊」 |
| 簽核鏈裡有自己的（含代理他人時的被代理人） | 比對**所有層**而不是只有當前層：只比當前層的話，下一關才輪到的人看不到即將輪到自己的單，已經簽過的人也看不到後面卡住了，兩種都會讓人以為「沒我的事」 |

⚠️ **過濾刻意只寫一處**、套在組裝好的 `items` 上（分組**之前**，否則會留下「某某人
0 件」的空群組）。這支端點已經長到 8 種單據類型，逐型各寫一段 WHERE 的話，下次
新增類型時漏掉的那一種就是全開的——「漏了會外洩」的規則必須預設安全。有一題測試
專門釘住「`_queue_visible_to(` 在原始碼裡只出現一次，而且位置在分組之前」。

詳情端點（`/api/approval-queue/detail`）2026-09-14 已經有 `_guard_queue_detail()`
與金額遮蔽，這輪不用再動；`/count` 本來就只算「輪到我」，是新規則的子集。

**② `GET /api/dashboard/activity-feed` 的進出物料段**：六個來源裡**唯一**沒有逐筆
過濾的一段（原註解：「比照 /api/devices・/api/materials-summary 開放給所有已登入
使用者」）。但那兩支回的是「有哪些料號、還剩幾個」，這一段回的是「**誰**把哪一個
序號用到哪一個案子」——那是人的行為軌跡，不是庫存數字。結果是一個只有 dashboard
模組的檢視者，在首頁就看得到全公司的料件流向。

改成：有 `inventory`／`equipment` 模組（或 admin）看全部，其他人只看自己動過的。
⚠️ 歸屬欄位（`consumed_by`／`created_by`）存的是**顯示名稱字串**，這張表沒有 user id
欄位，所以空字串一律不給——把空值當成「符合」等於所有沒填操作者的舊資料全部外洩。

**③「如果沒有就不顯示」**：首頁「最近的變動」整個 `<section>` 在一筆都沒有時收掉，
不留篩選鈕與空狀態。判斷用 `activityFeed` 而不是 `filteredFeed`——切到某個模組剛好
沒異動時，那是「這個模組沒動靜」，區塊要留著讓空狀態說明，不是整塊消失。

**④ 簽核佇列副標講清楚範圍**：非管理員看到的數字跟別人講的對不上時，要能看出是
權限範圍而不是系統漏單，所以副標會加「（僅顯示你送審的與需要你簽核的）」。

**測試**：新增 `test_queue_and_feed_scoping_2026_09_15.py`（9 題）。每一題都配一個
**看得到的正向控制**（admin 或有模組的人看得到同一筆資料）——只斷言「看不到」的話，
端點整個壞掉、回空清單也會通過，那是這個 repo 記過好幾次的假綠燈樣式。

**⑤ 實機驗證（同輪補做）**：開了一台只綁 127.0.0.1 的驗證用伺服器（備用埠、
`MOTRIX_DISABLE_SCHEDULERS=1`），建兩個 `_verify_` 臨時帳號（superadmin ／
viewer+dashboard）跑完三頁，驗完連帳號、session、軌跡與活躍時數紀錄一起刪掉
（`user_request_log` 回到驗證前的 1,577 筆）。**刻意不借用真人帳號的 session**
——`create_claude_account.py` 的說明就記著那個教訓：借用 corbin 的 session 做自動化，
稽核紀錄與通知信全部誤植為該真人所為。

實測結果：superadmin 的簽核佇列 4 筆（含客戶名與單號）、viewer 0 筆且整頁內文只有
180 字；首頁「最近的變動」對 viewer 在 DOM 裡但完全不顯示（篩選鈕 0 個可見）；
在線時數統計的成員下拉 15 個選項、軌跡表頭六欄、131 個重複標記只有 8 個真的顯示
（repeat>1 的那些）、「顯示原始路徑」0 → 131 筆。三頁主控台零錯誤零警告。
⚠️ 截圖在這台機器上一律逾時（CDP `Page.captureScreenshot` 30 秒），DOM 查詢完全正常
——全站反轉濾鏡＋上百列的大頁面會讓截圖卡死，要驗畫面請直接查 DOM，不要等截圖。

**⑥ 實機才抓到的 bug：同一道守門有兩份實作，只修了一份**

首頁有兩道「沒有儀表板權限就導去案件管理」的守門：檔案開頭的 inline script，以及
Alpine `init()` 裡的那段。2026-09-13 的模組權限稽核只補了 inline 那份（註解還寫著
「勾了儀表板模組的人照樣被踢去案件管理，兩邊對不齊」），**`init()` 那份至今只看
`finance`／`quotation`**——所以只勾「儀表板」模組的人會先通過第一關、再被第二關踢走。
這個洞是反方向的（不是外洩，是誤擋），測試照不到（那是前端導轉），只有真的用那種
帳號打開首頁才會現形。已補 `canDashboard`，條件照抄 `sidebar.js` 的 `canDash`。

---

### 2026-09-15（第五輪）— 一天少 120 GB 的追查：測試把真實 PDF 存檔複製進暫存（DB 無異動）

使用者回報「今天少了將近 120 GB 的空間，是否代碼儲存有狀況」。**不是程式碼的問題**
（`.git` 0.12 GB、`deploy_packages` 0.23 GB、`db_backups` 0.21 GB、G: 雲端存檔 1.83 GB，
備份都是最新的）。實測 `%TEMP%` 底下 **84 個 pytest 暫存目錄吃掉 136.3 GB**
（09/14 晚間 65 次共 111.3 GB、09/15 凌晨 18 次共 24.9 GB），已全部清除
（可用空間 293.4 → 429.6 GB）。

**一次測試為什麼要 3～5 GB**：拆開看是 **12,931 個 PDF（3.47 GB）** ＋ 1,584 個 `.db`
（1.29 GB）。PDF 不是測試產生的，是**從專案根目錄的真實 PDF 存檔複製進來的**
——`archive._mirror_pdf_archives()` 會把 `pdf_gen._get_*_pdf_base()` 指到的 6 個目錄
鏡像進存檔區，而 `conftest.py` 幫 DB／archive／uploads／photos 都導開了，
**只有這 6 個 PDF 目錄沒導**。那裡有 1,617 個真實 PDF，乘上 6 個 xdist worker
再乘上 session 級與 per-test 兩份存檔根目錄，就是那 12,931 個檔。

⚠️ **更嚴重的是反方向**：測試也**真的寫進**了那些真實目錄。查到
`報價單PDF` 1,183 檔裡有 138 個、`結案報表PDF` 139 檔裡有 55 個是
`MQ-TEST-*`／`MQ-CLOSE-004`／`_tester` 的測試產物（最早 2026-08-26）；其中
**108 個已經被每日備份鏡像到公司雲端存檔**（`G:\…\PDF存檔鏡像` 864 檔裡）。
`MQ-TEST-003`／`MQ-CLOSE-004` 在資料庫裡不存在、系統也沒有 `tester` 這個帳號
——可以確定全是測試假資料。這是 2026-09-07 那批隔離修正（當時修掉測試寫進
G: 即時備份、寫進 repo `uploads/`）唯一漏掉的一類。

**per-test patch 擋不住，一定要 session 級**：結案報表是
`spawn_bg_thread(_generate_case_closing_pdf, ...)`（`routers/quotations.py:1878`）
在背景產生的，Edge headless 渲染要好幾秒，**寫檔時那一題早就結束、monkeypatch 也
還原了**，那條執行緒讀到的又是真實路徑。本輪實測：只加 per-test patch 的那一次
全套跑完，真實目錄還是多了 7 個檔。所以 `_app`（session 級、直接賦值不會被還原）
與 `client`（per-test，讓題與題之間互相隔離）兩層都要有——跟既有
`archive._archive_base` ／ `isolated_archive` 的分層完全同一個道理。

**為什麼容量告警沒響**：`_check_disk_space()` 的兩個門檻是 AND（小碟看百分比、
大碟看絕對值，這個設計本身是對的）。930 GB 的碟上百分比那關永遠先滿足，實際觸發
點就是絕對值 20 GB——**136 GB 的洩漏離「剩 20 GB」還很遠**。
把 AND 改成 OR 不是正解：那會在剩 93 GB 時就開始每天寄信。

本輪改法：
1. **`_DISK_FREE_MIN_GB` 20 → 50**：對一台「每跑一次測試寫 3～4 GB」的機器，
   剩 20 GB 只剩五次測試的餘裕，而且備份寫不進去通常會先發作。
2. **新增 `_check_temp_bloat()`**（掛進每日排程／首次啟動／補跑三條路徑）：
   `%TEMP%` 底下 `motrix-pytest*`／`motrix-bench*`／`pytest-of-*` 合計超過 20 GB
   就寄信，**與剩餘空間無關**——「只看剩多少」永遠照不到「有東西在無聲累積」。
   信裡直接列出可以刪的目錄與各自大小。沿用 `disk_space_low` 這個通知偏好 key
   （對收信的人是同一件事，分兩個開關只會讓人多關一個），但標題不會誤寫成
   「空間不足」。
3. **打包腳本自己清**（`build_deploy_package.ps1`）：`--basetemp` 用的是帶時間戳的
   目錄名，**每次都不一樣所以永遠不會被覆蓋或清除**，一次打包固定漏 3～4 GB。
   改成測試通過後自己 `rd`；**e2e 失敗時保留**——那些檔案是唯一的現場。
4. **`conftest.py` 補上 PDF 存檔隔離**（session ＋ per-test 兩層，含 demo 那 6 個
   `from db import` by value 綁進 pdf_gen 的常數）。

**測試**：`test_backup_freshness_disk_2026_09_14.py` 加 4 題（暫存超標會叫並列出目錄、
不認別人的暫存目錄、門檻以下不吵、6 類 PDF 存檔在測試期間一律不得指向專案內）。
其中「不認別人的暫存目錄」那題的正向控制在前一題（同樣門檻下名字對的會叫），
不是「什麼都不叫」的假綠燈。

⚠️ 順手修掉那個 fixture 自己的假綠燈：`sent` fixture 的 `threading.Thread` 替身
**只轉 `args` 不轉 `kwargs`**，真正的 Thread 兩種都傳——差異會表現成「正式碼用
kwargs 帶的參數在測試裡憑空消失」，於是測試綠燈而信裡缺資料（本輪實際踩到）。

⚠️ 也順手修掉 `version_manifest.json` 的順序：慣例是新條目插**最前面**（打包腳本讀
`[0]` 當最新版顯示在部署包資訊裡），但最後 5 筆被附加到尾端了，所以 09-15 之前
打的包上面標的「最新版本」都還是 `2026-09-14i`。已把那 5 筆移回前面。

未處理（等使用者裁示）：真實目錄與雲端鏡像裡那 301 個測試 PDF（81 MB）還沒刪。

---

### 2026-09-15（第四輪）— 操作軌跡改用人話＋成員篩選（DB 無異動）

使用者要求：「在更直覺的語言，在線時數統計的操作軌跡，要能篩選每個使用者」。

原本每一列是 `GET /api/quotations/MQ-202607-047/finance-summary` ＋ `403`
這種給寫程式的人看的東西；篩選則只能「點上面時數表的某一列」——**沒有活躍時數的人
點不到，而那常常正是想查的那個人**（請假、離職、剛被停用）。

**① 新增 `backend/trail.py`（寫入端與讀取端共用）**

`main.py` 的中介層（寫入）跟 `routers/system.py` 的軌跡端點（讀取）必須共用同一份
「什麼不該記」的清單：放在 main.py 會讓 router 反過來 import main（循環匯入），
各自複製一份則遲早不同步——而不同步的那一刻，讀取端就會露出寫入端早就決定要藏的
東西。`_TRAIL_SKIP_PREFIXES` / `_TRAIL_DEDUPE_SECONDS` 從 main.py 搬過去。

**② 一句人話：`describe(method, path)`**

| 取捨 | 說明 |
|---|---|
| 翻譯原則 | 沿用 2026-09-14 的「**不猜**」：對不到的模組／路徑段原樣顯示原始字串（`查看 /api/brand-new-module 清單`），不用相近的字硬湊——猜錯的標籤比看得懂的路徑更誤導 |
| 對照表來源 | 模組名掃 `routers/*.py` 的 decorator（58 個第一段全覆蓋）、頁名抓各頁 `<title>`、動作段抓實際存在的子路徑——不是憑印象列的 |
| 中文動賓順序 | 動作標籤帶 `{}` 當受詞位置。全部用「動詞＋受詞」硬拼會拼出「解鎖密碼使用者 #9」「轉為案件業務開發案 #90」；現在是「解鎖使用者 #9 的密碼」「將業務開發案 #90 轉為案件」 |
| 編號掛給誰 | 照路徑順序掛在**前面那個名詞**上：`/api/inventory/stock-items/5/adjust` 的 5 是庫存品項的編號，不是庫存的 |
| 狀態碼 | `403` → 「沒有權限（被擋下）」、`409` → 「有人剛改過（衝突）」。另回 `ok` 布林給畫面上色 |
| 類型 | 檢視／變更／刪除／簽核／匯出五種（`kind`），畫面用顏色分——「只是看看」跟「刪掉了東西」不該長得一樣 |
| 原始路徑 | 照原樣回傳，畫面有「顯示原始路徑」開關（預設關）。人話是給人看的，出事時要查的是原始事實 |

**③ 剃掉雜訊：實測 1577 筆裡有 519 筆（33%）根本不是人的動作**

判斷標準沿用既有清單的標準「**前端會自動打、不是人按的**」，不是「不重要」：
`edit-presence`（同時編輯心跳，每 30 秒）95 筆、`list-prefs`（欄位偏好，開頁自動讀寫）
196 筆、`approval-queue/count`（側欄紅點）77 筆、`*/selectable`（下拉選單資料）117 筆、
`quotations/case-activity`（案件清單的「有新動態」指示燈，**POST 當查詢用**）34 筆
——最後這支還會在軌跡上長出一排「新增案件動態」，說的是反的。

**④ 一次點擊的連鎖請求收斂成一列（384 筆）**

既有的 30 秒去重只擋「同一支端點被連打」，擋不掉「一個動作打好幾支**不同**端點」：
開一張案件會同時撈 base＋財務彙總＋材料採購＋額外支出＋更新記錄，一次點擊留六列
幾乎一樣的字。寫入端用「群組基準路徑」去重（`path = base OR path LIKE base||'/%'`
兩個條件，**不能只用 LIKE 前綴**——那會讓 `/api/dev-cases/1` 的樣式吃掉
`/api/dev-cases/12/logs`，變成開了 12 號卻被算進 1 號的群組）。

⚠️ **子路徑用白名單不用黑名單**，這是刻意選的失敗方向：白名單漏一項，結果只是多幾列
重複紀錄；黑名單漏一項，就會把「看了某人的身分證影像」藏進「開啟外包人員 #3」裡面。
只收斂 GET——POST/PUT/DELETE 每一筆都是真的動作，少記一筆就是稽核漏洞。

讀取端另有一道「同一個人、同一句說明、60 秒內相鄰就併成一列（帶 `repeat`）」：寫入端
從今天起才收斂，**已經存在的舊資料還有 90 天**，不併的話接下來三個月每開一張案件
都還是六列一樣的字。翻頁游標取的是**原始**最後一筆 id，不是併完的——拿併完的算會
讓「載入更早的紀錄」跳過還沒看過的資料。

**⑤ 成員篩選（使用者要求的重點）**

`GET /api/user-activity` 多回一個 `members`（走 `users` 表**全部人**，停用的也列，
標「已停用」——離職前做了什麼是最需要查的）。頁面上是下拉選單，跟上面時數表的
點列共用同一個狀態，兩邊會互相反映。時間欄同時改成「今天 20:13／昨天 20:13／
9/14 20:13」。

**測試**：`test_online_activity_2026_09_14.py` 從 19 題加到 26 題（人話、被擋下來的
說明、頁面自動請求不記、連鎖請求收斂、**敏感資源不被收斂吃掉**、篩選只出現選定的人、
成員清單含沒有時數的人）。其中「頁面自動請求不記」那題刻意同時斷言一筆**應該留下**
的請求——只檢查「雜訊不在」的話，軌跡整個壞掉、一片空白也會過。

⚠️ 一併推翻 2026-09-14 的一項指示：模組名「客戶管理」改成「客戶」（現在會被組進
「查看客戶清單」整句），原本釘住舊標籤的那題觀測點跟著改成整句話——那才是畫面上
真正顯示的東西。

未實測：頁面沒有在瀏覽器實際開起來看（改動是欄位與下拉選單，無新端點）。

---

### 2026-09-15（第三輪）— 簽核角標跟佇列對不上（DB 無異動）

使用者回報「我跟另一位是最高管理者，需要我簽核但簽核佇列未顯示」。

**查下去發現佇列頁其實列得出來——是 topbar 的角標是 0。** 使用者不會沒事點進
簽核佇列翻，角標沒數字就等於沒發生，症狀自然表現成「沒顯示」。

根因是 `/api/approval-queue`（列表）與 `/api/approval-queue/count`（角標）是
**兩段各自獨立的查詢**。程式碼裡已經有兩則註解在講這個風險——
「角標數字要跟佇列列表一致，漏掉就會變成『列得出來但 topbar 是 0』，
兩邊矛盾比兩邊都沒有更難查」——但一直是靠每次新增單據類型時人工記得補。
抓到兩個**方向相反**的缺陷：

| | 缺陷 | 後果 |
|---|---|---|
| ① 少算 | count 的迴圈是 `if tiers and ct_idx < len(tiers)`，**沒有簽核層設定的單據整批被跳過** | 那種情況的規則是「任一 superadmin 皆可簽核」（`approve_quotation()` 的 no-tier 分支、前端 `canApprove()` 都這樣判）。佇列列得出來、角標 0 ← **使用者回報的就是這個** |
| ② 多算 | 已結案變更申請是 `WHERE status='pending'` 全部算，**沒排除自己送的** | 自己送的自己簽不掉（`check_no_tier_self_approval()` 擋、`canApprove()` 也回 false）→ 一個**永遠清不掉的紅點** |

修法：count 端點補上 no-tier 分支（`elif is_sa and requestedBy != me`）並在
`case_change_requests` 的查詢加上 `AND requested_by != ?`。

⚠️ no-tier 這段刻意跟**前端** `canApprove()` 一致：自己送的一律不算。後端
`check_no_tier_self_approval()` 另有「唯一在職 superadmin 可自簽」的逃生條款，
但前端不會給按鈕——角標跟著後端算反而會製造一個按不下去的紅點。

新增 `test_approval_queue_badge_consistency_2026_09_15.py`（5 題），守的不變量是
**角標數字必須等於佇列裡 `canApprove()` 為真的項目數**，並把前端那份
`canApprove()` 規則照抄成 Python 版當基準——兩邊的規則本來就必須一樣。
全套 **1008 passed**。

---

### 2026-09-15（第二輪）— 簽核卡死 32.8 秒：同一個坑踩第二次（DB 無異動）

使用者回報「簽核佇列按下簽核後系統卡死十幾秒，內容是已結案案件簽核」。
實測是 **32.8 秒**，而且**稽核紀錄同時被靜默丟掉**。

#### 根因：這個 codebase 第二次踩到同一個形狀

```
save_quotation_json(conn, ...)   # 只 execute、不 commit → conn 持有寫鎖
_audit(...)                      # get_db() 另開一條連線寫入 → 撞自己的鎖
```

SQLite 同時只允許一個 writer，`db.py::_connect()` 是 `connect(timeout=30)`，
所以第二條連線會等滿 30 秒；而 `_audit()` 的 `except` 會把逾時例外吞掉，
**使用者看到的是卡住然後「核准成功」，但事後查不到是誰核准的**。

第一次是 2026-09-10 的 `create_quotation()`——`_build_approval_tiers_and_notify()`
裡的 `_notify()` 同樣另開連線，通知被靜默丟掉（見該函式註解）。

**修法**：`_apply_case_change_request()` 裡四處 `_audit()` 改成 append 進
`deferred_audits`，由 `approve_case_change()` 在 `conn.commit()` 之後統一寫出。
`_sync_device_stock()` 用的是傳進去的同一條 conn，不受影響。
測試檔耗時 **136.6 秒 → 5.1 秒**。

#### 使用者要求的「檢查別的區域有沒有一樣的狀態」

寫成**守門測試**而不是一次性掃描（`test_write_lock_deadlock_guard_2026_09_15.py`）：
AST 靜態掃 `routers/`＋`helpers/`＋`main.py` 全部函式，找「寫了還沒 commit 就
跨連線再寫」。**刻意不執行任何程式碼**——真跑起來要等 30 秒才看得到症狀，
那種測試沒人會留著。

初掃 27 個命中，**逐一核對後 26 個是誤報**，兩個判準太寬：

| 誤報來源 | 為什麼不算 |
|---|---|
| `_set_setting()`（18 處，整個 system.py） | 它自己 `get_db()`、自己 commit、自己 close，是完整的一次交易，不會把鎖留給呼叫端 |
| `notify_*` 前綴（8 處） | 核對過 `helpers/email_notify.py` 全部 43 支：只查收件人 email（**讀**）然後開執行緒寄信，**一支都沒有寫 db**。WAL 下 reader 不會被 writer 擋 |

**真正的違規只有一處**，就是上面修掉的那個。守門測試已用「拿 git 上修復前的
`quotations.py` 直接掃」證明抓得到（4 處全中），修復後 0 處——**新寫的守門測試
一定要先證明它會紅**（MODULE-AUDIT §5 的教訓）。

> 附帶記錄一個目前不是 bug、但值得知道的事：那些 `notify_*` 在 commit 前讀到的是
> **尚未提交的舊狀態**。現在它們只讀使用者 email 所以沒差；日後若有人讓它們去讀
> 剛剛寫入的單據內容，就會讀到舊值。

全套 **1003 passed**。

---

### 2026-09-15 — 打包不再把整台機器吃滿（DB 無異動）

使用者回報：「打包的時候 pytest 會把 CPU 跟記憶體吃滿」。量過之後兩個發現：

**① 記憶體從來不是瓶頸，吃滿的是 CPU。** 32 GB 機器上峰值不到 2 GB。

**② 每個 xdist worker 都在 import 當下跑了一次完整備份。** `import main` 是
module-level 執行（不是 `@app.on_event`），所以 `_schedule_daily()` 的第一件事
——`_daily_backup()`：整庫 SQLite 快照＋41 張表 JSON＋月備份＋uploads/PDF 鏡像＋
過期清理——會在**每一個 worker** 跑一次，`_schedule_weekly()` 再來一次週備份，
`schedule_overdue_check()` 另起執行緒補跑九種檢查。`-n auto` 在 12 執行緒機器上
開 12 個 worker，等於**同一次測試跑了 12 遍完整備份**。

實測（本機 Ryzen 5 5600X，6 實體核心 / 12 執行緒，940 題非 e2e）：

| 設定 | 時間 | 峰值記憶體 | 峰值行程數 |
|---|---|---|---|
| `-n auto`(=12) ＋ 背景排程開著（**原本**） | **274 秒** | 1.86 GB | 33 |
| `-n auto`(=12) ＋ 背景排程停用 | 185 秒 | 2.20 GB | 37 |
| `-n 8` ＋ 背景排程停用 | 171 秒 | 1.63 GB | 23 |
| **`-n 6`（實體核心數）＋ 背景排程停用** | **175 秒** | **1.34 GB** | **20** |

兩項改動：

1. **`conftest.py` 設 `MOTRIX_DISABLE_SCHEDULERS=1`**（`main.py` 讀它決定要不要
   啟動那五個排程）。正式機與手動啟動都不會設，行為逐字不變。
   除了快 32%，也一併拆掉 QUICK 記載的 e2e flaky 放大因子——「背景排程整個
   session 都在寫 db，SQLite 寫鎖被佔住時最多會等 30 秒」。
2. **`build_deploy_package.ps1` 的 `-n auto` 改成依實體核心數開**
   （`min(實體核心, 8)`，查不到用 4）。`-n auto` 取的是**邏輯**處理器數，把 12 個
   worker 塞進 6 個實體核心只會互相搶——**比用 6 個還慢**，記憶體卻多 64%、
   行程數多 85%。順便把打包行程降到 `BelowNormal`（子行程繼承），時間差不多但
   打包期間機器還能用——使用者的痛點是「機器不能用」，不是「跑太久」。

**停掉排程之後有一題立刻變紅**，而且紅得有價值：`test_clean_backup_still_reports_ok`
原本是**靠背景排程的副作用**才綠的——它把 `_snapshot_sqlite` 換成 no-op，卻依賴
啟動時排程已經先跑過一次真的快照、檔案剛好存在。已改成自己造齊前提。

另修：`test_archived_filename_includes_seconds` 把日期資料夾寫死成 `2026-09-14`，
跨過午夜就紅（2026-09-15 實際踩到）。改用 `date.today()`。

**變更申請摘要的代碼值**（使用者回報「專案期間·狀態 `on_track`」）：新增
`_CASE_VALUE_LABELS` 值對照層，已知值翻成中文、**未知值原樣顯示不硬猜**
（硬翻會讓人以為系統認得它）。同類問題的全站掃描已列入 §11。

---

### 2026-09-14（第十五輪）— 報價條款組：付款／驗收／保固可成組切換（DB 無異動）

使用者裁示：「報價單可以增加付款條件的選項，名稱也可以自定義，例如純購料，
他有自己的付款條件、驗收標準、保固條件，可由報價人手動點選方塊做切換，只有
超級管理員可以點選設為預設付款條件的功能跟建立，像是完工單內單據用語這樣的選項」。

**形狀**：`system_settings.quote_terms_presets = {presets: [...], defaultKey: "..."}`，
每組 = `{key, name, paymentTerms, deliveryTerms, acceptanceTerms, warrantyTerms, afterSales}`。

| 端點 | 權限 | 說明 |
|---|---|---|
| `GET /api/settings/quote-terms-presets` | **登入即可** | 報價人要靠它切換；限 superadmin 等於這功能只有 superadmin 用得到，而它是做給報價人的 |
| `PUT /api/settings/quote-terms-presets` | superadmin | 整組覆寫（建立／改名／改內容／刪除／設預設都走這一支） |

**三個刻意的設計決定**：

1. **報價單存的是複製過去的文字，不是指向設定的 key**。已經開出去的單不能因為
   有人事後改了條款組、或把那組刪掉而跟著變——跟同日「單據原始版本存檔」同一個
   判準。`termsPresetKey` 只當「從哪一組起手」的線索。
2. **後端不自動種一組預設**。前端 `quotation-form.html` 本來就有 `DEFAULT_TERMS`
   當「沒有任何設定時」的內容，後端再種一份就變成兩個事實來源，而且一旦分岔
   不會有任何地方報錯。沒設定＝維持改動前的行為。
3. **刪掉被設為預設的那組時 `defaultKey` 自我修復**（落到第一組）。留一個指向
   不存在的 key 會讓新報價單完全拿不到預設條款，而畫面上看不出為什麼。

**`checkApproval()` 的比對基準一併改掉**：原本一律比 `DEFAULT_TERMS`，有了條款組
之後切到「純購料」會整組被判定成「條件已修改」而觸發簽核提示——**這功能一用就報警**。
現在以目前選中的那組為基準，提示文字也改成「與條款組「純購料」不同」。

#### e2e 抓到一個單元測試照不到的 bug

寫完之後語法檢查過、後端 14 題全綠，但 e2e 一跑就紅：`termsPresetKey` 設對了、
付款條件卻還是舊的。根因是 `init()` 新增模式分支裡那行**無條件**的
`this.q.paymentTerms = this._defaultPaymentTerms`，把稍早套用的整組條款又蓋回去。
已把套用移進那個分支，並保留「沒有任何條款組時走舊的單欄位預設」這條退路。
**這就是為什麼這種前端行為要有 e2e**——語法檢查與後端測試都照不到它。

測試：`test_quote_terms_presets_2026_09_14.py`（14 題）＋
`test_e2e_quote_terms_presets_2026_09_14.py`（3 題：預設組自動帶入／點方塊五欄
整組換掉／切換不得觸發假的簽核提示）。全套 **993 passed**。

---

### 2026-09-14（第十四輪）— 完工單用語搬到最上面＋業務員績效改讀業務負責（DB 無異動）

**完工單**（使用者：「避免員工都選完最後再重來」）：「單據用語」與「逐欄調整」
兩張卡從整頁最下方搬到最前面。順手處理了那個「換個位置還是會發生」的問題——
`applyPreset()` 是**整批覆寫**不是合併，先微調再按 preset 一樣會被吃掉，
現在偵測到有自訂值會先 `confirm()` 問一聲。

**營運報表業務員績效**（使用者：「讀取案件管理的人員角色，業務負責的欄位」）：

| | 舊 | 新 |
|---|---|---|
| 歸屬依據 | `quotations.sales_person_id`（**開單的人**） | `caseRecord.roles.sales`（**這個案子歸誰**），沒填才退回舊的 |
| 改名 | 用 id 比對，已處理 | 同左（反查得到帳號時） |
| 同名 | — | **不猜**，退回名字分組 |
| 反查不到 | — | 仍以那個名字歸屬，不會掉回開單者 |
| 目標達成率 | 各算各的 | **與績效表用同一組 key** |

三個刻意的決定：

1. **舊案件不回填**。`roles.sales` 當初沒人填，補一個猜測值只會製造假資料——
   沒填的就照舊用開單者，看得出來是舊資料。
2. **同名不猜**。硬選一個等於把 A 的業績算到 B 頭上；退回名字分組至少是
   「兩個同名的人被合成一列」這種看得出來的錯。
3. **目標達成率一起改**。那兩張表是並排看的，一邊算業務負責、另一邊算開單者，
   同一個人的兩個數字對不起來而且看不出為什麼。

⚠️ **部門彙總與 `department_id` 篩選仍依 `sales_person_id`**，沒有跟著改：
那條線會影響整份報表的取數範圍，而且要先決定「案件的部門是跟著開單者還是跟著
業務負責」。已記在 §11——**若兩張表的部門數字對不上，原因就在這裡**。

`_compute_achievement()` 是純函式、可能被直接餵手組的 dict（既有單元測試就是），
所以加了 `_owner_key_of()` 退路：缺 `ownerKey` 時退回舊欄位，語意與改動前相同。

全套 **976 passed**。

---

### 2026-09-14（第十三輪）— 已結案變更申請改成可讀摘要（DB 無異動）

使用者附截圖交辦：簽核佇列的「核准後會套用的內容」整包印出
`{"stages":[...],"payment":{"items":[{...,"writeOffRequestedAt":"...",
"invoiceFiles":[{"path":"..."}]}]}}`，**審核者根本無法從中判斷要不要核准**。

根因單純：`approval_queue_detail()` 對 `case_change` 是
`out["changes"] = {"after": payload}`——把 `payload_json` 整包丟給前端，而前端對
物件值是 `JSON.stringify()`。

**但這件事不只是難讀，是會誤導**：`approve_case_change()` 處理
`case_record_update` 的第一行是 `new_case_record["stages"] = cr.get("stages")`
——payload 裡的 stages **根本不會被套用**（案件階段有自己的專屬端點，見 §7.2）。
把它印在「核准後會套用的內容」底下，是告訴審核者一件不會發生的事。

新增 `_summarize_case_change()`，六種 `action_type` 各自產出可讀的 before／after：

| action_type | 摘要內容 |
|---|---|
| `case_record_update` | 攤平成「合約·交貨地址」「角色·業務負責」「款項 #1·金額」這類標籤，**只列有變動的欄位**；沒有可辨識變動時明講，而不是倒一堆 JSON |
| `payment_mark` | 只列這次申請真的動到的欄位（已收款／收款日期／發票號碼…），含前後值 |
| `*_upload` | 「於 叫料項目 #3 新增附件」＋檔名與數量（不給實體路徑） |
| `*_delete` | 「刪除 款項 #1 的發票附件」＋被刪檔案的檔名 |
| 未知類型 | 講清楚「這個類型還沒有可讀摘要，請開案件頁確認」——**不是**退回倒 raw JSON |

攤平刻意不收：`stages`（不會被套用）、`writeOffStatus`／`writeOffRequestedAt`／
`invoiceFiles[].path` 這類內部欄位；`materials`／`devices` 只收筆數
（逐項展開會比 raw JSON 還長，而要核的是「有沒有變動」）。

回傳形狀沿用額外支出那條既有路徑（`{label, before, after}`），所以
`approval-queue.html` 的渲染一行都不用改。

**使用者要求的「檢查是否有其他地方也這樣顯示」**：掃過全前端，畫面上做
`JSON.stringify` 的只有 `approval-queue.html:819` 一處，就是這一塊的 fallback
（後端現在一律送純量，不會再觸發）；稽核紀錄頁根本不渲染 `detail` 欄位；
額外支出變更申請本來就是逐欄對照。沒有第二處。

測試 `test_case_change_summary_2026_09_14.py`（12 題，含「stages 只改不算變動」
與「未知類型不得倒 raw payload」兩題反向守門）。全套 965 passed。

---

### 2026-09-14（第十二輪）— 取消 admin 直通，模組權限對管理員也生效（**DB v84**）

使用者裁示：「管理者一樣依據有開權限的內容去顯示，沒開的就不顯示，包含模組名稱。
超級管理者預設全開，使用者部分看模組內容去檢核，未開啟的直接不顯示」。
追加裁示：「沒有對應模組 key 也建立就沒有這個問題」。

**核心改動**：`require_any_module()` 從 `role in (superadmin, admin)` 直通改成
**只有 superadmin**；`sidebar.js` 的 `|| ad`／`|| eng`／`|| role !== 'viewer'`
三種非模組放行全部拿掉，收斂成單一 `has(k)`。

#### 為什麼這件事拖到現在才做得成

盤點開發機資料才看清楚真正的代價**不是「admin 看得太多」**：

```
admin / Dioz    19 個模組，缺 17 個（含 營運報表、出納、網路架構規劃書、
admin / kyle    19 個模組，缺 17 個   監控／門禁／閘道器／自動化四類選型導覽）
admin / queena  22 個模組，缺 14 個
admin / sundy   23 個模組，缺 13 個
```

那些模組是 2026-08／09 陸續新增的，**加進了角色樣板但既有帳號從來沒有回填**
——而因為 admin 直通，這件事完全看不出來。直接取消直通會讓四個人隔天上班憑空
少掉一半功能。所以順序是**先回填（DB v84）再取消直通**。

#### DB v84 回填的範圍：等於「直通原本給出去的東西」，不多也不少

| 對象 | 補什麼 | 為什麼是這些 |
|---|---|---|
| admin | ROLE_MODULES.admin ＋ `netplan` ＋四個新稽核 key | 逐項核對側欄，這才是 `|| ad` 實際給得到的範圍 |
| engineer | `case_manage`、`netplan` | 側欄 `|| eng` 給的就是這兩項 |
| 非 viewer | `work_log`、`daily_task` | 側欄 `|| role !== 'viewer'` 給的 |

**刻意不補** `*_guide_edit` 與 `settings`：查證後那兩類走的是
`_require_user(require_superadmin=True, module=...)`，**本來就不放行 admin**，
補了等於憑空放寬權限，不是保留現況。一律只增不減，重跑無副作用。

#### 新建的 5 個模組 key（目錄 35 → 40）

| key | 標籤 | 原本 |
|---|---|---|
| `audit_log` | 歷史紀錄（全系統操作軌跡） | 側欄寫死 `ad`；後端 `role in (superadmin, admin)` |
| `shipping_export_log` | 出貨單歷史紀錄 | 側欄寫死 `ad`；後端 `_require_admin` |
| `module_versions` | 版本紀錄 | 側欄寫死 `ad`；**後端只要求登入** |
| `selection_overview` | 選型資料庫涵蓋度總覽 | 側欄寫死 `ad`；無專屬 API |
| `netplan` | 網路架構規劃書－檢視 | **只有 `netplan_edit` 沒有檢視 key**；讀取端點只要求登入 |

`network_plans.py` 兩支讀取端點補上模組檢查，模組聯集含 `case_manage`
——`js/case-management.js` 也會打這組 API，只認 `netplan` 會把案件頁打死
（MODULE-AUDIT §5 的「擋錯人」失敗模式）。

#### 路上抓到的四件事

1. **`sidebar.js` 有兩份旗標計算，而且已經漂掉了**。`_refreshSession()` 裡抄了一份
   供「模組被改過就即時重建選單」用，但**漏了 `cCon`／`cPay`／`cNetPlan`**——
   session 更新後那三項會停在舊值。已收斂成單一 `computeFlags()`，並補上重建前
   清空 `_navGroups`／`_deniedPages`（原本會把新舊選單接在一起）。
2. **測試帳號一直都不像真實帳號**。`make_user()` 的 `modules` 預設是空陣列，
   而 admin 直通所以完全看不出來——取消直通當下 **31 題變紅**。改成依角色帶樣板
   （要驗「沒模組會被擋」的測試明確傳 `modules=[]`）。這正是 MODULE-AUDIT §5
   記的那句：「測試多半用 admin 帳號，admin 直通」。
3. **`test_module_keys_consistency` 的後端偵測器從來沒有比對過 `require_any_module()`**
   ——2026-09-13 補的 94 處檢查它一個都沒看到，只因為那些 key 剛好也出現在
   `module=`／`_EDIT_MODULE` 等其他形式裡才沒暴露。已補上（含抽成模組常數的寫法）。
4. **寫這批測試時又踩到一次假綠燈**，而且是 MODULE-AUDIT §5 記過的同一種：
   新加的 e2e 斷言「管理員看不到『財務』分組名稱」**永遠會綠**——因為「財務」
   分組目前只有一項，`renderMainNav()` 對單項分組直接渲染成項目名稱，「財務」
   三個字本來就不會出現。改成驗真正的多項分組（廠商與採購／選型資料庫／設備／
   勞務管理）＋單項分組驗項目名稱。**另外按慣例把 bug 種回去實測過**：
   `has()` 加回 `role === 'admin'` 之後那一題確實變紅，還原後又綠。

#### 測試

新增 `test_module_no_admin_bypass_2026_09_14.py`（19 題：五支探針端點各驗
「admin 無模組被擋／admin 有模組放行／superadmin 一律放行」，加上「取消勾選當下
就生效」「403 訊息講得出缺哪個模組」「新 key 在目錄裡勾得到」「案件管理打得開
規劃書 API」）＋ e2e 三題（分組名稱消失／反向控制／superadmin 全開）。
全套 **952 passed**。

---

### 2026-09-14（第十一輪）— 備份保留政策改版＋外部視角檢查＋單據原始版本存檔（**DB v83**）

使用者裁示：「每日備份保存兩個月，超過兩個開始刪除，每週備份超過三個月開始刪除，長久只留月備份，
PDF上傳的相關資料，都需要長久保留，如果有些像是報價單這類單據，產生當下自動備存一個，
如果有編修，需保留原始單據跟編輯紀錄在系統」。同一輪一併施作先前提出的維運評估前三項。

**一句話**：這批東西的共同主題是——原本這三個系統（備份／上傳／更新）的告警**全部是當事人
自己回報自己壞了**。備份沒跑不會叫、磁碟滿不會叫、存檔 PDF 被覆蓋不會叫。補的是外部視角。

#### 1. 備份保留政策（`archive.py`、DB v83）

| 層 | 舊 | 新 | 角色 |
|----|----|----|------|
| 每日備份 | 1825 天（5 年） | **60 天** | 日常誤刪誤改的回溯窗口 |
| 週備份 | 730 天 | **90 天** | 中期粗顆粒窗口 |
| **月備份** | （不存在） | **永久保留** | 長期法遵與歷史查詢 |
| 上傳／PDF 鏡像 | 只增不減 | 同左，**明訂任何情況不清除** | 原始憑據 |
| `pre_update_*` | **永遠不清** | 最新 5 份 | 部署退路 |

- 新增 `月備份/YYYY-MM/`，內容與每日層完全相同（41 表 JSON ＋ 整份 `.db`），共用新抽出的
  `_export_table_json_set()`——日後新增資料表兩邊會一起有，不會只有其中一邊。
- **執行時機是「當月第一次成功的每日備份」**，不是月底也不是 1 號：綁死日期的話那天沒開機
  或備份失敗，整個月就沒有長期備份且沒人發現。
- **月備份有表匯出失敗時不寫 `.done`**，隔天再試。它是永久保留的那一份，內容不完整比每日層
  嚴重得多，寧可晚一天也不要把殘缺的當成這個月的備份。
- **整庫 `.db` 一定要進月備份**：JSON 層刻意不含憑證欄位與內嵌影像（§8.3），長期保留的那一份
  如果只有 JSON，等於長期保留了一份殘缺的資料。
- **為什麼需要 DB v83 而不是只改預設值**：`_backup_retention()` 是 `{**預設, **DB 存的值}`，
  正式機只要曾經呼叫過一次 PATCH 端點，舊數字就固化在 DB 裡，**改預設完全不會生效、
  而且不會有任何錯誤訊息**。已實測驗證：在正式庫副本上跑 migration，儲存值確實被改成新政策。
- PATCH 端點的驗證也跟著改：三種欄位語意不同（天數／`0 = 永久`／份數），不能再一律套「1～3650 天」。

#### 2. 存檔所有權標記（`archive.py`，見 §8.1b）

`_detect_archive_base()` 掃 A–Z 找存檔目錄、`main.py` 無條件啟動備份排程——**任何掛著同一顆
雲端碟的機器都會寫進同一組資料夾**，而且兩個後果都是靜默的：①先跑的那台寫下當日 `.done`，
正式機看到就早退、還順手把警示清掉 ②`_snapshot_sqlite()` 的雲端複製不看 marker，會直接覆蓋
當天的整庫備份（還原優先序第二層）。2026-09-14 起存檔根目錄有 `.motrix_archive_owner`，
不符就整組雲端備份停寫並寄信，**本機快照照做**。刪掉 marker 即可轉移所有權。

#### 3. 備份新鮮度與磁碟空間（`daily_tasks.py`，見 §8.2）

補「備份根本沒跑」與「磁碟快滿」這兩個**完全沒有人會講**的盲區。做法比照 `_check_cert_expiry()`：
掛既有 08:00 排程、`system_settings` 當 guard、一天最多一封、恢復正常清掉 guard。
新通知 key：`backup_stale`／`disk_space_low`（已註冊進 `notification_prefs`，使用者關得掉）。

#### 4. 單據原始版本存檔與編輯紀錄（`pdf_gen.py`／`routers/quotations.py`／前端兩頁）

查證後現況有三個落差，逐一補：

| 落差 | 原本 | 現在 |
|------|------|------|
| **建立當下沒有備存** | 只有簽核／已簽核／結案／解鎖編輯四個事件存 PDF，「原始單據」那一份從來沒被留下來過 | 建立時自動備存 `建立` 事件的 PDF，操作者取自 session（不是 client 送的 `created_by`） |
| **存檔 PDF 會被覆蓋** | 檔名只到「日」，靠 `_2`…`_19` 後綴避開同日同人重複；**第 20 次會靜默覆蓋當天第一份**（迴圈找不到空位時沿用原檔名）——被蓋掉的偏偏是最早、最該留的那份 | 檔名帶到**秒**，不再需要後綴迴圈 |
| **一般編輯沒有紀錄** | `editHistory` 只有解鎖編輯與精算存檔會寫，草稿階段改了幾次、誰改的、改了什麼查不到；既有兩處也只記 who/when/type | 一般編輯也寫，並帶**欄位層級變更摘要**（16 個追蹤欄位＋報價項目數；追蹤清單外的變動補一筆「其他內容」，不會被靜默略過）。**無變更的存檔不寫**——autoSave 跟手動存檔共用同一支端點，每次都寫會讓紀錄被無意義條目淹沒 |

- 版本索引寫進 `data_json.docVersions[]` 而不是只靠 audit_log：`audit_log` 有 730 天保留期，
  **兩年後索引消失、檔案卻還在**，等於有備存卻找不到。存進單據自己身上就跟著單據一起備份。
- 路徑存**相對於 PDF base**，不是絕對路徑——`pdf_base_path` 是 superadmin 可改的設定
  （可能指到公司共用網路碟），存絕對路徑會在改設定那天整批失效。
- 新端點見 §7.21。下載一律回**存檔的那個檔案**，不重新產生——重新產生拿到的是「現在的內容」，
  那正好是這個功能要避免的事。
- 前端：`quotation-form.html` 右側新增「存檔版本」區塊（可下載、檔案不在時標示「檔案已遺失」），
  「修改歷程」補上變更明細。`quotations.html` 與表單頁的 `editTypeLabel()` 都補上 `quote_update`
  ——**表單頁原本是三元運算的預設分支＝「成本精算草稿」，任何未知 type 都會被標成那個**，
  已改成具名對照、未知值顯示原字串。

#### 實測與測試

- **真實 Edge 產生 PDF 實測**：同一張單連續三次存檔，得到三個不同檔名的 277 KB PDF，
  `docVersions` 三筆相對路徑正確。
- **migration 實測**：在正式庫副本上跑，log 印出 `DB migration 83/83`，儲存值確實被改。
- 新增測試檔 5 支（保留政策 9 題／月備份 4 題／所有權 9 題／新鮮度與磁碟 14 題／單據版本 13 題），
  全套 **930 題全過**。
- **踩到一次「測試間共用狀態」**：月備份測試在序列執行下綠、`-n auto` 下紅——`_app` 建的存檔
  目錄是 session 級共用，所有權測試把 `_owner_cache` 設成 `False` 之後，同一個 xdist worker
  裡接著跑的月備份測試全被那個 False 擋掉。已新增 conftest 的 `isolated_archive` fixture
  （每題自己的存檔根目錄＋清空所有權快取），需要寫進存檔目錄的測試都吃它。

---

### 2026-09-14（第十輪）— 跨層稽核測試、回簽附件刪除權限補洞、必要點註記（DB 無異動）

分支 `fix/system-audit-2026-09-14`（自 develop 拉出）。使用者交辦：
「做一個測試的程式確認每個模組串接跟備份、安全邏輯、組織邏輯都正確，
最後在每個必要點做備註，讓未來編寫更為流暢」。

#### 一、新增 `backend/tests/test_system_audit_2026_09_14.py`

跨層稽核，跟著每次 pytest 跑。設計理由與白名單的意義寫在
[維護規則 §跨層一致性稽核](#跨層一致性稽核2026-09-14)，不在這裡重複。
四個區塊：**A 備份涵蓋**、**B 路由守門**、**C 模組串接（刻意不做）**、**D 組織邏輯**。

C 區塊**刻意留空並附說明**：`test_module_keys_consistency_2026_09_13.py` 已經
完整覆蓋模組串接，而且比臨時寫的更周全。寫這支的過程中我一度斷言
`_SUPERADMIN_MODULES` 應該等於 `allModules` 並照著改了 `helpers/auth.py`，
**打破了那支既有測試守著的真正不變量**（該樣板要等於前端的 superadmin 角色樣板，
不是「全部模組」）。改動已 `git checkout` 還原，三題重複的模組測試也移除。
→ **動手改之前先確認有沒有既有測試在守同一件事。**

#### 二、⚠️ 稽核當下掃出來的兩件事

| # | 項目 | 處置 |
|---|------|------|
| 1 | `DELETE /api/shipping-notes/{no}/signed-files/{id}` 與完工單同名端點**只有 `_require_user()`**——任何登入者都能刪掉任何單據的回簽附件，且連實體檔案一起移除、不可復原 | **已修**：補 admin+，與同日動態附件同一標準。兩支的 docstring 都寫了「在此之前是什麼狀態」 |
| 2 | 每日 JSON 匯出只涵蓋 **8/76** 張表 | **未修，已追蹤**：整庫複製有保護到資料，但 §8.3 的最後手段目前重建不出 `users`／`system_settings`／`payslips`／dev-CRM／三種憑證流。用 `xfail(strict=True)` 釘住，補進匯出後會 XPASS 提醒回來拿掉標記 |

第 1 項是**這一輪才補上的安全修正**，比 master 上一個部署包
`20260914_165325_6118944` **晚**——要含這項修正必須重新打包。

#### 三、必要點註記（讓未來編寫更順）

| 位置 | 註記內容 |
|------|---------|
| `db.py` CURRENT_VERSION 上方 | 新增 migration 是**三個動作**，漏掉第③個（版號加一）**完全沒有症狀**：`_run_migrations()` 第一行就 return、log 一行都不印。v82 就是這樣漏的。並補上 v79–v82 的版本歷史 |
| `archive.py` 每日備份 `tables` dict | 為什麼只有 8 張、要補怎麼補、以及稽核測試**直接解析這個 dict 的原始碼**（不是複製清單），所以格式要維持單行一組 |
| `style.css` `.vm-bar` | `display:block` 不能拿掉：多數寫在 `<span>` 上，inline 吃不到寬高會整條消失；flex 容器裡的那幾處剛好被 blockification 救起來，所以症狀是「某幾頁看不到、某幾頁正常」 |
| 稽核測試 `_GUARD_CALL` | 新守門函式請沿用 `require_*`／`_guard_*` 命名；取別的名字會讓那支端點被誤判成「沒有守門」 |
| 兩支回簽附件 DELETE | 修補前的狀態、為什麼標準訂在 admin+ |
| 架構地圖 `tests/` 那行 | 從過期的「45 個測試檔／300+ 題」更新為實際的 **114 個測試檔、874 題** |


#### 四、備份涵蓋度補齊（同日稍晚，接著上面第 2 項做）

上面第 2 項原本標「未修、已追蹤」，同一輪內補完了：**每日 JSON 匯出從 8 張表
變成 41 張**，§8.3 的最後手段現在真的重建得出一套可用的系統。
那支 `xfail(strict=True)` 照約定拿掉——xfail 是追蹤用的，不是永久豁免。

沒進去的 35 張都是「重建它沒有意義」：選型資料庫七類（`sync_*.py` 產生、
git 裡有來源）、登入態與鎖、流水號、操作軌跡與時數、個人排序偏好。
逐項理由在測試檔的 `_NOT_IN_JSON_BACKUP`。

**使用者那一筆刻意逐欄列出、略過所有憑證欄位**：`password_hash` 之類是雜湊，
但 `totp_secret` 與 `totp_recovery_codes` 是**可以直接產生有效驗證碼的金鑰**，
寫進人看得懂的 JSON 等於把兩階段驗證抄一份放在備份資料夾。代價是從 JSON 還原後
所有人要重設密碼、重綁 2FA/Passkey——走到最後手段本來就該這樣做。

**過程中發現的兩個真問題**：

| # | 問題 | 處置 |
|---|------|------|
| 3 | `stock_batches` 沒有 `id` 欄位，`ORDER BY id` 語法正確、表也存在，**只有執行時才炸** | 改 `ORDER BY batch_no`；並新增 `test_every_backup_query_actually_runs`——不比對字串，直接把 41 條 SQL 拿去執行 |
| 4 | 單張表匯出失敗時，`_daily_backup()` 照樣寫 `.done`、照樣送 `backup.daily_ok`，**備份頁面顯示綠燈但那張表每天都是空的** | 改成有失敗就送 `backup.daily_partial` ＋ 留警示（WARN，不寄信），且不清掉既有警示。兩題測試守著，含「全部成功仍要報 ok」的正向控制 |
| 5 | `system_settings` 裡有**真的線上祕密**：`email_notify.smtp_password`、`google_calendar.client_secret` 與 `refresh_token`。原本要 `SELECT *` 匯出，等於把可直接使用的認證素材寫進備份資料夾並鏡像到雲端 | 改用 `json_remove()` 只挖掉這三個路徑，其餘設定照常保留。補 `test_settings_export_has_no_live_secrets`——往 `value_json` 裡面挖一層掃，新增的祕密設定也會被抓到 |
| 6 | 承攬人員欄位裡是**身分證正反面與存摺掃描件**（base64），協力廠商 `data_json`、承攬付款憑據 `snapshot_json` 也各自包了存摺影像。逐表 JSON 每天寫、鏡像雲端、留 30 天＝每天複製一疊身分證掃描件 | 加一條**通則**：`_strip_inline_images()` 遞迴把 `data:image/...` 換成佔位字串（含存成 TEXT 的 JSON 欄位與其中的陣列）。5.5 MB → 1.4 MB。三題測試守著，含不依賴資料內容的單元測試 |

第 3 項正是第 4 項的實例：如果不是順手把查詢真的執行一次，這個壞掉的匯出會
每天靜默失敗、備份頁面全綠，直到有人要還原庫存批次才發現。

**順手做的重構**：`tables` dict 從 `_daily_backup()` 裡抽成模組層級的
`archive._daily_backup_tables()`。稽核測試因此不必再用正規表示式解析函式內的
local dict（改成直接 import 呼叫，不可能解析歪掉），而且測試可以塞一條壞查詢
進去驗證失敗路徑——local 變數沒辦法 monkeypatch。

### 2026-09-14（第九輪）— 視覺化語彙推到其餘模組、報表補數值、動態附件（**DB v82**）

分支 `feature/ui-viz-boards`（接續第八輪），master 未動。待辦收斂在
[`docs/UI-BACKLOG.md`](docs/UI-BACKLOG.md)——使用者邊看邊提，那份是唯一的收斂點。

#### 一、⚠️ **DB v82：動態附件**（唯一需要注意部署的一項）

`_m082_feed_attachments`：`case_updates` 與 `dev_logs` 各加 `files_json`。
使用者裁示 multipart／加浮水印（含當天日期）／刪附件限 admin+／不限張數。

- **選 JSON 欄位不開附件表**：這兩處沒有任何跨紀錄查詢需求，附件永遠隨所屬的
  那一則一起讀、一起刪。開表只多一次 JOIN，換不到查詢能力。
- **API 改 multipart**：一次請求送出，沒有「文字存了、檔案失敗」的半完成狀態。
  只傳檔不打字也可以送——附件本身就是內容。
- **刪附件限 admin+**，刪整則仍是「本人或 admin+」。抽掉附件是**只改證據、
  留下文字**；業務開發那邊更要緊，代填記錄要經管理員審核，審核過還能讓原作者
  換掉附件的話那道審核就沒意義。
- **刪除會清實體檔案**。`uploads/` 被 `_mirror_uploads()` 增量同步進雲端備份而且
  **只增不減**，留孤兒檔案等於永久佔用備份空間。
- 浮水印走既有的 `photos.py::_process_project_photo()`（右下角「上傳者 · 日期時間
  · GPS」），`save_document_files()` 新增 `watermark_by` 開關，import 放在分支裡
  ——那個模組的設計就是「單純存檔不碰浮水印」，module-level import 會讓只存 PDF
  的呼叫端也被迫載入 Pillow。

**踩到並修正**：`CURRENT_VERSION` 忘了跟著 +1。migration 加進 `_MIGRATIONS` 但
`_run_migrations()` 會提早 return——等於送出一支永遠不會執行的 migration。
**實機重啟才發現**（db.py 第 38 行的註解正好寫著這件事）。

順手移除一個會嚇到人的既有行為：案件動態原本「只要選了照片就改存成工作日誌」。
附件跟「這是不是一筆工時記錄」無關，卻悄悄換掉紀錄種類，而且換過去就失去
「標記為重要」與 Google 行事曆同步。

#### 二、視覺化語彙推到其餘模組（純前端）

| 頁面 | 問題 | 處理 |
|------|------|------|
| 保固追蹤 | 5 個統計 + 5 個分頁顯示**完全相同的 5 個數** | 收成一條時效壓力帶，每段自己就是篩選器；補 90 天級距（原本只有 30 天，到期前 30 天才知道等於沒有準備時間） |
| 採購管理 | 4+4 同樣重複，連 `items.filter(...)` 運算式都各寫兩次 | 收成叫料流程帶（待採購→已下單→已到料，有方向所以放箭頭） |
| 網路架構規劃書 | 只有帶數字的分頁，看不出三階段比例 | 規劃流程帶 |
| 設備登載 | 統計是**死的數字**（看得到「已過期 3」點不下去），而正下方的下拉提供的正是同樣四個狀態 | 收成時效壓力帶；級距與保固追蹤對齊——**兩頁看同一批設備，分級不同會讓數字對不起來** |
| 料號主檔 | 見下方 | 分類籤 + 可排序表頭 |
| 客戶／供應商 | 分類只有下拉，看不出分布 | 分類籤（帶件數、0 筆淡化不隱藏、未填獨立一籤） |
| 簽核歷史 | 上方「標籤＋方框」、下方已是籤列——同一頁兩種語言 | 統一成籤列＋內嵌圖示搜尋框 |

**料號主檔查出結構問題**：同一頁有**兩份不同的分類清單**——編輯視窗用後端
`PART_CATEGORIES`（6 個正規類別，各帶料號前綴，驅動自動編號），篩選下拉卻是從
「實際存過的值」推的，所以 `test2` 這種一次性的值會混進去看起來像正式類別。
改成正規類別照主檔順序排並顯示前綴，非正規值標虛線框「未納入主檔」——看得見
才修得掉。另外這頁原本**完全沒有排序**（固定 `id DESC`），表頭改成可排序、
偏好存 `user_list_prefs`。

**客戶頁修掉一個分類軸混用**：「已停用」原本混在「客戶等級」下拉裡，但停用是
`active` 旗標不是等級，選它等於用等級欄位去篩一個完全不同的欄位。

**盤點結果修正了第八輪的估計**：原本估「約 20 頁需要改」是錯的。「同一組數字用
兩個控制項顯示」只集中在少數幾頁；`customers`／`suppliers`／`parts`／`payslips`／
`contractors`／`work-log`／`settlement`／`audit-log`／`online-stats` 等**沒有統計條
也沒有分頁**，是純表格或主檔維護頁；`daily-tasks` 與 `case-stage-board` 本來就在
做視覺化管理。**這套語彙該套的地方已經套完**，剩下的是各自不同的問題。

#### 三、營運報表

- 圖表分頁最上方加「本期財務快照」：當月收支（收入／支出／淨流）與未結部位
  （應收／應付／淨部位）。**用純 HTML 長條不再開 Chart.js 實例**——只有四個數值，
  canvas 換來的只有這一頁註解裡已記載過的尺寸與動畫時序問題。兩組各自縮放：
  收支是流量、應收應付是存量，共用比例尺會讓其中一組永遠貼邊。
- 五張圖各補一張數值明細表。**數字不另外算一份**：每張圖的 `_buildXChart()` 在畫
  圖的同時把自己用的那組數字寫進 `chartTables`，表跟圖必然一致。
- 月份軸下方帶當月金額（比照第五輪在儀表板做的）、案件狀態環圈的圖例帶件數與佔比。

**踩到並修正**：應收一開始接了 `activeOutstandingTotal`（應收報表的期別範圍數字），
畫面上變成快照說「應收 NT$ 0」、同一頁上方 KPI 卡說「未收款 NT$ 1,494,641」。
應收與應付**必須取自同一個來源**——這一頁在「資金水位」早就定義過「淨部位
（應收 − 應付）」就是出納佇列那兩個數字相減，快照沿用同一個定義。

#### 四、案件管理

- 標頭四個數字裡三個在講同一件事（已收 + 未收 = 合約），收斂成「一個主數字 +
  兩條量表」。施工階段從 meta 移進執行進度量表（原本印兩次）。
- 欄寬反映內容：11 個滿寬白框裡，「現場聯絡人」放三個字卻佔 750px。
- 區塊標題與欄位標籤分層；拿掉 `text-transform:uppercase`（對中文沒作用）與
  `.08em` 字距（套中文會把字撐開，第七輪在 `.topbar__title` 踩過同一件事）。
- 合約資訊可從報價單帶入：**單向、只在第一次建立時自動帶一次、只填空白欄位**。
  已存在的案件用「從報價單帶入」按鈕手動帶——自動補寫分辨不了「還沒填」與
  「刻意清空」。
- 修掉關卡矩陣的自相矛盾：`gateTone` 原本把 blocked 一律畫紅，但共通語彙裡
  crit 的定義是「逾期／退回」，「未達成」該是 warn——做到 2/5 階段是進行中不是異常。

#### 五、業務開發

人員篩選（業務與企劃都算「負責」）＋四欄可記憶排序。偏好分兩處存：排序進
`user_list_prefs`（跟著帳號跨裝置），人員篩選進 localStorage（那張表的 schema
沒有放篩選條件的地方，為了記一個下拉去動 DB schema 不划算）。

順手移除狀態 chips——漏斗帶每一段就是狀態篩選器，兩個控制項綁同一個
`filterStatus`。

#### 六、另外修掉的

- **`.vm-bar` 少了 `display:block`**（自己種下的）。這個類別常掛在 `<span>` 上，
  inline 吃不到 width/height；在 flex 容器裡剛好被 blockify 而看起來正常，
  **只在非 flex 容器裡現形**。
- **簽核歷史差點種下一個假綠燈**：一度把 `#ah-scope` 留在隱藏的 `<select>` 上想
  保住既有斷言，測試確實綠——但隱藏元素底下的 option 對**任何人**都不算 visible，
  斷言變成永遠成立。改成 id 放在看得見的籤上，並補反向控制。
- 單據簽章欄文案「簽章蓋印」→「簽章」（12 處；`rollback_snapshots` 不動，
  那是回退用的歷史快照）。

#### 驗收

- 全套後端測試（含新增的 `test_feed_attachments` 8 題、`test_case_gate_matrix` 7 題）
- 開發機實機逐頁看過：跑道、關卡矩陣、報價單生命週期、開發漏斗與溫度、
  五張圖的數值表與財務快照、四頁的壓力帶／籤列、附件上傳與刪除完整流程
- **DB schema 有異動（v82）**，其餘為前端與唯讀端點

---

### 2026-09-14（第八輪）— 三模組視覺化管理排版：提案＋簽核跑道＋案件關卡矩陣已實作（DB 無異動）

使用者交辦：「不用既有框架思考，簽核佇列、案件管理、業務開發，這幾個內容參照視覺化管理，
提供更好的介面排版」，追加「需思考長期案件量多，如何更好的索引使用者找到對應的內容」。

**產出**：[`docs/module-viz-mockup.html`](module-viz-mockup.html)（純參考稿，不接後端、不進導覽）。
Artifact：https://claude.ai/code/artifact/8829340c-0663-40b5-a521-f485082ea6e6

**一、三頁的共同問題：骨架一樣，而且軸選錯了**

簽核佇列／案件管理／業務開發現在都是「左清單＋右詳情」。清單只排「有哪些」，
狀態要點進去才知道——它們在回答「我可以打開什麼」，而不是「現在什麼卡住了」。
逐頁的實測問題：

- **簽核佇列依申請人分組**，但決定我要不要動手的是 `canApprove()`（輪不輪到我）與停留天數，
  兩者都跟申請人無關。`waitingForText()` 已經算得出「等待林佩瑜簽核（第 2/3 層）」，
  這句話卻只出現在右側詳情裡。送審時間只印成 `09/11 14:32`，沒有任何地方顯示積壓天數。
- **案件管理的五個結案關卡散在五個頁籤**。§5.2 的完結案五項前置條件（進度 100%／款項收齊／
  單據簽核完成／精算完結／無額外支出送審中）**本身就是一套現成的視覺化管理指標**，
  但目前只在按下「完結案」被 400 擋下來時才會看到。
- **業務開發的統計掛在 `x-show="!selectedCase"`**——選了案件之後整組統計消失。
  而且狀態是主編碼、接觸溫度只是一條警示列，但同樣「洽談中」，3 天前聯絡過跟 60 天沒動
  該做的事完全不同。

**二、提案的三個版面**

| 模組 | 新骨架 | 主軸 |
|------|--------|------|
| 簽核佇列 | 簽核跑道 | 左「待我簽核」／右「流程中（依卡住的人分組）」；泳道＝停留天數；卡片帶 `tiers` 階梯微圖；詳情改抽屜 |
| 案件管理 | 關卡矩陣 | 一案一列 × 五關卡格；預設排序「最接近結案」；上方到期帶用既有 `stage-board` 的 `dueDate/overdue` |
| 業務開發 | 漏斗＋接觸溫度 | 卡片頂緣溫度條＝距上次接觸天數（紅色門檻即既有 `isStale()`）；統計改常駐；`next_action` 提到卡片正面 |

**三、共通語彙先定死一條規則：品牌紅不參與狀態編碼**

呼應第六輪「狀態徽章不可以吃 `var(--accent)`」那個實際截圖才看到的坑。三頁共用一組
獨立於品牌色的語意色：時效色階（今日綠／2–3 天琥珀／≥4 天紅）與關卡燈號
（達成／進行中／逾期／**不適用**）。「不適用」是空心灰，不是紅——系統對沒有精算／
沒有階段／沒有款項的舊案件本來就視為無需檢查，矩陣不畫出這個語意的話舊案件會滿排紅燈。

**四、長期案件量：三層檢索，以及現在就存在的天花板**

實測目前量：報價單 26（已成案 5／已結案 9）、`dev_cases` 90、`dev_logs` 499、`case_stages` 49。
十年後同節奏是十倍以上。**現有實作是「全量拉回瀏覽器再前端篩選」**：

- `GET /api/dev-cases` **完全沒有 `limit`／`offset`**，永遠回全量（§7.5 已註明 2026-08-03a
  起前端全量篩選）
- `case-management.js::loadCases()` 寫死 `limit=500`，篩選排序分頁全在瀏覽器
- `/api/quotations` 只認 `status／customer／month／deal_tag`，**缺業務員篩選與跨欄關鍵字**，
  排序寫死 `ORDER BY id DESC`
- `/api/quotations/stage-board` 攤平回「案件×階段」全量，無時間範圍參數

幾十筆的時候全量拉回反而最簡單，這不是現在的缺陷；但三個新版面都要跨案件彙總，
等於把這個模式再往上壓一層，所以**伺服器端篩選＋分頁要跟版面一起做**。

檢索分三層：①作業區（看板，只放未結束的東西，量天生有上限）②檢索區（facet 篩選＋
年份摺疊，目標三次點擊收斂到 20 筆內，每個篩選條件都帶連動筆數）③直達（Ctrl+K 跨模組
命令面板，`MQ-YYYYMM-NNN` 前綴可當年月篩選用）。**儲存檢視重用既有 `user_list_prefs`**
（`GET/PUT /api/list-prefs/{list_key}`，現存排序偏好，把篩選條件一起存即可），不必新開表。

**五、落地順序（每階段可獨立上線可回退）**

1. 共通語彙進 `style.css`（只新增 class，畫面零變化）
2. 簽核跑道 — **後端零改動**，所需資料全在前端手上
3. 關卡矩陣 — 進度／單據／精算三格用現有欄位可畫；收款百分比與「額外支出送審中」要補進列表 API
4. 開發漏斗與溫度 — 溫度＝`updatedAt` 距今天數；通路圖標需列表 API 帶 `channels[]`
5. 檢索骨架 — 後端為主（dev-cases 補分頁、quotations 補篩選排序與 facet 筆數）

**六、已實作：階段 1（共通語彙）與階段 2（簽核跑道）**

分支 `feature/ui-viz-boards`，master 未動。

*階段 1 — `frontend/css/style.css` 新增 `.vm-*` 共通語彙（+153 行，0 刪除，畫面零變化）*

燈號／狀態籤／時效文字色／簽核階梯／狀態脊／微進度條／泳道標頭／人員標記／壓力帶，
三頁共用。深色模式不必另外處理——本站深色模式是 body 直接子元素的 invert 濾鏡，
只要用既有 token 就會跟著轉；這一區刻意不寫死非 `#RRGGBB` 的顏色格式、不自己加 filter。

*階段 2 — `frontend/pages/approval-queue.html` 改為簽核跑道（+501／−175）*

- 分組軸由**申請人**換成**輪不輪到我**（`canApprove()`）：左「待我簽核」大卡（核准／退回
  直接放在卡上）、右「流程中」緊湊列（依 `blockerOf()` 算出的「卡在誰身上」分組，
  標頭寫該人最久那件卡幾天）
- 泳道＝停留天數（`requestedAt` 距今；≥4 天紅／2–3 天琥珀／0–1 天綠）。**這個資訊原本
  畫面上完全沒有**，只印了一行 `09/11 14:32`
- 卡片與詳情都畫 `tiers`／`currentTier` 的階梯微圖（`ladderCells()` 把 dot 與 rung 交錯成
  一維陣列，讓 `x-for` 每次迭代只有一個根元素）
- 詳情由常駐右欄改為抽屜。**抽屜刻意放在 `<body>` 直下**——深色模式對 body 直接子元素
  套 filter，有 filter 的元素會變成 `position:fixed` 的 containing block，抽屜留在
  `.aq-layout` 內時深色模式下會整個偏掉（同一個坑 2026-09-13 在側欄踩過）
- `isMobileView` 整個移除：跑道的斷點交給 CSS media query，JS 不再需要知道視窗寬度

*路上修掉的既有缺陷*

1. **轉簽後的重新選取一直是失效的**：`(this.queue||[]).find(it => it.quoteNo === keep)`
   ——`queue` 是「依申請人分組」的陣列，group 身上沒有 `quoteNo`，所以永遠回 `undefined`。
   轉簽其實成功了，但畫面不會重新選回那一筆。改用攤平後的 `flatItems` + `itemKey()`。
   （原始碼註解本來就記著同一類的另一個坑，這支是漏網的第二個。）
2. **`var(--text-main)` 全站從未定義過**（5 處）：CSS 變數解析不到時整條宣告在
   computed-value 階段失效，`color` 會退回繼承值——看起來「差不多對」所以一直沒被發現。
   同頁的 `var(--bg)` 同樣沒定義。一併改成 `--text-primary` / `--white`。
3. **抽屜關閉鈕壓到「退回草稿」**（實作過程中量到：close 鈕 left 1898、動作列 right 1916）。
   改成關閉鈕自己佔一列，不用絕對定位。

*驗收*

在開發機實際跑起來看過（`uvicorn` :666，開發機 DB 內有 4 筆真實待簽核單據）：
壓力帶、空狀態、依「卡在誰身上」分組、類型分布、卡片（含階梯與快速動作鈕）、
詳情抽屜、深色模式都確認過。後端測試 49 綠
（`test_dark_mode_chrome_structure` / `approval_queue_detail` / `approval_delegates`
/ `approval_reassign_history` / `approval_flow_scope` 等）。
**`backend/` 零改動、DB schema 無異動、`/api/approval-queue` 沒有改。**

⚠️ **同時發現第七輪留下的三支紅燈 e2e（與本輪無關，已用 `git stash` 對乾淨工作樹複驗，
一模一樣紅）**：

| 測試 | 失敗原因 |
|------|---------|
| `test_e2e_page_module_guard_2026_09_13::test_page_with_module_is_not_redirected` | 等 `.sidebar .nav__item`，側欄第七輪已退役，10 秒超時 |
| `test_e2e_dark_mode_sidebar_2026_09_13::test_sidebar_paints_dark_in_dark_mode` | 用截圖量側欄像素，沒有側欄可量 |
| `test_e2e_dark_mode_sidebar_2026_09_13::test_probe_catches_the_original_regression` | 同上（負向控制） |

第七輪的驗收只記了 `test_dark_mode_chrome_structure`（全 51 頁的**靜態**掃描）3 綠，
這三支需要 playwright 的 e2e 應該沒跑到，所以紅了整整一輪沒人發現。

**不要直接刪掉它們**——它們守的是真實事故（15 頁側欄在深色模式下變白底、模組守門把有
權限的人也導走），前提從「側欄」換成「上方導覽列」而已，觀測點要跟著搬：像素探針改量
`.topbar` / 主導覽列，選擇器改成上方導覽的項目。這件事本輪沒做，先記在這裡。

未實測：卡片上的「核准」快速動作沒有實際按下去（會真的核准開發機上的單據）；
它走的是既有 `doApprove()` 這條沒有改動的路徑，只是先把 `selected` 指過去。
手機寬度沒有實機看過（瀏覽器視窗縮放在這台機器上沒生效），CSS 只有 5 條宣告。

**七、首頁兩處（使用者交辦）**

- **移除「最近的變動」的直向網格線**（`.h-rails`，官網 v4 的 ASML 式 rails）。官網那裡是
  大片留白的行銷版面，格線用來撐節奏；「最近的變動」是密集清單，格線會在列與列之間
  形成第二套垂直分隔、跟清單欄位對不齊，讀起來是雜訊。全頁只有這一個區塊用過它。
- **問候語只留早安／午安／晚安**：原本是 `夜深了 / 早安 / 午安 / 平安 / 晚安` 五種，
  依使用者指示拿掉「平安」與「夜深了」，也不放激勵語。凌晨 0–5 點歸晚安
  （早安 05–10、午安 11–17、晚安 18–04）。

**八、已實作：階段 3（案件關卡矩陣）**

*後端：判定只有一份*

§5.2 的完結案五項前置條件本身就是一套現成的視覺化管理指標。**刻意不另外寫一份給
矩陣用的判定**——那五個條件是整套系統裡最容易悄悄漂移的東西（③的清單就漏過一次
「完工單」，DB v77 上線時沒跟著加，等於完工單還在簽核中也結得了案），兩份實作遲早
對不上，症狀會是「矩陣說可以結案、按下去被 400 擋掉」這種最難查的。

改成 `_case_close_gates()` 是唯一判定，`_case_close_block_reasons()` 從它的結果推出
reasons。關卡三態 `ok` / `blocked` / `na`，**`na` 不是 `blocked`**——沒有階段／款項／
精算資料的舊案件那幾關是「不適用」，畫成紅燈是錯的；`readyCount` 也只數 `ok`，
否則一件什麼都沒建的空案件會顯示成 5/5 可結案。

⚠️ **唯一的行為差異是 reasons 的排列順序**：舊版是 ①進度 ②收款 ④精算 ⑤額外支出
③單據（③被擠到最後是當初插入④⑤時的副作用），新版照編號排成 ①②③④⑤。內容與
`pending_usernames` 逐字相同——**是用 git HEAD 的舊實作對開發機 26 件案件逐案比對
才發現這個順序差的**，不是看出來的。

新端點 `GET /api/quotations/gate-matrix`（已成案／已結案的五關狀態＋階段到期資訊）。
**必須定義在 `/api/quotations/{quote_no}` 之前**——FastAPI 依定義順序比對，排在後面
會被當成一個叫 `gate-matrix` 的單號而回 404，實作時就是這樣踩到的（既有的
`stage-board`／`last-received-bank-account` 也是同樣理由排在那條之前）。已用測試釘住。

`backend/tests/test_case_gate_matrix_2026_09_14.py` 7 題：路由順序、`na` 不可算成
`ok`、`canClose` 與實際完結案端點結果一致（含反向控制）、收款關卡讀的是
`caseRecord.payment.items`（**不是 `payments`**，路徑寫錯會安靜地變成永遠 `na`）。

*前端：第三種檢視*

清單／看板／**矩陣**。矩陣全寬，切過去時兩欄版面讓開。

- 一案一列 × 五關卡格，欄位順序＝結案檢查順序。五格全過才亮「5/5 可結案」
- **預設排序「最接近結案」**——既有畫面完全給不出、而且最會改變行動順序的資訊
- 到期帶（已逾期／今日／7 天內／8–30 天／無排定），點任一段就篩。**0 件時不上底色**：
  紅底配一個 0 會把視線拉去看一件沒事的事
- 整列不染色（會蓋掉格子裡的燈號），只在最左緣留 3px 狀態脊
- 點一列回到既有五頁籤詳情頁——矩陣是它的上層索引，不是取代它
- 切到矩陣時才抓；**載入失敗也標記成載入過**，否則表格會永遠停在「載入中…」

*實測時發現的兩個既有落差（未修，先記）*

1. **`deal_tag` 有兩個讀取口徑**：清單／矩陣走 `SQL_DEAL_TAG`（欄位優先、再退回
   `data_json.dealTag`），但 `update_deal_tag()` 判斷「已結案只能從已成案進入」讀的是
   `d.get("dealTag")`（只看 data_json）。正常寫入路徑會同步兩邊（§4.2 熱路徑同步），
   但兩者一旦不同步，矩陣會顯示案件為已成案、完結案卻回 400——正是這個畫面最該
   避免的那種矛盾。
2. **開發機有一件已結案案件的進度關卡是 blocked**（`MQ-202607-126`，進度 4/5）。
   結案前置條件是 2026-08-26 才加的，之前結的案子沒有被檢查過。矩陣會把這類歷史
   不一致攤出來——這是它的作用，不是 bug。

*驗收*

- 後端回歸 253 綠（`-k "quotation or case or settle or deal or close or approval or stage"`）
- 新增測試 7 綠
- 開發機實測 14 件已成案／已結案：三種排序、三種篩選、到期帶、點列進詳情都確認過，
  無 console 錯誤
- **DB schema 無異動**

**九、順手改掉的字串**

`docs/system-home-mockup.html` 與 `frontend/index.html` 的 `MOTRIX ERP · 內部營運系統`
依使用者指示改為 `MOTRIX 專案管理系統`（兩處，`index.html` 的 `<title>` 本來就已是這個名稱）。

**階段 4–5（開發漏斗與接觸溫度／檢索骨架）尚未動工。** 另有使用者交辦但先擱置的一項：報價單列表也套跑道語彙、把草稿／送審中／已送出的生命週期分段畫出來（使用者裁示「等這個結束處理，避免多開發遺失」）。

---

### 2026-09-14（第七輪）— 全站改上方分組導覽、儀表板重新定位、案件管理重排（DB 無異動）

分支 `feature/ui-v4-redesign`，**master 未動**（仍停在 `cb387c5`，即正式機版本）。
完整設計決策與現況盤點見 [`UI-REDESIGN-PLAN.md`](UI-REDESIGN-PLAN.md)。

> **要改這批東西的人先看這裡**：[`docs/UI-REDESIGN-PLAN.md` §9 調整索引](docs/UI-REDESIGN-PLAN.md)——列出「想改 X 就去搜尋 Y」的對照表（刻意不寫行號，行號會過期），並標出四個改了就會出事的地方。

#### 一、側欄退役，全站改上方分組導覽（mega-menu）

使用者裁示改採計畫書 §2.1 的**選項 C**（原先裁示 B）。槓桿點是兩個 token：
全站 52 個檔案用 `var(--topbar-h)` 當內容上方偏移、60 處用 `var(--sidebar-w)`
當左側偏移，所以

    --sidebar-w: 220px → 0px      所有 margin-left / left 自動塌掉
    --topbar-h:  60px → 104px     改成「頂欄 60 + 導覽列 44」的總高
    新增 --topbar-bar-h: 60px     頂欄自己的高度（以前由 --topbar-h 兼差）

**56 頁一頁都不用改版面。** 選單內容沿用側欄原本的 `sec()`／`ni()`，
改成同時記錄成結構資料再渲染成上方選單，權限判斷一行都沒重寫。

三個被側欄掩蓋的問題也一起浮出來修掉：

- `.topbar__logo` 原本是 `width: var(--sidebar-w)`（當初為了對齊側欄欄寬），
  歸零後 logo 被壓成 0 寬、跟頁名疊在一起。
- 簽核佇列與每日工作事項是**繞過 `ni()` 的手寫 `<a>`**，不處理會整個從選單消失。
- `.topbar__title` 原樣式是英文字體＋uppercase＋`.14em` 大字距，套在中文頁名上變形。

#### 二、頂欄顯示目前頁名（56 頁一次生效）

31 頁本來就沒有任何頁面標頭，逐頁新建成本高且每頁結構都不同。改成由
`sidebar.js` 在頂欄顯示頁名，取自各頁 `<title>`——**刻意不維護 file → label
對照表**，那種表跟頁面遲早對不起來。三頁的 `<title>` 用半形連字號而非破折號，
`_pageName()` 兩種都吃。

#### 三、儀表板重新定位為「跟我有關的變動」

「最近的變動」從頁面下方的小區塊（8 筆、一行小字）提升為主要區塊，20 筆、
加模組篩選。資料不用改後端：`/api/dashboard/activity-feed` 本來就涵蓋
報價單（`quotation`）、案件進度（`comment`）、業務開發（`dev_log`/`dev_case`），
且已依權限過濾。

移除 KPI 卡 6 張、銷售漏斗、全部圖表（約 27,000 字元）→ 到營運報表看。
**順帶解決一個資料正確性問題**：那 4 條 KPI 走勢線是寫死的陣列
（`[820,950,1100,…]`），跟卡片上的真實數字無關，隨卡片一起移除。

營運報表 `activeTab` 預設從 `targets` 改成 `charts`——年度目標那頁在沒設定
目標時是空狀態，等於一進營運報表看到「尚未設定 2026 年度目標」。

#### 四、案件從「業務」拆成獨立分組

**權限旗標本來就不同群**：`cCM = case_manage || eng || ad`（工程師也有），
而 `cQ`／`cDev` 沒有 `eng`。原本群組條件是 `sec('業務', cDev || cQ || cCM)`，
所以一個沒有任何模組的工程師會看到一個叫「業務」的分組，裡面只有案件管理
與案件執行看板——名叫業務卻沒有半個業務項目。加上這頁的分頁全是成案之後的
執行與財務，拆開才對。

#### 五、案件管理版面重排

- 左欄標頭 6 列 → 3 列。那 4 格統計跟下方頁籤徽章重複（「待精算」甚至是
  **完全相同的運算式**），只有「已逾期階段」是獨有訊息，收進標題列徽章。
- 右欄標頭 4 層 → 3 層。KPI 重新配色：原本已收款與執行進度都吃 `accent`
  （現在是紅）、未收款吃 `danger` 也是紅，**四個數字三個紅等於沒有訊號**；
  而且「未收款 > 0」是正常狀態不是錯誤。改成 合約金額中性／已收款綠／
  未收款琥珀／執行進度完成才轉綠。
- 「收款管理」與標頭重複的三格數字移除，只留標頭沒有的未稅金額與進度條。
- 分頁加數量徽章。**坑**：出貨單／動態／完工單原本是「點分頁才載」，直接綁
  `.length` 會在沒載入時顯示 0，看起來像「這案子沒有出貨單」，比沒有徽章更糟；
  兩個 loader 都是單純 GET 無副作用，改成選案件時一併載入。
- 分頁狀態進 URL（`?tab=`）。**坑**：選案件時那行 `activeTab = 'biz'` 是刻意的
  （2026-09-09 修過的 bug，見原始碼註解），不能拿掉；改成把 URL 的分頁記在
  `_pendingUrlTab`，在那行重設之後才套、且只套第一次。

#### 六、甘特圖：自動檔位 + 匯出 PNG/JPG

`renderGantt()` 的 `view_mode` 寫死 `'Day'`，跨半年的案件會拉出好幾千 px 寬。
改成依跨幅自動選（≤45 天→日、≤180 天→週、其餘→月），可手動覆寫。

匯出 PNG/JPG。兩個關鍵：
1. Frappe Gantt 畫的是 SVG，但顏色字體全部來自外部 CSS——直接序列化會變成
   沒有顏色的黑白線稿，**必須把 computed style 逐一 inline 回克隆節點**。
2. 「圖太長」的根因**不是字形也不是欄寬**，是 `setup_gantt_dates()` 自己把
   日期範圍撐開（週／日檔位前後各加 1 個月、月檔位補到整年再加 1 年）。
   所以壓縮的正解是裁掉空白而不是縮小整張圖（縮小會連日期刻度一起糊掉）。
   實測 5320×616 → 3040×424。左右留白刻意不對稱（左 60／右 240），因為長條的
   `x/width` 不含畫在右側的標籤文字。
   階段標籤前綴日期（「07/16 訂單確認」），縮放後仍讀得出日期。

#### 七、深色模式的品牌紅變粉紅

`hue-rotate` 是線性矩陣近似不是真的色相旋轉，對飽和紅特別不準：`#C8102E`
會被畫成粉紅 `#FF9CBA`。實測後確認**這個機制畫不出飽和深紅**（反解超出色域，
最接近只到 `#B44333` 且對深底僅 3.55:1）。改採深色主題通則：強調色提亮、
色相從洋紅（350°）移到真正的紅（0°）。用前置補償（濾鏡自反，想畫出 X 就把
token 設成 `filter(X)`），範圍跟濾鏡用同一個選擇器，只覆寫會被反轉的那一塊。

#### 八、順手修掉的既有缺陷

- **`--danger #DC2626` 對站內主底色 `#F5F4F0` 只有 4.39:1，本來就沒過 AA**
  （2026-08-28 那輪應是對純白算的，對純白 4.83:1 剛好過）。改 `#B91C1C` → 5.88:1。
- **儀表板圖表自 2026-08-28 起就跟色票脫節**：`initCharts()` 裡的
  success／danger／warning 還是無障礙修正**之前**的舊值。
- **修改密碼寫「至少 6 個字元」但後端 `MIN_PASSWORD_LEN = 8`**，而且前端**驗證
  門檻本身**也是 6，所以填 6 個字會通過前端、被後端擋下。四處一起改成 8。
- **報價單表單右側成本欄在窄視窗被擠出畫面**：`grid-template-columns: 1fr 310px`
  的左欄沒有 `minmax(0,…)`，而左欄裡的明細表有 `min-width:1080px`，所以左欄
  最小就是 1080px。外層 `overflow-x:auto` 也不會縮到內容以下，除非給 `min-width:0`。
- `login.html`／`login-qr-approve.html` 不載入 `css/style.css`，**不可使用 CSS 變數**
  （解析不到會沒有背景色，登入鈕只剩文字）。
- 首頁導覽合併「應收帳款」與「營運報表」——實測是同一頁，中間還隔兩層導向
  （`receivables.html` → `cashier.html` → `reports.html?tab=cashier`）。

#### 驗收

- 後端測試全數執行；`test_dark_mode_chrome_structure` 3 綠
- 伺服器存取紀錄：5,899 個 200、**零 5xx**；4xx 全是權限擋下或 session 失效期間
- `backend/` 只動到 `test_dark_mode_chrome_structure_2026_09_13.py`
  （與 `style.css` 的排除清單同步更新，該檔 docstring 本來就要求）
- **DB schema 無異動**

**未部署正式機**，待使用者確認。

---

### 2026-09-14（第六輪）— 官網風格系統首頁參考稿、介面轉換計畫書、分期比例欄位寬度（DB 無異動）

**一、`docs/system-home-mockup.html`（新增，純參考稿，不接後端、不進 sidebar）**

使用者要求參考公司暫訂官網設計（`v4`）的版面模式，做一份系統首頁畫面參考。
版面骨架與配色都沿用官網 `css/v4.css`（白底企業版型、紅 `#C8102E` 單一強調色、
28×3 紅色段落標記、ASML 式直向網格線 `.rails`、Noto Sans TC ＋ Inter、6px 圓角）。
段落順序對應官網首頁，但三處依系統用途調整：

- **主視覺壓縮成約 160px**（官網是 74vh 的 3D 渦流）。首頁不該把內容擠出第一屏。
- **深灰三欄帶的 01/02/03 換成「已逾期／7 天內／90 天內」**。官網那裡是三個並列的價值
  主張、順序沒有意義；在系統首頁上時效分級才是真資訊，用編號只是裝飾。
- **主視覺右側只講登入者自己**（上次登入／今日在線／我負責的案件／線上同仁）。原本放
  Schema 狀態、最後備份、資料庫版本，那是 `schema-status.html` 的事，擺首頁對使用者
  沒有可行動性——使用者明確要求拿掉前兩項，資料庫版本基於同一理由一併移除。

模組卡與側欄項目依 §6 實際模組寫，數字為示意資料，頁面最上方有標示。單一淺色主題，
logo 以 data URI 內嵌（256×72，約 21KB base64），不依賴外部檔案。
Artifact：https://claude.ai/code/artifact/819fa4c4-c209-4a82-8c6e-d7d3368a9e78

**改版過程（三版，記下來是因為中間那版走錯方向）**：V1 依官網配色 → V2 把整組色票換成
深靛藍主色、紅色只留警示（**我把「配色部分重新設計」理解成整組換色，過度解讀了**）→
V3 依使用者裁示退回官網配色，只拿掉主視覺那片紅色光暈渲染（`.hero__glow` 整個移除，
深色底只留透視網格），並移除底部 CTA 帶。

**二、`docs/UI-REDESIGN-PLAN.md`（新增）— 把 57 頁轉換成官網語彙的計畫書**

使用者要求「列一份計畫書，該怎麼轉換，按照計畫書轉換」。計畫書基於實際量測而非估計：

| 項目 | 實測 |
|------|------|
| 頁面數 | 57（`index.html` ＋ `pages/` 56） |
| 頁內 inline `<style>` | 合計 **425 KB**，最大單頁 `daily-tasks.html` 43 KB |
| 硬寫色碼 | **3,761 處 / 233 種** |
| `var(--…)` 引用 | **5,150 處** |
| 頂欄側欄 | `static/sidebar.js` 814 行統一生成，改一次全站生效 |

關鍵比例是 **`var()` 58% : 硬寫 42%**——換色票只要改 `:root` 一次就帶動 5,150 處，
**貴的是剩下那 3,761 處**加上分散在 57 頁的 425 KB inline CSS。

計畫書列出**四項必須先裁示**的前提（見 §2）、五個可獨立上線可回退的階段（§3）、
風險對策（§4）與每批共用的驗收標準（§6）。其中兩項已有明確結論、不必再問：

- **不可引入 Google Fonts**：參考稿目前用 `fonts.googleapis.com` 載 Noto Sans TC + Inter，
  但 ERP 是內網系統，正式機不保證連外；連不到時瀏覽器**靜默**退回系統字體，整站字重
  字距走樣而且沒有任何錯誤訊息。建議維持 LINE Seed TW_OTF，只借官網的字級字距規則。
- **WCAG 不可退步**：`style.css` 已有三次無障礙修正（`--text-dim` 4.54:1、`--success`
  5.02:1、`--warning` 7.09:1，2026-08-28），新色票上線前一律重算，不可回到 3.x。

附帶發現（未綁進本次轉換）：`frontend/fonts/` 4 個 OTF 共約 21 MB 未轉 woff2；
`frontend/static/fonts/` 是空的殘留目錄。

**三、階段 0 已執行：`frontend/css/style.css` 新增 v4 token 對照層**

`:root` 加入 `--v4-rail`／`--v4-max`／`--v4-gutter`／`--v4-sec`／`--v4-ease`／
`--v4-mark-*`／字級階梯／字距共 16 個 token。**只新增、不改任何既有 token 的值，
且目前沒有任何規則引用它們**，所以畫面零變化（`git diff --numstat` 為 32 新增 0 刪除）。
註解裡標明字級階梯是官網尺度（body 16.5px），**不可拿去套 `.data-table`** ——
ERP 的密集表格維持現行 11～13px。


**三之二、階段 1（＋追加的 1b）已執行——主色由藍改為官網紅**

使用者裁示：§2.1 選 **B（首頁頂欄、內頁側欄）**、§2.3 選 **丙（主色改紅，危險操作改框線）**。

原計畫的「階段 1 只動 `style.css` 與 `sidebar.js`」**在執行時證明行不通**：主色一改成紅，
頁面裡 212 處硬寫的舊主色藍會留在原地，全站一半紅一半藍，比不改更糟，階段 1 就不再是
可獨立上線的狀態。因此追加 **階段 1b：舊主色硬寫值收斂**。完整記錄見
[`UI-REDESIGN-PLAN.md`](UI-REDESIGN-PLAN.md) §7，這裡只摘三個值得記住的坑：

1. **「換一個更深的紅」來區分主色與 danger 是行不通的**——`#9F1239` 實心對 `#C8102E` 實心
   只有 **1.36:1**，並排分不出來。必須換**形狀**：`.btn-primary` 實心／`.btn-reject` 白底
   2px 粗紅框／`.btn-danger` 淺紅底細框，三層階梯。
2. **狀態徽章不可以吃 `var(--accent)`**。`.badge--sent`／`.stat-tag--accent` 原本吃主色，
   主色改紅後「已送出」變紅底紅字、跟「逾期」幾乎一樣——**這是實際截圖才看到的**，
   改用自有青色 `#ECFEFF`／`#0E7490`。狀態序列本來就不該跟品牌主色連動。
3. **分類色票不可以盲掃**。212 處藍色裡有 12 處是 `_GANTT_COLORS`／`_AV_COLORS`／
   `_MOD_COLORS`／拜訪類型／星期色／任務類型色——藍只是分類序列中的一個色相，
   改成紅會跟其他分類撞並且把資料編碼改錯。只收斂 CSS 情境中確定是主色複本的 146 處。

順手修掉的兩個既有缺口：

- **`--danger #DC2626` 對站內主底色 `--white #F5F4F0` 只有 4.39:1，本來就沒過 AA。**
  2026-08-28 那輪的三個修正應是對純白 `#FFF` 算的（`#DC2626` 對純白 4.83:1 剛好過），
  對奶白底就不過。改 `#B91C1C` 後 5.88:1。
- **儀表板圖表自 2026-08-28 起就跟色票脫節**：`initCharts()` 裡的 `success`／`danger`／
  `warning` 還是無障礙修正**之前**的舊值（`#16A34A`／`#DC2626`／`#D97706`）。改成讀 CSS 變數。
  ⚠️ 該處有 `accent + '28'` 拼字串疊透明度的寫法，色票 token 必須維持 `#RRGGBB`，
  不可改寫成 `rgb()`／`oklch()`。

驗收：`test_dark_mode_chrome_structure` 3 綠、UI/e2e 19 綠、無任何 `backend/` 改動、
新增或修改的顏色全數 ≥ 4.5:1。**未驗證**：登入後的內頁沒有逐頁開過（需要帳號），
深色模式也還沒逐頁看——這兩項在階段 2 之前要補。**尚未部署到正式機。**

**四、`frontend/pages/case-management.html` 分期比例欄位被截字**

案件財務的分期收款列，比例輸入框原本寫死 `width:72px`、`padding-right:20px`（留給 %），
`.fi` 本身還有 `padding:6px 10px` 與 1px 框線——內容區只剩 **40px**，`46.67`／`33.33`
這種兩位小數的值直接被截成 `46.6`／`33.3`，Chrome 的 number spinner 再吃掉約 16px。

改法（新增 scoped class `.fi--pct`，不動共用的 `.fi`）：

- 關掉 spinner。`step` 是 0.01，按一次箭頭只動 0.01%，實務上都是直接打字，
  它的唯一作用就是吃掉寬度。
- `width:86px` 後備值，放得下最長的合法值 `100.00`。
- 支援 `field-sizing: content` 的瀏覽器再加一層安全閥：`min-width` **等於**後備寬度、
  `max-width:116px`。**min-width 不能設小**——純 shrink-to-fit 時每列比例不同寬，
  後面「含稅／未稅」欄的左緣就會逐列參差（實測過，很明顯）；設成等於後備寬度後
  一般值每列同寬、欄位對齊，只有真的塞不下時才往外長。

驗證：把 `.fi` 系列 CSS 與整列 flex 結構原樣抽到獨立 HTML，用 `46.67／100.00／33.33／
7.5／0.01` 五個值對照修正前後渲染——修正前 `100.00` 只畫出 `100.`，修正後完整顯示且
五列左緣對齊。**尚未部署到正式機。**

---

### 2026-09-14（第五輪）— 儀表板圖表 x 軸加註每月完整金額（DB 無異動）

使用者要求：「月支出結構跟銷售收入趨勢這兩個月份下方都要顯示這個月的完整金額」。
兩張圖的 y 軸刻度是縮寫的（`200K`／`1.2M`），只能看出量級；卡片右上角的 KPI 也只有
本月一個數字，其餘 11 個月要滑上去看 tooltip 才知道實際金額。

`frontend/index.html` `initCharts()` 新增 `monthTotalPlugin`（Chart.js 4.4.0 inline
plugin，`afterDraw`），兩張圖各自把該月總額陣列傳進 `options.plugins.monthTotal.totals`：

- 月支出結構用後端 `/api/dashboard/expenses` 已經算好的 `total`（跟「本月支出」KPI
  同一個欄位）；銷售收入趨勢用 `monthly[].amount`（跟「本月銷售」KPI 同源）。
  **不要改成四類自己加總**——`contractor`/`equipment`/`material`/`other` 是各自
  round 過才回傳的，加起來會跟 KPI 差 1~2 元，同一張卡片上兩個數字對不起來最難解釋。
- **刻意用 plugin 自己畫，不是把 label 寫成兩行陣列**：多行 tick label 會把刻度寬度
  撐大，Chart.js 的 autoSkip 判定放不下時會整個月份跳過不畫，變成「為了顯示金額反而
  少掉幾個月」。plugin 走 `xs.getPixelForValue(i)` 定位，完全不受 autoSkip 影響。
- 字級用 `measureText` 實測最寬的那個數字決定：10px 放不下退 9px，再放不下整行不畫
  （窄版面寧可只留月份，也不要數字互相疊在一起）。
- 折線圖頭尾兩點就貼在繪圖區邊緣，文字置中會被畫布裁掉（實測最後一個月只畫出
  「263,8」），所以把 x 座標夾在 `xs.left + 半寬` ~ `xs.right - 半寬` 之間。
- 金額不重複寫 `NT$`（卡片副標已經標了單位），並靠 `layout.padding.bottom: 18` 在
  x 軸下方留位置；圖表卡片高度 220px 不變，繪圖區相應少 18px。
- 該月為 0 時顯示 `—`，跟全站 `fmtAmount` 的慣例一致。

深色模式是整頁 `filter: invert(1)` 反轉（§9），canvas 一併被反轉，文字色
`#6B6B6B`（0 值 `#C9C7C1`）反轉後仍在可讀範圍，不需另外處理。

驗證：把 plugin 原封不動抽到獨立 HTML、配模擬資料跑 Chart.js 實際渲染，量過全寬／
2fr／1fr 三種卡片寬度都正確（截圖見當次對話）。**尚未部署到正式機。**

---

### 2026-09-14（第四輪）— 轉簽與簽核歷史（DB 無異動）

使用者要求：「簽核代理人，增加最高權限人可以轉簽簽核佇列的內容，要註明原因跟註記
這筆簽核，並且增加簽核歷史的功能，可以回頭看每個月簽核哪些內容跟搜尋案件、簽核的
內容等等」。

**轉簽 vs 既有的簽核代理人**（`approval-delegates.html`，§7.13）：

| | 簽核代理人 | 轉簽 |
|---|---|---|
| 時機 | 事前、長期 | 事後、單筆 |
| 範圍 | 某人的**全部**簽核 | **這一張** |
| 誰設定 | 本人自助（superadmin 可代設） | 僅 superadmin |
| 典型情境 | 請假兩週 | 這張卡住了 |

兩者都需要：只有代理人的話臨時卡單只能等，只有轉簽的話請假期間每張都要人工轉。

`POST /api/approval-queue/reassign`（`routers/quotations.py`）：

- **原因必填**——轉簽等於把一筆待辦從 A 身上拿走塞給 B，沒有理由就是無從追究的權限
  變更。原因寫進三個地方，看到的是同一句話：該筆簽核人物件的 `reassignReason`、
  單據的 `approval.reassignLog[]`、`audit_log`（`approval.reassign`）。
- **只換當層第一個尚未簽核的人**：已經簽過的不能被換掉（那會讓簽核紀錄失真），後面
  幾層也不動（那是簽核流程設定的事，不是單筆處置）。
- 被轉到的人會收到通知（`_notify`），否則這張會靜靜卡在他的佇列裡。
- `extra_expense`／`case_change` **不支援**：前者的簽核名單存在自己的欄位、後者是單層
  「任一 superadmin 皆可」本來就不會卡在特定人身上。硬做只會多兩條沒人走過的路徑。

`GET /api/approval-history` + `approval-history.html`（側欄「簽核歷史」，與簽核佇列
／簽核代理人同一條線，`quotation` 模組或 admin+）：

- **建在既有的 `audit_log` 上，不另外開表**——簽核動作本來就每一筆都寫了 audit（動作、
  單號、含客戶名的標籤、備註），再開一張表等於同一件事記兩次，兩份紀錄遲早對不起來。
  缺的只是一支查得動的端點。
- 月份籤顯示每個月幾筆，點一下只看那個月（「回頭看每個月簽核哪些內容」）。
- **一個搜尋框打所有東西**：單號、客戶名、退回原因／轉簽原因、簽核人都比對——使用者
  不必先想清楚自己要搜哪一種。
- 轉簽也會進歷史；那是簽核流程上的處置，事後最需要追的就是它。

⚠️ 頁面裡的搜尋框刻意有 `id="ah-q"`：頂欄的全域搜尋也是 `x-model="q"`
（`sidebar.js:137`），`input[x-model="q"]` 這種選擇器會撞在一起——寫這支 e2e 時就先
踩過一次（填到了頂欄那一格，頁面完全沒反應）。

**測試**：`test_approval_reassign_history_2026_09_14.py`（11）／
`test_e2e_approval_reassign_ui_2026_09_14.py`（2）／
`test_e2e_approval_history_2026_09_14.py`（2）。兩支 e2e 都用「把端點打壞／把 `q` 參數
拿掉」驗證過會變紅。

**追查偶發紅燈，結果是產品 bug**：`test_e2e_material_orders_2026_09_11.py` 每次全套
都會紅一支（兩支輪流），單獨跑卻全綠。先把測試的假等待修掉（原本只等「尚無叫料
項目」**出現**就往下走，改成等「安定狀態」：空狀態文字在場**且**載入指示消失，
另補上「叫料清單只能載一次」的斷言），紅燈才顯示出真正的原因——

`case-management.js::selectCase()` 在 `this.selected = data` 之後、`moLoading = true`
之前，夾著 `ensureCaseRecord()` 與 `_seedDefaultStagesIfEmpty()` 兩個 **await**（後者
對全新案件會連打 5 次建立階段的 API）。而分頁列在 `selected` 一設定就渲染出來，使用者
可以立刻點「財務」——**這段空窗期的叫料面板會顯示「尚無叫料項目」**，接著才跳成
「載入中…」。也就是還沒查就先回答「沒有資料」；案件越新、網路越慢，看到的機率越高。

修法兩處：`moLoading` 預設改成 `true`（面板只在 `!moLoading` 時渲染空狀態，額外支出的
`xe.loading` 本來就是 `true`，這裡跟它對齊），以及把叫料那四個旗標的重設搬到**任何
await 之前**（比照 2026-09-09 已經這樣處理過的 `activeTab`／`execSubTab`）。修完同一支
檔案連跑六輪全綠。

⚠️ 這類 bug 的共同形狀：**「載入中」旗標立得比畫面出現的時機晚**。新增任何「載完才
知道有沒有資料」的面板時，旗標的預設值要是 `true`，或至少在第一個 `await` 之前就立
起來。

### 2026-09-14（第三輪）— 簽核佇列看得到送審內容（DB 無異動）

使用者要求：「簽核佇列內的送審資料要詳細，例如夾帶檔案，要顯示哪個案件什麼內容，
如果是檔案可顯示預覽，編修後的結果」。

在此之前佇列每一筆只有單號／客戶／金額／簽核進度——**簽核人要知道這張到底送了什麼，
得自己跑去各模組頁面翻**。新增 `GET /api/approval-queue/detail?type=&id=`，依 type 分流：

| 回傳 | 內容 |
|---|---|
| `case` | 屬於哪個案件（案號／客戶／案名／案件進度） |
| `fields` | 該單據的內容欄位（完工單的執行說明與遺留事項、額外支出的品名金額支出人、變更申請的類型與摘要…） |
| `items` | 明細（完工項目／出貨品項／報價品項／憑證品項） |
| `files` | **夾帶檔案**，含 `kind`（image／pdf／file）讓前端決定內嵌縮圖、開新分頁或下載 |
| `changes` | **編修後的結果**：額外支出變更申請的前後對照、已結案變更申請核准後會套用的內容、報價單最近一次解鎖編修 |

**為什麼不塞進清單**：佇列一次可能上百筆，每筆都去讀 `items_json`／`files_json`／
`payload_json` 會讓開啟簽核佇列變慢，而使用者一次只看一筆。點開才拿。

**檔案預覽**沿用既有的簽章機制（`/api/photo-token` 換 `pt` 再打 `/api/uploads/...`），
圖片直接顯示縮圖、點擊放大，PDF 與其他檔案開新分頁——沒有另外發明一套存取路徑。

**特別處理**：已結案案件變更申請的 `staged_files_json`（半解鎖期間上傳、核准後才會真的
掛進案件的暫存檔案）也要列出來——不然簽核人是在盲簽。

### 2026-09-14（第二輪）— 同時編輯警示（**DB v81**）

使用者要求：「如果有兩個人同時進入報價單、或是修改同一個表格的內容，需跳出警示，
避免兩人同時修改損失一方資料」。

**這是第二道防線，第一道早就有**——存檔時比對 `updated_at`，對不上就 409
「已被其他人更新，請重新載入後再存」（報價單／案件資料／款項／規劃書／業務開發案／
派工單）。那道保證**資料不會被無聲覆蓋**，但使用者要等到按下存檔才知道白做了 20 分鐘。

| 面向 | 作法與取捨 |
|---|---|
| 機制 | `edit_presence` 表＋前端 `edit-presence.js`：進入編輯畫面回報、每 30 秒心跳、有別人在編就在畫面頂端顯示警示條 |
| **不做鎖** | 鎖一定要處理「誰來解鎖」（關分頁、當機、下班沒關），最後都要做強制解鎖，而強制解鎖又回到兩人同時編的原點。這間公司同時線上是個位數，「看得到彼此」已足夠先喊一聲，真的搶著存還有第一道 409 |
| 離開判定 | `last_seen_at` 超過 90 秒沒更新就視為離開——**不依賴關頁面時的通知**（當機／斷網／直接關電腦一定收不到）。`DELETE` 只是讓正常離開更即時 |
| 覆蓋範圍 | 報價單、案件管理（切換案件會自動換）、完工單、網路架構規劃書、請款單 |
| 補齊 | **完工單**原本沒有樂觀鎖（v77 新模組漏掉），這次補上 `expected_updated_at`（選填，不送就維持原行為） |

**2026-09-14 追加：從橫幅升級成主動跳出對話框**——使用者回饋「如果兩個人在同一份
資料內做修改，先跳出提示」。橫幅是被動的：人盯著自己的欄位打字，不會注意到上面多了
一條。改成**進入時**（已有人在編）與**編輯途中**（有人加入）都主動跳一次對話框，
同一個人只跳一次（每 15 秒跳一次會變成噪音，而噪音的下場是使用者學會無視它）；
橫幅留著當持續指示。刻意不擋輸入——這是提示不是鎖，真的兩邊都存還有 409。

心跳從 30 秒改成 **15 秒**（有人同時編時 8 秒）：e2e 實測「編輯途中有人加入」時，
**先進來的那個人最久要等 30 秒才會知道**，而那正是最容易互相覆蓋的情境。每個開著的
編輯頁每分鐘 4 次請求，內網個位數使用者可接受。

**簽核佇列詳情的授權補強（自動安全掃描）**：`/api/approval-queue/detail` 第一版只要求
登入（理由是「跟佇列清單一致」）——那個理由站不住腳：清單只有摘要，詳情回的是完整
內容（明細、附件、變更 payload、匯款帳戶），而 `id` 是可預測的單號或小整數，正是同日
模組權限稽核收掉的那種 IDOR。已補上：**本單簽核人**（含代理人）→ 一般每案規則
（admin+／業務／協作者／`case_manage`）→ 變更申請的提出人本人；另加**金額遮蔽**
（無 `financial_view` 時欄位顯示「（無財務檢視權限）」而不是消失——直接拿掉會讓人
以為這張單沒有金額），本單簽核人例外。存簿封面只接受 `data:image/`（前後端都擋，
混進 `javascript:` 的話簽核人點下去就是在本站原點執行腳本）。

⚠️ **實測才發現的坑**：報價單有**兩條載入路徑**（`?id=` 的 init 內嵌載入、以及
`loadQuote()`），當初只在後者掛 hook，e2e 開兩個瀏覽器才發現開啟編輯根本不會經過那條。
兩條都要掛。

### 2026-09-14 — 業務開發深色模式＋在線成員與在線時數（**DB v79**）

**① 業務開發在深色模式下左側列表是白的**（使用者回報）。根因不是結構，是
`dev-crm.html` 自己寫了 **11 條 `:root[data-theme="dark"]` 手寫深色覆寫**——全站
深色模式是**反轉濾鏡**不是另一套色票，在會被整片反轉的內容上再塗一次深色，反轉後
就變成淺色（寫得越「對」越白）。刪掉那些覆寫即可，淺色底被反轉自然是深色。
守門：`test_dark_mode_chrome_structure_2026_09_13.py` 新增「頁面不得自己寫深色色票」
（已用種回 bug 驗證會紅）＋ e2e 補一題量業務開發列表的像素。

**② 在線成員與在線時數（DB v79，`user_activity_daily`）**——使用者要求
「右上角可顯示在線成員跟數量，並統計每個成員（含管理員、最高管理者）在線上的時間，
這些數據只有最高管理者看得到」。

| 面向 | 作法與取捨 |
|---|---|
| 資料來源 | `sessions.last_active`——**不另做心跳**：那個欄位本來就在更新，心跳會讓每個閒置分頁定時打伺服器 |
| 「在線」定義 | 5 分鐘內有活動。精度上限就是 `last_active` 的節流（main.py `idle_secs > 300`），所以剛登入的人最慢 5 分鐘後才出現 |
| 時數累加 | 在既有節流點累加兩次請求的間隔（`main.py::_record_user_activity`），超過 `_ACTIVITY_GAP_MAX`(600s) 視為中間離開過、只重新起算 |
| 統計口徑 | **活躍時間，不是登入時長**——開著分頁去開會不會被算進去。這句話寫在 API 回傳的 `note` 與頁面上，免得被當成出勤紀錄 |
| 資料表 | 每人每天一列的累加器，不是逐次登入的區間表：session 可同時多個、可被逾時砍掉，區間表要處理重疊與未關閉區間 |
| 權限 | `GET /api/online-users`、`GET /api/user-activity`、`GET /api/user-activity/trail` 皆限 **superadmin**；右上角小工具與 `online-stats.html` 也只給 superadmin |

**③ 逐條操作軌跡（DB v80，`user_request_log`）**——同日追加：「在線時數統計，同步能看
使用者點了什麼看了什麼，逐條紀錄」。在 `auth_middleware` 回應後記錄
（method／path／狀態碼／Referer 解析出的所在頁面），在線時數頁點任一成員即可看他的軌跡。

| 取捨 | 說明 |
|---|---|
| 與 `audit_log` 的分工 | audit_log 記「**改了什麼**」（帶業務語意，稽核用）；這張記「**去過哪裡、點了什麼**」含純檢視的 GET。**不合併**——把 GET 塞進 audit_log 會把它稀釋成流水帳，真正的稽核反而查不動 |
| 所在頁面 | 取 `Referer`，瀏覽器 fetch 本來就會帶，不必在每頁插埋點 |
| 不記什麼 | 頁面自己發的請求（輪詢／紅點／在線名單／ping／附件載入／同時編輯心跳／下拉選單 `*/selectable`／欄位偏好 `list-prefs`／`quotations/case-activity`）；**請求內容一律不記**（body/query 值）——那等於在資料庫裡多存一份業務資料副本，外洩風險與價值不成比例 |
| 收斂 | ①同一支端點 30 秒內連續請求只記一次（自動存檔 1.5 秒防抖會打很多次）②**一次點擊打出的一串不同端點**也只記一次（開一張案件會連帶撈 base＋財務彙總＋材料採購＋額外支出＋更新記錄）——見 2026-09-15 條目 |
| 保留期限 | 90 天，`daily_tasks.py::_prune_request_log()` 每天清。不設上限它會變成整個 DB 最大的一張表 |
| 被擋下的操作 | 照記（狀態碼一併存）——403/404 往往比成功的更需要查 |

> ⚠️ **這是員工行為紀錄**。功能本身是 ERP 管理者的正當需求，但實務上建議讓同仁知道
> 系統有這項紀錄與保留期限（台灣實務上，事先告知比事後解釋省事很多）。

### 2026-09-13（第五輪）— 解鎖複查＋結案規則（使用者裁示，DB 無異動）

- **解鎖維持全開**：使用者裁示「誰都可以改動，但都需要審核」。稽核時一度把
  `case-unlock`/`case-lock` 一起收成擁有者規則，已還原；半解鎖期間的附件上傳改用
  `_guard_case(..., skip_if_semi_unlocked=True)`——**已結案且半解鎖**放行任何人（每筆
  變更都排進待審核），**未結案**的案件沒有那道審核，維持擁有者規則。
- **`GET /api/case-changes/{change_id}` 補守門**：`change_id` 是小整數流水號、回的是整包
  變更內容，先前只要求登入。另放行提出申請本人；核准/駁回維持僅 superadmin。
- **完結案限最高管理者**（使用者裁示）：後端 `update_deal_tag()` 擋下，前端「完結案」
  按鈕與「全部進度完成」自動提示同步只給 superadmin。先前是 admin+，與「已結案只有
  superadmin 能降級」不對稱。
- **完結案前置條件從三項擴充為五項**（使用者裁示「結案前要確認案件進度、精算等這些
  全數完成」）：新增④**成本精算已完結**⑤**額外支出無送審中**，並把**完工單**補進③的
  單據清單——它是 DB v77 才有的模組，當初沒跟著加，等於完工單還在簽核中也結得了案。
  沒有精算／階段／款項資料的舊案件一律視為「無需檢查」。
- **半解鎖期間的變更寄信給最高管理者**：查證後確認**原本就有**
  （`_create_case_change_request()` → `notify_case_change_requested()`，只寄 superadmin），
  這次補上測試釘住——攔在 `_send` 上驗收件人，不是攔上層函式。

### 2026-09-13（第四輪）— 照裁示順序收尾：憑證流金額、單據 IDOR、頁面層守門（DB 無異動）

**解鎖流程複查**（使用者要求）：`test_case_semi_unlock.py` 14 題全綠、核准仍限
superadmin，但抓到三件事——①`GET /api/case-changes/{change_id}` 只要求登入，而
`change_id` 是小整數流水號、回的是整包變更內容（已補守門，另放行提出申請本人）
②解鎖/上鎖的 docstring 還寫著「任何登入使用者皆可觸發」（2026-08-26 使用者裁示），
與收斂後的行為對不上——**這是唯一一處推翻使用者先前明確裁示的改動**，來龍去脈
已寫進 docstring，要還原只要拿掉那一行 `_guard_case()` ③叫料附件放行 `case_manage`、
款項發票附件卻是純擁有者，同一個排隊審核家族一嚴一鬆，已統一。

見 [`MODULE-AUDIT-2026-09-13.md`](MODULE-AUDIT-2026-09-13.md) §3.9～§3.10。

- **巡視補漏**：第一輪只掃了 `quotations.py`，再巡一次發現同一種每案 IDOR 還在
  案件代辦、完工單、出貨單、三種憑證流、網路架構規劃書與**全域搜尋**（最容易被
  忘記的側門：它自己一套查詢，不經過任何 router 的檢查）。守門搬進
  `helpers/quotations.py::guard_case_access()` 供八支 router 共用。
- **憑證流與額外支出的金額可視**：原本卡在「套下去會擋到非管理員的簽核人」。
  解法是把例外寫清楚——**本單簽核人**（含代理人）與**額外支出的填寫人**看得到
  自己那幾筆，其餘人要 `financial_view`。清單用**過濾**而不是整支 403，否則
  非管理員簽核人連簽核佇列都打不開。
- **單據詳情 IDOR**：`GET /{voucher_no}`、PDF 下載、發票附件先前只要求登入，
  而單號可預測。
- **前端頁面層守門**：沿用側欄自己的顯示條件（不另外維護對照表），沒有權限就
  **就地顯示「你沒有這個頁面的權限」**。⚠️ 原本寫成導回首頁，實測發現
  `index.html` 自己也有守門，兩邊一搭是無限迴圈；順手修掉 index 那道漏了
  `dashboard` 模組的問題。

**兩個差點上線的錯配**（由新的守門測試當天抓到）：簽核佇列（模組 `quotation`）
讀不到待簽單據、`inventory` 模組打不開庫存管理頁——都是「擋錯人」，使用者看到
一片 403 而後端測試全綠（測試多半用 admin，admin 直通模組檢查）。

**一個假綠燈**：新寫的守門測試裡混進兩個看不見的退格字元，讓它永遠匹配不到、
永遠綠。修掉後用「把 bug 種回去」實測兩題都會紅、還原後又全綠。


### 2026-09-13（第三輪）— 依裁示收緊權限：IDOR、財務金額、模組後端檢查（DB 無異動）

使用者對稽核報告 §4 的五項待決策裁示：①其餘 IDOR 一起收 ②viewer／engineer 不該
看到金額 ③`/api/sales-orders` 加模組檢查 ④16 個模組逐一補後端檢查 ⑤`cashier` 保留。
細節見 [`MODULE-AUDIT-2026-09-13.md`](MODULE-AUDIT-2026-09-13.md) §3.8。

| 做了什麼 | 內容 |
|---|---|
| 每案 IDOR（28 支） | 新增 `quotations.py::_guard_case()`：案件階段／拜訪／動態／鎖定／協作者／簽回檔案／款項與叫料附件／匯出／三支 PDF。PDF 額外放行**簽核人與其代理人**（不然簽核人看不到單） |
| 財務金額 | 新增 `helpers/auth.py::can_see_financial()`，規則與前端 `canSeeFinancial()` 逐字相同；套在成本精算 GET/PUT、應收應付總覽、銷售訂單 |
| 模組後端檢查 | 新增 `require_any_module()`，依「該 API **所有消費頁面**所屬模組的聯集」套到 15 個 router。聯集是掃前端原始碼算出來的——只認單一模組會把跨模組使用路徑打死（例：`/api/parts` 同時服務料號主檔與案件叫料） |

**⚠️ 一個依實測改掉的決定**：案件「執行面」額外放行 `case_manage` 模組，沒有用純
擁有者規則。理由是開發機 26 張報價單裡 `assigned_user_ids` **有值的是 0 張**——
「指派協作者」實務上沒人在用，純擁有者規則會讓 `engineer` 角色對**全部案件**的存取
權變成 0。金額面（精算、應收應付、發票檔案）仍是純擁有者規則。等指派被落實，把
`allow_module="case_manage"` 拿掉即可收回。

**刻意不套的例外**：快速拓樸圖 preview／pdf 是無狀態繪圖工具（不讀不寫資料表），
擋它只會擋掉畫圖，不會保護到任何資料。

**上線後使用者會察覺的改變**（部署前務必先講）：
1. 只有「儀表板」的帳號（viewer／服務帳號）打不開料號、客戶、每日工作事項、選型導覽
2. 工程師沒有「財務金額可視」就看不到案件成本與毛利（先前後端照回，只有畫面藏起來）
3. 非該案業務／協作者、且沒有「案件管理」模組的人，打不開別人案件的執行進度

### 2026-09-13（第二輪）— 模組權限盤點：七項對接斷點（DB 無異動）

完整報告：**[`MODULE-AUDIT-2026-09-13.md`](MODULE-AUDIT-2026-09-13.md)**（含五項待決策）。
「模組」同時活在權限目錄（`users.html`）、側欄（`sidebar.js`）、後端檢查三個地方，
而**沒有任何東西在確保三邊對得起來**——盤出來七項全部是無聲漂移：

| 修了什麼 | 症狀 |
|---|---|
| 🔴 精算 IDOR | `GET/PUT …/settlement` 與 `finance-summary` 只要求登入，`quote_no` 可列舉 → 任何登入者（含 viewer、automation 服務帳號）可讀、可**覆寫**任何案件的成本精算。改用既有的 `_check_quotation_owner()` |
| 🟠 `reports`／`finance` 形同虛設 | 目錄勾得到、側欄會顯示營運報表，但 11 支報表端點只認 admin+ → 勾了進去整頁 403。新增 `_require_reports_access()`（比照 `cashier.py::_require_view_access`）。**不是放寬**：現有持有者全是 admin+ |
| 🔴 `project_manage` 勾不到 | 後端拿它擋修改叫料，key 卻在 2026-08-26 被移出目錄 → 新帳號永久 403。補回目錄，標籤改為「案件叫料－修改」 |
| 🟠 網路架構規劃書 | 前端 `canEdit` 放行 admin、後端要 superadmin／`netplan_edit`（0 人持有）→ 四個 admin 看得到按鈕、按了必 403。前端改成與後端對齊 |
| 🟡 死 key `sales` | 只在角色樣板與 `_SUPERADMIN_MODULES`，全系統沒有任何地方讀 |
| 🟡 `_SUPERADMIN_MODULES` 不同步 | 缺 `case_manage`／`reports`／`cashier`／`work_log`／`daily_task` 與七個選型導覽 |
| 🟡 `finance` 紅點與 `sales-orders.html` | 後端算了一個月的通知數字前端沒有元素可顯示（依附的側欄項目 2026-08-31 退役）；`sales-orders.html` 當初「退役」只移除側欄連結，活頁面與 API 還在、且已無人維護 → 紅點掛回營運報表，該頁比照 `receivables.html` 改成導向頁 |

**測試**：新增 13 題非 e2e（結構守門 5＋行為 8）。守門那 5 題用 HEAD 內容重跑，
①④⑤確實會紅。行為題的觀測點刻意放在下游（外人被擋後**資料真的沒被改到**），不是只看回傳碼。

### 2026-09-13 — 深色模式 15 頁側欄是白底（DB 無異動）

使用者回報「部分頁面在黑暗模式下，左側的選單列表是白背景」。

**根因**：深色模式是對 `body` 的非 chrome 子元素套 `filter: invert(1) hue-rotate(180deg)`，
排除清單是 **`body > *:not(.topbar):not(.sidebar):not(.sidebar-overlay)`——直接子元素選擇器**。
有 15 頁把 `<aside class="sidebar">` 包進 `<div class="app-shell">`（其餘 36 頁是 body 直下），
排除就對不上：被反轉的是 `.app-shell`，側欄整片跟著翻成白底深字。同一層問題還有第二個
後果沒被發現——容器有了 `filter` 會變成子孫 `position:fixed` 的 containing block，那 15 頁在
深色模式下側欄與頁內 Modal 是以 `.app-shell` 而不是 viewport 定位。

**受影響的 15 頁**：`access-guide`／`automation-guide`／`case-management`／`dev-crm`／
`env-guide`／`gateway-guide`／`inventory`／`monitor-guide`／`netarch-guide`／`parts`／
`procurement`／`reports`／`sales-orders`／`selection-db-overview`／`switch-guide`。

**修法**：把那 15 頁的 `<aside class="sidebar">` 移回 `<body>` 直下（`.app-shell` 全站沒有
任何 CSS，純粹是個版面容器，留著只包 `<main>`），每頁留一行註解寫明為什麼不能再包進去。
**刻意不用「在 CSS 裡再反轉一次抵銷」**：`hue-rotate` 是近似矩陣、來回兩次顏色會偏，而且
那只蓋掉顏色、fixed 定位仍然是壞的。

**測試（兩支互補）**：
- `test_dark_mode_chrome_structure_2026_09_13.py`——靜態掃描全部 51 頁的祖先鏈，非 e2e、
  每次都跑。已驗證把 `reports.html` 改回舊結構它會紅（不是空跑就綠）。
- `test_e2e_dark_mode_sidebar_2026_09_13.py`——**截圖量像素中位數**。必須量像素：`filter`
  是繪製階段的效果，**不會改變 computed style**，側欄被畫成白底時 `getComputedStyle` 讀到
  的仍然是 `rgb(17,17,17)`，斷言 background-color 是典型假綠燈。另含負向控制：在瀏覽器裡
  把側欄重新包回 `.app-shell`，亮度必須從 17 翻到 238，證明探針量得到差異。

### 2026-09-12 — 已收款改收款日期口徑＋完工單模組（**DB v77**）

**① 已收款／未收款分頁改用收款日期口徑**（詳見 §5.12 後續段落）

使用者連兩天回報同一筆（`MQ-202607-045` 交貨款）。**資料與計算都沒錯**——那兩個
分頁原本依**成案月份**分組，案件在 7 月成案，所以 9/1 收的錢被算在 7 月。改成
已收款看 `receivedAt`、未收款看 `expectedReceiptDate`，年／季／月一起改。

⚠️ 實測開發機未收款 7 筆全部沒填預計收款日，照日期分組會讓它們從每個月份都消失
——另外回傳 `undated*` 兩組固定顯示、不併進月份合計。破壞驗證三項全紅。

**② 案件管理新增完工單模組**（詳見 §5.13）

比照出貨單：同構的表、同一套分層簽核與客戶回簽、PDF、匯出紀錄，單號前綴 `CN`。
刻意不同的三件事：不碰庫存（否則同一批序號被扣兩次、完工單永遠簽不掉）、送審
強制要有完工日期（保固起算與工期的依據）、項目有完成狀態且不擋帶缺失送審（擋了
現場只會假裝做完）。內容依台灣工程業完工單慣例撰寫，含施工說明、測試與檢驗結果、
**遺留事項**（PDF 紅框）與雙方簽章。


**③ 同日回饋：完工單太偏向工程**（詳見 §5.13 後續段落）

使用者點出「公司除了工程還有專案、零組件販售、系統設定、網路架構、防火牆等業務」。
預設用語改中性、**11 個標題每張單可自己覆寫**（存 data_json.labels，五組預設可一鍵
套用）、**保固期間可不顯示**（比照報價單「留空就不印」）、PDF 上方第三欄改成案件名稱。
填寫介面依使用者指定改成**獨立頁面**（比照報價單），四個可切換分頁；該頁刻意不加
`x-init="init()"`，並有 e2e 數請求次數釘住「init 只跑一次」。

全套 **742 passed**（非 e2e 711／e2e 31）。

**測試**：新增 23 題（收款口徑 8＋完工單 15），全套 **731 passed** 一次全綠。
同批更新 5 支釘住舊行為的既有測試——它們忠實守著原本的規格，是規格變了，
每一支都寫明為什麼。

### 2026-09-11（晚，第四輪）— 額外支出變更申請＋執行進度同步行事曆＋收款資料異常（**DB v76**）

使用者上線後回報三件事，一次做完。三件事的共同點：**兩件是「資料無聲消失」，
一件是「簽核簽了一個會變的東西」**。

**① 額外支出：已核准後附件上鎖，編輯改走變更申請**（詳見 §5.10 第二輪段落）

- ⚠️ **推翻了同一天稍早（`2026-09-11k`）的決定**：附件原本「已核准後仍可補傳憑證」，
  現在跟金額一起上鎖。理由是核准當下簽核人看到的憑證，跟事後被換掉的不是同一份。
- 使用者明確指定 **「原核准金額不動，核准後才生效」**，所以**不能**用
  「退回草稿再改」那個直覺作法——那會讓人一按編輯、報表數字當場就變。
  改成把提議內容存在 `change_json`，全部簽核層過了才由 `_apply_change()` 覆蓋回本體。
- 佇列上必須是獨立類型 `extra_expense_change`：借用 `extra_expense` 的話，簽核人
  按核准會打到本體的 `/approve`，那支看到 status 已是「已核准」就 409，變更永遠簽不掉。

**② 執行進度勾選 → Google 行事曆＋每日工作事項月曆**（詳見 §5.11）

- 使用者回答「兩邊都要」。完成日事件**另開一欄**（`google_calendar_done_event_id`），
  不能共用到期日那一欄——共用會讓到期提醒被無聲蓋掉。
- 系統內月曆那一列一定要有指派人（否則只有 superadmin 看得到），而且**建立當下就要
  標成已完成**，否則隔天 `_check_overdue_and_notify()` 會對一件已經做完的事寄逾期信。
- 順手把「報價單成案」事件的標題補上案件名稱。

**③ 收款資料異常清單**（詳見 §5.12）

- 使用者回報「9/1 的收款沒算進當月收入」（`MQ-202607-045` 交貨款）。
  **查證後報表計算是對的**——在 db 副本上把那筆補成「已收款＋9/1」，兩支收入撈取
  函式都撈得到。根因是「已收款」勾選與「收款日期」只填了一個。
- 所以**沒有動報表的計算**，改成把這個狀態變成看得見的：案件裡那一列跳提示、
  營運報表最上方一張異常清單、外加獨立端點。
- 刻意不隨期別篩選（那些款項就是不屬於任何月份），也刻意不自動修正
  （錢收到沒有是人的判斷）。
- ⚠️ **開發機 db 副本實跑出 4 筆既有異常（合計 NT$ 1,626,990），其中 `MQ-202608-007` 兩筆合計
  NT$ 1,576,240 目前在任何月份的收入報表上都看不到**。正式機大概率也有，上線後請逐筆補齊。

**④ 追查測試偶發紅時挖出的兩件事**（不是本輪功能造成的，但不修拿不到穩定綠燈）

- **`company-profile-settings.html` 的 `init()` 每次開頁跑兩遍**（真缺陷）。
  `<body x-data="..." x-init="init()">`——Alpine 3 本來就會自動呼叫 `init()`，
  `x-init` 再寫一次就剛好兩遍。第二次 `_loadSysSettings()` 的回應晚一步抵達，
  會把使用者這段期間改過的欄位用伺服器舊值**無聲蓋回去**。跟 2026-09-11 第三輪
  在 `case-management.js` 修掉的同一個坑（當時就記著「全站還有 50 頁是同樣寫法」），
  **這是第二頁**。沿用同一套 `_initDone` 守門，並補
  `test_init_runs_exactly_once`——**數請求次數而不是等競態重現**（拿掉守門是 2 次、
  加上是 1 次，確定性）。
- **斷言打在會自我銷毀的元素上**（測試缺陷）。`saveCloudTarget()` 的驗證訊息有
  `setTimeout(() => cloudMsg = '', 5000)`，測試卻等 10 秒——只要第一次輪詢落在它
  消失之後就永遠等不到。改成把門檻放在不會過期的契約上：「bucket 沒填時儲存請求
  根本不該送出去」。**會自我銷毀的東西沒辦法可靠地斷言**，這條值得記住。

⚠️ **e2e 仍有殘餘偶發**：`test_e2e_t100_unconfirm_2026_09_10.py` 在修完之後的
3 輪 e2e 裡紅過 1 輪（單跑綠），與本輪改動無關、屬既有課題。決定性測試
（非 e2e 681 題）反覆執行皆全綠。


**DB v76**：`case_extra_expenses` 加 `change_status`／`change_json`／`change_approval_json`；
`case_stages` 加 `google_calendar_done_event_id`／`daily_task_id`。純加欄位，可重複執行。
在 db 副本上實跑 v74→v76 驗證過，並順帶確認 v75 的搬移結果與記憶檔記載一致
（7 筆／NT$ 10,490，`MQ-202607-045` 3 筆／NT$ 4,225）。

**測試**：新增 3 支共 28 題（變更申請 10、行事曆同步 10、收款異常 8），
e2e 新增 2 題。**六個破壞驗證全紅**（把修好的行改回壞掉的樣子確認測試會抓到）。
全套 **707 passed**（非 e2e 681／e2e 26），零失敗。
同批修正既有測試 `test_extra_expense_uploads_2026_09_11.py` 兩題——它們釘的是被推翻的舊行為。

### 2026-09-11（白天，第三輪）— 叫料前端 UI ＋涵蓋度總覽補第七類，路上抓到三個真缺陷（DB 無異動）

起點是一次全專案待辦盤點（QUICK.md ＋架構地圖＋週稽核三份合併去重、逐條拿
git／程式碼／部署 log 核對），結論是**六筆待辦其實早就不存在了**，照著做會白工。
清掉那六筆之後，依序做完「可立即動工」的兩項。

**① 叫料（材料訂購）前端 UI**——`routers/material_orders.py` 2026-09-10 修好四個
缺陷、7 題 API 測試全綠，但**全 repo 沒有任何前端呼叫得到它**（`case-management.js`
裡的「叫料出貨」只是階段標籤字串）。新增案件管理「財務」分頁的
`#fin-material-orders` 區塊：品項/數量/單位/單價（小計一律前端算，後端會用
`abs(小計 − 數量×單價) > 0.01` 擋）、待付／部分已付／已付清三態、合計三個 KPI、
已結案或無權限時整區唯讀**並寫明原因**。存檔走專屬端點而非 `saveCase()`——後者會
覆蓋整份 `data_json`，兩邊同時存會互相蓋掉。

**② 涵蓋度總覽補上自動化系統選型導覽**——`selection-db-overview.html::loadAll()`
只撈五組，漏了 2026-08-26 上線的第七類。諷刺的是 `automation-guide.html::applyDeepLink()`
早就寫好接這頁深層連結的程式碼，只差那一組 fetch。**漏掉不會有任何錯誤訊息**，
所以新增第八類時務必同時補這頁。

**③ 打包新增 Step 2.6「後端端點入口檢查」**（`backend/tools/check_endpoint_entrypoints.py`，
只警告不擋）——把「後端上線、前端沒入口」這個已經發生兩次的模式自動化：掃
`backend/routers/*.py` 的 `@router` 路徑，取最後一個非參數片段（`material-orders`、
`purchase-suggestions`…），到 `frontend/` 所有 .html/.js 找這個字串，找不到就列出來。
**刻意只警告**：字串比對本來就會誤判，拿它擋打包只會變成每次都在想辦法繞過。
實測 186 組路由只有 5 組沒有前端呼叫點，噪音很低。其中 `deployed-version` 查證過是
部署工具在用，進 `ALLOWLIST`；另外四組（`backup-retention`／`cloud-backup-target`／
`edge-path`／`pdf-base-path`）**沒查證過是刻意還是也忘了做**，所以放在獨立的
`KNOWN_BASELINE` 只用一行帶過，不跟新冒出來的混在一起——否則每次打包都跳同樣四行，
很快就沒人看了。查清楚後請往上搬進 `ALLOWLIST` 並補理由，或補上前端然後從那裡刪掉。
（已回頭驗證：`material-orders` 在 HEAD 版的 `frontend/` 出現 0 次，這支檢查當時就會抓到它。）

**寫 e2e 的時候抓到的三個真缺陷**（都不是測試寫法問題，是產品的）：

| 缺陷 | 症狀與根因 |
|------|-----------|
| **`init()` 每次開頁跑兩遍**（最嚴重） | `<body x-data="app()" x-init="init()">` ——**Alpine 3 本來就會自動呼叫資料物件的 `init()`**，加上 `x-init` 寫的那一次剛好兩遍。所有 API 發兩次，而且第二次 `selectCase()` 會把第一次已載好的狀態整個重置：使用者在兩次 init 中間按「＋ 新增項目」，那一列會被**默默抹掉**。先前看不出來是因為這頁的子清單全是唯讀的，重載一次看不出差別。已在 `case-management.js::init()` 加 `_initDone` 進入守門。**全站共 50 個頁面有同樣的 `x-init="init()"` 寫法**（其中 14 個是 `x-data="app()"`），本輪只修案件管理這一頁，其餘屬獨立課題。跟 `34e0ce1` 那個「`login.html` 有兩個 `init()` 互相覆蓋」是同一個家族的坑，這已經是第二次 |
| 載入回應覆蓋使用者的編輯 | `loadMaterialOrders()` 的回應抵達時直接 `this.materialOrders = [...]`，在途中新增的列會被伺服器版本蓋掉。修法比照 `reports.js` 的 `loadExpenses()` 競態（§12 2026-09-10「更晚」）：發請求當下記住 quote_no，回應到了先比對，並在 `moDirty` 為真時完全不覆蓋 |
| 空狀態會閃一下 | 分頁列在 `selected` 一設好就出現，但 `loadMaterialOrders()` 在 `selectCase()` 更後面才發出去，中間那段空窗會先閃「尚無叫料項目」再跳「載入中…」。`moLoading` 提前到選案當下就立起來 |

另修 `case-management.html` 精算額外支出明細呼叫了一個**不存在的 `fmt()`**（全 js 只有
`fmtFeedTime` 與一個區域變數），只要某筆額外支出有填數量，那一行就丟 ReferenceError；
改用元件實際有的 `caseSettleFmt()`。

**測試**：新增 `test_e2e_material_orders_2026_09_11.py`（2 題）與
`test_e2e_selection_overview_2026_09_11.py`（1 題）。前者含一條**確定性**的雙重初始化
回歸斷言——數「案件清單 API 被呼叫幾次」必須是 1，比等競態重現穩定（還原守門後實測
必紅）；後者比對六個區塊標題，還原修改後實測必紅。連跑 9 輪不flaky，且因為少發一半
API，單檔時間從 45 秒降到 13 秒。全套非 e2e **609 passed**／e2e **12 passed**。

**本輪更正的六筆文件落差**：①§11「營運報表月/季/年不同步、尚未查證」其實當天稍晚就修好
②週稽核「套用 `20260910_145349_35938fd`」早被後續 8 個部署包涵蓋 ③Passkey 步驟書寫正式機
`34e0ce1`、實際是 `06e1409` ④`pytest-current` 損壞連結已不存在 ⑤`routers/projects.py`
早在 `6bd04ca` 就刪了 ⑥涵蓋度總覽「是否含自動化、尚未查證」已查證並補上。

### 2026-09-11（白天，第二輪）— `webauthn_credentials.rp_id`（**DB v74**）

讓「RP ID 變更導致 Passkey 全滅」從一件**查不出、說不清、看不見**的事，變成可見、可通知、可清理。
行為細節見 §3.3c 的表；這裡只記三個判斷：

- **對外錯誤訊息刻意不講真話**：`login/begin` 在「憑證全部失效」時回的必須跟「帳號不存在」一模一樣，
  否則等於確認該帳號存在且註冊過 Passkey——`0527524` 修掉的用戶枚舉漏洞就是這種洩漏。真相寫進
  server.log，並在**登入後**的裝置清單講清楚（那裡沒有枚舉風險）。有一題專門釘住「兩種情境的回應完全相同」
- **`rp_id=''` 的取捨刻意不對稱**：登入路徑當成相符（不確定時不要把人鎖在門外）、失效統計則排除
  （不要謊報「已失效、無法復原」，那會讓人去刪掉可能還能用的憑證）。已用測試釘住，免得日後被當 bug 修掉
- **❌ 放棄「新舊網域並行過渡期」**：查證後發現前提不成立——切到 LE 之後憑證只涵蓋 `erp.miactw.com`，
  而 uvicorn 只能載一張憑證，**舊網址在切換的同一瞬間就沒有有效憑證**，Passkey 在那個 origin 本來就不會動。
  詳見 §3.3c

**測試 18 題**（含 migration 升級路徑：回填、未設定時留空、可重複執行、不覆蓋已有值），
並逐一破壞產品邏輯驗證真的抓得到（不過濾失效憑證／錯誤訊息洩漏帳號存在／把舊資料誤判成失效／
清單不標 stale／統計退回全表 COUNT，**五個破壞全部變紅**）。全套非 e2e **609 passed**，
Passkey e2e（CDP 虛擬認證器走完註冊＋登入）**2 passed**。

> 順帶修掉 `_startup_catchup()` 第一次執行分支漏掉的 `_check_range_task_deadline()`——它跟同批
> 其他檢查一樣是看未來的，不會因補跑歷史而洗版，單純是當初漏了；全新環境第一次啟動當天的區間
> 工作事項到期提醒會被靜默跳過。另把 §2／§13 記載的 `CURRENT_VERSION` 由 68 更正為 74。

### 2026-09-11（白天）— 憑證到期告警＋放棄 Cloudflare 方案（DB 無異動）

**決策：Cloudflare 兩條路都排除**，理由見 §3.3c 的「已排除的替代方案」表。一句話版本：
Origin CA 的根不被瀏覽器信任、解決不了原問題；Tunnel 的獨門好處只有「從外面能用」，
而那正是使用者規劃中的 VPN 要解的事，代價卻多了四項（含**對外斷線時連辦公室內也用不了**）。

**新增 `routers/daily_tasks.py::_check_cert_expiry()`——憑證到期在此之前完全沒有監控。**

- **門檻依「憑證總效期」自動切換**，不必有人在換憑證來源時記得回來改常數：
  總效期 > 180 天視為手動簽發（mkcert 822 天）→ **60/21/7 天**；否則視為 ACME（LE 90 天）→ **21/7/1 天**。
  ⚠️ 這一點是刻意的：Posh-ACME 在剩 30 天才續期，**若對 LE 沿用 60 天門檻，每張憑證都會在一切正常時誤報一次**，而狼來了的告警等於沒有告警
- 過期後每 7 天重寄（沿用 `_check_case_project_timeline_deadline()` 的分桶慣例）
- **讀檔而不是對自己開 TLS 連線**：`start.bat` 載入的就是 `certs\cert.pem`，讀檔沒有網路依賴、不受服務當下狀態影響，測試也不必真的起一個 TLS server
- guard key 帶 fingerprint，換憑證自動重置；每次都收斂到最多 1 列（理由同 `_prune_case_project_guard_keys`，本專案已為「只寫不刪」付過 `module_versions` 626,725 列／270MB 的代價）
- 信裡**依簽發者給不同的修復指示**（mkcert → 重跑 `https_setup.ps1`；LE → 查續期排程與 log）：這封信會在好幾百天後才第一次寄出，那時沒有人會記得 mkcert 或 Posh-ACME 是什麼
- `cert_expiry` 已加進 `notification_prefs.py::EVENT_GROUPS`（漏了會被 `test_notification_prefs_coverage.py` 擋下——那正是 `case_project_overdue` 當初踩的坑）
- `cryptography` 補進 `requirements.txt` 與打包守門的 `$depCheck`：先前只是 `webauthn` 的傳遞依賴，既然自己 import 了就該明寫

**實測**：拿正式機真的那張憑證餵進去 → 822 天／issuer `mkcert MOTRIX\Motrix@Motrix`／判定為手動簽發 →
**第一次告警落在 2028-10-11**（到期前 60 天）。開發機沒有 `certs/` → 靜默、不報錯。

**測試 16 題**，並逐一破壞產品邏輯驗證測試真的抓得到（門檻不切換／過期不分桶／guard key 去掉
fingerprint／遠期不收斂，四個破壞全部變紅）。全套非 e2e **591 passed**。

> ⚠️ **寫測試時自己踩到、值得記住的坑**：一開始用「重簽一張憑證」來模擬時間經過，
> 但重簽會換掉 fingerprint，而 fingerprint 正是 guard key 的一部分——`test_expired_next_week_resends`
> 因此會在 7 天分桶邏輯壞掉的情況下照樣變綠。**跟 `4ffe190` 是同一種錯**（斷言沒守住它該守的東西）。
> 改成用 `fake_cert` fixture 直接控制 `_read_serving_cert()` 的回傳值，把「同一張憑證變舊」
> 與「換了一張新憑證」分成兩個可獨立控制的維度。

### 2026-09-11（凌晨 01:05）— Let's Encrypt 公開憑證方案（`bbdd166`／`428e511`，規劃完成**尚未執行**，DB 無異動）

起因是使用者問「能否讓瀏覽器點一下 PASSKEY 就自動下載並執行憑證安裝，Windows、macOS 都可以」。
**答案是不行**——任何網頁都無法把憑證寫進系統信任存放區，這是 Windows 與 macOS 共同的安全邊界，
不是缺功能（可以的話，任何網站都能讓你信任它偽造的憑證）。能做到最接近的就是
`setup_passkey_client.ps1` 已經在做的「下載 → 執行 → 輸入管理員密碼」。

**但這個需求有另一個解法：把「需要裝 CA」整件事消滅掉。** 實測 `miactw.com` 的 DNS 在 Cloudflare
（`maria`／`cameron.ns.cloudflare.com`）、`erp.miactw.com` 目前是 NXDOMAIN、DNS-01 驗證不需要正式機
對外開放任何連接埠——三個前提都成立，所以可以簽一張全世界瀏覽器本來就信任的憑證。

- **新增 `LETSENCRYPT-PUBLIC-CERT-PLAN.md`**：7 個步驟、每一步的驗證方式、切換代價、長期要盯的三件事
- **新增 `backend/tools/letsencrypt_renew.ps1`**（228 行）。四個刻意的設計決定：
  ①比對「服務中的憑證」與「Posh-ACME 手上的憑證」，有變動才動作
  ②用 **fullchain** 而非單張葉憑證（少了中繼憑證有些客戶端會驗不過）
  ③**不呼叫 `restart.bat`**——它前景跑 uvicorn 且以 `pause` 結尾，排程會永遠不返回；改沿用
  `apply_update.ps1` 的「只停服、讓 autostart crash-restart 迴圈接手」
  ④`-InstallSchedule` 會檢查 `POSHACME_HOME` 是否為機器層級變數：Posh-ACME 預設存在
  `%LOCALAPPDATA%`，排程以 SYSTEM 跑會看不到個人帳號簽的憑證，變成**「每天都成功執行但什麼都沒做」
  直到 90 天後全站 HTTPS 一起壞掉**
- 重啟後刻意對 `https://erp.miactw.com:666/api/ping` 而非 localhost 驗一次——要驗的正是
  「憑證對這個名字有效且簽發者公開受信任」
- **`PASSKEY-CA-ROLLOUT.md` 進度表更新為實況**：先前停在「第 2、3 步完成，卡在第 4 步」，
  實際上 4～7、9 步都做完了。第 5 步改標「正式機＋開發機」（其他同事的電腦尚未處理），
  第 8 步系統網址標**待確認**（沒有依據說它改過，這一步最容易被忘記）

**尚未執行，決策點見 §11 那一列與 §3.3c。** DNS 記錄與正式機上的動作都需要人操作。

### 2026-09-11（深夜接續）— Passkey 從「上線但從來沒能用」到真的能用（`a1f56e9`→`4ffe190`→`34e0ce1`，DB 無異動）

四個根因，**每一個都足以讓整條路走不通**，詳細列表與共同教訓見 **§3.3c**。這裡只記過程中真正該記住的事：

- **`a1f56e9` base64url**：`base64.b64decode()` 解不了前端送的去 padding base64url，每次丟
  `Incorrect padding`，被上層 `except Exception` 收斂成籠統的「認證器驗證失敗」，畫面完全看不出原因
  ——**是靠正式機 `server.log` 才定位到的**。順帶統一前端編碼器：`login.html` 用標準 base64、
  `change-password.html` 用 base64url，同一個協定兩個頁面兩種格式，正是本專案一再吃虧的漂移模式
- **`4ffe190` credential 缺 `type`**：⚠️ **這一輪的真正教訓在測試**——上一輪的端點測試只斷言
  「錯誤不是 padding」，太寬鬆；padding 修好之後測試照樣綠，使用者卻還是拿到「認證器驗證失敗」，
  等於測試沒守住它該守的東西，還讓人以為修完了。改成把已知的結構性錯誤**全部列為不允許**
  （padding／unexpected type／missing required／not a json object／unable to decode credential），
  只有「真的走到密碼學驗證才失敗」才算通過
- **`34e0ce1` 用 CDP 虛擬認證器把整條路自動走完**，當場抓到兩個純人工往返碰不到的 bug——
  四輪來回都停在註冊，**沒有人真的走到「登入頁按 Passkey」那一步**。新增
  `backend/tests/test_e2e_passkey_2026_09_11.py`。測試設計上踩到的坑記在該檔檔頭：
  ①測 `excludeCredentials` 不能靠「第二張要註冊成功」，它本來就該失敗
  ②Passkey 登入必須在**同一個 browser context** 裡做（虛擬認證器的憑證綁在 context 上）
  ③uvicorn 用 port 0 抽到 1723（PPTP）時 Chrome 回 `ERR_UNSAFE_PORT`，改成自己在 20000 以上挑
  ④完成訊號改看 ok/err 出現而非 busy 變 false——點擊沒生效時 busy 從頭到尾是 false，
  **「什麼都沒發生」會被判成「順利完成」**

### 2026-09-10（最深夜 23:38）— 打包直譯器守門改成「先自己找對的那一支」（`35ec7a8`／`0da86bf`，DB 無異動）

同日稍早（見下方 2026-09-10「後續修復」條目）加的直譯器守門**擋是對的，但只解析 PATH 上的第一支
python，缺套件就直接 Fail**。問題是這台機器有 4 支 Python，「第一支」是誰完全取決於呼叫端環境：
我自己的 shell 解析到依賴齊全的 3.11.15 所以一直能跑，**使用者自己的 PowerShell 解析到
WindowsApps 那支 stub 就直接 Fail**——同一支腳本一個能跑一個不能，而使用者除了手動改 PATH 沒別的辦法。

改成把候選逐一試過去（`python`／`python3` 的所有 PATH 命中，加上專案內常見 venv 位置），挑第一支
依賴齊全的來用；全都不合格才 Fail，**並列出每一支各缺什麼**。仍然印出實際選中的路徑——守門的原意
是可追溯，不是為了擋人。

⚠️ **`0da86bf`：新加的探測迴圈立刻踩到 PS 5.1 原生執行檔 stderr 地雷（本專案第 5 次）**。
腳本開頭是 `$ErrorActionPreference = "Stop"`，迴圈用 `2>&1` 收 python 的 ImportError 來判斷缺哪個套件
——但在 `Stop` 之下，原生執行檔只要往 stderr 輸出任何東西就會被 promote 成終止型 `NativeCommandError`，
**即使那正是我們預期要發生的事**。結果是選對了直譯器卻在下一支候選就整個腳本中止。
前四次分別是 pip install／tar／db 備份／mkcert，記憶檔與本文件都有記載，**寫這段修正時卻沒套用**。
呼叫原生執行檔的迴圈前後要切 `Continue` 再還原。

### 2026-09-10（最終）— 慢請求記錄（DB 無異動）

**先更正**：前一輪說「存報價單可能卡 30 秒」是 commit 後那幾筆 notification／audit 寫入造成的
——**錯的**。逐段計時（另一條連線握鎖 6 秒）：`_audit` 0.01s、`notify_module_activity` 0.03s、
**主 INSERT/commit 6.17s**。卡的是主寫入，SQLite 單一寫入者的本質，移走那幾筆沒有幫助。

查完所有可能長時間佔鎖的地方——`reset_demo_db()` 的 VACUUM 只動 demo 獨立檔案、另一個 VACUUM
在 migration、三處 `BEGIN IMMEDIATE` 都是刻意短交易——**正式路徑沒有長時間佔鎖的東西**，
所以沒有對寫入路徑動刀。

改做**可觀測性**：`main.py::slow_request_log`，超過門檻（預設 5s，環境變數
`MOTRIX_SLOW_REQUEST_SECONDS` 可調）的 `/api/*` 請求寫一行 `SLOW REQUEST`，不改變行為。
**日後有人回報「存報價單偶爾要等很久」，先看 `server.log` 的 `SLOW REQUEST`**——
有紀錄就是真的撞到鎖，沒有就往別的方向查。測試 4 題（含端到端持鎖情境）。

### 2026-09-10（追到底）— flaky e2e 完整真相（DB 無異動）

**方法**：先加強測試自己的診斷再說，不要繼續猜。原 dump 只有 approver 那一頁的資訊，
加上建立端 page1 的完整 API 往來／對話框／「送出但沒收到回應」的請求、資料庫實際內容
（哪幾張單、tiers、`quote_seq`）、Alpine 狀態、現有按鈕、全頁截圖後，**第 1～2 輪就抓到**
（先前 9 輪抓不到）。

**真相有兩半**

① **前端守門有漏**：取號還沒回來就按送審 → POST 送空號 → 後端派 001 → 取號才回來拿到
002，而 `q.quoteNo` 仍是空的（POST 回應未到），守門 `!this.q.quoteNo` 放行 → 畫面變 002。
修法：`apiSave()` 開頭設 `_quoteNoFrozen`，守門改看**「有沒有開始存檔」**。

② **鎖等待是真的**（⚠️ 我先前說原作者方向錯了，那句才是錯的，已更正）：
`db.py:119` 是 `sqlite3.connect(path, timeout=30)`——寫入鎖被佔住時**最多等 30 秒**。
建單 commit 後還要寫 notification／audit_log／module activity，撞上背景排程就卡滿一輪。
測試時限放寬到 45 秒並寫明理由；等待條件改成等 `isNewRecord` 翻 false。

**結果**：10 輪全綠（先前最差 6/12 失敗）。

**⚠️ 正式環境隱憂（未動）**：那個 30 秒 busy timeout 表示真人存檔撞上備份／排程寫入時，
畫面可能卡最多 30 秒。正式機只啟動一次、機率低很多，但不是零。

### 2026-09-10（收尾）— `???` 假單號＋後端單號格式守門（DB 無異動）

`copyToNew()` 在取不到號時會造 `MQ-YYYYMM-???` 當單號。**它不會撞號**（先前誤判）——
那個字串跟任何既有單號都不衝突，INSERT 會成功，接著 `int('???')` 炸成未捕捉的
`ValueError` → 500。使用者只看到「儲存失敗」，複製的內容在載入時就已從 sessionStorage
清掉，重新整理再也回不來。

**修法三層**：①**後端守門**（`_QUOTE_NO_RE = ^MQ-\d{6}-\d{3}$`，格式不合就改由後端派號
——不管哪個 client 送什麼都擋得住）②序號解析 try/except 兜底③前端 `copyToNew()` 改用
`?copy=1`、不再造假號；新增模式與無號複製共用 `_peekQuoteNo()`。

**⚠️ 殘留未解**：`test_login_create_submit_approve_smoke` 仍約 2/16 偶發逾時。
`a619206` 修好 peek 競態後曾連 6 輪全綠，e2e 增加到 5 檔 8 題後又出現；
**9 輪抓不到 dump，無法確認是同一根因或純負載**，約略回到開工前的 1/18 基準。

### 2026-09-10（最後）— 報價單單號競態＋送審孤兒單（DB 無異動）

長年 flaky 的 e2e（註解原本寫「根因還沒有抓到」）**根因找到了**：
`quotation-form.html` 載入時非同步打 `/api/next-quote-no`，**那個回應可能在使用者按下
存檔／送審之後才回來**，直接指派就把存檔回應剛回填的真正單號蓋成新 peek 到的下一號
——畫面顯示 `MQ-YYYYMM-002`、資料庫其實只有 001，簽核的人照畫面開就開到不存在的單。
跟同日 `reports.js` 修的是同一類「晚到的非同步回應蓋掉新狀態」。

**修三項**

1. **peek 競態**：只有「還沒有號碼、且還是沒存過的新單」才採用 peek 結果。
2. **前端不再自己猜號**：`saveDraft()` 原本 quoteNo 為空時**寫死** `MQ-{ym}-001`
   當暫用號送出（那個值幾乎一定被用掉了）。改成送空值交給後端派、存檔回應一律回填；
   取號逾時 3→10 秒；拿不到號畫面顯示「（儲存後自動編號）」。
3. **送審失敗留下孤兒單**：`create_quotation` 先 INSERT+commit 才建簽核層級，
   層級解析失敗拋 400 時那筆 `待審核`、無層級的單已經留著——清單看得到、永遠簽不掉，
   使用者重按又多一張。改成補償性刪除，並**依實際留存的報價單重算 `quote_seq`**
   （不是減一，併發下會踩到別人剛拿的號）。

**驗證**：可控重現腳本 6 次中 2 次異常 → 8 次 0 次；完整 e2e 6 輪中 4 輪失敗 → 6 輪全綠。

**⚠️ 教訓**：本專案同一天在兩個不同模組踩到同一類競態（`reports.js` 的快取鍵、
本次的單號 peek）。**看到 `await` 之後直接指派 `this.xxx = <回應內容>` 就要問一句
「這個回應晚到的話會不會蓋掉更新的狀態」**。

### 2026-09-10（稽核後續）— 三項待決策處理完畢（DB 無異動）

1. **刪 `/api/cashier/summary`**（僅自身測試引用，是另兩支的合併版）。
2. **接上 `/api/company/search`**：客戶／供應商／承攬商三頁新增「公司名稱查詢」。
   查詢邏輯抽到 **`frontend/static/gov-lookup.js`** 共用（三頁的統編查詢已經各有一份
   幾乎相同的實作，再加三份必然漂移）；**帶入表單各頁欄位名不同**
   （customers/suppliers 是 `taxId`、vendor-contractors 是 `tax_id`），所以帶入由各頁
   自己的 `govApply()` 處理。
3. **刪 `backend/routers/projects.py`**（592 行死碼）。`projects`/`project_logs` 資料表
   保留不動。`RETIRED_ROUTERS` 白名單清空但機制留著。

**⚠️ e2e 測試檔變多會互相排擠**：新的 e2e 若用 `parametrize`，每個 param 都會各起一台
uvicorn 加一個 chromium。實測既有 `test_login_create_submit_approve_smoke` 的偶發失敗率
因此從 1/18 升到 2/4，把三個 param 併進同一個 browser 後回到 1/4。**新增 e2e 時盡量共用
browser／live_server。**

**⚠️ 既有 flaky 測試的根因已定位（未修）**：診斷 dump 顯示 approver 開的是
`MQ-202609-002`、簽核流程卻建在 `MQ-202609-001`——**表單顯示的單號 ≠ 實際存檔的單號**。
`quotation-form.html` 載入時打 `/api/next-quote-no` 只給 3 秒逾時就讓 `q.quoteNo` 留空，
`saveDraft()` 遇到空值會寫死 `MQ-{ym}-001` 送出，後端撞號改派下一號再回填。
要修需決定改哪一端（前端逾時／不要寫死 001／改成後端單一權威派號）。

### 2026-09-10（稽核）— 全系統模組串接與邏輯排查（DB 無異動）

10 個步驟的機械化比對（腳本產出，非人工翻閱）。**確認無問題的部分**：前端 452 個 fetch 呼叫點
對 468 支路由**零斷點**；schema **零漂移**（實際建新 DB 逐表逐欄比對，71 表/57 索引/v73 一致）；
demo 隔離無破口；簽核代理 5 routers/10 呼叫點全部傳 `conn`；sidebar 與 9 個徽章模組完整。

**修掉三項**

1. **`pdf_gen.py::_case_closing_report_data()` 漏傳 `pretax`**（13 個存活呼叫點中唯一漏的）。
   已核准稅額沖銷的款項，結案報表 PDF 顯示含稅、其他報表顯示未稅。2026-08-28 那輪掃了
   reports.py／dashboard.py 的 12 個呼叫點，沒掃到 pdf_gen.py。
2. **`POST /api/quotations` 建立者取自 request body**——該檔 45 支寫入端點裡唯一沒有
   `_require_user()` 的，改為以 session 為準。**刻意不加角色限制**（那是 business policy）。
3. **T100「已確認清單／反確認」有後端無前端**（`accounting_export.py:461/495`）。
   「確認已匯入」是批次操作，按錯之後原本只能改資料庫。已補 UI。

**⚠️ 新增防呆 `test_router_registration_2026_09_10.py`**：`routers/projects.py` 的 19 支端點在
`6089a8f` 下線後檔案留著但 main.py 不再 include，架構地圖卻寫「僅保留舊 API 供內部沿用」
——實際上全部 404。現在「哪些 router 刻意不註冊」是一份明確白名單，兩個方向都不會再無聲發生。

**待決策未動**：`/api/cashier/summary` 死碼、`/api/company/search` 前端沒接、
`projects.py` 592 行死碼檔案是否刪除。

### 2026-09-10（最後）— 匯出補上「季」範圍（DB 無異動）

接續上一條。**匯出先前完全不吃期別的季**——`period` 給 `YYYY-Qn` 也只產「當月收支」「今年度收支」
兩塊。兩支匯出端點（`/api/reports/financial/excel`、`/pdf`）新增 `quarter` 參數，帶了才多一張
**「本季收支」工作表**／**本季收支段落**；沿用既有 `write_income_table`／`write_expense_table`／
`write_net_summary` 與 PDF 的 `income_rows_html`／`expense_rows_html`，不另寫版面。

**刻意「加一張」而不是「取代當月那張」**：當月／本季／今年度三種口徑並存（跟畫面上三個範圍鈕一致），
不帶 `quarter` 時輸出與先前完全相同。前端 `exportFile()` 在 `expensesScope === 'quarter'` 時才送。

**驗證**：用真實資料實際產檔——Excel 多出「本季收支」（39 列），季收入 498,440／季支出 307,472
與該季三個月加總相符；真跑 Edge 產出 913KB PDF；再用 Playwright 開同一份 HTML 截圖肉眼複查版面。
測試 3 題，全套非 e2e **535 passed**／e2e **5 passed**。

⚠️ 寫測試踩到的：**手搭假 `data` dict 餵 `_build_report_html()` 會 `KeyError`**（少了
`totalReceivable`），且會隨程式演進失效。比照 `test_reports_export_expenses.py` 慣例改用真實
`_collect()` 組資料，只是不呼叫 `_html_to_pdf()`（那才需要 Edge）。

### 2026-09-10（更晚）— 營運報表期別不同步修復＋新增「季」範圍（DB 無異動）

**症狀**：使用者回報「營運報表切換月／季／年時財務資料不會跟著切換」。
**後端一直是對的**（`_collect()` 的 `periodCases`/`periodReceived`/`periodNet` 實測隨期別變動），
壞在前端狀態同步。

**根因**：「本期收支」KPI 區塊與 `recv`／`out`／`expenses` 三個分頁走的是獨立的
`/api/reports/expenses-monthly`、`/api/reports/receivables-monthly` 兩支資料流。
`56e52b3`（2026-09-09，刻意讓 recv/out 不跟隨 period-bar）與 `6bfcafb` 只在 `reports.js::init()`
同步過一次期別，**`prevPeriod()`／`nextPeriod()`／`switchType()` 以及 period-bar 的年/月/季下拉
全都沒跟上**——這三個函式自初始 commit 至今從未被改過。結果整頁只有「本期新成案」「本期收款」
兩張卡片真的會跟著期別切。

**修法（四項）**

1. **同步點收斂到 `loadData()` 開頭單一處**（新增 `_syncSubPeriods()`）——所有切期別的路徑最後
   都會走到這裡，日後新增觸發點不必再記得補。三個手拼快取鍵的呼叫點收斂成
   `_expensesKey()`／`_receivablesKey()`（鍵欄位漂移正是本 bug 成因）。
2. **兩支端點新增 `quarter` 參數**（1-4；範圍外 400，非整數由 FastAPI 型別轉換擋成 422）。
   `_month_expense_slice()` 抽成 `_months_expense_slice()` 供季共用——**刻意維持月份前綴字串
   比對而非日期區間比對**，`details` 的 `date` 不保證是完整 `YYYY-MM-DD`，改區間會靜默丟資料。
3. **季是純增量欄位**：不傳 `quarter` 時回空集合，`month*`／`year*` 行為零變化，
   Excel／PDF／每月結算寄信等既有呼叫端不受影響（有測試釘住）。
4. 畫面文字改用 `_scopePick()`／`scopeLabel` 統一取值，消掉 7 處只處理兩種範圍的 ternary。

**⚠️ 過程中被新增的 e2e 抓到一個競態（修 A 才浮出來的 B）**：`loadExpenses()`／`loadReceivables()`
原本在**回應抵達時**才算快取鍵，期別若在請求飛行途中被切走（7 月→8 月按很快），會把 7 月的資料
貼上 8 月的鍵，之後守門看鍵相符便不再重載，畫面**永遠**卡在舊月份。已改為發出請求當下就算好鍵
並隨這次請求走、過期回應直接丟棄；`loadData()` 本身同一類競態一併處理。

**測試**：新增 `test_reports_quarter_scope_2026_09_10.py`（9 題）＋ e2e
`test_e2e_reports_period_sync_2026_09_10.py`（1 題，真實瀏覽器切月報 7→8→季報 Q3→年報）。
**該 e2e 已用「還原前端修改後重跑」驗證確實抓得到本 bug**（切到 2026-07 時當月收入停在 0）。
全套非 e2e **532 passed**／e2e **5 passed**。

**已知未處理**：①Excel／PDF 匯出仍走既有 `expense_month` 參數、不含季範圍（行為與修復前一致）
②既有 `test_login_create_submit_approve_smoke` 在 18 輪中偶發 1 次逾時（等「預覽後簽核」按鈕），
與本次改動無關，另案。

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
- 驗證：全套非 e2e **502 passed / exit 0**；`build_deploy_package.ps1` 改完後 BOM（`EF BB BF`）與 CRLF 皆保留、PSParser 語法檢查 0 errors。

### 2026-09-10（打包實測）— tar 路徑歧義第三次踩到，這次徹底解決（commit `d2ff23f`）

- **被上一條剛加的關卡當場抓到**：實際跑 `build_deploy_package.ps1` 打包 `2ea463f` 時直接重現 `/usr/bin/tar: Cannot connect to C: resolve failed` → `[FAIL] tar 解壓失敗（exit code 128）`。這正是 `549d319`（09-08）修過、`942e3c4`（09-10 00:29）又改回去的那個 bug。
- **`942e3c4` 的理由不成立**：它寫「確保與 git archive 生成的 tar 格式完全兼容」才改回優先挑 Git 的 msys/GNU tar，但 git archive 產生的是標準 POSIX tar，Windows 內建 bsdtar（實測 3.8.8）讀得好好的。這台機器 `where tar` 其實就是 System32 的 bsdtar，是腳本刻意優先挑 Git tar 才踩到。
- **修法（兩個獨立的歧義來源一起處理，只修一個都還會壞）**：①**用哪一支 tar**——改回優先 `%SystemRoot%\System32\tar.exe` 並寫完整路徑，不受 PATH 順序影響；沒有內建 bsdtar 的舊系統才退回 Git tar，且那條路徑補 `--force-local` 明確告訴 GNU tar「冒號不是主機名」②**傳什麼形式的路徑**——反正已經 `Push-Location $pkgDir` 了，改傳相對檔名而非 `C:\...` 絕對路徑，讓 `-f host:path` 遠端磁帶機語法從根本上咬不到。並印出實際使用的解壓工具路徑，跟同批加的 Python 直譯器守門同一個做法。
- **這件事本身就是本週最大教訓的實證**：先前 11:28/11:31 那兩份包能成功解壓，代表這個失敗是**環境相依**的——真正保護你的不是「這次跑得過」，而是三層防護（`git archive` exit code／`tar` exit code／解壓後驗證 `backend`、`frontend` 目錄存在）。這次被第二層擋下，沒有再產出一份空殼部署包。失敗留下的空殼包 `20260910_134108_2ea463f` 已刪除。
- **完整打包流程實測通過**：語法檢查 5 支 OK → 直譯器守門（3.11.15，依賴齊全）→ 非 e2e **502 passed** → e2e **4 passed** → 版本標籤 `2026-09-10d`（不再是 null）→ 解壓工具 `C:\WINDOWS\System32\tar.exe` → 產出 `20260910_134616_d2ff23f`（backend 174／frontend 74）→ **exit 0**。
### 2026-09-10（14:01）— ✅ 已部署正式機：`9b0ad79` → `2471747`

- **部署前先做鏈路一致性確認**（09-08 那晚吃過大虧的地方）：①執行中的儀表板進程（09-10 09:48 啟動）**新於** `deploy_dashboard.py`（09-08 09:54），不是跑舊版進程②`_dashboard_remote.ps1` 的 `ad04397`（先同步 `backend/tools/` 再呼叫）與 `6ee3a6d`（`===EXITCODE=N===` 回傳）都在③部署包裡的工具腳本與工作區逐字相同，差異只在換行且**包是 CRLF+BOM**（Windows 安全形式）④包內 `apply_update.ps1` 的五項修復都在。**建議把這四項固定成部署前的例行檢查。**
- **套用過程**：db 快照 → Migration 乾跑通過 → 程式碼回滾快照 → 停服 → 套用 → pip install → 健康檢查（第 1 次 `WinError 10061` 服務還在起、第 2 次成功）→ 更新版本追蹤檔，exit 0。健檢逐次記錄與失敗原因都看得見，`1aa1dfb`＋`6ee3a6d` 在實戰中生效。
- **部署後驗證**：`deployed-version`=`2471747`／`system/version`=`2026-09-10e`（先前卡在 `2026-09-09c`）／`/api/ping` 部署後 +2/+4/+6 分鐘皆 200 無延遲崩潰／叫料 API 回 401 非 404／`webauthn-config-status` = `{"configured":false}`／WebAuthn `login/begin` 回 503 與新測試一致。
- **端對端功能實測（demo 帳號，§3.5 獨立資料庫，正式資料完全未觸碰）7/7 通過**：PATCH 寫入後 GET 真的讀得回來（證明 `conn.commit()` 修好）、報價單 `status` 改動前後都是「草稿」未被寫成 user_id、`updated_at` 仍是時間格式、`audit_log` 查得到 `material_orders.update`。**刻意不只看 HTTP 200**——叫料 API 原本就是回 200 但什麼都沒寫。
- **仍待人工**：WebAuthn RP ID／Origin 未設定（`configured:false`），需要先決定內部 DNS 名稱指向 172.16.10.177，再以 superadmin 在 `company-profile-settings.html` 填入；在那之前 Passkey 維持 503，密碼／TOTP／QR 三種登入不受影響。

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
│   ├── db.py                        ← schema + 74 個 migrations（CURRENT_VERSION=74，見 §2／完整主題索引見 ARCHITECTURE-MAP §4）
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
│   ├── tests/                       ← 114 個測試檔、874 題（2026-09-14 實際 collect 數）
│   │                                   其中 test_system_audit_2026_09_14.py 是「跨層稽核」
│   │                                   （備份涵蓋／守門缺漏／角色字串／組織外鍵），見 §12 同日條目
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

**⚠️ 桌面捷徑一定要指向「真的」GUI 版 pythonw.exe（2026-09-11 修）**

桌面捷徑「MOTRIX 部署儀表板」原本指向
`AppData\Local\hermes\hermes-agent\venv\Scripts\pythonw.exe`，結果**每次開啟都會多跳
一個 CMD 主控台視窗**。根因不在這個專案的程式碼，而在那個 venv：

```
venv\Scripts\python.exe   45,568 bytes  SHA256 ADBF666C...
venv\Scripts\pythonw.exe  45,568 bytes  SHA256 ADBF666C...   ← 位元組完全相同
```

那是 **uv 建 venv 時放的 trampoline**，`pythonw.exe` 只是 `python.exe` 改個檔名，
仍然是 console 版——所以就算叫 pythonw 也會配一個主控台，`ctl` 再用
`sys.executable` 旁邊的 pythonw 去起 server 時同樣帶著主控台。
（`ctl` 的 `CREATE_NO_WINDOW` 擋不住，主控台是 trampoline 自己配的。）

**現在的設定**：捷徑 TargetPath 改成
`C:\Users\hichan\AppData\Local\Programs\Python\Python313\pythonw.exe`
（系統 Python 3.13，有真正的 GUI 版 pythonw，且 tkinter／fastapi／uvicorn／requests／
urllib3／pydantic 都齊全，實測儀表板六支唯讀端點在 3.13 下全部 200）。
Arguments 與 WorkingDirectory 維持不變。

**檢查方式**（換機器或重建 venv 後值得跑一次）：

```powershell
# 兩者 hash 相同 = 那個 pythonw 是假的，用它會跳主控台
(Get-FileHash "$venv\Scripts\python.exe").Hash -eq (Get-FileHash "$venv\Scripts\pythonw.exe").Hash

# 開起來之後確認沒有 conhost 掛在 python 底下
Get-CimInstance Win32_Process -Filter "Name='conhost.exe'" | ForEach-Object {
  $p = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.ParentProcessId)").Name
  if ($p -match 'python') { "有主控台：conhost $($_.ProcessId) <- $p" } }
```

**⚠️ 第二半：`deploy_dashboard.py` 的 subprocess 一律要帶 `CREATE_NO_WINDOW`**

把捷徑改成真正的 GUI `pythonw` 之後，使用者回報「不定期一直跳 CMD 的快速關閉
視窗」。那不是新缺陷，是**原本被那個常駐主控台蓋住的舊缺陷浮出來**：

- 主行程由 `pythonw` 啟動 → **自己沒有主控台**
- 每次呼叫 console 程式（`git.exe`、`powershell.exe`）而沒帶 `CREATE_NO_WINDOW`
  → Windows 就替那個子行程配一個新主控台 → 畫面上閃一下又關掉
- `/api/dev-status` 被前端 `setInterval(refreshDevStatus, 15000)` 每 15 秒輪詢，
  而它一次跑 **4 個 git**，所以閃得特別勤

`deploy_dashboard_ctl.pyw` 從一開始就有這個旗標，`deploy_dashboard.py` 則是
一個都沒有。已補齊 5 處（部署/回滾 job 的 Popen ×1、dev-status 的 git ×1、
`_dashboard_remote.ps1` 遠端呼叫 ×3）。

**驗證方式**（直接驗機制，不要靠數 conhost——conhost 的父行程是 `git.exe`
而不是伺服器本身，git 又立刻結束，數不到，會得到假綠燈；實測踩過）：

```python
# 由 pythonw 執行；子行程用 console 版 python.exe
PROBE = "import ctypes,sys; sys.exit(1 if ctypes.windll.kernel32.GetConsoleWindow() else 0)"
subprocess.run([PY, "-c", PROBE]).returncode                      # → 1（有主控台，會閃）
subprocess.run([PY, "-c", PROBE], creationflags=0x08000000).returncode  # → 0（沒有）
```

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

### §14.3d · 兩邊同時有人／有 AI session 在動時的交接協定（2026-09-10）

> 2026-09-10 首次遇到「開發機與正式機同時各有一個 Claude session 在改同一個功能
> （WebAuthn）」，開發機這邊已經打包好正要部署才被叫停（見 §0 落差表同日條目）。
> §0 那張表長期記錄的都是「事後才發現」，這次是即時發現——差別只在有人剛好在看。
> 以下把它變成不依賴運氣的流程。

**原則：序列化，不要並行。** 同一時間只有一邊在改程式碼。理由很實際——正式機不是
git repo，兩邊各改各的之後沒有任何工具能自動合併，而 `apply_update.ps1` Step 3 是
整個覆蓋，先部署的那邊會無聲無息蓋掉另一邊。

**交接檔（由「正在動的那一邊」在收工時產出）**

固定路徑，刻意放在部署會覆蓋的範圍之外，才不會被 `apply_update.ps1` 蓋掉：

```
正式機：C:\Users\Motrix\Desktop\AGENT-HANDOFF\YYYYMMDD_HHMM_prod.md
開發機：C:\Users\hichan\Desktop\MOTRIX-ERP\..\AGENT-HANDOFF\YYYYMMDD_HHMM_dev.md
```

開發機這邊用 `backend/tools/check_prod_drift.ps1` 把正式機的交接檔拉回來讀
（同一條 WinRM 通道，`Copy-Item -FromSession`）。

**交接檔必須包含這 7 項**（少一項下一棒就得自己去翻，等於沒交接）：

| # | 欄位 | 為什麼需要 |
|---|------|-----------|
| 1 | 改了哪些檔案（完整路徑清單） | 下一棒要知道自己的改動會不會撞到 |
| 2 | 每個檔案改了什麼、為什麼 | 決定該合併還是該丟棄 |
| 3 | 有沒有動資料庫（schema／資料列） | migration 沒進 `db.py` 的話，兩機 schema 會分岔（§0 v32/v33 就是這樣） |
| 4 | 有沒有改設定（`system_settings` 的 key 與**實際值**） | 例如 `webauthn_rp_id`／`webauthn_origin`，這些不在 git 裡，重建環境時會整個消失 |
| 5 | 有沒有重啟服務／改排程工作 | 影響下一棒判斷當下狀態 |
| 6 | 有沒有進 git（有的話附 commit hash） | 沒進 git 的東西下次部署就會被覆蓋掉 |
| 7 | 未完成、待接手的事 | 半成品最容易被下一棒當成完成品 |

**接手方的固定動作**（不要只信交接檔）：

1. 讀交接檔
2. 跑 `check_prod_drift.ps1` —— 交接檔寫的是「對方以為自己改了什麼」，drift 檢查
   看的是「實際上什麼不一樣」。兩者對不上的部分才是真正的風險
3. 把有價值、還沒進 git 的改動依 §14.2 拉回開發機合併進 git
4. 確認 §0 落差表已更新，再開始自己的工作

### §14.3e · 正式機漂移檢查（`check_prod_drift.ps1`，2026-09-10）

正式機不是 git repo，任何人直接在 `C:\Users\Motrix\Desktop\V9.0` 底下改檔案，開發機
完全看不到；下次 `apply_update.ps1` 一跑，Step 3 整個覆蓋，那些改動就無聲消失。過去
只能靠人記得講——而 §0 那張表本身就是「人不會記得」的證據。

作法：正式機的 `/api/system/deployed-version` 會回報它跑在哪個 commit，本工具用
`git archive` 還原該 commit 算 SHA256，再透過 WinRM 對正式機同一批路徑算一次，逐檔
比對。**全程唯讀**（遠端只跑 `Get-ChildItem`／`Get-FileHash`，不寫入、不重啟）。

```powershell
"密碼" | powershell -ExecutionPolicy Bypass -File backend\tools\check_prod_drift.ps1
"密碼" | powershell -ExecutionPolicy Bypass -File backend\tools\check_prod_drift.ps1 -Commit 2471747
```

輸出分三類：**內容被改過**（下次部署會覆蓋掉）／**只有正式機有**（新增但沒進 git）／
**正式機缺少**（被刪或套用不完整）。比對範圍只含 `backend/`＋`frontend/`，排除 db、
log、上傳檔、快照、憑證、per-machine 設定檔等執行期產物。

**踩過的坑**：排除規則必須在**遠端**就套用，不能只在本機端過濾結果——正式機的
`backend\logs\server.log` 被執行中的 uvicorn 開著，`Get-FileHash` 會拋 FileReadError
讓整個 `Invoke-Command` 中止；另外每個檔案要個別 try/catch，任何一個讀不到都不該
讓整次掃描報廢。

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

### 溝通與撰寫風格（2026-09-15 使用者指示，最高優先）

**專業、簡短、以最佳建議為導向。減少過多解釋、過多備註。**

- 回覆先給結論與建議，不要鋪陳推理過程；要說明時一句到位
- 不逐步報告做了什麼，除非影響使用者的決策
- 有多個選項時直接給推薦做法，不列完所有可能
- 程式碼註解只留「為什麼」與踩過的坑，不寫敘述性長文
- 文件條目同樣從簡：結論、取捨、風險，三項為主

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

### 跨層一致性稽核（2026-09-14）

**`backend/tests/test_system_audit_2026_09_14.py`** —— 跟著每次 pytest 跑，
不驗證任何功能「做得對不對」，只驗證**跨層的對應關係有沒有漂掉**。
這類缺陷的共同特徵是「每一邊單獨看都正確、合起來才是錯的」，逐功能的測試照不到。

| 守什麼 | 漂掉的症狀 |
|--------|-----------|
| 每張資料表都要明確決定要不要進每日 JSON 匯出 | 平常沒事；要用 §8.3 的最後手段還原時，才發現那張表從來沒被匯出過 |
| 每一條匯出查詢都要真的跑得起來 | 表存在、語法正確，執行時才炸（`ORDER BY id` 但那張表沒有 id）；失敗被 try/except 吞掉，備份頁面照樣綠燈 |
| 單張表失敗不可以還是報 `backup.daily_ok` | 「備份看起來有在跑」型事故：綠燈跑了好幾個月，要還原才發現那張表每天都是空的 |
| 使用者匯出不可以夾帶憑證欄位 | `totp_secret` 被抄進人看得懂的 JSON，備份資料夾變成可直接使用的認證素材 |
| 任何一張表的匯出都不可以夾帶祕密欄位／設定值 | 同上，但發生在下一張新表或下一個新設定上；`system_settings` 的祕密藏在 `value_json` 裡，只看欄位名掃不到 |
| 匯出裡不可以有 base64 內嵌影像 | 身分證與存摺掃描件每天被複製一份到雲端備份資料夾 |
| 每支路由都要呼叫守門函式（16 支公開端點列成白名單） | 端點上線、測試全綠，因為沒有人針對「它應該要擋」寫題 |
| DELETE 端點要檢查角色或擁有者，不能只有「有登入就好」 | 任何登入者都刪得掉別人的東西，而且不可復原 |
| 程式與資料庫裡的角色字串都必須是已知角色 | `role == 'superadmn'` 這種拼錯不會報錯，只會讓那道檢查**永遠不成立** |
| 組織階層外鍵（users→departments→divisions、部門主管） | 部門篩選讓人默默消失、主管簽核找不到人，而不是報錯 |

模組串接**不在這支裡**——`test_module_keys_consistency_2026_09_13.py` 已經完整
覆蓋，而且比臨時寫的更周全（它還守著「擋錯人」：某模組的頁面呼叫到不接受該模組
的 API，畫面一片 403 而後端測試全綠，因為測試多半用 admin 帳號、admin 直通）。

**白名單的意義是讓下一個新增項目變紅，不是讓測試變綠。** 看到紅燈時該做的是判斷
「這個新項目應該進清單，還是應該修程式」。

**寫這支測試當下抓到的兩件事**：

1. `DELETE /api/shipping-notes/{no}/signed-files/{id}` 與完工單的同名端點，
   在此之前**只有 `_require_user()`**——任何登入者都能刪掉任何單據的回簽附件，
   而且會連實體檔案一起移除。已補 admin+（與同日新增的動態附件同一個標準）。
2. 每日 JSON 匯出只涵蓋 **8/76** 張表——§8.3 的最後手段重建不出 `users`／
   `system_settings`／`payslips`／業務開發／三種憑證流。先用一支
   `xfail(strict=True)` 把落差變成會被追蹤的東西，**同一輪內補完了**：
   現在 41 張，xfail 照約定拿掉。補的過程又掃出兩件事：`stock_batches`
   的 `ORDER BY id` 執行時才會炸（表存在、語法正確，前兩題都是綠的），
   以及單張表失敗時 `_daily_backup()` 照樣報 `backup.daily_ok`。兩件都已修，
   並各自補上會紅的測試（含正向控制）。詳見 §12 第十輪第四節。

> **這支測試自己也差點犯同一類錯**：初稿寫死守門函式名稱去掃，誤報 5 支 T100 端點
> （它們有自己的 `_require_t100_admin`）；又誤判 `financial_view`／
> `project_approve_eng` 沒有後端檢查（前者有專屬 helper、後者寫成 `'x' in modules`）；
> 還一度斷言 `_SUPERADMIN_MODULES` 應該等於 `allModules` 並照著去「修」
> `helpers/auth.py`，**打破了既有測試守著的真正不變量**（那份樣板要等於前端的
> superadmin 角色樣板），改動已還原。
> 教訓：**動手改之前先確認有沒有既有測試在守同一件事**，既有的那份通常比臨時
> 想出來的斷言更清楚為什麼要這樣。

### 其他維護提醒

- 功能變更時先更新本檔「對應 §N 章節」，再在 §12 加摘要。
- 死碼警告欄位如有整理（移除 .js、改用 include），記得更新 §2 與 §13。
- **新增任何 `import` 第三方套件時，記得同步補進 `backend/requirements.txt`**（2026-09-07 複查發現 `openpyxl`／`Pillow` 這兩個核心功能會直接用到的套件，先前完全沒被記載——`routers/contractors.py` 對 `PIL` 是模組頂層 unconditional import，若一台全新機器照抄 `requirements.txt` 裝環境，裝完直接啟動會在 import 這個 router 時整台伺服器起不來）；只有測試/工具腳本用到、伺服器本身不會 import 的套件（如 `tools/local_research_pipeline.py` 用的 `beautifulsoup4`/`requests`）放進 `backend/requirements-dev.txt` 即可。想確認目前有沒有已知安全弱點，跑 `python backend/tools/check_dependencies.py`（需要先 `pip install pip-audit`，見該腳本 docstring；非排程工具，建議升級套件版本或每季手動跑一次）。
