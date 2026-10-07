# R2 第 2–4 步設計（職責角色化；第 46 班；**設計稿，無程式**）

> 作者 b5（hichan-eb 視窗）｜2026-10-08｜分支 `wip/t46-r2-design`｜基底 `origin/platform`（bde21e2b6，第 45 班 dc4e2e42 已上線）
> 範圍：R2 第 2 步（`users.html` 整合＋舊 PUT 與扣項衝突＋唯讀報表工具改讀生效權限＋8a）、第 3 步（停用即回收＋刪除清孤兒）、第 4 步（完全吻合者自動綁定＋30 天整理提醒）。第 5–9 步不在本稿。
> 依據（已裁示，**本稿不重開**）：`plans/DUTY-ROLES-DESIGN.md`（Q1–Q12、N1–N4）、`plans/R2-STEP1-EQUIV-ROLLBACK-T45.md`（D1–D5）。這兩份目前只在分支 `wip/t45-duty-roles-design`／`wip/t45-r2-step1`（尚未進 platform），本分支一併帶入 `docs/platform/plans/` 供對照。
> 已核對現況：R2 第 1 步 `wip/t45-r2-step1-impl` **已在 origin/platform**（核心 1.118：檢查器 v2、`duty_roles_rollback.py`、D4、D5 影子模式 `finance_via_effective`＝預設關）。正式機 12 人、0 綁定、0 扣項。

## 0. 一頁結論

1. **順序**：第 2 步 → 第 3 步 → 第 4 步，**各自獨立一班上線**（不要三步同班）。第 2 步純介面＋拒絕規則，不動任何人的生效權限；第 3 步是**第一個不可逆**的資料動作；第 4 步是純加法。
2. **每一步的共同關卡**（R2-STEP1 §3.1）：套用前 `snapshot --schema 2` → 套用 → `verify`（結束碼 0）→（第 3、4 步）資料動作後 `verify --plan`。任何一步 `verify` 非 0 ⇒ 停、走 L0 回滾。
3. **第 3 步前置**：`duty_roles_rollback.py` 已在正式機（第 45 班已出貨 ✔）；停用回收的 `before_json` 要完整保存才能 L0 還原。
4. **第 4 步前置**：第 2 步的確認畫面已上線、第 3 步已跑（停用者先排除）；D5 仍在 `shadow`（`on` 需使用者核准，本稿不含切換）。
5. **權限影響**：第 2 步不放寬任何權限，只新增**拒絕**（舊 PUT 勾到被扣的鍵）；第 3 步**減少**停用者權限（本來停用者就不能登入，故實質可見面不變）；第 4 步對 `role=finance` 者自動綁「財務」角色——**生效集合不變**（完全吻合才綁），非 finance 一律須 superadmin 逐筆確認。三步都不改 superadmin 可見面（E6）。
6. **待使用者裁示**：§7 共 7 題，每題一個決定，皆附建議。

## 1. 現況盤點（讀碼，2026-10-08）

| 項目 | 現況 | 位置 |
|---|---|---|
| 職責角色服務層 | `bind_role／unbind_role／set_subtract／unset_subtract／update_role`，含高敏感原因必填、授予限制、`permission_changes` 只增 | `backend/helpers/duty_roles.py`（354 行） |
| 路由 | `/api/duty-roles*`（角色、綁定、扣項、變更紀錄），僅 superadmin | `backend/routers/duty_roles.py` |
| 介面 | 獨立頁 `duty-roles.html`（16 KB）；`users.html`（80 KB）**完全不認識**角色／扣項 | `frontend/pages/` |
| 舊 PUT | `PUT /api/users/{id}` 可任意改 `role`／`modules`，不看扣項；扣項靜默勝出（使用者看到勾選了卻沒權限） | `routers/auth.py:1558` |
| 停用 | `PATCH /api/users/{id}/active` 只翻 `active`；綁定、扣項、`users.modules` 全保留；`_require_user` 以 `u.active=1` 擋（停用後 session 實質失效） | `routers/auth.py:1695`、`helpers/auth.py:462` |
| 刪除 | `DELETE /api/users/{id}` 刪 `users`＋`sessions`；**不清** `user_duty_roles`／`user_perm_subtracts`（孤兒）；有 FK 關聯資料時 409 | `routers/auth.py:1660` |
| 後端模板 | `effective_modules` **沒有**「modules 為空就套基礎類別模板」的邏輯；該回退只存在 `users.html` 前端（`ROLE_MODULES`，約 L1008） | `helpers/auth.py:344`、`users.html` |
| 唯讀報表 | `tools/audit_account_permissions.py`、`tools/finance_role_impact_report.py` 讀原始 `users.modules`，看不到角色綁定 | `backend/tools/` |
| 第 1 步成果 | 檢查器 v2（`verify --plan／--finance-cutover`、`diff`、`catalog-check`、`scan-finance`）、`duty_roles_rollback.py`（L0）、D5 影子旗標 | `backend/tools/`、`helpers/auth.py` |

