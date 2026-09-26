# 外包工班 更新紀錄

## 1.0.5 — 2026-09-26
- 選單宣告搬進本模組：`contractors.html`、`vendor-contractors.html` 的 `pages[].menu`（原寫在 L1 的 `core/menu_l1.json`；group／order／perm／badge 原值照搬）。階段 C／C4（主持裁示 A）：本模組不在時它的入口隨宣告一起消失，不再靠前端寫死的頁面⇒模組對照表；版號與 c-probes／h-probes 交會，列車取號

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
