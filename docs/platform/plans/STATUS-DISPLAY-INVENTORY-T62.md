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
