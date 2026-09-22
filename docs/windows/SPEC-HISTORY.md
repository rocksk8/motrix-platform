# 五模組操作歷史 `FN4` —— **施工圖**
> A-2 2026-09-23 02:0x ／ 落點 `docs/windows/SPEC-HISTORY.md` ／ 誰在等：**B**
> 🔴 無修訂層。判準：不得出現任何一個被推翻的字。

---
# 一、使用者原話
```
「出納、財務、獎金計算、匯出傳票這些都是獨立功能，並且有**獨立紀錄**」
「相關紀錄、權限發放、歷史紀錄、預覽匯出這些功能都要**精準**，這是財務」
```

# 二、既有現況（實測，貼行號）
```
③ 全域稽核  db.py:466-477  audit_log(id, at, user_id, username, display_name,
                            action, target_type, target_id, target_label, detail)
            helpers/audit.py:92  def _audit(...)
            **34 支 router 在寫**／開發機現有 **2,267 筆**
            前五種：case.update 723／auth.login 197／auth.logout 126／
                    **quotation.export_pdf 117**／quotation.update 80
② 逐筆紀錄  db.py:1129  daily_task_edit_log(task_id, changed_by, changed_at, changes_json)
                        ＋ INDEX (task_id, changed_at)
① 執行歷史  cashier.py:150  _execution_history() ⇒ **對業務表的日期查詢，沒有專屬表**
```
🔑 **`quotation.export_pdf` 117 筆 ⇒ 「誰匯出過」既有機制已經在記** —— 不必新建。

---
# 三、🔴 形狀定案：**②各模組一張，③沿用既有，①不新建表**

## 3.1 ② 逐筆編寫紀錄 ⇒ **只有兩張：傳票與獎金**
```
使用者原話（STATE:25063 逐字）列的是**四個**：出納／財務／獎金計算／匯出傳票
（而「財務報表歸財務報表」被明著排除）
🔴 而 ②這一層**不是每個模組都需要**：
   出納 cashier.py       讀 2 張，**沒有業務單據的逐筆修改**
   營運報表 reports.py   **有 8 處寫入**（B 複核）——
                         而那 8 處寫的是 **audit_log（③那一層）與設定**，
                         **不是業務單據的逐筆修改**
   ⇒ ⇒ 它們要的是 ①執行歷史 ＋ ③audit_log，**沒有 ② 可記**
⚠️ **不要寫成「reports.py 不寫」** —— 它有寫，
   而下一個人查到那 8 處會以為這個結論也錯了。
```
```sql
-- **兩張**同形狀：voucher / bonus_award
CREATE TABLE <module>_edit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id     INTEGER NOT NULL REFERENCES <module>(id),
    changed_by    TEXT    NOT NULL,
    changed_at    TEXT    NOT NULL,
    changes_json  TEXT    NOT NULL DEFAULT '[]',   -- 改前 → 改後
    retention     TEXT    NOT NULL DEFAULT 'term'  -- 'permanent' | 'term'（見 §五）
);
CREATE INDEX idx_<module>_el ON <module>_edit_log(record_id, changed_at);
```
### ⇒ 為什麼不共用一張（三個理由，最後一個是決定性的）
```
① 前例：daily_task_edit_log 就是各一張
② 索引：共用要 (module, record_id) 複合 ⇒ 查單筆歷史要多過濾一層
③ 🔴 **外鍵**：共用表**無法**對五個不同的父表宣告 REFERENCES
   ⇒ 而沒有外鍵 ⇒ 父列刪掉時歷史變孤兒，**而它不會報錯**
```
⚠️ 副作用（**列出來，不藏**）：兩張表要各自維護；日後若有第三個「會逐筆修改業務單據」的模組，要再開一張。
⇒ 緩解：同形狀 ＋ 同命名 `<module>_edit_log`，**而不是抽成共用函式**
  （共用函式壞掉 ⇒ 五個模組同時失效，今晚已討論過那個單點）

## 3.2 ③ 全域稽核 ⇒ **沿用 `audit_log`，不新建**
```
五模組的動作一律走 helpers/audit.py:92 的 _audit()
action 命名：<module>.<verb>  （沿用既有 quotation.export_pdf 的形狀）
```

