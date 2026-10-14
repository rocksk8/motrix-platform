# 狀態顯示名稱與顏色（S-X2）：盤點與耦合說明

> 日期：2026-10-14　作者：hichan-3e（受 hichan-b4 指派）　基底 `train/t60-int` 9200a0b81　僅讀程式碼、未執行。
> **查證程度**：下列行號由三個唯讀盤點子任務掃出，我只抽查了 `status-chip.js`、`quotations.py` 結案閘門與 `approval_queue.py:26`（V）；其餘為 (S)，使用前請以現行程式為準。後端那份的審核狀態部分有 120 筆上限，可能不完整。
> 目標：**狀態的『顯示名稱』與『顏色』變成一張受治理的表（改名、改色、排序可調）；狀態的『鍵』（資料庫值）永遠不變、所有查詢與判定繼續用鍵。** 金額類狀態也只做顯示。

## 0. 結論

1. **顯示層是 5 種方言各寫一份**，且同一個值在不同頁面有不同名稱（見 §3）；唯一的『單一對照』`static/status-chip.js`（V：只有 `草稿→draft … 已作廢→void` 的色調表，**沒有名稱**）目前只有 `inventory.html` 與 `payment-request.html` 載入，報價、案件、出納、報表都沒用。
2. **後端幾乎不回狀態標籤**：`deal_tag` 與審核狀態在 API 都是原始值，由前端映射。後端回標籤的只有：單據類型（`typeLabel`）、自訂模組狀態（`statusLabel`）、派工狀態（`_STATUS_LABELS`，`pdf_gen.py:2595` 另抄一份）、請款款項類別（`stageLabel`）。所以這張表**主要是前端問題**，後端只需要『PDF／Excel／郵件裡印狀態字』那幾處（§2B）。
3. **邏輯一律不動**：所有 `x-show`／篩選／權限／SQL 都用鍵（§2A、§4）。這張表只能換『看到的字』與『看到的色』。
4. **最大風險**：同一個鍵在 6 處以上被寫成字面值（已成案／已結案）；名稱若改成別的字，使用者會看不出『已核准』是不是真的已核准——所以要有官方用語保護（§5）。

