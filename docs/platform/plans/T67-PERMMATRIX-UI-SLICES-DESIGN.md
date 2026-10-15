# T67 切片設計：權限矩陣 API＋頁面（design only，無程式）

基底：origin/train/t65-int @4de2ac1f8。來源需求：使用者 2026-10-10／10-13（每模組每動作獨立可設、勾選制、不寫死）。母設計稿：`wip/t54-1d-permmatrix-design`（`docs/platform/plans/PERMISSION-MATRIX-DESIGN-T54.md`，不在本基底，需併入或引用）。

## 0. 現況（靜態讀碼，已驗證）
| 項目 | 現況 | 證據 |
|---|---|---|
| 服務層 | 完整：角色格、個人覆寫、代理、24h 待生效、版本／復原、預覽 | `backend/modules/permmatrix/service.py`（set_role_cap:317、set_user_override:363、create_delegation:529、restore_version:429、undo_last_change:472、preview_*:635-662） |
| 判斷層 | L1 `helpers/perm.py`（can/require/explain/effective_caps）已接提供者 `perm.matrix_source` | `helpers/perm.py:214-281` |
| 端點 | 只有唯讀探針 `GET /api/permmatrix/status` | `modules/permmatrix/api.py:14`、SPEC PMX15 |
| 頁面 | 無；hub 卡片為 `planned`，連到不存在的 `permission-matrix.html` | `backend/core/system_hub_l1.json:79-89` |
| **能力宣告** | **15 個模組的 `module.json` 全部 `capabilities` 數 = 0；後端沒有任何 `perm.require` 呼叫** | 掃描 `modules/*/module.json`；`grep perm.require` 僅命中 system_hub 的讀取 |
| 待生效機制 | `perm_pending`＋`PENDING_HOURS=24` 是 P0 過渡實作；SPEC PMX13：M1 不得接畫面，P1 改走 `config_ledger`＋`change_control.confirm_period_days` | `permmatrix/SPEC.md` PMX13／PMX14 |

**結論：只做 API＋頁面會得到一張空矩陣。** 能力清單來自模組宣告；目前沒有任何單位宣告，所以必須同時做「宣告＋接線＋等價關卡」，否則使用者看不到可勾的格子。

## 1. 切片（建議順序；每片獨立稽核、獨立可回滾）
| 片 | 內容 | 可交付行為 | 估計 |
|---|---|---|---|
| PM-S0 | 待生效改走 `config_ledger`＋確認期間（取代 `perm_pending` 24h 過渡）；放寬＝雙人核准（與設定中心同一把） | 無畫面變更；服務層測試改寫 | M（3–4 人日） |
| PM-S1 | 第一批能力宣告（payroll：勞報單 view/create/submit/approve/pay/export；arap：出納 view/view_money/pay/export），`legacy` DSL 推導種子；`perm.require` 接線到對應端點；等價關卡擴張 | 行為與今天逐位元相同（零行為改變證明） | L（6–8 人日；母稿 P2a） |
| PM-S2 | 端點（見 §2）＋ `permission-matrix.html` 唯讀檢視（有效權限預覽、誰有什麼、為什麼）＋ hub 卡片轉 live | 超管可看，不能改 | M（3–4 人日） |
| PM-S3 | 編輯：角色格勾選、個人允許／禁止、存檔前一句話確認與影響面板、高風險授權待生效、一鍵復原 | 超管可改（先限 PM-S1 已接線的格） | L（5–7 人日） |
| PM-S4 | 代理／兼任（有期限、有範圍），與簽核代理人（`approval-delegates`）統一語意 | 同上 | M（3–4 人日） |
| PM-S5 | 其餘模組逐一宣告＋接線（每模組一片；格子在未接線前標「未接入」，不可勾） | 持續 | 每模組 S–M |

PM 提議的優先序＝PM-S0→S1→S2→S3。S2 可與 S1 並行（頁面讀取登錄表，空格子標「未接入」）。

## 2. API（PM-S2／S3，模組 `permmatrix`，前綴 `/api/permmatrix`；皆 superadmin）
| 端點 | 對應 service | 說明 |
|---|---|---|
| `GET /matrix` | `load_matrix`＋`capabilities.all_caps()` | 角色×能力格（種子／覆寫標示、未接入標示、風險等級、白話文案） |
| `GET /users/{id}/effective` | `perm.effective_caps`／`explain` | 某人的有效權限與每格理由（種子／角色／覆寫／代理） |
| `POST /role-cap/preview`、`POST /role-cap` | `preview_role_cap`／`set_role_cap` | 角色格；必填原因；高風險 → 待生效 |
| `POST /user-override/preview`、`POST /user-override`、`DELETE /user-override` | `preview_user_override`／`set_user_override`／`clear_user_override` | 個人允許／禁止 |
| `GET /pending`、`POST /pending/{id}/cancel`、`POST /pending/{id}/approve` | `list_pending`／`cancel_pending`／（PM-S0 後）`config_ledger.approve` | 待生效清單；任一超管可撤銷；放寬需第二位超管核准 |
| `GET /versions`、`POST /versions/{id}/restore`、`POST /undo` | `list_versions`／`restore_version`／`undo_last_change` | 版本與一鍵復原 |
| `GET/POST/DELETE /delegations` | `list_delegations`／`create_delegation`／`revoke_delegation` | PM-S4 |
寫入端點需列入 write-endpoint EXEMPT／route golden（見 §5）。回應不含個資；稽核由 service 同交易寫入。

