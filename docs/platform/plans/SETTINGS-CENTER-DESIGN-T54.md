# 設定中心設計（第 54 班）：重用定義文件庫的「設定群組」

基準 `origin/platform` `b2486535c`；作者 node-39；2026-10-10。設計稿，不含程式。承接 `CONFIGURABILITY-INVENTORY-T54.md`（141 項）與使用者的決定：第一批＝K01 利潤警示（**12% 門檻不變**）、K08 提醒／逾期／停滯天數、K05＋K06 保存期限與上傳容量（**稽核紀錄保存至少 365 天、無上限**）、K10 狀態徽章與選項清單；K04 登入安全為第二批（需安全評審）；簽核**金額級距**在設定中心之後與權限矩陣一起設計。

## 0. 結論

1. 不另建儲存：在 `core/definitions.py` 加一個 kind `setting_group`，白拿草稿、驗證、發布、差異、版本、還原（已被匯款款別與費用類型使用）。新增的只有：**L1 設定登錄（`SettingDef` schema）＋帶快取的 `settings.get()`＋設定中心頁＋共用的上下限／稽核／通知規則**。
2. **上線當天零行為變更**：部署不建立任何設定列；缺列＝程式預設＝今天的值。每個 K 項都有「預設值＝舊常數」的自動比對測試（見 §4）。
3. 更正盤點稿：K01 **不該**用 `operating_targets`——那是財務年度營收／毛利目標（僅財務可看），不是警示門檻；改用新群組 `profit_warning`。

## 1. 架構

| 層 | 做法 |
|---|---|
| 登錄（L1，`helpers/settings_registry.py`） | 各模組在 import 時 `register_group(group, label, fields=[SettingDef…], cross_check=fn)`，登錄表即「所有可調項」的唯一目錄（設定中心頁、驗證、預設、說明都從它產生） |
| 儲存（L0 既有） | `ui_definitions` 的 kind `setting_group`、key＝群組代號、scope＝`company`（`role:x` 預留不用）；body＝`{"values": {欄位: 值}}`，缺欄位＝預設 |
| 讀取 | `settings.get("reminders", "payable.soon_days")`：15 秒程序內快取（仿 `helpers/auth.py` 的 `_finance_mode`），發布後立即清本程序快取；缺列、壞值、超界 ⇒ **回程式預設並記 warning，不丟例外**；設定中心頁顯示「N 個值無效、已用預設」。目前以單一 uvicorn 程序執行（`start_server.ps1`），TTL 即足夠；改成多程序時需補跨程序失效 |
| 前端 | 一支 `GET /api/settings-center/public?groups=…`（登入者可讀 `visibility=public` 群組）＋ `static/settings-client.js`；內建與後端同一份預設（避免閃爍與離線），取代把常數抄進 JS |
| 寫入 | `POST /api/settings-center/{group}/publish`（僅 superadmin）＝一個交易內完成 草稿＋驗證＋發布（沿用 `D.save_draft/publish`）；差異、版本、還原直接用既有 `/api/definitions/setting_group/…` |
| 上下限 | **只在程式裡**（`SettingDef.min/max/enum`＋`cross_check`），管理者改不了；還原舊版本時以**現行**上下限重新驗證，不符就擋並說明 |

`SettingDef` 欄位：`key`、`type`（int／float／bool／enum／list／options）、`default`、`min`、`max`、`unit`、`label`、`help`、`risk`（none／ops／money／legal／security）、`visibility`（public／finance／superadmin）、`legacy`（舊常數的 `file:symbol`，供比對與「禁止舊字面值回流」守門）。`risk≥money` 的群組：發布必填原因＋通知其他 superadmin（信件類型 `settings_changed`）；`security` 另接 §3 的待生效層。

## 2. 與 1d 的 `config_ledger` 對齊

1d 提議 L1 `config_ledger`：變更明細、版本快照與回溯、待生效。定義文件庫**已有**版本、差異、還原、作者、備註，所以建議**不要兩邊各做一套版本表**：

