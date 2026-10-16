# 採購・庫存・出貨 更新紀錄

## 1.0.32 — 2026-10-16（wip/t66-format-fix-r1；T66 剩餘 toLocale* 顯示處遷移到共用格式器）
- T66 列車佔位條目：本列車內 supply 模組有程式變動（`wip/t66-lp-r3`）；與格式器遷移批次（`wip/t66-format-remaining-r2`）同車，本批對 supply 頁面無改動，顯示格式維持與 1.0.31 相同。

## 1.0.31 — 2026-10-15（wip/t65-format-rest-r1；T65 其餘 toLocale* 顯示處遷移到共用格式器）
- `pages/inventory.html`、`pages/parts.html` 的金額顯示改呼叫 `MotrixFormat.num()`（預設輸出逐字相同）。

## 1.0.30 — 2026-10-14（wip/t61-bp3-templates-r1；供應商管理頁 Excel 匯出接上匯出守門）；t62 整合 r8
- 供應商管理頁的 Excel 匯出在產檔前先過匯出守門（`MotrixExport.guard`）：自訂匯出旗標（`builder_exports.enabled`）關閉時不發任何請求、匯出結果與先前完全相同；開啟時才送一筆匯出稽核紀錄（不擋匯出）。純前端；無 migration、無新路由、無權限變更。

## 1.0.29 — 2026-10-14（wip/t61-s5-impl-r1＋wip/t61-s6-impl-r1；S5 供應商自訂欄位／S6 供應商管理頁自訂按鈕）
- 供應商管理頁標題列多一個「工具列」插槽（設定中心「自訂按鈕」開啟後才出現；預設關閉＝畫面與資料完全不變）。最高管理者可在插槽放「開啟頁面」「執行匯出」按鈕，先預覽再發布；每個人只看得到自己有權限的按鈕。按鈕不授權、不寫入任何資料。
- 無 migration、無新的寫入端點；供應商資料與既有端點行為不變。
- 供應商編輯視窗多一個「自訂欄位」區塊（設定中心「自訂欄位（內建畫面）」開啟後才出現；預設關閉＝畫面與資料完全不變）。欄位值存在 `data_json.customFields`（沒有值就沒有這個鍵），只給內部人員看。
- `POST/PUT /api/suppliers` 存檔前過自訂欄位閘門（`helpers.builtin_fields.gate`）：旗標關閉＝不介入（送來的 customFields 不存、舊值保留）；開啟時依已發布的欄位定義驗證型別（錯誤回 400 指名欄位）；PUT 沒送這個鍵＝沒有要改（舊頁面），送 `{}`＝清掉有效欄位的值。其餘欄位與端點行為不變。

## 1.0.28 — 2026-10-14（wip/t59-bp1-fields-r1；BP-1 第一刀：供應商管理頁可自訂版面；r2 併入治理預覽）
- module.json 登記供應商管理頁（suppliers.html）的可自訂點：列表「供應商清單」九個欄位（公司名稱、狀態為核心欄位，不能隱藏）。純加性宣告。
- 供應商管理頁接上既有的版面引擎（P9）：設定中心「自訂畫面版面」→「供應商管理頁可自訂版面」**預設關閉**；關閉時不發任何版面請求、畫面與先前相同。開啟後最高管理者可「編輯版面」調整欄位顯示／順序／標題，發布走定義文件庫（版本、還原、帳本）。
- 供應商管理頁多載入 `js/def-governance.js`；治理旗標（builder_governance）開啟時，編輯器發布前先顯示影響預覽，旗標關閉時完全略過。
- 無 migration、無新路由、無權限變更；供應商清單資料與遮蔽規則不變（非管理員仍回空清單）。

## 1.0.27 — 2026-10-13（wip/t57-download-name-p1-r1；A7 下載檔名第一期）
- 出貨單 PDF 下載檔名改走 `helpers.download_name`。無 migration、無新路由、無權限變更。

