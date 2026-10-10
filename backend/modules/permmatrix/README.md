# 權限矩陣（permmatrix）

「誰可以做哪件事」變成勾選：角色格、個人允許／禁止、代理（可限範圍與期間）、高風險授權 24 小時後生效。判斷在 L1 `helpers/perm.py`，**本模組只負責矩陣的資料與寫入**。
使用者核心規則（2026-10-10）：框架先行、預設值由今天的行為推導、其餘全由最高管理者在頁面決定，不寫死任何角色名單。

## 功能（里程碑 2）
- 五張表：`perm_role_caps`（覆寫列；沒有列＝種子）、`perm_user_overrides`、`perm_versions`、`perm_pending`、`perm_delegations`。
- 提供者 `perm.matrix_source`：L1 的 `perm.can()` 從這裡取得「種子 ⊕ 覆寫」＋有效代理；本模組不在 ⇒ L1 用種子（＝今天的行為）。
- 服務層（`service.py`）：角色格／個人覆寫／代理的寫入、高風險授予的 24 小時待生效（可撤銷）、版本與回溯、稽核與通知。
- 端點與「系統 > 權限設定」頁在後續里程碑；目前沒有任何端點使用 `perm.require`（各模組遷移照設計稿 §5 的順序）。

## 資料分類
五張表皆 T1，不含個資原文。

## 串接點
- IP-PM1 `perm.matrix_source`（本模組 → L1 `helpers/perm.py`；單一提供者）。簽名：`fn(seed: Matrix) -> Matrix`。
- 對方不在：本模組不在或讀取失敗 ⇒ L1 退回種子並記 log（不多給、不少給）。

## 開發者
- 規格條件見 `SPEC.md`（PMX1…）；等價關卡 `backend/tests/platform/test_perm_equivalence_gate_a.py`、模組測試 `backend/modules/permmatrix/tests/`。
