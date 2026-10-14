# T64 財務框架缺口（T62／T63 之後）：設計筆記

> 日期：2026-10-14　作者：hichan-84 轉派（本窗口）　基底 `origin/wip/t62-int-c1`（7ae47bbfd）　分支 `wip/t64-finance-note-r1`　**只有文件**：只讀碼，沒有跑任何測試／伺服器／node。
> 前置：`FINANCE-FRAMEWORK-INVENTORY-T62.md`（F1～F5）、T62 `tax401-round-r1`／`finance-r2..r8`、T63 `export-cols-r1`（案件批次匯出＋出納執行紀錄的工作表選擇）、`pay-stage-src-r1`。
> 不變的鐵則：**金額、稅額（5%）、進位（`round_half_up`）、單號（MQ-YYYYMM-NNN、傳票號）、傳票狀態機、試算平衡、簽核層（最後一層＝最高管理者、不可自簽）一律固定（LAW）**，本筆記的每一項都只動「顯示、文字、提醒嚴重度、預設值」。

## 0. 一覽：定義驅動 vs 固定（LAW）

| # | 項目 | 結論 | 可由管理者調的 | 固定不動的 | 放寬判定 | 優先 |
|---|---|---|---|---|---|---|
| 1 | `voucher_template`（13 個佔位符，**目前未接線**）→ 傳票摘要範本 | **定義驅動（文字）** | 摘要範本文字（只能用封閉清單內的佔位符）；套用於手動傳票的行摘要 | 佔位符清單（只增不刪）、金額/科目/借貸、自動傳票的內容雜湊、凍結規則（產生當下凍結，之後不重算） | 中性（只影響新開傳票的文字）；**不得移除所有可追溯佔位符** | 中 |
| 1b | 傳票 PDF 的頁尾／浮水印字 | 定義驅動（decor-only，沿用 BP-3） | 頁尾／浮水印（預設清單挑） | 未核准橫幅（程式決定，`voucher_pdf.py:179`）、版面、金額 | 任何客戶可見文字＝放寬（G-A 既有規則） | 低 |
| 2 | 期末檢查嚴重度（blocker／warning） | **部分定義驅動** | 「未過帳傳票」「更早期間未結」兩項：warning ↔ blocker（**只收緊**為預設方向） | **試算表借貸不平衡＝blocker，永遠**（LAW）；檢查內容與計算 | blocker→warning＝放寬（第二位核准＋確認期間）；warning→blocker 即時 | 中 |
| 3 | 報表預設口徑（現金／權責） | **可做成治理設定，但建議不做** | 預設口徑 | `DEFAULT_BASIS="cash"` 是 2026-09-30 使用者裁示；口徑的計算本身；`?basis=` 參數 | 任何改動走第二位核准（`loosen="both"`） | 低（建議維持常數） |
| 4 | F5 報表欄位顯示 | **延後**（見 §4.4） | — | — | — | 不排 |
| 5 | `tax401.py` 銀行家捨入疑點 | **已由 T62 修掉那一處；另發現 5 處同類（報表層）** | —（LAW：進位口徑固定 half-up） | 全部金額進位 | 不適用（不是設定） | 高（小） |
| 6 | 出納匯出欄位層級 | **定義驅動（欄位），需先重構** | 欄位顯示／順序／標題 | 合計列、數字格式、稽核、金額遮蔽 | 加回含金額欄＝放寬（沿用 BP-3） | 低 |

## 1. 逐項設計

