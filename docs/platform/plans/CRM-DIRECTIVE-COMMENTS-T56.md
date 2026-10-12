# CRM「批示」設計：可重用的留言／批註元件（Annotation Component）＋業務開發首個登錄

> 狀態：設計 r1（2026-10-12，1d；靜態文件，未動程式）。對齊：`FIELD-LAYOUT-FRAMEWORK-T56.md` r6（脊柱：目錄、版面、政策設定、標籤；§16.6 高影響橫幅）。
> 使用者需求 #2（經 1c 轉達）：業務開發每筆開發記錄有「批示」按鈕；主管／審閱人在該筆留下批示；自動顯示誰寫的與時間；記錄人可收 Email；記錄上有明顯標記表示有批示待閱，記錄人讀過才消失。全部框架化（選項＋預設＋影響橫幅），並做成**可重用元件**，日後別的單據也用同一個。

## 0. 結論（先看）

1. **不是 CRM 專用功能，而是一個 L1 元件 `annotations`（顯示名「批示」）**；業務開發只是第一個「目標類型」登錄者。別的模組（案件動態、報價單、請款單…）日後只需登錄一個目標類型＋設定預設，不再各寫一套留言。
2. **重用既有零件，不重造**：站內通知用 `helpers/audit._notify`＋`notifications` 表；信件用 `helpers/mail_types.register()`＋`email_notify.send_registered()`（含超管收件覆寫、個人退訂、`MAIL_OFF` 規則）；審計用 `audit_log`；權限用 `row_access.visible("dev_case", …)` 先擋；設定用設定中心 setting_group；橫幅依脊柱 §16.6。
3. **唯一新增的是「批示」本體與『每位收件人是否讀過』**。為何不用現有 `item_reads`：它的語意是『別人在我讀過之後動過這筆』（以整筆為單位、含所有動態），不能表達『這一則批示是給誰、他讀了沒有』；也不能讓記錄人收到的標記只因批示而亮。兩者並存：開啟記錄仍照舊清 `item_reads`，批示待閱另由 `annotation_recipients` 管。
4. **工量**：全量 **8.0 pd**；10 日範圍 **7.4 pd**（延後：信件範本可編輯、每日上限／彙整信、已讀回條）。與欄位版面框架 P0／P1 **並行登錄**，不先寫死再遷移（§12）。
5. **需要使用者回答的問題：無不可逆者**（§13）；兩個隱私預設由 PM 先定（信件不帶批示內文、不提供硬刪除），可事後改設定。

## 1. 盤點：已存在什麼（已核對程式）

| 需求 | 現有零件 | 結論 |
|---|---|---|
| 業務開發紀錄 | `dev_cases`（案件：`created_by`、`sales_persons` JSON、`planners` JSON）、`dev_logs`（開發記錄：`log_by` 記錄人、`created_by` 實際建立者、`needs_approval`＝代他人記錄時為 1、`files_json`）；API 在 `modules/crm/api.py`（`/dev-cases/{id}/logs`、`PUT/DELETE /dev-logs/{id}`、`PATCH /dev-logs/{id}/approve`）；頁面 `frontend/pages/dev-crm.html` | **記錄人＝`dev_logs.log_by`**；`dev_logs` 目前為**硬刪除**（`DELETE FROM dev_logs`，api.py:1016）→ 批示需要掛接刪除事件（§5.4） |
| 留言／動態 | `case_updates`（案件動態：`quote_no`、`author`＝帳號字串、`content`、`type`）、簽核備註 | 只有案件側，**沒有收件人、已讀、Email**；不併入，批示元件日後可成為案件動態的一種表示（不在本期） |
| 未讀標記 | `routers/item_reads.py`：`item_reads(username, kind, item_key, read_at)`，`LIST_KINDS=("dev_case","case","daily_task")`；伺服器時間、只往後推、依 `row_access` 過濾 | 重用其**慣例**（伺服器時間、只往後推、只回看得到的筆）；批示待閱另表 |
| 站內通知 | `notifications` 表（`username,type,ref_id,ref_label,message,is_read,created_at,link`）；`helpers/audit._notify()`（含 `link` 白名單、金額遮蔽 `_mask_money`、保留 90 天）；`routers/notifications` 鈴鐺 | 直接用；`link` 只准同站頁面＋查詢字串（`dev-crm.html?case=…&log=…` 合格） |
| 信件 | `helpers/mail_types.py`：`register(key,name,category,group,event,impact,action,owner)`，模組登記自動併入個人通知偏好；`email_notify.send_registered(event_key,title=,rows=,usernames=,to_group=,reason=,link=,note=,wait=)`；主旨前綴 `【MOTRIX 系統通知】`；超管可逐類覆寫收件（`mail_recipient_overrides`）；`notify_matrix.py` 管信件×行事曆對照；`tests/platform/test_mail_registry.py` 守門（`event_key` 必須字面字串且已登記） | 直接用；範本目前是**程式內固定**（`_build_html` 的 rows），**沒有範本登錄／管理者可編輯**→ 這是脊柱要補的（§7） |
| 設定 | 設定中心（M2）：registry＋`config_changes` 帳本＋放寬流程；**S1 編輯畫面尚未建**（先前稽核的阻擋項） | 本元件的設定登錄走它；S1 未建前只能以預設運作（§11 風險 R1） |
| 權限 | `row_access`（`dev_case` 規則：建立者／業務／企劃人員可見）；F3 能力通道（設計中）；角色名單歸 F3（脊柱 §15-4） | 『誰可批示』以**能力**表達（`directive.write`），設定只切預設集合，不存角色字串 |
| 備份／封存 | `archive.py`、`db.py` 的備份資料表清單；回收桶（T53 adapter 模式） | 新表必須併入（§5.5） |

