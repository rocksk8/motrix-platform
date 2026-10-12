# CRM「批示」設計：可重用的留言／批註元件（Annotation Component）＋業務開發首個登錄

> 狀態：設計 **r2**（2026-10-13，1d；靜態文件，未動程式）。r1＝`wip/t56-crm-directive-r1`（`1d2765e65`）；本版依 0d NOT-PASS（3 項必改＋6 項應改）與 PM 裁示修訂（分支 `wip/t56-crm-directive-r2`）。對齊：`FIELD-LAYOUT-FRAMEWORK-T56.md` r7（脊柱；§17 功能進件＝登錄）。
> 需求（使用者 #2，經 1c）：業務開發每筆開發記錄有「批示」按鈕；主管／審閱人留批示；自動顯示是誰寫的與時間；記錄人可收 Email；記錄上有明顯標記表示有批示待閱，讀過才消失。全部框架化（選項＋預設＋影響橫幅），做成**可重用元件**。
> **r3 變更摘要**（分支 `wip/t56-crm-directive-r3`；依 0d 剩餘 NOT-PASS 與 PM 裁示）：M1 選項欄位**一律整數代碼**（`choices` 目前只用於顯示，`str` 會接受任何值）＋值域規則（E7）＋讀取端失敗關閉；M2 新增 `who` 選項 3『管理員、案件成員與記錄人部門主管』（`security`、紅橫幅、須 `supervisor_read` 開，`cross_check` 把關），回答 O2；M3 `visible_to` 預設改為『作者＋收件人＋管理員以上』（非收件人的案件成員看不到他人批示）；S1 刪除掛鉤精確到 `crm/api.py` 軟刪除（逐筆開發記錄）與硬刪除、定義還原、共用 helper 對軟刪除案件對非管理員一律不可讀；S2 `email_include_case` 風險類改 `security`；S3 O3 只認記錄人所屬部門主管（部門主管階層為『已登錄但不可選』）；S4 `directive_badge` 由伺服器依 `state='active'` 收件列計算；pd 重估 10.6／9.35。
> **r2 變更摘要**：M1 誰能批示／可見性（OwnerRule 實況；新增獨立 `security` 選項『主管可看到下屬的開發記錄／批示』預設關）；M2 `visible_fn` ＝ `_require_dev` 規則＋`row_access`，與既有 helper 共用；M3 收件人在寫入與讀取時都要通過 `visible_fn`，不可見者丟棄並記 `skipped_no_access`；S1 核心 migration 併脊柱列車（一次 105 分鐘閘門）＋ `db.py` 三份清單＋core-only RC 測試；S2 信件逐收件人一次、狀態取自 `out` 字典，**合併視窗與重試移出 10 日範圍**；S3 `include_case` 三選一預設不帶；S4 目標刪除改為管理者選項（預設擋下）；S5 API 上限；S6 平面鍵、隱藏『指定角色』至 F3；pd 誠實重估（§12）。

## 0. 結論（先看）

1. **不是 CRM 專用功能，而是 L1 元件 `annotations`（顯示名「批示」）**；業務開發是第一個目標類型登錄者。別的單據日後只登錄目標類型＋設定預設。
2. **重用既有零件**：站內通知 `helpers/audit._notify`＋`notifications`；信件 `mail_types.register()`＋`email_notify.send_registered()`；審計 `audit_log`；可見性 `row_access`（`dev_case` OwnerRule）；設定走設定中心 `register_group`／`SettingDef`；橫幅依脊柱 §16.6。
3. **新增的只有『批示』本體與『每位收件人是否讀過』**。不用 `item_reads`：它表達『別人在我讀過後動過這筆』，不能表達『這則批示給誰、他讀了沒有』。
4. **可見性不擴大**（PM）：批示不改 `row_access` 的 `dev_case` 登錄；**預設只有作者、收件人與管理員以上看得到批示**（同案但非收件人的成員看不到別人的批示）；唯一放寬是管理者主動開啟的 `security` 級選項——『主管可看到下屬的開發記錄／批示』（`supervisor_read`）與『看得到該記錄的所有人』（`visible_to=2`），皆預設關、紅橫幅。
5. **工量（誠實重估，r3）**：全量 **10.6 pd**；10 日範圍 **9.35 pd**（延後：合併視窗、每日上限、重試、信件範本編輯、已讀回條）。核心 migration 與 helpers 併入脊柱 P0／P1／F3／S1 同一列車，**閘門 105 分鐘只算一次**（§8）；E7（`choices` 值域規則）屬脊柱 E-e／E-a 同批引擎項，不計入本表。
6. **需要使用者回答的問題：無不可逆者**（§13）。

