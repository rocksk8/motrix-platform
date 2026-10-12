# 脊柱引擎設計：E-a（模組自行登錄設定群組＋基準分割）與 E-b（`core/spine.py` 彙整驗證）

> 2026-10-13／1d（T57）。分支 `wip/t57-spine-engine-design-r1`（文件，基於 S1 `90bcd5ead`）。上位設計：`FIELD-LAYOUT-FRAMEWORK-T56.md` r9 §17（功能進件＝脊柱登錄）；實作等 0d 對 S1 通過後在 S1 之上開新分支。
> 本文只列**已核對程式**的事實與可實作的細節；沒有核對到的標「待核」。

## 0. 結論

1. **E-a 的真問題不是『模組登不了群組』**——模組在 import 時呼叫 `register_group()` 本來就行（載入器只對『已載入』的模組 import）。真問題有三個：①凍結基準 `settings_deploy_baseline.json` 是**單一檔**，`test_deploy_baseline_frozen` 把『目前登錄的所有群組』跟它比，模組群組一進來就紅（或因載入順序而時紅時綠）；②登錄表沒有『擁有者』概念，無法判斷某群組該不該出現、該比對哪份基準；③群組集中在 `helpers/settings_groups.py`（core 檔）→ 多班同改的熱點。
2. **E-a 做法**：登錄時蓋『擁有者』章（載入器在 import 模組期間設一個 L0 的擁有者範圍，`register_group` 自動讀取）、模組在 `module.json` 宣告它擁有的群組（宣告⇔實際登錄不一致 ⇒ 該模組不載入）、基準依擁有者分檔並**只比對已載入的擁有者**、模組卸載／載入失敗時一併移除其群組。1.0 pd。
3. **功能狀態（1c 要求，§3.7）**：每個功能在 `features[]` 帶 `status ∈ {open, planned, hidden}`——設定中心可以在所有功能完成之前先上線：`planned` 顯示成灰色『開發中，預計 MSn 版提供』（無日期）、後端拒絕寫入；`hidden` 完全不顯示。
4. **E-b 做法**：`core/spine.py` 讀 `module.json` 的 `features[]`（宣告式、靜態可掃），在載入結束後對已載入模組的宣告做跨表驗證；**CI 失敗＝硬紅；執行期失敗＝只停用該功能並降級（未驗證目錄項視為 isMoney/internal）**，結果進系統中心健康卡。目錄（P0）尚未落地，E-b 以『擴充點』設計：先驗證今天查得到的（設定、信件、群組擁有、宣告完整），目錄與標籤驗證器在 P0 落地時掛上。1.5 pd。
5. 兩者都在底層列車（`core/**`、`helpers/**`），與 S1 同列車的後續項；S1 先、E-a 後（1c 決定）。

## 1. 已核對的現況

