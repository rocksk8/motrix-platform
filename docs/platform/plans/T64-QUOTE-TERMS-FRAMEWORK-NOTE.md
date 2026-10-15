# T64 切片「報價條件框架」設計筆記（僅文件；不含程式）

> 日期：2026-10-14　作者：hichan-84 轄下非作者視窗（靜態閱讀，未跑任何測試／伺服器）　基底：`origin/wip/t62-int-c1`（讀取時 57cbd5674，建分支時 7ae47bbfd；本文引用的檔案在兩者之間沒有差異，除 `settings_groups.py`、`quotation-form.html` 的小改動與本文無關）。
> 來源：耦合表切片 3（`QUOTE-CASE-LAYOUT-COUPLING-T62.md` §4 Q1/§3.2「報價條件」列）＋ hichan-6c 對帳「Genuinely NOT in T62 #1」（該句在 repo 內搜不到原文，以 PM 轉述為準）。
> 前提：T62 已出貨的「簽核原因門檻」（`quote_approval.*`，D-K1：放寬須第二位最高管理者）**不在本切片範圍，只被引用、不得改變**。

## 0. 結論先講

1. 這一刀要框架化的是三件事：**(a) 條款欄位清單與標籤**、**(b) 條款組（`quote_terms_presets`）編輯器納入治理**、**(c) 擇一單送審的 `approval_basis`**。
2. 欄位**資料鍵固定為現有五個**（`paymentTerms/deliveryTerms/acceptanceTerms/warrantyTerms/afterSales`）；定義只決定「怎麼呈現與怎麼比對」，不新增資料鍵（新增鍵＝動 pydantic 模型、PDF、遮蔽、版本差異，成本與風險都高，列為使用者問題 Q4，建議不做）。
3. **`approval_basis = 2` 以現行字面定義（「只看計入金額的品項」）上線會讓所有擇一組在送審時完全不被審核**（送審時尚未回簽 ⇒ 沒有任何選定 ⇒ 整組不計入），而客戶回簽選定之後不會重新送審。建議本刀**不開放**，維持現在的夾回（`UNAVAILABLE_ALT_CHOICES`），除非使用者另外裁示並同時做「選定時重審」（Q1）。
4. 第一個 PR 只做「判準核心抽出＋黃金向量」，**零行為變更**；它同時修掉目前就存在的一個前後端標籤落差（§1.4 G1）。

## 1. 現況（以 c1 為準，附位置）

### 1.1 判準與預設
- `modules/case/quote_terms.py`：`DEFAULT_TERMS`（5 欄預設，唯一來源）、`TERMS_FIELD_DEFS`（鍵＋顯示名）、`compute_approval_reasons()`（逐條移植前端 `checkApproval()`）、`submit_reasons()`（加「代理送出」行與「標準報價單送出」）。
- 原因的組成與順序（固定）：有效期限 → 各品項毛利率（含區段標題在內的陣列位置 N）→ 含折讓 → 稅別／稅額（`taxRate < 5`；零稅率／免稅用法定稅別字樣，舊 1～4% 用「調整營業稅額」字樣）→ 報價條件已修改（與條款組不同／非預設內容，列出欄位標題）。
- 三個數值門檻（毛利 30%、有效天數 30、折讓 0）已是設定中心 `quote_approval.*`（`risk=money, loosen`），後端用 `settings_strict.strict_value` 讀，**讀不到＝最嚴**（100%／1 天／0 元）。前端經 `GET /api/project-margin/config` 拿同一組數字（`pmCfg`）。
- 送審時後端重算並覆蓋用戶端的 `approval.reasons`（`quotations.py::_apply_server_submit_reasons`，先 `_CT.freeze(q)` 再算原因）；代理送出那一行的**送出人名字用伺服器登入身分**。

### 1.2 條款組
- 儲存：`system_settings.quote_terms_presets = {presets:[{key,name,五欄…}], defaultKey}`（`routers/system.py` ~2339–2460）。讀：登入即可；寫：`require_superadmin`、整組覆寫、上限 30 組／名稱 30 字／每欄 5000 字、**立即生效、只有一行稽核（組數與預設名）**，沒有版本帳本、沒有預覽雜湊、沒有第二位核准。
- 報價單存的是**文字複本**，`termsPresetKey` 只是「從哪一組起手」的線索；比對基準＝選中的組，沒選＝`DEFAULT_TERMS`（付款條件用 `/api/settings/payment-terms` 的目前預設）。刪組後前端把 `termsPresetKey` 清空。
- 預設條款端點 `GET /api/settings/quote-terms-defaults`（登入即可），S-Q2 開啟時多帶 `titles`。