## 1. 現有的對照與重複（顯示層）
| 類別 | 位置（S，除註明 V） | 內容 |
|---|---|---|
| 色調共用表 | `static/status-chip.js:6-13`（V）；`css/style.css:952-965` `.st-chip--*`（語意 token） | 草稿/待審核·待核准/簽核中/已核准/已駁回·已退回·已拒絕/已付款·已匯款/已作廢·已取消·已撤回·已撤銷 → 7 種色調；只有 inventory.html、payment-request.html 載入 |
| `badge--*` 色表（寫死 hex） | `css/style.css:930-948`；4 份完全相同的 JS 對照：`case-management-dispatch.js:845`、`-fin.js:731,834`、`-shipping.js:471`；`payment-request-form.html:395` `statusClass()` | 草稿/待審核/簽核中/已核准/已駁回/已作廢 → draft/pending/signing/approved/rejected/lost |
| `badge-green/amber/gray` | `case-management-completion.js:145-149` | 另一套 class 家族 |
| 行內樣式函式 | `-xexp.js:60-65,276-280`（`xeStatusStyle`、`xeChangeStatusStyle`）、`-mchange.js:57-60`、`-exec.js:143-148,206-212`（`moPayTone`、`moApTone`） | 同義異色（已核准=綠、待審/簽核中=琥珀、駁回/退回=紅、草稿/作廢=灰） |
| 名稱函式（多為原值照印） | `dispatch.js:840-846`、`fin.js:726-728,829-831`、`shipping.js:466-468`、`completion.js:144`、`exec.js:199-203` | 身分對照＋原值退回 |
| 報價單列表 | `quotations.html:653-664` `statusBadge()` | **唯一有改名的對照**：待審核→『審核中』、已拒絕→『已退回』、已成案→『執行中』、已提供→『待決定』、未成案→『未成案』、已結案→『已結案』 |
| 報價單表單 | `quotation-form.html:819,834`（同一物件寫兩次，沒有簽核中）、`:856-858`、`:868` | 狀態色、成案鎖定徽章（已結案紫／其他綠，與 `quotations.html:298` 同色寫兩份） |
| 案件列表／頁首 | `case-management.html:336-337,391-392`（同一標籤寫兩次）、`:443-455`、`:2698-2699` | deal_tag 卡片標籤與頁首徽章；精算狀態文字『已定稿』 |
| 精算頁 | `settlement.html:303-312`（精算完結／精算草稿）、`:964`（已完結（凍結）） | 同一個 `finalized` 在三處有三種說法（精算完結／已定稿／已完結（凍結））；另 `reports.html:1251`（已結算）、`:2178`（已定稿） |
| 出納 | `cashier.js:223` `remitReviewLabel`（差額待審核／差額已核可）；`cashier.html:613`（已收款/待收款）、`:369-370` 與 `:502-503`（同文不同色：已逾預定日） | |
| 傳票 | `voucher.html:248-249,318-319`（已作廢／已過帳，其餘狀態無色）、`:238` 篩選下拉（**選項文字＝值**，需拆開） | |
| 報表 | `reports.html:672,712,1103,1142,1243`（deal_tag→`rb-closed/rb-active`，5 處）、`:1554-1556`（**另一種**映射）、`:2176-2178`（行內色） | 同值不同色 |
| 總帳 | `ledger-hub.js:191`（drafted/posted/drift/reversed/…→中文）、`ledger-reports.html:155` | 引擎事件狀態（英文鍵） |
| 派工狀態（英文鍵） | `dispatch.js:969-971`；後端 `vendor_contractors.py:53`、`pdf_gen.py:2595-2605`（兩份） | draft/sent/confirmed/pending_acceptance/accepted/completed/cancelled |

### 1.1 同值不同名（要統一或保留的）
待審核＝『審核中』(`quotations.html:654`)／『待審核』；已拒絕＝『已退回』(:658)；已成案＝『執行中』(:662)／『待 <階段>』(`case-management.html:337`)／『已成案』；已提供＝『待決定』(:663)；`finalized`＝精算完結／已定稿／已結算／已完結（凍結）。**表要允許『同一個鍵在不同情境用不同名稱』嗎？** 建議：一個鍵一個名稱＋可選的『情境簡稱』（`short`）欄，預設值保留今天的各種說法，不強迫統一。

## 2. 後端耦合
### 2A. 必須維持原始值的邏輯（不可動，S）
- `deal_tag` 已成案／已結案：`arap/gl_events.py:19`、`arap/receivables.py:161,231`、`arap/api/cashier.py:440`、`case/recognition.py:122`、`case/api/settlement_api.py:77`、`case/api/quotations.py`（約 :284,427,502,829-875,933-934,1029,1056,1213,1972,2562-2626,2775,3005,5819,6584）、`case/alt_sign.py:117`、`case/case_deadlines.py`、`analytics/api/dashboard.py`、`analytics/api/reports.py`（13 處，:1477 是顏色挑選）、`payroll/api/bonus.py:548,1176`、`db.py:1935-1974`、`pdf_gen.py:2521`。
- 審核狀態 待審核／簽核中：`helpers/approval_queue.py:26`（V：唯一定義）、`quotations.py` 結案閘門（V：`_CLOSE_DOC_TABLES`、`_close_gate_facts`）與待簽佇列 SQL（約 4764-4890）、`material_approvals.py:353`、`completion_notes.py`、`case_extra_expenses.py`、`payroll/*`、`accounting/voucher.py:36,41,51,381`；`db.py:4591` 的 CHECK 約束。
### 2B. 會印出狀態字的後端輸出（若要跟著表，最後一批）
`routers/approval_queue.py:231-264`（`typeLabel`，與前端 `docTypeLabel()` 鏡像）、`vendor_contractors.py:53,198` 與 `pdf_gen.py:2595`（派工狀態兩份）、`pdf_gen.py:2118,2150`（款項類別）、`reports.py`（Excel／HTML／PDF 文字：『已結案 N 件』『已結案未精算』『進行中』等）、`helpers/email_notify.py`（主旨與徽章『待審核』）、`payroll/*_notify.py`、`quotations.py` 各 HTTPException 與通知文字、`helpers/google_calendar.py:236,250,571`。**第一期不動這些**：郵件／PDF／錯誤訊息是『固定語彙』，改名會讓客服與稽核紀錄對不上；列為第二期選配。
### 2C. 顏色
後端沒有狀態→顏色對照（除了 `reports.py:1477` 的報表內部挑色與郵件徽章 hex）。顏色完全是前端問題。

