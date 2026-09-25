# 網路規劃 更新紀錄

## 1.0.0 — 2026-09-26
- 模組化：`routers/network_plans.py` → `modules/netplan/api.py`、`routers/network_plans_quick.py` 併入同一檔、同一支 router、`network_plan_export.py` → `export.py`、`network_plan_topology.py` → `topology.py`；三份測試移入 `tests/`（PLAYBOOK §B）
- 對 M01 的兩個相依（案件逐案權限、讀案件客戶／專案名稱）改走 IP-11 `case.access`；M01 不在時規劃書照常，只是不能綁定案件，並明說
