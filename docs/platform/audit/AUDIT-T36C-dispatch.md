# 稽核：第 36 班承攬商派發回推品項（t36c-dispatch；合回前）（rev-7f 稽核，2026-10-04）

> 依 PLAYBOOK §E／§G5。稽核者 rev-7f 沒有寫過受稽核程式碼。
> 對象：`origin/train/t36c-dispatch` `8b44ca78`（基底 `af722139`；正式機 `345a34cd`）。範圍：`settlement_actuals.py`、`api/quotations.py`、`api/settlement_actuals.py`（本班未改）、`frontend/pages/settlement.html`。
> 環境：自己的稽核樹 `D:\開發測試檔\aud-7f`（detached 於 8b44ca78 後開 `wip/t36c-audit-7f`）、`.venv312`、`-n 2`、basetemp 在 `%TEMP%`；**未動程式碼**，探針另存 `AUDIT-T36C-dispatch-probe.py.txt`（改名避免被 pytest 蒐集；用時複製成 `modules/case/tests/test_audit_t36c_probe.py`）。未碰正式機、未建包。

## 0. 結論

**必修 0、建議 3、觀察 5。可以合回。**
- 金額守恆、`validate_offsets` 濫用、完結 409 路徑、查無／無財務檢視規則、圖表 XSS，探針全部通過；4 個突變全部被既有題抓到並已精確還原。
- 唯一值得在上線前處理的是**下游輸出的分項加總對不上總成本**（S-1）：金額本身正確，但結案 PDF／獎金精算明細的「品項＋額外＋承攬商＝總成本」在有「被吸收的派發」時差一筆。

## 1. 基準

| 範圍 | 結果 |
|---|---|
| 作者新題＋finalize integrity／offsets validation／conservation（`-n 2`，59 題） | 59 passed |
| 稽核探針 P1–P5（13 個參數化案例） | 13 passed（P6 見 N-2，僅輸出編碼問題未跑完，結論改由讀碼） |

## 2. 探針

| # | 探針 | 結果 |
|---|---|---|
| P1 | 別案的派發 id 當 offset | PUT ⇒ 422；即使繞過驗證直接寫入存檔，`compute()` 只在**本案**派發列內查表（`dispatch_rows` 以 `quote_no` 過濾），別案金額不會被計入（dispatchTotal 仍只有本案 1000） |
| P2 | 已不在報價單的品項 | PUT ⇒ 422；已存的 offset 之後品項被刪 ⇒ 派發回到未對應、`dispatchAbsorbedTotal=0`，錢不消失 |
| P3 | 守恆格網：adopt a/b × 派發 d1／d2 去向（無／a／b）× 材料去向 × `unadopted` 兩種模式（共 144 組合，另含恆等式 已對應＋未對應＝dispatchTotal＝15000） | 全過。總成本＝Σ品項實際＋未對應材料／派發／額外＋手續費＋自訂＋「已對應但品項不採用的派發」＋（ADD 模式）未採用採購（扣除派發）。每筆錢只出現一次 |
| P4 | 完結：頁面沿用舊公式（沒扣吸收）送 `totalActualCost` | 409；缺 `dispatchAbsorbed`／拆分鍵 ⇒ 伺服器補齊 `dispatchAssignedTotal`／`dispatchUnassignedTotal`；已完結再存無理由 422；admin 重存 403；無權者對存在與不存在的案件回**同一個**狀態碼（不洩漏存在） |
| P5 | `actualSource` 值域：`[]`、`{}`、`0`、`False`、`["labor"]`、`{"a":1}`、`"<script>"`、`"LABOR"`、`" labor"` | 非空且不在 `manual／legacy／labor` ⇒ 422（假值 `[]`、`{}`、`0`、`False` 放行，等同「沒有」，讀回為 `manual`；無 500） |

## 3. 突變（先 commit、只動 `settlement_actuals.py`、還原後 `git diff` 為空）

