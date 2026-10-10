# 權限矩陣（勾選制）設計稿 — 第 54 班（v5：併入 PM 獨立審查修訂；相衝處以 §10 為準）

> 作者 1d（獨立設計，唯讀；基準 origin/platform `b2486535c`）。**只有設計，沒有程式。** 使用者原話：「權限的部分跟哪一個權限可以送出、填寫的，變成一個獨立頁面，勾選就能放行或是修改，未來也不用單獨寫程式微調……財務我勾選勞報單，他也可以送出審核；某個管理員可以有財務查看，但不能修改……不寫死在系統內，保留彈性跟確認稽核」。
> **v2 修訂（node-d8 轉述使用者裁示）**：① 動作要再細分 ② 匯出獨立一格 ③ ~~高風險授權＝必填原因＋24 小時後生效、期間可撤銷（不需第二位 superadmin）~~〔**作廢**：已被 §10.1 取代——放寬高風險能力＝另一位最高管理者核准＋確認期（預設 7 天，系統內可調，下限 24 小時）〕④ 勾「核准」只代表允許，簽核人仍由簽核流程設定決定。本版改動：§2 動作詞彙與 §2.1 分類表、§4 待生效授權機制、§5 分期、§6、新增 §7（與 n39 設定盤點共用稽核／版本層）。
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
- **動作詞彙固定 19 個（v3 加 `menu`，見 §8.1；以下列出原 18 個）**（避免各模組自創；單位可再宣告專屬動作，但須有 `risk`）：`view` 檢視、`view_money` 檢視金額、`view_sensitive` 檢視敏感個資（帳號／身分證／電話，今天只有 superadmin）、`create` 填寫新增、`edit` 修改、`submit` 送出審核、`withdraw` 撤回、`approve` 核准、`reject` 退回、`void` 作廢／取消、`pay` 付款／標記已匯款、`delete` 刪除、`export` 匯出、`print` 列印／產 PDF、`attach` 附件上傳／刪除、`comment` 備註／留言、`reassign` 改負責人／指派、`config` 該模組的管理設定。**匯出獨立一格，不由 `view` 帶出**（使用者裁示）。
- **每個物件只列「適用的動作」**（見 §2.1），矩陣不是 19×物件的全表；預估登錄能力約 350 條。
- **登錄**：各模組在 `module.json` 新增 `capabilities: [{key, label, risk: none|ops|money|legal|security, legacy: "<舊判斷式描述>", implies: […]}]`（**加法、L1 契約 `core/capabilities.py`**，載入時彙整；模組缺席＝能力不存在，畫面不列）。新模組／新端點自己宣告，**不必改權限頁或權限程式**。
- **舊模組鍵相容**：30 個模組鍵保留，視為「粗粒度別名」＝該模組全部能力的預設集合（`implied_by_module_key`）。`users.modules` 與職責角色**不改格式**。

### 2.1 物件家族 × 適用動作（矩陣只顯示適用格；●＝適用，○＝視物件而定）

| 家族（例） | view | view_money | view_sensitive | create | edit | submit | withdraw | approve | reject | void | pay | delete | export | print | attach | comment | reassign | config |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 金錢單據：報價單、請款單、開票憑據、匯款申請、勞報單、額外費用、採購單、費用單據 | ● | ● | ○ | ● | ● | ● | ● | ● | ● | ● | ○ | ● | ● | ● | ● | ● | ○ | — |
| 作業單據：完工單、出貨單、派發、叫料申請 | ● | ○ | — | ● | ● | ● | ● | ● | ● | ● | — | ● | ● | ● | ● | ● | ● | — |
| 案件（案件頁本身） | ● | ● | — | ● | ● | — | — | — | — | ○ 結案 | — | ● | ● | ● | ● | ● | ● 負責人/成員 | — |
| 主檔：客戶、供應商、料號、外包名冊、承攬商 | ● | ○ | ● | ● | ● | — | — | — | — | — | — | ● | ● | — | ● | ● | — | — |
| 記錄：工作日誌、每日事項、CRM 記錄、設備 | ● | — | — | ● | ● | — | — | — | — | — | — | ● | ● | — | ● | ● | ● | — |
| 帳務：傳票、總帳、稅務申報 | ●(本質金額) | — | — | ● | ● | ● | ● | ● | ● | ● | — | ○ | ● | ● | ● | ● | — | ● 關帳（不可委派） |
| 出納：待付款、銀行對帳 | ● | ● | ● | — | ● | — | — | — | — | ● | ● | — | ● | ○ | — | ● | — | — |
| 報表／儀表板 | ● | ● | — | — | — | — | — | — | — | — | — | — | ● | ● | — | — | — | — |
| 系統：使用者、設定、稽核、版本、備份、暫存區 | ● | — | — | ● | ● | — | — | — | — | — | — | ● | ● | — | — | — | — | ● |

- **預設等價的做法**：今天沒有對應閘的新動作，種子一律「抄最近的既有閘」（`legacy_alias`）——例如 `withdraw`／`reject` 抄 `submit`／`approve` 的閘、`comment`／`attach` 抄 `edit`、`print` 抄 `view`、`reassign` 抄 `edit`；因此上線當天每一格的值都等於今天實際行為，**只有之後被改的格才會不同**。
- **「本人」限定不進矩陣**：撤回自己送的單、編輯自己的草稿這類「只限本人」仍是資料範圍守門（與案件守門同層）；能力只決定「這類動作允不允許」。
- **常用組合（預設集）**：頁面提供「只看」「填寫」「填寫＋送出」「簽核」「出納」等一鍵勾選組（只是批次勾，不是新概念），降低 350 條的操作成本。

