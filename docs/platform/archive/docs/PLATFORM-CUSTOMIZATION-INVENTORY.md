# 平台化盤點：選單／欄位／內容／簽核／輸出可自訂（2026-09-23）

> 使用者目標（2026-09-23）：選單、欄位、對應內容、簽核、輸出都能在網站內自訂義，不再由我們寫好提供。報價單是第一個示範案例，範圍不限於它。
> **硬約束（使用者原話）：「這部分用額外引用，不要直接修改，避免改壞」** ⇒ 平台層是新增的一層，只引用既有模組，不改既有碼。
> 量測基準 HEAD `5c44d58`，行號以此版為準。來源：4 個程式碼盤點 agent＋視窗 hichan-61 文件盤點（392 筆，原始表未入庫）。

---

## 0. 🔴 動工前要先重裁的三件事

新方向和已定案的裁示互相牴觸。守門與規格不會自動翻面，要先改規格再動工。

| # | 既有裁示（原文位置） | 與新方向的衝突 | 建議 |
|---|---|---|---|
| R1 | `SELLABLE-AND-MOBILE-SPEC.md:110,375`「自訂報表產生器——明確不做，不要再提」 | 「輸出可自訂」包含報表 | 改為：**單據輸出（PDF 樣板）可自訂**；多段式報表（營運報表、結案報表）仍維持固定頁籤 |
| R2 | `docs/windows/STATE.md:12295,12310`「WL5 PDF 版型最後做、本輪不做」 | 輸出層的核心就是版型 | WL5 提前，併入本案的輸出層 |
| R3 | `docs/windows/STATE.md:12312`「多租戶不要混進來」 | 無衝突，但要寫明 | 本案是**單一客戶、單機內自訂**，不做多租戶 |

另：`SELLABLE:456`「通用引擎本期不抽」**只指選型導覽那五支複製模組**，不是泛指，不衝突。

---

## 1. 五層現況

| 層 | 已可設定 | 寫死（擋住自訂化） | 可沿用的前例 |
|---|---|---|---|
| **選單** | 自訂角色＝既有模組 key 的組合（`routers/system.py:1961-1985`） | 選單樹寫死在 `frontend/static/sidebar.js`（`buildSidebar` 約 :790-840、`computeFlags` :465-506、`_FILE_MODULE` :552-590）；模組 key 至少 6 處各抄一份（`users.html:718-849`、`helpers/auth.py:22-34`、`db.py:3729-3794`…）；104 處 `require_any_module` | 授權檔 `helpers/licensing.py` 已帶 `modules` 清單，但**沒有任何地方用它擋**（`LICENSE_GATE_ENABLED=False` :94） |
| **欄位** | `pdfShow` 6 欄開關（`quotation-form.html:2302`） | 報價 `q` 是扁平固定鍵（qf:2288-2337）、每區手寫 x-model（qf:1109-1683）；明細欄位與公式寫死（qf:1369-1486、2369-2413：1.05、10%、1%、5% 皆魔術數字） | `vouchers_all.custom_fields`（`db.py:5205`）——**有 schema、零寫入點**，是反面教材 |
| **內容** | 條款組 `quote_terms_presets`（`system.py:1665-1772`，存文字不存 key ⇒ 送出即凍結）；公司身分每據點＋快照（`company_identity.py:82-262`）；完工單用語覆寫（`completion_notes.py:61-107`） | 條款固定 5 鍵（`system.py:1684`）；預覽頁頁首的公司名／統編寫死（qf:2028-2030、2143） | 條款組與身分快照＝「送審時凍結」的做法 |
| **簽核** | 共用引擎 `helpers/tiered_approval.py`：關卡、指定人、部門／處主管、提交人主管鏈、代理人（`approval_delegates`）、統一或個別流程（`approval-settings.html`） | 單據類型清單寫死（:54）；**沒有金額／欄位條件**；簽核狀態 4 種存法（`data_json.approval` vs `approval_json` 欄）；佇列是每型一段手寫 SQL（`quotations.py:3783-4249`）；approve/reject 端點每個 router 複製一份；另有 4 處 superadmin 專用的獨立簽核 | 這層最接近平台化——引擎是純邏輯、無副作用，可直接被包裝 |
| **輸出** | 浮水印以參數傳入；T100 匯出欄位部分可設（`accounting_export.py:114`）；SMTP 設定、每人通知靜音 | 約 15 支 `_build_*_html`（f-string＋內嵌 CSS，無 Jinja）；Edge 啟動碼複製 16+ 次；報價**預覽與正式 PDF 是兩套各自寫死的版面**（qf:1969-2145 vs `pdf_gen.py:96-365`），已有差異；Excel 全寫死；約 50 支通知函式寫死 | `helpers/voucher_template.py:36-78`：**封閉佔位符清單＋存檔時驗證**＝最好的樣板語言前例；`EDGE_PDF_SEMAPHORE`（`helpers/startup.py:57`）共用渲染入口 |

---

## 2. 必須固定的核心欄位（下游在上面計算）

報價 `data_json` 是自由格式，後端**不重算**，直接信任前端算好的 `tot`（`quotations.py:1269-1271`、`pdf_gen.py:478`）。以下欄位被約 10 個模組讀取，**自訂化不可動它們的鍵名與語意**：

