# 稽核：第 38 班（t38；合回前）（rev-7f 稽核，2026-10-04）

> 對象：`origin/train/t38` `74c49323`（基底 `3b107abf`；26 檔；case 1.0.133、analytics 1.0.30、payroll 1.1.22）。作者：hichan-04（case BE）、hichan-f9（analytics）、hichan-05（settlement.html）。稽核者沒寫過受稽核程式碼。
> 環境：自己的樹 `D:\開發測試檔\aud-7h`、`.venv312`、`-n 0`、basetemp 在 `%TEMP%`。建包視窗在跑全量，測試守門擋了我的 pytest，**我沒有關守門**，改排背景工作等鎖放掉才跑（只跑目標檔，共約 3 分鐘）。未碰正式機、未建包。探針另存 `AUDIT-T38-probe.py.txt`。

## 0. 結論
**本班引入的必修 0；建議 4；觀察 6；另有 1 項「既有的高風險」H-1（非本班回歸，但直接回答你問的「還有沒有路徑能偽造精算」——有）。**
- 本班要守的東西都守住了：完結覆蓋、樂觀鎖、整包存檔不蓋精算、負數／零和採購、報表淨利判斷；6 個突變全被既有題抓到並精確還原。
- **H-1**：`POST /api/quotations`（新建報價單）直接採用用戶端帶來的 `dealTag` 與 `settlement`，探針建出一張 `deal_tag=已結案`、`settle_status=finalized`、`netProfit=99,999,999` 的報價單（201）。這條路完全不經 `PUT /settlement` 的任何檢查。建議在合回前或下一班處理（見 H-1）。

## 1. 基準與探針
| 範圍 | 結果 |
|---|---|
| 作者新題（case BE 14、analytics 15） | 29 passed |
| 稽核探針 a–f（6 題） | 6 passed（內含印出事實的探針，見下） |

| # | 探針 | 結果 |
|---|---|---|
| a | 完結時偽造 summary 中**不在重算清單**的鍵（`origNetProfit`、`profitDiff`、`origTotalCost`、`quotedTotal`） | **都被原樣凍結**（777777／555555／1／9）。重算清單內的鍵（總成本、毛利、淨利、管理費…）被伺服器值覆蓋 ⇒ S-1 |
| b | `itemActualTotal` 偽造 +2（容差內） | 200，凍結值 11027 對重算 11025；容差本來就是設計，但淨利以伺服器值覆蓋，兩者不再自洽 ⇒ N-1 |
| c | 編輯歷程：預先塞 70 筆草稿＋再存 3 次 | 保留 50 筆、無重複 rev、尾端 67–71（同一人連存合併成一筆）。**兩人輪流存**時 `rev=len+1` 在刪舊紀錄後會撞到既有編號——**推論，未實跑** ⇒ N-2 |
| d | `POST /api/quotations` 帶偽造完結精算 | **201，存成已結案／finalized／netProfit 99,999,999** ⇒ H-1 |
| e | 守恆格網含負數：adopt × 派發去向 × 負數額外支出（−300）去向 × 正數（700）去向 × 兩種 `unadopted` 模式（144 組合） | 全過；每筆錢只算一次 |
| f | 樂觀鎖語意：帶最新版 ⇒ 200；同一舊版再存 ⇒ 409；`expectedUpdatedAt=""` ⇒ 409（空字串算有帶）；不帶 ⇒ 舊行為 200；別處寫入 bump `updated_at` 後 ⇒ 409 | 符合設計；「別處寫入也會 409」見 N-3 |

## 2. 突變（既有樹無未提交修改；各突變後 `git diff --stat` 為空）
| # | 突變 | 結果 |
|---|---|---|
| M1 | `has = bool(po or mats or exs or dps)` 改回 `purchased > 0` | **紅 2**（負數退款、零和採購） |
| M2 | `fill_downstream` 改回「只補沒送的」 | **紅 1**（容差內偏差覆蓋題） |
| M3 | `rebuild_summary_if_missing` 停用 | **紅 1** |
| M4 | 樂觀鎖檢查拿掉 | **紅 1** |
| M5 | 整包存檔改回採用用戶端的精算 | **紅 1** |
| M6 | 報表 `netProfit` 判斷改回 `if settle.get("netProfit"):`（0 當缺值） | **紅 2** |