## 2. 元件設計

### 2.1 目標類型登錄（元件如何被重用）

```
register_annotation_target(
  target_type   = "dev_log",                 # snake_case，全系統唯一
  label         = "開發記錄",                 # 白話名稱；進 DocType 登錄／標籤來源，管理者可改
  owner_fn      = lambda conn, key: [帳號…],  # 記錄人（收件人預設）；dev_log→log_by（+選填 created_by）
  visible_fn    = lambda conn, user, key: bool, # 內含 row_access 檢查；批示『看得到記錄』是前提
  link_fn       = lambda key: "dev-crm.html?case=…&log=…",   # 站內連結（通知／信件共用）
  on_deleted    = "retain" | "block",        # 目標被刪時的處置（§5.4）
  default_settings = {…},                    # §6 的鍵與預設
  owner = "crm")                             # 登錄者（模組鍵，同 mail_types 慣例）
```
- 業務開發登錄兩個目標：`dev_log`（**本期主要**，使用者要求「每筆開發記錄」）與 `dev_case`（案件層級；元件已支援，預設**關**，管理者可在設定開啟，不另開發）。
- 登錄表在啟動時載入，守門測依登錄表逐一檢查（缺 `owner_fn`／`visible_fn`／`link_fn` ⇒ 登錄失敗）。

### 2.2 資料模型（L1 `core` 新表；migration 單向、可重跑）

```
annotations(
  id, target_type, target_key,                 -- 目標（dev_log 的 id 字串）
  body TEXT,                                   -- 批示內文（長度上限設定，預設 2000 字）
  author_id, author_name, author_title,        -- 寫入當下的快照：顯示名、職稱／角色白話（之後改名不回改）
  created_at,                                  -- 伺服器時間（TW，沿用 crm 的 _TW_NOW 慣例）
  edited_at, deleted_at, deleted_by,           -- 軟刪除；內文保留供稽核
  kind TEXT DEFAULT 'directive')               -- 預留：directive／note（日後一般留言）

annotation_recipients(
  annotation_id, username,                     -- 寫入時解析出的收件人（記錄人＋選填額外）
  notified_at,                                 -- 站內通知寫入時間
  read_at,                                     -- NULL＝待閱
  mail_status, mail_at,                        -- none／sent／failed_transient／failed_permanent／skipped_no_email／off
  PRIMARY KEY (annotation_id, username))

annotation_events(                             -- 只增不改（觸發器擋 UPDATE／DELETE，沿用 config_change_events 作法）
  id, annotation_id, event, actor, at, detail_json)   -- create／edit／delete／read／mail_sent／mail_failed
```
- 為何不用 JSON 欄位塞在 `dev_logs`：要查『我有幾則待閱』『某人寫過哪些』、要索引、要保留編輯軌跡；掛在別人的表會綁死 CRM。
- 作者名稱存快照＋帳號 id：畫面顯示快照（誰寫的一定看得到，且不因改名而漂移）；帳號停用後仍顯示。
- **顯示格式**（白話）：「王大明（業務經理）· 2026-10-12 14:03」，已編輯者加「（已編輯）」，已撤回者顯示「此批示已由作者撤回」。

