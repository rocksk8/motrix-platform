# 開發記錄「批示」設計（2026-11-04）

> 緣起：使用者看到開發記錄（dc-logs）畫面後提出：「右下角的編輯，管理員增加批示，可以增加留言，該留言會通知該填寫的成員，也可以指定誰回覆」「在權限內也要增加可以對應批示這個功能由誰可以做」。設計由 hichan-8（執筆）與 hichan-6（逐條對碼核對）討論收斂，主持（hichan-74）裁示 5 項開放問題後定稿。
> 實作：hichan-8。複核：hichan-9（對抗審查，不同人）。完成並通過複核後才排上線，走正常列車流程。

## 0. 關鍵前提：dev_logs 不是 append-only

`PUT /dev-logs/{id}` 原地覆寫、`DELETE` 硬刪（連附件）；`POST` 一筆會連動客戶拜訪同步、行事曆、`notify_module_activity`（全文寄全體 admin）、`dev_cases.updated_at`（重置停滯 30 天計時）、接洽統計、報價單動態、dashboard、封存匯出。批示若做成 `dev_logs` 的一列，每個讀者都要過濾，漏一處就把批示誤算成客戶拜訪——跟 T74 進度回報拒絕併入 dc-logs 同一個理由。**批示另開新表，只在畫面位置與 `log_id` 掛靠，不動 `dev_logs` 本身。**

## 1. 資料與掛載

新表（crm 模組 migration 0004，冪等 `CREATE IF NOT EXISTS`；L2 遷移，失敗讓整個 crm 模組下線，須用 T74 後含真實資料的庫實測）：
- `dev_log_directive(id, log_id, case_id, author_id, content, parent_id, created_at, owner_unit_id)`：批示與回覆同表，`parent_id` 只一層（回覆指向批示，不可回覆回覆）。
- `dev_log_directive_target(id, directive_id, user_id, must_reply, replied_at, owner_unit_id)`：批示的通知／待回覆對象，`UNIQUE(directive_id, user_id)`。

批示掛在某一筆開發記錄（`log_id`，不加 FK、新增時自己驗存在且 `log.case_id` 等於路徑 `case_id`，否則 400）。**不做案件層級批示**（v1 只做掛紀錄層級，對應使用者原話「右下角的編輯」描述的範圍；真要案件層級的批示再另開票——`log_id` 目前 NOT NULL，之後要加也只是欄位改可空）。

畫面：`dc-log-card` 在「編輯」「刪除」旁加第三顆「批示」鈕，**不塞進「編輯」視窗**（會混進被編輯者的內容、作者難分辨）。

## 2. 通知對象與回覆

- 多人（上限約 10），預設預選該紀錄的 `log_by`、`must_reply=1`；管理員可加人、可取消「要回覆」勾選（**保留「只知會」must_reply 0/1**——使用者原話「也可以指定誰回覆」本身就隱含不是每個人都要回，不砍這個欄位）。
- 不可含自己、去重；每人須在職、具 `dev_crm` 模組權限、`row_access.visible` 看得到該案，否則 400 並列出不合格的名字。
- 回覆：被列為對象的人＋批示作者可回（作者不必再驗能力），同表子列 `parent_id`。對象回覆 ⇒ 該列 `replied_at` 記首次回覆時間、通知作者；作者回覆 ⇒ 通知所有對象。畫面顯示「待回覆：某某」（`must_reply=1` 且 `replied_at` 空）。不另開一筆開發記錄當回覆。

## 3. 可見度（使用者裁示）

**限「作者＋對象＋管理員」可見**（不是案件原本看得到的人都能看）——批示可能是批評性內容，先限縮在有關的人，避免同事間的觀感問題。實作：
- `GET` 批示／回覆列表依請求者是否為作者、對象之一、或 admin 過濾；不符合的人連「這筆紀錄有批示」這件事本身都看不到（紀錄卡不顯示批示鈕以外的任何痕跡、不顯示「待回覆」標記）。
- 有「批示」權限（見 §4）但不是作者／對象的管理員仍算可見（管理員本來就該看得到全部批示以利追蹤）。

## 4. 權限

`module.json` 新增能力 `crm.dev_log_directive.comment`（沿用既有動作詞彙 `comment`，不另造新動作）：`label`「對開發記錄下批示」、`legacy={"role":["admin"]}`（superadmin 自動過）⇒ **上線當天等價「只有管理員」**，之後在權限矩陣可勾給別人；`risk: mid`、`delegable: true`、`recommended: ["admin"]`，`desc`／`impact`／`question` 白話必填，`impact` 要寫明「對象仍須有業務開發模組權限才能被指定」。

`POST` 批示 = `_require_dev` AND `perm.require(...)` AND `row_access.visible`（看得到案件才能批示）。回覆不需要這個能力（被列為對象或身為作者即可回）。能力總數 11→12（T73 步驟檔 #14、`final_verify`、權限矩陣計數基準都要同步改）。

## 5. 編輯／刪除、updated_at

- 批示與回覆**一律只增不改不刪**（寫錯＝再發一筆），同進度回報的規則。
- 既有開發記錄的「編輯」「刪除」行為不變，**唯一例外**：`delete_dev_log` 若該紀錄已有批示 ⇒ 409（避免硬刪附件後批示懸空）。接受「建立者不能刪已被批示的紀錄」這個限制；不做「保留原紀錄摘要快照」那個更複雜的替代方案。
- 已知限制（不處理，記錄但不擋）：被批示的紀錄仍可被 `PUT` 編輯改內容，批示可能對不上新內容——本票不存 `log_excerpt` 快照。
- 擋刪 409 與新增批示要同一交易判斷（`BEGIN IMMEDIATE` 或插入後複查），避免「檢查無批示→刪除」與「新增批示」競態交錯。

