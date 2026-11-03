# 稽核：T73 業務開發案件指派成員／回覆期限／進度回報（PM 派 subagent 複核，第二輪）

> 依 PLAYBOOK §E（交叉稽核）。對象：`train/t73-int` 分支（`origin/platform..origin/train/t73-int`，4 個 commit：
> `9a2b0994d`（squash：wip/t73-dev-case-assignment-r1，21 檔）、`8922cf416`（取號 1.148→1.149）、
> `b878045f8`（重產 dep_graph／UNIT-INDEX／test_map）、`1120159de`（version_manifest.json 補）。
> 稽核者未參與 T73 任何部分，符合「不得稽核自己寫的包」。本稽核純讀程式碼／文件／git diff，未執行 pytest 或啟伺服器
> （機器當時在跑官方閘門 `build_test_reuse.py run-stage --stage not_e2e`），凡需要「跑起來看」才能確認的項目已標 TODO-VERIFY。
> 分級：**必修**／**建議**／**觀察**。本輪由 PM 另派一個未參與 T73 編碼的 subagent 執行（非 hichan-2 視窗；
> 與 `AUDIT-hichan3-t73.md` 的 hichan-3 視窗為兩條獨立稽核線，findings 已由 PM 交叉核對）。關閉規則：
> 被稽核者回覆後，由 PM 確認才關。

## 0. 結論

- 核心權限模型（`DEV_CASE_ACCESS` 加 `owner_id_col="assigned_to"`）設計正確，`row_access.visible()`／`filter_sql()`
  的 None 處理與既有 `test_row_access_2026_09_25.py` 的 SQL↔Python 等價性測試已覆蓋，取消指派會正確收回權限。
  migration 冪等、只增欄，回滾風險低。
- **必修 2 項**：
  1. A-1：排程 `_check_dev_case_stale()` 漏了第 5 處「手列欄位缺 `assigned_to`」——被指派人不會收到逾期案件提醒。
  2. A-2：analytics 1.0.45 CHANGELOG 聲稱的測試覆蓋與實際測試內容不符（假綠燈）：
     `dashboard_ops_alerts`／`dashboard_activity_feed` 的修正完全沒有測試執行到。
- 建議 2 項、觀察 3 項。
- 驗證方式：全部以讀程式碼＋ `grep -rn` 交叉比對推論，未實跑 `pytest`（遵守派工限制）。

## 1. 逐項驗收

| 項目 | 規格／裁示 | 驗收 | 證據 |
|---|---|---|---|
| `DEV_CASE_ACCESS` 加 `owner_id_col="assigned_to"` | 被指派人取得與業務／企劃同等完整權限 | ✅ | `backend/modules/crm/api.py:126-133`；`row_access.visible()`（`backend/helpers/row_access.py:118-122`）`oid is not None and oid == uid` 對 NULL 正確不命中 |
| `PATCH /dev-cases/{id}/assign` 僅管理員 | 403 非管理員 | ✅ | `api.py:608-610`；測試 `test_dev_case_assignment_2026_11_03.py::test_assign_requires_admin` |
| `/assign` 400：對象不存在／停用／無 `dev_crm` 模組 | 需檢查 | ✅ | `api.py:624-630`；測試 `test_assign_validates_target_user` |
| `/assign` 404：案件不存在 | 需檢查 | ✅ | `api.py:615-616`；測試 `test_assign_missing_case_is_404` |
| `/assign` 審計寫入 | `_audit` | ✅ | `api.py:638-639`，與同檔其他端點（例如 `:594` status）同一寫法 |
| `/assign` 通知（站內＋email） | 需觸發 | ✅ | `api.py:643-651`；`helpers/email_notify.py` 新增 `notify_dev_case_assigned`；`mail_types.py`／`notification_prefs.py` 同步登記；測試驗 `notifications` 表（`test_assign_success_writes_db_response_and_notification`） |
| 取消指派（`assignedTo: null`） | 正確收回權限 | ✅ | `test_assignee_gets_full_row_access_until_unassigned`：取消後 `GET`／`PATCH status` 皆 403，且取消前的改動不受影響 |
| `PATCH /dev-cases/{id}/progress` 權限 | 被指派人或 admin，非 row_access 完整存取者 | ✅ | `api.py:671-672`（刻意比對 `user["id"] == assigned_to`，不是 `row_access.visible`）；測試 `test_progress_denied_for_non_assignee_non_admin`（建立者在列權限內但 403） |
| `/progress` 404／審計 | 需檢查 | ✅ | `api.py:668-669`、`:679` |
| migration `0002_dev_case_assignment.py` 只增、冪等 | 不動凍結 schema | ✅（讀碼推論，未實跑） | `migrations/0002_dev_case_assignment.py:11-21`，與既有 `0001_dev_cases_referrer.py` 同一模式；`cols` 檢查防重複 `ALTER TABLE` |
| 4 處「手列欄位」補 `assigned_to`（CHANGELOG 聲稱） | item_reads／activity-stats／analytics 停滯提醒／動態牆 | ⚠ 4/5（漏第 5 處） | `item_reads.py:193`、`api.py:887`（activity-stats）、`dashboard.py:683`、`dashboard.py:914-915` 已補；`api.py:1207`（`_check_dev_case_stale`）**沒有補**，見 A-1 |
| 舊資料相容（缺三欄時 GET 不 500） | 需檢查 | ✅ | `test_legacy_row_without_assignment_columns_does_not_crash`（DROP COLUMN 模擬） |
| 契約快照（`l1_interface_snapshot.json`／`response_keys_baseline.json`／`route_inventory.json`／`version_manifest.json`） | 重產應與程式碼一致 | ✅ | 新端點、新回應鍵、新公開函式簽名、版號 1.148→1.149、使用者可見變更紀錄四處互相一致（git show 逐一核對） |

