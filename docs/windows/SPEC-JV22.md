# `SPEC-JV22` · 傳票退回要留長期記憶

> 座標：`65fa488`（工作樹：本檔為新增）
> 作者：視窗 A-2 ／ 2026-09-23
> 使用者原話：
> 「傳票如果有退回，需顯示**上次退回**跟**這次編修的內容**，**長期記憶，這個不能刪除**」

---

## §1 🔴 現況：**兩半都已經有記錄，而兩半都沒有出口**

### 【上次退回】記在 `audit_log`，而傳票頁沒有讀它

```python
# routers/vouchers.py:654 附近（send_back_voucher）
_audit(_tok(authorization), "voucher.send_back", "vouchers",
       str(voucher_id), "傳票退回：%s（%s）" % (new_no, body.get("reason") or "未填原因"))
```
⚠️ 而它是一段**組好的字串**，不是結構化欄位 ⇒ 要顯示得反向解析。

### 【這次編修的內容】🔴 **A 的描述要更正 —— 它有記錄**

> A 寫：「**完全沒有記錄**」。

**實查：**
```python
# routers/vouchers.py:872  PUT /{voucher_id}
append_edit_log(conn, voucher_id, _user_name(user),
                changes + line_changes,          # <= **欄位級 ＋ 分錄級**
                table="voucher_edit_log", changed_at=now)

# routers/vouchers.py:1069  DELETE 附件
append_edit_log(conn, voucher_id, _user_name(user),
                [{"field": "attachment", "from": att.get("filename"), "to": ""}], …)
```

```
⚙️ 而讀取端 = **0**
   grep `edit_log`：vouchers.py 只有 import ＋ 兩個寫入點，**沒有任何 GET**
   frontend/pages/voucher.html ／ frontend/js/voucher.js = **0 處**
```

> ### 🔑 兩半是**同一個形狀**：**訊號在，消費端沒有入口。**
> ### 📌 〈缺欄位≠缺訊號〉 —— 而這一次是**兩次**。

---

## §2 🔑 基礎設施**已經全部存在**（今天第八次「已經有人解過這個問題」）

```
helpers/edit_log.py          `append_edit_log()`
   ☠️ **缺「改前值」就寫不進去**（`MissingOldValue`）
      docstring 逐字：「少了改前值的那一列…有時間、有人、有欄位名，
      **而回答不出『原本是什麼』** —— 那正是逐筆紀錄唯一要回答的問題」
   RETENTION_VALUES = ("permanent", "term")     <= **保留期已經是一個概念**
   EDIT_LOG_TABLES  = {voucher_edit_log: voucher_id, bonus_award_edit_log: award_id}

db.py:4913   CREATE TABLE voucher_edit_log(id, voucher_id, changed_by,
                                           changed_at, changes_json, **retention**)
archive.py:1639  逐字：「**編寫紀錄是憑證的一部分，不是軌跡**」
                 ⇒ 備份時它與 audit_log **不同群**
```

> ### ⇒ `JV22` **不加表、不加欄位、不動 migration。**
> ### 它要做的是：**補一個寫入點 ＋ 補一個讀取端 ＋ 補一個畫面區。**

---

## §2b 🔴🔴 **「長期記憶」與既有的 730 天清理直接衝突**（D 查到）

```python
# archive.py:1086  —— **已排程**（:1937 呼叫）
def _prune_audit_log(keep_days: int = 730) -> None:
    cutoff = (datetime.now() - timedelta(days=730)).isoformat()
    cur = conn.execute("DELETE FROM audit_log WHERE at < ?", (cutoff,))   # <= **真的 DELETE**
```

```
而**退回原因目前只存在 audit_log** => **兩年後它會被刪掉**
```

> ### ☠️ 使用者說「**長期記憶，這個不能刪除**」，而它兩年後會被刪掉。

### ⚠️ 而那支函式的 docstring 有一句要處理

> 「Daily backup exports first, **so nothing is lost**.」

```
✅ 對「資料有沒有消失」而言那句話是對的 —— 每日備份先匯出
🔴 而對使用者要的那件事**不成立**：
   **備份檔裡有 ≠ 他在畫面上查得到**
🔑 「長期記憶」是一個**查得到**的承諾，不是一個**存在過**的承諾
```