- `config_ledger` 只做兩件定義文件庫沒有的事：**變更明細**（`domain, key, 欄位, 舊→新, 原因, 操作者, IP`，只增不改）與**待生效**（`effective_at`、撤銷、到期轉態，即 1d 的 待生效期（預設 7 天，下限 24 小時）機制）。
- 版本與還原留在各 domain 自己的儲存：權限＝`perm_versions`，設定＝`ui_definitions`。`snapshot/restore` 以 adapter 形式註冊，不複製資料。
- 設定的 domain＝`setting:<群組>`，權限＝`perm`；**第一批設定（僅第一批的原規劃；Train A 實際已含待生效層）**不用待生效層（只有 K04 與高風險授權用），所以 `config_ledger` 可晚於設定中心第一版上線，介面先寫死 `record(domain, key, changes, reason, actor, effective_at=None)`。請 1d 確認這個最小集合。

### 2.1 定案協議（與 1d 一致；以下是 1d 設計稿 §7 全文，兩份文件保持同文）

## 7 與設定中心共用的稽核／待生效層：`helpers/config_ledger`（與 node-39 `SETTINGS-CENTER-DESIGN-T54` §2 一致的協議）
**原則：不建第二套版本表。** 版本、差異、還原留在各 domain 自己的儲存（權限＝`perm_versions`；設定＝`core/definitions.py` 的 `ui_definitions`／kind `setting_group`）。`config_ledger` 只做兩件那些儲存沒有的事：**變更明細**與**待生效狀態**。L1、只增不改、不 import 任何 L2。
1. **寫入**：`record(conn, domain, key, changes, reason, actor, *, ip="", effective_at=None, risk="low", ref_version=None) -> change_id`；`changes=[{field, old, new}]`；`domain` ＝ `perm` 或 `setting:<群組>`。與被改的資料**同一交易**寫入；同交易寫 `audit_log`（action `<domain>.change`）；`risk >= money`（view_money／approve／pay／delete／view_sensitive 等）時通知其他 superadmin。
2. **表（只增不改）**：`config_changes(id, at, domain, key, field, old_json, new_json, reason, actor, ip, effective_at, risk, ref_version, batch_id)`，DB 觸發器擋 UPDATE／DELETE；**狀態不放在這張表**，改記 `config_change_events(id, change_id, event, actor, reason, at)`，`event ∈ {pending, activated, cancelled, superseded}`，現況＝最後一筆（無事件＝立即生效的一般變更）。
3. **待生效 API**（只存與轉態，不決定效力）：`pending(domain=None)`、`cancel(change_id, actor, reason)`（寫 `cancelled` 事件、通知申請人）、`activate_due(now)`（把 `effective_at <= now` 且仍 pending 的轉 `activated`、寫稽核、通知；由 5 分鐘工作呼叫，**漏跑不影響效力**）、純函式 `in_effect(row, now)`（`effective_at` 空或已到、且最後事件不是 cancelled／superseded）。**效力在讀取時由 domain 判斷**（`perm.can()`／`settings.get()` 自行呼叫 `in_effect`），ledger 不介入。
4. **版本與還原**：`register_domain(domain, label, snapshot_fn, restore_fn, diff_fn, reason_required_fn=None)`；ledger 只提供「歷史」查詢 `history(domain, key)` 與統一的「還原＝新版本、歷史不改」呼叫流程。`perm` → `perm_versions`；`setting:*` → `ui_definitions`（`definitions.versions/restore/diff`）。還原含待生效項 ⇒ domain 的 restore 負責一併 cancel。
5. **既有表**：R1／R2 職責角色的 `permission_changes`（含只增不改觸發器）**不搬資料、不雙寫**，仍是 `duty` domain 的明細；權限矩陣的新變更只寫 `config_changes`（domain `perm`）。稽核報表以 UNION 呈現，避免兩份漂移。
6. **誰先做**：設定中心 S0（第一批不用待生效）先實作並上線 `config_ledger` 的 1、2、4 與 `history`；權限矩陣 P1 再加 3（待生效 API、`activate_due` 工作、`in_effect`）——介面現在就定死，後補不改簽名。設定第二批的 K04（登入安全）也走待生效層。

