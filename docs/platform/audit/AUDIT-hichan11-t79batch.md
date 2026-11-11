# AUDIT hichan-11：T79 批次（LINE 通知＋LINE Login 綁定／自選條件報表）

- 稽核對象：`train/t79-int` tip **73672373a**（MOTRIX-ERP 指定；`origin/train/t79-int` 目前仍是 1f00ab62c，兩者只差重產 dep_graph／UNIT-INDEX／test_map，程式碼相同），對 prod 基準 `55835216`。
- 日期：2026-11-12。稽核者：hichan-11。方式：讀碼＋既有測試重跑＋自寫探針（13 題，附於 `AUDIT-hichan11-t79batch-probe.py.txt`，只在稽核樹跑，不進產品測試）。
- **獨立性聲明**：
  - 第 1 群（LINE）：我沒參與過，**獨立稽核**。
  - 第 2 群（自選條件報表）：`0b8235fa6`「K 審修正（hichan-11）」就是我的 K 審，我**不具獨立性**。本報告該群只做「前審者複驗」（我當時提的修正是否仍在、反向控制重跑），**不算 §G7-3 獨立稽核**；MOTRIX-ERP 已改派 hichan-12 做獨立稽核。
- 沒有修改任何產品程式；探針檔在稽核樹內（未追蹤→本報告所在分支只帶文件與 `.py.txt` 副本）。

## 0. 結論

| 層級 | 件數 | 摘要 |
|---|---|---|
| **必修** | **0** | 未登入面沒有找到可利用的缺口（見 §1.2）。 |
| 建議 | 4 | S1 已登入者可耗盡全站對外查詢額度；S2 綁定寫入成功卻回「失敗」；S3 綁定表為單一 JSON，一次暫時性讀取失敗會抹掉所有人；S4 兩支測試的假綠燈風險。 |
| 觀察 | 6 | QR 是 10 分鐘的持有者憑證、亂猜 state 無痕跡、回調同步佔用執行緒最長約 30 秒、鎖內寫 DB、`line_links` 進每日匯出、未驗證項目。 |

可以凍結：LINE 群沒有必修項。S1～S3 建議在 T79 之後的下一班處理（都不是未登入可打、不洩漏資料）。

## 1. 第 1 群：LINE 通知＋LINE Login 綁定（獨立稽核）

範圍：`helpers/line_notify.py`、`helpers/line_login.py`、`routers/system.py`（`/api/line/*`、`/api/settings/line-notify*`）、`main._PUBLIC_API_PATHS`、`archive.py`（匯出）、`email_notify.send_registered`（收件人收集）、`routers/auth.py delete_user`。

### 1.1 (a) 逐項驗收（規格 → 證據）

