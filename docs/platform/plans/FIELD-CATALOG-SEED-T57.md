# 欄位目錄（A6）種子設計：報價單清單／詳情、案件管理頁、財務／應收應付摘要（僅文件，未跑任何測試）

> **r3（0d 通過 r2 後的兩項補充）**：①判定函式登錄表補 `cashier_access`（第二條財務縫：付款與**完整收款帳號**）與 `payslip_visible`（勞報單佇列），並把**收款人銀行帳號**登記為隱私欄位（`bank` 類，判定 `cashier_access`，不進檔名／帶入／客戶通道，`maskStyle` 依今天為 `partial`＝只留末 4 碼，查看即稽核）；off／on 矩陣擴到 `cashier_access`。②§4.4b 登錄表與獎金敘述一致：**獎金表可見＝出納頁門檻 `finance_access` AND `bonus_visible`**。U13 仍在使用者確認清單。

> **r2（回應 0d 對 r1 `bc688512b` 的稽核：4 項必修＋6 項建議）**：①§3 通道規則更正（`moneyClass=internal` 才禁客戶通道；`filename`／`carry_in` 對所有金額與隱私欄位一律禁）；②新增 §5.0『唯一規則』——**每一種衍生操作**（排序、篩選、搜尋、分組、聚合／計數、快速篩選條件與筆數、警示條件與文字、匯出欄、tooltip、條件式列樣式）都只對『檢視者通過該欄位判定函式』者在**伺服器端**成立，並補 `searchable／groupable／aggregatable` 屬性；③新增 §5.5『欄位可見＝表面門檻 AND 欄位判定』與 §5.6 `maskStyle`（`null`／`strip`／`absent`，r3 另增 `partial`；預設＝今天的遮蔽形狀）；④新增 §5.7 付款衍生事實（`recv_overdue`、`missing_invoice`、`overdue`）的明確決定；⑤判定函式登錄表加『同一函式物件』守門與兩條縫的註記；⑥`derived_ui` 守門；⑦隱私類最低通道規則；⑧對齊 `USER-DEFINED-LOGIC-THREAT-MODEL.md` §1／§5；⑨U3 先黃金比對、U5 已定案；⑩工量 +1 pd。

> 日期：2026-10-13　作者：hichan-5e（T57）　狀態：r1，待非作者稽核（0d）。
> 需求（使用者，經 1c 轉）：**早期功能都要使用者可自訂**——每個畫面顯示哪些資料、匯出（PDF／Excel）的範本、條件式紅色警示與上限、自訂按鈕與選單。地基＝**A6 欄位目錄**：每個模組宣告可顯示的欄位（id、白話名、來源、金額／隱私類別、格式、誰看得到），畫面從目錄挑選與排列。
> 依據（已讀）：`FIELD-LAYOUT-FRAMEWORK-T56.md` r9（`9fca488ec`，§3 目錄、§4 版面鍵、§7 權限、§14 脊柱、§17 登錄）、`SPINE-ENGINE-DESIGN-T57.md` r3（`features[]`、`status`）、`SPINE-FIXTURES-T57.md` r1（夾具與問題代碼）；程式取自本分支基底（M3 `c51fc84d1` 之後、專案毛利% `e5a6b4f9f`），行號僅供起點。
> **本文不重做**脊柱（目錄 schema 大綱、解析器、版面 v2、引擎 E-a～E-f 都在上列文件）。本文補的是它們**缺的那一半**：①真實欄位的種子清單（現在到底寫死了什麼）；②目錄項 schema 的落地欄位表與檔案位置建議；③遮蔽規則如何綁在目錄欄位上、使用者永遠放不出自己看不到的欄位；④匯出範本與紅色警示規則將來怎麼引用目錄（只定介面）；⑤逐頁轉換工量與前三頁建議；⑥未知事項。

## 0. 結論（先看）

1. **種子規模**：報價單清單 22 項（§4.1 表逐列）、報價單詳情 約 55 項（頭部約 20＋品項表 11 欄＋擇一 2＋合計 6＋內部損益約 12＋條款 5；§4.2）、案件管理頁 約 40 項（矩陣與卡片約 18＋詳情區塊約 18＋閘門家族 5）、財務／應收應付 約 36 項。**合計約 150 項（估計，未逐項點算到個位數）**；其中金額類（`isMoney`）約 60 項、隱私類（聯絡資料／統編／地址／獎金）約 14 項（皆為估計）。這些今天**全部寫死在 HTML／JS／SQL 欄位清單裡**（表頭 `<th>`、`x-text`、`select_cols`、`financial_mask` 的鍵清單各一份），沒有一份是機器可讀的。
2. **目錄放哪**：**姊妹檔案** `modules/<模組>/catalog.json`（欄位定義），模組宣告檔 `module.json` 只多兩行——`customization.schema: 2` 與 `features[].catalog.fields_file`／`surfaces`（`SPINE-ENGINE-DESIGN` §3.2 的 `features[].catalog.fields` 改為『引用代號清單，定義在姊妹檔』）。理由：①報價單一個模組就約 100 項欄位，塞進 `module.json` 會讓這個全模組熱點檔每班都衝突；②姊妹檔是純資料、可靜態掃描（沿用 `features[]` 的『宣告式、靜態可掃』原則）；③`module.json` 仍是唯一的『有哪些功能／表面』宣告，沒有第二份。**這是建議，需 1c／0d 裁定**（§8 U1）。
3. **遮蔽綁定的核心規則**（§5）：欄位的可見性只能引用**封閉的判定函式登錄表**（`quote_money_visible`／`money_visible`／`material_money_visible`／`bonus_visible`／`finance_access`…，名稱固定、由程式提供）；**解析器在伺服器端、以檢視者本人逐欄剔除**（不是前端隱藏）；管理者編輯版面、匯出範本、警示規則時，**引用的欄位 id 必須存在於目錄**，且在**畫面（編輯器）**上只列『該管理者自己看得到』的欄位；但儲存的定義本身不含任何資料，**任何一位使用者開啟時都再用他自己的可見性重新剔除**——所以『管理者放進去、別人看不到』是安全的，『使用者放出自己看不到的欄位』是做不到的（編輯器不給挑、後端驗證器也擋）。
4. **匯出範本與警示規則**（§6）：都是**定義文件庫的新 kind**（`export_template` 沿用 `output_template`，`alert_rule` 新增），**只引用目錄欄位 id，不含程式、不含公式**；條件運算子是封閉集合（相等／大小／介於／空白／距今天數…），沒有運算式。『上限』若會**阻擋動作**就不是警示，是**政策**（走設定中心與簽核政策，高影響橫幅），本文只定義『標紅／標記』類，並明列阻擋類不納入。
5. **前三頁建議**（§7）：①**報價單清單**（約 3.5 pd）——唯讀表格、欄位最單純、金額遮蔽已有 5 角色測試模式、已有個人排序偏好可接；②**案件管理頁的財務總覽區塊**（約 3.0 pd）——全是金額、純顯示、可證明遮蔽規則，且不碰 239 KB 的 `quotation-form.html` 版本守門；③**案件管理清單（含矩陣）**（約 3.5 pd）——證明動態欄位家族（閘門）與逐案可見範圍。**報價單詳情／表單**照既有脊柱計畫走 P0～P2 主幹（不在前三頁，避免同檔衝突與 `FORM_VERSION` 守門）。
6. **誠實的未知**（§8 共 12 項）：最影響排程的三項——①清單 API 目前是固定 SQL 欄位集合，『欄位投影』要改 SQL 組裝；②清單裡的『衍生顯示』（成案狀態徽章、停留天數、改版徽章）是前端 JS 函式，必須先搬成『具名格式化器／衍生欄位』才能進目錄；③出納頁的存取判定（`has_finance_access`／出納模組）與報價單金額判定**不是同一個函式**，目錄的判定函式登錄表必須涵蓋它們，否則會漏。

## 1. 目標拆解：使用者要的四件事 ↔ 目錄提供什麼

| 使用者要的 | 目錄／脊柱提供的地基 | 今天已有 | 缺口（誰補） |
|---|---|---|---|
| ① **每個畫面顯示哪些資料** | 目錄＋版面 v2＋解析器（FL §3～§6）；清單表面 `list_view`（S-D1） | 排版器 P9（順序／隱藏／改名）、`user_list_prefs`（只有排序偏好）、模組建構器表單設計器（只服務自訂模組） | **內建頁面沒有登記目錄**（`customization` 除 tender_radar 全空）；清單欄位沒有挑選能力；→ 本文種子＋S-D1 |
| ② **匯出範本（PDF／Excel）** | 同一解析器、不同『輸出通道』；`export_template` 定義引用目錄欄位 | 輸出版型引擎 `doc_template`（薪資單、開票憑據）；案件批次匯出 Excel（欄位寫死）；報價單 PDF 手寫 | 報價單／案件的 Excel 欄位沒有單一來源；→ §6.1 介面 |
| ③ **條件式紅色警示與上限** | 目錄欄位標註『可用於規則』＋規則定義文件 `alert_rule` | 寫死的門檻（§2.3 列 11 處）；`MotrixMargin` 色階；設定中心已有門檻類設定（`warn_pct`） | 規則引擎（封閉運算子）＋伺服器端標註；→ §6.2 介面 |
| ④ **自訂按鈕與選單** | `customization` 點（`menu`、`buttons`）＋**封閉的動作登錄表**（開頁面、套用篩選預設、匯出範本、連結） | `module.json` 的 `pages[].menu`、P9 排版器可 move／hide／relabel 既有按鈕 | **新增按鈕**不存在（現有只能動既有的）；動作登錄表；→ §6.3 介面 |

**共同邊界**（沿用 FL §14）：管理者能做＝挑、排、改名、定尺寸、選政策、設門檻與文字；**仍需程式**＝新增一種欄位、新的計算、新的儲存格畫法、新的單據結構、涉及金流的連動；**脊柱不做**＝自訂公式、自訂程式、第二套權限、第二套版本表。