## 3. 設計約束（來自耦合）
1. **鍵集合由程式擁有**（`helpers/status_display.py` 內的登錄，含群組：`approval`／`deal`／`settle`／`remit`／`dispatch`），使用者**不能新增或刪除鍵**；表只存 `label`、`tone`、`order`、`short`。
2. **色調只能從固定調色盤選**（`draft/pending/signing/approved/rejected/paid/void/neutral/info/violet`，對應語意 token 的 `.st-chip--*`），不收自由色碼——不引入新 CSS 值、深色模式自動跟著 token。
3. **金額狀態也只做顯示**：這張表不帶任何金額欄位、不隨 API 回金額；所有人都可讀（登入即可），因為它只是字與色。
4. 邏輯程式碼（§2A）**一律不讀這張表**；掃描式守門測試：新增的 `x-show`／SQL 不得出現『顯示名稱』字面值（只能是鍵）。

## 4. 前端落點（逐步，不一次改）
第一期只改『共用函式』與其已載入的頁面；各頁面的私有對照（§1）分批改成呼叫它，**每批都用黃金對照（今天的名稱與 class 逐一相同）**：
1. `MotrixStatus.label(raw, ctx)` 與 `chipClass(raw)`：表未載入或旗標關 ⇒ 回今天的值（label 原值照印、色調用內建 MAP）。
2. 批次一：`payment-request.html`、`inventory.html`（已載入 status-chip.js，行為不變）。
3. 批次二：案件頁六個 `_*StatusClass/_*StatusLabel`（四份相同對照合併）。
4. 批次三：報價單列表／表單（含『審核中／執行中』這類別名保留為預設表值）。
5. 批次四：出納、報表、傳票、精算頁。

## 7. 第二批消費點：出納與報表（逐行；2026-10-14，基底 99cadb75d；行號為該基底，(V)＝我讀過）
> 原則同前：只換『看到的字』（與已有 `badge--*`／`st-chip` 色調的 class），**所有判斷仍用原始值**；旗標關或沒改過 ⇒ 回呼叫端給的 fallback，與今天逐字相同。判斷依據是盤點 §1 的出納／報表列與我這次逐行重讀。