| 規格（line_login／line_notify 不變式） | 結果 | 證據 |
|---|---|---|
| ② state：32 byte 隨機、單次使用、10 分鐘、只存雜湊、每人 3／全域 200 | ✅ | `line_login.py:120,132,194`（`pop` 在鎖內）；探針 P4：兩執行緒同 state → 只有一個 `linked`，LINE token 端點只被打 1 次 |
| ③ 綁定對象＝發起人，登出／停用不綁 | ✅ | `_initiator_ok` `:154-169`；既有測試 `binding_follows_the_initiator…`、`inactive_user_is_not_linked`；與 `auth_middleware`（`main.py:575-592`）逐項比對：多出的只有閒置逾時，而 `start` 那次請求已刷新 `last_active`，10 分鐘 TTL 內不可能跨過閒置上限（無缺口） |
| ④ code→id_token→verify，aud／nonce／sub 格式 | ✅ | `_exchange :172-185`；nonce 不符／aud 不符／sub 格式錯皆回 None（既有 `line_side_failures` 參數化題） |
| ⑤ 純結果頁、不含 ERP 資料、不寫 code／state／secret 進 log | ✅（見 S4 對測試強度的保留） | `system.py:2802-2812`（固定 HTML、無反射輸入；`no-store`／`no-referrer`／CSP `default-src 'none'`）；`complete()` 只記例外型別 |
| ⑥ 唯一對外呼叫 `_post_form` | ✅ | HTTPS 常數 base、`urlopen` 預設驗憑證、secret 走 POST body 不在網址 |
| ⑧ 限流只算有效 state | ✅ 對未登入者／⚠️ 對已登入者（S1） | `rate_ok` `:91-99`、`complete :210`；既有 `garbage_requests_never_count…` 有正對照（最後一筆有效 state 成功） |
| 公開路徑只有 callback 一條 | ✅ | 探針 P1：`/api/line/callback/`、`/x`、`callbackx`、大小寫、`/api/line/binding` 未登入皆 401/404；POST/PUT/DELETE/PATCH callback ＝405 且不呼叫 `complete` |
| 設定頁 GET 遮罩、PUT 遮罩值＝保留、匯出挖掉 | ✅ | `system.py:2695-2696,2734,2749`；`archive.py:2249` `json_remove(...channel_access_token, login_channel_secret)`；既有 `secret_is_masked_kept_audited…` |
| 開發機標記擋 LINE 推播（驗證／額度唯讀刻意不擋） | ✅ | `_machine_may_send`；既有 `dev_marker_blocks_push…` |
| 刪除帳號同時解綁 | ✅ | `auth.py:1716-1722`（commit 之後；失敗只記 log） |
| 收件人＝信件最終收件人、停用者不收 | ✅ | 探針 P8：`active=0` 但綁定仍在 → `_users_emails`（`active=1`）已排除，不推播 |
| 內容不帶金額 | ✅ | 兩個已接線事件只有單號／客戶／設備／日期／編輯人／變動欄位名（`review_edit_notify.py:30-34`、`_warranty_expiry_mail`） |

### 1.2 未登入面（你點名的重點）

- **callback 濫用**：未登入者能做的只有「查不到 state」→ 400 固定頁。亂猜 32 byte state 不可行；不花對外成本、不計限流（探針與既有題）。state 單次，進 access log 的 code／state 在到達限流前已銷毀（每個請求要嘛 state 不存在、要嘛已被 `pop`）。✅
- **state／token 洩漏**：回應不反射任何輸入；設定 GET 遮罩；`push`／`verify_token`／`complete` 的例外只記型別；channel token 格式不合一律不送（避免 `Invalid header value b'Bearer …'` 帶出整串）。✅
- **限流是否真的守住**：對**未登入**守住；對**已登入的一般帳號**沒有（S1）。
- **綁定失敗路徑**：不論哪一步失敗 state 都已銷毀，不綁；已綁在別人的 LINE 帳號被拒（`link_user` 鎖內檢查）；唯一不一致見 S2。

### 1.3 (b) 反向控制（對照組不在／失敗路徑／回復路徑）

| 控制 | 結果 |
|---|---|
| 同 state 並發 | P4 ✅ 只一個贏 |
| 非 callback 路徑／其他 HTTP 方法 | P1／P1b ✅ |
| demo 帳號 token（只在 demo 庫）走 callback | P5 ✅ `session_ended`、不打 LINE、`_hits` 不增（`_initiator_ok` 在 `rate_ok` 之前，次序是對的） |
| 停用者的舊綁定 | P8 ✅ 不推播 |
| LINE 未設定／無對外網址 | 既有 `start_needs_login_and_complete_configuration` ✅ |
| 重啟（記憶體 state 消失） | 設計：使用者重按；`start_server.ps1` 沒有 `--workers`（單一行程）✅；多 worker 時綁定流程會壞——文件已寫，維持觀察 |
| 回復：解除綁定／超管代解／刪帳號 | 既有題＋`auth.py` 讀碼 ✅ |
| 設定寫入遇讀取失敗 | **P7 ❌（S3）** |
| 寫入後記帳失敗 | **P3 ❌（S2）** |

### 1.4 (c) 假綠燈

1. `test_no_code_state_secret_or_id_token_in_logs`：
   - 只收 logger 名首段在 `helpers／routers／main／db` 的紀錄，`modules.*`、`core.*` 漏看；
   - 沒有正對照（沒斷言「log 裡真的有東西」）：若 `complete()` 完全不記 log，這題一樣綠，無法證明「不記」是設計還是空集合；
   - 沒走例外路徑（`_post_form` 丟帶 secret 字樣的例外）也沒查 `audit_log.detail`／`target_id`。
   → 現行程式碼讀起來是對的，但這題單獨不足以防回歸（S4）。
