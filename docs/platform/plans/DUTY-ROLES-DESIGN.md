# 職責角色化設計（Duty-based roles）

> 狀態：**設計草案（已納入使用者 2026-10-06 對 12 題的裁示，見「使用者裁示」節），無程式**。分支 `wip/t45-duty-roles-design`，基底 `origin/wip/t43-base`（`ee3a778c2`）。
> 需求來源：使用者 2026-10-03 裁示（路線 A→職責角色化→B；「職責角色化 5 件方向同意」；不變式：superadmin 每個功能都要能使用）；2026-10-05 第 42 班財務角色上線；2026-10-06 再次要求：**一人多職責角色、變更權限必須填原因（稽核）、每季權限盤點**。
> 前置閱讀：`USER-DECISIONS.md` 列 88–89、`FINANCE-ROLE-GOLIVE.md`、a3 方案 `wip/t34-user-permissions-proposal-a3:docs/platform/plans/USER-PERMISSIONS-PROPOSAL.md` §9（本文把 §9 的草案落成可實作設計，並以第 42 班後的實況修正）。
> 數字取自基底 `ee3a778c2` 的 `backend/`（不含測試）：`has_finance_access／has_cashier_access` 呼叫 78 處、`user_has_module(` 36 處、`require_any_module(` 115 處、寫死 `"admin"` 的角色判斷約 73 處。

---

## 0. 一頁結論

1. **做什麼**：把「角色」從「5 種粗分類＋每人一份勾選」改成「**職責角色＝一組權限**，使用者綁多個角色，生效權限＝（各角色聯集 ∪ 個人加項）− 個人扣項」。改權限必填原因並寫不可竄改的變更紀錄；每季出盤點清單，逐人確認或回收。
2. **怎麼不出事**：分三步（R1 資料模型＋遷移＋稽核、R2 盤點／回收／職務分離、B 逐領域取代 admin 直通）。R1 **上線瞬間每個人的生效權限逐人相等**（遷移前後用腳本比對，不相等就不上線），且**不改任何既有權限判斷的行為**。
3. **關鍵設計選擇**：不新增一套「權限引擎」，而是**沿用現有模組鍵（`users.modules` 的鍵）當作權限單位**，只改「生效模組清單」的算法，接在已經存在的唯一縫 `helpers/auth.effective_modules()`／`_require_user()`；`users.modules` 保留為「個人例外」，`users.role` 保留為「基礎類別」。因此**零欄位刪除、回滾＝回程式**。
4. **superadmin 不變式**：生效權限的算法寫死 superadmin ⇒ 全部（含未來新增的鍵）；任何職責角色、例外、盤點、職務分離規則都**不能**降低 superadmin。守門見 §7。
5. **使用者裁示（2026-10-06）已回覆 12 題**，其中 3 題與本文原建議不同（Q4 原因只對高敏感必填、Q5 允許負向例外、Q8 不設 superadmin 使用規範），已改寫 §2–§7；衍生的 4 題（N1–N4）亦已於同日裁示（見裁示表，§10.1 標為已解決）。

---

## 使用者裁示（2026-10-06，12 題；經 hichan-69 轉達）

| 題 | 裁示 | 與原建議 | 落點 |
|---|---|---|---|
| Q1 誰管理使用者／角色 | a：**只有 superadmin** | 相同 | §2.4、§2.8 |
| Q2 綁定角色數 | a：**不限** | 相同 | §2.1 |
| Q3 預設角色清單 | a：照草稿；**財務與出納合併** | 相同 | §2.3 |
| Q4 變更原因 | b：**只有高敏感權限必填，其餘選填** | **不同**（原建議一律必填） | §2.4（明列高敏感清單） |
| Q5 個人例外 | b：**允許減（負向例外）** | **不同**（原建議只加不減） | §2.1、§2.2、§3、§4.1、§7 |
| Q6 授予限制 | a：操作者須持有被授予的鍵（superadmin 不受限） | 相同 | §2.4（因 Q1 僅 superadmin 管理，此條只在未來放寬管理者時生效） |
| Q7 盤點 | a：每季、superadmin 執行 | 相同 | §2.5 |
| Q8 superadmin 使用規範 | c：**不規範**（不做「日常禁用／登入通知／至少 2 位」） | **不同** | §2.8（只保留既有「至少一位在職有 Email 的 superadmin」） |
| Q9 職務分離 | b：**提示不擋** | 相同 | §2.6（不做嚴格模式） |
| Q10 保留期 | a：7 年 | 相同 | §2.4 |
| Q11 離職回收 | a：停用即自動回收；重新啟用＝新綁定且需原因 | 相同 | §2.7 |
| Q12 遷移 | a：保留現行權限 | 相同 | §3.2 |
| N1 扣「部分」強制程度的鍵 | a：**允許，並警告**（畫面標「部分生效」） | 同建議 | §2.2 |
| N2 高敏感清單 | a：**照 §2.4 提案，不含 `reports`** | 同建議 | §2.4 |
| N3 扣項期限 | a：**不設到期日**；季度盤點檢視 | 同建議 | §2.2、§2.5 |
| N4 一般變更無原因 | a：**盤點不補問** | 同建議 | §2.5 |

---

## 1. 現況（2026-10-06，第 42 班之後）

