# 網路規劃 更新紀錄

## (next) — 2026-10-10（wip/t50-int；第 50 班）
- **（併入）(next) — 2026-10-09（wip/t49-strict-bool；W1c-P4）**
- `module.json` `provides.routes` 明列 `/api/quotations/{quote_no}/network-plan`（`modules.json` M10 本來就有）：它落在案件模組的 `/api/quotations` 前綴底下，demo 缺席訊息原本會把它算成案件的。行為只影響 demo 缺席提示；沒有端點／權限變更。

## 1.0.9 — 2026-10-09（wip/t49b-b5-netplan-writes）：規劃書寫入端點同套逐案權限
- ab 稽核補強：`PUT /api/network-plans/{id}`、`PATCH …/status`、`POST …/import/excel`、`POST …/privacy-notice/ack` 原本用裸 `SELECT … WHERE id=?`，沒有讀取端點的逐案權限——有 netplan_edit 但沒有該案權限的人讀得到 404、卻能改（200）；ack 回 409 還洩漏『存在』。現在四支都先過 `_load_visible_plan`（看不到＝404、什麼都不寫）。
- admin／最高管理者視為直通：案件列被刪掉時 `case.access.allowed` 回 False，不能讓規劃書從 admin 眼前消失（一般人員案件不在就不給看）。
- 測試：`test_netplan_visibility_t49.py` 新增三題（無案件權限的寫入 404 且資料列不變、擁有者與獨立規劃書照常可寫、案件被刪後 admin 仍看得到）。

## 1.0.8 — 2026-10-09（wip/t49-b5-visibility）：規劃書讀取加逐案權限（可見範圍收緊）
- `GET /api/network-plans`、`GET /api/network-plans/{id}`：綁定案件的規劃書改依「依案件查詢」同一道逐案權限——看不到該案的人（不是該案業務／協作者、不是 admin 以上、沒有 case_manage）清單看不到、單筆 404；沒綁案件的獨立規劃書與 admin／最高管理者不受影響。案件模組不在時，綁案件的規劃書只給 admin 以上。
- 補洞：Excel／PDF 匯出、拓樸預覽原本只驗登入（任何登入者可匯出任一份），現在要規劃書讀取模組（netplan／netplan_edit／case_manage）並套同一道逐案權限；個資告知查詢同樣套逐案權限。

## 1.0.7 — 2026-09-30（暫用號，列車取號；wip/w3-export-pdf）
- 匯出規則（使用者 2026-09-30）：網路規劃 Excel／PDF 匯出每次寫稽核（`export.xlsx`／`export.pdf`）。

## 1.0.6 — 2026-09-27 23:02（暫用號；H10 品牌設定，主持派工）
- 頁面的分頁圖示（favicon）改讀 `/api/system/branding/favicon`（L1 品牌設定，可在公司資料設定更換；沒上傳回預設圖）：`network-plans.html`、`network-plan-form.html`、`topology-quick.html`

## 1.0.5 — 2026-09-27（C，M01-PLAN §5 ④；列車取號）
- 頁面（稽核 D M4-M2，M01-PLAN §5 ④）：案件模組（M01）不在 ⇒ 新增規劃書的「綁定案件」停用並明說「案件模組未安裝：無法綁定案件（規劃書本身照常可建立）」，不再是空清單；e2e `tests/test_e2e_pages_without_case_module_2026_09_27.py`（含正對照）

## 1.0.4 — 2026-09-26
- 選單宣告搬進本模組：`network-plans.html` 的 `pages[].menu`（原寫在 L1 的 `core/menu_l1.json`；group／order／perm／badge 原值照搬）。階段 C／C4（主持裁示 A）：本模組不在時它的入口隨宣告一起消失，不再靠前端寫死的頁面⇒模組對照表；〔rebase 到 origin：h-probes 已取 1.0.3 ⇒ 本段 1.0.4〕

## 1.0.3 — 2026-09-26
- 宣告 `provides.probes`（D7 演練與產品演練打這幾支確認模組在；純讀、無副作用，D7-CHECKLIST §4）

## 1.0.2 — 2026-09-26
- 第四班列車：IP 定號（`daily.check` IP-10→IP-11、`case.access` IP-11→IP-12，cb4667b1）
- `module.json` 補 `customization`（本模組目前沒有可自訂點：寫出空類別＝有人決定過）

## 1.0.1 — 2026-09-26
- 快速拓樸的說明文字不寫死頁面路徑（頁面位置一律經 `core.source_tree`）

## 1.0.0 — 2026-09-26
- 模組化：`routers/network_plans.py` → `modules/netplan/api.py`、`routers/network_plans_quick.py` 併入同一檔、同一支 router、`network_plan_export.py` → `export.py`、`network_plan_topology.py` → `topology.py`；三份測試移入 `tests/`（PLAYBOOK §B）
- 對 M01 的兩個相依（案件逐案權限、讀案件客戶／專案名稱）改走 IP-12 `case.access`；M01 不在時規劃書照常，只是不能綁定案件，並明說
- 第四班列車：搬遷期間 origin 在舊檔新增的個資蒐集告知兩支端點（`GET /api/network-plans/{id}/privacy-notice`、`POST …/privacy-notice/ack`，e381fdd0）原樣移入 `api.py`
