# M3「擇一方案報價」工作分解（設計者 1d；僅文件，不含程式）

> 依據：`QUOTE-CASE-DISPLAY-FRAMEWORK-SCOPE-T54.md` §9／§9.11（`wip/t54-n39-settings-design`，commits 90256d9aa／52b6bf97c）＋使用者 10-11 全部裁示（見 §1）。
> 程式錨點取自 `origin/train/m2-int-r2`＝8207b54d8（M2 凍結樹）；**M3 實作須以 M2 上線後的 `origin/platform` 為底，錨點行號開工前重核**。
> 目標 10～13 pd；本分解 **12.25 pd**（r2：T9 因 API 變更與鎖定集合 +0.25）（§3）。範圍＝擇一方案報價側；不含「勞報單選關聯派發」（≈4 pd，05 另案）。

## 0. 與設計文件相比，已變動的事實（先看）

1. **標籤更名（設計 §9.7 #4）已隨 M2 完成**：`quotation-form.html` 已是 `FORM_VERSION='V3.22'`、`AFTERSALES_LABEL='售後服務及備註說明'`，`pdf_gen.py:337`、`quote_terms.py:47` 同步。M3 **不再做**；僅留守門「不得回退」。
2. **回簽「稍後確認」已被裁示否決**（使用者 10-11：回簽必須選定、不可延後）→ 設計 §9.6 的「稍後確認／待確認方案／每週提醒」與 §9.10-3 作廢；不做提醒框架接線，省約 0.5 pd。
3. **§9.9 排 M2 的部分，使用者改排整塊到 M3**（M2 已凍結，不含擇一）。
4. **下游吃的是報價單「資料表欄位」不只 `data_json`**：`arap/api/invoice_vouchers.py`、`payment_requests.py` 讀 `q["total"]／q["pretax"]`（SQL 欄位）；存檔 SQL `quotations.py:1912` 同步寫 `total, pretax, direct_margin_pct, net_margin_pct`。回簽選定重算**必須同交易更新這四欄**，否則請款／開票基數與報價頁不一致（設計文件只講 `tot`，漏了這層）。
5. 計算單一來源現況：後端 `profit_guard.server_totals／server_profit`（`item_amount` 為切入點）、前端 `quotation-form.html calcTotals()`（:2455）、`settlement_actuals.py` 讀 `tot.pretax／tot.total`、`pdf_gen.py` 讀 `tot`、`helpers/financial_mask.py` 遮罩。擇一必須只在 `counted_items` 一處分流。

## 1. 已定裁示（不再問；實作照此）

| 項 | 裁示 |
|---|---|
| 單據 | 購料報價＝同一種報價單（同表單同資料表；`quote.alt_enabled` 總開關） |
| 合計遮蔽 | 「合計依方案選擇」只遮**兩格**（稅前合計、總計）；小計／稅額列照常（不遮） |
| 回簽 | **必須選定，不可延後**；有未選組別不得完成回簽 |
| 選定前面板 | 各方案各自按自己毛利率上色；**主合計列中性色**（暫估） |
| 組合檢視 | 預設收合、列前 24（`combo_view_max`，設定可調、範圍 1–200）、程式硬頂 200 |
| 組間基準 | 單項方案表中「其他組」取**各組第一個選項**，畫面可暫切換（不存檔） |
| 案件頁 | 比較表限有成本權限者 |
| 機密 | 成本比較面板僅內部；**不進客戶版／PDF／Excel／回簽頁** |
| 文字 | 「依方案選擇」、擇一備註句、售後服務及備註說明預設＝管理者可調範本（設定中心 `quote_alt` 群組），改範本不改歷史單 |
| 回簽後鎖定（10-12） | 回簽後品項（含擇一組別、增刪、單價數量）**鎖定**；要改須先「取消回簽」 |
| 取消回簽（10-12） | **清除**已選定（`altPicks` 清空、合計／毛利／SQL 四欄回到未選暫估、寫稽核）；重新回簽需重選 |
| 已請款／已開票後（暫定，**未裁示**） | 假設**鎖定**（連取消回簽也擋，需先沖銷）；見 §7 Q3 |
| 框架原則 | 預設＝今日行為；無 `altGroup` 的單逐位元不變；設定頁全白話、無代碼 |

