# 稽核 ⑰：B 的 M08 營運分析搬進 modules/analytics（PLAYBOOK §B；上車前稽核）（X 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 X（子代理）沒有寫過任何受稽核的程式碼，只寫本文件。
> 對象：`origin/wip/b-m08` `9930923f`（未見 `wip/b-m08-2`）；基底 `0d7dcc19`；11 個 commit（`07e22e0a`…`9930923f`）。
> 稽核樹 `D:\MOTRIX-PLATFORM-X17`（detached 於 9930923f）；Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改；主工作樹 `.venv` 缺 `pyvenv.cfg`，無法啟動）。
> 測試一律 `-n 1`、行程 BelowNormal、`--basetemp=%TEMP%\motrix-pytest-x17-<標記>`（每輪只刪自己那一個）。所有突變都在稽核樹做、做完 `git checkout -- <檔>` 還原；稽核樹最後 `git status` 乾淨。
> 分級：**必修 M**／**建議 S**／**觀察 O**。關閉規則：被稽核者回覆後，由原稽核者確認才關。

## 0. 結論

- 搬遷本身（import、main、選單、模組四件檔）大致完整；以「管理者停用」讓 M08 不載入時，L1 公司查詢、M01 `/api/sales-orders`、M05 出納、M06 T100（同 `/api/reports` 前綴）全部照常（§3）。
- D1b 數字可重現：reports.py **66.8%（3265/4889）→ 23.4%（1149/4907）**；B 報 23.3%（1141），差的 8 題恰好是 `9930923f` 新增的 `test_l1_connections.py` 8 題（§6）。
- **必修 4 項**：
  - M-1　`test_l1_connections.py` 的連線帳本看不到大多數連線：`/api/now` 突變成開連線，兩種寫法之中有一種照綠；兩支 GCIS「豁免」端點實測每次多開 5 個連線，豁免題卻判 0。
  - M-2　守門對象被搬走：`test_no_credentials_in_query` 只掃 `routers/*.py`，營運分析 19 支 GET 路由搬出掃描範圍（違反 §B-9）；在模組裡加 `token: str = Query(None)` 照綠，同樣的突變放在 `routers/` 就紅。
  - M-3　`product_drill` 依 `provides.api_prefixes` 打前綴本身：M08 在時 `/api/dashboard`、`/api/reports` 回 404 ⇒ 完整產品的演練必紅；M08 被排除時「404」不證明任何事。
  - M-4　M08 不在時，首頁的「有效期將屆」與「90 天內到期」兩格顯示 `0`，並寫著「沒有需要追蹤的報價單。」、「沒有已過保的設備。」，和「0 筆」長得一樣（§B-4）。e2e 只把 `/api/dashboard/stats` 改成 404，其他端點照常回資料，所以沒有模擬到這個狀態。
- **§B-11 反向控制（刪掉模組資料夾再跑測試）沒有由本稽核重做**：在稽核樹 `rm -rf backend/modules/analytics` 被權限擋下（§7）。依交辦，停下來沒有用別的方法刪檔。§3 改用 loader 的「停用」狀態驗執行期行為（沒有刪檔），但它不等於 §B-11：守門題看到的樹裡模組還在。
- 建議 8 項、觀察 9 項。

## 1. PLAYBOOK §B 逐步

| 步 | 內容 | 驗收 | 證據 |
|---|---|---|---|
| 3 | 跨組相依：下沉 L1 或 provider，登記 | ⚠ | GCIS／`/api/now` → L1 `routers/company_lookup.py`；收入／銷項發票 → L1 `helpers/receivables.py`；`/api/sales-orders` → M01 `routers/quotations.py:6908`；精算快照改走 IP-1。但 IP-1 那一處仍直讀 M04 的表（S-4）；`helpers/receivables.py` 是 L1 卻 import M01（S-7） |
| 4 | 對方不在時：少功能並明說 | ⚠ | 首頁大標、出納銀行對帳、報表精算快照都明說；**首頁兩格顯示 0＋「沒有…」**（M-4） |
| 6 | `git mv` | ✅ | `dashboard.py`／`reports.py` 以 rename 進 `modules/analytics/api/`；測試 44 檔進 `modules/analytics/tests/` |
| 7 | module.json、README、CHANGELOG、SPEC.md | ⚠ | 四件都有；SPEC.md 三段都寫「（尚未分出）」；`customization` 為 schema＋空清單，CHANGELOG 寫「五頁的可自訂點尚未盤點（待辦）」，只寫在散文裡（S-6） |
| 9 | import／測試路徑；守門掃描範圍用 `core.source_tree` | ❌ | 沒有程式 import 舊路徑（`grep -rn "routers.reports\|routers.dashboard\|from routers import.*reports"`：只剩註解與「兩個名字都掃」的守門）；**`test_no_credentials_in_query` 仍只掃 `routers/`**（M-2） |
| 10 | 受影響的題 | ✅ | 本稽核跑 tests/platform＋modules/analytics/tests（非 e2e）：見 §5 |
| 11 | 反向控制（刪資料夾） | 未重做 | 被權限擋（§7）；B 的 RUN-PLAN 登記：1670 過 3 紅（§B-11 允許 2 題＋`test_deploy_dashboard_jobs` 1 題） |
| 12 | 降級突變 | ✅（B） | B 登記：首頁、出納、IP-1 的突變都紅 |
| 14 | modules.json、ROADMAP、模組 CHANGELOG | ⚠ | modules.json、CHANGELOG ✅；ROADMAP `docs/platform/ROADMAP.md:76` 的 M08 條目沒有狀態，`:65` 的 M11「剩地圖 provider（等 M08）」已過期（S-6） |

