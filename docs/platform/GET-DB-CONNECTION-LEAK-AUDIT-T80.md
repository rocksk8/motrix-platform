# get_db() 連線未關閉：全後端風險分級稽核（T80 backlog）

- 稽核對象：`origin/train/t79-int` @ `8ab645ef0` 的 `backend/**`（排除 tests／`__pycache__`／data）
- 稽核者：hichan-11（K 組）　日期：2026-11-11
- 性質：**唯讀稽核**。沒有改任何產品程式碼、沒有重寫 426 個站點；只標「值得先處理」的候選。
- 工具與原始資料：`D:\Claude-pm\qse-tmp\conn-audit\`（`scan.py`、`sites.json`、`ranked.json`、`leakplug.py`、`pc.json`）

## 0. 結論（先看這段）

1. **沒有發現「現在就在發生」或「即將發生」的鎖漏。** 沒有立即回報 PM 的項目。
2. 唯一一個真實案例仍是 hichan-10 找到的 `create_payslip`（`adde4ceb7` 已修，改用 `core.txn.write_txn`）。整個後端用同一把尺量，**沒有第二個同級的站點**。
3. 比較值得先處理的不是個別端點，而是**機制**：洩漏的連線不會立刻被回收（見 §3），所以「寫入後丟例外、沒 rollback／close」的寫鎖會留到不確定的時間，下一個寫入卡滿 30 秒 busy timeout 後回 500 `database is locked`。端點層級逐一修不完（969 個站點），建議做**請求層級的收尾網**（§7 R1），一次蓋掉所有未來會再長出來的同類站點。
4. 正式機 4 個月只出現 2 次 `database is locked`，兩次都是「持寫鎖時又開第二條連線去寫」（B 類，§4），不是多人併發；這兩條路徑現行程式碼都已把 `_audit`／`_notify` 移到 commit／close 之後（9/15 的修正），本次靜態＋人工複核沒有找到同型的未修站點。
5. 靜態掃描的 17 個 B 類候選（持寫鎖呼叫自開連線寫入的函式）→ 修正掃描器的支配（dominance）判斷後剩 11 → **人工逐筆讀碼，全是誤報或已緩解**（§4）；僅留 1 個潛在 L 級（`recyclebin/jobs.py run_daily`，§4.3）。

## 1. 方法與限制

### 1.1 靜態（AST）
`scan.py` 掃全部 `get_db()`／`get_demo_db()` 站點，共 **969 個**（與 db.py 註解的「562 個呼叫、426 個裸用」不同——我把同一函式內多次呼叫、`return get_db()` 工廠、行內用法都分開算）。

每個站點判：

- 寫入／讀取：字面 SQL 是 INSERT／UPDATE／DELETE／REPLACE／CREATE／DROP／ALTER／BEGIN／VACUUM／SAVEPOINT、`begin_write(conn)`、`executescript`；以及「把 conn 傳給會寫入的 helper」（以函式名做不動點推導，`writer_by_name`；內部自己 commit 的 helper 當作釋放點，`commit_by_name`）。
- 保護：`try/finally` 內 close／rollback、寬例外處理內 close、`with write_txn／closing／db_conn(conn)`、`with conn:`。
- 暴露：第一個未保護寫入之後，沿同一條直線路徑，到下一個「釋放（commit／rollback／close）」之前，是否出現 `raise`／`return`（`covered()`）。
- 窗口：第一個未保護寫入到下一個 commit 之間，有多少「非 conn 本身」的呼叫、其中多少名稱屬於可丟例外（`int`、`HTTPException`、`json.loads`、`body_flag`……）。
- B 類：持寫鎖（含 `write_txn` 區塊）之後，呼叫「自己開連線並寫入」的函式（`self_writer`，467 個）或把 conn 傳進去又會自開連線的 helper（`nested_helpers`）。

### 1.2 分層

| 層 | 意義 | 站點數 |
|---|---|---|
| H0 | 寫入後既沒 commit 也沒 close（正常路徑也漏鎖） | 0 |
| H1 | 未保護寫入之後，有未被釋放覆蓋的 raise／return | 7 |
| M1 | 未保護寫入＋窗口內有其他呼叫（非預期例外會漏鎖） | 91 |
| L1 | 未保護寫入、窗口極小 | 44 |
| R1／R-pass | 只讀、沒關（漏 fd，不持鎖） | 16／58 |
| S-w／S-r | 已保護（寫／讀） | 287／463 |
| FACTORY | `return get_db()` 工廠，風險在呼叫端 | 3 |

### 1.3 動態偵測（`leakplug.py`）
pytest plugin：`db._connect` 的 `factory` 換成 `sqlite3.Connection` 子類，建立時記下產品程式碼的呼叫堆疊；`__del__` 時若沒 `close()`，記一筆事件並註明**回收當下是否仍在交易中**（`in_transaction`＝持寫鎖）。每個測試 teardown 做 `gc.collect()`。不改任何被測程式。結果見 §5。

### 1.4 限制（請照這個打折讀）
- 靜態掃描看不到「動態組出來的 SQL」「透過 `executemany`／`cursor` 另存變數」的寫入；我用 positive control 校準過 `execute`／`executemany`／`executescript`，其他寫法有漏判可能。
- 掃描器按**函式名**配對 helper，同名不同檔會誤配；上面 B 類誤報有一部分來自這個。
- 動態偵測只涵蓋測試走到的路徑；e2e 沒跑（機器負載規則）。
- 「人工判定」只讀過 §2、§4 列的站點，不是 969 個全讀。

## 2. 校準：用已知壞站點驗尺

把修復前的 `create_payslip`（`git show adde4ceb7^:backend/modules/payroll/api/payslips.py`）餵給掃描器：

| 站點 | 結果 |
|---|---|
| 修復前 `create_payslip` | **M1 第 1 名**：27 個呼叫夾在寫入與 commit 之間，其中 9 個可丟例外 |
| 同層其他 | 之後最多 3 個可丟例外 |

**重要教訓**：它不是 H1。它的明確 `raise` 路徑本來就都有 `close()`；真正的洞是**非預期例外**（`body_flag` 的 422、`int()` 的 ValueError）出現在大窗口內。所以判別式是「**未保護寫入＋大窗口的可丟例外呼叫**」，不是「寫入後有明確 raise」。H1 的 7 個因此不是重點（全部人工看過，見 §2.2）。

### 2.1 M1 前段人工判定（依窗口可丟例外數）

| # | 站點 | 判定 | 理由 |
|---|---|---|---|
| 1 | `payroll/api/payslips.py:326 create_payslip` | **已修**（`adde4ceb7`） | 即已知案例 |
| 2 | `case/api/quotation_stages.py:150 apply_stage_template` | 低 | `begin_write` 後的呼叫（`ensure_kind`、`_D.get`、`_SA.plan`）只做記憶體計算、錯誤已轉 `PlanError`；寫入階段整段 `except BaseException: rollback; _safe_close; raise` |
| 3 | `subcontract/api/vendor_contractors.py:673 update_dispatch` | 低～中 | UPDATE 之後、commit 之前有 `_begin_write`／`next_dispatch_code`／`int(prev.get("count") or 0)`；吃的是自己寫進去的資料，壞資料才會丟 |
| 4 | `supply/api/inventory.py:621 adjust_stock_item` | 低 | `next_entity_code` 唯讀；`.strip()` TypeError 發生在 INSERT 之前 ⇒ 只漏 fd，不持鎖 |
| 5 | `netplan/api.py:168 create_network_plan` | 低 | 同上 |
| 6–9 | `quotation_stages.py` 其他、`create_dispatch` | 低 | 窗口 3–4 個、無外部輸入解析 |
| 12 | `case_action_items.py:201 approve_case_action_item` | 低 | 先驗再寫，UPDATE 與 commit 之間沒有任何呼叫 |
| 13 | `payslips.py:725 void_payslip` | 低 | 每個失敗分支都 `close()`；UPDATE→commit 之間只有 rowcount 判斷 |
| 14 | `inventory.py:575 toggle_batch_paid` | 低 | 同上 |
| 15–18 | `org_structure.py` 四個 | 低 | INSERT／UPDATE 的 `IntegrityError` 都接了並 close；其他例外發生在寫入前（pydantic 已驗） |
| 7 | `module_versions.py:92 create_module_version` | 低 | `body.content.strip()` 在 INSERT 的引數裡，先於寫入；INSERT 本身失敗不持鎖 |

結論：**M1 的 91 個裡，只有 #1 是高風險且已修；其餘我看過的都屬「寫入與 commit 之間幾乎沒有可丟例外的東西」。**

### 2.2 H1 七個（全部人工看過）

| 站點 | 判定 |
|---|---|
| `main.py:596`／`:618 auth_middleware`（session 更新） | 誤報。`try: execute; commit; close; except: pass`，之後的 `return` 都在 close 之後 |
| `quotations.py:1921 create_quotation`（失敗後補償清理） | 低。只有「雙重失敗」才漏 |
| `quotations.py:3242 delete_quotation`、`supply/shipping_notes.py:361 delete_shipping_note` | 低。raise 之前的寫入已在 `write_txn`／明確 rollback 內 |
| `routers/auth.py:455 auth_login`、`:1414 auth_logout` | 誤報。commit／close 在 return 之前 |
| `arap/invoice_vouchers.py:680`、`subcontract/contractors.py:425`（掃描器早期版本的 H1） | 誤報。commit 與 close 在後面的 return／raise 之前 |

## 3. 為什麼「小窗口」也不能放心

做了一個探針：

```python
def endpoint():
    conn = db.get_db()
    conn.execute("INSERT ...")
    raise ValueError("boom")
