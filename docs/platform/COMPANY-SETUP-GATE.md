# 販售版：本公司資料設定閘門——調查與設計（E 線 E4，2026-09-28）

> 狀態：**調查＋設計，尚未實作**（主持派工：交 D 審，過了才實作）。
> 依據：CORE-SPEC 裁示表「販售版：輸出文件前強制設定本公司資料」（0f8b16bf＋99702431）。使用者原話（逐字）：
> 「未來販售輸出的檔案，需要對方強制設定自己的公司名稱跟統編等訊息，避免對方用預設我的公司統編輸出報價單等相關文件」；
> 「例如先導航去公司設置，設置完才開放功能」。
> 〔修訂 2026-09-28 18:53：D 設計審 AUDIT-D-E4-company-gate.md（wip/d-audit-train16 1bf0dadd）必修 CG-M1／CG-M2、建議 CG-S1～S5 全收；主持裁示：**綁定主體改為安裝識別檔**（不看硬體）、威脅模型照 CG-S4。被取代的段落以刪除線保留〕
> 〔實作註 2026-09-28（wip/e-company-gate-impl 第一段）：CLI 在 `backend/tools/`（UPDATE-DELIVERY §3.4 先複製包內 backend	ools，預檢才用得到新版）；三個 F3 檔都在 `backend/`；CLI 一律 UTF-8 輸出〕
> 〔修訂 2026-09-28 18:59：D 複審（wip/d-audit-train16 8661a1da §4）CG-M1／CG-M2 關閉；新必修 CG2-M1、建議 CG2-S1～S4 全收〕
> 本文件**不寫任何開發者公司的字面值**（公司名、統編、電話、網域…）：一律以「<字面值>」＋檔案:行號指稱（§3.3 說明為什麼與怎麼存指紋）。
> 盤點方式：兩個唯讀搜尋（輸出點／回退路徑）＋本人逐點抽查（voucher_pdf、legal_params、payslip-form、core/upgrade、.gitattributes 已對照原始碼）。

## 0. 結論

| 項目 | 結論 |
|---|---|
| 對外輸出點 | 後端 34 個端點＋1 個排程信、前端 6 類（§1）。**八種單據 PDF＋自訂模組**經同一條路（`company_identity.location_identity` → `pdf_gen._identity_head/_identity_foot`）；**繞過它的 3 處**：傳票 PDF、個資告知列印、薪資單（前端直讀設定並存進單據） |
| 回退到開發者資料的路徑 | 資料層已封：全新安裝種子是空、`DEFAULT_IDENTITY` 全空、包內沒有 .db。**仍會到客戶手上的 4 類**：預設 LOGO／favicon 圖、掃描器看不到的出貨檔（version_manifest 內文、docs/platform/audit、DR-SOP.md、.gitattributes 註解）、每個客戶庫都會寫入的版本紀錄內文、V9 轉換工具以「名稱片段」認本公司（§2） |
| 「已設定」判準 | **確認紀錄**（本安裝最高管理員在設定頁按「確認本公司資料」）＋**綁本安裝**（安裝識別檔，不看硬體）＋**欄位雜湊一致**；公司統編／名稱命中**開發者指紋**時另需「開發者簽章的確認檔」（綁安裝識別、有到期日）（§3）〔更正 CG-M1：~~綁本機（機器指紋）；登記的開發者機器~~〕 |
| 引導與擋 | 比照既有「必須先改密碼」：auth_middleware 之後擋所有 `/api/`（**精確 (方法, 路由樣板) 白名單**）回 **428** `company_setup_required`〔更正 CG-S1／CG-M2：~~409；白名單例外~~〕；`notif.js` 導向設定頁（最高管理員）或說明頁（其他人）；輸出端 `company_identity.require_for_output()` 第二道（§4、§5） |
| 既有正式機 | **兩階段**：先建安裝識別檔並回報 ⇒ 開發者簽確認檔 ⇒ 升級（套用前乾跑 status，會「未設定」就拒絕升級；套用後以本機 CLI 驗 status，未設定就自動回滾）⇒ 行為不變；現場另有 72 小時暫時放行（§4.3、§6）〔更正 CG-M1：~~登記正式機機器指紋；健檢靠人工回報~~〕 |
| 停擺風險 | 這是正式機第一個「擋全部功能」的機制（`LICENSE_GATE_ENABLED=False`）⇒ 預檢、套用後自動回滾、暫時放行、`status()` 例外處理（§3.6，Q7 裁示 C：中介層放行＋輸出拒絕，且橫幅＋告警不安靜）四層 |
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
〔但書 CG-O2：`/api/uploads/…?pt=`（簽名 token，1 小時）在登入檢查之前放行、不經閘門；token 只能由已受閘門保護的端點簽發 ⇒ 只剩閘門生效前已簽發、1 小時內的尾巴，可忽略〕

## 2. 回退到開發者公司資料的路徑

| # | 路徑 | 會不會到客戶 | 處置（本案或另案） |
|---|---|---|---|
| ① | 預設 `frontend/static/logo.png`／`logo-white.png`／`favicon.png`（含英文公司名；`KEPT_DEFAULT_IMAGES`（_our_company_literals.py:55-59）使用者裁示保留）經 `/api/system/branding/<kind>` 顯示 | **會**（上傳前的畫面；PDF 不嵌 LOGO） | 〔Q1 裁示：維持現狀，不在本案〕~~待裁示 Q1：換成中性預設圖或未上傳時不顯示~~ |
| ② | `backend/version_manifest.json` 內文 5 筆（:491、:1184、:1254、:1261、:1793）含 <字面值>；啟動時寫入客戶庫 `module_versions`（startup.py:526），V9 升上來的安裝全部顯示，且進每日備份（archive.py:2076） | **會** | 〔Q5 裁示：另開一線〕另案：出貨版本紀錄去識別化（改寫內文或出貨時過濾）＋既有客戶庫清理；需使用者裁示（已出貨的紀錄屬 ALLOWED「已出貨版本紀錄」） |
| ③ | `docs/platform/**`（未 export-ignore，141 檔）如 `audit/AUDIT-X-9b-…md:75`、`AUDIT-X-C-batch1.md:116,136,176`；`DR-SOP.md:127`（demo 密碼＝<字面值>）；`.gitattributes:180`（網域註解） | **會**（進 git archive） | 〔Q5 裁示：另開一線〕另案：docs/platform export-ignore（或逐檔）＋DR-SOP 改寫；掃描器擴到 .md 與根目錄（§7-③） |
| ④ | `core/upgrade.py:683-686 _is_our_install`：統編相等**或名稱含兩字片段** ⇒ 把 `V9_COMPANY_DEFAULTS`（:653-659，全部 <字面值>）寫進空白欄位；由出貨的 `tools/platform/upgrade.py:157` 呼叫 | 只有 V9 轉換；**名稱含該片段的客戶會被寫入開發者統編** | **本案修**：改為只認統編指紋（§3.3），刪名稱片段判斷 |
| ⑤ | `db.py:4704-4800 _m106`、`db.py:1032-1063 _m008`（staff 帳號名）、`helpers/auth.py:44`（弱密碼黑名單）、`tools/platform/upgrade_drill.py:96-97` | 凍結 migration／只寫演練暫存／黑名單，不寫進客戶輸出 | 不動（ALLOWED 已登記） |
| ⑥ | 種子 `db.py:769` 空白、`DEFAULT_IDENTITY` 全空、demo 庫每次登入重建（system_settings 清空）、包內無 .db（verify_package.py:108、:159-162 擋） | 不會 | —（守門已在） |

## 3. 「已設定」的判準

### 3.1 為什麼不能用「欄位非空」
從開發者機器複製來的資料庫、或 V9 轉換後的庫，欄位全都「非空」而且是開發者的（記憶〈守門要驗有沒有人做過決定〉）。

### 3.2 確認紀錄（新設定鍵 `company_identity_confirmation`，T1）〔修訂 CG-M1：綁定改安裝識別〕
```json
{"confirmed_by": "<帳號>", "confirmed_at": "<ISO>", "fields_hash": "<sha256>",
 "install": "<sha256(安裝識別)>", "via": "settings_page|upgrade_backfill|signed_file|demo_seed"}
```
**有效**＝以下全成立（`helpers/company_setup.status(db_path, install_root)`，L1、純函式、不 import main）：
1. 紀錄存在且格式正確；
2. `install` 等於本安裝識別檔的雜湊（3.4）；
3. `fields_hash`＝目前必要欄位（正規化後）的雜湊——必要欄位被改過（任何路徑：API、腳本、還原）⇒ 失效，要重新確認；
4. 必要欄位都合格（3.5）；
5. 統編或公司名命中**開發者指紋**（3.3）⇒ 另需「有效的開發者簽章確認檔」（3.3，綁本安裝識別、未過期）。