**矩陣（誰有哪些能力）**，生效集合＝
`（基礎角色格 ∪ 模組鍵展開 ∪ 職責角色格 ∪ 個人「允許」）− 個人「禁止」`，**禁止優先於允許**。
- 新表（皆模組 migration、只增）：`perm_role_caps(role_or_duty_key, cap, granted)`、`perm_user_overrides(user_id, cap, effect allow|deny, reason)`、`perm_versions(id, snapshot_json, created_by, reason, created_at)`；變更寫既有 `permission_changes`（只增不改）。
- **重用 R2，不重做**：職責角色就是矩陣的「欄」（`duty_roles.permissions` 從模組鍵擴充為「模組鍵或能力鍵」）；個人扣項 `user_perm_subtracts` 併入 `perm_user_overrides(effect=deny)`；`effective_preview`／`preview_whatif`／`permission_changes`／高敏感原因規則直接沿用。
- 「財務可送出勞報單」＝在 finance 欄勾 `payroll.payslip.submit`；「某管理員財務只看」＝個人允許 `finance.*.view`、`finance.*.view_money`，不給 `edit/pay`。

**中央檢查 API（取代寫死角色字串）**：`perm.can(user, cap) -> bool`、`perm.require(user, cap)`（403，訊息含缺哪個能力＝可稽核）。每請求只算一次生效集合（記憶體＋矩陣版本號失效），登入 payload 帶 `caps` 給前端，**前端 `can('…')` 取代 `role ===`，後端仍是唯一權威**。既有 `has_finance_access`／`require_any_module`／`user_has_module`／`_require_admin` 改成 `can()` 的薄包裝（行為不變），端點逐步直接改用 `require(cap)`。

**不變式**
- **superadmin 永遠通過且不可被鎖死**：`can()` 第一行直通；矩陣不存 superadmin 列、API 拒絕對它設禁止（與 R1 一致）。權限頁本身（`system.permissions.manage`）預設不可委派（問題 4），所以任何勾選錯誤都不可能讓 superadmin 進不了權限頁；另附伺服器端離線工具 `perm_reset --to-seed`（把矩陣與覆寫重設為種子並寫稽核），供誤設後急救。
- **不管範圍與序**：每案守門（`guard_case_access`）與簽核層級**照舊且必須同時通過**——能力只回答「這類動作你被允許嗎」，案件守門回答「這張案件你看得到嗎」，tier 回答「這張單輪到你嗎」。勾 `approve` **不會**讓人變成簽核人（簽核人仍在簽核流程設定挑）。
- **高風險能力**（使用者裁示：`view_money`、`approve`、`pay`、`delete`；本稿建議加 `view_sensitive`、可委派的 `config`）的**授予＝放寬**，一律走 §10.1 的流程（另一位最高管理者核准＋確認期（預設 7 天，系統內可調，下限 24 小時））；降權、撤銷、以及一般能力的授予都立即生效。
- **不可委派（僅 superadmin）**：權限設定頁本身、使用者管理、系統設定、備份／還原、稅務／總帳關帳（node-d8 預設，同意）；建議再加「刪除暫存區的還原／永久刪除」（已是 superadmin 專用，使用者先前裁示）與授權／金鑰類。這些能力登錄時標 `delegable: false`，矩陣不給勾。

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
- ~~高風險授予＝24 小時待生效（不需第二位 superadmin）／`perm_pending` 表~~〔**作廢**，本段原文已刪除以免照做；現行規則見 §10.1（方向表）、§10.2（只用帳本事件）、§10.8（確認期與到期重新判斷）〕。UI 只需知道：高風險授予存檔後進「待生效」清單，顯示『需要誰核准、哪天生效』，確認期內任何最高管理者可撤銷；其餘細節（資料、狀態、通知）以 §10 為準。
- **稽核與版本**：每次存檔＝一個 `perm_versions` 快照＋`permission_changes` 明細（誰、何時、哪格、舊→新、原因、IP）＋站內通知給其他 superadmin；**回溯**＝選一個舊版本「還原」，產生新版本（歷史不改），還原前同樣顯示差異。
- **可稽核報表**：「誰有 `pay` 能力」、「這個人為何有這項能力（來自哪一欄／覆寫）」、「近 30 天授予的高風險能力」。

## 5 落實與防倒退

**守門（棘輪，仿 `recyclebin_baseline`）**：
1. **角色字串守門**：AST 掃所有端點，凡在路由函式內以字面值比較 `role`（`== 'admin'`、`in (…)`）、呼叫 `_require_admin`／`require_superadmin` 而**不是** `perm.require(cap)` 者，必須在基線 `authz_hardcode_baseline.json` 登記（`exempt:` 例如純系統能力＋理由）；**只准縮小**，新增即紅。起始基線＝本稿盤點的約 450 處（角色 208＋admin 57＋super 189）。
2. **登錄守門**：每個 `perm.require('x')` 的 `x` 必須出現在某模組 `module.json`；每個登錄的能力必須有 `label/risk/legacy`、且至少被一個端點使用或標 `reserved`。
3. **前端守門**：頁面 `role ===` 計數基線（只減）。
4. **金標**：上節 B 層；新增路由未登錄授權 ⇒ 路由金標與授權金標雙紅。