try: endpoint()
except ValueError: pass
# 此時連線沒被釋放；要 gc.collect() 才會
```

例外的 traceback → frame → `conn` 形成參考循環，CPython 的引用計數回收不了，只能等 cyclic GC。所以**寫入後丟例外的那條連線會持著寫鎖，直到下一次 GC**（時間不定）。同一個程序內下一個寫入者會卡滿 `timeout=30` 後回 500。Positive control 在測試裡重現了這個 ~34 秒後 `database is locked` 的失敗模式（payslip 的樣子）。

讀取沒關只漏 fd、不持鎖（SELECT 不開交易）——這是 R1／R-pass 74 個站點風險低的原因。

## 4. B 類：持寫鎖時又開第二條連線去寫（自鎖）

### 4.1 正式機證據
`G:\我的雲端硬碟\MOTRIX-交付\正式機回報\20261111_正式機風險評估.md`：4 個月只有 2 次 `database is locked`，**兩次都是 B 類**：

| 日期 | 路徑 |
|---|---|
| 2026-09-14 | `approve_case_change → _apply_case_change_request → save_quotation_json` |
| 2026-09-29 | `_notify failed: database is locked` |

不是多人併發，是單一請求自己卡自己。

### 4.2 現況複核
- `approve_case_change`（`quotations.py:4049`）：`with write_txn(conn)` 內只做資料寫入；`_audit`／`_notify`／行事曆／通知全移到 `conn.commit(); conn.close()` 之後。程式碼註解記載 9/15 量到 32.8 s 阻塞後修正。**9/14 路徑目前已修。**
- 靜態掃描器第一版報了 17 個、第二版（支配判斷）降到 11，其餘全人工讀過：

| 站點 | 判定 |
|---|---|
| `settings_registry.py:813 publish` → `confirm_period_days` | 誤報。`confirm_period_days(c)` 用傳入的 `c`，不開新連線 |
| `case_extra_expenses.py:831 delete_extra_expense` → `_audit` | 誤報。`_audit` 在 `with delete_scope()` 區塊內 `conn.commit()` 之後 |
| `quotations.py:1952 create_quotation` → `_audit` | 誤報。`_conn2.close()` 在 `if` 分支內，`_audit` 在分支之後 |
| `quotations.py:5348 approve_quotation` → `_guard_expected_fp` | 誤報。該函式只 `conn.close()` 後 raise，不開新連線 |
| `recyclebin/api.py:146 bin_delete_approved` → `_notify_superadmins` | 誤報。呼叫在 `write_txn` 區塊（已 commit）之後 |
| `routers/parts.py:68 create_part` → `_audit` | 誤報。`conn.commit()` 在 `_audit` 之前 |
| `routers/auth.py:1407 auth_logout` → `_audit` | 誤報。demo 分支已 commit／close 並 return |
| `main.py:606/618 auth_middleware`、`quotation_stages.py:150` | 誤報（見 §2） |
| `recyclebin/jobs.py:39 run_daily` → `_audit`／`_notify` | **L 級潛在**（§4.3） |

### 4.3 唯一留下的：`recyclebin/jobs.py run_daily`（L）
`S.purge()` 起手 `begin_write(conn)`，之後所有已知失敗路徑都有 `rollback`；但**未預期的例外**（例如 UPDATE 時 `OperationalError`）不會 rollback，而 `run_daily` 的 `except Exception` 接著呼叫 `_audit("", "recyclebin.purge_failed", ...)`——它**自開連線寫入**，會卡在自己這條連線的寫鎖上 30 秒並吞掉例外，之後迴圈的下一筆再 `begin_write(conn)`。
- 觸發條件：每日工作中 purge 丟出 `BinError` 以外且發生在 `begin_write` 之後、commit 之前的例外；現行程式碼這個窗口只有一條 `_row`（不存在才丟，而 `due_ids` 剛查過）與一條 UPDATE。
- 影響：每日背景工作（不是使用者請求）；最壞多 30 秒。
- 建議：`except Exception` 內先 `conn.rollback()` 再 `_audit`；或 `purge()` 整段包 `try/except BaseException: rollback; raise`。**不是 T79 阻擋項。**

## 5. 動態偵測結果

（segment A：payroll／supply／subcontract／arap／daily_tasks／netplan／recyclebin／crm 的 module tests，不含 e2e）

pytest exit 0（payroll／supply／subcontract／arap／daily_tasks／netplan／recyclebin／crm 的 module tests，無 e2e）。`leakplug` 在 GC 回收時抓到 **14 筆「沒 close 就被回收」，其中「回收當下仍在交易中（持寫鎖）」＝ 0**：

| 回收當下在交易中 | 筆數 | 站點 |
|---|---|---|
| 0 | 10 | `helpers/google_calendar.py:592 push_event_for_dev_case_converted` |
| 0 | 3 | `google_calendar.py:714 push_event_for_case_stage_done`（由 `quotation_stages.update_case_stage` 觸發） |
| 0 | 1 | `google_calendar.py:498 push_event_for_payment_request` |

全是 `helpers/google_calendar.py` 的 `push_event_*` 只讀後沒 close 的路徑（只漏 fd、不持鎖）。**這些測試覆蓋的路徑沒有任何一條在寫入後漏掉寫鎖**——與靜態結論一致（寫入端漏鎖只剩 `create_payslip` 已修）。
範圍限制：只跑了上述八個模組的測試；`modules/case`、`accounting`、`analytics` 與 `tests/` 根目錄沒跑（機器負載規則＋測試走不到例外路徑，動態偵測本來就抓不到「例外路徑」的漏鎖——那一類靠靜態＋R1 的 `conn-reaper` 日誌）。

## 6. hichan-10／MOTRIX-ERP 候選名單逐項

| 候選 | 判定 | 見 |
|---|---|---|
| `create_payslip` | 已修（`adde4ceb7`）；本稽核的正對照 | §2 |
| `approve_case_action_item` | 低 | §2.1 |
| `quotations.review_edit_quotation` | S-w（`quotations.py:5539`，broad-except 內 close；窗口 0） | — |
| `subcontract update_contractor` | 誤報（commit／close 在後面的 raise 之前） | §2.2 |
| supply `create_batch`（`inventory.py:435`，L1） | **低～中（唯一值得順手修的）**：先 SELECT 查序號是否重複、再迴圈 INSERT，兩步之間沒有寫鎖（TOCTOU）；另一請求剛好先寫入同序號 ⇒ INSERT 丟 `IntegrityError`，這條連線沒 rollback／close（SQLite 語句失敗不放交易），寫鎖留到 GC。觸發需要同序號的併發進貨，機率低；修法：`with write_txn(conn)` 或 `begin_write(conn)` 放在 dup 檢查之前 | §7 R5 |
| supply `toggle_batch_paid`（M1）、`delete_supplier`（L1）、`update_supplier_visits`（M1） | 低。`json.dumps` 在 `execute` 的引數裡，先於寫入；UPDATE／DELETE 與 commit 之間沒有東西 | §2.1 |
| routers `auth`／`customers`／`org_structure`／`module_versions` | 低 | §2.1 |

## 7. 建議（由 PM 決定做不做）

| # | 建議 | 範圍 | 效益 |
|---|---|---|---|
| R1 | **請求層級收尾網**：`get_db()` 把「非背景執行緒」建出的連線登記進 per-request 的 `ContextVar` 清單；auth middleware 的 `finally` 對清單內仍開著的連線 `rollback()＋close()`，並 `logger.warning` 站點（順便得到動態偵測資料）。`spawn_bg_thread` 的執行緒（`_BACKGROUND_WORK`）排除，由各自的 owner 關 | `db.py`＋`main.py` 各約 20 行；不動 426 個站點 | 把「例外後漏寫鎖」從不確定時間（等 GC）縮成請求結束當下；未來新站點自動受益 |
| R2 | 新程式碼一律 `write_txn`／`db_conn`；把 db.py 那段「house style」註解改成明示「寫入端點必須用 `write_txn`」，並在 `ci.py` 加一條只對**新增行**生效的守門（不翻舊帳） | docs＋ci | 阻止新增 |
| R3 | `recyclebin/jobs.py run_daily` 的 except 內先 rollback（§4.3） | 2 行 | 消除唯一的 B 類潛在 |
| R5 | `supply/api/inventory.py create_batch`：dup 檢查前先 `begin_write`＋`write_txn`（§6） | ~3 行 | 消除唯一找到的 TOCTOU＋漏鎖組合 |
| R4 | 靜態掃描器放進 `tools/`，只在 release 前跑，報 M1 前 20 名 | — | 之後複查用 |

不建議：批次把 426 站點全改成 `db_conn`——diff 巨大、無法逐一驗證，而且 R1 以更小的改動涵蓋同一個風險。

## 8. 已實作（MOTRIX-ERP 裁示核准 R1／R3／R5，同一個 commit）

| 項 | 改動 | 守門 |
|---|---|---|
| R1 | `db.py`：`track_request_connections()`／`reap_request_connections()`／`REAP_REQUEST_CONNECTIONS`（環境變數 `MOTRIX_CONN_REAPER=0` 可關）；`get_db()` 在請求內（且不在 `spawn_bg_thread` 的背景執行緒）把連線登記進 per-request 的 `ContextVar` list，登記的連線以 `check_same_thread=False` 開（收尾在事件迴圈執行緒、連線在 worker 執行緒開）。`main.py`：純 ASGI 的 `_ConnReaperMiddleware`（不是 BaseHTTPMiddleware ⇒ 不多開 task），包住 `auth_middleware` 以內全部。請求結束時仍開著的連線：在交易中 ⇒ `rollback()`＋`close()`＋`logger.warning`（記開在哪個檔案:行 函式、哪個請求）；沒在交易中 ⇒ 只 `close()` | `tests/test_conn_reaper_t80_2026_11_11.py` 9 題：負對照（收尾網關掉＋GC 停掉 ⇒ 鎖確實還在）、未處理例外／HTTPException 之後別條連線寫得進去、被回收的是 rollback 不是 commit、背景執行緒連線不被回收、跨執行緒回收、請求外行為不變 |
| R3 | `recyclebin/jobs.py run_daily`：purge 失敗的 except 先 `conn.rollback()` 再 `_audit` | `modules/recyclebin/tests/test_run_daily_releases_lock_t80.py`（舊碼紅、新碼綠） |
| R5 | `supply/api/inventory.py create_batch`：整段 `with write_txn(conn)`（寫鎖在重複序號檢查之前；順便讓 `next_entity_code` 取號也在鎖內） | `modules/supply/tests/test_create_batch_write_lock_t80.py`：重複檢查那一刻已在寫交易內（舊碼紅、新碼綠）；序號撞 UNIQUE 後鎖已放（這題在舊碼也綠，因為 R1 兜住——是縱深防禦的第二道） |

### 8.1 設計取捨與已知邊界
- **回收發生在處理函式結束之後**：anyio `run_sync` 預設不在取消時放掉還在跑的執行緒，所以收尾網不會與還在執行的處理函式併用同一條連線。
- **不靠堆疊**：登記時只記 `sys._getframe(1)` 的檔案:行 函式（熱路徑上不做 `traceback.extract_stack`）。
- **沒登記的**：背景執行緒（`spawn_bg_thread`）、請求之外（排程、啟動、測試直呼 helper）、`get_demo_db()`。這些由各自 owner 負責，行為與從前完全相同。
- **看日誌**：上線後 `grep conn-reaper` 就是「還有哪些站點會漏寫鎖」的即時清單，可當之後逐站修的優先序（這比靜態掃描更準）。
- **不處理 B 類（持鎖又自開連線）**：收尾網在請求結束才動，B 類發生在請求中間；那一類靠 §4 的「commit／close 之後才 `_audit`／`_notify`」慣例。

## 附錄

### A1. M1／L1／H1 依「窗口內可丟例外的呼叫數」排序（前 40；完整 142 筆在 `ranked.json`）

| # | 站點 | 層 | 窗口呼叫 | 可丟例外 | 人工判定 |
|---|---|---|---|---|---|
| 1 | `modules/payroll/api/payslips.py:326` create_payslip | M1 | 27 | 9 |  |
| 2 | `modules/case/api/quotation_stages.py:150` apply_stage_template | M1 | 19 | 3 |  |
| 3 | `modules/subcontract/api/vendor_contractors.py:673` update_dispatch | M1 | 14 | 3 |  |
| 4 | `modules/supply/api/inventory.py:621` adjust_stock_item | M1 | 2 | 2 |  |
| 5 | `modules/netplan/api.py:168` create_network_plan | M1 | 6 | 1 |  |
| 6 | `modules/case/api/quotation_stages.py:436` add_stage_visit | M1 | 4 | 1 |  |
| 7 | `routers/module_versions.py:92` create_module_version | M1 | 4 | 1 |  |
| 8 | `modules/case/api/quotation_stages.py:288` delete_case_stage | M1 | 3 | 1 |  |
| 9 | `modules/subcontract/api/vendor_contractors.py:618` create_dispatch | M1 | 3 | 1 |  |
| 10 | `main.py:303` _record_user_activity | M1 | 1 | 1 |  |
| 11 | `main.py:417` _record_request_trail | M1 | 1 | 1 |  |
| 12 | `modules/case/api/case_action_items.py:201` approve_case_action_item | M1 | 1 | 1 |  |
| 13 | `modules/payroll/api/payslips.py:725` void_payslip | M1 | 1 | 1 |  |
| 14 | `modules/supply/api/inventory.py:575` toggle_batch_paid | M1 | 1 | 1 |  |
| 15 | `routers/org_structure.py:94` create_division | M1 | 1 | 1 |  |
| 16 | `routers/org_structure.py:121` update_division | M1 | 1 | 1 |  |
| 17 | `routers/org_structure.py:170` create_department | M1 | 1 | 1 |  |
| 18 | `routers/org_structure.py:202` update_department | M1 | 1 | 1 |  |
| 19 | `modules/subcontract/api/contractor_vouchers.py:1137` toggle_paid | M1 | 9 | 0 |  |
| 20 | `modules/daily_tasks/api.py:483` update_daily_task | M1 | 5 | 0 |  |
| 21 | `modules/daily_tasks/api.py:435` create_daily_task | M1 | 4 | 0 |  |
| 22 | `routers/auth.py:1543` create_user | M1 | 4 | 0 |  |
| 23 | `archive.py:413` _system_audit | M1 | 3 | 0 |  |
| 24 | `modules/case/api/quotations.py:1531` toggle_quotation_signed | M1 | 3 | 0 |  |
| 25 | `modules/case/api/quotation_stages.py:355` add_stage_assignee | M1 | 3 | 0 |  |
| 26 | `modules/case/api/quotation_stages.py:380` remove_stage_assignee | M1 | 3 | 0 |  |
| 27 | `modules/case/api/quotation_stages.py:404` toggle_stage_dependency | M1 | 3 | 0 |  |
| 28 | `modules/supply/api/shipping_notes.py:799` toggle_signed | M1 | 3 | 0 |  |
| 29 | `routers/auth.py:414` auth_login | M1 | 3 | 0 |  |
| 30 | `modules/case/api/quotations.py:1921` create_quotation | H1 | 2 | 0 |  |
| 31 | `modules/case/api/quotation_stages.py:493` delete_stage_visit | M1 | 2 | 0 |  |
| 32 | `modules/subcontract/api/contractors.py:485` toggle_contractor_active | M1 | 2 | 0 |  |
| 33 | `modules/subcontract/api/vendor_contractors.py:332` create_vendor_contractor | M1 | 2 | 0 |  |
| 34 | `modules/subcontract/api/vendor_contractors.py:360` update_vendor_contractor | M1 | 2 | 0 |  |
| 35 | `modules/subcontract/api/vendor_contractors.py:437` toggle_vendor_active | M1 | 2 | 0 |  |
| 36 | `modules/supply/api/shipping_notes.py:477` approve_shipping_note | M1 | 2 | 0 |  |
| 37 | `routers/auth.py:455` auth_login | H1 | 2 | 0 |  |
| 38 | `routers/customers.py:101` update_customer | M1 | 2 | 0 |  |
| 39 | `pdf_gen.py:591` _pdf_audit | M1 | 1 | 0 |  |
| 40 | `pdf_gen.py:1409` _shipping_pdf_audit | M1 | 1 | 0 |  |

### A2. 各層檔案分佈（寫入端站點數，不含 S-r／R-*）

| 檔案 | H1+M1+L1 |
|---|---|
| `routers/auth.py` | 15 |
| `modules/case/api/quotations.py` | 14 |
| `modules/supply/api/shipping_notes.py` | 11 |
| `modules/case/api/quotation_stages.py` | 10 |
| `modules/subcontract/api/vendor_contractors.py` | 8 |
| `modules/arap/api/invoice_vouchers.py` | 7 |
| `routers/system.py` | 7 |
| `modules/subcontract/api/contractor_vouchers.py` | 6 |
| `routers/org_structure.py` | 6 |
| `main.py` | 5 |
| `modules/arap/api/payment_requests.py` | 5 |
| `modules/netplan/api.py` | 5 |
| `modules/payroll/api/payslips.py` | 5 |
| `modules/supply/api/inventory.py` | 5 |
| `modules/case/api/case_action_items.py` | 4 |
| `modules/case/api/completion_notes.py` | 4 |
| `modules/daily_tasks/api.py` | 4 |
| `modules/subcontract/api/contractors.py` | 4 |
| `pdf_gen.py` | 3 |
| `modules/supply/api/suppliers.py` | 3 |
| `routers/customers.py` | 3 |
| `archive.py` | 2 |
| `routers/module_versions.py` | 2 |
| `helpers/audit.py` | 1 |
| `helpers/system_checks.py` | 1 |
