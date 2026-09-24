# SPEC-AC2：營運報表認列口徑（權責／現金）與待補登標註

規則來源：使用者 2026-09-24 裁示；細部見 `HANDOFF-PENDING-2026-09-23.md`「AC2 細部」「AC2 差異標註」兩節（hichan-0a 裁）。
本檔記**實作落點**與**交付時必須告知使用者的事**。

## 一、口徑

| | 權責（預設 `basis=accrual`，損益） | 現金（`basis=cash`，實際收付） |
|---|---|---|
| 收入 | 成交**未稅** × 階段比例，認列在階段完成月（`done_at`）；全部未設比例 ⇒ `MAX(done_at)` 一次認列；有階段未完成 ⇒ 該部分不認列 | 實收（含稅），依收款日 `receivedAt`（既有 `_collect_income_items`） |
| 派工 | 發票日 → 驗收日 → 派工日（後兩者為暫用）；承攬商部分**未稅**，外包人員全額（標「未拆稅」） | 匯款申請 `is_paid=1` 的 `paid_at`，金額＝快照 `grandTotal`（含稅） |
| 叫料 | 發票日 → 付款日（暫用）；全額，標「未拆稅」 | `paidStatus≠pending` 的 `paidDate`、`paidAmount` |
| 額外支出 | 發票日 → 核准日 → 憑證日（後兩者為暫用）；全額，標「未拆稅」 | 付款日 → 憑證日（暫用） |
| 進貨 stock_items | 不在 AC2 範圍，兩口徑照舊（`created_at`、`cost`） | 同左 |

- 比例合計 ≠ 100% ⇒ 照比例認列、**不補差**。`ratio_bp` NULL＝未設、0＝該階段不認列（兩件事）。
- 四捨五入一律 `round_half_up`（Python `round` 是銀行家捨入）。
- 日期 `''`＝未登錄，判斷一律 `== ''`。

## 二、落點

```
v115        case_stages.ratio_bp／contractor_dispatches.invoice_date／
            case_extra_expenses.invoice_date、paid_date
邏輯        backend/helpers/recognition.py（純函式 stage_revenue＋三種支出逐筆＋recognition_flags）
報表        GET /api/reports/expenses-monthly?basis=accrual|cash（Excel／PDF 匯出同參數）
            回應新增 basis／basisNote／incomeTaxLabel／recognitionFlags
補登端點    PUT  /api/quotations/{q}/stages/{id}               ratioBp
            PATCH /api/contractor-dispatches/{id}/invoice-date  （已有匯款申請也可登）
            PATCH /api/quotations/{q}/extra-expenses/{id}/dates  invoiceDate／paidDate（任何狀態可登）
            PATCH /api/quotations/{q}/material-orders           品項 invoiceDate（整份覆寫；已結案 400）
            PATCH /api/quotations/{q}/material-orders/{itemId}/invoice-date  只登一筆（任何案件狀態，含已結案）
首頁        GET /api/dashboard/expenses-monthly 改呼叫 reports._collect_expenses(basis="accrual")，回應帶 basis／basisLabel
畫面        reports.html 收支頁：口徑切換、頂端說明、待補登清單（逐種數量＋展開＋連到案件頁）
            case-management.html：階段比例＋合計提示、派工發票日、額外支出發票日／付款日、叫料發票日
```
- 派工 PUT 沒帶 `invoice_date` ⇒ 保留原值（其他頁面的 PUT 不會把已登錄的清掉）。
- 待補登：支出類只列歸在所選年度的；案件類（比例未設／≠100%／未完工／舊稅率）不分期別。金額遮蔽比照 CM13 `money_visible`。

## 三、交付時必須告知使用者

1. **營運報表收支頁的數字會變**：預設改權責口徑（收入依階段完成、未稅；支出依發票月；派工改未稅；**叫料原本沒算、現在算進去**）。頁面頂端有說明。
2. ~~首頁儀表板的月支出沒有改~~ **更正（hichan-0a 裁示）**：首頁 `/api/dashboard/expenses-monthly` 改呼叫報表同一支計算（權責口徑），同一個月只有一個數字。
   ⚠️ 實查：首頁目前**沒有任何地方顯示**這個月支出（`index.html` 的 `currentMonthExpenseTotal` 只定義、沒被渲染）⇒ 畫面上沒有可以標「權責口徑」的位置；API 回應已帶 `basisLabel`，日後接上畫面時照用。
3. 上線當下**所有案件都會列在「階段比例未設定」**、所有派工／叫料／額外支出都會列在「未登錄發票」：欄位是新的，需要財務逐筆補登。
4. ~~已結案案件的叫料發票無法登錄~~ **更正（hichan-0a 裁示）**：新增只登一筆發票日期的專用端點，任何案件狀態都可以登、不動金額、寫稽核；頁面上改了就直接存。
5. 叫料與額外支出沒有稅額欄 ⇒ 權責口徑用全額並標「未拆稅」（稅額欄列 NEXT）。
6. 順帶修正：案件管理的 `?q=` 深連結原本只在「目前清單」找，預設清單排除已結案 ⇒ **已結案案件的連結打開後什麼都沒選到**（待補登清單會連過來）。改成從全部案件找，已結案就切到「已結案」清單再選取。
