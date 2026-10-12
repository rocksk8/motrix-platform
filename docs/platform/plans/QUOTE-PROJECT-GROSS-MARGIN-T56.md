# 報價單「專案毛利%」設計（脊柱登錄項；僅文件，未跑任何測試）

> 日期：2026-10-12　作者：hichan-98　狀態：r1 草稿，待非作者稽核
> 依據樹：`f5ffce7d0`（M2 r3 基準；唯讀盤點，行號僅供起點）；脊柱：`FIELD-LAYOUT-FRAMEWORK-T56.md` r6（`wip/t56-field-layout-framework-r6`）。
> 需求（使用者，經 1c 轉）：報價單多一個「專案毛利%」＝（未稅營業收入 − 未稅報價服務產品成本）÷ 未稅營業收入；成本**不扣**攤分保留款、公益金、5% 稅等，是乾淨的專案毛利，與既有「直接毛利／營業利益」並存。

## 0. 結論（先看）

1. **定義**：`專案毛利% ＝ (tot.pretax − tot.totalCost) ÷ tot.pretax × 100`，四捨五入到 1 位小數（與 `directMarginPct` 同進位：`round_half_up(x, 10) / 10`）。分子分母都取**報價單已存的合計**，不另立第二套算法。
2. **與既有「直接毛利率」的差異恰為進項稅**：現行 `directProfit = pretax − totalCost − inputVat`（`inputVat = round_half_up(totalCost, 5%)`，`profit_rules.quote_profit`／`profit-rules.js quote`）。專案毛利**不扣 `inputVat`**，因此同一張單的專案毛利% 會比直接毛利率高約「成本的 5% ÷ 未稅收入」。這是使用者要的差異（「不扣 5% 稅」），不是兩套口徑打架；畫面標籤並列即可。
3. **不新增儲存欄、不需遷移**：由 `tot.pretax` 與 `tot.totalCost`（新舊單皆已存）**讀取時計算**；單一函式（後端 `helpers/profit_rules.py`，前端 `static/profit-rules.js` 為孿生，共用黃金向量）。舊單、已精算單自動有值，不需 recalc。
4. **框架化（脊柱登錄，不是硬接）**：欄位目錄一筆（`isMoney` 真、金額類別 `internal`）、顯示／隱藏／位置／寬度走版面設定、標籤可改、可選警示門檻為設定項（預設關）、清單欄為可選欄（預設隱藏）。程式只負責「計算」與「登錄」，其餘皆管理者在系統內調整。
5. **安全不變式不動**：客戶版 PDF／預覽／回簽頁／客戶版 Excel **永不出現**（`internal` 規則）；無金額權限者看不到（沿用 `tot` 在 `QUOTE_MONEY_KEYS` 的遮蔽，清單別名加入 `QUOTATION_MONEY_COLS`）。
6. **工量**：約 **2.75 pd**（含脊柱登錄與測試）；若脊柱 A6 登錄與目錄種子尚未落地，先做計算＋表單區塊（≈1.25 pd）、登錄隨 A6 種子補（≈ +1.5 pd）。口徑已由使用者原話確定（r2），**無阻擋性使用者問題**（§9 僅一項非阻擋、可延後）。

## 1. 現況盤點（重用同一套成本基數）

