# 勘查 A：設定中心／通知信件／單據編號與欄位設定（唯讀；repo = D:\Claude-pm\hichan4-matrix\wt）

計數方法：python 匯入 `helpers.settings_registry`＋`helpers.settings_groups` 數 `_GROUPS`（登錄在匯入時完成，不連 DB、不開伺服器）；信件用 `mail_types.all_types()`；其餘讀碼／grep。
痛度、頻率皆為我的判斷。未驗項目標「未驗」。
元件：[矩陣] [勾選批次] [群組全開全關] [搜尋篩選] [預設組] [確認+6秒復原] [手機卡片]

## 0. 結論（含與既有盤點不同或新增的事實）
1. 設定中心實測 50 群組／183 欄。型別：選項型 89、int 46、str 34、float 11、純 bool 3。選項型中 69 欄只有 2 個選項（實為開關），故「開/關類」= 69+3 = 72 欄（39%）。
2. 「預設組」分頁存在（settings-center.html:137,286-302），但沒有任何欄位宣告 presets：`profiles()` 實跑回 `{}`。機制完成、內容為 0。
3. 全站沒有「6 秒復原」：設定中心只有「原因必填＋預覽＋版本還原」；mail-settings 勾了立即存，只有關信件時 window.confirm（mail-settings.html:235）。
4. 沒有獨立「單據編號」頁：規則散在費用類型、自訂模組建構器、設定中心 quote_defaults 一欄；全站保留字首 36 個（doc_type.py:39-43）。
5. 同資料兩處改：行事曆事件開關在 google-calendar-settings（19 核取＋1 儲存鈕）與 mail-settings「行事曆」欄（逐列立即存）；LINE 個人偏好在 my-account、管理端在 notification-settings。
6. mail-settings 實際 76 列 = 67 信件類型 + 9 僅行事曆（實跑 all_types()、calendar_only_codes）。既有盤點寫 42、程式註解寫「約 120」，都過時。

## 1. (a) 設定中心 settings-center.html + settings_registry.py / settings_groups.py

### 1.1 操作模式
| 項目 | 現況 | 證據 |
|---|---|---|
| 群組導覽 | 左欄 50 個群組按鈕；搜尋框只比對群組名稱與說明，不搜欄位 | settings-center.html:106-108, 392-395 |
| 欄位呈現 | 每欄一張卡：問句＋說明＋radio 或「開啟」核取；進階欄收在「顯示進階項目（N 項）」（共 33 欄進階） | :142-197 |
| 儲存 | 以「群組」為單位：改多欄 → 底部「已修改 N 項」→ 預覽 → 原因必填 →（紅色影響需勾「我已了解」）→「確認儲存」 | :310-329, 491 |
| 跨群組 | 有未存修改時不能切群組（須先存或放棄） | :397 |
| 風險欄位 | 12 欄 requires_pending：進「待生效」7 天，可撤銷 | 實跑 pending=12；:215-228 |
| 預設組 | 有預覽、原因必填、確認套用；但 0 個預設組 | :286-302 |
| 批次工具 | 無群組全開/全關；只有逐欄「還原預設」 | :178 |
點擊成本（估）：同群組改 8 個開關 = 8 點＋輸入原因＋存＋確認 ≈ 11 動作；分散在 8 個群組 ≈ 8×(點群組＋點開關＋輸原因＋存) ≈ 32 動作。

### 1.2 群組欄位數（實跑）
超過 10 欄的群組只有 3 個：
| 群組 | 欄位 | 組成 | 進階 | 備註 |
|---|---|---|---|---|
| download_name 下載檔名 | 21 | 選項6／str13／int2 | 16 | 13 欄是檔名樣板文字 |
| quote_alt 擇一方案 | 16 | 選項9／bool3／int2／str2 | 3 | 風險 money |
| external_login 外網登入防護 | 14 | 選項9／int3／str2 | 3 | 風險 security |
6~10 欄：retention 9（int9）、finance_cashier 8、builder_layout 8（全為 2 選開關）、completion_note 7（選項7）、profit_warning 7（float7）、builder_governance 6（全 2 選）、list_view 6、lodging_labels 6。
其餘 39 群組 ≤5 欄；23 個群組只有 1 欄、32 個群組 ≤3 欄（碎：一組一顆儲存）。

