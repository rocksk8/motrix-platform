# `SPEC-QS1-a` · `bonus_award_lines.username` 改存帳號

> 座標：`eb953d3`（工作樹：本檔為新增）
> 作者：視窗 A-2 ／ 2026-09-23
> 🔴 **`BN14` 與 `BN18` 的前置**（A 裁：明知道一個欄位正在被修，就不要在那期間多開一個寫入端）

---

## §1 🔴 診斷要更準：**不是「一欄裝錯」，是一個函式的兩個來源回傳兩種識別**

### ⚙️ `people_for_item()` 有兩個來源（`helpers/bonus.py:197`）

```python
PERSON_SOURCES = (
    "sales_person",             # 業務
    "case_stages.assigned_to",  # 各執行階段負責人（JSON 陣列）
)
```

### 🔴 而它們回傳的東西**型別不同**

```
sales_person
   `case.get("sales_person")` => `quotations.sales_person`
   ⚙️ 實測值：'黃玉龍'／'高晟耀'  <= **顯示名**
   🔴 **壞的是這一條**

case_stages.assigned_to
   ⚙️ `case-stage-board.html:499` 指派時送的是 `JSON.stringify({ **username** })`
   ⚙️ :419 篩選用 `it.assignedTo.includes(this.session.**username**)`
   ⚙️ :503 顯示要先轉：`it.assignedTo.map(u => this._userDisplay(u))`
   => **它裝的是帳號**
   ✅ **這一條本來就是對的**
```

> ### ⇒ **同一個函式、兩個來源、兩種識別**，而下游一律當成 username 寫進
> ### `bonus_award_lines.username`。

```
⚙️ 今天的 5 列：username = '高晟耀'／'黃玉龍'×4，
   person_source_snapshot **全部是 'sales_person'**
```

---

## §2 ☠️ 為什麼一直沒有人發現

```
`case_stages.assigned_to` 今天 **100% 是空的**（49 列全空，見 `BN18 §5b`）
=> 那條路**從來沒有跑過**
🔴 而唯一跑過的那條，**正好是壞的那條**
```

> ### 🔑 **一個「兩條路不一致」的缺陷，在只有一條路會跑的時候，看起來像沒有缺陷。**

```
📌 ⇒ 而它會在 `assigned_to` 第一次被填的那天浮出來 ——
   那天 `bonus_award_lines.username` 會**同時有兩種值**，
   ☠️ 而那時候已經有歷史資料，修起來比今天貴
⇒ 這就是「現在修最便宜」的具體內容（不是「因為只有 5 列」）
```

---

## §2b 🔴🔴 補查：**這個缺陷今天就在發生 —— 非管理者一張獎金單都看不到**

### ⚙️ 三個值我都實測過，而它們對不起來

```
helpers/auth.py:214  `_require_user()` 回 `SELECT u.**username**, …`  => **帳號**
routers/bonus.py:475 `me = user.get("username")`                      => 'corbin'
helpers/bonus.py:286 `visible_lines()`：`l.get("username") == username`
                     而 `bonus_award_lines.username` 實測是 **'高晟耀'**
=> '高晟耀' == 'corbin'  =>  **False**
```

### ☠️ 而 `list_awards()` 的下一行把整張單也拿掉

```python
# routers/bonus.py:499
if not manager and not lines:
    continue          # 🔴 與自己無關的單**完全不出現**
```

> ### ⇒ **非 superadmin 打開獎金頁，看到的是空的。**
> ### 🔑 不是「看不到金額」，是**一張單都沒有**。

```
🔴 而 `BN9` 的設計是「非管理者看得到**自己那一列**」——
   `list_awards()` 的 docstring 逐字：
   「⚠️ 非管理者也看得到**單**（否則他不知道自己那一筆屬於哪一案），
     而他只看得到**自己那一列**金額。
     ☠️ 反過來（整張單都不給看）的話，他收到一筆錢而查不到來源。」
=> **那正是今天發生的事**，而它是這個欄位裝錯值的直接後果
```

### 🔑 為什麼沒有人回報

