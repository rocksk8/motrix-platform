# CRM「批示」設計：可重用的留言／批註元件（Annotation Component）＋業務開發首個登錄

> 狀態：設計 **r2**（2026-10-13，1d；靜態文件，未動程式）。r1＝`wip/t56-crm-directive-r1`（`1d2765e65`）；本版依 0d NOT-PASS（3 項必改＋6 項應改）與 PM 裁示修訂（分支 `wip/t56-crm-directive-r2`）。對齊：`FIELD-LAYOUT-FRAMEWORK-T56.md` r7（脊柱；§17 功能進件＝登錄）。
> 需求（使用者 #2，經 1c）：業務開發每筆開發記錄有「批示」按鈕；主管／審閱人留批示；自動顯示是誰寫的與時間；記錄人可收 Email；記錄上有明顯標記表示有批示待閱，讀過才消失。全部框架化（選項＋預設＋影響橫幅），做成**可重用元件**。
> **r2 變更摘要**：M1 誰能批示／可見性（OwnerRule 實況；新增獨立 `security` 選項『主管可看到下屬的開發記錄／批示』預設關）；M2 `visible_fn` ＝ `_require_dev` 規則＋`row_access`，與既有 helper 共用；M3 收件人在寫入與讀取時都要通過 `visible_fn`，不可見者丟棄並記 `skipped_no_access`；S1 核心 migration 併脊柱列車（一次 105 分鐘閘門）＋ `db.py` 三份清單＋core-only RC 測試；S2 信件逐收件人一次、狀態取自 `out` 字典，**合併視窗與重試移出 10 日範圍**；S3 `include_case` 三選一預設不帶；S4 目標刪除改為管理者選項（預設擋下）；S5 API 上限；S6 平面鍵、隱藏『指定角色』至 F3；pd 誠實重估（§12）。

## 0. 結論（先看）

1. **不是 CRM 專用功能，而是 L1 元件 `annotations`（顯示名「批示」）**；業務開發是第一個目標類型登錄者。別的單據日後只登錄目標類型＋設定預設。
2. **重用既有零件**：站內通知 `helpers/audit._notify`＋`notifications`；信件 `mail_types.register()`＋`email_notify.send_registered()`；審計 `audit_log`；可見性 `row_access`（`dev_case` OwnerRule）；設定走設定中心 `register_group`／`SettingDef`；橫幅依脊柱 §16.6。
3. **新增的只有『批示』本體與『每位收件人是否讀過』**。不用 `item_reads`：它表達『別人在我讀過後動過這筆』，不能表達『這則批示給誰、他讀了沒有』。
4. **可見性不擴大**（PM）：批示不改 `row_access` 的 `dev_case` 登錄；唯一例外是**管理者主動開啟、獨立、`security` 級、預設關**的『主管可看到下屬的開發記錄／批示』（§2.4，限讀取，在 `visible_fn` 內處理）。
5. **工量（誠實重估）**：全量 **10.0 pd**；10 日範圍 **8.75 pd**（延後：合併視窗、每日上限、重試、信件範本編輯、已讀回條）。核心 migration 與 helpers 併入脊柱 P0／P1／F3／S1 同一列車，**閘門 105 分鐘只算一次**（§8）。
6. **需要使用者回答的問題：無不可逆者**（§13）。

## 1. 盤點：已存在什麼（已核對程式）