| # | 突變 | 結果 |
|---|---|---|
| M1 | 總成本不扣 `disp_absorbed` | **紅**（`test_adopt_on_replaces_estimate_and_total_not_double_counted`） |
| M2 | 不論採用與否都計入吸收（`if has and adopt` → `if has`） | **紅**（`test_adopt_off_moving_between_unassigned_and_assigned_keeps_total`） |
| M3 | `check_finalize` 的派發拆分比對停用 | **紅**（`test_finalize_fills_split_and_rejects_wrong_split`） |
| M4 | `validate_item_sources` 的值域檢查停用 | **紅**（`test_item_actual_source_roundtrip_is_display_only`） |

各突變只被**一題**抓到（M1 尤其）。反向控制成立，但單點；見 S-3。

## 4. 發現

### 建議

**S-1｜下游輸出的分項不再加總到總成本【建議；需 PM 決定要不要本班處理】**
- 證據：`settlement_actuals.py` 本班起 `totalActualCost = … + dispatchTotal − disp_absorbed`，而 `itemActualTotal` 已含被吸收的派發。下游照舊分列：`backend/pdf_gen.py:2567-2571`（品項實際成本／額外支出／承攬商派發成本／實際總成本）、`backend/modules/payroll/bonus.py:149-155` `SETTLEMENT_ROWS`（獎金精算明細，PDF 與 `bonus.html` 共用）、`reports.py:1508-1512`（Excel「品項實際成本」「額外支出」「總成本」；該段註解寫「分項加總才等於實際總成本」）。
- 情境：派發 12000 對應到採用的品項 a ⇒ 品項實際 12000＋…、承攬商派發成本欄仍顯示全額 15000、總成本只扣一次。PDF 讀者把三欄加起來會多 12000，與使用者特別在意的「避免金額爭議」相衝。**總成本、毛利、淨利、獎金基數都是對的**，只有分項呈現。
- 證實方式：讀碼＋P3（absorbed 非 0 的組合）。**未實際產出 PDF 比對。**
- 提案（擇一）：(a) 在 PDF／獎金明細加一列「（其中已併入品項：NT$ X）」，資料來自 `summary.dispatchAbsorbed`（頁面已存、伺服器**沒有**補，見 N-3）；(b) 摘要新增 `dispatchOutsideItems = dispatchTotal − dispatchAbsorbed` 讓下游顯示；(c) 先不處理，在 PDF 加註。工 S。

**S-2｜`/settlement-actuals` 新增回傳承攬商名稱與逐張金額【建議；確認是否刻意】**
- 證據：`settlement_actuals.py` `dispatch_rows()`（`vendorName`、`docCode`、`amount`、`tax`、`grandTotal`）進入 `unassigned.dispatches`、`items[].dispatch.orders`；端點守門是「案件可見＋`can_see_financial`」（`api/settlement_actuals.py:23-27`，本班未改）。對照 `GET /contractor-dispatches` 需 `procurement／case_manage／contractor_list／quotation` 任一模組（`vendor_contractors.py:514`）。
- 情境：有財務金額可視、看得到該案、但沒有上述任一模組的帳號，現在能看到每一家承攬商的名稱與每張單金額；之前只看得到合計。MODULE-GUIDE §1.1 對案件子資料的可見範圍已有使用者裁示（維持現狀，改動要再問使用者），此處是**放寬**而非收緊。實務上有案件權限的人幾乎都有 `quotation`，影響面小，但屬於規則面。
- 提案：PM 確認屬於預期；若否，`dispatch_rows` 對無承攬商模組者只回金額、遮蔽名稱。工 S。

**S-3｜突變被單題抓到；頁面端公式沒有直接守門【建議】**
- M1 只有一題紅。前端 `dispatchAbsorbed` getter（`settlement.html` `get dispatchAbsorbed`）與後端 `disp_absorbed` 是兩份同式；現靠完結 409 比對當安全網（P4 證明有效），但**沒有一題直接比對頁面算出的總成本與後端 `totalActualCost`**（e2e 檔需有真瀏覽器，本次未跑）。
- 提案：在 e2e 加「採用＋派發對應後，頁面 `summary.totalActualCost` ＝ 後端 `totals.totalActualCost`」，並對 M1 這類突變補第二題非 e2e 的恆等式（P3 的獨立重算可直接收編）。工 S。