| 項目 | 現況（f5ffce7d0） | 與本案的關係 |
|---|---|---|
| 成本合計 | `profit_guard.server_profit`：`total_cost = Σ qty × cost`（跳過非 dict；`header` 列 qty／cost 為空 ⇒ 0）；前端 `quotation-form.html calcTotals()` :2458 同式 | **分母外的成本基數就是它**，不另算 |
| 進項稅 | `input_vat = round_half_up(total_cost, 0.05)`（:162／:2459） | 專案毛利**不扣**；直接毛利仍扣 |
| 未稅收入 | `server_totals`：`pretax = Σ item_amount − discount + freight`；`item_amount = round_half_up(qty, unitPrice)` | 已含折讓與運費；專案毛利吃它 |
| 直接毛利 | `profit_rules.quote_profit`：`direct = pretax − total_cost − input_vat`；`direct_pct = direct / pretax × 100`（pretax ≤ 0 ⇒ 0） | 對照口徑；不更動 |
| 管銷／公益 | `admin_cost`＝max(直接毛利,0)×pct；`charity`＝直接毛利×1%（或含稅額×1%）；`total_indirect`、`netProfit`、`netMarginPct` | 專案毛利**完全不含**（使用者明確要求） |
| 合計存放 | 前端算好送 `tot`；v2 模式後端 `prepare()` 重算並覆寫（`server_totals`＋`server_profit`）；legacy 只做影子比對；已精算／結案沿用資料庫現值（`SETTLED_PROFIT_KEYS`） | `tot.pretax`／`tot.totalCost` 於三種路徑皆已存在，直接讀 |
| SQL 欄 | `quotations.total／pretax／direct_margin_pct／net_margin_pct`（`db.py:508`、`quotations.py:1912` 寫入）；`QUOTATION_MONEY_COLS` 為遮蔽清單 | 本案**不加 SQL 欄**；清單用 `json_extract(data_json,'$.tot.totalCost')` 與既有 `pretax` 欄計算（清單 SQL 本已對 `data_json` 做 `json_extract`，見 `quotations.py` :826） |
| 遮蔽 | `financial_mask.QUOTE_MONEY_KEYS` 含 `tot`；`ITEM_MONEY_KEYS`＝cost／margin／unitPrice／amount | `tot` 整包被遮 ⇒ 讀取時計算的專案毛利只會出現在「本來就看得到 `tot`」的輸出 |
| 兩種金額權限 | `quote_money_visible`（superadmin／admin／sales／finance）＝報價單頁內部成本；`money_visible`（superadmin／finance／cashier）＝案件頁（M3 T4 已明文：兩者不得互換） | 專案毛利沿用與 `directMarginPct` **相同的判定函式**，各介面不另創 |
| 畫面 | `quotation-form.html` :1846–1907：直接毛利、直接毛利率（`MotrixMargin.tone`）、管銷、公益、間接合計、營業利益／率 | 新增一行在直接毛利附近（預設位置見 §4） |
| 報價異動紀錄 | `_TRACKED_QUOTE_FIELDS`（`quotations.py` :109）已含 `tot.directMarginPct`；`financial_mask.HISTORY_MONEY_FIELDS` 為其遮蔽 | 專案毛利是**衍生值**，不追蹤、不入歷史（避免與成本／單價異動重複）；見 §8 |
| 內部 PDF | `pdf_gen.py` 約 :2680–2702 是**精算**損益摘要（原始預估 vs 實際），非報價單 PDF | 專案毛利不在報價單 PDF；精算頁見 §7 |

## 2. 定義（精確）

```
專案毛利金額 = tot.pretax − tot.totalCost
專案毛利%    = 專案毛利金額 ÷ tot.pretax × 100      （四捨五入到 0.1，半進位）
```