> 實作對照（node-39，第 54 班 Train A）：`risk` 預設為 `'none'`（程式內五級，與上文 1d 稿的 `low` 預設不同，以本節為準）；事件集合為 `pending｜approved｜activated｜cancelled｜superseded`（多一個 `approved`＝雙人核准的一票，不改變狀態）；`record(conn, domain, key, changes, reason, actor, *, ip, risk, ref_version, effective_at)`；`risk ∈ none|ops|money|legal|security`（≥money 通知其他最高管理者）；回 `{batch, ids, audit_id}`；另有 `supersede／cancel_pending_for／restore_version／snapshot_version`。

### 2.2 與權限矩陣共用的協議（單一版本；兩份設計稿同文）

1. **風險詞彙只有一套**：`none｜ops｜money｜legal｜security`（`config_ledger.RISKS`）。權限能力（`module.json` 的 `capabilities[].risk`，1d 設計稿 v6）**直接使用同一套詞彙**，不再有 `low｜mid｜high`。（舊稿曾用 `low→ops`、`mid→money`、`high→security` 的別名，僅作為歷史註記，新程式不得使用。）寫入明細與稽核時一律用五級。`money｜legal｜security` 為「高風險」＝**通知**其他最高管理者（`HIGH_RISK` 只管通知）。待生效期不是由風險等級自動帶出，而是由呼叫端／登錄宣告決定（`requires_pending`、`loosen`）；待生效期長度見本節第 6 點（`confirm_period_days`）。
2. **待生效只有一套機制**：`config_changes`（不可變）＋`config_change_events`（`pending｜approved｜activated｜cancelled｜superseded`）。**不另建 `perm_pending` 表**；權限矩陣的待生效申請就是 `domain='perm'` 的 `config_changes` 列（`effective_at` ＝ 申請時間＋待生效期（預設 7 天，下限 24 小時）），撤銷＝`cancelled` 事件，雙人核准＝`approved` 事件（`approvals_required`）。權限設計稿 §4 的 `perm_pending` 欄位（scope、cap、effect…）改存於該列的 `field`／`new_json`，不另開表。
3. **快取失效只有一套說法**：每個讀取端（`settings.get`、`perm.can`）記住自己載入時的 **`config_epoch`**＝`MAX(config_changes.id)` 與 `MAX(config_change_events.id)` 兩數的組合；快取命中時，距上次檢查超過 2 秒才重查這兩個數字（單次索引查詢），變了就清自己的快取。**本行程發布後立即清**；多行程（日後多 uvicorn worker）最多延遲 2 秒對齊。**時間性失效（採用 1d v6）**：載入時同時算出 `next_change_at`＝該 domain 所有待生效列 `effective_at`（以及權限的 `valid_to`）中**大於現在的最小值**；快取的有效期限＝`min(15 秒保底 TTL, next_change_at − 現在)`，到點即重載——所以待生效值到期不會晚於約定時間被看到（不再需要「最多晚 15 秒」的例外）。到期值是否有效仍由讀取時的 `in_effect(row, now)` 判斷；`materialize_due`／`activate_due` 只是把它落成定義版本與事件。（Train A 先用 15 秒 TTL＋本行程立即清；`config_epoch` 與 `next_change_at` 於 M1 實作，介面不變。）
4. **版本邊界（edition bounds）涵蓋設定欄位與權限能力**：同一個載入點（程式／授權）設定；設定欄位＝數值上下限、可選項的子集；能力＝該版本可授予的最大範圍或整個能力停用。客戶沒有任何 API 能改。
5. **放寬＝雙人核准**、預設組（政策檔）、白話文字與影響說明的規則一體適用於設定與能力（見附錄 C、D）。
6. **確認期（待生效期）只有一個設定鍵：`change_control.confirm_period_days`**（使用者 2026-10-10）——預設 **7 天**，可在系統內調整，**下限 1 天（＝24 小時）**，無上限；所有「待生效」的變更（設定的 `requires_pending`／放寬、權限矩陣、財務機制、簽核政策…）的 `effective_at` 一律＝申請時間＋`confirm_period_days` 天。各設計稿**引用此鍵，不得自訂期間**。此設定本身是 `legal` 風險、`loosen='down'`：**縮短確認期視同放寬**，要走「目前的確認期」＋雙人核准才會生效；拉長則立即生效。已在待生效中的舊變更，其 `effective_at` 在申請當下已寫定，不受之後調整影響。登錄：群組 `change_control`（白話名稱「變更管理」），欄位問句「重要設定變更，要等幾天才生效？」，建議值 7；`settings_registry.PENDING_HOURS` 常數於 Train A 之後的第一個小改動改為讀此鍵（Train A 現況：常數 24 小時，尚無使用中的待生效欄位，所以不影響上線行為）。
7. 兩份設計稿以此節為準；任何一方要改協議，先改這一節並通知對方。