### 觀察

**N-1｜待審核派發可以讓「採用」取代估計**：`has = purchased > 0` 含派發；只有一張待審核（pending）的派發對應到品項且採用 ⇒ 估計被待審金額取代，但 `pendingTotal` 不含派發（USER-DECISIONS §H 末列，PM 裁示）。每列有 `pending` 標示，屬已知取捨。

**N-2｜整包存檔路徑不經 `validate_offsets`／`validate_item_sources`**：`api/quotations.py:1807` 只強制保留 `settlement.status`，其餘 `settlement` 內容來自用戶端（既有行為，我上一份審查 F-04）。本班新增的 `kind:"dispatch"`、`actualSource` 因此也可被寫入未驗證值，但：該路徑受 `_LOCKED` 狀態鎖保護（探針直接打已送出案件得 403），只有「解鎖編輯」能走到；計算端對 offsets 一律以本案現有列查表（P1）、`actualSource` 不在值域即讀回 `manual`；頁面對 `actualSource` 使用的是 `x-text`（見 N-4）。**無金額後果**。探針 P6 因輸出編碼中斷，結論來自讀碼。

**N-3｜`dispatchAbsorbed` 只由頁面寫入**：`fill_downstream` 只補 `dispatchAssignedTotal`／`dispatchUnassignedTotal`，不補 `dispatchAbsorbed`；`check_finalize` 也不比對它與（頁面不送的）兩個拆分鍵。總成本已被 `_check_downstream` 重算比對，所以不是缺口，但 S-1 若採 (a) 需要它由伺服器補。

**N-4｜XSS 檢查通過**：`settlement.html` 的 `x-html` 只有三處（圖表 ①②③），其輸入全經 `stlEsc()`（`label`、`id`、`tip`、`text`、`aria` 皆跳脫；`data-v` 為數值；填色為常數 token）。承攬商名稱、品名、說明、`actualSource` 在其餘新字串都走 `x-text`。無 `innerHTML` 新增。品名在圖③被 `.slice(0,16)` 截斷後才跳脫，順序正確。

**N-5｜其他小項**：(1) 後端 `name` 欄位直接帶 `scope`（自由文字），前端 `dispDetail` 只過濾字面 `'amount'`（`settlement.html` `dispDetail`）；正式資料若有其他佔位字會原樣顯示，無害。(2) `reports.py:545` 的「精算過期」比對仍用 `dispatchTotal` 快照 vs 現算全額，不受吸收影響（語意不變，已核對）。(3) CHANGELOG／manifest／changelog.md 皆有本班條目；`module.json` 版號有動（`## (next)` 佔位規則 §G6 應確認——只讀 diff 未驗證列車取號規則）。

## 5. 跨模組讀者核對

| 讀者 | 讀什麼 | 受影響？ |
|---|---|---|
| 獎金（`payroll/bonus.py` `SETTLEMENT_FIELDS`） | `summary` 十二格，原樣帶出 | 值正確；分項呈現見 S-1 |
| 結案 PDF（`pdf_gen.py:2545,2567-2571`） | `dispatchTotal`、`dispatchTax`、`itemActualTotal` | 值正確；分項呈現見 S-1 |
| 營運報表（`reports.py:406-407,534-550,1508-1541`） | `netProfit`、`dispatchTotal`（過期比對）、`itemActualTotal`＋`itemPoUnadopted` | 值正確；Excel 分項見 S-1 |
| 儀表板（`dashboard.py:152-155`） | `settlement.summary` | 只讀淨利類，不受影響 |
| 精算頁字串 | 其他模組沒有解析 `settlement.html` 的畫面字串；只有 docstring 提到 | 無 |

## 6. 清理
`%TEMP%\motrix-pytest-aud7f` 已刪；`D:\開發測試檔\aud-7f` 的 `git status` 除本報告與探針檔外乾淨。
