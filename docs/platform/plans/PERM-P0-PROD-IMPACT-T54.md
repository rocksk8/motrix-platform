# 權限矩陣 P0（M16 `permmatrix`＋L1 `helpers/perm.py`）：上正式機實際會改變什麼（T54 步驟檔用）

> 取代先前的「代理統一步驟檔」草稿（該草稿的前提已過時，已撤回）。2026-10-11 依 05 稽核更正，依據 `origin/platform` c14f0a1df 與 perm r9／r10 的實際程式。

## 0. 更正：過期代理缺陷**不在本次內容**
- 平台上四個讀取點**已經**檢查日期區間：`payroll/api/payslip_approval.py:60-61`、`:98`、`payroll/api/bonus.py:1296-97`、`payroll/bonus_payouts.py:117-118`（`start_date<=今天<=end_date`），`tiered_approval.active_delegators_for` 同。先前草稿說「三處不看日期」是讀了過時的版本。
- perm r9／r10 **沒有任何代理統一程式**（`approval_delegates` 沒被動到）。因此步驟檔**不得**寫「已過期代理不再生效／行為變更」。
- 舊草稿的 SQL 也不可用：勞報單簽核中的真實狀態是 `待審核`（`payslip_approval.py:35`），不是 `簽核中`，查詢恆為空＝假的「安全」。已撤回，不再提供。
- 代理統一（`active_delegates_of`、旗標 `perm_delegation_source`、關卡 D）仍是 P1 設計項目，上線時才另寫步驟檔，並以當時的程式為準重新核對。

## 1. 正式機看得到的變化（M2 範圍：perm P0＋系統中心能力過濾）
1. **新模組 `permmatrix`（M16）**：migration 0001 建 5 張表（`perm_role_caps`、`perm_user_overrides`、`perm_versions`、`perm_pending`、`perm_delegations`），**全空**。沒有端點、沒有頁面（`MODULE.routers == []`，有守門）。
2. **L1 `helpers/perm.py`**：新增中央檢查 `can()` 等；**目前沒有任何既有端點呼叫它**。目錄（能力登錄）在 M2 內尚無模組宣告 `capabilities`，所以對真實帳號沒有可被判斷的能力鍵。
3. **系統中心**：卡片有 `cap` 才會用 `perm.can` 過濾；M2 內沒有卡片宣告 `cap`（以 b5 的卡片清單為準，請 b5 確認）⇒ 可見性仍走舊的 `perm`（模組勾選）語意。
4. **`perm.changed` 通知**：`perm.invalidate()` 會呼叫系統中心的清快取；只在權限寫入時才觸發，而 M2 沒有任何寫入入口 ⇒ 實際不會觸發。
5. **結論：使用者可見的行為變更＝無。**

## 2. 「無矩陣資料時等價於舊規則」的證據
- 關卡 A `backend/tests/platform/test_perm_equivalence_gate_a.py`：窮舉六個角色 × 模組勾選形狀，`perm.can()` 與今天判斷式（測試內逐字副本）逐一相同。**限制：用的是合成目錄**（因為真實目錄在 M2 為空）；真實能力一旦宣告，P1 要加「真實目錄種子 baseline」守門（`perm_seed_baseline.json`）。
- `test_permmatrix_m2.py::test_empty_tables_give_exactly_the_seed…`：資料表為空 ⇒ 矩陣＝種子；提供者失敗 ⇒ 沿用最後一次成功或種子（高風險 fail-closed）。

## 3. 正式機預檢／驗證
- **上線前預檢 SQL：不需要**（沒有資料或行為被改動）。
- **上線後唯讀驗證（`mode=ro`）**：`SELECT name FROM sqlite_master WHERE name LIKE 'perm_%'` 應回 5 張；各表 `SELECT COUNT(*)` 皆為 0；`module_schema_versions` 的 `permmatrix` ＝ 1。
- 工作日誌／案件管理預檢（T50 p4p5）不屬本次：它已在第 50 班步驟檔步驟 0 #4b（`20261010-train50-apply.md`）隨 p4p5 上線，p4p5 已併入 platform（9064be05c）。

## 4. P0 寫入函式是過渡實作，M2 內不接任何入口
- 放寬高風險能力現為單人 24 小時待生效（`perm_pending`），**不是**使用者規則（第二位最高管理者核准＋確認期）。該規則走設定帳本（Train A）。
- 帳本接上前，`set_role_cap`／`set_user_override`／`clear_user_override`／`create_delegation`／`revoke_delegation`／`restore_version`／`undo_last_change`／`cancel_pending`／`activate_due` 不得被呼叫；守門 `test_permmatrix_writes_unwired.py` 會擋（含正對照）。見 SPEC PMX14。