### 1.1 帳號模型
| 項目 | 現況 | 位置 |
|---|---|---|
| 角色 | `users.role` ∈ `superadmin／admin／sales／engineer／viewer／finance`（`VALID_ROLES`），單值 | `helpers/auth.py`、`db.py` users 表 |
| 權限勾選 | `users.modules` JSON 陣列（約 35 個模組鍵）；**`cashier／finance／financial_view` 三鍵已改由角色推導，勾選惰性保留在 DB** | `helpers/auth.effective_modules`、`user_has_module` |
| 角色樣板 | `ROLE_TEMPLATES`（與 `users.html` 的 `ROLE_MODULES` 同源）：新增使用者／快速套用時把預設模組填進勾選，**之後脫鉤** | `helpers/module_registry.py:83` |
| 自訂角色 | `system_settings.custom_roles`：名稱＋基礎角色＋模組清單，**只是樣板 chip，不是權限實體** | `routers/system.py:2625` |
| 模組守門 | `require_any_module(user, keys, label)` 與 `_require_user(..., module=)`：superadmin 直通，其他人要持有其一 | `helpers/auth.py` |
| 角色寫死 | 約 73 處 `role in ("superadmin","admin")`／`_require_admin`／`_is_manager`：**admin 直通**（一般管理 M 類，第 42 班刻意不動） | 各模組 |
| 財務判斷 | `has_finance_access`＝角色 ∈ {superadmin, finance}；`has_cashier_access` 同；`user_has_module(財務三鍵)` 同；`finance_usernames()`、`finance_recipient_emails()` 給通知用 | `helpers/auth.py` |
| 前端 | `canSeeFinancial／canFinanceRole／isAdminPlus` 與後端「逐字相同」，登入／`me`／選單回傳 `effective_modules` | `case-management-core.js`、`cashier.js`、`reports.js` |
| 變更稽核 | 一般 `audit_log`；第 42 班只對「角色／財務三鍵」變更寫 `user.role_change`（前後值，**無原因欄**） | `routers/auth.py` 約 1620 行 |
| 使用者範圍 | 正式機在職 11 人（第 42 班前）：admin 4、superadmin 2、sales 2、viewer 2、engineer 1 | 記憶／BACKLOG |

### 1.2 已知痛點（驅動本設計）
1. `admin` 一詞承載太多職責（人員、設定、案件、叫料、承攬、報表…），第 42 班只切走金額面，其餘仍直通。
2. 職務（出納、採購、工務…）無處表達：只能「選一個粗角色＋逐項勾」。
3. 樣板與使用者脫鉤：公司要全體調整某職務的權限，只能逐人改。
4. 變更紀錄沒有「原因」、沒有「生效權限差異」、沒有定期盤點；離職／調職沒有回收流程。
5. 第 42 稽核 (h)：只有一位財務帳號時，其匯款差額只能由 superadmin 核可（職務分離的副作用，目前屬預期）。

### 1.3 不能破壞的既有契約
- superadmin 每個功能都能用（含財務／出納判斷、選單、API、PDF、通知；modules 為空也要通過）。
- 第 42 班財務規則：財務／出納只屬角色 `finance` 與 superadmin（admin／sales 的舊勾選惰性、不刪）。
- 一般管理（M 類）admin 直通暫不動，直到 B 階段逐領域處理。
- 簽核人／申請人例外、案件擁有者範圍（`row_access`）不屬權限清單，維持。
- 模組停用／未授權（`core.registry.module_states`）與使用者權限正交：模組停用時有勾也看不到。

---

## 2. 目標模型

### 2.1 名詞
| 名詞 | 定義 |
|---|---|
| **權限鍵（permission）** | 沿用現有模組鍵（`cashier`、`finance`、`case_manage`、`procurement`…）。R1 **不新增鍵**；B 階段若需拆細（例如把「人員管理」從 admin 直通拆出）才加，且加鍵＝向下相容。 |
| **職責角色（duty role）** | 具名的一組權限鍵，由 superadmin 在畫面維護。有 `key`（穩定識別）、名稱、說明、權限鍵清單、是否系統預設、是否啟用、`version`（每次改定義加 1）。 |
| **綁定（binding）** | 使用者 ↔ 職責角色，多對多；記錄誰、何時、為什麼綁。 |
| **個人加項（adds）** | 既有 `users.modules`：在角色聯集之外**額外加**的鍵。 |
| **個人扣項（subtracts，負向例外）** | **新**（Q5 b）：從角色聯集與加項中**扣掉**的鍵；存新表 `user_perm_subtracts`（§3.1）。不得針對 superadmin 使用者；R1 不得針對財務三鍵（見 §2.2）。 |
| **基礎類別（base category）** | 既有 `users.role`。R1 起意義改為「預設綁哪些職責角色、與哪些寫死判斷相容」；**寫死判斷仍讀它**（直到 B 階段取代）。`superadmin` 類別＝不變式觸發點。 |
| **生效權限（effective permissions）** | ＝（superadmin ⇒ 全部）否則 ∪(綁定且啟用角色的權限鍵) ∪ extras，再套用第 42 班的「財務三鍵由角色推導」。 |

### 2.2 生效權限算法（單一縫）與負向例外
```
effective(user):
  if user.role == 'superadmin':          return ALL_KEYS            # 不變式：忽略任何角色／加項／扣項；含未來新增的鍵
  keys  = ∪ roles(user).permissions      # 只計 active 角色
  keys ∪= adds(user)                     # = users.modules（個人加項）
  keys −= subtracts(user)                # 新：扣項最後套用、優先於一切授予
  keys  = apply_finance_rule(keys, user) # 第42班：財務三鍵只由 finance 基礎類別／財務角色決定（見下「限制」）
  return keys
```
**優先序（固定、可預期）**：`扣項 > 加項 ＝ 角色授予`。「扣」永遠贏，即使之後角色定義又把該鍵加回來，扣項仍然生效（畫面顯示「被個人扣除」）。

**衝突與邊界案例**
| 情況 | 處理 |
|---|---|
| 同一人同一鍵既在加項又在扣項 | 儲存時 400（一個鍵只能有一種個人狀態）；改狀態＝同一次請求內先移除舊的再設新的 |
| 角色定義後來移除該鍵，而此人有扣項 | 扣項成「閒置」：不影響生效；使用者畫面與盤點標示「閒置扣項」，可一鍵清除 |
| 扣項針對 superadmin 使用者 | **拒絕**（400）；算法也忽略（即使資料庫被硬塞）；守門題見 §7 |
| 扣項針對只經「基礎類別直通」取得的功能（admin 直通的一般管理，約 73 處寫死判斷） | **R1 無法讓它失效**：扣項只影響以「模組鍵」判斷的功能（`require_any_module`／`user_has_module`）。畫面對每個鍵顯示「強制程度」：**完整**（所有判斷都經模組鍵）／**部分**（尚有 admin 直通旁路，B 階段才完整）；扣「部分」的鍵時警告（見 N1） |
| 扣項針對財務三鍵（`finance／cashier／financial_view`） | R1 **不開放**：`has_finance_access` 仍讀 `users.role`，扣了不會生效，反而造成假安全感；B（財務領域）改讀生效權限後才開放。要拿掉某人的財務權，仍用「改基礎類別／解綁財務角色」 |
| 扣掉 `dashboard` 等基本鍵 | 允許；若導致登入後無可進入頁面，儲存時警告（不擋） |
| 扣項對象被停用 | 回收時連同扣項一併清除（§2.7） |
| 快取 | 鍵含：綁定、角色 `version`、`users.modules` 雜湊、扣項雜湊；任一項變動即失效 |