## 2. 任務順序與相依

```
T1 ─► T2 ─┬─► T3 ─┐
          ├─► T4 ─┼─► T5 ─► T6
          └─► T7 ─┘          │
T2 ─► T8 (PDF/Excel)          ▼
T2,T4 ─► T9 (回簽選定) ─► T10 (案件頁／下游) ─► T11 (收尾)
```
關鍵路徑：T1→T2→T4→T9→T10→T11。T3、T7、T8 可與 T4 並行（不同檔）；T5、T6 同檔（`quotation-form.html`）須序列，同一人做。

### T1 前置核對與契約凍結（0.5 pd）
- **寫入路徑清單（全文檢索，逐一標註「可否改品項／`altGroup`／`totalsByAlt`／`altPicks`／`tot`／`is_signed`」）**：必含 `update_quotation`（PUT）、`update_status`（PATCH，:1975）、`toggle_quotation_signed`（:1323）、`reject_quotation`（:4985，寫 `status='草稿'`，同樣不動 `is_signed`，須併入上列「移出已送出」處理）、`case_batch_assign`（:6391 起，寫 `data_json`＋`assigned_user_ids`；**僅動指派欄位**，須以測試證明不改品項／`tot`，否則併入鎖定檢查）；`recall_quotation`（:2053）只收 待審核／簽核中，**不是**已回簽單的路徑（已回簽必為 已送出）。未列入而在檢索中出現的寫入點視為遺漏。
- 重核錨點（`profit_guard.py`、`calcTotals`、`quotations.py:1912` 存檔 SQL、`_signed_back_gate`／`toggle_quotation_signed`、`pdf_gen` 合計區、`settings_registry` 註冊樣式）。
- 寫死「契約表」：`altGroup`／`altPick` 欄位、`totalsByAlt`、`altPicks`、`counted_items` 簽章、`plan_view` 回傳形狀、`quote_alt` 設定鍵；之後各任務不得自行加欄。
- 產出：本文件 §5 的「契約」小節補正，並把黃金向量檔（擇一向量）先定案（T2/T3/T4 共用）。

### T2 資料模型＋單一計入集合（1.5 pd）
- 品項加 `altGroup`（字串，空＝非擇一）；報價單層 `totalsByAlt`（bool，預設 false）、`altPicks`（`{組: 品項id}`）。**不用巢狀結構**；舊單缺鍵＝全計入。
- `profit_guard.counted_items(q)`：非擇一項＋（該組已選→所選／未選→空）。`server_totals`、`server_profit`（成本、進項稅）全改只走它；`prepare()` 的管銷／公益金戳記邏輯不動（只換基數）。
- 驗證規則（422）：同組至少 2 項；`type=header` 不可擇一；組數 ≤ `alt_groups_max`；`altPicks` 的值必須是該組內的品項；非擇一項不可出現在 `altPicks`。
- 已精算／已結案（`is_settled`）：不重算戳記、不接受改 `altGroup`／`altPicks`。
- 不納入合計 ≠ 不能存：未選項單價／成本照存。

### T3 前端同式計算（0.75 pd）
- `calcTotals()` 改走前端 `countedItems()`；未選項灰字＋「擇一」標籤；`totalsByAlt` 勾選與組別輸入（欄位放在 T6 一起做 UI，這裡只做計算）。
- 與後端用**同一份擇一黃金向量**（沿用 `static/profit-rules.js`／`helpers/profit_rules.py` 的雙端向量樣式與 `test_e2e_quote_reasons_parity` 的 parity 樣式）。

### T4 `plan_view` 後端＋成本權限（1.25 pd）
- `plan_view(q, selection)`：以「非擇一項＋各組所選」重算並回傳：未稅、含稅、成本、進項稅、直接毛利、毛利率、管銷（直接毛利×單上戳記 `overheadPct`）、公益金、營業利益、利潤率、燈號。與 `server_totals／server_profit` 共用 `counted_items`；純函式、不寫庫、不寫稽核、不改 `data_json`。
- 單項方案表（每組每選項；其他組取各組第一個選項或呼叫端傳入的基準）＋組合列表（乘積；依毛利率排序；`combo_view_max`；硬頂 200，超過只回組數）。
- 端點：僅回應「具成本權限」者（沿用 `financial_mask.quote_money_visible`／`money_visible`）；無權限回應**不含**任何成本、毛利、管銷、燈號欄位（後端剔除，不是前端隱藏）。已精算／結案：唯讀、不重算戳記。
- 燈號門檻讀現行 Q1–Q8 設定；每個方案欄各自上色。