**讀碼發現的風險**（影響本稿設計）：
- **R-烘焙**：`users.html` 編輯時，若 `users.modules` 為空會以基礎類別模板填入勾選（前端回退）；整合角色預覽後，若把「生效清單」當勾選送回，角色權限會被複製進個人加項，之後改角色或設扣項即失效。第 2 步必須讓前端**只送原始勾選**（見 §2.3）。
- **R-空模組停用**：第 3 步清空 `users.modules` 後，重新啟用者在後端是零權限，但 `users.html` 打開編輯會用基礎類別模板「預填」——superadmin 一按儲存就靜默發回整套模板。重新啟用流程必須顯式處理（見 Q4）。

## 2. 第 2 步：`users.html` 整合＋舊 PUT 衝突＋工具讀生效權限（＋8a）

### 2.1 範圍
| # | 項目 | 說明 |
|---|---|---|
| 2a | 編輯視窗加「職責角色」「個人扣項」「生效權限預覽」 | 依 DUTY-ROLES-DESIGN §4.1 草圖；角色多選、三態鍵（角色預設／＋加／－扣）、預覽即時更新（呼叫既有 `effective_preview`，伺服器算，前端不自己算） |
| 2b | 變更原因欄 | 有權限差異才出現；差異含高敏感鍵 ⇒ 必填紅星（伺服器端仍強制，缺 ⇒ 400） |
| 2c | 舊 `PUT /api/users/{id}` 與扣項衝突 | `body.modules` 含「目前被扣項扣掉的鍵」⇒ **400**，訊息列出鍵與「請先在扣項解除」（建議；見 Q1） |
| 2d | 唯讀報表工具改讀生效權限 | `audit_account_permissions.py`、`finance_role_impact_report.py` 改呼叫 `effective_modules(role, modules, user_id, conn)`（維持唯讀、維持 `--db`） |
| 2e | 8a：`permission_changes.audit_id` 填值＋`INSERT OR REPLACE` 靜態掃描守門 | 與 2a 同檔同函式（`duty_roles._record`／路由），分兩班會衝突；掃描守門是純測試 |
| 2f | 「強制程度」暫以固定警語（R1 已有）；逐鍵標籤留第 7 步 | 避免第 2 步膨脹 |
| 2g | 衝突提示（SoD）**不在本步** | 第 7 步 |

### 2.2 不做
- 不改任何權限判斷（`require_any_module`、`has_finance_access` 等一律不動）。
- 不新增表、不跑 migration（`audit_id` 欄 R1 已建）。
- 財務三鍵仍灰色不開放扣項（D5 `on` 之前）；顯示「由職責角色『財務』決定」。

### 2.3 設計重點
1. **前端只送原始勾選**：編輯視窗保存兩份狀態——`rawModules`（寫回 `users.modules`）與 `preview`（唯讀）。角色勾選／扣項走 `/api/duty-roles/bindings`、`/subtracts`，**不**經 `PUT /api/users`。存檔順序：先 `PUT /api/users`（基本資料／原始勾選）→ 再角色綁定差異 → 再扣項差異；任一步失敗即停並顯示已完成／未完成（沒有跨 API 交易，這點在 UI 明講）。
2. **原因欄對應**：同一次存檔的多個動作共用一個原因字串，逐筆寫入各自的 `permission_changes`。
3. **`last_superadmin_blockers`**（既有）涵蓋「改基礎類別」「停用」兩動作的呼叫點維持，不因新畫面少呼叫。
4. **前端回退修正**：`users.html` 對 `users.modules` 為空者的模板預填，限定在「新增使用者」；編輯既有使用者時空就是空（否則 R-空模組停用）。這是行為變更，列入使用者可見說明。
5. **工具讀生效權限**：新增 `--raw`（舊行為）旗標；預設改生效。輸出標頭註明口徑。