2. `test_rate_limit_applies_to_valid_states_and_burns_the_state`／`garbage…`：把 `CALLBACK_RATE_LIMIT` 改成 2／3，且 `START_INTERVAL=0`（夾具預設）。在真實節流（每人每 3 秒）下「已登入者能不能耗盡額度」沒被建模——P1／S1 就是這個縫。
3. `test_start_is_throttled_per_user` ✅ 有正對照（別人不受影響、時間推進後可再發起）。
4. 其餘登入流程題有正反兩面，未見假綠。

### 1.5 (d) 改善建議

**必修：無。**

**建議**

- **S1（已登入者耗盡全站額度）**——探針 P2（RED 即證實）：3 個一般帳號各依 `START_INTERVAL=3 秒`發起，60 秒內產生 60 個有效 state 配垃圾 code，真的打了 60 次 LINE token 端點，全站 60/分額度用完，第 4 位正常使用者綁定得 429。影響：綁定功能被擋（不洩漏資料、不能綁別人）；同時對 LINE Login channel 製造垃圾呼叫量。不變式 ⑧ 的敘述「攻擊者不能把所有人擋在外面」只對未登入者成立，文件應如實改寫。建議：額度改「每發起人」計（`rec["username"]`，另留較大的全站上限），或 `rate_ok` 之前先檢查該 state 的發起人當前 10 分鐘內失敗次數、連續失敗者停權一段時間。
- **S2（綁定已寫入卻顯示失敗）**——探針 P3：`link_user` 成功後 `set_confirmed`（寫設定）丟例外 → `complete()` 的總 `except` 回 `failed`；手機顯示「綁定失敗」、電腦設定頁卻 `linked=True`。建議：`link_user` 之後的收尾（`push`／`set_confirmed`）各自 try/except，一律回 `linked`（confirmed 記不下來＝None）。
- **S3（單一 JSON 綁定表＋讀取失敗＝空表）**——探針 P7：`_get_setting` 對 `execute` 階段的任何例外（locked／I/O／JSON 壞）回預設值 `{}`（`settings.py:20-30`；`get_db()` 連線失敗倒是會拋，不被吞）；`link_user`／`unlink_user`／`set_confirmed` 都是 讀→改→寫整份 `line_links`，所以一次暫時性讀取失敗就把**所有其他人**的綁定覆寫成只剩這一筆，沒有錯誤訊息。後果：通知靜默停掉，需全員重綁。機率低（WAL 讀取很少失敗），但是靜默資料遺失。這是 `_get_setting` 既有慣例，並非 T79 新增；`PUT /api/settings/line-notify` 同樣（token／secret 會被清成預設）。建議：這三個 RMW 用「會拋例外」的讀取（自己 `SELECT` 不吞），失敗就整次拒絕；或長期把綁定改成資料表（T79 文件已寫到這一步）。
- **S4（測試強度）**——見 §1.4 第 1、2 點：log 檢查加正對照與 `modules`／`core` logger，補例外路徑與 `audit_log` 欄位；限流題補「真實節流下多帳號」一題（可直接採用探針 P2 的形狀）。

**觀察**

- O1：授權 QR（`authorizeUrl` 內含 state＋nonce）10 分鐘內是持有者憑證——誰掃誰就被綁到發起人的帳號（設計如此：「電腦發起、手機授權」）。若使用者把 QR 截圖貼進群組或分享螢幕，該 LINE 會綁成他的通知收件人。設定頁已顯示綁定狀態；建議畫面加一句「請只用自己的手機掃描」。
- O2：亂猜／過期 state 不留應用層痕跡（探針 P6：30 次亂打，`audit_log` 無 `line.*`、無 WARNING）。目前只有 uvicorn／Tunnel access log。要偵測掃描需另加計數。
- O3：callback 是同步路由（執行緒池）：`token`10 秒＋`verify`10 秒＋確認訊息 `push`10 秒，最壞約 30 秒佔一條執行緒（LINE 服務變慢時）；每分鐘最多 60 筆被限流，可接受。
- O4：`link_user`／`unlink_user`／`set_confirmed`／`PUT line-notify`／`set_event` 共用 `_lock`，且在鎖內做資料庫寫入；DB 忙時寫入等待最長 30 秒會讓同鎖者排隊（沿用 T80 稽核對「鎖內寫 DB」的警告，量小不致命）。
- O5：`public_base_url` 只有超管能設，任意 https 網域皆可（`normalize_public_base` 不比對 Tunnel 網域）；超管被盜時 authorize 的 redirect 會帶 code 到別處。LINE Console 已登記的 Callback URL 是第二道（LINE 會拒絕未登記的 redirect_uri）。
- O6：每日 JSON 匯出含 `line_links`（帳號⇄LINE userId 對照）。userId 不是祕密但屬個資等級，與 email 同級，維持現狀即可；secret／token 已挖掉（已驗）。