## 2. 搬遷完整性（交辦 1）

| 項目 | 結果 | 證據 |
|---|---|---|
| 還有程式 import 舊路徑 | ✅ 沒有 | 產品碼、tools、frontend 都沒有；`core/upgrade.py:644`、`helpers/bonus.py:12` 等只在註解提到舊路徑 |
| main.py 拿掉的 router | ✅ | `main.py:28-29` 不再 import `dashboard`／`reports`；`:677` 改掛 `company_lookup`；模組的兩支 router 由 `modules/analytics/__init__.py:10` 宣告，`mount_modules()`（`main.py:722`）掛上。模組在時 `registry.loaded()`＝`['analytics','tender_radar']`，路由衝突檢查通過 |
| 月報排程 | ✅／⚠ | `main.py:615` 移除，`modules/analytics/__init__.py:11` 以 lambda 晚綁定宣告，`main.py:726` `start_schedulers()` 啟動；**沒有任何題驗證這條接線**（S-5） |
| 選單四項 | ✅ 逐字 | `core/menu_l1.json` 刪掉的四項（採購管理 60／procurement、設備登載 10／equipment、保固追蹤 20／equipment、營運報表 10／finance+reports）與 `module.json:16-23` 的 `pages[].menu` 欄位逐一相同；sidebar `MODULE_PAGES` 登記五頁（`static/sidebar.js:1163-1167`） |
| module.json／README／CHANGELOG／SPEC | ⚠ | 見 §1 第 7 步；`permissions` 只列 `dashboard`、`reports`（O-4） |

## 3. 模組不在時（交辦 2）：以「管理者停用」實測

做法：暫時探針放在 `backend/tests/platform/x17_child_probe.py`，檔名不是 `test_*`，只在指定路徑時執行，跑完就刪。探針比照 `child_module_gate.py`：在 `import main` 之前，把 `helpers.module_switches.read_disabled_list` 換成回傳 `{"analytics"}`。這樣 loader 不會 import 模組，也不會掛路由（CORE-SPEC §9c③），而且不刪任何檔案。

| 端點／頁面 | 狀態 | 判讀 |
|---|---|---|
| `/api/dashboard/stats`、`/api/reports/financial`、`/api/reports/ar-aging`、`/api/devices`、`/api/materials-summary` | 404 | M08 端點不在 ✅ |
| `/api/now`、`/api/company/search?q=…`（GCIS 接縫替換） | 200 | L1 公司查詢照常 ✅ |
| `/api/sales-orders` | 200 | M01 照常 ✅ |
| `/api/cashier/payable-queue`／`receivable-queue`／`execution-history`（用 `helpers.receivables.collect_income_items`） | 200 | 出納照常 ✅ |
| `/api/reports/t100-export/vouchers`、`/preview`（用 `collect_tax_invoices`）、`/confirmed` | 200 | **T100 與 M08 共用 `/api/reports` 前綴，不受影響** ✅ |
| `POST /api/reports/bank-reconcile` | 405 | 落到靜態檔 mount；`cashier.js:453-455` 把 404／405 都講成「需要營運報表模組」✅ |
| `/api/platform/menu` 的 M08 四項 | 不在 | ✅ |
| `/api/system/modules/unavailable-pages` | 五頁都列 | ✅ |
| `/pages/reports.html`、`/pages/sales-orders.html` | 404＋提示頁（含「營運分析」） | ✅（但 sales-orders 見 S-8） |
| `sys.modules` 裡的 `modules.analytics*` | 空 | 沒有被偷偷 import ✅ |

畫面有沒有明說：首頁大標、出納銀行對帳、報表頁精算快照都有明說。**首頁數字列沒有**（M-4）。