| 事實 | 出處 |
|---|---|
| `ModuleSpec` 欄位：`key, routers, schedulers, startup_notices, runtime_switches, providers, migrations`；無設定／宣告欄位 | `core/registry.py:34–47` |
| 載入流程：讀 `module.json` → 版本相容 → `customization.require_valid(manifest)`（import 前驗宣告）→ 授權／停用判斷 → `importlib.import_module` → 檢查 `MODULE`、`check_migrations` → 登記 migrations → `registry.register` | `core/loader.py:112–157` |
| 單一模組載入失敗被隔離（`mark_failed` + `STATE_FAILED`），不影響其他模組 | `core/loader.py:149–153` |
| `registry.unload(key, reason)`：模組 import 後才發現不可掛（路由衝突）時改記失敗並移出清單；**目前不會移除該模組在 import 時登記的任何東西** | `core/registry.py:140–145` |
| `register_group(group, label, fields, *, sensitive, risk, legacy_key, cross_check, help)`：重複 ⇒ ValueError；**沒有 owner** | `helpers/settings_registry.py` |
| `groups()` 回全部（含 `zz_` 測試群組）；測試夾具用 `R._GROUPS.pop(...)` 手動移除 | 同上、`tests/platform/test_settings_*` |
| `test_deploy_baseline_frozen`：`now == frozen["groups"]`，`now` 為 `R.groups()` 去掉 `zz_` 前綴者；基準檔 `tests/platform/settings_deploy_baseline.json` | `tests/platform/test_settings_pending_t54.py:77` |
| 該測試**不用 `client`**，只靠 import `helpers.settings_groups`；因此模組若在載入時登記群組，結果會**隨測試順序而變**（前面有 `client` 題載入過模組 ⇒ 紅） | 同上（推論，待以雙順序實跑證實；本設計不依賴實跑結果） |
| 既有群組：`change_control`、`retention`、`uploads`、`system_hub`（皆 core）；`completion_note`／`quote_alt`／`material_order` 在其他分支（c7／5e） | `helpers/settings_groups.py`；1c 通報 |
| 模組 `module.json` 既有宣告區段：`customization`、`mount_points`、`capabilities`、`capability_presets`、`system_cards`、`pages`、`permissions`…；載入器忽略未知區段 | `core/customization.py`、`core/mounts.py`、`core/capabilities.py`、`core/loader.py` |
| 信件類型登錄：`helpers/mail_types.register(...)`（模組登記自動併入個人通知偏好）；守門 `tests/platform/test_mail_registry.py` | `helpers/mail_types.py` |

## 2. E-a 設計

### 2.1 擁有者範圍（L0 小改）
- `core/registry.py` 新增：`_OWNER = contextvars.ContextVar("owner", default=None)`；`owner_scope(key)`（context manager）與 `current_owner() -> str|None`。**L0 不依賴 L1**，只提供範圍。
- `core/loader.py` 在 `importlib.import_module(f"{package}.{name}")` 外面包 `with registry.owner_scope(name):`。
- `helpers/settings_registry.register_group(..., owner=None)`：`owner` 省略 ⇒ `registry.current_owner() or "core"`。群組內存 `owner`；`groups()` 回傳多一個 `owner`。
- 簽章只加選填參數 ⇒ L1 快照『新增』類（升次版號）。

### 2.2 宣告⇔登錄一致（載入時檢查）
- `module.json` 新增選填區段 `settings`：`{"groups": ["completion_note", "quote_alt"]}`（只列群組代號；內容仍在 Python 的 `SettingDef`，因為驗證函式與 `impact_fn` 是程式）。
- 載入器（或 E-b 的 `spine`）在 import 後比對：`registry` 內 owner＝該模組的群組集合 **等於** 宣告集合；不等 ⇒ 該模組標記載入失敗（`ValueError("宣告的設定群組與實際登錄不一致：缺…／多…")`），與 `check_migrations` 同級的隔離處理。沒有 `settings` 區段而實際登錄了群組 ⇒ 同樣失敗（強迫宣告；這是『宣告檔存在』守門的一部分）。
- 群組代號格式與唯一性：`^[a-z][a-z0-9_]*$`（設計稿 §2.2-8 已定）、跨擁有者重複 ⇒ `register_group` 本來就丟 ValueError ⇒ 後載入者失敗。

### 2.3 卸載／失敗時移除
- `settings_registry.unregister_owner(owner)`：移除該擁有者的所有群組（含快取 `invalidate`）。
- `registry.unload()` 與 `load_all` 的失敗路徑呼叫它（透過 L0→L1 的『卸載鉤子』：`registry.on_unload(fn)` 由 `settings_registry` 在 import 時登記，避免 L0 依賴 L1）。
- 目的：路由衝突等晚期失敗的模組不會在設定中心留下孤兒群組。

