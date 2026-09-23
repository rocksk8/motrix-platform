# MOTRIX ERP — 模組：案件管理（§5.4–§5.6、§5.10–§5.13、§7.16、§7.17）

> 自 `MOTRIX-ERP-QUICK.md` 拆出（2026-09-23）。§ 編號沿用原編號，程式註解裡的「QUICK.md §N」依中樞檔的對照表找到本檔。
> 內容逐字搬移，未改寫；相對連結已改為自本目錄起算。

---

### §5.4 · 案件管理 Tab 結構

| Tab | 內容 |
|-----|------|
| 案件資訊 | 合約資訊 + 人員角色 + 收款管理（%／含稅／未稅雙向） |
| 執行進度 | 進度 / 叫料 / 設備 / 保固備注 |
| 承攬商 | 派發記錄 + 驗收流程 |
| **動態** | 案件留言板（手動留言 + work_log 同步 + daily_task 完成回報） |
| 財務 | KPI + 精算結果（需 `canSeeFinancial`） |

---

### §5.4b · 動態 Tab（案件留言板）

- **資料來源（合併排序，newest-first）**
  1. `case_updates` 表：手動留言（任何角色均可發布；發文者或 admin+ 可刪）
  2. `work_logs`（`case_no=此報價單號`）：工作日誌自動同步為只讀卡片
  3. `daily_task_completions JOIN daily_tasks`（`case_no=此報價單號`）：完成回報只讀卡片
  4. `dev_logs`（依 `dev_cases.converted_quote_no=此報價單號` 反查 case_id，`needs_approval=0`）：
     業務開發開發記錄自動同步為只讀卡片，僅在該報價單有業務開發案件連結時出現；代填記錄需先經
     管理員審核（`PATCH /api/dev-logs/{id}/approve`）通過後才會顯示（2026-08-05b）
  5. `audit_log`（`target_type='dev_case' AND action='dev_case.status'`）：業務開發案件狀態變更
     事件，同上僅連結案件時出現（2026-08-05b）
- **API**：`GET/POST /api/quotations/{no}/updates`、`DELETE /api/quotations/{no}/updates/{id}`
- 切換案件時自動重置；點擊「動態」Tab 時 `loadCaseUpdates()` lazy fetch

---

### §5.5 · 成本精算 settlement

- 入口：已成案／已結案 → `settlement.html?no=`
- 存於 `data_json.settlement`；欄位 `settle_status` = `draft` \| `finalized`
- 每次儲存寫入 `editHistory[]`
- `finalized` 後：非 superadmin 不可再修改；API 失敗時**完整回滾** status + finalizedAt + finalizedBy
- **實際總成本三個來源**（2026-08-03e 起）：`itemActualTotal`（原始報價品項實際成本）+
  `extraTotal`（額外支出，手動）+ `dispatchTotal`（承攬商派發成本，**自動即時讀取**
  `GET /api/contractor-dispatches?quote_no=`，唯讀不可編輯，排除 `status==='cancelled'`；
  每筆派發貢獻 = 承攬商含稅合計 `totalWithTax` + 外包名單人員金額加總 `personnelTotal`
  不計稅）；`calcSummary()` 每次都重新抓即時派發資料，不會凍結成精算存檔當時的快照
  **⚠️ 這代表三個顯示點不會永遠一致**：`settlement.html` 本身每次開啟都即時重算
  `dispatchTotal`；但 `case-management.html` 財務 Tab 與 `reports.py`（Excel/PDF）讀的是
  `data_json.settlement.summary` 這份**精算存檔當下寫入的快照**。如果承攬商派發在精算
  `finalized` 之後又被異動（新增/取消/改金額），重新打開 `settlement.html` 會看到新數字，
  但財務 Tab 跟營運報表仍停留在完結當下的舊數字，直到有人（僅 superadmin 可
  `reopenDraft()`）重新存檔覆蓋快照為止。這是**精算「完結即凍結」的正常會計邏輯**（快照
  才能保證財務報表不會被之後的異動悄悄改變），不是 bug——但三處顯示點跨頁比對時務必
  知道這個差異，不要誤以為數字對不上是計算錯誤。

---

### §5.6 · 專案

- `projects` + `project_logs`；與報價 M:N（`linked_cases`）
- 確認事項兩階段：`project_approve_eng` → `project_approve_biz`
- 照片：Pillow 水印 + GPS EXIF → `uploads/projects/...`

---

### §5.10 · 額外支出改版（2026-09-11 交辦，**已完成並上線**）

使用者要求把「額外支出」從精算頁搬到案件管理，並補上填寫人／支出人／送審等機制。
**動工前先讀完本節**，尤其最後那張「必須先確認」的表——裡面每一項猜錯都會做出不能用的東西。

**🚧 施作進度（2026-09-11）**

| 段 | 內容 | 狀態 |
|---|---|---|
| 一 | migration v75 建表＋搬資料＋回填填寫人；存取函式改名；四個讀取端改讀新表 | ✅ `1a43997` |
| 二 | CRUD／送審 API（新 router）＋`APPROVAL_DOC_TYPES` 加新類型 | ✅ `68f6a4a` |
| 三 | 案件管理新畫面（案件內選單）；精算頁那張表移除 | ✅ `ab1e696` |
| 四 | finance-summary／結案報表 PDF／附件端點／簽核設定頁／統一簽核佇列 | ✅ 本輪 |