## 2. 現況盤點（本文新增的、FL §1 沒有的細節）

### 2.1 同一份資料，現在有幾份『欄位宣告』

| 面向 | 報價單清單 | 報價單表單 | 案件管理頁 | 出納／財務 |
|---|---|---|---|---|
| 欄位集合 | `quotations.html` 表頭 11 欄寫死；API `select_cols`（`api/quotations.py` 約 :821–850）另一份 | 編輯表 `<th>` 11 欄＋預覽表另一份＋`pdf_gen._build_quote_html` 第三份 | 矩陣 `case-management.html` ~:100–125 寫死；案件卡另一份；詳情各分頁 `fi-label` 寫死 | 各頁 `<th>` 寫死（`cashier.html` 至少 6 張表） |
| 金額遮蔽 | `QUOTATION_MONEY_COLS` 以**鍵名**遮（`mask_row`） | `ITEM_MONEY_KEYS`／`QUOTE_MONEY_KEYS` 以鍵名**剝除** | 前端 `canSeeFinancial()` 隱藏＋後端 `money_visible` 剝除 `settlement`／`caseRecord.payment` | 端點層 `_require_view_access`（財務角色）／`_bonus_visible`（superadmin 或出納模組） |
| 格式化 | `toLocaleString`、`toFixed(1)+'%'`、`slice(0,10)`、`MotrixMargin.style` | 同左＋`MotrixLegalRound` | 同左＋`caseSettleFmt` | 各頁各寫 |
| 逐案可見範圍 | `row_access`（`case`／scope read） | 同左（`_guard_case`） | 同左＋`case_page_readable` | 依端點 |

**結論**：要做到『欄位使用者可自訂』，目錄必須**同時取代四份宣告**（欄位集合、遮蔽鍵清單、格式化、可見性判定）並以雙向守門維持一致——FL §3 已有『目錄 ⇔ `financial_mask` 雙向一致』守門設計，本文種子是它的**資料**。

### 2.2 清單 API 的限制（影響目錄設計）
- `GET /api/quotations` 的欄位是**固定 SQL 組裝**（含 6 個子查詢：`current_stage`、`stage_total/done/overdue`、`missing_invoice/notes`），不管畫面要不要都算。目錄若要『只算被挑選的欄位』，需要把 SQL 欄位集合改為**由目錄的 `source` 屬性組裝**（§8 U3）。
- 排序／搜尋／篩選：伺服器端白名單（報價單清單只認 `quote_date`／`customer_name`／`total` 三個排序鍵；看不到金額者不可依金額排序，因為順序本身會洩漏）。目錄的 `sortable`／`filterable` 屬性必須沿用同一條規則（§5.4）。

### 2.3 寫死的條件式標色／門檻（警示規則的第一批遷移對象）

| # | 位置 | 規則（今天） | 類別 |
|---|---|---|---|
| A1 | `quotations.html` `agingOf` | 草稿停留 >7 天『溫』、>30 天『舊』；送審中 ≥2 天『溫』、≥4 天『舊』 | 時間門檻（欄位：更新日） |
| A2 | `quotations.html` 有效天數欄 | `valid_days > 30` 顯示紅字『需審核』 | 數值門檻（與簽核原因 `compute_approval_reasons` 同源） |
| A3 | `static/margin-tone.js` | 直接毛利率 <30 危險、<40 警示（清單、表單、案件頁共用） | 數值門檻（K01 設定化未落地） |
| A4 | `quotation-form.html` 品項列 | `margin < 0.30 && cost > 0` 顯示『需審核』 | 數值門檻（簽核原因） |
| A5 | `quotation-form.html` 損益 | 營業利益率 <12 紅、<20 黃（`TARGET_MARGIN_PCT = 12`） | 數值門檻 |
| A6 | `case-management` 閘門 | 閘門燈號 `gateTone`（blocked＝琥珀、crit＝逾期／退回） | 狀態對照 |
| A7 | `case-management` 快速篩選 | `stage_overdue`、`recv_overdue`、`missing_docs` | 篩選＋計數 |
| A8 | 出納 | `overdue`（應收預定日已過） | 時間門檻 |
| A9 | 專案毛利% | `project_margin.warn_pct`（**唯一已設定化**，預設 0） | 數值門檻（設定中心） |
| A10 | 簽核佇列 | 停留 2／4 天（與 A1 的送審門檻『同一組』，程式註解自述） | 時間門檻 |
| A11 | 稅別／折讓 | `taxRate <5` 顯示警示色（需核准） | 數值門檻 |

這 11 處正好示範『規則＝欄位＋運算子＋門檻＋效果』的形狀（§6.2），也是第一批可『資料化』的對象；其中 A2／A4／A10 與簽核邏輯同源，**遷移時顯示規則可資料化、簽核判定本身不可**（簽核原因是政策，不是警示）。

## 3. 目錄項 schema（落地欄位表）

FL §3 已列屬性概念；SPINE-FIXTURES 已提議問題代碼。本節把它們定成**可實作的欄位表**（`catalog.json` 內每一項的鍵）。**〔格式待 2b〕**＝以 2b 的 `core/spine.py` 最終鍵名為準。

```json
{
  "schema": 1,
  "owner": "case",
  "surfaces": [
    {"key": "quotation_list", "type": "list", "labelDefault": "報價單清單",
     "rowScope": {"kind": "case", "scope": "read"},
     "fields": ["quote_no", "customer_name", "total", "direct_margin_pct"]}
  ],
  "fields": [
    {"id": "direct_margin_pct", "label": "毛利率", "type": "percent", "format": "pct1",
     "source": {"kind": "stored", "column": "direct_margin_pct"},
     "group": "pricing", "isMoney": true, "moneyClass": "internal",
     "visibility": "quote_money_visible", "maskKeys": ["direct_margin_pct"],
     "lock": "display", "channels": ["screen", "internal_excel"],
     "list": {"defaultVisible": true, "width": "narrow", "align": "right"},
     "ops": {"sortable": false, "filterable": false, "searchable": false, "groupable": false, "aggregatable": false,
             "quickFilterable": false, "ruleUsable": false, "tooltip": false, "opsRequireVisibility": true},
     "maskStyle": "null",
     "rule": {"usable": true, "valueType": "percent"},
     "tone": "margin_tone"}
  ]
}
```

| 鍵 | 必填 | 說明 |
|---|---|---|
| `id` | ✔ | snake_case，模組內唯一，**永不改名**（改名＝新欄位）；版面、範本、規則都用它引用 |
| `label` | ✔ | 預設白話名稱（管理者可 relabel）；守門：不得含鍵名／代碼 |
| `type` | ✔ | `text／number／money／percent／date／datetime／enum／longtext／badge／link／count` |
| `format` | 金額、百分比、日期必填 | **具名格式化器**（D2）：`money_ntd`、`pct1`、`date10`、`datetime_min`、`count`…；格式化器是程式登錄，不接受管理者字串 |
| `source` | ✔ | `stored`（欄位／JSON 路徑）／`computed`（來源函式名）／`joined`（連動其他表，標明表）／`derived_ui`（目前在前端算的衍生值，**過渡標記**，搬到後端前不得進匯出或規則） |
| `group` | ✔ | 沿用 F7 FieldGroup（`header／items／pricing／cost／terms／case.payment…`） |
| `isMoney` | ✔ | 金額／價格／比率類（對應 `financial_mask`）；**與 `moneyClass` 獨立** |
| `moneyClass` | ✔ | `public`（客戶可見）／`internal`（成本、毛利、管銷…）／`none` |
| `privacyClass` | ✔ | **本文新增（使用者要求『金額／隱私類別』）**：`none`／`contact`（電話、E-mail、傳真）／`identity`（統編、身分證字號）／`address`／`payroll`（薪資、獎金）／`bank`（r3：銀行帳號、戶名；與 `identity` 同級管制）。**最低通道規則（0d 建議 7，現在就生效）**：`identity／payroll／contact／address／bank` 一律**預設不含** `filename`、`carry_in`、`customer_excel`（`bank` 另不含任何客戶與匯出通道）；是否進 `customer_pdf` 由欄位自己的 `channels` 明列（例：客戶統編、聯絡人本來就印在客戶版，且受 `pdfShow` 控制）；`payroll`（獎金）只能經 `bonus_visible` **且**通過出納頁門檻（§5.5）；更細的隱私判定留 §8 U6 |
| `visibility` | ✔（`isMoney` 真或 `privacyClass` 非 `none` 時） | 判定函式 id（封閉登錄表，§5.1）；解析器逐檢視者呼叫；缺少 ⇒ 驗證失敗 `money_without_visibility_fn` |
| `maskKeys` | `isMoney` 真時 ✔ | 此欄位對應的**資料鍵**（`financial_mask` 清單內的鍵名）；雙向守門用 |
| `lock` | ✔ | `core`（不可隱藏）／`display`（可隱藏、改名、移動）／`required`（業務必填連動，不可隱藏） |
| `channels` | ✔ | `screen`（畫面編輯）、`preview`（畫面預覽）、`customer_pdf`、`internal_pdf`、`internal_excel`、`customer_excel`、`filename`、`carry_in`（帶入其他單據）、`rule`（可用於警示規則）。**規則（r2 更正）**：①`moneyClass=internal` ⇒ **永遠不得**含任何客戶通道（`customer_pdf`／`customer_excel`／回簽頁／客戶預覽）；②`isMoney` 真且 `moneyClass=public`（例：單價、金額）⇒ **可以**進客戶通道（客戶版報價單本來就印價格）；③**所有** `isMoney` 與 `privacyClass≠none` 欄位 ⇒ **一律不得**含 `filename`、`carry_in`；④`rule` 通道另受 §5.0 與 §5.7 限制 |
| `list` | 清單表面必填 | `sortable`、`filterable`、`defaultVisible`、`width`（檔位）、`align` |
| `ops` | ✔ | **衍生操作許可（r2，§5.0）**：`sortable／filterable／searchable／groupable／aggregatable`（含計數）／`quickFilterable`／`ruleUsable`／`tooltip`。**`isMoney` 真或 `privacyClass≠none` 者全部預設 false**；要開某項必須同時宣告 `opsRequireVisibility: true`（承諾由解析器以欄位判定函式把關，§5.0），否則驗證失敗 `ops_without_visibility_guard` |
| `maskStyle` | `isMoney` 真時 ✔ | 遮蔽後的**回應形狀**（r2，§5.6）：`null`（鍵保留、值置 None、列加 `moneyMasked`，例：報價單清單）／`strip`（鍵剝除，例：報價單與案件詳情）／`absent`（鍵不存在，例：專案毛利%）。**預設＝今天各表面的實際形狀**，使『預設＝今天』黃金比對成立 |
| `rule` | 選填 | `usable`（可被警示規則引用）、`valueType`（決定可用運算子） |
| `tone` | 選填 | 具名色階函式（`margin_tone`、`aging_tone`、`gate_tone`）；管理者不選，由規則覆寫 |
| `editable` | 表單表面 | 使用者輸入／系統計算（唯讀） |
| `dynamicFamily` | 選填 | 欄位家族（閘門、階段）：`{"source": "gate_heads"}`，成員由程式提供、目錄只登記家族（§4.3） |
| `since`／`deprecated` | 選填 | 版本註記；移除欄位走 `dropped`（FL §8），不悄悄略過 |

