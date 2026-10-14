# 報價單／案件頁框架化：現況盤點、掛勾、耦合與切片（T62）

> 日期：2026-10-14　作者：hichan-3c　狀態：**盤點＋計畫（第一刀 Q1 同批實作）**。基底 `train/t60-int`。
> 範圍：使用者優先序「報價、案件管理、財務」；本文件只做**報價單表單（`quotation-form.html`）＋案件頁（`case-management.html`）**，財務另案。
> 欄位 id 與 1f 的跨模組地圖對齊：**表單欄位 id＝報價單物件的屬性名**（`q.customerName`…），不另造。

## 1. 管理者現在還改不了什麼（逐項）

### 1.1 報價單表單 `quotation-form.html`（261 KB、單一 Alpine 元件）
| 區塊（畫面編號） | 欄位（x-model） | 現況 |
|---|---|---|
| 基（報價資訊） | 報價單號、開立據點 `locationId`、報價日期 `quoteDate`、有效天數 `validDays`、版本、填單人 `salesPerson`／`salesPhone`／`salesEmail`、「顯示成本欄」鈕 | 全部寫死；沒有登記可自訂點（`case/module.json` 的 `customization.pages` 只有 `case-management.html`） |
| 一 客戶資訊 | 公司名稱 `customerName`*、統一編號 `customerTaxId`、聯絡人 `contactName`、電話 `contactPhone`、E-mail `contactEmail`、傳真 `contactFax`、送貨／發票地址 `deliveryAddress` | 寫死 |
| 二 案件資訊 | 案件名稱 `projectName`*、交貨地點 `deliveryLocation` | 寫死 |
| 三 品項明細 | 品項表（含**單價、成本、毛利**等金額欄；成本欄靠 `showCostCols` 與角色遮蔽） | 寫死；**金額欄，第一批不碰** |
| 四 報價合計 | 運費、折扣、稅額、合計… | **金額，不碰** |
| 五 報價條件 | 付款條件 `paymentTerms`、交貨條件 `deliveryTerms`、驗收標準 `acceptanceTerms`、保固條件 `warrantyTerms`、售後服務 `afterSales`（預設文字來自設定中心 `quote_terms`） | 寫死（內容可改，欄位本身不能隱藏／改名／換序） |
| 六 確認簽署 | 簽核／回簽區 | 寫死；**簽核語意，不碰** |
| 成本面板（`cost-panel`） | 內部損益 | **金額，不碰** |
* 星號＝必填。報價單的列表頁 `quotations.html` 同樣沒有登記（欄位：單號、客戶名稱、案件名稱、金額、毛利率、有效天數、填單人、狀態、案件進度、日期）。

### 1.2 案件頁 `case-management.html`
| 範圍 | 現況 | 已有掛勾 |
|---|---|---|
| 左側案件清單（卡片） | 顯示／順序／「業務」標題可自訂 | ✅ `builder_layout.case_management`（t59/t60） |
| 案件資訊分頁的「合約資訊」「專案期間」表單 | 顯示／順序／標籤可自訂 | ✅ 同旗標（forms `contract`、`timeline`，各只登記第一個區塊） |
| **分頁列**（案件資訊／執行管理／承攬商／出貨單／完工單／動態／全部附件／財務／額外支出） | 寫死 | ❌ 無 |
| 案件資訊內其餘區塊（角色、收付款、材料、設備、階段、專案時程、材料叫料…） | 寫死 | ❌ 無（資料在 `caseRecord` 分段存檔，見耦合） |
| 狀態標籤（洽談中／已成案／已結案…、`dealTag`） | 寫死；**值同時是邏輯**（`=== '已成案'` 散在前後端與 SQL） | ❌ 無，且不能直接改（見 §3.3） |
| 自訂欄位 | 案件資訊可加欄位 | ✅ S5 `case_info`（`wip/t61-s5-impl-r5`；旗標 `builder_custom_fields`），**尚未併入 t60/t62** |
| 附件種類（完工單） | 管理者可宣告 | ✅ BP-4 S3（`wip/t62-bp4-s3-r2`） |

