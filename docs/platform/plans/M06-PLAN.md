# M06 會計（key `accounting`）搬遷步驟表（C，2026-09-26 草稿；未開分支；開工基底＝第六班合回後的 origin/platform）

> 量測：dep_scan `--check-modules` 於 origin/wip/b-m08-2 f7463dfa（M08 已搬、M04／M07 未搬）；M04（c-m04-3）、M07（c-m07-2）的改動另從該分支讀。第六班合回後要重量一次。
> 依賴：M04（IP-1、IP-14）、M08（/api/reports 前綴共用、receivables）都在第六班；M05 的 receivables 收回（M05-PLAN）會改 M06 的一個 import。

## 主持裁示（2026-09-26，RUN-PLAN §5 D1 段，Ruling-By: 8d）

1. 轉簽（#9）另做一包 `approval.reassign`：各單據擁有模組自己提供，與 `approval.queue_items` 一起併進 M01-PLAN §3-7。**M06 不只修傳票那一種**（#8、#9 都不在 M06 包內處理）
2. 前綴不改網址（V9 轉移、書籤、外部呼叫相容）⇒ modules.json 改成可以**明列個別路由歸屬、優先於前綴**；check_modules 的支援由 B 做；**M06 的 module.json 用明列寫法**（/api/reports/t100-export*、/api/settings/t100-export-config）
3. `inventory.paid_batches`（#2）核准，號碼由列車定
4. 順序：**M05 先、M06 後**

## 0. 成員（modules.json M06，11 單位）

| 類 | 單位 | 去處 |
|---|---|---|
| router | vouchers、accounting_export、account_items | `modules/accounting/api/{vouchers,accounting_export,account_items}.py` |
| helper | voucher、voucher_pdf、voucher_template、voucher_attachments | `modules/accounting/{voucher,voucher_pdf,voucher_template,voucher_attachments}.py`（voucher_attachments 見 §1-C：它也讀別人的表，要先拆） |
| 頁面／js | voucher.html、account-items.html、js/voucher.js、js/account-items.js | 留 frontend（模組頁面尚無服務路徑，同 M04／M07） |
| 表 | vouchers、vouchers_all、voucher_lines、voucher_attachments、voucher_edit_log、account_items、t100_export_confirmations | module.json `tables`；migration 不動（凍結） |
| 前綴 | /api/vouchers、/api/account-items；**/api/reports/t100-export\***（5 支）、**/api/settings/t100-export-config**（1 支） | ⚠ /api/reports 屬 M08、/api/settings 屬 L1 ⇒ 不能整個前綴歸 M06；module.json 要登記「路徑」而不是前綴（開工時先查 test_module_boundaries 的前綴規則是否允許子路徑；不允許 ⇒ 改路徑是破壞相容，要主持裁示） |

## 1. 接點（逐條）

### 1-A 已下沉 L1 或已有串接點（開工時確認，不重做）

| # | 接點 | 現況 | 來源 |
|---|---|---|---|
| a | `resolve_display_names`（簽核格帳號 → 顯示名稱） | 已在 L1 `helpers.tiered_approval`；voucher 保留同名匯入 | c-m07（CORE 1.30） |
| b | `_fmt_money`（0 印空白） | 已在 L1 `pdf_gen.fmt_money_blank_zero`；voucher_pdf 照舊用 `_fmt_money` 別名 | c-m07 |
| c | bonus_pdf 用的 `voucher_pdf._company_name`／`_render` | M07 改用 L1 `company_identity.company_name()`、`html_to_pdf_bytes` ⇒ M07 → M06 已切斷 | c-m07 |
| d | IP-2 `voucher.draft`＋`voucher.account_check`（M06 提供 → M07 bonus_vouchers） | provider 已在；搬遷時改 `ModuleSpec.providers` 宣告、提供方路徑改 `modules/accounting/…`（M07-S1 的路徑守門會抓） | 既有 |
| e | IP-3 `accounting.settings`（M06 → M07 撥付銀行選項） | 同上 | 既有 |
| f | IP-4 `voucher.void_draft`＋`voucher.status`（M06 → M07） | 同上 | 既有 |
| g | IP-1 `dispatch.row`（M04 → M06 vouchers 的案件支出來源） | 已走 provider（vouchers.py:582／699）；M04 不在 ⇒ 標示 unavailable | c-m04 |
| h | IP-14 `contractor_voucher.public`（M04 → M06 T100 匯出） | c-m04-3 已改 provider＋`T100_CONTRACTOR_MISSING` notice；⚠ 同檔 245 行仍有 `SELECT * FROM contractor_payment_vouchers`（provider 在時用？）——開工時確認是不是降級路徑殘留的直讀 | c-m04 |
| i | IP-5?／IP-6 `calendar.writeback` 等 | M06 不涉及 | — |