```
⚙️ 今天所有獎金單的 created_by 都是 `jeff`，而 jeff 是 **superadmin**
=> 走的是 `is_admin=True` 那一條 => **從來沒有人走過壞掉的那一條**
📌 與 §2 同一個形狀：**只有一條路會跑的時候，另一條壞了看起來像沒事。**
```

⇒ **驗收要加一項**（§5 ⓕ）——
🔴 而這表示本規格**不只是資料整理，它修好一個使用者看得到的缺陷**。

---

## §3 處置：**只改 `sales_person` 那一支**

### ① `people_for_item()` 把 `sales_person` 解析成帳號

```python
if source == "case_stages.assigned_to":
    …                                  # ✅ 不動，它本來就回 username
else:
    # 🔴 sales_person：解析成帳號，不要用顯示名
    uname = _username_of_sales_person(conn, case)
    if uname:
        people.append(uname)
```

```
⚙️ 解析順序（**先 FK 再退路**）：
   ① `quotations.sales_person_id` -> `users.username`     <= **可靠**
   ② 解不出時：`users.display_name == sales_person AND active=1`  <= **退路**
🔴 而 ② 是 `_m010` 失敗的那條路（`QS1 §2`）——
   同名或改過名就查不到，**而它不會報錯**
⇒ 走到 ② 時要**留一筆 log**，不要靜默
```

### ⚠️ 而 `people_for_item(item, case)` 今天**沒有 `conn`**

```
🔴 它是純函式（只吃 item 與 case）=> 加不了 SQL 查詢
⇒ 兩條路：
   甲 呼叫端先把 username 放進 `case`（例如 `case["sales_person_username"]`）
      ✅ `people_for_item()` 維持純函式 => **測得起來**
      ⚙️ 而呼叫端已經有 conn（`_plan_allocations(conn, …)`）
   乙 改成 `people_for_item(conn, item, case)`
      ⚠️ 它會讓這支函式從「純邏輯」變成「要資料庫」=> 測試都要改
```
📌 **我建議甲**，而理由是結構的：
```
🔑 `people_for_item()` 回答的是「**規則**」（這個項目該發給誰），
   而「這個顯示名對應哪個帳號」是**資料查詢** —— 兩件事
☠️ 合在一起之後，那條規則就再也不能離線驗了
⚙️ 而 `bonus.py:1039` 已經有一支「把案件上的人彙整成 people_for_item 吃得下的形狀」
   => **那裡就是甲的落點**，不是新增一層
```

### ② 🔴 而 `data_json.salesPersonUsername` 可能已經有值

```
⚙️ `QS1 §5④` 記過：25 張裡 **14 張**有 `salesPersonUsername`
🔴 而我**沒有比對過它與 `sales_person_id` 對不對得起來**（`QS1 §5④` 逐字）
⇒ B 動工前要決定以哪一個為準，**而我建議 `sales_person_id`**：
   它是 FK、有 migration 回填過、且 `quotations.py:244` 的擁有者過濾已經在用它
⚠️ 而若兩者不一致，**那本身是一個發現** —— 回報，不要選一個就算了
```

### ③ 🔴 前端**要一起改** —— 而 `JV13` 已經解過這一題

```
⚙️ 實查：`bonus.html:461` 與 `:493` 都是 `x-text="ln.username"`
=> 🔴 改完之後，畫面會從「**黃玉龍**」變成「**jeff**」
☠️ 而它**不會讓任何測試變紅** —— 那是一個使用者看得到的退步
```

> ### 🔑 而 `helpers/voucher.py:326 resolve_display_names()` 的 docstring
> ### 逐字寫著同一件事（`JV13`）：

> `signatures_of()` 的 `by` 存的是 **username**（穩定識別…），
> 而印在紙上／畫面上的要是**顯示名稱**。
> ## 🔴 **修的是輸出這一層，不改存的值**

```
⇒ 照抄那個做法：
   `bonus_award_lines.username`   **存帳號**（本規格在做的）
   `list_awards()` 的回傳值       多帶一個 `displayName`
   `bonus.html:461/493`           改讀 `displayName`
⚠️ 而**不要**在前端自己查 users 清單去對照 ——
   ☠️ 那會變成第二份「帳號 -> 顯示名」的邏輯，而兩份會漂移
```

