# M05 應收應付（key `arap`）搬遷步驟表（C，2026-09-26 草稿；開工基底＝第六班合回後的 origin/platform）

> 依據：PLAYBOOK §B 1～15；dep_scan（b-m08-2 f7463dfa 上量測，第六班合回後要重量一次）。

## 0. 成員（modules.json M05）

| 類 | 單位 | 去處 |
|---|---|---|
| router | cashier、invoice_vouchers、payment_requests | `modules/arap/api/{cashier,invoice_vouchers,payment_requests}.py`（CORE-SPEC §3：多支 router 放 api/） |
| 頁面 | cashier.html、payment-request-form.html、receivables.html | ⚠ 模組頁面尚未有服務路徑（page_files 支援 `modules/*/pages`，main 沒掛）⇒ **留在 frontend/pages**，與 M04／M07 相同；列入待辦 |
| js | js/cashier.js | 同上，留原處 |
| 表 | invoice_vouchers、payment_requests | module.json `tables`；migration 不動（凍結 migration 讓表在模組不在時仍存在） |
| 收回 | `helpers/receivables.py`（A8b 中繼，B 的 b-m08-2 新增） | `modules/arap/receivables.py`，以 provider 公開 |
| 收回 | `/api/reports/bank-reconcile`（analytics/api/reports.py:2676，M08 暫留） | 移到 `modules/arap/api/cashier.py`（路徑不變）；analytics tests 的 7 題 bank_reconcile 隨之搬 |

## 1. 跨組相依（逐條處置；每條登記 INTEGRATION-POINTS 六項）

### M05 → 別人
| # | 相依 | 處置 |
|---|---|---|
| a | cashier → M04 `contractor_vouchers._voucher_public` | 已是 IP-14（c-m04-2），確認合回後 cashier 只走 provider |
| b | cashier／invoice_vouchers／payment_requests → M01 `helpers.quotations`（payment_item_amounts、quote_tax_type、tax_split、LEGACY_TAX_NOTE、guard_case_access、is_document_approver） | ~~`helpers/quotations.py` 目前是 L1 ⇒ 不算跨組~~〔更正：modules.json 把 `helper:quotations` 歸 M01，dep_scan 列為 M05 → M01 跨組〕guard／is_document_approver 改直接 `from helpers.case_access import`（IP-12，已在 L1）；稅額純函式（payment_item_amounts、quote_tax_type、tax_split、invoice_amounts、LEGACY_TAX_NOTE）＝ M01 步驟表 §2 的「先下沉 L1 `helpers/tax_calc.py`」——**M05 開工前要先有**，否則 M05 搬進模組後就是 L2→L2 import |
| c | cashier 讀 `contractor_payment_vouchers`、`quotations` 表 | 前者改走 IP-14（確認沒有殘留 SQL）；quotations 表讀取＝M01 資料，暫列 L1 共用讀（O-2 類），M01 搬遷時改 provider |
| d | invoice/payment 讀 `customers` 表 | customers 屬 L1（確認 modules.json） |
| e | js/cashier.js 呼叫 M08 reports、M06 accounting_export、M07 bonus、M04 contractor_vouchers、M01 quotations | 前端呼叫；各自不在時頁面要說出原因（IP-14 已有 M04 的 notice 樣式）。逐一列：M07 bonus（IP-8 bonus.payouts 在 cashier 後端已走 provider？要查）、M06 T100、M08 報表 |
| f | payment-request-form.html 呼叫 M10 netplan、M01 case_action_items／case_extra_expenses／material_orders／quotations | 前端；M10 不在時的降級要查 |

### 別人 → M05
| # | 相依 | 處置 |
|---|---|---|
| g | M01 case-management-fin.js、approval-queue.html → invoice_vouchers／payment_requests API | M05 不在 ⇒ 案件頁「開票／請款」段與簽核佇列要說「應收應付模組未安裝」（新 IP，比照 IP-14 前端 notice） |
| h | M08 reports.js → /api/cashier/{payable,receivable}-queue、execution-history | M05 不在 ⇒ 報表那兩區顯示「未安裝」而不是「無權限」（reports.js:632 目前把 403 當無權限——404 要另分） |
| i | L1 讀 M05 表：google_calendar（:249/:274）、voucher_attachments（:164/:299）、core:archive、core:pdf_gen、routers/quotations（:1999/:4281/:4540/:4606/:4968）、db（W：migration） | 讀取：凍結 migration 讓表常在 ⇒ 不會壞；但「不在時」語意要決定：案件頁彙總（quotations:4281）M05 不在時該回空清單＋notice。改成 M05 provider `arap.case_documents`（名稱待定）；google_calendar／voucher_attachments 是 L1 服務 M05 的，留 L1 |
| j | M06 accounting_export → `helpers.receivables.collect_tax_invoices` | 收回後改 provider `tax_invoices.list`；M05 不在 ⇒ T100 匯出說明「收款事件來自應收應付模組，未安裝」 |
| k | M08 analytics/api/reports.py → `collect_income_items`／`collect_tax_invoices` | 改 provider `income.items`／`tax_invoices.list`；M05 不在 ⇒ 報表收入段 notice |
| l | 4 個 tests import `helpers.receivables`（test_case_management_logic_fixes、test_invoice_date_and_case_record_validation ×3、test_reports_tax_compliance、test_tax_by_law） | 隨 provider：題搬進 modules/arap/tests 或改呼叫 provider |

