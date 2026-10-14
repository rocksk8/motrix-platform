# BP-3 設計：集中輸出漏斗（公式中和）＋宣告式匯出範本模型（僅文件，未跑測試）

> 作者 hichan-1f，2026-10-14。前置：`BP3-EXPORTS-INVENTORY-T61.md`（現況與缺口 G1–G8）；路線圖 `FRAMEWORK-10DAY-ROADMAP-T56.md` §0B.3（BP-3）、`PLATFORM-BUILDER-ARCHITECTURE-T57.md` §2.5／§2.6／§3.2／§3.9。
> 實作約束（b4）：旗標 `builder_exports.enabled` 預設關；**關閉時所有輸出與今天逐位元相同**；實作待 02 釋放機器（~11:30）後，在 `train/t60-int` 之後的 wip 分支。

> **狀態更新（10-14）**：子系統 A 的『先修漏洞』小切片已另開 `wip/t61-xl-safe-r1`（95a7b3c66，無旗標；b4 裁示）：`xl_safe` 補 Tab／CR、三個 xlsx 檔、reports.py 剩餘值格、daily_tasks 與兩支前端 CSV、lodging 併入、AST 守門＋蓄意破壞正對照。本檔 §1 的 `safe_append`／`csv_row`／`export-safe.js` 等『完整漏斗』仍是 BP-3 本體的工作；小切片刻意**不新增公開名稱**（避免 L1 快照變動），只重用 `xl_safe`。

## 0. 兩個子系統，兩種旗標語意（重要）
| 子系統 | 是否受 `builder_exports.enabled` 管 | 理由 |
|---|---|---|
| **A 輸出漏斗（公式中和＋守門）** | **否 — 這是漏洞修補，不是功能**。不放在旗標後面 | 旗標關＝「今天的行為」會保留 G2/G4 的注入面。中和只改「以 `=+-@\t\r` 開頭的字串儲存格」，對正常資料零影響 |
| **B 匯出範本（欄位／標籤／順序／頁首頁尾／浮水印）＋編輯器＋預覽** | **是** | 新功能；關閉＝沒有範本解析，端點走今天的寫死欄位 |

**A 的「逐位元不變」例外必須明講並請 b4/46 認可**：對含觸發字元開頭自由文字的資料，xlsx/csv 的**該格內容會多一個前導 `'`**（這正是目的）。正常資料（金額、日期、一般文字）輸出不變。測試要以「無觸發字元的資料集 ⇒ 位元組相同」＋「有觸發字元 ⇒ 差異只在那些格、且僅多前導 `'`」兩題證明。
> 若 b4 仍希望 A 也走旗標：可做 `builder_exports.neutralize`（預設**開**），但不建議——關掉＝重開漏洞。

---
## 1. 子系統 A：集中輸出漏斗

### 1.1 目標
任何寫進試算表（xlsx／csv）的儲存格，**只能經過一個函式**，且有守門測試讓「繞過」變成紅燈。

### 1.2 單一函式
放在 `helpers/xlsx_out.py`（L1，既有公開面）：
- `neutralize_cell(v)`：`str` 且（去前導空白後）首字元 ∈ `= + - @ \t \r`（也含全形 `＝＋－＠` 與 `\x0b \x0c  `？→ 見 1.5）⇒ 前置 `'`；其他型別原樣。**同時給 xlsx 與 csv 用**（以 lodging `_csv_cell` 的字元集為下限，補上去前導空白判斷）。
- `xl_safe = neutralize_cell`（別名，既有呼叫端與 L1 快照不破）。
- `safe_append(ws, row)`、`safe_cell(ws, r, c, value)`：取代 `ws.append`／`ws.cell(value=…)`。
- `csv_row(values)`：`[neutralize_cell(v) for v in values]`，給 `csv.writer.writerow`。
- 前端：`frontend/static/export-safe.js` 的 `MotrixExport.csvCell(v)`（同一規則，兩份實作用同一組向量測試互驗）。