## 1.0.26 — 2026-10-10（wip/t50-int；第 50 班）
- **（併入）(next) — 2026-10-10（wip/t54-b5-system-hub-p1；系統中心 P1）：module.json 新增 `system_cards`（出貨單歷史紀錄卡片）**
- 加性宣告：在系統中心（`/pages/system-hub.html`）登記這個模組擁有的系統頁面；只影響索引顯示，頁面與 API 的權限、行為完全不變。
- **（併入）(next) — 2026-10-10（wip/t54-b5-system-hub-p1；系統中心 P1；r5）：module.json 新增 `system_cards`（出貨單歷史紀錄卡片）**

## 1.0.25 — 2026-10-10（wip/t53b-int；ab 稽核修正 r5）
- delete() 之後的步驟或 commit 失敗時，已搬進隔離區的附件搬回原處（出貨單刪除；另補連線不外漏）。

## 1.0.24 — 2026-10-10（wip/t50-int；第 50 班）
- **（併入）(next) — 2026-10-10（wip/t53-b5-rb-adapters；刪除暫存區 P1：出貨單）**
- `DELETE /api/shipping-notes/{no}` 改進刪除暫存區（IP-RB1／IP-RB2）：只有草稿能刪的規則不變；資料列與回簽檔進暫存區、最高管理者 30 天內可還原；暫存區模組不在 ⇒ 照舊硬刪並在回應 `notice` 明說。『刪除已核可』：已扣庫存序號的出貨單明確拒絕（先用『撤銷核准』歸還庫存）。還原：單號被占用／報價單不在 ⇒ 衝突，不覆蓋。測試 `tests/test_recycle_adapter_t53.py`。
- **（併入）(next) — 2026-10-10（wip/t53-b5-rb-adapters；刪除暫存區 P1：出貨單，提供者字面登記）**
- **（併入）(next) — 2026-10-10（wip/t53-b5-rb-adapters；刪除暫存區 P1：出貨單，提供者字面登記；單號不重發）**
- **（併入）(next) — 2026-10-10（wip/t53-b5-rb-adapters；刪除暫存區 P1：出貨單，提供者字面登記；單號不重發（IP-RB3））**
- **（併入）(next) — 2026-10-10（wip/t53-b5-rb-adapters；刪除暫存區 P1：出貨單，提供者字面登記；單號不重發（IP-RB3；next_entity_code 預設跳過））**

## 1.0.23 — 2026-10-09（wip/t49b-1d-strictbool2；W1c-P2b 旗標嚴格解析補丁）
- `POST /api/shipping-notes/{no}/approve` 的 `cascade`（『同一人連任多層時一次簽完』）：字串 `"false"` 以前會替簽核人自動簽完剩下的連續層。 旗標只收真布林（`helpers.validation.body_flag`）：JSON 字串 `"false"`／`"0"`／`""` 以前是 truthy，現在回 422、什麼都不寫（先驗旗標，再碰資料庫與簽核鏈）；真布林與沒帶（預設 false）行為不變。測試：`tests/test_strict_bool_cascade_t49b.py`。

## 1.0.22 — 2026-10-09（wip/t48-small-fixes）：供應商頁初始化 JS 例外
- `frontend/pages/suppliers.html`：聯絡人區塊的 `form.contacts.length` 在 `form` 尚為 `{}`（資料載入前）時丟 `Cannot read properties of undefined (reading 'length')`，與旁邊同型的判斷一樣加 `!form.contacts ||` 防呆。業務／工程師從供應商紀錄頁（`supplier-log.html`，找不到供應商會導回本頁）進來時最常撞到；行為不變。
- 測試：`tests/test_e2e_supplier_log_plain_roles_2026_10_09.py`（業務／工程師開供應商紀錄頁，有無 `?id=` 皆無 pageerror）。


## 1.0.21 — 2026-10-06（wip/t43-shipped-qty）：報價品項「已出貨數量」（提供者 shipping.quote_item_shipped）；支援排除單號
- 出貨單「從報價單匯入」的列加性欄位 `quoteItemId`（前端 `case-management-shipping.js`；舊單沒有 ⇒ 不歸屬）。新提供者 `shipping.quote_item_shipped`（IP-SH4，`material_link.quote_item_shipped`）：依報價品項加總已核准（shipped）與待審核／簽核中（reserved）；不計標題列、帶 `materialLink` 的列、庫存料號／序號列、非正數；草稿與已退回不計。**不改出貨單的送審、核准、庫存扣補**——只多一個唯讀提供者。
- 測試：`tests/test_shipped_qty_2026_10_06.py`。