**問題代碼**（沿用 `SPINE-FIXTURES-T57` §3，本文新增者標★）：`catalog_mask_mismatch`、`money_without_visibility_fn`、`bad_surface_key`；`money_in_customer_channel`（**r2 更正判準**：`moneyClass=internal` 含任何客戶通道才算；`isMoney`＋`public` 的客戶通道**不是**違規，夾具需有此反例『應通過』與正對照『internal 欄位放進 `customer_pdf` 必須失敗』）；★`money_or_privacy_in_filename_or_carry_in`（`filename`／`carry_in` 含任何 `isMoney` 或隱私欄位）、★`privacy_without_visibility_fn`、★`ops_without_visibility_guard`、★`unknown_ops_key`、★`derived_ui_in_export_or_rule`、★`unknown_visibility_fn`、★`unknown_formatter`、★`duplicate_field_id`、★`mask_style_mismatch`（與該表面今天的遮蔽形狀不符）、★`rule_input_forbidden`（§5.7）。

## 4. 種子清單

> 欄位說明：**判定**＝可見性判定函式；**遮**＝今天的遮蔽機制（鍵剝除 K／清單列置空 R／前端隱藏 F／端點拒絕 E）；金額欄標 **$**（`isMoney`），類別 pub／int。
> 所有『今天』欄的事實取自程式（檔案行號供起點）；標〔待核〕者是我沒有逐行核對的。

### 4.1 報價單清單（`quotations.html`＋`GET /api/quotations`）— 表面 `module:case.quotation_list`

表面屬性：`rowScope = row_access("case", scope=read)`（業務只看自己的，admin+ 全部）；個人層排序偏好沿用 `user_list_prefs`（key `quotations`）。

| id | 白話名 | 型別／格式化器 | 來源（今天） | 類別 | 判定 | 遮 | 今天的清單欄 | 備註 |
|---|---|---|---|---|---|---|---|---|
| `quote_no` | 報價單號 | text／link | SQL `quote_no` | — | — | — | ✔（核心，可點開） | 核心欄；含『改版』徽章（`-Rn` 後綴，前端正規式） |
| `revision_badge` | 改版標記 | badge | **derived_ui**：`/-R\d+$/` | — | — | — | 併在單號欄 | 衍生；建議後端 `computed`（`is_revision`） |
| `customer_name` | 客戶名稱 | text | SQL `customer_name` | — | — | — | ✔ | 排序鍵 |
| `project_name` | 案件名稱 | text | SQL `project_name` | — | — | — | ✔ | |
| `total` | 金額（含稅） | money／`money_ntd` | SQL `total`（0 顯示『—』） | $ **pub**（客戶版會印；但在清單只有 `quote_money_visible` 者可見） | `quote_money_visible` | **R**（`QUOTATION_MONEY_COLS` 置 None＋`moneyMasked`） | ✔ | 排序鍵（看不到者忽略） |
| `pretax` | 金額（未稅） | money／`money_ntd` | SQL `pretax` | $ | `quote_money_visible` | R | ✘（API 有、表頭無） | 專案毛利%的分母 |
| `direct_margin_pct` | 毛利率 | percent／`pct1` | SQL `direct_margin_pct` | $ int | `quote_money_visible` | R | ✔（色階 `margin_tone`＝A3） | |
| `net_margin_pct` | 營業利益率 | percent／`pct1` | SQL `net_margin_pct` | $ int | `quote_money_visible` | R | ✘ | |
| `project_margin_pct` | 專案毛利% | percent／`pct1` | 計算（Python，`project_margin()`） | $ int | `quote_money_visible` | **鍵不存在**（不是 None） | ✘（預設隱藏的可選欄） | 專案毛利% 設計 §3 |
| `valid_days` | 有效天數 | number／`count` | SQL `valid_days`（預設 30） | — | — | — | ✔（>30 紅『需審核』＝A2） | |
| `sales_person` | 填單人 | text | SQL `sales_person` | — | — | — | ✔ | 篩選鍵 |
| `status` | 簽核狀態 | enum | SQL `status` | — | — | — | 併入狀態欄 | 7 值：草稿／待審核／簽核中／已核准／已送出／已取消／已拒絕 |
| `deal_tag` | 成案標記 | enum | SQL（`SQL_DEAL_TAG` 先欄位、後 `$.dealTag`） | — | — | — | ✔（『案件進度』欄的下拉＝**可編輯動作**，不是純顯示） | 欄位同時是**操作**，目錄需 `editable` 與動作登錄（§6.3） |
| `display_status` | 狀態徽章 | badge | **derived_ui**：`dealDisplayStatus(q)` | — | — | — | ✔（『狀態』欄） | 把 `status`＋`deal_tag` 合成一個徽章；建議後端 `computed` 並供 `label_map`（F5） |
| `aging` | 停留天數 | badge／`aging_tone` | **derived_ui**：`agingOf(q)`（草稿／送審才有） | — | — | — | 併在狀態欄 | 規則 A1；先搬後端 `computed`（`updated_at` 與生命週期） |
| `quote_date` | 報價日期 | date／`date10` | SQL `quote_date`，缺則 `created_at` | — | — | — | ✔ | 排序鍵；月份篩選用 |
| `updated_at` | 最後異動 | datetime | SQL | — | — | — | ✘ | `aging` 的來源 |
| `edit_badge` | 修改標記 | badge | SQL 子查詢 `edit_count`＋`edit_last_json`（作者、時間、類型） | — | — | — | ✔（單號欄下方） | 含**人名**（privacy: none，但屬稽核資訊；〔待核〕是否要 `privacyClass`） |
| `settle_status` | 精算狀態 | enum | SQL `SQL_SETTLE_STATUS` | — | — | — | ✘ | 案件清單用 |
| `current_stage` | 目前階段 | text | SQL 子查詢（case_stages） | — | — | — | ✘（案件清單卡） | 每列一個子查詢 |
| `stage_progress` | 階段進度 | badge | SQL 子查詢 `stage_total/done/overdue` | — | — | — | ✘（案件卡） | 計數 |
| `missing_docs` | 缺單據 | badge | SQL 子查詢（`_CASE_MISSING_*`） | — | — | — | ✘（案件卡） | 規則 A7 |

**篩選／搜尋**（目前寫死）：文字搜尋（單號、客戶、案名）、`filterSales`、`filterMonth`、`filterDealTag`、生命週期頁籤（進行中／草稿／待審核／已核准／已送出／已確認／已結案／已取消／未成案…，`tabs` 陣列寫死）。→ 目錄 `ops.filterable` 屬性＋表面的 `quickFilters[]`（§6.3，頁籤也是一種『篩選預設』）。**快速篩選的條件與筆數同受 §5.0 約束**（例：不得做『毛利率 <20％：5 件』給遮蔽者看）。
**金額遮蔽事實**（已核對）：`masked = not quote_money_visible(user)` ⇒ SQL 之後 `mask_row` 把 `total／pretax／direct_margin_pct／net_margin_pct` 置 None 並加 `moneyMasked`；`sort=total` 對遮蔽者被忽略（:893–898）。

### 4.2 報價單詳情／表單（`quotation-form.html`＋`GET /api/quotations/{no}`）— 表面 `module:case.quotation_form`（由 FL P0～P2 主幹承接，本表供 P0 轉錄）

分五個區塊；**金額遮蔽事實**（已核對）：`get_quotation` 先看 `money_visible`（為真⇒完全不遮）→ 否則 `quote_money_visible` 為真⇒保留報價層級（`keep_quote`）只遮精算／款項／叫料 → 兩者皆否⇒剝除 `tot` 與品項金額鍵。

**頭部（20 項，皆非金額；聯絡資料屬隱私類）**

