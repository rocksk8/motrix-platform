# 採購・庫存・出貨 更新紀錄

## 1.0.0 — 2026-09-26
- 模組化：`routers/suppliers.py`、`routers/inventory.py`、`routers/shipping_notes.py` 搬進 `modules/supply/api/`（PLAYBOOK §B；CORE-SPEC §3 多支 router 放 `api/`）
- 提供者改由 `ModuleSpec.providers` 宣告（IP-6 出貨單行事曆回寫、IP-18 案件整包出貨段、IP-19 設備序號認領／釋放庫存）：模組未載入即不登記
- M01 不再 import 本模組、不再直寫 `stock_items`（前置 b15f600d）