### 2.4 基準依擁有者分割
- **檔案**：核心 `tests/platform/settings_deploy_baseline.json`（只含 owner=core）；模組 `modules/<模組>/tests/settings_deploy_baseline.json`（只含該模組宣告的群組）。格式不變：`{"groups": {群組: {欄位: [default,min,max,clamp]}}}`。
- **比對**：共用函式 `tests/platform/_settings_baseline.py::compare(owners)`：對每個**已載入**的擁有者，`R.groups()` 中 owner 相符者（排除 `zz_`）必須等於該擁有者基準檔的 `groups`；某擁有者未載入 ⇒ 它的基準檔不參與、其群組也不應出現在登錄表。
- **測試放哪**：核心的 `test_deploy_baseline_frozen` 只比對 owner=core；每個有設定群組的模組自帶 `modules/<m>/tests/test_settings_baseline.py`（呼叫同一個 `compare([m])`）。這樣 core-only RC 與單模組安裝包各自只跑自己存在的檔，不會因為別人的基準而紅。
- **順序獨立**：比對前先確保擁有者已載入（`load_all` 或直接 import 該模組的 `settings.py`）；core 題不依賴其他模組是否剛被載入（以 owner 過濾，與載入順序無關）。
- **遷移（機械式、可驗證）**：一次性腳本把現有 JSON 依 owner 拆開；拆分前後『所有群組預設值集合』逐位相同（測試：拆分後合併 == 拆分前）。`completion_note`／`quote_alt`／`material_order` 等在各分支落地時搬到各自模組基準（與 c7／5e 協調，見 §6）。
- **群組總數**：不再有手寫常數；『總數』由宣告計算（`sum(len(declared) for loaded)`），步驟檔 #19 改為引用該計算（待核：步驟檔 #19 原文）。

### 2.5 測試（E-a）
1. 擁有者蓋章：模組 import 期間登記 ⇒ owner＝模組鍵；core 檔登記 ⇒ `core`；顯式 `owner=` 覆寫。
2. 宣告⇔登錄：缺／多／無宣告而有群組 ⇒ 該模組載入失敗且其他模組不受影響；失敗後該模組的群組已移除。
3. `registry.unload()` 後群組消失（卸載鉤子）。
4. 基準：核心／模組各自凍結；修改某模組群組預設值 ⇒ 只有該模組的基準題紅；模組缺席 ⇒ 不要求其基準；孤兒基準檔（擁有者未載入）被忽略。
5. 順序獨立：先跑 `client` 題再跑 core 基準題、與反過來，結果相同（同一個 pytest 程序以 `-p no:randomly` 固定兩種順序各跑一次）。
6. 拆分等價：拆分前後群組預設值集合逐位相同。
7. core-only RC：沒有任何模組時，核心基準題綠、模組基準題不存在。
8. L1 快照：`register_group` 多 `owner`、`groups()` 回傳多欄位 ⇒ 新增（快照更新、CHANGELOG `(next:minor)`）。

## 3. E-b 設計：`core/spine.py`

### 3.1 位置與層級
- L0（`core/spine.py`），**只用標準函式庫**（與 `customization.py`、`mounts.py`、`capabilities.py` 同級：載入器要在 import 前驗宣告）。依賴 L1 的驗證（設定風險、信件登記）以**驗證器擴充點**注入：`register_validator(name, fn)`，由 L1 檔案在 import 時登記（`helpers/settings_registry`、`helpers/mail_types` 各登記自己的），避免 L0→L1 依賴。

### 3.2 宣告格式 `features[]`（`module.json`，v1）
```json
{"features": [{
   "code": "directive",
   "label": "批示",
   "settings": {"group": "directive"},
   "mail": ["annotation_received"],
   "catalog": {"fields": ["directive_badge"], "surfaces": ["module:crm.dev_log_list"]},
   "capabilities": ["directive.write"],
   "labels": ["directive.button"],
   "status": "open",
   "notes": "CRM-DIRECTIVE-COMMENTS-T56.md"
}]}
```
- `status`（選填，預設 `open`）：`open`｜`planned`｜`hidden`——功能的**成熟度**，見 §3.7。`planned` 時另需 `planned_train`（例 `"MS2"`，**不寫日期**）。
- 每個區段**選填**；有宣告就必須對得上：`settings.group` ⇒ 該擁有者確有此群組；`mail[]` ⇒ `mail_types` 已登記且 owner＝本模組；`capabilities[]` ⇒ `core.capabilities` 已收集；`catalog`／`labels` ⇒ 目錄與標籤驗證器（P0 之後才掛，之前『有宣告但無驗證器』記為 `pending_validator`，不算失敗）。
- `code`：snake_case、全域唯一（跨模組重複 ⇒ 後載入者失敗）；與設定群組代號一致是**慣例**（§15-2），不強制，但 `settings.group` 缺省取 `code`。
- 與 §2.2 的 `settings.groups` 關係：`features[].settings.group` 必須是模組 `settings.groups` 的子集（同一份宣告檔，不兩處維護；實作上 `settings.groups` 可由 `features[]` 推導，兩者並存時以一致性檢查為準）。