### 1.3 負數與數字
**只處理 `str`**：真正的負數（`-5.5`）是 `int/float`，不受影響；字串 `"-5"` 才加 `'`（它本來就是自由文字）。需要表達「文字型數字」的欄位由欄位目錄宣告型別（子系統 B 的 `type: number` 一律傳數字型別，不經字串）。

### 1.4 守門（防回退）
新測試 `tests/platform/test_output_funnel_bp3.py`（AST + 行為）：
1. **AST**：在 `modules/**`、`routers/**`、`helpers/**` 中，任何呼叫 `*.append(`／`*.cell(`／`*.writerow(`／`*.writerows(` 且 receiver 名稱可追到 `openpyxl.Workbook()`／`csv.writer(...)` 的位置，其引數必須是 `safe_append`／`safe_cell`／`csv_row`／`neutralize_cell(...)` 的結果，或在**核准清單**（`OUTPUT_FUNNEL_BASELINE.json`，一筆一行，棘輪只准縮小）。
2. **正對照**：造一段 `ws.append([user_text])` 的原始碼，掃描器必須抓到（沿用 `_unscoped_reads` 的做法）。
3. **端到端向量**：對每個匯出端點用含 `=HYPERLINK(...)`、`+1+1`、`-2+3`、`@SUM(1)`、`\t=1`、`\r=1`、全形 `＝` 的客戶名稱建資料，匯出後用 openpyxl 讀回：沒有任何 `data_type == 'f'`；CSV 讀回每列首字元不在觸發集。
4. **balance**：`test_every_xlsx_and_csv_export_endpoint_is_logged…`（既有）擴成同時要求端點所在檔案 import 漏斗。

### 1.5 開放題（請 b4 裁示，不阻擋實作）
- 全形 `＝＋－＠` 與 `\x0b \x0c`：Excel 只認半形，但 LibreOffice／部分試算表接受更多；建議一併中和（成本低、無副作用）。
- 前導 `'` 在 xlsx 會被 Excel 當「文字前綴」隱藏（儲存格內容為去掉 `'` 的字串），在 CSV 則可見。可接受（OWASP 建議做法）。
- `add_pdf_sibling` 的 `xlsx_to_html`：PDF/HTML 已 `html.escape`，不需再中和；但讀 xlsx 回來時的 `'` 前綴要在 PDF 顯示時去掉嗎？**不去掉**（保持與 Excel 看到的一致，並避免二次解析歧義）。

### 1.6 遷移順序（最小 diff，逐檔）
1. 先加函式＋守門（核准清單先收錄所有現況位置 ⇒ 守門初始為綠）。
2. 修 G2：案件批次（`quotations.py:6608`）、外包名冊（`contractors.py:253`）、netplan（`export.py:186–243`）。
3. 修 G4：`daily_tasks/api.py:789`、前端兩支 CSV。
4. 修 G3：`reports.py` 61↔40 逐格（用守門列出的清單當待辦）。
5. 每修一檔就從核准清單移除該檔條目（棘輪縮小）。

---
## 2. 子系統 B：宣告式匯出範本

### 2.1 資料模型（新 kind `export_template`，走既有定義文件庫）
不改既有 `output_template`（它是自訂模組的版面 PDF 範本）；新 kind 避免語意混用。key＝`<exportId>`（例 `case-batch`、`contractors`），scope＝`company`（之後可加 `role:<r>`）。