## 3. 各 K 項的遷移與等價證明

通用做法：①登錄群組，預設＝舊常數；②讀取點換成 `settings.get()`（缺列＝舊值）；③刪除重複字面值，舊常數名保留一班作別名；④守門：`test_settings_defaults_equal_legacy`（凍結在 `settings_deploy_baseline.json` 的部署值＝登錄預設＝舊常數，三方相等）、`test_no_legacy_literal`（舊字面值不得回流）、上下限與 `cross_check` 的正反測試。

| K | 群組與欄位（預設＝今天） | 改動點 | 等價證明 |
|---|---|---|---|
| K01 利潤警示 | `profit_warning`：`quote.red_below=12`、`quote.yellow_below=20`、`settlement.green_from=20`、`reports.green_from=20`、`reports.orange_from=10`、`export.green_from=20`、`export.amber_from=0`（%；僅顯示，risk none） | `quotation-form.html:1911/1915/1916`、`settlement.html:1019`、`reports.html:1563`、`reports.py:2198`、`pdf_gen.py:2702`；`profit_rules.py:34` 與 `profit-rules.js:10/74` 的 `TARGET_MARGIN_PCT` **保留為字面常數 12，作為登錄預設值的鏡像**（不是執行時導出：L1 快照記的是常數、`tests/test_profit_rules_t48.py:87` 斷言 ==12、前端是靜態字面值）；由 `test_settings_defaults_equal_legacy` 守住「鏡像＝登錄預設」；`test_no_legacy_literal` 對它列為**已知例外**（見 §3 末） | 各畫面**維持各自的語意與數值**（不順手統一，統一是之後改一個值的事）；以黃金向量（毛利率 −5～40 每 0.1）比對舊三元式與新函式，前端用 node、後端用 Python，沿用 `profit_rules_vectors.json` 做法；文字「低於目標 12%」改插值，預設輸出逐字相同 |
| K08 提醒天數 | `reminders`：`payable.soon_days=3`、`approval.remind_stages=[1,3,5]`、`approval.remind_step=5`、`crm.stale_days=30`、`crm.renotify_days=14`、`crm.hold_auto_convert_days=180`、`quote.followup_days=14`、`warranty.warn_days=[7,30]`、`ar_aging.orange_over=60`、`ar_aging.red_over=90`、`map.closing_soon_days=7`；`quote.valid_days_review_over=30`（**risk money**：是審核觸發條件） | `payable_due_core.py:33/39`、`cashier.html:370/503`、`system_checks.py:503`、`crm/api.py:1083-1085`、`dashboard.py:584/654`、`case_deadlines.py:218`、`reports.py:1862`、`map_points.py:1025`、`quotation-form.html:2253/2599`＋`quotations.py:1557` | 抽成純函式（日期、天數、設定值→等級），對 ±400 天日期格比對舊／新；既有提醒測試**不改動即全綠**；前後端的「3 天／30 天」改讀同一個鍵（消除重複）；`payable_reminders` 的「08:00＋補跑」語意不動（時刻不在第一批） |
| K05＋K06 保存與容量 | `retention` 包住現有 `backup_retention`（六鍵不變）＋新增 `notification_keep_days=90`、`request_log_keep_days=90`；`uploads`：`max_file_mb=20`、`case_extra_expense.max_files=10`、`max_request_mb=50`。**稽核紀錄 `audit_log_keep_days` 下限 365、無上限**（其餘保留鍵維持 1～3650） | `archive.py:52/62`、`routers/system.py:2277-2314`（PATCH 轉為同一支發布）、`audit.py:165`、`system_checks.py:731`、`uploads.py:38/43` | 第一次發布時把現有 `backup_retention` 值原樣存成 v1，`_backup_retention()` 先讀群組、缺列退回舊鍵（雙讀一班）；部署前後值比對腳本；**唯一有意的行為差異**：已存的 `audit_log_keep_days<365` 在讀取時**向上夾到 365**（只會多留、不會多刪）並在設定中心提示——先查正式機現值，預期是預設 1825。副檔名白名單**不開放**（檔頭檢查是 fail-closed） |
| K10 徽章與選項 | `options.crm_status`、`options.netplan_status`、`options.expense_category`：項目 `{code,label,color,active,order}`，`code` 發布後不可改、不可刪只能停用（沿用 `remit_kinds` 規則）；`status_badges`：狀態→**既有 CSS badge 類別**（固定清單，不收任意色碼） | `crm/api.py:26`、`netplan/api.py:58`、`case_extra_expenses.py:91`＋伺服器端狀態驗證改讀登錄；前端 `static/status-badge.js` 取代 `case-management-dispatch.js:845`、`-fin.js:699/802`、`-shipping.js:471`、`payment-request-form.html:394` | 五份對照表**已用雜湊比對確認逐字相同**，合併後外觀不變；選項預設＝今天的清單，伺服器接受值＝啟用的 `code`；硬編碼十六進位色的完工單頁（`completion-note-form.html:455`）**不在第一批**，因為換成徽章類別會改外觀 |

