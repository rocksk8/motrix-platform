# 權限矩陣（勾選制）設計稿 — 第 54 班

> 作者 1d（獨立設計，唯讀；基準 origin/platform `b2486535c`）。**只有設計，沒有程式。** 使用者原話：「權限的部分跟哪一個權限可以送出、填寫的，變成一個獨立頁面，勾選就能放行或是修改，未來也不用單獨寫程式微調……財務我勾選勞報單，他也可以送出審核；某個管理員可以有財務查看，但不能修改……不寫死在系統內，保留彈性跟確認稽核」。
> 數字用簡單的原始碼掃描（正規表示式，±10%），目的是量級，不是稽核報告。

## 1 現況盤點：權限今天怎麼決定

**六道判斷，彼此獨立、各寫各的：**
1. **模組勾選**：`users.modules`（30 個模組鍵，`helpers/module_registry.py`）＋角色樣板 `ROLE_TEMPLATES`（建帳號時預帶）。後端 `require_any_module(user, keys)`／`user_has_module`；**只有 superadmin 直通，admin 也要勾**（2026-09-14 裁示）。粒度＝整個模組，**沒有「檢視／編輯／送出」之分**（唯一例外 `netplan` 與 `netplan_edit` 兩個鍵）。
2. **角色字串寫死在端點**：`user["role"] in ("admin","superadmin")`、`_require_admin()`、`require_superadmin=True`／`_sa()`。六種角色 `superadmin/admin/sales/engineer/viewer/finance`（`VALID_ROLES`）。
3. **財務三鍵由角色推導**（第 42 班）：`cashier/finance/financial_view` 不看勾選，只有 finance 角色與 superadmin；`has_finance_access`／`has_cashier_access`／`can_see_financial`／`finance_duty_person` 是縫，R2 step1 加了旗標 `finance_via_effective`（off／shadow／on）把它們改讀生效權限。**「財務查看」與「財務編輯」今天是同一個閘（`has_finance_access`）**，無法分開給人。
4. **職責角色 R1/R2**（`helpers/duty_roles.py`）：生效模組＝（`users.modules` ∪ 綁定的職責角色權限）− 個人扣項；單一縫 `effective_modules`；`permission_changes` 只增不改（DB 觸發器）、高敏感變更必填原因、`effective_preview`／`preview_whatif`、`duty_roles_equivalence` 上線關卡、`users.html` 編輯視窗。**但它的單位仍是 30 個模組鍵，只能整模組給或扣。**
5. **簽核層級**（`helpers/tiered_approval.py`）：每張單據的 tiers 由「簽核流程設定」逐一挑人（或部門主管展開）；`check_approve_permission`、`is_document_approver`。這是「這張單輪到誰」，**不是角色權限**。
6. **每案資料範圍**：`guard_case_access`／`row_access.OwnerRule`／`require_case(_money)`：擁有者、成員、被指派、cashier 讀全部。這是「哪些列」，**不是動作權限**。另有 `bank_mask`（只有 superadmin 看完整帳號）、`financial_mask`（沒有 `can_see_financial` 就從回應拿掉金額）。

**寫死點規模**（後端產品碼；欄：路由數／角色字面值／`_require_admin`／superadmin 閘／財務閘／模組閘／案件守門／簽核判斷）

| 單位 | 路由 | 角色 | admin | super | 財務 | 模組 | 案件 | 簽核 |
|---|---|---|---|---|---|---|---|---|
| case（M01） | 156 | 45 | 10 | 3 | 36 | 8 | 40 | 50 |
| routers（舊 legacy：使用者、設定、系統…） | 235 | 27 | 2 | 106 | 4 | 27 | 2 | 6 |
| subcontract | 74 | 25 | 16 | 13 | 14 | 32 | 5 | 15 |
| payroll | 75 | 20 | 0 | 52 | 6 | 11 | 0 | 8 |
| arap | 40 | 4 | 13 | 0 | 21 | 7 | 6 | 17 |
| accounting | 89 | 27 | 0 | 7 | 2 | 20 | 0 | 3 |
| supply | 38 | 6 | 16 | 0 | 1 | 21 | 6 | 7 |
| helpers（共用閘本身） | 0 | 30 | 0 | 1 | 17 | 11 | 5 | 22 |
| 其他 8 個單位 | 89 | 24 | 0 | 7 | 5 | 22 | 0 | 1 |
| **合計** | **796** | **208** | **57** | **189** | **106** | **159** | **64** | **129** |

