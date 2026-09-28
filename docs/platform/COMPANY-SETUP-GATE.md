# 販售版：本公司資料設定閘門——調查與設計（E 線 E4，2026-09-28）

> 狀態：**調查＋設計，尚未實作**（主持派工：交 D 審，過了才實作）。
> 依據：CORE-SPEC 裁示表「販售版：輸出文件前強制設定本公司資料」（0f8b16bf＋99702431）。使用者原話（逐字）：
> 「未來販售輸出的檔案，需要對方強制設定自己的公司名稱跟統編等訊息，避免對方用預設我的公司統編輸出報價單等相關文件」；
> 「例如先導航去公司設置，設置完才開放功能」。
> 本文件**不寫任何開發者公司的字面值**（公司名、統編、電話、網域…）：一律以「<字面值>」＋檔案:行號指稱（§3.3 說明為什麼與怎麼存指紋）。
> 盤點方式：兩個唯讀搜尋（輸出點／回退路徑）＋本人逐點抽查（voucher_pdf、legal_params、payslip-form、core/upgrade、.gitattributes 已對照原始碼）。

## 0. 結論

| 項目 | 結論 |
|---|---|
| 對外輸出點 | 後端 34 個端點＋1 個排程信、前端 6 類（§1）。**八種單據 PDF＋自訂模組**經同一條路（`company_identity.location_identity` → `pdf_gen._identity_head/_identity_foot`）；**繞過它的 3 處**：傳票 PDF、個資告知列印、薪資單（前端直讀設定並存進單據） |
| 回退到開發者資料的路徑 | 資料層已封：全新安裝種子是空、`DEFAULT_IDENTITY` 全空、包內沒有 .db。**仍會到客戶手上的 4 類**：預設 LOGO／favicon 圖、掃描器看不到的出貨檔（version_manifest 內文、docs/platform/audit、DR-SOP.md、.gitattributes 註解）、每個客戶庫都會寫入的版本紀錄內文、V9 轉換工具以「名稱片段」認本公司（§2） |
| 「已設定」判準 | **確認紀錄**（本安裝最高管理員在設定頁按「確認本公司資料」）＋**綁本機**（機器指紋）＋**欄位雜湊一致**；公司統編／名稱命中**開發者指紋**時另需「登記的開發者機器」或「開發者簽章的確認檔」（§3） |
| 引導與擋 | 比照既有「必須先改密碼」：auth_middleware 之後擋所有 `/api/`（白名單例外）回 409 `company_setup_required`；`notif.js` 導向設定頁（最高管理員）或說明頁（其他人）；輸出端 `company_identity.require_for_output()` 第二道（§4、§5） |
| 既有正式機 | 正式機機器指紋先登記（正式機回報取得）⇒ 升級當下自動補確認紀錄 ⇒ 行為不變；以演練＋正式機升級後健檢驗證（§6） |
| 守門 | ①所有 `/api` 路由預設被擋（白名單要逐條理由＋存在性）②輸出點掃描器（先讓已知 40 點亮起）——新輸出點沒經過 `require_for_output` 或未登記「不含本公司資料」⇒ 紅（§7） |

## 1. 對外輸出點盤點（本公司資料從哪來）

簡寫：**CI**＝`helpers/company_identity.py`；**LI**＝`location_identity()`；**Head/Foot**＝`pdf_gen._identity_head`（pdf_gen.py:562）／`_identity_foot(_short)`（:578／:589）；**snap**＝送審時凍結的 `data_json.locationIdentity`（`apply_snapshot`）。

### 1.1 經共用路徑（LI／Head/Foot／doc_template／company_heading）

