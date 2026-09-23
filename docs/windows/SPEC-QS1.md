# `SPEC-QS1` · `quotations.sales_person` 同一欄混兩種識別

> 座標：`4e8ca1e`（工作樹：本檔為新增）
> 作者：視窗 A-2 ／ 2026-09-23
> 來源：查 `BN14` 時撿到；A 裁另開編號。

---

## §1 🔴🔴 **正確的識別欄位已經存在** —— 這一件的處置整個換了

### 實查

```
quotations.**sales_person_id**   INTEGER REFERENCES users(id)
   由 `db.py:1028 _m010_sales_person_id()` 加的，**並且已經回填**
⚙️ 26 張裡 sales_person_id 為 NULL 的 = **3 張**（23 張已經有）
```

### 而讀取端**早就在用它了**

```sql
-- routers/quotations.py:244（擁有者過濾）
sales_person_id=? OR (sales_person_id IS NULL AND sales_person=?)
```
🔑 ⇒ **「id 優先，NULL 才退回字串」的相容寫法已經存在** ——
系統**早就在遷移中**，而 `sales_person` 是那條遷移路上的舊值。

> ### ⇒ `QS1` **不是**「把 `sales_person` 改成裝 `username`」，
> ### 而是「**把那 3 張補回填，並讓讀取端一律走 `sales_person_id`**」。

📌 ⚠️ 而這也讓 D 量的那份回填表（`display_name` → `username`）**答的是另一個問題** ——
正確的目標是 `sales_person_id`（一個整數 FK），不是一個 username 字串。

---

## §2 🔴 那 3 張沒回填到的**原因就是這一件本身**

```
MQ-202607-059   sales_person='**test3**'（小寫＝**username**）  sales_person_id=NULL
MQ-202607-060   sales_person='**test3**'                        sales_person_id=NULL
MQ-EXPFILE-001  sales_person=''（空，測試單）                    sales_person_id=NULL
```

而 `_m010` 的回填 SQL：
```sql
UPDATE quotations SET sales_person_id = (
    SELECT id FROM users
    WHERE **display_name** = quotations.sales_person AND active = 1
    LIMIT 1
)
WHERE sales_person_id IS NULL AND sales_person != '' AND sales_person IS NOT NULL
```

> ### ☠️ 它只比對 `display_name` —— 而那兩張存的是 **`username`** ⇒ **比對不到**。
> ### 🔑 **那個 migration 的回填失敗，正是因為「同一欄混兩種識別」。**

### 🔴🔴 更正（D 指出，A 轉）：**這支函式裡有兩個洞，而害到 `QS1` 的只有一個**

我原本寫成一句（「它靜默失敗：`try … except: logger.warning`」）。
**那是把兩個獨立的風險合併成了一個**，而合併之後**修法會指錯**。

```
洞 A  **例外被吞掉**
      try: UPDATE …  except: logger.warning("m010 backfill failed")
      守的是**整句 SQL 的語法錯／連線層級的錯**
      修法 = **不要吞**（或吞了要往上報）
      ⚠️ 而 `QS1` 這件事**從頭到尾沒有觸發過它**

洞 B  🔴 **比對到 0 筆**          <= **害到 `QS1` 的是這一個**
      子查詢 `display_name = 'test3'` 查無結果
      => SQL **正常執行完**、沒有拋任何例外、`UPDATE` 回報成功
      修法 = **看 `cur.rowcount`**（例外處理一行都幫不上忙）
```

> ### 🔑 **「靜默失敗」不是一種東西 —— 至少有兩種，而它們可以在同一支函式裡並存。**
> ### ☠️ 而 **B 比較危險：它連一個可以被吞掉的訊號都沒有產生。**

```
📌 ⇒ 本規格的範圍**只有 B**。
   洞 A 那一族 D 已經量完（加總自檢 23 = 純 DDL 容錯 20 + re-raise 0 + 靜默 3），
   其中會停在「改了一半」的只有 `_m008_fix_legacy_owner_names`（逐筆迴圈裡 try）
   => A 已另開 `MG3` 追，**不在本編號內**
⚠️ 而 `_m006`／`_m010` 是**單一整句 UPDATE** ⇒ SQLite 整句成敗，**不會改一半**
```

📌 而我合併它們的成因值得記一筆：
**兩個洞在同一支函式、在同一個 `try` 區塊裡、而且症狀一樣（沒有人知道回填沒成功）**
⇒ 🔑 **「症狀相同」不是「同一個成因」** —— 而我是從症狀往回推的。

---

## §3 處置

### ① 補回填：**兩層比對，而第二層要留痕**

