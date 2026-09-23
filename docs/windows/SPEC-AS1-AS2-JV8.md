# `AS1` ／ `AS2` ／ `JV8` —— 施工圖（三項共用同一組量測）

> A-2 撰寫／2026-09-23。量測座標 **`99ea423`**，量測時工作樹 **乾淨**（0 個異動）。
> **單一版本、無修訂層。照這一份做。**

**使用者原話（逐字，兩則）**
```
「匯款申請簽核設定整合進去簽核設定，傳票應該是新增傳票後才出現傳票的頁面，
  傳票的簽核需要在簽核設定中出現，最後當視窗回報但某視窗沒有回覆，
  應於三分鐘後再次傳送要求，避免空轉」
「**超過兩層就把版面往下加列**，繼續做」
```

---

## §0 🔴 先講一件會改變三項做法的實況：**分派機制已經存在**

```
helpers/tiered_approval.py:36  APPROVAL_DOC_TYPES        七種
                          :38  DEFAULT_UNIFIED_DOC_TYPES 六種
                          :52  approval_flow_setting_key(doc_type, scope)
                                 scope[doc_type] 為 True => unified_approval_flow
                                 否則                     => {doc_type}_approval_flow
```

```
七種：quotation 報價單／shipping 出貨單／invoice_voucher 發票開立簽核單／
      payment_request 請款單／contractor_voucher 承攬商匯款申請／
      extra_expense 案件額外支出／completion 完工單
🔴 而 DEFAULT_UNIFIED 只有六種 —— **`contractor_voucher` 是唯一被排除的那一個**
```

⇒ **`AS1` 不是要蓋一個新機制，是要把那一個排除拿掉（並把頁面併起來）。**

---

## §1 `AS1` 匯款申請簽核設定併進簽核設定

### 🔴 A 問的前置：兩個設定頁背後**是不是同一張表**？

**是同一張表，不同的 key。而那正是「併頁面」與「併資料」是兩件事的原因。**

```
表      system_settings（欄位：key / value_json / updated_at）
頁面    frontend/pages/approval-settings.html
        frontend/pages/contractor-voucher-approval-settings.html   ← 要被併掉的那個
key     approval_flow                     ← **孤兒，見下**
        contractor_voucher_approval_flow
        invoice_voucher_approval_flow
        unified_approval_flow
scope   approval_flow_scope               ← **DB 裡 0 筆** ⇒ 全部走預設分組
```

### ☠️ 而「併資料」今天會**清空匯款申請的簽核鏈**

實讀四把 key 的內容（`99ea423`）：
```
approval_flow                      2 層：jeff -> corbin          ← 孤兒
contractor_voucher_approval_flow   2 層：corbin -> queena        ← 匯款申請現在走這個
invoice_voucher_approval_flow      2 層：corbin -> queena
unified_approval_flow              **0 層**，includeSubmitterManagerTier: true
```

🔴 ⇒ 把 `contractor_voucher` 切進 unified 的那一刻：
```
corbin -> queena（兩層具名）   變成   **0 層 ＋ 送審者的主管**
```
☠️ **那是「誰核准匯款」這件事被改掉了，而它不會有任何錯誤訊息。**
⇒ **本項只做「併頁面」，切不切 scope 由使用者在頁面上按**，
而按下去之前畫面要先講出**現在是什麼、按了會變成什麼**。

⚙️ 驗收要有一題釘這個：**切換 scope 之前，畫面必須顯示兩邊現有的層與人**。

### 📌 順帶：`approval_flow` 是孤兒

```
精確比對 "approval_flow"（排除 unified_／contractor_／invoice_ 前綴）
=> 全 repo 只有 **db.py:2806 的一段 docstring**（在講歷史），**沒有任何活的讀取端**
```
⇒ 它是報價單的舊 key；報價單現在在 `DEFAULT_UNIFIED` 裡 ⇒ 走 `unified_approval_flow`。
⚠️ **本項不要刪它**（刪設定是不可逆的，而它不妨礙任何事）——
但**設定頁不可以顯示它**，否則使用者會去編一把沒有人讀的設定。