## 2. 可用的掛勾（不必新發明）
1. **版面引擎（P9）頁面登記**：`module.json` 的 `customization.pages[]`（list／form／section／field）＋ `frontend/static/layout-pages.json`（旗標、限制說明）＋ `layout-runtime.js` 的 `fShown/fo/fLabel/secLabel` 綁定模式（案件頁合約資訊表單是現成樣板：`x-show="fShown(...)"`＋`:style="fo(...)"`，CSS `order`）。
2. **欄位核心旗標**：`core:true` 的欄位不可隱藏／改名（伺服端驗證 422）。
3. **自訂欄位 S5**：`helpers/builtin_fields.py`（`RECORD_TYPES`、`gate()`、`public_fields()`）；寫入路徑的閘門樣板在 `update_case_record`／`update_quotation`／`create_quotation`。**加 `quotation` 記錄類型即可**（見 Q3）。
4. **遮蔽優先**：金額欄由資料層遮蔽（`moneyMasked`／`quote_money_visible`），版面只決定排版；已有「受限角色發布前後 API 回應不變」的測試樣板。
5. **治理**：版面 kind `layout` 已是 `def_pipeline` 的受管 kind（放寬＝顯示原本隱藏的欄位走待核准）、`preview_hash`、版本帳本。
6. **分頁列可以不加新點種類**：把每個分頁當一個 `list` 的 column（entity `tab`），沿用顯示／順序／標題三個操作；核心分頁（案件資訊）不可隱藏。**零 L0 改動。**

## 3. 耦合清單（欄位改名／隱藏會碰到誰）

### 3.1 一個原則
**版面只改「這個畫面怎麼呈現」，不改資料鍵、不改伺服端、不改 PDF／匯出。** 所以：
- 改標籤（relabel）＝只改表單上那一行字；**報價單 PDF、匯出、報表、列印預覽、客戶回簽頁的字不變**（它們各自寫死標題）。管理者必須在編輯器看到這句警語（`layout-pages.json` 的 `notes`／`relabelIneffective` 機制已有）。
- 隱藏（hide）＝只是不顯示輸入框；已存的值仍在資料裡、仍會進 PDF／匯出。**新建的單據該欄位會是空值（或預設）**——所以必填欄位、會進 PDF 抬頭的欄位必須是核心。

### 3.2 報價單欄位被誰消費（以 `git grep` 為準，不含測試）
| 欄位 | 主要消費者（耦合點） | 第一批 core？ |
|---|---|---|
| `customerName` | 儀表板、請款單、開票申請、額外支出、行事曆、附件搜尋、系統檢查（客戶名稱當顯示／搜尋鍵） | ✅ core（必填） |
| `projectName` | 簽核佇列、附件搜尋、會計傳票提供者、儀表板、自訂模組 | ✅ core（必填） |
| `quoteDate`、`validDays` | 報價單 PDF、儀表板、報表、`quote_terms`、出納、核准流程 | ✅ core |
| 報價單號 | 全系統主鍵 | ✅ core（本來就唯讀） |
| `customerTaxId` | PDF、請款單、開票申請、應收（receivables）——**法定欄位** | ✅ core |
| `contactName`／`contactPhone`／`contactEmail`／`contactFax` | PDF、完工單、出貨單、netplan 匯出、承攬派工；`contactPhone` 也在 S5 的 `case_info` 核心清單 | `contactName`、`contactPhone` core；`contactEmail`、`contactFax` 可隱藏（**個資**：隱藏只影響輸入，告知流程不變） |
| `deliveryAddress`、`deliveryLocation` | PDF、出貨單、完工單、地圖點（`map_points`）、合約資訊（案件頁同名欄位） | `deliveryAddress` core；`deliveryLocation` 可隱藏 |
| `paymentTerms`、`deliveryTerms`、`warrantyTerms`、`acceptanceTerms`、`afterSales` | PDF（條款區）、請款單、`quote_terms` 預設值、設定中心 | 可隱藏／改名；**隱藏仍會印在 PDF**（預設文字）→ 預覽要明講 |
| `salesPerson`／`salesPhone`／`salesEmail`／`salesPersonUsername`／`locationId` | PDF 抬頭、權限（`salesPersonUsername` 是列級權限鍵）、據點抬頭 | 全部 core（權限與抬頭） |

### 3.3 案件頁的耦合
- **`dealTag`／狀態字串是邏輯，不是標籤**：前端 `=== '已成案'`、後端 SQL（`SQL_DEAL_TAG`）、報表、儀表板、財務結案閘門都依字串值。→ **不提供「改狀態字串」**；只考慮第二階段的「顯示標籤對照表」（value→顯示字，純呈現層，所有顯示點都要走同一支 `statusLabel()`），先不做。
- **案件資訊分段存檔（`caseRecord`，`PATCH …/case-record` segments）**：欄位 id＝segment 內的鍵；隱藏表單欄位不會從 segment 刪除。S5 自訂欄位放 `caseRecord.customFields`（「沒有值就沒有鍵」避免誤判 409）。
- **分頁**：隱藏分頁只是不顯示頁籤；分頁內的功能仍可由其他入口到達、權限不變。核心分頁：案件資訊。`財務`、`額外支出` 的金額遮蔽仍由資料層決定（`canSeeFinancial()`），版面不能讓無權者看到。
- 案件清單卡片金額欄、財務分頁：維持現況（金額）。

