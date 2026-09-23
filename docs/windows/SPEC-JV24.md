# `SPEC-JV24` · 作廢重開把憑證的來源改寫成「上一張傳票」

> 座標：`4a46c65`（工作樹：本檔為新增）
> 作者：視窗 A-2 ／ 2026-09-23
> 🔴 **與 `JV18`（已計算標記）直接相撞** —— 而 `JV18` 剛出貨（`504e14a`）。

---

## §1 四個發現：**③ 是 ①② 的成因，而 ④ 最重**

```
① 複製附件時，`source_*` 被改寫成指向**舊傳票**
② 連續作廢重開 => 鏈式，要走 N 步才回得到業務來源
③ 🔴 **新舊兩張單之間，`vouchers_all` 上沒有任何欄位把它們連起來**
④ 🔴🔴 **分錄複製只帶 5 欄，丟掉 9 欄**（補查，見 §4b）—— **本件最重的一格**
```

> ### ☠️ 而 ④ 不是「來源追不回去」，是「**新單的內容就少了東西**」。

---

## §2 ③ 先講：**血緣沒有落點，所以它去佔了 provenance 的欄位**

### ⚙️ 重開的 INSERT 逐字（`vouchers.py:695-699`）

```sql
INSERT INTO vouchers_all (voucher_no, voucher_date, category,
 summary, status, created_by, created_at, updated_at)
 VALUES (?,?,?,?, '草稿', ?,?,?)
```

> ### ☠️ **沒有一欄記「這張是從哪一張重開來的」。**

```
`out["new_id"]` 只回給**當下那一次 HTTP 呼叫** => 關掉視窗就沒了
`void_reason` 是**自由文字** => 不是關聯
⇒ 一張**沒有附件**的傳票作廢重開後，
  🔴 **新舊兩張單在資料庫裡完全沒有任何關聯。**
```

### 🔑 而唯一記得的地方，是附件表的 `source_doc_no`

```python
# vouchers.py:1166  _copy_attachments_to()
_insert_attachment(conn, new_id, file_id, att["filename"], rel,
                   size, att["mime"], COPY_SOURCE_TYPE,
                   str(old_id), att["file_id"], who, now)
#                  └ source_type="voucher"
#                              └ source_doc_no=**舊傳票 id**
#                                              └ source_file_id=舊附件 file_id
```
⚙️ 位置參數已複驗：`_insert_attachment` 第 7/8/9 個參數就是
`source_type, source_doc_no, source_file_id`（`vouchers.py:902-904`）。

> ### 🔑 ⇒ **`source_*` 被拿去兼差記血緣，而它只裝得下一件事。**
> ### ⇒ 記了血緣，就記不住「這張憑證原本是從哪個業務文件帶進來的」。

---

## §3 🔴 後果一：`JV18` 的**假陰性** —— 而 `JV18` 正是為了防這件事

### `used_map` 的鍵與過濾（`helpers/voucher_attachments.py:369-376`）

```sql
SELECT va.source_type, va.source_doc_no, va.source_file_id, …
  FROM voucher_attachments va
  JOIN vouchers_all v ON v.id = va.voucher_id
 WHERE va.deleted_at = '' AND **v.voided_at = ''**
   AND va.source_type != '' AND va.source_doc_no != '' AND va.source_file_id != ''
```
```python
key = (row["source_type"], row["source_doc_no"], row["source_file_id"])
…
used_by = used_map.get((st, doc_no, file_id)) or []   # :423，st/doc_no 來自**業務文件**
```

### ☠️ 而作廢重開之後，**兩列都對不上**

```
舊單那一列  鍵 = ("extra_expense", "MQ-202608-007", "abc123")  ✅ 鍵是對的
            🔴 而舊單已作廢 => 被 `v.voided_at = ''` **排除**

新單那一列  🔴 鍵被改寫成 ("voucher", "12", "abc123")
            => 與業務文件查的 ("extra_expense","MQ-202608-007","abc123") **不相等**

⇒ `used_map.get(…)` = 空 => `used = False`
```

> ### 🔴 **那張發票明明躺在一張有效的傳票裡，而畫面說「未使用」。**

```
=> 使用者會**再帶入一次** => **重複入帳**
☠️ 而重複入帳正是 `JV18` 要防的事 —— `case_attachments()` 的 docstring 逐字：
   「**`usedBy` 列出全部，不是只列最近一張** —— 只列最近一張會把重複入帳
     的那一筆藏起來，而重複入帳正是這個功能要防的事。」
🔑 ⇒ 同一支函式為了防重複入帳而特意多列一份，
     而這條路**繞過了整個標記**。
```

### ⚠️ 而這是**推的不是量的** —— 射程要講清楚