### 2.3 待閱狀態如何產生與清除
- **產生**：新增批示時，在同一交易寫 `annotations`＋`annotation_recipients`（收件人＝`owner_fn` 結果＋設定的額外收件人，去除作者本人）；**作者批示自己的記錄不產生待閱**。
- **清除（設定 `clear_on`）**：預設 `open`＝記錄人開啟該筆的批示面板（前端顯示後呼叫 `POST /api/annotations/{id}/read`，**由伺服器寫 `read_at` 與 `read` 事件**；列表預取、機器人、`GET` 本身不清除）；可改 `button`＝須按「我已閱讀」。只清**自己**的收件列；不影響他人。
- **再批示**：同一筆記錄有新批示 ⇒ 該記錄對記錄人再次成為待閱；已讀的舊批示不重亮。
- 『已讀回條』（設定，預設開）：批示人可看到『○○已於 10-13 09:10 讀取』；未讀則顯示『尚未讀取』。
- 待閱數端點：`POST /api/annotations/pending`（沿用 `/api/reads/unread` 形狀：給一批 `target_type`＋`keys`，回仍待閱的 keys 與數量；**只回呼叫者看得到的筆**，看不到的那筆有沒有批示本身就是資訊）。

### 2.4 誰可以批示
- 能力 `directive.write`（F3 能力；`dev_log` 目標的預設集合＝**部門主管以上＋管理員＋超級管理員**，沿用現有『部門主管』判斷 `_department_manager_emails` 的資料來源）。設定項只切『預設集合』：`主管以上（預設）／僅管理員以上／指定角色（由 F3 維護名單）`。**風險等級 `security`**（帶權限效果，走放寬流程）。
- 前提永遠是 `visible_fn` 為真（看不到記錄就不能批示）。
- 不可批示自己的記錄的規則：**允許**但不產生待閱（可當筆記）；設定 `allow_self` 預設開。

## 3. 畫面（白話，無代碼）

1. **按鈕**：每筆開發記錄右上「批示」（按鈕名稱可由管理者改，走 relabel；預設『批示』）。僅有 `directive.write` 者看得到按鈕。
2. **批示面板**（按鈕展開的側欄或記錄下方區塊）：由新到舊列出批示，每則顯示『寫的人（職稱）· 日期時間』、內文、『已編輯』標記、（批示人／超管）撤回；輸入框＋『送出批示』；送出前顯示『將通知：王小明（記錄人），Email：開／關』。
3. **待閱標記**：記錄人的列表／記錄卡顯示**明顯紅色徽章『有批示 N』**；點開並讀過後消失。徽章在清單是一個欄位（目錄項 `directive_badge`，type `badge`），管理者可在版面編輯器中顯示／隱藏／移位（設定 `list_badge`，預設顯示）。
4. **主管視角**：在案件的開發記錄清單可篩選『我寫過批示且對方尚未讀』（輔助欄位，預設關）。
5. **選單與鈴鐺**：站內通知『【批示】王大明對「○○案」的開發記錄留了批示』，點擊直達該記錄並定位到批示；沿用現有未讀紅點。
6. 全部用語走標籤來源；錯誤訊息白話（『你沒有批示這筆記錄的權限』『批示不可空白』『內容超過 2000 字』）。

## 4. 通知設計

### 4.1 站內（永遠寫，不可關）
- 新批示一律寫 `notifications`（`type='annotation_received'`，`ref_id`＝批示 id，`link`＝直達連結）。`_notify` 會對非財務角色遮蔽金額字樣（內文含金額時行為已知，列為 R3）。
- **站內通知是真相來源**；待閱狀態不依賴它（通知 90 天會被清，待閱要留到讀為止）。

