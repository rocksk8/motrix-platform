# `SPEC-JV6` · 從既有單據帶入分錄

> 2026-09-23 ／ 視窗 A-2
> ⚙️ 使用者原話（`STATE.md §158`，逐字）：**「從既有單據帶入分錄（發票／承攬商支出／購料發票）」**

---

## §1 🔴 邊界 —— **先讀這一節，否則會做出第三份「從案件撈東西」的邏輯**

有三個編號都在講「把案件的東西帶進傳票」，而它們**產出不同的東西**：

```
JV7   帶入**摘要文字**      => 寫進 voucher_lines.summary（人可再編輯）
JV21  擴充 JV7 的來源清單   => 多一類來源（案件底下的支出子項目）
JV18  帶入**憑證檔案**      => 寫進 voucher_attachments（並標記「已計算」）
JV6   帶入**分錄列**        => 寫進 voucher_lines 的 source_* 三欄  ← 本件
```

> ### 🔑 判準是**產出物落在哪張表的哪幾欄**，不是「從哪裡撈」。
> ### ☠️ 三者都會去讀案件相關的資料，所以「從哪裡撈」分不出它們。

### ⚠️ 而有一個同名不同表的陷阱，B 一定會撞到

```
voucher_attachments.source_type   <= JV3／JV18／JV24 在用（附件的來源）
voucher_lines.source_type         <= **本件在用**（分錄的來源）
```
☠️ **兩張表都有 `source_type`／`source_id`，而它們無關。**
🔑 ⇒ 讀到既有程式碼裡的 `source_type` 時，**先看它 INSERT 進哪張表**。
```
⚙️ 實查：backend/routers/vouchers.py 裡 8 處 source_type 全部是 voucher_attachments 的
⚙️ 而 accounting_export.py 裡的是第三張表 t100_export_confirmations 的
```

---

## §2 ⚙️ 現況實查（2026-09-23，`ast` ＋ 唯讀查 DB）

### ① 資料層 ✅ 齊備

```
backend/db.py:5244-5247  voucher_lines
   source_type              TEXT    NOT NULL DEFAULT ''
   source_id                INTEGER NOT NULL DEFAULT 0
   source_amount_snapshot   INTEGER NOT NULL DEFAULT 0
backend/db.py:5255        索引 ON voucher_lines(source_type, source_id) ✅
```

### ② 🔴 而**寫入端是零** —— 那三欄從來沒有被任何人寫過

```
⚙️ INSERT INTO voucher_lines 共 **3 處**（vouchers.py:230／740／899）
   三處都只寫 6 欄：voucher_id, line_no, account_code, summary, debit, credit
⚙️ 實際資料：voucher_lines 3 列，**source_type 非空 = 0 列**
```
> ### ⚠️ 這裡要講清楚一個差別，因為它與 `JV24` 長得很像而**意義相反**：
```
JV24  作廢重開時 source_* 指向錯的對象   => **寫錯了**
JV6   source_* 三欄從來沒有被寫過         => **還沒有人寫**
```
🔑 ⇒ 不要把這裡當成「複製分錄時漏掉欄位」——**沒有東西漏掉，是功能還沒做**。

### ③ ✅ 而相依 `JV1`-`JV3` **已經滿足**，`JV6` 有落腳處

```
backend/routers/vouchers.py   端點 **15 支**（ast 數的）
   POST / ／ GET / ／ GET /summary-sources ／ GET /{id} ／ submit ／ approve ／
   send-back ／ void ／ post ／ PUT /{id} ／ attachments ×3 ／ pdf-download ／ preview
frontend/pages/voucher.html   **存在**（43,306 bytes），有 `vc-lines` 分錄表格與 `lines` 陣列
```
> ### 🔴 `STATE.md §158` 的「現況」段（`vouchers.py` 只有 2 支／`voucher*.html` 不存在）
> ### **已經過期** —— 那是當時的盤點。**動工前不要引用它。**

### ④ ⚠️ 而 `summary-sources` 的 docstring 也有一段過期的

```
它寫著「附件表屬於 JV3，還沒建（實查：106 張表裡沒有 attachments）」
⚙️ 而 voucher_attachments 現在存在（db.py:4783）
```
📌 不是要改它（那是 B 的檔），是**讀到它時不要當成現況**。

---

## §3 🔴 三種單據對應哪些表 —— **而第三種找不到**

| 使用者說的 | 對應表 | 筆數 | 金額欄 |
|---|---|---|---|
| 發票 | `invoice_vouchers` | 1 | ✅ `amount`（233,725） |
| 承攬商支出 | `contractor_payment_vouchers` | 2 | ⚠️ **不在欄位裡，在 `snapshot_json`** |
| 購料發票 | 🔴 **找不到** | — | — |

### 🔴 ①「購料發票」沒有對應的表