### 2.4 回滾
- 純前端＋拒絕規則＋工具：**程式回滾即還原**（L1），無資料動作；L0 不適用。
- 影子/旗標：不需要。但 2c 的拒絕規則給一個旗標 `system_settings.users_put_reject_subtracted`（預設**開**＝拒絕；設 `0`＝回舊行為），秒級退場（建議；風險小但屬登入後第一個可能擋住 superadmin 存檔的規則）。

### 2.5 影子模式
不需要。替代：上線後第一週，被 2c 拒絕的每一次在 `audit_log` 記 `user.put_rejected_subtract`（鍵、對象、操作者），供檢視是否誤傷。

### 2.6 權限影響
- 只有 superadmin 能進這個畫面（Q1 a，不變）。
- 新增拒絕：superadmin 以舊方式勾選被扣的鍵會被擋（過去默默無效）——**不放寬**。
- 工具改讀生效權限：稽核報告多顯示角色給的權限，屬資訊。

### 2.7 測試（純函式／小 fixture；全部合計目標 ≤ 1.5 分）
| 題 | 突變檢查 |
|---|---|
| PUT 勾到被扣的鍵 ⇒ 400 且 `users.modules` 不變；勾不衝突的鍵 ⇒ 200；旗標關 ⇒ 200（舊行為） | 拿掉衝突檢查 ⇒ 紅 |
| 編輯存檔**不烘焙**：e2e 綁角色後只改姓名存檔，`users.modules` 位元組相同 | 改成送生效清單 ⇒ 紅 |
| 原因規則：差異含高敏感 ⇒ 缺原因 400；一般差異無原因 200 | 取消伺服器檢查 ⇒ 紅 |
| 預覽與 `effective_modules` 一致（窮舉基礎類別×綁定×扣項） | 預覽自行計算 ⇒ 紅 |
| `audit_id` 填值：每筆 `permission_changes` 有對應 `audit_log` id | 不填 ⇒ 紅 |
| 靜態掃描：`permission_changes` 不得出現 `INSERT OR REPLACE`／`REPLACE INTO`（含 `backend/tools`、`tools/`） | 加一行 ⇒ 紅 |
| 工具：有綁定者的報表含角色鍵；`--raw` 不含 | — |
| e2e（-m e2e）：開編輯視窗 → 勾角色 → 預覽即時變 → 高敏感時原因欄必填 → 存檔 → 變更紀錄頁出現；空 modules 的既有使用者編輯**不**預填模板 | — |
| superadmin 不變式：對 superadmin 綁角色／設扣項 ⇒ 仍拒絕 | — |

### 2.8 上線步驟檔要點
快照→套用→`verify`（零差異）→ 手動驗：開一位使用者編輯、不改任何東西存檔，`users.modules` 不變（唯讀 SQL 比對）。

## 3. 第 3 步：停用即回收（Q11 a）＋刪除清孤兒（**不可逆**）

### 3.1 範圍
| # | 項目 | 說明 |
|---|---|---|
| 3a | `toggle_user_active`（停用）同一交易內：寫完整 `before_json`（基礎類別、原始勾選、綁定、扣項、`active`）→ 清綁定、清扣項、**清空 `users.modules`**（D3）→ 寫 `permission_changes`（kind=`deactivate`，原因＝系統固定「離職回收」）→ `active=0`。用 `core.txn`（單一交易，半途失敗全撤） | 重用 R2-STEP1 §4 L0 的還原格式 |
| 3b | 重新啟用 | **新綁定**（Q11 a）；基礎類別必須重新確認（D3）：`role=finance`／`superadmin` 者需確認才啟用，未確認 ⇒ 400；啟用後 `users.modules` 為空（見 Q4：是否預填模板） |
| 3c | 刪除使用者 | 同一交易清 `user_duty_roles`、`user_perm_subtracts`；`permission_changes` 保留（只增）；有 FK 關聯仍 409（不變） |
| 3d | 既有停用帳號（正式機現有停用者）的一次性回收 | **不自動**；提供計畫工具 `duty_roles_deactivated_plan.py`（唯讀，列出停用帳號仍有綁定／扣項／勾選者），由使用者決定是否套用（Q5） |
| 3e | 月提醒：近 30 天停用／調職、90 天未登入卻持高敏感權限（DUTY-ROLES-DESIGN §2.7） | 站內通知＋信，走 `mail_types` 登記；**可移到第 5 步**（盤點）一併，見 Q6 |