| 需求 | 現有零件 | 結論 |
|---|---|---|
| 業務開發紀錄 | `dev_cases`（`created_by`、`sales_persons`／`planners` JSON）、`dev_logs`（`log_by` 記錄人、`created_by` 實際建立者、`needs_approval`）；`modules/crm/api.py`；`frontend/pages/dev-crm.html` | **記錄人＝`dev_logs.log_by`**；`dev_logs` 現為**硬刪除**（`api.py` `delete_dev_log`，`DELETE FROM dev_logs`）→ 需在同交易掛鉤（§5.4） |
| **模組規則** | `_require_dev`（api.py:94）：`role ∈ {superadmin, admin}` **或** `"dev_crm" ∈ user.modules`，否則 403『無業務開發模組權限』 | 這是第一道門；批示的 `visible_fn` 必須**逐字等於**這條規則＋`row_access` |
| **列級規則** | `DEV_CASE_ACCESS = row_access.OwnerRule(creator_col="created_by", id_list_cols=("sales_persons","planners"), lenient_json=True)`（api.py:110）→ admin+ 直通，否則須為建立者／業務／企劃；`scope="read"` 另有 `read_bypass_modules`（如 `case_access` 的 cashier） | **成員 ≠ 具 dev_crm**：案件成員可能沒有 `dev_crm` 模組權限（要有測試，§10） |
| **既有共用 helper** | `_DevLogPathAccess.readable`（api.py:119–132）：模組規則＋`row_access.visible("dev_case", …)`（`uploads.path_access`，IP-104） | 抽成單一函式 `dev_case_readable(conn, user, case_row)`，`_DevLogPathAccess` 與批示 `visible_fn` **共用**，不複製規則 |
| 留言／動態 | `case_updates`（無收件人／已讀／Email） | 不併入 |
| 未讀 | `routers/item_reads.py`（`LIST_KINDS=("dev_case","case","daily_task")`） | 重用慣例（伺服器時間、只往後推、只回看得到的筆）；批示待閱另表 |
| 站內通知 | `notifications` 表、`audit._notify()`（`link` 白名單、`_mask_money`、保留 90 天） | 直接用 |
| 信件 | `mail_types.register`；`send_registered(...) -> bool`；`SEND_*` 結果（`out["outcome"]`）；`MAIL_OFF`；`notify_matrix` | 直接用；**注意回傳值語意**（§4.2）；範本目前寫死（脊柱 E-c） |
| 設定 | `helpers/settings_registry.py`：`register_group(group, label, fields, risk=…, cross_check=…)`、`SettingDef(key, type∈int/float/bool/str, default, question, label, help, impact, risk, risk_text, choices=[(值,中文標籤,影響說明)], recommended, requires_pending, loosen, impact_fn …)`；風險類 `none／ops／money／legal／security`，`money／legal／security` 或 `requires_pending` 須 `risk_text`；放寬走確認期＋雙人核准 | **鍵為平面欄位名**（無點號）；登錄當下缺中文必填即失敗 |
| 備份／重置 | `db.py`：觸發器名單（`saved_triggers`，:299–:321，含 `config_change_events_no_update／no_delete`）、demo 重置清單（:427）、備份清單 | 新表三處都要補（§5.5） |

## 2. 元件設計

### 2.1 目標類型登錄

```
register_annotation_target(
  target_type = "dev_log",
  label       = "開發記錄",                          # 進 DocType／標籤來源
  owner_fn    = lambda conn, key: [帳號…],           # 候選收件人：log_by（＋依設定的建立者／案件成員）
  visible_fn  = lambda conn, user, key, scope="owner": bool,
                                                     # = dev_case_readable()：_require_dev 規則 + row_access；scope="read" 才套主管例外
  link_fn     = lambda key: "dev-crm.html?case=…&log=…",
  on_deleted  = <管理者設定 directive.on_deleted>,   # §5.4
  owner       = "crm")
```
- 業務開發登錄 `dev_log`（本期）與 `dev_case`（元件支援，預設關）。
- 登錄表在啟動載入；缺 `owner_fn／visible_fn／link_fn` ⇒ 登錄失敗。**零個已登錄目標**時元件必須完全正常（§8 core-only RC）。

### 2.2 資料模型（L1 `core` 新表；migration 單向、可重跑）

```
annotations(
  id, target_type, target_key, body TEXT,
  author_id, author_name, author_title,        -- 寫入當下快照
  created_at,                                  -- 伺服器時間
  edited_at, deleted_at, deleted_by,           -- 軟刪除（撤回）
  target_gone INTEGER DEFAULT 0,               -- 目標已刪（§5.4）
  kind TEXT DEFAULT 'directive')

annotation_recipients(
  annotation_id, username,
  state TEXT,                                  -- active／skipped_no_access（M3）
  notified_at, read_at,                        -- read_at NULL 且 state=active ＝待閱
  mail_status TEXT,                            -- none／queued／sent／unknown／failed／skipped_no_email／off／skipped_no_access
  mail_at,
  mail_attempts INTEGER DEFAULT 0, next_try_at TEXT,   -- 保留欄位；10 日範圍不使用（重試移出，§4.2）
  PRIMARY KEY (annotation_id, username))

annotation_events(                             -- 只增不改：觸發器 annotation_events_no_update／_no_delete
  id, annotation_id, event, actor, at, detail_json)
```
- 待閱＝`state='active' AND read_at IS NULL AND annotations.deleted_at IS NULL AND target_gone=0`。
- 顯示：「王大明（業務經理）· 2026-10-12 14:03」，已編輯加『（已編輯）』，撤回顯示『此批示已由作者撤回』。