| id | 白話名 | privacy | 備註 |
|---|---|---|---|
| `quote_no` 報價單號、`location` 開立據點、`quote_date` 報價日期、`valid_days` 有效天數、`version` 版本 | none | 版本＝`FORM_VERSION`，唯讀 |
| `sales_phone`、`sales_email` 報價人電話／E-mail | contact | 報價人（員工）聯絡資料，會印在客戶版 |
| `customer_name` 公司名稱 | none | |
| `customer_tax_id` 統一編號 | **identity** | `pdfShow.taxId` 控制是否印 |
| `contact_name` 聯絡人、`contact_phone` 電話／分機、`contact_email`、`contact_fax` | contact | `pdfShow.*` 控制是否印；**個資蒐集告知**（`privacy_notice_acks`）綁在聯絡人上 |
| `delivery_address` 送貨／發票地址 | **address** | `pdfShow.deliveryAddress` |
| `project_name` 案件名稱、`delivery_location` 交貨地點 | none（`delivery_location` 〔待核〕可能含地址） | |
| `tax_type`、`tax_rate`、`tax_basis`（稅別、稅率、免稅依據） | none；`tax_rate` **$**（pub） | 稅別有法規連動（`validate_tax_basis`），`lock: required` |

**品項表（11 欄，現況三份手寫）**

| id | 白話名 | 型別 | 類別 | 判定 | 遮 | 通道 |
|---|---|---|---|---|---|---|
| `item_no` # | 項次 | derived（列序，不含標題列） | — | — | — | 全部 |
| `item_desc` 品名／規格說明 | longtext | — | — | — | 全部（核心） |
| `item_brand` 廠牌／型號 | text | — | — | — | 全部 |
| `item_qty` 數量 | number | — | — | — | 全部 |
| `item_unit` 單位 | text（datalist） | — | — | — | 全部 |
| `item_cost` 成本單價 | money | **$ int** | `quote_money_visible` | K（`ITEM_MONEY_KEYS`） | 畫面、內部 PDF、內部 Excel（**不進客戶版**） |
| `item_margin` 毛利率 | percent | **$ int** | 同上 | K | 同上（核心欄 `unitPrice` 的反推來源） |
| `item_price` 售價（未稅） | money | **$ pub** | `quote_money_visible` | K | 全部（客戶版稱『單價（未稅額）』） |
| `item_amount` 金額（未稅） | money | **$ pub**（衍生＝qty×price，伺服器重算） | 同上 | K | 全部 |
| `item_profit` 單項毛利（直接） | money | **$ int**（`derived_ui`：amount − qty×cost×1.05） | 同上 | 前端衍生，資料中沒有鍵 | 僅畫面 |
| `item_notes` 備註 | text | — | — | — | 全部（客戶版有備註才顯示該欄） |
| ＋M3：`item_alt_group` 擇一組別、`item_alt_tag` 擇一／未選標記 | text／badge | — | — | — | 畫面、客戶版 PDF（標記） |

**合計與內部損益（20 項）**：`subtotal` 品項小計、`discount` 折讓、`freight` 運費、`pretax` 稅前合計、`tax` 稅額、`total` 總計（**$ pub**，K＝`QUOTE_MONEY_KEYS` 含整個 `tot`）；內部損益區（**$ int**）：`total_cost` 直接成本、`input_vat` 進項稅額、`direct_profit` 直接毛利、`direct_margin_pct` 直接毛利率、`project_margin_pct` 專案毛利%、`admin_cost` 管銷分攤、`charity` 公益捐款、`total_indirect` 間接合計、`net_profit` 營業利益、`net_margin_pct` 營業利益率；另 `overhead_pct` 管銷比率（**僅 superadmin 可改**，編輯權限不同於可見權限，需 F7 `evaluate()`）、五項舊口徑間接成本（`indirect*`，只在舊口徑單顯示）。

**條款（5 項，皆長文字、非金額）**：付款條件、交貨條件、保固條件、售後服務及備註說明、驗收標準（`termsFieldDefs` 已是程式內單一清單，是目錄最接近的現成來源；條款組 presets 是資料不是欄位）。

**狀態**：`FORM_VERSION` 守門（表單內容雜湊變 ⇒ 必須升版）使本頁**每次動工都要升版**，所以本頁的轉換排在主幹（P2），不當前三頁。

### 4.3 案件管理頁（`case-management.html`＋`js/case-management-*.js`）— 表面 `module:case.case_list`（卡片）、`module:case.case_matrix`、`module:case.case_detail`

**案件清單／卡片（左欄）與矩陣（`GET /api/quotations?scope=case`、`/api/quotations/gate-matrix`）**

| id | 白話名 | 來源 | 類別 | 判定 | 遮 |
|---|---|---|---|---|---|
| `case_no` 案件、`customer_name`、`project_name`、`location` 據點（只有一個據點時不顯示） | SQL／`locationName()` | — | — | — |
| `contract_total` 合約金額 | 矩陣 `row.total`、案件清單 `total` | **$ int** | 前端 `canSeeFinancial()`；後端案件清單只遮 `("total",)` 以 `quote_money_visible`〔待核：矩陣端點的判定〕 | K／F（**前後端判定函式不同**，見 §8 U5） |
| `sales_person` 負責 | SQL | — | — | — |
| `gate_progress` 進度、`gate_payment` 收款、`gate_documents` 單據、`gate_settlement` 精算、`gate_extra` 變更 | 後端 `gate-matrix`（`case_close_gates`，**動態家族** `dynamicFamily: gate_heads`；每格有 `value/state/ratio/reason`） | — | — | — |
| `next_due` 下一到期、`can_close` 結案（可結案） | 後端計算 | — | — | — |
| `deal_tag`、`settle_status`、`stage_*`、`missing_docs`、`recv_overdue`（卡片徽章與快速篩選 A7） | SQL 子查詢 | — | — | — |

**案件詳情（右側，各分頁）**：分頁 `案件資訊 biz`／`執行管理 exec`／`承攬商 dispatch`／`出貨單 shipping`／`完工單 completion`／`動態 feed`／`全部檔案 allfiles`／`財務 fin`／`額外支出 xexp`（`canSeeFinancial()` 才顯示）。欄位約 18 個區塊級目錄項（以**區塊**為單位登錄比以欄位為單位實際：`D3 頁面區塊`）：

| 區塊 id | 內容 | 類別 | 判定 | 備註 |
|---|---|---|---|---|
| `case_contract` 合約資料 | 交貨／安裝地址（address）、交貨條件、現場聯絡人（contact）、聯絡電話（contact） | privacy | 逐案可見（`case_page_readable`） | 個資告知（`privacy_notice_acks`）綁現場聯絡人 |
| `case_settlement_kpi` 精算 KPI | 含稅收入（稅前）、實際總成本、真實毛利（%）、營業利益率… | **$ int** | `money_visible`（財務角色／superadmin／出納模組） | 後端剝除 `settlement`；前端 `canSeeFinancial()` |
| `case_project_margin` 專案毛利% | 見專案毛利% 設計 | $ int | `money_visible`（詳情）；信封鍵 `project_margin_pct` | 已實作 |
| `case_alt_plan` 擇一所選方案／方案比較 | M3 T10 | $ int（比較） | `money_visible`（比較）／逐案（所選方案） | 已實作 |
| `case_payment_items` 款項期別 | 期別、金額、已收、發票… | **$ int** | `money_visible` | 後端 `mask_case_record` |
| `case_materials` 叫料 | 品項、單價、總價、已付 | **$ int** | `material_money_visible`（admin 在內）或 `money_visible` | 另一個判定函式 |
| `case_stages`、`case_roles`、`case_files`、`case_devices`、`case_warranty`、`case_todos` | 階段／角色／檔案／設備／保固／待辦 | — | 逐案 | 非金額 |

### 4.4 財務／應收應付摘要

**4.4a 案件頁「財務」分頁（`GET /api/quotations/{no}/finance-summary`）**— 表面 `module:case.case_finance`（區塊型）

| id | 白話名 | 來源 | 類別 | 判定 |
|---|---|---|---|---|
| `fin_receivable_total`、`fin_collected_total`、`fin_outstanding_total`、`fin_net_collected`、`fin_fee_total` | 應收總額／已收／未收／實收淨額／另列手續費 | 後端 `summarize_payment_items`（`receivable.*`） | **$ int** | 端點沿用既有端點權限（同一批資料的既有端點）；畫面 `canSeeFinancial()`（**顯示偏好，不是權限邊界**——程式註解自述） |
| `fin_payable_paid`、`fin_payable_unpaid`、`fin_payable_pending_total/count`、`fin_remit_fee_total` | 應付（承攬商匯款申請）：已匯款／未匯款／簽核中 | `payable.*` | $ int | 同上 |
| `fin_vouchers[]` 承攬商匯款單明細 | `voucherNo/vendorName/status/grandTotal/payableDate/isPaid/paidAt/createdAt` | $（grandTotal） | 同上 |
| `fin_invoice_vouchers[]`、`fin_payment_requests[]` | 開票申請（`voucherNo/status/amount/createdAt`）、請款單（`requestNo/status/stage/amount/createdAt`） | $（amount） | 同上；**不併入應收合計**（避免重複計算，程式註解自述） |
| `fin_settlement_extras[]` | 精算額外支出（類別、說明、單號、總成本、日期、數量、單位、單價、備註、建立者、付款人、狀態、檔案） | $ int | 另有 `masked` 旗標列（遮蔽後仍留列） |
| `fin_custom_finance` | 自訂模組收入／支出 | $ | 同上 |

**4.4b 出納頁（`cashier.html`＋`GET /api/cashier/*`）**— 表面 `module:arap.cashier_*`（多張表：待付款、承攬商匯款、獎金分潤、匯款差額審核、應收佇列、歷史）

