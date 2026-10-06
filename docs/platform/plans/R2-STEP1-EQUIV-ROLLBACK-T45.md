# R2 第 1 步：等價／回滾衛生（第 45 班設計，無程式）

> 狀態：**設計／分析稿，無程式、未跑測試**（測試鎖被第 44 班佔用）。分支 `wip/t45-r2-step1`，基底 `origin/wip/t45-duty-roles-design`（設計 `DUTY-ROLES-DESIGN.md`，12 題＋N1–N4 已裁示）。
> 讀碼基準：`origin/platform` `03656587`（含第 43 班 R1：`helpers/duty_roles.py`、`routers/duty_roles.py`、`backend/tools/duty_roles_equivalence.py`、`duty_roles_export_effective.py`）。
> 正式機基準：第 43 班上線後＝12 人、0 綁定、0 扣項。⚠ 本稿**沒有讀到正式機快照內容**，12 人／0 綁定取自主持轉述，由正式機視窗拍快照時核對。第 43 班步驟檔的 `duty_before_43.json` 是「R1 之前」基準，**不是 R2 基準**；R2 基準每次動手前重拍（§3）。
> 標 **【裁示】** 者涉權限或金額可視，需使用者決定（彙整於 §8）。

---

## 0. 一頁結論

1. R1 的關卡（`duty_roles_equivalence.py snapshot|verify`）只證明「R1 程式上線＝零行為變更」。R2 第 2–9 步會真的建立綁定、清除權限、改變判斷來源，R1 工具不夠用：只比 `effective_modules()` 的**有序清單**；不看 `_require_user` 給後端守門用的那份；不看財務判斷；不認「預期內的差異」；回滾工具只寫回 `users.modules`、不拆綁定。
2. 本步交付：①等價的精確定義（§1）②檢查器 v2 設計（§2）③快照→動作→比對流程（§3）④三層回滾（§4）⑤更新包清單（§5）⑥測試計畫（§6）⑦R2 第 2–9 步順序與相依（§7）⑧待裁示（§8）。
3. 原則：**R2 全程不清、不改 `users.modules`**（維持 R1 §6.1「加項＝既有勾選、不雙寫」）。綁定在綁定當下是純加法，且在「角色權限 ⊆ 現有權限」時對生效權限為空操作；所以「綁定」可逐人證明等價，「清理例外」不做。舊程式只讀 `users.modules`，因此回滾仍可用。

---

## 1. 「等價」的定義

對每位使用者 u，動作前（快照 S）與動作後（現況 N），下列六個面向都必須相同：

| # | 面向 | 取法 | 比較 |
|---|---|---|---|
| E1 | 生效權限集合 | `set(helpers.auth.effective_modules(role, modules, user_id, conn))` | 集合相等（順序只報資訊） |
| E2 | 守門視圖 | `_require_user` 回傳的 `user["modules"]`（＝`resolve_raw_modules` 套用後的原始勾選；`require_any_module`、`user_has_module`（非財務鍵）與直讀者看的是這份） | 集合相等 |
| E3 | 財務能力判斷 | `has_finance_access`、`has_cashier_access`、`can_see_financial`（以 `{role, modules}` dict 呼叫） | 布林相等 |
| E4 | 基礎類別與在職 | `users.role`、`users.active` | 相等（非預期變動算差異） |
| E5 | 原始勾選 | `users.modules` 解析後排序 | R2 全程相等（除非該步白名單明列）；這是舊程式回滾可用的前提 |
| E6 | superadmin | E1 等於快照（維持 R1 現狀）；superadmin 帳號不得有綁定／扣項列 | 逐人 |

