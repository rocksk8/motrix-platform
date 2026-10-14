# S-X3 簽核事件通知用語：盤點與設計（T62，hichan-1f；基底 train/t60-int 9200a0b81）

狀態：設計＋盤點。第一個實作切片＝「報價單送審（approval_request）」，旗標關閉、關閉時輸出逐位元相同。本文件只讀原碼寫成（閘門期間不跑程式）。

## 1. 盤點

### 1.1 兩條通道，四種寫法

| 通道 | 位置 | 現況 |
|---|---|---|
| 信件 | `helpers/email_notify.py` 的 `notify_*`（共 ~60 個函式；簽核家族 33 個）＋ 各模組自己的 `*_notify.py`（accounting／case expense／material／payroll bonus／payslip／subcontract dispatch／tender_radar） | 一律走 `_build_html(mail_key, title, badge, color, rows, …, intro, button_text, impact, action)`；主旨走 `mail_types.subject(key, 事由)` → `【MOTRIX 系統通知】<分類>－<事由>`；影響／建議處理預設取 `mail_types` 登記表；收件人可由 `system_settings.mail_recipient_overrides` 改（已有，**文字沒有**） |
| 站內 | `helpers/audit._notify(username, type_, ref_id, ref_label, message, link)` | message 由**各呼叫端自己用 f-string 組**；寫入前一律經 `_mask_money(conn, username, text)`（沒有財務權限的收件人，金額樣式被換成「（金額略）」）；核准類（`_approved` 結尾）同 (type, ref_id, user) 只留一列 |
| 模組自帶 | `case_extra_expenses`（`XN.fire`／`XN.doc_ident`）、`subcontract/dispatch_notify`（`_dn.fire`）、`material_notify`、`accounting/notify.py` | 各自一套組字；站內訊息仍走 `_notify` |

結論：**文字散在 ~40 個信件函式與 ~50 個站內呼叫點；沒有任何一處可由管理者調整。** 收件人已可調（mail_recipient_overrides）、開關已可調（notify_matrix 的 off），所以缺的是「文字」這一塊。

### 1.2 簽核家族清單（file:line 以 9200a0b81 為準）

事件分四型：**送審（submitted）／輪到下一層（next_tier）／核准（approved）／退回或駁回（returned／rejected）**。文件類型 × 事件：

| 單據 | 送審 | 下一層 | 核准 | 退回／駁回 | 站內 type |
|---|---|---|---|---|---|
| 報價單 | email_notify:509 `notify_approval_request`；站內 quotations.py:587,608 | :525 `notify_next_tier`；站內 quotations.py:595 | :543 `notify_approved`（只有信，**沒有站內**） | :560 `notify_returned`；站內 quotations.py:5231（approval_returned）；拒絕結案 :5296（approval_rejected，**沒有信**） | approval_request／approval_returned／approval_rejected |
| 出貨單 | :578 | :595 | :615 | :632；shipping_notes.py:445,523,606,679,723 | shipping_approval_request／shipping_approved／shipping_returned |
| 承攬商匯款申請 | :650 | :668 | :688 | :707；contractor_vouchers.py:671,744,788,845,892 | contractor_voucher_approval_request／_approved／_returned |
| 開票申請憑據 | :727 | :745 | :765 | :784；invoice_vouchers.py:534,606,650,702,747 | invoice_voucher_* |
| 請款單 | :804 | :822 | :842 | :861；payment_requests.py:627,698,742,794,839 | payment_request_* |
| 完工單 | （僅站內）completion_notes.py:583 | :649 | :691 | :746,790（含「核准已被撤銷」） | completion_* |
| 自訂模組單據／模組定義 | :924／:975 | :936 | :950／:987 | :962／:999 | 見 custom_record／custom_def |
| 材料申請／變更／匯款、派工、額外支出 | 各自 `*_notify` 與 `_notify` | 同左 | 同左 | 同左 | material_*／dispatch_*／extra_expense_* |
| 獎金分潤／更正 | :1011,:1048 | — | :1030,:1062 | :1076 | payroll 自帶（**信中不含金額**，已是鎖定規則） |
| 傳票／帳務動作 | accounting/notify.py:51,95 | :62 | :73,:106 | :84,:117 | accounting 自帶 |
| 其他 | 催辦 :1090、重送審確認 :1142、轉簽 approval_queue.py:582,593、知會 audit.py:198 | | | | |