> ✅ **四段都完成了，功能可用**（2026-09-11）。先前「資料已改從新表讀但沒有填寫入口」
> 那個不能部署的中間狀態已經解除。T100 傳票匯出查證後**不需要改**——
> `accounting_export.py` 從來沒有讀過額外支出。


**🔁 第二輪交辦（2026-09-11 晚，DB v76）：已核准後的「編輯＝變更申請」＋附件上鎖**

使用者：「額外支出上傳照片功能已核准要上鎖，增加編輯按鈕，編輯需要審核。」
並在追問時明確指定 **「原核准金額不動，核准後才生效」**。

| 段 | 內容 | 狀態 |
|---|---|---|
| 五 | DB v76（`change_status`／`change_json`／`change_approval_json`）；附件在已核准時上鎖；變更申請 6 支端點；統一簽核佇列新類型 `extra_expense_change`；案件管理變更申請面板 | ✅ 本輪 |

**⚠️ 這一輪推翻了第四段的一個刻意決定**：附件原本「已核准後仍可補傳憑證」
（理由是補憑證是會計常態），現在改成**跟金額一起上鎖**。推翻的理由是
「核准當下簽核人看到的憑證，跟事後被換掉的憑證不是同一份，等於簽核簽了一個
會變的東西」。`test_extra_expense_uploads_2026_09_11.py` 的檔頭已改寫成新規則
（同一天翻兩次，看到那支測試的人一定會困惑，所以把兩次的理由都寫在裡面）。

**最容易做錯的地方：不要用「退回草稿再改」**

最直覺的實作是「按編輯 → 狀態退回草稿 → 改完重新送審」。**那是錯的**：人一按
編輯，成本／案件財務總覽／營運報表的數字當場就變了，簽核淪為事後追認，正好
違反使用者指定的那句話。正確作法是把提議內容另外存一份：

```
本體（status / total_cost / files_json）           ← 核准前完全不動
   └─ change_status / change_json / change_approval_json   ← 變更申請自己走一輪簽核
                                                              全部層過了才由
                                                              _apply_change() 覆蓋回本體
```

`change_status` 狀態機（與本體的 `status` 是兩條獨立的線）：

```
（無）──存草稿──▶ 草稿 ──submit──▶ 待審核 ──▶ 簽核中 ──approve──▶ 套用並清空
                   ▲                             │
                   └────── 已駁回 ◀───reject──────┘
```

| 決策 | 內容與理由 |
|---|---|
| 用獨立三欄，不共用 `approval_json` | 一筆支出可能被改很多次，每次都是獨立一輪簽核。共用一欄的話，變更申請一送出就蓋掉「這筆原本是誰核准的」——那正是查帳要看的東西。歷次變更 append 進 `approval_json.changeHistory`（含前後金額與核准人） |
| 待核准附件 | 檔案在草稿階段就實際落地（同一個文件資料夾），但只記在 `change_json.addFiles`，**不進 `files_json`**——核准前案件財務與結案報表 PDF 都撈不到。撤銷／駁回後撤銷時實體檔一併刪除 |
| **不支援**「刪除已核准的既有附件」 | 已被簽核人看過、已計入成本的憑證不該被單方面移除，語意同「已核准的項目不可刪除」（要移除請找最高管理員） |
| 簽核流程沿用 `extra_expense` 這個文件類型 | 「改一筆已核准的支出」跟「新增一筆」本來就該由同一批人把關，簽核設定頁不必多一個分頁 |
| 佇列上必須是**獨立類型** `extra_expense_change` | 借用 `extra_expense` 的話，簽核人按核准會打到本體的 `/approve`，那支看到 status 已是「已核准」就回 409——**變更永遠簽不掉，畫面上只顯示一句「簽核失敗」**，沒有人查得出為什麼 |
| 沒有簽核層時送審即生效 | 同新增流程的既有理由：簽核設定是選配的，不能因為沒設定就把人永久卡住 |

**端點**（全部掛在 `/api/quotations/{quote_no}/extra-expenses/{id}/change-request`）

| 方法 | 路徑 | 說明 |
|---|---|---|
| PUT | `` | 建立／更新草稿（**只有已核准的項目**走這條；草稿與已駁回直接 PATCH 本體即可） |
| DELETE | `` | 撤銷（草稿／已駁回；送審中要撤銷請先請簽核人駁回） |
| POST | `/files` | 上傳待核准附件 |
| DELETE | `/files/{file_id}` | 刪除待核准附件 |
| POST | `/submit` | 送審 |
| POST | `/approve` | 核准當層；全過了才 `_apply_change()` |
| POST | `/reject` | 駁回 → 已駁回（本體從頭到尾沒動過，不需要回滾） |

**測試**：`test_xe_change_request_2026_09_11.py`（10 題）＋
`test_e2e_extra_expenses_ui_2026_09_11.py` 新增兩題（已核准列的鎖定與編輯入口、
瀏覽器完整來回）。六個破壞驗證全紅（把修好的行改回壞掉的樣子，確認測試會抓到）。

**⚠️ 搬資料時抓到的兩個「會讓資料無聲消失」的坑（都在實跑 db 副本時才發現）**