```
⚙️ 掃過 99 張表：invoice／contractor／purchase／material／stock／item／order 七種 pattern
⚙️ 最接近的是 case_extra_expenses，而它的 category 實際值是：
      其他 1 筆 ／ 工時 1 筆 ／ 材料 3 筆 ／ 運費 2 筆
   => **沒有「購料」這個分類**
```
> ### ⇒ 這一格**要問使用者**（見 §7①）。在他回答之前，**只做前兩種**。
> ### ⚠️ 而不要自己把「材料」當成「購料發票」——
> ### 🔑 `case_extra_expenses` 是 `JV21` 的來源（帶**摘要**），與本件帶**分錄**是兩件事。

### 🔴 ② 承攬商支出的金額：**五個候選鍵，而選錯就是記錯帳**

```
⚙️ snapshot_json 裡有五個金額鍵，而兩列資料**剛好互補**：

           id=2 PV-202608-001      id=3 PV-202608-002
totalAmount        0.0                12,000.0
taxAmount            0                     600
totalWithTax       0.0                12,600.0
personnelTotal   3,500.0                    0
grandTotal       3,500.0  ✅          12,600.0  ✅
```
> ### 🔑 **只有 `grandTotal` 兩列都對。**
> ### ☠️ 用 `totalAmount` 的話，id=2 會記成 **0**（漏掉 3,500 的人員費用），
> ### 而**那張傳票會平衡、會過帳、而金額是錯的**。

```
⇒ `source_amount_snapshot` 取 **`grandTotal`**（整數分位，見 §4③）
⚠️ 而 id=2／id=3 這兩列是**天然的對照組**（一列只有人員、一列只有項目）
   🔑 C 出題時兩列都要有 —— 只測 id=3 的話，`totalAmount` 的寫法也會過。
```

---

## §4 🔴 `source_amount_snapshot` 是**快照** —— 原單改了要不要跟著動

### ① 這是本件最容易「順手做對而其實做錯」的一格

```
帶入時    voucher_lines.source_amount_snapshot = 那一刻原單的金額
之後      原單金額被改了（或作廢重開）
❓         傳票上那一列要不要跟著變？
```

### ② ⚙️ 而這個問題**系統裡已經有答案**，不要重新發明

```
JV18 的下游已經裁過：**讀報價單的快照**，不是即時重算
JV7 的 docstring 逐字：「帶入是**起點不是終點**」
   ☠️ 「存來源 id、開啟時重組」的症狀是
      「使用者改完、存檔、關掉；**下次打開才變回來**」
      —— 中間隔了幾天，他不會把兩件事連起來
```
> ### ⇒ **本件沿用同一個裁定：快照就是快照，不跟著原單動。**
> ### 🔑 而理由不是一致性，是會計的：**傳票一旦過帳，它記的就是那一刻的事實。**

### ③ ⚠️ 而型別是 `INTEGER`，而來源是浮點數

```
invoice_vouchers.amount            233725.0   （REAL）
snapshot_json.grandTotal            12600.0   （JSON number）
voucher_lines.source_amount_snapshot  INTEGER
```
🔑 ⇒ 規格定：**存「元」的整數**（與 `debit`／`credit` 同一個單位）。
⚠️ 而轉換要**明著寫 `round()` 再 `int()`**，不要靠隱式截斷 ——
☠️ `int(12600.9)` 是 12600，而那會讓一分錢在對帳時追不回來。

---

## §5 處置

### ① 後端：一支查詢端點 ＋ 寫入既有的兩支

```
GET /api/vouchers/line-sources        新增（列出可帶入的單據）
   ⚠️ 靜態路徑要宣告在 /{voucher_id} **之前**，否則走到動態路由回 422 不是 404
   （`JV21` 踩過這一格，STATE:29117）
   ⚠️ 閘門與傳票其餘端點**同一道**（`_require_voucher_access`）——
      ☠️ 它會列出案件與客戶名，放鬆等於從記帳畫面繞過去看客戶清單
```
```
POST /api/vouchers            create_voucher  :230   ← 三處 INSERT 都要收 source_*
PUT  /api/vouchers/{id}       update_voucher  :899
POST /api/vouchers/{id}/void  void_voucher    :740   ← 作廢重開複製時**沿用原值**
```
> ### ⚠️ 第三處（`:740`，作廢重開）是 `JV24` 正在改的同一段 ——
> ### 🔑 **動之前先確認 `JV24` 的狀態**，兩件都改那一段 INSERT。

### ② 前端：分錄表格多一個「帶入」入口

```
⚙️ frontend/pages/voucher.html 已有 vc-lines 表格與 lines 陣列
⚙️ 而**沒有任何「帶入既有單據」的入口**（grep「帶入」只命中欄位提示文字）
```
```
⚠️ 帶入後那一列**仍然要可以編輯**（JV7 的裁定）
⚠️ 而已經帶過的要看得出來 —— 一個記號就好，**不要擋住**
   🔑 同 JV18 的裁定：只標記不擋住（作廢重開會複製，擋住會把合法路徑擋死）
```

### ③ ⚠️ 而「帶入分錄」要帶幾列？