### 1.3 標題與 PDF §五
- S-Q2（`helpers/clause_titles.py`，匯出範本 `case:quotation-clause-titles`）：五個標題各自只能從 3 個預設候選挑；**送審時凍結**到 `data_json.clauseTitles`（離開草稿／解鎖重簽再凍結；回草稿清掉）；PDF（`pdf_gen.py` ~382–396）、表單 `ct(key)`、後端原因文字都用「凍結 > 目前範本 > 預設」。任何標題變更＝放寬（走治理）。
- PDF §五 `五、報價條件`：`term_block` 依序印 付款、交貨、保固、售後（擇一單自動說明句接在售後後面）、驗收（整列）；空白欄不印；**隱藏表單欄位不影響 PDF**（耦合表 §3.2 與 §6 決定 1 已建議接受並明講）。另有請款單／其他 PDF 把「付款條件」標題寫死（`pdf_gen.py` ~2247），不跟 S-Q2。

### 1.4 已知落差與風險（本文新發現／確認）
| # | 項目 | 說明 |
|---|---|---|
| G1 | **前後端標籤落差（現存）** | 前端 `checkApproval()` 的欄位標題用靜態 `termsFieldDefs[].label`（`quotation-form.html` ~2493、~2892），後端原因文字用 `_CT.title()`（凍結／範本）。S-Q2 開啟且選了非預設標題時，畫面上的預覽原因與送審後的原因文字不同；現有 parity 題（`test_e2e_quote_reasons_parity_2026_09_24.py`）只測預設標題。修法：前端改用 `ct(key)`（PR-A）。 |
| G2 | **條款組編輯無治理** | 改條款組文字會改變「報價條件已修改」的比對基準：把組內文字改成較寬鬆的版本之後，用這組的報價單不再被標示。這是一條放寬路徑，今天只靠「僅最高管理者＋單人立即生效」。 |
| G3 | **原因遮蔽靠中文子字串** | `financial_mask.py:28` `_REASON_MONEY_MARKS=("毛利","NT$","折讓")`：原因文字含這三個詞之一就整句換成「（涉及金額，無財務檢視權限）」。任何新原因文字／可自訂的標籤，若帶金額又不含這三詞＝洩漏；若標籤（或條款組名稱）剛好含這三詞＝被無謂遮蔽。 |
| G4 | **遮蔽覆蓋面待查** | `mask_quotation_data` 會遮 `approval.reasons`；但簽核佇列清單（`quotations.py` ~5117）與儀表板待審清單（`dashboard.py` ~117）直接回 `approval.reasons` 與 `total`。是否被可見範圍擋住（只列給簽核人／財務檢視者）需另外實證（見 §8）。 |
| G5 | **`approval_basis=2` 的語意陷阱** | 見 §3.3。 |

## 2. 什麼變成「定義驅動」、什麼維持固定

### 2.1 變成定義驅動（新 kind，建議名 `quote_terms`，scope=company，單一份 key=`default`）
```
{ "version": 1,
  "fields": [ {"key":"paymentTerms","label":"付款條件","order":10,"inForm":true}, … ],   # 只能是上述五個鍵；不可新增、不可刪除、不可改鍵
  "presets": [ {"key":"p1","name":"純購料","values":{"paymentTerms":"…","deliveryTerms":"…", …}} ],   # 取代 system_settings.quote_terms_presets
  "defaultKey": "p1" }
```
- 標籤：**沿用 S-Q2 的「3 選 1」白名單與凍結機制**（不重做）；本定義的 `label` 欄位只是 S-Q2 結果的鏡射或乾脆不放（建議 v1 不放，避免兩處矛盾，見 Q5）。
- 順序（`order`）與表單可見（`inForm`）：只影響表單（版面引擎已提供 Q1 的 `qterms` 表單登記，建議直接沿用版面引擎，不在本定義重複）。
- 條款組（presets）：整份納入定義文件庫（版本、差異、還原、帳本、發布前預覽雜湊）。
- 讀取端點仍是 `GET /api/settings/quote-terms-presets`（回應形狀不變）；旗標開且有已發布版本時改讀定義，**舊 `PUT` 在旗標開啟時回 409「已改由定義管理」**（比照 `_managed_guard`）；旗標關＝逐位元不變。