| 坑 | 後果 | 修法 |
|---|---|---|
| 歸月日期少了 `editHistory` 的兩層 fallback（精算完結時間／最後存檔時間） | 實測 7 筆既有資料**有 6 筆 `expenseDate` 與 `createdDate` 都是空的**，全靠那兩層歸月——少了就是 **7,990 元直接從月支出報表蒸發，而且不會有任何錯誤**。正是 2026-09-09 修過的同一類問題 | `_move_extra_items_for_quote()` 把四層 fallback 完整搬過來，並有回歸測試 |
| 品項說明少了 `name`／`desc` 這兩個舊欄位名的 fallback | 舊資料的說明整欄變空白，報表明細只剩類別、對不回實體憑證 | 同上，`description or name or desc` |

**教訓**：搬資料時「欄位對欄位」照抄不夠——**舊的讀取函式做了哪些 fallback，要一起搬**。
這兩個都不是搬移邏輯寫錯，是原本的讀取端比表面上複雜。動手前先把舊讀取函式整個讀完，
不要只看資料長什麼樣子。搬完務必**在 db 副本上實跑一次並逐筆比對**，不能只跑測試——
這兩個坑的測試資料都很乾淨，是拿真實資料跑才看出來的。

**第四段改了哪些讀取端**

| 位置 | 改動 |
|---|---|
| `quotations.py::get_finance_summary()` | 改讀新表；多回 `status`／`pending`／`payerName`。⚠️ 連帶把 `conn.close()` 移到查詢之後——原本在它之前就關，改完會變成 use-after-close |
| `pdf_gen.py::_case_closing_report_data()` | 改讀新表；結案報表多「支出人」與「狀態」兩欄——對外文件要讓看的人知道哪幾筆還沒簽完 |
| 附件端點 | 從 `/settlement/extra/{idx}/files` 搬到 `/extra-expenses/{id}/files`，**改用資料列 id 而不是陣列索引**（索引會因新增／刪除／重排指到別筆去）。檔案分類 `quotation_settlement_extra` → `case_extra_expense`。**刻意的行為改變**：已核准之後仍可補傳憑證（補憑證是會計常態，核准當下常常還沒拿到紙本發票），但金額與說明仍然鎖住 |
| `approval-settings.html` | 套用範圍多選加入「案件額外支出」，預設跟統一流程走、取消勾選即獨立 |
| 統一簽核佇列 | `/approval-queue` 與 `/approval-queue/count` 都加入；前端補 `extra_expense` 的類型標籤、核准／駁回 URL（掛在案件底下，形狀與其他類型不同）與「沒有 PDF 可預覽」的分流 |


**實作筆記（第一段）**

- 新表 `case_extra_expenses`，欄位見 `db.py::_m075_case_extra_expenses()`。
  `data_json` 裡的原陣列**刻意保留**當唯讀備份，不再被任何程式碼寫入。
- 存取函式 `settlement_extra_expenses(data)` → `case_extra_expenses(conn, quote_no)`。
  **刻意改名**：沿用舊名只改實作的話，漏改的呼叫端會安靜地拿到空陣列、
  報表數字歸零卻不報錯。改名當場就抓到一個原本沒發現的呼叫點（`reports.py:3440`）。
- `pending` 語意從「精算未完結」改成「送審未核准」。依使用者指定，
  送審中的項目**照樣算進成本**（不算會讓當月的錢消失）但標 pending。
- 搬移邏輯抽成 `db.py::_move_extra_items_for_quote()`，**測試用同一支**——
  欄位對應與日期 fallback 在測試裡另外複製一份的話，兩邊遲早會漂移。

**現況（2026-09-11 實際翻程式碼與資料庫確認，非依賴舊文件）**

| 項目 | 現況 |
|---|---|
| 位置 | `settlement.html`（精算頁）「二、額外支出」表格，`settlement.html:440-600` |
| 資料落點 | `quotations.data_json` → `settlement.extraItems[]`，**無獨立資料表、無 migration** |
| 既有欄位 | `id`(Date.now())、`category`、`description`、`qty`、`unit`、`unitCost`、`totalCost`、`note`、`expenseDate`、`createdDate`、`docNo`、`files[]`、`createdBy` |
| 類別選項 | 固定七項 `<select>`：工時／材料／差旅／運費／安裝／外包／其他（`settlement.html:492-504`） |
| 唯讀顯示 | `case-management.html` 財務分頁的「精算額外支出明細」（可展開），資料源就是同一份 `extraItems` |
| 計入方式 | `finExtrasTotal()` 只顯示總額，**刻意不計入「應付總額」**——那個數字的定義是承攬商匯款申請 |
| 送審 | **完全沒有**。精算頁存檔就生效，只有 `settlement.status` 的 draft／finalized 兩態 |

**⚠️ 已查證的兩個現行缺陷（改版時一併修掉，不要照抄舊行為）**

1. **`createdBy` 永遠是空字串**——`settlement.html:1096` 取 `this.session?.user?.display_name`，
   但這個路徑不存在；同一支檔案其他地方（`:1187`、`:1221`）用的都是
   `this.session.displayName || this.session.username`。實測開發機 db：
   **7 筆既有額外支出，`createdBy` 有值的 0 筆**。2026-09-09 新增這個欄位的目的正是
   「案件財務總覽要顯示填寫人」，結果那裡永遠顯示「填寫人：—」。
   → 這也正是使用者這次提「要自動帶入填寫人」的由來。既有 7 筆資料要決定是否回填。
2. **類別欄位寬度寫死**——`<th style="width:90px">` ＋ `select` 的 `font-size:11px`，
   中文選項（「外包」「安裝」）在某些縮放比例下會被截斷，且不隨內容自適應。
   → 使用者說的「類別太小沒有自適應」。