### 3.4 與財務（只列，不在本批）
報價單金額／合計欄 → 請款、應收、傳票提供者、毛利報表；**欄位 id 不變就不會壞**（版面不改 id）。若日後做「財務」框架化，金額欄一律走「核心＋遮蔽」。

## 4. 切片
| 切片 | 內容 | 旗標 | 核心改動 |
|---|---|---|---|
| **Q1（本批）** | `quotation-form.html` 的非金額區塊（基、一、二、五）接版面引擎：4 個 form、各一個區塊；欄位顯示／順序／標籤；核心欄位如 §3.2 | `builder_layout.quotation_form`（預設關） | 無（`case` 的 module.json 加登記；`layout-pages.json` 加一筆） |
| Q2 | `quotations.html` 清單欄位（金額／毛利率欄登記但沿用 `moneyMasked`）＋案件頁分頁列（tab 當 list） | `quotations`、`case_tabs` | 無 |
| Q3 | 報價單自訂欄位：`builtin_fields.RECORD_TYPES["quotation"]`；寫入閘門＝仿 case_info 的 PUT／POST／finance 預檢；**客戶輸出掃描**（PDF／預覽／回簽頁不得出現自訂欄位）、「使用數」 | `builder_custom_fields`（沿用） | 無（依賴 S5 先併入） |
| Q4 | 狀態「顯示標籤」對照（呈現層）＋案件頁其餘區塊 | 另議 | 視設計 |

## 5. 第一刀 Q1 的邊界（本批實作）
- **登記**：`case/module.json` 新頁 `quotation-form.html`；forms：`qbasic`（基）、`qcustomer`（一）、`qproject`（二）、`qterms`（五）；entity 各為 `qinfo`／`qcustomer`／`qproject`／`qterms`。
- **綁定**：每個輸入的 `.form-group` 加 `x-show="fShown(form,field)"`＋`:style="fo(form,field)"`（CSS `order`；格線子元素 `order` 有效）；標籤用 `fLabel`；區塊標題用 `secLabel`。**不碰**：品項、合計、簽署、成本面板、`showCostCols` 鈕、所有 `@click`／儲存邏輯。
- **OFF 同一性**：旗標關閉時所有綁定回中性值（`fShown`＝true、`fo`＝''、`fLabel`＝預設字）；`MotrixLayout.init` 為 deferred，不發版面請求；`x-show` 不掛在帶行內 `display:` 的元素上（守門 `test_xshow_inline_display`）。
- **不影響**：伺服端 API、PDF、匯出、儲存內容；`hide` 的欄位照樣儲存既有值。
- **測試**：登記有效、核心不可隱藏（422）、fallback＝登記順序、每個登記欄位有綁定、OFF 中性（node 實跑）、受限角色 API 回應發布前後相同。
- **依賴 1f**：欄位 id 與他的跨模組地圖逐一對照（§3.2 的欄位名即 id）。

## 6. 需要的決定（只列需要的）
1. 隱藏非核心條款欄位後 PDF 仍印預設文字——是否接受（建議：接受，並在編輯器明講；要不印得走匯出範本 BP-3）。
2. 個資欄位（`contactEmail`、`contactFax`）可隱藏但**告知流程不變**——同客戶頁的處理，請確認。
3. Q3 需 S5 先併入 t62；順序由 46 決定。

---

## 7. Q3 報價單自訂欄位——已決定的行為（04 審查後確認）
- **複製報價單**（用戶端複製成新單 ⇒ `POST /api/quotations`，舊值＝無）：`customFields` **跟著複製**，並過閘門（旗標關閉時新單不帶；欄位已被停用或型別不符時依閘門規則忽略／400）。理由：自訂資料屬於這張報價單的內容，複製就是複製內容。**改版（-R）同樣保留**。
  - 對照：**案件記錄**的自訂欄位（S5 `case_info`）複製案件時**不複製值**（那是執行期的紀錄，不是報價內容）。兩者規則不同，是刻意的。