## 1. 盤點：已存在什麼（已核對程式）

| 需求 | 現有零件 | 結論 |
|---|---|---|
| 業務開發紀錄 | `dev_cases`（`created_by`、`sales_persons`／`planners` JSON）、`dev_logs`（`log_by` 記錄人、`created_by` 實際建立者、`needs_approval`）；`modules/crm/api.py`；`frontend/pages/dev-crm.html` | **記錄人＝`dev_logs.log_by`**；`dev_logs` 現為**硬刪除**（`api.py` `delete_dev_log`，`DELETE FROM dev_logs`）→ 需在同交易掛鉤（§5.4） |
| **模組規則** | `_require_dev`（api.py:94）：`role ∈ {superadmin, admin}` **或** `"dev_crm" ∈ user.modules`，否則 403『無業務開發模組權限』 | 這是第一道門；批示的 `visible_fn` 必須**逐字等於**這條規則＋`row_access` |
| **列級規則** | `DEV_CASE_ACCESS = row_access.OwnerRule(creator_col="created_by", id_list_cols=("sales_persons","planners"), lenient_json=True)`（api.py:110）→ admin+ 直通，否則須為建立者／業務／企劃；`scope="read"` 另有 `read_bypass_modules`（如 `case_access` 的 cashier） | **成員 ≠ 具 dev_crm**：案件成員可能沒有 `dev_crm` 模組權限（要有測試，§10） |
| **既有共用 helper** | `_DevLogPathAccess.readable`（api.py:119–132）：模組規則＋`row_access.visible("dev_case", …)`（`uploads.path_access`，IP-104）。**注意：它查 `dev_cases` 時沒有 `is_deleted` 條件**（api.py:131），其他端點都有（`WHERE … is_deleted=0`，如 :382、:446、:514、:897） | 抽成單一函式 `dev_case_readable(conn, user, case_row)`，`_DevLogPathAccess` 與批示 `visible_fn` **共用**。**新規則：案件已軟刪除（`is_deleted=1`）時，非管理員一律不可讀**（管理員可讀供稽核）。這會**有意收緊**上傳路徑存取（現況軟刪除案件的附件對案件成員仍可讀），需回歸測試 |
| **刪除路徑** | 案件軟刪除：`approve_dev_case_delete`（api.py:503–534）以 `UPDATE dev_cases SET is_deleted=1 …`（:524）執行，**開發記錄不會被刪**；單筆開發記錄：`delete_dev_log` 硬刪除（`DELETE FROM dev_logs`，約 :1016）。**目前沒有任何還原案件的程式路徑**（只有 `unlink_deleted_quote` 的報價連動；回收桶 T53 的 adapter 尚未涵蓋業務開發） | 兩處都要掛鉤（§5.4）；還原以 `on_target_restored` 預留，待回收桶涵蓋時呼叫 |
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
  on_deleted  = <管理者設定 directive.on_deleted>,   # §5.4；另有 on_restored（目標還原時，無呼叫者則閒置）
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
| 能批示（`directive.who`，**整數代碼**；F3 能力 `directive.write` 的預設集合） | `1`＝**管理員以上＋該案成員**（預設；＝看得到這筆記錄的人）；`2`＝僅管理員以上（收緊）；`3`＝**管理員、案件成員與記錄人所屬部門的主管**（`security`、**紅橫幅**；須同時開啟 `supervisor_read`，由 `cross_check` 把關）；`4`＝指定角色（**F3 就緒前不可選**，`cross_check` 拒絕）。**設定值是選項代碼，不存角色字串**（角色名單歸 F3） |
| **主管讀取例外**（`directive.supervisor_read`，獨立選項，**預設關**，`security`＋紅色橫幅） | 開啟後，記錄人（`log_by`）所屬部門的主管（**只認 `departments.manager_user_id`，且是該筆記錄的記錄人所屬部門**；部門主管之上的處／事業部階層 ＝ `supervisor_scope=2`，『已登錄但不可選』）可**唯讀**這筆開發記錄與其批示。實作只在 CRM 的 `visible_fn(scope="read")` 與批示面板入口（比照 `case_access` 的 `read_bypass` 概念）；**不改 `row_access` 的 `dev_case` 登錄**，所以主管不會因此出現在案件清單、全站搜尋、儀表板、未讀鍵。**主管要『寫』批示**＝同時 `who=3`（兩個設定缺一不可：`who=3` 而 `supervisor_read` 關 ⇒ `cross_check` 拒絕儲存）。**主管對下屬記錄留批示（使用者主要情境）的啟用步驟寫進上線／驗收說明**：①『主管可看到下屬的開發記錄／批示』改為『開』；②『誰可以批示』改為『管理員、案件成員與記錄人部門主管』；兩者皆為高影響設定，各自走確認期間與第二位最高管理者核准 |
| 看得到批示（`directive.visible_to`，整數代碼） | `1`＝**作者＋收件人＋管理員以上**（預設；**同案但不是收件人的其他成員看不到別人的批示**，包含另一位業務／企劃）；`2`＝看得到該記錄的所有人（**真正的放寬**、紅橫幅）。永遠先過第一道 |