### 4.2 Email（管理者選項；預設**開**）
- 信件類型登錄：`mail_types.register("annotation_received", "收到批示", "business", "none", "記錄人", "您的開發記錄有主管批示，請閱讀並依批示處理。", "請登入系統，開啟該記錄閱讀批示。", owner="crm")`——自動併入個人通知偏好（個人可退訂）、超管可在『信件與通知收件設定』覆寫；`MAIL_OFF` 規則照現有。
- **主旨不含任何內容**：`【MOTRIX 系統通知】業務－收到新的批示`（不帶案件名、客戶名、批示內文）。內文列：批示人、時間、記錄日期、案件名稱（設定 `email_include_case`，預設開——客戶名稱屬個資不帶）、按鈕『前往系統查看』；**批示內文預設不寄**（設定 `email_include_text` 預設關，開啟為高影響：信件一旦寄出無法回收）。
- **收件人**：預設＝記錄人（`owner_fn`）；選項『一併通知建立者（代記錄時）』『一併通知案件業務／企劃』（預設關）；選項『副本給批示人自己』（預設關）；額外收件角色（由 F3 角色，預設無）。
- **頻率限制**：同一收件人、同一記錄、`mail_merge_minutes`（預設 10）內多則批示合併為一封（『有 N 則新批示』）；每收件人每日上限 `mail_daily_cap`（預設 20）超過改寄一封彙整、其餘僅站內。
- **失敗處理**：用 `send_registered(…, wait=True)` 取結果寫 `annotation_recipients.mail_status`：`SENT`＝sent；暫時失敗 ⇒ 排程下一輪重試（最多 3 次、24 小時內）；永久失敗／無 Email ⇒ `failed_permanent`／`skipped_no_email`，**站內通知不受影響**；批示人畫面顯示『對方未設定 Email，已以站內通知送達』。遵守現有 `email_send_policy`／開發機寄信規則（開發環境主旨前綴、不真寄）。
- **範本可編輯**：見 §7——本期（10 日範圍）只開放『標題文字、開頭說明、按鈕文字』三個文字鍵走設定（白名單占位符以 chips 表示，不用大括號），完整範本登錄（欄位列增減）為脊柱後續項。

### 4.3 站內鈴鐺以外的提醒（選項，預設關）
- 『逾 N 天未讀提醒記錄人』（`remind_unread_days`，預設關）：沿用既有 `notify_approval_reminder` 的排程模式；對批示人另寄『你的批示 N 天尚未被讀取』（預設關）。本期不做，只登錄鍵。

## 5. 權限、個資、稽核

1. **誰看得到批示**（設定 `visible_to`）：預設＝批示作者＋記錄人（收件人）＋有 `directive.write` 者＋管理員以上；選項『能看到該記錄的所有人』（放寬類、**紅色橫幅**：同案其他業務、企劃也看得到主管評語）。永遠先通過 `visible_fn`（`row_access`）。
2. **內文屬個資／管理資訊**：不進全站搜尋索引、不進匯出（Excel／PDF）預設、不進行事曆、不進 `notify_module_activity` 的摘要；`audit_log.detail` 只存批示 id 與長度，**不存內文**（內文僅在 `annotations`／`annotation_events`）。
3. **編輯／撤回政策**（設定）：作者可在 `edit_window_minutes`（預設 15）內修改（留 `edit` 事件含舊內文，面板標『已編輯』）；作者可**撤回**（軟刪除，面板顯示撤回標記；內文保留於稽核，僅超級管理員可查看）；超管可撤回任何批示。**不提供硬刪除**（資料保存規則；日後依保存年限由受控清理處理）。
4. **目標被刪時**（`on_deleted`）：`dev_logs` 現為硬刪除。`dev_log` 登錄為 `retain`：刪除記錄時批示與事件保留（`target_gone=1` 標記，僅超管可查），其收件列自動視為已讀（避免永久紅點）；`dev_case` 同。回收桶（T53 模式）若日後涵蓋開發記錄，批示隨之還原。
5. **備份／封存**：三張新表併入備份清單（`db.py` 備份表清單、`archive.py` 規則）；匯入／還原守門測涵蓋。
6. **稽核事件**（`audit_log`）：`annotation.create／edit／delete`、`annotation.mail_failed`；『讀取』只記在 `annotation_events`，不灌 `audit_log`（量大）。設定變更走 `config_changes` 帳本。
7. **帳號異動**：批示人帳號停用／改名 ⇒ 顯示快照；記錄人帳號停用 ⇒ 收件列保留但不寄信、不計入待閱統計。

## 6. 框架化：全部是選項＋預設＋影響橫幅