- **分母**：`tot.pretax`（未稅營業收入，已扣折讓、已加運費；這是報價單既有的「未稅」）。
- **分子的成本**：`tot.totalCost`＝Σ(數量 × 成本單價)，**不含**：進項稅、攤分保留款、公益金、管銷、舊口徑五項間接成本、營業稅。
- **`pretax ≤ 0`**：回「無值」（畫面顯示「—」，不顯示 0%）；與 `directMarginPct` 的 0 不同，原因：0% 會被誤讀成「剛好打平」。此差異只在顯示層，函式回 `None`。
- **虧損（成本 > 收入）**：回負數，**不補零**（管銷／公益的「虧損以 0 計」是它們自己的規則，不適用於毛利率）。
- **折讓**：已反映在 `pretax`（收入減少，成本不變 ⇒ 毛利下降）。符合「未稅營業收入」。
- **運費**：計入收入；成本只計品項成本——運費若有實際成本，使用者應以品項登錄（既有行為，新口徑已不收五項間接成本，使用者 2026-10-09：費用一律走請款申請）。
- **`unitPriceOverride` 品項**：只影響單價（是否由成本＋毛利反推）；`amount` 仍是 qty × unitPrice、成本仍是 qty × cost，專案毛利照常（單價被手動壓低 ⇒ 單項毛利下降，會如實反映）。
- **成本未填**：`cost` 空／0 的非標題品項視為成本 0；專案毛利會偏高。顯示層加一行小字「有 N 項尚未填成本」（`N` 由同一函式的輔助回傳計算；N＝0 不顯示）。這是提醒，不是阻擋。
- **擇一方案（M3）**：`tot` 已只計 `counted_items`（非擇一項＋各組所選），`pretax`、`totalCost` 自動隨之；**專案毛利不另寫分流**。有未選組別時沿用 M3 T5 規則：主合計列中性色並加「尚有 N 組擇一未選，為不含擇一項的暫估」。`plan_view`（T4）在每個方案列另回 `projectMarginPct`（用同一函式，輸入為該方案的 `pretax`／`totalCost`）。
- **標題列（`type=header`）**：無金額、無成本，不影響。
- **幣別／稅別**：零稅率／免稅單的 `pretax` 定義不變（未稅），公式不變。
- **進位**：`round_half_up(pct, 10) / 10`，與 `directMarginPct` 一致；比較／警示用**進位後**數字（顯示與警示一致，不出現「顯示 12.0% 卻因 11.96% 觸發」）。

## 3. 實作位置（單一函式、讀取時計算、免遷移）

- **後端**：`helpers/profit_rules.py` 新增 `project_margin(pretax, total_cost) -> dict`，回 `{amount, pct, uncosted_items}`：
  - 純函式、無 I/O；`pretax ≤ 0` ⇒ `pct=None`。
  - 輸入來自 `tot.pretax`／`tot.totalCost`（不重掃品項），`uncosted_items` 另由 `count_uncosted(items)`（走 `counted_items`）。
  - **不寫入 `tot`**：避免多一個必須與舊單同步的戳記（`_restore_stamps`、`SETTLED_PROFIT_KEYS`、影子比對都不必改）。
- **前端**：`static/profit-rules.js` 孿生 `projectMargin`；`calcTotals()` 之外的**顯示層**讀 `tot.pretax／tot.totalCost` 計算，不進 `this.tot`（避免 `FORM_VERSION` 之外再動儲存形狀）。**共用黃金向量檔**（既有 profit_rules 黃金向量增加專案毛利案例）。
- **端點回傳**：報價單詳情／案件詳情／`plan_view` 的回應中，於**已通過金額遮蔽的輸出**附 `projectMargin`（權限不足者整個 `tot` 已被剔除，故不另開洩漏面）；不新增獨立端點。
- **清單**：案件清單 SQL 加計算欄別名（`ROUND((pretax - COALESCE(json_extract(data_json,'$.tot.totalCost'),0)) * 1000.0 / NULLIF(pretax,0)) / 10.0 AS project_margin_pct`，**僅在管理者啟用該欄且請求者通過 `money_visible` 時才選取**）；別名加入 `QUOTATION_MONEY_COLS`（遮蔽雙向守門）。SQLite 的捨入與 Python 半進位在 .x5 邊界可能不同 ⇒ **清單改取 `pretax`／`totalCost` 兩數在 Python 端用同一函式算**（不用 SQL 內捨入），避免兩處數字差 0.1。
- **為何不加 SQL 欄／不存 `tot`**：(a) 既有 SQL 四欄（`total／pretax／direct_margin_pct／net_margin_pct`）已是 M3 回簽重算必須同交易更新的集合（M3 §H）；再加一欄＝再多一處同步點；(b) 衍生值讀取時計算＝舊單、已結案單、擇一暫估都自動一致；(c) 免遷移 ⇒ 不佔 M 班的資料遷移與回滾面。

## 4. 脊柱登錄（框架化）

登錄為**一筆欄位目錄項**（隨 A6「登錄與目錄種子」一起進種子，不是另一條機制）：