## 3. 畫面（白話，無代碼）

1. **按鈕**：每筆開發記錄右上『批示』（名稱走 relabel，可改）。僅有批示權且通過第一道者看得到。
2. **批示面板**：由新到舊，每則『寫的人（職稱）· 日期時間』、內文、『已編輯』、撤回（作者／超管）；輸入框；送出前顯示『將通知：王小明（記錄人），Email：開／關』；收件人被丟棄時顯示 M3 的提示句。
3. **待閱標記**：記錄人的列表／記錄卡顯示紅色徽章『有批示 N』，讀過後消失；**N 與徽章是否出現由伺服器計算**（`/pending` 與清單回應的 `directive_count`，只數 `state='active'`、`read_at IS NULL`、批示未撤回、目標未刪的收件列；`skipped_no_access` 與他人的列不計；前端不自行推算）。徽章是清單欄位（目錄項 `directive_badge`），管理者可在版面編輯器顯示／隱藏／移位（`directive.list_badge`，預設顯示）。
4. **鈴鐺**：『【批示】王大明對一筆開發記錄留了批示』，點擊直達並定位。**通知標題不含案件名與內文**（案件名依 `email_include_case` 同規則，§4.2）。
5. 錯誤訊息白話：『你沒有批示這筆記錄的權限』『批示不可空白』『內容超過 2000 字』『你送出得太快，請稍後再試』。

## 4. 通知設計

### 4.1 站內（永遠寫，不可關）
`audit._notify(type='annotation_received', …, link=…)`；僅對 `state='active'` 收件人。`_mask_money` 對非財務收件人遮蔽金額字樣（R3）。站內通知 90 天清除，待閱狀態**不依賴它**。

### 4.2 Email（管理者選項；預設開）
- 信件類型登錄：`mail_types.register("annotation_received", "收到批示", "business", "none", "記錄人", "您的開發記錄有批示，請閱讀並依批示處理。", "請登入系統，開啟該記錄閱讀批示。", owner="crm")`。個人可退訂、超管可覆寫收件、`MAIL_OFF` 照舊。
- **主旨**固定：`【MOTRIX 系統通知】業務－收到新的批示`；內文**預設通用句**『您有一則新批示』＋批示人＋時間＋按鈕『前往系統查看』。
- **`directive.email_include_case`（整數代碼，風險類 `security`；預設『不帶』）**：`1`＝不帶（預設）、`2`＝帶案件編號、`3`＝帶案件名稱；`2`、`3` 為非預設，顯示**紅色橫幅**（案件資訊將出現在信箱，寄出無法回收）。客戶名稱永不帶。批示內文預設不寄（`email_include_text` 預設 `0`，`security`＋紅橫幅）。
- **S2 寄送實作（修正 r1）**：`send_registered(...)` 回傳 `bool`，**`SEND_UNKNOWN`／`SEND_PERMANENT_FAIL` 也回 True**（保留記號語意），所以**狀態不可用回傳值判斷**。做法：**每位收件人各呼叫一次**（`usernames=[該人]`），傳入 `out={}`，由 `out["outcome"]` 決定 `mail_status`：`SEND_SENT`→`sent`；`SEND_UNKNOWN`→`unknown`；`SEND_PERMANENT_FAIL`／`SEND_TRANSIENT_FAIL`→`failed`；`"no_recipient"`→`skipped_no_email`；`SEND_SKIPPED`→`skipped`。寄送在**交易提交後**的背景執行緒（沿用 `spawn_bg_thread`），不阻塞請求；寄前再過一次 `visible_fn(recipient)`。無 Email ⇒ 僅站內，批示人畫面顯示『對方未設定 Email，已以站內通知送達』。
- **10 日範圍移出（S2）**：合併視窗（同收件人同記錄 N 分鐘合併）、每日上限彙整信、暫時失敗重試。表內保留 `mail_attempts`／`next_try_at` 欄位供後續（含排程掃描 `failed` 且 `next_try_at<=now`，最多 3 次、24 小時）；10 日內 `failed` 只留狀態、批示人面板顯示『Email 未寄出，已以站內通知送達』，並於系統中心健康卡計數。
- 範本文字鍵（標題／開頭／按鈕）走設定；完整範本登錄為脊柱 E-c。