```
⚙️ 開發機實測：`voucher_attachments` 共 **1 列**，`source_type` 是**空字串**
              作廢過的傳票 **1 張**（`20260923-001-R1`，理由 "test"）
              `source_type='voucher'` 的列 = **0**
🔴 ⇒ `_copy_attachments_to()` **從來沒有真的跑出過一列**
⇒ 上面的結論是從**兩個讀到的事實**推出來的（參數順序 ＋ used_map 的鍵），
  **不是從資料觀察到的**
🔑 而它可以被證偽：B 造一次「帶入憑證 -> 過帳 -> 作廢重開」就看得到
```

---

## §4 後果二：鏈式，而**中間每一節都是作廢的**

```
原始文件 -> 傳票A -> （作廢重開）傳票B -> （再作廢重開）傳票C
傳票C 的 source_doc_no = **B 的 id**
傳票B 的 source_doc_no = **A 的 id**，而 B 已作廢
傳票A 的 source_* = 業務文件 ✅，而 A 已作廢
```
```
=> 要回到業務文件，得走 N 步，而**中間每一節都在 used_map 的排除條件裡**
⚠️ 而沒有任何欄位說「這條鏈有多長」⇒ 也沒有人知道自己走到哪
```

---

## §4b 🔴🔴 補查：分錄複製**丟掉九個欄位**

### ⚙️ `voucher_lines` 共 **15 欄**，而複製只寫 **6 欄**

```python
# vouchers.py:707-711
"INSERT INTO voucher_lines (voucher_id, line_no,"
" account_code, summary, debit, credit) VALUES (?,?,?,?,?,?)"
```

```
🔴 沒有帶過去的 9 欄：
   account_name_snapshot       **科目名稱快照**（過帳時凍結的那個名字）
   dept_code                   部門
   counterparty                往來對象
   source_type                 🔴 **分錄層的來源型別**
   source_id                   🔴 **分錄層的來源 id**
   source_amount_snapshot      🔴 **來源金額快照**
   summary_template_id         摘要範本
   summary_template_version    摘要範本版本
   （id 不算 —— 那本來就該重新產生）
```

> ### ☠️ **作廢重開產生的新傳票，在畫面上看起來是完整的一張。**
> ### 🔑 而它丟掉了部門、往來對象、凍結的科目名稱，以及**整個分錄層的來源追溯**。

```
📌 〈降級之後它還是會動〉的教科書實例：
   **最危險的結果不是失敗，是「成功且降低了資料完整度」** ——
   ☠️ 壞掉會被報修，**降級不會**。
```

### 🔑 而 ④ 與 ①③ 是**同一個成因**

```
①  附件層：source_* 被改寫    => 來源**變成錯的**
④  分錄層：source_* 沒被帶    => 來源**變成空的**
⇒ 兩層都在「複製一張傳票」這個動作裡，而**兩層的來源都沒活下來**
🔑 ⇒ 這一件的判準是一句話：
     **「作廢重開＝換一張單，不是換一批資料」** ——
     除了 id／單號／狀態／建立資訊，其餘一律原樣帶過去。
```

⚠️ 而**判準要指出例外**，否則它會被機械套用：
```
不可以原樣帶的：id（新的）／voucher_id（新的）／voucher_no（新號）
                status（一律回「草稿」）／created_by／created_at／updated_at
                posted_*／voided_*／submitted_*／checked_*／manager_*／approval_json
🔑 判準：**「這一欄描述的是憑證內容，還是那一張單的處理過程？」**
   內容 => 帶；過程 => 不帶（新單要重走一次流程）
☠️ 而 `account_name_snapshot` 看起來像「過程」（它是過帳時凍結的）——
   **它是內容**：它記的是「當時這個科目叫什麼」，那不會因為換一張單而改變
```

---

## §5 處置：**血緣與來源分開放，兩個都要留**

### ① 複製時**保留原始 `source_*`**（本件的主體）

```python
# vouchers.py:1166
_insert_attachment(conn, new_id, file_id, att["filename"], rel,
                   size, att["mime"],
                   att["source_type"], att["source_doc_no"],   # 🔴 原樣帶過去
                   att["source_file_id"], who, now)
```
```
✅ 這樣 used_map 的鍵就**跟著憑證走**，不管它被搬過幾張傳票
🔑 判準：**`source_*` 回答「這份憑證是從哪個業務文件來的」** ——
   那個答案**不會因為傳票作廢而改變**
```