- **E1 與 E2 要分開**：R1 的 `_require_user` 把角色鍵併進 `user["modules"]`，但 `effective_modules` 另外把財務三鍵從非財務基礎類別剝掉。把含財務三鍵的職責角色綁給非財務類別者，E1、E3 不變，E2 會多出 `cashier／finance／financial_view`。目前直讀 `user["modules"]` 的呼叫端（`modules/analytics/api/dashboard.py`、`modules/case/api/case_action_items.py`、`modules/crm/api.py`、`routers/search.py`、`routers/custom_records.py`、`routers/map_points.py`、`helpers/custom_modules.py`、`helpers/custom_files.py`）經 grep 沒有一處以財務三鍵判斷，所以今天不外露；但這是潛在洩漏路徑，檢查器主動比 E2，日後有人新增直讀才會被擋住。
- **順序**：R1 檢查器連順序都比（`list(after) != list(before)`）。R2 綁定會改順序（`resolve_raw_modules` 在原順序後附加角色鍵）。建議「集合相等＝等價，順序差異只列資訊（`orderOnly`）」。前提是沒有消費者依賴清單順序：選單分組由 `module_registry.MODULES` 決定，讀碼看起來成立，但列入 §6 測試；測試不過就回報，不硬做。
- **預期差異**：第 3 步（停用回收）與第 9 步（B）本來就要改權限。等價判準改為「每人 `lost`／`gained` 恰好等於計畫白名單」，多一個少一個都 FAIL（§2.3）。
- **範圍外**：快照後新建的帳號（列資訊）；`last_login`、session；`permission_changes` 新增列（反而要驗只增不減）。

### 1.1 現有檢查器的盲點（讀碼確認）
1. 只比 E1，沒有 E2／E3／E5。
2. `legacy_effective()` 內嵌第 42 班演算法——對「R1 前後」正確，對「R2 前後」不適用（R2 的 before 已是 R1 程式在跑）。
3. 不記角色定義（`duty_roles.permissions`／`version`／`active`）：有人改角色權限，所有綁定者的權限跟著變，快照分不出是角色改了還是人改了。
4. 不記 `permission_changes` 筆數與觸發器；回滾後無法證明紀錄沒被刪。
5. `export_effective.py` 只回寫 `users.modules`，不拆綁定；寫回值是「（原勾選∪角色）−扣項」，不是還原原狀（§4）。
6. 讀 raw 的工具（`tools/audit_account_permissions.py`、`tools/finance_role_impact_report.py`、`db.py:3872` 的 v84 回填）看不到角色綁定；R2 綁定出現後，其輸出會漏算角色給的權限。非守門路徑，但稽核報告會失真，第 2 步一併處理。

---

## 2. 檢查器 v2 設計（擴充 `tools/duty_roles_equivalence.py`，不換檔名）

### 2.1 子命令
```
duty_roles_equivalence.py snapshot --out S.json [--db P] [--schema 2]
duty_roles_equivalence.py verify   --snapshot S.json [--db P] [--plan PLAN.json] [--json-out R.json]
duty_roles_equivalence.py diff     --a S1.json --b S2.json [--plan PLAN.json]    # 離線，不開 DB
```
- `--schema 1`（預設，第 43 班用法）行為與輸出不動，舊步驟檔不失效；R2 一律 `--schema 2`。
- 只做 SELECT。E1／E2／E3 用 `helpers.auth`／`helpers.duty_roles` 的唯讀函式取得：R2 的 before 是現行 R1 程式，以它為「動作前的事實」是正確的；它不能證明新程式正確，所以另有 §2.4 的獨立重算。
- 結束碼：`0` PASS；`1` 有差異（不可放行／要回滾）；`2` 用法或讀檔錯誤；**新增 `3`**＝結構問題（紀錄表筆數減少、append-only 觸發器不見、superadmin 帳號出現綁定／扣項、快照 schema 不符）。1 與 3 都不可放行，步驟檔分開處理。

### 2.2 快照內容（schema 2）
```
{ "schema": 2, "takenAt": "...", "dbPath": "...", "codeVersion": {...},
  "roles": { "<key>": {"id","permsSha","perms":[...],"active","version","isSystem"} },
  "users": { "<id>": {"username","role","active","rawModules":[sorted],
                      "bindings":[roleKeys sorted],"subtracts":[sorted],
                      "effective":[sorted],      // E1
                      "guardView":[sorted],      // E2
                      "caps":{"finance":b,"cashier":b,"seeFinancial":b}} },   // E3
  "log": { "permissionChangesCount": n, "permissionChangesMaxId": m, "triggers": ["...no_update","...no_delete"] } }
```
- 帳號名沿用 R1 快照格式與回報資料夾慣例；**進 repo 的 fixture 不得含真實帳號名**（§3.2）。
- `permsSha`：角色權限排序後雜湊，用來區分「角色被改」與「人被改」。

