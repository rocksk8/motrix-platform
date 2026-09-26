# M01 案件（key `case`）搬遷步驟表（C，2026-09-26 草稿；未開分支，等主持裁示由誰做）

> 2026-09-26 18:10（C）：本體搬遷的分段、搬移清單與路徑對照見 §5。
> 量測：dep_scan `--check-modules` 於 origin/wip/b-m08-2 f7463dfa（含 /api/sales-orders 已歸 M01）。第六班合回後要重量一次。
> ROADMAP：M01「最後搬，此時其他模組已不依賴它的內部實作」⇒ 本表的 §2（切相依）是**其他模組搬遷前就可以、也應該先做**的部分。

## 0. 成員（modules.json M01，30 單位）

- router（5）：quotations、case_action_items、case_extra_expenses、completion_notes、material_orders → `modules/case/api/`
- helper（5）：quotations、quote_terms、recognition、case_deadlines、case_stage_tasks；core：completion_pdf
- 頁面 8、js 11（case-management-*.js）：留 frontend（模組頁面尚無服務路徑，同 M04／M07）
- 表 9：quotations、quote_seq、case_stages、case_stage_visits、case_updates、case_action_items、case_change_requests、case_extra_expenses、completion_notes
- 前綴 8：/api/quotations、/api/sales-orders（b-m08-2 移入）、/api/approval-history、/api/approval-queue、/api/case-batch、/api/case-changes、/api/completion-notes、/api/next-quote-no

## 1. 必做（ROADMAP 已登記）

| # | 事項 | 作法 | 驗收 |
|---|---|---|---|
| CA-O3 | `case.access`（IP-12；c-case-access-3 起也是「M01 在不在」唯一訊號）改由 M01 的 `ModuleSpec.providers` 登記，不在 import 時登記 | `modules/case/__init__.py` 的 ModuleSpec 列 `case.access`；刪 helpers/quotations 裡 import 時的 `register_provider` | 模組載入失敗 ⇒ 登記不殘留（突變：改回 import 時登記 ⇒ 題紅） |
| CA-O4 | 切斷 L1 對 `helpers.quotations` 的匯入（否則 M01 拿掉時 L1 仍載入它、登記仍在） | L1 使用者見 §2-A 表：`pdf_gen`（payment_item_amounts、quote_tax_type）、`routers/system`（`_steps_to_tiers`、`quote_terms.DEFAULT_TERMS`）、`helpers/receivables`（M05 收回後消失）、`helpers/__init__` 的 18 個再匯出 | 真刪 M01 後 `case.access` 不在登記表；`import main` 不載入 `helpers.quotations`（sys.modules 斷言） |
| ATT | A 的 `attachments.for_document`：M01 的附件提供者先放在 L1 `helpers/case_attachments.py`（主持 2026-09-26） | M01 本體搬遷時改由 M01 的 `ModuleSpec.providers` 宣告（與 CA-O3 的 `case.access` 同一件事），L1 那一支移出 | 真刪 M01 後 `attachments.for_document` 沒有 M01 的提供者 |
| SO | `/api/sales-orders` 已歸 M01（routers/quotations.py）；每日工作頁（M12）依賴它 | M01 不在 ⇒ 每日工作頁明說「需要案件模組」，不留空清單（主持裁示）；拿掉 l2_import_baseline 裡 analytics → M01 的 3 條 | e2e：M01 不在時每日工作頁出現提示；突變拿掉判斷 ⇒ 紅 |
| pdf_gen W | `core:pdf_gen` **寫** quotations 表（pdf_gen.py:442 `UPDATE quotations SET data_json=?`） | 查這一筆是什麼（推測：PDF 產生時回寫快照）⇒ 移回 M01 或改 M01 provider；L1 不可以寫 L2 的表（table_write_exceptions 有沒有登記要查） | dep_scan：core:pdf_gen 不再 W quotations |

## 2. 其他模組對 M01 的相依（逐條）

### 2-A 後端 import（dep_scan＋AST 名稱層級）

