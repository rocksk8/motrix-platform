# T64 F7 S1：求值函式 `visible()` 與出口遷移——設計（只有文件，無程式）

> 日期：2026-10-15　基底 `wip/t64-f7-s0-r1`（96afaeb6e，S0 已含目錄與唯讀 `FIELDS`）　分支 `wip/t64-f7-s1-design-r1`
> 承接 `T64-F7-FIELD-POLICY-DESIGN.md` §8 S1。S1 的唯一目標：**把『誰看得到哪個金額欄位』的答案收成一個函式，並證明它和今天的 6 支角色函式在所有組合下逐格相同。** 政策規則（S2）、編輯器（S3）都不在 S1。

## 0. 結論（先看）

1. S1 之後，出口只問一個問題：`field_policy.visible(field_id, user) -> bool`。S1 的實作＝**『天花板』查表**：欄位的 `ceiling` → 今天那支角色函式，一對一，不新增判斷。⇒ 輸出與今天逐位元相同，是純重構。
2. 今天真正的分歧是 **4 個層級（tier）**，不是 6 支函式：`quote_money`（報價單層級）、`finance_money`（精算／款項／總覽）、`material_money`（叫料）、`cashier`（出納）。`can_see_financial`／`has_finance_access` 在旗標 `off` 時是同一個答案，`money_visible` 只是它多了 `cashier` 模組。S1 把這個對照寫成**一張表**（§2），不再靠讀 docstring。
3. 遷移分 5 小步（S1a–S1e），每步獨立可上線、旗標不存在（因為沒有行為變化）；最大風險是**出口多且遮蔽不是單一動作**（鍵剝除、整段清空、文字替換、欄位省略四種），所以每種動作各自一組矩陣金標，而不是只驗一個函式。
4. 本期不碰：政策規則、治理、預覽、前端；不新增路由、旗標、資料表（S0 已確認目錄是純程式）。

## 1. 現況：遮蔽有四種動作（已讀程式）

| 動作 | 位置 | 做什麼 | 目錄是否已涵蓋 |
|---|---|---|---|
| ① 鍵剝除（dict 鍵直接拿掉） | `mask_quotation_data`：品項 `ITEM_MONEY_KEYS`、頂層 `QUOTE_MONEY_KEYS`；`mask_case_record`：款項 `PAYMENT_MONEY_KEYS`、叫料 `MATERIAL_ORDER_MONEY_KEYS` | `d.pop(k)` | ✅ S0 已衍生 |
| ② 欄位置 None | `mask_row`：`QUOTATION_MONEY_COLS` | `row[k] = None` ＋ `moneyMasked` | ✅ |
| ③ 整段清空 | `settlement`（只留 `status`）、`payment.received`（舊形狀的金額數字）、`editHistory[].reason`（自由文字） | 結構性遮蔽，不是鍵清單 | ❌ **S0 沒登記** |
| ④ 文字替換 | `approval.reasons`（含『毛利』『NT$』『折讓』的整句換成 `MASKED_REASON`）、`editHistory.changes[]`（`HISTORY_MONEY_FIELDS` 的 from/to 換成『—』） | 內容式，不是鍵 | 部分（history 標籤✅，reasons 規則❌） |
| ⑤ 整欄省略 | 匯出：`export_templates` 的 `money`＋`visible`；PDF：`quote_money_visible(user) or _is_case_approver(...)` | 輸出端再問一次 | 匯出✅（S0 互核）；PDF ❌ |

**S1 必須先補 ③④⑤ 的登記**（目錄新增 `kind` 欄：`key`／`subtree`／`text`／`column`／`document`），否則『一個函式』只涵蓋最簡單的一半，剩下的仍是各出口自己的 if。補登記的工作不改行為：只是把今天寫死在函式裡的規則變成目錄上的一筆資料，並用金標證明新舊相同。

## 2. 層級對照表（S1 寫進目錄、守門測試寫死）

| `ceiling` | 今天的函式 | 角色集合（`finance_via_effective=off`） | 備註 |
|---|---|---|---|
| `quote_money` | `financial_mask.quote_money_visible` | superadmin、admin、sales、財務（經 `auth.finance_duty_person`） | 報價單層級；業務維持編輯報價單、看總額 |
| `finance_money` | `financial_mask.money_visible` ＝ `auth.can_see_financial` **或持有 `cashier` 模組** | superadmin、財務；加上 `cashier` 模組持有者 | 精算、款項、財務總覽；`cashier` 例外是 2026-09-24 使用者裁示 A |
| `material_money` | `financial_mask.material_money_visible` | 與 `quote_money` 同集合（獨立函式，因為 Q6 要保留日後分開調整的可能） | 取消已核准材料申請／改成本單價另需財務角色（`material_approval`／`material_guard`），**不在這張表裡** |
| `cashier` | `auth.has_cashier_access` | 旗標 `off` 時＝財務存取 | 出納匯出的工作表 |

