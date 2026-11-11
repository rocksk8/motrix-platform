# 獨立稽核：T79 三張票（草稿併發編輯保護／勞報單建立寫鎖洩漏／自選條件報表）（hichan-12，2026-11-12）

> 稽核對象：`origin/train/t79-int` tip `1f00ab62c`（取得時 fetch 的最新；派工單寫的 73672373a 是更早的一筆），範圍＝三張票各自的 diff，不是整段 `55835216..tip`（154 個 commit）。
> 行號以 tip `1f00ab62c` 為準。方法：讀碼＋跑各票自己的測試＋**變異檢查**（在拋棄式 worktree 內改壞程式，看測試會不會紅，改完一律 `git checkout` 還原）。**沒有改任何產品程式碼。**
> 獨立性聲明：我沒有參與這三張票的開發與 K 審。但同一批 train 上的 `quotation-form.html`（N7 待審核唯讀＋橫幅）、`case_access.py`、`versions` 遮金額是我寫的（T79 維運票），與本稽核的 `apiSave`／`loadQuote` 衝突處理在同一檔不同段；下面 §1 沒有碰我的那幾段。

## 0. 結論

- **必修 0、建議 5、觀察 5。** 三張票的規格逐條成立，各自的核心測試都有牙齒（11 個變異全被抓到，見 §4）。
- 沒有發現會讓資料錯、權限洩漏、或鎖卡住的缺陷。最值得處理的是兩件「文件／語意與實作不符」：
  1. **鎖稽核文件說 99 條寫入路由，實際 112 條**——少的 13 條是用 `_BASE + "/…"` 常數組路徑的（`material_approvals.py` 7、`material_changes.py` 6），產生文件的掃描只認字面字串路徑（§1 建議 1）。
  2. 衝突橫幅的「載入最新版（放棄我未存的修改）」用的 `loadQuote()` 是 `Object.assign(this.q, row.data)`（合併），不是取代：只存在本機、伺服器資料裡沒有的鍵，會留在畫面上，下次存檔又被存回去（§1 建議 2）。
- 這一輪實跑：三票自己的測試共 **79 題全過**（`D:\Claude-pm\t79-audit-run1.log`）。tip 上的全量回歸（我另外跑的，4449d316b）只紅 vr1 日曆題，已由 1f00ab62c 補。

## 1. 票一：報價單草稿併發編輯保護（6f538f3b1）

規格來源：`backend/modules/case/CHANGELOG.md`「(next) — 2026-11-11（feat/draft-optimistic-lock）」、FORM_VERSION V3.41 註解、`docs/platform/WRITE-ENDPOINT-LOCK-AUDIT-T79.md`。作者 hichan-10、K 審 hichan-11。

### a. 逐條驗收

| # | 規格 | 證據 | 判定 |
|---|---|---|---|
| 1 | 既有單 PUT 撞 409 ⇒ 顯示持續橫幅＋暫停自動存檔 | `quotation-form.html:3288-3294`（`res.status === 409 && !isNew` ⇒ `_saveConflict`、`saveConflictBanner = true`、`clearTimeout(autoSaveTimer)`）；`autoSave()` :3578 早退；測試 `test_autosave_conflict_is_no_longer_silent_and_pauses_autosave` 綠 | 成立 |
| 2 | 新單 POST 的 409 是單號衝突，不算樂觀鎖 | `:3288 && !isNew`；`test_new_quote_post_409_is_a_number_collision_not_an_edit_conflict` 綠；後端 PUT 只有兩處 409（`quotations.py:2279` 前置、`:2472` 寫鎖內），都是樂觀鎖，橫幅文案不會誤報 | 成立 |
| 3 | 載入最新版成功才清橫幅，失敗保留橫幅與 isDirty | `reloadLatestAfterConflict` :3587-3595、`loadQuote()` 回 true/false（:4417-4466）；`test_failed_reload_keeps_banner_and_dirty_and_other_loads_clear_the_banner` 綠 | 成立 |
| 4 | 存檔成功也清橫幅 | `:3304`；`test_second_editor_gets_a_visible_conflict_on_save_and_can_reload_then_save`（載入後再改再存，兩人修改都在） | 成立 |
| 5 | 橫幅在 1440／1024／390 寬都在流程內、不壓住下一個元素 | `test_banner_is_in_flow_and_does_not_cover_the_content_below_it`（3 個 viewport）綠 | 成立 |
| 6 | 手動儲存／送審撞 409 仍有 alert | `:3836`、`:4365`（既有路徑，三個呼叫 `apiSave` 的地方：autosave／saveDraft／送審） | 成立 |
| 7 | 「不動 API」 | `git diff 6f538f3b1^1 6f538f3b1 --stat`：只有前端、測試、文件、CHANGELOG；沒有 `.py` | 成立 |
| 8 | 99 路由鎖稽核文件 | 逐條對 code：**文件 99、實際 112**（§建議 1） | **不符** |

