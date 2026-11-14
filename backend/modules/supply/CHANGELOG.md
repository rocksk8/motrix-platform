# 採購・庫存・出貨 更新紀錄

## (next) — T86 出貨列「材料申請連結＋庫存序號並存」（feat/ship-link-serial-coexist-t86；h11 審查補強；版號由列車取）
- 放寬 33-S1：出貨單同一列可同時帶 `materialLink` 與 `part_no`＋`serials`（原錯誤碼 `ship_link_serial_exclusive` 不再產生）。並存時兩邊都要驗證一致：序號筆數 ≤ 連結數量（`ship_link_serial_qty`，存檔／送審／核准都擋）；**每個序號**都必須是為這個案件、這筆材料申請入庫的（`stock_items.material_item_id`＋批次案件單號＋料號；別案、一般庫存、另一筆材料申請入庫的同料號序號不行；`ship_link_serial_part`，訊息點名序號，送審／核准都擋，沒有入庫紀錄＝不通過）。
- 其餘不變：連結數量照舊占用材料申請到料量（序號不重複計）；序號於核准時照一般出貨規則驗在庫並扣庫；只有連結、或只有序號的列行為逐位元相同；沒有旗標（放寬前這種列存不進來，沒有舊資料要相容）。
- 畫面：出貨單頁已連結材料申請的列也能「選料號」；選完序號後出貨數量不縮水（序號比數量多才補到序號筆數），連結數量同步。序號挑選清單仍列出該料號所有在庫序號，是否屬於這筆材料申請由後端送審時逐個驗。
- 審查補強（h11）：並存時改成**逐個序號**驗證屬於這筆材料申請（不只比料號）；別案、一般庫存、另一筆材料申請入庫的同料號序號不得掛上，送審與核准都擋。
- 契約 `docs/platform/plans/SHIPPING-MATERIAL-LINK-CONTRACT-S1.md` §3／§6 改寫；`test_shipping_material_link_2026_10_03.py` 互斥題改寫成並存題（不是刪除）。
- **（併入）(next) — 2026-11-14（fix/supplier-privacy-notice-mask-t86-h9；供應商聯絡人「已告知」紀錄對非管理員遮罩）**
- 行為變更（資料範圍收窄）：`GET /api/suppliers/{id}/privacy-notice`（及 `POST …/contacts/{ctid}/privacy-notice/ack`——已記錄過時回傳的是既有紀錄，同一支 `_ack_view` 遮罩，否則會成為繞過的後門；伺服器端寫入的紀錄與稽核仍是完整的）對非管理員（只有供應商檢視權者，與 `GET /api/suppliers` 同一條線）只回 `{聯絡人id: {at}}`＝已告知與日期，不再帶記錄人姓名／帳號（`by`／`byUsername`）與告知文字雜湊（`noticeHash`）；管理員（admin／superadmin）照舊看完整紀錄。回應形狀不變（只是少欄位）、沒有新增權限鍵。
- 測試：`modules/supply/tests/test_supplier_privacy_notice_mask_2026_11_14.py`（管理員完整、非管理員只有 `at` 且全文不含記錄人／雜湊／聯絡人個資、POST ack 對已告知聯絡人不外洩既有紀錄、首次告知伺服器端仍存完整紀錄、無紀錄回空與 404、無檢視權 403；突變驗證：拿掉遮罩分支 ⇒ 非管理員題紅）。

## 1.0.44 — T85 一條龍 P3「出貨／設備／保固對齊」（train/t85-p2-h1；旗標 `onepipe.ship_device_warranty`，預設開；版號由列車取）
- 新提供者 `stock.shipped_serials`（IP-120）、`stock.serial_history`（IP-121）（`modules/supply/serial_view.py`）：唯讀、沒有金額；序號歷史只從 P2a 異動紀錄啟用日起有資料。
- 新端點 `GET /api/inventory/serial-history?part_no=&serial_no=`（庫存同一組模組權限；旗標關 ⇒ 404）；庫存頁序號列多「歷史」按鈕（旗標開）。
- `stock.serial_history`（IP-121）新增選填參數 `quote_no`（案件頁用）：給了才檢查序號與該案件有庫存關係，並把不是本案的異動（含沒有案件編號的）遮掉 `ref`／`reason`／`actor`；不給＝原樣（庫存頁，已有庫存權限）。

