# AUDIT-0C — 第 35b 班標案雷達熱修（`origin/wip/t35b-tender-parser` @`f85e25fb`，作者 hichan-d5）

- 範圍：`git diff origin/platform...origin/wip/t35b-tender-parser`（20 檔，+1826/−24）。唯讀；稽核者 hichan-0c，2026-10-03。
- 方法：讀碼；自寫情境探針（未入庫、已刪，附錄 B）；突變 3 條；官方 CSV 逐列比對（2 個 GET，各 1 次）；目標測試單程序 `-n 1`（non-e2e：tender_radar/tests＋L1/L2 守門測試，409 passed，basetemp 已刪）。

## 結論

**PASS（可出貨）。** 無會漏信／誤寄／越權的缺陷。2 項建議（非阻擋）：**F1** 一個守門條件的測試缺口（突變存活）、**F2** 假日表 2028 年維護提醒只在日誌與頁面。

## (1) 漏信（最優先）

- 唯一的新閘在 `_notify_found` 最前面：`if no_mail_today()[0]: return False`。它在 `_remember_first_scan`、`_load_unnotified_hits`、`notify_tender_found`、`_mark_hits_notified` **之前**就返回 ⇒ 不寄信日**完全不碰** `tender_hits.notified_at`；`run_scheduled_scan` 只在 `_notify_found` 回 True 時才寫 `NOTIFY_MARK_SETTING`（時段標記）⇒ 假日不會標記時段。
- `_mark_hits_notified` 只在 `notify_tender_found` 沒丟例外之後呼叫（既有路徑，本班未動）；判準仍是「有沒有未通知的命中」，所以週末掃到的標案不會因 `INSERT OR IGNORE` 而消失。週末**照常掃描**（決策正確：列表是「當日」查詢）。
- 自建情境（真實寄信路徑、僅 stub SMTP 層 `_send_raising`；附錄 B）：
  1. 掃 09／寄 18（兩者不重疊）。**2026-10-09（補假，週五）09:00 掃到 3 筆** → 當日 18:00、週六、週日各時段皆未寄、3 筆保持未通知、時段標記未設 → **週一 10-12 09:00（非寄信時段）未寄** → **10-12 18:00 寄出 1 封（3 筆），全數標記已通知；同時段再觸發不重寄**。✔
  2. 週六掃到 → 週一寄信時 SMTP 掛掉：命中保持未通知、時段未標記；週二重試成功寄出 1 封、命中清空。✔
  3. 涵蓋範圍外／壞表：`2028-01-03`（週一）可寄、`2028-01-01`（週六）不寄、`covered()`＝False；`data={}`（讀不到表）只擋週末，不丟例外；`2026-10-09`、`2027-10-11` 皆「國定假日：補假」，`2026-10-12` 可寄。✔
- 殘餘風險（可接受）：沒有「延後上限」。若假日表被改壞到連續標成假日，信會一直延後；結構上只能標單日、且為一次性轉出的受控檔，`next_mail_day()`（有 30 天上限）目前僅是公用函式、正式碼未使用。
- 次要觀察：不寄信日提早返回使 `_remember_first_scan`（靜默期起算）延到第一個可寄信日的呼叫；只影響「首次啟用」的起算日，與漏信無關。

## (2) 假日資料

- 官方 CSV 重抓（各 1 個 GET，HTTP 200，無重試）：2026 `6499 bytes`／sha256 `0edd80d3…f00d`；2027 `6511 bytes`／sha256 `e30df188…cf3`；**皆與檔內記錄逐字相同**（也各 365 列、欄位 `西元日期,星期,是否放假,備註`、旗標僅 0／2）。
- 逐列比對（腳本 `cmp.py`，附錄 A）：以 CSV 重推「平日放假日＋名稱」與「週末上班日」，對 `holidays_tw.json`：2026（16 筆）**diff＝空**；2027（17 筆）**diff＝空**；補班日兩年皆無，檔內亦無 ⇒ **diff＝空**。
- 補假日：`2026-10-09`（週五，補假）、`2027-10-11`（週一，補假）皆在表內且為官方 CSV 的 `2`／`補假`。
- 規則（`calendar_tw.no_mail_day`）：補班日先判（可寄）→ 週六日不寄 → 表內平日放假不寄 → 其餘可寄；年份不在表內 ⇒ 只能辨識週末、`covered()`＝False；頁面與每日日誌會提示（見 F2）。邏輯 sound。

## (3) 告警語意

- `_is_empty_result_row`：單格＋「無符合條件資料」才算空結果；`suspect_redesign(0,0)`＝False，空日不再誤報；真壞的列（格數不對／內容怪）仍算 dropped，「十列九列壞」仍 suspect。`list_state` 要求頁面真的說了無資料才標 `empty_day`。
- 每個 key 一天最多一封（`ALERT_DAY_SETTING`）；不寄信日只記待寄，下一個可寄信日**條件仍成立**才補寄，已恢復者從待寄清單移除。
- **突變（附錄 C）**：M2（關掉每日去重）→ 1 failed（`…mails_once_and_not_again_the_same_day`）✔被抓到；M3（待寄不看條件是否仍成立）→ 2 failed ✔被抓到；**M1（拿掉 `len(cells)==1`，只剩字樣判斷）→ 23 passed，存活 ✘**（見 F1）。

