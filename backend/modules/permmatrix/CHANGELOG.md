# 權限矩陣 更新紀錄

## 1.0.0 — 2026-10-10（wip/t54-1d-permmatrix-p0）：里程碑 2——矩陣資料表、提供者、服務層（覆寫／代理／24 小時待生效／版本回溯）
- 新模組 `permmatrix`（M16）。表 `perm_role_caps`／`perm_user_overrides`／`perm_versions`／`perm_pending`／`perm_delegations`（皆 T1；沒有 core schema 版本升級）。
- 提供者 `perm.matrix_source`（IP-PM1）：L1 `helpers/perm.py` 取「種子 ⊕ 覆寫」＋有效代理；模組不在或讀取失敗 ⇒ L1 用種子（＝今天的行為）。
- 服務層：角色格／個人覆寫／代理的寫入、高風險授予 24 小時待生效（讀取時判斷、可撤銷）、版本與回溯、稽核同交易、通知 commit 後。尚無端點與頁面。