## 3.3 ① 執行歷史 ⇒ **不新建表**，沿用 cashier 的做法
```
對業務表做日期範圍查詢（cashier.py:150 的形狀）
⇒ 它答的是「這個月實際發生了什麼」⇒ **資料來源是業務表自己，不是另一份副本**
```
🔑 **不新建表的理由**：另一份副本＝兩份會分岔，而分岔之後哪一份是真的沒有定義。

---
# 四、🔴 ①③ 為什麼不可合併 —— **合併後會失去什麼**
```
① 執行歷史  答「**這個月做了什麼**」⇒ 業務查詢：要快、要能篩日期、**取消的那筆要消失**
③ 全域稽核  答「**這個人做過什麼**」⇒ 稽核查詢：要全、**不可刪、取消的那筆也要留著**
```
## ⇒ 合併之後失去的兩件
```
① **「取消」的語意沒有地方放**
   執行歷史裡取消的那筆**該消失**（它不該算進本月金額）
   稽核裡取消的那筆**該留著**（誰在什麼時候取消的）
   ⇒ 合併 ⇒ 只能二選一 ⇒ **選任一邊都會讓另一個問題答不出來**
② **保留期綁死**
   稽核不可刪 ⇒ 合併後執行歷史也刪不掉 ⇒ **它會無限成長**
   （audit_log 現在 2,267 筆；五模組上線後 export/preview 是高頻動作）
```
📌 既有前例已經證明它們分開是對的：`contractor_vouchers` 的 `unpay` 會
   `SET is_paid=0`（執行歷史裡消失）**而同一個 UPDATE 把 `{action:"unpaid"}` append 進 `paid_log`**。
   ⇒ **兩層都在，而「消失」只發生在該消失的那一層。**

---
# 五、⚠️ 保留期 —— **兩種答案下都成立**
```
未決（會計師三題之一）：「誰預覽過」算不算會計帳簿
```
## ⇒ 設計不依賴那個答案
```
每一列有 retention 欄位：'permanent' | 'term'
⇒ 會計師答了之後**改設定值，不改結構**
⇒ 清理排程只刪 retention='term' 且超過保留天數的
```
```
🟡 預設（A 已裁，未反對即生效）
   「誰**匯出**過」 ⇒ permanent（資料離開系統的證據）
   「誰**預覽**過」 ⇒ term（保留期可設）
```
⚠️ 副作用：**保留期的天數本身也未決**（法條起算點是「年度決算辦理終了後」，
   而系統沒有記錄那個時點）⇒ 清理排程**在那個時點有落點之前不要啟用**。

---
# 六、⚙️ 守門
```
① changes_json 缺「改前值」⇒ **寫入失敗**（DEFAULT '[]' 擋不住，要在應用層）
② 五張 *_edit_log 的欄位形狀必須一致 ⇒ 少一欄或多一欄 ⇒ 紅
③ 每個模組的寫入路徑都要有對應的 _audit() 呼叫 ⇒ 缺一個 ⇒ 紅
④ retention 只能是 'permanent'／'term' ⇒ 值域外 ⇒ 紅
⚙️ 反向控制：合法的寫入必須成功（否則「一律拒絕」也會讓 ① 綠）
```

---
# 七、⚙️ 兩問掃描
| 決定 | 誰決定的 | 副作用列過了嗎 |
|---|---|---|
| ②各模組一張，不共用 | **A-2** | ✅ 五張要各自維護；新模組要再開一張 |
| ③沿用 audit_log | **A-2** | ✅ 34 支已在寫，命名慣例要跟上 |
| ①不新建表 | **A-2** | ✅ 查詢效能綁在業務表的索引上 |
| ①③不可合併 | **A**（§72a） | ✅ 已寫出合併會失去的兩件 |
| 匯出 permanent／預覽 term | **A**（🟡） | ✅ 保留天數未決 ⇒ 清理排程先不啟用 |
| 「誰預覽過」算不算帳簿 | **未決** | 🔴 會計師三題之一 |

---
# 八、⚠️ 未查
```
✅ **已解除**：使用者裁「財務」＝整個側欄分組，不是獨立頁；
  獨立頁是出納／獎金計算／匯出傳票／會計科目
✗ audit_log 的 detail 欄位現在放什麼（只知道 DEFAULT '{}'）
✗ 清理排程要掛在哪（archive.py 的既有排程還是新的）
```