### 2.3 verify 的判定
1. **角色定義**先比：與快照 `roles` 不同 ⇒ 計畫檔 `roleChanges` 有列才算預期；否則直接 FAIL 並指出是角色定義變動（不再逐人洗出一堆差異）。
2. **逐人 E1–E6**：差異集合必須等於 `PLAN.users[<id>]` 的 `{lost, gained}`；沒有計畫檔＝全員零差異。計畫檔以 `id` 為鍵、用鍵清單、不接受萬用字元。
3. **結構（結束碼 3）**：紀錄筆數與 `maxId` 不得小於快照；兩個觸發器必須存在；superadmin 帳號不得有綁定／扣項列。孤兒列（user 不存在，`DELETE /api/users` 目前會留下，R1 已知限制）在第 3 步修正前只以資訊列出，不算失敗。
4. 快照後新增帳號：資訊。快照有、現在沒有：差異（帳號不見了）。

### 2.4 獨立重算（防自證）
檢查器內嵌純函式 `spec_effective(role, raw, active_bound_role_perms, subtracts)`，逐字照 `DUTY-ROLES-DESIGN §2.2` 與 R1 §6.1（superadmin 不經角色；扣項最後套；財務三鍵由基礎類別決定），**不呼叫 `helpers.auth`**。verify 同時算 `helpers.auth` 與 `spec_effective`，不同 ⇒ FAIL（「程式與規格不一致」）。它抓的是「資料碰巧沒變、程式卻改壞」這一類。

### 2.5 計畫檔（PLAN.json）
- 第 3 步（停用回收）、第 4 步（自動綁定）由各自的計畫工具產出；**同一份計畫檔**既給套用步驟執行、也給 verify 驗證。驗證只看結果（DB 狀態），不看執行日誌。
- 第 4 步綁定的計畫預期**零差異**（`lost`／`gained` 皆空）——綁定只是把已有權限標成角色來源，驗的就是這點。

---

## 3. 流程：快照→動作→比對

### 3.1 通用流程（R2 每一步上線都照做，寫進該班步驟檔）
| # | 時點 | 動作 | 判準 |
|---|---|---|---|
| 1 | 套用前（唯讀） | 用**暫存新包**內的工具 `snapshot --schema 2`（舊安裝目錄不一定有 v2；第 43 班已用此法）；DB 備份走既有 `Backup-DatabasesOnline` | 人數＝在職＋停用總數；`bindings`／`subtracts` 與上一班結束時一致（R2 開工前＝0／0） |
| 2 | 套用（含 migration） | 照 `apply_update.ps1` | — |
| 3 | 套用後（唯讀） | `verify --snapshot S.json [--plan]` | 結束碼必須 0；1／3 ⇒ 停下、走 §4、回報差異 |
| 4 | 資料動作（僅第 3、4 步） | 用計畫檔執行，再 `verify --plan` | 同上 |
| 5 | 留存 | 快照與 `--json-out` 放正式機回報資料夾（沿用 `duty_before_43.json` 作法），檔名帶班次與時間（由 `date` 產生） | — |

### 3.2 R2 基準
- 基準＝**R2 第一個上線班次的套用前快照**（預期 12 人、0 綁定、0 扣項；系統角色種子 8 個：finance、sales、engineer、procurement、pm、sysadmin、viewer、admin_legacy，皆 `version=1`）。之後每班的「套用前快照」＝上一班的「套用後快照」＋該班計畫；**不得拿更早的快照跨班比對**，否則中間合法的變動會被誤判成差異。
- 12 人固定 fixture（進 repo）：只放 `id`、`role`、`active`、`modules`，帳號名去識別化；來源是正式機快照，由正式機視窗產出去識別化版再進 repo，本稿不產。

---

## 4. 回滾程序（三層，由輕到重）

