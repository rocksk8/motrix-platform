# 權限矩陣 更新紀錄

## (next) — 2026-11-14（feat/t86-b1-h2；T86 文字：中性正式用語與覆核修正）
- 文字（行為不變）：影響預覽回傳的 `reversibleText` 與批次說明由「一鍵復原」改為「復原」（稽核原因值 `UNDO_REASON` 不動）；同步更新斷言。

## (next:minor) — 2026-11-14（feat/settings-matrix-s4；T86 設定矩陣 S4c：角色格暫存區批次；含文字準則修正）
- 新增 API：`POST /api/permmatrix/role-cap/batch/preview`（唯讀：每格現況與去向、哪些要等待期並經核准、要不要原因、`planHash`）、`POST /api/permmatrix/role-cap/batch`（整批同一個寫入交易、`planHash` 過期 ⇒ 409；立即生效的格合併成一個版本，「一鍵復原上一次調整」整批還原；放寬高風險格各自進待生效；每格各一筆稽核、與資料同交易）。單格 `/role-cap` 與 `/role-cap/preview` 不變。
- 前端（`permission-matrix.html`）：點格子改為「暫存」（待套用標記、暫存列、每組每角色「全勾／全清」），按「預覽並套用」看完整影響再儲存；離開頁面前若有未套用的暫存，瀏覽器會先詢問。畫面用詞「確認期間」改為「等待期」，提示文字依文字準則改用「您」「尚未」；暫存列在手機寬度貼在頂欄下方。
- 測試：`tests/test_permmatrix_s3_writes.py`（批次：預覽唯讀、過期 409、原因規則、整批復原、輸入驗證）、`tests/test_e2e_permission_matrix_staging_2026_11_14.py`。金標：`write_golden_cases/cases_permmatrix.py`、`route_inventory.json`、`route_table_golden.json`。

## 1.1.5 — 2026-11-14（train/t85-text；T85 文字專業化；版號由列車取）
- 文字（行為、API、欄位、設定鍵、錯誤碼不變）：畫面、通知、錯誤提示與說明文字改為正式、一致的用語（您、尚未／尚無、是否、其他使用者、無法／不可等），標點與中英文間距依 `docs/platform/plans/TEXT-STYLE-GUIDE.md`；同一提交同步更新斷言字串的測試。逐項前後對照見 `docs/platform/plans/TEXT-DIFF-TABLE.md`。

## 1.1.4 — 2026-11-13（fix/loosen-demo-count-h11；展示帳號不算第二位最高管理者）
- 變更（內部，不影響對外介面）：`service._superadmins()` 改用 `config_ledger.real_superadmins()`（不含展示帳號 demo）：放寬類授權變更「要不要第二位核准」與生效通知名單只看真人最高管理者；只有一位真人時改走「原因＋確認期間＋警告」。
- 測試：`tests/test_loosening_demo_not_second_approver_2026_11_13.py`（守門）。

## 1.1.3 — 2026-11-13（feat/ux-p15-dashboard；UX P1.5）
- 前端（文字）：頁面 `<title>` 後綴「專案管理系統」一律改為「MOTRIX PLATFORM」（系統標語改由公司設定 `brand.tagline` 決定，預設 MOTRIX PLATFORM）；不動 API／資料／權限。

## 1.1.2（next，未取號）— 2026-11-13（ui/mobile-tablet-combined 的改動；條目由 fix/mobile-cases-layout-v2 補，依各頁 git 歷史照實記錄；僅前端版面，不動 API／資料／權限判斷）
- `permission-matrix.html`：平板／手機觸控——勾選框 22px、整格可點；手機彈窗改貼底全寬（高度依字級縮放換算）。桌機版不變。

