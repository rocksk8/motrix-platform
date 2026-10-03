# AUDIT-0C — 第 35a 班（`origin/wip/train-35a-int1`，作者 hichan-31）獨立稽核

- 稽核範圍：`git diff origin/platform...origin/wip/train-35a-int1`（10 檔，+89/−8；tip `c9958dbf`，基準 `4b18cd01`）。唯讀；未動該分支。
- 稽核者：hichan-0c（2026-10-03）。方法：讀碼＋在 base 與 35a 兩棵 worktree 跑同一支探針（未入庫，附錄 A）。

## 結論

**PASS（可出貨），附 1 項建議出貨前順手修的低機率回歸（S1）。** 可見性、金額、XSS、舊連結／e2e 掛鉤皆無問題。

## (1) 新欄位的可見性（最優先）

新欄位：`recognition.extra_entries` 列加 `description`；`material_money_rows` 列加 `quantity`／`unit`；`settlement_actuals.compute` 的未對應／歸屬列帶出。

呼叫者逐一盤點（`grep` 全 backend 非測試碼）：

| 消費者 | 是否原樣吐出新欄位 | 說明 |
|---|---|---|
| `analytics/api/reports.py:3538` | 否 | 逐欄組新 dict（`date/quoteNo/desc/amount/files/pending/taxNote/provisional/category`），不含新鍵；`desc` 本來就含說明（舊行為） |
| `recognition.py:517` 旗標 | 否 | 只取 `desc/amount/date` 等 |
| `gl_events.py` | 否 | 自己查 DB，不經 extra_entries 列 |
| `GET /api/quotations/{no}/settlement-actuals`、`POST …/preview` | **是**（唯一出口） | 兩支都：`_require_user`→`_guard_case`（看不到＝404）→`can_see_financial`（否＝403） |

- `compute` 的輸出是逐欄組出的 `rec`／`row`，**不含 `order`（原始材料申請列）也不含採購單行金額**；新欄位的來源是材料申請的 `quantity/unit`、額外支出的 `description`，都不是採購單行（第 34 班首包洩漏的那條路徑）。
- 規則：`can_see_financial` ＝ role ∈ {superadmin, admin, sales} 或持 `financial_view`（第 35a 班未改）。
- 現有權限題 `test_permissions_other_cases_and_financial_view` 於 35a 通過（16/16）。

**正對照（非財務角色拿不到；財務角色拿得到，證明 403 不是空轉）** — 探針：同一案件、同一 DB，建立有 `description`/`quantity` 的資料後，以各角色打兩支端點（指令與輸出見附錄 A）：

| 帳號 | role / modules | GET | POST preview | 回應含新欄位 |
|---|---|---|---|---|
| viewer | viewer / case_manage | 403 | 403 | 否 |
| eng_expense | engineer / case_manage, expense_forms | 403 | 403 | 否 |
| anon | — | 401 | — | — |
| eng_finview | engineer / case_manage, financial_view | 200 | 200 | 是 |
| sales_nomod | sales / case_manage | 200 | 200 | 是 |
| admin_nomod | admin / （無任何模組） | 200 | 200 | 是 |

base（`origin/platform`）上同一矩陣的狀態碼完全相同（403/403/401/200/200/200）⇒ 本班未改變任何人的存取權。
說明：admin 與 sales 依**現行規則**（角色即放行）本來就看得到財務金額；「admin 無出納／財務模組」仍 200 是既有規則，非本班引入。engineer＋`expense_forms` 本來就能經額外支出 API 讀到說明文字，新欄位未擴大其可見範圍。

## (2) 精算分頁的閘門

- 前端：`<a class="cm-tab-link" x-show="canSeeFinancial()" data-testid="cm-tab-settlement">`；`canSeeFinancial()`（`case-management-core.js:69`）與後端 `can_see_financial` 同式（角色 superadmin/admin/sales 或 `financial_view`）。舊連結（財務分頁內「前往精算頁面 ▶」，`case-management.html:2658`）未動。
- 伺服器端（不只 JS）：目標頁 `settlement.html` 為靜態檔，資料全走 API：`GET /api/quotations/{no}/settlement`（`require_case`＋`_require_financial_view`）、`settlement-actuals`（見上）、`PUT settlement`（同）。直接輸入網址的非財務帳號只會得到 403，頁面無資料。

## (3) 隱藏的金額／規則／進位變更