### 4.3 提醒（選項，預設關，10 日範圍『尚未提供』）
`directive.remind_unread_days`：逾 N 天未讀提醒記錄人（沿用 `notify_approval_reminder` 排程模式）。

## 5. 權限、個資、稽核

1. **內文屬管理資訊／個資**：不進全站搜尋索引、預設不進匯出、不進行事曆、不進 `notify_module_activity`；`audit_log.detail` 只存批示 id 與長度。
2. **編輯／撤回**：作者在 `edit_window_minutes`（預設 15）內可改（留 `edit` 事件含舊內文）；作者可撤回（軟刪除）；超管可撤回任何批示；**無硬刪除端點**。
3. **撤回後／目標被刪後的內文，誰能看**（S4 隱私定義）：預設**僅超級管理員**（稽核檢視）；作者與收件人在撤回／目標被刪之後**只見『此批示已撤回』或『此記錄已刪除』標記，不見內文**。不提供選項放寬（避免被刪資料外流）。
4. **目標被刪／還原（`directive.on_deleted`，整數代碼；管理者選項）**：`1`＝**擋下（預設）**——有批示的開發記錄，**只有管理員以上**可以刪除，其他人得到 409『這筆記錄有主管批示，只有管理員可以刪除』；`2`＝保留——照既有刪除權限刪，批示與事件保留（琥珀橫幅）。
   - **掛鉤位置（兩處，皆同一交易、在 `commit` 之前）**：①**案件軟刪除** `approve_dev_case_delete`（api.py:524 的 `UPDATE dev_cases SET is_deleted=1 …`）：因為案件被軟刪除時**其下所有開發記錄仍在表中**，掛鉤要對**該案件的每一筆 `dev_logs`**（以及 `dev_case` 目標）呼叫 `annotations.on_target_deleted(conn, target_type, key)`；②**單筆開發記錄硬刪除** `delete_dev_log`（`DELETE FROM dev_logs` 之前）。`on_target_deleted`：寫 `target_gone=1`、把仍待閱的收件列設 `read_at=now`（避免永久紅點）、寫 `annotation_events`。
   - **`on_deleted=1` 與案件軟刪除**：案件刪除本來就需最高管理者核准（`approve-delete`），視為已是管理員以上操作，**不另擋**；『擋下』只針對一般成員刪除單筆記錄與案件刪除申請的發起（`request-delete`）時**提示該案件有批示**（不擋申請，避免卡死流程）。
   - **還原（`on_target_restored`）**：目前**沒有任何還原案件／記錄的程式路徑**；元件預留 `on_target_restored(conn, target_type, key)`（把 `target_gone` 清回 0；已被標已讀的收件列**不**回復待閱，避免重複打擾；內文可見性回到一般規則）。待回收桶（T53 adapter）涵蓋業務開發時由 adapter 呼叫；在那之前 `target_gone` 視為單向，測試以單元層呼叫驗證。
   - 測試：刪除失敗回滾時批示不變；案件軟刪除後該案件所有記錄的批示皆 `target_gone`；硬刪除單筆；`on_deleted` 兩值各自行為；非管理員刪有批示的記錄 409。
