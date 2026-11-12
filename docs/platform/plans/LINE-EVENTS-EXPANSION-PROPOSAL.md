# LINE 通知事件擴充提案（唯讀調查，未實作）

> 作者：hichan-6　日期：2026-11-12　派工：MOTRIX-Platform（PM）
> 調查基準：`train/t79-int` @ `333ee073b`（主程式）；T80 新增的 `line_quota`／`line_recipients`／心跳監控只存在於 T80 分支（`wip/audit-t80-notify-17`／`feat/auth-lockout-alert`），引用時標明分支。
> 狀態：**提案，需 PM／使用者裁示後才開工。** 本檔以外沒有改任何程式、設定或資料。

---

## v2 修訂（2026-11-13，使用者新裁示；**與下文衝突處以本節為準**）

> 使用者原話：「LINE 主要業務開發更新、指定人員、簽核這些要發通知；寄信有的 LINE 都要，但我可以決定誰要發。」
> 同時選定：獎金／薪資／勞報單維持不開；額度先用免費方案、快滿再升級、沿用 90% 分級；手機版與 LINE 排同一班上線。
> 實作由 hichan-6 負責，建在 hichan-3 的共用底層上（`LINE_EVENTS` 事件字典、`deliver_event`／`notify_event` 單一入口、`event_audience` 收件人解析、`line_key` 已推播記號、`line_quota.reserve_paused` 90% 保留）。**實作狀態（2026-11-13）：已完成於分支 `feat/line-events-all`**（基底＝hichan-3 批次 0 commit c654a9380）；實際介面與行為以 `backend/core/CHANGELOG.md` (next) 2026-11-13 段與 `docs/platform/guides/LINE-NOTIFY-USER-GUIDE.md` 為準，本文為提案與取捨紀錄。

### v2-0 PM 裁示（2026-11-13，已定案）

1. **LINE-only 新事件同意新增**：`dev_case_unassigned`、`dev_case_deadline_changed`、`dev_log_directive_reply`、`dispatch_file_delete_request`（站內通知有、信件沒有）；只加 LINE，**不新增 Email**；設定頁標示「僅 LINE」。
2. **CRM 更新類預設收件人＝案件相關人**（`sales_persons`＋`planners`＋`assigned_to`＋建立者）；管理員要看用 `business_plus` 自己加；拜訪與進度回報預設關，其他 CRM 事件也預設全關。
3. 排除 `system_test_mail`、`line_quota_warning`：同意。
4. 「核准」LINE 預設只給申請人：同意。
5. 手機版：hichan-4 的 `fix/mobile-cases-layout` 動共用 CSS 與頂欄；設定頁重整前先看它的 diff。hichan-4 之後做估價單，會動報價相關通知呼叫端文字（類型名稱），不碰 `line_notify`／`email_notify` 核心。
6. 所有預設值都可由管理員在設定頁改。

### v2-1 範圍（取代 §1.4／§2.4 的評等）

| 項目 | 規則 |
|---|---|
| 納入 | **所有有寄信的事件**（含舊寫法 `notify_*`、模組登記的類型、自訂模組）；以 `mail_types` 登記表為準，約 100 種（實作時用登記表實際數為準，不手寫清單） |
| 排除（使用者裁示） | 獎金、薪資、勞報單：`bonus_*`（8 種）、`payslip_*`（7 種）、以及 `owner="payroll"` 的任何類型。**測試要守：這些 key 不得出現在 LINE 事件清單、設定頁、接線判斷裡**，且日後新增 payroll 類型預設也被擋 |
| 排除（我的判斷，請 PM 確認） | `system_test_mail`（信件設定測試信，LINE 有自己的「驗證 token」）、`line_quota_warning`（LINE 額度告警用 LINE 發＝耗額度且額度滿時發不出去，維持 Email） |
| 不在範圍 | 目前沒有信件的（例如「缺單據」主動偵測）。**例外**：使用者在 (b)(c) 要求「到 crm 找實際有寄信或應該通知的點」——站內通知有、信件沒有的點（見 v2-4），我列為「LINE-only 新事件」，需 PM 確認可否新增（不新增 Email） |
| 附件類 | `monthly_report`／`case_closing_report`：LINE 只發文字「報表已產生，請登入系統」，不帶附件、不帶金額 |
| 預設 | 全部**關**；由最高管理者逐項開（維持 T79／T80 規則） |

### v2-2 「誰要發」：管理員指定人員（在 T80 角色＋個人勾選上加一層）

T80 現有兩層（**只縮不擴**）：`event_roles`（角色允許清單）、`line_prefs`（個人退訂）。新增第三層「**管理員指定**」，每個事件一份設定 `system_settings.line_notify.audiences[event_key] = {"mode", "roles", "users"}`：

| 模式 | 收件人 | 白話 |
|---|---|---|
| `business`（**預設**，沒設定＝此模式） | 業務收件人（事件收件人＋群組，經 `event_audience` 解析）∩ 角色允許清單 | 與現在行為完全相同 |
| `business_plus` | 上列 **∪** 管理員指定的「角色＋個人」 | 「照原本的人發，另外再加這幾位」 |
| `only` | **只有**管理員指定的「角色＋個人」，業務收件人不看 | 「只發給這幾位業務」 |

規則（寫死，測試守）：
1. 指定的個人／角色，一律只取**在職**帳號；停用帳號濾掉。
2. 管理員明確指定的人**不受** `event_roles` 角色允許清單過濾（那是對「業務收件人」的縮小；明確指定就是管理員的決定）。
3. **個人在自己的 LINE 設定退訂該事件，一律尊重**（連管理員指定的也不發）——手機是本人的；設定頁指定清單旁標示「已自行關閉」讓管理員知道。
4. `exclude`（操作者本人）只套用在**業務收件人**，不套用在管理員明確指定的人。
5. 沒綁 LINE 的人在設定頁指定清單旁標示「尚未綁定」（發不到），不阻擋儲存。
6. 預設值＝`business`，**沒有任何人被自動加入或自動移除**；既有兩個事件與 `auth_lockout` 行為不變。
7. 額度保留與已推播記號等 hichan-3 的底層規則照常套用（`only` 模式也會被 90% 暫停，除非事件是 critical）。
8. 設定寫入走 `line_notify.settings_lock`；API 驗證：mode 合法、roles 在 `mail_types.ROLES`、users 為存在的帳號字串、人數上限（例如 200）；非最高管理者不可改。

實作落點：`helpers/line_recipients.py` 新增 `resolve_audience(event_key, business_usernames)`；`line_notify.deliver_event` 在 `filter_usernames` 那一步改呼叫它（**這是對 hichan-3 檔案的一行掛鉤，已請它確認**）。

### v2-3 設定頁：依模組分組

