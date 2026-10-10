# 系統中心（System Hub）設計：把『系統』下拉整合成一個像營運報表的獨立頁（第 54 班）

作者 b5；基準 `origin/platform` `b2486535c`；2026-10-10。**設計與靜態稿，未改任何產品程式。** 靜態稿：`mockups/system-hub-mock.html`（單檔、示意資料、可切角色／深淺色／搜尋；手機寬度可看）。

使用者原話：「系統的模組獨立開一個頁面，重新設計排版，點選系統像營運報表有一個獨立頁面，將既有的功能整合彙整進去那個頁面」。

## 0. 原則（使用者核定）：先蓋框架、不寫死決定

框架先行、底層接線保留、易於日後維護：**只改框架，內容與決定交給使用者填**。落實為一條硬規則——**新增一個設定或頁面 ＝ 在擁有它的模組加一筆註冊（`system_cards`），不改 hub**；hub 的分組順序在 L1 固定、項目與徽章全部來自註冊表。守門測試（第 5 節）保證做不到『新頁面忘了登記』或『登記了卻權限不符』。

## 1. 現況盤點（系統相關頁面／功能）

選單群組 `system` 目前 **21 項**（`core/menu_l1.json` 與各模組 `module.json pages[].menu`，下拉長度已超過一屏）。另有未放在該群組、但邏輯上屬於系統的頁面／功能。

| 區塊 | 頁面（路由 `/pages/…`） | 權限 | 擁有模組 | 備註 |
|---|---|---|---|---|
| 帳號與權限 | `users.html` 使用者管理 | superadmin | core | |
| | `duty-roles.html` 職責角色 | superadmin | core | |
| | `org-structure.html` 組織架構設定 | superadmin | core | |
| | `approval-delegates.html` 簽核代理人 | 任何登入者 | core | 現在在『我的工作』群組，hub 做連結（兩處都在） |
| | 權限設定（矩陣） | superadmin | core | **設計中**（1d） |
| 簽核與流程 | `approval-settings.html` 簽核設定 | superadmin | core | 統一入口；舊 `contractor-voucher-approval-settings.html` 已廢棄不列 |
| | `remit-kinds-settings.html` 匯款款別設定 | superadmin | subcontract | |
| | `expense-types.html` 支出申請類型 | superadmin | core | |
| 通知與信件 | `notification-settings.html` 通知設定 | superadmin | core | |
| | `mail-settings.html` 信件與通知收件設定 | superadmin | core | |
| | `google-calendar-settings.html` Google 行事曆設定 | superadmin | core | |
| 資料與備份 | `storage-settings.html` 儲存位置 | superadmin | core | |
| | 備份與保留（`company-profile-settings.html` 內區塊） | superadmin | core | **沒有獨立頁**；hub 深連結到區塊錨點 |
| | `recycle-bin.html` 資源回收筒 | superadmin | recyclebin | ab P0（t53 分支） |
| | `file-center.html` 檔案中心 | 模組 `file_center` | filehub | |
| | `lodging-records.html` 旅宿檔案更新 | 模組 `lodging` | lodging | |
| 稽核與紀錄 | `audit-log.html` 歷史紀錄 | 模組 `audit_log` | core | |
| | `shipping-export-history.html` 出貨單歷史紀錄 | 模組 `shipping_export_log` | supply | |
| | `online-stats.html` 在線時數統計 | superadmin | core | |
| 公司與參數設定 | `company-profile-settings.html` 公司資料設定 | superadmin | core | 含品牌、備份保留 |
| | `legal-params.html` 法規參數設定 | superadmin | core | |
| | `ledger-settings.html` 報表設定 | 模組 `cashier`/`finance` | accounting | 現在在『財務會計』群組 |
| | 利潤口徑與管銷比率 | superadmin | case | **只有 API**（`/api/overhead/settings`），需補頁 |
| | 設定中心（索引） | superadmin | core | **規劃中**（node-39 的 141 項） |
| 模組與擴充 | `module-settings.html` 模組管理 | superadmin | core | |
| | `module-builder.html` 模組建構器 | superadmin | core | |
| 系統狀態與版本 | `module-versions.html` 版本紀錄 | 模組 `module_versions` | core | |
| | `schema-status.html` Schema 狀態 | superadmin | core | |

