# 網路規劃 更新紀錄

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