| 層 | 何時用 | 動作 | 驗證 |
|---|---|---|---|
| **L0 邏輯回滾（首選）** | 只有 R2 資料動作（綁定／回收）出問題，程式沒壞 | 新工具 `duty_roles_rollback.py --snapshot S.json [--apply]`：①預設 dry-run，列出將解除的綁定（以計畫檔批次標記＋`granted_at` 晚於快照為準，不靠猜）、將還原的 `users.modules`／`users.active`（僅限計畫白名單內的人）②`--apply`＝單一交易（`core.txn.begin_write`）③每筆還原**追加**一列 `permission_changes`（原因固定「系統：R2 回滾（批次 X）」；不刪不改既有紀錄） | `verify --snapshot S.json`（無計畫檔）必須 0；紀錄筆數只增不減 |
| **L1 程式回滾** | 程式有問題，或 L0 失敗 | 第 0 步先 dry-run `duty_roles_export_effective.py`（列出有綁定／扣項者，尤其有扣項者給使用者看）→使用者同意才 `--apply`（寫回 `users.modules`）→依既有 `rollback_update.ps1` 回程式。R2 全程不清 `users.modules`，多數情況 export 結果等於原勾選（空操作） | 回滾後以舊程式讀庫，`diff --a S_before --b S_after` 比 E1／E2／E3 |
| **L2 整庫還原** | 資料庫損毀等最後手段 | 還原套用前的 DB 備份。**代價**：備份之後的所有業務資料遺失，需使用者決定 | 同 L1 |

要點：
- 第 3 步（停用回收）清綁定與扣項後**不可逆**，所以計畫工具執行前必須把被清掉的內容完整寫進 `permission_changes.before_json`，L0 才有東西可還原；`duty_roles_rollback.py` 必須在第 3 步上線**之前**就已在正式機。
- append-only 與回滾：回滾只能追加反向紀錄、不能刪紀錄；稽核上會看到「綁定→回滾解除」兩筆，屬預期。
- `INSERT OR REPLACE` 可繞過 append-only 觸發器（R1 已知限制，第 8 步補掃描）：L0 工具禁止對 `permission_changes` 用 `INSERT OR REPLACE`／`REPLACE INTO`，並進 §6 靜態掃描。
- 含資料動作的班次，步驟檔必須同時寫「快照檔位置」「L0 指令」「何時改用 L1」，形式與第 43 班步驟 4 相同。

---

## 5. 更新包清單（`tools/duty_roles_*`）

- 出貨途徑：`backend/tools/**` 依 `ship_tier` 為③（完整包），**不能走單模組包**；工具隨完整包的 `payload/backend/tools/` 進正式機。第 43 班已出貨 `duty_roles_equivalence.py`、`duty_roles_export_effective.py`。

| 檔 | 狀態 | 用途 | 何時進包 |
|---|---|---|---|
| `duty_roles_equivalence.py` | 已出貨（R1）→ 擴充 v2，v1 用法不動 | 快照／驗證／離線 diff | R2 第一個上線班次 |
| `duty_roles_export_effective.py` | 已出貨（R1）→ 行為不改，dry-run 輸出補列「綁定含高敏感鍵者」 | L1 第 0 步 | R2 第一個上線班次 |
| `duty_roles_rollback.py` | **新** | L0 邏輯回滾 | 第 3 步之前必須已在正式機 |
| `duty_roles_autobind_plan.py` | **新** | 第 4 步：唯讀產出「完全吻合者」計畫檔 | 第 4 步 |

- **清單登記處**：各班步驟檔①「新功能靜態存在」列加上述檔（照 `prod-tasks/20261006-train43-apply.md` 第 9 列寫法：`<ROOT>\backend\tools\<檔>` 存在）②「快照」「驗證」兩列（照該檔步 6、14）。**不改** `product_select.REQUIRED_PKG_FILES`（那是 `tools/platform/*` 的硬性必要檔，本工具在 `backend/tools`）；若要「缺了就拒絕套用」另案。
- 靜態守門（§6）：`backend/tools/duty_roles_*.py` 每支必須有 `--db`；寫入子命令預設 dry-run；snapshot 路徑不得 import 寫入路徑。

---

## 6. 測試計畫（本步不跑；列給後續上線班次）

純函式＋小 fixture，目標合計 ≤ 1 分鐘，不拉長 30 分預算（可重用 `tests/test_duty_roles_*_2026_10_06.py` 的 fixture 建法）。