事件約 100 種，不一次攤開。設定頁（`frontend/pages/notification-settings.html` 的 LINE 區塊）改成：
- 「**模組**」清單，每個模組一個可收合區塊，標題列顯示「已開 N／共 M」；
- 區塊內每個事件一列：開關、白話名稱、重要程度標籤（重要／一般）、收件人摘要（例如「業務收件人」「業務收件人＋3 人」「只發 2 人」）、「設定誰要發」按鈕（展開角色勾選＋個人搜尋勾選＋模式三選一）；
- 事件所屬模組由 `LINE_EVENT_GROUPS` 對照表決定：`MailType.owner`（case／accounting／payroll… ）為主，核心登記的類型依 key 前綴對照（`approval_*`／`shipping_*`／`invoice_voucher_*`／`payment_request_*`／`daily_task_*`／`dev_case_*`／`cert_*`…）；對不上的歸「其他」。守門測試：**每個已接線事件都必須有分組**（新增事件忘了分組會失敗）。

### v2-4 事件清單與收件人規格（依使用者優先順序）

priority：簽核與指派類＝`normal`；系統告警＝`critical`（`backup_error`、`backup_stale`、`heartbeat_stale`、`disk_space_low`、`cert_expiry`、`company_setup_alert`、`auth_lockout`；`geo_quota_warning`、標案來源異常類為 `normal`）。90% 保留只暫停 `normal`。

**(a) 簽核類**（約 70 種；全部走「申請人／當層簽核人」，**預設 `business`**）

| 子類 | 事件 key（依單據） | 業務收件人（事件收件人／群組／排除） | 觸發點 |
|---|---|---|---|
| 待簽核／下一層 | `approval_request`／`next_tier`（報價）；`shipping_*`；`payment_request_*`；`invoice_voucher_*`；`contractor_voucher_*`；`expense_form_*`；`material_order_*`／`material_payment_*`／`material_change_*`；`dispatch_*`／`dispatch_completion_*`；`voucher_*`／`ledger_action_*`（會計）；`custom_record_*`／`custom_def_*`（自訂模組）；`completion_note_*` | 當層簽核人（含代理人）／`none`／無 | 見 §2.2；舊寫法 `email_notify.py` 各 `notify_*`（報價 `quotations.py:640/647/660/5652`、出貨 `shipping_notes.py:465`、請款 `payment_requests.py:655`、開票 `invoice_vouchers.py:560`、承攬匯款 `contractor_vouchers.py:691`） |
| 退回 | 各 `*_returned` | 申請人／`none`／無 | `quotations.py:5750` 等 |
| 核准 | 各 `*_approved`（報價 `approved` 信件群組為 admins，**LINE 預設只給申請人**：字典 `line_group: None`） | 申請人／`none`／操作者本人 | `quotations.py:5483`、`payment_requests.py:752`、`shipping_notes.py:607` 等 |
| 催辦 | `approval_reminder` | 逾期那一層簽核人／`superadmins`／無 | `system_checks.py:683` |
| 重新送審 | `resubmit_requester`、`approval_review_edit`（既有） | 申請人／送審人 | `quotations.py` |

**(b) 指定人員類**（被指派／被加入／被移除）

| 事件 | 有無信件 | 業務收件人 | 觸發點 | 備註 |
|---|---|---|---|---|
| `dev_case_assigned` 被指派業務開發案件 | 有 | 被指派人／`none`／無 | `modules/crm/api.py:770` | |
| `dev_case_unassigned` 前任負責人被取消指派 | **僅站內** | 前任（`old_user`）／`none`／無 | `crm/api.py:775` | **LINE-only 新事件**（T73 稽核 S5 已指出「前任失去存取卻不知情」） |
| `dev_case_deadline_changed` 回覆期限被調整 | **僅站內** | 被指派人／`none`／無 | `crm/api.py:780` | **LINE-only 新事件** |
| `dev_log_directive` 開發記錄批示 | 有 | 要回覆的成員／`none`／無 | `crm/api.py:1550` | 全文不外送，只通知「請登入查看」 |
| `dev_log_directive_reply` 批示被回覆 | **僅站內** | 批示作者或對象／`none`／回覆者本人 | `crm/api.py:1603` | **LINE-only 新事件** |
| `daily_task_assigned` 工作事項被指派 | 有 | 負責人／`none`／指派者本人 | `modules/daily_tasks/api.py:462`、`:531` | |
| `daily_task_edited`／`daily_task_completed`／`daily_task_overdue(_manager)`／`range_task_deadline` | 有 | 負責人與主管／依登記 | `daily_tasks/api.py:1012`、`:1070` | 量大，預設關 |
| 案件負責人／協作者被加入、被移除 | **無信件也無站內通知** | — | `quotations.py:407–420` 註解：「指派協作者」機制實務上為 0 張、尚未落實 | **不在範圍**；機制落實後再議 |
| 「工單」 | 承攬商派發 `dispatch_*` 已在 (a)；另有 `dispatch_file_delete_request` 僅站內 | — | `subcontract/dispatch_notify.py` | 檔案刪除申請可併為 LINE-only 新事件，**待 PM 確認要不要** |

**(c) 業務開發（CRM）更新**

調查結果：CRM 目前所有「更新」信件都走同一個類型 `module_activity`（群組＝全體管理員，主旨用 `module_label／action_label` 區分；`email_notify.py:2002`），`modules/crm/api.py` 有 14 個呼叫點。若直接把 `module_activity` 當一個 LINE 事件，使用者**無法只選「拜訪」或「階段變更」**。做法：
- `notify_module_activity` 新增選填參數 `line_event`（事件 key）；CRM 的各呼叫點各傳一個專屬 key；沒傳的其他模組維持單一 `module_activity` 事件（預設關、標示「量大」）。
- 事件字典新增 `mail_key` 欄位：專屬 key 的「收件人設定來源」指回 `module_activity`（`event_audience` 查設定時用 `mail_key`），所以不用為了 LINE 新增信件類型、**Email 內容與收件人完全不變**。

| 事件 key（建議） | 對應操作 | 觸發點 | 業務收件人（建議；PM 可改） | 每月則數估 |
|---|---|---|---|---|
| `crm_case_created` | 新增案件 | `crm/api.py:477` | 案件相關人（業務／企劃／建立者）；`line_group: None` | ~8×2 |
| `crm_case_status` | 狀態變更（＝階段變更） | `crm/api.py:684` | 案件相關人＋被指派人；排除操作者 | ~15×2.5 |
| `crm_case_progress` | 更新進度回報 | `crm/api.py:844` | 案件相關人；排除操作者 | ~40×2.5（**量大，預設關**） |
| `crm_visit_logged` | 新增拜訪記錄（＝拜訪／跟進） | `crm/api.py:1209` | 案件相關人；排除操作者 | ~60×2.5（**量大，預設關**；只發「某人新增拜訪記錄」，不放內文） |
| `crm_log_approved` | 審核通過開發記錄 | `crm/api.py:1358` | 記錄作者 | ~20×1 |
| `crm_case_converted` | 轉建報價單 | `crm/api.py:882` | 案件相關人＋admins | ~5×3 |
| 指派案件／調整期限（`module_activity` 那一則，`crm/api.py:784`） | — | — | 與 `dev_case_assigned` 重複，**併入 (b)，不另立** | — |
| 刪除／連結異動的申請與核准／退回 | 既有類型 `dev_case_delete_request`／`dev_case_relink_request`（有信）＋核准／退回走 `module_activity` | `crm/api.py:571/642/654`、`:926/1004/1017` | 申請人／最高管理者 | ~3 |
| `dev_case_stale`／`dev_case_reply_overdue`（既有信件） | 逾期未跟進／回覆逾期 | `crm/api.py:1672`、`:1738` | 業務與規劃人員；被指派人與指派人 | ~10 |