## 3. 逐項（對照 PM 清單）
1. **完結覆蓋**：`fill_downstream` 對 `_expected_downstream` 全部鍵＋`quotedPretax`＋三個派發拆分鍵一律 `put`（`settlement_actuals.py`，M2 紅）。缺 `itemActualTotal` ⇒ `rebuild_summary_if_missing` 以 `compute()` 重建並保留非計算欄位（M3 紅）。凍結舊案：`_freeze` 對缺 `dispatchAbsorbedTotal` 的舊 summary 讀 0，輸出不變（讀碼＋author 題）。**缺口：S-1。**
2. **樂觀鎖**：stale ⇒ 409、不帶 ⇒ 舊行為（f、M4）。整包存檔改為一律沿用資料庫精算（`quotations.py:1807-1815`，M5）。**其他能蓋精算本文的路徑**：`update_quotation` 已封；`PUT /settlement` 本身有鎖；**`create_quotation` 沒封（H-1）**；`withdraw`（收回草稿）讀 DB 後改 `approval`，不碰精算。編輯歷程上限只刪**無理由的草稿**紀錄，完結（帶 `netProfit／totalActualCost／dispatchBasis／frozenAt` 快照）與重新開啟（有 `reason`）永不合併或刪除（c；`quotations.py:4380-4398`）。
3. **負數／退款**：新規則 `has = bool(po or mats or exs or dps)`（M1）；前端 `hasPurchase` 逐列對應同一組清單（`settlement.html:1269-1273`：po.docs／material.orders／extra.docs／dispatch.orders），兩邊一致；e 通過。副作用：**只有一筆退款（−300）也算「有採購」，採用時品項實際成本變負數**——符合規則 A，但畫面是否要特別提示？N-4。
4. **報表**：`_settle_actual_profit_margin`（有鍵才用淨利，含 0／負數）取代 `or`（M6）；舊精算才退回毛利並加註「（舊精算為毛利）」（畫面 `actualIsGross`、Excel 案件表率欄、PDF 兩處）；金額改 `round()`。儀表板只算 `status=='finalized'`、有 `netProfit` 才用淨利、否則毛利。Excel 工作表名「毛利分析」未改（`create_sheet("毛利分析")`）。21 處字樣：抽查 `reports.py` 剩餘的「毛利」都在「真實毛利／原始（直接）毛利」與註解，與 NOTE 的 B 表一致。**注意**：N-5（字樣裁示來源）。仍有 `int()`：`reports.py:1544,1575`（Excel 利潤表的淨利合計）未改 round，淨利為整數存檔時無差別。
5. **PDF／Excel 分項加得回總成本**：`pdf_gen.dispatch_absorbed_row`（吸收>0 才輸出，否則空字串＝舊輸出逐位元不變）；`reports.py` Excel「額外支出」欄＋未併入承攬（`dispatchTotal − dispatchAbsorbedTotal`）、PDF 另列一行；`bonus_pdf` 只在吸收>0 時多一行，`SETTLEMENT_ROWS` 11 列與標籤一字未動（`payroll/bonus.py` 不在 diff）。作者另有題驗證加總。**殘留**：36／37 班已完結且有吸收的案件，summary 只有頁面寫的 `dispatchAbsorbed`、沒有 `dispatchAbsorbedTotal` ⇒ 這些案件的 PDF／Excel 仍不加總（S-2）。
6. **前端**：失敗不再偷改頁面狀態（完結／重新開啟成功才套用）；409 ⇒ 橫幅＋停用存檔／完結；403／404／5xx 用固定中文訊息，只有 400／409／422 顯示後端 `detail`；未見使用者文字進 `x-html`（仍只有三張圖表，輸入同上一輪）；`orphanItems` 只經 `x-text` 顯示、不進 `calcSummary`；a11y 只加屬性與 `x-text` 描述。**建議 S-3、S-4**。
7. **跨模組讀者**：`dispatchAbsorbedTotal` 新鍵只被 `pdf_gen`、`bonus_pdf`、`reports` 讀；獎金仍只讀 `netProfit` 已存值；字串變更（報表標籤）只被 `reports.html／reports.js／reports.py` 使用，未見他處比對。

## 4. 發現
**H-1（既有、高）｜新建報價單可直接帶入已完結精算。** `api/quotations.py:1490` `quote_hot_fields(q)` 與 `:1544` 寫入用戶端 `data`，沒有清掉 `settlement`／`dealTag`（對照 `update_quotation` 已強制沿用 DB 值）。探針 d：201，`deal_tag='已結案'`、`settle_status='finalized'`、`netProfit=99999999`。營運報表（讀 `deal_tag`＋`settlement.summary`）與獎金基數（讀 `summary.netProfit`、`status==finalized`）會直接吃這個值，且不經完結比對、不留編輯歷程。需有建立報價單權限。提案：`create_quotation` 一律 `q.pop("settlement", None)`、`q["dealTag"]=""`（新單沒有資格有成案標記與精算）；補題。S。**不是本班引入，但本班「偽造 summary 不可存活」的主張在這條路上不成立。**

