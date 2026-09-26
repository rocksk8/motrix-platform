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

## 4. JV 系列規格搬進 `modules/accounting/SPEC.md`（主持裁示 M06-e，比照 M07 的 BN；A 2026-09-26）

> 量測：`test_spec_coverage_2026_09_21.py` 的 `_declared_where()`／`_implemented_where()`／`_scope_sections()`，樹＝origin/platform（第七班後）。
> 判定「只由 M06 的題命名」＝命名它的每一個測試檔都需要 M06 才能跑。下表「候選」欄先以內容判斷（檔內打 `/api/vouchers`、`helpers.voucher`、`routers.vouchers`、`accounting_export`、`/api/account-items`、T100），
> **最後以 §B-11 反向控制定案**：拿掉 `modules/accounting` 後 `test_spec_coverage` 報「宣告了沒人管」的編號＝要搬的（BN 的做法）。

JV 共 36 條，全部宣告在 `docs/windows/STATE.md`；範圍 THIS 35 條、NEXT 1 條（JV6）。

| 類 | 編號 | 命名它的測試檔 | 處置 |
|---|---|---|---|
| 候選搬遷（檔案都是 M06 題） | JV1、JV2、JV3、JV5、JV7、JV9、JV10、JV11、JV12、JV13、JV15、JV16、JV17、JV18、JV19、JV20、JV21、JV22、JV23、JV24、JV25、JV27、JV28、JV29、JV30、JV31、JV32、JV33、JV34、JV35、JV36 | 各自一到兩支 `test_*voucher*`／`test_jvNN_*`（搬遷時隨題一起進 `modules/accounting/tests/`，同檔名） | 宣告原文照搬到 SPEC.md「## 規格條件」（表格列 `\| **JVn** \| …`），`## 範圍` THIS 列入；STATE.md 那一列刪除並留一行指向 |
| 要個別判斷 | JV4（`test_jv4_voucher_page_under_cashier`：出納頁底下的傳票入口 ⇒ 若驗的是 M05 出納頁 ⇒ 留 STATE.md，題改依 module_installed）、JV8（`test_approval_settings_unify`：L1 簽核設定頁列出傳票 ⇒ 可能是 L1 題）、JV26（`test_jv26_voucher_lines_inserts_agree`：掃 db.py migration 與 M06 的 INSERT 是否一致 ⇒ 可能是 L1 守門） | 見左 | 反向控制時看它們紅不紅：紅 ⇒ 搬（題與宣告一起）；綠 ⇒ 留 STATE.md |
| 沒有題 | JV14（EXEMPT，寫明驗法）、JV6（NEXT） | — | EXEMPT／NEXT 隨宣告一起搬進 SPEC.md 的 `## 範圍` 對應段；EXEMPT 的理由原文照抄 |

⚠ 撞名：STATE.md 其他節若也有 JVn（`_declared_where` 會列出行號），只搬傳票那一行；兩處都在 ⇒ 加 `AMBIGUOUS_ACK` 前先問主持。
⚠ 題與宣告要同一個 commit 搬（否則中間態：宣告在 SPEC.md、題在 tests/ ⇒ 模組不在時「有題無宣告」）。

## 5. 已知例外與到期守門（主持裁示 M06-a、b、d；比照 `tests/platform/test_case_access_l1.py` 的 KNOWN_L1）

M06 搬進模組後，下列三類讀取暫時保留（沒有 import 邊，只有 SQL 讀別人的表），**每一筆寫明到期條件，到期不靠人記**：