⚠️ 而**直接上傳**的那些 `source_*` 是空字串：
```
複製時原樣帶過去 => 仍然是空字串 => 仍然被 used_map 的 `!= ''` 排除
✅ 那是**對的** —— 它本來就沒有業務來源可以標
☠️ 不要為了讓它「有值」而填 COPY_SOURCE_TYPE
   （`voucher_attachments.py:360` 逐字警告過：三個欄位要一起比對，
     否則「一個從未被帶入的候選憑證被誤標成已使用——這是**假的紅字**」）
```

### ①b 🔴 分錄複製要帶**全部內容欄位**（§4b）

```python
# vouchers.py:707  改成把 15 欄裡的「內容欄」全帶
"INSERT INTO voucher_lines (voucher_id, line_no, account_code,"
" account_name_snapshot, summary, summary_template_id,"
" summary_template_version, debit, credit, dept_code,"
" source_type, source_id, source_amount_snapshot, counterparty)"
" VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
```
```
✅ 只有 `id` 與 `voucher_id` 是新的，其餘 13 欄原樣
🔑 而**不要寫成 `SELECT *` 再改兩欄** ——
   ☠️ 那樣日後加欄位會自動帶過去，聽起來很好，
      而它**同時會把不該帶的（若哪天加了 posted 類欄位）也帶過去**
   ⇒ 明著列欄名，加欄位時**強迫下一個人做一次判斷**
```

⚠️ 而 `voucher_lines` 的欄位清單**會長**：
```
🔴 守門要釘「**這支 INSERT 的欄數 ＝ 表的欄數 − 2**」（扣 id／voucher_id）
   ⇒ 加欄位而沒有在這裡做決定時，**它會紅**
📌 〈守門要驗「有沒有人做過決定」〉—— 不是驗決定得對不對
☠️ 而若某一欄**刻意不帶**，就要登記在一個明碼的排除清單裡，
   ⇒ 配反向控制：排除清單的長度也要釘死，否則可以靠「全部排除」變綠
```

### ② 血緣要有**自己的落點** —— 🔴 而這一格要 A 裁

```
現況：`vouchers_all.**supersedes_no**` TEXT NOT NULL DEFAULT ''
      db.py:4855 的註解逐字：「**本張取代了哪一張**」
⚙️ 而它**從來沒有被寫過，也從來沒有被讀過**：
   全 repo 只有 3 處提到它（schema 定義 ＋ 兩句 docstring），
   **0 個 INSERT／UPDATE／SELECT，前端 0 處**
```

> ### ☠️ 而 `helpers/voucher.py:24-26` 那句 docstring 逐字說：
> ### 「作廢…落在 `voided_at`／`voided_by`／`void_reason`／**`supersedes_no`** 四個欄位上。」
> ### 🔑 **第四個從來沒有被寫入過** —— 那句話有四分之一是假的。

```
📌 這與 `UP1 §2` 是**同一種東西**，今天第二次：
   一句寫死的、說明設計的散文，而**沒有任何東西在維護它的真假**
⚠️ 而這一句的性質稍有不同：它說的**不是錯的事實，是沒做完的計畫**
   => `supersedes_no` 是一個「**意圖存在、實作缺席**」的欄位
```

#### ⇒ 兩條路（要 A 裁）

```
甲 **用 `supersedes_no`**（新單寫舊單的 voucher_no）
   ✅ 欄位已存在、註解語意相符、且沒有任何既有用途會衝突
   ✅ 它同時**讓那句 docstring 變成真的**
   ⚠️ 而「退回升版」日後若要用它，兩者會撞
      🔑 而目前退回升版走的是**單號後綴**（`next_revision_no()` -> `-R1`），
         `supersedes_no` **不在它的路徑上**（已查）

乙 **另加一欄**（`reopened_from_id`）
   ✅ 語意最乾淨、不與任何未來用途相撞
   ⚠️ 而它讓 `supersedes_no` **繼續是一個沒有人用的欄位** ——
      ☠️ 那句 docstring 也就**繼續是假的**，而下一個人還是會相信它
```

📌 **我傾向甲**，理由不是成本：
🔑 **乙留下一個「意圖存在、實作缺席」的欄位，而那正是今天已經出過兩次事的形狀。**
⚠️ 而若 A 裁乙，那**同一輪要把那句 docstring 改掉**（寫成三個欄位＋註明第四個未實作），
☠️ 否則這一件修完之後，那句假話**還在原地**。

---

## §6 驗收（`AC1`）

