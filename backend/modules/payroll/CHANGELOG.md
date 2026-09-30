# 薪資獎金 更新紀錄

## 1.1.7 — 2026-09-30（暫用號，列車取號；wip/w2-upload-magic：上傳檔頭檢查）
- 勞報單簽回檔上傳（`POST /api/payslips/{no}/signed-files`）在副檔名檢查之後呼叫 L1 `_check_upload_magic`（檔頭與副檔名不符 ⇒ 400＋稽核）；單據狀態、大小、空檔檢查不變。

## 1.1.6 — 2026-09-30（暫用號，列車取號；wip/w2-attach-p2：附件目錄 P2）
- 新增 `attachments.py::_PayrollCatalog`（`attachments.catalog`／`payroll`，IP-105）：勞報單簽回檔開檔（實體檔在封存目錄，宣告 `ROOTS`）；權限＝superadmin 或出納（同簽回檔讀取端點）。

## 1.1.5 — 2026-09-30（暫用號，列車取號；W4 總帳 C6／扣繳補齊）
- 獎金發放事件 E07b（native）多帶 `meta.withholding`／`wh_prefix`（發放當下的每人代扣所得稅與補充保費快照），供總帳扣繳清單；作廢的發放傳票也照送，讓總帳移除未繳庫的列。無 migration。

## 1.1.4 — 2026-09-30（暫用號，列車取號；W4 總帳 R12 畫面）
- `payslip.remit`（IP-105，原暫用 IP-104 與 sec-p0 撞號）新增 `candidates(conn, contractor_id)`：列出該受款人已簽回、未付款的勞報單供匯款單挑選。

## 1.1.3 — 2026-09-30（暫用號，列車取號；W4 總帳 R12）
- 新增提供者 `payslip.remit`（IP-105）：承攬商匯款單驗證、標記、退回勞報單付款；由匯款單付款的勞報單不可單獨 unpay（409，請到匯款單取消），總帳不再另產生其 E06b。無 migration（沿用 data_json.paid_via_remit）。

## 1.1.2 — 2026-09-30（暫用號，列車取號；W4 總帳 C3b）
- 獎金核准應付／發放傳票開立時帶 `origin`（bonus_accrual／bonus_payment，經 `voucher.draft` 可選參數）；`gl.events` 新增獎金事件 E07a／E07b（mode=native，登記既有傳票，不重複產生）。無 migration、無新欄位。

## 1.1.1 — 2026-09-30（暫用號，列車取號；W4 總帳 C3）
- 新增提供者 `gl.events`（IP-GL1）：勞報單應付（E06，已簽回／已付款，依勞報日或簽回日）與付款（E06b，依付款日）事件，供 M06 總帳引擎產生傳票草稿；唯讀、不寫資料、不改欄位；不帶身分證字號。

## 1.1.0 — 2026-09-29（暫用號，列車取號；wip/payslip-void-signed）
- 勞報單作廢（新功能）：`POST /api/payslips/{單號}/void`，只准從「已匯出」、原因必填，終結狀態（不可改／刪／再匯出）；PDF 對已作廢單加斜向「已作廢」浮水印與頂端紅色橫幅（作廢時間、人、原因；`pdf_gen._payslip_apply_void_mark`，版型沒有 <body> 也不漏）。
- 勞報單簽回（新功能）：上傳對方簽回檔 `POST /api/payslips/{單號}/signed-files`（已匯出 → 已簽回；pdf／jpg／png、單檔 20MB），實體檔放勞報單存檔目錄（F2，鏡像流程照走）；讀取 `GET …/signed-files/{id}`（最高管理者或出納）；`DELETE` 只准已簽回、刪光退回已匯出；`POST …/unsign` 退回簽回（才可作廢）。
- 出納付款（新功能）：`POST /api/payslips/{單號}/mark-paid`（最高管理者或 cashier 模組；已簽回 → 已付款；付款日期 YYYY-MM-DD、傳票單號經 M06 `voucher.by_no` 驗證存在且未作廢；會計模組不在 ⇒ 拒絕並說明），`POST …/unpay` 退回付款。
- 新增提供者 IP-103 `payslip.payables`（出納頁待付款，只回付款需要的欄位、不含 F2 個資）與 IP-9 `expense.entries`（名稱 `payslip`：已付款者依付款日期歸月、取應付總額，類別「勞報單」）。
- 狀態鎖：已匯出／已簽回／已付款／已作廢一律不可修改、刪除；補印（再匯出）不會把已簽回／已付款洗回已匯出。
- 首個模組自有 migration：`migrations/0001_payslip_void_signed_paid.py`（payslips 加 10 欄，只新增、冪等、表不在回原因字串）。⚠ 模組更新包（P7）拒收帶 migrations 的模組 ⇒ 這一版走完整部署包。