**使用者要求的七項**

| # | 要求 | 備註 |
|---|---|---|
| 1 | 從精算頁搬到**案件管理的案件內選單** | 精算頁那張表要保留唯讀還是整個移除，見下方待確認 |
| 2 | 類別欄位加寬、**自適應** | 連同整列在窄螢幕的排版一起處理 |
| 3 | **自動帶入填寫人**（目前的人）＋ **可選「支出人」** | 支出人是新欄位，跟填寫人是兩回事：填寫人＝誰輸入這筆，支出人＝錢實際由誰支付／代墊 |
| 4 | **填寫日期**與**更動日期** | 填寫日期≠支出日期（`expenseDate` 已存在）；更動日期要在每次編輯時更新 |
| 5 | **填寫需送審** | 接哪一套簽核見下方待確認 |
| 6 | 相關支出計算對應**都要與現有的結合** | 精算總成本、案件財務總覽、營運報表、T100 傳票匯出都讀得到這批數字 |
| 7 | 備註要寫清楚 | 即本節 |

**❓ 動工前必須先跟使用者確認（猜錯會做出不能用的東西）**

| # | 問題 | 為什麼不能猜 |
|---|---|---|
| A | 「支出人」是從**使用者清單**選、從**承攬商清單**選，還是自由文字？ | 三種的資料模型與後續統計完全不同；若要做「某人代墊多少」的彙總，就必須是 id 而非文字 |
| B | 送審接**哪一套**？現有兩套機制：`helpers/tiered_approval.py`（五種文件共用的分層簽核）或 `case_change_requests`（半解鎖的排隊重放） | 前者要新增文件類型＋簽核設定頁要多一個分頁；後者是「暫存 payload、核准時重放」，改動小但語意是「變更申請」不是「單據」 |
| C | **送審中的項目算不算進成本？** | 影響精算總成本、案件財務總覽、月支出、營運報表四處的數字。若算，核准前後金額不變、簽核形同虛設；若不算，精算頁在等待期間會少一筆，使用者可能以為資料掉了 |
| D | 精算頁的那張表**保留唯讀還是整個移除**？ | 保留＝兩個地方看得到同一份資料（要明確標示唯讀與入口在哪）；移除＝精算頁的「額外支出小計」要改成連結過去 |
| E | 已結案案件還能不能新增／編輯額外支出？ | 現有 `_deny_if_case_locked_unsupported()` 的 13 支端點一律 403，這批新端點要歸到「支援排隊審核」還是「直接擋」 |
| F | 既有 7 筆 `createdBy` 空白的資料要**回填**還是留空？ | 回填只能用猜的（沒有紀錄誰建的），留空則報表上會一直有「—」 |

**技術註記**

- 目前 `extraItems` 存在 `data_json` 裡。要做送審與「更動日期」的稽核軌跡，**建議改成獨立資料表**
  （比照 `case_stages` 從 data_json 正規化出來的前例，見 §11 相關列）；若維持 data_json，
  送審狀態與歷史版本會很難查。這是本案最大的架構決策，會決定要不要 migration。
- 金額欄位若改為「送審核准後才計入」，`routers/quotations.py::get_finance_summary()`、
  `settlement` 彙總、`accounting_export.py`（T100）三處都要同步，**不要只改畫面**。
- 送審通知沿用 `notify_module_activity()` 與 `_check_approval_reminders()` 既有機制即可，不必新寫。

---

### §5.11 · 執行進度勾選 → 兩張行事曆（2026-09-11 交辦，DB v76）

使用者：「報價單成交跟案件管理執行進度勾選進單確認、叫料出貨這些或是手動打上的
選項，只要有勾選，要同步於行事曆標註，例如當日勾選客戶驗收，行事曆要增加案件
名稱＋進度在行事曆上。」追問「行事曆」指哪一個時，回答 **「兩邊都要」**——
Google 行事曆與系統內「每日工作事項 → 月曆總覽」。

**兩條路徑各自的落點**

| 目標 | 實作 | 記在哪 |
|---|---|---|
| Google 行事曆 | `helpers/google_calendar.py::push_event_for_case_stage_done()` | `case_stages.google_calendar_done_event_id`（v76 新欄位） |
| 系統內月曆 | `helpers/case_stage_tasks.py::sync_daily_task_for_case_stage()` | `case_stages.daily_task_id`（v76 新欄位），指向一列 `daily_tasks` |

兩支都由 `routers/quotations.py::update_case_stage()` 以 `spawn_bg_thread()` 觸發
（fire-and-forget，失敗只記 log，不能擋住勾選本身）。觸發條件是 **`done` 真的翻面**，
或**已勾選的情況下改了 `done_at`**；只改標題之類的不重推（每推一次就是一趟 Google API）。

**四個一定要注意、而且做錯都不會有任何錯誤訊息的地方**

