# D7 provides.probes（主持派工 2026-09-26，RUN-PLAN §6、D7-CHECKLIST §4；第六班合回後、c-m07-s12 之前）

機制：B 的 b-m08-3（第六班）。格式照 analytics：`module.json` 的 `provides.probes`＝1～4 支真的 GET 路由、在自己的 `api_prefixes` 底下、模組在時最高管理者打回 200。
守門：`backend/tests/platform/test_product_drill_probes.py`（`test_declared_probes_are_real_get_routes_under_the_modules_prefixes`、`test_declared_probes_answer_200_when_the_module_is_installed`）。

## 候選（各分支的 GET 路由，無路徑參數；合回後以守門實跑確認，要參數的換掉）

| 模組 | 候選 probes |
|---|---|
| crm | `/api/dev-cases`、`/api/dev-logs/pending`、`/api/dev-crm/activity-stats` |
| subcontract | `/api/contractors`、`/api/vendor-contractors`、`/api/contractor-dispatches`、`/api/contractor-vouchers` |
| payroll | `/api/payslips`、`/api/tax-rules`、`/api/bonus/awards`、`/api/bonus/items`（bonus 的 router prefix 確認是 `/api/bonus`） |

## 步驟

1. 合回後 worktree from origin/platform，分支 wip/c-probes
2. 三個 module.json 以**文字插入** `"probes": [...]`（記憶〈共用 JSON 用文字插入〉）；模組版號各升 patch＋CHANGELOG
3. 跑 test_product_drill_probes＋package／CHANGELOG 守門；反向控制：拿掉任一模組（sparse）⇒ 該模組的 probe 不打、不紅
4. 突變：probe 改成不存在的路徑／要參數的路徑 ⇒ 紅
5. 推、登記、通知 D

## 主持補充條件（2026-09-26）

### ① probe 必須純讀、無副作用（不寫表、不寄信、不排程、不記「已讀」）
- 守門（新檔、我的）：`backend/tests/platform/test_probe_side_effects.py`
  - 用 client＋最高管理者；**先各打一次**（暖機：首次讀取可能懶初始化設定列——那不算 probe 的副作用，但要記錄在題目說明裡並確認是冪等）
  - 再對每支已安裝模組的 probe：打之前 / 之後，比對**每張表的列數＋整表內容雜湊**（sqlite `SELECT * ORDER BY rowid` 的 sha256；排除 sqlite_ 內部表）、以及 `audit_log`、`notifications`、已讀標記類表的列數
  - 寄信：monkeypatch email_notify 的最底層送信函式（開工時查名稱）⇒ 呼叫次數必須 0；排程：monkeypatch spawn_bg_thread／scheduler 的 add ⇒ 0
  - 任一有變 ⇒ 紅，訊息列出「模組、probe、哪張表變了／哪個副作用被呼叫」⇒ 換掉那支 probe
- 正對照：同一個比對器對一支**已知會寫**的端點（例：`POST` 某個會寫 audit 的端點，或合成：直接在比對期間 INSERT 一列）要報得出來
- 反向控制（突變）：把某個 probe 換成會記已讀的 GET（例：若 `/api/dev-logs/pending` 會標已讀）⇒ 紅

### ② probe 回應不可以進演練報告或 log 內文，只記狀態碼
- 已查（origin/wip/b-m08-3）：
  - `tools/platform/product_drill.py`：probe 走 `st, _ = _req(...)`，回應內文丟棄；報告 `checks` 只有 module／installed／路徑／status／ok ✅
    - 內文只在**登入／改密碼失敗**時截 200～150 字進 `error`（不是 probe；是認證端點的錯誤訊息）——不含個資，照舊
  - `tools/platform/final_drill.py` 冒煙：`urlopen(...).status`／`HTTPError.code`，不讀內文 ✅
  - 兩者都把**伺服器自己的 stdout／stderr** 寫進演練目錄的 log（final_drill_smoke.log、product_drill 的 server log）——那是 app 自己的 logging，演練工具控制不了；probe 路由若在 log 裡印出資料就會落地。⇒ 觀察（給 B／主持）：probe 守門可加一條「打 probe 前後 app log 的新增行不含回應欄位值」，或規定 probe 路由不得 log 內容；目前不擋
- 守門：`test_probe_side_effects.py` 另加「演練工具只記狀態碼」的靜態題：AST 找 product_drill／final_drill 裡對 probe／smoke 回應的使用 ⇒ 只允許 `.status`／`.code`／丟棄（`_`）；有 `.read()` 的結果被放進 result／out ⇒ 紅（突變：把 `st, _` 改成 `st, body` 並寫進 checks ⇒ 紅）

### ③ 主持裁示（2026-09-26）：app log 觀察併進同一檔，不另開
- `test_probe_side_effects.py` 加：打每支 probe 時用 `caplog`（level=DEBUG，攔 root logger）攔 app 的 logging ⇒ 新增的 log 行不可以含該 probe 回應 JSON 裡**任何長度 ≥4 的字串值**（遞迴取出所有字串值；數字不比，避免誤報）
- 反向控制：合成路由（測試內掛到 app 上、只在題目期間存在）把回應值 `logger.info(...)` 出來 ⇒ 比對器必須報紅；再加一支不 log 的合成路由 ⇒ 綠（正對照）
- 規則寫進 MODULE-GUIDE 的 probes 段：「probe 路由不可以 log 回應內容（個資外洩到演練目錄的 server log）」，註明守門＝`tests/platform/test_probe_side_effects.py::<題名>`
- ⚠ caplog 攔不到 uvicorn access log 與 print()：access log 只有路徑與狀態碼（不含內文）；print 另用 capsys 一併比對