```
一張發票 => 借：應收帳款 / 貸：營業收入 ＋ 稅額   => **至少兩列，可能三列**
```
> ### 🔑 ⇒ 這不是「一張單對一列」，而**借貸必須平衡**（`helpers/voucher.py` 已有那道檢查）。
> ### ⇒ 帶入產生的列要**一起通過既有的平衡檢查**，不是繞過它。
⚠️ 而**科目代號從哪裡來**沒有答案 —— 見 §7②。

---

## §6 驗收（`AC1`：後端＋前端＋頁面三者皆備才算完整）

### ① 必過

```
① 帶入一張 invoice_vouchers => voucher_lines 出現 source_type='invoice_voucher'
   ／source_id=該單 id ／source_amount_snapshot=233725
② 帶入 id=2 PV-202608-001 => source_amount_snapshot = **3500**
   🔴 而**不是 0** —— 這一題就是在擋 totalAmount 的寫法
③ 帶入 id=3 PV-202608-002 => source_amount_snapshot = **12600**
④ 帶入後改那一列的 summary => 存檔 => 重新開啟 => **仍然是使用者打的那個**
   （JV7「帶入是起點不是終點」）
⑤ 原單金額改了 => 傳票上的 source_amount_snapshot **不變**（§4）
⑥ 前端：分錄表格有帶入入口，帶入後那一列可編輯，且看得出它是帶入的
```

### ② 🔴 誘餌（反向控制）—— 沒有這一格，②③ 可以靠寫死通過

```
誘餌：一列**刻意只有 personnelTotal 而 totalAmount=0** 的合成資料
      （不要用 id=2 當誘餌 —— 它是真實資料，可能被改掉）
🔑 誘餌要與受測對象是**同一種寫法**：也放在 snapshot_json 裡，不要用欄位
⇒ 讀不到 grandTotal 就退回 totalAmount 的實作，**必須紅在這一題上**
```

### ③ ⚠️ 而要先證明它會紅

```
破壞方式（真實失效模式，不是隨便改）：
   把取值改成 d.get("totalAmount")  => ② 與誘餌兩題都要紅
   把快照改成即時重算              => ⑤ 要紅
☠️ 而破壞方式若只是「刪掉整個函式」，那證明不了什麼
   （〈證明測試會紅時破壞方式必須是真實失效模式〉）
```

---

## §7 ⏳ 待使用者確認（他人在，A 可以直接問）

### ① 🔴 **「購料發票」指的是什麼**

```
⚙️ 99 張表裡找不到對應的表（七種 pattern 都掃過）
⚙️ case_extra_expenses 的分類是「其他／工時／材料／運費」，沒有「購料」
```
```
我裁（暫行）：**本輪只做發票與承攬商支出兩種**，購料發票等他回答
依據         寧可少做一種，也不要猜錯一種 —— 猜錯的那一種會**記錯帳**
他若說是別的 那就是多一個來源類型，§5① 的端點多一個分支，
             §6 多兩題（正例＋誘餌）—— 結構不用改
```

### ② 🔴 **帶入的分錄，科目代號從哪裡來**

```
一張發票要產生「借：應收帳款 / 貸：營業收入 / 貸：銷項稅額」——
而**哪一個科目代號**對應哪一種單據，系統裡沒有這個對照。
```
```
我裁（暫行）：**科目留空，由使用者自己選**（帶入只帶金額與摘要）
依據         voucher.html 的欄位提示寫著「（輸入代號後自動帶入）」
             => 選科目已經有現成的互動，不必發明新的
他若要自動帶 那需要一張「單據類型 -> 科目」的對照表（新表 ＋ 設定頁），
             ⚠️ 那是**另一個編號的份量**，不要塞進本件
```

### ③ ⚠️ **承攬商支出的稅額要不要分開列**

```
id=3 PV-202608-002：totalWithTax 12,600 = totalAmount 12,000 ＋ taxAmount 600
```
```
我裁（暫行）：**帶入一列 grandTotal**，稅額不分拆
依據         分拆需要知道稅額該記哪個科目（同 ② 的問題）
他若要分拆   那是兩列（本體 ＋ 稅額），而 §6② 的期望值要改成 12,000 ＋ 600
```

---

## §8 動工前要先查的

```
① 🔴 `JV24` 的狀態 —— 它正在改 void_voucher 的那段 INSERT（vouchers.py:740），
   而本件也要動同一段。**兩件的順序要有人決定**，不要同時改。
② `invoice_vouchers` 只有 **1 列**、`contractor_payment_vouchers` 只有 **2 列** ——
   ⚠️ 開發機的樣本太小，正式機上的分佈可能不同（而我們不碰正式機）
③ `snapshot_json` 的五個金額鍵是**這兩列**觀察到的 ——
   ☠️ 若有一列的 snapshot 結構不同（舊格式），`grandTotal` 可能不存在
   ⇒ 動工時先掃**全部**的 snapshot_json，數有幾列缺 grandTotal
④ 前端 `lines` 陣列的結構我只看了 vc-lines 的 HTML，**沒有讀它的 JS 邏輯**
⑤ `helpers/voucher.py` 的借貸平衡檢查我**沒有讀**，只知道它存在
```