5. **備份／重置／封存（S1）**：`db.py` 三份清單都要補——觸發器名單（`saved_triggers`，:299–:321 區，加 `annotation_events_no_update／no_delete`，demo 重置時拿掉再建回，比照 `config_change_events`）、demo 重置清單（:427，加 `annotations`、`annotation_recipients`、`annotation_events`）、備份清單；封存規則同步。往返測試涵蓋。
6. **稽核**：`audit_log` 動作 `annotation.create／edit／delete／mail_failed`；『讀取』只記在 `annotation_events`。設定變更走 `config_changes` 帳本。
7. **帳號異動**：批示人停用／改名 ⇒ 顯示快照；記錄人停用 ⇒ 收件列保留，不寄信、不計待閱。

## 6. 框架化：選項＋預設＋影響橫幅（S6：平面鍵）

設定群組 **`directive`**（顯示名『批示』；`register_group("directive", …)`）。**欄位鍵為平面 snake_case，無點號**（文件寫作 `directive.who` 只是『群組.鍵』稱呼）。**選項型欄位一律為整數代碼（PM 決定，比照 `quote_alt`／`system_hub.show_denied`）**：開關＝`0/1`、多選一＝`1..n`（`min=1,max=n`），`choices=[(代碼, 中文標籤, 影響說明)]` 供畫面顯示。理由（已核對程式）：`validate_values` 只檢查型別與 `min/max`，`choices` 目前**只用於顯示**——`str`＋`choices` 會接受任何字串；`publish()._loosens` 也只認數字，`bool`／`str` 的 `loosen` 不會觸發待生效。

| 欄位鍵 | 代碼（預設加粗） | 風險 | 讀取到未知值時（失敗關閉） | 橫幅／備註 |
|---|---|---|---|---|
| `dev_log_enabled` | `0` 關／**`1` 開** | ops | 預設 `1` | 關閉＝按鈕與徽章隱藏，既有批示保留 |
| `dev_case_enabled` | **`0` 關**／`1` 開 | ops | 預設 `0` | — |
| `who` | **`1` 管理員以上＋案件成員**／`2` 僅管理員以上／`3` 管理員、案件成員與記錄人部門主管／`4` 指定角色 | **security** | **`2`（最嚴）** | `3`⇒**紅**，須 `supervisor_read=1`；`4` F3 前不可選（`cross_check`） |
| `supervisor_read` | **`0` 關**／`1` 開 | **security** | **`0`** | `1`⇒**紅**：『部門主管可唯讀其下屬的開發記錄與批示』；`impact_fn` 顯示目前主管人數與受影響記錄數 |
| `supervisor_scope` | **`1` 記錄人所屬部門的主管**／`2` 含處／事業部階層 | **security** | **`1`** | `2` 已登錄但不可選（`cross_check` 拒絕，待組織階層資料就緒） |
| `visible_to` | **`1` 作者＋收件人＋管理員以上**／`2` 看得到記錄的所有人 | **security** | **`1`** | `2`⇒**紅**：同案其他成員也看得到他人的評語 |
| `clear_on` | **`1` 開啟面板**／`2` 按『我已閱讀』 | ops | 預設 `1` | — |
| `email_enabled` | `0` 關／**`1` 開** | ops | 預設 `1` | 關⇒琥珀：記錄人可能漏看 |
| `email_recipients` | **`1` 僅記錄人**／`2` ＋建立者／`3` ＋案件成員 | ops | 預設 `1` | 加人⇒琥珀；加入者同樣須通過 `visible_fn` |
| `email_include_case` | **`1` 不帶**／`2` 案件編號／`3` 案件名稱 | **security** | **`1`** | `2`、`3`⇒**紅**（寄出無法回收） |
| `email_include_text` | **`0` 否**／`1` 是 | **security** | **`0`** | `1`⇒**紅**：批示內文將寄到信箱 |
| `email_subject_text`／`email_intro_text`／`email_button_text` | 文字：白話預設句 | ops | 預設句 | 占位符以 chips；不可放金額／個資變數 |
| `edit_window_minutes` | 整數 **15**（0＝不可編輯） | ops | 預設 | — |
| `max_length` | 整數 **2000**（上限 2000，伺服器硬限；只能調小） | ops | 2000 | — |
| `write_rate_per_minute` | 整數 **10** | ops | 預設 | 超過⇒429 白話訊息 |
| `list_badge` | `0` 隱藏／**`1` 顯示** | ops | 預設 `1` | — |
| `allow_self` | `0` 關／**`1` 開** | ops | 預設 `1` | — |
| `on_deleted` | **`1` 擋下**／`2` 保留 | **security** | **`1`** | `2`⇒琥珀 |
| `read_receipt`、`remind_unread_days` | — | — | — | **10 日範圍不登錄**（登錄時才加） |