## 1.0.43 — T85 P2b 審查補強（train/t85-p2-h1；h9／h2／PM；版號由列車取）
- `stock.receive`（IP-118）新增 `consumable` 到貨方式：只留一筆 `delivery_mode='consumable'` 批次表頭（前綴 `CN`），讓入庫對帳表視為已處理；全部是耗材時不需入庫權限；直送／耗材的防重複依方式分開算。
- 新提供者 `stock.receive_undo`（IP-122，暫定號；`receive.py::undo_receipt`）：案件撤銷到貨確認時收回庫存那一半——刪直送／耗材／無序號列的入庫表頭；已有為該材料申請入庫的序號、或批次已登記付款 ⇒ 回 `BLOCKED`、不動任何東西。

## 1.0.42 — T85 P2a 審查補強的小尾巴（train/t85-p2-h1；版號由列車取）
- 人工刪除在庫序號寫的 `delete` 異動，時間格式與其他異動一致（到秒）。

## 1.0.41 — T85 一條龍 P2a「入庫底層」（train/t85-p2-h1；旗標 `onepipe.receive_ledger`，預設開；關閉＝與今天逐位元相同；版號由列車取）
- **自有 migration v1**（`modules/supply/migrations/0001_receive_ledger.py`；首支，supply 先前沒有自有 migration）：`stock_batches` 加 `quote_no`／`po_doc_code`／`material_item_id`／`delivery_mode`（`stock` 入庫、`direct` 直送）；`stock_items` 加 `material_item_id`；新表 `stock_item_events`（序號異動紀錄）。只新增、冪等、不動既有值。
- 新提供者 `stock.receive`（IP-118，暫定號；`modules/supply/receive.py`）：一站式到貨的入庫那一半。吃呼叫端連線、不 commit（與案件存檔同一筆交易）；逐列回報（重複／空白／已存在的序號不寫、不擋其他列）、一列最多 50 筆；`direct`（D1＝A）只留批次表頭；入庫權限＝管理員（`can_receive` 一處，P2-pre 上線後由該處放寬）；沒有權限 ⇒ 不寫庫存、回 `NO_PERMISSION`（案件只做自己那一半）；旗標關 ⇒ `DISABLED`。
- 序號異動紀錄（`modules/supply/stock_events.py`）：旗標開時，進貨、出貨核准、撤銷出貨、設備安裝（`claim`）、釋放（`release`）、人工報廢／退回在庫都寫一筆；只有從啟用日起才有歷史、不回補；寫入失敗不擋主流程。
- `stock.case_summary`（IP-117）：旗標開時多回 `receivedInStock`（為該案入庫、還在庫的台數）、`directBatches`、每料號 `inStock`；旗標關時回應與今天相同。物料流程時間軸的入庫格據此顯示完整數字。
- 新端點 `GET /api/inventory/reconcile`（管理員；旗標關 ⇒ 404）：入庫對帳表——案件已確認到貨、庫存這一側沒有入庫或直送紀錄的材料申請（經 IP-119 `material.received_list`；M01 不在 ⇒ 空清單）。唯讀、沒有金額。
- 進貨批次／序號的讀取回應：旗標關時不帶新欄位（`quote_no`／`po_doc_code`／`material_item_id`／`delivery_mode`），與今天相同。
- 審查補強（h9）：`stock.receive` 直送防重複（同一筆材料申請已有直送批次 ⇒ 該列不寫，分批由呼叫端帶 `additional`）、`materialItemId` 必須是該案件已確認到貨的材料申請（經 `material.shippable`）、`caller=None` 只限可信內部呼叫；對帳表先過濾再取滿一頁（不被已處理項擠掉）、`since` 格式檢查（400）；人工刪除在庫序號也留 `delete` 異動。
- 本批不含新畫面（一站式到貨畫面是 P2b）；`POST /api/inventory/batches` 行為不變。
- 測試：`tests/test_onepipe_p2a_receive_ledger_2026_11_14.py`。