**分期（舊估，已被 §10.6 唯一總表取代；僅留作階段說明）**
| 期 | 內容 | 人日 | 主要風險 |
|---|---|---|---|
| P0 | `core/capabilities.py`＋表＋`perm.can/require`＋種子（含 `legacy_alias`）＋A 層等價關卡＋B 層授權金標（尚無端點遷移）；頁面唯讀「生效權限」 | 7–9 | 金標範圍大 ⇒ 抽樣＋快取；18 動作的 legacy 對照要逐模組確認 |
| P1 | 矩陣編輯（家族過濾、一鍵組合、搜尋）＋差異預覽＋原因＋**確認期機制（用帳本事件＋核准；撤銷頁、通知——見 §10）**＋版本／回溯＋稽核報表（格子標「未接入」） | 10–13 | 待生效與快取的一致性（讀時判斷＋到期邊界）；UI 與 R2 視窗整合 |
| P2a | **payroll**（75 路由）＋**arap**（40）：首批，含「財務可送出勞報單」；開放矩陣編輯（其他模組格子顯示「尚未生效」） | 6–8 | 需使用者確認哪些端點屬 `view` vs `edit` vs `export`/`print` |
| P2b | **case**（156；案件守門／簽核層級不動，只換動作閘約 100 處）＋ subcontract（74） | 12–14 | 案件頁最複雜；前端 `canSeeFinancial` 同步換 |
| P2c | accounting、supply、其餘小模組 | 7–9 | 稅務／總帳維持不可委派 |
| P2d | legacy routers（235，106 個 superadmin 閘）：多登錄為不可委派能力，只換標記 | 3–4 | 量大但機械 |
| P3 | 前端約 150 處 `role ===` 改 `can()`；移除包裝裡的 `legacy` 判斷；基線歸零 | 4–5 | 逐頁 e2e |
| **合計** | | **49–62**（含 §7 的待生效部分；`config_ledger` 的寫入／明細部分由設定中心 S0 先做，不計入） | |

**推出節奏（node-d8 預設，同意）**：P0＋P1 完成後先接 payroll＋arap，即開放矩陣編輯；其他模組的格子標「尚未生效」，隨 P2b–P2d 逐批轉為「已接入」。

**模組日後接入不改程式**：新模組只要在 `module.json` 宣告能力並在端點用 `perm.require('…')`（守門強制），權限頁自動多出一列；同一模組的能力調整（例如新增一個 `export` 勾）也是「宣告＋端點一行」，**不需動權限程式或畫面**。

## 6 已裁示與剩餘確認
**已裁示**：動作要再細分（§2、§2.1）；匯出獨立一格；高風險授予＝放寬＝另一位最高管理者核准＋確認期（預設 7 天、系統內可調、下限 24 小時；使用者裁示，取代先前的「24 小時、不需第二位」）；「核准」勾選只代表允許、簽核人仍由簽核流程設定決定（不自動成為候選）。**node-d8 預設（已同意）**：不可委派能力清單、先 payroll＋arap 後開放編輯。

**仍請確認（可用預設前進）**：
1. 高風險清單是否加 `view_sensitive`（銀行帳號／身分證／電話，今天只有 superadmin 看得到完整值）與可委派的 `config`？預設：加。
2. 19 個動作中，`print`（產 PDF）要不要與 `export` 合併？預設：分開（PDF 常是對外文件，風險不同）。
3. 「只限本人」的撤回／編輯草稿維持資料範圍守門、不進矩陣（§2.1）？預設：是。

## 7 與設定中心共用的稽核／待生效層：`helpers/config_ledger`（與 node-39 `SETTINGS-CENTER-DESIGN-T54` §2 一致的協議）
**原則：不建第二套版本表。** 版本、差異、還原留在各 domain 自己的儲存（權限＝`perm_versions`；設定＝`core/definitions.py` 的 `ui_definitions`／kind `setting_group`）。`config_ledger` 只做兩件那些儲存沒有的事：**變更明細**與**待生效狀態**。L1、只增不改、不 import 任何 L2。
1. **寫入**：`record(conn, domain, key, changes, reason, actor, *, ip="", effective_at=None, risk="none", approvals_required=0, ref_version=None) -> change_id`（`risk ∈ none|ops|money|legal|security`）；`changes=[{field, old, new}]`；`domain` ＝ `perm` 或 `setting:<群組>`。與被改的資料**同一交易**寫入；同交易寫 `audit_log`（action `<domain>.change`）；`risk >= money`（view_money／approve／pay／delete／view_sensitive 等）時通知其他 superadmin。
2. **表（只增不改）**：`config_changes(id, at, domain, key, field, old_json, new_json, reason, actor, ip, effective_at, risk, ref_version, batch_id)`，DB 觸發器擋 UPDATE／DELETE；**狀態不放在這張表**，改記 `config_change_events(id, change_id, event, actor, reason, at)`，`event ∈ {pending, activated, cancelled, superseded}`，現況＝最後一筆（無事件＝立即生效的一般變更）。
3. **待生效 API**（只存與轉態，不決定效力）：`pending(domain=None)`、`cancel(change_id, actor, reason)`（寫 `cancelled` 事件、通知申請人）、`activate_due(now)`（把 `effective_at <= now` 且仍 pending 的轉 `activated`、寫稽核、通知；由 5 分鐘工作呼叫，**漏跑不影響效力**）、純函式 `in_effect(row, now)`（`effective_at` 空或已到、且最後事件不是 cancelled／superseded）。**`in_effect` 只在帳本裡實作一份**（含核准票數與確認期判斷）；`perm.can()`／`settings.get()` 在讀取時**呼叫它**，domain 不得自己重寫（§10.2）。
4. **版本與還原**：`register_domain(domain, label, snapshot_fn, restore_fn, diff_fn, reason_required_fn=None)`；ledger 只提供「歷史」查詢 `history(domain, key)` 與統一的「還原＝新版本、歷史不改」呼叫流程。`perm` → `perm_versions`；`setting:*` → `ui_definitions`（`definitions.versions/restore/diff`）。還原含待生效項 ⇒ domain 的 restore 負責一併 cancel。
5. **既有表**：R1／R2 職責角色的 `permission_changes`（含只增不改觸發器）**不搬資料、不雙寫**，仍是 `duty` domain 的明細；權限矩陣的新變更只寫 `config_changes`（domain `perm`）。稽核報表以 UNION 呈現，避免兩份漂移。
6. **誰先做**：設定中心 S0（第一批不用待生效）先實作並上線 `config_ledger` 的 1、2、4 與 `history`；權限矩陣 P1 再加 3（待生效 API、`activate_due` 工作、`in_effect`）——介面現在就定死，後補不改簽名。設定第二批的 K04（登入安全）也走待生效層。

