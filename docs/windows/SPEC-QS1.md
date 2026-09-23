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

### ⚠️ 而它**靜默失敗**

```python
try:
    conn.execute(""" UPDATE … """)
except Exception as e:
    logger.warning("m010 backfill failed: %s", e)
```
```
☠️ 而這裡連例外都沒有 —— SQL 跑成功了，只是**那兩列一筆都沒更新到**
   => `UPDATE` 的 rowcount 沒有人看
🔑 ⇒ **一個「best-effort backfill」沒有回報它 best 到哪裡。**
📌 〈迴圈裡跳過一筆而沒有人在數〉的 migration 版：
   **它不是跳過，它是「條件不成立所以沒動」，而那在 SQL 上沒有任何痕跡。**
```

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

⚠️ **而要印出結果，不可以靜默**：
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

🔴 **而這 26 處不是都要改**：
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

🔑 而 A 指出的那一格成立：
> **那是 `EM9`（寫入失敗不可以是靜默的）在 migration 上的版本，
> 而 `EM9` 的母體只掃了前端與 router，沒有掃 migration。**

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

## §5 我沒查什麼

```
① 🔴 **那 26 個 `row["sales_person"]` 我沒有逐處讀** ——
   「顯示用 vs 識別用」的分類**是判準不是清單**，B 要逐處判
   ⚠️ 而我**不列清單**是刻意的：列了一份沒讀過的清單，
      比說「要逐處判」更容易被當成已經判完
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
```