### 1.3 共用範本分組（可合併成「事件家族範本」）

同一個事件型、不同單據，信件與站內的**句型完全一致，只差：單據名稱、單號、對象名稱（客戶／廠商）、層數**。例：

- 送審：`<單據> <單號><標記>（<對象>）需要您簽核`（標記＝（解鎖改版）／（退回改版）／空）
- 下一層：`<單據> <單號><標記>（<對象>）輪到您簽核（第 N 層 / 共 M 層）`
- 核准：`<單據> <單號>（<對象>）已核准`（報價單信：已完成全部層級審核，正式生效）
- 退回：`<單據> <單號>（<對象>）已退回，請確認後重新送審：<備註>`

信件另有：標題、徽章字（待您審核／輪到您審核／全數通過／請修改後重新送審）、徽章色、引言（intro）、按鈕字、明細列（rows）。

家族＝4 個事件型 × 2 個通道＝**8 個範本槽**（再乘單據種類，但單據種類只是一個佔位符 `{單據}`）。

### 1.4 使用到的佔位符（現況）

`quote_no/note_no/voucher_no/request_no`（單號）、`customer/cname/vname`（對象）、`label`（標記）、`tier_no/total_tiers`、`approved_by`（最終審核人）、`note`（退回備註，使用者輸入）、`new_quote_no`、`requestedByDisplay`（知會）。**金額在簽核家族的訊息裡沒有直接放；但 `_mask_money` 仍存在，因為備註、事由、`summary` 可能含金額文字。**

### 1.5 收件人

送審／下一層＝該層待簽核人（找不到信箱就略過）；核准＝申請人＋`_admin_emails`（報價單）；退回＝申請人。收件人邏輯**不在本切片範圍**（已有 mail_recipient_overrides），範本不碰收件人。

## 2. 設計：每個事件家族一個受治理的範本

### 2.1 定義物

- 匯出代號沿用既有 `export_template` 機制？**否**。信件文字是文字、不是欄位清單，另開 kind `notify_template`（惰性登記，掛在 BP-3 同一個治理管線：草稿→預覽→放寬需第二位核准）。key＝`<家族>:<事件型>`，例如 `approval:submitted`。
- 範本本體（宣告式）：
  ```
  {"version":1,"event":"approval:submitted",
   "inapp":{"message":"…"},
   "mail":{"subject":"…","badge":"…","intro":"…","button":"…","impact":"…","action":"…"}}
  ```
  每一欄都是「**預設清單挑選**或**限制的純文字**」：
  - 預設清單＝今天寫死的字為第一項，再補 1～3 個同義說法（與 S-Q2 的 `CLAUSE_PRESETS` 同款）。
  - 純文字欄（intro／impact／action）：長度上限（subject≤60、intro≤120、其餘≤200）。

### 2.2 佔位符白名單（硬鎖，不可由範本擴充）

`{單據}` `{單號}` `{對象}` `{標記}` `{層}` `{總層}` `{最終審核人}` `{備註}` `{原單號}` `{修改版單號}`

- 每個事件型只允許它本來就有的子集（`submitted` 沒有 `{最終審核人}`）；範本用了子集外的佔位符 ⇒ 驗證失敗。
- **金額佔位符＝本切片不提供**（簽核家族今天就沒有）。日後若要加：只能是 `{金額}`，且**只在站內通道、經 `_mask_money` 逐收件人遮蔽後才展開**；信件通道一律不放（與獎金信「信中不含金額」同規則）。
- `{備註}` 是使用者輸入：展開後仍經 `_mask_money`、去控制字元、限長（200）、HTML 逸出（信件）。

### 2.3 文字禁令（沿用 BP-3）

