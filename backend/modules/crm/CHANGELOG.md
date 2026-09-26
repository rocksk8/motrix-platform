# 業務開發 更新紀錄

## 1.0.4 — 2026-09-26
- 第五班列車反向控制（§B-11）：刪報價單「M02 在 ⇒ 沒有 notice」的 e2e 正對照需要本模組，自模組外拆進 `modules/crm/tests/test_e2e_crm_quote_delete_no_notice_2026_09_26.py`

## 1.0.3 — 2026-09-26
- 第五班列車：IP 定號（`crm.quote_deleted` IP-11→IP-13；origin 已用到 IP-12 `case.access`）

## 1.0.2 — 2026-09-26
- 稽核 D M02-S2：補「改不了」的題——外人修改內容、狀態、轉建、新增開發記錄一律 403 且資料不變，刪除／重新連結申請只准管理員；突變（四個端點各拿掉列權限檢查）皆紅

## 1.0.1 — 2026-09-26
- 稽核 D M02-M1：需要本模組的 33 題搬進 `modules/crm/tests/`（整檔 2、拆出 7 檔；混合檔只拆業務開發那幾題），本模組不在時跟著消失
- `module.json` 補 `customization`（P3：目前沒有宣告可自訂點）

## 1.0.0 — 2026-09-26
- 模組化：自 `routers/dev_crm.py` 搬入 `modules/crm/api.py`（PLAYBOOK §B）；路由自帶 `/api` 前綴，由載入器掛載；每日 08:00 的停滯／暫緩到期檢查改由 `ModuleSpec.schedulers` 宣告
- 新增串接點 IP-13 `crm.quote_deleted`：報價單刪除時解除轉建連結改由本模組提供（原本 M01 直寫 `dev_cases`）
- 報價單清單刪除時顯示 IP-13 的 notice（原本只看成功與否）