### 2.2 維持固定（不可由管理者調整）
| 項目 | 原因 |
|---|---|
| 稅別／稅率觸發（`taxRate < 5` 及零稅率／免稅字樣） | 法定（AC1，營業稅法 §7、§8）；`validate_tax_basis` 已在寫入端把關 |
| 後端送審重算並覆蓋用戶端 `reasons`；代理送出人用伺服器身分 | 簽核人看到的原因不能由送件人決定（N13 裁示） |
| 原因的種類、順序、文字格式（含「第 N 項」＝陣列位置、`toFixed(2)`、千分位） | 前後端逐字 parity、遮蔽子字串（G3）、簽核佇列與歷史顯示都依賴它 |
| 「標準報價單送出」「代理送出」兩句 | 同上；也是簽核畫面辨識用語 |
| 五個資料鍵與其 pydantic／PDF／版本差異對照 | 見 §4 耦合 |
| 門檻數值與其放寬核准 | 已在 `quote_approval.*`（T62，D-K1），本切片不碰 |
| 讀取失敗的收斂方向（比對基準讀不到＝視為不同＝多標示） | 寧可多送審，不悄悄放寬 |

### 2.3 `approval_basis`（擇一單送審的審核基準）
現在：欄位已在 `quote_alt.approval_basis`（`risk=money, loosen=up, requires_pending`），但 `2` 被 `UNAVAILABLE_ALT_CHOICES` 夾回 1，`compute_approval_reasons` 一律逐項檢查所有品項。

## 3. 設計細節

### 3.1 比對基準與 `judge`
- 比對方式不變：`_text(q[key]) != _text(baseline[key])`（JS 語意的 trim：含 U+FEFF、不含 U+001C–U+001F；falsy→''）。
- **v1 不提供每欄「不納入判定」開關**（`judge=false`）：那等於讓管理者關掉一個送審原因（放寬）。若使用者要（Q2），規則為：關掉＝放寬（第二位核准），且 `paymentTerms` 永遠不可關。

### 3.2 條款組編輯的治理比較（`COMPARATORS["quote_terms"]`）
見 §5 表。原則：**任何會讓「更多報價單不被標示」或「對外文字改變」的變更＝放寬**；看不懂＝放寬。

### 3.3 `approval_basis = 2` 的語意
- 字面定義：只檢查 `profit_guard.counted_items(q)`（非擇一項＋每組被選定的那一項；未選整組不計入）。
- 問題：送審發生在客戶回簽**之前**，此時每個擇一組都未選 ⇒ 所有擇一品項都不被檢查；回簽選定後單據已核准，不會再送審 ⇒ 低毛利方案可以零審核成交。
- 若使用者仍要上：必須同時做 **「選定時重審」**——回簽選定的那一刻，用選定後的 `counted_items` 重算毛利／折讓原因，有原因就進入重新簽核（等同解鎖修改的簽核流）。這超出本切片大小，建議獨立成 T65。
- 在那之前：維持 `UNAVAILABLE_ALT_CHOICES`（夾回 1），文件註明原因。「第 N 項」的 N 在任何基準下都維持陣列位置。

## 4. 耦合清單（動到欄位清單／標籤／組時會碰到誰）