### b. 反向控制

- 對方不在（單人正常存檔）：不出橫幅——`test_second_editor…` 的前半段先做無衝突存檔；`apiSave` 成功分支 :3304 明確 `saveConflictBanner = false`。
- 失敗路徑：重新載入失敗（網路／401／404）⇒ `loadQuote()` 回 false、橫幅與 isDirty 留著（有題）。
- 回滾路徑：本票是前端，沒有 DB 回滾；後端 409 路徑在 `update_quotation` 寫鎖內檢查，丟例外前沒有寫入（`quotations.py:2469-2472`）。
- 變異（§4）：C1 拿掉「橫幅時暫停自動存檔」、C2 把 POST 409 也當衝突、C3 載入成功不清橫幅——三個都被 e2e 抓到（各 1–2 題紅）。

### c. 假綠燈檢查

- e2e 的「第二位編輯者」是**直接打 API 的 PUT**，不是第二個瀏覽器——對這個行為（版本比對在後端）是正確的替身，不算假綠。
- `test_autosave_conflict…` 斷言「不再重打 PUT」靠計數，我用 C1 變異驗證它真的會紅（不是只看橫幅有沒有出現）。
- 沒有找到斷言驗到自己設值的題。

### d. 建議／觀察

- **建議 2（真問題，低頻）：`loadQuote()` 是合併不是取代。** `quotation-form.html:4435` `Object.assign(this.q, row.data)`。橫幅按鈕文案寫「放棄我未存的修改」，但本機有、伺服器 `data_json` 沒有的頂層鍵（動態才產生的選填物件，例如 `returnInfo`、`approval` 一類）不會被清掉；`isDirty=false` 之後下一次存檔（基準已換新，不會再 409）就把它存回去，等於悄悄蓋掉對方「沒有這個鍵」的狀態。陣列欄位（品項）是整個被取代，不受影響。現有 e2e 只驗「對方的修改在、我重做的修改在」，沒有驗「我被丟掉的修改真的不見」。修法：`reloadLatestAfterConflict` 在 `loadQuote()` 前把 `q` 重設成預設再 assign，或加一題「丟棄的本機修改不得復活」。
- **觀察 1：`_lastUpdatedAt` 為 null 時樂觀鎖整個不生效**（`:3276 if (!isNew) data._expectedUpdatedAt = this._lastUpdatedAt`；後端 `:2278` 要 `expected_updated_at` 有值才比）。載入沒取到 `updated_at`（`row.updated_at || null`，:4439）時，PUT 退回「後存蓋先存」，而且**沒有橫幅**——使用者不會知道保護失效。屬於 CHANGELOG 已寫的「token 選填」範圍，列觀察。
- **觀察 2：`_refreshUpdatedAt()`（:3735）在有未存編輯時不同步**（設計如此，註解寫明）。因此「我自己在別處的動作（階段 API、deal-tag PATCH）推進了 updated_at」＋「我頁面上有未存編輯」⇒ 下次存檔 409，橫幅出現，要求載入最新版而**丟掉未存編輯**。是已知取捨（寧可 409），但橫幅文案說「可能是其他人，也可能是你在別處的操作」，沒有告訴使用者這時按鈕會丟掉他剛打的字；可考慮「先複製我的修改」說明。

## 2. 票二：勞報單建立寫鎖洩漏（adde4ceb7、850f3d3e2）

規格來源：`modules/payroll/CHANGELOG.md`、測試檔 docstring（真因：`create_payslip` 開頭 `INSERT payslip_seq` 開了隱式寫交易，之後 422／ValueError 沒 rollback 沒 close，鎖留到 GC）。作者 hichan-10、K 審 hichan-9。

### a. 逐條驗收