設定群組代號 **`directive`**（顯示名『批示』；遵脊柱 §15-2：snake_case、一個功能一個群組；鍵 `directive.<目標>.<鍵>` 或全域 `directive.<鍵>`）。

| 鍵 | 選項（預設加粗） | 風險 | 橫幅 |
|---|---|---|---|
| `directive.dev_log.enabled` | **開**／關 | normal | 關閉＝按鈕與徽章隱藏，既有批示保留 |
| `directive.dev_case.enabled` | **關**／開 | normal | — |
| `directive.dev_log.who` | **主管以上**／僅管理員以上／指定角色（F3） | **security** | 放寬（更多人可批示）⇒ 琥珀：誰能對業務記錄留下管理評語 |
| `directive.visible_to` | **作者＋記錄人＋批示者＋管理員**／能看到記錄的所有人 | security | 後者⇒ **紅**：同案其他業務也看得到評語；影響所有既有批示 |
| `directive.clear_on` | **開啟面板**／按『我已閱讀』 | normal | — |
| `directive.read_receipt` | **開**／關 | normal | 10 日範圍內預設值固定『開』，選項顯示『尚未提供』 |
| `directive.email.enabled` | **開**／關 | normal | 關閉⇒ 僅站內；琥珀：記錄人可能不看系統而漏看批示 |
| `directive.email.recipients` | **僅記錄人**／＋建立者／＋案件業務企劃 | normal | 加人⇒ 琥珀：更多人收到業務管理信件 |
| `directive.email.include_text` | **否**／是 | **security** | 是⇒ **紅**：批示內文將寄到信箱，寄出後無法回收 |
| `directive.email.include_case` | **是**／否 | normal | — |
| `directive.email.merge_minutes`／`daily_cap` | **10 分／20 封** | normal | — |
| `directive.email.subject_text`、`intro_text`、`button_text` | 預設白話句（可改） | normal | 占位符以 chips；不可放金額／個資變數 |
| `directive.edit_window_minutes` | **15**（0＝不可編輯） | normal | — |
| `directive.max_length` | **2000** | normal | — |
| `directive.list_badge` | **顯示**／隱藏 | normal | — |
| `directive.button_label` | **批示**（可改） | normal | 走 relabel，不另存 |
| `directive.allow_self` | **開**／關 | normal | — |
| `directive.remind_unread_days` | **關** | normal | 尚未提供 |

- 高影響者（上表 security 與紅色者）依 §16.6 登錄 `impact_scope={documents:['開發記錄'], roles:[…], amounts:'無金額影響', reversible:…, effective:…}`；`impact_calc` 回傳即時數量（例：『目前有 37 則批示將對更多人可見』）。放寬走原因＋帳本＋第二位最高管理者＋確認期（沿用設定中心規則）。
- **不寫死的只有**：伺服器端權限檢查（先過 `visible_fn`）、作者與時間的伺服器端寫入、軟刪除與事件只增不改、主旨不含內容的底線（`include_text` 只影響內文，主旨永不含內容）。

## 7. 與脊柱（欄位版面框架 r6）的對齊——這個功能登錄了什麼

| 脊柱零件 | 批示登錄的內容 |
|---|---|
| **目錄（Catalog）** | 表面 `module:crm.dev_log`（page，批示面板區塊）與 `module:crm.dev_log_list`（list，≤30 字元，點分隔鍵）；項目 `directive_badge`（badge，`isMoney=false`，可見性判定 `directive_visible`＝有 `directive.write` 或為收件人）、`directive_count`（number）、`directive_panel`（block）。清單欄位『批示』由此出現在版面編輯器，不手寫在 `dev-crm.html` |
| **版面** | 徽章／面板位置由 P9 `layout` 點決定；預設＝現況（徽章在記錄卡右上） |
| **政策設定** | 群組 `directive`（§6），登錄 `impact_scope`；設定群組總數守門 +1 |
| **標籤** | 按鈕名稱、面板標題、狀態字（『尚未讀取』『已讀取』『已撤回』『已編輯』）走 `label_map`／relabel；目標類型白名稱走 DocType 登錄 |
| **權限／能力** | F3 能力 `directive.write`、`directive.view_all`（命名由 1d 提供給 F3） |
| **通知／信件** | `mail_types.register("annotation_received", …)`；範本鍵三個（標題、開頭、按鈕）→ 脊柱新增『通知範本登錄』（§8 工程項 E2） |
| **稽核／帳本** | `audit_log` 動作 `annotation.*`；設定變更 `config_changes` |
| **測試** | 登錄表驅動：每個登錄的目標類型自動跑一組守門測（§10） |