| 使用者 | 用到的 M01 名稱 | 處置 |
|---|---|---|
| L1 `pdf_gen` | quotations.payment_item_amounts、quote_tax_type | 稅額純函式下沉 L1 `helpers/tax_calc.py`（見下「T」） |
| L1 `routers/system` | quotations._steps_to_tiers、quote_terms.DEFAULT_TERMS | `_steps_to_tiers` 是簽核層轉換（非案件專屬）⇒ 下沉 `helpers/tiered_approval`；DEFAULT_TERMS 是報價條款預設值 ⇒ system 改讀 M01 provider `case.default_terms`，M01 不在時 system 那一段回「未安裝」 |
| L1 `helpers/receivables` | LEGACY_TAX_NOTE、invoice_amounts、payment_item_amounts、quote_tax_type、tax_split | M05 收回（M05 步驟表）；稅額函式走「T」 |
| M03 shipping_notes | guard_case_access（經 helpers） | 改 `from helpers.case_access import`（IP-12 已在 L1；只改 import 位置） |
| M04 contractor_vouchers | guard_case_access、is_document_approver | 同上（c-m04-2 之後確認） |
| M04 vendor_contractors | quotations.save_quotation_json、recognition.normalize_date | save_quotation_json＝IP-13（c-m04 已由 M01 提供）⇒ 確認沒有殘留直接 import；normalize_date 已下沉 `helpers/dates`（c-m04-2）⇒ 確認 |
| M05 cashier／invoice／payment | payment_item_amounts、quote_tax_type、tax_split、LEGACY_TAX_NOTE、guard_case_access、is_document_approver | 「T」＋case_access |
| M08 analytics/dashboard | norm_at、payment_item_amounts | norm_at 是日期正規化 ⇒ 下沉 `helpers/dates`；payment_item_amounts ⇒「T」 |
| M08 analytics/reports | 上列稅額函式＋case_extra_expenses、quote_won_month_map、summarize_payment_items、recognition.*（BASIS_NOTES、accrual_income_items、dispatch_entries、dispatch_unavailable、extra_entries、material_entries、normalize_basis、recognition_flags） | **最大的一條**。recognition 是「收入／支出認列」——資料屬 M01（案件階段），計算給 M08 用 ⇒ M01 provider `case.recognition`（一次回認列項目＋旗標），M01 不在 ⇒ 報表收入段 notice。quote_won_month_map／summarize_payment_items／case_extra_expenses 同一個 provider 或另立 `case.finance_summary` |
| tools/list_payment_anomalies | payment_item_amounts | 「T」 |

**T（先做，其他模組搬遷的前置）**：`payment_item_amounts`、`quote_tax_type`、`tax_split`、`invoice_amounts`、`LEGACY_TAX_NOTE` 是**純稅額計算**（輸入是報價單 JSON，不讀表）⇒ 下沉 L1 `helpers/tax_calc.py`，helpers/quotations 保留同名別名（同一物件）。這一步解掉 L1 pdf_gen、M05 三支、M08 兩支、receivables 的大部分 M01 相依。⚠ 升 CORE 次版號（新增）。

### 2-B 讀 M01 的表（dep_scan tables_r）

- 讀 `quotations`：L1 audit、company_identity、google_calendar、voucher_attachments、archive、pdf_gen；M07 bonus／bonus_payouts／bonus_pdf；M08 dashboard／reports；M02 dev_crm；M04 contractor_vouchers／vendor_contractors；M05 cashier／invoice／payment；M03 shipping_notes；L1 item_reads、map_points、search、system；M06 vouchers
- 讀 case_stages／case_updates／case_extra_expenses／case_action_items／case_stage_visits：archive、pdf_gen、google_calendar、voucher_attachments、bonus、dashboard、item_reads、vouchers
- 寫：db（migration，凍結）、**pdf_gen W quotations**（§1）
- 處置原則（同 M04 O-2）：凍結 migration 讓表常在 ⇒ 讀取不會壞；但「M01 不在時」讀到的是空表或舊資料，每一個讀取者要決定語意。建議分三類：
  1. L1 服務（archive 備份、search、item_reads、map_points、audit）：表在就照讀，M01 不在時資料不會再增加——可接受，登記即可
  2. 顯示案件名稱／編號（company_identity、google_calendar、bonus_pdf、vouchers）：改 M01 provider `case.summary`（IP-12 已有讀案件名稱），不在時顯示單號不顯示名稱
  3. 金額計算（dashboard、reports、bonus_payouts、cashier）：走 provider（上表），不在時 notice
- 這一段是**讀取連接器**（M04 O-2 另開題的同一件事），建議與 M01 分開做、先做

### 2-C 前端（別人的頁面呼叫 M01 API）