```sql
-- 第一層：display_name（既有）
UPDATE quotations SET sales_person_id = (
    SELECT id FROM users WHERE display_name = quotations.sales_person AND active = 1 LIMIT 1)
WHERE sales_person_id IS NULL AND sales_person <> '';

-- 🔴 第二層：**username**（新增，這一件的主體）
UPDATE quotations SET sales_person_id = (
    SELECT id FROM users WHERE username = quotations.sales_person AND active = 1 LIMIT 1)
WHERE sales_person_id IS NULL AND sales_person <> '';
```

⚠️ **而要印出結果，不可以靜默** ——
🔴 而「印到哪裡」由 `SPEC-MG4` 定義（**不是 `logger`**，它的消費端是 0）：
```
跑完要印：第一層命中 N 筆／第二層命中 M 筆／**仍然 NULL 的 K 筆逐筆列名**
🔴 K > 0 時**不要失敗**，但要留一筆 logger.warning 含那 K 個單號
☠️ 而「仍然 NULL」是合法狀態（`MQ-EXPFILE-001` 的 sales_person 是空的）
   => **不要為了讓 K=0 而去猜**
```

### ② 讀取端一律走 `sales_person_id`

```
⚙️ 母體（AST 掃，已切開三種形狀）：
   下標取值 `row["sales_person"]`   = **26 處**（reports 11／dashboard 5／quotations 4／其餘 6）
   `.get("salesPerson")`             = **6 處**（data_json 那一側）
   ⚠️ 而**不含** `sales_person_id`（那是另一個欄位）與 `sales_persons`（dev_cases 的，另一張表）
```

### 🔴🔴 完整版（2026-09-23）：**逐處判完了，而要改的只有 2 處**

⚙️ 重掃（`ast`，含 `row["sales_person"]` 與 `.get("sales_person"/"salesPerson")`）= **34 處**
（我原本寫 26+6=32 —— 那一次沒有把兩種形狀合起來數）

```
🟢 顯示用 **25**  —— **一個字都不改**
   ⚙️ 其中 18 處是**同一個形狀**：`"salesPerson": row["sales_person"] or ""`
      （打包成 JSON 回前端）
      pdf_gen :2541 :3059 ／ cashier :92 ／ dashboard :234 :750 :817 :828
      quotations :875 :1039 :3826 ／ reports :274 :312 :458 :2448 :3240 :3295 :3375 :3745
   ⚙️ 另 7 處是別的顯示形狀：
      pdf_gen :292（「報　價　人：」）／ quotations :5641（`{"label": "業務"}`）
      reports :193 :194 :560（圖表標籤，`"（未指定）"`）／ reports :2903（放進 txns）
      daily_tasks :1264（保固到期通知信的參數）

🔴 識別用 = **2**  <= **這就是全部要改的**
   helpers/quotations.py:32   `owns = (sp_id == user["id"]) or (sp_id is None and sp_name == user["display_name"])`
   routers/dashboard.py:1052  同一個形狀，註解逐字：「（**尚未回填 sales_person_id 的舊資料**）」

🟡 寫入時解析 = **4**（quotations :1223 :1272 ／ :1467 :1558）
   `sp_name` ＋ `sp_id` 一起存 —— ✅ 已經是對的做法
🟡 已改 = **2**（bonus.py :1134 :1135，`QS1-a` 落地中）
🟡 migration = **1**（db.py:3402）
⚙️ 加總 25 + 2 + 4 + 2 + 1 = **34** ✅
```

> ### 🔑 ⇒ 我原本寫「26 處 B 要逐處判」——
> ### **判完之後只有 2 處，而那兩處都是刻意的相容寫法、註解寫明了原因。**

```
📌 而分類**是機械的**，不是逐行讀出來的：
   `"salesPerson": <expr>` 這個 dict 項的形狀 => 打包給前端 => 顯示用
   ⇒ 18/34 一眼判完，剩下 16 才要讀
🔑 而我當初說「要逐處判」是對的，只是**沒有先找一個判得快的形狀**
☠️ 「逐處判」聽起來很負責，而它讓一件 16 行的事看起來像 34 行的事
```

### ✅ 而那 2 處的收斂條件**可以被數**

```
兩處都是：`sales_person_id IS NULL` 時**退回比對顯示名**
=> 🔑 **相容分支的存在，就是遷移未完成的證據**
⚙️ 而它今天量得出來：26 張報價單裡 `sales_person_id` 為 NULL 的 = **3**
   （`MQ-202607-059`／`-060` 存 username 'test3'；`MQ-EXPFILE-001` 是空字串）
```

> ### ⇒ 處置**不是改那 2 處**，是 §3① 的回填把 NULL 清掉，
> ### 然後**那 2 處自己就沒有作用了**。