### T5 內部成本面板 UI（1.75 pd）
- 位置：報價單編輯模式、具成本權限才渲染；列印預覽（客戶樣式）不渲染。
- 單項方案表（方案 A、B、C 並排；手機改堆疊卡片）；表頭白話註明「其他組以〔某選項〕計」＋暫切基準（只畫面）。
- 組合檢視：預設收合；「共 M 種組合，僅顯示前 N 種」白話提示；排序切換。
- 前端只呈現 `plan_view` 回傳，不自算。

### T6 表單 UI（1.25 pd）
- 品項列「擇一方案」勾選＋組別名稱輸入；「合計依方案選擇」勾選；合計區兩格依狀態顯示範本文字；備註區即時預覽自動句。
- 主合計列：有未選組別時中性色＋白話「尚有 N 組擇一未選，毛利為不含擇一項的暫估」；燈號不得誤報綠。
- `FORM_VERSION` V3.22→V3.23（`test_form_version_bumped` 規則：程式動了必升版）；說明文字全白話。

### T7 設定群組 `quote_alt` 與範本快照（0.75 pd）
- 登記：`total_text`（依方案選擇）、`note_template`（項次{items}為{group}擇一方案選擇）、`show_unpicked_in_pdf`（否）、`alt_groups_max`（10）、`combo_view_max`（24）、`combo_view_default_open`（否）、`alt_enabled`（開）。每項含白話題目、影響說明、風險詞（文字類 legal；數字類 none/ops）。
- `default_aftersales_note` **不另存**，沿用 `quote_terms` presets（不建第二份）。
- 存檔時把當下採用的 `total_text`／`note_template` 快照進該單 `data_json`（`altTexts`），改設定不改歷史單。
- `alt_enabled` 關：介面不顯示擇一欄；已含擇一資料的舊單仍照資料計算與列印。

### T8 PDF／列印／Excel（1.0 pd）
- `pdf_gen` 合計區：`totalsByAlt` 且有未選組 → 稅前合計、總計兩格印快照文字；已選定 → 恢復數字且未選項不印（`show_unpicked_in_pdf` 可開灰字「未選」）。
- 品項表擇一標記；備註自動句：每組一句、接在使用者自填備註之後，變數 `{items}`／`{group}`。
- Excel 匯出與列印預覽、回簽頁走同一計入集合與同一範本函式；**輸出路徑不引用 `plan_view`**。
- 守門（正反對照）：含擇一單的 PDF 文字不得出現成本／毛利／管銷／方案表標題；內部畫面有、PDF 無。