| 模組 | 端點（檔:行） | 形式 | 本公司資料來源 |
|---|---|---|---|
| case | `GET /api/quotations/{no}/pdf-download`（quotations.py:5149）、`POST …/export`（:3575）、`POST /api/quotations/preview-html`（:5108） | PDF／HTML | LI＋snap → Head/Foot（pdf_gen.py:118、:862） |
| case | `GET …/closing-report-pdf`（:5313）、`GET …/project-report-pdf`（:5349） | PDF | LI＋snap → Head/FootShort |
| case | `GET …/completion-notes/…/pdf-download`（completion_notes.py:625）、`POST …/export`（:647） | PDF | LI＋snap（completion_pdf.py:36） |
| supply | 出貨單 `pdf-download`／`export`（shipping_notes.py:627／:652） | PDF | LI＋snap |
| subcontract | 承攬匯款申請 `pdf-download`／`export`（contractor_vouchers.py:655／:683） | PDF | LI＋snap |
| arap | 開票申請 `pdf-download`／`export`（invoice_vouchers.py:740／:767） | PDF（doc_template） | LI＋snap 注入 identity_head／foot |
| arap | 請款單 `pdf-download`／`export`（payment_requests.py:832／:859） | PDF（含匯款帳號） | LI＋snap；**銀行欄位用即時值** |
| payroll | 獎金分潤單 PDF／預覽（bonus.py:1492、:1435、:2237） | PDF／HTML | `CI.company_name()`（bonus_pdf.py:46）；空 ⇒ 印「未設定」 |
| accounting | T100 傳票匯出（accounting_export.py:475） | XLSX | `CI.company_heading` |
| analytics | 財報 Excel／PDF、稅務匯出（reports.py:2332、:2367、:2614） | XLSX／PDF | `company_heading`＋`contact_line` |
| analytics | **每月排程報表信**（reports.py:2771–2812） | 信件＋XLSX／PDF 附件 | 同上（排程，不經 HTTP） |
| netplan | 規劃書 Excel／PDF（api.py:293、:311） | XLSX／PDF | `company_name`、`contact_line`、`footer_line`、LI 英文名 |
| L1 自訂模組 | `GET /api/custom/{key}/records/{no}/output`（custom_records.py:213）、預覽（:291）、輸出版型預覽（definitions.py:303） | HTML／PDF | `render_view` → LI（一律主要據點）；版型預覽用假資料 |
| L1 品牌 | `GET /api/system/branding`（auth.py:321）、`…/branding/{logo,logo-dark,favicon}`（system.py:2774） | JSON／PNG | LI；圖檔＝上傳檔或**預設圖**（§2-①） |

### 1.2 繞過共用路徑（直讀 `company_profile`）——**要改成走 CI**

| 位置 | 問題 |
|---|---|
| `modules/accounting/voucher_pdf.py:97 _company_name()`（:123 讀設定）→ 傳票 PDF／預覽（vouchers.py:1734、:1807） | 只讀 `name`，不認據點與別名 |
| `routers/legal_params.py:51`（及 customers.py:191、auth.py:1614、quotations.py:6158、completion_notes.py:791 的告知端點）→ `static/privacy-notice.js:37-43` 列印 | 直接回 `profile["name"]`；前端 `document.write`＋`print()` |
| `frontend/pages/payslip-form.html:744-749` | 前端讀設定預填 `companyName／companyTaxId／companyContactInfo` 並**存進薪資單**（可手改）；後端只在三欄全空時才用 LI（pdf_gen.py:618） |

### 1.3 不含本公司資料的輸出（只受第一道擋）

case-batch XLSX（quotations.py:6004）、承攬人員 XLSX（contractors.py:230）、出納 XLSX（cashier.py:302）、每日任務 CSV（daily_tasks api.py:730）、快速拓樸 PDF（netplan api.py:463，標題由請求帶）、附近旅宿 CSV／JSON（lodging）、前端 XLSX（customers／parts／suppliers／vendor-contractors）、甘特圖 PNG（case-management-exec.js:730）。
一般通知信：內文不含本公司資料、寄件人名＝產品名（email_notify.py:334、:455、:1529）。

### 1.4 已存檔的輸出

`GET …/versions/{seq}/download`（quotations.py:5272）等「下載當時產生的 PDF」：內容在產生時已凍結。閘門擋**產生**；已存在的檔在設定完成前一樣被第一道擋（§4），設定完成後照舊可下載（那是當時的正式文件）。

## 2. 回退到開發者公司資料的路徑