## 1.1.1 — 2026-11-11（feat/ux-navigation-hierarchy；UX 提案批次 1+2「導覽與資訊架構＋視覺層級」；不動 API／資料／權限判斷；L1 介面不變）
- 前端視覺（D3）：本模組頁面內文字最小 12px（原有 9～11px 一律拉到 12px）；文字色改用語意 token（`--text-secondary` #595959／`--text-dim` #666666／深底 `--text-on-dark-dim` #A3A3A3，在頁底 #F5F4F0 上對比 ≥4.5:1）。只改 CSS 值，不改版面結構、不改 API、資料、權限。規格見 `docs/UI-HEADER-COLOR-SPEC.md`。
- 測試：`tests/test_e2e_nav_hierarchy_2026_11_11.py`（7 項真瀏覽器：每個舊入口仍可達、群組與報表中心頁籤、權限過濾、頁頭麵包屑）。

## 1.1.0 — 2026-10-16（train/t67-int；T67 PM-S2／PM-S3）
- 新增『權限設定』頁（`permission-matrix.html`，只走系統中心卡片，不新增選單）與端點：唯讀檢視 `GET /api/permmatrix/matrix｜users｜users/{id}/effective｜pending｜versions｜delegations`（PM-S2）；寫入 `POST /role-cap`＋`/role-cap/preview`、`POST /user-override`＋`/user-override/preview`、`DELETE /user-override`、`POST /pending/{id}/cancel｜approve`、`POST /versions/{id}/restore`、`POST /undo`（PM-S3）。全部限最高管理者；規則仍全在服務層（原因必填、高風險放寬走設定帳本確認期間＋第二位最高管理者核准、稽核同交易）。
- 格子內容全部來自各模組的能力宣告（`views.py` 唯讀檢視）：沒有宣告就是空表；『未接入』的格子不可勾。存檔前一定先顯示一句話影響面板。
- 守門：`test_permmatrix_writes_unwired.py` 改為『其他產品碼不得取用 service；api.py／views.py 是模組自己的檔案』＋完整路由清單＋每個寫入端點第一行必須是最高管理者檢查；SPEC 新增 PMX16／PMX17。金標案例 `cases_permmatrix.py`（錯誤形狀）。
- 守門修正（預檢）：端點本體直接呼叫 `_require_user(authorization, require_superadmin=True)`（取代 `_su()` 包裝，讓 system_audit 掃描認得）；個人覆寫刪除端點登記進刪除暫存區基線 exempt。
- 沒有 schema 變更、沒有 migration。

## 1.0.4 — 2026-10-16（wip/t67-pms0-r1；T67 PM-S0）
- 待生效改走設定帳本（`config_ledger`，domain `perm:*`）：確認期間＝設定中心 `change_control.confirm_period_days`（預設 7 天、下限 1 天），取代 P0 的 24 小時 `perm_pending`；放寬（高風險授予、取消高風險個人禁止、高風險代理）另需**第二位最高管理者核准**（`approve_pending`；只有申請人一位最高管理者 ⇒ 不需核票、回警告）。
- 服務層：`list_pending` 讀帳本；`cancel_pending` 任一最高管理者；新增 `approve_pending`；`activate_due` 只轉『確認期間已過且票數足夠』者，逐筆 SAVEPOINT，出錯的那筆撤銷並稽核；同一目標再申請取代舊的待生效項；預覽句子改為確認期間＋核准說明（L1 `perm_text` 不動，服務層換句）。
- `perm_pending` 表保留、不再讀寫（沒有 schema 變更）；寫入函式仍未接任何端點／頁面（PMX14，守門 `test_permmatrix_writes_unwired.py` 納入 `approve_pending`），接線在 PM-S2／S3。

## 1.0.3 — 2026-10-13（wip/t57-u0a-core-r1；U0a 組織單位預留）
- 新增模組 migration v2：`perm_role_caps`、`perm_user_overrides` 各加可為空的 `scope_json TEXT`（NULL＝全部＝今天的行為；共 2 欄）。只加欄位、冪等；沒有任何程式讀寫它（授權帶範圍屬 U1）。

## 1.0.2 — 2026-10-12（wip/t57-permmatrix-probe-r1）
- 新增唯讀狀態探針 `GET /api/permmatrix/status`（登入即可；只回 `{"ok": true}`（無字串值，符合 probe「回應值不進 log」規則），不讀 `perm_*` 表、不改任何權限判斷），`module.json` 宣告 `provides.api_prefixes`／`probes`，補 D7 final_drill 的「沒有宣告 provides.probes」。寫入端點與頁面仍未接線（SPEC PMX14）。