```json
{
  "version": 1,
  "format": "xlsx",                      // xlsx | csv | pdf（pdf = xlsx 版面經 xlsx_to_html，或 BP-6 後的 PDF 範本）
  "sheetTitle": "案件",                  // 純文字 ≤31 字、禁 []:*?/\
  "columns": [
    {"id": "quote_no", "label": "單號", "width": 14},         // id 只能是該匯出「欄位目錄」裡的 id
    {"id": "customer_name", "label": "客戶"},
    {"id": "total", "label": "金額", "format": "money0"}      // format 只能選目錄允許的格式
  ],
  "header": {"text": "MOTRIX 案件清單", "showCompany": true, "showExportedAt": true},
  "footer": {"text": "內部資料，請勿外流", "showPageNo": true},
  "watermark": {"text": "內部使用", "angle": 30, "opacity": 0.12}   // 僅 pdf；其餘格式忽略並在預覽標明
}
```
- **只收宣告式資料，不收原始 HTML／公式／樣式碼**（護欄 ①）。所有文字欄位：純文字、長度上限（label 20、header／footer 60、浮水印 40 且最多 1 條）、字元白名單（去控制字元與雙向覆寫 U+202A–202E／2066–2069）、輸出一律跳脫＋經子系統 A 中和。
- **欄位目錄（寫死在程式，不由使用者定義）**：每個匯出在其模組登記 `EXPORT_CATALOG[exportId] = {columns: {id: {label, type, money: bool, internal: bool, perm?: …}}, formats, default}`（放 `module.json` 的 `customization.pages[].exports` 旁，或先放 `helpers/export_catalog.py` 的明確表——與 S6 `BUTTON_EXPORTS` 同樣先導作法，不動 L0）。
- `default` ＝今天寫死的欄位／標籤／順序，**旗標關或沒有已發布範本時就用它**（逐位元相同的來源）。

### 2.2 遮蔽優先（masking wins）
1. 欄位目錄標 `money: true` 的欄位：**輸出端**再問一次 `quote_money_visible(user)`／該模組既有的金額權限；沒權限 ⇒ 整欄**省略**（不是留空欄位頭——與今天 `case-batch` 的 `show_money` 行為一致：金額欄值為 None；範本層規則＝照該匯出今天的作法，目錄宣告 `on_masked: "blank"|"omit"`，預設 `blank` 以維持位元不變）。
2. `internal: true` 欄位不得進**客戶通道**的匯出（目前所有 xlsx 均為內部通道；此欄是為 BP-6 客戶版 PDF 預留，驗證器先擋）。
3. 範本**不能新增資料**：欄位只能挑目錄裡已存在、且該使用者今天就看得到的欄位；範本無法讓使用者看到自己本來看不到的列或欄（資料來源仍是端點今天的查詢＋今天的列權限／遮蔽函式）。
4. 欄位頭 `label` 是**顯示文字**，不影響 `perm`；`isMoney` 欄位標籤不得被拿去當檔名變數（A7 守門沿用）。
5. 預覽以**檢視者自己的權限**渲染（或最高管理者指定「以某帳號」，沿用 S6/BP-1 `preview(..., username=)`，且指定他人時**只回該人看得到的欄位**）。

### 2.3 渲染管線（單一處理點）
`helpers/export_templates.py`（新，L1）：
```
resolve(exportId, user, conn)  → template | None      # 旗標關 ⇒ None；無已發布 ⇒ None；None ⇒ 端點用今天寫死的路徑
render_xlsx(template, rows, user, ctx) → bytes         # 只用 safe_cell／safe_append；欄寬／格式只取自目錄
render_csv(template, rows, user, ctx)  → str           # csv_row
preview(conn, caller, draft_body, exportId, username=None, sample="sample"|"real", n=20)
```
- 端點改法（每個匯出一個小 diff）：把「組欄位表頭＋逐列轉值」抽成 `columns_for(exportId)`＋`row_values(row, user)`，由漏斗依範本重排／改名／省略欄位；**預設範本＝今天的順序與標籤**。
- `export_logged`、冷卻、PDF 姊妹、檔名全不動（套在端點外層）。
- PDF 姊妹（`xlsx_to_html`）自動沿用範本的頁首／頁尾／浮水印：加三個**只接受已驗證純文字**的參數，浮水印以 CSS 固定樣式（z-index 在內容下層、不可蓋住程式產生的橫幅）。PDF 範本層的完整化（報價單等 12 個手寫 HTML）是 BP-6，不在本班。