```
① 後端  複製時保留原始 source_*；血緣寫進 §5② 裁定的落點
② 前端  無異動（`used` 這三個欄位前端已經在讀了 —— `JV18` 做的）
③ 頁面  ⓐ 案件裡帶一張發票進傳票 -> 過帳
           => 候選憑證清單上那一筆顯示「**已計算**」（紅字）
        ⓑ 把那張傳票**作廢重開**
           => 🔴 那一筆**仍然顯示「已計算」**，且 `usedBy` 指向**新單**
           🔑 ⓑ 是這一件的核心 —— 改之前它會變回「未使用」
        ⓒ **再**作廢重開一次（鏈式第二節）=> 仍然「已計算」，指向最新那一張
           ☠️ 少了 ⓒ，「只保留一層」的修法也會綠
        ⓓ 負對照：一張**直接上傳**的附件（`source_*` 全空）
           => 作廢重開之後**仍然不出現在任何候選清單的已計算標記上**
           🔑 少了 ⓓ，「複製時一律填 COPY_SOURCE_TYPE」會製造**假的紅字**
        ⓔ 沒有附件的傳票作廢重開 => 新舊單之間**查得到關聯**（§5②）
        🔴 ⓕ **分錄層**（§4b）：造一張分錄**九個欄位都有值**的傳票
           （至少 dept_code／counterparty／account_name_snapshot／
             source_type／source_id／source_amount_snapshot 六個）
           -> 作廢重開 -> 逐欄比對新舊兩張的分錄
           => **13 個內容欄一字不差**
           ☠️ 少了「先把值填出來」這一步，測試會在**全部是空字串**上比對成功
              => 那是假綠燈（空 == 空）
           🔑 ⇒ 驗收的第一步是**造資料**，不是跑流程
```

---

## §7 守門

```
✅ 釘：`_copy_attachments_to()` 寫入的 `source_type` **不可以是 `"voucher"`**
   🔑 釘「**不可以是什麼**」而不是「應該是什麼」——
      後者在來源型別增加時會誤報（`SOURCE_TYPES` 現在 9 種，會長）
⚙️ 誘餌（合成，不留真缺陷當對照）：
   A  複製一筆 source_type="extra_expense" 的附件 -> 新列必須**還是** extra_expense
   B  複製一筆 source_type="" 的附件           -> 新列必須**還是** ""（不可以被填值）
   C  一筆直接寫入 source_type="voucher" 的列   -> **必須亮**

✅ 釘：`COPY_SOURCE_TYPE` 這個常數**若不再被使用就要刪掉**
   ☠️ 留著的話下一個人會以為它是現行設計
   ⚠️ 而它今天在 `SOURCE_TYPES` 之外自成一格，**刪它不影響那 9 種**
```

---

## §8 我沒查什麼

```
① 🔴 **開發機上這條路 0 列** => §3 的後果是**推的不是量的**（已在 §3 標明）
   ⇒ B 實作前先造一次那個流程，**確認它現在真的是壞的**
   📌 〈新回歸測試一定要先證明它會紅〉
② 正式機有沒有 `source_type='voucher'` 的列 —— **沒查**（不碰正式機）
   ⚠️ 若有，那些列的原始來源**已經遺失** => 要不要回填是另一個決定
   🔑 而回填**做得到**：舊單那一列還在（作廢不刪列），順著 source_doc_no 走得回去
③ ✅ **已查，而答案讓嚴重度往上不是往下**
   `resolve_picks()`（`voucher_attachments.py:201`）擋四件事：
   來源型別不是會計憑證／不支援的來源／缺來源編號或檔案編號／檔案不存在
   🔴 **它不擋「已經被帶入過」** => 重複帶入是**被允許的**
   ⇒ `JV18` 的紅字標記是**唯一的防線**，而它在顯示層
   ☠️ ⇒ 本件讓那道唯一的防線失效 —— 我原本寫「若它會擋，後果更重」，
      **方向反了**：正因為它不擋，後果才更重
④ 前端拿 `usedBy` 之後怎麼顯示鏈式（一筆憑證出現在多張傳票）—— 沒看
⑤ ✅ **已查，而它變成本件最重的一格** —— 見 §4b（15 欄只帶 6 欄）
   📌 我原本把它寫成「沒查」的第五項 ——
   🔑 而它三分鐘就查得出來，且**改變了整件事的主體**
   ⇒ 〈量它不等於修它〉：**量通常唯讀、三分鐘、不跟人打架**
⑥ 🔴 §4b 那 9 欄裡，**哪幾欄今天真的有值** —— **沒查**
   ⚠️ 若開發機上它們全是空的，那 `④` 在**今天**不會有可見症狀
   ☠️ 而那**不會**讓它變成不用修 —— 它會讓「證明它壞了」變難
   ⇒ B 實作前要先把那幾欄填出值來，否則測試會是假綠燈
⑦ 附件的 `SOURCE_TYPES` 有 9 種，而 §7 的誘餌只覆蓋 2 種 —— 刻意的
   （釘「不可以是 voucher」不必逐種列舉），但**我沒有驗過那 9 種都會被保留**
```