```
🔴 而「沒有作用」不等於「可以刪」：
   `MQ-EXPFILE-001` 的 `sales_person` 是**空字串** => 它永遠回填不了
   => 🔴 只要有一張這樣的單，`sales_person_id` 就永遠有 NULL
   ⇒ **相容分支拿不掉**
☠️ 而拿掉它的話，那張單會變成「沒有擁有者」=> superadmin 以外的人看不到
```
📌 ⇒ **不要把「拿掉相容分支」寫進驗收** ——
🔑 它的收斂條件是「**沒有任何一張單的 `sales_person_id` 是 NULL**」，
而那**今天做不到**，也不該為了做到而去猜。

---

🔴 **而這 34 處不是都要改**：
```
顯示用（PDF 抬頭的「業務」、報表的欄位）=> **繼續用 sales_person**（它就是要顯示的名字）
識別用（比對是誰、發獎金給誰、權限過濾）=> **必須走 sales_person_id**
```

> ### 🔑 **判準：這個讀取端是在「印一個名字」還是在「決定一個人」？**

```
☠️ 而兩者在 diff 上長得一模一樣（都是 `row["sales_person"]`）
⇒ **B 要逐處判斷**，本規格不列「要改的那幾處」——
   🔴 我**沒有逐處讀那 26 個呼叫端**（§5 ①）
```

### ②b 🔴 A 問「這個形狀在 `db.py` 還有幾處」—— **答案是一類，而只有 2 個**

```
⚙️ AST 掃 `db.py`：寫入型 SQL 被 try 包住、handler **不 raise 且只記 log／無動作**
   = **11 處**

而它們是**三種東西**：
   ALTER × **8**   `try: ALTER TABLE ADD COLUMN; except: pass`
                   ✅ **冪等慣用法**（欄位已存在就略過）—— **不是缺陷**
   `_m008_fix_legacy_owner_names`（:961）
                   try 在 **for 迴圈裡**，逐筆跳過
                   ⇒ 那是 **`EM7` 的形狀**（迴圈裡跳過一筆而沒有人在數），不是這一族
   ──
   同形狀（**整批回填靜默 no-op**）= **2 處**
      `_m006_hot_columns`（:912）    WHERE deal_tag = '' AND settle_status = ''
      `_m010_sales_person_id`（:1033） WHERE display_name = sales_person
```

> ### ⇒ **是一類，而它只有兩個成員。**

```
🔑 兩個都是**回填**，兩個都是「**條件不成立所以沒動**」——
   而那在 SQL 上**沒有任何痕跡**（不是例外、不是錯誤，是 0 rows affected）
☠️ `_m006` 的條件同樣有風險：`WHERE deal_tag='' AND settle_status=''`
   => 一列若 deal_tag 有值而 settle_status 空，**它整列被跳過**
```

📌 ⇒ 建議處置**兩個一起**（而那是 A 要裁的）：
```
回填類的 migration 一律 `cur = conn.execute(...)` 並 log `cur.rowcount`
⚠️ 而 **ALTER 那 8 個不要動** —— `except: pass` 在那裡是**對的**
   ☠️ 一個「把所有 try/except 都加上 log」的修法會把它們一起改掉，
      而那會在每次啟動時印 8 行「欄位已存在」的雜訊
```

🔑 而 A 指出的那一格成立，**但要用更正後的說法**：
> **`EM9` 的母體是「寫入失敗而沒有失敗分支」——
> 那涵蓋洞 A，而 🔴 `EM9` 不涵蓋洞 B（`UPDATE` 成功而 0 筆匹配）。**
> ☠️ 因為洞 B **沒有失敗**，它不在任何一個「找失敗」的母體裡。

⚙️ 已在 `SPEC-EM9` 補上射程宣告（不擴母體，只寫清楚它不涵蓋什麼）。

---

### ③ 🔴 `bonus` 那一條是**已知要改的**（`BN14` 相依）

```python
# helpers/bonus.py:147  PERSON_SOURCES 的 "sales_person"
# people_for_item() 走 case.get(source) => 拿到**顯示名字串**
```
```
⇒ 改成由 sales_person_id 解析出 users.username
   => bonus_award_lines.username 才裝得到真的 username（`BN14 §6`）
🔑 而那正是 A 裁「bonus_award_lines 現在修」的落點 ——
   **它的上游修法在這裡，而兩者要一起看**
```

#### ✅ 而這讓 `BN14` 的那條界線**自動成立**（A 指出）

```
BN14 §2 的界線：「**綁帳號，不存自由文字**」
=> 若 people_for_item() 改成走 sales_person_id -> users.username，
   那條界線在**來源**就成立了，**不必在獎金那邊各自防**
🔑 〈共用能力下沉〉：**在來源解決，不要在每個消費端解決**
☠️ 而在消費端各自防的代價是：**下一個消費端不會知道要防**
```

---

## §4 驗收（`AC1`）