### 1.3 自訂（builder_*）總開關
- builder_* 共 13 群組、29 欄，全為 2 選開關（0 個 bool 型）。名為 `enabled` 的總開關 12 個：status_display、governance、rules、menu、custom_fields、actions、slots、exports、option_lists、notify、stage_templates、custom_modules（settings_groups.py 約 :689-1088）。
- 另有 builder_layout 8 個逐畫面開關（suppliers、case_management、procurement、devices、vendor_contractors、customers、quotation_form、quotations）、builder_governance 5 個 enforce_*、builder_custom_fields 3 個報價單子開關、builder_rules.k01_seed。
- external_login 另有「（總開關）」欄（settings_groups.py:1000）。
- 「總開關＋子開關」是設定中心唯一真正的階層。

### 1.4 元件適用
| 元件 | 適用度 | 說明 |
|---|---|---|
| 群組全開/全關 | 中 | 僅 builder_layout／governance／custom_fields 類有意義 |
| 搜尋篩選 | 高 | 現只搜群組名；應能搜 183 欄、篩「非預設／已改／待生效」 |
| 預設組 | 高 | 機制在、內容 0 |
| 確認+6秒復原 | 低 | 已有原因＋預覽＋版本還原＋待生效 |
| 矩陣／勾選批次 | 低 | 欄位異質 |
| 手機卡片 | 低 | 已是卡片 |
痛度中；頻率低。

## 2. (b) 通知與信件

### 2.1 mail-settings.html（信件與通知收件設定）
| 項目 | 數字／行為 | 證據 |
|---|---|---|
| 列數 | 67 信件類型（簽核38／業務19／系統技術10）+ 9 僅行事曆 = 76 | 實跑；routers/mail_settings.py:55-70 |
| 欄 | 信件(核取)／行事曆(核取)／分類／預設收件人／影響說明／收件人設定／儲存 | mail-settings.html:69 |
| 篩選 | 只有分頁：全部＋3 分類＋「僅行事曆」；無文字搜尋 | :60-63 |
| 信件核取 | 勾了立即存；取消勾選有 confirm | :235-242 |
| 行事曆核取 | 勾了立即存（逐格 PUT） | :255 |
| 收件人設定 | 手機需先按「收件人設定與說明」展開；選模式（3 種）；custom 再點角色晶片（後端 ROLES 6 個）／加帳號；逐列按「儲存」 | CSS 註解 :56 附近；mail_types.ROLES |
| 前端缺漏 | ROLE_LABELS 為 superadmin/admin/sales/engineer/user/viewer，缺後端有的 finance、多出 user（讀碼） | mail-settings.html ROLE_LABELS |
點擊成本（改 8 列）：
- 關 8 種信件：8 勾＋8 confirm = 16 動作，各自即時存。
- 8 列改「僅最高管理者」：每列 展開(1)＋下拉(1)＋儲存(1) ≈ 24（桌機約 16）。
- 8 列改「指定 3 角色」：每列約 6 → 約 48。
- 無「選取多列批次套用」、無「整分類一起」。
痛度高；頻率中（判斷：上線初期與組織異動集中調整）。
適用：矩陣（76 列 × 6 角色＋行事曆）高；勾選批次高；群組全開全關高（以 3 分類）；搜尋高；預設組中；確認+6秒復原高；手機卡片已有。