**只有**設定頁的「確認本公司資料」（`PUT /api/settings/company-profile` 帶 `confirmIdentity: true`，**限最高管理員**）會寫紀錄；一般存檔（例如只改 Google 金鑰）**不會**——否則複製來的庫只要管理員存一次任何設定就「確認」了。寫紀錄同時記稽核（誰、何時、欄位雜湊，不記值）。
回傳 `{configured: bool, reason: <代碼>, via, grace: {active, until}|null}`；reason 代碼：`no_record`／`install_mismatch`／`fields_changed`／`fields_invalid`／`developer_identity_unsigned`／`signed_file_expired`／`status_error`。

### 3.3 開發者指紋與簽章確認檔〔修訂：主持裁示 Q2＋CG-M1、CG-S3、CG-S4〕
- 出貨程式碼內只放**雜湊**：`DEVELOPER_IDENTITY_FP = {sha256("motrix-devco-v1|" + 正規化值)}`，正規化值＝統編只取數字、公司名去空白與「股份有限公司／有限公司」字尾。建置時由開發者本機的一次性工具算出貼入（工具不存字面值）。
- **威脅模型（CG-S4，主持裁示寫明）**：本閘門防的是「**沿用預設**」與「**疏忽**」（忘了設定、從開發者那裡拿到的庫直接用），**不防**會修改程式碼、或整包複製安裝目錄的客戶——程式碼在客戶機器上。**不要把它當成授權或防盜機制來加強**；那是 licensing 的職責。
  - 加鹽雜湊防的是「程式碼與文件裡多一處字面值」，不防還原：統編 8 碼可在數秒內暴力還原（鹽在程式碼裡）；統編是公開登記資料，且已以字面值存在於凍結的 `db.py`／`core/upgrade.py`（ALLOWED）⇒ 可還原不構成新風險。
- **開發者簽章確認檔**（Q2 裁示：主要且唯一的開發者認定方式；~~登記機器指紋為輔~~ 依主持裁示綁定不再看硬體，機器指紋不用）：
  - 檔名 `company_confirmation.sig`，放 `backend/`（與 license.key 同層；〔實作註：~~安裝根目錄~~〕F3：`.gitignore`、`verify_package` 拒絕帶入、每日備份不收、~~不上雲~~〔D SG-S1：只經交付資料夾傳遞、用完刪除，§6.7(c)〕）。
  - 被簽內容（正規化 JSON）：`{"purpose": "motrix-company-confirm-v1", "identity_fp": "<統編指紋>", "install": "<sha256(安裝識別)>", "issued": "YYYY-MM-DD", "expires": "YYYY-MM-DD"}`；簽章原文前綴 `motrix-company-confirm-v1\n`（CG-S3 網域分隔：與交付包共用同一把 Ed25519 金鑰，驗證端只認這個前綴與 `purpose`，交付包的簽章不能被當成確認檔，反之亦然）。
  - 到期日：~~建議簽 3 年；到期前 30 天起~~〔~~2026-09-29 使用者授權（主持）：有效期 30 天；到期前 7 天起~~〕〔有效期兩次變更：2026-09-29 先 30 天（主持轉述授權）⇒ 同日使用者表單改 **365 天**，理由：過期＝全公司暫停，每月重簽風險太高〕有效期 **365 天**；到期前 **30 天**起每日告警一次（速率上限），到期 ⇒ `signed_file_expired` ⇒ **全公司暫停**（中介層 428，直到放入新簽章檔或啟用 §4.3 暫時放行）。
  - 公鑰：〔實作註：交付簽章公鑰（與 `backend/tools/delivery.py` 的 `DELIVERY_PUBKEY_PEM` 相同，題目比對一致；CG-S3 指的就是這把）〕~~沿用 licensing 內嵌的開發／正式公鑰（`env` 記在 status 回傳，開發金鑰簽的檔在正式機上標示）。~~
- `_our_company_literals` 守門：雜湊不是字面值、掃描器看不到 ⇒ 另加一題「指紋常數只出現在 `helpers/company_setup.py`」。

### 3.4 綁本安裝：安裝識別檔〔修訂 CG-M1、CG-O1，主持裁示〕
- **不看硬體**：D 查證 `licensing.machine_fingerprint()` 會因插 USB 網卡、手機 USB 分享（MAC 較小即換）、PowerShell 被擋（改用 MachineGuid、**不丟例外**、整個行程快取）而漂移 ⇒ 用它擋全部功能＝停擺風險。
- `backend/.install_identity`：安裝時產生（`secrets.token_hex(32)`＋建立時間），隨安裝目錄；F3：`.gitignore`、`verify_package` 拒絕帶入、**不進每日／月備份**、不上雲。紀錄與簽章檔只存它的 sha256。
- 產生時機：`backend/tools/company_setup_cli.py ensure-install-id --root <安裝目錄>`（冪等：已有就不動）由 `apply_update.ps1` 在**停服之前**呼叫；新裝由安裝程序呼叫；啟動時仍不存在 ⇒ 產生，並依庫裡有沒有確認紀錄分兩種：
  - 庫裡**沒有**確認紀錄（新裝、第一次啟動）⇒ 記 WARN；
  - 庫裡**已有**確認紀錄 ⇒ 重建＝改掉綁定 ⇒ **ERROR＋系統告警**（與備份告警同一套：邊緣觸發、每日一封）「安裝識別檔遺失，已重建；本公司資料確認紀錄失效，請最高管理員重新確認（開發者正式機：需新簽章檔或暫時放行）」〔CG2-M1；~~產生並記 WARN（第一次啟動）~~〕
- **登記為安裝設定（CG2-M1）**：三個 F3 檔（`.install_identity`、`company_confirmation.sig`、`company_setup_grace.json`）進 `core.paths` 常數＋`core.upgrade.CONFIG_FILES`（:74-83，同 license.key、`.deployed_commit.json`；同 DB-O1 對 `.deployed_modules.json` 的做法）。沒登記的檔在 `classify` 預設是「程式」⇒ 刪除計畫、cleanup-snapshot、完整包套用、V9 轉換、兩種回滾都可能動到它；識別檔一丟，開發者正式機就被擋。
- 後果（寫進 DR-SOP，CG-S5）：只複製資料庫、或還原到新目錄／新機器 ⇒ 識別不同 ⇒ 未設定 ⇒ 最高管理員重新確認一次；開發者正式機 ⇒ 需新簽確認檔或 §4.3 暫時放行。整包複製安裝目錄（連識別檔）⇒ 視為同一安裝（威脅模型外，3.3）。
- ~~首選 `licensing.machine_fingerprint()`（主機板 UUID＋第一張實體網卡 MAC，已有且已測）…讀不到硬體（RuntimeError）⇒ 退用安裝識別檔…網卡更換會讓紀錄失效~~（CG-O1：與現行程式不符——先退到 MachineGuid、最後才丟 RuntimeError；整段取代）

### 3.6 `status()` 自己出錯時〔CG-M1 ⑤；**主持裁示 Q7＝C**（2026-09-28）：中介層放行（避免全公司停擺）＋含本公司資料的輸出一律拒絕（保護面不降級）〕
| 選項 | 行為 | 停擺風險 | 錯印開發者資料的風險 |
|---|---|---|---|
| A 全部視為未設定（fail closed） | 中介層 428＋輸出拒絕 | **高**：`status()` 的任何 bug（壞 JSON、權限、檔案鎖）＝全公司停擺，只能靠 §4.3 暫時放行或回滾 | 無 |
| B 全部視為已設定（fail open） | 照常 | 無 | 有：bug 期間閘門等於不存在（但這是防疏忽的閘門，不是防盜，3.3） |
| **C（建議）中介層 fail open／輸出端 fail closed** | 功能照常可用；**有本公司資料的輸出**拒絕並說明「無法確認本公司資料設定狀態」；兩處都記 ERROR＋系統告警（邊緣觸發、每日一封） | 低：只停「印本公司抬頭的文件」，其餘業務照常；~~§4.3 暫時放行對輸出端同樣有效~~〔更正 CG2-S4：放行是在 `status()` 內判斷的，`status()` 丟例外時讀不到 ⇒ **status_error 時輸出仍拒絕，暫時放行不適用**（Q7 裁示「保護面不降級」一致）；解法是修好判定或回滾〕 | 無：抬頭輸出被擋住 |
- 理由：閘門的目的（不讓預設／開發者資料印在客戶文件上）只需要擋輸出；擋全部功能是「引導」的手段。`status()` 出錯時保住目的、放掉手段，停擺範圍最小。
- 另外兩層讓 C 的輸出端也不太會在正式機觸發：套用前乾跑（§6-1）與套用後 CLI 驗證（§6-2）用同一支 `status()`，會丟例外的新版在停服前就被擋下。
- ~~題：`status()` 丟例外 ⇒ 中介層放行＋ERROR；報價單 PDF 428 帶 `status_error`；告警每日一封（第二次不寄）。~~（由下方「裁示附帶要求」取代）