| # | 路徑 | 會不會到客戶 | 處置（本案或另案） |
|---|---|---|---|
| ① | 預設 `frontend/static/logo.png`／`logo-white.png`／`favicon.png`（含英文公司名；`KEPT_DEFAULT_IMAGES`（_our_company_literals.py:55-59）使用者裁示保留）經 `/api/system/branding/<kind>` 顯示 | **會**（上傳前的畫面；PDF 不嵌 LOGO） | 待裁示 Q1：換成中性預設圖（產品名 MOTRIX）或未上傳時不顯示 |
| ② | `backend/version_manifest.json` 內文 5 筆（:491、:1184、:1254、:1261、:1793）含 <字面值>；啟動時寫入客戶庫 `module_versions`（startup.py:526），V9 升上來的安裝全部顯示，且進每日備份（archive.py:2076） | **會** | 另案：出貨版本紀錄去識別化（改寫內文或出貨時過濾）＋既有客戶庫清理；需使用者裁示（已出貨的紀錄屬 ALLOWED「已出貨版本紀錄」） |
| ③ | `docs/platform/**`（未 export-ignore，141 檔）如 `audit/AUDIT-X-9b-…md:75`、`AUDIT-X-C-batch1.md:116,136,176`；`DR-SOP.md:127`（demo 密碼＝<字面值>）；`.gitattributes:180`（網域註解） | **會**（進 git archive） | 另案：docs/platform export-ignore（或逐檔）＋DR-SOP 改寫；掃描器擴到 .md 與根目錄（§7-③） |
| ④ | `core/upgrade.py:683-686 _is_our_install`：統編相等**或名稱含兩字片段** ⇒ 把 `V9_COMPANY_DEFAULTS`（:653-659，全部 <字面值>）寫進空白欄位；由出貨的 `tools/platform/upgrade.py:157` 呼叫 | 只有 V9 轉換；**名稱含該片段的客戶會被寫入開發者統編** | **本案修**：改為只認統編指紋（§3.3），刪名稱片段判斷 |
| ⑤ | `db.py:4704-4800 _m106`、`db.py:1032-1063 _m008`（staff 帳號名）、`helpers/auth.py:44`（弱密碼黑名單）、`tools/platform/upgrade_drill.py:96-97` | 凍結 migration／只寫演練暫存／黑名單，不寫進客戶輸出 | 不動（ALLOWED 已登記） |
| ⑥ | 種子 `db.py:769` 空白、`DEFAULT_IDENTITY` 全空、demo 庫每次登入重建（system_settings 清空）、包內無 .db（verify_package.py:108、:159-162 擋） | 不會 | —（守門已在） |

## 3. 「已設定」的判準

### 3.1 為什麼不能用「欄位非空」
從開發者機器複製來的資料庫、或 V9 轉換後的庫，欄位全都「非空」而且是開發者的（記憶〈守門要驗有沒有人做過決定〉）。

### 3.2 確認紀錄（新設定鍵 `company_identity_confirmation`，T1）
```json
{"confirmed_by": "<帳號>", "confirmed_at": "<ISO>", "fields_hash": "<sha256>",
 "binding": "m:<機器指紋>" , "via": "settings_page|upgrade_backfill|signed_file"}
```
**有效**＝以下全成立（`helpers/company_setup.status()`，L1）：
1. 紀錄存在且格式正確；
2. `binding` 等於本機（`licensing.machine_fingerprint()`；讀不到硬體 ⇒ 改用 `i:<安裝識別檔>`，見 3.4）；
3. `fields_hash`＝目前必要欄位（正規化後）的雜湊——必要欄位被改過（任何路徑：API、腳本、還原）⇒ 失效，要重新確認；
4. 必要欄位都合格（3.5）；
5. 統編或公司名命中**開發者指紋**（3.3）⇒ 另需「本機是登記的開發者機器」或「有效的開發者簽章確認檔」。

**只有**設定頁的「確認本公司資料」（`PUT /api/settings/company-profile` 帶 `confirmIdentity: true`，**限最高管理員**）會寫紀錄；一般存檔（例如只改 Google 金鑰）**不會**——否則複製來的庫只要管理員存一次任何設定就「確認」了。寫紀錄同時記稽核（誰、何時、欄位雜湊，不記值）。

