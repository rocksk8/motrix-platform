# 端點稽核 W1b：case／subcontract／supply（第 48 班，基底 origin/platform 4012847ab）

作者：b5。範圍：`backend/modules/{case,subcontract,supply}/**`（router、module.json、provider／consumer）。方法：AST 掃描 251 條路由（case 139／subcontract 74／supply 38）＋實際 app 路由表（OpenAPI）無憑證／無模組帳號呼叫＋全庫 grep 對照前端、測試、文件。掃描腳本不進 repo；可重複的部分已變成守門 `tests/test_endpoint_auth_w1b_t48.py`。

## 結論（先看）
| 項目 | 結果 |
|---|---|
| (1) module.json `api_prefixes`／`probes` | 三個模組**無遺漏、無失效**：每條真實路由都落在某個宣告前綴下；宣告的前綴都有路由；probes 全是存在的 GET 路由。`case` 的 `/api/quotations` 前綴同時有別的模組掛路由——本來就是共用前綴，記錄不動。 |
| (2) 授權守門 | **251/251 條路由都有 `_require_user`（或包裝）**；無憑證呼叫全部被拒（新守門）；無跨檔「參數路由吞掉靜態路由」；無重複路由。66 條只呼叫 `_require_user` 的路由，逐一確認有自己的角色／模組／案件判斷或是刻意「任何登入者」。**發現 1 個真缺口，已修（見下）**。 |
| (3) IP 登記 | 本範圍 provider 全部有文件段落；沒有「被取用卻沒人提供」的能力；取用端對缺席提供者都有 fail-safe（`if pub else []`、`part()` 包裝等）。IP-112／113／114／115 皆有段落與提供者。僅 `uploads.path_access` 在 grep 看起來沒被取用——實為常數 `PATH_ACCESS` 取用，非缺口。 |
| (4) module.json／頁面／信件 | 所有 `pages` 檔案都存在、無一頁被兩個模組宣告；不在任何 module.json 的頁面全是 L1 頁（守門 `test_core_pages`）。信件類型：本範圍 33 個 `send_registered` 字面 key 由既有 `test_mail_registry` 逐一核對。權限鍵（`case_manage／quotation／contractor_list／procurement／inventory／shipping_export_log／netplan_edit／customer／financial_view`）皆為已知鍵（模組宣告或 L1 `menu_l1.json`）。 |
| (5) 死端點 | 三個「前端無呼叫」候選，**都不符合『零引用』刪除條件**，只列出建議，不刪（見下）。 |
| (6) 前端懸空呼叫 | 對 case／subcontract／supply 的前綴**沒有懸空呼叫**（掃描器列出的 33 筆全是字串拼接／模板雜訊或其他模組路由，逐筆檢查過，例如 `/api/expense-categories` 屬 accounting）。 |

## 已修（分支 wip/t48-w1b-fixes）
1. **subcontract `GET /api/contractor-vouchers/last-paid-bank-account`**：任何登入者（含完全沒有模組的帳號）都讀得到公司最近一次「標記已匯款」用的付款帳戶名稱與科目代碼。同型的 `quotations/last-received-bank-account` 早已限財務角色，庫存版 `inventory/batches/last-paid-bank-account` 也要模組。⇒ 加 `has_cashier_access` 檢查（財務角色＋最高管理者），其他 403。測試 `modules/subcontract/tests/test_w1b_fixes_t48.py`（無模組／一般人員 403、無憑證 401／403、財務與超管 200）。
2. **新守門** `tests/test_endpoint_auth_w1b_t48.py`：走真實 OpenAPI 路由表（三個模組宣告前綴下的全部路由），無憑證呼叫一律不得 2xx／5xx；含正對照（確認掃描器真的走到關鍵路由、數量≥200）。以後新增的路由漏了登入檢查會直接紅。

## 保留不動（附理由）
- **任何登入者可讀（by design）**：`GET /api/contractors/selectable`（外包名冊 id／姓名／電話，案件派發下拉用；比照 `vendor-contractors/selectable`，程式註解明載；電話屬個資——若要收緊須同時確認所有會用到派發表單的角色，屬需求裁示，列為提案）、`/api/overhead/settings`（報價單載入要讀預設百分比與模式）、`/api/contractor-vouchers/settings/approval-flow`（與 L1 `/api/settings/approval-flow/{doc_type}` 同為任何登入者可讀，簽核頁需要；寫入皆限最高管理者）、`/api/next-quote-no`、`/api/quotations`／`stage-board`／`gate-matrix`／`approval-history`／`extra-expenses/cases|mine`（回傳內容已依案件存取／使用者過濾，無模組帳號實測只看到自己的）。
- **緊急開關**：`GET/PUT /api/contractor-vouchers/settings/remit-require-payslip`（無 UI，文件與測試有引用）保留。

## 死端點候選（提案，未刪）
| 路由 | 現況 | 建議 |
|---|---|---|
| `GET /api/quotations/{quote_no}/material-po-lines` | 前端、測試、文件皆無呼叫；只剩 CHANGELOG 敘述、模組 docstring、`route_table_golden.json` | 可刪，但要同步改 route_table_golden 並由主持裁示（golden 規則「只准加不准改」）。 |
| `POST /api/quotations/case-activity` | 前端無呼叫；有測試（write-audit 清單）與文件 | 確認是否還有外部腳本／行動端使用後再議。 |
| （更正）`GET /api/contractor-vouchers/last-paid-bank-account`、`GET /api/inventory/batches/last-paid-bank-account` | **有前端呼叫者**：`cashier.js:615`、`case-management-dispatch.js:722`（承攬商匯款標記視窗預帶帳戶）、`inventory.html:697`（進貨批次付款視窗）；原稿「前端無呼叫」是我 grep 漏了模板字串（`${…}`）造成的錯誤 | 保留；承攬商那支已收緊為財務角色／最高管理者——標記已匯款本來就是出納動作，視窗預帶失敗時退回預設帳戶（前端對非 ok 回應不報錯） |
其餘 70 條「找不到精確前端字串」的路由，皆為前端以字串拼接動態呼叫（`.../${action}`、`_postWriteoff(idx,'request-writeoff')` 等），逐筆 grep 有前端或測試引用。

## 延後
- 逐條驗證 66 條「僅 `_require_user`」路由的**授權語意是否恰當**（是否該更嚴）超出靜態可證範圍；已用無模組帳號實測 GET 面（87 條 GET 中僅 11 條回 2xx，皆列於上）。寫入端點的細部權限由各模組既有測試與 `test_write_endpoints_are_audited` 守。
- 跨模組共用前綴（`/api/quotations` 同時掛在 arap／crm 等）屬其他視窗範圍。