- **值域規則（E7，引擎小改動＋測試，併脊柱 E-e／E-a 同批，約 0.25 pd；見脊柱 r9 §17.2）**：`SettingDef` 若有 `choices`，**寫入與讀取都必須是其中一個代碼**——`validate_values` 對不在 `choices` 內的值回問題（寫入被擋）；`_effective` 讀到庫內不在 `choices` 內的值時視為不合法、回預設並記 warning。測試：非選項值寫入被拒；庫內被竄改成未知值時，讀取端得到預設（與 `clamp` 語意一致：不丟例外、不放行）。
- **讀取端失敗關閉**：所有讀取批示設定的程式都經單一存取函式 `directive_cfg(name)`（不直接用 `settings.get`）。值未知、超出值域、或讀取發生例外時：一般欄位回預設；**`security` 欄位回『最嚴』值**（見表中『讀取到未知值時』欄：`who→2`、`supervisor_read→0`、`supervisor_scope→1`、`visible_to→1`、`email_include_case→1`、`email_include_text→0`、`on_deleted→1`）。測試：把庫內值改成未知值 ⇒ 行為等同最嚴。
- **不可選項目與交叉檢查**（`cross_check`，登錄在群組上）：`who=4` 被拒（F3 就緒前）；`supervisor_scope=2` 被拒；`who=3` 而 `supervisor_read=0` 被拒（兩個方向：關閉 `supervisor_read` 時若 `who=3` 亦被拒，訊息指出須先把 `who` 改回）。畫面以『尚未提供』標示不可選的選項，不顯示代碼。
- 高影響者（security／money 級與紅橫幅）：`risk_text` 必填（登錄當下檢查）；結構化 `impact_scope` 待脊柱 E-e（`SettingDef.impact_scope`）落地；**E-e 就緒前以 `impact`＋`risk_text`＋`choices` 影響說明承載，並同步在登錄清單標註 `impact_scope` 待補**。放寬走確認期＋雙人核准（`loosen`／`requires_pending`）。
- **寫死的只有**：先過 `visible_fn`、作者與時間由伺服器寫、軟刪除與事件只增不改、主旨不含內容、API 上限（§9）。

## 7. 與脊柱（欄位版面框架 r7）的對齊

| 脊柱零件 | 批示登錄內容 |
|---|---|
| 目錄 | 表面 `module:crm.dev_log`（page）、`module:crm.dev_log_list`（list）；項目 `directive_badge`（badge；**由伺服器計算**，只數 `state='active'` 的待閱收件列）、`directive_count`、`directive_panel`；`isMoney=假`；可見性判定＝**CRM `visible_fn`（含 `dev_crm` 模組門）且收件人存取檢查** |
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
| E7 | `SettingDef.choices` 值域規則（寫入拒絕、讀取回預設）＋測試；`directive_cfg()` 失敗關閉存取（本元件內） | 引擎部分併脊柱 E-e／E-a 同批（約 0.25 pd，不計入本表）；`directive_cfg` 計於 A6 |

CRM 側（`modules/crm`）的登錄與前端隨 CRM 模組列車，不佔底層閘門。

## 9. API 草案與上限（S5）