| 呼叫方 | 呼叫的 M01 端點 | M01 不在時 |
|---|---|---|
| M05 js/cashier.js | /api/quotations | 出納頁的案件連結／名稱改顯示單號，說明「案件模組未安裝」 |
| M05 payment-request-form.html | quotations、case_action_items、case_extra_expenses、material_orders | 請款單從案件帶入的功能不可用 ⇒ 明說；手動輸入仍可 |
| M08 js/reports.js | quotations、case_action_items、case_extra_expenses、material_orders | 報表的案件段 notice |
| M10 network-plans.html | /api/quotations | 已走 IP-12（case.access）；確認前端 notice |
| M12 daily-tasks.html | /api/quotations（sales-orders） | 見 §1 SO |
| L1 static/notif.js | /api/quotations | 通知點擊跳案件 ⇒ 不在時通知仍顯示但不跳轉 |

### 2-D M01 對別人的相依（M01 搬進模組後就是 L2→L2）

- 後端：routers/quotations → M03 shipping_notes、M04 vendor_contractors、M06 helper:voucher、M06 vouchers ⇒ 各自要對方 provider（M04 已有 IP-1／IP-13 反向；M03、M06 要新 IP）
- 前端（案件頁是整合頁）：case-management-*.js／approval-queue.html／settlement.html → M03、M04、M05、M06、M07、M10、M12 ⇒ 每一個分頁／佇列段在對方不在時說出原因（M04 已做出納頁樣式、M12 已做案件頁提示）；approval-queue 是六種單據的彙整 ⇒ 改成各模組 provider `approval.queue_items`（每個單據模組自己提供自己的待簽），M01 只負責彙整

## 3. 建議順序（每步可單獨上車）

1. **T**：稅額純函式下沉 L1（小、無行為改變、解最多相依）
2. `_steps_to_tiers` → tiered_approval、norm_at → dates（同上性質）
3. 各模組改 `from helpers.case_access import`（M03、M04、M05 三處；純 import 位置）
4. 讀取連接器 `case.summary`（2-B 第 2 類）
5. M05 搬遷（依賴 1、3）
6. `case.recognition`／`case.finance_summary` provider（M08 的最大相依）
7. approval-queue 改成各模組提供待簽項目
8. M01 本體搬遷：CA-O3＋CA-O4＋SO＋pdf_gen 寫表＋2-D
9. 反向控制：sparse 工作樹排除 `/backend/modules/case/`；範圍＝tests/platform＋提到 M01 的所有題（量會非常大：quotations 幾乎全系統都碰到，預估數百檔）

## 4. 規模與風險

- M01 是最大的模組（30 單位、9 表、8 前綴）＋全系統的整合點；§2 的前置（1～4、6、7）每一項都是 M04 級別的工作量。**本體搬遷（8）單獨估 1 個工作天以上**；前置合計 1～2 個工作天
- 最大風險：reports（M08）對 recognition 的相依是「計算邏輯」不是「資料」——拆 provider 時，回傳形狀就是契約，要有契約題（PLAYBOOK §C-11a 第 5 點）
- ⚠ 反向控制範圍：「提到 M01 的測試檔」幾乎是全部 ⇒ 實務上＝全量；要跟主持確認用 core-only 工具＋全量兩輪，還是分批
- 本表的 dep_scan 量測在 b-m08-2 上；第六班（c-m04-2、c-m07、c-case-access-3）合回後 2-A 的 M04、M07 列會變，開工前重量

## 5. 本體搬遷（§3-8）的分段、搬移清單與路徑對照（C，2026-09-26 18:10；主持核准五段、死線 02:10）

分支 `wip/c-m01`，疊在 c-approval-2。**② 開工前先把整疊 rebase 到第九班之後**：m05b-2 → m01-s3-2 → m01-rec-2 → approval-2 → m01（主持裁示），這樣只需要面對 C4 與 supply 一次。每段各自 commit、各自跑閘門。