### 1. 傳票摘要範本（`voucher_template.py`）
**現況（已讀）**：`modules/accounting/voucher_template.py` 有 13 個封閉佔位符 `SUMMARY_PLACEHOLDERS`（發票號、發票日期、單號、客戶名稱、廠商名稱、未稅、稅額、含稅、本行金額、單據日期、上傳檔案日期、案件編號、專案名稱）、取值來源表 `PLACEHOLDER_RESOLVERS`、驗證與 `render_summary(body, context) → (文字, 缺值清單)`（缺值不靜默補空字串）。資料表 `voucher_templates`／`voucher_template_versions` 與 `voucher_lines.summary_template_id/_version`（追溯欄，db.py:5614）**都已建好**，`archive.py` 也會匯出；但**沒有任何 API／畫面存取範本，也沒有任何寫入端呼叫 `render_summary`**（全庫只有模組自己與測試引用）。今天的摘要來源是：手動傳票由畫面挑來源列組字串（`voucher.js` 的 `panelPick`／`voucher_summary.case_summary`）、自動傳票由 `ledger/engine.py:85,90` 取事件的 `memo`／`doc_no`（硬截 60 字）、T100 匯出另有兩處 f-string（`accounting_export.py:318,349`，`[:60]`）。

**做法（定義驅動，沿用施工圖「單一版本、儲存時驗證、產生當下凍結」）**
1. 後端：範本 CRUD（列出／讀／新增／發布新版本，superadmin 或會計管理權限）走**既有兩張表**（保留追溯欄與 archive 匯出），驗證沿用 `voucher_template.validate`（儲存時就擋未知佔位符，指出是哪一個）。佔位符清單**只增不刪**（刪＝已存範本變非法）。
2. 「可追溯」守門（新）：發布的範本至少含 `{單號}`／`{發票號}`／`{案件編號}` 其中之一，否則拒絕（摘要是會計憑證文字，全部拿掉＝稽核追不到）。
3. 手動傳票：行摘要旁多「套用範本」按鈕（旗標預設關）；套用＝呼叫 `render_summary` 用該行的來源 context，**缺值不寫入、列在提示裡**；寫入的是**凍結文字**＋`summary_template_id/version`；之後範本改了，已開傳票不變。
4. 自動傳票（第二步，可選）：`engine.py` 組行摘要時，若有範本則用事件 context 的**子集**（單號、客戶／廠商、案件、金額）；缺值 ⇒ 退回今天的 memo（不留 `{…}` 殘渣）；仍截 60 字。
5. 不做：T100 匯出的 f-string 摘要（格式由會計軟體匯入決定，另案）。

**固定／風險**：金額、科目、借貸、稅碼不經範本。自動傳票的 `canonical_hash`（`contract.py:108`）**不含 memo／說明文字**（註解逐字：「`meta` 與說明文字不參與」），所以範本改 memo **不會觸發 drift 反向傳票**——但要有測試鎖住這點（改範本前後同一事件雜湊相同）。60 字截斷在範本展開之後做。

### 1b. 傳票 PDF 頁尾／浮水印
沿用 BP-3 R4（`invoice_vouchers.py` 已做 `arap:invoice-voucher-pdf`）：登記 `accounting:voucher-pdf`（`caps=("footer","watermark")`、`columns=[]`），`voucher_pdf.export_voucher_pdf`／`preview_html` 外包 `decorate_pdf`。未核准橫幅（`voucher_pdf.py:179` 的 `unapproved_banner`）與程式決定的核可狀態**不可被版型移除**（同 `test_unapproved_pdf_banner`）。這不是摘要範本；放獨立切片。

### 2. 期末檢查嚴重度
**現況（已讀）**：`ledger/periods.py::checklist` 回 `{"blockers":[試算表借貸不平衡], "warnings":[未過帳傳票, 更早期間未結帳], "counts"}`；`close_period`：有 blocker 一律擋；有 warning 需 `accept_warnings` 與理由。**試算平衡是 LAW（blocker 永遠）**。
**做法**：設定群組 `ledger_close_checks`（敏感、risk=money）兩欄 `unposted_vouchers`、`earlier_open_periods`，整數代碼 1＝提醒（預設＝今天）、2＝擋結帳；`loosen="down"`（2→1＝放寬，需第二位最高管理者核准＋確認期間；1→2 即時）。同 `case_close_gates` 的「只收緊」精神，**讀不到設定 ⇒ 全部 2（往嚴）**（用 `settings_strict`，不經會讓失敗回預設的 `SR.get`）。`checklist` 依設定把該項放進 blockers 或 warnings；訊息文字不變。**不新增檢查項**（避免「新 blocker 讓既有流程突然不能結帳」；新增項目另案、預設 warning）。
**耦合**：`close_period`、`ledger_closing`（年度結轉也呼叫 checklist？以程式為準）、`ledger_periods` 的 API 與期間頁（顯示 blockers／warnings 的畫面）、`tb_hash` 留證、`reopen/stale` 流程（不動）。