- diff 只有 4 行後端：2 行 `extra_entries`／`material_money_rows` 加鍵、2 行 `compute` 加鍵；`amount`、`total`、`cost_state`、`linked`、`noPo` 運算式皆未改。
- 數值比對（附錄 A）：同一 fixture（採購單連品項 3000、材料申請 連單 3000／直歸品項 800／未對應 250、未對應採購單額外支出 700）在 base 與 35a 各跑一次 `settlement-actuals`，`diff` 僅有 **新增鍵**：`description`（×2 處）、`quantity`／`unit`（×2 處）；所有 `totals`（含 `itemActualTotal 4325`、`extraTotal 700`、`materialUnassignedTotal 250`、`purchasedTotal 4750`、`totalActualCost 5275`）逐值相等，腳本比對 `totals_equal = True`。

## (4) XSS／跳脫

- `settlement.html` 渲染標籤的兩處（488、541 行）皆為 `x-text`；全檔無 `x-html`／`innerHTML`／`document.write` 用於這些列。
- 實測 `description = 假日午餐餐費<img src=x onerror=alert(1)>` 由 API 原樣回傳（JSON 字串），頁面以文字顯示，不會當 HTML 執行。標籤字串僅用於畫面，不寫入 `settlement` 存檔（offsets 只存 `kind/ref/itemId`）。

## (5) 舊連結與 e2e 掛鉤

- 新連結刻意不帶 `.cm-tab`：既有 e2e 一律用 `.cm-tab:has-text("財務"｜"額外支出")`，不受影響；新 e2e 以 `.cm-tabs > .cm-tab, .cm-tab-link` 驗順序（…「額外支出」、「精算 ▶」）。
- 實跑：`pytest -m e2e modules/case/tests/test_e2e_settlement_actuals_2026_10_03.py` → **5 passed**；`test_settlement_actuals_2026_10_03.py` → **16 passed**（35a worktree，單程序，basetemp 已刪）。

## 發現

### S1（建議出貨前修；低機率、爆炸半徑大）— `quantity` 解析可使共用原語丟例外
`recognition.py:312`：`float(mo["quantity"]) if str(...).replace(".","",1).isdigit() else None`。`str.isdigit()` 對上標／圈數字（如 `²`、`①`）為 True，但 `float()` 會 `ValueError`。實測：某材料申請 `quantity="²"` ⇒ 35a 上 `GET settlement-actuals` 回 **500**（base 為 200）。`material_money_rows` 同時被 `material_entries`（營運報表、總帳 E12）使用，所以一筆壞資料可能讓報表一起 500（以讀碼判斷，未實跑報表端點）。
建議：改成 `try: float(...) except (TypeError, ValueError): None` 並加一題 `quantity="²"` 的回歸測試。UI 若 quantity 為 number 欄位則實際觸發機率極低，故列為出貨前順手修，不是阻擋。

### 觀察（不需改）
- 新增的 `description` 與既有 `desc`（「客戶｜類別｜說明」）重複承載說明文字，屬同一份資料。
- `matLabel`：`m.quantity` 為 0 時不顯示數量（`0` 為 falsy），可接受。

## 附錄 A — 證據與重現

探針（未入庫；位於 `backend/modules/case/tests/test_zz_audit0c_probe.py`，跑完已刪）以現有 fixture（`W`、`_won_case`、`_approved_po`、`_put_materials`、`make_user`）組出上述 fixture，輸出 JSON。指令（在各 worktree 的 `backend/`）：

```
PROBE_OUT=<out.json> .venv312\Scripts\python.exe -m pytest -q -p no:cacheprovider \
  modules/case/tests/test_zz_audit0c_probe.py::test_probe_dump_and_roles \
  modules/case/tests/test_zz_audit0c_probe.py::test_probe_quantity_edge --basetemp=<tmp>
```

`diff probe_base.json probe_35a.json`（節錄，僅新增鍵）：
```
25a26   >  "description": "假日午餐餐費<img src=x onerror=alert(1)>",
66c67-69 > "quantity": 2.0, ... "unit": "台"
151a155 >  "description": "假日午餐餐費<img src=x onerror=alert(1)>",
165c169-171 > "quantity": 2.0, ... "unit": "台"
totals equal: True
```
角色矩陣（35a）：`viewer 403/403`、`eng_expense 403/403`、`anon 401`、`eng_finview 200/200`、`sales_nomod 200/200`、`admin_nomod 200/200`；非財務帳號回應不含 `"description"`／`"quantity"`；base 狀態碼相同。
`quantity="²"`：base → 200；35a → `ValueError: could not convert string to float: '²'`（`recognition.py:312`，HTTP 500）。