### 3.3 開發者指紋怎麼存（不把統編字面值寫到出貨程式碼以外）
- 出貨程式碼內只放**雜湊**：`DEVELOPER_IDENTITY_FP = {sha256("motrix-devco-v1|" + 正規化值)}`，正規化值＝統編只取數字、公司名去空白與「股份有限公司／有限公司」字尾。建置時由開發者本機的一次性工具算出貼入（工具不存字面值）。
- ⚠ **誠實說明**：統編只有 8 碼，有鹽的雜湊仍可在數秒內暴力還原（鹽在程式碼裡）。這個設計的目的是**不再多一處字面值**（文件、測試、設定、log 都不出現），不是保密——統編本來就是公開登記資料，且已以字面值存在於凍結的 `db.py`／`core/upgrade.py`（ALLOWED）。
- 開發者機器登記：`DEVELOPER_MACHINES_FP = {sha256("motrix-devmachine-v1|" + 機器指紋)}`（開發機、正式機）；正式機指紋由正式機回報取得（`MOTRIX-交付\正式機回報`），不寫進文件。
- 硬體更換的出口：開發者以既有交付簽章金鑰（Ed25519，D:\MOTRIX-KEYS\delivery）簽一個確認檔 `company_confirmation.sig`（內容：統編雜湊＋機器指紋＋簽發日），放安裝根目錄（F3，不進包、不上雲）；公鑰已內嵌於 licensing。**建議**以此為主、登記機器為輔（Q2）。
- `_our_company_literals` 守門：雜湊不是字面值、掃描器看不到 ⇒ 另加一題「指紋常數只出現在 `helpers/company_setup.py`」。

### 3.4 綁本機
- 首選 `licensing.machine_fingerprint()`（主機板 UUID＋第一張實體網卡 MAC，已有且已測）：只複製資料庫、或整個安裝目錄搬到另一台 ⇒ 失效。
- 讀不到硬體（RuntimeError）⇒ 退用安裝識別檔 `backend/.install_identity`（首次啟動產生的隨機值，F3：`.gitignore`、`verify_package` 拒絕帶入、每日備份不收）；退用時設定頁標明「本機綁定改用安裝識別檔」。
- ⚠ 網卡更換會讓紀錄失效 ⇒ 管理員重新確認一次（非開發者資料不受 3.3 限制，按一次即可）。

### 3.5 必要欄位（調查結果＋建議）
| 欄位 | 印在哪 | 建議 |
|---|---|---|
| 公司名稱 | 所有單據抬頭、報表、規劃書、告知、傳票 | **必要** |
| 統一編號 | 單據抬頭／頁尾、報價單 | **必要**；8 碼＋財政部檢查碼驗證（含第 7 碼為 7 的例外） |
| 電話 或 email（至少一項） | 頁尾 `contact_line`／`footer_line` | **必要其一** |
| 英文名稱 | 報價單、規劃書 | 選填 |
| 地址 | 目前**沒有任何輸出印本公司地址**（只印客戶交貨地址） | 選填（地圖據點另有用途） |
| 匯款銀行／戶名／帳號 | 請款單 | 全域不必要；**請款單輸出時**才要求（`require_for_output("payment_request")` 另驗銀行欄位） |
| LOGO | 畫面（PDF 未嵌） | 不在判準內（見 Q1） |

## 4. 首次引導與後端擋

### 4.1 後端（第一道）
- 位置：`main.py` `auth_middleware` 在「必須先改密碼」之後、`call_next` 之前（同一套形狀：`_MUST_CHANGE_PW_ALLOWED` 那個白名單＋`code`）。
- 未設定 ⇒ `409 {"detail": "尚未完成本公司資料設定", "code": "company_setup_required", "canFix": <是否最高管理員>, "settingsUrl": "/pages/company-profile-settings.html?setup=1"}`。
- 白名單 `_COMPANY_SETUP_ALLOWED`（每條附理由，§7-①）：登入／登出／`/api/auth/me`／改密碼／TOTP 與 Passkey 設定（帳號本身必要功能）、`/api/ping`、`/api/system/version`、健康檢查、`/api/system/branding*`（登入頁）、`/api/settings/company-profile`（GET／PUT）、`/api/settings/company-setup/status`、上傳品牌圖、`/api/platform/menu`（導頁需要）、使用者管理的「自己」端點。**其他全部擋**（預設拒絕：新 API 自動被擋，不必記得加）。
- 效能：`status()` 結果快取在行程內，以 `system_settings` 的 `company_profile`／`company_identity_confirmation` 的 `updated_at` 當版本；機器指紋已有行程快取。
- 非 HTTP 的輸出（每月排程報表信）：走第二道（§5），未設定 ⇒ 不寄、記一則「本公司資料未設定」系統告警（邊緣觸發、每日一封，比照〈告警必須有速率上限〉）。
- demo：demo 庫每次登入重建、公司資料為空 ⇒ **待裁示 Q3**。建議：demo 庫種一份明確虛構的示範公司（名稱含「示範」、統編用不合檢查碼的 `00000000`）＋確認紀錄 `via: "demo_seed"`，且 demo 模式所有輸出加「示範資料」浮水印；demo 的虛構身分永遠不進正式庫（demo 隔離已有）。

