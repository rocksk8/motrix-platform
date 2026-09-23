# `BN6`／`BN7` 獎金分潤單的明細表 ＋ PDF —— 施工圖

> A-2 撰寫／2026-09-23。量測座標 **`64caf04`**。
> ⚠️ 量測時工作樹有 **6 個異動**（不是我的）。
> **單一版本、無修訂層。照這一份做。**

**使用者原話（逐字）**
```
「獎金單需要詳細有張表格，像是精算頁面一樣，報價多少、成本多少、衍生成本、
  比例最後總利潤多少，再用這個利潤去拆發比例，可預覽、可匯出pdf」
```

🔴 **`BN6` 一個數字都不要算。** 10%／1% 只寫在 `settlement.html`；
再寫一份就是**第三份實作**（`helpers/bonus.py` 模組 docstring 已寫死這條）。

---

## §1 表格：逐字抄 `settlement.html` 的標籤與順序

使用者說「**像是精算頁面一樣**」⇒ **不可以自己重新命名欄位**，
否則他要對照兩張表才看得懂。

### 實查的標籤與對應鍵（`frontend/pages/settlement.html`）

```
─ 上半：報價 ────────────────────────────────
原始報價預估        quotedPretax      （未稅）
                    quotedTotal       （含稅）
─ 中段：成本 ────────────────────────────────
品項實際成本        itemActualTotal
額外支出            extraTotal
承攬商派發成本      dispatchTotal
實際總成本          totalActualCost
─ 下半：利潤 ────────────────────────────────
真實毛利            grossProfit
真實毛利率          grossMarginPct
管銷分攤（10%）     adminCost
公益捐款（1%）      charityDonation
真實淨利            netProfit          ← **這就是獎金基數**
真實淨利率          netMarginPct
```

⚠️ **括號裡的百分比要照抄**（「管銷分攤（**10%**）」），
而**不要在 `BN6` 這一側把 10% 寫成常數** —— 那個數字**來自 `settlement` 已存的值**，
`BN6` 只是把 `adminCost` 印出來。
📌 使用者若日後改比例，改的是精算那一側；`BN6` 不必動。

### ☠️ 缺欄位標「無」，**不要印 0**

實查 13 筆 settlement：
```
6 筆  十個關鍵欄位齊全
6 筆  **缺 dispatchTotal**（沒有派發承攬商 ⇒ 那一欄不存在，不是 0）
1 筆  summary 是 **空的 `{}`**（MQ-EXPFILE-001，而 status 是 finalized）
```
🔑 `dispatchTotal` 不存在 ＝ **這個案件沒有派過承攬商**；印 0 讀起來是
「派了而金額為零」—— **兩件事**。〈null 不等於 0〉。
⇒ 缺的欄位印「**—**」或「無」，與 `notify_tender_found` 的 `_dash()` 同一個做法
（那支 docstring 逐字：「『沒有』要看得見，才知道那是**沒有**不是**漏掉**」）。

---

## §2 ④利潤 → ⑤拆發：`plan_award()` 缺哪幾格

### 現在回什麼（實查）

```
{ quote_no,
  base: { ok, amount, error },          ← amount 就是 netProfit
  has_active_award, active_award_id,
  items: [ { bonus_item_id, name, person_source, ok, people, note } ] }
```

### 缺的兩塊

```
🔴 缺一：**整張精算明細**（§1 那十二格）
   現在只有 base.amount 一個數字 ⇒ 畫不出「報價多少、成本多少、衍生成本」
   ⇒ plan 要多回一格 settlement（把 summary 原樣帶出來，**不要重算、不要改鍵名**）

🔴 缺二：**拆發後的金額**
   items[].people 只有 username，**沒有金額**
   而金額要 total_pct ＋ person_pct 才算得出來 —— 那是使用者在畫面上填的
```

### ⇒ 「可預覽」怎麼接：**`POST` 同一個路徑**

```
使用者要的「可預覽」= **還沒產生獎金單就要看得到拆發結果**
⇒ 需要把 allocations 送上來 ⇒ GET 帶不了
```
📌 A 裁「**擴充既有端點，不要開新端點**」。**我照那個意圖，而形式要微調**：
```
GET  /api/bonus/awards/plan/{quote_no}          ← 不變（母體＋精算明細）
POST /api/bonus/awards/plan/{quote_no}          ← **同一個資源，多一個動詞**
     body 與 POST /awards 的 allocations **完全相同**
     回 { settlement, base, lines: [...], remainder }
```
🔑 **同一個路徑、同一個 body 形狀** ⇒ 使用者按「預覽」與按「產生」送的是同一份資料，
**唯一的差別是有沒有寫進資料庫**。
☠️ 若預覽與產生各用一套輸入格式，**預覽對了而產生出來不一樣**，
而那正是預覽存在的意義被抵銷的方式。