## 2. 步驟（依序；每步可單獨驗）

1. 第六班合回後 `git worktree add ..\MOTRIX-PLATFORM-C35 -b wip/c-m05 origin/platform`；重跑 dep_scan、確認 §1 表沒變（有變就先更新本表）
2. **先切相依（不搬檔）**：
   - receivables → `modules/arap/` 前先在 L1 位置加 provider 登記點？——不行（provider 只在模組載入時登記）⇒ 順序：建 `modules/arap/`＋ModuleSpec providers（`income.items`、`tax_invoices.list`）→ M06／M08 改 `registry.providers(...)`、不在時 notice → 刪 `helpers/receivables.py`
   - ⚠ 跨檔重構用自己的 worktree（記憶：刪定義先於改呼叫端會讓 import main 壞）；每步 `ast.parse`＋import main 冒煙
3. 案件頁彙總（i）改 provider；M01 前端 notice（g）；報表 404≠403（h）
4. `git mv` 三支 router → `modules/arap/api/`；bank-reconcile 端點從 analytics 搬進 cashier（路徑不變）
5. module.json（key arap、version 1.0.0、core 範圍、tables、permissions、data 分類、provides.api_prefixes 含 `/api/reports/bank-reconcile`？——⚠ 前綴歸屬：`/api/reports/` 屬 M08，單一路徑例外要登記）、`customization` 空段、README、CHANGELOG、SPEC.md（查 STATE.md 有沒有題全在本模組的編號：先跑反向控制的 spec_coverage 再決定）
6. main.py 拿掉三支 router；import 修正；守門掃描範圍用 core.source_tree
7. **測試搬遷**：需要 M05 的題整檔／拆題進 `modules/arap/tests`（同檔名）；留外面的守門改 module_installed
8. 驗證：M05 在＝tests/platform＋modules＋提到 M05 的所有題（grep `cashier|invoice_vouchers|payment_requests|invoice-vouchers|payment-requests|receivables|bank-reconcile|arap`）
9. **反向控制**：sparse 工作樹（`git worktree add --no-checkout`＋sparse 檔排除 `/backend/modules/arap/`，⚠ 在 Git Bash 下 `sparse-checkout set '!/...'` 會被 MSYS 路徑轉換弄壞 ⇒ 直接寫 info/sparse-checkout），同範圍、有旗標／無旗標兩輪；允許紅只有 §B-11 兩題；伺服器啟動＋三個前綴 404
10. 突變：每個「不在時」降級（M06 T100 notice、M08 收入 notice、案件頁彙總、報表 404 分辨）拿掉判斷 ⇒ 紅
11. core_bump、UNIT-INDEX、page_paths 基線、ROADMAP（A8b ✅、M05 條目）、modules.json 狀態
12. 推 wip/c-m05、月台登記（依賴：第六班）、通知 D

## 3. 已知風險／要先問的

- `/api/reports/bank-reconcile` 前綴屬 M08：搬進 M05 後 M08 的 `api_prefixes` 守門會不會把它算成 M08 的？——開工時先查 test_module_boundaries 的前綴規則
- reports.js 把 403 當「無權限」：M05 不在時是 404，現在畫面會說錯（h）——這是既有缺陷還是搬遷才出現？M05 在時不會發生 ⇒ 搬遷才需要
- pdf_gen 的 `_generate_invoice_voucher_pdf`／`_generate_payment_request_pdf` 留 L1（同 M04 的 contractor voucher PDF）：G1 快照的「刪除」判定等 B 的 b-g1 顯式宣告合回，否則反向控制又會紅一題
- 預估：M04 約 5 小時（含兩輪反向控制）；M05 規模相近（3 router、2 表、收回 2 項）⇒ **約 5～6 小時**，開工時回報死線
