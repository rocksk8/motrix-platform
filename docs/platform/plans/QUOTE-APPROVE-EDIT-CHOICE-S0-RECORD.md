# 報價單簽核二擇一 — S0 執行記錄（盤點＋守門；不改任何現有行為）

> 日期：2026-11-06　基準樹：`76d3e2d07`（train/t76-int）　分支：`s0/fp-write-path-inventory`
> 對應規格：`QUOTE-APPROVE-EDIT-CHOICE-PROPOSAL.md` §H1／§H5-S0。本檔另立（提案檔在共用樹是未追蹤檔，不去動）。
> 守門測試：`backend/modules/case/tests/test_content_fp_write_paths_s0_2026_11_06.py`（13 題）。**未動任何 production 檔**。

## 1. 結論（與提案數字的差異）

| 項目 | 提案寫的 | 實測 | 說明 |
|---|---|---|---|
| `save_quotation_json` 呼叫點 | 約 31 | **25** | 31 是文字比對，含 `def`、import、註解、docstring。改用 AST 數真正的 Call：`api/quotations.py` 22、`api/material_orders.py` 2、`api/settlement_api.py` 1 |
| 直接 `UPDATE quotations SET data_json` | 約 15 | **執行期 15**（外加 INSERT 2、漏斗本體 2、開機遷移／一次性工具 10） | 共 **29 句、27 個函式**；hichan-7 的「約 15」＝執行期的直接 UPDATE，對得上 |
| 動態表名寫 data_json | 未提 | **1**（`helpers/approval_queue.py::DataJsonApproval.save`） | 服務另外 5 張表（請款／開票／出貨／完工／承攬匯款），**不是 quotations**；守門確認沒有人傳 `"quotations"` 給它 |

## 2. 全部寫 `quotations.data_json` 的路徑（行號為基準樹，會漂；守門以「檔::函式」為鍵）

處置類別：`FUNNEL` 漏斗本體｜`NEW_ROW` 新單｜`BOOKKEEPING_ONLY` 只動排除清單內的鍵（指紋不變）｜`CONTENT_FULL` 整份取代（解鎖編輯，spec 明訂不動）｜`LEAVES_APPROVAL` 離開簽核範圍｜`POST_APPROVAL` 只有已成案可達｜**`CONTENT_DIRECT` 繞過漏斗＋改內容鍵（S3 重點）**｜`MIGRATION_ONCE` 開機遷移／一次性。