- 這個函式取代 `helpers/auth.effective_modules(role, modules)` 的內部（**簽章與回傳型別不變**），`_require_user`（auth.py:284–295）、登入（`routers/auth.py:476`）、`/api/me`、`/api/platform/menu` 全部經它，**不需逐一改呼叫端**。
- 財務三鍵（過渡）：R1 `has_finance_access` **仍讀 `users.role`**；R1 的「財務」職責角色在遷移時對 `role='finance'` 的使用者自動綁定，使兩者同步。真正改成「讀生效權限」放在 B 階段的財務領域。
- 快取為行程內，不跨行程共享（正式機單行程）。

### 2.3 預設職責角色（草稿，可在畫面改）
| 角色 key | 名稱 | 權限鍵（草稿） | 說明 |
|---|---|---|---|
| `finance` | 財務（含出納） | `dashboard, quotation, case_manage, customer, reports, finance, financial_view, cashier, work_log, daily_task` | = 現 `ROLE_TEMPLATES["finance"]`；目前財務／出納合併（第 42 班裁示） |
| `sales` | 業務 | `dashboard, quotation, case_manage, customer, project_approve_biz, work_log, daily_task, map` | = 現 sales 樣板 |
| `engineer` | 工務 | `dashboard, case_manage, project_approve_eng, equipment, work_log, daily_task` | = 現 engineer 樣板 |
| `procurement` | 採購 | `dashboard, procurement, inventory, equipment, work_log, daily_task` | 新；叫料建立／到貨確認一般管理仍走 admin 直通，B 階段才改 |
| `pm` | 專案管理 | `dashboard, case_manage, project_approve_eng, project_approve_biz, reports, work_log, daily_task` | 新；與 admin 樣板的差別＝不含人員／設定 |
| `sysadmin` | 系統管理 | `dashboard, settings`（以及使用者管理相關鍵）；**不含任何金額鍵** | 新；人員與設定 |
| `viewer` | 唯讀 | `dashboard` | = 現 viewer |
| `admin_legacy` | 管理員（過渡） | = 現 `ROLE_TEMPLATES["admin"]` | 遷移時給既有 admin，使其生效權限不變；B 完成後評估移除 |

> 注意：`ROLE_TEMPLATES` 目前也被 `users.html` 的 `ROLE_MODULES`、`/api/modules/catalog` 共用，且有「superadmin 預設模組集合相等」題守；R1 要把它改為「**系統預設角色的種子**」，單一來源由 DB 角色表取代，前端 `ROLE_MODULES` 改讀 API。

### 2.4 變更原因與紀錄（Q4 b：只有高敏感必填）
**高敏感權限清單（提案，使用者可增刪，見 N2）**
| 類別 | 內容 | 理由 |
|---|---|---|
| 金額與付款 | 模組鍵 `financial_view`、`finance`、`cashier` | 第 42 班財務角色範圍 |
| 系統管理 | 模組鍵 `settings`（系統設定）、`audit_log`（全系統操作軌跡）、`module_versions` | 可改全站設定／看全部軌跡 |
| 薪資個資 | 模組鍵 `payslip`（勞報單） | 個人所得與簽回檔 |
| 身分類別 | 基礎類別變更涉及 `superadmin／finance／admin`（升或降）；新增／移除 superadmin；停用／啟用 superadmin 或持高敏感權限者 | 權限升級路徑 |
| 角色層級 | 修改「含上述任一鍵」的職責角色定義；綁／解「含上述任一鍵」的角色；對上述鍵設定個人加項或扣項 | 間接取得 |

- 註：模組目錄沒有「使用者管理」鍵——使用者／職責角色管理本來就是 **superadmin 專屬**（Q1 a），不需列入。`reports`（營運報表）不列為高敏感（使用者已裁示 admin／`reports` 持有者可看，見 FINANCE-ROLE-GOLIVE），要列入見 N2。

**原因欄規則**
- **高敏感變更**：`reason` 必填（去頭尾空白後 ≥4 字、≤200 字），**伺服器端強制**：缺原因 ⇒ 400，不靠前端。
- **其他變更**（一般角色綁定、一般鍵的加／扣項、一般角色定義）：原因**選填**；有填就記錄。
- 是否高敏感只看**差異內容**（生效權限前後差異含上列鍵，或屬上表身分／角色層級動作），由伺服器計算，不信任前端旗標。
- 沒有「系統自己改」的旁路：背景遷移、離職回收由系統觸發者，原因由系統填固定格式（如 `系統：離職回收（停用帳號）`），不得由使用者端點傳入。
- **變更紀錄表 `permission_changes`**（只增不改不刪，見 §3）每筆含：時間、操作者、對象、種類（`bind／unbind／role_def／adds／subtract／unsubtract／base_role／deactivate／activate／migrate／review`）、**生效權限前後差異**、`high_sensitivity` 旗標、原因（可空）、來源 IP、對應 `audit_log` id。**負向例外**每次設定／解除各寫一筆，差異欄顯示「移除 X（個人扣項）」。
- **不可自改**：操作者不得變更自己的角色／加扣項／基礎類別。Q1 a 使管理者只有 superadmin，實際只約束 superadmin 自己（其權限本為全部，自改無實質意義：**允許但記錄**，不另發通知，Q8 c）。
- **授予限制（Q6 a）**：操作者必須持有被授予的鍵才能授予；superadmin 不受限。目前管理者只有 superadmin，此條是未來放寬管理者時的護欄，R1 先實作並測試。
- **高敏感通知**：高敏感變更信件通知所有 superadmin（走 `mail_types` 登記、system 類鎖定，沿用 `notify_matrix.MAIL_OFF_LOCKED` 作法）。
- **保留**：紀錄與盤點存檔保留 **7 年**（Q10 a）；清理只能由專用工具、需 superadmin 且寫入清理紀錄，系統不自動刪。
- **紀錄保護**：沒有任何更新／刪除端點；`permission_changes` 加 SQLite 觸發器 `BEFORE UPDATE／DELETE ⇒ RAISE(ABORT)`（備份還原是整庫替換，不受影響；7 年清理工具需先停用觸發器並留痕）。