不納入：`company-setup-required.html`（首次設定強制流程）、各單據頁內嵌的設定。

## 2. 版面（左：大分組；右：所選分組的細項列）

使用者回饋：「設計頁面太雜亂，左側為大分組，右側顯示區塊細項」。因此取消狀態列、最近使用晶片與卡片格，改為**兩欄主從式**（仍沿用營運報表的骨架：頂欄＋主導覽 → `.page-main` → 標題列＋一行副標題）：

- **頂部**：標題『系統』＋**全域搜尋框**（標題、說明、關鍵字、模組名；跨所有分組；`/` 聚焦；命中字標示；搜尋時右欄改顯示結果並標示每列所屬分組，清空回到分組檢視）。
- **左欄＝8 個大分組**（來自註冊表的 `section` 欄位，順序由 L1 固定）：每列顯示分組名、**依權限過濾後的項數**；分組內有任何『待處理』徽章（tone=warn）時顯示**琥珀點**（含文字替代 `aria-label`）；使用者一項都看不到的分組整個隱藏。
- **右欄＝細項列**（非卡片）：圖示、標題、一行說明、**選用的即時徽章**（待處理數／最近備份時間…）、右箭頭；整列可點、深連結到既有頁面。無權限項目預設隱藏；可切換『顯示未授權項目』→ 灰階列＋原因（『需要最高管理者』『需要模組權限：audit_log』），不可點。
- **URL 與導覽**：所選分組寫在網址 hash（`#identity`、`#data`…）→ 可分享、上一頁／下一頁有效、重新整理停留；預設分組＝第一個可見的分組。**鍵盤**：左欄是垂直 tablist（`role=tab`、roving tabindex），↑↓（←→）切換、Home／End 跳首尾，選到即顯示；列為一般連結，Tab 可達，焦點框清楚。
- **響應式**：≤720px 左欄變成**水平捲動的分組列**（選中項底線），細項仍是列；搜尋框獨占一行。
- **深淺色**：只用既有 token（`--surface`、`--border-light`、`--accent`、`--success/--warning/--danger` 及 `-light/-border`），不寫死色碼；徽章一律『文字＋顏色』。
- **載入**：一支端點 `GET /api/system-hub` 一次回傳（伺服器已依權限過濾，含各分組項數與徽章），15 秒快取；徽章提供者逾時（預設 300ms）或失敗＝不顯示徽章，不影響項目。
- **不做**：KPI 狀態列、最近使用、卡片格（已於使用者回饋中移除；之後若要『最近使用』可在搜尋框下拉內提供，不佔版面）。

## 3. 註冊表合約（新模組／新設定自動出現，不改 hub）

加性、向下相容，仿 `pages[].menu`：

```jsonc
// 各模組 module.json（或 ModuleSpec）
"system_cards": [{
  "id": "backup", "section": "data",            // section 為 L1 固定清單的 key；未知 ⇒ 『其他』
  "title": "備份與保留", "desc": "備份保留天數、最近一次備份、還原說明",
  "href": "company-profile-settings.html#backup",
  "perm": "superadmin",                         // 同選單語意：'superadmin' | ["模組鍵",…] | 'any'
  "order": 20, "keywords": "備份 還原 保留 災難", "icon": "disk"
}]
```