## 8. 引擎仍需的改動（誠實版）與時程

| # | 改動 | 為什麼 | 何時 | 工量 |
|---|---|---|---|---|
| E1 | `core/annotations`：三表 migration、服務層、`register_annotation_target` 登錄、API（建立／列出／撤回／編輯／讀取／待閱） | 元件本體 | 里程碑 1（與脊柱 P0／P1 並行；不依賴解析器） | 含於 §12 A1～A3 |
| E2 | **通知範本登錄**（`register_template(key, default_title, default_intro, default_button, placeholders)`；管理者可改三個文字鍵，占位符白名單） | 目前信件內文寫死在 `email_notify.py`；批示、專案毛利、完工單通知都會要 | 本期只做『三個文字鍵走設定』（A4）；完整範本（欄位列增減）併入脊柱後續 | 本期含於 A4 |
| E3 | 設定中心 **S1 編輯畫面** | 目前未建；沒有它管理者改不了任何選項 | 屬設定中心里程碑，**非本元件工量**；未建時以預設運作 | 0（相依） |
| E4 | F3 能力命名與預設集合 | `directive.write` | 與 F3 同步；本元件先以內建預設集合（部門主管／管理員）判斷，標記待遷移 | 0.1（含於 A2） |
| E5 | 目錄 `badge` 型項目與清單欄位渲染 | 徽章為清單欄位 | 脊柱 P0（目錄）後；之前用固定徽章，預設相同 | 含於 A5 |

## 9. API 草案（皆需登入；沿用 `Authorization` 標頭慣例）

- `GET /api/annotations?target_type=&key=`：該筆的批示列表（先 `visible_fn`，再依 `visible_to` 過濾）。
- `POST /api/annotations`：`{target_type, key, body}`；伺服器決定作者／時間／收件人；回 201。
- `PATCH /api/annotations/{id}`：作者在視窗內編輯。`DELETE …/{id}`：軟撤回（作者或超管）。
- `POST /api/annotations/{id}/read`：記錄人標已讀（伺服器寫時間）。
- `POST /api/annotations/pending`：批次待閱數（給清單徽章）。
- 所有新增路由登錄整合點並重產 route golden（沿用脊柱 §15-3）；`GET` 不改狀態。

## 10. 測試清單（紅 → 綠）

1. 批示人：有能力者可寫、無能力者 403；看不到記錄者 403（`row_access` 正反對照）。
2. 作者／時間由伺服器寫，用戶端送的 `author`／`created_at` 一律忽略；改名後舊批示仍顯示快照。
3. 記錄人收到站內通知（連結合格）；作者批示自己的記錄不產生待閱。
4. 待閱：產生→徽章亮→`read` 後熄；`GET` 列表不清除；他人讀不清我的；再批示重亮。
5. 信件：關閉時不寄但站內仍寫；開啟時主旨不含案件／客戶／內文；`include_text` 開才有內文；個人退訂生效；超管覆寫生效；無 Email ⇒ `skipped_no_email` 且畫面白話提示；暫時失敗重試上限；開發環境不真寄。
6. 頻率：10 分鐘內多則合併一封；超每日上限改彙整。
7. 編輯視窗內可改、超過不可；撤回後內文僅超管可見；無硬刪除端點；`annotation_events` 無法 UPDATE／DELETE（觸發器）。
8. 目標刪除：`dev_log` 被刪後批示保留、收件列視為已讀、僅超管可查；`dev_case` 同。
9. 備份／還原往返含三表；`audit_log.detail` 不含內文（掃描斷言）。
10. 金額內文：非財務角色的站內通知遮蔽金額（既有行為，正反對照）。
11. 設定：高影響選項缺 `impact_scope` ⇒ 登錄失敗；紅色橫幅未勾選不可送出；變更同交易寫帳本＋稽核；白話守門（`test_settings_ui_plain_language`）涵蓋橫幅與錯誤訊息。
12. **登錄表驅動守門**：列舉所有已登錄目標類型，逐一斷言 `owner_fn／visible_fn／link_fn` 可呼叫、`link_fn` 結果通過 `_LINK_RE`、`mail_types` 已登記、設定預設齊全。新目標類型不需改測試。
13. UI（e2e，真路由）：按鈕只對有能力者出現；送出後面板出現含『王大明（職稱）· 時間』；記錄人登入徽章亮、開啟後熄；手機寬度不橫向捲動；深色模式。
14. 路由 golden、設定群組總數、`FORM_VERSION`／頁面版號（若動 `dev-crm.html`）依既有守門更新。