無 HTML／標記字元（`< > & " '` 與全形同類）、無不可見字元（零寬／雙向控制）、無官方字眼骨架（狀態字、「已核准」類**僅限事件型本身的預設句**可含；自由文字欄不得含）、無網址、無 `{` `}` 以外的括號佔位語法。**狀態判斷永遠看事件型 key，不看文字**（鎖死項目：事件型、狀態 key、收件人邏輯、核准冪等規則）。

### 2.4 渲染

- 單一函式 `helpers/notify_templates.render(event, channel, ctx, recipient)`：未發布範本／旗標關 ⇒ **回 None**，呼叫端走原本的 f-string（逐位元相同）。
- 站內：展開 → `_mask_money(conn, 收件人, 文字)` → 既有 `_notify`（link、冪等規則不變）。
- 信件：展開 → 逸出 → 套進既有 `_build_html`（版型、樣式、按鈕連結、發送時間與來源**固定，不可改**）。
- 任一欄展開失敗（缺佔位符值）⇒ 整則退回預設文字並記一筆警告（寧可寄預設，也不寄壞掉的）。

### 2.5 預覽

`POST /api/notify-templates/{event}/preview`（唯讀）：輸入草稿範本＋**樣本單據**（用內建樣本＋可選真實單號，只取非金額欄位）＋**樣本收件人角色**（有／無財務權限）→ 回「目前 vs 草稿」兩欄文字、佔位符展開結果、被遮蔽的片段標示。管理者在發布前看得到「財務角色看到什麼／非財務看到什麼」。

### 2.6 治理

- 任何文字變更＝放寬（對外可見文字），沿用 `def_pipeline` comparator：新增或更換＝放寬、恢復預設＝收緊。
- 旗標 `builder_notify_templates.enabled`（預設關；同樣需 `builder_governance.enabled`）。關閉 ⇒ 沒有新路由行為差異、沒有額外請求、輸出逐位元相同。
- 編輯器重用 `export-editor.js` 的下拉模式（預設清單挑選）；純文字欄走設定中心既有的白話文案守門。

### 2.7 鎖死（不可設定）

事件型與 key、收件人選擇、核准冪等（同 type/ref/user 一列）、`_mask_money` 遮蔽、信件版型與「發送時間與來源」區段、資安／營運攸關信件（`MAIL_OFF_LOCKED`）、獎金類「信中不含金額」。

## 3. 第一個實作切片（本分支）

**報價單送審 `approval:submitted`（站內＋信件）。**

涵蓋：`quotations._build_approval_tiers_and_notify` 兩處站內 msg（:587/:608，第一層與無簽核層退回超管）＋ `email_notify.notify_approval_request`（主旨、徽章、引言、按鈕字）。
不涵蓋：輪到下一層（:595，第二切片，同家族不同槽）、核准、退回、其他單據。

實作清單：
1. `helpers/notify_templates.py`（L1）：事件登記（佔位符子集、預設句、預設清單）、`active()`、`render()`、驗證器；單位卡 `[公開介面]`。
2. `routers/def_pipeline.py` comparator：`notify_template` kind。
3. 兩個呼叫端各加一行 `render(...) or <原 f-string>`。
4. 預覽路由（唯讀、write-endpoint 稽核 EXEMPT 表登記）。
5. 測試：預設句逐位元等於今天（站內 msg、信件主旨／徽章／引言／按鈕）、旗標關／無範本 ⇒ 回 None、佔位符白名單／子集、禁令、金額遮蔽（有／無財務權限）、備註逸出、comparator、無 `**`、`page_file()`。
6. CHANGELOG（core、case、email 若有）。

## 4. 待 b4 裁示（僅此三項；其餘照上方預設）

1. 信件主旨前綴 `【MOTRIX 系統通知】<分類>－` 是否鎖死？預設：**鎖死**（郵件規則、收件匣過濾依賴它），範本只改「事由」。
2. 退回備註 `{備註}` 展開位置是否限於站內訊息尾端 `：{備註}`、信件的備註區塊？預設：**是**（不可放進主旨）。
3. 自訂模組單據的通知是否納入同一族？預設：**否**（模組作者自己有 `intro` 欄位，下一輪處理）。