- **即時徽章（選用）**：`ModuleSpec.providers[("system.hub_badge", "<card id>")] = fn(conn, user) -> {"text": str, "tone": "ok|info|warn|bad", "count": int|None}`；唯讀、不得寫入、不得查他組的表（走各自的提供者）。
- **聚合器**（L1 `core/system_hub.py`）：讀已載入模組的 `system_cards`＋core 自己的 → 依 `perm` 過濾（複用 `core.menu.visible` 的判斷）→ 依 `section` 分組並算各組項數／待處理旗標 → 呼叫徽章提供者（並行、逾時）→ 回傳。模組停用／未授權 ⇒ 該模組的卡片不出現（與選單一致）。
- **區塊清單**固定在 L1（`帳號與權限／簽核與流程／通知與信件／資料與備份／稽核與紀錄／公司與參數設定／模組與擴充／系統狀態與版本`），模組只能選用，不能自開區塊（避免區塊雜亂；要新區塊走 L1 變更）。
- **設定中心**是其中一張卡（`公司與參數設定`），也是 node-39 規劃的『所有可調參數索引』的入口；兩者不重複建設。

## 4. 遷移與相容

- **舊網址全部不變**，頁面不搬家；hub 只是新的入口與索引。
- **選單**：`system` 群組顯示為單一項目『系統』→ `/pages/system-hub.html`（原 21 項在 `module.json` 保留 `menu`，加性旗標 `menu.hub: true` 讓導覽列不再列出，但仍供 `_deniedPages` 與 `test_menu_parity` 使用）。`/pages/system.html` 作為別名導向 hub。
- **麵包屑**：`sidebar.js` 對 `menu.group=="system"` 的頁面在標題上方加『← 系統』連結（一行程式，不改各頁）。
- **深連結區塊**：`company-profile-settings.html#backup` 需補錨點；利潤口徑補一個獨立頁（目前只有 API）。
- **權限不放寬**：hub 只是索引，每個目標頁自己的權限檢查不變；卡片 `perm` 必須與目標頁的選單 `perm` 一致（守門測試保證）。

## 5. 守門與測試

1. **對等**：每個 `menu.group=="system"` 的頁面都有一張 `system_cards`（反向：每張卡的 `href` 指向存在的頁面）——仿 `test_menu_parity`，新增頁面忘了登記就紅。
2. **權限一致**：卡片 `perm` 與頁面 `menu.perm` 相同；hub 對每個測試角色回傳的項目與各分組項數＝該角色在選單舊群組中可見的項目（零洩漏／零遺漏）。
3. **徽章隔離**：徽章提供者丟例外／逾時／回傳壞格式 ⇒ 卡片仍在、無徽章、不 500；提供者不得寫入（begin-only 守門）。
4. **載入預算**：頁面載入 = 1 個 `system-hub` 請求（寫進黃金請求清單）；P95 < 300ms（徽章並行）。
5. **e2e**：superadmin 看到全部；一般人員只看到自己有權限的；左欄切換＋網址 hash＋上一頁、鍵盤方向鍵、搜尋、手機寬度（分組列水平捲動）、深色各一題；舊網址仍可開。

## 6. 工作量與順序

| 階段 | 內容 | 量 |
|---|---|---|
| P1 | L1 聚合器＋`GET /api/system-hub`（無徽章）、`system-hub.html`、為現有頁面（約 24 項，其餘為規劃中）補 `system_cards`、選單收斂為單一入口、麵包屑、守門 1／2／4 | M（約 3～4 人日） |
| P2 | 徽章提供者：備份時間、使用者數、待核權限、回收筒、法規參數待確認、稽核今日筆數、Schema（各 S） | M（約 2 人日） |
| P3 | 補頁：利潤口徑設定頁、備份錨點；設定中心接入；權限設定矩陣接入（各自專案） | 依專案 |

風險：卡片 `perm` 與頁面不一致會洩漏或擋人（守門 2 解）；徽章查詢拖慢（並行＋逾時＋快取）；模組各自的『我的工作』類入口（簽核代理人）會在兩處出現，需文案區分。**待使用者確認**：預設『隱藏』還是『灰階顯示並說明原因』無權限卡片（本稿預設隱藏，可切換）；是否需要『最近使用』（已移出主版面，可放搜尋框下拉）。