---

## §2 `AS2` 傳票簽核出現在簽核設定中

### 🔴 這一項推翻 `§161` 的「傳票不接 `approval_settings`」

A 的更正（我照收）：那個裁定是從「跟坊間正式傳票一樣」推出「簽核流程也要寫死」，
**而使用者那句是在講版面**（那張 PDF 上的三格）。
⇒ **「兩層」是預設值，不是常數** —— 要改的是**它從哪裡來**。

### 做法：傳票成為**第八個** doc type

```
helpers/tiered_approval.py
  APPROVAL_DOC_TYPES        + "voucher"
  APPROVAL_DOC_TYPE_LABELS  + "voucher": "傳票"
  DEFAULT_UNIFIED_DOC_TYPES  ⚠️ **加不加由使用者裁**（見 §4 待裁）
```

⚠️ **命名衝突要先看一眼**：既有已經有 `invoice_voucher`（發票開立簽核單）與
`contractor_voucher`（承攬商匯款申請）。
☠️ 再加一個 `voucher`（會計傳票）⇒ 三個都叫 voucher，而它們是三種不同的單據。
📌 標籤上要看得出來：`"voucher": "傳票（會計）"` 比 `"傳票"` 好。

### 🔴 而傳票的簽核欄位**已經存在**（B 的 `v99`，實查 `PRAGMA`）

```
vouchers_all  submitted_by / submitted_at / checked_by / checked_at
              manager_by  / manager_at
⇒ **固定三格的欄位已經落地** —— 而 §3 的版面要求是「依層數往下長」
```
☠️ ⇒ **兩者現在對不上。** 這是本項最貴的一格，而它要先決定：
```
(a) 欄位保持三格，超過兩層的部分存進別的地方（例如一張簽核紀錄表）
(b) 改成一張 voucher_approvals 明細表，三個欄位退成 view／相容層
```
📌 A-2 建議 **(b)**，兩個理由：
```
① 既有六個單據類型都已經走 tiered_approval 的明細形狀 ⇒ 傳票另立一套 = 規則有兩份
② (a) 的「別的地方」會變成第二個真相來源，而版面要同時讀兩處才畫得出來
```
⚠️ **而這是建議不是裁示** —— 它會動到 B 剛落地的 `v99`，**要 A 裁**。

---

## §3 版面：簽核區**依層數往下長**（同時解掉 `AS2` 與 `JV5`）

使用者原話：**「超過兩層就把版面往下加列」**。

```
簽核區 = 製票（建立者，**不算層**） ＋ 第 1 層 ＋ … ＋ 第 N 層
```

### 兩件要寫進實作

```
① **尚未簽的層照樣印出空格** —— 紙本要有地方簽
   📌 與「清單那一層說實話」同一個方向：畫面／紙上要看得出「還缺誰」
② 🔴 **31.8% 是三格版的量測，不是版面規則**
   §103b 量的是那一張實例（三格）⇒ **不可以寫成驗收條件**
   ⚠️ 層數多到超過一頁時的分頁規則 —— **§103b 只量過單頁** ⇒ **待查，不要假設放得下**
```

⇒ `SPEC-JV5-PDF.md` `§2` 的座標**仍然有效**（欄界／列高／抬頭兩行都是量出來的），
**而「內容佔頁高 31.8%」那一行要改成「三格版的實測值，不是上限」**。

---

## §4 `JV8` 新增傳票後才出現傳票的頁面

使用者原話：**「傳票應該是新增傳票後才出現傳票的頁面」**。
現況：一打開就是編輯畫面（`voucher.html` 進來就有三行空白分錄）。

```
進入頁面        -> **清單**（或一個「新增傳票」的起點），不是空白編輯畫面
按「新增傳票」  -> 呼叫 POST /api/vouchers 產生草稿 -> **才顯示編輯畫面**
`?id=` 進來     -> 直接顯示那一張
```
📌 `?id=` 的 `replaceState`（`JV7` 加的）**已經做掉一半** ⇒ 本項是把入口那一半補上。