### 3.2 不做
- 不刪帳號、不改歷史單據的建立人／簽核人。
- 不碰 session（`_require_user` 已以 `u.active=1` 擋；另可在停用時 `DELETE FROM sessions`，列為建議，風險低）。
- 不改 `FINANCE_ROLES`、不動 D5 旗標。

### 3.3 回滾
| 層 | 動作 |
|---|---|
| **L0（首選）** | `duty_roles_rollback.py --snapshot S.json [--apply]`：依計畫白名單（被停用者）從 `before_json` 還原 `users.modules`、綁定、扣項、`active`；`--apply` 需使用者同意；只追加反向 `permission_changes`（綁定→回滾解除兩筆屬預期）。**第 3 步最重要的關卡：上線前在副本 DB 演練 L0 一次並留存輸出** |
| L1 | 程式回滾＋`duty_roles_export_effective.py`（R2 全程不寫 `users.modules`，3a 例外：停用者已被清空，回滾程式不會讓他們復活，因為 `active=0`） |
| L2 | 整庫還原（最後手段） |
- 工具守則不變：`--db` 必填、預設 dry-run、禁用 `INSERT OR REPLACE`。

### 3.4 影子模式
資料動作無法影子。替代：**兩段上線**——先上線 3c（刪除清孤兒；影響面極小，只動孤兒表）與 3a/3b 的「**dry-run 模式旗標**」`system_settings.deactivate_reclaim`：`off`（預設，行為同舊）／`log`（只寫將會回收的內容到 `audit_log`，不動資料）／`on`。第一班 `log` 觀察；使用者核准後下一班切 `on`。切 `on` 本身是改旗標（秒級）；但**已回收的資料靠 L0 還原**（旗標切回不會還原資料）。

### 3.5 權限影響
- 停用者本來不能登入，所以**可見面不變**；變化是「重新啟用後不再自動復原舊權限」（需重新授予）——這是 Q11 a 的本意，也是使用者最可能感受到的行為變更，需寫進使用者說明。
- E5（`users.modules`）自此步起第一次被系統改寫：驗證計畫白名單必須逐人列出清空內容（R2-STEP1 §8 D3 ①）。

### 3.6 測試
| 題 | 突變檢查 |
|---|---|
| 停用 ⇒ 綁定／扣項／勾選清空、`before_json` 完整、`permission_changes` 一筆、原因固定文字不可由請求傳入 | 漏清任一類 ⇒ 紅 |
| **原子性**：模擬中途失敗（monkeypatch 第二個 DELETE 丟例外）⇒ 全部回到停用前 | 不用交易 ⇒ 紅 |
| 重新啟用：`role=finance`／`superadmin` 未確認 ⇒ 400；確認後成功；啟用後無綁定、無扣項 | 取消確認檢查 ⇒ 紅 |
| 刪除清孤兒：無孤兒綁定／扣項；`permission_changes` 不減 | 不清 ⇒ 紅 |
| L0 往返：快照→停用→L0 `--apply`→`verify`（無計畫）＝0；L0 只動白名單內的人 | 多動白名單外一人 ⇒ 紅 |
| superadmin：停用 superadmin 仍受 `last_superadmin_blockers`＋內建 admin 不可停用；對 superadmin 不產生回收紀錄 | — |
| 旗標 `off` ⇒ 行為與現況逐字相同；`log` ⇒ 資料不變但有 audit | `log` 時偷偷改資料 ⇒ 紅 |
| 正式機形狀（12 人去識別化）演練：停用一位測試帳號→verify --plan＝0→L0→verify＝0 | — |
| e2e：users.html 停用／啟用按鈕流程與確認對話 | — |

### 3.7 上線步驟檔要點
副本 DB 演練 L0（留輸出）→ 快照 → 套用（旗標預設 off）→ `verify` → 使用者核准後把旗標改 `log` → 一週後檢視 audit → 再核准改 `on`（同一班或下一班）。每次改旗標寫稽核。

## 4. 第 4 步：完全吻合者自動綁定＋30 天整理提醒（純加法）

