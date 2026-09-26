# 採購・庫存・出貨 更新紀錄

## 1.0.4 — 2026-09-26（C，M01-PLAN §3-7；主持同意出貨單改成提供者；列車取號）
- 待我簽核、轉簽與佇列詳情：本模組以 ModuleSpec 宣告 `approval.queue_items`（出貨單待簽項目，欄位同原 M01 佇列）、`approval.reassign`（`shipping_notes.data_json.$.approval` 讀寫）、`approval.detail`（詳情內容）；M01 佇列、角標、轉簽、詳情不再直讀直寫本模組的表。本模組不在 ⇒ 佇列不列、不給轉簽、詳情 400 並明說

## 1.0.3 — 2026-09-26（列車第九班交會修正）
- 選單宣告搬進本模組：`suppliers.html`、`inventory.html`、`shipping-export-history.html` 的 `pages[].menu`（原寫在 L1 的 `core/menu_l1.json`；group／order／perm／badge／active 原值照搬）。本模組搬遷（M03）早於階段 C／C4，C4 只處理了當時已存在的模組；本模組不在時它的入口隨宣告一起消失，不再靠前端寫死的頁面⇒模組對照表

## 1.0.2 — 2026-09-26
- 出貨單收件人的個資蒐集告知（稽核 D PN-M1；主持裁示：比照手動輸入的聯絡人）：`GET`／`POST /api/shipping-notes/{note_no}/privacy-notice(/ack)`，只接受已存檔的收件人、鍵含姓名（換人要重新告知）、權限同出貨單清單

## 1.0.1 — 2026-09-26
- 提供 IP-20 `inventory.paid_batches`：M06 T100 付款傳票的料件進貨段（會計匯出不再直讀庫存表；本模組不在時 T100 預覽明說）
- `provides.probes`（產品演練用的 GET 端點）、`customization` 空段

## 1.0.0 — 2026-09-26
- 模組化：`routers/suppliers.py`、`routers/inventory.py`、`routers/shipping_notes.py` 搬進 `modules/supply/api/`（PLAYBOOK §B；CORE-SPEC §3 多支 router 放 `api/`）
- 提供者改由 `ModuleSpec.providers` 宣告（IP-6 出貨單行事曆回寫、IP-18 案件整包出貨段、IP-19 設備序號認領／釋放庫存）：模組未載入即不登記
- M01 不再 import 本模組、不再直寫 `stock_items`（IP-18、IP-19）