> **`test_no_legacy_literal` 已知例外**：`TARGET_MARGIN_PCT = 12`（`profit_rules.py:34`、`profit-rules.js`）保留字面值作為登錄預設的鏡像，由 `test_settings_defaults_equal_legacy` 比對；刪除該常數屬於 K01 之後的清理，需先改測試與 L1 快照。

## 4. 設定中心頁（系統 > 設定中心，僅 superadmin 可改）

- 左欄群組樹（依領域分組、搜尋、風險徽章、「已改過」標記）；右側表單由 `SettingDef` 產生：數值輸入帶單位與上下限提示、每欄「還原預設」、即時伺服器驗證、發布前**差異預覽**（舊→新、影響說明）、原因欄（`risk≥money` 必填）。
- 頁籤：**目前值／版本**（清單、差異、還原，直接沿用 `remit-kinds-settings.js` 的流程）／**索引**（已有專屬頁的設定，如簽核、款別、法規參數、公司資料，只放連結與最近變更）。
- 非 superadmin 看不到；`finance` 對 `visibility=finance` 群組唯讀（待權限矩陣落地後改查能力）。

## 5. 稽核、回滾、緊急開關

- 每次發布寫 `definitions.publish`（既有）＋`settings.<群組>.update`（沿用既有稽核篩選命名），明細含逐欄舊→新與原因；還原寫 `settings.<群組>.restore`。
- 回滾＝還原到舊版本（產生新版本，歷史不改）；**緊急開關**：環境變數 `MOTRIX_SETTINGS_DEFAULTS_ONLY=1` 讓 `settings.get()` 一律回程式預設（不改資料庫）；最後手段是刪除該群組的定義列＝回到程式預設。
- 測試：`conftest` 在每題前後清設定快取與 `setting_group` 列，避免測試互相污染。