**裁示附帶要求（〈降級之後它還是會動〉：降級不能安靜）**
1. **ERROR＋每日告警**：`status()` 丟例外 ⇒ 記 ERROR（含例外類型與訊息，不含設定值）；系統告警與**備份告警同級**（`_write_backup_alert` 同一套：邊緣觸發、每日一封、寄超級管理員，mail_types 登記「系統技術」類 `company_setup.status_error`）；恢復正常 ⇒ 告警解除。
2. **全頁橫幅**：中介層放行時在回應標頭帶 `X-Motrix-Company-Setup: status_error`；`notif.js` 看到就在所有頁面頂端顯示橫幅「本公司設定狀態無法判定，對外文件暫停輸出，請聯絡管理員」（不可關閉；標頭消失即移除）。另 `GET /api/settings/company-setup/status` 回 `{configured: null, reason: "status_error"}`，設定頁顯示同一句。
3. **輸出拒絕的訊息與「未設定」不同**：code 分開——未設定 `company_setup_required`（「尚未完成本公司資料設定」，導設定頁）；判定失敗 `company_setup_undetermined`（「本公司設定狀態無法判定，對外文件暫停輸出，請聯絡管理員」，**不導設定頁**：去設定頁按確認解決不了程式錯誤）。狀態碼同為 428；排程報表信判定失敗 ⇒ 不寄、告警寫明「判定失敗」而非「未設定」。
4. **題**：
   - `status()` 丟例外（monkeypatch）⇒ 一般 API（例：`GET /api/customers`）**200** 且帶 `X-Motrix-Company-Setup: status_error`；輸出 API（報價單 PDF、財報 Excel、自訂模組輸出）**428 `company_setup_undetermined`**；告警寫入一次，同日第二次呼叫不重寫；ERROR 有；
   - e2e：一般頁面出現橫幅文字（DOM 終點）；
   - 反向控制①：`status()` 正常且已設定 ⇒ 無標頭、無橫幅、輸出 200、無告警；
   - 反向控制②：`status()` 正常而未設定 ⇒ 中介層 428 `company_setup_required`（不是 undetermined、不是放行）；
   - 反向控制③：例外消失 ⇒ 下一個請求橫幅消失、告警解除。


> ~~### 3.2 確認紀錄（新設定鍵 `company_identity_confirmation`，T1）~~
> ~~```json~~
> ~~{"confirmed_by": "<帳號>", "confirmed_at": "<ISO>", "fields_hash": "<sha256>",~~
> ~~ "binding": "m:<機器指紋>" , "via": "settings_page|upgrade_backfill|signed_file"}~~
> ~~```~~
> ~~**有效**＝以下全成立（`helpers/company_setup.status()`，L1）：~~
> ~~1. 紀錄存在且格式正確；~~
> ~~2. `binding` 等於本機（`licensing.machine_fingerprint()`；讀不到硬體 ⇒ 改用 `i:<安裝識別檔>`，見 3.4）；~~
> ~~3. `fields_hash`＝目前必要欄位（正規化後）的雜湊——必要欄位被改過（任何路徑：API、腳本、還原）⇒ 失效，要重新確認；~~
> ~~4. 必要欄位都合格（3.5）；~~
> ~~5. 統編或公司名命中**開發者指紋**（3.3）⇒ 另需「本機是登記的開發者機器」或「有效的開發者簽章確認檔」。~~
> ~~**只有**設定頁的「確認本公司資料」（`PUT /api/settings/company-profile` 帶 `confirmIdentity: true`，**限最高管理員**）會寫紀錄；一般存檔（例如只改 Google 金鑰）**不會**——否則複製來的庫只要管理員存一次任何設定就「確認」了。寫紀錄同時記稽核（誰、何時、欄位雜湊，不記值）。~~
> ~~### 3.3 開發者指紋怎麼存（不把統編字面值寫到出貨程式碼以外）~~
> ~~- 出貨程式碼內只放**雜湊**：`DEVELOPER_IDENTITY_FP = {sha256("motrix-devco-v1|" + 正規化值)}`，正規化值＝統編只取數字、公司名去空白與「股份有限公司／有限公司」字尾。建置時由開發者本機的一次性工具算出貼入（工具不存字面值）。~~
> ~~- ⚠ **誠實說明**：統編只有 8 碼，有鹽的雜湊仍可在數秒內暴力還原（鹽在程式碼裡）。這個設計的目的是**不再多一處字面值**（文件、測試、設定、log 都不出現），不是保密——統編本來就是公開登記資料，且已以字面值存在於凍結的 `db.py`／`core/upgrade.py`（ALLOWED）。~~
> ~~- 開發者機器登記：`DEVELOPER_MACHINES_FP = {sha256("motrix-devmachine-v1|" + 機器指紋)}`（開發機、正式機）；正式機指紋由正式機回報取得（`MOTRIX-交付\正式機回報`），不寫進文件。~~
> ~~- 硬體更換的出口：開發者以既有交付簽章金鑰（Ed25519，D:\MOTRIX-KEYS\delivery）簽一個確認檔 `company_confirmation.sig`（內容：統編雜湊＋機器指紋＋簽發日），放安裝根目錄（F3，不進包、不上雲）；公鑰已內嵌於 licensing。〔Q2 裁示：以此為主、登記機器為輔〕~~
> ~~- `_our_company_literals` 守門：雜湊不是字面值、掃描器看不到 ⇒ 另加一題「指紋常數只出現在 `helpers/company_setup.py`」。~~
> ~~### 3.4 綁本機~~
> ~~- 首選 `licensing.machine_fingerprint()`（主機板 UUID＋第一張實體網卡 MAC，已有且已測）：只複製資料庫、或整個安裝目錄搬到另一台 ⇒ 失效。~~
> ~~- 讀不到硬體（RuntimeError）⇒ 退用安裝識別檔 `backend/.install_identity`（首次啟動產生的隨機值，F3：`.gitignore`、`verify_package` 拒絕帶入、每日備份不收）；退用時設定頁標明「本機綁定改用安裝識別檔」。~~
> ~~- ⚠ 網卡更換會讓紀錄失效 ⇒ 管理員重新確認一次（非開發者資料不受 3.3 限制，按一次即可）。~~

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

### 4.1 後端（第一道）〔修訂 CG-M2、CG-S1、Q3〕
- 位置：`main.py` `auth_middleware` 在「必須先改密碼」之後、`call_next` 之前（同一套形狀：精確集合＋`code`）。
- 未設定 ⇒ **428 Precondition Required** `{"detail": "尚未完成本公司資料設定", "code": "company_setup_required", "reason": <代碼>, "canFix": <是否最高管理員>, "settingsUrl": "/pages/company-profile-settings.html?setup=1"}`。
  - 為什麼 428（CG-S1）：產品碼有 19 處 409（版本衝突），頁面自己的 fetch 可能在導頁前把 409 顯示成「資料衝突」；403 已被 `must_change_password` 與一般權限不足共用。428 目前產品碼 0 處，語意＝「先滿足前置條件」。`notif.js` 以 `code` 為準（狀態碼只是第二訊號）。
- **白名單 `_COMPANY_SETUP_ALLOWED`：精確 `{(方法, 路由樣板): 理由}`**，~~中介層以 FastAPI 比對到的路由樣板（`request.scope["route"].path`）＋方法比對~~〔更正 CG2-S1：D 探針實測 `@app.middleware("http")` 在 `call_next` **之前** `scope["route"]` 是 None——路由在 call_next 裡才解析〕中介層**自己比對**：啟動時把白名單每條 (方法, 樣板) 對應到 app 路由表裡的那一個 route 物件（找不到 ⇒ 啟動記 ERROR、守門 §7-⑥ 紅），請求進來時對這些 route 呼叫 `route.matches(scope)`（Starlette 的比對，含路徑參數與方法），`Match.FULL` 才放行；不自己拼正規式；**不收萬用字元、不收描述性條目**：