### 4.1 範圍
| # | 項目 | 說明 |
|---|---|---|
| 4a | 計畫工具 `duty_roles_autobind_plan.py`（唯讀，`--db`） | 對每位**在職、非 superadmin** 使用者，算現行 E1；**僅當 E1 ＝某系統角色權限集合（完全相等，D2）** 才列入。輸出兩份：**自動清單**（僅 `role=finance` 且吻合「財務」，D1）與**待確認清單**（其餘吻合者；含財務鍵角色的非 finance 者一律只能待確認） |
| 4b | 確認畫面（第 2 步的 users.html 上，或獨立「綁定確認」區） | superadmin 逐筆勾選後才綁；每筆各寫一筆 `bind` 紀錄（一般角色固定原因「第一次整理：保留現行權限」；含高敏感鍵者原因怎麼填見 Q7） |
| 4c | 自動綁執行：計畫檔 → 一支 `--apply`（需使用者同意）→ `verify --plan`（預期差異＝空；E1/E2/E3/E5 全不變，E2 順序差異只報 `orderOnly`） | 冪等：該使用者已有任何綁定即跳過 |
| 4d | 30 天整理提醒（Q12 a） | 上線滿 30 天仍有「可綁未綁」者 ⇒ 每週一封給 superadmin（節流、用 `business_days`、`mail_types` 登記、`MAIL_OFF_LOCKED` 不鎖） |

### 4.2 不做
- 不放寬為「⊇」(D2)；不替非 finance 者自動綁含財務鍵角色（D1）。
- 不自動綁停用者（第 3 步已回收；計畫工具排除 `active=0`）。
- 不綁 superadmin；不建立任何扣項。

### 4.3 回滾
- L0：`duty_roles_rollback.py` 以計畫批次標記＋`granted_at` 晚於快照為準解除綁定（R2-STEP1 §4）；因綁定是純加法且 E1 不變，回滾後 `verify` 應為 0。
- L1：程式回滾後舊程式忽略綁定表，行為不變（E5 未動）。

### 4.4 影子模式
天然影子：**先只跑 4a（唯讀計畫）一班**，把兩份清單貼回報資料夾給使用者看；使用者核准後才在下一班（或同班第二階段）`--apply`。正式機另在**副本**上做「計畫→apply→verify」演練（R2-STEP1 §6「正式機演練」，第 4 步唯一前置）。

### 4.5 權限影響
- 設計上**零變動**（完全相等才綁）；實際影響是之後「改角色定義」會同時改變所有被綁者的權限（這是職責角色的本意）——需在使用者說明明講：被綁後，改「財務」角色的鍵會影響所有綁定者。
- 含財務鍵角色綁給非 finance：E2 多財務鍵（僅資訊、`has_finance_access` 不變）；故只走確認、不自動。

### 4.6 測試
| 題 | 突變檢查 |
|---|---|
| 計畫：完全相等者列入；⊋/⊊ 者不列入（D2）；停用者、superadmin 不列入 | 放寬成 ⊇ ⇒ 紅 |
| 自動清單僅含 `role=finance`；非 finance 吻合「財務」者落待確認（D1） | 全自動 ⇒ 紅 |
| apply 後 `verify --plan`＝0（E1/E2 集合/E3/E4/E5）；`orderOnly` 只報資訊 | 綁定後多出一鍵 ⇒ 紅 |
| 冪等：重跑不重複綁；已有綁定者跳過 | — |
| 逐筆記錄：每綁一人一筆 `permission_changes`（kind=`bind`） | — |
| 正式機形狀 12 人 fixture：計畫輸出固定（去識別化 fixture 進 repo） | 某人多一鍵 ⇒ 計畫不再列入 |
| 提醒：同一週只寄一封、假日順延、全綁完停寄、`test_mail_registry` | — |
| superadmin 不變式（沿用） | — |

## 5. 各步共同事項

### 5.1 版本與登記（PLAYBOOK §G6）
- 核心 `helpers/duty_roles.py`／`routers/auth.py` 屬 L1：CORE CHANGELOG `## (next)`；介面快照 `core_bump.py --pending`（新增公開函式者）。
- `tools/duty_roles_*` 隨完整包出貨（`ship_tier` ③）；新工具列入步驟檔「新功能靜態存在」列。
- manifest 版本寫 `"next"`；`docs/quick/changelog.md` 加使用者向說明（停用不再自動復原權限等）。

### 5.2 與其他分支的衝突面
- `routers/auth.py`（PUT／active／DELETE）：目前無其他 t46 分支改動此段（`fix/login-return-to-hardening` 動 `login.html／auth-guard.js`，不衝突）。
- `users.html`（80 KB）：第 2 步大改；`wip/t46-payslip-impl-r1` 不動它。建議第 2 步開工前先把 `users.html` 角色/權限區塊抽成獨立片段（>40KB 拆檔慣例）以降低衝突，抽離本身列入第 2 步第一個提交（行為不變，可獨立驗證）。