前端另有約 150 處 `role === '…'`／`includes(session.role)`（40 個檔案）決定按鈕顯示——**畫面與後端各一套**，這是第二個漂移來源。

**各模組實際存在的動作類別**（由路由名稱＋閘推得；`✓`＝有此類端點）

| 模組 | 檢視 | 檢視金額 | 建立/填寫 | 修改 | 送出 | 核准/退回 | 付款 | 刪除 | 匯出/列印 | 作廢/鎖定 |
|---|---|---|---|---|---|---|---|---|---|---|
| case（報價/案件/額外費用/完工/出貨前置） | ✓ | ✓(`financial_view`) | ✓ | ✓ | ✓ | ✓ 19 | ✓ 16（收款） | ✓ 17 | ✓ 8 | ✓ 9 |
| arap（請款/開票憑據/出納） | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ 6 | ✓ 26 | ✓ 3 | ✓ 5 | ✓ |
| subcontract（派發/匯款申請/承攬商） | ✓ | ✓(帳號僅 super) | ✓ | ✓ | ✓ | ✓ 13 | ✓ 10 | ✓ 6 | ✓ 3 | ✓ |
| payroll（勞報單/獎金） | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ 8 | ✓ 28 | ✓ 4 | ✓ 3 | ✓ |
| accounting（傳票/總帳/稅務） | ✓ | 本質即金額 | ✓ | ✓ | ✓ | ✓ 3 | — | ✓ 3 | ✓ 10 | ✓ 5 |
| supply（採購/庫存/出貨單/網路規劃） | ✓ | ✓(成本) | ✓ | ✓ | ✓ | ✓ 3 | — | ✓ 4 | ✓ 3 | ✓ |
| crm/daily_tasks/netplan/lodging/tender_radar/analytics | ✓ | analytics 有 | ✓ | ✓ | — | 少 | — | ✓ | ✓ | — |
| 系統（使用者、設定、稽核、版本、檔案中心） | ✓ | — | ✓ | ✓ | — | — | — | ✓ | ✓ | — |

結論：**九種動作（檢視／檢視金額／填寫／修改／送出／核准／付款／刪除／匯出）幾乎每個大模組都有，但今天只有「模組有沒有勾」與「角色字串」兩把鑰匙**，所以「財務可送出勞報單」或「某管理員能看財務但不能改」都需要改程式。

## 2 模型：能力登錄＋矩陣＋覆寫

**能力（capability）**＝`<單位>.<物件>.<動作>`，例：`payroll.payslip.submit`、`finance.receivable.view_money`、`case.quotation.delete`。
- **動作詞彙固定**（避免各模組自創）：`view`、`view_money`、`create`、`edit`、`submit`、`approve`、`pay`、`delete`、`export`、`void`（單位可再宣告專屬動作，但須有 `risk`）。
- **登錄**：各模組在 `module.json` 新增 `capabilities: [{key, label, risk: low|mid|high, legacy: "<舊判斷式描述>", implies: […]}]`（**加法、L1 契約 `core/capabilities.py`**，載入時彙整；模組缺席＝能力不存在，畫面不列）。新模組／新端點自己宣告，**不必改權限頁或權限程式**。
- **舊模組鍵相容**：30 個模組鍵保留，視為「粗粒度別名」＝該模組全部能力的預設集合（`implied_by_module_key`）。`users.modules` 與職責角色**不改格式**。

**矩陣（誰有哪些能力）**，生效集合＝
`（基礎角色格 ∪ 模組鍵展開 ∪ 職責角色格 ∪ 個人「允許」）− 個人「禁止」`，**禁止優先於允許**。
- 新表（皆模組 migration、只增）：`perm_role_caps(role_or_duty_key, cap, granted)`、`perm_user_overrides(user_id, cap, effect allow|deny, reason)`、`perm_versions(id, snapshot_json, created_by, reason, created_at)`；變更寫既有 `permission_changes`（只增不改）。
- **重用 R2，不重做**：職責角色就是矩陣的「欄」（`duty_roles.permissions` 從模組鍵擴充為「模組鍵或能力鍵」）；個人扣項 `user_perm_subtracts` 併入 `perm_user_overrides(effect=deny)`；`effective_preview`／`preview_whatif`／`permission_changes`／高敏感原因規則直接沿用。
- 「財務可送出勞報單」＝在 finance 欄勾 `payroll.payslip.submit`；「某管理員財務只看」＝個人允許 `finance.*.view`、`finance.*.view_money`，不給 `edit/pay`。