| 段 | 內容 | 驗收 |
|---|---|---|
| ① CA-O4 | L1 不 import M01。`norm_at` → `helpers/dates`、`summarize_payment_items` → `helpers/tax_calc`、`_steps_to_tiers` → `helpers/tiered_approval.steps_to_tiers`（逐字搬，M01 留別名）；`helpers/__init__` 撤掉 M01 的再匯出；`routers/system` 條款改用 `case.default_terms`；`pdf_gen` 版本紀錄改用 `case.doc_version`（pdf_gen 不再寫 quotations）；M08 成案月份改用 `case.recognition.won_month_map` | `test_l1_does_not_load_m01`：載入全部 L1（main 除外）後，M01 單位都不在 sys.modules，並附正對照；`test_m01_l1_providers`（M01 在與不在兩種情形） |
| ② 搬檔 | 見下表；`main.py` 拿掉五支 router 的 include，改由載入器依 ModuleSpec 掛載；測試改路徑；只需要 M01 的題搬進 `modules/case/tests/` | 受影響題（選題）；`import main` 後 M01 由載入器載入；sparse 抽樣真刪 M01 |
| ③ CA-O3 | 下表 12 個 import 時登記改成 `ModuleSpec.providers` 宣告；刪除所有 `_registry.provide(...)` | 模組載入失敗 ⇒ 登記不殘留（突變：改回 import 時登記 ⇒ 紅）；真刪 M01 後 `case.access` 不在登記表 |
| ④ SO＋文件＋補題 | M01 不在 ⇒ 每日工作頁明說「需要案件模組」；module.json／README／CHANGELOG／SPEC；modules.json 的 M01 成員改成 `mod:case/...`；**補題（主持 2026-09-26 19:42，D 觀察）**：(a) 詳情遮蔽的「看 dataUrl」那一層：id 不是 passbook 但帶 dataUrl 的檔案也要被拿掉；(b) M05 不在時 L1 簽核鏈讀不出來會擋下的那條路 | e2e 驗提示；突變拿掉判斷 ⇒ 紅；(a)(b) 各一題＋突變 |
| ⑤ ATT | A 的 `attachments.for_document`（a-attachments）尚未合回 ⇒ 本包登記為已知例外並附到期守門（L1 `helpers/case_attachments.py` 存在時即紅，要求改成 M01 的 ModuleSpec 宣告） | 到期守門的正對照與反向對照 |

### 5-1 搬移清單（② ；舊路徑 → 新路徑）

| 舊 | 新 | 備註 |
|---|---|---|
| `backend/routers/quotations.py` | `backend/modules/case/api/quotations.py` | 6.7k 行；前綴 /api/quotations、/api/sales-orders、/api/approval-queue、/api/approval-history、/api/case-batch、/api/case-changes、/api/next-quote-no |
| `backend/routers/case_action_items.py` | `backend/modules/case/api/case_action_items.py` | |
| `backend/routers/case_extra_expenses.py` | `backend/modules/case/api/case_extra_expenses.py` | |
| `backend/routers/completion_notes.py` | `backend/modules/case/api/completion_notes.py` | /api/completion-notes |
| `backend/routers/material_orders.py` | `backend/modules/case/api/material_orders.py` | |
| `backend/helpers/quotations.py` | `backend/modules/case/quotations.py` | 提供者本體（case.access／summary／locations／recognition／default_terms／doc_version） |
| `backend/helpers/quote_terms.py` | `backend/modules/case/quote_terms.py` | |
| `backend/helpers/recognition.py` | `backend/modules/case/recognition.py` | 口徑標籤已在 L1 `recognition_basis` |
| `backend/helpers/case_deadlines.py` | `backend/modules/case/case_deadlines.py` | daily.check 提供者 |
| `backend/helpers/case_stage_tasks.py` | `backend/modules/case/case_stage_tasks.py` | 經 M12 provider 寫每日工作（既有） |
| `backend/completion_pdf.py` | `backend/modules/case/completion_pdf.py` | |
| 前端 8 頁、11 支 js | 不動（同 M04／M07：模組頁面還沒有服務路徑） | 選單項移進 `modules/case/module.json`（C4 之後） |

import 對照（測試與模組內部一律改成新路徑，**不留 L1 相容殼**：留殼的話，M01 拿掉時 L1 會 import 失敗，或殼本身又把 M01 載進來）：

| 舊 | 新 |
|---|---|
| `routers.quotations`／`from routers import quotations` | `modules.case.api.quotations` |
| `routers.{case_action_items,case_extra_expenses,completion_notes,material_orders}` | `modules.case.api.<同名>` |
| `helpers.quotations`／`from helpers import quotations` | `modules.case.quotations` |
| `helpers.{quote_terms,recognition,case_deadlines,case_stage_tasks}` | `modules.case.<同名>` |
| `completion_pdf` | `modules.case.completion_pdf` |
| monkeypatch 字串 `"routers.quotations.X"` 等 | 同上替換（逐檔 grep 字串形式，不只看 import 敘述） |