### 2.3 待閱狀態
- **產生**：新增批示同交易寫 `annotations`＋`annotation_recipients`。收件人＝`owner_fn` 候選，**逐一以 `visible_fn(recipient)` 過濾（M3）**：通過者 `state='active'`；不通過者寫一列 `state='skipped_no_access'`、`mail_status='skipped_no_access'`、**不寫通知、不寄信、不計待閱**；作者本人不產生待閱。若記錄人被丟棄，批示人畫面顯示白話提示：『這筆記錄的記錄人沒有權限閱讀此案件，因此沒有通知對方。』
- **讀取時再檢查（M3）**：`GET 列表`、`/pending`、`/read` 對呼叫者都再跑 `visible_fn`；權限事後被收回者看不到批示、不計待閱。信件在背景寄送前也再檢查一次。
- **清除（`directive.clear_on`）**：預設『開啟批示面板』：前端面板可見後呼叫 `POST /api/annotations/{id}/read`，**只更新呼叫者自己的收件列**（沒有則 404；B 無法清除 A 的待閱）；`GET` 絕不標已讀；列表預取／機器人不清除。可改為『按「我已閱讀」』。
- 再批示：同一筆有新批示 ⇒ 重新待閱，舊已讀不重亮。
- 『已讀回條』10 日範圍不提供（選項顯示『尚未提供』）。

### 2.4 誰可以批示、誰看得到（M1／M2）

**實況**：`DEV_CASE_ACCESS` 是 OwnerRule（admin+ 或 建立者／sales_persons／planners），外加 `_require_dev` 的 `dev_crm` 模組門。r1 的『部門主管以上』預設與此不符，作廢。

| 層 | 規則 |
|---|---|
| 第一道（永遠） | `visible_fn(user, 這筆)`＝`dev_case_readable()`：`admin+ 或 dev_crm ∈ modules`，**且** `row_access.visible("dev_case", user, case_row)`。沒有它就不能讀、不能批示、不能被通知（含案件成員但沒有 `dev_crm` 者） |
| 能批示（`directive.who`，F3 能力 `directive.write` 的預設集合） | **預設＝『管理員以上＋該案成員』**（＝看得到這筆記錄的人，值 `admin_and_case_members`）；選項『僅管理員以上』（`admin_only`，收緊）；『指定角色』**F3 就緒前不提供**（以『已登錄但不可選』呈現，§6）。**設定值是選項代碼，不存角色字串**（角色名單歸 F3） |
| **主管讀取例外**（`directive.supervisor_read`，獨立選項，**預設關**，`security`＋紅色橫幅） | 開啟後，記錄人（`log_by`）所屬部門的主管（`departments.manager_user_id`）可**唯讀**這筆開發記錄與其批示。實作只在 CRM 的 `visible_fn(scope="read")` 與批示面板入口（比照 `case_access` 的 `read_bypass` 概念）；**不改 `row_access` 的 `dev_case` 登錄**，所以主管不會因此出現在案件清單、全站搜尋、儀表板、未讀鍵（沒有靜默擴大）。主管能否『寫』批示仍由 `directive.who` 決定（預設不能） |
| 看得到批示（`directive.visible_to`） | 預設＝批示作者＋收件人＋有批示權者＋管理員以上；選項『看得到該記錄的所有人』（放寬類、紅色橫幅）。永遠先過第一道 |

## 3. 畫面（白話，無代碼）

1. **按鈕**：每筆開發記錄右上『批示』（名稱走 relabel，可改）。僅有批示權且通過第一道者看得到。
2. **批示面板**：由新到舊，每則『寫的人（職稱）· 日期時間』、內文、『已編輯』、撤回（作者／超管）；輸入框；送出前顯示『將通知：王小明（記錄人），Email：開／關』；收件人被丟棄時顯示 M3 的提示句。
3. **待閱標記**：記錄人的列表／記錄卡顯示紅色徽章『有批示 N』，讀過後消失；徽章是清單欄位（目錄項 `directive_badge`），管理者可在版面編輯器顯示／隱藏／移位（`directive.list_badge`，預設顯示）。
4. **鈴鐺**：『【批示】王大明對一筆開發記錄留了批示』，點擊直達並定位。**通知標題不含案件名與內文**（案件名依 `email_include_case` 同規則，§4.2）。
5. 錯誤訊息白話：『你沒有批示這筆記錄的權限』『批示不可空白』『內容超過 2000 字』『你送出得太快，請稍後再試』。