### 2.4 預覽
- 端點 `POST /api/export-templates/{exportId}/preview`（僅最高管理者；旗標關 ⇒ 404；唯讀；**不計匯出次數、不寫 `export.*` 稽核、不發通知**）。
- 輸入：`{draft, user?, sample: "sample"|"real", n}`；輸出：`{columns, rows(前 n), omitted:[{id, reason}], warnings, previewHash}`；PDF 預覽另回 base64 PDF（每頁寫死「預覽」斜浮水印，範本不可關）。
- `real` 取該匯出今天的查詢前 n 列，**經遮蔽後**才進渲染；`sample` 用目錄宣告的樣本列（不碰真實資料）。
- 預覽記稽核 `definitions.previewed`（沿用治理層，發布時比對 `previewHash`，同 S1 `_preview_gate`；加入 `_PREVIEW_ENFORCED_KINDS`）。

### 2.5 編輯器（前端）
`frontend/static/export-editor.js`（浮動面板，風格同 `menu-editor.js`／`custom-fields.js`）：
- 掛在有匯出按鈕的頁面（先導：案件批次匯出、外包名冊、網路規劃——三個正好是 G2 缺口檔，一次補中和＋範本）。
- 功能：勾選／拖曳欄位、改標籤、頁首頁尾文字、浮水印（僅 PDF）；即時預覽表（用預覽端點）；存草稿、看差異、發布；**pending 回應如實顯示**（沿用 `pendingText`）。
- 旗標關：不載入、不顯示按鈕（頁面只多一個 GET 旗標查詢，沿用 S5 作法）。

### 2.6 治理層重用（不新建治理）
- 註冊 kind：`D.register_kind("export_template", label="匯出範本", validator=…)`（同 `user_buttons`）。
- `def_pipeline.ACTIVE_KINDS` 加入 `export_template` ＋比較函式 `_cmp_export_template(old, new)`：
  - **收緊**：移除欄位、縮短頁首頁尾、關浮水印；**中性**：改標籤、改順序、改欄寬（純顯示）；
  - **放寬**：新增欄位（尤其 `money: true` 欄位）、新增通道、任何「無法判斷」＝放寬（D3 嚴格）。
  - `money` 欄位新增 ⇒ 理由字串明寫「新增金額欄位」，第二位最高管理者核准。
- 版本／差異／還原／帳本／快照／`/api/def-governance/export_template/*`：全部沿用，零新程式。
- 非最高管理者看不到定義：沿用 `/api/definitions/*` 的 `require_superadmin`（定義可能含內部標籤與浮水印文字）。

### 2.7 旗標與逐位元不變
- 設定群組 `builder_exports`：`enabled`（int 0/1，預設 0，`risk=ops`），放 `settings_groups.py` 檔尾區塊（同 S5/S6 模式）。
- 旗標關 ⇒ `resolve()` 立即回 None（不查資料庫）⇒ 端點走原本路徑；預覽端點 404；`export-editor.js` 不載入；定義驗證器拒收 `export_template` 發布（同 BP-1 的 `_validate_layout` 作法）。
- **證明方式**：對每個已接線的匯出做「旗標關 vs 基準」的**位元組比對測試**（基準＝改動前同資料同時間凍結後匯出的檔；xlsx 要固定 `creator`／時間戳，或比對解壓後 sheet XML 的儲存格值與樣式，不比整包 zip 位元組——openpyxl 會寫入時間戳）。⚠ 這一點請 46/b4 確認：「逐位元」對 xlsx 實務上是「逐格值＋樣式相同」。

### 2.8 在不同層的測試（寫在實作班，列於此供估工）
| 層 | 測試 |
|---|---|
| 單元 | `neutralize_cell` 向量表（含全形、前導空白、數字不動）；範本驗證器（欄位不在目錄、重複 id、label 過長、雙向字元、浮水印保留字）；`resolve` 旗標關 ⇒ None |
| 遮蔽 | 無金額權限者：範本含金額欄 ⇒ 輸出無金額值；預覽「以某帳號」只含該人可見欄；`internal` 欄位擋 |
| 回歸 | 旗標關位元一致；既有 `test_export_pdf_and_audit` 全綠 |
| 守門 | 漏斗 AST 棘輪＋正對照；`EXEMPT` 登記預覽 POST（唯讀）；`ACTIVE_KINDS` 比較函式三類各一題 |
| e2e（HTTP） | 同 `tools/platform/e2e_t60_t61_on_state.py` 格式：OFF 不變／ON 可用／遮蔽優先／非超管讀不到定義／pending 誠實 |