「案件相關人」＝`dev_cases.sales_persons`＋`planners`＋`assigned_to`＋建立者（與 `crm/api.py:140–149` 的 `DEV_CASE_ACCESS` 同一組人），在職者。

### v2-5 額度（沿用 90% 分級，免費方案，快滿再升級）

- 所有事件預設關，用量由管理員的勾選決定；本提案不會因為「全部接線」而讓則數自動增加。
- 估算（§3 假設不變）：簽核與指派類全開約 **200～260 則／月**；加上 CRM 的狀態／被指派／批示約 +50；`crm_case_progress`、`crm_visit_logged`、`module_activity` 是量大項，建議維持預設關。
- 免費額度 200 則是**未經 LINE 官方確認**的數字，**以設定頁用量條的上限為準**；T80 的 80%／100% 告警＋hichan-3 的 90% 保留（critical 照發）就是「快滿再升級」的觸發機制。

### v2-6 測試（每個事件至少一組；以參數化涵蓋全清單）

1. **LINE 有發**：對清單每個事件，打開開關、綁定測試收件人，觸發 → `_http` 被呼叫且收件人正確（參數化跑全事件；觸發函式用統一的「事件夾具表」）。
2. **Email 不受影響**：同一觸發在 LINE 開／關兩種情況下，信件收件人、主旨、內容逐字相同；LINE 失敗（429／500）不影響信件與呼叫端回傳值。
3. **管理員指定生效**：`business`／`business_plus`／`only` 三模式各驗；指定個人收得到、沒指定的收不到；個人自行退訂仍尊重；停用帳號濾掉；`only` 模式下業務收件人不收。
4. **獎金／薪資／勞報單不在清單**：清單、設定頁 API、`event_enabled`、`set_event` 對這些 key 全部拒絕；新增一個假的 payroll 類型也被擋。
5. **分組守門**：每個已接線事件都有模組分組；每個事件字典項都有 priority。
6. **額度保留**：用量 ≥ 90% 時 `normal` 被暫停、`critical` 照發（含 `only` 模式）。
7. **設定頁**：e2e 驗分組收合、開關、指定個人儲存／重新載入、已退訂／未綁定標示。
8. 全部通過 `test_mail_registry`／`test_notify_matrix`／既有 T79／T80 LINE 測試；`known_flakes` 維持空。

### v2-7 與其他班次的關係

- 手機版與 LINE 同一班上線（使用者裁示）：設定頁的分組與指定人員 UI 要在手機寬度下可用（沿用既有手機版面樣式，**開工前先確認 hichan-4 的分支進度，避免撞檔**）。
- 不碰正式機；更新步驟檔（`docs/platform/prod-tasks/`）由 PM／整合者決定要不要我寫。

---

## 0. 給使用者看的白話摘要（先看這段）

**現在的情況**
- 目前系統只有 **2 種事件** 會同時發 LINE：「報價單審核中被簽核人編輯」和「設備保固即將到期」。
- 更大的問題：這兩種 LINE **是掛在 Email 上面的**。系統是「先寄信、信有寄出去才順便發 LINE」。所以只要這個人沒有 Email、自己退訂了信件、或管理者把那種信關掉，**他就算綁了 LINE 也收不到**。
- 另外，系統裡大約 **120 種**會寄信的事件，絕大多數（包含最常用的「報價單／請款單／出貨單待審核」）程式寫法比較舊，**根本沒有接上 LINE 的入口**，想勾也勾不到。

**建議新增的事件（白話版）**
| 類別 | 例子 | 為什麼值得發 LINE |
|---|---|---|
| 系統出事（一定要看） | 備份失敗、備份停擺、心跳監控異常、硬碟快滿、憑證快到期 | 出事時沒人看信，資料可能掉了；每月幾乎不會超過 10 則 |
| 等你處理的單子 | 輪到我簽核、簽核卡太久被催、出納待撥款、付款日到了 | 手機馬上看到，簽核就不會卡 |
| 該注意的狀況 | 應收款逾期、結案被擋下、材料到貨、庫存跌破安全量 | 這些現在沒人主動通知，要自己上系統才發現 |

**免費額度夠不夠？**
- LINE 官方帳號的免費額度是**每月 200 則**（「發給 3 個人」算 3 則）。這個數字我是從網路資料看到的，**各家說法不一致，而且有資料提到 2026 年 11 月方案會調整**，請 PM 到 LINE 官方帳號後台確認；系統設定頁的用量條顯示的「上限」就是 LINE 回報的真值，以它為準。
- 以「公司約 20 人、每月約 50 張要簽核的單據」的**假設**估算（還沒有正式機資料可校準，見第 3 節）：
  - 現有 2 種 ＋ 第一批（系統告警、催辦、結案被擋）：**約 60 則／月**，夠用。
  - 再加第二批（付款、出納、費用／材料／派發待簽核）：**約 170 則／月**，貼近 200 的 85%，剛好卡在 80% 告警線。
  - 全部開滿：**約 370 則／月**，免費額度不夠，要升級方案，或把「每天提醒」改成「每天彙整成一則」。
- 額度用完時 LINE 會拒收，**連「備份失敗」這種重要的也會收不到**。所以我建議做「**額度保留給重要告警**」：用量過 90% 時，次要事件自動暫停，系統告警照發。

**我建議的做法**
1. 先做共用底層（把 LINE 改成不依附 Email、加「彙整」與「重要程度」），不新增事件。
2. 第一批只上系統告警＋催辦＋結案被擋（量最小、價值最高）。
3. 觀察一個月 LINE 用量條，再決定要不要上第二、三批，以及要不要升級方案。

**需要使用者／PM 裁示的事**：見第 7 節（4 題）。

---

## 1. 現況盤點

### 1.1 LINE 通道現在怎麼運作（程式事實）

| 項目 | 位置 | 事實 |
|---|---|---|
| 已接線事件 | `backend/helpers/line_notify.py:301` `WIRED_EVENTS` | 只有 `approval_review_edit`、`warranty_expiry`；不在清單內的事件設定頁不開放勾選（`set_event` 會 `ValueError`，:314） |
| 唯一的呼叫入口 | `backend/helpers/email_notify.py:1011`（`_line()` → `_ln.notify_users`） | 只有 `send_registered`（:980）會呼叫 LINE |
| 依附 Email 的原因 | `email_notify.py:1000` | `if not to:`（沒有任何 Email 收件人）就 `return False`，**在 `_line()` 之前就結束**；LINE 收件人是從「最後有寄信的信箱」反推帳號（`_resolved.pairs`，:225–:251） |
| 重試時的行為 | `email_notify.py:1021–1028` | `wait=True` 的呼叫端（每日檢查）：只有信件「可以寫已通知記號」時才發 LINE，避免重試時重複推播 |
| 開發機保護 | `line_notify.py:215` `_machine_may_send` | 開發機標記同時擋信件與 LINE（維持） |
| 內容規則 | `line_notify.py` 檔頭 ⑤ | 不帶金額；連結預設關（`LINK_PAGES` 白名單） |
| 訊息長度 | `line_notify.py:50` | `MAX_TEXT=1000` |
| T80 新增 | T80 分支 `line_notify.py:283–345`、`line_recipients.py` | 事件可設「允許角色」`event_roles`、個人可退訂 `line_prefs`；收件人＝信件收件人 ∩ 允許角色 ∩ 未退訂 ∩ 已綁定 |
| T80 額度告警 | T80 分支 `helpers/line_quota.py`、`system_checks.py:808` `_check_line_quota` | 以 LINE 回傳的 `totalUsage` 為準；門檻預設 80／100%，同門檻同月只寄一封（Email 給最高管理者）；**100% 只告警，不自動停推播**（PM 裁示 D6） |