## 2. 發現

### 必修

**A-1　排程 `_check_dev_case_stale()` 沒有把被指派人納入停滯提醒收件人**
- 位置：`backend/modules/crm/api.py:1206-1239`（`SELECT` 在 `:1207`，收件人組裝在 `:1228-1239`）。
- 這是「洽談中案件超過 30 天未更新」每日排程（`:1194`），收件人＝`sales_persons`＋`planners`（JSON 陣列）＋
  （以上皆空時）`created_by`＋所有 `admin`/`superadmin`。這個 SELECT 手列欄位，**沒有列 `assigned_to`**，
  也沒有把被指派人併入 `usernames`。
- 為什麼是必修：T73 的裁示是「被指派人取得與業務／企劃同等的完整權限」，crm 1.0.18／analytics 1.0.45
  CHANGELOG 已明確列出「4 處手列欄位漏 `assigned_to`」並逐一修正（`item_reads.py`、`api.py::dev_crm_activity_stats`、
  `dashboard.py` 兩處），但同一個檔案裡的這個排程函式是**第 5 處同類缺陷**，被兩輪審查（hichan-9、hichan-10）都漏掉。
  結果：一個只被指派（不在 `sales_persons`／`planners`、也不是建立者）的人，案件逾期 30 天也不會收到任何提醒
  （站內通知＋email 都不會發），但他是這個功能設計下唯一該負責跟進的人。
- 重現（讀碼即可確認，不需要跑）：
  - `backend/modules/crm/api.py:1207` 的 SELECT 欄位清單與 `item_reads.py:193`／`dashboard.py:683`／`dashboard.py:914-915`
    的欄位清單對照，前者缺 `assigned_to`，後三者都有。
  - `backend/modules/crm/tests/` 底下 `grep -rn "_check_dev_case_stale\|dev_case_stale" `無任何測試檔把
    `assigned_to` 與這個函式放在一起驗證（`test_dev_case_assignment_2026_11_03.py`、
    `test_dev_case_assignee_visibility_hichan10_2026_11_03.py` 都沒有覆蓋到）。
- 建議修法：`:1207` 的 SELECT 加 `assigned_to`；`:1236` 的 `usernames` 併入
  `[uid_map[row["assigned_to"]]] if row["assigned_to"] in uid_map else []`；補一題仿
  `test_dev_case_assignee_visibility_hichan10_2026_11_03.py` 的寫法，直接呼叫
  `api._check_dev_case_stale()` 或跑排程後檢查 `notifications` 表。

**A-2　analytics 1.0.45 CHANGELOG 聲稱的測試覆蓋與實際測試內容不符（假綠燈）**
- 位置：`backend/modules/analytics/CHANGELOG.md`（1.0.45 段）寫「修正 `api/dashboard.py` 的業務開發停滯提醒
  （`dev_stale`）與動態牆（`dev_cases` 區塊）手列欄位的 SELECT 補上 `assigned_to`」，並列測試為
  `modules/crm/tests/test_dev_case_assignee_visibility_hichan10_2026_11_03.py`。