⚠️ **這是對 A 裁示的形式調整（多一個 `POST` 動詞），不是另開端點。**
若 A 認為仍算「新端點」，**請回覆，我改**。

### 🔴 拆發金額**必須用 `split_award()` 的實際輸出**

```
❌ 前端自己算 pool × pct     ⇒ 餘數處理只有 remainder_of() 知道
                               （尾差歸公司，不補給任何人 —— A 已裁）
✅ 後端呼叫 split_award()，把 lines 原樣回給前端
```
⇒ 預覽回的 `lines` 要與 `POST /awards` 寫進 `bonus_award_lines` 的**同一組值**。
⚙️ 驗收釘這一條：**預覽的金額 == 產生後 `bonus_award_lines` 的金額，逐筆相等**。

📌 而 `remainder` 也要回並**印在表上**（「尾差 N 元歸公司」）——
☠️ 不印的話，使用者會自己加總然後發現「加起來不等於淨利」，
**而他不知道那是設計**。

---

## §3 那兩筆特殊案件，預覽各自要說什麼

A 已裁：**都要給看**，而「可發放金額 0」明著寫在表上。

```
MQ-EXPFILE-001   settlement.summary = {}，status=finalized，netProfit=None
  表格           十二格全部印「—」
  基數           「精算未完成，無法計算基數」
  出路           直接用 base_amount_for 的原話：
                 「這個案件的精算是舊格式（沒有淨利欄位），無法產生獎金單。
                   請重新開啟並儲存一次該案的精算，系統會自動補算淨利後即可發放。」
  拆發區         **不顯示比例輸入框**（沒有基數可以拆）

netProfit <= 0   （今天 **0 筆**，而規則要先寫好）
  表格           照常印（它有完整數字，那些數字本身是有意義的）
  基數           「淨利 0 或負數，**可發放金額 0**」
  拆發區         **不顯示比例輸入框**
```
🔴 **兩者的訊息不可以合併**：一個**有出路**（重存精算），一個**沒有出路**（就是沒賺錢）。
📌 同 `BN5` 的四態規則。

---

## §4 `BN7` PDF 匯出

### ✅ Edge headless 那條路**可以直接沿用**，而且比 `JV5` 簡單

```
JV5   本體 ＋ **附件合併** ⇒ 需要 pypdf
BN7   **只有一張表，無附件** ⇒ **不需要 pypdf**
⇒ HTML -> run_edge_pdf(--print-to-pdf) -> bytes，與既有 16 個呼叫端同一形狀
```

⚠️ **必須照抄那道檢查**（`helpers/startup.py::run_edge_pdf` docstring 逐字）：
```
run_edge_pdf **吞掉逾時不丟例外**，靠呼叫端緊接的
「tmp_pdf 沒產出或 0 byte 就 raise」報錯
⇒ 忘了抄 = 逾時變成回一份 **0 byte 的 PDF**
```
📌 併發受 `EDGE_PDF_SEMAPHORE` 限制、逾時 120 秒。

### 端點

```
GET /api/bonus/awards/{award_id}/pdf-download
```
沿用既有慣例（`quotations`／`payslips`／`invoice_vouchers` 六處同形狀）。
**權限**：`_is_manager`（與 `POST /awards` 同一道閘）。
⚠️ 而**已作廢的單也要印得出來**（稽核要看得見）。

### ⚠️ 康熙部首（`§214`）—— 驗收要 NFKC

```
實查：backend 產品碼裡 NFKC／康熙 命中 **0 處** ⇒ **目前沒有任何正規化**
```
⇒ `BN7` 的驗收要對**輸出的文字**做 `unicodedata.normalize("NFKC", …)` 之後再比對，
否則「⾦額」（康熙部首 U+2666）與「金額」(U+91D1) 在斷言上是兩個字串。
☠️ 而症狀是**測試紅在一段看起來完全正確的文字上** —— 肉眼分不出來。
📌 **本項不負責去正規化既有資料**，只要求驗收比對時正規化。

---

## §5 ✅ 已裁：要抬頭，也要用印欄 —— 🔴 **而用印欄算不出來**

使用者 2026-09-23（`STATE.md §229`）：**要抬頭，也要用印欄**，
**用印欄列數從簽核設定算**（同 `JV5` 的做法）。

```
抬頭  ✅ 從 company_profile 讀，**不可以寫死**
      （這個 repo 已經寫死在 14 個檔／56 行）
      ⚠️ 而 JV9 剛修掉一個同族的坑：_get_setting() 已經 json.loads 過，
         voucher_pdf.py:82 又 loads 一次 => TypeError 被 except 吞掉
         => 本項讀設定時**不要再 loads 一次**
```

### ☠️ 而「用印欄列數從簽核設定算」**今天算不出來** —— 獎金單沒有簽核流程