### 2.5 季度權限盤點
- **開立**：每季第一個工作日（用 `helpers/business_days`）排程在 08:00 自動開一份盤點（`2026Q4`…），通知 superadmin；也可手動開立。
- **內容**：每位在職使用者一列：基礎類別、綁定角色、個人例外、**生效權限鍵**（分「一般」與「高敏感」）、最後登入日、距今天數、是否 90 天未登入、是否同時持有衝突組合（§2.6）、與上一季的差異。
- **決定**：每列「保留」「調整」「回收」；調整／回收走一般變更流程（同樣必填原因，原因預填「季度盤點」）。每列記錄決定者與時間。
- **結案**：全部列有決定才可結案；結案後凍結（快照＋決定存檔、可匯出 PDF／Excel）；逾 30 天未結案每週提醒 superadmin。
- **不阻擋登入／作業**：盤點是治理流程，不是門檻；未結案不影響任何人使用系統。

### 2.6 職務分離規則（Q9 b：只提示、不擋）
- 規則表（superadmin 可在畫面設定，預設一組）：**衝突組合**＝同一人不宜同時持有 A 與 B。預設：「`cashier`（登錄付款）＋ 核可匯款差額」（第 42 班已合併，現況靠稽核兜底）。既有的「自我核可拒絕」行為維持不變。
- **只有提示模式**：綁定／加項時顯示警告、季度盤點標示「衝突持有」；**不擋存檔**（不做嚴格模式；日後要擋再另案裁示）。只有一位財務時，其造成的差額仍只能由 superadmin 核可（42 稽核 (h)，維持）。
- superadmin 不被規則限制（不變式），仍在盤點標示。

### 2.7 離職／調職
- **停用帳號** ⇒ 同一交易內：清除全部綁定、個人加項與**個人扣項**（保留紀錄＝`permission_changes` 前後差異）、使登入階段失效、寫變更紀錄（原因必填或固定「離職」）；**不刪帳號**（歷史單據的建立人／簽核人要對得上）。
- **調職** ⇒ 換綁角色（解舊角色＋綁新角色可在同一動作、同一原因），舊角色權限即時消失（下次請求生效；快取以 `version`＋綁定變更失效）。
- **重新啟用＝新綁定**（Q11 a）：啟用後該人沒有任何角色與例外；再綁角色視為新的綁定，**高敏感者需原因**，其餘選填。
- 提醒：每月第一個工作日列出「近 30 天停用／調職」與「90 天未登入但仍有高敏感權限」給 superadmin。

### 2.8 與 superadmin
- superadmin 不由職責角色授予，只由基礎類別 `superadmin` 決定；其生效權限＝全部，**不可被扣項、角色、盤點回收降低**（§2.2、§7）。
- **使用者裁示 Q8 c：不設 superadmin 使用規範**——**不做**「日常禁用」「登入通知另一位」「至少兩位」，也不為此新增任何通知。
- 只保留**既有**不變式：至少一位在職且有 Email 的 superadmin（沿用 `last_superadmin_blockers`，並擴大到「改基礎類別」「停用」兩個動作，以免新畫面造成最後一位被移除）；新增／移除 superadmin 屬高敏感變更（原因必填、通知所有 superadmin，見 §2.4）。

---

## 3. 資料模型與遷移

### 3.1 新表（core migration；只加表，不改既有表）
```
duty_roles
  id INTEGER PK, key TEXT UNIQUE NOT NULL, name TEXT NOT NULL, description TEXT DEFAULT '',
  permissions TEXT NOT NULL DEFAULT '[]',      -- JSON 陣列（模組鍵）
  is_system INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
  version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL

user_duty_roles
  user_id INTEGER NOT NULL, role_id INTEGER NOT NULL,
  granted_by INTEGER, granted_at TEXT NOT NULL, reason TEXT DEFAULT '',   -- 高敏感角色的綁定由應用層強制非空
  PRIMARY KEY (user_id, role_id)

permission_changes                              -- 只增（觸發器擋 UPDATE／DELETE）
  id INTEGER PK, ts TEXT NOT NULL, actor_id INTEGER, actor_username TEXT, actor_display TEXT,
  kind TEXT NOT NULL,                           -- bind／unbind／role_def／extras／base_role／deactivate／activate／migrate／review
  target_type TEXT NOT NULL,                    -- user／role
  target_id INTEGER NOT NULL, target_label TEXT,
  added TEXT NOT NULL DEFAULT '[]', removed TEXT NOT NULL DEFAULT '[]',   -- 生效權限差異（鍵清單）
  before_json TEXT, after_json TEXT,            -- 綁定／例外／基礎類別的前後值
  high_sensitivity INTEGER NOT NULL DEFAULT 0,
  reason TEXT NOT NULL DEFAULT '', ip TEXT DEFAULT '', audit_id INTEGER   -- 原因：高敏感變更由應用層強制非空（Q4 b）

user_perm_subtracts                            -- 負向例外（Q5 b）
  user_id INTEGER NOT NULL, perm_key TEXT NOT NULL,
  set_by INTEGER, set_at TEXT NOT NULL, reason TEXT DEFAULT '',
  PRIMARY KEY (user_id, perm_key)

access_reviews        (id PK, quarter TEXT UNIQUE, opened_at, opened_by, closed_at, closed_by, status)
access_review_items   (review_id, user_id, snapshot_json, last_login, decision, decided_by, decided_at, note,
                       PRIMARY KEY (review_id, user_id))
sod_rules             (id PK, name, key_a, key_b, mode 'warn'|'strict', active)
```
- 歸屬模組：這是 L0／L1 公共能力（使用者／權限屬核心），表與 migration 放 `core`（`register("core", …)`），**不屬任何業務模組**；業務模組只呼叫 `helpers.auth` 的穩定函式。CORE CHANGELOG 登記為 L1 新增（向下相容），照 PLAYBOOK §G6 用 `(next)` 佔位。
- 不改 `users`：`role`、`modules`（＝個人加項）原封不動。**不新增 `users` 欄位**；扣項放新表，**舊版程式不認識扣項**（回滾見 §3.3）。