重點：這些函式在旗標 `finance_via_effective=on`（D5，本期不開）時會改看**生效權限**。`visible()` 只呼叫它們，**不複製其判斷**，所以 D5 之後自動繼承，不會出現第二套答案。

## 3. `field_policy` 模組（S1 版，約 80 行）

```
helpers/field_policy.py            L1，[穩定度] 實驗
  visible(field_id, user) -> bool   天花板查表；未知欄位 ⇒ False（fail-closed）
  visible_many(field_ids, user) -> {id: bool}
  tier_allowed(ceiling, user) -> bool    唯一把 ceiling 對映到角色函式的地方（延遲 import，避免環）
  mask_flags(user) -> {"keep_quote":…, "keep_orders":…, "money":…}   給 mask_* 的既有旗標參數用
```
- 導入順序：`field_catalog`（純資料）← `field_policy`（對映 ceiling → `financial_mask`／`auth` 函式）← 各出口。`financial_mask` **不 import** `field_policy`（避免環）；S1b 起 `financial_mask` 的 `mask_*` 保持原簽章，由呼叫端傳旗標，旗標由 `mask_flags(user)` 產生。
- 求值錯誤（目錄壞掉、auth 丟例外）⇒ 回 False，並記 log 一次；**不得**回 True。
- S2 在這裡加『∧ 政策』；S1 不留半成品鉤子。

## 4. 出口遷移清單與分批

依 `grep` 實際引用（不含測試）；括號是引用處數：

| 批次 | 出口 | 為什麼放這批 |
|---|---|---|
| S1a（零接線） | 只新增 `field_policy.py`＋目錄補登記（③④⑤）＋**等價金標**（§5）。沒有任何出口改動 | 先證明『新函式＝舊函式』，再動出口 |
| S1b | `financial_mask.py` 內部：`mask_*` 的旗標預設值改由 `mask_flags` 推導（簽章不變） | 一個檔，最容易回滾 |
| S1c | 案件：`quotations.py`（32）、`alt_plan.py`（7）、`material_orders.py`（9）、`material_payments`（6）、`material_changes`（5）、`material_approvals`、`project_margin`、`settlement_actuals`、`material_links` | 金額遮蔽最密集；quotations.py 單檔最多，**逐函式拆小批**，每批一個回歸矩陣 |
| S1d | 財務側：`arap`（`payment_requests`、`invoice_vouchers`、`cashier`）、`subcontract`（`contractor_vouchers`、`vendor_contractors`、`remit_kinds`、`contractors`）、`payroll`（`bonus`、`payslips`、`payslip_payables`）、`accounting_export` | 多半是『整支端點要財務』的擋門，不是欄位遮蔽——**這類保留 `has_finance_access` 當權限檢查，不改**；只改欄位遮蔽處 |
| S1e | 輸出：匯出 `money`/`visible` 由目錄產生（取代各登記處手寫）；`analytics`（`reports`、`dashboard`、`ledger_diff`）；通知占位符 `notify_actions._expand_text`；內部 PDF | 匯出已在 S0 互核，這步把『手寫』改成『產生』並保留互核測試 |

**判準（避免過度遷移）**：只有『依欄位決定給不給值』的點要走 `visible()`；『整支端點要不要讓你進』的權限檢查（`_require_user(module=…)`、`has_finance_access` 擋 403）**不是欄位政策**，不動。S1c/S1d 開工前先對每個引用點標一欄『擋門／欄位遮蔽』，清單寫進該批的 PR 說明。

## 5. 等價金標（證明零行為變更的核心）

矩陣維度（全組合）：
- 角色：`superadmin`、`admin`、`sales`、`engineer`、`viewer`、`finance`
- 模組勾選：有／無 `cashier`、有／無 `financial_view`
- `finance_via_effective`：`off`、`shadow`、`on`（`on` 用測試替身注入生效權限；本期不開，但函式必須和舊函式在 `on` 下也一致，因為 `visible()` 只轉呼叫它們）
- 欄位：目錄全部（47 筆，含 16 張工作表）

每一格斷言 `visible(fid, u) == _OLD[ceiling] 在同一 u 的結果`，其中 `_OLD` 是**寫在測試裡的舊函式對照表**（不讀目錄，避免自證）。再加動作矩陣：對同一份樣本單據，分別用舊流程（`mask_quotation_data(..., keep_quote=…, keep_orders=…)`）與新流程（旗標由 `mask_flags` 產生）遮蔽，比較**整份輸出 JSON 逐位元相等**——樣本要含：舊形狀 `payment.received`、`settlement` 全欄、含『毛利／NT$／折讓』的核准原因、含『淨利率』舊標籤的修改紀錄、`editHistory[].reason`。
正對照：把 `ceiling` 對映故意改錯一格，金標必須變紅。