| # | 檔（搬遷後） | 讀的表（擁有者） | 到期條件（提供者） | 裁示 |
|---|---|---|---|---|
| a | `modules/accounting/api/vouchers.py` | `quotations`、`case_extra_expenses`（M01） | M01 提供 `case.summary`、`case.extra_expenses` | M06-a |
| ~~a'~~ | ~~〃~~ | ~~`contractor_dispatches`、`vendor_contractors`（M04）~~ | ~~M04 提供 `dispatch.by_case`（新 IP，待主持裁示）~~ | 〔更正（A 2026-09-26 盤點，dep_scan 實掃）：原表漏列〕 |
| | 〔主持裁示（2026-09-26 18:45）：不開新 IP，先核對 IP-15 `dispatch.list_for_case`。**A 核對結果：資料涵蓋，a' 不需要例外**——IP-15 回 `[_dispatch_row(r)]`（SQL 已 join `vendor_contractors.name` ⇒ `vendorName`），與 `_dispatch_expense_entry` 經 IP-1 `dispatch.row` 算出的 `d` 同一個形狀；用到的 id／vendorName／scope／grandTotal／invoiceNo／items／personnel 全在 ⇒ **不必擴充 IP-15**。搬遷時：JV21 `_case_expense_sources` 改呼叫 IP-15（不再經 `dispatch.row` 自己轉）；`vouchers_by_case` 的派工段改成先取 IP-15 的 id 再 `IN (…)`。⚠ **差別在權限不在欄位**：IP-15 簽名是 `fn(quote_no, authorization)`，照 M04 派工清單的模組檢查（procurement／case_manage／contractor_list）⇒ 只持 finance 的傳票使用者看不到派工支出來源（今天看得到）。取用方把 403 當「不列」（同 AT-M1b：可見範圍不比原單據寬），**這個行為變更待主持確認**〕 | | |
| b | `modules/accounting/voucher_attachments.py` | `case_extra_expenses`、`case_updates`、`quotations`（M01）、`contractor_dispatches`（M04）、`invoice_vouchers`（M05） | 各擁有者提供 `attachments.for_document`（獨立一包，排在 M01 前置） | M06-b |
| d | `modules/accounting/api/accounting_export.py` | `contractor_payment_vouchers`（M04） | M04 的 IP-14 加 `paid_between(start, end)` | M06-d |

守門：`backend/tests/platform/test_accounting_foreign_reads.py`（L1 守門，M06 不在時照跑：檔案不在 ⇒ 那一筆不比，`module_installed`）

```python
#: 表 ⇒ (擁有的模組 key, 到期的 capability)
KNOWN_ACCOUNTING_FOREIGN_READS = {
    "modules/accounting/api/vouchers.py": {"quotations": ("case", "case.summary"),
                                           "case_extra_expenses": ("case", "case.extra_expenses")},
    "modules/accounting/voucher_attachments.py": {t: (o, "attachments.for_document") for t, o in (...)},
    "modules/accounting/api/accounting_export.py": {"contractor_payment_vouchers": ("subcontract", "contractor_voucher.paid_between")},
}
```

| 題名 | 做什麼 | 反向控制（合成資料） |
|---|---|---|
| `test_accounting_reads_of_other_modules_only_shrink` | 掃 `modules/accounting/**`（`source_tree.module_files`，排除 tests）的 SQL（`dep_scan.sql_tables`，與 dep_graph 同一份）：讀到別組的表而不在基線 ⇒ 紅 | 合成檔多讀一張別組表 ⇒ 紅；讀自己的表 ⇒ 綠 |
| `test_accounting_foreign_reads_expire_when_the_provider_exists` | 基線每一筆：到期 capability 已被程式碼提供（`test_integration_points_registered.code_capabilities` 同一個掃描）⇒ 紅「提供者已在，改走它並自基線刪除」；檔已不讀那張表 ⇒ 紅「過期，自基線刪除」 | 合成 capability 出現 ⇒ 紅；合成檔不再讀 ⇒ 紅；兩者都沒有 ⇒ 綠 |
| （既有）`test_integration_points_registered` | 新 capability 要登記 INTEGRATION-POINTS | — |