| # | 規格 | 證據 | 判定 |
|---|---|---|---|
| 1 | 任何錯誤路徑都放掉寫鎖 | `payslips.py:327-404` 整段包進 `with write_txn(conn):`；`write_txn.__exit__`（`core/txn.py`）對例外一律 rollback＋close 且吞掉已關連線的 ProgrammingError，不蓋掉原 HTTPException | 成立 |
| 2 | 422（`body_flag`）、`int()` ValueError 兩條路徑不留鎖 | `test_failed_create_payslip_does_not_leave_the_write_lock` 兩個參數；**變異 A：還原成修前的 payslips.py ⇒ 這兩題紅**（§4），新碼綠 | 成立 |
| 3 | 400 單號格式（本來就自己 close）當對照 | 第三個參數；修前也綠（對照組，符合 docstring 所說） | 成立 |
| 4 | T49 `test_strict_bool_sites` payslip 題穩定紅的真因 | 同一個鎖（422 後第二個 POST 卡 busy timeout）；`test_create_payslip_still_works_right_after_a_422` 綠 | 成立（見假綠燈段） |
| 5 | 範圍乾淨 | diff 只有 `payslips.py`、CHANGELOG、一個測試檔 | 成立 |
| 6 | 連結（派工單）失敗整張不建 | `payslip_links` 的 `LinkError` ⇒ rollback＋close＋raise；`test_payslip_links_t46.py` 9 題綠 | 成立 |

### b. 反向控制

- 失敗路徑：422／ValueError／400 三條都有鎖探針（另開一條連線 `BEGIN IMMEDIATE`，timeout 0.3 秒）。
- 回滾路徑：失敗後 `payslip_seq` 的那列也一併回滾（交易內），之後第二個合法 POST 成功（`…right_after_a_422`）。
- 沒有被測到：**「單號衝突 409」路徑**（`payslips.py` 的 `_insert` 兩次都失敗 ⇒ `HTTPException(409, "勞報單號碼衝突…")`）與**派工單連結失敗**路徑的「鎖被放掉」沒有鎖探針（`write_txn` 結構上保證，但沒有題釘住）。建議 3。

### c. 假綠燈檢查

- 作者自己的測試 docstring 已誠實寫：`test_create_payslip_still_works_right_after_a_422` 在舊碼上是否紅取決於 GC 時機，**不能單獨當守門**；真正的守門是兩個鎖探針參數。我用變異 A 驗證了鎖探針在舊碼上確實紅（2 題），結論與 docstring 一致。
- 這票的修法在 T80（連線收尾網，尚未併 train）之後會**多一層保險**，但本票不依賴它。

### d. 建議／觀察

- **建議 3：** 補一題「兩次 INSERT 都失敗 ⇒ 409 之後鎖是空的」與「派工連結失敗 ⇒ 422/4xx 之後鎖是空的」，用同一個 `_write_lock_is_free()` 探針；現在這兩條路徑只靠 `write_txn` 的結構保證。
- **觀察 3：同檔還有類似形狀的寫入端點沒用 `write_txn`**（`void_payslip`、`record_export`、`record_archive_download`：先 get_db 再 UPDATE／INSERT，例外前多半自己 close；單一語句後 commit，洩漏機率低）。不在本票範圍；T80 的收尾網會涵蓋。
- **觀察 4：`GET /api/next-slip-no`（`payslips.py:210`）是 GET 但會 `INSERT payslip_seq` 並 commit**（讀端點有寫入副作用，且沒有 `try/finally`）。既有行為、非本票引入。

## 3. 票三：自選條件報表（71387f655、0b8235fa6、f91978fe1）

規格來源：`modules/analytics/CHANGELOG.md` 1.0.48、`report_templates.py` 模組 docstring（不變式 7 條）。作者（feature）、K 審 hichan-11（2 必修 3 建議，commit 0b8235fa6）。

### a. 逐條驗收（對模組 docstring 的不變式）