| 屬性 | 值 |
|---|---|
| 鍵（內部） | `project_margin_pct`（目錄鍵；不顯示給使用者） |
| 表面 | 報價單頁「內部損益」區塊（`form` 的合計區）；案件清單（`list`，可選欄）；案件詳情的報價摘要（`page` 區塊，內部） |
| 預設標籤 | 「專案毛利%」（標籤可由管理者改，F5） |
| 型別／格式 | 百分比、1 位小數（D2 格式化器的 `percent` 格式；格式化器未落地前沿用 `toFixed(1) + '%'`） |
| 金額旗標 `isMoney` | **真** |
| 金額類別 | **`internal`**（客戶版輸出不可用；編輯器不提供放入客戶通道的操作；驗證器遇到即擋；輸出端再擋一次） |
| 可用通道 | 畫面編輯、內部畫面預覽、Excel（內部）；**不含** 客戶版 PDF、客戶預覽、回簽頁、客戶版 Excel |
| 可見性判定 | 與 `directMarginPct` 相同：報價單頁＝`quote_money_visible`；案件頁／清單＝`money_visible` |
| 預設顯示 | 報價單內部損益：**顯示**，位置＝「直接毛利率」之後；案件清單：**隱藏**（可選欄，今日零變化） |
| 預設寬度 | 內部損益列為單行（無寬度屬性）；清單欄＝窄欄檔位 |
| 欄位來源 | 系統計算欄位（`source=computed`）：來源函式 `project_margin`；**管理者不可改算式**（算式是程式，不是管理者能力——脊柱邊界 §14） |
| 可改性 | 唯讀（衍生值，不可編輯） |

**版面可調的項目（管理者在系統內）**：顯示／隱藏、同區塊內順序、清單欄的位置與寬度檔位、標籤文字、小數位數的**格式選項**（D2，預設 1 位）。**寫死的只有**：算式、`internal` 不入客戶通道、金額權限遮蔽。

### 4.1 警示門檻（設定項，預設關）

- 設定鍵：群組 `project_margin`、鍵 `project_margin.warn_pct`（PM 命名裁定：一個功能一個 snake_case 群組，鍵為 `<群組>.<鍵>`；登錄於 M2 設定登錄；本案**自第一天就走登錄**，不新增常數）。型別：0～100、至多 1 位小數，或「不啟用」；**預設＝不啟用**（今日行為零變化）。
- 行為：僅**顯示警示**（數字旁淡色提示「低於門檻 X%」），**不阻擋存檔、送審、回簽**（阻擋屬簽核政策，不在本案；若日後要「低於門檻須審核」，應作為簽核政策選項另案登錄）。
- 群組：獨立群組 `project_margin`（顯示名「專案毛利%」）；與 K01 利潤警示群組的關係由 K01 落地時決定，不改本鍵。
- 風險類別：`none`（只改顯示）；**非高影響選項**，不需橫幅；放寬／收緊皆即時生效並留變更帳本（沿用 M2 帳本）。白話題目：「專案毛利% 低於多少時，在報價單上提醒業務？」；影響說明：「只改畫面提示，不影響存檔與審核。」
- 比較用進位後數字（§2）。與 K01 的 `MotrixMargin.tone` 色階互不干涉：專案毛利預設**不上色**（中性），啟用門檻後才用既有警示色。

### 4.2 本案要登錄的東西（脊柱接案清單的實例；通用清單見路線圖 r6 §3C）

| 項目 | 本案 |
|---|---|
| 1. 要顯示什麼 → 目錄項 | `project_margin_pct`（§4 表） |
| 2. 金額旗標與類別 | `isMoney` 真、`internal` |
| 3. 哪些表面 | 報價單內部損益、案件清單（可選欄）、案件詳情報價摘要 |
| 4. 哪些通道 | 畫面內部、Excel 內部；客戶通道排除 |
| 5. 權限判定函式 | 沿用 `quote_money_visible`／`money_visible`（與 `directMarginPct` 一致） |
| 6. 設定項 | 警示門檻（預設關）；群組、題目、影響、風險類、預設值＝今日行為 |
| 7. 標籤 | 預設「專案毛利%」；可改 |
| 8. 守門 | 目錄 ⇔ 遮蔽雙向、白話守門、預設＝今日（見 §6） |
| 9. 文件 | 欄位說明、`docs` 中既有利潤口徑說明加一段對照表（專案毛利／直接毛利／營業利益） |