### 1.2 能發 LINE 的「入口」其實只佔一半

信件類型登記表合計 **120 種**（核心 `mail_types.py` 64 種 ＋ 各模組 56 種；分類：簽核 82、業務 27、系統技術 11）。寄出方式分兩種：

| 寄法 | 數量 | 能不能發 LINE |
|---|---|---|
| 走 `send_registered`（新寫法：費用單據、材料申請、承攬商派發、勞報單、獎金、付款日提醒、發票上傳、保固、審核中編輯 …） | 約 50 個呼叫點（`modules/case/*_notify.py`、`modules/payroll/*_notify.py`、`modules/subcontract/dispatch_notify.py`、`payable_reminders.py`） | **加進 `WIRED_EVENTS` 就能發**（每個事件約 1 行＋測試） |
| 直接 `_async_send`（舊寫法：報價／出貨／請款／開票／承攬匯款的簽核、工作事項、案件期限、結案、備份／磁碟／憑證告警 …） | `email_notify.py` 內約 40 個 `notify_*` 函式（例：`notify_approval_request` :580） | **沒有入口**，必須改寫或加一個共用掛鉤 |

### 1.3 站內通知（小鈴鐺）

`helpers/audit.py:168` `_notify()` 另有約 30 種站內通知類型（`*_approval_request`、`*_returned`、`extra_expense_*`、`planned_pay_date`、`recyclebin_daily` …）。它與信件不是同一份清單；**本提案不建議直接把站內通知鏡像到 LINE**（沒有收件人解析規則、沒有退訂機制），而是以信件類型為單位，一個事件對應一個信件類型 key，這樣收件人／退訂／覆寫規則才只有一個來源。

### 1.4 哪些既有事件適合也發 LINE（評等）

評等：★★★＝建議上；★★＝可上、看額度；★＝不建議（量大或價值低）；✕＝政策排除。

| 事件（mail key） | 預設收件 | 評等 | 備註 |
|---|---|---|---|
| `backup_error`／`backup_stale`／`disk_space_low`／`cert_expiry`／`heartbeat_stale`（T80） | 最高管理者 | ★★★ | 系統技術類，信件端已「鎖住不可關」（`notify_matrix.MAIL_OFF_LOCKED`） |
| `company_setup_alert` | 最高管理者 | ★★ | 偶發 |
| `line_quota_warning`（T80） | 最高管理者 | ✕ | **刻意不發 LINE**：LINE 額度告警用 LINE 發會耗額度、額度滿時發不出去；維持 Email |
| `approval_reminder`（簽核逾期催辦） | 當層簽核人 | ★★★ | 卡住的單才發，量小 |
| `*_submitted`／`*_next_tier`（輪到我簽核，約 10 種單據） | 當層簽核人 | ★★★ 價值高但量大 | 見第 3 節，最大宗 |
| `*_returned`（被退回） | 申請人 | ★★★ | 量小、要立刻處理 |
| `*_approved`（核准完成） | 申請人 | ★ | 量大、不緊急，預設不開 |
| `expense_form_payout_pending`（出納待撥款） | 出納 | ★★★ | 動作型待辦 |
| `payable_due_today`／`payable_due_overdue`（付款日當天／逾期） | 財務 | ★★★ | 建議做「每日彙整」；`payable_due_soon`（3 天前）★ |
| `case_close_blocked`（結案被擋下） | 待處理承辦＋最高管理者 | ★★★ | 量小 |
| `case_invoice_uploaded`（發票已上傳） | 財務 | ★★ | |
| `case_stage_deadline`／`range_task_deadline`／`case_project_overdue` | 負責人／主管 | ★★ | 量中 |
| `dev_case_assigned`／`dev_case_reply_overdue`／`dev_log_directive` | 被指派人 | ★★ | 業務開發線 |
| `daily_task_*`（工作事項指派／逾期／編輯） | 負責人 | ★ | 量大（個人事項），不建議 |
| `tender_found`（新標案） | 管理員 | ★ | 每日掃描、筆數不定；若要上只能彙整 |
| `module_activity`（模組新增與異動） | 管理員 | ✕ | 全站每個新增都寄，量爆炸 |
| `monthly_report`／`case_closing_report`（帶附件） | — | ✕ | LINE 文字訊息無附件 |
| `bonus_*`／`payslip_*`（獎金／勞報單） | — | ✕（現階段） | **PM 2026-11-11 裁示**：付款／薪資／獎金類先不開放，要開放須逐類確認內容不含金額與個資（`line_notify.py:299`） |

---

## 2. 建議新增的事件（逐一寫清楚）

> 觸發點行號為 `train/t79-int` @ `333ee073b`；T80 專有的標 `[T80]`。
> 「每月則數」＝每月發生次數 × 平均收件人數，**是依假設的估算**（假設見 3.1）。
> 事件 key 欄：現有登記的沿用原 key；**〔新〕＝要新登記信件類型**（同時也會有 Email，兩邊由同一個類型控制收件人）。
> 「獨立通道」＝LINE 不依附 Email（見第 5 節）；所有事件最終都應走獨立通道，此欄標示「必須」的是不獨立就失去意義的。

### 2.1 系統出事（系統技術類，預設只給最高管理者）

| 事件 key | 觸發點 | 預設收件 | 每月則數 | 備註 |
|---|---|---|---|---|
| `backup_error` | `archive.py:496` `_send_backup_error_email`（:550） | 最高管理者 | ~2 | 獨立通道**必須**（Email 常是出事的同一台機器寄的） |
| `backup_stale` | `helpers/system_checks.py:291`（`_check_backup_freshness` :215） | 最高管理者 | ~2 | 每日檢查、同日一次 |
| `heartbeat_stale` `[T80]` | T80 分支 `system_checks.py:327` `_check_heartbeat_health` | 最高管理者 | ~2 | 正式機心跳壞了兩個月沒人知道的那件事 |
| `disk_space_low` | `system_checks.py:380`／`:446`（`_check_disk_space` :344） | 最高管理者 | ~2 | |
| `cert_expiry` | `system_checks.py:154`（`_check_cert_expiry` :125） | 最高管理者 | ~2 | 到期前分階段提醒 |
| **小計** | | | **≈10** | |

### 2.2 等你處理的單子