- **旗標關閉後**，已存的值仍在資料裡：`GET /api/quotations/{no}` 照常回傳 `customFields`（資料沒有被刪除；畫面不顯示、不能改、整份存檔也不會洗掉）。這是可接受的：看得到這張報價單的人本來就拿得到整份 JSON，自訂欄位被視為與其他欄位同權限（內部人員）。若要在關閉時連 API 也不回，需另開一道回應過濾——目前不做。
- 自訂欄位**不進**報價單 PDF／預覽／回簽頁／內部列印 HTML（測試含正對照）；匯出（案件批次匯出等）不含。要進輸出得明確開旗標（尚無此旗標）。

## 8. 案件頁其餘區塊：現況盤點與下一刀（C 系列）
### 8.1 案件頁還不能自訂的（行號為 `case-management.html`）
| 範圍 | 位置 | 現況 |
|---|---|---|
| 「案件資訊」分頁的**區塊**：健康總覽、合約資訊、人員角色、專案期間、自訂欄位、個資告知、客戶回簽單 | `x-show="activeTab==='biz'"`（:638–849） | 只有「合約資訊」「專案期間」的**欄位**可改（區塊內的顯示／順序／標籤）；**區塊本身**的顯示、順序、標題不行；人員角色三個下拉（業務／執行負責／填單人）完全寫死 |
| 「執行管理」分頁的**子分頁**：執行進度、材料申請、設備登錄、保固備註、待辦事項、專案資訊（成員） | `exec`（:852–1515） | 寫死（第二層分頁列） |
| 區塊標題文字 | 21 處 `cm-section-title` | 只有合約資訊、專案期間走 `secLabel`；其餘寫死 |
| 按鈕（帶入合約資訊、新增完工單、複製、列印告知書…） | 各區塊 | 未登記 `actions`；使用者自訂按鈕目前只有供應商頁工具列 |
| 狀態文字（成案標籤、階段名） | 全頁 | 是邏輯值，不開放改字串；顯示標籤對照屬 3e 的 status_display |
| 財務分頁、額外支出、承攬商、出貨、完工單、動態、全部附件 | 各分頁 | 金額／簽核／流程語意：先不碰（財務分頁整個維持現況） |

### 8.2 已有的掛勾
版面引擎的 list（顯示／標題／順序，物件式 `:style`）、`x-effect` 的分頁回退（`tabFix`）、S5 `case_info` 自訂欄位區塊、`MotrixPublicFlags` 一次讀旗標、核心欄位鎖。**區塊與子分頁都可以用 list 表示（entity `block`、`subtab`）——不需要新的點種類、不改 L0。**

### 8.3 建議切片
| 切片 | 內容 | 旗標 | 風險 |
|---|---|---|---|
| **C1** | 「案件資訊」分頁的區塊當一個 list `bizBlocks`：health／contract／roles／timeline／customFields／privacy／signedBack。**核心**：contract（合約資訊的核心欄位已鎖）、privacy（個資告知，法定，不可隱藏）、signedBack（簽回，流程語意）；**可隱藏／改標題／換順序**：health、roles？（見下）、timeline、customFields。順序用 CSS `order`（biz 分頁容器 ON 時加 `flex column` 的 class，OFF 不加）。 | 沿用 `case_management`（登記檔加說明） | 低：只動顯示；資料與存檔不變；隱藏的區塊不渲染≠刪資料 |
| **C2** | 「執行管理」子分頁 list `execTabs`（同分頁列模式，`tabFix` 同款退回） | 沿用 | 低 |
| **C3** | 區塊標題 `secLabel` 擴到 roles／health 等；`actions` 登記幾個無金額的按鈕（帶入合約資訊、列印告知書不可隱藏）——**只登記，不開放新增按鈕** | 沿用 | 中：按鈕有 endpoint/權限，要逐顆過驗證 |
| 不做 | 人員角色三個下拉的欄位化（涉及負責人指派與列級權限）；任何金額區塊 | — | — |

### 8.4 決定請 PM 確認
1. `roles`（人員角色）區塊要不要允許隱藏？它決定誰是業務／執行負責（列級權限的鍵）；隱藏只是不顯示，值不變。建議：**核心（不可隱藏）**，只允許改標題與換順序。
2. 區塊標題改名不影響 PDF／報表／通知文字（同 §3.1 原則）。
3. 「健康總覽」含逾期應收與付款衍生旗標（U13：衍生旗標不可推論被隱藏的金額）：維持現行可見度規則，版面只能再收窄。