### T9 回簽選定（1.75 pd）
**API 變更（契約，T1 凍結）**
- **sign（`toggle_quotation_signed` 開）**：請求 body 新增「每組所選」`picks`（`{組名: 品項id}`，涵蓋該單**全部**擇一組別）。伺服器在**同一交易**、**執行 UPDATE 之前**先驗：每個組別都有 pick、pick 屬於該組、非擇一項不得出現；任一不符 → 422 白話「請先選擇客戶採用的方案」，不寫任何東西。通過後同交易：寫 `altPicks`＋`altPickedAt／altPickedBy`、重算 `tot`、更新 SQL 四欄 `total／pretax／direct_margin_pct／net_margin_pct`、寫稽核（誰、哪組、哪項、金額前後）。無擇一組的單：body 不帶 `picks`，行為與今日逐位元相同。
- **unsign（`toggle_quotation_signed` 關）**：新增守門——單據已開票、已請款（含已提請款）或已精算／結案 → **409**（白話「已請款／已開票，請先沖銷」；Q3 暫定）。通過後同交易：清空 `altPicks`（及 `altPickedAt／altPickedBy`）、重算 `tot` 回未選暫估、更新 SQL 四欄、寫稽核，**稽核內容記錄被清除的內容**（原 `altPicks` 各組→品項、清除前後 `total／pretax`、操作者）。全部或全無（中途失敗整筆回滾）。
- **權限與前提（沿用，不變）**：`toggle_quotation_signed` 僅 admin／superadmin（:1328），且報價單狀態須為 `已送出`（:1341）；兩 action 皆然。
- **picks 驗證對象＝伺服器已存品項**（自資料庫讀出的 `data_json`），**不採用 body 內任何品項資料**；pick 的品項 id 必須存在於已存品項且屬該組。
- **unsign 守門的資料來源**：已開票＝`invoice_vouchers` 表（`quote_no`＋狀態欄）；已請款＝`payment_requests` 表（`quote_no`＋`status`）（兩表定義見 `db.py` 的 `CREATE TABLE`，以表名為準、不引行號）；已精算／結案＝報價 `settle_status`／`deal_tag`。「有效單據」的狀態值定義（排除草稿、已作廢／已取消／已退回）開工前自這兩張表的現行狀態集核對，不在本文寫死。
- 回簽介面逐組列選項（預設不預選）。
- **不做獨立「改選」動作**（10-12 裁示）：回簽後要換方案＝先取消回簽（清除選定、重算回暫估、寫稽核）→ 改 → 重新回簽並重選。管銷／公益金戳記沿用既有規則，只換基數。

**回簽後鎖定（伺服器端；r3 依 0d 複審更正鎖定路徑）**
- **現況事實（`case/api/quotations.py`，M2 凍結樹）**：`PUT /api/quotations/{quote_no}`（:1690）已在 `_LOCKED`（:1854-1857）對狀態 待審核／簽核中／已送出／已成案／已結案 回 403，**唯一例外是 `is_unlock_edit`**；該旗標來自用戶端 body 的 `_isUnlockEdit`（:1701 `q.pop`），僅另要求呼叫者為 superadmin（:1731-1734）。回簽（`toggle_quotation_signed`）需 status＝已送出，故回簽單在一般存檔必被 `_LOCKED` 擋下——**真正的洞是 unlock-edit 分支**。`is_signed` 是獨立欄位，存檔路徑目前**完全不讀**。
- **`is_signed` 會在狀態變動後殘留（r4 更正）**：`update_status`（`PATCH /api/quotations/{quote_no}/status`，superadmin，白名單 草稿／待審核／已送出／已取消／已拒絕）可把 已送出 改回 **草稿**，且不動 `is_signed`（`is_signed` 唯一寫入者是 `toggle_quotation_signed` 的 sign／unsign 兩條 UPDATE）。草稿不在 `_LOCKED`，一般 `PUT`（無 `_isUnlockEdit`）即可自由改品項，造成 `is_signed=1`＋`altPicks` 還在，但品項／`tot`／SQL `total／pretax` 已不一致。故「`_LOCKED` 擋 PUT」**不能**當作回簽鎖定的依據。
- **新增檢查（涵蓋 `update_quotation` 全部儲存路徑）**：只要**已存列 `is_signed=1`**（讀自既有 `SELECT`，:1795-1800 加選 `is_signed`），**不論當時狀態、不論 `_isUnlockEdit`、不論是否通過 `_LOCKED`**，一律對「鎖定欄位集合」與**已存值**比對，不同即 422「已回簽，請先取消回簽」。同一檢查套用到其他可改品項的路徑（T1 grep 清單見下）。不得以任何用戶端旗標或狀態作為放行依據。
- **`update_status` 把已回簽單移到 草稿／已取消／已拒絕（偏好做法）**：視同 unsign——同交易清除 `is_signed`（連 `signed_by／signed_at`）＋`altPicks`＋`tot` 回未選暫估＋SQL 四欄＋寫稽核（記錄被清除內容），**並套用與 unsign 相同的 409 下游守門**（已開票／已請款／已精算／結案 → 409，狀態不變）。**替代做法**：直接拒絕（409「已回簽，請先取消回簽」）。偏好做法由使用者／作者擇一，列 §7 Q11；實作前預設＝替代做法（拒絕），因為最保守、不新增清除路徑。移到 待審核 或維持 已送出 不觸發。
- **unlock-edit 往返下 `is_signed` 的去向**：unlock-edit 會把狀態強制改為 待審核（:1752-1760 一帶，重走簽核）；重新核准後回到 已送出，而 `is_signed` 全程未被動到，仍為 1。規則：該往返期間鎖定檢查照上條持續生效（品項不可改），因此 unlock-edit 對已回簽的擇一單**實際只能改鎖定集合以外的欄位**，往返前後 `altPicks`／`tot` 不變；若使用者要在 unlock-edit 裡改品項，必須先取消回簽（Q10）。
- **鎖定欄位集合**：品項（增、刪、改單價／數量／成本／`taxRate`）、`altGroup`、`totalsByAlt`、`altPicks`、`tot`。
- **unlock-edit 對「已成案」報價仍可做什麼＝不確定，列為待確認（§7 Q10，作者／使用者答覆）**：本設計要求**不得破壞既有已成案解鎖修改流程，唯一例外是「已回簽的擇一單」**（無擇一組的單、未回簽的單，unlock-edit 行為逐位元不變）。答覆前實作預設＝已回簽擇一單的 unlock-edit 只能改鎖定集合以外的欄位。
- **備註與附件是否在鎖定集合外＝§7 Q8**：預設假設可編輯，但伺服器必須明文列舉可改欄位，其餘比對拒絕。
- 已精算／結案、**已請款或已開票（暫定）**：取消回簽亦拒絕（Q3 待裁示）。
- `altPicks` 防悄悄改動：用戶端送來的 `altPicks`／`tot` 在一般存檔一律不採用，由伺服器放回（對照既有 `_restore_stamps`）；只有 sign 路徑能寫 `altPicks`。