### 2.2 notification-settings.html（1114 行）
| 區塊 | 項目數 | 操作 | 證據 |
|---|---|---|---|
| Gmail SMTP | 2 核取＋6 欄（寄件人、密碼、主機、埠、顯示名、系統網址） | 一顆「儲存設定」 | :237-350 |
| LINE 連線 | 啟用核取＋token／Login channel 2 欄／對外網址＋帶連結核取 | 一顆「儲存 LINE 設定」 | :339-571 |
| LINE 事件 | 70 事件／10 群組：業務開發15、請款與開票8、案件管理8、系統告警8、自訂模組7、報價單與簽核6、工作事項6、承攬商5、出貨單4、通知與報表3（實跑 `line_notify.wired_events()`） | 群組手風琴（預設收合 :489-492）；每事件 1 核取＋6 個角色核取＋「設定誰要收」展開；**核取立即存**（toggleEvent :873） | :485-540 |
| 月報收件人 | 下拉加入＋「儲存收件人名單」 | 一顆儲存 :628 | :419-468 |
- LINE 事件角色核取共 70×6 = 420 個，無總覽矩陣、無整群全開/全關。與另一窗口設計一致，僅確認 70／10。
- 改 8 事件 ≈ 展開 1~3 群組＋8 勾 ≈ 10 動作（立即存）；改 8 事件×3 角色 ≈ 35。
痛度高；頻率中。適用：矩陣高、群組全開全關高、預設組高、搜尋中、確認+6秒復原中、手機卡片中。

### 2.3 個人通知偏好
| 位置 | 數量 | 操作 | 證據 |
|---|---|---|---|
| users.html 編輯使用者 Modal「Email 通知偏好」（不在 my-account） | EVENT_KEYS 78 鍵／8 組：簽核流程34、系統與報表15、案件與到期提醒8、會計傳票與總帳申請7、工作事項6、標案雷達4、業務開發審核2、已結案案件解鎖2（實跑 EVENT_GROUPS；模組自登記者另併入，notification_prefs.py:128） | 8 個手風琴預設收合，每鍵一個 pill；無群組全選/全不選；隨使用者表單整份儲存；不在收件範圍者灰掉 | users.html:686-720, 929, 954-970；notification_prefs.py:17 |
| my-account.html「我要收的 LINE 通知」 | 同 LINE 事件，只列公司已開且角色允許者（≤70） | 全展開清單逐項核取，立即存（setPref） | my-account.html:345-361 |
- 改 8 個 Email 偏好 ≈ 開 Modal＋展開 1~3 組＋8 勾＋存檔 ≈ 12；對 N 位使用者要重做，無依角色套預設、無跨使用者矩陣。
- my-account 沒有 Email 偏好（grep 無 notification_muted）；Email 偏好只有管理員在 users.html 代改。
痛度中-高；頻率低。適用：群組全開全關高、預設組中、矩陣中（使用者×事件）、手機卡片中。

### 2.4 google-calendar-settings.html
- 事件開關 19 個／6 群組（案件5、金額單據3、業務開發3、付款3、期限提醒3、收款2；實跑 gc.event_types()），全展開核取＋一顆「儲存事件設定」（:205-224）；總開關另一張卡（:280）。
- 與 mail-settings「行事曆」欄是同一份 `google_calendar.events`（routers/mail_settings.py:56）。其中 9 個為僅行事曆、9 個與信件 1:1 綁定（實跑）。
痛度低；頻率低。適用：群組全開全關中。建議併入信件矩陣的一欄。

## 3. (c) 單據編號與欄位設定