| 方法 | 路由樣板 | 理由 |
|---|---|---|
| （`_MUST_CHANGE_PW_ALLOWED` 全部） | `/api/auth/login`、`/api/auth/logout`、`/api/auth/me`、`PATCH /api/auth/change-password`、`/api/ping` | 帳號本身必要；方法照各路由實際方法逐條列 |
| （`_PUBLIC_API_PATHS` 全部） | 登入 TOTP／QR／WebAuthn 登入、`/api/system/version`、`GET /api/system/branding`、`GET /api/system/branding/{kind}`、`/api/system/deployed-version` … | 本來就不經登入，閘門不看 |
| （`licensing.LICENSE_EXEMPT_PATHS` 全部）| `/api/license/status` 等 | 授權自救（CG-M2：兩道閘門同時生效時，未授權又未設定的安裝要能啟用授權） |
| GET | `/api/settings/company-profile` | 設定頁讀取 |
| PUT | `/api/settings/company-profile` | 設定頁存檔／確認（DELETE 等其他方法擋） |
| PUT | `/api/settings/branding/{kind}` | 設定頁上傳品牌圖（DELETE 不在） |
| GET | `/api/settings/company-setup/status` | 前端判斷導頁 |
| GET | `/api/platform/menu` | 側欄只顯示設定入口 |
| GET | `/api/auth/totp/status` | 帳號安全狀態（設定頁頂端會提示） |
| POST | `/api/auth/totp/setup`、`/api/auth/totp/enable` | 首次綁定 TOTP（帳號必要） |

  - **不在**白名單（CG-M2）：備份還原、模組管理、使用者管理、部署與更新頁、所有業務與報表 API。未設定時需要它們 ⇒ 經 §4.3 暫時放行。
  - 白名單的最終內容以實作時的路由表為準；守門 §7-① 驗每一條存在於路由表、方法相符、理由 ≥ 20 字。
  - 〔實作註 段②〕
    - 比對：~~`route.matches(scope)`~~ 改用 Starlette 的 `compile_path(樣板)` 編出與路由同一套的正規式（`company_setup.compile_allowed／is_allowed`；HEAD 視同 GET）。理由：`route.matches` 需要完整 scope，且同樣板多方法時要逐一找 route 物件；`compile_path` 就是路由自己用的編譯器，規則一致。守門：白名單每條都在路由表且方法相符；**路由表裡每一條不在白名單的 `/api` 路由（>300 條，`/api/uploads/` 靜態除外）逐條打一次都回 428**（新 API 自動被擋的證明）。
    - 表外補兩條（實跑設定頁發現）：`GET /api/settings/branding`（設定頁「品牌與公司名稱」卡讀目前品牌圖狀態）、`DELETE /api/settings/branding/{kind}`（品牌圖「恢復預設」）。兩者限最高管理員、端點自己驗權限，只動品牌圖、不動確認紀錄。上表「DELETE 不在」一句作廢。
    - 標頭 `X-Motrix-Company-Setup: status_error|grace` 在 `_record_request_trail` 之後設（`call_next` 後緊接記軌跡是既有守門）。
    - demo token 段② 先視同已設定；段③ 種虛構示範公司後拿掉豁免。
    - 測試：`conftest` 預設把 `company_setup.status` 釘成已設定（否則全部既有題都 428）；閘門題以 marker `company_gate` 退出這個預設；每個 xdist worker 的識別檔／簽章檔／放行檔經 `FILES_OVERRIDE` 放各自暫存目錄。
    - 未做（併段③）：`/api/platform/menu` 回 `companySetup` 讓側欄只留設定入口（現況：側欄照常，點任何業務頁 ⇒ 該頁 API 428 ⇒ 導回設定頁／說明頁，擋的效果相同，只是多一次跳轉）；設定頁「只有一位最高管理員時建議再設一位」提示。
- 效能：`status()` 結果快取在行程內，以 `company_profile`／`company_identity_confirmation` 的 `updated_at`＋安裝識別檔與簽章檔的 mtime 當版本。
- 非 HTTP 的輸出（每月排程報表信）：走第二道（§5），未設定 ⇒ 不寄、記一則「本公司資料未設定」系統告警（邊緣觸發、每日一封，比照〈告警必須有速率上限〉）。
- demo（Q3 裁示）：demo 庫每次登入重建 ⇒ 重建時種虛構示範公司（名稱含「示範」、統編 `00000000`，~~**不過檢查碼**＝不可能是真公司~~〔更正 段③：`00000000` 加權和為 0，**會通過**檢查碼；「不會被當成真公司」改由名稱含「示範資料」、只在 demo 庫有效的確認紀錄、demo 單據浮水印三者保證〕）＋確認紀錄 `via: "demo_seed"`（`install` 綁 demo 專用常數，只在 demo 庫有效）；demo 模式所有輸出加「示範資料」浮水印；demo 的虛構身分永遠不進正式庫（demo 隔離已有）。

> ~~### 4.1 後端（第一道）~~
> ~~- 位置：`main.py` `auth_middleware` 在「必須先改密碼」之後、`call_next` 之前（同一套形狀：`_MUST_CHANGE_PW_ALLOWED` 那個白名單＋`code`）。~~
> ~~- 未設定 ⇒ `409 {"detail": "尚未完成本公司資料設定", "code": "company_setup_required", "canFix": <是否最高管理員>, "settingsUrl": "/pages/company-profile-settings.html?setup=1"}`。~~
> ~~- 白名單 `_COMPANY_SETUP_ALLOWED`（每條附理由，§7-①）：登入／登出／`/api/auth/me`／改密碼／TOTP 與 Passkey 設定（帳號本身必要功能）、`/api/ping`、`/api/system/version`、健康檢查、`/api/system/branding*`（登入頁）、`/api/settings/company-profile`（GET／PUT）、`/api/settings/company-setup/status`、上傳品牌圖、`/api/platform/menu`（導頁需要）、使用者管理的「自己」端點。**其他全部擋**（預設拒絕：新 API 自動被擋，不必記得加）。~~
> ~~- 效能：`status()` 結果快取在行程內，以 `system_settings` 的 `company_profile`／`company_identity_confirmation` 的 `updated_at` 當版本；機器指紋已有行程快取。~~
> ~~- 非 HTTP 的輸出（每月排程報表信）：走第二道（§5），未設定 ⇒ 不寄、記一則「本公司資料未設定」系統告警（邊緣觸發、每日一封，比照〈告警必須有速率上限〉）。~~
> ~~- demo：demo 庫每次登入重建、公司資料為空 ⇒ 〔Q3 裁示採建議〕：demo 庫種一份明確虛構的示範公司（名稱含「示範」、統編用不合檢查碼的 `00000000`）＋確認紀錄 `via: "demo_seed"`，且 demo 模式所有輸出加「示範資料」浮水印；demo 的虛構身分永遠不進正式庫（demo 隔離已有）。~~

### 4.2 前端
- `static/notif.js` 的 fetch 包裝（已處理 `must_change_password`）加 `company_setup_required`（以 `code` 判斷，428）：最高管理員 ⇒ 導 `company-profile-settings.html?setup=1`；其他人 ⇒ 導新頁 `company-setup-required.html`（「請最高管理員先完成本公司資料設定」＋最高管理員帳號名單不列，只說角色）。
  〔CG-S5：說明頁另寫「最高管理員不在時：請貴公司系統負責人依 DR-SOP〈本公司資料設定〉使用暫時放行（本機、72 小時）」；設定頁在只有一位最高管理員時提示「建議再設一位最高管理員」〕
- 登入後第一個請求（`/api/platform/menu` 在白名單內，回應帶 `companySetup: {configured, canFix}`）⇒ 側欄在未設定時只顯示設定頁入口。
- 設定頁 `?setup=1`：頂端說明「輸出文件會使用以下資料；確認前系統其他功能暫停」＋必要欄位驗證＋「確認本公司資料」鈕（勾選「以上為本公司資料」才可按）；命中開發者指紋 ⇒ 明說「這是 MOTRIX 開發者的公司資料，請改成貴公司資料」，確認鈕停用。

### 4.3 現場安全閥：暫時放行（CG-M1 ③）
- 形式：`backend/company_setup_grace.json`（〔實作註：~~安裝根目錄的~~〕F3：`.gitignore`、`verify_package` 拒絕、不進備份、不上雲），由 **本機 CLI** 建立：
  `python backend/tools/company_setup_cli.py grace --root <安裝目錄> --hours 72 --reason "<原因>"`（只在伺服器本機執行；不開網路端點，免登入＝最高管理員不在也能用）。