## 4. 守門改成模組感知之後（交辦 3、4）

| 守門 | 正對照（模組在、該紅就紅） | 「模組不在就不驗」的假綠 | 結論 |
|---|---|---|---|
| 選單對等 `test_menu_parity.py:22-38` | 突變 MX-MENU-a：拿掉 `module.json` 保固追蹤的 `menu` ⇒ `test_every_legacy_item_is_declared_identically`、`test_rendered_menu_matches_for_every_single_permission` **紅** | 突變 MX-MENU-c：同上再把 `MODULE_PAGES['warranty.html'].key` 改成 `analytic` ⇒ 對等兩題**轉綠**（舊選單那一項也被濾掉），只剩 `test_module_selection::test_every_module_page_is_declared_in_sidebar` **紅** | 成立（靠旁邊那一題補住，O-1） |
| 跨組邊基線 `_boundaries.py:90-103` | 合成題 `test_edges_of_modules_not_installed_are_not_vanished`：來源是一般單位 ⇒ 照報 | 來源模組 key 在整個 repo 都不存在的基線條目永遠不報（改名後的殘留），見 O-2 | 成立 |
| final_drill `smoke_plan`（`final_drill.py:66-74`） | 合成樹題 `test_smoke_plan_skips_only_entries_of_absent_modules` | 突變 MX-SMOKE：`SMOKE` 兩條的 key 改成 `analytcs` ⇒ `test_final_drill_tool.py` **15 過**；實際演練時營運報表兩項會永遠「略過：模組 analytcs 不在安裝包」，而 `out["ok"]`（`:272`）不看 skipped | **會假綠**（S-1） |
| IP-1 `test_dispatch_connector.py` | tests/platform 保留 recognition、vouchers 兩個使用方與契約形狀（`CONSUMED_KEYS` 含 `grandTotal`）；報表那一半搬到 `modules/analytics/tests/test_reports_dispatch_row_consumer.py`，正對照在前 | 無 | 成立 |
| 獎金發放 IP-9 `test_bonus_payout_connectors.py` | 報表三題搬到 `modules/analytics/tests/test_reports_bonus_payout_consumer.py` | **tests/platform 已經沒有任何題碰到 `expense.entries`**（`grep -n "expense.entries\|_expense_entries" backend/tests/platform` 只剩 docstring） | 覆蓋缺口（S-3） |
| `test_l1_connections.py`（交辦 4） | 突變 MX-NOW-b：`/api/now` 內 `import db; db.get_db().close()` ⇒ `test_exempt_endpoint_really_does_not_touch_the_database[/api/now]` **紅** | 突變 MX-NOW-a（`/api/now` 內呼叫 `_get_setting(...)`）⇒ **8 過**；突變 MX-NOW-c（模組層 `from db import get_db`，端點內 `get_db().close()`）⇒ **8 過** | **會假綠**（M-1） |

## 5. 本稽核跑的題

| 範圍 | 結果 |
|---|---|
| `tests/platform`＋`modules/analytics/tests`，`-m "not e2e"`，模組在（9930923f，未改） | **1035 passed**，0 紅（9 分 19 秒，-n 1、BelowNormal） |
| 突變與正對照（§4、M-1、M-2）：各跑單檔 | 如表所列 |

## 6. D1b 選題比例（交辦 5）

`python tools/platform/modtest.py --files <檔> --dry-run --refresh-map --list`（collect-only，不跑題）：

| 樹 | 改動檔 | 選中題數／全量 | 比例 |
|---|---|---|---|
| 搬遷前 `6691f3a8`（暫時 detached worktree，量完已 `git worktree remove`） | `backend/routers/reports.py` | 3265／4889 | **66.8%** |
| 搬遷後 `9930923f` | `backend/modules/analytics/api/reports.py` | 1149／4907 | **23.4%** |

B 報「66.8%→23.3%（3265→1141 題）」。前半逐字重現。後半差 8 題，就是 `9930923f` 新增的 `test_l1_connections.py`（8 題、屬契約題）；B 量的是它之前的 commit。**可重現。**

⚠ 同一個指令**不加 `--refresh-map`**（讀分支裡的 `docs/platform/test_map.json`）⇒ 選中 54 檔、880 題（17.9%）。分支裡的 test_map.json 停在 `98d43855`（01:02），裡面一條 `modules/analytics/tests` 都沒有 ⇒ 預設用法會少選約 49 檔（S-2）。

## 7. 被權限擋下的動作（依交辦停下，未繞過）

