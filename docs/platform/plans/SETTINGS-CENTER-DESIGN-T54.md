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

- `config_ledger` 只做兩件定義文件庫沒有的事：**變更明細**（`domain, key, 欄位, 舊→新, 原因, 操作者, IP`，只增不改）與**待生效**（`effective_at`、撤銷、到期轉態，即 1d 的 24 小時機制）。
- 版本與還原留在各 domain 自己的儲存：權限＝`perm_versions`，設定＝`ui_definitions`。`snapshot/restore` 以 adapter 形式註冊，不複製資料。
- 設定的 domain＝`setting:<群組>`，權限＝`perm`；第一批設定**不用**待生效層（只有 K04 與高風險授權用），所以 `config_ledger` 可晚於設定中心第一版上線，介面先寫死 `record(domain, key, changes, reason, actor, effective_at=None)`。請 1d 確認這個最小集合。

## 3. 各 K 項的遷移與等價證明

通用做法：①登錄群組，預設＝舊常數；②讀取點換成 `settings.get()`（缺列＝舊值）；③刪除重複字面值，舊常數名保留一班作別名；④守門：`test_settings_defaults_equal_legacy`（凍結在 `settings_deploy_baseline.json` 的部署值＝登錄預設＝舊常數，三方相等）、`test_no_legacy_literal`（舊字面值不得回流）、上下限與 `cross_check` 的正反測試。

| K | 群組與欄位（預設＝今天） | 改動點 | 等價證明 |
|---|---|---|---|
| K01 利潤警示 | `profit_warning`：`quote.red_below=12`、`quote.yellow_below=20`、`settlement.green_from=20`、`reports.green_from=20`、`reports.orange_from=10`、`export.green_from=20`、`export.amber_from=0`（%；僅顯示，risk none） | `quotation-form.html:1911/1915/1916`、`settlement.html:1019`、`reports.html:1563`、`reports.py:2198`、`pdf_gen.py:2702`；刪 `profit_rules.py:34` 與 `profit-rules.js:10/74` 未使用的 `TARGET_MARGIN_PCT` | 各畫面**維持各自的語意與數值**（不順手統一，統一是之後改一個值的事）；以黃金向量（毛利率 −5～40 每 0.1）比對舊三元式與新函式，前端用 node、後端用 Python，沿用 `profit_rules_vectors.json` 做法；文字「低於目標 12%」改插值，預設輸出逐字相同 |
| K08 提醒天數 | `reminders`：`payable.soon_days=3`、`approval.remind_stages=[1,3,5]`、`approval.remind_step=5`、`crm.stale_days=30`、`crm.renotify_days=14`、`crm.hold_auto_convert_days=180`、`quote.followup_days=14`、`warranty.warn_days=[7,30]`、`ar_aging.orange_over=60`、`ar_aging.red_over=90`、`map.closing_soon_days=7`；`quote.valid_days_review_over=30`（**risk money**：是審核觸發條件） | `payable_due_core.py:33/39`、`cashier.html:370/503`、`system_checks.py:503`、`crm/api.py:1083-1085`、`dashboard.py:584/654`、`case_deadlines.py:218`、`reports.py:1862`、`map_points.py:1025`、`quotation-form.html:2253/2599`＋`quotations.py:1557` | 抽成純函式（日期、天數、設定值→等級），對 ±400 天日期格比對舊／新；既有提醒測試**不改動即全綠**；前後端的「3 天／30 天」改讀同一個鍵（消除重複）；`payable_reminders` 的「08:00＋補跑」語意不動（時刻不在第一批） |
| K05＋K06 保存與容量 | `retention` 包住現有 `backup_retention`（六鍵不變）＋新增 `notification_keep_days=90`、`request_log_keep_days=90`；`uploads`：`max_file_mb=20`、`case_extra_expense.max_files=10`、`max_request_mb=50`。**稽核紀錄 `audit_log_keep_days` 下限 365、無上限**（其餘保留鍵維持 1～3650） | `archive.py:52/62`、`routers/system.py:2277-2314`（PATCH 轉為同一支發布）、`audit.py:165`、`system_checks.py:731`、`uploads.py:38/43` | 第一次發布時把現有 `backup_retention` 值原樣存成 v1，`_backup_retention()` 先讀群組、缺列退回舊鍵（雙讀一班）；部署前後值比對腳本；**唯一有意的行為差異**：已存的 `audit_log_keep_days<365` 在讀取時**向上夾到 365**（只會多留、不會多刪）並在設定中心提示——先查正式機現值，預期是預設 1825。副檔名白名單**不開放**（檔頭檢查是 fail-closed） |
| K10 徽章與選項 | `options.crm_status`、`options.netplan_status`、`options.expense_category`：項目 `{code,label,color,active,order}`，`code` 發布後不可改、不可刪只能停用（沿用 `remit_kinds` 規則）；`status_badges`：狀態→**既有 CSS badge 類別**（固定清單，不收任意色碼） | `crm/api.py:26`、`netplan/api.py:58`、`case_extra_expenses.py:91`＋伺服器端狀態驗證改讀登錄；前端 `static/status-badge.js` 取代 `case-management-dispatch.js:845`、`-fin.js:699/802`、`-shipping.js:471`、`payment-request-form.html:394` | 五份對照表**已用雜湊比對確認逐字相同**，合併後外觀不變；選項預設＝今天的清單，伺服器接受值＝啟用的 `code`；硬編碼十六進位色的完工單頁（`completion-note-form.html:455`）**不在第一批**，因為換成徽章類別會改外觀 |

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
