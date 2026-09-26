# 案件 更新紀錄

## 1.0.0 — 2026-09-26
- 模組化（M01-PLAN §3-8 ②）：自 `routers/quotations.py`、`case_action_items.py`、`case_extra_expenses.py`、`completion_notes.py`、`material_orders.py` 搬入 `modules/case/api/`；`helpers/quotations.py`、`quote_terms.py`、`recognition.py`、`case_deadlines.py`、`case_stage_tasks.py` 與 `completion_pdf.py` 搬入 `modules/case/`（PLAYBOOK §B）；由載入器掛載（路由順序同搬遷前）
- 選單：「報價單」「案件管理」「案件執行看板」「簽核佇列」「簽核歷史」自 L1 `core/menu_l1.json` 移進本模組 `module.json` 的 pages[].menu
- 前置（其他包，已在本分支之下）：稅額純函式下沉 L1（T）、`norm_at`／`steps_to_tiers`（§3-2）、`case.summary`／`case.locations`（§3-4）、`case.recognition`（§3-6）、`approval.*`（§3-7）、CA-O4（§3-8 ①：L1 不 import M01、pdf_gen 不寫 quotations）
- 提供者仍在 import 時登記（載入器 import 本套件即登記）；改成 ModuleSpec 宣告是 ③（CA-O3）