| # | 耦合點 | 位置 | 對策 |
|---|---|---|---|
| C1 | 五欄鍵與標籤在四處各一份：`TERMS_FIELD_DEFS`（後端）、`termsFieldDefs`（前端）、`_TERMS_FIELDS`＋`QuoteTermsPreset`（pydantic）、`CLAUSE_PRESETS`（S-Q2） | `quote_terms.py:51`、`quotation-form.html:2493`、`system.py:2354`、`clause_titles.py:17` | 固定鍵；PR-A 把前端標題改用 `ct(key)`；加一題「四份鍵集合相同」守門 |
| C2 | JS `checkApproval()` ↔ Python `compute_approval_reasons()` 逐字 parity | `quotation-form.html:2862`、`quote_terms.py:218` | PR-A 抽成純函式＋共用黃金向量（§6） |
| C3 | `termsPresetKey` ↔ presets 的 key；刪組時前端清 key、伺服器端比對時找不到 key ⇒ 退回 `DEFAULT_TERMS` | `quotation-form.html:3140`、`quote_terms.py:140` | 保留；定義的 key 穩定（建立後不可改）；刪除＝移除＝收緊 |
| C4 | 付款條件預設來自 `/api/settings/payment-terms`（`default_payment_terms` 參數），與條款組並存 | `quote_terms.py:140`、`system.py` | 不併入；比對基準讀不到時用 `DEFAULT_TERMS`（更嚴） |
| C5 | S-Q2 標題凍結：原因文字用 `_CT.title(key, q)`，且 `_CT.freeze(q)` 必須在算原因**之前** | `quotations.py:1590–1600` | 保持呼叫順序；加題鎖順序 |
| C6 | PDF §五 區塊順序與標題（含擇一自動說明句接在售後） | `pdf_gen.py:360–396` | 順序固定；隱藏表單欄位仍印 PDF（明講）；不改 PDF |
| C7 | 請款單等其他 PDF 把「付款條件」標題寫死 | `pdf_gen.py:~2247` | 不跟 S-Q2／本定義；在編輯器警語中明講「只影響報價單」 |
| C8 | 原因遮蔽子字串 `("毛利","NT$","折讓")` | `financial_mask.py:28` | 原因文字固定（不開放自訂）；條款組名稱驗證器禁用這三詞與 `NT$`（名稱會出現在原因句裡）；加「所有原因樣板×遮蔽」不變式題 |
| C9 | 原因出現在：簽核佇列清單與詳情、儀表板待審、報價單歷史版本、通知信（S-X3 樣板的 `{標記}` 等不含原因） | `quotations.py:~5117`、`dashboard.py:~117`、`approval_queue.py` | 實證可見範圍（§8 V1）；若有缺口，遮蔽改在輸出端統一一支函式 |
| C10 | 報價單版本差異／修改紀錄的欄位顯示名（`_TRACKED_QUOTE_FIELDS`） | `quotations.py:~136` | 固定鍵＝不受影響 |
| C11 | 版面引擎 Q1 的 `qterms` 表單（欄位顯示／順序／標籤，核心欄位鎖） | `QUOTE-CASE-LAYOUT-COUPLING-T62.md` §5 | 欄位可見／順序交給版面引擎，不重複 |
| C12 | `quote_approval.*` 門檻與前端 `pmCfg`（`/api/project-margin/config`） | T62 已出貨 | 不動；PR-A 的向量要含「門檻非預設」案例 |
| C13 | `quote_alt.approval_basis` ↔ `profit_guard.counted_items` ↔ `alt_policy.policy()` 夾回 | `settings_groups.py:224`、`alt_policy.py` | §3.3 |
| C14 | 解鎖重簽（`is_unlock_edit`）與條款標題凍結的重新計算 | `quotations.py:2105–2120` | 條款組變更對**已送審單據**無影響（單據存文字複本）；僅影響之後的送審比對 |

## 5. 治理分類（哪些編輯是放寬）

規則沿用 `def_pipeline` 慣例：放寬＝第二位最高管理者核准＋確認期間；收緊／中性＝直接發布（仍有版本帳本與預覽雜湊）；看不懂＝放寬。

| 編輯 | 分類 | 理由 |
|---|---|---|
| 條款組內任一欄文字改變（含新增字、刪字、換行） | **放寬** | 改變比對基準；同時是對外文字 |
| 新增條款組 | **放寬** | 新基準：用這組的單據不被標示 |
| 移除條款組 | 收緊 | 用該組起手的單據會退回與 `DEFAULT_TERMS` 比對，更容易被標示 |
| 條款組改名 | 中性 | 只影響原因句裡的組名（驗證器禁金額詞、長度 ≤30） |
| 調整預設組（`defaultKey`） | 中性 | 只決定新單預填；比對基準仍是「選中的組」 |
| 條款組排序 | 中性 | 純顯示 |
| 欄位 `inForm`／`order` 變更 | 交給版面引擎（`layout` kind 已受管） | 不在本 kind |
| 標題（S-Q2） | 放寬（已實作） | 客戶可見文字 |
| （若 Q2 選做）某欄 `judge=false` | **放寬**；`paymentTerms` 禁止 | 關掉一個送審原因 |
| `approval_basis` 1→2 | **放寬**（已是 `loosen=up, requires_pending`） | 本刀不開放（§3.3） |
| 任何未知鍵／結構 | **放寬** | fail-closed |
| 門檻（毛利／天數／折讓）、`receivable_grace_days`、`settle_overdue_days` | 已依 D-K1 實作 | 本刀不碰 |