```
📌 `JV13` docstring 的那一段也一起適用：
   「使用者改名之後，舊的 approval_json 裡**沒有任何欄位需要跟著動**，
     這裡永遠查的是**現在**的顯示名稱」
🔑 ⇒ 那正是把帳號存進去、顯示名查出來的好處，
   而它同時回答了「改名之後獎金單會不會錯」——**不會**
```

⚠️ 而 `resolve_display_names(conn, slots)` 吃的是**簽核格**的結構，
不一定直接套得上 lines ⇒ **B 要看它的簽名**，必要時抽一支共用的。
🔴 而**不要複製一份** —— 兩份查詢遲早會分岔（`EM13` 那一族）。

---

## §4 🔴 Migration：**不依賴「全是測試資料」**（A 裁）

```
⚙️ 今天 `bonus_award_lines` 共 **5 列**，而**不要**寫成「反正只有 5 列」
🔑 我自己踩過：我記「4 列」而第 5 列在我量完之後才出現
   => **B 跑 migration 的那一刻有幾列，今天算不出來**
```

### ⇒ 分來源處理，而**解不出就原值保留**

```
for 每一列 in bonus_award_lines:
    src = person_source_snapshot
    if src == 'case_stages.assigned_to':  => **不動**（本來就是帳號）
    elif src == 'sales_person':
        ① 經該 award 的 quote_no -> quotations.sales_person_id -> users.username
        ② 解不出 -> users.display_name == username AND active=1
        ③ 兩條都解不出 -> 🔴 **原值保留**，並 log 這一列的 id 與值
    else:                                  => **不動**，並 log（未知來源）
```

### 🔴 而跑完**一定要印一筆**，不論結果

```
「bonus_award_lines 回填：經 FK N 筆／經顯示名 M 筆／**未變更 K 筆**」
K > 0 時逐列印出 id 與原值
📌 `QS1 §2` 的教訓：**一個 best-effort backfill 沒有回報它 best 到哪裡**
☠️ 而那一次的失敗形狀是「SQL 成功、0 筆匹配、rowcount 沒有人看」
```

⚠️ **而不要為了讓 K=0 而去猜**：
```
一個解不出的值原樣留著 = **一個誠實的未知**
一個猜出來的值         = **一個看起來正確的錯誤**
🔑 而這一欄的下游是「誰領到錢」
```

### ⚙️ 今天的可解率（**參考，不是驗收條件**）

```
5 列全部兩條路都解得出，**且兩條路答案一致**：
   line1 高晟耀 -> corbin（FK id=2／顯示名 皆同）
   line2~5 黃玉龍 -> jeff（同）
```
🔴 ⇒ **驗收不可以釘「K == 0」** —— 那是今天這份資料的性質，不是修法的性質。
⇒ 釘「**K 筆都有被列出來**」。

---

## §5 驗收（`AC1`）

```
① 後端  people_for_item 的 sales_person 那一支回帳號；
        migration 分來源處理並印出 N／M／K
② 前端  🔴 **要改**（§3③）：`bonus.html:461`／`:493` 從 `ln.username`
        改讀後端新帶的 `displayName`
        ☠️ 不改的話畫面會變成 `jeff` —— 而**沒有任何測試會紅**
③ 頁面  ⓐ 跑 migration -> 5 列的 username 變成 corbin／jeff
        ⓑ 產生一張新的獎金單 -> 新寫入的 username **也是帳號**
           🔑 ⓐ 是歷史、ⓑ 是新資料 —— **兩個都要，少一個就是只修了一半**
        ⓒ 🔴 負對照：造一列 `person_source_snapshot = 'case_stages.assigned_to'`
           且 username 已經是帳號 => migration **不可以動它**
           ☠️ 少了 ⓒ，「全部拿去查 display_name」的實作會把 'jeff' 查成查不到，
              而若它寫了空值，那一列就毀了
        ⓓ 🔴 造一列 username = '查不到這個人' => **原值保留**，且出現在 K 的清單裡
           🔑 少了 ⓓ，「解不出就寫空」或「解不出就跳過而不報」都會綠
        ⓔ 畫面上那幾列**仍然顯示中文名**（前端查出來的），不是 `jeff`
        🔴 ⓕ 用**非 superadmin**（corbin）登入獎金頁（§2b）
           => 改之前：**一張單都看不到**
           => 改之後：看得到 `MQ-202607-028` 那一張，且**只有自己那一列**
           🔑 ⓕ 驗的是 `BN9` 的設計今天有沒有真的成立
           ☠️ 而它**不是**這一件的副作用 —— 它是這一件修好的東西
```