### 3.3 驗證步驟（`validate_all()`，載入結束後執行一次）
1. **結構**：`features[]` 型別、`code` 格式與唯一、未知鍵（拼錯）⇒ 問題。
2. **擁有一致**：§2.2 的宣告⇔登錄。
3. **設定**：群組內每個 `SettingDef`——風險 ∈ `money/legal/security` 必有 `risk_text`（既有）；**新群組**必有 `impact_scope`（`IMPACT_SCOPE_GRANDFATHERED` 例外）；選項欄位為整數代碼（E-f）；預設＝凍結基準（交給基準測試，不在執行期）。
4. **信件**：宣告的 key 已 `register`；`owner` 相符；分類／群組合法（既有 `register` 已丟 ValueError，這裡只確認存在）。
5. **能力**：宣告的能力在 `core.capabilities` 收集結果內。
6. **擴充點**：其他已登記驗證器依序執行（目錄⇔遮蔽、標籤等，P0 落地後掛上）。
7. **結果**：`spine.report()` → `{features: [{code, owner, state: ok|failed|pending_validator, problems:[…]}], problems: n}`。

### 3.4 失敗處理
- **CI／測試**：`tests/platform/test_spine_registry.py` 以真實載入結果斷言 `problems == 0`（硬紅）；並有負對照（餵壞宣告 ⇒ 抓得到）。
- **執行期**：失敗的功能 `state=failed`，`spine.feature_enabled(code)` 回 False；功能自己的入口（路由、按鈕、排程）依此降級；**未驗證的目錄項 ＝ isMoney 真、類別 internal**（P0 落地後由目錄讀取端套用——客戶通道、檔名變數、帶入白名單、範本占位符一律隱藏，絕不當 public）。失敗不阻止系統啟動、不影響其他功能。
- **可見性**：系統中心健康卡新增一行『有 N 項功能登錄未通過驗證』（`system_cards` 宣告在 core 的 `system_hub_l1.json`），列功能代號與白話原因（superadmin）；同時 `audit_log` 動作 `spine.validation_failed`（啟動時每次失敗各一筆，去重）。
- **fail-closed 的邊界**：驗證器本身丟例外 ⇒ 該功能視為失敗（不是通過）。

### 3.7 功能狀態 `status`：`open`｜`planned`｜`hidden`（設定中心可先於功能上線；r3）

**目的**：設定中心與版面編輯器的畫面可以先出貨，尚未做完的功能不用等；使用者看得到『之後會有什麼』，但不能誤改一個還沒有行為的設定。

| status | 畫面 | 後端 |
|---|---|---|
| `open`（預設；沒寫＝open） | 正常顯示、可編輯 | 正常，完整驗證（§3.3） |
| `planned` | **灰色顯示**，欄位全部停用，只顯示『開發中，預計 MSn 版提供』（句子**只從 `planned_train` 組出**，不取 label／notes；不寫日期）；預設值與影響說明仍可讀 | 寫入類一律 409『這項功能還在開發中，尚未開放調整』；讀取（GET）可 |
| `hidden` | **不顯示**（群組清單、版面編輯器可挑項目、預設組預覽都不出現） | 對外回 404『沒有這個設定群組』（**連 superadmin 也是 404**——不洩漏存在）；內部讀預設值照常 |