| # | 坑 | 後果 | 作法 |
|---|---|---|---|
| 1 | 完成日事件共用 `google_calendar_event_id` | 那一欄記的是**到期日**事件（v55）。共用的話，設了到期日再勾完成，後者會把前者的事件改成完成日，**到期提醒就這樣無聲消失** | v76 另開 `google_calendar_done_event_id` |
| 2 | `daily_tasks.assigned_to` 留空 | `daily_tasks.py::_user_filter_sql()` 對非 superadmin 只回「我是負責人或監督人」的任務——空的那列等於做了一個使用者**看不見**的東西 | 階段負責人優先，沒有就掛勾選的人 |
| 3 | 建立時沒有標成已完成 | `_check_overdue_and_notify()` 每天掃前一天的 `once` 任務，沒有完成紀錄就寄逾期信——**對一件已經做完的事，隔天寄信給每個負責人** | 同時寫 `daily_task_completions`（`completed=1`） |
| 4 | 取消勾選靠標題比對去找那一列 | 標題含案件名稱，案件一改名就對不上 | 用 `case_stages.daily_task_id` 記住 id；取消勾選 soft delete（`is_deleted=1`），階段被刪也一併收回 |

**事件內容格式**（使用者指定「案件名稱＋進度」）

- Google：標題 `{案件名稱}｜{進度} 完成`，日期用 **`done_at`**（勾選時前端自動帶今天，可改成實際完成日），
  說明欄含案件編號／客戶／完成日期
- 每日工作事項：`title` = `{案件名稱}｜{進度}`，`category` = `案件進度`，`task_date` = `done_at`，`case_no` = 報價單號

**順帶改掉的**：`push_event_for_quotation_won()` 的標題補上案件名稱
（原本是 `報價單成案 — {單號}（{客戶}）`，案件名稱只在說明欄裡，Google 的月檢視
只看得到標題）。使用者這次把「報價單成交」跟執行進度並列提出來，多半就是因為
在月檢視上認不出那是哪個案子。

**測試**：`test_case_stage_done_calendar_2026_09_11.py`（10 題，含「端點有沒有真的
接上這兩支」與「只改標題不該重推」）。⚠️ 該檔有一個 autouse fixture 把端點自己起的
背景執行緒關掉、改成測試裡明確同步呼叫——不關的話端點的執行緒會跟測試自己的呼叫
同時寫同一列，斷言拿到誰的結果純看排程（**實際偶發紅過一次**）。那是測試自己製造的
競態，不是產品的：正式流程一次勾選只會起一支執行緒。

---

### §5.12 · 收款資料異常：「已收款」與「收款日期」是兩個欄位（2026-09-11）

**起因**：使用者回報「案件資訊有一筆 2026/09/01 收款，沒有同步顯示於營運報表計算
當月收入」（`MQ-202607-045` 交貨款）。

**查證結果：報表的計算邏輯是對的。** 在 db 副本上把那筆設成
`received=true` / `receivedAt=2026-09-01` 之後，`_collect_income_items()`（收支報表）
與 `_collect()`（主財務報表）**兩支都撈得到**（NT$ 263,828）。所以不要去改報表。

真正的原因是那兩個欄位**各自獨立**，只填一個就會出事：

| 狀況 | 收入報表 | 未收報表 | 使用者在案件裡看到的 |
|---|---|---|---|
| `received=1`、`receivedAt` 空 | ❌ 不屬於任何月份 | ❌（已收，不算未收） | 綠色的「已收款」 |
| `receivedAt` 有值、`received=0` | ❌（未收） | ❌ 未收看的是 `expectedReceiptDate` | 收款日期欄有日期 |

**兩種都是兩邊都撈不到**——錢從所有月報表上消失，而且沒有任何錯誤訊息。跟
2026-09-09 修過的「精算未完結的額外支出被月支出漏算」、`_m075` 搬移時抓到的
「歸月日期少了兩層 fallback」是同一類坑：**資料形狀不完整時靜默丟棄**。

**作法：不修計算，改成把狀態變成看得見的**（三個地方）

| 位置 | 內容 |
|---|---|
| `routers/reports.py::_collect_payment_anomalies()` | 偵測上表兩種形狀，範圍與 `_collect_income_items()` 完全一致（`deal_tag IN ('已成案','已結案')`），金額走 `payment_item_amounts()` |
| `GET /api/reports/payment-anomalies` | 獨立端點（admin+）；`/api/reports/expenses-monthly` 的回應也帶 `paymentAnomalyItems`／`paymentAnomalyTotal` |
| `case-management.html` 款項明細 | 那一列底下直接跳提示，寫明「不會計入營運報表的當月收入」 |
| `reports.html` 收支分頁 | 最上方一張「收款資料異常」表，案件號可點過去修 |

**兩個刻意的決定**

- **不隨期別篩選**：這些款項正是因為欄位不完整而不屬於任何月份，用期別去篩等於
  再篩掉一次，那正是這一區要解決的問題本身。
- **不自動修正**（例如「有日期就當作已收」）：錢收到了沒有是人的判斷，系統替使用者
  決定，錯了會比漏算更嚴重。這裡只負責點名。

**⚠️ 開發機 db 副本（2026-09-11 11:27）實跑出來的既有異常——正式機大概率也有**：
**4 筆、合計 NT$ 1,626,990**，其中 `MQ-202608-007` 兩筆就佔 **NT$ 1,576,240** 是「已勾已收款、沒填收款日期」，
目前在任何月份的收入報表上都看不到。上線後請開營運報表 →「月支出」分頁最上方
那張表，逐筆補齊。

---


**🔁 2026-09-12 後續：分頁口徑也一起改了**

同一位使用者隔天又回報同一筆（`MQ-202607-045` 交貨款，截圖顯示已勾已收款、收款
日期 2026/09/01），但營運報表的「**已收款**」分頁還是 0。這次的根因跟上面那個
（欄位只填一半）**不是同一件事**：