量測（c-approval-2 49dcb781）：測試檔提到 `routers.quotations` 38 檔、`helpers.quotations` 22、`helpers.recognition` 9、其餘 M01 單位合計 22（有重疊）。非測試端：`helpers/case_access.py` 只在註解提到 M01；③ 之後 L1 不 import M01（由 ① 的守門保證）。

### 5-2 提供者宣告（③；現在全部是 import 時登記）

| 能力 | 名稱 | 現在的位置 |
|---|---|---|
| `case.access`（IP-12） | case | helpers/quotations.py |
| `case.summary`（IP-96 暫定） | case | helpers/quotations.py |
| `case.locations`（IP-97 暫定） | case | helpers/quotations.py |
| `case.recognition`（IP-95 暫定） | case | helpers/quotations.py |
| `case.default_terms`（IP-91 暫定） | case | helpers/quotations.py |
| `case.doc_version`（IP-92 暫定） | case | helpers/quotations.py |
| `daily.check`（IP-11） | case_deadlines | helpers/case_deadlines.py |
| `approval.reassign`（IP-94 暫定） | quotation、completion_note | routers/quotations.py |
| `calendar.writeback`（IP-6） | quotation、case_stage | routers/quotations.py |
| `quotation.append_items`（IP-17） | quotations | routers/quotations.py |
| `attachments.for_document`（A） | （a-attachments 合回後） | L1 helpers/case_attachments.py ⇒ ⑤ |

### 5-3 已知例外（使用者已接受：D7 時可以有少數已知例外，每一筆都要附到期守門）

- ATT（⑤）：見上。
- §2-B 的讀取者（L1 archive、search、item_reads、map_points、audit，以及 M07、M08 的報表直讀 quotations）不在本包範圍，照 §2-B 的三類登記；本包不新增任何讀取。

### 5-4 c-case404（M01-O1，主持裁示 2026-09-26 20:04；排在 ② 之後、③ 之前，獨立一小包 `wip/c-case404`）

A 發現：案件端點對「看不到」回 403、對「不存在」回 404 ⇒ 可以探知案件編號是否存在。

| 項 | 內容 |
|---|---|
| 判定位置 | L1 `helpers/case_access` 集中判定：案件規則拒絕 ⇒ **404**，訊息與「查無案件」**逐字相同**；audit 記真正原因（拒絕／查無）。`row_access.require` 不全面改 |
| 必含 | `row_access.require("case")` 的 16 處改走同一判定（否則留一條 403 的路）；M01 `_guard_case`、M03／M04／M05／M10 經 `guard_case_access` 的路徑同一份 |
| 守門 | 掃描「案件判定路徑之外沒有對逐案拒絕回 403」＋反向控制（植入一處 403 ⇒ 紅）。掃描對象是**案件判定路徑**；傳票 summary-sources 的「案件」頁籤（JV7）不在其中，**不為了讓守門變綠而把它排除** |
| 題 | 看不到與不存在：狀態碼＋回應內容完全相同；audit 原因不同；模組權限的 403（cashier／reports）不受影響；既有 43 檔約 62 處 403 斷言機械替換成 404，改前後各跑一次、對照題數 |
| 一致性 | A 的 `case_access.case_documents_readable()` 與附件-6 的「整案看不到 ⇒ 404」：guard 改成 404 之後訊息與狀態碼仍要一致；不一致算本包 |
| 規格界線（D AT6-O1） | 傳票 summary-sources 的「案件」頁籤（JV7）照舊對 cashier／finance 列出全部案件，本包不過濾。「看不到＝不存在」**只保護沒有傳票權限的角色，不保證對 finance 隱藏案件是否存在**——寫進 `case_access` 說明與 ROADMAP |
| 交會 | A 的 wip/a-m06 在 `case_access.py` 檔尾新增 `case_documents_readable()`；誰後上車誰解那一處（逐 hunk、解完 ast.parse、重跑 case_access 題＋A 的附件題與 M06 題＋case404 題；rebase 與 push 分開） |
| 稽核 | 權限類 ⇒ D 完整稽核 |