### 3.2 遷移（零損失）
1. **種子**：寫入 §2.3 的系統預設角色（`is_system=1`）。
2. **綁定原則**：只在「該人現行生效集合恰好等於某系統角色」時自動綁該角色（`role=finance`→財務、`admin`→管理員過渡、`sales／engineer／viewer`→同名；`superadmin` 不綁，只記 `migrate`）；其餘一律不綁（見下點）。**不得**因綁角色讓任何人的生效權限變大。
3. **作法**：以每人**目前實際生效權限**為準，計算「該人現行生效集合 E」，再決定綁定：若 E ⊆ 某系統角色的權限且 E ⊇ 該角色權限 ⇒ 綁該角色、例外清空；否則 ⇒ **不綁角色、把 E 全部留在例外**（例外＝今天的勾選）。換言之遷移後 `effective(user) == E` 對每個人成立；「更貼近職責角色」的整理由 superadmin 在畫面逐人做（走原因＋稽核）。
3b. **負向例外的遷移影響**：遷移**不建立任何扣項**（`user_perm_subtracts` 為空表），不改變任何人的生效權限；Q12 a 的「逐人相等」不受 Q5 b 影響。
4. **驗證腳本**（唯讀，可在正式機跑）：`tools/duty_roles_equivalence.py`：遷移前匯出每人生效集合 JSON；遷移後重算；逐人比對，**任一人不等 ⇒ 結束碼非 0**，輸出差異；上線步驟檔以它為關卡（比照 `finance_role_impact_report.py`）。
5. **冪等**：種子以 `key` upsert（不覆蓋 superadmin 已改過的角色定義：`updated_at ≠ created_at` 即跳過）；自動綁定只在 `user_duty_roles` 該使用者無任何列時執行；重跑不重複。回報未完成時依 migration 慣例回原因字串、不記版號。
6. **每人一筆 `migrate` 變更紀錄**（原因＝系統固定文字「第一次遷移：保留現行權限」，差異為空，`high_sensitivity=0`）。

### 3.3 回滾
- **程式回滾**：舊版程式不讀新表，仍讀 `users.role`／`users.modules`；而遷移**未改這兩欄**，故回滾＝回程式，行為立即還原。
- **資料回滾**：新表可保留（舊程式忽略）；不需 down migration。
- **扣項的雷（新增）**：舊版程式不認識 `user_perm_subtracts`，回滾後被扣掉的鍵會「復活」。**回滾第 0 步必須跑 `tools/duty_roles_export_effective.py`**：把每人**最終生效集合**（已含扣項）寫回 `users.modules`，舊程式即得到相同結果；步驟檔列為強制關卡，並在回滾前列出「有扣項的人」給 superadmin 看。
- **其他的雷**：R1 之後若有人用新畫面改了權限，**改的是新表**，舊程式看不到。對策：R1 期間「個人例外」的編輯仍**同步寫回 `users.modules`**（雙寫），角色綁定變更則在回滾 SOP 中以腳本 `tools/duty_roles_export_effective.py` 把每人生效集合回寫成 `users.modules`（回滾前跑）。步驟檔列為回滾第 0 步。
- **備份**：遷移前依既有流程備份 DB；`permission_changes` 隨主庫備份（不需新分流）。

---

## 4. 介面草圖

### 4.1 使用者管理（`users.html`，編輯視窗）
```
┌ 編輯使用者：王小明 ───────────────────────────────┐
│ 帳號 wang   姓名 王小明   Email …   部門 …          │
│ 基礎類別  [ 業務 ▾ ]   （影響預設與舊版相容判斷）   │
│ 職責角色  [✓ 業務] [✓ 採購] [ 財務 ] [ 工務 ] …    │
│           （可多選；滑過顯示該角色的權限清單）      │
│ 個人例外  ▸ 展開：每個權限鍵三態 [角色預設｜＋加｜－扣]  │
│           －扣：標示「強制程度：完整／部分」；財務三鍵灰色│
│           （R1 不開放扣）；扣項在生效預覽中為刪除線   │
│ ── 生效權限（唯讀預覽）─────────────────────────   │
│ 一般：案件管理、報價、客戶、叫料…                   │
│ 高敏感：（無）                                      │
│ ⚠ 衝突提示：…（若命中職務分離規則）                 │
│ 變更原因 * [____________________________]          │
│                      [取消]  [儲存（寫入稽核）]    │
└────────────────────────────────────────────────┘
```
- 沒有改權限的存檔（改姓名、Email）不出現原因欄；有權限差異時顯示原因欄：**差異含高敏感權限 ⇒ 必填（紅星）**，否則選填。
- 扣項：被扣的鍵在預覽顯示刪除線與「個人扣除」徽章；角色後來又授予該鍵時顯示「角色已授予，但被個人扣除」；閒置扣項灰色、可一鍵清除。
- 財務三個舊勾選維持灰色＋說明；改為「由職責角色『財務』決定」。

### 4.2 職責角色管理（新頁，僅 superadmin；系統設定下）
列表（名稱、說明、人數、權限鍵數、高敏感標記、啟用）→ 編輯：權限鍵多選（沿用 `/api/modules/catalog` 分組）、說明、啟用；儲存必填原因並顯示「將影響 N 位使用者：新增 X、移除 Y」預覽。系統預設角色可改權限但不可刪。