| 事件 key | 觸發點 | 預設收件 | 每月則數 | 備註 |
|---|---|---|---|---|
| `approval_reminder`（簽核逾期催辦） | `system_checks.py:683` `notify_approval_reminder`（`_check_approval_reminders` :590） | 當層簽核人 | ~13 | 只有逾期才發 |
| `approval_request`／`next_tier`（報價單） | `modules/case/api/quotations.py:640`／`:647`／`:660`／`:5652` | 當層簽核人 | 與下列合計 ~130 | 舊寫法，需改（第 5 節） |
| `shipping_submitted`（出貨單） | `modules/supply/api/shipping_notes.py:465` | 當層簽核人 | 同上 | 舊寫法 |
| `payment_request_submitted`（請款單） | `modules/arap/api/payment_requests.py:655` | 當層簽核人 | 同上 | 舊寫法 |
| `invoice_voucher_submitted`（開票憑據） | `modules/arap/api/invoice_vouchers.py:560` | 當層簽核人 | 同上 | 舊寫法 |
| `contractor_voucher_submitted`（承攬匯款） | `modules/subcontract/api/contractor_vouchers.py:691` | 當層簽核人 | 同上 | 舊寫法 |
| `expense_form_submitted`／`next_tier`、`material_order_*`／`material_payment_*`／`material_change_*`、`dispatch_*`（待簽核與下一層） | `modules/case/expense_notify.py:92/96`、`material_notify.py:88–197`、`subcontract/dispatch_notify.py:50–79` | 當層簽核人 | 約 50（上列 130 的一部分） | **新寫法：加進 `WIRED_EVENTS` 即可** |
| `returned`（各單據被退回） | `quotations.py:5750` 等 | 申請人 | ~8 | 約 10% 的單據會被退 |
| `expense_form_payout_pending`（出納待撥款） | `modules/case/expense_notify.py:108` | 出納（財務角色） | ~30 | 新寫法，零改碼 |
| `payable_due_today`／`payable_due_overdue` | `modules/case/payable_reminders.py:84/87`（排程 `modules/case/case_deadlines.py:403`）；`modules/subcontract/payable_due.py:94/97` | 財務 | ~30（逐筆發可到 ~50） | 新寫法；**建議做每日彙整** |
| `approved`（核准完成，給申請人） | `quotations.py:5483`、`payment_requests.py:752`、`shipping_notes.py:607` 等 | 申請人 | ~50 | 預設不開 |

### 2.3 該注意的狀況

| 事件 key | 觸發點 | 預設收件 | 每月則數 | 備註 |
|---|---|---|---|---|
| `case_close_blocked`（結案被擋） | `quotations.py:3160`（函式 `email_notify.py:1786`） | 待處理承辦＋最高管理者 | ~10 | 這就是現有「缺單據／款項未收齊／簽核未完成」的防呆通知；舊寫法 |
| `receivable_overdue`〔新〕應收逾期 | **新每日／每週檢查**：判斷邏輯已存在於 `modules/arap/api/cashier.py:442` `_receivable_queue`（逾期＝預定收款日＋寬限天數 `receivable_grace_days()`），但**目前沒有任何通知**；排程可掛在 `case_deadlines.py:403` 旁 | 財務＋最高管理者（業務負責人看是否納入，見第 7 節 #3） | ~14（每週彙整一則） | 逐筆發會爆量，只做彙整 |
| `material_received`〔新〕採購（材料）到貨 | `modules/case/api/material_approvals.py:308`（`/receive` 端點，呼叫 `material_approval.record_receipt` :396） | 該案業務負責人＋申請人 | ~22 | 目前到貨確認完全不通知；注意按「確認到貨」的通常就是本人，收件應排除操作者本人 |
| `stock_below_safety`〔新〕庫存低於安全量 | 判斷邏輯 `modules/supply/api/inventory.py:57–85`（`safety_stock`、`_stock_level` 紅燈）；**只有查詢頁會算，沒有任何通知**；需在出貨／領料扣庫存後或每日檢查加「由綠／黃轉紅」的狀態轉移判斷 | 管理員（倉管） | ~10（只在「跨過紅線」那一刻發，不是每天） | 沒有「採購」專用角色，預設 admin |
| `case_stage_deadline`（案件階段到期） | `modules/case/case_deadlines.py:103` | 負責人（主管版 :128） | ~45 | 舊寫法，量中；第三批 |
| `settlement_finalized`／案件狀態變更 | `modules/case/api/settlement_api.py:165` 等 | 管理員 | ~20 | 「案件狀態變更」目前沒有統一事件，只有精算完結／結案／成案各自零散；要做需先定義哪幾個狀態值得通知，建議等第二批看額度 |
| 缺單據（主動偵測）〔暫緩〕 | 無現成偵測規則；`case_close_blocked` 只在「按結案」時才檢查 | — | — | 要先由使用者定義「哪些算缺」（發票？驗收單？），建議併入 `case_close_blocked` 的規則再擴充 |

### 2.4 不建議做的

`daily_task_*`、`module_activity`、`tender_found`（逐筆）、`monthly_report`、獎金／薪資／勞報單、`line_quota_warning`（理由見 1.4）。

---

### 2.5 各事件的「業務收件人規則」（給 hichan-3 的共用解析層當規格）

> **前提（使用者已裁示，經 MOTRIX-Platform 轉達）：所有 LINE 事件都獨立於 Email；hichan-3 抽出共用的「事件 → 業務收件人」解析層。** 本表就是各事件要餵給那一層的規則。
> 寫法：**①事件收件人**＝觸發點當下算得出的人（呼叫端給帳號）；**②群組**＝`mail_types` 登記的預設群組（`none`／`admins`／`superadmins`／`finance`）；**③排除**；**④沒人時**。
> 共通：所有結果都會再套 公司事件開關 → `event_roles` → `line_prefs` → 已綁定 → 在職（停用帳號排除）。超級管理員在「信件與通知收件設定」的覆寫（`default`／`superadmin_only`／`custom`）**同樣適用於 LINE**（收件人只有一個來源）。

