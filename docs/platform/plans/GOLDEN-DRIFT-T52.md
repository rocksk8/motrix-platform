# route golden 漂移分析（node-39，第 52 班；唯讀分析，沒有改程式／測試／golden）

基底 `origin/platform` `cab72495d`。起因：b7 發現 `backend/modules/case/tests/route_table_golden.json`（768 筆）少了 30 條自第 46～50 班起已上線的路由（duty-roles ×13、overhead/settings ×2、extra-expenses/po-bank-block ×2、payslips 送審／核准／駁回／確認承攬商／派工連結／簽核揭露、contractor-dispatches 勞報連結、payslip-person-dispatches 清單、出納 planned-pay-date ×2、users/sales-contact、item-shipped），而第 46～50 班的官方閘門都綠。

## 一、根因（已用程式碼與 git 歷史確認）

**`test_openapi_route_table_matches_the_golden` 只做單向比對：golden 有、現況沒有才紅；現況多出來的路由永遠不會紅。**

```python
golden  = json.loads(GOLDEN.read_text(...))
missing = [g for g in golden if g not in table]
assert not missing, "既有路由被改動或消失：%s" % missing[:5]
```
（`backend/modules/case/tests/test_route_table_golden_2026_10_05.py` 第 26～32 行）

- 它是第 40 班為「把精算端點純搬移到 `api/settlement_api.py`」寫的**搬移守門**（檔頭：「之後只准加路由、不准改既有的」）。目的是抓「既有路由被改動或消失」，所以刻意允許新增；它從來不是「路由登記簿」。
- 不是被跳過：檔內沒有 `skip`／`xfail`／marker；放在 `modules/case/tests/`，全閘門的 not_e2e 會跑它。
- 不是被默默重產：`T40_WRITE_GOLDEN=1` 只有測試檔自己讀，repo 內沒有任何腳本、工具或文件會設它。
- 不是比對子集合：`_table()` 取整個 app 的 OpenAPI（含方法、路徑、operationId、參數、requestBody、security），比的是每一筆完整內容；只是方向單向。
- 檔案沒有最近被改過：測試檔只有兩個 commit（`cac019498`、`cb0ac7193`，都是 2026-10-05）。
- **golden 的維護因此不對稱**：刪路由或改參數會紅，作者被迫去改 golden（`7531753e3` 第 49 班移除 8 條墓碑端點時刪了 177 行）；新增路由不會紅，只有作者「記得」才補（`d7607ff0f` pr-to-po +19 行、`d4572e2d9` attach-views 稽核修正 +29 行，是僅有的兩次新增）。第 46～50 班新增的 30 條路由沒有人補，也沒有任何東西會提醒。
- golden 檔目前不含 `duty-roles`（`grep -c` ＝ 0），與 b7 的觀察一致。

## 二、哪些守門有同樣的盲點

盤點方式：列出 repo 內所有 golden／baseline／snapshot 檔，逐一看比對方向（讀碼，沒有執行）。

| 守門／檔 | 比對方向 | 新增會紅嗎 | 結論 |
|---|---|---|---|
| `route_table_golden.json`（本案） | 單向（golden ⊆ 現況） | **否** | **盲** |
| `l1_interface_snapshot.json`（`test_l1_interface_snapshot.py`） | 三向：新增／修改／刪除都報，並要求升 CORE_VERSION | 是 | 不盲 |
| `page_path_baseline.json`、`json_extract_baseline.json`、`l2_import_baseline.json` | 棘輪（只准變少），增加與過期基線都紅 | 是 | 不盲 |
| `golden_case_page_*.json`（e2e，`sorted(got) == sorted(exp)`） | 對稱 | 是 | 不盲 |
| `case_read_scope.json`（`test_case_read_scope.py`） | 每條帶 `quote_no` 的 GET 都要歸類 | 是 | 不盲 |
| `test_write_endpoints_are_audited`、`test_non_api_routes_whitelist` | 逐條現況路由對清單，另守清單過期 | 是 | 不盲 |
| `test_module_routes_declared.py` | 逐條現況路由要落在模組宣告的前綴／路由底下 | 是 | 不盲 |