```
① 後端  migration 兩層比對；跑完印出 N／M／K，且 K 筆逐筆列名
        bonus 那條改走 sales_person_id
② 前端  無異動（顯示用的那些繼續顯示名字）
③ 頁面  ⓐ 跑 migration -> `MQ-202607-059`／`060` 的 sales_person_id 變成 6（test3）
        ⓑ `MQ-EXPFILE-001` **仍然 NULL**，而 log 裡列得出它
           🔑 ⓑ 是負對照 —— 沒有它，「把所有 NULL 都填成某個人」也會綠
        ⓒ 產生一張獎金單 -> `bonus_award_lines.username` 是 **`jeff`** 不是 `黃玉龍`
        ⓓ 報價單 PDF 的「業務」欄**仍然顯示中文名**（§3② 的顯示用那一側）
           ☠️ 少了 ⓓ，「全部改成 username」會讓紙上印出 `jeff`
```

### 🔴 守門

```
✅ 釘：migration 跑完**一定有一筆 log**（不論 K 是不是 0）
   🔑 `_m010` 的教訓：**一個 best-effort 沒有回報它 best 到哪裡**
✅ 釘：`bonus` 那條路**不再讀 `case.get("sales_person")`**
   ⚙️ 正對照 改之前要亮；負對照 `pdf_gen` 的顯示用那幾處**不可以亮**
```

---

## §4b ⏳ 待使用者回來確認

```
① 🔴 **`MQ-EXPFILE-001` 那種「沒有業務」的單要怎麼算**
   我裁：**維持 NULL，不猜**（而相容分支因此永遠拿不掉）
   依據：它的 `sales_person` 是**空字串** —— 那不是「資料遺失」，
        是「這張單本來就沒有業務」（測試單）
   ⚠️ 代價：`sales_person_id IS NULL` 的相容分支**永遠留著**，
        而那 2 處（`helpers/quotations.py:32`／`dashboard.py:1052`）是永久的
   ⇒ **若他要清乾淨**：那要先決定「沒有業務的單算誰的」——
      而那是一個業務規則，不是資料修補
      ☠️ 隨便指一個人的話，那張單的擁有者會變成一個沒有做過那筆生意的人

② ⏳ **`test3` 那兩張（`MQ-202607-059`／`-060`）要不要回填**
   我裁：**要**（第二層 username 比對，§3① 的新增那一半）
   依據：`test3` 是一個**真實存在且 active 的帳號**（users id=6）
   ⚠️ 而它是測試帳號 ⇒ 回填之後那兩張單的擁有者是一個測試帳號
   🔑 而**那是資料的現狀，不是回填造成的** —— 回填只是讓它被正確表達
   ⇒ **若他要把那兩張改成真人**：那是一次資料修正，**與本規格分開做**

③ ✅ **無**其餘 —— §3② 的 34 處分類是查出來的事實
```

---

## §5 我沒查什麼

```
① ✅ ~~那 26 個我沒有逐處讀~~ => **已逐處判完**（見 §3② 的完整版）
   ⚙️ 34 處：顯示 25 ／識別 2 ／寫入時解析 4 ／已改 2 ／migration 1
   🔑 而我當初「不列清單是刻意的」那個理由**仍然成立** ——
      差別是現在這份清單**是讀過的**，而我把「怎麼判的」寫在旁邊
   📌 〈報「查不到」要同句講出查的範圍〉：這一次是
      **報「判完了」要同句講出怎麼判的**
② 正式機的 `sales_person_id` NULL 有幾筆 —— **沒查**（開發機是 3/26）
   ⚠️ 而 `_m010` 是**已經跑過**的 migration ⇒ 正式機的狀態取決於它當時的資料
③ `users.display_name` **改過名**的情況：D 自標
   「只驗證了**現在**的 users 表，沒有查這些單建立當時（2026-07）
     是否有帳號後來被改過 display_name 或刪掉重建」
   🔑 ⇒ 這一格**仍然成立**，而它對 §3① 的第一層比對同樣適用
   ⇒ **回填結果要人工確認過再寫入**，理由不是機率高，
      是**錯了之後沒有任何東西會說**（那是「誰領到錢」的上游）
④ `data_json.salesPersonUsername`（25 張裡 14 張有）與 `sales_person_id` 對不對得起來
   —— **沒比對**。⚠️ 若兩者不一致，要決定以哪一個為準
⑤ `dev_cases.sales_persons`（複數，另一張表）有沒有同樣的問題 —— 沒查
⑥ 🔴 **「回填成功而 0 筆匹配」這個形狀在 `db.py` 以外有幾處** —— 沒查
   ⚠️ §2 只掃了 `db.py`；而 router 裡的 `UPDATE … WHERE` 同樣會 0 筆匹配
   🔑 ⇒ 母體是「**有沒有人讀 rowcount**」，而那與 `EM9`（有沒有失敗分支）**是兩個母體**
```