## 8 v3 增補：選單能力、代理與兼任、把「寫死」變成可勾選（使用者 10-10 三項要求）

**核心做法不變**：框架＋由今天行為推導的種子；誰勾什麼全由 superadmin 在頁面決定，不新增任何寫死名單（使用者核心規則）。

### 8.1 選單可見度＝獨立的能力種類 `menu`
- 動作詞彙加第 19 個 **`menu`**（導覽列項目、系統中樞卡片是否出現）。`menu` 與 `view` **各自獨立**：只藏入口不擋 API（API 仍由 `view` 擋）；反之有 `view` 沒有 `menu` ＝能開（直接網址／被連結）但導覽列不顯示。使用者要求的四個獨立勾選＝`menu`／`view`／`edit`／`submit`／`approve`。
- 宣告：`module.json` 的 `pages[].menu` 新增選填 `cap`（省略＝`<單位>.<頁面鍵>.menu` 自動產生）。**legacy 由現有 `perm` 欄位機械推導**：`"any"`→`{"everyone": true}`（DSL 新葉子＝所有角色）、`"superadmin"`→`{"superadmin": true}`、`[鍵…]`→`{"any": [{"module": 鍵}…]}`——即 `core/menu.py::visible` 的語意，所以**今天的選單規則就是種子**，不必人工翻譯。
- 消費：選單 builder（`core/menu.py`）與系統中樞卡片改以 `perm.can(user, cap)` 過濾；前端 `MOTRIX_MENU` 宣告改帶 `cap`，登入 payload 帶使用者的 `caps`（含 `menu`）。`perm` 欄位保留為 legacy 來源（棘輪：模組逐步改宣告 `cap`，`perm` 計數只減）。
- **關卡 C（選單等價）**：每個（角色 × 模組勾選形狀）的「可見選單集合」＝內嵌的 `core/menu.visible` 逐字副本；新舊必須逐項相同。

### 8.2 把寫死變設定——以勞報單送出為第一個遷移（P2a）
- 今天 `POST /api/payslips/{no}/submit` 是 `_require_user(require_superadmin=True)`：**只有 superadmin**，財務角色不能（核准／退回則是 superadmin 或持有 `payslip` 模組）。
- 遷移後：宣告 `payroll.payslip.submit`（`legacy: {"superadmin": true}` ⇒ 種子＝只有 superadmin，**上線當天行為不變，關卡 B 證明**）；端點改 `perm.require(user, "payroll.payslip.submit")`。之後 superadmin 在權限頁「角色」分頁於「財務」欄勾這一格，財務就能送出——**不改任何程式**。「某管理員可以有財務查看、不能修改」＝在「人員」分頁給該人 `finance.*.view`／`view_money` 個人允許，不給 `edit`／`pay`。

### 8.3 代理（delegation）與兼任（concurrent role）
**生效能力＝ 基礎角色格 ∪ 模組鍵展開 ∪ 職責角色（可多個，疊加＝兼任）∪ 有效代理（受 §下列限制）∪ 個人允許 − 個人禁止**；禁止優先於所有來源（含代理）；superadmin 直通。
- **兼任＝職責角色疊加**：R2 的 `user_duty_roles` 本來就允許一個人綁多個職責角色，矩陣的「欄」就是職責角色 ⇒ 不新增機制。人員分頁顯示「基礎角色＋各兼任角色＋來源」。選配：綁定可帶 `valid_to`（臨時兼任到期自動失效；P1 小改，預設無期限＝現況）。
- **代理＝統一現有「簽核代理人」`approval_delegates`，不做第二套**：新表 `perm_delegations(id, delegator, delegate, scope_kind caps|doc_types|approval_slot, scope_json, valid_from, valid_to, reason, state pending|active|revoked|expired, requested_by, requested_at, effective_at, revoked_by, revoked_at, revoke_reason, legacy_id)`。
  - 現有 `approval_delegates` 的每一列遷成 `scope_kind=approval_slot, state=active`（語意＝今天的「代替他在簽核層裡簽」）；讀取點統一成兩個（正向 `active_delegators_for`、反向 `active_delegates_of`，見 §10.4），依旗標讀一邊；`/api/approval-delegates` 舊端點變薄包裝（寫新表）。**關卡 D**：對現有每一列，改前後 `active_delegators_for(delegate, 日期)` 逐日相同。
  - **範圍**：`caps`（能力清單）或 `doc_types`（單據類型，展開成該類型的 `view/comment/submit/approve…` 能力）；委派的只能是**委派人自己目前有的**能力（不能憑代理升權）、不含不可委派能力、**不可再轉代理**（A→B→C 不傳遞）。
  - **風險範圍**（含 `view_money／approve／pay／delete／view_sensitive／config`）一律走放寬流程（§10.1：另一位最高管理者核准＋確認期、可撤銷；用 `config_ledger` 事件，沒有第二套）；一般範圍立即生效。撤銷與到期立即失效。
  - **誰能建**：superadmin 任何人；本人替自己建（限非風險範圍）需要能力 `perm.delegation.create_own`（種子＝今天能建簽核代理的人）。
  - **「代理某某」要留痕**：`perm.can_via()`/`perm.acting_as(user, cap)` 回傳這次是否**只靠代理**才通過、代誰（自己的基礎權限足夠時不算代理）。靠代理完成的動作：稽核 `detail.actingAs=<委派人>`、通知文字「X（代理 Y）…」、單據自己的簽核紀錄同時記**代理人與委派人**（`approvedBy` 加 `onBehalfOf`），簽核歷史／PDF 顯示「X 代 Y」。
  - **介面**：「代理與兼任」分頁——建立代理（選委派人／被代理人／範圍：能力或單據類型／起訖／原因）、清單（有效／待生效／已撤銷／已到期）、撤銷鈕；被代理人與其他 superadmin 在生效前收到通知。