| 表 | 欄位（今天表頭／鍵） | 類別 | 判定（端點層） |
|---|---|---|---|
| 請款待付款 | 申請單號、關聯案件、廠商、應付金額、應付款日（合約）、預定付款日、動作（付款／設預定付款日） | $ int（金額） | `has_finance_access`（財務角色＋superadmin）〔`_require_view_access`〕 |
| 承攬商匯款 | 勞報單號、承攬人、應付總額、實發金額、簽回檔、付款日期、傳票單號 | $ ＋ 隱私（承攬人、**簽回檔**） | 同上 |
| 獎金分潤 | 案件號、客戶、人數、發放總額、核准日 | **$ payroll** | **出納頁門檻 `finance_access` AND `bonus_visible`**（`bonus_visible`＝superadmin 或**出納模組**，`_bonus_visible`，**不同於**財務角色判定；財務角色看得到其他分頁但看不到獎金；只有出納模組的非財務帳號過不了頁面門檻，§5.5） |
| 勞報單待付款（`payslip-queue`） | 勞報單金額、受款人身分、簽回狀態、付款日期、傳票單號 | $ ＋ 隱私（受款人身分） | **`payslip_visible`**（`_payslip_visible`；今天 ＝ `has_finance_access`，**不再認出納模組勾選**，使用者 2026-10-07 Q1）；仍受出納頁門檻 |
| 付款操作與**完整收款人銀行帳號**（`payee-bank`） | 付款人資料：銀行、**帳號**、戶名、來源（銀行資料表／單據快照） | 隱私 `bank`（見下） | **`cashier_access`**（`has_cashier_access`；今天 ＝ `has_finance_access`，旗標 `on` 時 `_finance_cap(user,'cashier')` 可個別被扣）；`_can_pay` 同一函式；非 `cashier_access` 者（含一般管理員）只看到末 4 碼 |
| 匯款差額審核 | 案件號、客戶、申請內容、受款人、金額 | $ ＋ 隱私（受款人） | 財務角色 |
| 應收佇列（`receivable-queue`） | `quoteNo/customer/project/salesPerson/quoteDate/dealTag/type/amount/actualAmount/feeAmount/feeNote/invoiceNo/invoiceDate/expectedReceiptDate/received/receivedAt/receivedBy/overdue/unreceived/idx/itemId/note` | $ int | 財務角色 |
| 開票申請／請款單清單 | 見 `invoice_vouchers.py`／`payment_requests.py`：`require_any_module(case_manage／finance／cashier／quotation)`＋逐案可見 | $ | **模組檢查**（不是金額判定函式）〔待核各欄遮蔽〕 |

**判定函式登錄表（封閉集合，種子）**——這是財務頁的重點：同一個『金額』在不同頁用**多種不同判定**（r3：八個），目錄必須全部登錄，否則轉換時一定漏：

| id | 對應程式 | 誰為真 |
|---|---|---|
| `quote_money_visible` | `financial_mask.quote_money_visible` | superadmin／admin／sales／財務職責人 |
| `money_visible` | `financial_mask.money_visible` | superadmin／財務角色（`can_see_financial`）**或持出納模組** |
| `material_money_visible` | `financial_mask.material_money_visible` | superadmin／admin／sales／財務職責人（叫料日常作業） |
| `finance_access` | `helpers.auth.has_finance_access` | 財務角色＋superadmin（出納頁端點） |
| `bonus_visible` | `cashier._bonus_visible` | superadmin 或出納模組（**獎金表需再 AND `finance_access`**） |
| `cashier_access` | `helpers.auth.has_cashier_access` | 與 `finance_access` 同（今天）；旗標 `finance_via_effective=on` 時改看 `_finance_cap(user,'cashier')`＝**第二條財務縫**；用於付款與完整收款帳號 |
| `payslip_visible` | `cashier._payslip_visible` | 今天＝ `has_finance_access`（勞報單金額與受款人身分；不再認出納模組勾選） |
| `case_page_readable`（逐案，非金額） | `helpers.case_access.case_page_readable` | 該案成員／管理者／持 cashier 讀取例外者 |

**收款人銀行帳號——隱私欄位種子（r3）**

| 屬性 | 值 |
|---|---|
| id | `payee_bank_account`（與同一組的 `payee_bank_name` 銀行、`payee_account_name` 戶名、`payee_source` 來源） |
| privacyClass | **`bank`**（新增類別，與 `identity` 同等級管制）；`isMoney = false` |
| visibility | `cashier_access`（**不是** `finance_access`；兩者今天結果相同，旗標 `on` 後可分開）；表面門檻＝出納頁 |
| channels | **只有 `screen`**（付款前查看）；**不含** `preview／customer_*／internal_excel／internal_pdf／filename／carry_in／rule`；`ops` 全 false |
| maskStyle | **`partial`**（r3 新增形狀）：非 `cashier_access` 者回 `****` ＋ 末 4 碼（不足 4 碼全遮），並附說明文字；其他形狀不適用 |
| 附加行為 `auditOnView` | 每次查看寫稽核 `cashier.payee_bank_view`（標明是否遮罩）；**嚴格提供者（勞報單，`FULL_ACCOUNT_STRICT`）先稽核才給值：稽核寫不進去 ⇒ 500、不回帳號**，回應 `no-store` 且不快取 |
| 來源優先序 | 銀行資料表提供者 `payee.bank_profile`（員工）→ 單據手填快照 → 明說『尚未登錄』（不猜） |
守門：①目錄驗證 `privacy_without_visibility_fn`、`money_or_privacy_in_filename_or_carry_in`（此欄不得出現在檔名／帶入）；②`auditOnView` 欄位的解析輸出必須走『先稽核再給值』的單一路徑（測試：稽核寫入失敗 ⇒ 不回值；正對照：稽核成功 ⇒ 回值且 `Cache-Control: no-store`）；③5 角色×2 模式矩陣（見 §5.9）。

## 5. 遮蔽與可見性如何綁在目錄欄位上（使用者永遠放不出自己看不到的欄位）

### 5.0 唯一規則：每一種衍生操作都只對『通過該欄位判定函式的檢視者』成立（伺服器端；r2 必修 2）

**規則**：對欄位 X 的任何**衍生操作**，只有當**本次請求的檢視者**通過 X 的 `visibility` 判定函式**且**目錄 `ops` 對該操作為 true 時才成立。在**解析器**（伺服器）強制，不靠前端、不靠各端點各自記得。檢視者不通過 ⇒ ①請求端：新的目錄驅動請求回 **400**（威脅模型 §5）；舊參數維持今天行為（忽略）；②回應端：該操作的**結果與痕跡**都不出現。

| 衍生操作 | 對『不可見欄位』的結果 | 要防的洩漏 |
|---|---|---|
| 排序（含預設排序、個人排序偏好） | 該欄不在可排序清單；個人偏好引用它 ⇒ 丟棄入 `dropped` | 順序洩漏大小 |
| 篩選／快速篩選條件 | 條件不成立；快速篩選的**定義**對該檢視者不出現 | 二分搜尋出值 |
| 快速篩選／頁籤的**筆數** | 筆數由伺服器以檢視者可見性計算；依賴不可見欄位的篩選不回筆數（連 0 都不回） | 筆數差異洩漏（例：『毛利率 <20％：5 件』） |
| 搜尋（全文／欄位搜尋） | 搜尋範圍只含可見欄位 | 命中與否洩漏 |
| 分組、聚合（總計、平均、小計列、`count`） | 不可見欄位不得被分組或聚合；由它衍生的合計列一併剔除 | 總額洩漏 |
| 警示規則的**條件** | 引用不可見欄位的規則對該檢視者**不評估**，且不回任何訊號（連『被隱藏』都不回） | 標紅＝洩漏門檻比較結果 |
| 警示規則的**文字**（badge、tooltip） | 代入值只能取可見欄位（chips） | 文字內夾帶金額 |
| 匯出欄 | 範本欄 ∩ 匯出者可見 ∩ 通道可用 | 匯出夾帶 |
| tooltip／`title`／無障礙文字 | 同上：只用可見欄位 | 滑鼠懸停洩漏 |
| 條件式列／儲存格樣式（class、色階） | 色階函式的輸入欄位必須可見；否則該樣式不套用 | 顏色洩漏（`margin_tone` 對遮蔽者不得上色） |
| 衍生欄位（`computed`／`derived_ui`） | 衍生欄位的可見性＝其**所有輸入欄位**可見性的交集（目錄 `source.inputs` 宣告） | 由可見欄位推回不可見欄位 |

**測試（正對照必備）**：①對每個表面，遮蔽檢視者的回應**不得含任何依賴不可見欄位的排序鍵、篩選定義、筆數、聚合、警示標記、tooltip、列樣式**（遞迴走訪回應）；②正對照：把 `direct_margin_pct` 設 `ops.filterable=true` 但**不**宣告 `opsRequireVisibility` ⇒ 驗證器必須失敗（`ops_without_visibility_guard`）；宣告了卻在解析器關掉把關（突變）⇒ 遮蔽檢視者測試必須紅；③二分探測：engineer 對不可見欄位的目錄驅動篩選一律 400，回應內容不隨門檻值改變（只斷言 400，不做計時）。

### 5.1 三層，缺一不可
1. **宣告層（目錄）**：每個 `isMoney` 或 `privacyClass≠none` 的欄位**必須**宣告 `visibility`（引用上面的**封閉判定函式登錄表**；字串不在表內 ⇒ `unknown_visibility_fn`）。金額欄位必須宣告 `maskKeys`（對應 `financial_mask` 的資料鍵）。
2. **解析層（伺服器，逐檢視者）**：解析器 `resolve(surface, version, viewer, channel)` 對每個欄位呼叫其判定函式；**為假 ⇒ 該欄位、其標題、其衍生欄位／合計列整個不出現在回應**（不是置空）。檢視者永遠是**本次請求的使用者**（預覽用『角色合成檢視者』，限制見 FL §4-5b）。
3. **資料層（既有遮蔽，縱深）**：`mask_row`／`mask_quotation_data`／`mask_case_record` 照舊運作。即使解析器有漏洞，資料本身已被剝除。