### ✅ ⇒ 裁定（A）：**退回原因必須也寫進 `voucher_edit_log`**

```
❌ 不可以只靠 audit_log
✅ 落點 = voucher_edit_log（**沒有任何清理程式碰它**）
```
📌 〈計數器要有落點〉的變形：
> **一個「永久保存」的承諾，要指出它保存在哪一張不會被清的表。**

---

## §3 ① 「不能刪除」——**三個層次，而現況已經滿足兩個**

```
① 不提供刪除入口   ✅ 今天就沒有（畫面上沒有，端點也沒有）
② 端點拒絕刪除     🔑 **不要做一支「拒絕」的端點** —— **根本不要有那支端點**
                      `EDIT_LOG_TABLES` 只被 `append_edit_log()` 用，**沒有 delete**
③ 作廢後仍保留     ✅ `void_voucher` 只 UPDATE `voided_at`，**不碰 edit_log**
```

### ✅ 而 A 問的「作廢的傳票它的退回記錄要不要留」—— **要留，而理由在碼裡**

```
pdf_gen.py 那一段（JV5）逐字：
   「已作廢的傳票**也印得出來** —— 一份憑證法定保存 5 年，
     而**作廢單正是稽核最需要看到的那一種**」
🔑 ⇒ 作廢不是「這張單不存在了」，是「這張單不生效了」
   => 它的編修史**正是事後要查的那一份**
```

### 🔴 而「不能刪除」要寫成**守門**，不是寫成一句話

```
### 🔴 而 A 裁：**要加資料庫層的 TRIGGER**，不只靠「沒有人寫」

D 的原話：
> 「這是『**沒有人寫**』的保護，不是資料庫層擋下來的保護 ——
> 全庫只有 5 個 TRIGGER，**全部只保護 `account_items`**（`RAISE(ABORT)`）。
> 若之後有人比照 `_prune_audit_log()` 幫 `voucher_edit_log` 寫一支保留期清理，
> **今天沒有任何機制擋得住**。」

```
⇒ 照 `account_items` 那 5 個的形狀加 TRIGGER（BEFORE DELETE -> RAISE(ABORT)）
   📌 **今天第十次「這個系統裡已經有人解過這個問題」**
🔑 理由：使用者說「不能刪除」，而「**沒有人寫刪除**」與「**刪不掉**」是兩件事
   📌 〈守門被拿掉≠規則被解除〉的鏡像：**規則存在 ≠ 有東西在擋**