| 事件 | ①事件收件人（來源） | ②群組 | ③排除 | ④沒人時 |
|---|---|---|---|---|
| 系統告警 5 種（`backup_error`／`backup_stale`／`heartbeat_stale`／`disk_space_low`／`cert_expiry`） | 無 | `superadmins`（系統技術類登記時強制只給最高管理者，`mail_types.register` 會擋其他值） | 無 | 沒有任何最高管理者綁定 LINE ⇒ 只記 log（Email 仍寄）；**不要退而求其次改發管理員**（保持現行信件規則） |
| `approval_reminder` | 逾期那一層的簽核人（`system_checks.py:683` 呼叫端已算出） | `superadmins` | 無 | 同上 |
| 待簽核／下一層（各單據 `*_submitted`／`*_next_tier`） | 當層簽核人（含代理人；`bonus` 已有此規則）。報價單：`quotations.py:640/647` 的 `_appr_names`；其他單據：`first_tier_usernames` 等 | `none` | 無 | 簽核層沒人 ⇒ 不發（流程本身會擋） |
| `*_returned`（被退回） | 申請人（`requestedBy`） | `none` | 無 | 申請人沒綁 LINE ⇒ 不發 |
| `*_approved`（核准完成） | 申請人 | 報價單 `approved` 登記為 `admins`，**LINE 建議只給申請人**（用 `event_roles` 限縮，或在字典標 `to_group=False`） | 操作者本人 | 同上 |
| `expense_form_payout_pending` | 出納（`expense_notify.py:108` 已給） | `none` | 無 | 沒綁 ⇒ 不發 |
| `payable_due_today`／`payable_due_overdue` | 無 | `finance`（財務角色＋最高管理者） | 無 | 彙整成每人一則 |
| `case_close_blocked` | 尚未完成前置條件的承辦／簽核人（`quotations.py:3160` 的 `pending_usernames`，可能為空） | `superadmins`（現行信件就是「承辦＋最高管理者」） | 無 | 承辦為空 ⇒ 只給最高管理者 |
| `receivable_overdue`〔新〕 | **提案：不含業務**（需使用者裁示，第 7 節 #3） | `finance` | 無 | 每週彙整 |
| `material_received`〔新〕 | 該案業務負責人（`case_access.case_owner_username`，與保固同一個取法）＋材料申請人 | `none` | **操作「確認到貨」的本人** | 都沒綁 ⇒ 不發 |
| `stock_below_safety`〔新〕 | 無 | `admins`（沒有「倉管」角色；若之後新增角色再改） | 無 | 只在「綠／黃→紅」轉換時發一次，回升後再跌破才再發 |
| `case_stage_deadline` | 階段負責人（`case_deadlines.py:103`）；主管版另一個事件（:128，只給部門主管） | 現行登記 `admins`（**LINE 建議 `none`**，負責人＋主管就夠，不要打給全體管理員） | 無 | |
| 既有 `warranty_expiry` | 案件業務（FK 解出的帳號） | `admins` | 無 | 改獨立後沒 Email 也會收到 |
| 既有 `approval_review_edit` | 送審人 | `superadmins` | 編輯者本人 | 同上 |

**對解析層的要求（請 hichan-3 確認）**
1. 解析層吃 `(event_key, 事件收件人帳號清單)`，自己展開群組、套覆寫，回「帳號清單」；不回信箱。
2. 要能「**這個事件在 LINE 的群組與信件不同**」：例如 `approved`、`case_stage_deadline` 的信件群組是 `admins`，LINE 想縮成只給事件收件人。建議在事件登記字典（4.2）放 `line_group: None | "inherit" | <group>`，預設 `"inherit"`（與信件相同，維持行為不變）。
3. 要能排除「操作者本人」（`exclude=[actor]`），這是現有信件沒有的需求（到貨確認、核准完成）。
4. 彙整型事件（`digest`）要能在「發送當下」才解析收件人（每日 08:00 的人可能與事件發生那天不同）。

## 3. 免費額度估算

### 3.1 假設（請以正式機實際值校準）

- LINE 計費：推播給 N 人＝N 則（`multicast` 也是每位收件人各算一則；見 `line_quota.py` 檔頭與 `LINE-NOTIFY-SETUP-GUIDE.md`）。
- 公司約 **20 人**，其中約 **10 人**綁 LINE；每月送審約 **50 張**單據（報價／請款／出貨／開票／承攬／費用／材料／派發合計），平均 **2 層**，每層 **1.3 位**簽核人，約 **10%** 被退回。
- 本機是開發庫（`motrix_erp.db` 只有 1 位使用者、所有業務表 0 筆），**沒有可推算每月實際量的資料**。校準方法：到正式機查近 3 個月 `audit_log` 的送審動作數、案件數、付款申請數（唯讀 COUNT 即可，不需新功能）。
- 免費額度：**200 則／月**（網路資料，未經官方確認；2026 年 11 月方案可能調整 — **PM 請到 LINE Official Account Manager 確認**）。系統端不必寫死：`line_notify.quota()`（:445／T80 分支 :485）讀的是 LINE 回傳的真實上限。

### 3.2 每月則數與累計

| 批次 | 內容 | 本批則數 | 累計 | 佔 200 |
|---|---|---|---|---|
| 現況 | `approval_review_edit`（~8）＋`warranty_expiry`（~18） | 26 | 26 | 13% |
| 第一批 | 系統告警（10）＋簽核催辦（13）＋結案被擋（10） | 33 | 59 | 30% |
| 第二批 | 付款到期彙整（30）＋出納待撥款（30）＋新寫法的待簽核（50） | 110 | 169 | **85%（超過 80% 告警線）** |
| 第三批 | 應收逾期（14）＋材料到貨（22）＋庫存跨紅線（10）＋退回（8） | 54 | 223 | **112%（超過）** |
| 第四批 | 舊寫法的待簽核（80）＋案件階段到期（45）＋案件狀態（20） | 145 | 368 | 184% |

**結論**
- 免費額度撐得住「現況＋第一批」，第二批做完就在 80% 告警線附近，**第三批起會超過**。
- 收件人數是線性放大的：綁 LINE 的人從 10 變 20，上表所有「待簽核類」數字幾乎翻倍。
- T80 的告警能看到「用了多少」，但**不能阻止超額**（100% 只告警）。額度滿了之後，連系統告警都送不出去——這是整個擴充最大的風險，所以第 4 節加了「重要程度」機制。

### 3.3 省額度的做法（成本由低到高）

1. **每日彙整**（付款到期、應收逾期、庫存）：同一人同一天同一類只發一則，內文列前 N 筆＋「共 N 筆」。付款提醒從 ~50 降到 ≤ 22 工作日 × 2 人。
2. **只發動作型事件**：預設不開「核准完成」「3 天前預告」這類資訊型。
3. **依角色限縮**：T80 已有 `event_roles`，例如「待簽核」只給簽核人角色。
4. **重要程度分級**（第 4 節）：用量 ≥ 90% 時次要事件自動暫停。
5. **升級方案**（價格待確認）。

---

## 4. 共用架構建議

### 4.0 與 hichan-3 的對齊（2026-11-12 收到的回覆，**尚未提交，設計可能再改**）

hichan-3 的 `auth_lockout` 獨立通道（分支 `feat/auth-lockout-alert`，工作樹 `D:\Claude-pm\hichan3-login-alert`）：
1. **沒有新的通用函式**，沿用 `line_notify.notify_users(event_key, usernames, title, rows, reason=, link=)`，**不經過 `send_registered`**。
2. 新增 `email_notify.group_usernames(event_key)`：用 T80 的「信件收件人設定」（預設群組／只給最高管理者／自訂帳號＋角色）解出收件**帳號**，**不需要 Email**；`helpers/auth_alert._deliver` 負責把兩者接起來。
3. 事件 key 仍須在 `WIRED_EVENTS` 且在 `mail_types` 登記（收件人設定存在那裡）；新增 `line_notify.INDEPENDENT_EVENTS = ("auth_lockout",)`，`send_registered` 對這些 key 跳過附帶的 LINE 推播，避免重複。
4. 仍套用公司層事件開關（預設關）、`line_recipients.filter_usernames`（`event_roles`＋`line_prefs`）、`ids_for`（已綁定）、`push_async` → `line_quota.after_push`。
5. `approval_review_edit`／`warranty_expiry` 不動（仍依附 Email）。