### 5.2 『使用者不能放出自己看不到的欄位』的具體機制
- **編輯器只列看得到的**：版面編輯器的欄位挑選清單由解析器以**編輯者本人**的可見性產生；看不到的欄位**連名稱都不出現**（FL §7-4）。
- **後端驗證器再擋一次**：發布版面／匯出範本／警示規則時，驗證器檢查其引用的每個欄位 id ① 存在於目錄 ② **引用者看得到**（否則 422『這項資料你沒有權限使用』，不洩漏欄位內容）。
- **渲染時再剔除一次**：定義是共用資產（公司版），可能含『編輯者看得到、檢視者看不到』的欄位；渲染時**用檢視者的可見性重新剔除**。所以『管理者放進去的內部欄位，業務看不到』是安全的預期行為，而不是漏洞。
- **角色預覽**：以被預覽角色的合成檢視者解析（FL §4-5b）；限制：不反映個別使用者另外被加減的能力（例：被授予出納模組的一般帳號）。
- **通道硬規則（r2 更正）**：①`moneyClass=internal` 欄位不可進**任何客戶通道**；②所有 `isMoney`／隱私欄位不可進 `filename`／`carry_in`；`isMoney`＋`public`（單價、金額）**可以**進客戶版。驗證器擋（發布不過），輸出端再擋一次（FL §7-2）。夾具：`internal`＋`customer_pdf` 必須失敗（正對照）、`public` 金額＋`customer_pdf` 必須通過（反例）。

### 5.3 規則與匯出對遮蔽的特別要求（容易漏的洩漏面）
- **警示規則**：規則引用欄位 X 時，**只對看得到 X 的人評估**；看不到者連『這列有被標紅』都不能出現（標紅本身洩漏『X 低於門檻』）。規則在伺服器端以檢視者可見性評估後才附標記（§6.2）。
- **排序／篩選／搜尋／分組／聚合／計數**：一律依 §5.0 唯一規則。**既有行為不變**（黃金）：報價單清單目前對遮蔽者『忽略』 `sort=total`；**目錄驅動的新請求**依威脅模型 §5 改為對不可見欄位回 **400**（不是靜默忽略後仍用該欄排序）。兩者並存的過渡：舊參數保持舊行為、只有目錄新增的操作走 400。
- **匯出**：沿用 `export_logged` 稽核；欄位集合＝範本欄位 ∩ 匯出者可見欄位 ∩ 通道可用欄位；匯出者的可見性以**匯出當下的使用者**評估（不是範本作者的）。
- **個人層**：個人偏好只能改顯示／排序，不能改『可用欄位』；個人層引用不存在或已不可見的欄位 ⇒ 靜默丟棄並列入 `dropped`。

### 5.4 雙向守門（登錄表驅動，沿用 FL §17.5）
1. 目錄 `isMoney` 欄位的 `maskKeys` ⇔ `financial_mask` 各鍵清單（`ITEM_MONEY_KEYS`／`QUOTE_MONEY_KEYS`／`QUOTATION_MONEY_COLS`／`PAYMENT_MONEY_KEYS`／`MATERIAL_ORDER_MONEY_KEYS`）：兩個方向都要對得上（目錄金額鍵必在遮蔽清單；遮蔽清單的每個鍵必屬於某目錄欄位或明列『非顯示欄位』）。專案毛利%已經是這個機制的第一個實例（`project_margin_pct` 登記於 `QUOTATION_MONEY_COLS`）。
2. 每個 `isMoney` 欄位有 `visibility`；每個 `visibility` id 在判定函式登錄表內。
3. 5 角色 × 每個表面的**可見度參數化測試**（admin／sales／finance／cashier／engineer，專案毛利% 設計 §6-4 已定模式）：`欄位出現 ⇔ 該角色該表面判定為真`；反向：無權限者的回應**任何位置**（含巢狀、含標題）都不得出現該欄位 id 或其資料鍵（遞迴走訪）。
4. 預設版面 ＝ 今天（黃金比對：預設解析結果轉成 DOM／API 形狀，與改前逐位元相同）。

### 5.5 欄位可見＝表面門檻 AND 欄位判定（r2 必修 3a）

**一個欄位對某檢視者出現，必須同時通過兩道門**：①**表面門檻**（`surface.gate`：該頁／該表面本身誰能開，例：出納頁 `finance_access`、案件頁 `case_page_readable` 逐案）；②**欄位判定**（`field.visibility`）。任何一道不過 ⇒ 不出現。
- 例（出納頁，已核對）：頁面端點 `_require_view_access` ⇒ `has_finance_access`（財務角色＋superadmin）；獎金分潤表另需 `bonus_visible`（superadmin 或**出納模組**）。**只有出納模組、不是財務角色的一般帳號** `bonus_visible` 為真但過不了頁面門檻 ⇒ 看不到獎金（目前端點層就是如此；目錄化後不得因為『欄位判定為真』而放行）。
- 測試（兩個方向）：持出納模組的**非財務**帳號 ⇒ 出納頁任何欄位都不出現（含獎金）；財務角色（無出納模組）⇒ 出納頁其餘欄位出現、獎金不出現；superadmin ⇒ 全部出現。

### 5.6 遮蔽後的回應形狀 `maskStyle`（r2 必修 3b）

今天三種形狀並存，目錄必須逐欄記錄，才能保證『預設＝今天』逐位元相同：
| 形狀 | 表面 | 行為 |
|---|---|---|
| `null` | 報價單清單（`mask_row`） | 鍵保留、值置 None、列加 `moneyMasked: true` |
| `strip` | 報價單詳情、案件詳情（`mask_quotation_data`、`mask_case_record`） | 鍵整個剝除（`tot`、品項金額鍵、`settlement`、款項期別金額） |
| `absent` | 專案毛利%（信封鍵 `project_margin_pct`） | 判定為假時鍵不存在 |
| `partial` | 出納頁收款人銀行帳號（r3） | 值保留但只剩末 4 碼（`****1234`）並附說明；**第四種形狀**，僅限 `bank` 類欄位 |
預設 `maskStyle` 取各表面今天的形狀；改成別的形狀＝回應形狀變更，須走黃金比對與版本。測試：每個 `isMoney` 欄位對遮蔽檢視者的回應形狀 == 目錄 `maskStyle`（`mask_style_mismatch`）。

### 5.7 付款衍生事實的明確決定（r2 必修 4）

`recv_overdue`（應收逾期，SQL 以 `json_each` 掃 `caseRecord.payment.items`）、`missing_invoice`（缺發票）、`overdue`（出納應收佇列）、案件卡的 `stage_overdue`／`missing_docs` 等，**從金額資料衍生，但今天對任何『有該案件列存取權』的檢視者都回傳**（案件清單的快速篩選與筆數、卡片徽章），並不經 `money_visible`。
- **決定（記錄為已接受的現況，需使用者確認，§8 U13）**：這些旗標屬『進度提醒』而非金額；`visibility = case_page_readable`（逐案），`isMoney = false`，但標 `derivedFromMoney: true`。
- **限制（避免它們變成金額旁路）**：①`ops.ruleUsable = false`——**不得作為警示規則的輸入**，也不得與金額門檻組合成條件（`rule_input_forbidden`）；②不得進 `filename`／`carry_in`／匯出的金額欄；③筆數僅顯示『有 N 件逾期』，**不得提供『逾期金額』**；④若日後要『逾期金額』欄，那是另一個 `isMoney` 欄位，走 `money_visible`。
- 不接受此決定時的備案：改 `visibility = money_visible`（遮蔽者不見這些徽章與筆數），屬行為變更，需使用者裁示。

### 5.8 與威脅模型對齊（`USER-DEFINED-LOGIC-THREAT-MODEL.md` §1、§5；0d 建議 8）

本文**不重寫**威脅模型的控制，只對齊：①目錄是唯一事實來源；讀取衍生操作先與可見欄位集合取交集（→ §5.0）；②自訂欄位（日後）一律 `x_` 前綴、與系統欄位分離、同名拒絕；③**敏感度只能往更嚴改**（放寬走放寬流程）；④標籤與選項文字存**純文字**、前端一律 `textContent`、後端輸出跳脫（`alert_rule` 的 badge 文字、`relabel` 皆同）；⑤警示規則的求值身分＝目前使用者，輸出型別只有標記（§6.2），不寫入、不改狀態。威脅模型 §1 的『規則評估預算』（節點數、深度、逾時）適用於 `alert_rule`，上界寫死、管理者只能調小。

### 5.9 判定函式登錄表的守門（r2 建議 5、6）
1. **同一函式物件**：登錄表中的每個判定函式 id 必須解析到**與實際使用處相同的函式物件**（`registry[id] is financial_mask.quote_money_visible` 之類的 `is` 斷言），不得另寫一份包裝；測試：突變其中一個實際函式的行為，目錄解析結果必須跟著變。
2. **縫（r3 擴充）**：`quote_money_visible`／`material_money_visible` 經 `finance_duty_person` 縫；`has_finance_access` 與 **`has_cashier_access`（第二條財務縫）** 經 `_finance_mode()`（旗標 `finance_via_effective`：`off`／`shadow`／`on`，快取 15 秒）。旗標 `off` 時 `has_cashier_access` ＝ `has_finance_access`；`on` 時分別看 `_finance_cap(user,'finance')` 與 `_finance_cap(user,'cashier')`，可個別被扣。判定語意由『角色』改為『生效權限』——因為登錄表指向同一函式物件，行為會一起變；測試需在 `off` 與 `on` 兩種模式各跑一次 5 角色矩陣，**矩陣含 `finance_access`、`cashier_access`、`payslip_visible`、`bonus_visible` 四者**（`on` 模式下『有 finance 無 cashier』的帳號：看得到出納頁其餘欄位、看不到完整收款帳號——正對照）。
3. **`derived_ui` 守門**：`source.kind=derived_ui` 的欄位不得出現在匯出、規則、檔名、帶入通道（`derived_ui_in_export_or_rule`，正對照：把一個 `derived_ui` 欄位加進匯出範本必須失敗）；另測『瀏覽器端用被剝除的鍵算 `derived_ui` 值』結果為空（例：`item_profit` 在無成本權限者的畫面算不出東西、且沒有殘留數字）。