- 內容：`{"created": ISO, "until": ISO, "reason", "install": sha256(安裝識別), "created_by_os_user"}`。
- **有效期由伺服器保證**（CG2-S4；檔案是本機檔，任何能寫安裝目錄的人都可以不經 CLI 改它）：
  - 伺服器第一次看到某份放行檔（以**內容雜湊**為鍵）⇒ 記 `first_seen` 到 DB（設定鍵 `company_setup_grace_seen`＝{內容雜湊: first_seen}，T1）＋系統稽核；
  - 有效期＝`min(until, first_seen + 72h)`；`created` 晚於現在（容許 5 分鐘誤差）⇒ 無效；`install` 不符 ⇒ 無效；
  - 內容一改就是「新的一份」⇒ 新的 first_seen、新的稽核與告警（重建看得見，但不禁止；設計本來就允許重建）。
  - CLI 的 preflight／status 讀放行檔時，`first_seen` 取 DB 裡的值，沒有就以「現在」計（CLI 不寫 DB）。
  ~~`until − created ≤ 72 小時`，超過或 `install` 不符 ⇒ 無效。**不可延長**：要再放行得重建（每次都記稽核）。~~
- 效果：`status()` 回 `configured: false, grace: {active: true, until}`；中介層與輸出端**都放行**；**不寫確認紀錄** ⇒ 到期自動恢復擋（複製庫的情境到期後仍擋得住）。
- 可見性：伺服器偵測到新的放行檔 ⇒ 寫系統稽核（誰、原因、到期）；所有頁面頂端橫幅「本公司資料尚未確認，暫時放行至 …」；每日告警一次；到期前 6 小時再提醒一次。
- 放行期間輸出的文件照常用 `company_profile` 的值（那正是要最高管理員儘快確認的理由；橫幅與告警說明這一點）。

## 5. 輸出端第二道
- L1 `company_identity.require_for_output(kind)`：`status()` 不通過 ⇒ 丟 `CompanySetupRequired`（端點轉 **428** 同一個 code；判定失敗 ⇒ `company_setup_undetermined`）〔更正 CG2-S2：~~409~~〕；`kind="payment_request"` 另驗銀行欄位。
- 放在**共用路徑本身**：`location_identity()` 之上加 `identity_for_output(location_id, kind)`，Head/Foot、`doc_template` identity 區塊、`company_heading`／`contact_line`／`footer_line` 的輸出呼叫全部改走它 ⇒ 一處擋住 1.1 全部。
- 1.2 的三處改走 CI：voucher_pdf 改 `identity_for_output`；legal_params 等告知端點改 `company_name()`；薪資單前端預填改讀 `/api/system/branding` 的 LI 欄位，後端產 PDF 時若單據上的公司欄位與本公司不同 ⇒ 以本公司為準並提示〔Q4 裁示：手改保留、第二道只驗已設定 ⇒ ~~以本公司為準並提示~~ 不做〕。
- 1.3 不含本公司資料的輸出不加第二道（第一道已擋），但守門要求逐一登記「不含本公司資料」理由（§7-②）。
- 〔實作註 段③（併 D CG5-M1 必修、CG5-S1／S2 建議）〕
  - 例外：`company_setup.CompanySetupRequired` 繼承 `HTTPException(428)`，`code`＝`company_setup_required`／`company_setup_undetermined`／`company_bank_required`；`main.py` 專屬 handler 回與中介層同形 JSON（`code` 在最外層）。判定走 `company_setup.require()` ⇒ `gate()`（同中介層；grace 放行，undetermined 拒絕）。
  - 位置：~~`identity_for_output` 取代 `location_identity()` 的所有輸出呼叫~~ 改為**輸出文字的 helper 一進來就問**——`company_identity.company_name／company_heading／contact_line／name_pair／footer_line` 與 pdf_gen `_identity_head／_identity_foot／_identity_foot_short`。理由：pdf_gen 的 8 支 builder 要保留 `location_identity` 這個測試接縫（`apply_snapshot` docstring），改 helper 一處即涵蓋 8 種單據、完工單、自訂模組輸出（`doc_template` identity 區塊呼叫的也是這兩支）。`location_identity`／`identity_from_profile` 不擋（登入頁品牌、稽核、閘門自己也用）。`identity_for_output` 仍提供給新呼叫端。
  - 請款單匯款欄位：~~builder 內~~ 放在兩個產生端（`generate_payment_request_pdf_bytes`、簽核後存檔），驗該筆所屬據點解析後的銀行名稱／戶名／帳號；builder 單元題本來就驗「空白資料排得出版面」。
  - 吞例外：輸出端點 `except Exception` 前補 `except HTTPException: raise`（10 處）；守門掃 KNOWN_GATED 端點。
  - 1.2 三處：傳票 `voucher_pdf._company_name` → `company_name()`；個資告知 `legal_params` 回傳公司名與範本代入改走 company_identity（`privacy_notice._company_name_of`，同一套解析；告知文字的雜湊只在「name 與主要據點公司名不同」的安裝會變）；勞報單 Q4：`_payslip_view` 開頭只驗已設定。
  - 月報：`_catchup_monthly_reports` 與 `_send_monthly_report_for` 開頭問第二道；被擋 ⇒ 不寄、`monthly_report_skipped` 告警（每日一次）、`monthly_report_last_sent` 不前進（設定後補寄）。
  - demo：`routers/auth.py` demo 登入重建後 `seed_demo`；`gate(demo=None)` 依 `db.is_demo_mode()` 判 demo 庫、比對 `DEMO_INSTALL`，demo 與正式分開快取；中介層拿掉 demo 豁免；pdf_gen `_identity_head` 在 demo 加「示範資料」浮水印。XLSX／報表 HTML 沒有浮水印版位 ⇒ 靠公司名本身含「示範資料」。
  - 側欄（§4.2）：`/api/platform/menu` 回 `companySetup`；未設定 ⇒ `groups` 與 `layout.groups` 只留設定頁入口（非最高管理員＝空）；在伺服器端過濾，sidebar.js 不改。
  - CG5-S1：已確認的安裝，一般存檔會改動必要欄位（欄位雜湊變）⇒ 409 `company_setup_reconfirm`、**不存**；設定頁把確認卡換成「儲存並確認本公司資料」（同一請求帶 confirmIdentity）。本來就未確認 ⇒ 照常存。
  - CG5-S2：判定失敗後 `ERROR_CACHE_SECONDS`（60）秒內直接回 undetermined 不重算；告警另有行程內「每代碼每日一次」節流（庫讀不到節流紀錄時仍擋得住）。
  - 到期提醒（§4.3、§6.5 原設計，段①未做，段③補）：`observe_expiry`——放行剩 ≤ 6 小時、開發者簽章檔剩 ≤ 30 天（2026-09-29：~~30~~ ⇒ ~~7~~ ⇒ 30，有效期 365 天） ⇒ 告警（每日一次），在 `gate` 重算時呼叫。
  - CG-S5：status 端點對最高管理員回 `superadminCount`；設定頁只有一位時提示再設一位。DR-SOP §4a〈本公司資料設定〉。
  - §2-④：`core.upgrade._is_our_install` 只認統編（去分隔符比對），刪名稱片段；`test_b2_blank_string_fill_passes_verify` 的前提（名稱在、統編空白）隨之改為統編在、名稱空白字串。
  - 測試：`conftest` 預設同時換掉 `status` 與 `gate`（第二道在沒有建庫的單元題也會被呼叫）。
  - 〔D §11 建議，主持視為上車前必做〕E4S3-S1：`company_setup_cli` preflight／status 的 JSON 加 `payment_bank_missing`（主要據點解析後缺哪幾欄；讀不到＝null），`apply_update.ps1`（2026-09-28j）預檢通過後 `Write-CompanyBankNote` 印 `[WARN]`＋`::NOTE:: company_bank_missing=<欄位>`／`company_bank=ok`／`company_bank=unknown`——**只報不擋**；`::RESULT::` 與結果檔不動（欄位與值域固定、結果檔寫入函式與 rollback 逐字相同）、`Invoke-CompanySetupCli` 不動（單模組腳本逐字複製它；A 落地時若複製呼叫點，連這一行一起）。E4S3-S2：`required_problems(profile, demo=False)` 非 demo 庫拒收 `RESERVED_DEMO_UBN`（00000000）⇒ 設定頁確認 422、直接寫庫的判定為 `fields_invalid`；demo 判定照常。

## 6. 既有正式機行為不變的證明〔修訂 CG-M1、CG-S2、CG-S5〕