- 到期觸發的是**提供者出現**，不是日期：C 的 M01 前置合回（`case.summary`）那一班，這一題就會紅，改走提供者的是 M06 擁有者（A）。
- 刪除條目的 commit 要引用觸發它的那一班列車（RUN-PLAN §6 記一筆），比照 CA-S3。
- `parse_approval_json` 不在本表：裁示 M06-c 已下沉 L1（`wip/a-approval-parse`），M01 不再 import M06。
- 〔2026-09-26 A〕守門已寫：`wip/a-m06` 的 `backend/tests/platform/test_accounting_foreign_reads.py`（KNOWN_FOREIGN_READS＝a、a'、d；自己的表取 `module.json` 的 `data.tables`／`views`，L1 表只列 `users`）。M06 搬遷前三題略過、兩支反向控制照跑；用今天的七支檔映射到搬遷後路徑實掃：多出＝0、過期＝0。

## 6. 搬移清單（A 2026-09-26；`grep` 實掃 import，樹＝wip/a-m06 49ac9ffd）

| 檔（現在） | 搬遷後 | 產品碼的呼叫端（要改） | 測試的呼叫端 |
|---|---|---|---|
| `routers/vouchers.py` | `modules/accounting/api/vouchers.py` | main.py；M01 `routers/quotations.py`（`vouchers_by_case`，§1 #7 新 IP `voucher.by_case`） | 8 支 M06 題（隨模組搬）；M04 `modules/subcontract/tests/test_dispatch_row_provider.py:83`（`_case_expense_sources`，要依 module_installed 略過） |
| `routers/accounting_export.py` | `modules/accounting/api/accounting_export.py` | main.py；`routers/vouchers.py`（同模組，改相對 import） | M06 題 3 支（隨模組）；**別人的題**：`tests/platform/test_subcontract_connectors.py:77,100`、`tests/platform/test_supply_connectors.py:93,104`、`modules/subcontract/tests/test_subcontract_providers.py:116`、`tests/test_xlsx_out_l1_2026_09_25.py:27,36,41,86`、`tests/test_money_round_half_up_2026_09_26.py:243` ⇒ 路徑改走 `source_tree`、import 改依 module_installed 略過（動 B／C 的檔，RUN-PLAN §6 先講） |
| `routers/account_items.py` | `modules/accounting/api/account_items.py` | main.py | `test_account_tree_page`（隨模組） |
| `helpers/voucher.py` | `modules/accounting/voucher.py` | `helpers/voucher_pdf.py`、`routers/vouchers.py`（同模組）；M01 `routers/quotations.py`（`parse_approval_json` 已下沉 L1，改 import L1 即切斷，§1 #8） | 12 支 M06 題（隨模組）；M07 `modules/payroll/tests/test_voucher_connectors.py:180,200`（驗「M06 不在也能跑」，改成模組路徑） |
| `helpers/voucher_pdf.py` | `modules/accounting/voucher_pdf.py` | `routers/vouchers.py`（同模組）；M07 `bonus_pdf.py` 只剩註解（c-m07 已切斷） | `tests/test_edge_profile_2026_09_25.py:12`（L1 題 import M06 ⇒ 改依 module_installed） |
| `helpers/voucher_template.py` | `modules/accounting/voucher_template.py` | 無 | `test_voucher_template_placeholders`（隨模組） |
| `helpers/voucher_attachments.py` | `modules/accounting/voucher_attachments.py` | `helpers/voucher_pdf.py`、`routers/vouchers.py`（同模組） | 5 支 M06 題（隨模組）；`tests/platform/test_attachments_providers.py`（M06 是取用方 ⇒ 取用方那幾題依 module_installed 略過） |

- 題檔搬遷：命名 JV 的題全部隨模組（§4）；`test_approval_settings_unify_2026_09_23.py` 只搬 JV8 段（行 478 起），沿用原檔名。
- 別人的檔共 8 支（上表粗體那格＋M04／M07 各一），搬遷當天在 RUN-PLAN §6 列出再動。