## 6. 介面（只定介面，不實作）

### 6.1 匯出範本（PDF／Excel）— 沿用定義文件庫 kind `output_template`，新增 `export` 變體
```json
{ "kind": "output_template", "key": "export:case.quotation_list", "scope": "company",
  "body": { "version": 2, "channel": "excel", "surface": "module:case.quotation_list",
            "columns": [ {"field": "quote_no"}, {"field": "customer_name"},
                         {"field": "total", "label": "報價金額"}, {"field": "project_margin_pct", "width": "narrow"} ],
            "rows": {"filterPreset": "active", "sort": {"field": "quote_date", "dir": "desc"}},
            "header": {"title": "報價單清單", "showExportedAt": true} } }
```
- 欄位只能引用目錄 id；`label` 為 relabel；`width` 是檔位；**無運算式、無程式**。
- 通道欄位＝範本欄位 ∩ 目錄 `channels` 含該通道 ∩ 匯出者可見（§5.0、§5.3）。**客戶通道含 `moneyClass=internal` 欄位 ⇒ 發布失敗**（`isMoney`＋`public` 的價格可以進客戶版）。
- 現況落點：案件批次匯出（`case_batch_export`，欄位寫死）、報價單 PDF（`pdf_gen`）、之後的報價單 Excel（FL P5）都吃同一個解析結果；**PDF 版型**走 `doc_template` 積木（`items_table` 的 `columns[].width`），Excel 走 openpyxl 適配器（空字串須轉 None 的既有陷阱照舊）。
- 檔名：沿用下載檔名設計的『範本變數由目錄產生、金額類不可成為變數』。

### 6.2 條件式警示規則 — 新 kind `alert_rule`
```json
{ "kind": "alert_rule", "key": "quote_low_margin", "scope": "company",
  "body": { "version": 1, "surface": "module:case.quotation_list",
            "when": { "all": [ {"field": "direct_margin_pct", "op": "lt", "value": 20},
                               {"field": "status", "op": "in", "value": ["草稿", "待審核"]} ] },
            "then": { "tone": "crit", "badge": "毛利偏低", "target": "row" } } }
```
- **封閉運算子**（依欄位 `rule.valueType` 決定可用者）：`eq／ne／lt／le／gt／ge／between／in／empty／notempty`；日期型另有 `older_than_days／within_days`（距今天數）。**沒有運算式、沒有跨欄位算式**（要『毛利率低於門檻』就用 `direct_margin_pct` 這個目錄欄位，不讓管理者寫 `price - cost`）。`value` 可為常數或**設定引用**（`{"setting": "project_margin.warn_pct"}`，讓門檻仍由設定中心管理與稽核）。
- **效果**：只有顯示類——`tone`（`warn／crit／info`，沿用既有色階語彙）、`badge`（白話文字，**範本占位符只能是 chips**：可見欄位的值，不用大括號）、`target`（`row／cell`）。
- **上限（會阻擋動作者）不是警示**：例如『折讓超過 X% 不得送審』是簽核／政策，必須走設定中心的政策選項（`loosen`、雙人核准、高影響橫幅）與簽核層，**不在 `alert_rule` 範圍**；驗證器遇到 `then.action` 之類鍵 ⇒ 失敗。本期警示＝『看得見的提醒』，阻擋類之後以政策登錄。
- **評估位置**：清單＝伺服器評估後在每列附 `_alerts`（只含檢視者看得到欄位所觸發的規則；§5.3）；表單＝前端即時評估，使用同一份運算子語意——與專案毛利% 同做法：**運算子語意用共同黃金向量鎖前後端一致**。
- **第一批遷移**：§2.3 的 A1、A2、A3、A5、A8（顯示規則資料化）；A4、A10、A11 與簽核原因同源，**簽核判定保持程式**，只把『顯示紅字』資料化。
- 風險：規則是公司共用資產，改規則＝改全公司畫面；風險類 `none`（只改畫面）；走定義文件庫版本／還原；**不是**設定中心高影響類。

### 6.3 自訂按鈕與選單 — `customization` 點 v2
- 現況：`module.json` 的 `pages[].menu` 與排版器已能 `move／hide／relabel` **既有**按鈕與選單項；**不能新增**。
- 設計：新增兩種點 `buttons[]`、`menus[]`，管理者可新增項目，但 `action` 只能選**封閉的動作登錄表**（由程式登錄、帶白話名稱與必要參數）：`open_page`（開某個頁面＋預設分頁）、`apply_filter_preset`（套用表面的『篩選預設』，例：清單頁籤 `進行中`／`逾期階段`）、`run_export`（執行某個匯出範本）、`open_link`（站內連結，**限相對路徑白名單**，禁外部網址與 `javascript:`）、`create_from`（新增某單據並帶入預設值，僅限程式登錄的預設集合）。**沒有腳本、沒有任意 HTTP 呼叫。**
- 權限：按鈕顯示條件＝其動作所需能力（動作登錄表的 `requires`）∩ 檢視者；管理者新增按鈕**不會**讓沒有權限的人做到更多事（動作本身仍過既有端點權限）。
- 篩選預設：把清單的頁籤／快速篩選（目前寫死的 `tabs`、`quickFilterDefs`）登錄為表面的 `quickFilters[]`（id、白話名、條件＝目錄欄位上的封閉運算式），管理者可增刪排序——與警示規則共用同一組運算子。**快速篩選的條件欄位與筆數受 §5.0 約束**：條件欄位必須是檢視者可見且 `ops.quickFilterable`；筆數由伺服器以檢視者可見性計算，依賴不可見欄位的快速篩選對該檢視者**整個不出現**（不回筆數、不回 0）。

### 6.4 解析輸出（所有消費者吃同一份）
`GET /api/layout/{module}?surface=<表面>`（FL §4-3，不新增路由前綴）回：
```json
{ "surface": "module:case.quotation_list", "layoutVersion": 7,
  "columns": [ {"field": "quote_no", "label": "報價單號", "format": "link", "width": "mid", "sortable": true, "tone": null} ],
  "quickFilters": [ {"id": "active", "label": "進行中"} ],
  "alertRules": [ {"id": "quote_low_margin", "when": "...", "then": {"tone": "crit"}} ],
  "dropped": [] }
```
`columns` 已被檢視者可見性剔除；`alertRules` 只含檢視者看得到欄位的規則；清單資料回應另帶每列 `_alerts`。

## 7. 逐頁轉換工量與前三頁

**估算方法**：以 FL §12.2 的插槽工量為基準（S-D1 首個表面 3.0＋之後每個 0.5；S-D3 案件頁 3.0、儀表板 2.0、報表欄位 2.0；S-D2 格式化 2.0；S-F5 標籤 1.5），加上**本文發現的實際欄位數與衍生欄位搬遷量**修正；每頁 = 種子登錄（填 `catalog.json`＋守門）＋後端投影／解析接線＋前端改吃解析結果＋測試（5 角色×遮蔽、黃金比對）。**前置（只算一次）**：脊柱主幹 P0＋P1＋閘門（6.75 pd）＋E-a/E-b（2.5 pd）已在路線圖，不重計；S-D2 格式化器（2.0）為所有頁共用前置。**這些是估計，未做原型驗證**（§8 U11）。

| # | 頁面／表面 | 欄位數（種子） | 主要工作 | pd | 風險／備註 |
|---|---|---|---|---|---|
| 1 | **報價單清單** `quotation_list` | 22 | 種子 1.0；清單 SQL 改由目錄投影 0.75；`derived_ui` 搬後端（成案徽章、停留、改版）0.5；前端 `quotations.html` 改吃解析結果 0.75；5 角色遮蔽測試＋黃金 0.5 | **3.5** | 含 S-D1 首個表面基礎（`list_view` kind、個人層）；排序白名單沿用；頁籤→`quickFilters` |
| 2 | **案件管理—財務總覽區塊** `case_finance` | 36 | 種子 0.75；區塊型表面（D3 區塊顯示／順序）1.0；改 `case-management.html` 財務分頁區塊 0.75；遮蔽（`money_visible`／前端旗標統一）＋測試 0.5 | **3.0** | 純顯示、全金額，是遮蔽規則最乾淨的證明；不碰 `quotation-form`（無 FORM_VERSION 守門） |
| 3 | **案件管理—案件清單與矩陣** `case_list`／`case_matrix` | 約 22 | 種子 1.0（含閘門動態家族）；案件清單 SQL 投影（6 個子查詢按需）1.0；矩陣欄位選擇 0.5；快速篩選→`quickFilters` 0.5；測試 0.5 | **3.5** | 動態欄位家族（`gate_heads`）；`recv_overdue` 等為 SQL 子查詢；逐案可見範圍 |
| 4 | 案件詳情—合約／階段／檔案等非金額區塊 | 約 18 區塊 | D3 區塊顯示／順序；多為 `x-show` 搬遷 | 3.0 | 案件頁 3.0 的主體（與 #2 共享基礎，可併；此列為其餘部分） |
| 5 | 出納頁（6 張表） | 約 45 | 5 種判定函式（`finance_access`／`bonus_visible`…）；每張表 0.5 | 3.5 | 獎金表隱私＋金額最敏感；放在 #2 驗證完判定函式登錄表之後 |
| 6 | 報價單詳情／表單 | 約 52 | **走 FL P0～P2 主幹（17.75 pd 內）**，不重計；每次動工要升 `FORM_VERSION` | （主幹） | 同檔衝突、239 KB、三份手寫渲染；最後轉 |
| 7 | 開票申請／請款單 清單與表單 | 約 30 | 與報價單同型；之後每個 0.5～1.0 | 2.0 | 先在 #1 建立 `list_view` 後套用 |
| 8 | 客戶／廠商／承攬商等主檔清單 | 各 8～12 | 純非金額清單；套用 #1 的基礎 | 每頁 0.5 | 最便宜，可批次 |
| 9 | 報表欄位（`reports.py`） | 約 60 | S-D3 報表欄位 2.0 | 2.0 | 欄位多、金額多；另案排期 |
| 10 | 匯出範本（PDF／Excel）介面落地 | — | `export` 變體＋適配器；FL P5 已含報價單 Excel | 2.0 | 依 #1／#6 的解析器；與 `doc_template` 轉錄 |
| 11 | `alert_rule` kind＋評估器＋第一批遷移（A1、A2、A3、A5、A8） | 5 條 | 規則 kind 驗證 0.5；評估器（伺服器＋前端孿生＋黃金向量）1.0；遷移 5 條 0.5 | 2.0 | 依 #1 的清單解析；與專案毛利% 同型的前後端等值做法 |
| 12 | 自訂按鈕／選單（動作登錄表） | — | `buttons/menus` 點＋5 種動作＋權限 | 2.0 | 最後做；風險低但要安全審查（`open_link`） |
| — | **合計（#1～#5 ＋ #7～#12，不含 #6 主幹）** | | | **約 25.5 pd**（r1） | 加 S-D2 格式化器 2.0（共同前置）＝ 27.5 pd；**r2 新增 §3／§5 的驗證器與測試（`ops` 屬性驗證、唯一規則的角色×操作矩陣、`maskStyle` 對照、判定函式同一物件與兩模式矩陣、`derived_ui` 守門、正對照夾具）約 +1.0 pd ⇒ 約 28.5 pd**；前三頁 10.0 pd（r2 的 +1.0 屬共同前置，攤在 #1 首先落地） |