### T10 案件頁與下游一致（1.0 pd）
- 案件詳情報價摘要：金額／成本／毛利／管銷／營業利益一律用所選後數字；另列「所選方案：〔組別〕→〔選項〕」。
- 具成本權限者可展開「方案比較」（唯讀、標示未採用）；回簽前（業務追蹤期）同樣可展開。
- 下游對帳清單（逐項核對取數來源是 SQL 欄位或 `tot`，皆須等於重算後數字；補整合測試，見 §4 I 類）：
  1. 開票：`arap/api/invoice_vouchers.py`（讀 `q["total"]／q["pretax"]`）
  2. 請款：`arap/api/payment_requests.py`（同上）
  3. 精算：`case/settlement_actuals.py`（:504-518 `tot.pretax／tot.total`、:577-582 `tot.directProfit／directMarginPct／adminCost`；`case/api/settlement_actuals.py` 為端點層，非取數處）
  4. 認列：`case/recognition.py`（:119 `_case_rows` 讀 SQL `total／pretax`；`caseRecord.payment.items` 亦由報價金額衍生）
  5. 營運報表／儀表板：`analytics/api/reports.py`（:2845、:3137 讀 SQL `total／pretax／net_margin_pct`）、`analytics/api/dashboard.py`（:39、:335 讀 `total／pretax`＋`data_json`）；其餘報表出口開工前全文檢索補全
  6. PDF／Excel／回簽頁：`pdf_gen.py`（讀 `tot`）
  7. 案件詳情報價摘要、`helpers/financial_mask.py` 遮罩後金額
  8. 成案（報價轉案件）與由報價產生的採購單（PO）：凡複製或引用報價金額／品項處（T1 以全文檢索補全清單，未列入者視為遺漏）

### T11 收尾與文件（0.75 pd）
- case 模組 `CHANGELOG`／`SPEC`／`README`、設定中心群組說明、`MODULE-GUIDE` §14 補「擇一計入集合」條目、更新登記（強制）、`route_table_golden` 重產。
- 步驟檔草稿段落：新設定預設值、驗收字母（使用者驗收項，白話操作清單）、**零資料遷移**（只加鍵，無 DB 版本變更；若 T1 判定需要新欄位則另列）。

## 3. 工量彙總