**我的提案完全建立在這個形狀上**：不另開第二套收件人解析，所有事件共用「`group_usernames` ＋ `notify_users`」。

### 4.1 建議的分層

```
事件觸發點（各模組）
   │  usernames（事件收件人）＋ to_group（登記群組）
   ▼
line_notify.notify_event(event_key, usernames=…, to_group=…, title, rows, …)   ← 本提案新增的「單一入口」
   ├─ 收件人：usernames ∪ email_notify.group_usernames(event_key)   （hichan-3 已有，不需 Email）
   ├─ 過濾：公司開關 → event_roles → line_prefs → ids_for（已綁定）   （T80 已有，不變）
   ├─ 重要程度／額度保留（新）
   ├─ 彙整（新，選用）
   └─ push_async → line_quota.after_push（T80 已有）
```
- `send_registered` 內附帶的 LINE（:1011）改成呼叫同一個入口；`INDEPENDENT_EVENTS` 這個「例外清單」可以消失（全部都獨立後就不需要）。
- 舊寫法的 `notify_*`（~40 個）在原本找收件人（`_lookup_emails(usernames, key)`）的同一處，多一行呼叫 `notify_event(...)`；**不必**把它們全部改成 `send_registered`（那是 Email 內容的重構，風險與本案無關）。

### 4.2 事件登記表

現在 `WIRED_EVENTS` 只是一個 tuple。建議改成字典，**每個事件帶屬性**（仍保持「沒接線就不開放勾選」的現行規則）：

```python
LINE_EVENTS = {
  "backup_error":      {"priority": "critical", "digest": False},
  "approval_reminder": {"priority": "normal",   "digest": False},
  "payable_due_today": {"priority": "normal",   "digest": "daily"},
  "approved":          {"priority": "low",      "digest": False},
  ...
}
WIRED_EVENTS = tuple(LINE_EVENTS)          # 相容舊用法
```
- `priority`：`critical`（系統告警；永不因額度暫停）／`normal`／`low`（用量 ≥ 90% 自動暫停，並記 log）。
- 依 `line_quota` 已有的 5 分鐘記憶體快取讀用量（`CACHE_SECONDS=300`），**不增加 LINE API 呼叫**。
- 與 hichan-3 的 `INDEPENDENT_EVENTS` 並存期間可共用同一個字典，等全部獨立後移除。

### 4.3 每日彙整

`digest: "daily"` 的事件：觸發點不直接推播，而是寫入記憶體／設定的待發清單；每日 08:00（`system_checks.run_all` 內新增一個 `_flush_line_digest`）把「同一人、同一事件」合成一則，格式例如：

```
【MOTRIX】付款日到期提醒（共 5 筆）
・案件 A／廠商甲
・案件 B／廠商乙
…另外 2 筆，請登入系統查看
```
不放金額（既有規則 ⑤）。

### 4.4 重複推播與「已通知」記號

`send_registered(wait=True)` 現在讓 LINE 跟著信件的成敗走（:1021–1028），這是依附 Email 的另一面。改成獨立通道後要處理：
- 每日檢查型（`wait=True`）的事件，Email 暫時失敗會隔天重試；若 LINE 在每次重試都發，會**天天重複推播同一件事**。
- 建議：LINE 自己帶「已推播」記號（比照現有 `*_last_notified` 旗標慣例，key＝事件＋對象＋日期），**LINE 只在記號不存在時發，發出（無論成敗結果非 transient）就寫記號**，與 Email 的重試脫鉤。
- 這是第 5 節「全面獨立」最需要審慎測試的地方（也是 hichan-3 的 `auth_lockout` 因為「每次鎖定都是新事件」而不會碰到的）。

### 4.5 其他共用規則（維持現行，不改）

- 內容不帶金額、連結預設關（`include_links`＋`LINK_PAGES` 白名單；若新增事件要放連結，要同步擴 Cloudflare Tunnel ingress，需 PM／正式機確認）。
- 開發機標記同時擋 LINE（`_machine_may_send`）。
- 預設全部**關**，由最高管理者在通知設定頁逐項勾選；可另提供「套用建議組合」按鈕（只是一次勾多項，不改預設）。
- 新事件要過 `test_mail_registry`（`send_registered` 的 key 必須字面常數且已登記）與 `test_notify_matrix`；`WIRED_EVENTS` 變動要補 `tests/platform/test_line_notify_t79.py` 的清單題。

---

## 5. 所有 LINE 事件改成獨立通道：影響面與注意事項

> **使用者已裁示（經 MOTRIX-Platform 轉達 2026-11-12）：所有 LINE 事件都不依附 Email，由 hichan-3 實作，並抽出共用的「事件 → 業務收件人」解析層。** 本節不再評估「要不要」，只列影響面與實作時要注意的點，供 hichan-3 與後續批次參考。

做法比想像中小，因為 hichan-3 已經做掉最難的兩件事（不需 Email 解出收件帳號、避免雙推）。影響面如下。

### 5.1 好處
- 修掉「沒 Email／退訂 Email／信件類型被關掉 ⇒ LINE 也收不到」（PM 補充題 3 的缺口）。
- 系統告警這類「Email 可能正是壞掉的那條線」的事件才真的有意義。
- `INDEPENDENT_EVENTS` 例外清單與「兩條路徑各一份判斷」可以收成一條。

### 5.2 獨立後的語意（我的理解；與 hichan-3 的實作不一致處請以其為準並回報我更正本表）
| 情況 | 獨立後的行為 | 說明 |
|---|---|---|
| 個人退訂了**信件** | LINE 照發（LINE 有自己的 `line_prefs` 退訂） | 兩邊各自退訂；設定頁／手冊要寫清楚，否則使用者會以為退訂信件＝不再收 LINE |
| 公司把某信件類型「關閉」（`mail_recipient_overrides[key].off`） | 以 LINE 自己的事件開關為準，信件關不影響 LINE | |
| 超級管理員覆寫收件人（`superadmin_only`／`custom`） | 沿用同一份覆寫解出收件帳號 | 收件人只有一個來源 |
| 沒有 Email 的人 | 只要有綁 LINE 就收得到 | 這正是目的 |

### 5.3 影響面（要動的地方）
1. `email_notify.send_registered`（:980–1030）：LINE 區塊改呼叫單一入口，收件人不再由 `_resolved.pairs` 反推（那套「信箱→帳號」收集器，:225–:251，在 LINE 這邊就不再需要）。**約 50 個呼叫點不用改**，因為它們都經過 `send_registered`。
2. 舊寫法 `notify_*`（~40 個）：各加一行（只做要上 LINE 的那些）。
3. `line_notify.notify_users`（:409／T80 :446）：收件人解析與過濾合併進單一入口（hichan-3 已用同一函式）。
4. 通知設定頁：事件清單文案、「依附 Email」的說明要拿掉（`frontend/pages/notification-settings.html`）。
5. 測試：`tests/platform/test_line_notify_t79.py`、`modules/case/tests/test_line_review_edit_2026_11_11.py`（既有兩事件的行為會變：沒 Email 也發）；新增「Email 全失敗／無 Email／信件被關，LINE 仍發」「重試不重複推播」題。
6. 與 T80 的相容：`line_recipients`（角色＋個人退訂）、`line_quota`（`after_push`）**完全不用動**，因為它們都掛在 `notify_users`／`push_async` 之後。