**規則**
1. **狀態由開發決定，不是管理者的設定**：寫在 `module.json`（隨功能程式出貨）；管理者不能把 `planned` 打開（那是成熟度，不是政策）。功能做完的那個提交把 `planned` 改成 `open`（或刪掉該行）。
2. **`planned_train` 與文字驗證**：`planned` 必須有 `planned_train`，格式 `^MS[1-9][0-9]?$`（MS1～MS99）；`open`／`hidden` 不可帶。出現 `date`／`eta`／`deadline` 之類的日期鍵 ⇒ 失敗。另外驗證器對 **`planned` 功能的 `label`／`notes`** 檢查**不得出現看起來像日期或時程的文字**（`\d{4}[-/年]\d{1,2}`、`\d{1,2}[/月]\d{1,2}`、`\d+\s*(天|週|周|日|月|年)`、`Q[1-4]`、`下(週|個月)`、`本月|月底|年底`）⇒ 失敗並指出哪個欄位。畫面的『預計 MSn 版』句子**只由 `planned_train` 產生**，不取 label／notes，因此即使文字漏網也不會被當成承諾顯示。
3. **引擎層攔截，不只靠路由**：`settings_registry.publish()` 最前面問 `spine.group_status(group)`（L1 呼叫 L0，方向合法）；非 `open` ⇒ `SettingError`。如此 `apply_profile`、`restore`、`reset`、任何內部呼叫端都一併被擋。**`publish()` 不可因脊柱未初始化而丟例外**：`group_status` 對『未宣告的群組』與『`validate_all()` 尚未執行（啟動早期、單元測試、獨立執行的備份工作）』一律回 `open`；匯入 `core.spine` 失敗也視為 open（保守地維持今天行為）。
4. **待生效項（讀取時也生效，要兩處擋）**：現行 `materialize_due()` 用 `publish_direct` 寫入，而讀取時 `_effective()`／`_due_pending()` 也會把『已到時且核准足夠』的待生效值疊上去。所以：
   - **啟動時**（`spine.validate_all()` 之後，由設定登錄表登記的 post-validate 回呼）把**所有**非 open 群組的待生效項標 `cancelled`，ledger 事件 actor＝`system`、原因『功能改為開發中／隱藏』；**已投的核准票隨之作廢**，`planned→open` 之後**不會復活**，要重新申請。
   - **讀取時**：`_due_pending()` 對非 open 群組回空（即使還有漏網的待生效項、即使票數已足、即使已到時，讀到的仍是**已儲存的值**）。
   - `materialize_due()` 對非 open 群組：不寫入、順手 `cancelled`（actor `system`）。
   - 測試：對一個『已到時＋核准足夠』的待生效項，把群組翻成 planned ⇒ `get_group` 仍回已儲存值、`materialize_due` 寫入 0 筆、事件為 `cancelled`（actor `system`）。
5. **歸屬**：群組屬於哪個功能由 `features[].settings.group` 決定（沒歸屬任何功能的群組＝`open`）。一個群組只能歸一個功能；同一功能多個群組狀態相同。
6. **核心群組沒有 `module.json`**：`change_control`／`retention`／`uploads`／`system_hub` 屬 core，沒有模組宣告檔，因此預設 `open`。若日後核心也要有 `planned`／`hidden` 的功能，採 **`core/features_l1.json`**（比照既有 `core/system_hub_l1.json` 的 L1 宣告檔，owner＝`core`），由 E-b 與模組宣告同一條路徑載入；本期不建立該檔（沒有需要）。
7. **目錄項（P0 之後）**：功能的 `catalog.fields`／`surfaces` 繼承功能狀態——`planned` 在版面編輯器的可挑清單裡灰色列出、不可放入版面；`hidden` 不出現。解析器對非 open 的項目一律不輸出（不影響既有單據）。
8. **與降級（§3.4）的差別**：`status` 是**宣告的成熟度**（刻意、可預期）；`failed` 是**驗證失敗**（意外、要處理）。`spine.report()` 分開欄位：`state ∈ ok｜failed｜pending_validator`、`status ∈ open｜planned｜hidden`。`feature_enabled(code)` ＝ `state != failed and status == open`。
9. **基準仍強制**：`hidden`／`planned` 群組的凍結基準（E-a3）照常比對——隱藏不等於可以悄悄改預設值。
10. **完成閘（DoD）**：每個功能的**所有進入點**（路由、按鈕、排程、通知寄送）必須呼叫 `feature_enabled(code)`（或在 `planned` 時走『尚未提供』分支）；`status` 翻成 `open` 前，測試要證明 `planned` 時進入點被擋（避免『設定頁灰了但功能其實偷偷在跑』）。