### 7.1 要接的點
| # | 位置 | 今天 | 顯示用的鍵／情境 | 改法 | 備註 |
|---|---|---|---|---|---|
| C1 | `cashier.html:613`（V） | `it.received ? 'rb-received' : 'rb-pending'`，字 `'已收款' : '待收款'` | 新鍵 `已收款`（付款語意）、`待收款`（一般）／cashier | 只換字：`stLabel(it.received ? '已收款' : '待收款', 'cashier')`，class 不動 | 這是布林欄位 `received`，不是資料庫狀態字串；新增鍵由程式登錄，邏輯仍用 `it.received` |
| C2 | `cashier.html:586-587, 317, 638-639`（V） | 分頁／摘要的『未收款／已收款／待收款』靜態字 | — | **本批不接**（含狀態詞的分頁／摘要文字，見 7.2.1） | 04 審查：需明說這些標題維持系統用語 |
| C3 | `js/cashier.js:223` `remitReviewLabel`（V） | `pending→差額待審核`、`approved→差額已核可` | 新鍵 `差額待審核`（一般）、`差額已核可`（核准語意）／cashier | 函式內改成 `MotrixStatus.label(…, 'cashier', 原字)`；`cashier.html:732` 已經走這個函式 | 決定動作仍用 `approve`／`reject`（js/cashier.js:276-286 不動） |
| C4 | `cashier.html:542` | `it.signedBack ? '已簽回' : '未簽回…'` | 暫不接 | — | 布林＋說明文字混在一起，價值低 |
| C5 | `cashier.html:369-370, 502-503` | `已逾預定日`、`N 天內到期`（衍生狀態，不是資料庫值） | **不接** | — | 不是狀態值；兩處顏色不一致（`--tone-*` vs `#b91c1c`）另案統一 |
| C6 | `payment-request.html:315, 361, 703, 724`（S） | 列表狀態 `e.status` 原值＋`chipClass` | 既有鍵／cashier | 字：`MotrixStatus.label(e.status, 'cashier')`；色已走 `chipClass` | 這頁已載入 `status-chip.js`；判斷（361、703、724）不動 |
| C7 | `payment-request-form.html:395`（S） | `statusClass()` 的 `badge--*` 對照 | 既有鍵 | `MotrixStatus.badgeClass(raw, 今天的 class)` | 只有被改色的鍵才換 |
| R1 | `reports.html:672, 712, 1103, 1142, 1243`（V） | `:class="X.dealTag==='已結案'?'rb-closed':'rb-active'"`，字 `X.dealTag` | 既有鍵 已成案／已結案／未成案…／report | 只換字：`stLabel(X.dealTag, 'report')`，class 不動 | 5 處同一運算式 |
| R2 | `reports.html:1554-1556`（V） | 另一種映射（已結案→rb-fin、已成案→rb-active、未成案→紅、其他→rb-closed），字 `dealTag \|\| status` | 同上 | 只換字 | 同值不同色的不一致保留（色不接） |
| R3 | `reports.html:1251`（V） | `settleStatus==='finalized'?'已結算':'草稿'` | `finalized`／`draft`／report | `stLabel('finalized','report','已結算')`／`stLabel('draft','report','草稿')` | 預設情境簡稱＝已結算 |
| R4 | `reports.html:2177-2178`（V） | `stlStatus()==='finalized' ? '已定稿' : '草稿'`，行內色 | 同上 | 只換字，fallback 傳 `'已定稿'`（與 R3 今天就不同，保留不統一；管理者設 report 簡稱後兩處才一致） | 行內色不動 |
| R5 | `js/reports.js:974-984`（S） | 圖表／KPI 標籤 `進行中`、`已結案` | `已結案`／report | 只換 `已結案` 字（`進行中` 不是狀態鍵） | 低優先 |
| R6 | `reports.html` 其他 `已結案`、`待匯款` 說明文字 | 靜態說明 | **不接** | — | 敘述文字，不是狀態徽章 |

### 7.2 不接（理由）
- 伺服器端產生的 Excel／PDF／HTML 報表文字（`reports.py` 內的『已結案 N 件』等）、郵件、錯誤訊息：第二期（固定語彙，客服與稽核要對得上）。
- 衍生狀態（逾期、即將到期）、布林旗標的說明句、UI 內部鍵（分頁鍵、`remitReview` 的 pending/approved 傳遞值、決定動作 approve/reject）。
- 顏色（`rb-*`、行內色）本批只有 C7 與 C6 走既有 `st-chip`／`badge--*`；`rb-*` 與行內色的色調映射留到下一批（需要先決定 `rb-*` 對應哪個色調）。