**中央檢查 API（取代寫死角色字串）**：`perm.can(user, cap) -> bool`、`perm.require(user, cap)`（403，訊息含缺哪個能力＝可稽核）。每請求只算一次生效集合（記憶體＋矩陣版本號失效），登入 payload 帶 `caps` 給前端，**前端 `can('…')` 取代 `role ===`，後端仍是唯一權威**。既有 `has_finance_access`／`require_any_module`／`user_has_module`／`_require_admin` 改成 `can()` 的薄包裝（行為不變），端點逐步直接改用 `require(cap)`。

**不變式**
- **superadmin 永遠通過且不可被鎖死**：`can()` 第一行直通；矩陣不存 superadmin 列、API 拒絕對它設禁止（與 R1 一致）。權限頁本身（`system.permissions.manage`）預設不可委派（問題 4），所以任何勾選錯誤都不可能讓 superadmin 進不了權限頁；另附伺服器端離線工具 `perm_reset --to-seed`（把矩陣與覆寫重設為種子並寫稽核），供誤設後急救。
- **不管範圍與序**：每案守門（`guard_case_access`）與簽核層級**照舊且必須同時通過**——能力只回答「這類動作你被允許嗎」，案件守門回答「這張案件你看得到嗎」，tier 回答「這張單輪到你嗎」。勾 `approve` **不會**讓人變成簽核人（簽核人仍在簽核流程設定挑）。
- 高風險能力（`view_money`、`approve`、`pay`、`delete`、`export` 個資、`void`）預設只開放給種子所給的角色。

## 3 預設等價：上線當天零行為變更

1. **種子**：由一支 `seed_from_legacy()` 把「六角色 × `ROLE_TEMPLATES` × 財務三鍵規則 × 每個既有閘」翻成矩陣列；**不建任何個人覆寫**。每個能力在登錄時附 `legacy`（原判斷式的可執行版本，只供閘門用，數個版本後刪）。
2. **等價關卡（仿 `duty_roles_equivalence`，永不砍）**，兩層：
   - **A 判斷層**：對 6 角色 × 模組勾選形狀（空、單鍵、全部、含惰性財務勾選）× 綁定／扣項形狀，逐能力比對 `can()` 與內嵌「出貨當時演算法」的逐字副本。
   - **B 端點層（授權矩陣金標）**：用 TestClient 對**每一條路由**以 7 種代表帳號（6 角色＋一個有扣項的）送「空內容」請求，只記「是否被授權閘擋下」（403／401 vs 其他）→ `authz_matrix_golden.json`（一行一筆、排序，仿路由金標）。遷移前後 **diff 必須為空**；有意的改變要在同一提交更新金標並寫原因。約 800 路由×7≈5,600 次請求，單程序數分鐘，可進建包。
3. 上線流程沿用 R2 的 `off／shadow／on` 旗標：先 shadow 比對舊／新並寫限速稽核，一個班無差異再 `on`；回滾＝切回旗標。

## 4 頁面：系統 > 權限設定（僅 superadmin 可改）

- **矩陣視圖**：列＝能力（依模組分組、可摺疊、搜尋、只看高風險）；欄＝基礎角色＋職責角色；格＝勾選（繼承顯示灰勾）。**使用者視圖**：選一個人 → 生效權限預覽（沿用 `effective_preview`）＋個人允許／禁止。
- **每格標示「已接入／未接入」**：能力還沒有任何端點使用 `can()`（尚未遷移的模組）時，格子顯示「尚未生效」——**避免 R1 的「部分生效」假安全感**。
- **存檔前差異預覽**：列出 `誰/哪欄 / 哪個能力 / 舊→新 / 影響人數`；高風險授權用紅色警示（檢視金額、核准、付款、刪除、匯出個資）；**原因欄位必填（高風險）**，沿用 R1 的原因規則。
- **雙人確認（建議，見問題 3）**：授予高風險能力給非 superadmin 角色，需第二位 superadmin 在待辦中確認才生效；撤銷（降權）不需。
- **稽核與版本**：每次存檔＝一個 `perm_versions` 快照＋`permission_changes` 明細（誰、何時、哪格、舊→新、原因、IP）＋站內通知給其他 superadmin；**回溯**＝選一個舊版本「還原」，產生新版本（歷史不改），還原前同樣顯示差異。
- **可稽核報表**：「誰有 `pay` 能力」、「這個人為何有這項能力（來自哪一欄／覆寫）」、「近 30 天授予的高風險能力」。