## 6. 分期與工作量

| 期 | 內容 | 工作量 |
|---|---|---|
| S0 | 登錄、`settings.get()`、kind、發布／公開端點、四道守門、稽核與通知 | M（約 4 人日） |
| S1 | 設定中心頁（表單產生器、版本、差異、還原） | M（約 4 人日） |
| S2 | K05＋K06（接線為主、風險最低，先上） | S～M（約 3 人日） |
| S3 | K01 利潤警示 | S～M（約 2.5 人日） |
| S4 | K08 提醒天數（約 16 個讀取點、日期格測試） | M（約 4 人日） |
| S5 | K10 徽章與選項清單 | S～M（約 3 人日） |

合計約 20～21 人日。建議三班：**甲班** S0＋S2，**乙班** S1＋S3，**丙班** S4＋S5；每班都是「預設值不變」的上線，使用者之後在畫面上改才有行為變化。第二批：K04（接 `config_ledger` 的待生效層與安全評審）；再之後是簽核金額級距（與權限矩陣一起設計，儲存可直接用同一個 `setting_group`／approval-flow 擴充）。

## 7. 風險與待決

- **預設值被悄悄改**：之後有人改了程式預設，所有沒自訂過的人都會跟著變。規則：改 `SettingDef.default` 要同班更新 `settings_deploy_baseline.json` 並寫更新紀錄，守門強制。
- **前後端不同步**：一律由登錄表產生兩邊的預設；`test_no_legacy_literal` 防舊字面值回流。
- **舊版本還原遇上收緊的上下限**：以現行上下限驗證並擋下（訊息指出哪一欄）。
- **排程類設定**（每日 08:00、備份間隔）不在第一批：改時刻要連動重試語意與守門。
- **待確認**：①五個畫面的利潤警示門檻是否要統一（預設維持各自）；②`audit_log_keep_days` 讀取時夾到 365 是否接受；③`config_ledger` 最小介面（§2）；④`visibility=public` 的群組是否僅限登入者可讀（建議是）。

## 附錄 B 風險選項框架與「暫列鎖定」清單（使用者 2026-10-10：連「可簽自己的核准」也要是選項）

**原則**：任何需要改動或改動有風險的東西，都做成擁有者可決定的選項；「必須留在程式」只是暫列鎖定、逐項待使用者確認，不是終局。

**機制（框架，Train A 已內建）**
- `SettingDef.risk ∈ none|ops|money|legal|security` ＋ `requires_pending`（bool）。`requires_pending` 的欄位（建議 money／legal／security 全開）經 `publish()` 時**不立即生效**：寫 `config_changes`（`effective_at` ＝ 現在＋待生效期（預設 7 天，下限 24 小時），`pending` 事件）、通知其他最高管理者；期間任何最高管理者可 `cancel`（寫稽核）；`settings.get()` 在讀取時以 `in_effect()` 判斷——到期前仍回舊值。
- 解鎖一個鎖定項＝在 `settings_groups` 新增一個欄位（預設＝今天的行為，等值證明＋凍結基準），標 `risk` 與 `requires_pending`，再接線；**不需要動別的地方**。
- 變更一律：原因必填＋稽核＋通知＋版本可還原。

