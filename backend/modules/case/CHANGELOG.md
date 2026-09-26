# 案件 更新紀錄

## 1.0.2 — 2026-09-26（M01-PLAN §3-8 ③ CA-O3；列車取號）
- 提供者 13 個一律改由 `__init__.py` 的 ModuleSpec.providers 宣告，刪除所有 import 時的 `registry.provide()`：模組停用／未授權／載入失敗 ⇒ 不登記，`case.access`（M01 在不在的唯一訊號）隨之消失
- ATT：A 的 `helpers/case_attachments.py`（attachments.for_document 的 M01 提供者）移入 `modules/case/attachments.py`，改 ModuleSpec 宣告（原規劃的已知例外不需要：a-attachments 已隨第十班合回）
- 守門 `tests/platform/test_case_module_spec.py`（無 import 時登記＋反向控制、宣告清單、執行期不在 import 時登記表）

## 1.0.1 — 2026-09-26（c-case404，M01-O1；列車取號）
- 看不到＝不存在：`_guard_case` 與 13 處單筆讀寫改走 L1 `helpers.case_access` 的 `deny_case`／`require_case`——逐案被拒與查無案件同一個 404（訊息逐字相同），audit 另記真正原因；`_is_case_member` 改用布林 `row_access.visible`（不丟例外、不記 audit）

## 1.0.0 — 2026-09-26
- 模組化（M01-PLAN §3-8 ②）：自 `routers/quotations.py`、`case_action_items.py`、`case_extra_expenses.py`、`completion_notes.py`、`material_orders.py` 搬入 `modules/case/api/`；`helpers/quotations.py`、`quote_terms.py`、`recognition.py`、`case_deadlines.py`、`case_stage_tasks.py` 與 `completion_pdf.py` 搬入 `modules/case/`（PLAYBOOK §B）；由載入器掛載（路由順序同搬遷前）
- 選單：「報價單」「案件管理」「案件執行看板」「簽核佇列」「簽核歷史」自 L1 `core/menu_l1.json` 移進本模組 `module.json` 的 pages[].menu
- 前置（其他包，已在本分支之下）：稅額純函式下沉 L1（T）、`norm_at`／`steps_to_tiers`（§3-2）、`case.summary`／`case.locations`（§3-4）、`case.recognition`（§3-6）、`approval.*`（§3-7）、CA-O4（§3-8 ①：L1 不 import M01、pdf_gen 不寫 quotations）
- 提供者仍在 import 時登記（載入器 import 本套件即登記）；改成 ModuleSpec 宣告是 ③（CA-O3）
