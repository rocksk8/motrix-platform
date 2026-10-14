# T63 F4：請款單「款項類別」清單單一來源 — 耦合清單與做法

> 日期：2026-10-14　分支 `wip/t63-pay-stage-src-r1`（基底 `origin/wip/t62-int-c1` 7ae47bbfd）　僅讀碼；本批只做 py_compile／node 檢查，不跑 pytest。
> 出處：`FINANCE-FRAMEWORK-INVENTORY-T62.md` §4 F4「款項類別清單單一來源（後端定義 → 前端讀同一 API）」。
> **S-F1（選項清單 `payment_request_stage`／`payment_stage`）已做的**：顯示名稱可改（`option_lists.request_stage_label`／`payment_stage_display`），請款單 PDF／清單／詳情已走它。**沒做的（本批）**：「代碼清單」本身仍有多份手抄。

## 1. 現況：同一份 5 個代碼（full／deposit／delivery／acceptance／final）有 4 份
| # | 位置 | 角色 | 本批 |
|---|---|---|---|
| A | `helpers/option_lists.py` `BUILTIN["payment_request_stage"]["defaults"]` | 選項清單的程式預設（closed：只能改名與順序，不能增減代碼） | **成為唯一來源** |
| B | `modules/arap/api/payment_requests.py:100` `PAYMENT_STAGES` | 建立／更新請款單的**驗證集合**（`body.stage not in PAYMENT_STAGES` ⇒ 400，:373、:469）＋ `stageLabel` 後備 | 改為由 A 衍生（內容、順序逐項相同） |
| C | `pdf_gen.py:2121` `_PAYMENT_STAGE_LABELS` | 客戶端請款單 PDF 的款項類別後備字（:2159，查不到 ⇒ 『未分類』） | 改為由 A 衍生 |
| D | `frontend/pages/payment-request-form.html:382` `STAGES` | 款項類別按鈕的後備清單（`MotrixOptions.items('payment_request_stage', STAGES)`；選項清單沒開 ⇒ 用它） | 改為讀後端（見 §2）；留一份**僅在請求失敗時用的後備**，由守門測試鎖定等於 A |

案件款項期別（`payment_stage`：訂金款…其他，8 個，**自由字串**、值就是顯示字）另有 `case-management-core.js:105` `STAGE_ITEMS` 一份。它不是代碼（沒有驗證集合，自訂義還有 `customLabel`），**本批不動**；只在守門測試鎖「前端後備 = 後端預設」以防漂移。

## 2. 做法
1. **後端單一來源**：`option_lists.request_stage_defaults()`／`request_stage_codes()` 由 A 產生；B、C 由它衍生（`PAYMENT_STAGES = {代碼: 名稱}`，順序與今天相同）。
2. **端點**：`GET /api/payment-requests/stages`（登入即可，`_require_user`；只有代碼與名稱，**沒有任何金額**，不需要金額遮蔽）⇒ `{items:[{value,label,disabled}], source:'default'|'published'}`，內容＝`option_lists.effective("payment_request_stage")`（旗標關／沒發布 ⇒ 程式預設，逐項等於今天的 5 個）。必須註冊在 `/{request_no}` 之前（同 `/remaining`）。
3. **前端**：請款單表單載入時取一次；取到 ⇒ 按鈕用它；取不到 ⇒ 用現有後備 `STAGES`（畫面與今天相同）。**舊值／未知代碼仍要畫得出來**：目前這張單的 `q.stage` 若不在清單裡（理論上只有歷史資料），多畫一顆『代碼（舊值）』按鈕，不洗掉、不改存檔值。`MotrixOptions.items` 的既有路徑（選項清單開啟時 sidebar 帶的 `MOTRIX_OPTION_LISTS`）保留為優先，與端點內容一致。
4. **不改**：驗證規則（代碼仍須在 PAYMENT_STAGES 內）、金額計算（`scope`／比例）、請款單狀態機、單號、簽核、PDF 版面、報表的款項期別欄、案件款項期別。

## 3. 耦合清單（改動不得影響）
- 請款單流程：建立／更新驗證（B）、`_request_public.stageLabel`、`payment-request.html` 清單與詳情、`payment-request-form.html` 表單；`q.stage` 存進 `payment_requests.stage`（db v57 欄位，代碼字串）——**代碼不變**。
- PDF：`pdf_gen._build_payment_request_html_core` 款項類別（C）；已送出的檔案不改。
- 報表／出納：用的是案件款項期別 `payment_stage`（`reports.py`、`cashier.py`、`receivables.py`、`dashboard.py`、`receipt_calendar.py`），**不同清單，不受影響**。
- 簽核／傳票／總帳：不讀這份清單。
- 路由登記：新增 1 條 GET ⇒ `tests/platform/route_inventory.json`、`modules/case/tests/route_table_golden.json`、`tests/platform/response_keys_baseline.json` 需同提交加列（本批手寫；**整合者以 `U0B_RECORD=1`／`U0A_RECORD=1` 重錄對照**）；`docs/platform/dep_graph.json`、`case_read_scope.json` 由整合者 regen。

## 4. 守門（新增 `backend/tests/test_payment_stage_single_source_2026_10_14.py`）
①B、C 的內容逐項等於 A；②端點在旗標關時回 A（靜態＋函式層）；③前端後備 `STAGES` 與 `case-management-core.js` 的 `STAGE_ITEMS` 等於後端預設（node 讀頁面抽出）；④舊值按鈕邏輯 node 黃金對照（清單內 ⇒ 不多畫；清單外 ⇒ 多一顆）；⑤頁面不再有第二份驗證用的寫死集合。本批不跑 pytest，以直接呼叫＋node 驗。

## 5. 風險
低：預設內容逐項不變、只新增唯讀端點與前端讀取；失敗退回現有後備。最大風險是**手寫的路由基準檔列**與實際不符（整合者重錄即可）。