### 6.1 升級 backfill（核心 migration 新版號；**不丟例外**，CG-S2）
- 本庫沒有確認紀錄，且必要欄位合格，且（統編／名稱未命中開發者指紋，**或**有有效簽章確認檔綁本安裝識別）⇒ 寫確認紀錄 `via: "upgrade_backfill"`（`install`＝本安裝識別；識別檔不存在 ⇒ 先建）。
- 算不出來（讀不到設定、JSON 壞、識別檔寫不進、簽章驗證丟例外…）⇒ **不寫紀錄、回 None（完成）、記 ERROR**——交給 6.2 的預檢與 4.3 安全閥；不回原因字串（那會讓版號不前進、每次啟動重試，而結果不會變），不丟例外（丟 ⇒ 模組 migration 下線、core migration 則啟動失敗 ⇒ 整包回滾，範圍大於閘門本身）。題：五種失敗各一，啟動照常、紀錄不在、ERROR 有。
- ⚠ 其他已上線客戶（目前沒有）：資料非開發者 ⇒ 同樣自動補；是開發者資料 ⇒ 不補（正是要擋的情境）。

### 6.2 開發者正式機：兩階段
1. 〔CGI-S1：第一次升級前，CLI 要**從 staging（包內 `backend\tools`）執行**——安裝目錄裡還沒有這支工具；預檢被拒時 `::RESULT::` 上方的 JSON 帶 `install`（安裝識別雜湊），開發者照這個值簽〕
   **第一階段（不動服務）**：隨下一個一般修補包（或單獨一支腳本）執行 `company_setup_cli.py ensure-install-id --root <安裝目錄>`，把安裝識別的 sha256 寫進正式機回報（`MOTRIX-交付\正式機回報`）。
2. 開發者在自己的機器以交付金鑰簽 `company_confirmation.sig`（`identity_fp`＋`install`＋到期日），經交付資料夾送到正式機，放安裝根目錄。
3. **第二階段（含閘門的版本）**：`apply_update.ps1` 套用。

### 6.3 `apply_update.ps1` 的兩道檢查（CG-M1 ①②）
〔主持裁示 2026-09-28 19:47：**單模組更新包（`apply_module_update.ps1`）同樣做**這兩道檢查（同樣會重啟服務）——逐字複製 `Invoke-CompanySetupCli` 與兩個呼叫點（停服前預檢、套用後檢查＋自動回滾），同樣沒有任何略過參數；由 A 在該腳本落地，逐字守門比照既有共用函式〕

1. **套用前預檢（停服之前）**：以**新版**程式碼（包內 `backend/`，不 import main）執行
   `company_setup_cli.py preflight --db <正式庫> --root <安裝目錄>`：模擬 backfill＋`status()`。
   結果會是「未設定」且沒有有效暫時放行 ⇒ **拒絕升級**、服務不停、`::RESULT:: v=2 status=refused_company_setup reason=<代碼>`；
   〔CG2-S3 補前提〕以下一律視為**拒絕**（不可當成通過）：預檢行程丟例外／非零結束／逾時（上限 60 秒）／輸出不是預期的一行 JSON；結果 `configured: null`（`status_error`）。
   `-Force`（版本比對用）**不略過**預檢。~~真的要略過另開 `-SkipCompanySetupPreflight`，只准人工使用、`::RESULT::` 帶 `company_preflight=skipped`、並寫系統稽核。~~
   〔更正 CG3-M1（D bfdb5003 §5，主持裁示）：正式機 ps1 **沒有任何略過預檢的參數**。理由：套用後 status 會自動回滾、§4.3 的 72 小時放行已涵蓋「先升級後補設定」、預檢壞了要修工具重出包（跳過＝〈降級之後它還是會動〉）；儀表板以 `-Yes` 呼叫擋不住「只准人工」；`::RESULT::` 多一個欄位會動到出口值域。〕
   正式機 Claude 指示寫明各代碼的處置（`developer_identity_unsigned` ⇒ 先做 6.2 的簽章檔；`fields_invalid` ⇒ 先在舊版設定頁補欄位）。
2. **套用後自動健檢**：`/api/ping` 通過之後，再執行 `company_setup_cli.py status --db … --root …`（本機、免登入、直接讀庫與識別檔，**不開新的網路端點**）。
   未設定（且無有效放行）**或 `configured: null`（判定失敗）或 CLI 當掉／逾時** ⇒ 與 ping 失敗同級：**自動回滾**，`::RESULT::` 帶原因〔CG2-S3：新版上線即全公司停止輸出文件，等同故障〕。
3. **手動套用也要先複製 tools**（CG2-S3）：UPDATE-DELIVERY §3.4 步驟 2 先把包內 `backend/tools/*` 複製到安裝目錄再執行 `apply_update.ps1`——預檢與 `ensure-install-id` 是新版 tools 的一部分；正式機 Claude 指示與更新步驟檔都寫明，漏了這步＝舊版 ps1 不會做預檢。
   為什麼不用 HTTP：`/api/ping` 在白名單內驗不到閘門；status 端點要登入，ps1 沒有 token；開一個免登入的 localhost 端點＝多一個公開面（E3-S2 的非 /api 白名單也會多一條）。

### 6.4 證明與演練
1. 題：正式機形狀的庫（BASELINE 演練庫）＋有效簽章檔（測試金鑰）⇒ backfill 後 `status().configured`、報價單 PDF 200；反向控制：同一個庫、無簽章檔 ⇒ 預檢拒絕、中介層 428；簽章檔換一個安裝識別 ⇒ `install_mismatch`；過期 ⇒ `signed_file_expired`。
2. 演練（`apply-run` 演練目錄，正式機條件：排程開、雲端存檔 off）：
   a. 無簽章檔套用 ⇒ 預檢拒絕、服務未停、0 變動；
   b. 放入簽章檔 ⇒ 套用成功、登入無導頁、報價單 PDF／每月報表乾跑照舊；
   c. 刪簽章檔重啟 ⇒ 428 ⇒ 用 CLI 建 72 小時暫時放行 ⇒ 恢復、橫幅出現、稽核有；手動把 `until` 改成 80 小時 ⇒ 無效；
   d. **還原到新目錄**（DR 情境：複製庫＋備份還原，無識別檔）⇒ 未設定 ⇒ 最高管理員確認（非開發者資料）或暫時放行（開發者資料）⇒ 恢復；
   e. 套用後故意讓 `status()` 丟例外（演練用壞設定 JSON）⇒ 依 Q7 裁示的行為。
3. 正式機升級後：`::RESULT::` 已含 status 結果（6.3-2），不再靠人工回報。

### 6.5 DR-SOP 補一節〈本公司資料設定〉（CG-S5）
- 還原到新機器／新目錄 ⇒ 必然未設定（識別檔不在備份裡）⇒ 最高管理員登入後按「確認本公司資料」；開發者正式機 ⇒ 用暫時放行撐到新簽章檔到位。
- 唯一最高管理員不在 ⇒ 伺服器本機建暫時放行（72 小時，記稽核）⇒ 同時處理「第二位最高管理員」。
- 簽章檔到期 ⇒ ~~到期前 7 天起已有告警（有效期 30 天）~~ 到期前 30 天起每日告警（有效期 365 天）〔有效期兩次變更：2026-09-29 先 30 天（主持轉述授權）⇒ 同日使用者表單改 **365 天**，理由：過期＝全公司暫停，每月重簽風險太高〕。
  **到期＝全公司暫停**（D SG-M2）：`signed_file_expired` ⇒ 中介層對全公司 428，直到放入新簽章檔或啟用暫時放行（72 小時）。
  **年度重簽（負責人：主持）**：安裝識別不變 ⇒ **(a) 不必重做**，只做 §6.7 (b)(c)（`--install` 用上次回報的值）；在告警期（到期前 30 天）內完成。

### 6.6 與品牌設定（h-branding）的關係
h-branding 守「**程式碼**不含本公司字面值」＋「單據與頁面經 `company_profile`／`/api/system/branding`」；本案守「**資料**不可以是開發者的、且有人確認過」。兩者互補：本案的指紋常數是雜湊（h-branding 掃描器看不到），另加「指紋只在一處」題；§2-③ 的 .md／根目錄盲區屬另一線（Q5 裁示）。

### 6.7 開發者正式機登記兩步：操作說明（主持 2026-09-29；使用者授權主持執行，CORE-SPEC 6d8b1a17）

> 順序：**(a) → (b) → (c) → 套用第二十一班更新包**。(a)(c) 在正式機，(b) 在開發機。任一步不照做的結果都是「套用前預檢拒絕、正式機不動」（fail closed），不是停擺。
> 以下 `<…>` 都是要代入的值；本文件不寫開發者公司的統編等字面值。