## 1.0.40 — 一條龍 P0c／P0a／P1'（feat/onepipe-p0-p1，含審查修正、守門補登與 case_summary 註記；旗標 `onepipe.ship_install_ok`、`onepipe.links`，預設開（升級後一條龍功能預設開啟；關閉＝與今天逐位元相同））；已併 T82 凍結 head f66dfd9ef
- **升級後一條龍功能預設開啟（T84 使用者裁示：一條龍上線就開啟）：群組 `onepipe` 每個旗標預設 1；既有環境啟動時一次性遷移把存成 0 的改成 1（經設定中心引擎、稽核「系統升級」、只跑一次，之後使用者自己關掉的保留）；仍可在設定中心逐項關閉，關閉＝與今天逐位元相同。** 本模組的一條龍行為（旗標見標題）升級後即生效；預設值與遷移見 core 的 CHANGELOG。
- 守門補登：`modules.json` 補歸屬（M03：`supply/case_summary`）；未經範圍讀取基準登記 `release`／`case_summary` 兩筆（理由見 `test_unscoped_reads_ratchet.py` 的 MAX_ENTRIES 註解）。
- `stock.serial` 的 `claim`：旗標開時，**同一案件**出貨（`shipped` 且 `quote_no` 相同）的序號可由該案登載成設備 ⇒ 標成 `installed`、保留出貨單號、回 `"in_stock"`（不再報序號衝突）；他案出貨、無案號或已被認領的序號仍回原狀態（衝突）。
- `release`：**看資料、不看旗標**——從出貨狀態登載來的序號（`installed` 且還帶著出貨單號；在庫認領的一定沒有單號，旗標全程關時不會進這個分支）釋放後，若該出貨單仍是已核准 ⇒ 回到 `shipped`（保留案號與出貨單號）；出貨單已不是已核准 ⇒ 回 `in_stock` 並清掉出貨單號。在庫來的照舊回 `in_stock`。`claim` 的更新加 `AND status='shipped'` 並檢查 rowcount。
- 撤銷出貨單核准（`POST /api/shipping-notes/{no}/revoke-approval`）：這張單的序號有 `installed`（先出貨後登載）⇒ 409「這張出貨單有設備已登載安裝，請先從案件移除設備再撤回」；旗標從沒開過就不會有這種列，行為與今天相同。
- `stock.case_summary` 有給 `caller` 時，要有「檢視庫存」同一組模組權限（`inventory`／`procurement`／`case_manage`／`netplan_edit`），沒有 ⇒ 403；沒給（內部呼叫）不檢查。
- 一條龍 P0a（旗標 `onepipe.links`）：出貨單的四種信件與站內通知（送審、輪到簽核、核准、退回）、模組活動信的連結改為該案件頁的出貨單分頁 `case-management.html?q=<案號>&tab=shipping`（原連結 `shipping-notes.html` 不存在）；旗標關或查不到案號 ⇒ 連結與站內通知的 link 欄與今天相同。新增 L1 公開函式 `helpers.email_notify.shipping_link(note_no)`。
- 一條龍 P1'：新提供者 `stock.case_summary`（IP-117，暫定號；`modules/supply/case_summary.py`）——該案件已安裝／已出貨／作廢的序號台數與料號（唯讀、只有數量沒有金額），給案件的物料流程時間軸入庫格用。
- 測試：`tests/test_onepipe_p0c_ship_install_2026_11_13.py`（旗標關仍衝突；開：同案登載／釋放、他案與已認領仍衝突、在庫路徑不變）。無 migration、無新表。

## 1.0.39 — 2026-11-13（feat/upload-files-txn；T83；版號由列車取）
- 變更（內部）：出貨單回簽附件（`api/shipping_notes.py` signed-files 上傳／刪除）。附件清單寫回改用 L1 `helpers.uploads.files_txn／append_json_list／remove_json_item`（T83 審計 C 組）：原本先讀出現有清單、存檔（數秒）、再整份寫回，兩個請求同時上傳會互相蓋掉紀錄（先寫那批的檔成孤兒、請求卻早已回 201），寫庫失敗或單據在上傳途中被刪也會留下沒有紀錄的檔（舊寫法 UPDATE 影響 0 列仍回 201）；刪除端點則是先刪實體檔、再整份寫回。現在：存檔做完才拿寫鎖、重讀目前清單、只加自己這批，任何失敗回收這次剛存的檔；單據不存在 ⇒ 404；刪除在寫鎖內重讀、commit 之後才刪實體檔。API 路徑與回應形狀不變。 測試：`tests/test_upload_files_txn_2026_11_13.py`。

## 1.0.38 — 2026-11-13（feat/ux-p15-dashboard；UX P1.5）；併入 fix/wording-t82-sweep（T82 用詞整理）
- 文字（T82 用詞整理）：出貨單「僅草稿狀態可送出審核」409 訊息 → 「…可送出簽核」；僅訊息文字，狀態判斷不變
- 前端（文字）：頁面 `<title>` 後綴「專案管理系統」一律改為「MOTRIX PLATFORM」（系統標語改由公司設定 `brand.tagline` 決定，預設 MOTRIX PLATFORM）；不動 API／資料／權限。