## (4) 狀態 API／頁面

- `/api/tender-radar/status`：`_require_radar`（登入＋`tender_radar` 模組）；測試 `assert … in (401, 403)` 已覆蓋（我跑的 409 題包含）。`notices` 只含狀態與「上次抓取解析／失敗筆數」，不含標案內容；`tenderCount` 為既有欄位。
- 前端：`<div x-text="n.text">`、`x-text` 圖示；測試斷言區塊內無 `x-html`／`innerHTML`；地點「未取得」為靜態字串，`t.location` 走 `_esc`。✔

## (5) 通知偏好

- `EVENT_GROUPS` 加 `tender_detail_blocked`；`is_enabled` 的語意是「**不在使用者靜音名單就開**」⇒ 既有使用者預設為**開**；`tender_source_changed` 的靜音與它互不影響（各自 key；`notify.py` 以獨立 key 取收件人）。`tests/test_notification_prefs_coverage.py`、`test_mail_registry`、`test_mail_send_registered` 皆通過。

## (6) 驗證碼行為

- 偵測在 `fetch_detail`（兩字樣皆有且沒有詳細頁欄位 id）→ 回 `(None, CAPTCHA_ERROR)`；呼叫端 `break` 並記狀態。
- 全 `tender_radar` 程式碼：`fetch_detail` 只有 `_fetch_details` 一處呼叫；`User-Agent` 為固定常數 `USER_AGENT`（無輪替）；無重試／睡眠後重打／繞過；同日第二次起 `_detail_blocked_today()` 直接 `return 0`，隔天最多試 1 次。✔

## (7) L1／L2 邊界

- `helpers/notification_prefs.py` 只加一行事件清單；與既有 `tender_found`／`tender_fetch_failed`／`tender_source_changed` 同一作法（亦有 `ensure_event` 自動併入機制，不加也行；加了與前例一致）。模組邏輯（日曆、假日表）全在 `modules/tender_radar/`；假日表到期檢查刻意放模組內而非 `helpers/system_checks`。`docs/platform/modules.json` 已登記 `mod:tender_radar/calendar_tw`；`tests/platform/test_module_boundaries.py`、`test_core_only_rc.py` 通過。

## (8) autouse conftest

- `_mail_day_independent_of_the_real_weekday` 把 `source.no_mail_today` 釘成 `(False, None)`，除非測試模組宣告 `USES_REAL_CALENDAR = True`（3 個檔：state／notices／calendar 相關，自行注入 `today`／`now_dt`）。
- 遮蔽風險：其他檔不再測「閘真的會擋」，但**反向側有 3 檔真實日曆測試＋我的情境探針**覆蓋閘本身；若閘誤擋平日，`test_a_weekday_still_mails_normally` 會紅。`api._source_notices` 在其他檔也走被釘住的函式（不出現 no_mail_day 提示），不影響其斷言。模組外的測試未呼叫排程／寄信路徑（grep 無週別相依）。可接受。

## 發現

- **F1（建議，非阻擋）**：`source._is_empty_result_row` 的 docstring 宣稱「必須同時滿足只有一格與字樣」，但**測試沒有鎖住「只有一格」**：突變拿掉 `len(cells) == 1` 後 23 題全綠。現有題只覆蓋「單格但別的字」「空列混壞列」。補一題：**多格列且第一格含「無符合條件資料」仍算 dropped**。實害極低（資料列第一格是流水號，不太會含該字樣），但那條件正是為防「改版時被放行」而存在。
- **F2（建議）**：假日表涵蓋到 2027-12-31；過期後（2028 起）國定假日平日會照常寄信。已有每日日誌（到期前 60 天起）與頁面提示，但沒有寄信告警。官方通常年中公布次年表 ⇒ 建議在維護清單登記「2027 年中取 116→117 年 CSV 更新 `holidays_tw.json`」。

## 附錄

- A．`cmp.py`：以 `csv` 讀兩份官方檔 → 平日 `是否放假=2` 對 `years[y].holidays`（含名稱）、週末 `=0` 對 `makeup_workdays`；輸出 `holiday diff … EMPTY`、`makeup diff: EMPTY`（2026、2027）。
- B．情境探針 `test_zz_audit0c_probe.py`（未入庫）：`test_disjoint_hours_holiday_then_weekend_then_monday`、`test_monday_send_failure_keeps_hits_and_slot_unmarked`、`test_notify_only_hour_on_makeup_or_outside_coverage`，3 passed。
- C．突變（皆還原）：M1 `return EMPTY_RESULT_MARKER in _text(cells[0])`→存活；M2 `_alert_sent_today` 恆 False→1 failed；M3 `due` 去掉 `cond[k]`→2 failed。