**API（`core/spine.py`，標準庫）**
```
feature_status(code) -> "open"|"planned"|"hidden"          # 未宣告 ⇒ "open"；validate_all 之前 ⇒ "open"
group_status(group)  -> "open"|"planned"|"hidden"          # 由 features[].settings.group 對映；未歸屬 ⇒ "open"
planned_train(code)  -> "MS2"|None
```

**設定中心每一條路由的行為（結構化，不靠記憶）**

| 路由 | `planned` 群組 | `hidden` 群組 |
|---|---|---|
| `GET /groups` | 列出，多 `status`／`plannedTrain` | 不列 |
| `GET /groups/{g}` | 200（唯讀，欄位停用） | 404 |
| `POST /groups/{g}`（儲存） | 409 | 404 |
| `POST /groups/{g}/preview`、`/impact`、`/reset` | 409 | 404 |
| `POST /groups/{g}/restore/{v}` | 409 | 404 |
| `GET /groups/{g}/versions`、`/diff` | 200（唯讀） | 404 |
| `GET /pending` | 該群組的待生效項不列（啟動時已全數取消） | 過濾掉 |
| `POST /pending/{id}/approve` | 409（拒絕核准） | 404 |
| `POST /pending/{id}/cancel` | **允許**（收尾用，寫稽核） | 允許（收尾；不洩漏內容） |
| `GET /profiles`、`GET /profiles/{n}/preview` | 預設組欄位數與預覽**略過**非 open 群組，預覽顯示『略過 N 項（開發中／隱藏）』 | 同左（不出現） |
| `POST /profiles/{n}/apply` | 略過，回應含 `skipped:[{group, reason}]`；**畫面不得宣稱『已全部套用』**，要寫『已套用 X 項，略過 N 項（開發中）』 | 同左 |
| `GET /public?groups=a,b`（任何登入者可讀） | 200（回預設值） | 404（或不回該鍵；採 404 與單組一致） |

**結構化測試（路由表驅動）**：測試走訪 app 路由表中**所有** `/api/settings-center/*` 路由，逐一對一個 `hidden` 群組與一個 `planned` 群組發請求，斷言結果等於上表；**路由表裡出現上表沒有的新路由 ⇒ 測試紅**（強迫新增端點時決定它對非 open 群組的行為）。

**健康卡（§3.4 的那張）**：新增資訊行『開發中的功能 N 項（planned）』並列功能與預計列車（`MSn`），`hidden` 只計數『已隱藏 M 項』。這兩行**不算失敗**（不影響卡片顏色）；『登錄未通過驗證 N 項』維持紅色警示。僅 superadmin 可見。稽核 `spine.validation_failed` 維持**去重**（同功能同原因只記一次）。