| # | 檔案:行（函式） | 類別 | 該納入排除清單？／說明 |
|---|---|---|---|
| 1–2 | `modules/case/quotations.py:363,370`（`save_quotation_json`） | FUNNEL | 漏斗本體；有／無 status 兩分支 |
| 3 | `modules/case/api/quotations.py:1715`（`create_quotation._do_insert`） | NEW_ROW | 新單，沒有既存簽核 |
| 4 | `…/api/quotations.py:2104`（`create_historical_quotation`） | NEW_ROW | 補登已成案，無簽核 |
| 5 | `…/api/quotations.py:1847`（`create_quotation`） | BOOKKEEPING_ONLY | 送審後只 patch `approval` |
| 6 | `…/api/quotations.py:2427`（`update_quotation`） | CONTENT_FULL | PUT 整份取代；解鎖編輯重建簽核（現狀） |
| 7 | `…/api/quotations.py:2550`（`update_status`） | BOOKKEEPING_ONLY | superadmin 改狀態；只動 `locationIdentity`／`clauseTitles`。⚠ 既有行為：白名單容許草稿→已送出，繞過分層簽核 |
| 8 | `…/api/quotations.py:2610`（`recall_quotation`） | LEAVES_APPROVAL | pop approval、回草稿 |
| 9 | `…/api/quotations.py:5863`（`reject_quotation`） | LEAVES_APPROVAL | 單號升版、pop approval、回草稿 |
| 10 | `…/api/quotations.py:7234`（`case_batch_assign`） | POST_APPROVAL | 只准已成案；改 `caseRecord.roles.executor` |
| 11 | `…/api/quotations.py:7357`（`_calendar_writeback_quotation`） | BOOKKEEPING_ONLY | 只寫 `googleCalendarEventId` → **建議新增進排除清單** |
| 12 | `modules/case/quotations.py:610`（`_record_doc_version`） | BOOKKEEPING_ONLY | 只 append `docVersions` → **建議新增進排除清單** |
| 13 | `modules/case/material_change.py:511`（`_apply`） | **CONTENT_DIRECT** | 材料申請投影進 `caseRecord.materialOrders`；**不更新 `updated_at`**、不過漏斗 |
| 14 | `modules/case/material_payment.py:646`（`sync_order_paid`） | **CONTENT_DIRECT** | 已付款狀態投影進 `materialOrders`；**不更新 `updated_at`** |
| 15 | `modules/case/profit_guard.py:468`（`change_pct`） | **CONTENT_DIRECT** | `overheadPct`／`tot`／`net_margin_pct` |
| 16 | `modules/case/recycle_adapter.py:508`（`delete_in_tx`） | **CONTENT_DIRECT** | 刪材料申請（有更新 `updated_at`） |
| 17 | `modules/case/recycle_adapter.py:529`（`restore_in_tx`） | **CONTENT_DIRECT** | 還原材料申請（有更新 `updated_at`） |
| 18 | `modules/case/alt_sign.py:136`（`sign`） | **CONTENT_DIRECT** | `altPicks`／total／pretax＋`is_signed` 欄位 |
| 19 | `modules/case/alt_sign.py:165`（`clear_signed_selection`） | **CONTENT_DIRECT** | 清 `altPicks`／`altPickedAt`／`altPickedBy` |
| 20 | `db.py:1882`（`_m052_fix_stage_json_ids`） | MIGRATION_ONCE | caseRecord.stages |
| 21 | `db.py:1945`（`_m058_backfill_deal_won_at`） | MIGRATION_ONCE | 只已成案／已結案 |
| 22–23 | `db.py:1982,1986`（`_m059_fix_deal_won_at_from_audit_log`） | MIGRATION_ONCE | 同上 |
| 24 | `db.py:4554`（`_m116_case_roles_username`） | MIGRATION_ONCE | ⚠ 不分狀態；未來類似遷移若碰簽核中的單，指紋會一次性翻動 |
| 25 | `tools/backfill_location_identity_snapshot.py:89` | MIGRATION_ONCE | 補 `locationIdentity`（排除鍵） |
| 26–27 | `migrations_frozen/t48_overhead25/recalc.py:157,225` | MIGRATION_ONCE | 凍結 |
| 28–29 | `migrations_frozen/t52_charity/recalc.py:120,181` | MIGRATION_ONCE | 凍結 |

## 3. 給 S1／S3 的發現（需 K 審）

1. **7 條 `CONTENT_DIRECT` 繞過漏斗**：提案 §H2 的「`save_quotation_json` 結尾寫後掛鉤」抓不到它們。判斷正確性不受影響（指紋是讀時推導），但**及時通知**會漏。S3 要嘛把它們改走漏斗、要嘛各自呼叫 `reconcile`。守門把這 7 條釘成清單，改走漏斗後要從清單拿掉。
2. **`updated_at` 粗篩不可靠**：§H1 效能段寫「佇列列表先用 `updated_at` 粗篩再算指紋」。但 `material_change._apply`、`material_payment.sync_order_paid` 寫 data_json **不動 `updated_at`**（程式註解自己寫明）。以 `updated_at` 當前置篩選會漏掉「叫料狀態改了」這類「更寬」範圍內的變動。建議 S1 擇一：這兩處補 `updated_at`，或粗篩不用 `updated_at`。
3. **排除清單盤點**（鎖在測試）：
   - 提案原列 7 鍵：`approval statusLog editHistory returnInfo clauseTitles locationIdentity status`＋時間戳類（目前頂層實際只見 `updatedAt`）。
   - **S0 建議新增**：`docVersions`（PDF 版本紀錄，伺服器 append）、`googleCalendarEventId`（日曆回寫）。
   - 請求暫存、寫入前已 pop、不進 data_json：`_expectedUpdatedAt`、`_isUnlockEdit`。
   - **有疑義，先依「未知從嚴」算內容，請 K 裁定**：`dealTag`（成案標記）、`dealWonAt`（成案時間戳）、`altPickedAt`／`altPickedBy`（與 `altPicks` 成對寫）、`rejection`。
   - 既有 `_DIFF_IGNORE_KEYS`（editHistory 差異摘要用）＝`editHistory docVersions approval updatedAt _expectedUpdatedAt`，與上述清單一致（守門有比對）。