### 4.2 前端
- `static/notif.js` 的 fetch 包裝（已處理 `must_change_password`）加 `company_setup_required`：最高管理員 ⇒ 導 `company-profile-settings.html?setup=1`；其他人 ⇒ 導新頁 `company-setup-required.html`（「請最高管理員先完成本公司資料設定」＋最高管理員帳號名單不列，只說角色）。
- 登入後第一個請求（`/api/platform/menu` 在白名單內，回應帶 `companySetup: {configured, canFix}`）⇒ 側欄在未設定時只顯示設定頁入口。
- 設定頁 `?setup=1`：頂端說明「輸出文件會使用以下資料；確認前系統其他功能暫停」＋必要欄位驗證＋「確認本公司資料」鈕（勾選「以上為本公司資料」才可按）；命中開發者指紋 ⇒ 明說「這是 MOTRIX 開發者的公司資料，請改成貴公司資料」，確認鈕停用。

## 5. 輸出端第二道
- L1 `company_identity.require_for_output(kind)`：`status()` 不通過 ⇒ 丟 `CompanySetupRequired`（端點轉 409 同一個 code）；`kind="payment_request"` 另驗銀行欄位。
- 放在**共用路徑本身**：`location_identity()` 之上加 `identity_for_output(location_id, kind)`，Head/Foot、`doc_template` identity 區塊、`company_heading`／`contact_line`／`footer_line` 的輸出呼叫全部改走它 ⇒ 一處擋住 1.1 全部。
- 1.2 的三處改走 CI：voucher_pdf 改 `identity_for_output`；legal_params 等告知端點改 `company_name()`；薪資單前端預填改讀 `/api/system/branding` 的 LI 欄位，後端產 PDF 時若單據上的公司欄位與本公司不同 ⇒ 以本公司為準並提示（**待裁示 Q4**：薪資單可手改公司欄位是否保留）。
- 1.3 不含本公司資料的輸出不加第二道（第一道已擋），但守門要求逐一登記「不含本公司資料」理由（§7-②）。

## 6. 既有正式機行為不變的證明
- 升級 migration（L1，核心 migration 新版號）：若本庫沒有確認紀錄，且必要欄位合格，且（統編未命中開發者指紋，**或**本機是登記的開發者機器／有有效簽章確認檔）⇒ 寫確認紀錄 `via: "upgrade_backfill"`；否則不寫（該安裝首次登入會被導向設定頁）。
  - 開發者正式機：機器指紋先登記（出貨前由正式機回報取得）⇒ 升級當下補紀錄 ⇒ 登入後沒有任何導頁、所有輸出照舊。
  - ⚠ 其他已上線客戶（目前沒有）：資料非開發者 ⇒ 同樣自動補；是開發者資料 ⇒ 被擋（正是要擋的情境）。
- 證明方式：
  1. 題：以正式機形狀的庫（BASELINE 演練庫）＋登記機器指紋（monkeypatch）⇒ 升級後 `status().configured` 為真、報價單 PDF 200；反向控制：同一個庫、機器指紋不在登記 ⇒ 409。
  2. 演練：`apply-run` 演練目錄在開發機（已登記）跑一輪：登入→開報價單 PDF→每月報表排程乾跑，全部照舊。
  3. 正式機升級後健檢加一項：`GET /api/settings/company-setup/status` 為 configured（正式機 Claude 指示回報），不是則立即回滾。
- 與品牌設定（h-branding）的關係：h-branding 守「**程式碼**不含本公司字面值」＋「單據與頁面經 `company_profile`／`/api/system/branding`」；本案守「**資料**不可以是開發者的、且有人確認過」。兩者互補：本案的指紋常數是雜湊（h-branding 掃描器看不到），另加「指紋只在一處」題；§2-③ 的 .md／根目錄盲區建議擴大 h-branding 掃描範圍（另案）。