🔴 而這會動 `db.py`（**鎖定檔**）⇒ **動前要宣告**
⚠️ 而 TRIGGER 要**同時保護 `bonus_award_edit_log`** —— 同形狀的另一張
```

⚙️ 釘：`backend/**` 裡沒有任何 `DELETE FROM voucher_edit_log`／
      `DELETE FROM bonus_award_edit_log`
      🔑 而這一道與 TRIGGER **兩個都要**：
         掃原始碼擋「有人寫」，TRIGGER 擋「寫了會成功」
   ⚠️ 判準要含 `bonus_award_edit_log` —— **它是同形狀的另一張**，
      而「只擋傳票那張」會在獎金單那邊留一個洞
🎣 誘餌 自己留一句合成的 DELETE（註解掉的不算 —— 要能被掃到）
```

⚠️ **而 `archive.py` 的清理邏輯要一起看**：
```
archive.py:1598 的註解逐字：「`voucher_edit_log` 看起來像『紀錄類』（audit_log 那一群）…」
🔑 ⇒ 有人已經在那裡**差一點把它歸錯群** ——
   而歸錯群的後果就是**被當成軌跡清掉**
⇒ 守門要再釘一條：它在 `archive.py` 的分群裡**屬於憑證不屬於軌跡**
```

---

## §4 ② 記在哪 ＋ ③ 粒度 —— **兩題的答案都是「現況已經對了」**

### ② `voucher_edit_log`（既有）

```
❌ 不加 vouchers_all 欄位  —— 一張單會退回多次，欄位裝不下
❌ 不加新表               —— 已經有一張同形狀的
✅ 用既有的 voucher_edit_log
⇒ **不動 migration**（而 `db.py` 是鎖定檔，這一點省掉一次宣告）
```

### ③ 粒度：**欄位級**，而附件只記檔名

```
既有格式  [{"field": …, "from": …, "to": …}, …]
PUT 已經在寫「欄位級 ＋ 分錄級」（`changes + line_changes`）
附件刪除  :1069 寫 `{"field": "attachment", "from": 檔名, "to": ""}`
          ✅ **不帶二進位** —— A 擔心的那一格現況已經避開了
```

☠️ **不要改成整包快照**：
```
傳票有附件 => 整包快照會把**檔案內容**帶進 changes_json
   => 一張有 5 個附件的傳票，每改一次就複製一份
🔑 而 `edit_log.py` 的規則（缺改前值就寫不進去）在整包快照上**沒有意義**
   —— 它要的是「這個欄位原本是什麼」，不是「整張單原本長什麼樣」
```

### 🔴 缺口一（D 查到）：**附件「新增」留不住動過什麼**

```
附件**刪除**  voucher_edit_log（field="attachment", from=檔名, to=""）＋ audit_log（含檔名）
附件**新增**  vouchers.py:1001  _audit(…, "傳票附件 **+%d**" % added)
              => **只有數量，連檔名都沒有**，而 voucher_edit_log **一列都沒寫**
```

> ### ☠️ **刪得掉的留得住，加上去的留不住。**
> ### 而使用者要的正是「這次編修的內容」。

⇒ 新增端點比照刪除端點補：
```python
append_edit_log(conn, voucher_id, _user_name(user),
                [{"field": "attachment", "from": "", "to": meta["filename"]}
                 for meta in 新增的每一筆],
                table="voucher_edit_log", changed_at=now)
```
⚠️ **多筆併成一批寫一列** —— 維持「一次操作一列」（與 PUT 的
`changes + line_changes` 合併寫一列是同一條慣例）。

---

## §5 ④ 🔴 退回會換單號 —— **而傳票這邊沒有 `QN1` 的問題**

```
傳票   send_back 走 `next_revision_no()`：**同一個 voucher_id，換 voucher_no**
       （`vouchers.py:650` UPDATE vouchers_all SET status='草稿', voucher_no=? …）
       而 voucher_edit_log 的外鍵是 **voucher_id（整數）**
       ⇒ **換號完全不影響它**  ✅

報價單 reject 走 `_next_revision_no()`：**同一列，換 quote_no（主鍵字串）**
       而下游 17 張表存的是 **quote_no（字串）**
       ⇒ **全部變孤兒**（`SPEC-QN1`）
```

> ### 🔑 **同一個動作，兩種後果 —— 差別只在「下游存的是 id 還是字串」。**

📌 ⇒ `JV22` 這一格**什麼都不用做**，而**理由要寫下來**：
☠️ 否則下一個人看到「退回會換號」會以為這裡也有 `QN1` 那個問題，去「修」一個不存在的東西。

### ✅ 而 D 補的一句要原文寫進來

```
send_back ／ update ／ 附件刪除 全部 _audit(…, str(**voucher_id**), …)
voucher_edit_log 外鍵也是 voucher_id REFERENCES vouchers_all(id)
⇒ 不管升版幾次，`WHERE voucher_id=X ORDER BY at` 就串得起來
```

> ### **記錄掛在穩定 ID 上，不隨升版漂移。**

🔑 A 的理由：**否則下一個人會重新擔心一次，而重新擔心的成本比寫一句話高。**

### ⚠️ 而有一格要補：`send_back` **現在不寫 edit_log**

```
實查 send_back_voucher（:594-654）：只有 UPDATE ＋ `_audit`，**沒有 append_edit_log**
⇒ 「上次退回」要成為結構化紀錄，**這一支要補寫一筆**：
   [{"field": "status", "from": 原狀態, "to": "草稿"},
    {"field": "退回原因", "from": "", "to": reason},
    {"field": "voucher_no", "from": 舊號, "to": 新號}]
⚠️ 而 `reason` 為空時 `append_edit_log` 會不會被 `MissingOldValue` 擋掉 ——
   🔑 「退回原因」的 `from` 本來就是空的（它是新增不是修改）
   ⇒ **B 開工前要先讀 `edit_log.py` 的驗證規則**，確認空 `from` 是否合法
   🔴 若不合法，這一筆要換一種寫法，**不要為此放寬規則**
      ☠️ 放寬「缺改前值」那條規則 = 把整套紀錄的唯一保證拆掉
```

---

## §6 ⑤ 顯示：**成對，而不是流水帳**

使用者要的是「**上次退回**跟**這次編修的內容**」⇒ **一組對照**。

```
┌ 上次退回 ────────────────────────────┐
│ 2026-09-23 14:20  由 王小明 退回        │
│ 原因：科目代號選錯                       │
│ 單號 VC-2026-0012 → VC-2026-0012-R1     │
├ 這次編修 ────────────────────────────┤
│ 借方科目  5101 → 5201                   │
│ 摘要      「文具」→「辦公用品」           │
│ 分錄      3 列 → 4 列                   │
└──────────────────────────────────────┘
```

```
「上次退回」  = 最近一筆 field='status' 且 to='草稿' 的 edit_log
「這次編修」  = **那一筆之後**的所有 edit_log 合併
```

### ⚠️ 退回過很多次怎麼辦

```
預設顯示**最近一組**（上次退回 ＋ 其後的編修）
而「更早的」要**收合可展開**，不是不顯示
🔑 使用者說「長期記憶」⇒ 舊的不能消失，**而預設不要淹沒最近那一組**
```

### 🔴 **這一區在畫面上不可以有任何編輯或刪除控制項**

```
☠️ 一個看起來像備註欄的東西，**下一個人會很自然地加上編輯功能**
⇒ 版面上：沒有 <input>、沒有 <textarea>、沒有「刪除」「編輯」按鈕
⚙️ 配一道題：該區塊的 DOM 裡 `input`／`textarea`／`contenteditable` = **0**
   ⚠️ 而判準要綁**那個區塊**不是整頁（整頁當然有 input）
```

---

## §7 驗收（`AC1`）

```
① 後端  send_back 補寫一筆結構化 edit_log
        新增 GET /api/vouchers/{id}/edit-log（⚠️ **靜態路徑要宣告在
        `@router.get("/{voucher_id}")` 之前**，否則回 422 不是 404）
        閘門 `_require_voucher_access`（與其餘 14 支一致）
② 前端  傳票頁新增「退回與編修」區，成對顯示，**無任何編輯／刪除控制項**
③ 頁面  ⓐ 送審 -> 退回（填原因）-> 改兩個欄位 -> 重新開這張單
           => 看得到原因、看得到那兩個欄位的 from/to
        ⓑ **再退回一次**再改 -> 預設顯示最近那一組，舊的收合可展開
        ⓒ 把這張單**作廢** -> 退回與編修**仍然看得到**
           🔑 ⓒ 是 §3 的驗收
        ⓓ 那一區的 DOM 裡沒有 input／textarea／contenteditable
        ⓔ 新端點**不回 422**
```

---

## §8 我沒查什麼

```
① `append_edit_log()` 對「`from` 為空」的驗證規則 —— §5 那一格，**B 要先讀**
② `audit_log` 那一半要不要**一起顯示**（它有的東西 edit_log 沒有嗎？）
   ⚠️ 我判斷 send_back 補寫之後就不需要，**而沒有逐欄比對兩邊記了什麼**
③ 舊資料：現有的 `voucher_edit_log` 只有 **1 列** ——
   ⇒ ⓑ 那題要**自己造**多次退回的資料，現有資料驗不到
④ `vouchers_all.custom_fields` **有 schema、零寫入點、連建立時都沒寫**（D 查）
   📌 D 標「**不算會被編修，是尚未串接**」⇒ **本規格不涵蓋它**
   🔴 而這一句要留著 —— 否則下一個人會以為是漏做的
⑤ `bonus_award_edit_log` 有沒有同樣的「有寫無讀」——**沒查**
   🔑 而它與 `voucher_edit_log` 是同形狀 ⇒ **很可能一樣**
   ⇒ 若是，那是 `BN` 那一側的同一件事，建議另開編號
⑤ `retention` 欄位現在寫進去的是什麼值（`term` 還是 `permanent`），
   以及**誰會依它做事** —— 沒查
   ⚠️ 而「不能刪除」若靠它，那就要先回答「term 到期之後呢」
```