**(a) 正式機：產生並回報安裝識別雜湊**（不寫資料庫、不停服、不重啟；只在 `<安裝目錄>\backend\` 建一個 `.install_identity` 檔，已存在就不動）
1. 更新包已照 UPDATE-DELIVERY §3.4 複製到本機 staging：`<ROOT>\..\motrix-staging\<包名>\`（本步只需要這份包裡的 `backend\` 程式碼，不套用）。
2. 在正式機執行（`python`＝apply_update.ps1 用的同一個）：
   ```
   python <staging>\<包名>\backend\tools\company_setup_cli.py ensure-install-id --root <安裝目錄>
   python <staging>\<包名>\backend\tools\company_setup_cli.py preflight --db <安裝目錄>\backend\motrix_erp.db --root <安裝目錄>
   ```
   - 第一行輸出一行 JSON：`{"created": true|false, "install": "<64 碼十六進位>", "ok": true}`。`install` 就是安裝識別雜湊（不是秘密；是這個安裝目錄的隨機識別，不含任何機器資訊）。
   - 第二行是**唯讀**預檢（在正式庫的記憶體副本上模擬，正式庫一個位元組都不動）。預期 `allowed: false`、`reason: "developer_identity_unsigned"`（正式機的公司資料是開發者的、還沒有簽章檔）；同時看 `payment_bank_missing` 應為 `[]`（E4S3-S1；非空 ⇒ 先在舊版設定頁補匯款欄位）。
3. 把兩行的輸出原樣寫回開發機：`G:\我的雲端硬碟\MOTRIX-交付\正式機回報\<yyyyMMdd_HHmm>_<正式機 commit>_install-id\install_id.json`（兩行 JSON 各一行）。
4. ⚠ 從這一步到套用之間，**不要**用舊版 apply_update／rollback 套任何別的包：舊版腳本的 robocopy 沒有排除 `.install_identity`，會把它刪掉 ⇒ 下次重建的雜湊不同 ⇒ (b) 簽的檔失效（預檢會拒絕，不會停擺，但要重做 (a)(b)）。

**(b) 開發機：用交付私鑰簽確認檔**（私鑰只以路徑傳入；工具不印、不存私鑰內容，簽完以內嵌的交付公鑰自驗，驗不過就不寫檔）
```
cd D:\MOTRIX-PLATFORM            （第二十一班合回前：D:\MOTRIX-PLATFORM-E2，wip/e-company-gate-impl 才有 sign）
D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe backend\tools\company_setup_cli.py sign ^
    --private-key D:\MOTRIX-KEYS\delivery\<交付私鑰檔> ^
    --install <(a) 回報的 install> ^
    --tax <開發者公司統編> ^
    --days 365 ^
    --out "G:\我的雲端硬碟\MOTRIX-交付\company-confirmation\<yyyyMMdd_HHmm>_<install 前 8 碼>\company_confirmation.sig"