### 8.4 權限設定頁（系統 > 權限設定）分頁
**角色（矩陣）｜人員（生效預覽＋每項來源：角色／兼任／代理／個人）｜代理與兼任｜選單（每頁一列的 `menu` 勾選）｜待生效（確認期內可撤銷）｜變更紀錄／版本**。每格標「已接入／未接入」。

### 8.5 等價證明的影響
關卡 A（判斷）＋ B（端點授權金標）維持；新增 **C（選單可見集合）**與 **D（代理讀點）**；種子新增 `menu` 能力與 DSL `everyone` 葉子後，A 的窮舉形狀同步擴充。P2a 的 `payroll.payslip.submit` 以 `{"superadmin": true}` 種子，B 金標證明財務帳號仍被擋，之後勾選才改變。

### 8.6 工作量變化（舊估，已被 §10.6 唯一總表取代）
| 項目 | 增加 |
|---|---|
| `menu` 能力＋選單 builder／中樞卡片改讀能力＋關卡 C＋前端宣告 | +5–6 |
| 代理統一（`perm_delegations`、遷移、`active_delegators_for` 單一讀點、舊端點包裝、acting-as 留痕、關卡 D、分頁） | +9–11 |
| 兼任 `valid_to`＋人員分頁來源顯示 | +2 |
| **合計** | **+16–19 ⇒ 約 65–81 人日**（P0 仍先做框架；代理表介面在里程碑 2 就先建，端點接線隨 P2） |

### 8.7 需要使用者確認
1. 本人能否自行替自己建「非風險範圍」的代理（預設：能，若今天就是這樣）？風險範圍一律需 superadmin、另一位最高管理者核准並經過確認期。
2. 兼任是否需要到期日（預設選配、不填＝長期）？
3. 代理期間，被代理人自己是否仍保有同樣權限（預設：是，只是「額外」給代理人；不是轉移）？

## 9 v4 增補：給完全不懂技術的人用（使用者 10-10 三項規則）

**規則**：畫面只有繁體中文名稱、一句話說明、白話風險提示；不出現能力鍵、`allow`／`deny` 這類英文、id、代碼；選項用勾選／開關／下拉；每個選項旁說明「選了會影響什麼」。

### 9.1 宣告就是文案（框架強制）
- 能力宣告**必填** `label`（動作短語，如「送出勞報單」）、`desc`（一句話說明）、`impact`（勾選後會影響什麼，白話），且必須含中文——缺或只有代碼／英文，登錄**拒絕**（`core.capabilities`，已實作）。選填：`question`（含 `{who}` 的白話提問，缺省由 label 產生「{who}可以送出勞報單嗎？」）、`recommended`（建議可以做的角色，缺省＝種子即今天的行為）、`presets`（各預設組合下有此能力的角色）、`impact_calc`（有影響計算）。
- 動作（19 個）、角色、預設組合（模組以 `capability_presets: [{key,label,desc}]` 宣告）、代理範圍同樣各帶中文名稱與說明；角色名稱取系統設定 `role_labels`（管理者可改）。
- **白話文字層** `helpers/perm_text`（已實作）：提問、`explain_text`（「王小明可以修改勞報單：『管理員』這個角色有勾選。」）、`sentence_role_cap`、`sentence_delegation`（「你即將讓王小明代理李主任：送出勞報單，到 11/30，7 天後生效」）、`risk_hint`。不用「他／她」，對不到名稱說「（未命名）」而不露代碼。
- **畫面掃描守門（render-scan）**：枚舉文字層對所有能力×角色×來源的輸出，禁止出現能力鍵、`allow`／`deny`／`superadmin` 等代碼與代名詞（`tests/platform/test_perm_text.py` 已含）；頁面實作時再以 node-39 的設定中心畫面掃描 helper 對權限頁的 DOM 文字做同一檢查（該 helper 出現後接上）。

### 9.2 最簡單的選法
- **問句式**：矩陣不是 350 格的表，而是一題一題的問題——「財務可以送出勞報單嗎？」→ **可以／不可以**，旁邊標「建議：不可以」（`recommended`）。依模組分組、可搜尋；**進階**（個人例外、代理細節）預設收合。
- **一鍵預設組合**：「一般公司」「嚴格分工」…（由模組宣告、管理者可看內容）；點選後先顯示**效果預覽**（哪些問題會變成什麼、影響哪些角色／人），按「套用」才生效；高風險項仍走 確認期待生效。
- **代理／兼任精靈**：三步——① 誰代理誰 ② 做哪些事（勾選白話項目，或選單據類型）③ 到何時；最後一頁是白話摘要句（如上）與「儲存」。
- **存檔前摘要句**＋**一鍵復原**（`undo_last_change`，每按一次往回一步，已實作）；待生效項目有「撤銷」鈕。