## 7. 守門
| # | 守什麼 | 做法 |
|---|---|---|
| ① | 新 API 自動被擋 | 未設定狀態下，列出所有 `/api` 路由（沿用 E3-S2 的路由走訪，含 include 子 router）：白名單外的每一條打一次（路徑參數填假值）⇒ 必須 409 `company_setup_required`（不可 200／4xx 其他）；白名單每條有理由、存在；正對照：設定完成後同一批不再 409；反向控制：把一條加進白名單不寫理由 ⇒ 紅 |
| ② | 新輸出點要經第二道 | 掃描器（AST＋文字）找「會產生對外檔案」的程式：`html_to_pdf_bytes`／`run_edge_pdf`／`_render_pdf_via_edge`／`openpyxl.Workbook`／`csv.writer`＋`text/csv`／`Content-Disposition: attachment`／`FileResponse`／`_send_with_attachments`；每一點必須（a）同函式或其端點呼叫 `require_for_output`／`identity_for_output`，或（b）登記在「不含本公司資料」清單附理由。**正對照**：§1 的已知點全部要被掃到（數量下限＋逐一點名 8 種單據 PDF、傳票、報表、規劃書、排程信）；反向控制：合成一個新端點產 XLSX 不經檢查 ⇒ 紅；登記過期 ⇒ 紅 |
| ③ | 不回退到開發者資料 | 全新庫：`status()` 未設定、所有 identity 輸出 409；複製庫（帶確認紀錄、機器指紋不同）⇒ 未設定；開發者指紋資料在非登記機器上按確認 ⇒ 拒絕；§2-④ 名稱片段 ⇒ 不再認；demo 輸出不含正式庫資料 |
| ④ | 判準是「有人決定過」 | 欄位全非空但沒有確認紀錄 ⇒ 未設定；改必要欄位（直接寫 DB）⇒ 紀錄失效；只存 Google 金鑰（不帶 confirmIdentity）⇒ 不寫紀錄 |
| ⑤ | 指紋只在一處 | 開發者指紋常數只准出現在 `helpers/company_setup.py`；repo 任何地方出現與開發者統編相同的 8 碼字面值 ⇒ 沿用 h-branding 的 ALLOWED 規則 |

## 8. 步驟（實作時，依序）
1. L1 `helpers/company_setup.py`：`status()`、確認紀錄讀寫、指紋常數、機器綁定（含安裝識別檔退路）、統編檢查碼；題（§7-③④⑤）。
2. `PUT /api/settings/company-profile` 接 `confirmIdentity`；`GET /api/settings/company-setup/status`；稽核。
3. `main.py` 中介層＋白名單；§7-① 題。
4. `company_identity.identity_for_output`／`require_for_output`；共用路徑改走；1.2 三處改走 CI；排程信；§7-② 掃描器與正對照。
5. 前端：notif.js、設定頁 `?setup=1`、`company-setup-required.html`、側欄。
6. 升級 migration（backfill）＋§6 題與演練；`core/upgrade.py` 名稱片段移除。
7. demo 身分（依 Q3）。
8. 文件：MODULE-GUIDE §3.7 補一條、INTEGRATION-POINTS（若模組需要登記「不含本公司資料」）、CORE CHANGELOG。

## 9. 待裁示（交 D／主持／使用者）
- **Q1** 預設 LOGO／favicon 含開發者英文名（使用者曾裁示保留）：販售版改中性預設圖，或未上傳時不顯示？
- **Q2** 開發者本機認定：簽章確認檔為主＋登記機器指紋為輔（建議），或只用其一？
- **Q3** demo：虛構示範公司＋浮水印（建議），或 demo 也強制設定？
- **Q4** 薪資單可手改公司欄位（存在單據上）是否保留；若保留，第二道只驗「已設定」，不驗單據上的值。
- **Q5** §2-②③（版本紀錄內文、docs 與根目錄文件）是否本案一起做，或另開一線。
- **Q6** 必要欄位定案（建議：名稱＋統編（含檢查碼）＋電話或 email 其一；請款單另要銀行欄位）。