| 任務 | pd | 任務 | pd |
|---|---|---|---|
| T1 契約 | 0.50 | T7 設定群組 | 0.75 |
| T2 資料模型／計入集合 | 1.50 | T8 PDF／Excel | 1.00 |
| T3 前端同式 | 0.75 | T9 回簽選定 | 1.75 |
| T4 plan_view | 1.25 | T10 案件頁／下游 | 1.00 |
| T5 面板 UI | 1.75 | T11 收尾 | 0.75 |
| T6 表單 UI | 1.25 | **合計** | **12.25** |

不含：官方閘門／建包／稽核的列車固定成本（每班另計）、勞報單下拉（另案）。省項：標籤更名（已在 M2）、稍後確認＋提醒（作廢）。若 T5 組合檢視縮為只做單項方案表可再省 ≈0.5 pd（需使用者同意，見 §6 Q5）。

## 4. 測試清單（紅→綠；檔名隨 `_2026_10_XX` 慣例，在 `backend/modules/case/tests/` 或 `backend/tests/`）

**A 計算（向量）**
1. 無 `altGroup` 的單：`server_totals／server_profit` 與現行黃金向量**逐位元相同**（零行為改變；舊資料樣本取自真實形狀）。
2. 兩組擇一、未選：合計只含非擇一；成本／進項稅／管銷／公益金皆以計入集合為準。
3. 已選：金額＝所選；`tot` 與把所選當一般品項的單**逐欄相等**。
4. 前後端同式：同一擇一向量，`calcTotals` ＝ `server_totals`（parity 樣式）。
5. 進位邊界：含小數數量×單價、稅率 0／免稅／缺 `taxRate`（沿用 `effective_tax_rate` 舊語意）下擇一向量。
6. 驗證 422：單項組、header 擇一、`altPicks` 指向他組、超過 `alt_groups_max`、非布林 `totalsByAlt`（遵守 MODULE-GUIDE §14.1 只收真布林）。

**B plan_view**
7. 核心對照：每個方案欄＝把該方案單獨當成「已選定」時 `server_totals／server_profit` 的輸出（逐欄）。
8. 3 組×3 項＝27 組合、排序正確；`combo_view_max=5` 只回 5 列＋總數；硬頂 200（設 999 仍受限）。
9. 呼叫前後 `data_json` 與 `overheadPct` 戳記相同、無稽核列、無 DB 寫入（唯讀斷言）。
10. 已結案單：唯讀、不重算。
11. 各方案燈號以自己的毛利率；主合計於未選時為中性。

**C 權限與機密（後端）**
12. 無成本權限：`plan_view` 回應不含成本／毛利／管銷／燈號欄位（正反對照：有權限者有）。
13. 案件詳情比較表同上。
14. PDF／Excel／列印預覽／回簽頁對含擇一單：不含成本／毛利／管銷字樣與方案表標題；`pdf_gen` 原始碼不 import／引用 `plan_view`（守門式靜態檢查）。

**D 回簽**
15. 有未選組別時回簽 422；全選定可回簽。
16. 同交易：`altPicks`＋`tot`＋SQL 四欄＋稽核，全部或全無（中途失敗回滾）。
17. 用戶端偽造 `altPicks`／`tot` 於一般存檔被忽略。
18. 取消回簽：`altPicks` 清空、`tot`＋SQL 四欄回未選暫估、稽核有列；已回簽狀態下改品項／組別被拒；已結案拒絕。

18a. sign 驗證順序：缺任一組 pick／pick 非該組成員 → 422 且資料庫無任何變動（`altPicks`、`tot`、SQL 四欄、稽核皆不變）。
18b. 鎖定範圍（伺服器端）：已回簽（`is_signed`＝1）時，① 一般 `PUT`（無旗標）→ 403（`_LOCKED`，既有）；② **`_isUnlockEdit=true`（superadmin）改品項／`altGroup`／`totalsByAlt`／`altPicks`／`tot` → 422**（新檢查，明確覆蓋此情境）；③ 其他可改品項的路徑同樣 422；④ 備註、附件依 Q8（參數化兩種結果）；⑤ 對照組：已成案但**未回簽**、或**無擇一組**的單，unlock-edit 行為與今日逐位元相同（Q10 預設）；⑥ 繞過前端直接打 API 同樣被拒；⑦ **已回簽擇一單 → `PATCH …/status` 改 草稿 → `PUT` 改品項必須 422**（採偏好做法時：此 `PATCH` 已清除 `is_signed／altPicks／tot／SQL 四欄` 且稽核有列，或遇下游單據 409 不變；採替代做法時：此 `PATCH` 即 409）；⑧ 往返：unlock-edit→待審核→重新核准 已送出 後 `is_signed` 仍為 1、`altPicks`／`tot` 不變、品項仍被鎖。
18c. `totalsByAlt` 與 `altGroup` 經一般存檔切換：未回簽時可切換，合計／`tot`／SQL 四欄隨之重算；已回簽時被拒；切換前後無擇一的單逐位元不變。
18d. unsign 守門：已開票／已請款／已精算 → 409 且無變動；通過時稽核含被清除內容（原 `altPicks`、前後金額）。
18e. 取消回簽發生在**已成案（轉案件）或已產生採購單（PO）之後**：確認行為（擋下或同步／標記下游，依 Q3／Q9 答覆）且下游金額與重算後一致，不出現報價頁與案件／PO 金額分叉。