- `rm -rf D:/MOTRIX-PLATFORM-X17/backend/modules/analytics`（§B-11：在另一個 worktree 刪掉模組資料夾後跑 tests/platform＋提到該模組的測試）：被 auto mode 分類器以 [Irreversible Local Destruction] 拒絕。**沒有用改名、sparse checkout 或其他方式重做**。
- 影響：§B-11 的「其餘測試全綠」沒有獨立重現；§4 對四道守門在「樹上沒有模組」時的行為，是讀程式碼加上既有的合成樹題推論，不是實跑。B 在 RUN-PLAN 登記的結果（1670 過 3 紅）未經本稽核核對。
- 要補做的話：使用者核准刪檔後，在 detached worktree 執行 `rm -rf backend/modules/analytics`，再以 `-n 1` 跑 `tests/platform` 加上下列清單（`grep -rlE "analytics|/api/dashboard|/api/reports/(financial|…)|reports\.html|…" backend/tests`，另加分支改過的測試，共 41 檔）。**注意不要加 `--continue-on-collection-errors` 就只看「紅」**：收集錯誤會列在 errors，不在 failed。

## 8. 發現

### 必修

**M-1　`test_l1_connections.py` 的連線帳本看不到大多數連線，豁免題是假綠**
- 位置：`backend/tests/platform/test_l1_connections.py:18-22`（EXEMPT）、`:48-54`（帳本只包 `db.get_db`）、`:107-116`（豁免題）、`:127-134`（「帳本看得到」反向控制）。
- 帳本只換掉 `db.get_db` 這個屬性。`helpers/settings.py:6`、`helpers/auth.py:11` 等都是 `from db import get_db`，在 import 當下就綁定了名字 ⇒ 經由它們開的連線，帳本一個都看不到。
  - 實測（暫時探針，在 `sqlite3.connect` 這一層計數；`/api/now` 的 1 個是中介層驗 token 開的）：`/api/now` 1、`/api/company/tax/12345678` **6**、`/api/company/search?q=motrix` **6** ⇒ 兩支 GCIS 端點本身各多開 5 個連線（`_require_user`、`_gcis_take_quota` 的 `_get_setting`×2／`_set_setting`，`routers/company_lookup.py:140,145,163-164`）。
  - EXEMPT 的理由「GCIS 政府開放資料純查詢，不碰資料庫」與事實不符，而豁免題照樣判 0、全綠。
  - 突變 MX-NOW-a／c 照綠（§4）：`/api/now` 只要經過 helper，或在模組層 `from db import get_db`，洩漏或開連線都抓不到。只有端點內寫 `db.get_db()` 的那一種會紅。
- `:127-134` 的反向控制只證明「`db.db_conn()` 看得到」，沒有證明「端點取連線的那一條路看得到」，而檔案本身的註解（`:129`）已經寫出「`from db import get_db` 綁了名字的端點繞過帳本」。這是〈證據的適用範圍〉的案例。
- 這一段是從 `test_dashboard_connections_2026_09_22.py:74-77` 原樣搬來的（既有問題）。但本分支把它提升為 L1 守門，並寫下「反向控制：真的一個連線都不開」（`:7`），所以列必修。
- 建議修法：帳本改在 `sqlite3.connect`（或 `db` 建立連線的最底層）計數。先量一支只經過中介層的 L1 端點當基準，豁免題比較「端點本身多開的數」。GCIS 兩支移出 EXEMPT，改成「開了就要關」的那一組。另補一題正對照：把一支 helper 經 `from db import get_db` 開連線的端點放進豁免清單，豁免題要紅。
- 重現：在 `routers/company_lookup.py` 的 `server_now()` 第一行加 `_get_setting("x", None)`，執行 `pytest -n 1 --basetemp=… tests/platform/test_l1_connections.py` ⇒ 8 passed。

**M-2　`test_no_credentials_in_query` 的掃描範圍沒有跟著模組走（§B-9）**
- 位置：`backend/tests/test_no_credentials_in_query_2026_09_22.py:57`（`ROUTERS = …/"routers"`）、`:97`（`ROUTERS.glob("*.py")`）。
- 營運分析的 19 支 GET 路由（dashboard.py 8、reports.py 11）（含 `financial/excel`、`financial/pdf`、`tax-export` 等下載端點，正是最容易有人想加 `?token=` 的地方）已經不在 `routers/`。
- 突變 MX-CRED：`modules/analytics/api/reports.py:2457` 的 `get_ar_aging` 加 `token: str = Query(None)` ⇒ 該檔＋`test_exception_detail_leak` 共 **23 passed**。
- 正對照：同樣的參數加在 `routers/company_lookup.py` 的 `lookup_by_tax` ⇒ `test_fx23a_no_get_route_takes_a_credential_in_the_query_string` **紅**。
- 同檔的 `test_exception_detail_leak`（`:189-190`）、`test_write_endpoints_are_audited`（`:130`）已經改用 `source_tree.router_files()`；只有這一支沒改。tender_radar、daily_tasks 搬遷時就已經漏掉，但本次搬出的量最大。
- 建議修法：`_routes()` 改掃 `source_tree.router_files()`（`:275` 的 `local_auth` 同步改）。另補一題正對照，用合成模組放一支帶 `token` 的 GET，要紅。
- 順帶：`backend/tools/check_endpoint_entrypoints.py:81,107` 也只掃 `routers/`（工具，O-7）。