### 1-B M06 → 別人（搬進模組後就是 L2→L2 或 L2→L1）

| # | 相依 | 處置 |
|---|---|---|
| 1 | accounting_export → `helpers.receivables.collect_tax_invoices` | M05 收回 receivables 後改 provider `tax_invoices.list`（M05-PLAN §1-j）；M05 不在 ⇒ T100 匯出說明「收款事件來自應收應付模組，未安裝」。**順序：M05 先於 M06**，否則 M06 搬進模組時還在 import L1 中繼（可接受，但要在 M05 時一起改） |
| 2 | accounting_export 讀 M03 的 `parts`、`stock_items`、`stock_batches`（料件進貨付款 ⇒ T100） | 新 IP `inventory.paid_batches`（M03 提供），M03 不在 ⇒ T100 料件段 notice；或 M03 搬遷前暫列 L1 共用讀（O-2 類）——建議前者，M03 還沒搬時由 L1 位置先登記 |
| 3 | vouchers 讀 M01 `quotations`、`case_extra_expenses`，M04 `contractor_dispatches`、`vendor_contractors`（帶入分錄的來源單據） | M04 那兩張已有 IP-1 覆蓋 dispatch.row——**查 vouchers.py 裡還有沒有直接 SQL**；M01 的兩張 ⇒ M01 provider `case.summary`／`case.extra_expenses`（M01-PLAN §2-B 第 2、3 類） |
| 4 | voucher 讀 `users` | L1 表，不算 |
| 5 | voucher_attachments 讀 `case_extra_expenses`、`case_updates`、`contractor_dispatches`、`invoice_vouchers`、`quotations`（帶入附件的來源） | 已查（b-m08-2 樹）：import 它的只有 M06 自己（voucher_pdf、routers/vouchers）；archive／db 只以表名出現 ⇒ **整支搬進模組**，來源讀取改各擁有者 provider（`attachments.for_document`：每個單據模組提供自己的附件清單；擁有者不在 ⇒ 那一類來源不列並說明） |
| 6 | account_items → audit、auth | L1，不算 |

### 1-C 別人 → M06

| # | 相依 | 處置 |
|---|---|---|
| 7 | M01 `routers/quotations.py:2230` `from routers.vouchers import vouchers_by_case`（案件整包的傳票段） | 新 IP `voucher.by_case`（M06 提供），M06 不在 ⇒ 案件整包 `parts.vouchers = {ok: False, status: 404, detail: …}`（比照 IP-12 dispatches 的形狀） |
| 8 | M01 `routers/quotations.py:6537` `from helpers.voucher import parse_approval_json, VoucherChainUnreadable`（簽核佇列讀傳票的簽核鏈） | 併入 M01-PLAN §2-D「approval.queue_items 由各單據模組提供」：M06 提供自己的待簽項目，M01 不再解析傳票的 approval_json |
| 9 | ☠ **M01 寫 M06 的表**：`routers/quotations.py:6597` `reassign_approval`（轉簽）`UPDATE vouchers_all SET approval_json=…` | 與 pdf_gen 寫 quotations 同一類（主持裁示 ④：L1／他模組不再直寫）。`reassign_approval` 用 `_REASSIGN_TABLES` 對六種單據逐表直寫 ⇒ 新 IP `approval.reassign`（每個單據模組提供自己的轉簽），M01 只做權限與稽核；M06 不在 ⇒ 轉簽清單不出現傳票。**這一條同時影響 M03／M04／M05／M07 的單據** ⇒ 建議與 M01-PLAN §3-7（approval-queue）同一包做 |
| 10 | L1 `core:db` 寫 `account_items`（migration／預設科目種子？）、讀 voucher_lines／vouchers_all | 查是 migration（凍結，不動）還是啟動時的種子：種子 ⇒ 移進 M06 的 ModuleSpec 啟動掛勾 |
| 11 | L1 `core:archive` 讀六張 M06 表（備份匯出） | L1 服務，表在就照讀（同 M04 O-2）；確認 module.json `data` 分類（T1 必須匯出） |
| 12 | 前端：M01 case-management-close.js、approval-queue.html → /api/vouchers；M01 case-management-dispatch.js、M03 inventory.html、M05 js/cashier.js → /api/reports/t100-export* | M06 不在 ⇒ 各頁說出原因（同 IP-14 出納頁 notice 樣式）；清單逐頁做 e2e |