**未驗證（超出稽核樹能證明的）**：真實 LINE 端點行為（Login／Messaging channel 同 Provider 與否）、Cloudflare Tunnel ingress 的精確比對設定、Tunnel／uvicorn access log 保存期限與是否記 query string。以上需正式機側確認。

## 2. 第 2 群：自選條件報表（前審者複驗，**非獨立**）

範圍：`modules/analytics/api/report_templates.py`（新）、`reports.py`（抽出 `_sales_perf_rows`／`_dept_perf_rows`）、`frontend/pages/report-templates.html`。

| 你點名的重點 | 複驗結果 | 證據 |
|---|---|---|
| 權限與營運報表同一道門 | ✅ | 三支端點（清單／run／excel）皆 `_require_user` ＋ `_rp._require_reports_access`（`report_templates.py:335-355,389-390`）；同一函式為 T68 閘門（財務角色，或 reports 模組＋money_visible）；測試 `:131,142` 驗 403 與訊息 |
| SQL 注入／參數化 | ✅ | 檔內只有兩支固定 SQL（`departments` 清單、部門 id 驗證），**使用者參數不進 SQL**：全部在記憶體對 `_collect()` 結果篩選；參數白名單（未知參數 400、日期 `YYYY-MM-DD`＋`fromisoformat`、部門須存在、列舉值白名單、文字長度上限 40） |
| 金額遮罩真的有套 | ✅（沿用） | 範本不重算金額，來源是同一個 `_collect()`；能進來的人本來就看得到全公司金額（T68）。**沒有**逐案權限縮減——與營運報表一致（母體＝已成案／已結案）。Excel 匯出走 `export_logged`＋`check_export_rate`＋`xl_safe`（公式字串中和，測試 `:333-341`） |
| 重構不改營運報表輸出 | ✅ | `reports.py` 的 `_sales_perf_rows`／`_dept_perf_rows` 是逐字搬移（基準版 `dm`／`sm` 只在被搬走的區段使用，grep 驗證）；50 題（範本）＋營運報表既有題重跑全綠 |

反向控制與假綠燈：複驗 `0b8235fa6` 提交訊息列的修正：收款率定義與營運報表一致（`report_templates.py:166`、測試 `:386` 手算 47.7）、重複條件鍵回 400（`:321`、測試 `:458`）、Excel 先驗條件再進冷卻（測試 `:465-471`，好請求仍 429＝有正對照）仍在碼中且有對應測試；其餘（換範本作廢、無報價日註記）靠 e2e／同檔測試，本次只重跑單元（50 題綠），e2e 未跑。**本群我不提出新的必修／建議**；獨立稽核請以 hichan-12 的報告為準。

## 3. 重跑的證據

- 既有 LINE 三個檔：`tests/platform/test_line_login_t79.py`＋`test_line_notify_t79.py`＋`test_line_notify_review_fixes_t79.py` ＝ **97 passed**。
- 探針 13 題 ＝ **13 passed**（其中 P2／P3／P6／P7 是「斷言壞結果發生」＝證實缺口；P1／P1b／P4／P5／P8 是反向控制綠燈）。
- 報表：`modules/analytics/tests/test_report_templates_2026_11_11.py` ＝ **50 passed**。
- 全部序列執行、`--basetemp` 與 `TMP` 在 `D:\Claude-pm\qse-tmp\t79tmp`；未碰 e2e、未跑全量回歸（那是 hichan-12 的範圍）。