**相關但不同的涵蓋缺口（不是 golden，但同一類「新路由沒人檢查」）**：`test_endpoint_auth_w1b_t48.py` 的「無憑證不得成功」只掃 `case`、`subcontract`、`supply` 三個模組宣告的 `api_prefixes`（`MODS = ("case", "subcontract", "supply")`）。第 46～50 班新增的路由裡，屬於 `payroll`（payslips）、`arap`（planned-pay-date）、核心 `routers`（duty-roles、users）的，沒有被這支掃到。這 30 條中哪幾條落在涵蓋範圍外，要跑一次才能精確列出（我沒有跑 pytest）。

## 三、建議修法

**A. 把 golden 守門改成嚴格相等（含新增），失敗訊息要直接說怎麼修**
1. 現況 ⊇ golden 與 golden ⊇ 現況都檢查。分三組報告：`新增（現況有、golden 沒有）`、`消失`、`內容改變（同方法＋路徑但其他欄位不同）`，各列前 20 筆。
2. 失敗訊息固定尾巴：「這是路由表守門。新增路由要一起更新 golden：`T40_WRITE_GOLDEN=1 python -m pytest backend/modules/case/tests/test_route_table_golden_2026_10_05.py -q`，檢視 `git diff` 後與程式一起提交。」
3. 把「方法＋路徑」鍵與「內容」分開報：避免操作 ID 或參數順序小改動被誤判成一堆新增＋消失。

**B. 讓 golden 不再是合併衝突的來源**（嚴格相等後，每個新增路由的分支都會改這個檔）
- 現在 `json.dumps(..., indent=0)` 一筆路由寫成約 20 行，兩個分支各加路由必衝突。改成**一行一筆**、依 (路徑, 方法) 排序（`json.dumps(entry, ensure_ascii=False)` 逐行寫），相鄰才會衝突，且可用既有的合併驅動（`tools/platform/setup_merge_drivers.py`）登記成「兩邊都取、排序去重」。
- 或把它歸入**產生檔**（跟 `dep_graph.json`／`test_map.json` 一樣，只由列車提交，`regen_all.py` 重產），分支上只跑 `--check`；缺點是需要先載入整個 app，`regen_all --check` 會多一段時間（我沒量）。

**C. 補上一次性的現況修復**
- 把現在漂移的 30 條補進 golden（`T40_WRITE_GOLDEN=1` 重產一次，審 `git diff`：應該只有新增，沒有任何既有筆內容改變）。這要跑 pytest，等主持放行；b7 已有名單，可直接做。

**D. 預檢加一項（選配）**：`train_preflight.py` 的 A 層不載入 app，放不進去；但 B 層的「便宜守門」會自動挑到這支（若實測 < 10 秒）。請 `train_preflight.py measure` 後確認它在 B 層清單裡，否則手動加入 `NARROW_FIXED` 類固定清單。

**E. 涵蓋缺口另案**：`test_endpoint_auth_w1b_t48.py` 的 `MODS` 改成「所有模組」，或新增同型守門掃其餘模組與核心 `routers`；先跑一次看有幾條要進 `PUBLIC` 白名單（目前為空）。

## 四、沒有查到／限制

- 沒有執行 pytest，也沒有載入 app，所以「30 條」是引用 b7 的名單，golden 缺它們是用 `grep` 與 git 歷史旁證（`duty-roles` 0 筆；golden 僅 3 次新增／刪除的 commit），不是我重新比對出來的。
- 沒有逐一讀所有 `*_baseline.json` 的測試實作，二節表中「不盲」是依各檔檔頭與 `assert` 形狀判斷。
- 第 46～50 班各自的閘門紀錄沒有逐一查，結論來自測試程式本身的邏輯（單向比對不可能對新增報紅），不是從閘門輸出倒推。