- `GET /api/annotations?target_type=&key=`：先 `visible_fn`，再依 `visible_to` 過濾；**絕不改狀態**。
- `POST /api/annotations`：`{target_type, key, body}`。**伺服器端**：`body` 去頭尾空白、拒空白、**≤ `max_length`（硬上限 2000）**、去控制字元；作者／時間／收件人皆伺服器決定；**每位作者寫入頻率限制**（`write_rate_per_minute`，預設 10 次／分，超過 429＋白話訊息）；回 201。
- `PATCH /api/annotations/{id}`（作者、視窗內）；`DELETE …/{id}`（軟撤回，作者或超管）。
- `POST /api/annotations/{id}/read`：**僅更新呼叫者自己的收件列**（沒有 ⇒ 404）；呼叫者須通過 `visible_fn`。
- `POST /api/annotations/pending`：`keys` **最多 200 筆**（超過 400）；**逐鍵存取策略**：同一請求內先一次查出涉及的 `dev_cases`，對每個案件只算一次 `visible_fn`（快取），不可見的鍵靜默略過（看不到的那筆有沒有批示本身就是資訊）；只回呼叫者為 `state='active'` 收件人的待閱；回應附 `directive_count`（徽章數字由伺服器算，前端不推算）。
- 新增路由登錄整合點並重產 route golden。

## 10. 測試清單（紅 → 綠）

1. **M2** 案件成員但**沒有 `dev_crm`** ⇒ 讀、批示、被通知皆 403／略過；admin 無 `dev_crm` 也可；有 `dev_crm` 但非成員（非 admin）⇒ 不可（`row_access`）。`_DevLogPathAccess` 與批示 `visible_fn` 走同一函式（斷言同一物件，改規則兩邊同動）。
2. **M1／整數代碼** 預設 `who=1`；`who=2` 收緊生效；`who=4`、`supervisor_scope=2` 不可選（`cross_check`）；`supervisor_read=0`（預設）：部門主管（非成員）403；`=1`：僅唯讀（可讀記錄與批示、不能寫、不出現在案件清單／搜尋／儀表板／`/api/reads/unread`），`row_access` 的 `dev_case` 登錄不變（快照斷言）；**非選項值寫入被拒、庫內未知值讀取回預設（`security` 欄位回最嚴）**。
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
16. **M2 主管情境（使用者主要情境）**：`who=3` 且 `supervisor_read=1` 時，記錄人所屬部門的主管可讀並**寫**批示；另一部門的主管、部門主管的上級（`supervisor_scope=2` 不可選）不可；`who=3` 而 `supervisor_read=0` 儲存被 `cross_check` 拒絕、反向亦然；預設組態下主管**不能**寫批示（驗收說明的兩個設定缺一不可）。
17. **M3 可見性預設**：同案成員 A 讀不到成員 B 寫給記錄人 C 的批示（A 非作者、非收件人）；C（收件人）、作者、管理員讀得到；`visible_to=2` 時 A 讀得到；撤回後 A、C 皆只見標記。
18. **S1 刪除掛鉤**：案件軟刪除（`approve-delete`）⇒ 該案件**每一筆**開發記錄與案件本身的批示 `target_gone=1`、待閱列已清；單筆硬刪除同；`on_target_restored` 單元測試（清回 `target_gone`、已讀不回復待閱）；`on_deleted` 兩值；**非管理員對軟刪除案件的記錄與附件路徑不可讀（含 `_DevLogPathAccess` 回歸）**、管理員可讀。
19. **S4 徽章**：`directive_count` 只數 `state='active'`、未讀、未撤回、目標未刪的列；`skipped_no_access` 與他人的列不計；清單回應的數字等於 `/pending`。
20. **S2** `email_include_case` 為 `security` 風險：非預設值有紅橫幅與 `risk_text`；`security` 登錄缺 `risk_text` ⇒ 登錄失敗。

## 11. 風險

- **R1** S1 編輯畫面未建 ⇒ 管理者暫不能改選項；預設皆為安全值。
- **R2** 信件外洩：預設不寄案件名與內文；`email_include_case=case_name`、`include_text` 皆有橫幅。
- **R3** 批示內文含金額：站內通知遮蔽；面板內顯示依 `visible_to`（不在目錄 `isMoney` 管轄）。建議提示『請勿在批示寫報價金額』（可關）。
- **R4** 硬刪除：以 `on_deleted` 與同交易掛鉤處理；若日後改軟刪除，改為跟隨。
- **R5** 熱點檔 `dev-crm.html`／`crm/api.py`：PM 排單一順序（與 D1 清單接線不可並行改同檔）。
- **R6** `supervisor_read` 的 `read` 路徑需在 `crm/api.py` 現有 GET 端點加分支；漏掉任一端點會形成『批示可讀、記錄不可讀』的不一致 ⇒ 測試 2 逐端點覆蓋，並以『只經批示入口可讀』為準（不擴大 `row_access`）。
- **R7** 記錄人口徑（`log_by` vs `created_by`）：預設 `log_by`，建立者為選項；改 `owner_fn` 單點。
- **R8** 10 日範圍移出重試後，暫時失敗的信件不會自動補寄；以面板提示＋健康卡計數補償，並保留欄位供後續。
- **R9** 整數代碼降低可讀性：畫面與稽核一律顯示中文標籤，不顯示代碼；`choices` 的標籤改名不影響已存代碼；新增選項只能追加新代碼，不得重用或改義舊代碼。