## 11. 風險

- **R1** S1 編輯畫面未建 ⇒ 上線時管理者不能改選項（只有預設）。緩解：預設皆為安全值；S1 落地後即可用，無資料遷移。
- **R2** 信件外洩：預設不寄內文、主旨不含內容；`include_text` 為紅色橫幅。
- **R3** 批示內文含金額：站內通知會遮蔽；面板內顯示依 `visible_to`（不屬金額欄位，**不在目錄 `isMoney` 管轄內**）。建議使用提示『請勿在批示寫報價金額』（白話提示，預設開，可關）；若使用者要求結構性防止，需另案（內容掃描有誤判成本）。
- **R4** `dev_logs` 硬刪除與孤兒批示：以 `on_deleted=retain` 處理；若日後改軟刪除，改為跟隨。
- **R5** 熱點檔 `dev-crm.html`／`crm/api.py`：需 PM 排單一順序（與欄位版面框架 P2 清單接線不可並行改同檔）。
- **R6** 郵件量：以合併＋每日上限控制；排程重試上限避免風暴。
- **R7** 記錄人定義（`log_by` vs `created_by`）：代他人記錄時 `needs_approval=1`；預設收件人＝`log_by`，建立者為選項。若業務對『誰是記錄人』另有口徑，改 `owner_fn` 即可（單點）。

## 12. 工量與排序

| 項 | 內容 | pd | 10 日範圍 |
|---|---|---|---|
| A1 | `core/annotations`：三表、migration、服務層、目標登錄、API、路由 golden | 1.50 | 1.50 |
| A2 | CRM 登錄（`dev_log`、`dev_case`）：`owner_fn／visible_fn／link_fn／on_deleted`、`directive.write` 內建預設集合 | 0.75 | 0.75 |
| A3 | 待閱／已讀／再批示、批次待閱端點、已讀回條 | 0.75 | 0.65（回條延後） |
| A4 | 站內通知＋`mail_types` 登記＋寄送（合併、每日上限、失敗重試、無 Email 處理）、三個文字鍵 | 1.00 | 0.75（每日上限彙整信延後） |
| A5 | 前端：按鈕、面板、徽章（清單與記錄卡）、白話文字、深色／手機 | 1.50 | 1.50 |
| A6 | 設定群組 `directive`、橫幅 `impact_scope`、帳本、白話守門 | 0.75 | 0.50（無編輯畫面，僅登錄與預設；S1 後接上） |
| A7 | 稽核、備份／封存、目標刪除處置、停用帳號處理 | 0.50 | 0.50 |
| A8 | 測試（§10）含登錄表驅動守門、e2e | 1.25 | 1.25 |
| **合計** | | **8.00** | **7.40** |

算術：全量 1.50＋0.75＋0.75＋1.00＋1.50＋0.75＋0.50＋1.25＝8.00；10 日範圍 1.50＋0.75＋0.65＋0.75＋1.50＋0.50＋0.50＋1.25＝7.40。

**排序（並行登錄，不先寫死再遷移）**：A1～A4、A7 屬後端，與欄位版面框架 P0／P1 同期、互不依賴（元件不吃解析器）；A5 的徽章欄位在 P0 目錄落地前用固定徽章，**預設值與日後目錄項相同**，之後機械式換成目錄項。A5 與 `dev-crm.html` 為熱點，與 P2 清單接線排前後。里程碑：元件後端＋CRM 登錄可放在里程碑 1 或 2（每個里程碑完整驗證，預設行為不變：未啟用前不顯示按鈕）。

## 13. 需要使用者回答的問題

無不可逆者。PM 先定的兩個隱私預設（可事後在設定中心改，改動走橫幅）：**信件不帶批示內文**、**不提供硬刪除**。記錄人口徑（`log_by`）若與業務現場不同，告知即可改單點。