## 4. 通知設計

### 4.1 站內（永遠寫，不可關）
`audit._notify(type='annotation_received', …, link=…)`；僅對 `state='active'` 收件人。`_mask_money` 對非財務收件人遮蔽金額字樣（R3）。站內通知 90 天清除，待閱狀態**不依賴它**。

### 4.2 Email（管理者選項；預設開）
- 信件類型登錄：`mail_types.register("annotation_received", "收到批示", "business", "none", "記錄人", "您的開發記錄有批示，請閱讀並依批示處理。", "請登入系統，開啟該記錄閱讀批示。", owner="crm")`。個人可退訂、超管可覆寫收件、`MAIL_OFF` 照舊。
- **主旨**固定：`【MOTRIX 系統通知】業務－收到新的批示`；內文**預設通用句**『您有一則新批示』＋批示人＋時間＋按鈕『前往系統查看』。
- **S3 `directive.email_include_case`（三選一，預設『不帶』）**：不帶（none，預設）／帶案件編號（case_no）／帶案件名稱（case_name；放寬類，琥珀橫幅：客戶與案件名稱將出現在信箱）。客戶名稱永不帶。批示內文預設不寄（`email_include_text` 預設關，`security`＋紅橫幅）。
- **S2 寄送實作（修正 r1）**：`send_registered(...)` 回傳 `bool`，**`SEND_UNKNOWN`／`SEND_PERMANENT_FAIL` 也回 True**（保留記號語意），所以**狀態不可用回傳值判斷**。做法：**每位收件人各呼叫一次**（`usernames=[該人]`），傳入 `out={}`，由 `out["outcome"]` 決定 `mail_status`：`SEND_SENT`→`sent`；`SEND_UNKNOWN`→`unknown`；`SEND_PERMANENT_FAIL`／`SEND_TRANSIENT_FAIL`→`failed`；`"no_recipient"`→`skipped_no_email`；`SEND_SKIPPED`→`skipped`。寄送在**交易提交後**的背景執行緒（沿用 `spawn_bg_thread`），不阻塞請求；寄前再過一次 `visible_fn(recipient)`。無 Email ⇒ 僅站內，批示人畫面顯示『對方未設定 Email，已以站內通知送達』。
- **10 日範圍移出（S2）**：合併視窗（同收件人同記錄 N 分鐘合併）、每日上限彙整信、暫時失敗重試。表內保留 `mail_attempts`／`next_try_at` 欄位供後續（含排程掃描 `failed` 且 `next_try_at<=now`，最多 3 次、24 小時）；10 日內 `failed` 只留狀態、批示人面板顯示『Email 未寄出，已以站內通知送達』，並於系統中心健康卡計數。
- 範本文字鍵（標題／開頭／按鈕）走設定；完整範本登錄為脊柱 E-c。

### 4.3 提醒（選項，預設關，10 日範圍『尚未提供』）
`directive.remind_unread_days`：逾 N 天未讀提醒記錄人（沿用 `notify_approval_reminder` 排程模式）。

## 5. 權限、個資、稽核

1. **內文屬管理資訊／個資**：不進全站搜尋索引、預設不進匯出、不進行事曆、不進 `notify_module_activity`；`audit_log.detail` 只存批示 id 與長度。
2. **編輯／撤回**：作者在 `edit_window_minutes`（預設 15）內可改（留 `edit` 事件含舊內文）；作者可撤回（軟刪除）；超管可撤回任何批示；**無硬刪除端點**。
3. **撤回後／目標被刪後的內文，誰能看**（S4 隱私定義）：預設**僅超級管理員**（稽核檢視）；作者與收件人在撤回／目標被刪之後**只見『此批示已撤回』或『此記錄已刪除』標記，不見內文**。不提供選項放寬（避免被刪資料外流）。
4. **目標被刪（S4，`directive.on_deleted`，管理者選項）**：
   - **擋下（block，預設）**：有批示的開發記錄，**只有管理員以上**可以刪除；其他人得到 409『這筆記錄有主管批示，只有管理員可以刪除』。
   - **保留（retain）**：照既有刪除權限刪；批示與事件保留。
   - 兩者在刪除時**同一交易內**呼叫 `annotations.on_target_deleted(conn, target_type, key)`（掛在 `delete_dev_log` 的 `DELETE FROM dev_logs` 之前／同一 `commit`、以及案件刪除的連動路徑）：寫 `target_gone=1`、把仍待閱的收件列設 `read_at=now`（避免永久紅點）、寫 `annotation_events`。測試：刪除失敗回滾時批示不變；刪除成功後批示標記一致（§10）。