實查（`8e68088`）：
```
bonus_awards 欄位   id / quote_no / base_amount / base_source / template_id /
                    template_version / status / voucher_no_accrual /
                    voucher_no_payment / voided_* / supersedes_id / created_*
                    ⇒ **沒有 approval_json，沒有任何簽核欄位**
APPROVAL_DOC_TYPES  八種（quotation … completion ＋ **voucher**）
                    ⇒ **`bonus` 不是其中之一**
bonus router 七支   items×2 ／ base ／ plan ／ awards GET,POST ／ void
                    ⇒ **沒有 submit／approve／reject**
UPDATE bonus_awards 全 repo 只有一處，而它只寫 voided_*
                    ⇒ **status 建立之後從來不會改**
實際資料            1 筆，status = **草稿**
```

🔴 ⇒ **獎金分潤單建立之後永遠是「草稿」，沒有簽核、沒有過帳。**
☠️ **使用者的裁示預設了一個不存在的前提**：它說「從簽核設定算」，
而獎金單**沒有簽核設定可以算**。

### ⇒ 三條路，**要 A／使用者裁，本規格不決定**

```
(a) 獎金單也走 tiered_approval  => 成為**第九個** doc type
    ✅ 用印欄列數自然算得出來；與傳票（第八個）同一條路
    ⚠️ 而它是一個**新流程**：要 submit／approve／reject 三支端點 ＋ 狀態機
       => 那是一個獨立編號的量，不是 BN7 的一格
(b) 用印欄印**固定格**（例如 製表／核准 兩格）
    ✅ 今天就做得完
    ⚠️ 而它與使用者那句「從簽核設定算」**不一致** => 要他點頭
(c) BN7 先不做用印欄，只做抬頭
    ✅ 不會做出一個之後要拆掉的東西
    ⚠️ 而使用者明著要了用印欄
```
📌 A-2 建議 **(b) ＋ 明著告訴使用者「獎金單目前沒有簽核流程」** ——
讓他決定要不要為它開一條（那是 (a)，而它值得一個自己的編號）。
🔑 **不要自己選 (a) 去做** —— 那會在他只要一張紙的時候長出一整條流程。

---

## §6 驗收（`AC1`：後端＋前端＋頁面三者皆備）

```
後端 ① GET /plan 回的 settlement **鍵名與 settlement.summary 逐字相同**
        ☠️ 改名的話下一個人要維護兩套對照
     ② 缺 dispatchTotal 的案件 -> 那一格回 **null**（不是 0）
        而畫面印「—」
        ⚙️ 用今天那 6 筆之一，**不必合成**
     ③ summary 空的案件（MQ-EXPFILE-001 那種）-> 十二格全 null，
        base.error 是 base_amount_for 的原話
     ④ 🔴 **POST /plan 的 lines == POST /awards 之後 bonus_award_lines 的值，逐筆相等**
        ⚙️ 同一組 allocations 先預覽再產生，兩邊金額比對
        ☠️ 這一題紅而其他全綠 = 預覽會騙人，**而那比沒有預覽更糟**
     ⑤ 預覽回的 remainder == remainder_of() 的值，且**表上印得出來**
     ⑥ BN7：PDF 回 200、application/pdf、**位元組數 > 0**
     ⑦ 已作廢的獎金單也印得出來
     ⑧ 非管理者 -> 403（**不是 500、不是空 PDF**）
     ⑨ 先斷言 status_code in (200, 400, 403) 再看內容（`§166` 三種臉）
前端 ⑩ 獎金頁有「預覽」與「匯出 PDF」兩個會送出的動作
頁面 ⑪ 表格的標籤與 settlement.html **逐字相同**（含「管銷分攤（10%）」的括號）
     ⑫ 文字比對前先 NFKC（`§214`）
```

⚠️ **④ 是這一份的核心。** 預覽的價值全部建立在「它與實際產生的一致」上。

---

## §7 我沒做的

```
✗ 沒有實作、沒有跑任何測試
✗ settlement.html 的標籤我用 grep 取，**沒有開瀏覽器看實際渲染順序**
  ⚠️ 若版面上有我沒抓到的欄位（例如條件顯示的），**會漏掉**
✗ 沒查 settlement.html 那十二格在**畫面上的分組線**（我照原始碼順序分成三段，
  而那是我分的，不是它的 DOM 結構）
✅ 已作廢的浮水印：`JV10/JV11 §5` 已查 —— **這個 repo 沒有「作廢」浮水印的慣例**
  （`pdf_gen.py` 對「作廢」命中 0 次）⇒ 獎金單沿用傳票那邊裁定的優先序
  （**作廢優先於未簽核**，使用者已裁）
✗ 沒量 PDF 產生的耗時（Edge 有 semaphore，而獎金單可能被連續匯出）
✗ `§214` 康熙部首我只查了「產品碼有沒有正規化」（0 處），
  **沒有查既有資料裡有沒有康熙部首字元**
```