### 2.9 風險與 UNKNOWN
| 項目 | 說明 |
|---|---|
| 工量 | 路線圖估 21～34 pd 含 PDF；本班只做 xlsx／csv 範本＋漏斗＋三個先導匯出，約 8～12 pd；PDF 範本層與報價單遷移留 BP-6 |
| U-B1 | `reports.py` 61↔40 的逐格盤點量大（單檔 4000 行級），可能要拆成兩個 commit |
| U-B2 | 範本可「重排／省略」欄位，但**下游依賴欄位位置的人工流程**（使用者自己貼進其他表）會被打斷；預設範本＝今天，發布前預覽差異顯示「欄位順序改變」警示 |
| U-B3 | 單元（U0a unit）範圍：匯出查詢的列範圍由端點自己處理，範本層不碰；ratchet 掃描器對新 SELECT 要小心（範本層不寫 SELECT，只吃端點傳進來的 rows） |
| U-B4 | SheetJS 三頁（客戶／料號／供應商）改走伺服端匯出端點是另案（G7）；本班只在文件列出，不動 |
| 需 b4/46 裁示 | ① A 不進旗標是否同意（§0）；② xlsx「逐位元」的定義（§2.7）；③ 先導匯出清單（案件批次、外包名冊、網路規劃）；④ 全形字元是否一併中和（§1.5） |

### 2.10 前端 SheetJS 匯出（客戶端 xlsx；G7）
現況：`customers.html:995`、`parts.html:619`、`suppliers.html:1064` 以 `XLSX.utils.json_to_sheet(rows)` + `XLSX.writeFile` 在瀏覽器產檔；`rows` 是頁面已載入的資料（遮蔽已在 API 層，**範本層不得因此放寬**）。
- **公式風險**：SheetJS `json_to_sheet` 把字串存成字串儲存格（`t="s"`），不是公式，所以 xlsx 本身注入面低於 openpyxl；但同一份 rows 若被另存 CSV／貼進其他試算表仍有風險，且這三條路徑**沒有 `export.*` 稽核、沒有冷卻、不經 `require_for_output`**。
- **做法（兩段）**：
  1. **近程（BP-3 本班）**：三頁的 rows 組好後先過 `MotrixExport.safeRow(row)`（= 前端 `csvSafeCell` 的物件版，只處理字串）；匯出後 `POST /api/export-log {module, name, rows}` 寫一筆 `export.xlsx` 稽核（新唯讀稽核端點，限制：只記 module／name／列數，與 `log_export` 同格式、同冷卻）。
  2. **遠程（BP-3 本體或之後）**：把三個匯出搬到伺服端端點（`export_logged` + `add_pdf_sibling` + 欄位目錄），前端只剩下載按鈕；如此才能套用 §2 的匯出範本（欄位／標籤／順序／頁首頁尾），也才能讓『每個 Excel 匯出同時有 PDF』（使用者規則 2026-09-30）涵蓋這三頁。
- **匯入側（`XLSX.read`）**：本設計不動；匯入的展開／大小防護屬 H-J 寫死項，另案。
- **範本層與 SheetJS 的關係**：在遠程搬遷完成前，這三頁不套匯出範本（旗標關或開都一樣）；編輯器的匯出清單只列已伺服端化的匯出，並在說明寫明『這三個匯出尚未支援自訂』。
- **UNKNOWN**：三頁的 rows 是否含 `perm` 才看得到的欄位（客戶頁的金額、供應商的銀行帳號）——搬遷前要逐欄對照 API 遮蔽，確認前端 rows 不比伺服端匯出多。