5. **備份／重置／封存（S1）**：`db.py` 三份清單都要補——觸發器名單（`saved_triggers`，:299–:321 區，加 `annotation_events_no_update／no_delete`，demo 重置時拿掉再建回，比照 `config_change_events`）、demo 重置清單（:427，加 `annotations`、`annotation_recipients`、`annotation_events`）、備份清單；封存規則同步。往返測試涵蓋。
6. **稽核**：`audit_log` 動作 `annotation.create／edit／delete／mail_failed`；『讀取』只記在 `annotation_events`。設定變更走 `config_changes` 帳本。
7. **帳號異動**：批示人停用／改名 ⇒ 顯示快照；記錄人停用 ⇒ 收件列保留，不寄信、不計待閱。

## 6. 框架化：選項＋預設＋影響橫幅（S6：平面鍵）

設定群組 **`directive`**（顯示名『批示』；`register_group("directive", …)`）。**欄位鍵為平面 snake_case，無點號**（文件中寫作 `directive.who` 只是『群組.鍵』的稱呼；實際 `SettingDef.key` 為 `who`）。選項型＝`type="str"` 搭 `choices=[(值, 中文標籤, 影響說明)]`。

| 欄位鍵 | 型別／選項（預設加粗） | 風險 | 橫幅／備註 |
|---|---|---|---|
| `dev_log_enabled` | bool：**開**／關 | ops | 關閉＝按鈕與徽章隱藏，既有批示保留 |
| `dev_case_enabled` | bool：**關**／開 | ops | — |
| `who` | str：**`admin_and_case_members`**／`admin_only`；（`specified_roles` 見下） | **security** | 放寬⇒琥珀；`risk_text`：誰能對業務記錄留下管理評語 |
| `supervisor_read` | bool：**關**／開 | **security** | 開⇒**紅**：『部門主管可唯讀其下屬的開發記錄與批示』；`impact_scope`：documents＝開發記錄、roles＝部門主管、amounts＝無、reversible＝是（關閉即停）、effective＝待確認期；`impact_fn` 顯示目前主管人數與受影響記錄數 |
| `visible_to` | str：**`author_recipients_admin`**／`all_record_viewers` | **security** | 後者⇒**紅**：同案其他成員也看得到評語 |
| `clear_on` | str：**`open_panel`**／`button` | ops | — |
| `email_enabled` | bool：**開**／關 | ops | 關⇒琥珀：記錄人可能漏看 |
| `email_recipients` | str：**`owner_only`**／`plus_creator`／`plus_case_members` | ops | 加人⇒琥珀；加入者同樣須通過 `visible_fn` |
| `email_include_case` | str：**`none`**／`case_no`／`case_name` | **money**（個資級，沿用最近類）| `case_name`⇒琥珀 |
| `email_include_text` | bool：**關**／開 | **security** | 開⇒**紅**：寄出無法回收 |
| `email_subject_text`／`email_intro_text`／`email_button_text` | str：白話預設句 | ops | 占位符以 chips；不可放金額／個資變數 |
| `edit_window_minutes` | int：**15**（0＝不可編輯） | ops | — |
| `max_length` | int：**2000**（上限 2000，伺服器硬限；只能調小） | ops | — |
| `write_rate_per_minute` | int：**10** | ops | 超過⇒429 白話訊息 |
| `list_badge` | bool：**顯示**／隱藏 | ops | — |
| `allow_self` | bool：**開**／關 | ops | — |
| `on_deleted` | str：**`block`**／`retain` | **security** | `retain`⇒琥珀（任何有刪除權者可刪掉有批示的記錄）|
| `read_receipt`、`remind_unread_days` | — | — | **10 日範圍不登錄**（登錄時才加） |