4. 開機遷移 `db.py::_m116` 不分狀態改 `caseRecord.roles`——已套用且冪等，但示範了「遷移會讓簽核中的單指紋翻動」的類型；新遷移登記時請在備註寫明。
5. 動態表名寫入點（`DataJsonApproval`）服務的 5 張單據表有同樣的「approval 存在 data_json」結構；本案範圍只有 `quotations`，未納入。

## 4. 守門測試做了什麼

`backend/modules/case/tests/test_content_fp_write_paths_s0_2026_11_06.py`

| 題 | 鎖什麼 |
|---|---|
| `test_every_direct_data_json_write_is_registered_with_a_disposition` | 全樹（含凍結遷移、tools，不含 tests）寫 `quotations.data_json` 的 SQL，與 `DIRECT_WRITES`（檔::函式→語句數、處置類別、備註）**逐項相等**。新增／搬走／數量變＝紅，訊息要求回答「進不進指紋、要不要 reconcile」 |
| `test_dispositions_are_valid_and_every_content_bypass_is_listed_for_s3` | 處置類別合法、每筆有備註；`CONTENT_DIRECT` 七條清單釘死 |
| `test_scanner_positive_and_negative_controls` | **正對照**：單行／三引號多行／分段字串／INSERT／INSERT OR REPLACE／REPLACE INTO／`json_set`／小寫／帶引號表名都抓得到；**負對照**：改別的欄位、別張表、SELECT、SET 運算式裡只讀 `data_json`（`_m006` 那種）、註解裡提到 SQL、WHERE 裡讀 都不誤抓；限定名取最內層 |
| `test_tests_in_the_tree_are_really_excluded_but_the_scan_reaches_real_sources` | 掃描確實涵蓋 `db.py`、凍結遷移，且不含任何 tests 路徑 |
| `test_save_quotation_json_call_sites_are_pinned` | AST 數呼叫點＝25，逐檔相等 |
| `test_the_funnel_is_the_only_place_…` | 漏斗那兩句 UPDATE 留在 `save_quotation_json`，`modules/case/quotations.py` 內另一處只有 `_record_doc_version` |
| `test_dynamic_table_data_json_writer_is_pinned_and_never_pointed_at_quotations` | 動態表名寫入只有 `helpers/approval_queue.py` 一處；沒有任何 `DataJsonApproval("quotations", …)` |
| `test_exclusion_list_is_locked` | 排除清單內容鎖死；與內容清單不重疊；核心鍵（items／tot／caseRecord／customFields／overheadPct／settlement／altPicks／dealTag）不得入排除清單 |
| `test_existing_diff_ignore_keys_stay_within_known_classification` | 既有 `_DIFF_IGNORE_KEYS` 的每個鍵都有歸類 |
| `test_the_snapshot_key_is_location_identity`、`test_alt_server_keys_are_pinned` | `SNAPSHOT_KEY`＝`locationIdentity`；`ALT_SERVER_KEYS` 三鍵 |
| `test_every_server_written_top_level_key_is_classified` | 12 個會寫報價單的檔裡，`d/data/q/qdata/_data2/_sd/dd` 的 `["k"]=`／`setdefault`／`pop` 出現的頂層鍵必須歸類（排除／暫存／內容／待 K）；沒歸類＝紅 |
| `test_key_scanner_positive_control` | 鍵掃描器正對照，且真實掃描必須抓到已知的 7 個鍵（防掃描範圍默默失效而全綠） |

**突變驗證**（暫改後已還原）：①在 `profit_guard.py` 加一句 `UPDATE quotations SET data_json` 與 `q["brandNewKey"]=1` → 直接寫入題與鍵歸類題都紅；②把 `items` 塞進排除清單 → 排除清單題紅。

## 5. 已知盲點（守門不涵蓋）

- SQL 靠字串拼接成變數再執行（非 `UPDATE quotations` 字面）的寫法；目前只見 `DataJsonApproval` 一處，已另行釘住。
- 頂層鍵掃描只認 `X["k"]=`、`X.setdefault/pop("k")`；`X.update({...})`、整份 dict 字面值重組、前端整份送來的鍵都看不到（後者走 PUT 整份取代，登記為 `CONTENT_FULL`，且排除清單是 denylist，未知鍵本來就算內容）。
- 產生檔（`test_map.json` 等）依 PLAYBOOK §G3 只由列車重產，本分支未提交；列車重產時會納入這支新測試檔。