## 2. 步驟（依序）

1. 第六班合回後 `git worktree add ..\MOTRIX-PLATFORM-C4x -b wip/c-m06 origin/platform`；重跑 dep_scan、確認 §1 沒變（有變先更新本表）
2. **先切相依（不搬檔）**：#7 `voucher.by_case`、#2 `inventory.paid_batches`、#5 voucher_attachments 拆分、#3 殘留直讀；#1 等 M05；#8／#9 併 M01 approval 那一包（若先搬 M06，這兩條暫留直 import＋直寫、登記 table_write_exceptions 並寫明由哪一包收）
3. `git mv` 三支 router → `modules/accounting/api/`、四支 helper → `modules/accounting/`
4. module.json（key accounting、tables、data 分類、provides：前綴＋兩個子路徑例外）、customization 空段、README、CHANGELOG、SPEC.md（反向控制的 spec_coverage 先跑，看 JV 系列有沒有題全在本模組的編號——JV1～JV36 大多是傳票，**預期很多**，要像 M07 的 BN 一樣把條件與範圍搬進 SPEC.md）
5. main.py 拿掉三支 router；import 修正；守門掃描範圍用 core.source_tree
6. 測試搬遷：需要 M06 的題進 `modules/accounting/tests`（同檔名）；留外面的守門改 module_installed
7. 驗證（主持裁示：不自跑全量）：modtest 差異題＋tests/platform＋改到的頁面 e2e
8. 反向控制：sparse 工作樹排除 `/backend/modules/accounting/`（直接寫 info/sparse-checkout），tests/platform＋提到 M06 的所有題（grep `voucher|accounting|account_items|t100`），有旗標／無旗標兩輪；允許紅只有 §B-11 兩題
9. 突變：每個「M06 不在」的降級拿掉判斷 ⇒ 紅
10. core_bump、UNIT-INDEX、page_paths 基線、l2_import_baseline --prune、ROADMAP、modules.json
11. 推 wip/c-m06、月台登記、通知 D

## 3. 風險／要先問的

- **前綴**：`/api/reports/t100-export*`、`/api/settings/t100-export-config` 是 M06 的端點掛在別人的前綴下；modules.json 的 api_prefixes 若只收前綴，這兩組會被判給 M08／L1 ⇒ 開工前查守門規則；可能需要主持裁示（改路徑＝前端與書籤全改）
- **#9 轉簽直寫** 是跨六種單據的共通問題，不是 M06 專屬；單獨在 M06 修會做出只有傳票走 provider、其他五種仍直寫的中間態 ⇒ 建議主持排成獨立一包（approval.reassign＋approval.queue_items）
- **JV 系列規格**：傳票相關的 JV1～JV36 是 STATE／SCOPE 裡數量最多的一組，搬遷量可能比 M07 的 BN 大
- 預估：3 router、4 helper、7 表、12 條接點 ⇒ 約 6～8 小時（不含 #8／#9 的共通包）；開工時回報死線