**測試**
1. `planned` 群組：各寫入類端點 409 且**資料與變更明細不變**（前後計數）；直接呼叫 `publish()` 丟 `SettingError`；讀取預設值正常；`apply_profile` 略過並回 `skipped`。
2. `hidden`：清單不列、單組與所有寫入／版本端點 404（**含 superadmin**）；`GET /public` 404；內部 `get()` 仍回預設；其凍結基準仍被比對。
3. **待生效**（規則 4）：到期＋核准足夠的項目、群組翻 planned ⇒ 讀值＝已儲存值、`materialize_due` 寫 0 筆、事件 `cancelled`（actor `system`）；啟動取消後 `planned→open`，舊票不復活（`GET /pending` 為空、需重新申請）。
4. 驗證：`planned` 缺 `planned_train`／格式不符（`MS0`、`MS100`、`ms2`、`MS 2`）／帶日期鍵／label 或 notes 含日期或時程字樣 ⇒ 失敗；`open`／`hidden` 帶 `planned_train` ⇒ 失敗；`status` 值不合法 ⇒ 失敗；沒寫 `status` ⇒ `open`。
5. 歸屬：群組歸兩個功能 ⇒ 失敗；未歸屬群組（如現有 core 群組）⇒ `open`，行為不變（黃金）。
6. `feature_enabled`：`planned`／`hidden`／`failed` 皆 False；`open` 且 ok 才 True；`validate_all` 之前與未宣告 ⇒ True。
7. **脊柱未初始化**：不匯入／不執行 `validate_all` 的情況下呼叫 `publish()` 照常工作（`group_status` 回 open）；`core.spine` 匯入被模擬為失敗時亦然。
8. 路由表驅動測試（上表）。
9. 畫面（e2e，需另行同意才跑）：planned 群組欄位全部 disabled、顯示『開發中，預計 MS2 版提供』且全頁無日期字樣、沒有儲存列；套用預設組後訊息為『已套用 X 項，略過 N 項』。
10. 健康卡：planned／hidden 的資訊行出現、顏色不變；有 failed 才變紅；稽核去重。

### 3.5 字面掃描器（`宣告檔存在`守門）
- 以 `ast` 掃 `backend/**`（排除 tests）：只抓**字面**：`send_registered("<key>"…)`、`mail_types.register("<key>"…)`、`register_group("<group>"…)`、`SettingDef("<key>"…)`、與 `QUOTE_MONEY_KEYS`／`QUOTATION_MONEY_COLS` 內已列出的金額鍵名。
- 對照：程式出現而 `features[]`／`settings` 宣告沒有 ⇒ 紅。**不掃散文、不做啟發式**。
- **正對照**：測試內放故意違規樣本（未登記的 `event_key`、群組、金額鍵）斷言掃描器抓得到（抓不到 ⇒ 掃描器自己紅）。
- **誤報白名單**：`tests/platform/spine_scan_allowlist.json`，每筆 `{pattern, file, reason, owner, expires}`；測試斷言每筆仍對得上實際出現（失效／過期 ⇒ 紅）。

### 3.6 測試（E-b）
1. 結構驗證：缺 `code`、重複 `code`、未知鍵、`settings.group` 不存在、`mail` 未登記 ⇒ 各自失敗並指出原因；其他功能不受影響。
2. 擴充點：登記一個驗證器丟例外 ⇒ 該功能失敗；驗證器 `pending_validator` 不算失敗。
3. `feature_enabled`：失敗功能回 False；ok 回 True；未宣告功能（舊模組）預設 True（向下相容）。
4. 健康卡：失敗時卡片顯示 N 與功能代號；全部通過時不顯示；寫 `spine.validation_failed` 稽核（去重）。
5. 掃描器：正對照抓得到；白名單失效即紅；真實樹上 0 問題。
6. 向下相容：現有所有模組（無 `features[]`）載入結果與之前相同；`module.json` 驗證器（`test_core_loader`）接受新區段、拒絕型別錯誤。
7. L1／L0 快照：`core/spine.py` 新單位（新增）；`core/registry.py` 多 `owner_scope／current_owner／on_unload`（新增）。

## 4. 工作拆分（小提交；CHANGELOG 與程式同提交）