## 5. 內部／客戶輸出

| 輸出 | 專案毛利% |
|---|---|
| 報價單編輯頁（內部損益） | 顯示（有 `quote_money_visible`） |
| 客戶預覽／客戶 PDF／回簽頁／客戶版 Excel | **永不**（`internal`；驗證器擋、輸出端再擋） |
| 內部 Excel（欄位版面 B4 的內部通道） | 可選，預設隨畫面 |
| 精算 PDF／精算頁 | 本期不加（見 §7，需口徑確認） |
| 異動紀錄（`editHistory`） | 不追蹤（衍生值） |
| 下載檔名（A7） | **永不**含金額，專案毛利亦屬金額類 |
| 完工單帶入（A8） | 白名單 ∩ `isMoney=假` ⇒ 自動排除 |

## 6. 測試（紅 → 綠）

1. **黃金向量**（後端／前端共用檔）：一般案；折讓；運費；`pretax = 0`（回 None）；`pretax < 0`；成本 > 收入（負值、不補零）；0.05 邊界進位（如 pct 為 x.x5）；全部成本未填（100%，並 `uncosted_items = N`）；`header` 列混入；`unitPriceOverride` 品項。
2. **與直接毛利的恆等關係**：對隨機品項集，`專案毛利金額 − 直接毛利 == input_vat`（未結案單）——鎖住「差異恰為進項稅」。
3. **擇一**：兩組未選 ⇒ 只計非擇一項（與 `counted_items` 一致）；已選 ⇒ 計所選；`plan_view` 每個方案列的專案毛利＝以該方案 `pretax`／`totalCost` 呼叫同一函式。
4. **遮蔽（正反對照＋突變）**：無金額權限者的報價詳情、案件詳情、清單、`plan_view` 不含專案毛利（含別名欄位）；有權限者有；把專案毛利放進客戶通道的版面被驗證器擋；客戶 PDF／預覽／回簽頁輸出文字不含「專案毛利」。
5. **目錄 ⇔ 遮蔽雙向守門**：`project_margin_pct`（internal、isMoney）對應的鍵／別名出現在 `QUOTE_MONEY_KEYS`／`QUOTATION_MONEY_COLS`；反向亦然。
6. **設定**：預設值＝不啟用（`test_settings_defaults_equal_legacy` 樣式）；白話守門（題目、影響不含鍵名）；啟用後以**進位後**數字比較；不阻擋存檔（端點測：低於門檻仍 200）。
7. **舊單／已結案單**：無 `tot.totalCost` 的極舊單 ⇒ 函式回 None（不丟例外）；已精算單值不隨精算改變（因為讀 `tot`）。
8. **清單**：欄位預設隱藏時回應形狀不變（golden）；啟用時數字與詳情頁逐位相同（同一函式）。
9. 前端：`FORM_VERSION` 守門（表單內容雜湊變 ⇒ 升版）照常；e2e 一條：內部損益區塊出現專案毛利、客戶預覽不出現。

## 7. 範圍外／後續

- **精算頁的「實際專案毛利%」**：精算的實際成本含承攬派發、額外支出、稅支出列；是否都屬「未稅專案成本」是另一個口徑問題（§9 Q2）。本期不做；若要做，用同一函式，輸入換成 `quotedPretax` 與「實際成本（未稅）」。
- **簽核門檻／低於毛利須審核**：屬簽核政策，另案（走政策設定）。
- **報表（reports.py）新增專案毛利彙總**：另案，作為第 2 層登錄（報表欄位）。

## 8. 風險

