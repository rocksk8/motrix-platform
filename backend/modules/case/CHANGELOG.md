# 案件 更新紀錄

## 1.0.7 — 2026-09-27（第十三班列車取號，原暫用 1.0.6；c-queue-json，主持指派）
- 待簽佇列提供者：簽核 JSON 改用 L1 `helpers.approval_queue.approval_json_of` 在 Python 逐筆解析（原本 SQL `json_extract(data_json,'$.approval')` 遇到一筆 malformed JSON ⇒ 整個查詢丟例外 ⇒ 這一類待簽全部靜默消失）；壞的那一筆跳過並記 ERROR（寫單號、不寫內容）；〔更正〕~~壞的報價單當成沒有簽核層列出、角標計 1~~（1.0.6）：那是降級（任一 superadmin 可簽），改成跳過

## 1.0.6 — 2026-09-27（第十三班列車取號；c-approval-l1-2，稽核 D AL-M1／AL-S1／AL-O3／AL-O4／AL-O1）
- 佇列提供者：報價單、完工單的簽核 JSON 改在 Python 逐筆解析（原本 SQL `json_extract` 遇到一筆 malformed JSON ⇒ 整個查詢丟例外 ⇒ M01 的待簽全部消失；舊版是整支佇列 500）
- 題：已結案變更 selfViewBy 兩方向（沒有案件權限的申請人 200、外人 404 同查無）、完工單查無＝看不到、壞 JSON 報價單照列且不影響其他（稽核 D AL-M1／AL-S1／AL-O4）

## 1.0.5 — 2026-09-27（第十三班列車取號，原暫用 1.0.4；c-approval-l1，主持裁示）
- 「待我簽核」佇列／角標搬進 L1 `routers/approval_queue.py`（路徑不變、前端不改）；M01 改為 `approval.queue_items` 提供者 `approval_queue_items`（報價單、已結案變更、額外支出、完工單、額外支出變更），ModuleSpec 宣告
- 已結案變更的客戶名稱改一次 JOIN（原本逐筆查 quotations，結果相同）
- 詳情與轉簽端點也搬 L1：M01 改為 `approval.detail` 提供者 `detail_quotation`／`detail_completion_note`／`detail_extra_expense`／`detail_case_change`（找不到的 404 訊息同前；已結案變更給 `selfViewBy`＝申請人本人照看）；`_case_header`、`_guard_queue_detail`、金額遮蔽移至 L1
- `case.summary` 加欄 `deal_tag`（L1 詳情抬頭；既有欄位不變）
- 選單「簽核佇列」與頁面、`/api/approval-queue` 前綴歸回 L1（`core/menu_l1.json`、modules.json）

## 1.0.4 — 2026-09-27（第十三班列車取號，原暫用 1.0.3；M01-PLAN §3-8 ④）
- 題：`test_approval_providers.py` 隨模組搬進 `modules/case/tests/`；新增 `test_approval_detail_and_reassign_edges.py`（稽核 D 兩項觀察：詳情遮蔽看 dataUrl、M05 不在時轉簽簽核鏈讀不出來擋下）

## 1.0.3 — 2026-09-27（第十三班列車取號，原暫用 1.0.2；M01-PLAN §3-8 ③ CA-O3）
- 提供者 13 個一律改由 `__init__.py` 的 ModuleSpec.providers 宣告，刪除所有 import 時的 `registry.provide()`：模組停用／未授權／載入失敗 ⇒ 不登記，`case.access`（M01 在不在的唯一訊號）隨之消失
- ATT：A 的 `helpers/case_attachments.py`（attachments.for_document 的 M01 提供者）移入 `modules/case/attachments.py`，改 ModuleSpec 宣告（原規劃的已知例外不需要：a-attachments 已隨第十班合回）
- 守門 `tests/platform/test_case_module_spec.py`（無 import 時登記＋反向控制、宣告清單、執行期不在 import 時登記表）

## 1.0.2 — 2026-09-27（第十二班列車，隨 M06 會計搬遷帶入）
- `modules/case/api/quotations.py::case_bundle` 的 `parts.vouchers` 改經 IP-22 `voucher.by_case`（M06 提供）取用，不再直接 import `routers.vouchers`／`modules.accounting.api.vouchers`；M06 不在時該段回 404 並明說（`VOUCHERS_UNAVAILABLE`）

## 1.0.1 — 2026-09-26（c-case404，M01-O1；列車取號）
- 看不到＝不存在：`_guard_case` 與 13 處單筆讀寫改走 L1 `helpers.case_access` 的 `deny_case`／`require_case`——逐案被拒與查無案件同一個 404（訊息逐字相同），audit 另記真正原因；`_is_case_member` 改用布林 `row_access.visible`（不丟例外、不記 audit）

## 1.0.0 — 2026-09-26
- 模組化（M01-PLAN §3-8 ②）：自 `routers/quotations.py`、`case_action_items.py`、`case_extra_expenses.py`、`completion_notes.py`、`material_orders.py` 搬入 `modules/case/api/`；`helpers/quotations.py`、`quote_terms.py`、`recognition.py`、`case_deadlines.py`、`case_stage_tasks.py` 與 `completion_pdf.py` 搬入 `modules/case/`（PLAYBOOK §B）；由載入器掛載（路由順序同搬遷前）
- 選單：「報價單」「案件管理」「案件執行看板」「簽核佇列」「簽核歷史」自 L1 `core/menu_l1.json` 移進本模組 `module.json` 的 pages[].menu
- 前置（其他包，已在本分支之下）：稅額純函式下沉 L1（T）、`norm_at`／`steps_to_tiers`（§3-2）、`case.summary`／`case.locations`（§3-4）、`case.recognition`（§3-6）、`approval.*`（§3-7）、CA-O4（§3-8 ①：L1 不 import M01、pdf_gen 不寫 quotations）
- 提供者仍在 import 時登記（載入器 import 本套件即登記）；改成 ModuleSpec 宣告是 ③（CA-O3）
