# 採購・庫存・出貨 更新紀錄

## 1.0.13 — 2026-09-30（暫用號，列車取號；wip/w2-open-bind：附件開檔路徑綁單據（安全審查 W3））
- 附件目錄提供者 `open()` 加路徑綁單據檢查（`helpers.uploads.upload_path_key`）：檔案路徑不在這張單據自己的資料夾 ⇒ 當作沒有這個檔。

## 1.0.12 — 2026-09-30（暫用號，列車取號；wip/w2-attach-p2：附件目錄 P2）
- 新增 `attachments.py::_SupplyCatalog`（`attachments.catalog`／`supply`，IP-105）：出貨單回簽附件開檔；權限＝出貨單清單規則 `case_documents_readable`。

## 1.0.11 — 2026-09-30（暫用號，列車取號；W4 總帳 C5）
- `gl.events` 進貨入庫 E08：批次有發票號碼時存貨行帶稅碼 IN-5，讓營業稅 401 的進項金額欄取得到這筆進貨金額。純事件內容，無 migration。

## 1.0.10 — 2026-09-30（暫用號，列車取號；W4 總帳 C4 存貨）
- `gl.events` 新增出庫成本事件 E10（出貨單核准 shipped、案件序號認領 installed；只回料號／件數／案件／日期，不含金額）；期間內被標為作廢（報廢／盤損）的庫存件數在 notice 提醒手工處理。

## 1.0.9 — 2026-09-30（暫用號，列車取號；W4 總帳 C4）
- 新增提供者 `gl.events`（IP-GL1）：進貨批次入庫 E08（成本合計，未稅）、進貨發票進項稅額 E08b（有發票號碼才有；稅額與日期暫為估計，會計可補登）、進貨付款 E09（付款日）。唯讀、不寫資料、不改欄位。

## 1.0.8 — 2026-09-30（暫用號，列車取號；wip/sec-p0 安全修正 P0）
- 安全修正 P0：`GET /api/shipping-notes/{no}` 與 `POST /api/shipping-notes/{no}/signed-files` 原本只要求登入 ⇒ 改用出貨單清單的規則（`_readable_note`：`guard_case_access(allow_module="case_manage")`）；看不到與查無同一句 404「出貨單 X 不存在」（不帶案件單號），上傳被擋時不寫檔。
- 新增提供者 `uploads.path_access`／`supply`（IP-104，`_ShippingPathAccess`）：`shipping_notes/<單號>/` 依同一規則判斷。

## 1.0.7 — 2026-09-28（暫用號，列車取號；E4 wip/e-company-gate-impl 第三段）
- 本公司資料設定閘門第二道（COMPANY-SETUP-GATE §5；D CG5-M1）：出貨單 PDF 下載端點：`except Exception` 前先 `except HTTPException: raise`（第二道的 428 不被吞成 500）

## 1.0.6 — 2026-09-27 23:02（暫用號；H10 品牌設定，主持派工）
- 頁面的分頁圖示（favicon）改讀 `/api/system/branding/favicon`（L1 品牌設定，可在公司資料設定更換；沒上傳回預設圖）：`suppliers.html`、`supplier-log.html`、`inventory.html`、`shipping-export-history.html`

## 1.0.5 — 2026-09-27（c-queue-json，主持指派；列車取號）
- 待簽佇列提供者：簽核 JSON 改用 L1 `helpers.approval_queue.approval_json_of` 在 Python 逐筆解析（原本 SQL `json_extract(data_json,'$.approval')` 遇到一筆 malformed JSON ⇒ 整個查詢丟例外 ⇒ 這一類待簽全部靜默消失）；壞的那一筆跳過並記 ERROR（寫單號、不寫內容）

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