| 欄位 | 誰依賴 |
|---|---|
| `quoteNo`、`status`、`dealTag`、`settlement.*` | 狀態機、資料表欄位、報表 |
| `customerName`／`customerId`／`customerTaxId`、`projectName` | 欄位同步、開票／出貨快照、T100 |
| `salesPerson`（→`sales_person_id`） | 擁有者與 IDOR 守門、獎金 |
| `quoteDate`、`validDays` | 成交月判定、儀表板 |
| `tot.total/pretax/tax/subtotal/directMarginPct/netMarginPct`、`taxRate`、`freight`、`discount` | 報表、應收、T100、PDF |
| `items[].id/type/qty/unitPrice/amount/cost/margin` | 開票憑證、請款、精算、派工匯入 |
| `caseRecord.*`（付款項、階段、設備、叫料、角色） | 案件、出納、報表、庫存 |
| `approval.*`、`editHistory`、`docVersions`、據點快照 | 流程與稽核 |

可交給使用者自訂的：聯絡資訊類、備註、區段標題、欄位標籤與順序、額外資訊欄位、版面。

---

## 3. 建議架構：疊加一層，不改原碼

```
┌────────── 平台層（全部新增）──────────┐
│ 定義登錄  doc_types／fields／menus      │ ← 存 system_settings 或新表
│ 樣板      版本化，送審時凍結到單據上    │ ← 比照條款組／身分快照
│ 自訂值    data_json.customFields{}      │ ← 獨立命名空間，不碰核心鍵
│ 規則      簽核條件（金額／欄位 → 關卡） │
│ 輸出      佔位符樣板 → 共用 Edge 渲染   │ ← 比照 voucher_template
└──────────────┬──────────────────────────┘
               │ 只「引用」，不修改
┌──────────────▼──────────────────────────┐
│ 既有模組：tiered_approval／company_identity│
│ ／EDGE_PDF_SEMAPHORE／報價 API／權限守門   │
└──────────────────────────────────────────┘
```

原則：
1. **核心鍵固定**：自訂欄位一律放 `customFields{}`，核心鍵只唯讀引用。
2. **樣板版本化＋凍結**：單據記下樣板 id 與版本，舊單據用當時的結構顯示（目前 `FORM_VERSION` 只顯示、沒存進資料，qf:2224）。
3. **一份定義驅動所有出口**：同一份欄位定義同時產生表單、預覽、PDF。否則會重演「兩套版面各自漂移」（WL7 的教訓）。
4. **權限從同一份登錄來**：選單改由資料驅動時，API 守門必須讀同一份登錄，否則會是「選單有而 API 全 403」，或反過來「API 沒擋」。
5. **驗收釘寫入與讀回**：不可以再出現「有 schema、零寫入點」。

---

## 4. 需要動原碼的點（依約束，每一點都要個別裁示）

完全不改原碼做不到的地方：

| 點 | 為什麼避不開 | 最小侵入做法 |
|---|---|---|
| 報價表單要顯示 `customFields` | 表單是手寫 Alpine | 表單加一個掛載點，由平台層的元件渲染；原欄位不動 |
| 正式 PDF 要印 `customFields` | `_build_quote_html` 是寫死的 f-string | 在頁尾前加一個 hook；或新樣板引擎另產一份，雙軌並行到驗證完成 |
| 選單要列出使用者自訂的頁面 | `sidebar.js` 寫死 | 在 `_navGroups` 渲染前 merge 一份 `GET /api/nav` 的結果；既有項目不動 |
| 簽核要依條件選關卡 | 引擎沒有條件概念 | 在呼叫 `tiered_approval` 前由平台層選 flow，引擎本體不改 |

---

## 5. 建議施作順序

1. **P0 重裁**：§0 的 R1～R3。
2. **P1 定義登錄＋customFields**：先做「報價單加自訂欄位 → 存 → 讀回 → PDF 印出」這一條端到端細線，站得上去才往下。
3. **P2 輸出樣板**：以 `voucher_template.py` 的封閉佔位符模式做單據樣板，先接報價、出貨、完工這類單一單據。
4. **P3 簽核條件**：金額／欄位條件選 flow。
5. **P4 選單登錄**：`GET /api/nav`＋權限共用登錄；同步改寫目前用 regex 掃 `sidebar.js` 的一致性測試。
6. **P5 自訂單據類型**：使用者自建整張新單據（組合 P1～P4）。

---

## 6. 附帶發現（不屬本案，已移交）

- 🔴 `POST /api/contractor-dispatches/{did}/import-to-quote` 漏 commit＋status 參數錯位 ⇒ 見 `docs/windows/HANDOFF-PENDING-2026-09-23.md` T9。
- `frontend/index.html:22-25` 仍放行 `admin`，而 sidebar 的 `canDash` 已不放行，兩處不一致。
- 報價條款順序：預覽（qf:2533-2535）與正式 PDF（`pdf_gen.py:183-187`）的排列不同。
- `FORM_VERSION`：changelog 只記到 V1.2，現值 V2.0，中間沒有紀錄。

## 7. 沒查的

- 各項數字（例如「約 50 支通知」「約 15 支 PDF」）是 agent 讀碼計數，沒有獨立重數。
- 前端其他單據表單（出貨、完工、憑證）的欄位寫死程度：只查了報價單。
- 效能：自訂欄位對報表查詢（`json_extract`）的影響沒量。