## 6. 測試計畫

### 6.1 黃金向量（零行為變更的核心）
- 檔案：`backend/tests/vectors/quote_reasons_vectors.json`，每筆 `{id, q, presets, defaultPaymentTerms, cfg:{maxValidDays,minItemMarginPct,discountReviewAbove}, titles?, expected:[…]}`。
- 消費者三個：①Python `compute_approval_reasons`（pytest，不需瀏覽器）；②前端純函式（node 直跑；repo 已有 node 實跑題的先例，見耦合表 §5「OFF 中性（node 實跑）」）；③既有瀏覽器 parity 題（保留，抽樣 3 筆）。**向量由人手寫＋兩邊各自計算比對，不以其中一邊的輸出當標準答案**（避免假綠燈）。
- 向量類別（每類至少一筆正例、一筆邊界、一筆反例）：
  1. 有效期限：`validDays` 為 30／31／"31"／"abc"（NaN→不觸發）／空；門檻改 45。
  2. 毛利率：`cost<=0` 跳過；`margin` 剛好 0.30（不觸發）；0.2999；區段標題在第 0 項時 N 的位置；`toFixed(2)` 平手進位；門檻改 50（字樣「低於 50%」）。
  3. 折讓：`showDiscount` 假；折讓 1 且門檻 0（觸發）；折讓等於門檻（不觸發，嚴格大於）；千分位與 ≥4 位小數。
  4. 稅：`taxRate` 缺省（5）；0＋零稅率依據／免稅依據；3（舊「調整營業稅額」字樣）；4.9。
  5. 條款：無組＋預設；選組＋相同；選組＋改一欄／改兩欄（頓號串接順序＝`TERMS_FIELD_DEFS` 順序）；組被刪（key 找不到→退回預設）；前後空白與 U+FEFF（JS trim）／U+001C（不去）；預設條款未載入（前端不判定；後端有預設）——**此類為前後端刻意不同，列為「已知差異」向量，不在 parity 比對內**。
  6. 標題（S-Q2）：旗標關；開且凍結標題；開但未凍結（草稿）。**含 G1 的回歸向量**。
  7. 組合：多個原因的順序固定（期限→品項→折讓→稅→條款）。
- 不變式題（Python）：
  - 「所有原因樣板 × `_REASON_MONEY_MARKS`」：帶毛利率或金額的原因必含遮蔽詞；有效期限／稅別／條款原因**不得**含遮蔽詞（否則無財務權限者看不到）。
  - 四份鍵集合相同（C1）。
  - `_CT.freeze(q)` 先於原因計算（C5）。
  - 條款組名稱驗證：禁 `毛利`、`折讓`、`NT$`、控制／隱形字元。

### 6.2 治理與讀寫
- 比較函式：每一列 §5 表一題；未知鍵＝放寬；空→第一次發布（以「無組」為基準，只新增組＝放寬）。
- 旗標關：`GET/PUT /api/settings/quote-terms-presets` 與今天逐位元相同（回應鍵、400 訊息、稽核字串）；旗標開且有已發布版本：PUT 409、GET 回定義內容、形狀不變。
- 讀取失敗：定義庫讀不到 ⇒ 後端視為「無組」（基準退回 `DEFAULT_TERMS`，更嚴）＋記錄 ERROR；不擋送審。
- 受限角色：發布前後，非財務角色的報價單 API 回應（原因遮蔽）相同。
- 不寫入：預覽端點唯讀、不留稽核（比照其他 builder 預覽）。