| # | 規格 | 證據 | 判定 |
|---|---|---|---|
| 1 | **金額不重算**：範本只篩選／投影 `reports._collect()`／`_collect_receivable_items()`；業務員績效用 `_sales_perf_rows()` | `report_templates.py` 無任何自己的加總定義（只有 `_collection`＝已收÷應收，與營運報表同定義，註解與測試對帳）；`reports.py` 的重構是**逐字搬移**成 `_sales_perf_rows`／`_dept_perf_rows`（我逐行對 diff：算式、排序、欄位名、四捨五入都不變）；`test_no_conditions_equals_operating_report`、`test_payments_amounts_match_operating_report`、`test_department_filter_matches_operating_report` 綠 | 成立 |
| 2 | 權限沿用 `_require_reports_access`，與營運報表同一道門 | `run_template`／`list_templates`／`excel_template` 都先呼叫；`test_gate_same_as_reports[5 個 URL]`、`test_gate_matches_the_operating_report_gate_for_every_role_module_shape`（逐角色×模組形狀對 `/api/reports/financial` 差分）、`test_pdf_sibling_has_the_same_gate` 綠；**變異 B2（拿掉 run 的閘門）⇒ 8 題紅** | 成立 |
| 3 | 參數一律伺服器端驗證，未知參數 400 | `validate_params`、`_raw_params`（重複鍵 400）；`test_bad_params_are_400` 9 個參數、`test_bad_params_on_excel_are_400_not_a_file`、`test_invalid_excel_request_does_not_burn_the_export_cooldown` 綠 | 成立 |
| 4 | 母體＝已成案／已結案 | `DEAL_TAGS` 只列兩種；`deal_tag=報價中` 400（測試有） | 成立 |
| 5 | 不靜默截斷、不靜默排除 | `truncated`＋notes（`_produce`）；有日期條件時未標日期的案件／款項被排除並寫出件數（`_filtered_cases`、`_run_payments`）；`test_truncation_is_declared`、`test_cases_without_quote_date_are_reported…`、`test_payments_undated_rows_are_reported_not_silently_dropped` 綠；**變異 B5（truncated 恆 False）、B6（不排除不計數）各 1 題紅** | 成立 |
| 6 | Excel：公式中和、匯出冷卻、匯出稽核 | `set_row`→`xl_safe`（`xlsx_out.py:68`）；`test_excel_neutralises_formula_text`（種子有客戶「=1+1」）、`test_excel_is_audited_with_its_conditions_and_rate_limited` 綠；**變異 B4（xl_safe 不中和）⇒ 該題紅** | 成立 |
| 7 | 頁面：文字當文字、換範本作廢舊結果、下載只認上次產出的條件 | `report-templates.html` 無 `x-html`／`innerHTML`；e2e 9 題綠（含 `test_cell_text_is_rendered_as_text_not_markup`、`test_switching_template_while_a_run_is_in_flight_does_not_mix_results`） | 成立 |
| 8 | 登記：路由清單／模組版本／報表中心卡片 | `route_inventory.json` 有 4 條（run／excel／pdf／清單）；`analytics 1.0.48`；`test_hub_lists_the_page_and_it_opens` 綠 | 成立（CHANGELOG 寫「3 支端點」，實際 4 條，見觀察 5） |

### b. 反向控制

- 對方不在（無權限）：財務以外的角色／只有「營運報表」模組但沒有 money_visible ⇒ 403，與營運報表同；e2e `test_account_without_finance_view_sees_explanation` 綠。
- 失敗路徑：9 種壞參數都 400；Excel 的壞請求不消耗冷卻；未知範本 404。
- **我補做的 PDF 姊妹探針**（作者測試只驗閘門，因為「需要 Edge」）：在拋棄式 worktree 寫一題，攔掉 `pdf_gen.html_to_pdf_bytes` 取得送去轉 PDF 的 HTML：`/api/report-templates/case-list/pdf?date_from=2026-05-01&date_to=2026-05-31` ⇒ 200，HTML 內含 5 月的 MQ-T2／MQ-T3、**不含** 3 月 MQ-T1 與 8 月 MQ-T4，條件頁有回顯；`?bogus=1` ⇒ 400。**PDF 確實套用條件**（探針已刪除，沒有留在 repo）。
- 回滾路徑：本票只讀（GET），沒有寫入，無回滾問題；匯出稽核寫入由既有 `export_logged` 負責。

### c. 假綠燈檢查

- 與營運報表「對帳」的題用的是**同一份 `_collect()` 結果**——這是設計（金額不重算），但意味著這些題證明的是「範本沒另外加工」，**不證明 `_collect()` 本身正確**（那是營運報表既有測試的責任）。作者在 K 審修正後加了「手算收款率」題（`test_headline_collection_rate…`）補這個洞；我用變異 B3（四捨五入位數）驗證它抓得到。
- 種子資料含真實形狀（多期、無收款期別、無報價日、已收沒實收日、未來日期），不是只有單期乾淨資料，這點做得好。
- 沒有找到驗到自設值的斷言。

### d. 建議／觀察

- **建議 4：PDF 姊妹沒有功能測試**（只有閘門題）。我的探針證明現在是對的，但沒有題釘住「PDF 套用條件」；用攔 `html_to_pdf_bytes` 的作法不需要 Edge（本檔 §b 的探針可直接收編，約 20 行）。
- **建議 5：每次請求都呼叫 `_collect("0000-01-01","9999-12-31",…)` 全量重算**（`_filtered_cases`、`_run_payments` 的 `_collect_receivable_items`），再在記憶體裡篩選。與營運報表同量級，目前資料量沒問題；但條件越窄越浪費，且 `MAX_ROWS=20000` 是**輸出**上限，不是掃描上限。資料成長後列為效能待辦即可，不影響這次出貨。
- **觀察 5：** CHANGELOG 寫「3 支端點」，路由清單有 4 條（含 PDF 姊妹，平台規則自動加）；文件小誤差。

