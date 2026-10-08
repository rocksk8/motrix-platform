# 勞報單人員 ⇄ 派工連動（第 48 班）

作者：b5。基底 `origin/platform` 412a53630（第 47 班已上線）。需求（使用者經 node-d8 轉述，表單裁示）：勞報單的人員要能連動到案件管理內的派工——①依「人」自動連結 ②用外包名冊主檔 id 當鍵、不再靠名字比對 ③可見範圍不變（派發頁不出現金額）。

## 1. 現況（已查實）
- 派發 `contractor_dispatches.personnel_json`＝`[{id, name, amount, note}]`，`id` ＝ 外包名冊 `contractors.id`（`case-management-dispatch.js` 加人時帶入）。
- 勞報單 `payslips.contractor_id`（欄位已存在，FK `contractors`）＋ `contractor_name`；`payslip-form.html` 從名冊挑人會帶 `contractorId`，但姓名欄仍可手改、也可不挑人 ⇒ `contractor_id` 可為 NULL。
- 連結表 `payslip_dispatch_links`（P3，IP-112／IP-113）：手動連結＝最高管理者；建立時可帶單一 `dispatchId`。

## 2. 資料模型／遷移（payroll migration 5，冪等）
- `payslips.contractor_match TEXT NOT NULL DEFAULT ''`：`''`＝已確認（新單、人工確認過）；`'unconfirmed'`＝舊單靠名字推測的對應。
- 回填：`contractor_id IS NULL` 且 `contractor_name` 去空白後**恰好對到一位**名冊人員（`contractors.name`，唯一、不分在職）⇒ 寫 `contractor_id`＋`contractor_match='unconfirmed'`；對不到或多位同名 ⇒ 不動（保持 NULL）。重跑不改任何已有值。**不建任何連結列**。
- 回滾：`contractor_match` 欄位留著無害；要還原回填＝`UPDATE payslips SET contractor_id=NULL WHERE contractor_match='unconfirmed'`（寫進 CHANGELOG 回滾段）。

## 3. API
- 新增提供者 `dispatch.by_person`（M04→M07，registry 單一提供者，IP-115 暫定）：`fn(conn, contractor_id)` ⇒ `[{id, docCode, quoteNo, status, vendorName, dispatchDate}]`（掃 `personnel_json`，**不含金額**，上限 200 筆，新到舊）。`dispatch.brief` 加欄位 `personnelIds`、`dispatchDate`（加法）。
- 新增 `GET /api/payslips/person-dispatches?contractor_id=`（最高管理者＋勞報單模組）：勞報單頁勾選用。
- `POST /api/payslips` 新增 `dispatchIds: [int]`（取代單一 `dispatchId`，後者仍相容）：必須同時有 `contractor_id`；每個派發必須存在**且 `personnelIds` 含該人**，否則 400；同一交易連結（任一失敗整張不建）。連結由系統代為執行，手動新增／解除仍只有最高管理者。
- `POST /api/payslips/{slip_no}/confirm-contractor`（最高管理者）：把 `contractor_match` 清成 `''`（可附帶 `contractor_id` 改對人）；稽核。
- `PUT` 更動 `contractor_id`（人工改選）⇒ `contractor_match=''`。
- 提供者 `payslip.dispatch_links` 加 `payslips_for_contractors(conn, ids)`：只回 `contractor_match=''`（已確認）的勞報單，欄位同現有（單號、狀態、受領人、開單日、已作廢旗標），**不含金額**。
- `GET /api/contractor-dispatches/{id}/payslip-links` 回應加 `byPerson`（該派發人員名單的已確認勞報單，扣掉已手動連結的）與 `unconfirmedCount`（只給數字、不列內容）。