### 4.3 權限變更紀錄（新頁，superadmin）
篩選（對象、操作者、種類、期間、是否高敏感）；每列顯示差異（＋鍵／－鍵）與原因；匯出 Excel。唯讀。

### 4.4 季度盤點（新頁）
進行中的盤點：表格每人一列＋決定下拉＋備註；頂部統計（待決定 N／回收 M）；結案按鈕；歷次盤點列表（唯讀存檔）。

### 4.5 選單
「使用者管理」旁新增「職責角色」「權限變更紀錄」「權限盤點」，三者皆僅 superadmin；superadmin 選單必定顯示（不變式題守）。

---

## 5. 各模組影響清單

| 區域 | 影響 | R1 要改？ |
|---|---|---|
| `helpers/auth.py` | `effective_modules()` 內部改算法；新增 `effective_permissions(user)`、角色快取；`has_finance_access`／`has_cashier_access` R1 **不動**（仍讀 `role`） | 是 |
| `routers/auth.py` | 建立／修改使用者端點：偵測生效權限差異、高敏感時強制 `reason`、扣項設定／解除、寫 `permission_changes`＋`audit_log`；停用帳號回收；新增角色／綁定／紀錄／盤點 API（建議放新 router，避免 auth.py 再膨脹） | 是 |
| `routers/system.py` `custom_roles` | 舊「自訂角色」端點保留相容 1 版，內部轉為建立 `duty_roles`（基礎類別欄忽略）；遷移把既有自訂角色轉成職責角色（`is_system=0`） | 是 |
| `helpers/module_registry.py` | `ROLE_TEMPLATES` 降為種子；`/api/modules/catalog` 的 `roleTemplates` 改回傳 DB 角色；題守「superadmin 預設集合相等」保留 | 是 |
| `users.html`／`users.js` | §4.1；`ROLE_MODULES` 改讀 API | 是 |
| 直接讀 `user["modules"]` 的呼叫端 | `modules/analytics/api/dashboard.py`（6 處）、`modules/case/api/case_action_items.py`（3 處）、`modules/crm/api.py`（2 處）、`helpers/custom_modules.py`（2）、`helpers/custom_files.py`（1）、`db.py` 的 v84 回填 | **要查**：這些讀的是 `_require_user` 回傳的 `modules` JSON，若縫補在 `_require_user` 就自動正確；`db.py` 啟動回填讀 DB 原始值，R1 需確認不與新算法衝突（回填屬 V9 凍結遷移，不動，只確認冪等） |
| `routers/mail_settings.py` | `last_superadmin_blockers` 擴大涵蓋「改基礎類別、停用」；`mail_recipient_overrides` 的 `roles` 目前比對基礎類別，R1 維持，R2 評估支援職責角色 | R1 小改 |
| `helpers/email_notify.py`、`mail_types` | 新增高敏感權限變更信、盤點開立／逾期信、離職回收月報；登記於 `mail_types`（system 類、鎖定） | R2 |
| `helpers/notify_matrix.py` | 新信件進 `MAIL_OFF_LOCKED`（與 hichan-68 的第二階段矩陣檔同檔，**併入前要對一次**） | R2 |
| `modules/case`、`arap`、`subcontract`、`accounting`、`payroll`、`analytics` | R1 **不改**（行為不變）；B 階段逐領域把 F／M 類判斷改讀生效權限 | B |
| 前端 `canSeeFinancial／canMarkPayment／canFinanceRole／isAdminPlus` | R1 不動；B 階段改讀登入回傳的 `effective modules` 鍵，不再比對角色字串 | B |
| `core/menu.py`、`/api/platform/menu` | 已用 `effective_modules`；新三頁登錄為僅 superadmin | 是 |
| 建包／更新包 | `tools/duty_roles_equivalence.py`、`duty_roles_export_effective.py` 進 `backend/tools`；步驟檔模板新增「等值驗證」關卡 | 是 |
| 備份／還原 | 新表自然隨主庫；`DR-SOP.md` 補一行 | R1 文件 |
| `docs` | `MODULE-GUIDE`（新增權限判斷必含 superadmin 直通）、`CORE-SPEC`（使用者裁示表加列）、`MONEY-FLOWS`（F 類判斷來源改為生效權限，B 階段） | 是 |

---

## 6. 分階段交付

| 階段 | 內容 | 驗收（關卡） | 風險／回滾 |
|---|---|---|---|
| **R1** 資料模型＋遷移＋稽核＋畫面 | §3 新表與種子；`effective_modules` 改算；使用者管理多角色畫面；原因必填；`permission_changes`；變更紀錄頁；`duty_roles_equivalence` 工具 | 等值驗證逐人相等（正式機形狀＋合成多形狀）；既有全部權限測試 0 紅；superadmin 守門；原因必填的雙向測試；不可竄改觸發器測試 | 中；回程式＋（若已用新畫面改過）先跑回寫腳本 |
| **R2** 盤點／回收／職務分離／通知 | §2.5–2.7；排程；信件登記；匯出 | 排程在假日表上的開立日測試；停用帳號全回收測試；SoD 提示模式（存檔不被擋、盤點標示）測試 | 低（純新增） |
| **B1** 人員／設定領域 | 把 admin 直通的「使用者管理、系統設定、模組狀態」改讀 `sysadmin` 角色權限 | 領域演練：持／不持權限雙向 + superadmin | 中～高：擋錯人；逐領域單獨一班、可單獨回滾 |
| **B2** 案件／叫料領域 | 案件編輯、叫料建立／送審／到貨、案件列範圍 | 同上；案件擁有者範圍不變 | 同上 |
| **B3** 承攬／供應領域 | 承攬派發、供應商、進貨 | 同上 | 同上 |
| **B4** 評估移除 `admin` 基礎類別 | 全領域改完、`admin_legacy` 無人綁定 | 使用者裁示後才做；`users.role` 的 `admin` 值保留相容 | — |