---

## §6 守門

```
✅ 釘：`people_for_item()` 的**每一個來源**都回帳號
   ⚙️ 誘餌：兩個來源各造一組輸入，斷言回傳值都能在 users.username 裡找到
   🔑 釘「每一個來源」而不是「sales_person 那一支」——
      ☠️ 否則 `PERSON_SOURCES` 增加第三個時，同樣不會有人想到
   ⚠️ 而 `PERSON_SOURCES` 今天是 2 個 ⇒ 守門要**逐一走過那個常數**，
      不要寫死兩個 case（寫死的話新來源加進去時它照樣綠）

✅ 釘：`bonus_award_lines.username` 的值**都在 `users.username` 裡**
   🔴 而**要排除 migration 標為「未變更」的那幾列**
   ☠️ 否則 §4 的「原值保留」會讓這道守門永遠紅 =>
      最省力的反應是**把那幾列改掉或刪掉**，而那正是我們刻意不做的事
   ⇒ 排除清單要**明碼列出 id**，並釘住它的長度（反向控制）
```

---

## §7 ⏳ 待使用者回來確認

```
① 🔴 **解不出的那幾列要怎麼處置**
   我裁：**原值保留**（顯示名留在 username 欄裡），並在守門的排除清單裡列名
   依據：A 的指示「解不出就原值保留＋記一筆」；
        且〈降級之後它還是會動〉—— 猜一個值比留一個未知更難發現
   ⇒ **若他選另一個**（例如「解不出的就清空」或「解不出的整批擋住不給產生獎金單」）：
      要改 §4 的第 ③ 步、§5 ⓓ、以及 §6 第二道的排除清單機制

② ⚠️ **`data_json.salesPersonUsername` 與 `sales_person_id` 誰為準**
   我裁：**`sales_person_id`**（FK、有 migration 回填、擁有者過濾已在用）
   依據：`quotations.py:244` 的既有寫法
   ⇒ **若他選另一個**：改 §3① 的解析順序①
   🔴 而**若兩者不一致**，那是一個要回報的發現，不是一個可以自己選的選項
```

---

## §8 我沒查什麼

```
① ✅ **已查，而它成立**：`bonus.html:461`／`:493` 都是 `x-text="ln.username"`
   ⇒ 前端必須一起改（§3③），而 `JV13` 已經確立了做法（存帳號、輸出層換顯示名）
   🔑 這一格原本會變成「規格說前端無異動，而 B 照做 ⇒ 畫面變成 jeff」
② `data_json.salesPersonUsername` 與 `sales_person_id` 的一致性 —— **沒比對**
   （承 `QS1 §5④`，那一格從那時到現在都沒有人做）
③ 正式機的 `bonus_award_lines` 有幾列、解得出幾列 —— **沒查**（不碰正式機）
   🔑 而 §4 的修法**不依賴那個數字** —— 那正是 A 要求的
④ `bonus_award_lines` 以外，還有沒有別的表存了 `people_for_item()` 的輸出 —— 沒查
   ⚠️ 若有，它們有同樣的問題，而本規格沒有涵蓋
⑤ ~~visible_lines 的比對會不會壞~~ => 🔴 **已查，而它今天就是壞的**（見 §2b）
⑥ 正式機上有沒有非 superadmin 實際在用獎金頁 —— 沒查（不碰正式機）
   ⚠️ 若有，§2b 那個缺陷**今天正在發生**而沒有人回報
```
