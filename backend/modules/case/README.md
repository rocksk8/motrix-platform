# M01 案件（case）

報價單、案件管理（階段、執行進度、動態、額外支出、叫料、完工單、案件整包）、簽核佇列與簽核歷史、業務訂單（`/api/sales-orders`）。

## 內容

| 檔 | 說明 |
|---|---|
| `api/quotations.py` | `/api/quotations*`、`/api/approval-queue*`、`/api/approval-history`、`/api/case-batch`、`/api/case-changes`、`/api/next-quote-no`、`/api/sales-orders` |
| `api/case_action_items.py` | 案件待辦 |
| `api/case_extra_expenses.py` | 案件額外支出（含變更申請） |
| `api/completion_notes.py` | `/api/completion-notes*` |
| `api/material_orders.py` | 叫料 |
| `quotations.py` | 報價單熱欄位同步、驗證；提供者：`case.access`、`case.summary`、`case.locations`、`case.recognition`、`case.default_terms`、`case.doc_version` |
| `recognition.py` | 收入認列／支出歸月／待補登（經 `case.recognition` 給 M08） |
| `quote_terms.py` | 報價條款預設值、送審原因 |
| `case_deadlines.py` | 每日到期檢查（`daily.check`） |
| `case_stage_tasks.py` | 執行進度勾選 → 每日工作事項 |
| `completion_pdf.py` | 完工單 PDF |

表：quotations、quote_seq、case_stages、case_stage_visits、case_updates、case_action_items、case_change_requests、case_extra_expenses、completion_notes（凍結 migration 建立）。
頁面 8 頁仍在 `frontend/pages/`（模組頁面尚無服務路徑）；案件頁的 `js/case-management-*.js` 11 支同。

## 串接點

- 提供：見上表與 INTEGRATION-POINTS（IP-12 case.access、case.summary、case.locations、case.recognition、case.default_terms、case.doc_version、IP-17 quotation.append_items、IP-6 calendar.writeback、approval.reassign 的 quotation／completion_note、IP-11 daily.check）
- 取用：IP-1／IP-14／IP-15（M04）、IP-18／IP-19（M03）、approval.queue_items／approval.reassign／approval.detail（各單據模組）、case.default_terms 的取用方是 L1 system

## 本模組不在時（別人怎麼辦）

- L1：`routers/system` 報價條款端點 404 並明說；`pdf_gen` 不記版本紀錄；地圖不列案件（case.locations）
- M08 報表：權責收入 `incomeNotice`、支出 `unavailable` 列案件類、待補登 {}；成案月份 {}
- M10 網路規劃：綁案件改用 case.access（IP-12）的「不在」分支
- M12 每日工作：`/api/sales-orders` 不在 ⇒ 待④（M01-PLAN §5）

## 尚未處理

- ③ 提供者改成 ModuleSpec 宣告（CA-O3）；④ SO 提示與補題；⑤ ATT（A 的 attachments.for_document）已知例外＋到期守門
- 其他模組直接讀本模組的表（M01-PLAN §2-B）：讀取連接器另案