## 4. 變異檢查結果（11 個變異，全部被抓到）

| 代號 | 票 | 改壞了什麼 | 結果 |
|---|---|---|---|
| A | 二 | `payslips.py` 還原成修前版本 | 2 題紅（422、ValueError 的鎖探針） |
| B1 | 三 | 日期上界改成不含迄日 | 1 題紅（`test_case_list_filters`） |
| B2 | 三 | `run` 端點拿掉權限閘門 | 8 題紅 |
| B3 | 三 | 彙總收款率四捨五入位數改成 0 | 2 題紅 |
| B4 | 三 | `xl_safe` 不再中和公式 | 1 題紅（`test_excel_neutralises_formula_text`） |
| B5 | 三 | 截斷旗標恆為 False | 1 題紅 |
| B6 | 三 | 無報價日案件不排除也不計數 | 1 題紅 |
| B7 | 三 | 業務條件被忽略 | 2 題紅 |
| C1 | 一 | 橫幅出現時不暫停自動存檔 | 1 題紅 |
| C2 | 一 | 新單 POST 409 也當成編輯衝突 | 1 題紅 |
| C3 | 一 | `loadQuote()` 成功不清橫幅 | 2 題紅 |

每個變異都是單點修改、改完用 `git checkout` 還原；稽核結束時 worktree `git status` 乾淨。腳本：`D:\Claude-pm\t79-audit-mut.sh`，輸出：`D:\Claude-pm\t79-audit-mut.log`。

## 5. 發現清單（三級）

### 必修
（無）

### 建議
1. **鎖稽核文件少列 13 條路由**（票一的文件交付物）：`docs/platform/WRITE-ENDPOINT-LOCK-AUDIT-T79.md` 宣稱 99 條、「逐條分類」，實際 `modules/case/api/*.py` 有 **112** 條寫入路由。少的 13 條都是用 `_BASE + "/…"`／`_CHG + "/…"` 常數組路徑：`material_approvals.py`（submit／approve／reject／withdraw／cancel／receive×2＝7）、`material_changes.py`（changes／revise／submit／approve／reject／withdraw＝6）。產文件的掃描只認字面字串。這 13 條大多是狀態機（T 類），`revise_change` 在 `begin_write` 內讀後改，且 `MC.revise` 有狀態檢查，風險不大，但文件的「99」與「已涵蓋全部」是錯的；補上並註明掃描方法（含 `_BASE` 這類常數路徑）。
2. **衝突橫幅的「載入最新版」不是真的丟棄**（`Object.assign` 合併；§1-d）。補取代語意或補一題「被丟棄的本機修改不得復活」。
3. **票二：補兩題鎖探針**（單號衝突 409、派工連結失敗）。
4. **票三：PDF 姊妹補功能測試**（攔 `html_to_pdf_bytes`，免 Edge）。
5. **票三：`_collect` 全量重算**列效能待辦（現況不阻擋）。

### 觀察
1. `_lastUpdatedAt` 為 null 時樂觀鎖無聲失效、沒有橫幅（票一）。
2. 有未存編輯時不同步 `updated_at` ⇒ 自己的動作也會造成 409＋橫幅，按鈕會丟掉未存編輯，文案沒說（票一）。
3. `payslips.py` 其他寫入端點（void／record_export／record_archive_download）沒用 `write_txn`（票二；T80 收尾網涵蓋）。
4. `GET /api/next-slip-no` 有寫入副作用（票二，既有）。
5. 報表範本 CHANGELOG 寫 3 支端點、實際 4 條（含 PDF 姊妹）（票三）。

## 6. 稽核的限制

- 範圍是三張票的 diff，不是 `55835216..tip` 的全部 154 個 commit；其他 commit（含我自己的 T79 維運票、LINE 通知、EXIF、版本紀錄）不在本稽核內。
- 票一的 e2e 在 Chromium 跑，沒有真的第二個瀏覽器分頁（用 API 當第二位編輯者）；沒有實機瀏覽器（Safari／手機）驗證。
- 票三只驗了 3 個範本、一組種子（9 筆案件）；沒有大量資料（`MAX_ROWS` 截斷是用小上限／測試覆寫驗的）。
- PDF 探針攔截了 `pdf_gen.html_to_pdf_bytes`，驗的是「送去轉 PDF 的內容」，不是 Edge 實際渲染的 PDF 外觀。
- 變異檢查是我挑的 11 個點，不是窮舉；沒被變異到的程式碼不代表有測試保護。