```
- 工具只簽**開發者身分**（`--tax` 不在開發者指紋內 ⇒ 拒絕）；`--install` 必須是 64 碼十六進位；`--days` 1～400；輸出檔已存在不覆蓋。
- 輸出一行 JSON：`{"ok": true, "out": …, "install": …, "issued": …, "expires": …}`。有效期 **365 天**（`--days` 預設 365、上限 365）〔有效期兩次變更：2026-09-29 先 30 天（主持轉述授權）⇒ 同日使用者表單改 **365 天**，理由：過期＝全公司暫停，每月重簽風險太高〕；到期前 30 天起正式機每日告警；**到期＝全公司暫停**，年度重簽只做 (b)(c)（§6.5）。
- 簽章檔不進 git（`.gitignore`）、不進正式機備份；交付資料夾是唯一傳遞路徑。

**(c) 正式機：取用確認檔**
1. 把 (b) 的檔複製到 `<安裝目錄>\backend\company_confirmation.sig`（檔名固定）。
2. 再跑一次 (a) 的 `preflight`：預期 `allowed: true`、`reason: "configured"`、`via: "upgrade_backfill"`（模擬升級時自動補確認紀錄）。不是 ⇒ 不套用，把輸出回報開發機（`install_mismatch`＝雜湊不同，重做 (a)(b)；`signed_file_expired`＝重簽）。
3. 預檢通過後，**刪除交付資料夾裡的那一份**（`G:\我的雲端硬碟\MOTRIX-交付\company-confirmation\<…>\`）：確認檔只經交付資料夾傳遞、用完刪除（D SG-S1；檔案本身不是秘密，公開可驗、只綁這一個安裝）。
4. 之後照一般流程套用更新包（apply_update.ps1 自己也會在停服前再跑一次這個預檢，並在 log 印 `::NOTE:: company_bank=ok`）。

**(d) 演練（apply-run 演練目錄；兩條都演）**
- **路徑一：新安裝／一般客戶的確認路徑**（演練庫是新庫）
  1. 演練目錄全新安裝 ⇒ 啟動 ⇒ 最高管理員登入 ⇒ 自動導到「公司資料設定」（`?setup=1`），其他帳號導到說明頁；業務 API 一律 428。
  2. 填測試公司（名稱、**通過檢查碼的測試統編**——不可用 00000000，E4S3-S2 會拒收——、電話）、匯款三欄 ⇒ 勾選「以上為本公司的資料」⇒「確認本公司資料」。
  3. 驗：`company_setup_cli.py status --db <演練庫> --root <演練目錄>` ⇒ `configured: true`、`via: "settings_page"`；報價單 PDF、請款單 PDF 200；側欄完整；改公司名按一般「儲存」⇒ 出現「儲存並確認」（CG5-S1）。
  4. 反向：刪 `<演練目錄>\backend\.install_identity` ⇒ 重啟 ⇒ `install_mismatch`、428、log 有 ERROR＋告警 ⇒ 最高管理員重新確認即恢復。
- **路徑二：開發者簽章路徑**（演練庫放「公司資料為開發者身分」的庫：開發機既有的演練庫形狀，**不用正式機資料**）
  1. 對演練目錄做 (a) ⇒ 預檢 `developer_identity_unsigned`＋`install`。
  2. 做 (b)，`--install` 用演練目錄的值、`--days 7`、`--out` 放演練目錄旁的暫存位置（演練用檔，用完刪）。
  3. 做 (c) ⇒ 預檢 `configured`／`upgrade_backfill` ⇒ 用 apply_update.ps1 套第二十一班包 ⇒ `::RESULT::` status=success、log 有 `::NOTE:: company_bank=…`；套用後 status `configured`；登入無導頁；報價單 PDF 200。
  4. 反向：刪簽章檔重啟 ⇒ 428 ⇒ `company_setup_cli.py grace --root <演練目錄> --hours 72 --reason "演練"` ⇒ 恢復、橫幅出現、稽核有；把放行檔的 `until` 手改成 80 小時 ⇒ 有效期仍以伺服器第一次看到的時間＋72 小時為準。
  5. 演練完刪除演練用的簽章檔與放行檔（不留在任何雲端資料夾）。

> ~~## 6. 既有正式機行為不變的證明~~
> ~~- 升級 migration（L1，核心 migration 新版號）：若本庫沒有確認紀錄，且必要欄位合格，且（統編未命中開發者指紋，**或**本機是登記的開發者機器／有有效簽章確認檔）⇒ 寫確認紀錄 `via: "upgrade_backfill"`；否則不寫（該安裝首次登入會被導向設定頁）。~~
> ~~  - 開發者正式機：機器指紋先登記（出貨前由正式機回報取得）⇒ 升級當下補紀錄 ⇒ 登入後沒有任何導頁、所有輸出照舊。~~
> ~~  - ⚠ 其他已上線客戶（目前沒有）：資料非開發者 ⇒ 同樣自動補；是開發者資料 ⇒ 被擋（正是要擋的情境）。~~
> ~~- 證明方式：~~
> ~~  1. 題：以正式機形狀的庫（BASELINE 演練庫）＋登記機器指紋（monkeypatch）⇒ 升級後 `status().configured` 為真、報價單 PDF 200；反向控制：同一個庫、機器指紋不在登記 ⇒ 409。~~
> ~~  2. 演練：`apply-run` 演練目錄在開發機（已登記）跑一輪：登入→開報價單 PDF→每月報表排程乾跑，全部照舊。~~
> ~~  3. 正式機升級後健檢加一項：`GET /api/settings/company-setup/status` 為 configured（正式機 Claude 指示回報），不是則立即回滾。~~
> ~~- 與品牌設定（h-branding）的關係：h-branding 守「**程式碼**不含本公司字面值」＋「單據與頁面經 `company_profile`／`/api/system/branding`」；本案守「**資料**不可以是開發者的、且有人確認過」。兩者互補：本案的指紋常數是雜湊（h-branding 掃描器看不到），另加「指紋只在一處」題；§2-③ 的 .md／根目錄盲區建議擴大 h-branding 掃描範圍（另案）。~~

## 7. 守門
| # | 守什麼 | 做法 |
|---|---|---|
| ① | 新 API 自動被擋 | 未設定狀態下，列出所有 `/api` 路由（沿用 E3-S2 的路由走訪，含 include 子 router）：白名單外的每一條打一次（路徑參數填假值）⇒ 必須 **428** `company_setup_required`（不可 200／4xx 其他）；白名單每條有理由、存在；正對照：設定完成後同一批不再 428；〔更正 CG2-S2：~~409~~〕反向控制：把一條加進白名單不寫理由 ⇒ 紅 |
| ② | 新輸出點要經第二道 | 掃描器（AST＋文字）找「會產生對外檔案」的程式：`html_to_pdf_bytes`／`run_edge_pdf`／`_render_pdf_via_edge`／`openpyxl.Workbook`／`csv.writer`＋`text/csv`／`Content-Disposition: attachment`／`FileResponse`／`_send_with_attachments`；每一點必須（a）同函式或其端點呼叫 `require_for_output`／`identity_for_output`，或（b）登記在「不含本公司資料」清單附理由。**正對照**：§1 的已知點全部要被掃到（數量下限＋逐一點名 8 種單據 PDF、傳票、報表、規劃書、排程信）；反向控制：合成一個新端點產 XLSX 不經檢查 ⇒ 紅；登記過期 ⇒ 紅 |
| ③ | 不回退到開發者資料 | 全新庫：`status()` 未設定、所有 identity 輸出 **428**；複製庫（帶確認紀錄、**安裝識別**不同）⇒ 未設定；開發者指紋資料**沒有有效簽章檔**時按確認 ⇒ 拒絕；〔更正 CG2-S2：~~409；機器指紋；非登記機器~~〕§2-④ 名稱片段 ⇒ 不再認；demo 輸出不含正式庫資料 |
| ④ | 判準是「有人決定過」 | 欄位全非空但沒有確認紀錄 ⇒ 未設定；改必要欄位（直接寫 DB）⇒ 紀錄失效；只存 Google 金鑰（不帶 confirmIdentity）⇒ 不寫紀錄 |
| ⑥ | 白名單精確（CG-M2） | `_COMPANY_SETUP_ALLOWED` 每條是 (方法, 路由樣板)、存在於 app 路由表、方法相符、理由 ≥ 20 字；不含 `*`；`_MUST_CHANGE_PW_ALLOWED`／`_PUBLIC_API_PATHS`／`LICENSE_EXEMPT_PATHS` 都被涵蓋；反向控制：加 `DELETE /api/settings/company-profile`、加前綴條目、加描述性條目 ⇒ 各自紅 |
| ⑦ | 停擺防線（CG-M1）；Q7 題見 §3.6-4 | preflight／status CLI 與中介層走同一支 `status()`（AST：CLI 不自己判斷）；apply_update.ps1 的 refused_company_setup 與自動回滾路徑有 ps1 題（比照既有 `::RESULT::` 協定題）；暫時放行的到期、不可延長、install 不符、不寫確認紀錄各一題；§3.6 依 Q7 裁示的行為題 |
| ⑧ | F3 檔不外流、也不被當程式處理 | `.install_identity`、`company_confirmation.sig`、`company_setup_grace.json`：`.gitignore` 有、`verify_package` 帶入就拒、每日／月備份不收（掃備份樹）；**在 `core.upgrade.CONFIG_FILES`**；刪除計畫、cleanup-snapshot、apply、兩種 rollback 之後三檔**逐位元組不變**（合成安裝目錄）；庫裡已有確認紀錄而啟動時重建識別檔 ⇒ ERROR＋告警（反向控制：新裝重建 ⇒ WARN、無告警）〔CG2-M1〕 |
| ⑨ | 預檢與套用後不放水（CG2-S3、CG3-M1） | ps1 題：預檢丟例外／逾時／輸出壞 ⇒ refused；`configured:null` ⇒ refused；`-Force` 仍跑預檢；**正式機 ps1 沒有任何略過預檢的參數**（掃 `param(...)` 區塊與所有 `$`旗標：名稱或說明含 skip／bypass＋preflight／company 的一律紅；正對照：合成一個 `-SkipCompanySetupPreflight` ⇒ 紅）；套用後 null／CLI 當掉 ⇒ 自動回滾。演練要測「預檢失敗」⇒ 在**演練副本**注入預檢結果（同 U-M2 的做法），不在正式 ps1 開後門 |
| ⑩ | 放行期限由伺服器保證（CG2-S4） | `until` 設 30 天 ⇒ 有效期仍 ≤ first_seen＋72h；`created` 在未來 ⇒ 無效；改一個字 ⇒ 新 first_seen＋新稽核；status_error 時輸出仍拒絕（放行不適用） |
| ⑪ | 白名單比對方式（CG2-S1） | 中介層以 `route.matches(scope)` 比對：帶路徑參數的白名單（`PUT /api/settings/branding/{kind}`）放行、同路徑 DELETE 擋、相似前綴（`/api/settings/branding-x`）擋；白名單條目在路由表找不到 ⇒ 啟動 ERROR＋守門紅 |
| ⑤ | 指紋只在一處 | 開發者指紋常數只准出現在 `helpers/company_setup.py`；repo 任何地方出現與開發者統編相同的 8 碼字面值 ⇒ 沿用 h-branding 的 ALLOWED 規則 |

## 8. 步驟（實作時，依序）
1. L1 `helpers/company_setup.py`：`status(db_path, install_root)`（純函式）、確認紀錄讀寫、指紋常數、安裝識別檔、簽章確認檔驗證（用途前綴＋到期）、暫時放行檔、統編檢查碼；`backend/tools/company_setup_cli.py`（ensure-install-id／preflight／status／grace）；題（§7-③④⑤⑦⑧）。
   〔~~機器綁定（含安裝識別檔退路）~~ 更正 CG-M1〕
2. `PUT /api/settings/company-profile` 接 `confirmIdentity`；`GET /api/settings/company-setup/status`；稽核。
3. `main.py` 中介層＋白名單；§7-① 題。
4. `company_identity.identity_for_output`／`require_for_output`；共用路徑改走；1.2 三處改走 CI；排程信；§7-② 掃描器與正對照。
5. 前端：notif.js、設定頁 `?setup=1`、`company-setup-required.html`、側欄。
6. 升級 migration（backfill，不丟例外）＋`apply_update.ps1` 預檢與套用後 status＋§6 題與演練；`core/upgrade.py` 名稱片段移除；DR-SOP〈本公司資料設定〉。
7. demo 身分（依 Q3）。
8. 文件：MODULE-GUIDE §3.7 補一條、INTEGRATION-POINTS（若模組需要登記「不含本公司資料」）、CORE CHANGELOG。

## 9. 待裁示（交 D／主持／使用者）〔裁示結果 2026-09-28，CORE-SPEC d27ce2dc，逐條附在各題後〕
- **Q1** 預設 LOGO／favicon 含開發者英文名（使用者曾裁示保留）：販售版改中性預設圖，或未上傳時不顯示？
  〔**裁示（使用者）：維持現狀**——預設 LOGO／favicon 不改；§2-① 列為已知、不在本案處理〕
- **Q2** 開發者本機認定：簽章確認檔為主＋登記機器指紋為輔（建議），或只用其一？
  〔**裁示：簽章確認檔為主＋機器指紋為輔**（照 §3.3 建議）〕
- **Q3** demo：虛構示範公司＋浮水印（建議），或 demo 也強制設定？
  〔**裁示：虛構示範公司＋浮水印**（照 §4.1 建議）〕
- **Q4** 薪資單可手改公司欄位（存在單據上）是否保留；若保留，第二道只驗「已設定」，不驗單據上的值。
  〔**裁示：保留手改；第二道只驗「已設定」**——§5 的「以本公司為準並提示」一句不做〕
- **Q5** §2-②③（版本紀錄內文、docs 與根目錄文件）是否本案一起做，或另開一線。
  〔**裁示：另開一線，不併本案**；但 §2-④ `_is_our_install` 名稱片段判斷**屬本案，照修**〕
- **Q7**（CG-M1 ⑤）`status()` 丟例外時：A 全擋／B 全放／**C（建議）中介層放行＋輸出拒絕**，理由與停擺取捨見 §3.6。
  〔**裁示（主持）：C**，附帶要求①～④ 已寫進 §3.6〕
- **Q6** 必要欄位定案（建議：名稱＋統編（含檢查碼）＋電話或 email 其一；請款單另要銀行欄位）。
  〔**裁示（使用者）：名稱＋統編（檢查碼）＋電話或 email 擇一；請款單另要銀行欄位**（照 §3.5）〕