**M-3　`product_drill` 用 `provides.api_prefixes` 的前綴本身當端點：M08 在時假紅、被排除時假綠**
- 位置：`tools/platform/product_drill.py:120-126`；`backend/modules/analytics/module.json:14`；規格 MODULE-GUIDE §9（「演練依 api_prefixes 驗證端點在或不在」）。
- 實測（模組在，探針）：`GET /api/dashboard` **404**、`GET /api/reports` **404**、`/api/devices` 200、`/api/materials-summary` 200。
  - 完整產品的演練：`installed ⇒ 要 200` 而拿到 404 ⇒ 判失敗。
  - 排除 M08 的產品：`/api/dashboard`、`/api/reports` 本來就不是路由，模組在不在都是 404 ⇒ 那兩條檢查不證明任何事。另外，`/api/reports` 這個前綴在 M06（`/api/reports/t100-export/*`）仍然有路由。
- 目前的程式只替 tender_radar 寫死一條特例（`:122`）。M08 是第一個前綴本身不是端點的模組，所以問題在這次才浮出來。
- 建議修法：module.json 另宣告一支演練用的端點（例如 `provides.probe: "/api/reports/financial"`），product_drill 讀它，不要用前綴猜。或者演練時只把前綴當「底下至少一條路由存在」來判。再補一個守門：每個模組宣告的演練端點，在模組在時要是真的 GET 路由（比照 `test_smoke_paths_are_real_routes_or_pages`）。

**M-4　M08 不在時，首頁數字列顯示 0＋「沒有…」（§B-4、MODULE-GUIDE §1「不可以跟 0 筆、沒有長得一樣」）**
- 位置：`frontend/index.html:504-515`。
  - 「有效期將屆」：`expiringQuotes.length`＝0，下方寫「沒有需要追蹤的報價單。」（資料來自 `/api/dashboard/funnel`，`:1106`）。
  - 「90 天內到期」：`(stats.warrantyWarnings||[]).length`＝0，下方寫「沒有已過保的設備。」，並連到 M08 的 `warranty.html`。
  - 營運警示、動態（`:1118-1135`）的 `catch {}` 讓它們安靜地變空。
- 同一個畫面上，大標寫著「需要營運分析模組」，兩格卻各自寫出確定的「沒有」，彼此矛盾。只有「等我簽核」那一格（`:502`）改了。
- e2e `test_e2e_index_without_analytics_2026_09_26.py:19-21` 只把 `/api/dashboard/stats` 改成 404。funnel、ops-alerts、activity-feed 在測試裡照常回資料 ⇒ 模擬的不是「模組不在」，所以看不到這兩格。檔案 docstring 寫的「也不可以把 0 講成沒有資料」沒有被任何斷言驗到。
- 建議修法：`analyticsMissing` 時兩格改顯示「—」＋同一句明說（或整條數字列換成一則說明）；營運警示、動態區塊同理。e2e 改攔 `**/api/dashboard/**` 全部回 404，並斷言兩格不出現「沒有需要追蹤」「沒有已過保」；正對照（全部照常）在前。

### 建議