## 4. UI
- `payslip-form.html`：挑名冊人員後，列出該人的派發（勾選，預設不勾）；新單送出帶 `dispatchIds`。沒挑名冊人員（手打姓名）⇒ 提示「未選名冊人員，不會連到派工」。
- `payslips.html`：舊單 `contractor_match='unconfirmed'` 顯示「身分待確認」標籤；最高管理者可按「確認」。
- 案件管理派發卡片：原「勞報單」區塊下加「同一人員的勞報單」清單（單號、狀態、受領人，無金額）。

## 5. 權限／金額可見（不變）
派發頁仍無金額；手動連結／解除僅最高管理者；核准／揭露／銀行與身分資料規則不動；自動連結只在建立勞報單的交易內由系統執行。

## 6. 測試
API（遷移冪等＋唯一對應才回填、同名不回填、不建連結；建立帶多派發同交易、任一派發不含此人 ⇒ 400 且整張不建；confirm 端點權限；byPerson 排除未確認與已手動連結）；e2e（payslip-form 建立流程勾選派發；派發分頁以最高管理者與一般派發檢視者看，皆無金額）；突變檢查（拿掉「派發必含此人」檢查、回填不查唯一性、byPerson 不過濾未確認，各自必紅）。

## 7. 待決（依建議直接做）
1. 同名多位名冊人員的舊單：不回填（建議）。2. 作廢的勞報單在 byPerson 仍列出並標已作廢（同現有連結）。3. 手打姓名（無 contractor_id）的新單是否擋下：不擋，只提示（不碰錢）。

## 8. 回滾與步驟檔註記（第 48 班）
- **只回程式碼（不還原 DB）**：安全。模組 migration 載入器只跑「版號大於庫內記錄」的支（`core/migrations.py::run_all`：`v <= start` 跳過、不比對「庫比程式新」）；實測（暫存記憶體庫，庫內 payroll=5、程式只登記 1～4）：`ran={}`、無例外、無 incomplete、版號維持 5。舊程式的 `INSERT/UPDATE` 不帶 `contractor_match`（預設 ''）、`SELECT *` 照常，新欄位無害；已寫進去的 `payslip_dispatch_links` 連結列舊程式本來就認得（第 46 班表）。
- **殘留與處理**：舊程式下 PUT 會把舊單的 `contractor_id` 依表單送的值覆寫（沒帶＝NULL），`contractor_match='unconfirmed'` 標記留著無害。要完整還原回填：`UPDATE payslips SET contractor_id=NULL, contractor_match='' WHERE contractor_match='unconfirmed'`；（依人建立時自動連結的）`payslip_dispatch_links` 不必刪（與手動連結同表同形，舊頁面照常顯示）。
- **還原 DB 備份**：照第 46 班起的慣例（回滾須還原 DB 備份）時，備份前建立的連結／確認一併回到當時狀態，不需額外動作。
- **步驟檔（正式機）**：無新增步驟——migration 啟動時自動執行（只加欄位＋保守回填，秒級；不需停機額外動作）。上線後驗證一行：`SELECT contractor_match, COUNT(*) FROM payslips GROUP BY 1`（'unconfirmed' 的是回填、請最高管理者在勞報單頁逐張確認）。

## 9. 驗收清單（新的使用者可見行為）
1. 勞報單新增頁：從外包名冊選人後，出現「這位人員的派工」清單（只列人員名單含他的；無金額）；勾選後建立 ⇒ 勞報單與這些派發已關聯。
2. 沒從名冊選人（手打姓名）⇒ 頁面提示「不會連到任何派工」，仍可建立。
3. 案件管理派發卡片：「勞報單」區塊下多一行「同一人員的勞報單」——最高管理者可點進勞報單、一般人員只有文字；兩者都看不到金額。
4. 舊勞報單（上線前建立、僅姓名）：若姓名恰好對到名冊一人 ⇒ 勞報單頁顯示「身分待確認」，最高管理者按「確認受領人對應」後才出現在該人員的派發頁；同名多位或查無 ⇒ 不處理。
5. 一般人員（非最高管理者）仍不能建立／解除派發與勞報單的手動關聯；派發頁不出現任何金額、扣繳、身分、銀行資料。