### 7.1 前三頁：選擇理由
1. **報價單清單**——最小的完整垂直切片：資料來源單一端點、欄位 22 個且多數非金額、金額遮蔽已有成熟的 5 角色測試模式、個人排序偏好已存在可擴充為 `list_view`。能一次驗證：目錄 schema、解析器（含欄位投影）、衍生欄位搬遷、`quickFilters`、第一批 `alert_rule` 的資料來源。
2. **案件管理—財務總覽**——全金額、純顯示、端點已把數字算好（前端不重算，程式註解自述）；能驗證判定函式登錄表（`money_visible`／前端旗標的前後端判定不一致問題 §8 U5）與『遮蔽後整區消失』的行為；不碰有版本守門的表單。
3. **案件清單與矩陣**——驗證動態欄位家族（閘門）、逐案可見範圍、子查詢按需計算，也是使用者最常用的日常頁。
**不選報價單表單當前三頁**：同檔多班衝突、`FORM_VERSION` 守門、三份手寫渲染，已由脊柱主幹 P2 專責；強行放前三頁會與 M3／專案毛利% 同檔排隊。

## 8. 未知事項（逐項，影響排程者標 ★）

| # | 未知／決定 | 影響 | 我的建議／需誰 |
|---|---|---|---|
| ★U1 | 目錄放 `module.json` 內還是姊妹檔 `catalog.json` | 熱點檔衝突、掃描方式、`SPINE-ENGINE-DESIGN` §3.2 的 `catalog.fields` 語意 | 姊妹檔（§0-2）；需 1c／0d 裁定與 2b 對齊鍵名 |
| U2 | 判定函式登錄表放哪、如何擴充 | 目錄驗證 `unknown_visibility_fn` | `core/spine.py` 擴充點由 L1 登錄（比照驗證器擴充點）；`helpers/financial_mask` 與 `auth`/`cashier` 各登錄自己的；需 2b |
| ★U3 | 清單 API 的 SQL 由目錄投影組裝 | 改 `list_quotations` 核心查詢（6 個子查詢、`SQL_DEAL_TAG`、遮蔽、分頁、計數）；回歸風險最大的一處 | 先做『相同結果、只是欄位按需』的黃金比對；子查詢逐個變成 `source.kind=sql_subquery` 並可按需略過；需 #1 原型 |
| ★U4 | `derived_ui` 欄位（`dealDisplayStatus`、`agingOf`、改版徽章、`item_profit`）搬後端 | 不搬就不能進匯出、規則、檔名 | 先登錄為 `derived_ui`（驗證器：不得進匯出／規則通道）；#1 搬 3 個 |
| ~~★U5~~ 已定案（0d） | 案件頁金額的前後端判定不一致：前端 `canSeeFinancial()` 較窄（財務角色／superadmin），後端 `money_visible`（另含出納模組）、案件清單 `quote_money_visible` | — | **後端函式是真相**；前端 `canSeeFinancial()` 只是較窄的顯示偏好，轉換後由解析器結果決定、前端不再自行判斷 |
| U6 | `privacyClass` 的可見性規則（聯絡資料、統編、地址、獎金）怎麼判 | 客戶通道、檔名、匯出對隱私欄位的處理 | r2：最低通道規則已定（§3 `privacyClass` 列：`filename`／`carry_in`／`customer_excel` 預設排除；獎金經 `bonus_visible` AND 出納頁門檻）；其餘（個資告知 `privacy_notice_acks` 與目錄互動、聯絡資料在匯出的處置）待設計；銀行帳號（`bank`）已在 §4.4b 定案；需使用者／法務確認 |
| U7 | 動態欄位家族（閘門、階段、自訂欄位 `custom_fields`）如何登記 | 閘門 5 欄由後端回傳；自訂模組欄位是另一個目錄來源 | `dynamicFamily`（成員由程式提供）；自訂模組表單設計器的欄位如何併入目錄＝另案 |
| U8 | `status`（`open／planned／hidden`）對目錄項的繼承 | 未完成功能的欄位（例：M3 擇一欄位）要不要先出現在編輯器 | 沿用 `SPINE-ENGINE-DESIGN` §3.7-7：`planned` 灰色列出不可放入版面 |
| U9 | 同一欄位在多個表面的『預設寬度／預設顯示』是否可不同 | 目錄 schema 是欄位級還是（欄位×表面）級 | 預設值放在**表面的 `fields[]` 引用**（`{"id","defaultVisible","width"}`），欄位定義放全域屬性；本文 §3 範例的 `list` 屬性應視為預設，需 2b 定案 |
| U10 | 匯出範本的『列來源』（用哪個篩選、是否分頁）與權限（誰可執行匯出） | 匯出量大時的效能與稽核 | 沿用 `export_logged`＋`quickFilters`；匯出權限沿用各端點既有判定；上限（列數）走設定中心 |
| U11 | 工量未經原型驗證 | §7 數字的誤差可能 ±30% | 做完 #1 後以實績重估；#1 結束前不承諾 #2 以後日期 |
| U13 | §5.7 付款衍生事實（應收逾期、缺發票等）今天對任何有列存取權者可見，目錄記錄為『已接受現況』 | 若使用者視為金額洩漏則需改 `money_visible`（行為變更） | 需使用者確認（備案見 §5.7） |
| U12 | 阻擋類『上限』的政策承載 | 使用者說的『上限』若指阻擋，需政策框架（簽核政策 t55） | 本文只做標紅類；阻擋類另開設計（以政策選項登錄，高影響橫幅） |

## 9. 登錄檢查清單（FL §17.1）對本文的套用

| # | 項目 | 狀態 |
|---|---|---|
| 1 | 功能代號 | `field_catalog`（本文是脊柱的資料面，不新增功能代號）；各表面隨自己的功能宣告 |
| 2 | 欄位目錄項 | §3 schema、§4 種子（約 150 項） |
| 3 | 表面 | §4 各節表面鍵（≤30 字） |
| 4 | 設定群組／風險類 | 本文不新增設定；`alert_rule` 的門檻引用既有設定；`export`／`alert_rule`／`buttons` 為定義文件（版本／還原），風險類 `none` |
| 5 | 標籤與白話 | 欄位白話名＝目錄 `label`；守門沿用 `test_settings_ui_plain_language` 樣式 |
| 6 | 權限與能力 | 判定函式登錄表（§4.4）；編輯版面／範本／規則的權限預設 superadmin |
| 7 | 通知與信件 | 無 |
| 8 | 輸出通道 | 目錄 `channels`＋§5 |
| 9 | 清單欄位 | §4.1、§7 #1 |
| 10 | 稽核與帳本 | 定義文件庫版本；匯出走 `export_logged` |
| 11 | 資料與生命週期 | 免遷移（定義文件新 kind；目錄是程式碼旁的資料檔） |
| 12 | 測試 | §5.4（雙向守門、5 角色、黃金、預設＝今天） |
| 13 | 排班資訊 | §7 工量表；熱點檔：`api/quotations.py`、`quotations.html`、`case-management.html`、`financial_mask.py` |

## 10. 來源
- 脊柱：`FIELD-LAYOUT-FRAMEWORK-T56.md` r9、`SPINE-ENGINE-DESIGN-T57.md` r3、`SPINE-FIXTURES-T57.md` r1、`QUOTE-PROJECT-GROSS-MARGIN-T56.md` r5（逐面可見度模式）。
- 程式：`frontend/pages/quotations.html`（表頭、`agingOf`、`tabs`）、`quotation-form.html`（表單欄位、品項表、損益區）、`case-management.html`＋`js/case-management-{core,list,fin}.js`、`cashier.html`；`backend/modules/case/api/quotations.py`（`list_quotations` :821–956、`get_quotation`、`get_finance_summary` :4510）、`helpers/financial_mask.py`（五個鍵清單與三個判定函式）、`helpers/row_access.py`、`modules/arap/api/cashier.py`（`_require_view_access`、`_bonus_visible`、佇列鍵）、`modules/arap/api/{invoice_vouchers,payment_requests}.py`、`routers/list_prefs.py`、`core/definitions.py`（`KINDS`）、`core/customization.py`／`core/catalog.py`（可自訂點與目錄收集）、`static/margin-tone.js`。