## 6. 通知

- 站內通知必發（`dev_log_directive`／`dev_log_directive_reply`，可帶前約 40 字）。
- 信件只寄 `must_reply=1` 的人，新 `mail_type dev_log_directive`（照 `dev_case_assigned` 的方式登 `notification_prefs.EVENT_GROUPS`＋`mail_types.register`），本文只放案名／批示人／請登入查看，**不放全文**。
- **不呼叫 `notify_module_activity`**（那支函式帶 `detail` 全文寄全體 admin，與「批示限縮可見度、信只寄要回覆的人」矛盾；既有進度回報端點仍帶 `detail=content` 是既有問題，不在本票範圍，可另提）。
- 稽核走 `_audit`（標籤只取前約 40 字）。
- `dev_cases.updated_at`：**批示與回覆都不動**。理由：`_check_dev_case_stale` 用 `updated_at` 判「洽談中超過 30 天沒新開發記錄」並組 guard key；管理員催一句或成員回「收到」不是跟進客戶，重置會把停滯警報洗掉而案件其實沒人聯絡客戶。進度回報會重置它，是因為發言者是現任負責人、語意不同。串的「最後活動」改用 `MAX(created_at)` 推導，不依賴 `updated_at`。
- 逾期催辦：v1 不做（之後可重用進度逾期的 guard key 作法；`replied_at` 已經讓查詢變得容易）。

## 7. 實作別漏（hichan-6 對碼修正版，比照 `dev_case_progress` 實際登記處）

1. `notify_module_activity` 的 N1 風險（全文外洩給全體 admin）：批示／回覆**不得**使用它帶 `detail`。
2. N2 兩層閘：權限矩陣可能把能力勾給沒有 `dev_crm` 模組的人，勾了仍 403，畫面會誤導 ⇒ `impact` 白話寫明、補測試（有能力無模組 ⇒ 403）。
3. N3：`GET` 批示對 `is_deleted=1` 的案件回 404（同 `add/list_dev_case_progress`；`list_dev_logs` 本身沒擋，批示照 progress 的規則）。
4. N4：`GET /dev-cases/{id}/directives` 回整案全部＋`canDirect` 旗標（前端現在沒有任何地方問能力，要自己帶），前端依 `log_id` 分組。
5. **最容易忘**：`modules/crm/__init__.py` 要 `importlib` 載入 `0004_…` 並把 `(4, _m0004.up)` 加進 `migrations=[…]`（現為 1～3）。
6. 兩張新表都帶 `owner_unit_id INTEGER NOT NULL DEFAULT 1`（過 `test_unit_scope_guard_t6`）、`idx(case_id, id)`。
7. 註冊清單：`tests/platform/test_org_units_u0a.py` 的 `MODULE_KEYED_TABLES`（加兩張新表）；`tests/platform/test_u0a_sinks.py` 登記 0004 檔名；`archive.py` 封存表清單（新增「業務開發批示」「批示對象」）；`db.py` demo 表清單；`crm/module.json` 的 `tables`／`data.tables`（T1）；`route_table_golden.json`／`route_inventory.json`／寫入 golden（`cases_zz_rest.py`）；`unscoped_reads_baseline.json`／`test_unscoped_reads_ratchet.py` 的 `MAX_ENTRIES`（依實際數字更新，T73 栽過一次）；`docs/platform` 的 `dep_graph`／`modules`／`test_map`（產生檔，跑 regen）；crm CHANGELOG／版號、core 版號。
8. **不用動**：`core/migrations.py`（那是舊表加 `owner_unit_id` 欄的清單，progress 沒登）、`helpers/storage_slots.py`（只有 `dev_logs`，progress 也沒登）——實作時跑 `storage_slots`／`recyclebin_baseline_t53` 相關測試確認不要求新表登錄。
9. 能力總數 11→12：T73 步驟檔 #14、`final_verify`、權限矩陣計數基準要同步改。
10. 已知限制（記錄，不處理）：對象之後失去案件可見性（案件換人等），回覆走 `row_access` 即擋、通知連結失效、`target` 列留著；要再催就新發一筆批示給有權限的人。

## 8. 測試清單（要明列）

未登入 401、非能力者 403、有能力無模組 403、對象不在職／無模組／看不到案件各 400（列名字）、對象含自己 400、`log_id` 不屬該案 400、非對象非作者回覆 403、作者回覆通知全體對象、信件收件人只含 `must_reply=1`（真實 HTTP 呼叫釘住，T73A-M1 教訓，不能只人工檢查）、§3 可見度過濾（非作者／對象／admin 看不到批示存在）、擋刪 409 與其競態、`dev_cases.updated_at` 不變、`dev_logs` 既有端點行為位元組不變（差異探針）、migration 0004 冪等與真實資料實測。

## 9. 範圍外（本票不做）

- 案件層級批示（不掛紀錄）——見 §1。
- 批示逾期催辦——見 §6。
- 被批示紀錄的內容快照（`log_excerpt`）——見 §5 已知限制。
- 既有進度回報端點 `notify_module_activity(detail=content)` 的全文外洩問題——不在本票範圍，可另提。