### 6.3 e2e（等 gate 空檔，要瀏覽器）
- 兩個分頁：A 開報價單、B 發布新條款組；A 儲存→看到的原因與送審後後端原因文字一致（G1）。
- 簽核佇列詳情以非財務簽核人開啟：原因含毛利／折讓者被遮蔽，其餘可見（G4）。

## 7. 切片（2–3 個小 PR）

| PR | 內容 | 旗標 | 風險 | 大小 |
|---|---|---|---|---|
| **PR-A 判準核心與黃金向量** | ①前端把 `checkApproval()` 的純計算抽成 `frontend/static/quote-reasons.js`（頁面改呼叫，行為不變）；②標題改用 `ct(key)`（修 G1）；③向量檔＋Python／node 兩個消費者＋§6.1 不變式題；④文件 | 無（零行為變更；G1 修正僅在 S-Q2 開啟時可見） | 低 | 小 |
| **PR-B 條款組定義化** | 新 kind `quote_terms`（驗證器、比較函式、預覽端點）、旗標 `builder_quote_terms`（預設 0，且需 `builder_governance`）、`system.py` 讀寫轉接（§2.1）、`compute_approval_reasons` 讀定義（失敗＝更嚴）、前端條款組管理改走定義（`pending` 回應不說「已發布」）、`ACTIVE_KINDS`＋`COMPARATORS` 登記、設定中心旗標、`MODULE-GUIDE`／CHANGELOG | `builder_quote_terms` | 中：改動治理與寫入端點 | 中 |
| **PR-C（有條件）** | `approval_basis=2` 與「選定時重審」；或額外條款欄；**僅在使用者回答 Q1／Q4 為「要」時開工**，各自獨立 PR | 沿用 `quote_alt` | 高（簽核語意） | 大 |

順序：A →（可與 gate 並行）→ B；C 另案。

## 8. 待實證（讀碼無法定論，PR 內要驗）
- V1：簽核佇列清單（`/api/approval-queue`，`quotations.py` ~5117 回 `total` 與 `reasons`）與儀表板待審清單，對「非財務檢視者」是否可見（`_queue_visible_to`／`can_quotation` 的範圍）；若可見，需在輸出端套 `MASKED_REASON`。
- V2：S-Q2 開啟時，前端預覽原因與後端原因文字是否真的不同（G1 的重現步驟）。
- V3：條款組 key（`uuid4().hex[:8]`）在定義庫的鍵規則（小寫英數底線）是否相容；相容性遷移要把舊 `system_settings` 內容「讀入第一版草稿」而不是自動發布。
- V4：hichan-6c 對帳原文「Genuinely NOT in T62 #1」在 repo 搜不到；本文假設其內容＝「條款欄位清單／條款組編輯器／`approval_basis`」，請對照確認範圍。

## 9. 需要使用者的決定（短；每題附建議預設，使用者不在時由 PM 依預設）

| # | 問題 | 建議預設 |
|---|---|---|
| Q1 | 擇一單的 `approval_basis=2`（只看計入金額）要不要在 T64 開放？（現行字面定義會讓擇一品項在送審時完全不被審核，需配「選定時重審」才安全） | **不開放**；維持夾回 1；另案 T65 做「選定時重審」後再談 |
| Q2 | 管理者可否關掉某欄的「報價條件已修改」判定（`judge=false`）？ | **不可**（五欄永遠判定）；若日後要，放寬走第二位核准且付款條件禁關 |
| Q3 | 條款組文字／新增組算放寬、須第二位最高管理者核准？（現在單人立即生效） | **是**（與 D-K1 一致；收緊／改名／排序不需要） |
| Q4 | 要不要新增「第 6 個以上的自訂條款欄」？ | **不要**（動資料模型、PDF、遮蔽、版本差異；等有具體需求再開） |
| Q5 | 條款標題是否併入本定義（取代 S-Q2 的三選一匯出範本）？ | **不併**；S-Q2 原樣保留，本定義不放 `label` |
| Q6 | 隱藏表單上的條款欄後，PDF 仍照印既有文字？ | **是**（耦合表 §6 決定 1 已建議；要不印走 BP-3 匯出範本） |

## 10. 不在本切片
原因文字自訂；門檻數值（T62 已完成）；稅別觸發；簽核層與簽核規則；請款單等其他 PDF 的條款標題；報價單金額／品項區塊；個資欄位告知流程。