### 7.2.1 文字規則（04 審查補充）
- **只換『狀態徽章與狀態欄』裡的字**。動詞與按鈕（標記已收款／標記已匯款／確認標記…，`cashier.html:373,415,625,1110,1155,1214,1238,1268,1292`）、說明文字（`:803,865` 會計說明）、區段標題與空狀態句（`:713,716,773,775` 已匯款明細／已收款明細／此區間沒有…紀錄）、統計卡標題（`:296,300,304` 待收款總額／本期已匯款／本期已收款）都是**含狀態詞的句子**，**不跟著表改**。
- 結果：管理者把『已收款』改名後，狀態欄會顯示新名稱，而上述標題與按鈕仍寫系統用語。編輯面板在『出納收款』『匯款差額審核』群組下方明說這一點。
- `receivableFilterTab`（`unreceived`／`received`）是 UI 內部鍵，不接；`it.received` 是儲存的 JSON 旗標（`quotations.py:776,785,1177,2348,2928-2965`、`tax_calc.py:216`、`financial_mask.py`），所有判斷維持直接讀它，顯示字只放進 `x-text`，**不得傳進任何篩選**。
- 衍生狀態（逾期、即將到期）與 `remitReview` 的傳遞值（pending／approved）不接；`cashier.js:223` 是唯一把傳遞值轉成字的地方。

### 7.3 新增鍵（程式登錄，仍是 display-only）
`已收款`（paid 語意，預設色調 paid）、`待收款`（plain，pending）、`差額待審核`（plain，pending）、`差額已核可`（approved 語意，approved）。四個都不改任何資料庫值；`remit` 的 `pending`／`approved` 仍是傳遞用的英文值。

### 7.4 載入與請求
- `cashier.html`、`reports.html`、`payment-request.html` 目前都沒有讀 `builder_status_display`：每頁要用 `MotrixPublicFlags.read` 讀一次旗標（旗標關也會有一次請求）；`cashier.js` 另有 F3（`wip/t62-finance-r2`）的 `finance_cashier` 讀取——兩者合併時應改成**同一個請求**（`groups=finance_cashier,builder_status_display`），由整合者處理。
- 旗標開才呼叫 `MotrixStatus.load()`（多一個 `GET /api/status-display`）。
- 黃金對照：這三頁沒有現成的黃金檔；OFF 的證明用 node 測試把每個改過的運算式在『表未載入』時與原運算式逐字比較（同報價單列表那一題的做法）。

### 7.5 第三批（精算頁、傳票頁）：已接與未接（04 審查後）
- **已接**：`settlement.html` 草稿徽章與完結徽章（完結字包在 span 裡，DOM 結構與版面不變）；`voucher.html` 列表狀態欄、編輯頁標題、**狀態篩選下拉的選項文字**（`:value` 維持原始狀態字，所以篩選邏輯不變）；`case-management.html:2701`（精算徽章字，後備『已定稿』）；`reports.html:1253`、`:2180`（精算字，後備『已結算』『已定稿』）。
- **本批不接**：`case-management.html:2727`、`reports.html:2183`（`x-if="…==='finalized'"`，是判斷）；`case-management.html:2731` 的句子『精算完結 · 精算日期：…』（含日期與人員的整句，不是狀態徽章）；`settlement.html` 約 40 處 `status==='finalized'` 判斷與 `:964` 的『已完結（凍結）』『草稿（未凍結）』稽核列說明；`js/ledger-hub.js:191` `statusLabel`（總帳**引擎事件**狀態：drafted／posted／drift／reversed…，英文鍵，是另一個領域，與傳票單據狀態不同鍵；其中 `posted→已過帳` 的字不跟傳票的『已過帳』顯示名連動）；`ledger-reports.html:155` 的『未過帳』字尾；`js/voucher.js` 其餘的狀態字面值（判斷用）。