**暫列鎖定、待使用者逐項確認（我盤點的清單）與解鎖時的方案**
| 項目 | 今天（預設） | 若解鎖：選項與風險機制 |
|---|---|---|
| 密碼雜湊參數 | 程式固定 | 只開放「提高強度」，不可降低（下限寫在程式）；`security`＋待生效期；既有密碼下次登入重雜湊 |
| 最高管理者直通 | 恆為真 | 選項「最高管理者也受權限矩陣約束」預設關；`security`＋待生效期；保留至少一位不受限的緊急帳號 |
| 公開路徑白名單 | 程式清單 | 只開放「縮減」（把公開頁改成要登入）；新增公開路徑不開放；`security`＋待生效期 |
| 稽核紀錄只增不改 | 觸發器擋 | 不提供「可改」；僅提供匯出與保存年限（已有，下限 365） |
| 路徑逃逸／簽章檢查 | 程式固定 | 不提供關閉；若要放寬簽章驗證範圍，`security`＋待生效期＋雙人核准 |
| 舊 10% 管銷口徑 | 舊單沿用 | 選項「新單預設口徑」（已有 25% 設定）；舊單戳記不動；`money`＋待生效期 |
| `FORM_VERSION` | 程式固定 | 不開放（版本戳是資料相容用）；改版走遷移 |
| 已過帳傳票不可變 | 不可變 | 選項「允許以更正傳票沖銷」（不是修改）；`money`＋待生效期＋雙人核准 |
| 401 錯誤碼 | 程式固定 | 不開放（前端契約） |
| `MQ-` 單號格式 | 程式固定 | 選項「前綴／補零位數」；僅對新單生效；`ops` |
| 回收桶 30 天 | 30 天 | 設定群組 `recyclebin.keep_days`（下限 7）；`ops` |
| D1 只存草稿 | 只存草稿 | 待確認需求後再設計；先列待決 |
| 可簽自己的核准（本人送審本人核） | 不允許 | 選項「允許本人核准」預設關；`money`＋待生效期＋稽核標註「自核」＋通知其他最高管理者；金額上限欄位可配 |
| 副檔名白名單／檔頭檢查 | 程式固定 | 只開放「在安全清單內縮減」；新增副檔名需 `security`＋待生效期 |
| 金額公式與進位 | 程式固定 | 公式不開放；參數（費率、門檻）依生效日已開放（§11） |

以上每一項都**等使用者確認**後才排入批次；未確認前維持今天的行為。

## 附錄 C 介面規則：零技術門檻（使用者 2026-10-10）

**零技術門檻**（使用者 2026-10-10 強化）：每個設定畫面都當使用者完全不懂技術來設計——①用白話中文**問問題**、選項很少（「財務可以送出勞報單嗎？　可以／不可以」），不放鍵值表；②標出**建議**選項；③常見情境給一鍵**預設組**（如「小型公司」「嚴格管控」），套用前先顯示會造成的效果；④進階選項收在「進階」；⑤複雜設定做成一步一步的精靈；⑥儲存前用一句話摘要（「你即將讓財務可以送出勞報單，待生效期滿後生效」）並預覽受影響的人；⑦一鍵復原。

結構強制：`SettingDef`／能力／欄位政策宣告**必填** `question`（問句）、`label`、`help`、選項標籤、風險文字（高風險）、`effect`（效果句型，含 `{舊}`／`{新}`／`{生效時間}`）；可填 `recommended`（建議）、`presets`（所屬預設組）、`advanced`（進階）。缺必填 ⇒ 登錄驗證失敗。

**`SettingDef` 欄位（Train A 起強制）**

| 欄位 | 必填 | 說明 |
|---|---|---|
| `question` | 是 | 白話問句，例：「稽核紀錄要保留幾年？」 |
| `label` / `help` | 是 | 簡短標籤／一行說明（繁中） |
| `choices[(值, 中文標籤)]` | 選項型必填 | 少量選項；數字型用滑桿／步進＋單位 |
| `risk_text` | risk≥money 或 `requires_pending` 時必填 | 白話風險提示 |
| `effect` | 是 | 效果句型：「你即將把 {名稱} 從 {舊} 改成 {新}，{生效時間}生效」 |
| `recommended` | 否 | 建議值（畫面標「建議」） |
| `presets` | 否 | 所屬預設組（如「小型公司」「嚴格管控」）；預設組套用前顯示逐項變更預覽 |
| `advanced` | 否 | 收在「進階」 |