## 1.0.1 — 2026-10-10（wip/t50-int；第 50 班）
- 白話預覽（影響面板：摘要、影響、人數、適用範圍、可否復原、何時生效、風險提示）與一鍵復原；文字由 L1 `helpers/perm_text.py` 產生（畫面無代碼、無代名詞）。
- **（併入）(next) — 2026-10-11（wip/t54-1d-permmatrix-p0-r3；05 稽核 A／B／C 修正）**
- `load_matrix` 改為純讀取（不再呼叫 `activate_due`）；到期待生效由 `kick_activation()` 背景轉態（單一飛行、不阻塞權限檢查）。
- `activate_due`：套用前確認申請人仍是在職最高管理者，否則標 `superseded` 並稽核（不以已降級／停用帳號的名義套用）。
- `perm_pending`／24 小時仍是過渡實作，M1 不接端點或畫面（見 SPEC PMX13）。
- `kick_activation`：執行緒起不來時放掉鎖並回 None（05 複驗備註；有測試）。
- r6：提供者 `perm.can`（IP-PM2，值＝L1 `helpers.perm.can`，給系統中心）；`perm.invalidate()` 會通知所有 `perm.changed` 提供者（IP-PM3；只涵蓋本程序，跨程序靠 P1 `config_epoch`）。
- r7：`perm.invalidate()` 會通知所有 `perm.changed` 提供者（系統中心登記，整合點見其 IP-HUB1；只涵蓋本程序，跨程序靠 P1 `config_epoch`）。系統中心直接呼叫 `helpers.perm.can`，不需 `perm.can` 提供者。
- **（併入）(next) — 2026-10-11（wip/t54-1d-permmatrix-p0-r8；05 稽核 A／B／C 修正＋perm.changed 通知）**
- **（併入）(next) — 2026-10-11（wip/t54-1d-permmatrix-p0-r9；05 稽核 A／B／C 修正＋perm.changed 通知）**
- **（併入）(next) — 2026-10-11（wip/t54-1d-permmatrix-p0-r10；05 稽核 A／B／C 修正＋perm.changed 通知）**
- r10（05 稽核 B）：放寬一律不立即——勾回「種子本來就有、後來被取消」的高風險格子、取消高風險能力的個人禁止，都改走 24 小時待生效（需原因）；到期套用回種子預設時刪覆寫列。新增守門 `test_permmatrix_writes_unwired.py`：帳本接上前不得有端點／頁面／其他程式呼叫 P0 寫入函式（SPEC PMX14）。
- **（併入）(next) — 2026-10-11（wip/t54-1d-permmatrix-p0-r11；05 稽核 A／B／C 修正＋perm.changed 通知）**
- r11：未接線守門補洞——字串常數（含 `a`+`b` 折疊）、`modules.permmatrix.service` 的匯入／字串／屬性鏈（堵 getattr／importlib／globals 寫法），正對照列出 12 種寫法。

## 1.0.0 — 2026-10-10（wip/t54-1d-permmatrix-p0）：里程碑 2——矩陣資料表、提供者、服務層（覆寫／代理／24 小時待生效／版本回溯）
- 新模組 `permmatrix`（M16）。表 `perm_role_caps`／`perm_user_overrides`／`perm_versions`／`perm_pending`／`perm_delegations`（皆 T1；沒有 core schema 版本升級）。
- 提供者 `perm.matrix_source`（IP-PM1）：L1 `helpers/perm.py` 取「種子 ⊕ 覆寫」＋有效代理；模組不在或讀取失敗 ⇒ L1 用種子（＝今天的行為）。
- 服務層：角色格／個人覆寫／代理的寫入、高風險授予 24 小時待生效（讀取時判斷、可撤銷）、版本與回溯、稽核同交易、通知 commit 後。尚無端點與頁面。