⚠️ **一個要明著決定的**：按下「新增傳票」就**先在資料庫建一張草稿**，
還是**填完才建**？
```
先建   單號當場就有（使用者看得到）；而**使用者按了又離開會留下空草稿**
後建   不留垃圾；而單號要到存檔才出現，**畫面上那一格會是空的**
```
📌 A-2 建議**先建**，理由是 `voucher_no` 由後端發號（`next_voucher_no`）
⇒ 前端無法預先顯示；而空草稿是可刪的（草稿階段可刪，`§JV3-5` 同一條）。
⚠️ **而這是建議不是裁示。**

---

## §5 驗收（`AC1`：後端＋前端＋頁面三者皆備）

```
AS1 ① 簽核設定頁看得到「承攬商匯款申請」這一類
    ② 🔴 切換 scope **之前**，畫面顯示兩邊現有的層與人
       （現在 corbin->queena ／ 切過去會變成 0 層＋送審者主管）
    ③ 設定頁**不顯示** approval_flow 這把孤兒 key
    ④ 舊頁 contractor-voucher-approval-settings.html 的入口移除，
       而**舊網址仍可開**（或導向新頁）—— 有人把它加進我的最愛

AS2 ⑤ 簽核設定頁看得到「傳票（會計）」
    ⑥ 傳票送審時讀的是 resolve_active_flow_setting("voucher")，
       **不是寫死的兩層**
       ⚙️ 觀測方式：**把設定改成三層**，再送審，簽核鏈必須是三層
       ☠️ 只驗「兩層時能過」的話，寫死與讀設定**結果一樣**
    ⑦ 標籤分得出三種 voucher（發票開立／承攬商匯款／會計傳票）

版面 ⑧ 設定三層 -> 傳票頁面與 PDF 的簽核區都是 **製票 ＋ 三格**
    ⑨ 只簽了第一層 -> 第二、三層**仍然印出空格**
    ⑩ ⚠️ **不可以**斷言「內容佔頁高 31.8%」（那是三格版的實測值）

JV8 ⑪ 直接開 voucher.html -> **看不到空白編輯畫面**
    ⑫ 按「新增傳票」-> 出現編輯畫面且**單號已經有值**
    ⑬ 帶 ?id= 進來 -> 直接顯示那一張
    ⑭ 先斷言 status_code in (200, 400, 403) 再看內容（`§166` 三種臉）
```

⚠️ **⑥ 是 `AS2` 的全部**。其他全綠而它紅 ＝ 只是把一個新標籤畫在設定頁上。

---

## §6 待裁（**不要自己決定**）

```
① `voucher` 要不要進 DEFAULT_UNIFIED_DOC_TYPES（＝傳票預設跟大家同一條流程，
   還是自己一條）
② `contractor_voucher` 要不要**預設**切進 unified
   ⚠️ 切了 = 匯款申請的簽核鏈從 corbin->queena 變成 0 層 + 送審者主管
   📌 A-2 建議「不預設切，讓使用者在頁面上自己按」
③ `AS2` 的 (a)/(b)：三個簽核欄位保留，還是改成明細表
   📌 A-2 建議 (b)，而它會動到 B 剛落地的 v99
④ `JV8` 按下新增就先建草稿，還是填完才建
   📌 A-2 建議先建（單號由後端發，前端無法預顯）
⑤ 版面超過一頁時的分頁規則（§103b 只量過單頁）
```

---

## §7 我沒做的

```
✗ 沒有實作、沒有跑任何測試
✗ 沒讀 approval-settings.html 的實際版面（只查了它打哪些 API：org/tree、users）
✗ 沒查 tiered_approval 的簽核推進邏輯對「三層以上」是否已經支援
  ⚠️ 既有四把 key 全都是 2 層 ⇒ **三層以上從來沒有被跑過**，那一格要實測
✗ 沒查 voucher.html 目前的進入流程細節（只確認它一進來就有三行空白分錄）
✗ 使用者那句「某視窗沒有回覆應於三分鐘後再次傳送」是**協定的事**，不在本規格範圍
```