## 1.0.20 — 2026-10-05（wip/t42-finance-role）：財務角色
- 進貨批次「標記已付款」改為出納動作：僅「財務」角色與 superadmin（建立／修改批次仍是一般管理）。

## 1.0.19 — wip/t34-ship-link-c7：出貨單連動材料申請（34-S1／S2，供應側）
- 出貨單明細列可帶選填 `materialLink: {materialItemId, docCode, qty}`（加性；舊單沒有此鍵＝行為不變）。送審與核准各檢查一次：同一筆材料申請所有活的連結數量合計 ≤ 已到料（`material.shippable` 的 `arrivedQty`）；錯誤碼 `ship_exceeds_arrived`／`ship_link_invalid`／`ship_link_serial_exclusive`／`ship_link_module_off`（400，回 `{detail, code}`）。存檔時先擋形狀與序號互斥。
- 新提供者 `shipping.material_shipped`（`{materialItemId: {reserved, shipped, notes}}`）與單一數字版 `shipping.material_shipped_qty`（reserved＋shipped；M01 變更申請用）；新端點 `GET /api/shipping-notes/{note_no}/material-link-check`（E6 警示：已到料有剩餘量卻沒連結，不擋）。IP-SH1／SH2／SH3 已登記。
- 34-S2：出貨單頁「從材料申請帶入」（新端點 `GET /api/shipping-notes/material-shippable?quote_no=&note_no=`＝已到料且有剩餘量的材料申請與剩餘可出貨量；帶入後該列帶 `materialLink`、列上數量改動時連結數量同步、與庫存序號同列互斥）；簽核人詳情新增「對應材料申請」欄；清單頁 `approval.tiers` 缺值容錯。送審前提醒（E6）。
- 新提供者 `shipping.material_shipped_qty`（IP-SH3）。
- 測試：`modules/supply/tests/test_shipping_material_link_2026_10_03.py`（25 題）、`test_e2e_shipping_material_link_2026_10_03.py`、`test_material_ship_case_view_2026_10_03.py`。契約 docs/platform/plans/SHIPPING-MATERIAL-LINK-CONTRACT-S1.md。

## 1.0.18 — 2026-10-01（wip/w1-attach-p3-a3：附件目錄 P3）
- 附件目錄 P3：`_SupplyCatalog` 加 `search`／`count`（出貨單回簽；權限＝`case_documents_readable`，逐案）。

## 1.0.17 — 2026-10-01（暫用號，列車取號；wip/w3-local-date）
- 本地日期（使用者 2026-10-01：凌晨建的單日期變前一天）：供應商／料號頁的匯出檔名日期改用本地日期。

## 1.0.16 — 2026-09-30（wip/w1-t27fix2）
- 出貨單退回與撤銷核准：原因改在狀態與權限檢查之後才驗（已回簽不可撤銷的 409 不再被 400 蓋掉）。

## 1.0.15 — 2026-09-30（暫用號，列車取號；W4 寫入串接缺口 L1／L2／L6／L8／L9／L10）
- L10：庫存報廢（作廢件，終態）產生 E10 報廢事件（借存貨盤損／貸存貨，依移動加權平均）；報廢件改備註不再更動報廢日。

## 1.0.14 — 2026-09-30（暫用號，列車取號；wip/w2-open-bind：附件開檔路徑綁單據（安全審查 W3））
- 附件目錄提供者 `open()` 加路徑綁單據檢查（`helpers.uploads.upload_path_key`）：檔案路徑不在這張單據自己的資料夾 ⇒ 當作沒有這個檔。

## 1.0.13 — 2026-09-30（暫用號，列車取號；wip/w1-pdf-unapproved）
- 出貨單：退回與撤銷核准一律要填原因；`pdf-download` 放行本單簽核人／申請人（含代理），不再限管理員；`export?mode=preview` 不計匯出次數；PDF 預覽未核准時有紅色警示、預覽可「退回修改」。

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