## 1.0.8 — 2026-09-28（暫用號，列車取號；E4 wip/e-company-gate-impl 第三段）
- 本公司資料設定閘門第二道（COMPANY-SETUP-GATE §5；D CG5-M1）：勞報單 PDF 下載端點：`except Exception` 前先 `except HTTPException: raise`；勞報單視圖（L1）先驗本公司已設定（Q4：單據上手改的公司欄位保留）

## 1.0.7 — 2026-09-27 23:02（暫用號；H10 品牌設定，主持派工）
- 頁面的分頁圖示（favicon）改讀 `/api/system/branding/favicon`（L1 品牌設定，可在公司資料設定更換；沒上傳回預設圖）：`payslips.html`、`payslip-form.html`、`bonus.html`

## 1.0.6 — 2026-09-27（c-approval-l1-4，稽核 D QJ-M1；列車取號）
- 待簽佇列提供者：簽核 JSON 存在獨立欄位的單（`approval_json`／`change_approval_json`）改經 L1 `approval_raw_of`：解析不了 ⇒ 跳過那一筆＋ERROR（原本 `tier_fields` 把壞 JSON 吞成 {} ⇒ 列給每個 superadmin、計角標，核准時才丟例外；稽核 D QJ-M1）

## 1.0.5 — 2026-09-26（C；第九班之後 rebase 重編，原暫用 1.0.3，列車取號）
- 待我簽核（M01-PLAN §3-7）：新增 `bonus_queue.py`，提供 `approval.queue_items`（獎金分潤單 `bonus_award`、案件獎金分潤 `bonus_case_award`，欄位同原 M01 佇列）；M01 佇列與角標不再直讀 `bonus_awards`／`bonus_case_awards`。案件獎金的客戶與案名不再 JOIN M01 的 `quotations`，改由 M01 彙整端依 `linkedQuoteNo` 補

## 1.0.4 — 2026-09-26〔稽核 X C4-S5：c-probes 先上第八班、用了 1.0.3 ⇒ 本段改 1.0.4〕
- D7 演練：`module.json` 宣告 `provides.probes`（`/api/payslips`、`/api/tax-rules`、`/api/bonus/awards`、`/api/bonus/items`）——純讀的 GET、在本模組前綴下、模組在時回 200（守門 `tests/platform/test_product_drill_probes.py`、`test_probe_side_effects.py`：不寫表、不寄信、不排程、不把回應值寫進 log）
- 選單宣告搬進本模組：`payslips.html`、`bonus.html` 的 `pages[].menu`（原寫在 L1 的 `core/menu_l1.json`；group／order／perm／badge 原值照搬）。階段 C／C4（主持裁示 A）：本模組不在時它的入口隨宣告一起消失，不再靠前端寫死的頁面⇒模組對照表；版號與 c-probes／h-probes 交會，列車取號

## 1.0.2 — 2026-09-26
- 規格編號隨模組走：`BN1`～`BN18`、`QS1a` 的條件（原在 STATE.md）與 `BN1`～`BN19`、`QS1a` 的範圍（原在 SCOPE.md）移進本模組 `SPEC.md`；`AC1`／`BN17` 的撞名登記改在本模組 `## 登記`（反向控制：模組不在時這些編號變成「沒有題」與「未宣告」）
- 勞報單稅額純函式題（`TestCalc`，9 題）自 `tests/test_core.py` 拆進本模組 `tests/test_payslip_calc.py`：模組層 import 讓本模組不在時整檔收集中斷（不帶 --continue-on-collection-errors 的反向控制抓到）
- 勞報單的個資告知端點登記 `api_module: payroll`（`docs/platform/pii_forms.json`）：本模組不在時不比對端點，告知區塊照驗

## 1.0.1 — 2026-09-26
- 反向控制（刪掉 modules/payroll）抓到 204 題綁著本模組 ⇒ 需要本模組的題搬進 `modules/payroll/tests/`（整檔 41、從 9 個混合檔拆出）；`payslip_seq` 分類改 T3（編號計數，本來就在備份排除清單）

## 1.0.0 — 2026-09-26
- 模組化：自 `routers/payslips.py`、`routers/bonus.py`、`helpers/bonus*.py`（6 支）搬入 `modules/payroll/`（PLAYBOOK §B；兩支 router 放 `api/`，CORE-SPEC §3）；由載入器掛載
- 提供者改由 `ModuleSpec.providers` 宣告：IP-8 `bonus.payouts`、IP-9 `expense.entries`、IP-16 `bonus.module_status`
- 不再依賴 M06：獎金分潤單的版面元件改用 L1（簽核格顯示名稱、公司抬頭、HTML→PDF、金額格式）——會計模組不在時照樣能預覽與匯出