| 組 | 題目 | 突變檢查（必須能讓題紅） |
|---|---|---|
| 檢查器本身 | ①零變動 ⇒ 0 ②各注入一種差異各自 ⇒ 1：多一鍵／少一鍵／財務鍵滲入 E2／角色定義改權限／`users.role` 改／帳號消失／`users.modules` 被清 ③順序不同集合相同 ⇒ 0＋`orderOnly` ④計畫白名單：差異＝白名單 ⇒ 0；少列／多列一鍵 ⇒ 1 ⑤紀錄筆數減少／觸發器被 DROP／superadmin 有綁定 ⇒ 3 ⑥schema 1 快照仍可用 | 把比對改成只比 E1、忽略白名單多列、不查觸發器，各必有題紅 |
| 獨立重算 | `spec_effective` 與 `helpers.auth` 在「全基礎類別 × 全模組鍵 × 綁定組合 × 扣項」窮舉一致 | 改壞任一邊 ⇒ 紅 |
| 形狀矩陣 | 合成使用者：admin／sales／engineer／viewer／finance／superadmin（modules 空）、有惰性財務勾選的 admin／sales、停用帳號、綁定停用角色 | — |
| 正式機形狀 | 12 人去識別化 fixture：快照→綁定計畫→verify，預期零差異 | 把某人綁定角色權限多加 1 鍵 ⇒ 紅 |
| 綁定等價 | 對每個系統角色，綁給「現有權限 ⊇ 角色權限」者 ⇒ E1／E2／E3／E5 不變；綁給不⊇者 ⇒ 計畫工具拒絕列入（不是 verify 才發現） | 取消「⊇」檢查 ⇒ 紅 |
| 綁定含財務三鍵 | 綁含財務鍵的角色給 admin／sales ⇒ E1、E3 不變，E2 多財務鍵（已知，僅資訊）；靜態掃描：所有直讀 `user["modules"]` 的程式不得出現 `financial_view／finance／cashier` 判斷 | 在任一直讀點加財務鍵判斷 ⇒ 紅 |
| 順序無關 | `/api/platform/menu` 與登入回傳（排序後）在綁定前／後相同 | — |
| 回滾 | 快照→綁定→停用回收→L0 rollback→verify（無計畫）＝0；紀錄表只增；L0 只動白名單內的人 | 讓 rollback 多動白名單外一人 ⇒ 紅 |
| 舊 PUT 不烘焙 | users.html 存檔只送原始勾選，不得把預覽（生效）清單送回 `users.modules`（否則角色權限被複製進加項，之後改角色或設扣項失效）。屬第 2 步 | 改成送生效清單 ⇒ 紅 |
| 靜態掃描 | `permission_changes` 不得出現 `INSERT OR REPLACE`／`REPLACE INTO`（含工具）；§5 工具守則 | 在工具加一行 REPLACE ⇒ 紅 |
| superadmin 不變式 | R2 任何動作後 superadmin E1 不變；對 superadmin 設綁定／扣項／回收 ⇒ 拒絕 | — |

**正式機演練（只讀，不佔測試鎖）**：用正式機快照在**副本**上做「綁定計畫→verify」，輸出放回報資料夾；這是第 4 步上線前唯一前置。

---

## 7. R2 第 2–9 步順序與相依