## 5 落實與防倒退

**守門（棘輪，仿 `recyclebin_baseline`）**：
1. **角色字串守門**：AST 掃所有端點，凡在路由函式內以字面值比較 `role`（`== 'admin'`、`in (…)`）、呼叫 `_require_admin`／`require_superadmin` 而**不是** `perm.require(cap)` 者，必須在基線 `authz_hardcode_baseline.json` 登記（`exempt:` 例如純系統能力＋理由）；**只准縮小**，新增即紅。起始基線＝本稿盤點的約 450 處（角色 208＋admin 57＋super 189）。
2. **登錄守門**：每個 `perm.require('x')` 的 `x` 必須出現在某模組 `module.json`；每個登錄的能力必須有 `label/risk/legacy`、且至少被一個端點使用或標 `reserved`。
3. **前端守門**：頁面 `role ===` 計數基線（只減）。
4. **金標**：上節 B 層；新增路由未登錄授權 ⇒ 路由金標與授權金標雙紅。

**分期（人日為粗估，單人）**
| 期 | 內容 | 人日 | 主要風險 |
|---|---|---|---|
| P0 | `core/capabilities.py`＋表＋`perm.can/require`＋種子＋A 層等價關卡＋B 層授權金標（尚無端點遷移）；頁面唯讀「生效權限」 | 6–8 | 金標範圍大、跑得久 ⇒ 抽樣＋快取 |
| P1 | 矩陣編輯＋差異預覽＋原因＋版本／回溯＋雙人確認＋稽核報表（但格子標「未接入」） | 6–8 | UI 與 R2 視窗整合 |
| P2a | **payroll**（75 路由、superadmin 閘 52）＋**arap**（40）：風險最高（金錢）、結構單純 | 5–6 | 「財務可送出勞報單」第一個真案例，需使用者定義哪些端點屬 `view` vs `edit` |
| P2b | **case**（156，案件守門 40／簽核 50 保持不動，只換動作閘 ~100 處）＋ subcontract | 8–10 | 案件頁最複雜、前端 `canSeeFinancial` 要同步換 |
| P2c | accounting、supply、其餘小模組 | 6–8 | 稅務／總帳類維持 superadmin-only（`system.*` 不可委派） |
| P2d | **legacy routers**（235，106 個 superadmin 閘多屬使用者／設定／系統）：大多登錄為「不可委派」能力，只換標記不開放 | 3–4 | 量大但機械 |
| P3 | 前端 `role ===` 約 150 處改 `can()`；移除包裝裡的 `legacy` 判斷；基線歸零 | 4–5 | 逐頁 e2e |

**模組日後接入不改程式**：新模組只要在 `module.json` 宣告能力並在端點用 `perm.require('…')`（守門強制），權限頁自動多出一列；同一模組的能力調整（例如新增一個 `export` 勾）也是「宣告＋端點一行」，**不需動權限程式或畫面**。

## 6 需要使用者裁示（≤6）
1. **粒度**：九個動作（檢視／檢視金額／填寫／修改／送出／核准／付款／刪除／匯出）夠不夠？要不要「檢視金額」獨立於「檢視」（建議要，與現有 `financial_view` 同義）？
2. **「財務只看不能改」的邊界**：哪些端點算「只看」（所有 GET＋匯出？是否含匯出 PDF／Excel）？建議：`view`＋`view_money`，匯出另算一格。
3. **雙人確認**：授予高風險能力需第二位 superadmin 確認？若目前只有一位 superadmin，建議改為「原因必填＋24 小時後生效、期間可撤銷」。
4. **哪些能力永遠只給 superadmin 且不可委派**（建議：權限頁本身、使用者管理、系統設定、備份／還原、稅務／總帳關帳）？
5. **勾 `approve` 的語意**：只代表「允許執行核准動作」，簽核人仍須在簽核流程設定被挑到（建議如此）；或勾了就自動成為該類單據的候選簽核人？
6. **推出節奏**：第一批只做 payroll＋arap（含「財務可送出勞報單」）後即開放編輯，其他模組格子標「未接入」？或全部遷完才開放編輯（較慢但無「部分生效」）？
