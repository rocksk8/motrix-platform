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
- **PMX5.** 高風險能力（`risk=high`）的**新增授予**（角色格勾選、個人允許、含高風險能力的代理）一律：原因必填（至少 4 個不同的字）、寫設定帳本（`config_ledger`，domain `perm:<kind>`）待生效明細——**確認期間**（與設定中心同一把 `change_control.confirm_period_days`，預設 7 天、下限 1 天）後才生效、期間任何最高管理者可撤銷、且需**另一位**最高管理者核准（雙人核准；只有申請人一位最高管理者 ⇒ 不需核票，改為原因＋確認期間＋警告）；降權、撤銷、回到種子預設、一般能力的授予立即生效。
- **PMX6.** 待生效由背景轉態（`kick_activation`：單一飛行、拿不到鎖就略過；`load_matrix` 本身**純讀取、不寫庫**，05 稽核 B）轉為生效（`activate_due`）；只轉『確認期間已過**且**核准票數足夠』的項目（帳本 `in_effect`）；到期套用前再確認申請人仍是在職最高管理者，否則標 `superseded`（05 稽核 C）；逐筆 SAVEPOINT：套用出錯的那筆撤銷並稽核，不影響其他筆；重複呼叫冪等；生效時委派人／對象已不符 ⇒ 標 `superseded` 並說明，不套用。同一目標（同格、同人同能力、同委派對）再次申請 ⇒ 舊的待生效項標 `superseded`。
- **PMX7.** 每次即時生效的矩陣變更都寫一筆版本快照；回溯＝與目前的差異逐項走一般寫入路徑（新增高風險授予仍要確認期間與核准），歷史不改。
- **PMX8.** 稽核（`audit_log`）與資料變更同一個交易；通知在 commit 之後送（申請、撤銷、生效）。
- **PMX9.** 代理：範圍限能力清單或單據類型；委派人必須自己目前就有該能力（不能憑代理升權）；不可再轉代理；範圍含高風險能力 ⇒ 只有最高管理者能建並走 PMX5；非風險範圍 ⇒ 委派人本人（政策 `selfDelegateNonRisky`，預設＝今天任何登入者可替自己建簽核代理）或最高管理者，立即生效；委派人本人或最高管理者可隨時撤銷。
- **PMX10.** 白話預覽（存檔前的影響面板）：`preview_role_cap`／`preview_user_override`／`preview_delegation` 回傳『一句話摘要、勾選後會影響什麼（宣告時寫的中文影響說明）、影響幾位使用者、適用範圍（之後的操作；已完成的單據與簽核不受影響）、可否復原、何時生效（立即／24 小時後）、白話風險提示』；內容只有中文句子，不露出能力鍵、`allow`／`deny` 或 id。單據數等影響計算（`perm.impact` 提供者）P0 先不接，P1 第一個單位需要時再登記。
- **PMX11.** 一鍵復原：`undo_last_change` 每按一次往回一步（復原本身產生的版本不算一步，不會來回跳）；走一般寫入規則（新增高風險授予仍要確認期間與核准）；已是最早狀態 ⇒ 錯誤。

## 非目標

- 本里程碑不含端點與頁面、不遷移任何既有端點、不併入既有 `approval_delegates`（`scope_kind=approval_slot` 欄位已預留）。

## 測試

- `backend/modules/permmatrix/tests/test_permmatrix_m2.py`、`backend/tests/platform/test_perm_equivalence_gate_a.py`。