### 3. 報表預設口徑
**現況（已讀）**：`helpers/recognition_basis.py`：`DEFAULT_BASIS = "cash"`（2026-09-30 使用者裁示：現金口徑＝依收付款日、含稅；權責保留在切換）；`reports.py`（多個端點的 `basis: str = DEFAULT_BASIS` **在 import 時就綁定成預設參數**；Excel/HTML/PDF 的 `data.get("basis", DEFAULT_BASIS)`）、`ledger_diff.py:148`、月報郵件都用它；`dashboard.py` 的利潤口徑固定權責（另一回事）。
**判斷**：可以做成治理設定，但這是**使用者已裁示的值**，改它改變所有人看到的頭條數字；而且技術上要把「預設參數在 import 時綁定」改成「呼叫時解析」，涉及十餘處端點簽章（路由基準檔會連動）。收益低。**建議維持常數**，除非使用者要求；若要做：設定 `reports.default_basis`（cash／accrual 整數代碼）、`loosen="both"`（任何變更都要第二位核准）、讀不到 ⇒ `cash`、`?basis=` 參數永遠優先、月報郵件用同一解析。

### 4. F5 報表欄位顯示 — 延後
營運報表的各表格是異質的（含合計列、跨表引用、PDF 版面依欄位位置）。T62 已有「工作表層級」選擇（`reports:financial`）。欄位層級會遇到和出納匯出相同的「合計/格式綁位置」問題（見 §6）。**不排**；若使用者指名某個欄位要隱藏，個案處理。

### 5. `tax401.py` 銀行家捨入疑點 — 驗證結果
- **T62 `wip/t62-tax401-round-r1`（a8591141d）改了什麼**：`tax401.py` 的「與應收應付發票逐項對比」檢查，發票未稅／稅額合計由內建 `round()`（銀行家捨入）改為逐張 `round_half_up`（`_invoice_sum`），與總帳 `arap/gl_events._i` 同口徑；`tests/platform/test_legal_amount_rounding_guard.py` 的 `MONEY_PY_FILES` 加入 `modules/accounting/ledger/tax401.py`。影響：只有**對帳檢查的比較值**（誤紅），不動傳票金額、稅率、`tax_split`。
- **還剩什麼（本次讀碼發現，未驗證數值影響）**：不在守門清單內的 `round()` 金額站點——`analytics/api/reports.py:344`（`int(round(…))` 保留款）、`:374`（結算利潤 `round(float(profit))`）、`:3833`（其他支出明細 `"amount": round(amount)`）、`analytics/api/ledger_diff.py:57`、`:106`（`round(sum(…))`：報表 vs 總帳對照，半偶數捨入會在剛好 .5 時多出 1 元的「殘差」）。其餘 `round(…, 1)` 是百分比顯示，不是金額。
- **結論**：疑點在 tax401 已關閉；報表層 5 處屬同類缺陷，建議一個**小 PR**改成 `round_half_up`，並把 `reports.py`、`ledger_diff.py` 加入 `MONEY_PY_FILES`（百分比行以註解標「非金額」，依守門既有慣例）。這是 LAW（進位口徑固定），不是設定。**唯一行為改變**：金額剛好 .5 的情況下報表數字多 1 元（與總帳對齊）。