### 9.3 影響面板（每個選項旁）
勾選／切換時，右側即時顯示（`preview_*` 已實作）：一句話摘要；**勾選後會影響什麼**（宣告的 `impact`）；**影響幾位使用者**（即時計數）、有影響計算的能力再顯示**幾份單據**；**適用範圍**（之後的操作依新設定；已送出或完成的單據與簽核紀錄不受影響）；**可否復原**（隨時一鍵復原）；**何時生效**（立即／確認期後，期間可撤銷）；**白話風險提示**。選單類能力另顯示**該角色的選單 前／後 預覽**（`menu` 能力落地後）。

### 9.4 工作量變化（舊估，已被 §10.6 唯一總表取代）
文字層、宣告驗證、預覽、復原已在框架里程碑完成；其餘＝頁面（問句式 UI、預設組合與效果預覽、代理精靈、影響面板、選單前後預覽）**+6–8 人日**，整體約 **71–89 人日**（含 §8 的 +16–19）。

### 9.5 實作進度（wip/t54-1d-permmatrix-p0）
里程碑 1 `fb828f62e`（能力登錄、中央檢查、關卡 A）；里程碑 2 `133c33053`（permmatrix 模組：表、提供者、覆寫／代理／確認期待生效／版本）；白話規則 `22b9c8a51`（必填白話宣告、perm_text、影響預覽、一鍵復原）。

## 10 v5/v6 審查修訂（PM 獨立設計審查；**與前文相衝處以本節為準；前文已作廢的段落以刪除線＋〔作廢〕標示**）

**確認期（使用者裁示 10-10）**：高風險授予（放寬）的等待期＝**預設 7 天、系統內可調、下限 24 小時**（取代先前固定的 24 小時）。數值**不由本設計另訂**，直接使用設定中心（node-39 Settings §2.2）擁有的單一設定鍵 `confirm_period_days`（預設 7 天、下限 24 小時＝1 天）；權限矩陣在**申請當下把天數換算成小時**寫進該筆變更的 `effective_at`（之後改設定不影響已申請的）。調短確認期本身是放寬，走同一套核准。下文凡寫「確認期」皆指此值。

### 10.1 放寬／收緊方向表（審查 1：高風險授予＝放寬＝雙人核准＋確認期）
採設定中心附錄 D 的同一套規則（`config_ledger.approve`：申請人不能自核、同一人不能重複投票、票數不足時到時間也不生效；只有一位最高管理者時＝必填原因＋確認期＋畫面警告＋通知並留紀錄）。

| 變更 | 方向 | 生效 |
|---|---|---|
| 角色格：勾選**高風險**能力（查看金額／查看個資／核准／付款／刪除／管理設定，及其他 `risk≥money` 者） | 放寬 | 另一位最高管理者核准＋確認期，期間可撤銷 |
| 角色格：勾選低／中風險能力 | 放寬（非風險類） | 立即（原因選填） |
| 角色格：取消勾選任何能力 | 收緊 | 立即 |
| 個人允許（高風險）／**移除個人禁止**使高風險能力重新可用／**把被取消的高風險格勾回去**（含一鍵復原一項收緊） | 放寬 | 同第一列（復原一項收緊＝再放寬，所以不例外） |
| 個人禁止 | 收緊 | 立即 |
| 建立代理（範圍含高風險能力）／套用含高風險的預設組合／綁定含高風險能力的職責角色 | 放寬 | 同第一列 |
| 建立代理（非風險範圍）、`approval_slot` 範圍（只轉移委派人**已被指名**的簽核位，不給新能力＝維持今天『任何登入者替自己建』） | 非風險 | 立即 |
| 撤銷代理、取消勾選、回溯到較緊的版本 | 收緊 | 立即 |
| 回溯／預設組合套用 | 逐項依上列判斷 | 逐項 |

### 10.2 只用一套待生效機制（審查 2）：刪除 `perm_pending`
- 待生效、核准、撤銷**只存在 `config_changes` ＋ `config_change_events`**（事件 `pending／approved／activated／cancelled／superseded`）；**只有一份 `in_effect(change, now)`**（`config_ledger`），`perm.can()` 與 `settings.get()` 共用，不再各寫一份。
- 權限表改為**只增不改的格子紀錄**：`perm_role_caps`／`perm_user_overrides`／`perm_delegations` 每列帶 `change_id`（指向 `config_changes`）；某格目前的值＝該格最後一筆 `in_effect` 的列。沒有『啟用時才寫入』的動作，`activate_due` 只負責寫 `activated` 事件、稽核與通知（漏跑不影響效力）。
- 風險紅線：待生效中的列存在但不納入計算；撤銷＝加 `cancelled` 事件。`perm_versions` 仍是快照（回溯用），回溯時含待生效項一併 cancel。
- **實作對照（待解禁後改）**：目前分支 `wip/t54-1d-permmatrix-p0` 的 `perm_pending` 與 `activate_due` 是過渡實作，本節定案後以 ledger 取代（`service.py` 改成呼叫 `config_ledger.record/approve/in_effect`，表加 `change_id`、刪 `perm_pending`）。