- **PMX12.** 提供者讀不到時，`helpers.perm` 沿用**最後一次成功載入的矩陣**（保留個人禁止／角色格取消），不退回種子；從未載入成功過才用種子並進入降級——降級時高風險能力對非最高管理者一律拒絕、恢復後自動離開（05 稽核 A）。
- **PMX14.** 放寬的判斷：任何**放寬高風險能力**都走帳本待生效（PMX5：確認期間＋雙人核准）、必填原因，包含：新增角色授予、把種子預設後來被取消的格子勾回來、個人允許、**取消高風險能力的個人禁止**、高風險範圍的代理。收緊與低風險放寬立即。待生效的服務函式：`list_pending`／`cancel_pending`（任一最高管理者，需原因）／`approve_pending`（一票；申請人不能核准自己的、同人不能重複投票）／`activate_due`。**寫入函式（`set_role_cap`／`set_user_override`／`clear_user_override`／`create_delegation`／`revoke_delegation`／`restore_version`／`undo_last_change`／`cancel_pending`／`approve_pending`／`activate_due`／`kick_activation`）仍不得被任何端點、頁面或其他程式呼叫**——端點與頁面屬 PM-S2／S3（T67 設計），接線時同一個 commit 改守門 `test_permmatrix_writes_unwired.py`（掃 `source_tree.product_files()`：匯入、屬性、名稱、字串常數含 `a`+`b` 相加、`modules.permmatrix.service` 的匯入與屬性鏈；**不含 backend/tools 與各層 tests**，且只防不小心、不防刻意規避）。另：「沒有任何程式呼叫 `perm.can`」只對 r10＋系統中心成立，其他分支合併後需重新 grep（整合者在合併樹上做）。
- **PMX13.** （T67 PM-S0 取代原 P0 過渡實作）待生效資料在 `config_changes`／`config_change_events`（只增不改不刪），不再寫 `perm_pending`：該表保留（沒有 schema 變更、無程式讀寫，P0 期間沒有任何端點接線，正式機無資料），待後續清理班才移除。一筆待生效＝一列帳本明細：domain `perm:role_cap`／`perm:user_override`／`perm:user_override_clear`／`perm:delegation`，key＝目標（`角色:能力`、`使用者id:能力`、`委派人>代理人`），欄位＝kind，`new`＝套用所需的完整內容；風險等級 `security`（帳本同交易通知其他最高管理者，連結 `permission-matrix.html`）。

- **PMX15.** （1.0.2）唯一端點為唯讀狀態探針 `GET /api/permmatrix/status`（登入即可，只回 `{"ok": true}`，不讀 `perm_*` 表）；供 D7 final_drill 的 `provides.probes`。寫入端點仍未接線（PMX14）。
- **PMX16.** （T67 PM-S2）唯讀檢視端點，全部限最高管理者（非最高管理者 403）、純讀取（不寫任何表、不寫稽核）：`GET /api/permmatrix/matrix`（角色×能力格：種子／已調整／未接入旗標，能力清單只來自模組宣告，沒宣告＝空表而非錯誤）、`/users`（個人覆寫人選與現有覆寫；不含最高管理者）、`/users/{id}/effective`（有效權限與白話理由）、`/pending`、`/versions`、`/delegations`。端點層 `api.py` 與唯讀檢視 `views.py` 是除宣告檔外唯一可取用 service 的檔案（守門 `test_permmatrix_writes_unwired.py` 的 `OWN_PACKAGE`；`views.py` 另有「不得出現寫入函式名」守門）。頁面 `frontend/pages/permission-matrix.html` 只走系統中心卡片（module.json `pages` 不帶 `menu`），畫面不顯示能力代碼。
- **PMX17.** （T67 PM-S3）寫入端點，全部最高管理者限定：`POST /role-cap`＋`/role-cap/preview`、`POST /user-override`＋`/user-override/preview`、`DELETE /user-override?user_id&cap&reason`、`POST /pending/{id}/cancel`、`/pending/{id}/approve`、`POST /versions/{id}/restore`、`POST /undo`。端點只驗證輸入（嚴格布林／整數）後呼叫服務層，規則全在服務層（PMX5／PMX14：高風險放寬＝原因必填＋確認期間＋第二位最高管理者核准；稽核與資料同交易；最高管理者不在矩陣內、不可被個人覆寫，故不可能被鎖死）。存檔前一律先呼叫 preview，畫面顯示一句話影響面板（句子、影響、人數、何時生效、風險）才送出；預覽與句子不含能力鍵。頁面只開放『已接入』（`wired`）的格子與可委派的能力。代理（delegations）的寫入端點屬 PM-S4，本版沒有。金標案例 `tests/platform/write_golden_cases/cases_permmatrix.py` 記錄錯誤形狀（正式庫無宣告）；成功形狀由 `test_permmatrix_s3_writes.py` 以宣告過的能力斷言。