**S-1（建議）｜完結時非重算清單的欄位仍可偽造後凍結**（探針 a）：`origNetProfit`、`profitDiff`、`origTotalCost`、`quotedTotal` 等「原始側」欄位原樣存入；報表 Excel／PDF 的「原始」欄與「差異」讀它們（`reports.py:1536-1540`、儀表板 `profitDiff`）。不影響淨利與獎金基數。提案：`fill_downstream` 也覆蓋這四個（原始側可由報價單 `tot` 重算：`origNetProfit`＝`tot.netProfit`、`origTotalCost`＝Σqty×cost、`quotedTotal`＝`tot.total`、`profitDiff`＝淨利−原始淨利）。S。

**S-2（建議）｜已完結且有吸收的 36／37 班案件，分項仍不加總。** summary 只有 `dispatchAbsorbed`（頁面鍵），報表／PDF／獎金讀的是 `dispatchAbsorbedTotal`。提案：讀取端 fallback `dispatchAbsorbedTotal ?? dispatchAbsorbed`（只讀，不改寫已凍結資料）。先用唯讀查詢確認正式機有幾件（`json_extract(data_json,'$.settlement.summary.dispatchAbsorbed') > 0`）。S。

**S-3（建議）｜任何 409 都進「請重新載入」橫幅並停用存檔／完結，而 `location.reload()` 會丟掉未存的手改。** 完結前重算差異（`check_finalize` 的 409，例如承攬商單剛好被改）與樂觀鎖衝突共用同一條處理（`settlement.html:1854-1858`、`:340`）。使用者按「重新載入最新內容」＝頁面上的手填實際成本、備註全部消失。提案：衝突橫幅旁加「先匯出本頁手改（JSON／複製）」或在 reload 前把草稿寫入 `sessionStorage` 並於載入後提示套用；至少把「完結數字差異」與「別人改過」分兩種橫幅。S–M。

**S-4（建議）｜`finalize()` 成功後凍結的是頁面算的 `summary`，不是伺服器覆蓋後的值。** `_frozenSummary = Object.assign({}, this.summary, {dispatchBasis:'pretax'})`（`settlement.html` 完結成功分支）；伺服器已把總成本／淨利等改成重算值（容差內可能差 1–3 元）。畫面到下次載入前顯示的淨利與資料庫不同。提案：成功後以回應重新載入（或回應帶回 summary）。S。

**N-1（觀察）**：`itemActualTotal` 容差內偏差保留（探針 b），淨利卻以伺服器值覆蓋，存檔內兩者可差幾元；若要完全自洽，`fill_downstream` 可一併覆蓋 `itemActualTotal`／`itemPoUnadopted`／`extraTotal`。
**N-2（觀察）**：草稿紀錄刪除發生在 `settle_rev=len(history)+1` 之後，兩人輪流存草稿超過 50 筆時，新 `rev` 可能與既有編號相同；稽核日誌 `{"rev": …}` 與歷程的對應會有歧義（推論，未實跑）。提案：`rev = max(既有 rev)+1`。
**N-3（觀察）**：樂觀鎖比的是整張報價單的 `updated_at`，案件頁其他分頁、階段、叫料等任何寫入都會讓精算存檔 409（訊息已寫「或這張報價單」）。屬設計，但完結前剛好有人在案件頁動了階段會被擋一次。
**N-4（觀察）**：只有一筆負數（退款）且無原採購時，採用後品項實際成本為負；規則一致、畫面無特別提示。
**N-5（觀察）**：`docs/platform/plans/NOTE-REPORT-LABELS-T38.md` 寫「待使用者裁示，尚未改」，但 CHANGELOG 寫「（使用者裁示）」已改 21 處；`USER-DECISIONS.md` 沒有對應列。請主持確認裁示出處並補登記（使用者原話與詮釋分開標）。
**N-6（觀察）**：儀表板查詢由 `$.settlement.summary` 改為整個 `$.settlement`（含 `items` 陣列），對全部報價單逐列取出，熱路徑資料量變大（見上一份審查 F-06）。

## 5. 清理
`%TEMP%\motrix-pytest-aud7h`、背景腳本輸出已刪；樹內僅本報告與探針檔。建包窗口的鎖檔未動。