## 6. 回寫與推論風險（S1 要守住的）

- **寫回**：看不到金額的帳號送回的資料沒有那些鍵，照存會用空值蓋掉真值；`restore_case_record`（款項／叫料）維持原樣呼叫，S1c 每個被改的寫入點加一題『遮蔽帳號存檔後金額不變』。
- **推論**：S1 不改『哪些人看得到』，只改『誰來回答』，所以不產生新的推論面；但目錄 `derivedFrom` 的審查（毛利依賴成本）此時開始成為新增欄位的必填項（S0 已有守門）。
- **效能**：`visible()` 只呼叫既有純函式（角色比對、讀一次旗標快取），不查資料庫；`visible_many` 給清單端點一次算完，避免逐列重算。
- **例外路徑**：PDF 的『核准人例外』（`_is_case_approver`）屬於**資料相關**判斷（看這張單的簽核人），不是使用者層級——保留在呼叫端，`visible()` 回答『使用者層級』，呼叫端再 `or` 例外。目錄上標 `exceptions: ["case_approver"]` 供 S2 預覽使用。

## 7. 需要使用者決定的事

S1 是純重構，**沒有新的使用者決定**。唯一要確認的工程判斷：S1d 把『整支端點擋門』排除在外（只遷移欄位遮蔽）——建議照此，理由是擋門屬權限勾選制，不屬欄位政策，混在一起會讓『欄位可見』與『能不能進這個畫面』兩件事互相牽動。

## 8. 工量與風險

| 步驟 | 預估（pd） | 主要風險 |
|---|---|---|
| S1a | 1.5 | 補登記 ③④⑤ 時漏規則 ⇒ 由金標的樣本單據覆蓋 |
| S1b | 0.5 | 預設旗標推導錯 ⇒ 動作矩陣 |
| S1c | 3 | quotations.py 單檔 32 處；逐函式批次，每批一次回歸 |
| S1d | 1.5 | 擋門／遮蔽分類錯 ⇒ 每個點標註並覆核 |
| S1e | 2 | 匯出登記改產生；PDF 例外路徑 |
合計約 8.5 pd；每步可單獨上線，任何一步紅了只回滾該步。

## 9. 2026-10-15 使用者裁示對 S1 的影響（只改文件，S1a 程式不變）

承接 `T64-F7-FIELD-POLICY-DESIGN.md` §11（受保護層）與 §12（單位維度）。對 S1 的約束：

1. **S1 不實作受保護層**，但**不得寫死任何會擋住它的東西**：
   - 目錄 `moneyClass` 值域保留 `protected`（S1a 的 54 筆全是 `money`；P0 盤點前不新增 `protected` 條目）；程式與測試裡不得出現 `hardlock`。
   - `tier_allowed(ceiling, user)` 維持『一個天花板 → 一支既有函式』的單一對映處。P1 要在這裡加讀 `protected_grant`（只對 `protected` 欄位），所以 S1b–S1e 的出口**一律只呼叫 `visible()`／`mask_flags()`，不得自己呼叫 `financial_mask.*_visible`**——否則 P1 的授權層會被旁路。S1 的金標加一題守門（S1b 起）：出口檔案內不得再直接 import 那四支角色函式（白名單：`field_policy.py`、`financial_mask.py` 本體、擋整支端點的 `_require_user`）。
   - 受保護欄位在 P0 盤點出的出口，**不在 S1 遷移範圍**；P1 時才接 `visible()`。S1 完成後它們仍走今天的函式，行為不變。
2. **求值順序的終態**（寫在 `field_policy` 檔頭，S1 不實作）：`可見 = (原天花板 ∨〔僅 protected〕授權受眾命中) ∧ 政策`；錯誤一律 fail-closed。
3. **目錄新增欄位屬性的位置已預留**：`kind`（S1a 已加）、`exceptions`（S1a 已加）；P0 再加 `protectedSurfaces`（該欄位出現的出口清單）。
4. **單位**：S1 不碰。`owner_unit_id` 等單位鍵留在 `core/internal_cols.py` 的剝除，不進目錄的 `api` 鍵名（S1a 的 `problems()` 已擋非 key 種類有 API 名；單位鍵將以 `protected` 條目登記，且 `api=None`）。
5. **工量**：S1 本身不變（約 8.5 pd）；P0／P1／P2／S5a／S5b 見 F7 設計 §8，**不併入 S1**。
6. **順序建議**：S1（純重構）→ S2（政策）→ P0 → P1/P2 → S5a。P0 的盤點結果可能改變 S1c/S1d 的出口清單（若發現受保護欄位與金額欄位同一端點），屆時回頭補註即可，不影響 S1a。