- **S-1　`smoke_plan` 的模組 key 打錯或改名 ⇒ 該條永遠略過、演練照綠**：`tools/platform/final_drill.py:58,66-74,258-260,272`。突變 MX-SMOKE（key 改 `analytcs`）⇒ `test_final_drill_tool.py` 15 passed。建議補一題：`SMOKE` 裡每個 key 必須是 `docs/platform/modules.json` 登記的模組 key（用 repo 層的登記，不用「樹上有沒有」判斷）；`out["ok"]` 在略過項的 key 不在登記表時判失敗。
- **S-2　分支的 `docs/platform/test_map.json` 過期**：改 reports.py 時，預設的 `modtest`（不加 `--refresh-map`）只選 54 檔、880 題，加了之後是 103 檔、1149 題。少選的主要是 `modules/analytics/tests`。上車 rebase 時要重產；建議補守門「test_map.json 與現場重算一致」，或讓 modtest 發現 map 比 HEAD 舊時自動重算。
- **S-3　IP-9 `expense.entries` 在 tests/platform 沒有任何題**：提供方是 L1／M07 的 `helpers/bonus_payouts.py:85-96`，唯一的驗證在 `modules/analytics/tests/test_reports_bonus_payout_consumer.py`。PLAYBOOK 附錄 C-11a 第 5 點要求每個被模組使用的串接點至少有一題契約題放在 tests/platform。建議補一題形狀契約（比照 `test_dispatch_connector.py:38-43`，直接呼叫提供者、檢查使用方讀的欄位），不需要 M08。
- **S-4　IP-1 那一處仍直讀 M04 的表**：`modules/analytics/api/reports.py:128-131` 自己 `SELECT cd.*, vc.name … FROM contractor_dispatches cd LEFT JOIN vendor_contractors vc`，只把「列 → grandTotal」交給提供者。`INTEGRATION-POINTS.md:38-39` 寫的兩件事（第二份算法、M08 直接讀 M04 的表），只解決了前一件，`:41` 卻標「✅ 已處理」。`module.json:9` 的 `tables_note` 與 README `:35` 也只寫「經 IP-1」。建議：改由 M04 公開「列出有效派工」的提供者，或在 INTEGRATION-POINTS／README 明寫「仍直讀 contractor_dispatches、vendor_contractors（讀），待 M04 搬遷」。
- **S-5　月報排程的接線沒有任何題**：`modules/analytics/__init__.py:11`。晚綁定的註解寫的是「為了讓測試 patch 得到」，但沒有題真的這樣做。建議在模組 tests 補一題：patch `reports.schedule_monthly_report` ⇒ 對 `MODULE.schedulers` 逐一呼叫（或 `loader.start_schedulers()`）⇒ 被呼叫 1 次；再補反向控制，把 lambda 拿掉要紅。
- **S-6　待辦只寫在散文裡；ROADMAP 沒有更新（§B-7、§B-14）**：`SPEC.md` 規格編號沒有分出，`customization` 沒有盤點，兩件都只寫在模組 CHANGELOG／SPEC 的文字裡（SPEC.md 說「見 ROADMAP」，但 ROADMAP 沒有這兩條）。`ROADMAP.md:76` 的 M08 沒有狀態記號，`:65` 的 M11「剩地圖 provider（等 M08）」與地圖歸 L1 的裁示牴觸。建議把兩條待辦寫進 ROADMAP（附負責人），並更新 M08、M11 兩行。
- **S-7　L1 `helpers/receivables.py` import M01（MODULE-GUIDE §1：L1 不可以 import 任何 L2）**：`helpers/receivables.py:16-17`（`helpers.quotations` 屬 M01）。`_boundaries.l2_import_edges`（`:76-87`）只算 L2 之間的邊 ⇒ 這條邊沒有守門。目前 L1 → L2 共 3 條（`router:system → helper:quotations`、`→ helper:quote_terms`，以及本條），都看不到。docstring 與 ROADMAP 的 M01 條目有寫。建議把「L1 → L2 的邊只准減少」納入同一份基線，列出這 3 條。
- **S-8　`sales-orders.html`（轉址到 M01 的案件管理）被劃給 M08**：`module.json:24`、`modules.json:451`、`sidebar.js:1167`。M08 不在時，舊書籤會看到「需要營運分析」提示頁，而不是轉到案件管理（§3 實測 404＋提示）。資料端點已經歸 M01，建議把這頁一併歸 M01（或 L1）。

### 觀察