### 10.3 風險詞彙（審查 3，PM 決定）：能力宣告**直接使用帳本詞彙**
`module.json` 能力宣告的 `risk ∈ none｜ops｜money｜legal｜security`（**不再有 low／mid／high**；舊值不存在於任何已落地宣告，註冊時遇到即拒絕）。畫面的低／中／高徽章由它推導（none→低、ops→中、≥money→高）。各動作預設（宣告可往高調、不可往低調）：

| 動作 | 預設 `risk` |
|---|---|
| approve／pay／delete／view_money（及匯出含金額檔的 export） | `money` |
| view_sensitive／config／權限管理（`perm.*`、使用者管理） | `security` |
| 稅務／總帳關帳類 | `legal`（且不可委派） |
| 其他（menu／view／create／edit／submit／withdraw／reject／void／attach／comment／print／reassign） | `none`；營運類可明寫 `ops` |

`risk ≥ money` ⇒ 授予＝放寬走 §10.1、通知其他最高管理者。與設定中心 §2.2 同一詞彙、同一判斷，守門核對 `capabilities` 的對應表。

### 10.4 `approval_delegates` → `perm_delegations` 的切換（審查 5）
- 旗標 `perm_delegation_source ∈ legacy｜new`（`system_settings`，預設 `legacy`＝今天）。
- **讀點其實有兩個方向，先前「單一讀點」不成立**：今天 `approval_delegates` 還被直接讀在 `payroll/api/payslip_approval.py:60,98`、`payroll/api/bonus.py:1296`、`payroll/bonus_payouts.py:117`（皆為**反向**：委派人→代理人們）與 `archive.py:2206`（備份匯出）。因此統一成**兩個**讀點（`helpers/tiered_approval`）：**正向** `active_delegators_for(delegate, today)`（代理人→委派人們，既有）與新增**反向** `active_delegates_of(delegator, today=None, window=True)`；依旗標讀一邊（`legacy` 只讀舊表、`new` 只讀 `perm_delegations` 的 `approval_slot`），任何時刻只讀一邊，不會重複計算。上述三處改呼叫反向讀點。
- **注意既有語意不一致**：`payslip_approval.py:98` 用日期區間（`start_date<=今天<=end_date`），但 `:60`、`bonus.py:1296`、`bonus_payouts.py:117` 只看 `active=1`、**不看日期**（已過期的代理仍被算進去，疑為既有缺陷）。反向讀點以 `window` 參數**逐站保留各自現行語意**（零行為變更），是否把不看日期的三處改成看日期＝另案向使用者確認，不在本次等價範圍內偷改。
- **備份**：`archive.py` 匯出同時涵蓋舊表與 `perm_delegations`（T1，隨表備份）；切換後舊表唯讀仍可匯出。
- **守門**：直接 `SELECT … FROM approval_delegates` 只准出現在這兩個讀點、遷移、舊端點包裝與 `archive.py`（棘輪基線，只減）。
- 遷移（冪等）：把舊表每列複製為 `approval_slot`＋`legacy_id`，不刪舊列。**關卡 D**：對每一列、每一天，`legacy` 與 `new` 兩種模式下**正向 `active_delegators_for` 與反向 `active_delegates_of`（含 `window` 兩種）**結果逐日相同，才可切換。
- 切到 `new` 後：舊表**唯讀**（DB 觸發器擋 INSERT／UPDATE／DELETE）；舊端點 `/api/approval-delegates*` 變薄包裝（寫新表）；回滾＝旗標切回 `legacy` ＋ 工具把切換期間新增／撤銷的列同步回舊表（有等價測試）。
- **範圍重疊時的優先序**：同一對（委派人→代理人）同時有 `approval_slot` 與 `caps` 範圍時，兩者**各自獨立評估、不合併計算**——`approval_slot` 決定『能不能代簽這一層』，`caps` 決定『這類動作被不被允許』；實際簽核需兩者各自成立。稽核 `actingAs` 列出所有提供權限的委派人；**單據簽核紀錄蓋章用 `approval_slot` 的委派人**（簽核位本來就是他的名字）。