### 5.4 風險
- 收件人規模擴大：過去「沒 Email 的人收不到」等於變相限縮，獨立後綁了 LINE 的每個人都會收到，則數會增加（第 3 節已用「綁 LINE 的人」算，不是用 Email 人數）。
- `wait=True` 重複推播（4.4）要用自己的記號擋。
- 既有兩事件行為變更要在更新步驟檔寫明（給正式機管理員看的白話：「之後沒有 Email 的同仁，只要綁了 LINE 也會收到保固與審核編輯通知」）。

---

## 6. 建議實作順序

| 批次 | 內容 | 規模 | 驗收重點 |
|---|---|---|---|
| **0 共用底層** | 單一入口 `notify_event`；事件登記字典（priority／digest）；`send_registered` 的 LINE 區塊改走單一入口並獨立於 Email；`line_quota` 讀取用量做「次要事件 90% 暫停」；4.4 的已推播記號；與 hichan-3 合併（等其 `auth_lockout` 提交後再對一次 file:line） | M（不新增事件） | 沒 Email 也發；重試不重複；額度 90% 時 low 事件被擋、critical 照發 |
| **1** | 系統告警 5 種（含 T80 的 `heartbeat_stale`）＋`approval_reminder`＋`case_close_blocked` | S–M（系統告警與結案被擋是舊寫法，要各加一行；`archive.py` 備份錯誤要新增呼叫） | 每月約 +33 則；觀察 T80 用量條一個月 |
| **2** | 新寫法零改碼的：付款到期（彙整）、出納待撥款、費用／材料／派發的待簽核與下一層、`case_invoice_uploaded` | S（加 `WIRED_EVENTS`／字典＋彙整） | 累計 ≈170，需 PM 確認方案 |
| **3** | 〔新〕應收逾期（每週彙整）、材料到貨、庫存跨紅線；各類被退回 | M（3 個新信件類型＋新每日檢查／新觸發點） | 新信件類型要同步登記（Email 與 LINE 同一類型） |
| **4** | 舊寫法的報價／出貨／請款／開票／承攬匯款待簽核、案件階段到期、案件狀態變更 | M–L（量大，視額度決定） | 先看 1–3 批的真實用量再決定 |

順序理由：先做底層（否則每批都要重做獨立化）；第 1 批量最小價值最高；第 2 批改碼最少；第 4 批量最大、放最後看額度。

---

## 7. 需要使用者／PM 裁示（白話）

1. **LINE 方案**：是否接受「免費 200 則夠用就好，超過再考慮升級」？還是先確認方案與價格？（我查到的資料互相矛盾，須以 LINE 後台為準。）
2. **額度保留**：同意「用量 ≥ 90% 時次要事件自動暫停、系統告警照發」嗎？門檻 90% 要不要改？
3. **應收逾期**：除了財務與最高管理者，要不要也通知該案業務負責人？（要的話，每月則數會多一倍以上。）
4. **獎金／薪資／勞報單**：維持不開（現有裁示），還是之後逐類確認內容後開放？

> **〔2026-11-12 使用者裁示：四題全部照建議〕** ① 先用免費額度，方案與價格由使用者到 LINE 後台確認，超過再升級；② 用量 ≥ 90% 時次要事件自動暫停，critical 照發；③ 應收逾期只通知財務＋最高管理者，不通知業務負責人；④ 獎金、薪資、勞報單維持不開。
>
> 已定案、不再詢問：LINE 全面獨立於 Email（使用者已裁示，hichan-3 實作）。個人退訂信件後 LINE 是否照發，我的理解是「照發，LINE 另有自己的退訂」，如與 hichan-3 實作不同請以實作為準。

---

## 8. 附帶改善（PM 補充＋調查中發現）

### 8.1 PM 轉來（hichan-7 的手冊找到的缺口）
1. **最高管理者替別人解除 LINE 綁定只有 API**（`DELETE /api/line/binding/{username}`），沒有前端按鈕。換手機、離職時管理者無處可按。建議在「使用者管理」每位使用者列加「解除 LINE 綁定」按鈕（僅最高管理者可見，已綁定才顯示，按下前確認）。
2. **用語不一致**：通知設定頁文案寫「帳號安全」頁，但畫面上實際名稱是「修改密碼」（`frontend/pages/change-password.html`）。建議統一文案（改文案為「修改密碼」頁，或把頁面標題改成帳號安全；需使用者選一個名稱）。
3. **LINE 依附 Email**：使用者已裁示全面改獨立通道（hichan-3 實作）；影響面與注意事項見第 5 節，各事件的業務收件人規則見 2.5。

### 8.2 調查中發現
4. **舊寫法 `notify_*` 完全沒有 LINE 入口**（1.2）：設定頁看起來只有兩個事件可勾，使用者容易以為「LINE 就是這樣」；本提案的底層批次解決。
5. **`notify_matrix` 的 `MAIL_OFF_LOCKED`（信件鎖住不可關）只管信件**：系統告警 LINE 的事件開關沒有對應的「鎖」。若把系統告警做成「重要程度 critical」，建議事件開關在設定頁上對 critical 類型加提示（「關閉後系統出事您可能收不到通知」），比照信件端的確認警告。
6. **綁定紀錄與 Email 是兩份資料**：員工離職停用帳號時，`line_links` 要一併清（現行「刪除帳號時會一併解除」，但「停用」是否解除，我只看了設定文字、**沒有逐行驗證**，建議第 0 批順手確認）。
7. **額度告警目前只寄 Email 給最高管理者**：額度達 100% 時，若同一位最高管理者只看 LINE，就看不到。可考慮額度告警固定走 Email（已是這樣，維持）＋ 在設定頁用量條顯眼處提示；**不要**改成發 LINE。

---

## 9. 附錄：事實來源索引

- LINE 通道：`backend/helpers/line_notify.py`（`WIRED_EVENTS` :301、`notify_users` :409、`quota` :445、`_machine_may_send` :215）
- 信件寄送與 LINE 入口：`backend/helpers/email_notify.py`（`send_registered` :980、`if not to` :1000、`_line()` :1011、舊寫法範例 `notify_approval_request` :580、`notify_case_close_blocked` :1786、`notify_backup_stale` :2131）
- 信件類型登記：`backend/helpers/mail_types.py`（核心 64 種）、各模組 `*_notify.py`（56 種）；`notify_matrix.py`（`MAIL_OFF_LOCKED`）
- 每日檢查：`backend/helpers/system_checks.py`（`run_all` 於 T80 分支 :819）；案件期限排程 `backend/modules/case/case_deadlines.py`
- T80（分支 `feat/auth-lockout-alert`／`wip/audit-t80-notify-17`）：`helpers/line_quota.py`、`helpers/line_recipients.py`、`system_checks.py:327`（心跳）、`:808`（額度備援）
- 免費額度與方案：網路搜尋資料互相矛盾（輕用量 200 則免費；另有舊制 500／4000／25000 的報導），**未經 LINE 官方確認**；以 LINE Official Account Manager 與系統用量條為準。