**E 輸出文字**
19. 兩格遮蔽文字＝快照；改設定後舊單不變；新單用新值。
20. 備註自動句多組、變數替換、接在自填備註之後；空組名的處理。
21. `show_unpicked_in_pdf` 開／關。

**F 設定與框架守門**
22. `test_settings_defaults_equal_legacy` 樣式：七個新設定預設值＝使用者原文／今日行為。
23. 白話守門：`quote_alt` 群組與表單新文字不得出現鍵名／代碼／英文列舉值。
24. 棘輪：不新增寫死的業務字串（「依方案選擇」等只在設定預設一處）。
25. `alt_enabled` 關：UI 不顯示、舊擇一單照算照印。
26. 標籤不回退：「售後服務」單獨標籤不得再出現（承 M2）。

**G 版本與路由**
27. `test_form_version_bumped`（V3.23）；`route_table_golden` 重產且無意外路由。

**H 前端**
28. 手機寬度面板堆疊；未選項灰字標籤；暫估提示在有未選組別時出現、全選後消失（UI 按鈕實點驗，依 feedback「UI 驗按鈕」）。

**I 下游整合**
29. 回簽選定後：`arap` 請款／開票基數＝重算後 `total／pretax`；精算取數與報價頁一致；營運報表同值。
30. 已開票／已請款的單取消回簽或改動 → 擋下（暫定，見 Q3）。

## 5. 契約（T1 凍結前的草案）

- 品項：`altGroup: str`（空＝非擇一；同值同組；組名即顯示名）。`altPick` **不存於品項**（設計 §9.2 有 `altPick` 布林，但已有 `altPicks` 對照表，兩處並存會分叉 → 建議刪 `altPick`，以 `altPicks` 為唯一來源；此為對設計的修正，T1 須取得使用者同意，見 §7 Q4）。
- 單層：`totalsByAlt: bool`、`altPicks: {組名: 品項id}`、`altTexts: {total_text, note_template}`（存檔快照）、`altPickedAt／altPickedBy`（回簽戳記，伺服器寫）。
- `counted_items(q, picks=None)`：`picks` 預設取 `q.altPicks`；`plan_view` 傳入假設選擇。
- 組名正規化：去頭尾空白；空白視同非擇一。

## 6. 風險