### 6. 出納匯出欄位層級（接 T63 工作表層級之後）
**現況**：T63 `export-cols-r1` 把 `arap:cashier-history` 登記為「工作表型」（4 張：已匯款明細〔必選〕、支出申請付款明細、已收款明細、獎金發放明細），**刻意不做欄位型**：三張表有合計列、數字格式、欄寬都綁欄位位置；且 `register_export` 的規則是「`sheets` 與 `columns` 二選一」。
**做法（需先重構才能做）**：①把每張表改成欄位規格 `[{id,label,width,numfmt,money}]`＋以 id 計算合計（OFF 輸出逐格黃金對照）；②framework 擴充 `sheets[].columns`（工作表內可挑欄位；加回含金額欄＝放寬，沿用既有規則），或把四張各登記成獨立欄位型匯出（較省框架改動，但失去『同一活頁簿』的工作表選擇）；③PDF 姊妹跟著走（`add_pdf_sibling`）。**耦合**：`export_logged` 稽核、`check_export_rate`、`_require_view_access`／`bonusVisible`、`cashier.js` 匯出按鈕。價值取決於是否有人要改欄位——見問題 Q6。

## 2. 耦合清單（改任何一項前先看）
| 對象 | 與本筆記的關係 |
|---|---|
| **GL 事件 E01（開票）／E03（收款）**（`arap/gl_events.py`、`ledger/contract.py`、`engine.py`） | 摘要範本（§1.4）只改事件行的 memo；`canonical_hash` 不含 memo ⇒ 不觸發 drift／反向傳票；engine 截 60 字。期末檢查（§2）不改事件。進位（§5）：`gl_events._i` 已是 half-up，是報表要對齊的基準 |
| **T100 匯出**（`accounting_export.py`；現金基礎用 `receivedAt`） | 摘要有自己的 f-string（`:318,349`，`[:60]`）——本筆記**不動**；進位已 half-up（`:88`）。傳票行摘要流進 T100 的路徑要確認（凍結文字會被帶出） |
| **稅務匯出／401**（`tax401.py`、`tax401_media.py`） | §5 只動比較值；稅率 5%、欄位對照、`taxExempt/writeOffStatus` 不動 |
| **應收**（`arap/receivables.py`、`cashier.py::_receivable_queue`） | 不動；`round_half_up_invoice` 已是 half-up |
| **傳票 PDF／預覽**（`voucher_pdf.py`） | §1b decor-only；摘要凍結文字原樣印；未核准橫幅固定 |
| **期間／結帳**（`periods.py`、`closing.py`、`ledger_periods.py` 與期間頁） | §2；`tb_hash`、重開 `stale` 流程不動 |
| **報表**（`reports.py`、`ledger_diff.py`、月報郵件） | §3（建議不做）、§5（改 5 處進位） |
| **出納匯出**（`cashier.py::export_execution_history`） | §6 |
| 路由基準檔 | §1 會新增範本 API（`route_inventory`／`route_table_golden`／`response_keys_baseline` 與 `regen_all` 由整合者重錄）；§2、§5 不新增路由 |

## 3. 治理分類
| 變更 | 分類 | 說明 |
|---|---|---|
| 發布／修改摘要範本 | 中性 | 只影響之後新開傳票的文字；要保留可追溯佔位符（守門，非核准） |
| 傳票 PDF 頁尾／浮水印 | 放寬（客戶可見文字） | 沿用 G-A：第二位核准 |
| 期末檢查 warning→blocker | 收緊（即時） | |
| 期末檢查 blocker→warning | **放寬**（第二位核准＋確認期間） | 試算不平衡不在可調範圍 |
| 預設口徑（若做） | 放寬（兩個方向都走核准） | 因為是使用者裁示值 |
| 出納匯出加回含金額欄 | 放寬 | 沿用 BP-3 |
| 進位站點修正 | 不是設定（LAW 修正） | 需使用者知情（Q4） |