- **『指定角色』選項**（`who=specified_roles`）：F3 就緒前以『已登錄但不可選』呈現——`choices` 內含該項並標『尚未提供』，`cross_check` 拒絕選取（比照脊柱既有的『尚未提供』選項處理）；F3 落地後解除，**角色名單由 F3 維護，設定只存代碼**。
- 高影響者（security／money 級與紅橫幅）：`risk_text` 必填（登錄當下檢查）；結構化 `impact_scope` 待脊柱 E-e（`SettingDef.impact_scope`）落地；**E-e 就緒前以 `impact`＋`risk_text`＋`choices` 影響說明承載，並同步在登錄清單標註 `impact_scope` 待補**。放寬走確認期＋雙人核准（`loosen`／`requires_pending`）。
- **寫死的只有**：先過 `visible_fn`、作者與時間由伺服器寫、軟刪除與事件只增不改、主旨不含內容、API 上限（§9）。

## 7. 與脊柱（欄位版面框架 r7）的對齊

| 脊柱零件 | 批示登錄內容 |
|---|---|
| 目錄 | 表面 `module:crm.dev_log`（page）、`module:crm.dev_log_list`（list）；項目 `directive_badge`（badge）、`directive_count`、`directive_panel`；`isMoney=假`；可見性判定＝**CRM `visible_fn`（含 `dev_crm` 模組門）且收件人存取檢查** |
| 版面 | 徽章／面板位置走 P9 layout 點；預設＝現況 |
| 政策設定 | 群組 `directive`（§6）；群組總數守門 +1 |
| 標籤 | 按鈕、面板、狀態字走 `label_map`／relabel |
| 能力 | F3：`directive.write`、`directive.view_all`（命名由 1d 供給） |
| 通知／信件 | `mail_types.register("annotation_received", …)`；範本文字鍵（E-c） |
| 稽核／帳本 | `annotation.*`；`config_changes` |
| 宣告檔 | `module.json` 的 `features[]` 區塊（不需改載入器；加入 `test_core_loader` 的宣告驗證器） |

## 8. 引擎改動與列車（S1：一次閘門）

| # | 改動 | 時程 |
|---|---|---|
| E1 | `core/annotations`：三表 migration、服務層、目標登錄、API（含 §9 上限）、觸發器 | **併入脊柱 P0／P1／F3／S1 同一列車**（`core/**`、`helpers/**` 底層變更集中一班）；**全量閘門約 105 分鐘，與其他底層項合計只算一次** |
| E1b | `db.py` 三份清單（觸發器名單、demo 重置、備份）＋封存 | 同列車 |
| E1c | **core-only RC 測試**：零個已登錄目標 ⇒ `/pending` 回空、列表對未知目標 404、不 import `modules.crm`、三表存在且空；per-module 安裝包（無 crm）仍可載入 | 同列車 |
| E2 | 通知範本登錄（最小版） | 里程碑 2 |
| E3 | 設定中心 S1 編輯畫面（相依） | 設定中心里程碑 |
| E4 | F3 能力 | 隨 F3；之前內建預設集合並標記待遷移 |
| E5 | 目錄 `badge` 型項目 | 脊柱 P0 後；之前固定徽章（預設相同） |
| E6 | 脊柱 E-e `impact_scope` | 見脊柱文；之前以 `impact`／`risk_text` 承載 |

CRM 側（`modules/crm`）的登錄與前端隨 CRM 模組列車，不佔底層閘門。

## 9. API 草案與上限（S5）

- `GET /api/annotations?target_type=&key=`：先 `visible_fn`，再依 `visible_to` 過濾；**絕不改狀態**。
- `POST /api/annotations`：`{target_type, key, body}`。**伺服器端**：`body` 去頭尾空白、拒空白、**≤ `max_length`（硬上限 2000）**、去控制字元；作者／時間／收件人皆伺服器決定；**每位作者寫入頻率限制**（`write_rate_per_minute`，預設 10 次／分，超過 429＋白話訊息）；回 201。
- `PATCH /api/annotations/{id}`（作者、視窗內）；`DELETE …/{id}`（軟撤回，作者或超管）。
- `POST /api/annotations/{id}/read`：**僅更新呼叫者自己的收件列**（沒有 ⇒ 404）；呼叫者須通過 `visible_fn`。
- `POST /api/annotations/pending`：`keys` **最多 200 筆**（超過 400）；**逐鍵存取策略**：同一請求內先一次查出涉及的 `dev_cases`，對每個案件只算一次 `visible_fn`（快取），不可見的鍵靜默略過（看不到的那筆有沒有批示本身就是資訊）；只回呼叫者為 `state='active'` 收件人的待閱。
- 新增路由登錄整合點並重產 route golden。

