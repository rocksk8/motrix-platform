# 外包工班 更新紀錄

## 1.0.8 — 2026-09-26
- 附件來源看不到時說出沒列出幾個附件（`AttachmentNotVisible(hidden=N)`，只有數字；主持裁示：因權限沒列出要明說，不可以帶出單號與內容）

## 1.0.7 — 2026-09-26
- 附件來源提供者加權限（稽核 D AT-M1，主持裁示 (b)）：`files`／`doc_nos_for_case` 多帶 `user`，看不到派工單所屬案件的人 ⇒ `AttachmentNotVisible`（同派工單清單的讀取規則）

## 1.0.6 — 2026-09-26
- 提供 `attachments.for_document`（IP-21 暫定號，主持裁示 M06-b）：派工單與承攬商發票的已上傳檔案（`attachments.py`）；M06 傳票帶入附件不再直讀 `contractor_dispatches`。本模組不在時，傳票頁明說「外包工班模組未安裝：派工單、承攬商發票的附件沒有列出」、帶入 400 並說明

## 1.0.5 — 2026-09-26
- D7 演練：`module.json` 宣告 `provides.probes`（`/api/contractors`、`/api/vendor-contractors`、`/api/contractor-dispatches`、`/api/contractor-vouchers`）——純讀的 GET、在本模組前綴下、模組在時回 200（守門 `tests/platform/test_product_drill_probes.py`、`test_probe_side_effects.py`：不寫表、不寄信、不排程、不把回應值寫進 log）

## 1.0.4 — 2026-09-26
- 第六班列車：IP 定號（`dispatch.list_for_case` IP-12→IP-15、`quotation.append_items` IP-13→IP-17；origin 已用 IP-12 `case.access`、IP-13 `crm.quote_deleted`；`contractor_voucher.public` 維持 IP-14）；只改註解與文件

## 1.0.3 — 2026-09-26
- 稽核 D M04-M1（§B-11 反向控制：刪掉本模組跑 tests/platform＋提到 M04 的所有題）：需要本模組的題搬進本模組 `tests/`（整檔 9、從 19 個混合檔拆出 36 題，同檔名）；留在外面的守門改以 `core.source_tree.module_installed` 判斷本模組在不在（連簽 helper、EM1 訊息、module_history 前例、案件單據端點、案件頁黃金錄製）；兩個模組層 import 改在題目裡 import
- 承攬人員名冊、承攬商的個資告知端點登記 `api_module: subcontract`（`docs/platform/pii_forms.json`）：本模組不在時不比對端點，告知區塊照驗
- M04-S1：`INTEGRATION-POINTS.md` 提供方路徑補 `api/`，並加守門「模組在時提供方檔案必須存在」；M04-S2：README 的 M01 不在判準改 `case.access`（IP-12）；M04-S3：SPEC.md 指向本模組 tests/；O-1：`privacy_notice_acks` 維持 L1 共用（主持裁示），README 劃掉並加〔更正〕

## 1.0.2 — 2026-09-26
- `module.json` 補 `customization`（P3：目前沒有宣告可自訂點，寫出空的類別＝有人決定過）

## 1.0.1 — 2026-09-26
- 搬遷後續：已廢棄的匯款簽核設定頁（AS4）不列入 `pages`；IP-1 的契約與正對照題搬進本模組的 tests/（本模組不在時跟著消失）；測試不用規格編號樣式的名稱
- 出納頁在本模組不在時說出原因（e2e）

## 1.0.0 — 2026-09-26
- 模組化：自 `routers/contractors.py`、`routers/vendor_contractors.py`、`routers/contractor_vouchers.py` 搬入 `modules/subcontract/`（PLAYBOOK §B）；由載入器掛載
- 提供者改由 `ModuleSpec.providers` 宣告：IP-1 `dispatch.row`、IP-12 `dispatch.list_for_case`、IP-14 `contractor_voucher.public`
- 派工品項匯入報價單改用 M01 的 IP-13 `quotation.append_items`（不再自己讀寫報價單）
- 日期欄驗證改用 L1 `helpers.dates.normalize_date`；案件存取守門改用 L1 `helpers.case_access`