- 實際讀 `test_dev_case_assignee_visibility_hichan10_2026_11_03.py` 全文（99 行，3 個測試函式）：
  - `test_assignee_sees_the_case_in_the_list_baseline`：打 `GET /api/dev-cases`（`SELECT *`，本來就會過）。
  - `test_assignee_gets_unread_marks_for_their_assigned_case`：打 `POST /api/reads/unread`（對應
    `routers/item_reads.py`，不是 `dashboard.py`）。
  - `test_assignee_activity_stats_counts_their_assigned_case`：打 `GET /api/dev-crm/activity-stats`（對應
    `modules/crm/api.py::dev_crm_activity_stats`，不是 `dashboard.py`）。
  - **三題都不呼叫 `/api/dashboard/ops-alerts` 或 `/api/dashboard/activity-feed`**（路由定義在
    `backend/modules/analytics/api/dashboard.py:664-665`、`:841-842`）。
  - 用 `grep -rn "dashboard/ops-alerts\|dashboard/activity-feed" backend/` 可重現：命中的既有測試
    （`test_row_access_callers_2026_09_25.py`、`test_dept_follows_sales_owner_2026_10_01.py`、
    `test_dashboard_connections_2026_09_22.py`、`test_queue_and_feed_scoping_2026_09_15.py`）全部與 `quotations`／
    `materials`／部門過濾相關，沒有一題用 `dev_cases.assigned_to` 當資料去驗證這兩個端點。
- 為什麼是必修：這正是 §E 要求的「找假綠燈：綠燈是真的，但證明的是另一件事」——CHANGELOG 寫的「測試」
  是真的綠燈（這三題真的會過），但它們證明的是 `item_reads.py` 與 `crm/api.py` 的修正，**不是**
  `dashboard.py` 的修正。`dashboard.py:683`、`:914-915` 這兩行改動本身，讀程式碼邏輯是對的（單純補一欄給
  `row_access.visible()` 讀取，與其他三處同一模式），但目前完全沒有自動化測試保護，往後有人不小心改掉
  也不會被抓到。也違反專案規則「宣稱測試通過要附上指令和原始輸出」——這裡連「附哪一題」都對不上。
- 建議修法：仿 `test_dev_case_assignee_visibility_hichan10_2026_11_03.py` 的模式，在同檔或
  `modules/analytics/tests/` 下補兩題：被指派人（非 `sales_persons`／`planners`／建立者）對一筆「洽談中」
  且逾期的案件呼叫 `/api/dashboard/ops-alerts`，應該看到該提醒；對一筆有活動的案件呼叫
  `/api/dashboard/activity-feed`，應該看到該筆動態。

### 建議

**B-1　`/assign` 的 `assignedTo`／`replyDeadline` 沒有區分「沒帶這欄」與「刻意設 null」**
- 位置：`DevCaseAssignIn`（`api.py:77-82`）兩欄預設值都是 `None`；`:632-633` 的 `UPDATE` 永遠整組覆寫兩欄。
- 目前唯一呼叫端 `frontend/pages/dev-crm.html` 的 `saveAssign()` 每次都把 `assignDraft`（從目前案件狀態初始化）
  兩欄一起送，所以現狀不會觸發問題。但 API 本身沒有用 Pydantic 的 `model_fields_set`／`exclude_unset` 分辨
  「只想改期限」與「要把指派也清空」，之後如果有別的呼叫端（行動版、整合腳本）只送 `{"replyDeadline": "..."}`，
  會把現有 `assigned_to` 連帶清空。
- 建議：改成只處理請求裡真的帶到的欄位，或在文件／型別上明確要求兩欄必須一起送。

**B-2　取消指派不會自動清空 `reply_deadline`**
- 位置：`api.py:631-634`；`frontend/pages/dev-crm.html` 的 `saveAssign()`（約行 180-194，`assignDraft.deadline`
  若使用者只改了指派下拉、沒清日期欄，會把舊期限原樣送出）。
- 取消指派後 `assignedToId` 會是 `null`，但 `replyDeadline` 可能還留著舊值，`_case_row()`（`api.py:283-288`）
  原樣回傳 → 畫面可能顯示「負責：未指派｜期限：2026-12-01」，造成管理上的疑惑（不是安全問題）。
- 建議：後端在 `assigned_to` 設為 `null` 時順便把 `reply_deadline` 也清空，或前端在選「未指派」時自動清空日期欄。

### 觀察

**C-1　migration 重跑兩次／`dev_cases` 表不存在的行為只用讀碼＋對照 `0001` 驗證，未實跑**
- `migrations/0002_dev_case_assignment.py:11-21` 與既有 `0001_dev_cases_referrer.py:10-16` 同一模式
  （`cols` 存在性檢查、表不在時回原因字串不前進版號）。守門 `tests/platform/test_module_migrations.py`
  理論上會覆蓋，但本次稽核依派工限制沒有實際跑 pytest。TODO-VERIFY(pm)：找機器空檔時跑
  `python -m pytest backend/tests/platform/test_module_migrations.py -k crm` 確認。