## 3. 頁面與入口
- 檔案 `frontend/pages/permission-matrix.html`；入口＝系統中心卡片 `permission-matrix`（`system_hub_l1.json:79`，移除 `planned` 旗標），不新增獨立選單（框架先行：一個設定面）。
- 版面：分頁「角色×能力」「個人覆寫」「待生效」「版本與復原」（代理在 PM-S4）。列＝物件、欄＝動作（`ACTIONS` 19 個詞彙，`capabilities.py:27-31` 的白話標籤）。
- 白話守門：只顯示 `label/desc/impact`，不外露能力鍵；存檔前必須出現一句話影響面板（沿用 `test_settings_ui_plain_language.py` 模式）。
- 與使用者管理／職責角色／組織架構的關係：先只放連結；整併留給 UI 整併案（B6，不在本片）。

## 4. 權限與安全規則
- 全部端點 `require_superadmin`；頁面 `perm=superadmin`。
- 不可委派（永遠只給超管）：權限頁本身、使用者管理、系統設定、備份還原、稅務總帳關帳、資源回收筒還原／清除、授權金鑰（見使用者 10-10 預設）。
- 超管不可被鎖死（服務層已有 `_need_super`；測試加：移除最後一位超管的任何格 ⇒ 拒絕）。
- 高風險動作（`HIGH_RISK_ACTIONS`：view_money／view_sensitive／approve／pay／delete／config）：原因必填、確認期間後生效、期間可撤銷；放寬＝第二位超管核准（與 D-K1 同一條規則；只有一位超管時降級為原因＋確認期間＋警告）。
- 「核准」勾選只代表允許，簽核人仍由簽核流程指定（使用者 10-10 裁示）。
- 身分證字號類（`view_sensitive`）：沿用 P1 前須使用者書面確認的個資裁示；本片不放寬任何個資授權。

## 5. 測試與守門（實作時；本稿不跑）
- `test_perm_equivalence_gate_a.py` 擴張：每個接線端點「矩陣種子 ≡ 今日 legacy 判斷」。
- 新：端點權限矩陣（非超管 403）、最後超管不可鎖死、放寬走待核准、復原一步一步往回、提供者讀不到時沿用最後一次成功矩陣（PMX12）。
- route golden／write-endpoint EXEMPT／L1 快照／`test_map` 重產；`PAGE_POPULATION` +1；`test_module_pages_match_units`（module.json `pages` 補 `permission-matrix.html`，不帶 `menu`——只走 hub 卡片）。
- 棘輪：新程式不得再寫死角色字串（母稿 §守門）。
- 閘門期間不跑 pytest（記憶規則）；測試在 T65 官方閘門結束後。

## 6. 相依
- **F7 欄位政策（`docs/platform/plans/T64-F7-FIELD-POLICY-DESIGN.md`）**：矩陣管「動作」層（誰能對這類單據做什麼）；F7 管「欄位」層（哪個欄位誰看得到／能改）。兩者正交：`view_money`／`view_sensitive` 是動作層總閘，F7 在其下細分到欄位。矩陣的 `view_*` 格必須是 F7 欄位政策的上限（F7 不能授予矩陣沒給的）。PM-S2 前須與 F7 對齊「上限」語意，避免兩處各自判斷。
- **T66 列表偏好（L0–L2）**：個人偏好（每頁筆數）不受權限矩陣管；不相依。列表欄位的隱藏屬 F7／版面引擎，不是權限。
- **設定中心**：待生效／雙人核准共用 `config_ledger`（PM-S0）；`change_control.confirm_period_days` 是同一個確認期間。
- **簽核代理人**（`routers/approval_delegates.py:56`）：目前任何人可為自己設代理，無期限上限、無範圍；PM-S4 統一語意前不動。

## 7. 待使用者／PM 裁示（只列會改變做法的）
1. 第一批接線範圍：母稿預設 payroll＋arap；是否同意？
2. PM-S0（待生效改走 config_ledger）是否列為 PM-S3 的前置？（建議：是，否則 PMX13 被破壞。）
3. 母設計稿在 `wip/t54-1d-permmatrix-design`，需先決定併入 platform 或在 T67 重新引用。

## 8. 不在本片
各模組完整能力宣告（PM-S5）；欄位層權限（F7）；選單可視獨立勾選的 UI（`menu` 動作已在詞彙內，先由 PM-S3 一併呈現，接線隨模組）。
