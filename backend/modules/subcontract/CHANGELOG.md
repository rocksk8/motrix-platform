# 外包工班 更新紀錄

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