**C-2　`progress_report`／`reply_deadline` 沒有長度上限**
- `DevCaseAssignIn`／`DevCaseProgressIn`（`api.py:77-85`）都是裸 `str`／`Optional[str]`，沒有像 `referrer`
  （`REFERRER_MAX`，`api.py:244`）一樣的長度檢查。與既有 `case_name` 等欄位現狀一致，不是本次新增的缺陷，
  純粹記錄：之後統一規範自由文字欄位上限時可以一併處理。

**C-3　被指派人之後被停用／拿掉 `dev_crm` 權限，`assigned_to` 不會自動清掉**
- `_require_user`（`backend/helpers/auth.py:449-464`，session join `u.active=1`）與 `_require_dev`
  （`api.py:107-111`）會在後續請求擋掉已停用或沒有 `dev_crm` 模組的人，**不是安全缺口**；但案件上仍會留著
  「指派給一個現在打不開這張案件的人」的殘留狀態，`assignedToName` 仍會顯示該人姓名，可能造成管理上的困惑。
  非本次範圍要求，列為觀察。

## 3. 反向控制與假綠燈檢查

- **被指派人是 null 時，`sales_persons`／`planners` 不會被誤改**：`/assign` 的 `UPDATE` 只碰
  `assigned_to`、`reply_deadline`、`updated_at` 三欄（`api.py:631-634`），不碰 `sales_persons`／`planners`。✅
- **指派給無 `dev_crm` 模組或已停用帳號**：兩者都在 `/assign` 內以 400 擋下（`api.py:627-630`），且有測試
  覆蓋（`test_assign_validates_target_user`）。✅
- **取消指派後正確收回權限**：`test_assignee_gets_full_row_access_until_unassigned` 直接驗證
  `GET`／`PATCH status` 取消後變 403，且取消前的修改不受影響。✅
- **migration 重跑兩次**：讀碼確認冪等（`cols` 檢查），未實跑，見 C-1。⚠（TODO-VERIFY）
- **回滾風險**：只新增欄位，舊程式碼不讀取新欄位、`SELECT *` 自動帶出不影響舊邏輯；唯一「只能往前」的
  效果是已發出的指派通知信（email／站內通知）與已寫入的 `assigned_to`／`progress_report` 資料本身無法隨
  程式碼回滾一起消失——這是任何通知／資料寫入功能都有的固有特性，不是本次設計缺陷。
- **假綠燈**：見 A-2（analytics CHANGELOG 聲稱的測試覆蓋與實際不符）。另外確認
  `test_dev_case_assignment_2026_11_03.py` 的 12 題與 `test_dev_case_assignee_visibility_hichan10_2026_11_03.py`
  的 3 題本身斷言紮實（直接查 `dev_cases`／`notifications` 表，不是只看 API 回應文字；403/400/404 分支、
  資料不變、通知對象精確比對都有覆蓋），沒有發現 mock 掉待驗證行的情況。

## 4. 回覆欄（被稽核者填；PM 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | PM 確認 |
|---|---|---|---|
| A-1 | 已修：`_check_dev_case_stale` 的 SELECT 補 `assigned_to`，收件人併入被指派人（與 sales_persons／planners 同等，不只是備援）；補題 `test_assignee_gets_the_daily_stale_reminder_notification` 直接呼叫排程後查 `notifications` 表 | 85d04c3e | ✅ |
| A-2 | 已修：`modules/crm/tests/test_dev_case_assignee_visibility_hichan10_2026_11_03.py` 補 `test_assignee_sees_their_stale_case_in_dashboard_ops_alerts`／`test_assignee_sees_their_dev_log_in_dashboard_activity_feed` 兩題，真打 `/api/dashboard/ops-alerts`／`/api/dashboard/activity-feed`；analytics CHANGELOG 1.0.45 的測試引用同步改為這兩題 | 85d04c3e | ✅ |
| B-1 | 建議，不修：現狀唯一呼叫端（`dev-crm.html`）兩欄一起送，不觸發問題；之後有新呼叫端再處理 | | |
| B-2 | 建議，不修：非安全問題，純顯示疑惑；列入之後統一處理自由文字欄位時的待辦 | | |
| C-1 | TODO-VERIFY(pm)：待機器空檔跑 `pytest backend/tests/platform/test_module_migrations.py -k crm` | | |
| C-2 | 觀察，不修：與既有欄位現狀一致，非本次新增缺陷 | | |
| C-3 | 觀察，不修：非安全缺口，純管理顯示問題 | | |

### 關閉紀錄（標準格式，PLAYBOOK §E-6）

- ✅ A-1 關閉（85d04c3e）——`_check_dev_case_stale` 補 `assigned_to`，被指派人同等收停滯提醒，題已覆蓋
- ✅ A-2 關閉（85d04c3e）——補兩個 dashboard 端點的真實 HTTP 呼叫測試，CHANGELOG 測試引用同步修正