### 10.5 其他必修與建議
- **（6）勞報單送出的種子**：`POST /api/payslips/{no}/submit` 今天是 `_require_user(require_superadmin=True)`（`payslip_approval.py:123`），**沒有財務閘可抄**——§2.1 的『抄最近既有閘』在此為**明列例外**：`payroll.payslip.submit` 種子＝`{"superadmin": true}`。頁面在這一題旁明寫：「勾選『送出』只代表可以送去審核，**不代表**是簽核人；簽核人仍由簽核流程設定決定。」
- **（7）中樞卡片**（已與 b5 對齊）：卡片宣告選填 `cap`；中樞呼叫單一提供者 `("perm.can","permmatrix")`＝`fn(user, cap) -> bool`（模組缺席 ⇒ 沿用卡片原本的 perm 宣告＝今天的行為）。選單能力鍵格式＝`<單位>.<頁面檔名去 .html、- 換 _>.menu`（L1 頁面單位為 `core`，例：`core.users.menu`、`arap.cashier.menu`），由 `capabilities.menu_cap_key(unit, href)` 產生、不手打。矩陣變更時呼叫所有 `("perm.changed", <名稱>)` 提供者（中樞登記 `clear_cache`）。守門：中樞的 parity 測試比對卡片宣告與頁面的**種子**宣告；關卡 C 比對種子矩陣下的可見集合。
- **（8）快取失效與效能預算（PM 決定：只用一套機制）**：沿用設定中心的 **`config_epoch`**＝（`MAX(config_changes.id)`、`MAX(config_change_events.id)`）兩個數；各程序**至少每 2 秒**重查一次 epoch，變了就重載矩陣，另有 15 秒的硬 TTL。**不再另設單調版本號列**。因為矩陣的每個變更（含待生效轉態、撤銷、核准）都經帳本，epoch 一定會動。再加『**到下一個時間界線就失效**』：快取的有效期限＝`min(2 秒查詢間隔下的 epoch、最近的未來 effective_at／valid_to／代理到期)`，所以到時間才生效或到期的授予不必等 epoch 變動（此規則同步加進設定中心）。預算：`can()` 快取命中 P95 ≤ 0.2 ms、重載 P95 ≤ 50 ms、單請求只算一次生效集合；以微基準測試守。**授權矩陣金標**（B 層）只收**已遷移的路由**×7 種帳號（每路由一行位元遮罩），未遷移者仍由路由金標與匿名掃描守；行數設上限棘輪（超過需註明原因）。
- **（9）緊急開關與回溯驗證**：環境變數 `MOTRIX_PERM_LEGACY_ONLY=1` ⇒ `perm.can()` 只用種子（忽略矩陣覆寫與代理＝今天的行為）；與 `MOTRIX_SETTINGS_DEFAULTS_ONLY` 同層級、不改資料庫。回溯／預設組合套用時以**目前的能力登錄**重新驗證：已移除或不可委派的能力略過並在摘要說明，不套用。
- **（10）版本邊界涵蓋能力**：`capabilities.set_edition_bounds(unit_or_pattern, allowed, delegable)` 由授權載入器設定（客戶無 API 可改），與矩陣取交集——例：基本版 `payroll.*` 不可用、不可委派能力清單固定；頁面顯示「此版本不提供」並禁用該格。
- **（11）M1（第一個合回的班）的範圍與風險控制**：只含框架（登錄、`perm`、種子、關卡 A、版本邊界、緊急開關）、`permmatrix` 資料層與**唯讀的『生效權限』頁骨架**；**不遷移任何既有端點**、編輯功能由旗標 `perm_matrix_ui`（預設關）控制，選單不列入口——上線當天零行為變更，出事一個環境變數退回。**種子變更基準守門**：`perm_seed_baseline.json` 凍結『能力→種子角色／模組』，種子變了而基準沒更新（含原因）⇒ 紅燈（仿 `settings_deploy_baseline.json`）。

### 10.6 唯一工作量總表（取代 §5、§8.6、§9.4 的各自估算；人日、單人；`config_ledger` 核心由設定中心 S0 先做，不計入）
| 階段 | 內容 | 人日 |
|---|---|---|
| **M1（第一個合回的班）** | F0 全部＋F1 的資料層與帳本串接＋唯讀頁骨架（旗標 `perm_matrix_ui` 預設關）；不遷移端點。**這一行是 F0／F1／F2 中屬於 M1 的子集合，不另計入合計** | 約 26–32 |
| F0 框架核心 | 能力登錄、`perm`、種子與基準守門、關卡 A、版本邊界、緊急開關、快取版本與效能預算 | 10–12 |
| F1 資料與規則 | `permmatrix` 資料層改用 ledger、雙人核准整合、代理（caps／doc_types）、版本回溯、稽核與通知 | 14–17 |
| F2 頁面 | 問句式矩陣、預設組合與效果預覽、代理／兼任精靈、影響面板、人員來源顯示、待生效清單 | 12–15 |
| M 選單能力 | `menu` 能力、選單／中樞卡片改讀能力、關卡 C | 5–6 |
| D 代理統一 | `approval_delegates` 併入、切換旗標與唯讀、回滾工具、關卡 D、acting-as 留痕 | 9–11 |
| P2a | payroll＋arap（勞報單送出為首例；開放矩陣編輯） | 6–8 |
| P2b | case＋subcontract | 12–14 |
| P2c | accounting、supply、其餘小模組 | 7–9 |
| P2d | legacy routers（多為不可委派標記） | 3–4 |
| P3 | 前端約 150 處角色判斷改 `can()`、基線歸零 | 4–5 |
| **合計** | | **82–101** |

### 10.7 其他更正
- 動作詞彙為 **19 個**（含 `menu`）：§2 的『原 18 個』是歷史敘述，§5／§6 內的『18』一律指『不含 menu 的 18 個舊詞彙』，現行以 19 為準。

### 10.8 確認期與「有效最高管理者人數」的到期重新判斷（審查 5）
- 申請時：`approvals_required` ＝ 1（目前有效最高管理者 ≥ 2 位，核准者必須是**申請人以外**、仍在職的最高管理者）或 0（只有一位 ⇒ 單人路徑：必填原因＋確認期＋畫面警告＋通知並留紀錄）。
- **到期（及每次判斷是否生效）時重新計算**：`eligible` ＝ 目前在職、非申請人的最高管理者人數。
  - 票數已足 ⇒ 生效。
  - 票數不足但 `eligible = 0`（唯一可核准的人離職／停用）⇒ **退回單人路徑**：視為已滿足、寫稽核 `perm.single_superadmin_fallback`、通知所有最高管理者與申請人，並在『變更紀錄』標記；不會永遠卡著。
  - 票數不足且 `eligible ≥ 1` 但沒人核准 ⇒ 繼續待生效，直到**到期後 14 天**自動作廢（事件 `superseded`＋原因『逾期未核准』，通知申請人），之後可重新申請。
  - 核准票若來自事後停用的帳號 ⇒ 該票作廢（到期時只計目前仍有效的票）。
- 這些判斷在 `config_ledger` 的 `in_effect`／`approve` 內做一次，權限與設定共用。