## 1.0.37 — 2026-11-13（fix/backlog-bugs-20261113；T81 backlog 修正，版號由列車取）
- 前端：`shipping-export-history.html` 等頁的載入失敗訊息改用 UX 規範的白話（403／連線失敗／其他），狀態碼只進 console。無 API／資料／權限變更。
- 測試：`tests/test_e2e_load_error_banner_2026_11_13.py`。

## 1.0.36 — 2026-11-11（fix/t80-conn-leak-net；進貨建批的重複序號檢查納入寫鎖；L1 介面不變）
- 修正（後端）：`POST /api/inventory/batches`（`create_batch`）整段改在 `write_txn` 內：重複序號檢查與逐筆 INSERT 之間原本沒有寫鎖（先查再寫的 TOCTOU），併發進貨同序號時 INSERT 丟 `IntegrityError`，連線沒 rollback／close ⇒ 寫鎖留到被 GC，下一個寫入者卡 30 秒。寫鎖現在在檢查之前拿，`next_entity_code` 取批號也在鎖內。正常路徑回應不變。
- 測試：`tests/test_create_batch_write_lock_t80.py`（重複檢查那一刻已在寫交易內，舊碼紅、新碼綠；序號撞 UNIQUE 後鎖已放）。
- 來源：`docs/platform/GET-DB-CONNECTION-LEAK-AUDIT-T80.md` §6／R5。無 migration、無新表。

## 1.0.35 — 2026-11-11（feat/ux-navigation-hierarchy；UX 提案批次 1+2「導覽與資訊架構＋視覺層級」；不動 API／資料／權限判斷；L1 介面不變）
- 頁頭（B6）：`suppliers.html`／`procurement.html`／`inventory.html`／`parts.html` 的眉標改為自動麵包屑（「採購與庫存 › 頁名」，由 sidebar.js 依選單群組填入）；群組顯示名稱「廠商與採購」改為「採購與庫存」。
- 前端視覺（D3）：本模組頁面內文字最小 12px（原有 9～11px 一律拉到 12px）；文字色改用語意 token（`--text-secondary` #595959／`--text-dim` #666666／深底 `--text-on-dark-dim` #A3A3A3，在頁底 #F5F4F0 上對比 ≥4.5:1）。只改 CSS 值，不改版面結構、不改 API、資料、權限。規格見 `docs/UI-HEADER-COLOR-SPEC.md`。
- 測試：`tests/test_e2e_nav_hierarchy_2026_11_11.py`（7 項真瀏覽器：每個舊入口仍可達、群組與報表中心頁籤、權限過濾、頁頭麵包屑）。

## 1.0.34 — 2026-10-17（wip/t70-supply-caps-r1；T70-2 PM-S5：供應商能力宣告＋端點接線，預設等價）
- `module.json` 新增 `capabilities`（4 項：`supply.supplier.view｜create｜edit｜delete`）；`legacy` ＝ 今天的閘（最高管理者，或持有「客戶」「採購」「庫存」任一功能勾選），種子矩陣不給任何角色預設勾選 ⇒ 行為與今天逐位元相同。`delete` 依框架規則一律列高風險：之後在權限頁放寬需填原因、等確認期間、由另一位最高管理者核准。
- `api/suppliers.py`（7 支：清單、新增、修改、刪除、更新拜訪、聯絡人個資告知讀取／登記）的第一道閘由 `require_any_module(…, "供應商管理")` 改為 `user = _require_user(authorization)` ＋ `perm.require(user, <能力鍵>)`；本體不動。被擋時 403 訊息改為『權限不足：需要「…」（鍵）』（狀態碼不變）。
- 刻意不接：庫存（`inventory.py`）、出貨單（`shipping_notes.py`）各端點的閘不同（多模組、含案件／簽核人判斷），留給後續。
- 測試：`modules/supply/tests/test_supplier_perm_wiring_t70.py`（結構＋純函式等價）、`modules/supply/tests/test_supplier_perm_wiring_http_t70.py`（真實帳號 HTTP 等價：6 角色 × 7 種勾選形狀 × 7 支端點；矩陣編輯後行為跟著變）。

## 1.0.33 — 2026-10-16（wip/t68-c7-r1；C7 採購建議狀態顯示名稱）
- `pages/inventory.html` 採購建議視窗的狀態文字與「標記已下單／標記已到貨」按鈕改讀設定中心『採購建議：狀態名稱』（預設＝待下單／已下單／已到貨，逐字相同）；狀態值 suggested／ordered／received 與必須依序經歷的規則不變。

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