## 10. 測試清單（紅 → 綠）

1. **M2** 案件成員但**沒有 `dev_crm`** ⇒ 讀、批示、被通知皆 403／略過；admin 無 `dev_crm` 也可；有 `dev_crm` 但非成員（非 admin）⇒ 不可（`row_access`）。`_DevLogPathAccess` 與批示 `visible_fn` 走同一函式（斷言同一物件，改規則兩邊同動）。
2. **M1** 預設 `who`＝管理員以上＋案件成員；`admin_only` 收緊生效；`specified_roles` 不可選（`cross_check` 拒絕）；`supervisor_read` 關：部門主管（非成員）403；開：僅唯讀（可讀記錄與批示、不能寫、不出現在案件清單／搜尋／儀表板／`/api/reads/unread`），`row_access` 的 `dev_case` 登錄不變（快照斷言）。
3. **M3** `log_by` 不在案件成員內 ⇒ 不寫通知、不寄信、不計待閱；`annotation_recipients` 有一列 `skipped_no_access`；批示人看到白話提示。權限事後收回 ⇒ 列表／`/pending`／`/read` 皆不可見。
4. 作者／時間由伺服器寫、忽略用戶端值；改名後快照不變。
5. 待閱：產生→亮→`read` 後熄；`GET` 不清除；**B 的 `/read` 不能清 A**（404／不變）；再批示重亮。
6. **S2** 信件：每位收件人一次呼叫、狀態取自 `out["outcome"]`（`SEND_UNKNOWN`、`SEND_PERMANENT_FAIL` 回傳雖為 True 但狀態分別是 `unknown`／`failed`）；關閉時不寄但站內仍寫；個人退訂、超管覆寫生效；無 Email ⇒ `skipped_no_email` 與提示；開發環境不真寄；寄前再檢查可見性。
7. **S3** `email_include_case`：none（預設）內文為『您有一則新批示』、不含案件名／編號；`case_no`／`case_name` 各自出現；主旨永不含內容；`include_text` 才有內文。
8. 編輯視窗內可改、超過不可；撤回後內文僅超管可見；無硬刪除端點；`annotation_events` 觸發器擋 UPDATE／DELETE。
9. **S4** `on_deleted=block`：非管理員刪除有批示的記錄 ⇒ 409 白話；管理員可刪，批示標 `target_gone`、待閱列清除、事件寫入；`retain`：照既有權限；刪除交易失敗回滾批示不變；撤回／目標已刪後作者與收件人看不到內文，超管看得到。
10. **S5** `/pending` 超過 200 鍵 ⇒ 400；逐鍵策略（同案件只算一次，以呼叫計數斷言）；`body` 超過 2000／空白 ⇒ 400；超過頻率 ⇒ 429；`GET` 前後 `read_at` 不變。
11. **S1** `db.py` 三份清單含三表與兩個觸發器；demo 重置後三表為空且觸發器仍在；備份往返；**core-only RC**：零目標 ⇒ `/pending` 空、不 import `modules.crm`、無 crm 的安裝包可啟動。
12. 設定：預設值、白話守門（`question／label／help／impact`、`risk_text`）、群組總數；紅橫幅未勾選不可送出；變更同交易寫帳本＋稽核。
13. 登錄表驅動守門：每個目標類型的 `owner_fn／visible_fn／link_fn` 可呼叫、連結合格、設定預設齊全。
14. e2e（真路由）：按鈕只對有批示權者出現；面板含『王大明（職稱）· 時間』；記錄人徽章亮→開啟後熄；手機寬度不橫向捲動；深色模式。
15. route golden、`FORM_VERSION`／頁面版號依既有守門。

## 11. 風險