## 12. 工量與排序（r2 誠實重估）

| 項 | 內容 | 全量 pd | 10 日 pd |
|---|---|---|---|
| A1 | `core/annotations`：三表、migration、觸發器、服務層、目標登錄、API 與上限（S5）、route golden、`db.py` 三份清單（S1）、core-only RC 測試 | 1.75 | 1.75 |
| A2 | CRM 登錄：共用 `dev_case_readable()`（含改 `_DevLogPathAccess`、軟刪除規則）、`owner_fn`、收件人過濾（M3）、案件軟刪除與單筆硬刪除兩處掛鉤＋還原預留（S1）、`supervisor_read`／`who=3` 主管情境、`directive.who` 預設集合 | 1.50 | 1.50 |
| A3 | 待閱／已讀／再批示、批次待閱（逐鍵策略）、讀取時再檢查；已讀回條 | 0.85 | 0.75 |
| A4 | 站內通知＋`mail_types` 登記＋逐收件人寄送與狀態（S2）；全量另含合併視窗、每日上限、重試排程 | 1.50 | 0.75 |
| A5 | 前端：按鈕、面板、徽章、白話文字、深色／手機 | 1.50 | 1.50 |
| A6 | 設定群組 `directive`（整數代碼、`cross_check`、不可選項、`directive_cfg` 失敗關閉）、橫幅、帳本、白話守門 | 0.85 | 0.60 |
| A7 | 稽核、封存、目標刪除隱私處置、停用帳號 | 0.65 | 0.65 |
| A8 | 測試（§10 全部，含 16～20）、登錄表驅動守門、e2e | 2.00 | 1.85 |
| **合計** | | **10.60** | **9.35** |

算術（r3）：全量 1.75＋1.50＋0.85＋1.50＋1.50＋0.85＋0.65＋2.00＝10.60；10 日 1.75＋1.50＋0.75＋0.75＋1.50＋0.60＋0.65＋1.85＝9.35。較 r2（10.00／8.75）增加：A2 +0.25（兩處刪除掛鉤、還原預留、`who=3` 主管情境）、A6 +0.10（整數代碼、交叉檢查、失敗關閉存取）、A8 +0.25（測試 16～20）。**E7 值域規則屬引擎項（約 0.25 pd），計於脊柱列車，不在本表。**底層閘門 105 分鐘不計入 pd。

排序：後端（A1～A4、A7）與脊柱 P0／P1 並行、互不依賴解析器；A5 徽章在目錄落地前用固定徽章，預設相同。里程碑 1 帶 A1（底層列車）與 CRM 後端；前端與設定在里程碑 2。

## 13. 需要使用者回答的問題與待 PM 確認

- 使用者：無不可逆者。隱私預設（信件不帶案件資訊與內文、無硬刪除、撤回後內文僅超管可見、其他成員看不到他人批示）由 PM 先定，可事後在設定中心改（除『撤回後內文僅超管』不提供放寬）。
- **O1（已定）**：`supervisor_read` 只開『經批示入口可讀』，不進案件清單／搜尋／儀表板。
- **O2（回答）**：主管能否『寫』批示 ＝ 取決於 `who`：預設 `1` 不能；`who=3` 且 `supervisor_read=1` 才能。預設組態保守；上線／驗收說明須明確告訴管理員『要讓主管對下屬留批示，需把這兩個設定都打開』（§2.4）。
- **O3（回答）**：只認『記錄人所屬部門』的 `departments.manager_user_id`（一個部門一位）；處／事業部階層（`supervisor_scope=2`）已登錄但不可選，待組織階層資料與使用者需求明確再開放。
