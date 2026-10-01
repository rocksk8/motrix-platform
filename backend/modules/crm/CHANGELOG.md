# 業務開發 更新紀錄

## (next) — 2026-10-01（wip/w1-attach-p3-a3：附件目錄 P3）
- 附件目錄 P3：`_CrmCatalog` 加 `search`／`count`（開發記錄附件；權限＝`_DevLogPathAccess.readable` 逐開發案）。

## 1.0.15 — 2026-10-01（暫用號，列車取號；wip/w3-local-date）
- 本地日期（使用者 2026-10-01：凌晨建的單日期變前一天）：業務開發頁的記錄日期預設值改用本地日期（static/motrix-date.js）。

## 1.0.14 — 2026-09-30（暫用號，列車取號；wip/w2-open-bind：附件開檔路徑綁單據（安全審查 W3））
- 附件目錄提供者 `open()` 加路徑綁單據檢查（`helpers.uploads.upload_path_key`）：檔案路徑不在這張單據自己的資料夾 ⇒ 當作沒有這個檔。

## 1.0.13 — 2026-09-30（暫用號，列車取號；wip/w2-referrer：業務開發新增「介紹人」）
- 新增案件欄位「介紹人」（`dev_cases.referrer`，自由文字、選填、去頭尾空白、最多 60 字；超過或型別不對 400）：由本模組自己的 migration（`migrations/0001_dev_cases_referrer.py`，只新增一欄、冪等）建立；新增／編輯視窗、列表卡片、詳情、搜尋框（也搜介紹人）、編輯稽核 old→new；備份匯出的 `SELECT *` 自動含此欄。不帶到轉建的報價單（報價單沒有對應的自由「來源」欄位）。

## 1.0.12 — 2026-09-30（暫用號，列車取號；wip/w2-attach-p2：附件目錄 P2）
- 新增 `attachments.py::_CrmCatalog`（`attachments.catalog`／`crm`，IP-105）：開發記錄附件開檔；權限＝`_DevLogPathAccess`（模組規則＋row_access dev_case）。

## 1.0.11 — 2026-09-30（暫用號，列車取號；wip/w1-file-preview 共用檔案預覽 P1）
- 業務開發頁的附件開啟改用 L1 共用預覽元件（頁內預覽，不再開新分頁／換 photo-token）。

## 1.0.10 — 2026-09-30（暫用號，列車取號；wip/cal-toggle 行事曆推送可選）
- 行事曆「業務開發案件更新」（預設關，事件種類開關在 L1）：新增開發紀錄 commit 之後推 `push_event_for_module('dev_case_update', …)` ⇒ 標題「○○案件更新」、說明＝紀錄內容（管道／內容／下一步）、同一案件同一天合併。題 `modules/crm/tests/test_dev_case_update_calendar_2026_09_30.py`
## 1.0.9 — 2026-09-30（暫用號，列車取號；wip/sec-p0 安全修正 P0）
- 安全修正 P0：新增提供者 `uploads.path_access`／`crm`（IP-104，`api._DevLogPathAccess`）：`dev_logs/<案 id>/` 的附件只簽給 `GET /dev-cases/{id}/logs` 放行的人（admin+ 或 dev_crm，且 row_access `dev_case`）。原本任何登入者都拿得到簽章。

## 1.0.8 — 2026-09-27 23:02（暫用號；H10 品牌設定，主持派工）
- 頁面的分頁圖示（favicon）改讀 `/api/system/branding/favicon`（L1 品牌設定，可在公司資料設定更換；沒上傳回預設圖）：`dev-crm.html`

## 1.0.7 — 2026-09-26〔稽核 X C4-S5：c-probes 先上第八班、用了 1.0.6 ⇒ 本段改 1.0.7〕
- D7 演練：`module.json` 宣告 `provides.probes`（`/api/dev-cases`、`/api/dev-logs/pending`、`/api/dev-crm/activity-stats`）——純讀的 GET、在本模組前綴下、模組在時回 200（守門 `tests/platform/test_product_drill_probes.py`、`test_probe_side_effects.py`：不寫表、不寄信、不排程、不把回應值寫進 log）
- 選單宣告搬進本模組：`dev-crm.html` 的 `pages[].menu`（原寫在 L1 的 `core/menu_l1.json`；group／order／perm／badge 原值照搬）。階段 C／C4（主持裁示 A）：本模組不在時它的入口隨宣告一起消失，不再靠前端寫死的頁面⇒模組對照表；版號與 c-probes／h-probes 交會，列車取號

## 1.0.5 — 2026-09-26
- 稽核 D M02-S2 觀察：補核准端點（刪除／重新連結）的外人題，並分開角色與列權限——建立者（有列權限）申請 403、管理員（不在名單）申請成功；外人／建立者／管理員核准 403 且資料不變，最高管理者核准成功；突變（兩個核准放寬成管理員、兩個申請不擋角色）皆紅〔原為 1.0.3（wip/c-m02-s2b 6e2e15a7）；第五班定 1.0.4 之後改號〕

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