「已收款／未收款」兩個分頁原本是依**成案月份**分組（2026-09-09 初版設計）。
`MQ-202607-045` 在 2026-07 成案，所以那筆 9/1 收的錢一直被算在 **7 月**——實測
7 月那頁抓得到、金額 263,828。分頁標題只寫「已收款」，看不出它問的其實是「當月
**成案**的案子收了多少」。

依使用者指示改成**收款日期口徑**：已收款看 `receivedAt`、未收款看
`expectedReceiptDate`，年／季／月三個範圍一起改。

⚠️ **改這個最危險的地方是「缺日期的會消失」**：實測開發機未收款 7 筆**全部沒填
預計收款日**，直接照日期分組會讓它們從每一個月份都撈不到。所以另外回傳
`undated*` 兩組（不隨期別篩選、**不併進月份合計**——併進去同一筆會在每個月被
重複計算），前端在兩個分頁下方各列一區並說明怎麼補。

---

### §5.13 · 完工單（2026-09-12 交辦，DB v77）

使用者：「在案件管理內增加完工單的選項，參考出貨單的形式跟內容建立完工單，一樣走
流程申請完工，內容先由你依據企業完工單撰寫。」

**形狀比照出貨單**：`completion_notes` 表與 `routers/completion_notes.py` 跟
`shipping_notes` 同構——一個報價單可有多張完工單（分階段／分區完工）、同一套狀態機
（草稿→待審核→簽核中→已核准）、共用 `unified_approval_flow`（文件類型
`completion`，預設走統一流程、可在簽核設定頁取消勾選改成獨立）、核准後客戶回簽並
可上傳簽回附件、PDF 匯出與匯出紀錄。單號前綴 `CN`。

**刻意跟出貨單不同的三件事**

| # | 差異 | 為什麼 |
|---|---|---|
| 1 | **不碰庫存** | 東西在出貨單那一關就出掉了。跟著抄庫存扣減會讓同一批序號被扣兩次，而且第二次扣時第一次已不是 `in_stock`，核准直接 409 ——**完工單永遠簽不掉**。有專門一題測試釘住 |
| 2 | **送審強制要有完工日期** | 保固起算與工期都以它為準，缺了這張單就沒有意義 |
| 3 | **項目有完成狀態**（完成／部分完成／未施作），且**不擋**有未完成項目的送審 | 擋下來現場只會被迫把沒做完的也填「完成」，遺留事項那欄就永遠是空的。改成把未完成數量算出來，清單、簽核佇列、送審確認視窗三處都顯示 |

**完工單內容（依台灣工程業慣例撰寫）**

客戶與施工地點（**施工地點≠送貨地址**）／工程期間與保固（開工日、完工日、工期、
保固起訖、現場負責人）／完工項目明細（含完成狀態）／施工說明／測試與檢驗結果／
**遺留事項**（PDF 上用紅框）／業主驗收與承攬商雙方簽章。

> 遺留事項那一欄最容易被省略，也最重要：**完工不等於零缺失**，沒寫清楚的缺失在
> 日後驗收爭議時沒有任何依據。所以畫面上只要有項目填「部分完成／未施作」，就會
> 跳出提示把使用者推到那一欄。

**保固**：`warranty_months` 自**完工日**起算，用既有的 `helpers/dates.py::_add_months()`。
⚠️ 刻意**不**自動建立保固追蹤紀錄——保固模組有自己的資料來源，偷塞一筆會變成兩套
來源打架。先存月數、PDF 印出起訖，要不要接進保固追蹤之後另議。

**路上抓到的一個靜默錯誤**：`_warranty_range()` 第一版把字串丟給吃 `date` 物件的
`_add_months()`，TypeError 被 `except Exception` 吞掉，保固迄日永遠是空字串、畫面
與 PDF 都只是「沒顯示」而不報錯。已改成只吞 `ValueError`（日期格式不合法，屬預期
情況），型別錯不再靜默。**這是本專案第 N 次被寬鬆的 except 藏住真錯誤。**


**🔁 2026-09-12 同日回饋：這份完工單太偏向工程**

使用者：「我們公司除了工程外還有專案、販售零組件、系統設定、網路架構、防火牆等
多項業務，這份完工單太偏向工程。」並逐一點名要能改名的欄位。改了三件事：

**① 預設用語改中性**

| 原本 | 現在 |
|---|---|
| 施工地點 | 服務地點 |
| 二、工程期間與保固 | 二、執行期間與保固 |
| 三、完工項目明細 | 三、完成項目明細 |
| 四、施工說明 | 四、執行說明 |
| 六、遺留事項 / 待改善 | 六、待辦與未完成事項 |
| 工程項目 / 規格說明 | 項目 / 規格說明 |
| 現場負責人 | 負責人 |
| 業主驗收 · 簽章蓋印 | 客戶驗收 · 簽章蓋印 |
| 承攬商 · 工程負責人 | 執行單位 · 負責人 |

有一題測試掃過**全部**預設標題，只要出現「施工／工程／承攬商／業主」就紅——
避免之後有人順手又把工程用語加回去。

**② 這 11 個標題每一張完工單都可以自己覆寫**

存在 `data_json.labels`，**刻意不開新欄位**：純粹是列印用字串、永遠整包讀寫、
不會被查詢或彙總，正是 data_json 適合放的東西。（額外支出當初要正規化出來，是因為
每一列需要各自的簽核狀態與稽核軌跡，跟這裡不是同一種需求——不要混為一談。）