- 每個 B 子階段結束時，`role in ("superadmin","admin")` 寫死判斷數量必須下降並記錄在 CHANGELOG（用靜態掃描計數，見 §7）。
- 每階段獨立上線，不綁班次；R1 與 R2 之間可穿插其他班次。

---

## 7. 測試與守門計畫

### 7.1 R1
| 守門 | 內容 |
|---|---|
| **等值題**（核心） | 合成多種使用者形狀（各基礎類別、有／無舊勾選、惰性財務勾選的 admin／sales、空 `modules` 的 superadmin、`role='finance'`）→ 遷移前後 `effective_permissions` 逐人相等；另跑一份「正式機形狀」固定 fixture（11 人，模組取自 BACKLOG 計數）。 |
| **superadmin 不變式** | ① `effective(superadmin, modules=[])` ⊇ 目錄全部鍵（含測試中動態新增的鍵），且不受任何扣項影響；② 對每個 F／M 類端點 superadmin 通過（沿用 `test_finance_role` 的靜態題＋擴充）；③ 掃描新增的權限判斷函式必含 superadmin 直通（AST 掃描）；④ 角色停用、角色清空、例外清空、SoD 嚴格模式、盤點回收皆不影響 superadmin。 |
| **原因規則（Q4 b）** | 高敏感變更（清單見 §2.4，含角色定義含高敏感鍵、對高敏感鍵設加／扣項）缺原因／過短／全空白 ⇒ 400 且資料不變；非高敏感變更不填原因 ⇒ 200；紀錄 `high_sensitivity` 旗標正確（由伺服器算，傳入旗標被忽略）。清單內每個鍵各一題（防清單漏鍵）。**突變檢查**：拿掉強制 ⇒ 變紅。 |
| **負向例外（Q5 b）** | ① 優先序：角色授予＋加項−扣項，扣項贏（含角色後來又授予）；② 同鍵同時加與扣 ⇒ 400；③ 閒置扣項不影響且被標示；④ **superadmin**：對其設扣項 ⇒ 400，且資料庫硬塞扣項時 `effective(superadmin)` 仍＝全部；⑤ 財務三鍵 R1 設扣項 ⇒ 400；⑥ 停用帳號清除扣項；⑦ 設／解扣項寫 `subtract／unsubtract` 紀錄且差異正確；⑧ 快取：設／解扣項後下一次請求即反映；⑨ 回寫腳本：有扣項者回寫後以舊程式讀取＝新算法生效集合。 |
| **紀錄不可竄改** | 嘗試 `UPDATE`／`DELETE permission_changes` ⇒ 觸發器 ABORT；沒有對外更新端點（路由掃描）。 |
| **不可自改** | 非 superadmin 改自己的角色／加扣項 ⇒ 403；superadmin 改自己 ⇒ 成功並留紀錄（不另發通知，Q8 c）。 |
| **授予限制（Q6 a）** | 非 superadmin 授予自己未持有的鍵 ⇒ 403（以測試中暫時放寬的管理者驗證）。 |
| **多角色聯集** | 兩角色聯集、重疊鍵、停用角色不計、刪綁定即失去、角色定義改動即時反映（`version` 失效快取）、個人加項只加、扣項見下列「負向例外」題。 |
| **最後一位 superadmin** | 改類別／停用最後一位在職有 Email 的 superadmin ⇒ 400（既有不變式；**不**新增「至少 2 位」「登入通知」類檢查）。 |
| **介面快照** | `helpers.auth` 新增公開函式進 L1 快照；`effective_modules` 簽章不變（題守）。 |
| **前端** | 使用者管理 e2e：多選角色、預覽即時更新、原因欄出現條件、衝突提示；superadmin 選單必有三新頁。 |
| **回滾演練** | 遷移→用新畫面改幾個權限→跑回寫腳本→以舊程式讀 `users.modules` ⇒ 與新算法生效集合相等。 |

### 7.2 R2
盤點開立日（假日順延）、冪等（同季只開一份）、逾期提醒節流、停用回收的原子性（半途失敗全撤回）、SoD 提示（不擋）、通知登記守門（`test_mail_registry`）。

### 7.3 B 各階段
每領域：持權限／不持權限／superadmin／原 admin 四方矩陣；掃描該領域 `role in ("superadmin","admin")` 殘留數歸零；現有領域測試 0 紅；正式機形狀演練（依 `drill`）。

### 7.4 測試成本控管
新守門盡量用純函式＋小 fixture，避免拉長建包時間（預算 ≤30 分）；等值題與 superadmin 掃描為靜態／快速測試。

---

## 8. 風險與對策

| 風險 | 對策 |
|---|---|
| 遷移讓某人權限變大／變小 | 等值驗證為上線關卡；遷移以「現行生效集合」為準（§3.2 第 3 點）。 |
| 管理者只有 superadmin（Q1 a）⇒ 日常改權限都要找 superadmin | 使用者已接受；B1 之前不放寬。日後放寬時由 Q6 a 的授予限制擋權限升級。 |
| 扣項造成假安全感（admin 直通旁路仍在） | 「強制程度」標籤＋警告；財務三鍵 R1 不開放扣；B 各階段把旁路改讀生效權限後標籤轉「完整」。 |
| 權限升級（有人授予自己更大權限） | 不可自改；授予者必須持有被授予的鍵（Q6）；高敏感變更通知 superadmin。 |
| 前後端判斷逐字重複（約 100 處寫死） | R1 不動；B 階段每領域前後端一起改，並以靜態掃描計數防回彈。 |
| 變更紀錄量 | 每次變更一列、保留 7 年（Q10 a，已裁示）；盤點快照 JSON 每季約 11 人，量小。 |
| 與第二階段通知矩陣併檔衝突 | `notify_matrix.py`／`mail_types` 的新增放 R2，併入前與矩陣視窗對齊。 |
| 單一財務帳號的差額（第 42 稽核 h） | 本設計不改變；Q9 讓使用者決定是否維持「只能 superadmin 核可」。 |

---