- **R1** S1 編輯畫面未建 ⇒ 管理者暫不能改選項；預設皆為安全值。
- **R2** 信件外洩：預設不寄案件名與內文；`email_include_case=case_name`、`include_text` 皆有橫幅。
- **R3** 批示內文含金額：站內通知遮蔽；面板內顯示依 `visible_to`（不在目錄 `isMoney` 管轄）。建議提示『請勿在批示寫報價金額』（可關）。
- **R4** 硬刪除：以 `on_deleted` 與同交易掛鉤處理；若日後改軟刪除，改為跟隨。
- **R5** 熱點檔 `dev-crm.html`／`crm/api.py`：PM 排單一順序（與 D1 清單接線不可並行改同檔）。
- **R6** `supervisor_read` 的 `read` 路徑需在 `crm/api.py` 現有 GET 端點加分支；漏掉任一端點會形成『批示可讀、記錄不可讀』的不一致 ⇒ 測試 2 逐端點覆蓋，並以『只經批示入口可讀』為準（不擴大 `row_access`）。
- **R7** 記錄人口徑（`log_by` vs `created_by`）：預設 `log_by`，建立者為選項；改 `owner_fn` 單點。
- **R8** 10 日範圍移出重試後，暫時失敗的信件不會自動補寄；以面板提示＋健康卡計數補償，並保留欄位供後續。

## 12. 工量與排序（r2 誠實重估）

| 項 | 內容 | 全量 pd | 10 日 pd |
|---|---|---|---|
| A1 | `core/annotations`：三表、migration、觸發器、服務層、目標登錄、API 與上限（S5）、route golden、`db.py` 三份清單（S1）、core-only RC 測試 | 1.75 | 1.75 |
| A2 | CRM 登錄：共用 `dev_case_readable()`（含改 `_DevLogPathAccess`）、`owner_fn`、收件人過濾（M3）、`on_deleted` 同交易掛鉤（S4）、主管讀取例外（M1）、`directive.who` 預設集合 | 1.25 | 1.25 |
| A3 | 待閱／已讀／再批示、批次待閱（逐鍵策略）、讀取時再檢查；已讀回條 | 0.85 | 0.75 |
| A4 | 站內通知＋`mail_types` 登記＋逐收件人寄送與狀態（S2）；全量另含合併視窗、每日上限、重試排程 | 1.50 | 0.75 |
| A5 | 前端：按鈕、面板、徽章、白話文字、深色／手機 | 1.50 | 1.50 |
| A6 | 設定群組 `directive`（平面鍵、選項型、不可選項）、橫幅、帳本、白話守門 | 0.75 | 0.50 |
| A7 | 稽核、封存、目標刪除隱私處置、停用帳號 | 0.65 | 0.65 |
| A8 | 測試（§10 全部）、登錄表驅動守門、e2e | 1.75 | 1.60 |
| **合計** | | **10.00** | **8.75** |

算術：全量 1.75＋1.25＋0.85＋1.50＋1.50＋0.75＋0.65＋1.75＝10.00；10 日 1.75＋1.25＋0.75＋0.75＋1.50＋0.50＋0.65＋1.60＝8.75。較 r1（8.0／7.4）增加主因：共用 helper 與收件人過濾（A2 +0.5）、刪除掛鉤與隱私（A7 +0.15、A2）、`db.py` 三清單與 core-only RC（A1 +0.25）、API 上限與更多測試（A8 +0.5）；A4 因移出合併／重試而 10 日內減少。**底層閘門 105 分鐘不計入 pd，與脊柱同列車只算一次。**

排序：後端（A1～A4、A7）與脊柱 P0／P1 並行、互不依賴解析器；A5 徽章在目錄落地前用固定徽章，預設相同。里程碑 1 帶 A1（底層列車）與 CRM 後端；前端與設定在里程碑 2。

## 13. 需要使用者回答的問題與待 PM 確認

- 使用者：無不可逆者。隱私預設（信件不帶案件名與內文、無硬刪除、撤回後內文僅超管可見）由 PM 先定，可事後改設定（除『撤回後內文僅超管』不提供放寬）。
- 待 PM／0d 確認（內部）：O1 `supervisor_read` 只開『經批示入口可讀』或需進案件清單（本版採前者，最小擴大）；O2 主管讀取是否也應能『寫』批示（本版預設否，仍由 `who` 決定）；O3 『主管』沿用 `departments.manager_user_id`（一個部門一位）是否足夠。