- **O-1　選單對等的篩選依賴 `sidebar.js` 的 `MODULE_PAGES`**：key 打錯時，對等兩題會一起把那一項濾掉而轉綠。靠 `test_module_selection::test_every_module_page_is_declared_in_sidebar` 補住（突變 MX-MENU-c 實測紅）。兩題之間的依賴建議寫進 `test_menu_parity.py:22` 的 docstring。
- **O-2　基線條目的來源模組在整個 repo 都不存在時永遠不報**（`_boundaries.py:100-103`）：模組改名之後，舊 key 的邊會留在基線裡。建議「不在這棵樹」的判斷改看 `modules.json` 有沒有登記這個 key：登記了才當成「沒裝」，沒登記就報「殘留」。
- **O-3　`INTEGRATION-POINTS.md:41` 的題目路徑寫成 `tests/test_reports_dispatch_connector_2026_09_26.py`**，實際在 `backend/modules/analytics/tests/`。
- **O-4　`module.json:7` 的 `permissions` 只列 `dashboard`、`reports`**：端點實際檢查的還有 `finance`、`financial_view`、`equipment`、`procurement`、`case_manage`、`cashier`（README 端點表）。目前 `customization` 是空的，還沒有影響；能力目錄（`core/catalog.py:237`）會照這份列出。
- **O-5　`modules/analytics/api/dashboard.py:4-5` 還留著 `import urllib.request`、`urllib.parse`**：GCIS 搬走之後已經沒有使用者。
- **O-6　`backend/tests/test_money_round_half_up_2026_09_26.py:249-257` 的 `_patch_entries` 已沒有呼叫者**，而且它 import `modules.analytics`。目前不會紅，但下一個人一呼叫就綁上 M08。
- **O-7　`backend/tools/check_endpoint_entrypoints.py:81,107` 只掃 `routers/`**：模組的端點不在它的報告裡。
- **O-8　分支落後**：基底 `0d7dcc19`，`origin/platform` 已前進 95 個以上的 commit（CORE_VERSION 1.29）。本分支暫取 1.22，上車時照 §C-7 跑 `core_bump`，並重產 G1 快照、UNIT-INDEX、test_map（S-2）。
- **O-9　模組測試 import tests/platform 的測試檔**：`modules/analytics/tests/test_reports_dispatch_row_consumer.py:6`、`test_reports_bonus_payout_consumer.py:6-7` 直接取 `tests.platform.test_*` 的 fixture 與私有函式（含 autouse `_legal`）。L1 那邊改名，模組題就會壞，而改的人不一定會跑模組題（D1b 步驟 4 之後更是如此）。建議把共用的種資料函式移到 `tests/_*.py` 輔助檔。

## 9. 回覆欄（被稽核者填；原稽核者確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | 稽核確認 |
|---|---|---|---|
| M-1 | （B 以 commit／月台登記回覆）帳本改在 `sqlite3.connect` 層（`tests/_db_ledger.py`），以呼叫堆疊經過端點原始檔歸屬；GCIS 兩支移到 DB_PATHS | wip/b-m08-2 f7463dfa | ✅ 09:29 D 複核：MX-NOW-a（經 helper）／b（端點內 db.get_db）／c（模組層 `from db import get_db` 綁名）／d（開了不關）全紅；突變 LD1「中介層的連線也算到端點頭上」⇒ 豁免題與帳本反向控制 2 紅 ⇒ 中介層確實不算、且有題守 ⇒ **關閉** |
| M-2 | `_router_files()` 真實樹改走 `source_tree.router_files()`；合成樹正對照 | wip/b-m08-2 f7463dfa | ✅ 09:29 D：原稿 MX-CRED（`get_ar_aging` 加 `token: Query`）⇒ 紅；退回只掃 `routers/` ⇒ `test_scan_covers_module_routers`、`test_rc_a_module_route_with_a_query_token_is_caught` 紅 ⇒ **關閉** |
| M-3 | `provides.probes` 由模組宣告；沒宣告列 `undeclared_probes` | wip/b-m08-2 f7463dfa | ✅ 09:29 D：probe 寫成前綴 ⇒ 2 紅（不是真路由、不回 200）；沒宣告不列 ⇒ 紅；退回用 api_prefixes ⇒ 紅 ⇒ **關閉**（見 §10 觀察 X-O10） |
| M-4 | 兩格模組不在時顯示「—」＋明說；e2e 攔 `/api/dashboard/**` 全部 | wip/b-m08-2 f7463dfa | ✅ 09:29 D：將屆格、保固格各自退回顯示數字 ⇒ 各紅 ⇒ **關閉** |
| S-1 | 採納：SMOKE 的模組 key 必須在 modules.json 登記（repo 層級登記表）；打錯的 key 標「未登記」而非「不在包內」，smoke_ok 判不過。突變 MX-SMOKE（analytcs）紅 2 題 | 02de3109 | |
| S-2 | 不改碼（已處理）：wip/b-maps-2 的 `tests/platform/test_generated_maps.py::test_test_map_json_is_current`（test_map.json 必須等於現場重產）＋PLAYBOOK §G3「列車疊完重產三份產生檔」 | b-maps-2 c8c69c79 | |
| S-3 | 採納：tests/platform 加 IP-9 `expense.entries` 形狀契約題 `test_expense_entries_contract_shape`（直接呼叫提供者、驗使用方讀的 5 個欄位與型別，不需營運分析）。突變（category 改鍵名）紅 | 71821d15 | |
| S-4 | 部分採納（文件路線）：tables_note、README、INTEGRATION-POINTS IP-1 寫明「列出有效派工仍直讀 contractor_dispatches、vendor_contractors」並更正原本的「✅ 已處理」只涵蓋第二份算法。改碼不採納：需要 M04 公開「有效派工列表」提供者，已寫進 ROADMAP 待辦（擁有者 C） | 311a601c、943d0bfe | |
| S-5 | 採納：modules/analytics/tests/test_module_wiring.py——逐一呼叫 MODULE.schedulers ⇒ schedule_monthly_report 被呼叫一次。突變（lambda 改直接放函式物件）紅 | 0f672400 | |
| S-6 | 採納：ROADMAP M08 標已搬、兩條待辦（customization 盤點 B；M04 有效派工列表提供者 C）、SPEC 編號已結（本模組沒有專屬編號）；M11「剩地圖 provider（等 M08）」劃掉更正 | 943d0bfe | |
| S-7 | 採納：L1 → L2 的 import 邊也只准變少（基線 l1_to_l2：pdf_gen／receivables／system 共 5 條，扣掉載入器 core:main → router:）；三題含合成反向控制。順帶修 --prune：原本在拿掉模組的樹上會刪掉真實的邊、且整份只寫 edges（會洗掉 l1_to_l2，實際跑到一次已還原）——改成與守門同一個判定、保留其他鍵，新題在 tmp 副本上驗 | c8397440 | |
| S-8 | 採納：sales-orders.html 改歸 M01（module.json pages、sidebar MODULE_PAGES、modules.json 單位），模組 1.0.1 | 311a601c | |
| O-1 | 採納：選單對等說明寫明依賴 MODULE_PAGES 的 key，與補位的 test_every_module_page_is_declared_in_sidebar | 4da21328 | |
| O-2 | 採納：「沒裝」只認 modules.json 登記過的 key；沒登記（改名殘留）照報消失。突變（拿掉登記判斷）紅 | 4da21328 | |
| O-3 | 採納：INTEGRATION-POINTS 題目路徑改 modules/analytics/tests/ | 311a601c | |
| O-4 | 部分採納：permissions 補 finance、equipment、procurement（本模組頁面實際檢查、也是 pages[].menu 用的鍵）；cashier、case_manage 屬其他模組（M05、M01），不列為本模組的權限 | 311a601c | |
| O-5 | 採納：dashboard.py 拿掉 urllib | 311a601c | |
| O-6 | 採納：_patch_entries 搬到 modules/analytics/tests（只有它用、且 import 營運分析） | 60a31d9d | |
| O-7 | 採納：check_endpoint_entrypoints 改用 source_tree.router_files()（含模組端點；227→269 組片段，孤兒仍是原本 7 組）；讀不到 source_tree 才退回只掃 routers/ 並印出說明 | 60a31d9d | |
| O-8 | 已處理：rebase 到 427c8be9（b-m08-2）、再到 a6dc4be6（b-m08-3，改名推）；CORE 暫取 1.30，列車 core_bump 重定 | b-m08-3 7f7cda39 | |
| O-9 | 暫緩（理由）：共用的種資料正被其他包同時改動——test_dispatch_connector 在 c-m04-2（M04 搬遷）、獎金發放種資料在 c-m07（M07 搬遷）；現在抽到 tests/_*.py 會與兩包文字衝突。第六、七班合回後由 B 抽出（共用 fixture 與種資料函式移到 tests/_dispatch_seed.py、tests/_bonus_payout_seed.py，平台題與模組題都從那裡取） | — | |