畫面共用元件：問句卡片、預設組挑選器（套用前預覽）、進階收合、精靈（多步驟設定）、儲存前確認句＋受影響清單、變更紀錄頁上的「一鍵復原到這一版」。內部鍵只存在程式與稽核明細，不顯示在這些畫面。

### C.2 影響說明（impact；使用者 2026-10-10）

**每個選項旁邊都說明「會影響什麼」**（使用者 2026-10-10）：每個欄位與每個選項宣告白話**影響說明**（`impact`）——影響哪些頁面、單據、人；只影響之後的單據還是連既有的也改；能否復原；何時生效；風險提示。可再宣告**即時影響函式**（唯讀查庫回數字，例「會影響 12 張未精算報價單、5 位使用者」；有快取與時限，失敗只顯示靜態說明）。畫面在選項旁放影響面板（切換選項即更新，前後對照），並重複在儲存前的一句話摘要。登錄項目缺影響說明 ⇒ 驗證失敗。

| 欄位 | 必填 | 說明 |
|---|---|---|
| `impact` | 是（欄位層級） | 白話影響說明：誰／哪些畫面與單據受影響；既有單據或只影響之後；可否復原；何時生效 |
| `choices[i].impact` | 選項型必填 | 每個選項各自的影響說明 |
| `impact_fn(conn, 新值) -> {數字, 句子}` | 否 | 唯讀即時影響；逾時（預設 1.5 秒）、結果快取 60 秒、失敗只顯示 `impact` |

畫面：選項旁的影響面板（前後對照）＋儲存前確認句重複影響摘要。守門：登錄欄位或選項缺 `impact` ⇒ 驗證失敗；`impact_fn` 只准讀取（以唯讀連線執行）。

## 附錄 D 安全風險類別、雙人核准與政策預設組（使用者 2026-10-10 裁示）

**裁示**：公開頁面、密碼雜湊強度、檔案路徑／簽章檢查、允許上傳類型四項**不鎖死**，雙向可調（可收緊也可放寬），因為未來要販售、必須保有最大彈性；放寬用最強管制。

**機制（Train A 已實作於 `settings_registry` 與 `config_ledger`）**
- 欄位宣告 `risk="security"`（另有 money／legal）與 `loosen="up"|"down"`（哪個方向算放寬）。**收緊立即生效；放寬**＝待生效（預設 7 天）＋需要**另一位在職最高管理者核准**（`config_ledger.approve`：申請人不能自核、同一人不能重複投票；票數不足時到時間也不生效）。只有一位最高管理者時：必填原因＋待生效期（預設 7 天，下限 24 小時）＋畫面警告＋通知，並留紀錄。
- 資料：`config_changes.approvals_required`、事件 `approved`（只增不改）；待生效清單與撤銷介面（`/api/settings-center/pending`、`…/approve`、`…/cancel`）。
- **版本邊界**：`set_edition_bounds(group, field, min, max)` 由程式／授權載入器設定，與欄位自己的上下限取交集；客戶沒有任何 API 能改；畫面顯示的範圍是交集後的有效範圍。販售不同版本＝同一份程式、不同邊界。
- **政策預設組**：欄位 `presets={"標準": v, "嚴格": v, "寬鬆": v}`；`profiles()`／`profile_preview(name)`（套用前顯示逐項「目前 → 新值」）／`apply_profile(name)`（每個群組各走一次 `publish`，同一套管制，所以套用「寬鬆」也要雙人核准）。建置客戶環境時套用預設組，之後客戶在邊界內自行調整。
- 白話文字：每個安全欄位必填 `risk_text`（例：「調大後可能讓過大的檔案進入系統」）與 `impact`；守門 `test_settings_ui_plain_language`。

**仍維持不可改／鎖定（使用者裁示）**：稽核只增不改（保存年限可調，至少 365 天）、單據版本標記、登入錯誤碼；舊單 10% 管銷口徑、已過帳傳票只能沖銷、金額公式與進位。