| # | 內容 | pd |
|---|---|---|
| E-a1 | `registry.owner_scope／current_owner／on_unload` ＋ loader 包 import ＋ `register_group(owner=)`／`groups()` 回 owner／`unregister_owner` ＋ 測試 1、3 | 0.3 |
| E-a2 | `settings` 區段宣告⇔登錄檢查 ＋ 測試 2 | 0.3 |
| E-a3 | 基準分割（腳本＋共用 `_settings_baseline.compare`＋核心題改 owner 過濾＋模組題樣板）＋ 測試 4–7 | 0.5 |
| E-b1 | `core/spine.py`（結構驗證、擁有一致、擴充點、`feature_enabled`、`report`、**`status`／`planned_train` 驗證與 `feature_status`／`group_status`／`planned_train` API**）＋ L1 驗證器登記（設定、信件、能力）＋ 測試 1–3、6、§3.7 測試 4–6 | 1.1 |
| E-b2 | 健康卡（含 §3.7 的 planned／hidden 資訊行）＋稽核＋降級讀取端 API ＋ 測試 4、§3.7 測試 8 | 0.4 |
| E-b3 | 字面掃描器＋正對照＋白名單 ＋ 測試 5 | 0.3 |
| S1+ | 設定中心套用 `status`：`publish()` 最前面問 `spine.group_status`（引擎層，脊柱未初始化＝open）、`_due_pending` 對非 open 回空、`materialize_due` 取消、啟動時取消非 open 群組的全部待生效項（actor `system`）、`apply_profile` 略過並回 `skipped`、路由 `_writable` 與 `/pending`／`/public` 過濾、清單多 `status`／`plannedTrain`、畫面灰色卡片、路由表驅動測試 ＋ §3.7 測試 1–3、5、7–9（依賴 E-b1 的 API；S1 已出貨後的小補丁） | 0.9 |
| 合計 | | **3.8**（區間 3.7–4.0）（E-a 1.1＋E-b 1.8＋S1+ 0.9；E-a 多 0.1 是 0d 稽核後的修補（核心群組蓋章、import 範圍檢查、形狀前置驗證）；S1+ 因待生效讀取時也要擋、路由表驅動測試、預設組略過回報而由 0.5 增為 0.9） |

順序：E-a1→E-a2→E-a3（可單獨出貨）；E-b1 依賴 E-a1／E-a2；E-b2、E-b3 之後。每一步單檔測試各自執行，底層閘門與其他列車項合併一次（脊柱 §17.7）。

## 5. 風險

- **基準測試順序相依**（§1 末列）：分割前就存在；分割後以 owner 過濾消除。若 E-a 比 c7／5e 晚落地，他們的群組仍進 `settings_groups.py`（owner＝core）並更新同一份核心基準——**不阻擋**，之後機械式搬遷。
- **L0→L1 鉤子**：`registry.on_unload` 與驗證器登記是『回呼註冊』，避免反向依賴；測試需涵蓋『L1 未載入時 L0 單獨可用』（`test_l1_does_not_load_m01` 同族）。
- **單模組安裝包**：模組自帶基準檔必須隨包出貨（測試檔通常不隨正式包）；基準比對是 CI 守門，不在正式機執行，沒有影響；但**宣告⇔登錄檢查是執行期**（載入時），要確認它對正式機既有模組零誤殺（現有模組沒有 `settings` 區段且沒登記群組 ⇒ 通過）。
- **宣告漂移**：`features[]` 與 `settings.groups` 兩處 ⇒ 以『子集』檢查；長期應由 `features[]` 單一來源推導。

## 6. 協調與待確認

- 與 5e／c7：他們的群組目前加在 `settings_groups.py` 與單一基準——E-a 落地前維持；落地後由我提供搬遷清單（群組→模組、基準拆分腳本），他們各自在下次動到時搬。
- 待 1c／0d：①宣告⇔登錄不一致是否**一律讓模組載入失敗**（本文預設是；較保守的替代＝只記 ERROR 與健康卡、不擋載入）；②`features[]` 驗證失敗是否也要擋住該功能的路由（本文預設：功能自己依 `feature_enabled` 降級，引擎不代為卸路由）；③基準檔放 `modules/<m>/tests/` 是否符合單模組打包慣例（待核 `build` 規則）。