| 步 | 內容 | 相依 | 說明 | 本步建議（供裁示，不改已定的 1→9） |
|---|---|---|---|---|
| 1 | 等價／回滾衛生（本稿） | — | 之後每步的關卡 | — |
| 2 | `users.html` 整合；舊 `PUT /api/users` 與扣項衝突改拒絕／警告；§1.1-6 的唯讀報表工具改讀生效權限 | 1 | 第 4 步要有 UI 讓 superadmin 確認；「烘焙」風險（§6）在此關 | 併入第 8 步的 `audit_id` 填值（同檔同函式，分兩班會衝突） |
| 3 | 停用即回收（Q11 a）＋刪除使用者清孤兒 | 1（含 `duty_roles_rollback.py` 已在正式機） | 第一個不可逆步驟，L0 必須先到位 | **【D3】** |
| 4 | 完全吻合者自動綁定（超管確認清單、逐筆記錄）＋30 天整理提醒（Q12 a） | 1、2（確認畫面）、3（停用者先排除） | 綁定＝純加法；用計畫檔＋verify 零差異 | **【D1、D2】** |
| 5 | 季度盤點（Q7 a） | 3、4；`helpers/business_days`（第 43 班已有） | 盤點快照沿用 §2.2 欄位定義，避免兩套「生效權限」口徑 | 取數函式直接重用檢查器 v2 |
| 6 | 高敏感變更寄信（鎖定類） | 5（同批新增 mail_types）；`notify_matrix.py` 持有視窗對齊 | 一次登記、一次對矩陣 | 矩陣視窗已併入則可提前 |
| 7 | SoD 提示規則＋每鍵「強制程度」 | 2（UI）、5（盤點標示） | 純提示不擋（Q9 b） | 「部分」清單可由 B 階段靜態掃描（約 73 處）自動產生 |
| 8 | 完整性：`audit_id`、`INSERT OR REPLACE` 掃描、7 年清除工具 | 無硬相依 | 掃描守門是純測試，可最早做；清除工具要停用觸發器，風險最高，最後 | 拆 8a（audit_id、掃描）併入第 2 步；8b（清除工具）維持原位 |
| 9 | B 階段：superadmin 是否「全部鍵」、財務三鍵扣項、逐領域取代 admin 直通 | 1–8；每領域一班 | 才會改變誰能看／做什麼 | **【D4、D5】** 每領域上線前再問 |

每步上線關卡都照 §3.1；第 2、3 步另依 §6 專屬題。

---

## 8. 需使用者裁示（涉權限／金額可視）

| # | 議題 | 為什麼需要 | 建議 |
|---|---|---|---|
| **D1** | 第 4 步：含財務三鍵的職責角色（`finance`）可不可以自動綁？ | 綁定當下 E1／E3 不變（`has_finance_access` 仍只看基礎類別），但畫面會顯示「此人持有出納／財務」而實際判斷不採用，「誰能看金額」的認知會與實際脫鉤 | 只對 `role=finance` 者自動綁 `finance` 角色；admin／sales 一律不自動綁含財務鍵的角色，其惰性勾選維持原樣 |
| **D2** | 第 4 步綁定範圍：只綁「權限集合與系統角色完全相等」者，或放寬為「現有權限 ⊇ 角色權限」者（多出的留在加項）？ | 設計 §3.2 寫完全相等；放寬後綁的人更多，但每人同時有角色＋加項，盤點更雜 | 先照完全相等；其餘由 superadmin 在 UI 逐人處理 |
| **D3** | 第 3 步：停用帳號是否同時清空 `users.modules`（個人加項），以及重新啟用時是否強制重選基礎類別？ | 設計 §2.7 清綁定、加項、扣項，但基礎類別不清 ⇒ 重新啟用一位 `role=finance` 者會立刻重得財務／出納能力，與 Q11 a「重新啟用＝無任何角色與例外」有出入；清空加項則回滾要靠 `before_json` | 停用時清綁定＋扣項＋加項；重新啟用時基礎類別要明確確認（原類別當預設） |
| **D4** | 第 9 步：superadmin 是否改為「全部鍵」 | 會改變 superadmin 的選單／模組清單（R1 刻意不改） | 維持 R1 現狀至 B 階段，逐領域上線時再問 |
| **D5** | 第 9 步：開放財務三鍵扣項／`has_finance_access` 改讀生效權限 | 直接改變誰能看金額與出納，是 R2 影響最大的一步 | 單獨一班、單獨裁示；本稿不做任何準備性程式 |
| 附 | `duty_roles_rollback.py`／`export_effective.py` 的 `--apply` 在正式機執行是否一律需使用者同意 | 會改 `users.modules`／綁定；第 43 班步驟檔已寫「需使用者同意」 | 沿用；dry-run 不需 |

已裁示、本稿**不重開**：N2（高敏感清單不含 `reports`）、Q1（僅 superadmin 管理）、Q5（允許負向例外）、Q8（不規範 superadmin 使用）。

---

## 9. 已知未驗證
- 正式機快照內容（12 人／0 綁定）未直接讀取；§3.2 預期值待正式機視窗拍快照時核對。
- 「沒有消費者依賴清單順序」（§1）是讀碼推論，列在 §6 測試。
- 本稿未跑任何測試、未動程式、未碰 platform。