### 5.3 測試成本
全部為純函式＋小 fixture＋少數 e2e，三步合計新增題預估 < 4 分鐘（第 2 步 e2e ≈ 2 題、第 3 步 ≈ 1 題）；不拉長 30 分建包預算。

## 6. 順序與估計
| 班 | 內容 | 先決 | 風險 |
|---|---|---|---|
| A | 第 2 步（含 8a） | 本設計裁示 Q1–Q3 | 低～中（拒絕規則可能擋 superadmin 存檔→旗標退場） |
| B | 第 3 步 3c＋旗標 `log` | A；`duty_roles_rollback.py` 在正式機 ✔；副本演練 L0 | 中（不可逆；`log` 階段先不動資料） |
| C | 第 3 步 `on`＋第 4 步 4a 計畫唯讀 | B 觀察期零異常；使用者核准 | 中 |
| D | 第 4 步 apply＋提醒 | C 計畫清單經使用者看過 | 低（純加法） |
（B、C 可視觀察期合併；絕不與 D5 `on` 切換同班，避免兩個權限相關變動疊加。）

## 7. 給使用者的問題（一題一決定）

| # | 題目 | 建議 | 影響 |
|---|---|---|---|
| **Q1**（第 2 步） | 舊 `PUT /api/users` 若勾到「已被個人扣掉」的鍵：**拒絕存檔（400，提示先解除扣項）**，或**允許存檔但警告**？ | 拒絕（附秒級退場旗標） | 拒絕 ⇒ 不再有「勾了卻沒權限」的假象；警告 ⇒ 沿用現況只是多一行字 |
| **Q2**（第 2 步） | 角色/扣項整合進 `users.html` 編輯視窗，**同時保留**獨立 `duty-roles.html`（角色定義維護）？ | 保留：users 頁管「人」，duty-roles 頁管「角色定義與變更紀錄」 | 不保留 ⇒ 第 2 步工作量約 +1 倍 |
| **Q3**（第 2 步） | 編輯**既有**使用者且 `modules` 為空時，前端是否仍用基礎類別模板預填？ | 不預填（只在新增使用者預填）；否則第 3 步清空後極易被一鍵復原 | 屬使用者可見行為變更 |
| **Q4**（第 3 步） | 停用者**重新啟用**後的權限起點：**(a) 全空，需重新授予**；或 **(b) 預填其基礎類別的預設模板，需 superadmin 確認後才生效**？ | (a)（最貼近 Q11 a「新綁定」）；(b) 較省事但等於把舊模板自動送回 | 影響離職回任的作業量 |
| **Q5**（第 3 步） | 正式機**現有**停用帳號若仍帶綁定/扣項/勾選：**一次性回收**（用計畫工具，需你核准），或**維持現狀**只對之後的停用生效？ | 先唯讀列清單（目前綁定為 0，多半只有勾選），清單看過再決定 | 回收是不可逆動作 |
| **Q6**（第 3 步） | 「近 30 天停用／調職、90 天未登入卻有高敏感權限」月提醒：**併入第 3 步**或**留到第 5 步（季度盤點）一起**？ | 留第 5 步（同批 `mail_types` 與矩陣對齊，避免兩次登記） | 併入 ⇒ 第 3 步多一個信件登記 |
| **Q7**（第 4 步） | 對「待確認」清單中**持高敏感鍵角色**者（如把「財務」綁給非 finance 者），逐筆確認的原因欄：**固定文字「第一次整理」即可**，或**每筆必須人工填原因**？ | 一般角色固定文字；含財務三鍵者人工填（符合 Q4 b：高敏感必填） | 影響確認作業量 |

> 另列待你知悉（非決策）：第 3 步是 R2 第一個不可逆動作，建議採 `log`→`on` 兩段上線（§3.4）；D5 `finance_via_effective` 的 `on` 切換仍須你另行核准，本稿不含。

## 8. 已知未驗證
- 正式機現有停用帳號數量與其殘留綁定/勾選未直接讀取（待 `catalog-check`／快照）。
- `users.html` 空 `modules` 回退的確切行號與觸發條件是讀碼推論，第 2 步開工第一件事用 e2e 釘住。
- 「停用時 `DELETE FROM sessions`」是否有副作用（例如工作階段稽核）未查；列為建議、非必要。
- 4d 提醒的 `mail_types` 與 `notify_matrix` 對齊視窗未確認是否已併入。
