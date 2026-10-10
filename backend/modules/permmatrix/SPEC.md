# M16 權限矩陣（permmatrix）· 規格條件

> 2026-10-10 建立（權限矩陣框架 P0 里程碑 2；設計 `docs/platform/plans/PERMISSION-MATRIX-DESIGN-T54.md`）。
> 格式同 `modules/filehub/SPEC.md`（`backend/tests/test_spec_coverage_2026_09_21.py` 讀各模組的 `SPEC.md`）。

## 用途與 API

- 矩陣資料與寫入的服務層；沒有端點、沒有頁面（之後的里程碑）。L1 `helpers/perm.py` 經提供者 `perm.matrix_source` 取矩陣。

## 規格條件

- **PMX1.** 預設等價：沒有任何覆寫列、個人覆寫、代理時，`load_matrix(seed)` 回傳的矩陣與種子完全相同；本模組不在或讀取失敗 ⇒ L1 退回種子。
- **PMX2.** 覆寫列只存「與種子不同」的格：把某格改回種子預設就刪列；新模組新增的能力不需要回填矩陣。
- **PMX3.** 所有寫入只有最高管理者（服務層再檢查一次）；superadmin 不能被角色格或個人覆寫影響；不可委派的能力不能被授予（角色格、個人允許、代理皆然）。
- **PMX4.** 禁止優先於所有來源（角色格、模組勾選、個人允許、代理）。
- **PMX5.** 高風險能力（`risk=high`）的**新增授予**（角色格勾選、個人允許、含高風險能力的代理）一律：原因必填（至少 4 個不同的字）、24 小時後才生效、期間任何最高管理者可撤銷；降權、撤銷、回到種子預設、一般能力的授予立即生效。
- **PMX6.** 待生效在**讀取時**判斷並轉為生效（`activate_due`），不依賴排程；轉態用條件式 UPDATE，重複呼叫冪等；生效時委派人／對象已不符 ⇒ 標 `superseded` 並說明，不套用。
- **PMX7.** 每次即時生效的矩陣變更都寫一筆版本快照；回溯＝與目前的差異逐項走一般寫入路徑（新增高風險授予仍要 24 小時），歷史不改。
- **PMX8.** 稽核（`audit_log`）與資料變更同一個交易；通知在 commit 之後送（申請、撤銷、生效）。
- **PMX9.** 代理：範圍限能力清單或單據類型；委派人必須自己目前就有該能力（不能憑代理升權）；不可再轉代理；範圍含高風險能力 ⇒ 只有最高管理者能建並走 PMX5；非風險範圍 ⇒ 委派人本人（政策 `selfDelegateNonRisky`，預設＝今天任何登入者可替自己建簽核代理）或最高管理者，立即生效；委派人本人或最高管理者可隨時撤銷。

## 非目標

- 本里程碑不含端點與頁面、不遷移任何既有端點、不併入既有 `approval_delegates`（`scope_kind=approval_slot` 欄位已預留）。

## 測試

- `backend/modules/permmatrix/tests/test_permmatrix_m2.py`、`backend/tests/platform/test_perm_equivalence_gate_a.py`。