- 空字串視為「沒覆寫」，不是「標題留白」：標題整個消失只會讓人以為版面壞了
- 只接受已知的鍵、每欄上限 40 字
- `labelOverrides` 另外回傳使用者真正改過的那幾欄，前端表單才不會被預設值塞滿
- ⚠️ 編輯時 data_json 一定要 **read-modify-write**，整包覆蓋會把 `approval` 洗掉
  （被駁回退回草稿的單子仍留著那段歷史）。有測試釘住

前端提供五組預設一鍵套用：工程施工／系統建置·設定／設備·零組件供應／
網路架構·資安／維運服務。

**③ 保固期間可不顯示**

比照**報價單「條件留空就不印」**的既有慣例（`pdf_gen.py::term_block()`），不另外
開顯示旗標：保固月數 0／留空 → `_warranty_range()` 連起算日都不回、PDF 整列不印。
零組件販售、系統設定那類單子常常沒有保固可言。

**④ PDF 上方第三欄從「關聯報價單」改成案件名稱**（使用者指定），案件編號移到
第二區保留可追溯性。

**⑤ 填寫介面改成獨立頁面**（使用者：「可用報價單的方式去建立，一個頁面做填寫，
多增加可切換的頁面」）

`frontend/pages/completion-note-form.html`——跟「報價單清單 → 報價單表單」同一種
分工：清單留在案件管理的完工單分頁，填寫在獨立頁面。固定工具列＋四個分頁
（基本資料／完成項目／說明與驗收／單據用語）。

> ⚠️ 這一頁刻意**沒有** `x-init="init()"`。Alpine 3 自己就會呼叫 `init()`，兩者
> 並存會跑兩遍，第二次載入的回應會把使用者改到一半的欄位蓋回去（2026-09-11 在
> `case-management.js` 與 `company-profile-settings.html` 各踩過一次）。有一題
> e2e 數請求次數釘住它。**新增頁面時請照這個寫法，不要再加 x-init。**


**🔁 2026-09-12 再一輪回饋：整合成一頁、帶入報價單資料**

| 使用者說的 | 處理 |
|---|---|
| 「公司的業務不只工程…選一組最接近的」那段說明不要 | 改成一句「依據案件類型選取適合的完工單，再視需要逐欄微調」 |
| 基本資料可拉報價單的地址包含聯絡人 | 新增時從報價單 `data_json` 拉 `deliveryAddress` → 服務地點、`contactName` → 驗收人/聯絡人、`contactPhone` → 聯絡電話（**DB v78** 新欄位），地址欄下方標明「已從報價單帶入，可直接修改」 |
| 是否能整合成一頁逐條改善下來不要有分頁 | 拿掉四個分頁，改成單一頁面由上往下填；分頁用的 CSS 與 `tab` 狀態一併移除 |

**`contact_phone` 為什麼開欄位而不是塞 `data_json`**：那是業務資料不是版面設定
（標題那組才是後者，所以放 data_json）。完工單是會交到客戶手上、之後可能要回頭
聯絡的文件，只有名字沒電話等於還要再翻報價單。

⚠️ **e2e 改寫時的一個重點**：驗「四個區塊同時可見」要用 `state="visible"`，**不能
只檢查元素存在**——分頁那一版元素也「存在」，差別只在看不看得見。另補一條
「分頁按鈕不該再存在」，避免之後有人把分頁加回來而測試照樣綠。

**測試**：`test_completion_notes_2026_09_12.py`（15 題）。PDF 用 Edge headless 實跑
產出 383KB 的真檔案驗證過，不是只有語法正確。

---

### §7.16 · 案件代辦事項 / 出納彙總視圖

| 模組 | Method+Path | 說明 |
|---|---|---|
| 案件代辦事項（`case_action_items.py`，DB v62 `_m062_case_project_merge`） | `GET/POST /quotations/{quote_no}/action-items`、`PUT/DELETE .../action-items/{item_id}`、`PATCH .../action-items/{item_id}/approve` | 取代舊 `project_logs.action_items` JSON blob；兩階段簽核（`stage1_approver`/`stage2_approver`），主管解析比照 `_m050_project_department()` 既有查表 pattern |
| 出納彙總（`cashier.py`） | `GET /cashier/payable-queue \| receivable-queue \| summary \| execution-history \| export` | **2026-08-31 起併入 `reports.html` 第 13 個頁籤「出納」**（`?tab=cashier` 深連結），獨立 `cashier.html`/`cashier.js` 已退役為導向 stub；本質是 §5.9 財務三憑證流的**唯讀彙總層**，非獨立資料源 |

---

### §7.17 · T100（鼎新）傳票批次匯出（2026-09-01，DB v69，見 §12 同日條目）

**2026-09-02 UX 調整（純前端，無 DB/API 變動）：** 使用者反映 T100 匯出/設定原本埋在「資金水位」頁籤最底下太隱蔽，改成 `reports.html` 獨立的第 14 個頁籤「T100匯出」（`showT100Tab()`，切換進來自動預覽本期待確認事件）。另外三個「標記已付款/已收款」Modal（`case-management.html`／`reports.html`出納分頁／`inventory.html`）讀取銀行帳戶清單的 `loadT100BankAccounts()` 改成每次開啟 Modal 都重新 fetch（不再 cache-once）——superadmin 在 T100 設定頁新增/修改銀行帳戶後，其他人下一次開啟任一個標記視窗就會看到最新清單，三處共用同一份設定、即時連動，不用整頁重新整理。