## 9. 不在範圍
- 資料列層級（`row_access`：案件擁有者、部門範圍）改為可設定（另案）。
- 簽核流程（簽核層、代理人）的權限（已有獨立機制）。
- 自訂模組（`helpers/custom_modules.py`）內部的角色設定（由各自定義管理；本設計只讓其「持有模組鍵」判斷自動讀生效權限）。
- 外部身分（SSO／AD）、兩步驟驗證（另案）。
- 移除 `admin` 基礎類別（B4，需另行裁示）。

---

## 10. 題目紀錄（目前無未決題）

### 10.1 由 Q4 b／Q5 b 衍生的 4 題（**已解決**：使用者 2026-10-06 全選 a；以下保留題目作紀錄）

1. **N1 扣項對「強制程度：部分」的鍵**（admin 直通旁路尚未收斂，扣了不會完全擋住）：
   (a) 允許，畫面明示「部分生效」並警告（建議；符合「可以減」的需求）
   (b) R1 只開放「強制程度：完整」的鍵，其餘灰色，B 階段逐步開放。
   **建議 (a)**。
2. **N2 高敏感清單**（§2.4 提案：`financial_view／finance／cashier／settings／audit_log／module_versions／payslip`＋身分類別動作）：
   (a) 照提案（建議） (b) 再加入 `reports`（營運報表含財務數字） (c) 縮小為只含財務三鍵＋`settings`。
   **建議 (a)**。
3. **N3 扣項是否要有到期日（到期自動恢復）**：
   (a) 不需要，扣項長期有效，由季度盤點檢視（建議） (b) 可選設到期日（例如暫時收回）。
   **建議 (a)**。
4. **N4 非高敏感變更原因為選填時，季度盤點是否補問**：
   (a) 不補問（建議，符合 Q4 b） (b) 盤點時列出「無原因的一般變更」請 superadmin 補註（可略過）。
   **建議 (a)**。

### 10.2 原 12 題（已裁示；實際答案見文首「使用者裁示」表，以下保留當時的選項與建議作紀錄）

> 回答方式：每題選一個選項即可；未答的題以「建議」為預設。

1. **誰能管理使用者／職責角色？**
   (a) 只有 superadmin（建議 R1；最安全，但 superadmin 日常要用）
   (b) superadmin ＋ 持「系統管理」職責角色者（可管理一般使用者，**不可**授予財務類／系統管理／superadmin 鍵，也不可改 superadmin 帳號）
   **建議 (a)**；B1 時再依實際負擔改 (b)。

2. **一個人可以綁幾個職責角色？** (a) 不限（建議，兼任常見）(b) 最多 3 個。**建議 (a)**。

3. **預設職責角色清單**是否照 §2.3（財務含出納合併、業務、工務、採購、專案管理、系統管理、唯讀、管理員過渡）？
   (a) 照草稿，之後在畫面改（建議）(b) 出納與財務拆成兩個角色（需先推翻 2026-10-05 的合併裁示）(c) 你給名單。**建議 (a)**。

4. **變更原因規則**：(a) 一律必填 ≥4 字（建議）(b) 只有高敏感權限必填，其餘選填 (c) 全選填。**建議 (a)**。

5. **個人例外是否允許「減」（負向例外）**？(a) 只加不減（建議；規則簡單、可預期）(b) 允許減（例如角色給了但此人不要）。**建議 (a)**。

6. **授予限制**：(a) 操作者必須自己持有被授予的鍵，否則不能授予（建議；防權限升級，superadmin 不受限）(b) 不限制。**建議 (a)**。

7. **盤點頻率與執行人**：(a) 每季，由 superadmin 執行（建議）(b) 每季，另指定一位非 superadmin 的主管執行（superadmin 的權限由另一位 superadmin 覆核）(c) 每半年。**建議 (a)**。

8. **superadmin 使用規範**：(a) 日常禁用、**登入即通知另一位 superadmin**、至少 2 位（建議）(b) 只要求至少 2 位，不通知 (c) 不規範。**建議 (a)**；自改權限同樣通知。

9. **職務分離（SoD）**：預設規則「登錄付款者不得核可自己登錄的匯款差額」（目前靠稽核兜底）——
   (a) 維持現況（可同人，稽核＋通知兜底；只有一位財務時由 superadmin 核可）
   (b) **提示模式**：綁定／盤點時警告，不擋（建議）
   (c) **嚴格模式**：同一人不得同時持有；只有一位財務時必須由 superadmin 核可（等於把 42 稽核 (h) 變成硬規則）。
   **建議 (b)**。

10. **變更紀錄與盤點存檔保留期**：(a) 7 年（建議，與帳務保存一致）(b) 永久 (c) 3 年。**建議 (a)**。

11. **離職回收的觸發**：(a) 停用帳號當下自動回收全部角色與例外，不可復原但可重新綁定（建議）(b) 停用只凍結、保留角色，重新啟用即還原 (c) 停用後 30 天才回收。**建議 (a)**；重新啟用視同新綁定，需原因。

12. **R1 上線時既有帳號的處理**：(a) 遷移保留每人現行權限（綁定只在能完全吻合系統角色時自動綁，其餘留在例外；建議，零風險）(b) 遷移後全部由 superadmin 在畫面逐人整理，期間**不改任何人權限**（等同 a，但要求限期整理）(c) 一次依 §2.3 強制套用（會改變部分人的權限，**不建議**）。**建議 (a)**，並訂「R1 後 30 天內由 superadmin 整理完例外」的提醒。

---

## 11. 附：與既有文件的關係
- 取代 a3 `USER-PERMISSIONS-PROPOSAL.md` §9 的「R1／R2」細節；§9 的 5 件方向（職責角色＝一組權限、使用者綁角色、權限變更稽核、季度清單、離職／調職回收、superadmin 作 break-glass、職務分離）全部落在 §2。
- 使用者原話中的「**變更權限需要填原因**」在 a3 §9.6 第 3 題為「建議必填」；本文把它提升為伺服器端強制（Q4 可改）。
- 2026-10-05 財務角色合併（出納＋財務）仍有效；本設計 R1 不改其行為，只把它表達為一個職責角色。
- `FINANCE-ROLE-GOLIVE.md`「已知的後續」自核自匯風險 ⇒ 對應 §2.6／Q9。