### 3.1 單據編號
| 位置 | 規則 | 操作 | 證據 |
|---|---|---|---|
| 設定中心 quote_defaults | 只有 `estimate_no_prefix`（估價單字首，預設 ME，2 個大寫字母，不得撞保留字首） | 1 個文字欄 | settings_groups_profit.py:96；doc_type.py:46 |
| expense-types.html | 每類型 `numbering.prefix`（≤4 字，自動轉大寫）；內建 4 類：PC、PO、PR、TE | 文字框＋單據類型下拉 | expense-types.html:166-172；expense_type_defs/*.json |
| module-builder.html | 每自訂模組：前綴＋日期格式（3 種）＋位數（3~8） | 3 個控制項 | module-builder.html:219-233 |
| 全站保留字首 | 36 個（30 個 2 字母＋6 個表單範本） | 程式固定 | doc_type.py:39-43 |
| 其他單據（出貨、匯款、傳票…） | 日期 YYYYMM、流水 3 位固定，未開放 | — | doc_type.py:34-36 |
結論：沒有集中的編號頁或一覽表。適用元件幾乎無（不是批次問題）；若要做是「唯讀總表＋可編字首」新頁。痛度低；頻率低。

### 3.2 欄位／清單類設定頁
| 頁面 | 項目數（計數規則） | 現況操作 | 痛 | 頻 | 適用元件 |
|---|---|---|---|---|---|
| expense-types.html（368 行） | 內建 4 類型；欄位數 petty_cash 8、purchase_order 12、purchase_req 9、travel 11 = 40（數 expense_type_defs/*.json 的 fields）；欄位表 9 欄含 3 個核取欄（必填／預填鎖定／僅出納可改，:201-212） | 草稿→驗證→發布；新舊兩種 UI（:184-187）；逐欄逐格改 | 中 | 低 | 矩陣中；其餘低 |
| module-builder.html（1169 行） | 欄位型別15、屬性15、元素20、表欄型別6、日期格式3（custom_modules 常數實跑）；單一模組欄位數不固定（未驗） | 設計器：一次一欄＋右側屬性面板 | 中 | 低 | 不適用批次；手機卡片低 |
| report-templates.html（309 行） | 這頁是報表查詢、不是設定：範本清單＋參數＋本月/本季/今年/去年快捷（:122-125） | 查詢＋匯出 | 低 | 中 | 無 |
| account-items.html（226 行） | 547 筆科目（data/account_items_112.json：L1 8、L2 20、L3 94、L4 425）；有「只看一級／展開到二級／全部展開」（:115-117） | 逐列「＋延伸」、「停用」逐列二次確認 | 中 | 低 | 搜尋高（現無，grep 無 search）；批次中 |
| remit-kinds-settings.html（191 行） | 預設 4 款別 × 6 派發階段 = 24 核取（remit_kinds.py:23,29-37；html:121-126） | 整份草稿編輯→驗證→存草稿→發布，核取不即時存 | 低 | 低 | 矩陣（已近矩陣，可加欄全選）；其餘低 |
| ledger-settings.html（353 行） | 4 分頁：科目歸屬（547 科目×2 個下拉）／報表列（預設 50 列：fs_lines.seed_rows）／費用類別科目對應（逐列儲存）／科目角色對應（DEFAULT_ROLES 39） | 科目歸屬與報表列：@change 立即存；類別對應逐列「儲存」；角色對應走申請→核准；已有「只看有問題的」核取（:83） | 中-高 | 低 | 搜尋高；勾選批次高；矩陣中 |
| legal-params.html（193 行） | 每版本 10 個欄位標題（:76-77），預設 1 版；有「新增下一年度（複製最新一版）」（:116） | 表格一列一版、一顆「儲存」；凍結版不可改 | 低 | 低（每年一次） | 無 |
| company-profile-settings.html（1744 行） | 輸入欄約 56 行含 input/select/textarea、僅 1 個核取；多張卡各一顆儲存（:255、544、587、638、673 共 5 顆，文字相近、存的範圍不同；:533-540 註解記載過去事故） | 逐卡儲存 | 中 | 低 | 無批次；改善重點是儲存範圍清楚 |

## 4. 優先序（依實測，判斷性，供彙整）
1. 信件收件矩陣（76 列×6 角色＋行事曆，順便併入 19 個行事曆事件）：痛高、頻中。
2. LINE 事件×角色矩陣（70×6）＋預設組：痛高。
3. Email 個人偏好 78 鍵：先加「群組全選/全不選」，成本最低。
4. 設定中心：補欄位搜尋、補預設組內容；builder_* 13 群組做「總開關＋子開關」面板。
5. ledger-settings 科目歸屬（547）：搜尋＋批次。

## 5. 未驗
- 模組自行登記的設定群組：grep 顯示 register_group 只在 settings_groups.py，據此判斷 50 群組完整，但未啟動伺服器載入模組驗證。
- mail-settings 畫面是否把 9 列「僅行事曆」併進同表（讀碼為 calendarOnly 另列）。
- 各頁「點擊成本」為依讀碼的估計，非實測。