| Method | Path | 說明 |
|--------|------|------|
| GET | /settings/t100-export-config | 科目代號對照設定（admin+ 可查閱） |
| PUT | /settings/t100-export-config | 更新科目代號（superadmin only） |
| GET | /reports/t100-export/vouchers?start=&end= | 現金基礎傳票批次匯出 Excel（admin+），涵蓋已收款發票＋已匯款承攬商費用，刻意排除請款單；**已標記已匯入的事件自動排除** |
| GET | /reports/t100-export/preview?start=&end= | 預覽本期尚未標記已匯入的事件（JSON，非 Excel），供財務正式標記前核對筆數/金額 |
| POST | /reports/t100-export/confirm | `{start,end}`；財務確認該區間候選事件已實際匯入 T100，標記後永久排除於之後匯出/預覽（除非撤銷）；冪等 |
| GET | /reports/t100-export/confirmed?start=&end= | 已標記已匯入的事件清單（稽核／複核用） |
| POST | /reports/t100-export/unconfirm | `{sourceType,sourceKey}`；撤銷單一事件的已匯入標記（誤標記時的救援手段） |

`backend/routers/accounting_export.py`；每筆事件產生的傳票天生借貸平衡；科目代號預設全部留白，需 superadmin 依貴公司 T100 實際設定填入才具備直接匯入意義。**匯出≠已匯入**：`t100_export_confirmations` 表（DB v69）獨立追蹤「財務確認已實際匯入 T100」的事件，用 `(source_type, source_key)` 穩定識別碼（`quotation_payment` → `{quote_no}::{invoiceNo}`；`contractor_voucher` → `voucher_no`；`stock_batch` → `batch_no`），不是每次匯出重算的 AR0001/AP0002/PC0003 流水號。

**事件來源第三類：料件/設備進貨已付款（2026-09-01 同輪新增，DB v70 `stock_batches`，端點見 §7.18）**——過去 `stock_items`（序號級庫存）只有共用字串 `batch_no`，沒有獨立批次表頭，供應商/發票號/付款狀態完全沒地方放。新增 `stock_batches` 表頭，既有批次全部回填但 `is_paid` 一律預設 0（系統過去從未追蹤這件事，不能假設已付款，見 `db.py::_m070_stock_batches()` docstring）——**首次啟用這個功能時，財務需要回頭逐批確認歷史進貨是否已付款**，之後才會逐漸準確反映在 T100 匯出裡。

**科目代號分維度設定（2026-09-01 同輪擴充，DB v71）：**
- **依銀行帳戶**：設定頁維護 `bankAccounts: [{name, acctCode}]` 清單，但匯出計算**不查這份清單**——直接讀「標記已付款/已收款當下」寫進各筆交易自己身上的欄位（`contractor_payment_vouchers.paid_bank_account_name/code`、`stock_batches.paid_bank_account_name/code`、報價單款項 JSON 的 `bankAccountName/Code`，皆為 DB v71 新增，比照既有 `paidBy/paidAt` 快照精神——之後改設定頁清單不會回頭影響已標記的舊交易）。三個「標記已付款/已收款」UI（`case-management.html`「標記已匯款」Modal、`reports.html`「出納」分頁的標記已匯款/已收款 Modal、`inventory.html`「標記已付款」Modal）皆已加上銀行帳戶下拉選單（選填）。
- **依料件分類**：`inventoryExpenseAccounts: {分類名稱: 科目代號}`（鍵對應 `parts.py::PART_CATEGORIES`），這個**是**即時查表（不快照）——分類本身不會變，財務事後更正某分類科目代號，未確認的舊事件會一起套用新值。
- 其餘科目（銷貨收入/銷項稅額/承攬商費用/部門別/傳票別）維持全公司單一設定。

**銀行帳戶欄位自動帶入預設值（2026-09-02 新增，無 DB migration）：** 使用者要求「標示已匯款須帶入當時填寫或是預設的匯款帳戶」——三個標記 Modal 開啟時，銀行帳戶下拉不再一律空白「未指定」，依序嘗試：①查這個對象（承攬商/供應商/客戶）上一次標記時用的帳戶 ②查無則退回 `t100-export-config` 新增的 `defaultBankAccountCode`（系統預設帳戶，設定頁「🏦 銀行帳戶清單」卡片每列可點 ☆ 設為預設）③兩者都沒有才維持空白；使用者仍可手動改選，不是強制值。三支新端點：

| Method | Path | 說明 |
|--------|------|------|
| GET | /contractor-vouchers/last-paid-bank-account?vendor_id= | 該承攬商上次已匯款用的帳戶 |
| GET | /inventory/batches/last-paid-bank-account?supplier_id= | 該供應商上次已付款用的帳戶 |
| GET | /quotations/last-received-bank-account?customerName= | 該客戶（依 `customer_name` 熱路徑欄位比對）上次已收款用的帳戶；⚠️ 註冊在 `GET /quotations/{quote_no}` 之前，避免被當成 quote_no 吃掉 |

三支皆純讀取、需登入不需要 admin+，查無資料回傳 `{"name":"","acctCode":""}` 不噴錯。前端 `reports.js`/`case-management.js`/`inventory.html` 各自新增 `_resolveDefaultBankAccount()` helper 呼叫對應端點。