| # | 風險 | 影響 | 對策 |
|---|---|---|---|
| 1 | 與直接毛利率並列，業務混淆 | 溝通 | 白話說明小字：「不含進項稅、管銷、公益」；標籤並列；說明加進利潤口徑文件 |
| 2 | 成本未填使毛利偏高 | 誤導 | `uncosted_items` 提醒；不阻擋 |
| 3 | 清單 SQL 捨入與 Python 不同 | 兩處差 0.1 | 清單在 Python 端算（§3） |
| 4 | 脊柱 A6 尚未落地時要先交付 | 先硬接，之後補登錄 | 先做函式＋表單區塊（不含登錄），登錄隨 A6 種子補；函式與顯示層介面不變 |
| 5 | 衍生值被誤存進 `tot` | 戳記／遷移面擴大 | 本案明文「不寫入 `tot`」；測試 7 鎖定 |
| 6 | 金額權限判定函式選錯（`quote_money_visible` vs `money_visible`） | 外洩或看不到 | §4 明列各介面判定；測試 4 正反對照 |

## 9. 需要使用者回答的問題（只列不可逆者）

（r2：原 Q1 口徑確認已由使用者原話解決——未稅成本＝Σ(數量 × 品項成本)、不另扣進項稅／保留款／公益／5% 稅，數字高於直接毛利率是預期，不再是使用者問題。）

1. （非阻擋）精算頁要不要也顯示「實際專案毛利%」？若要，需另說明『實際成本』哪些算入（承攬派發、額外支出、稅支出）。可延後到上線後回答。

其餘（位置、標籤、是否預設顯示、門檻）皆為設定預設值或 PM 決定，管理者之後可在系統內改。

### 9.1 標籤說明文字（白話，預設值；管理者可改）

- 標籤：「專案毛利%」
- 說明：「（未稅營業收入 − 未稅品項成本）÷ 未稅營業收入。成本只算報價品項的『成本單價 × 數量』，不另外扣進項稅（5%）、管銷分攤、公益捐款與保留款。因此這個數字會比『直接毛利率』高，差距就是成本的 5% 進項稅部分，不是計算錯誤。」
- 守門：說明文字不含鍵名／代碼；「直接毛利率」「營業利益率」為畫面現有名稱。

## 10. 工量

| 項 | pd | 備註 |
|---|---|---|
| 後端函式＋黃金向量＋恆等測試 | 0.5 | `profit_rules.py` ＋ 前端孿生 |
| 報價單內部損益區塊（顯示層；含「N 項未填成本」） | 0.25 | `FORM_VERSION` 升版 |
| 端點回傳（詳情／案件詳情／`plan_view`）＋遮蔽測試 | 0.5 | 無新端點 |
| 清單可選欄（Python 端計算）＋別名遮蔽 | 0.5 | 預設隱藏 |
| 脊柱登錄（目錄項＋設定項＋標籤＋守門） | 0.75 | 依賴 A6 種子；A6 前先放 0.25 的硬接版 |
| 文件（口徑對照表） | 0.25 | |
| **合計** | **2.75** | A6 前可先交 ≈1.25，餘 ≈1.5 隨種子補 |

不含：官方閘門／建包／稽核的列車固定成本（每班另計）。建議併入有 `quotation-form.html` 動工的里程碑（與 A8／M3 T5 同檔需排串行，避免同檔衝突）。

## 11. 來源

- `backend/helpers/profit_rules.py`（`quote_profit`、`admin_cost`、`charity`）、`backend/modules/case/profit_guard.py`（`server_totals`、`server_profit`、`prepare`、`SETTLED_PROFIT_KEYS`）、`frontend/static/profit-rules.js`、`frontend/pages/quotation-form.html`（:1846–1907、:2455–2482）、`backend/helpers/financial_mask.py`（`QUOTE_MONEY_KEYS`、`ITEM_MONEY_KEYS`、`QUOTATION_MONEY_COLS`）、`backend/modules/case/api/quotations.py`（:109 追蹤欄位、:821 清單 SQL、:1912 SQL 欄寫入）、`backend/pdf_gen.py`（精算摘要）。
- 設計：`FIELD-LAYOUT-FRAMEWORK-T56.md` r6（§3 目錄、§7 權限、§14 脊柱、§16 插槽與橫幅標準）、`M3 擇一方案計畫 r11`（`counted_items`、T4 `plan_view`、T5 內部面板）。