| # | 風險 | 對策 |
|---|---|---|
| R1 | 計算分叉（前端、後端、PDF、Excel、`plan_view` 各算各的） | 唯一 `counted_items`；共用黃金向量；PDF 路徑禁引 `plan_view`；測 4、7、14 |
| R2 | **下游讀 SQL 欄位 `total/pretax` 而非 `tot`** → 回簽後請款基數仍是舊的 | T9 同交易更新四欄；測 16、29 |
| R3 | 成本外洩（面板、API、PDF、案件頁） | 後端剔除欄位；測 12–14；只有 `cost` 權限者 |
| R4 | 乘積爆炸拖慢開單 | 硬頂 200；組數上限 10（3^10 仍超，故超頂只回組數不展開）；組合預設收合不計算（展開時才請求） |
| R5 | 毛利燈號誤導（暫估被當真） | 主合計中性＋白話提示；方案欄才上色 |
| R6 | 已回簽後被編輯品項／組別，致 `altPicks` 失效 | 回簽後鎖品項與組別（已裁示）；取消回簽即清選定；伺服器驗 `altPicks` 對應存在；測 17 |
| R7 | 舊單／舊資料形狀（缺鍵、`taxRate` null） | 缺鍵＝全計入；測 1、5 |
| R8 | M2 尚未上線，M3 與 M2 同改 `quotation-form.html`／`profit_guard.py` | M3 以 M2 上線基準為底；不提前動；T1 重核錨點 |
| R9 | `FORM_VERSION` 守門雜湊：任何表單改動都須升版，否則包被擋 | T6 一次升版；T6 後不再改該檔，後續只改後端 |
| R10 | `quotations.py` 6700 行，改動易衝突 | 擇一邏輯放新檔 `modules/case/alt_options.py`（`counted_items`、`plan_view`、驗證），`quotations.py` 只留呼叫點 |
| R11 | 管銷／公益金戳記（`formulaVer`、`STAMP_KEYS`）被誤改 | 只換基數；測 9、`MODULE-GUIDE` §14.5 對照 |
| R12 | 白話守門：組合檢視、暫估等文字易露代碼 | 測 23；文案走設定／常數單一處 |

## 7. 待確認（請 node-86 轉使用者／PM；每題 ≤4 選項，首項為建議）

1. ~~回簽後可否改品項~~ **已裁示（10-12）：鎖定，需先取消回簽。**
2. ~~取消回簽時已選定保留或清除~~ **已裁示（10-12）：清除。**
3. **已請款／已開票後可否取消回簽或改選？（未裁示，暫定鎖定）** ①擋下，需先沖銷（建議、目前實作假設） ②允許，必填原因並通知財務 ③允許且不通知。
4. **刪除 `altPick` 品項層布林、以 `altPicks` 為唯一來源**（對設計 §9.2 的修正，純內部；**須待使用者同意**——不是 PM／node-86 單方可核准；T1 契約凍結前須取得使用者答覆，未同意則照設計保留 `altPick` 並加一致性測試）。
5. **組合檢視是否為本班必做？** ①做（建議，已裁示） ②先只做單項方案表，組合檢視下班（省約 0.5 pd）。
6. **只對「購料報價」開放，還是所有報價類型？** 已裁示同一種報價單；確認 `alt_enabled` 預設開是否可接受。（若維持裁示則本題不問。）
7. 管理者可調的是範本文字；**擇一品項在客戶版上的標記樣式**（「擇一」文字／組別符號）是否也要開放選項？建議本班固定一種、下班再框架化（需使用者知悉，因與「不寫死」原則有張力）。

8. **回簽後鎖定範圍：備註、附件可否編輯？**（見 T9）①可編輯，伺服器明文列舉可改欄位（建議、目前假設） ②全鎖，需先取消回簽。須使用者答覆；0d 複審一併核。
9. **取消回簽時，單據已成案（轉案件）或已產生 PO 的處理？**（測 18e）①擋下，需先處理下游（建議，與 Q3 同向；理由：`recognition.py:119` 與 `caseRecord.payment.items` 皆由報價金額衍生，允許取消回簽會使認列／案件付款項與報價頁數字分叉） ②允許並標記下游待更新 ③允許且不處理。

10. **已成案報價的 unlock-edit（superadmin 解鎖編輯）目前可改哪些範圍、哪些流程依賴它？（作者／使用者答覆）** 本設計僅要求「已回簽的擇一單」例外鎖定、其餘不變；若已成案解鎖修改本就用於改品項金額，需決定回簽擇一單走「先取消回簽（受 Q3／Q9 守門）」是否可接受。
11. **已回簽單被 `update_status` 移到 草稿／已取消／已拒絕（含 `reject_quotation` 退回）時：①拒絕（預設，最保守） ②視同取消回簽：同交易清除回簽與選定並寫稽核，且守 409 下游守門（偏好）。** 須使用者／作者擇一。

## 8. 不在本班範圍
勞報單選關聯派發下拉（05）；報價單欄位標籤可由管理者在系統內改（F7，後續）；`quotation` output_template 化（M4，承接 T8 的字面實作）；組合以外的優化（最佳方案推薦等）。