（B 回覆 2026-09-26；分支 wip/b-m08-s（疊在 b-m08-3；第六班合回後 --onto rebase）。採納項目各附突變，見各列。）

## 10. D 複核（2026-09-26 09:29，wip/b-m08-2 f7463dfa）

- **§B-11 獨立重做**：D 在自己的稽核樹 `rm -rf backend/modules/analytics`（D 的權限沒有擋；未改用 sparse checkout，因為在 worktree 啟用 sparse 會把 `extensions.worktreeConfig` 寫進共用的 `.git/config`），跑 tests/platform＋20 個提到營運分析的檔：**1264 passed、2 failed（皆 §B-11 允許）、3 skipped**；`--collect-only` 不加旗標 1269 題、exit 0（無收集錯誤）。模組在時同範圍＋`modules/analytics/tests`：**1459 passed**。與 B 登記的「1862 過 3 紅（允許 2＋已修 1）」一致（範圍不同：B 93 檔）。
- 突變合計 14 項全紅：M-1 5（含 LD1）、M-2 2、M-3 3、M-4 2（另 D 在 b-g1 的 core-only 實跑）。
- **X-O10（觀察）　tender_radar 的演練端點檢查在改版後消失**：舊版 product_drill 對 tender_radar 寫死 `/api/tender_radar/tenders`；新版只看 `provides.probes`，而目前只有 analytics 宣告 ⇒ tender_radar、daily_tasks、netplan 列在 `undeclared_probes`、不打端點（主持過渡裁示允許）。建議各模組補一行 probes（成本很低），否則演練對它們只驗頁面。