## 4. 測試計畫（每切片；T62 閘門結束後才跑）
- 摘要範本：`validate` 現有題不退步；新增 ①發布含未知佔位符被拒（指名）；②無可追溯佔位符被拒；③`render_summary` 缺值回報、不寫入；④凍結：改範本後舊傳票行不變、`summary_template_id/version` 寫入；⑤**自動傳票 memo 範本不改 `canonical_hash`**（正對照：改金額會改）；⑥60 字截斷；⑦OFF（旗標關）輸出逐位元等同今天；⑧權限（誰能發布）。
- 期末檢查：預設（兩項 warning）行為與今天逐位元相同；設 blocker 後 `close_period` 被擋、訊息同；**試算不平衡永遠 blocker（突變控制：把它改成可調要失敗）**；讀不到設定 ⇒ 全 blocker；放寬走 pending（`SR.publish` 結果 `pending`，參考 T63 dk1 測試的清理寫法）。
- 進位：守門 `MONEY_PY_FILES` 加入新檔後全綠；`round(738.5)` 風格的邊界格（.5 偶/奇）報表值＝`round_half_up`；`ledger_diff` 殘差在 .5 格為 0。
- 出納欄位型：OFF 逐格黃金對照；合計列以 id 計算與位置版相同；無金額權限整欄省略。
- 全部：新路由基準重錄；`test_money_flows_registered` 不受影響（沒有新金流）。

## 5. 小 PR 切片與順序
1. **S1 進位站點修正**（§5）：5 處＋守門清單；最小、最確定、獨立；**先問 Q4**。
2. **S2 期末檢查嚴重度**（§2）：設定群組＋`checklist` 讀取＋期間頁文字；獨立。
3. **S3 傳票 PDF decor**（§1b）：複製 R4 模式；獨立。
4. **S4a 摘要範本後端**（§1.1–1.2：CRUD＋驗證＋可追溯守門＋測試，旗標預設關）→ **S4b 手動傳票「套用範本」按鈕**（§1.3）→ **S4c 自動傳票 memo 範本**（§1.4，最後；含雜湊不變測試）。
5. S5 預設口徑設定（§3，建議不做）；S6 出納欄位層級（§6，需 Q6 為是）。F5 不排。
順序理由：S1 是缺陷修正且與其他無關；S2、S3 小且互不相依；S4 最大且價值取決於會計是否要範本（Q1），放後面分三段，每段可單獨上線（旗標預設關）。

## 6. 需要使用者回答的問題（每題附建議預設）
- **Q1 傳票摘要範本要不要接線？**（今天沒有任何畫面能管理範本；13 個佔位符與資料表是預先蓋好的。）建議：**要，先做手動傳票的「套用範本」**（S4a＋S4b），自動傳票 memo（S4c）等會計用過再決定。
- **Q2 範本存哪裡？** 建議：沿用既有 `voucher_templates` 兩張表（已有版本與追溯欄），不改存到定義庫。
- **Q3 期末檢查：哪些提醒允許管理者升級成「擋結帳」？** 建議：「未過帳傳票」與「更早期間未結帳」兩項，預設維持提醒；試算不平衡永遠擋。
- **Q4 報表層 5 處進位改 half-up（剛好 .5 的金額報表多 1 元，與總帳對齊）？** 建議：**要**（S1）。
- **Q5 預設口徑要做成設定嗎？** 建議：**不要**（維持 2026-09-30 裁示的現金口徑常數）。
- **Q6 出納匯出需要「欄位」層級嗎（目前可選工作表）？** 建議：**先不要**；等有人指名要改某個欄位再做（需先重構合計列）。
- **Q7 傳票 PDF 要不要能加頁尾／浮水印字？** 建議：**要**（S3；與開票憑據、請款單一致，未核准橫幅仍由程式決定）。
