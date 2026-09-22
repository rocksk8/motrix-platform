> ⚠️ **這是修訂紀錄，不是施工圖。**
> ☠️ 裡面三個 `CREATE TABLE` 區塊是 **被推翻的版本**（`§111`），
>    照它實作會寫出已經被退回兩次的 schema。
> ✅ **要做事情請讀 `SPEC-VOUCHER.md`**；這份只用來查「當初為什麼這樣決」。

# 傳票設計（`§92b` ④）
> A-2 產出 2026-09-23 00:0x ／ 基準 `2f8d592` ／ migration 從 **v95** 起
> ⚠️ 仍不開發。設計交 A 審，由 A 派 B。

---
# 🔴 零、先更正一個前提：**「既有狀態機」有兩種，而多數派不是 A 說的那個**

A 寫：「沿用既有慣例（`EDITABLE_STATUSES` 散在 **8 個 router**）」

## 實查
```
$ grep -rn "EDITABLE_STATUSES\s*=" backend/routers/*.py
case_extra_expenses.py:56   EDITABLE_STATUSES = ("草稿", "已駁回")   ← **唯一一處**
```
```
五個狀態字串各在幾支 router：
  草稿   11 支      待審核 9 支      簽核中 9 支      已核准 9 支
  **已駁回 1 支**（8 次出現，全部在 case_extra_expenses.py 之內）
```
## ⇒ 真正的分歧在「退回」怎麼做，而它是**設計層**的
```
甲（多數，9–11 支）  退回 ⇒ **狀態回「草稿」＋ 單號升版（-Rn）＋ 清除簽核**
    逐字依據：quotations.py:4305
    「退回修改：清除簽核、單號升版（-Rn）、狀態回草稿，申請人可重新編輯後再送審。」
乙（少數，1 支）      退回 ⇒ 進入獨立狀態「已駁回」，而它也可編輯
    依據：case_extra_expenses.py:56 EDITABLE_STATUSES = ("草稿","已駁回")
```
## ✅ **傳票選甲**，三個理由（不是偏好）
```
① 多數既有模組用它（9–11 支 vs 1 支）
② **單號升版（-Rn）是 append-only 的痕跡** ⇒ 與 §35p 法定本的事件流同一個原則
③ 乙的「已駁回」記在**狀態欄**，而狀態欄只有一個值
   ⇒ **同一張被退兩次，看不出來** ⇒ 財務不可接受
```
🔑 ⇒ 而選甲之後，`EDITABLE_STATUSES` 對傳票**只有一個值：`("草稿",)`**。

---
# 一、狀態機（實際字串值）
```
草稿 ──送審──▶ 待審核 ──(分層簽核)──▶ 簽核中 ──▶ 已核准 ──過帳──▶ **已過帳** 🔒
  ▲                                                │
  └──── 退回修改（清除簽核＋單號升版 -Rn）◀─────────┘
```
```
狀態值   "草稿" / "待審核" / "簽核中" / "已核准" / **"已過帳"**（新增）
可編輯   **只有 "草稿"**
```
## ⚠️ 「已過帳」是新的，它的位置要明著說明
```
既有五個狀態**沒有「已過帳」** —— 因為既有那些單據核准完就結束了
而傳票核准 ≠ 入帳 ⇒ 需要第六個狀態
🔑 它在「已核准」之後，是**第二道鎖**（§46：送審第一道、過帳第二道）
⇒ 已核准 = 簽核流程走完、**而帳還沒動**（仍可退回修改）
⇒ 已過帳 = 帳已動、**不可退回，只能作廢重開**（§35 使用者裁示）
```

---
# 二、傳票主表 `vouchers`
```sql
CREATE TABLE vouchers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    voucher_no      TEXT    NOT NULL,          -- 含升版尾碼，例 'V2026090001-R2'
    voucher_date    TEXT    NOT NULL,          -- 傳票日期（≠ 建立日）
    category        TEXT    NOT NULL DEFAULT '轉',  -- 傳票別，沿用 T100 voucherCategory
    summary         TEXT    NOT NULL DEFAULT '',    -- 摘要
    status          TEXT    NOT NULL DEFAULT '草稿',
    -- 過帳
    posted_at       TEXT    NOT NULL DEFAULT '',
    posted_by       TEXT    NOT NULL DEFAULT '',
    -- 作廢／取代鏈（§35 使用者裁示：作廢留痕、重開一張）
    voided_at       TEXT    NOT NULL DEFAULT '',
    voided_by       TEXT    NOT NULL DEFAULT '',
    void_reason     TEXT    NOT NULL DEFAULT '',
    supersedes_no   TEXT    NOT NULL DEFAULT '',  -- 本張取代了哪一張
    -- 法定副本（§35p 丙案）
    ledger_confirmed INTEGER NOT NULL DEFAULT 0,  -- 0 = 未確認 ⇒ 要出現在首頁計數
    -- 自訂欄位（使用者裁示：只在可編輯狀態可新增）
    custom_fields   TEXT    NOT NULL DEFAULT '{}',
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);
CREATE UNIQUE INDEX idx_vouchers_no ON vouchers(voucher_no);
CREATE INDEX idx_vouchers_status ON vouchers(status);
CREATE INDEX idx_vouchers_date ON vouchers(voucher_date);
CREATE INDEX idx_vouchers_ledger ON vouchers(ledger_confirmed);   -- 首頁計數要查得動
```

---
# 三、分錄表 `voucher_lines` —— **沿用 T100 的兩欄式，不要新發明**
```
既有依據 accounting_export.py:157-161 `_voucher_line(...)`
         {"debit": round(debit) if debit else 0, "credit": round(credit) if credit else 0, …}
⇒ **借、貸各一欄，其中一欄為 0**（不是單欄 ±）
```
```sql
CREATE TABLE voucher_lines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    voucher_id      INTEGER NOT NULL,
    line_no         INTEGER NOT NULL,
    account_item_id INTEGER NOT NULL,          -- → account_items.id（v93）
    summary         TEXT    NOT NULL DEFAULT '',
    debit           INTEGER NOT NULL DEFAULT 0, -- 整數（既有 round()，無小數）
    credit          INTEGER NOT NULL DEFAULT 0,
    dept_code       TEXT    NOT NULL DEFAULT '',
    -- §37b 決定性連結：型別＋主鍵，不是描述文字
    source_type     TEXT    NOT NULL DEFAULT '',  -- 'invoice_voucher'/'payment_request'/…
    source_id       INTEGER NOT NULL DEFAULT 0,
    counterparty    TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX idx_vlines_voucher ON voucher_lines(voucher_id, line_no);
CREATE INDEX idx_vlines_account ON voucher_lines(account_item_id);
CREATE INDEX idx_vlines_source  ON voucher_lines(source_type, source_id);
```
## ⚙️ 借貸平衡：**在過帳那一刻擋，不在儲存時擋**
```
草稿階段允許不平衡（使用者還在編）
過帳前檢查 SUM(debit) == SUM(credit) 且 > 0 ⇒ 不平衡**拒絕過帳並說出差額**
⚠️ 不可以只在前端擋（〈散文對工具是隱形的〉的資料版）
```

---
# 四、編寫紀錄 `voucher_edit_log` —— 照 `daily_task_edit_log` 的形狀
```sql
CREATE TABLE voucher_edit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    voucher_id   INTEGER NOT NULL,
    changed_by   TEXT    NOT NULL,
    changed_at   TEXT    NOT NULL,
    changes_json TEXT    NOT NULL DEFAULT '[]'   -- 改前 → 改後
);
CREATE INDEX idx_vel_voucher ON voucher_edit_log(voucher_id, changed_at);
```
⚠️ **`DEFAULT '[]'` 擋不住空紀錄** ⇒ 「缺改前值就寫入失敗」**必須在應用層擋**
   （與 `case_stages.assigned_to` 同一個形狀，已在 §45b 記過）

---
# 五、法定副本落點（`§35p` 丙案）
```
事件結構  voucher_no ／ attempt_seq ／ event ／ ts ／ who ／ payload_hash
event 值  posting_attempt ／ erp_confirmed ／ voided ／ superseded_by
存放點    🔴 **不放 ERP 資料庫**（使用者裁示）
寫入順序  ERP db 先（過帳成立）→ 法定本後 → 失敗則 ledger_confirmed=0 並進補寫佇列
```
🔴 **而「未確認筆數」必須出現在使用者每天會看的地方**（營運報表首頁／側欄紅點）
   —— **少了這一項，丙就退化成乙**（使用者裁示的組成部分，不是建議）

---
# 六、Migration（**v95 起**，v93／v94 已被 B 用掉）
```
v95  vouchers ＋ voucher_lines ＋ voucher_edit_log ＋ 索引
v96  預設科目「應付獎金」寫進 account_items（source='custom'？見下）
```
## ⚠️ v96 有一個要 A 裁的
```
「應付獎金」是**法定表裡本來就有的科目**，還是我們加的自訂科目？
  若法定表已有  ⇒ v96 不必新增，只要在設定頁指定它
  若法定表沒有  ⇒ 它是 source='custom' 的預設值，而**預設值不是使用者自訂的**
                  ⇒ 那會讓「自訂科目」這一類混進一個系統塞的東西
🔑 ⇒ **B 的解析結果出來後（547 筆）查一次就知道** —— 不要現在決定
```

---
# 七、⚠️ 我沒查的
```
✗ 那 9–11 支 router 的狀態轉移是否完全一致（我只比對了字串是否出現）
✗ 「單號升版 -Rn」的實際格式與產生邏輯（只讀到 quotations.py:4305 的 docstring）
✗ 分層簽核（待審核→簽核中）的既有實作，傳票要不要沿用同一套 approval 表
✗ 「應付獎金」在法定表 547 筆裡有沒有（要等 B 的解析結果）
✗ custom_fields 用 JSON 欄位是否與「匯出要照當下結構產生」相容（§35 第 5 節）
```

---
# 【修訂 v2】2026-09-23 00:0x — 依使用者實例與 `§104`

## 🔴 八、`source` 要**三態**，不是兩態（我原設計要改）
**實查 `backend/data/account_items_112.json`（547 筆）**：
```
'應付獎金'    **0 筆 —— 法定表裡沒有**
'應付薪資'    2191 ✅ 有
'其他應付費用' 2197 ✅ 有
```
⇒ 使用者裁的「科目樹預設『應付獎金』」**不能用法定科目**，三條路：
```
甲 用 2191 應付薪資      ✅ 法定、零新增  ⚠️ 獎金與薪資混在一起，報表分不出來
乙 用 2197 其他應付費用  ✅ 法定、零新增  ⚠️「其他」是垃圾桶科目，進去就看不見
丙 自訂一個「應付獎金」  ✅ 報表看得見    ☠️ 它是**系統塞的**，不是使用者建的
```
🔴 **這是會計判斷不是技術判斷 ⇒ 要問（併入「要問會計師」那一組）。**
✅ **而不論選哪一個，結構現在就該改成三態：**
```
source  'statutory'       法定表 547 筆，唯讀（TRIGGER 擋）
        'system_default'  **系統預設塞的**（若選丙，應付獎金屬這類）
                          ⇒ 可停用、可改指向 2191／2197，但**不混進 custom**
        'custom'          使用者自己建的
```
🔑 兩態的話，丙會讓「使用者自訂科目」這一區混進一個他沒建過的東西 ——
   **而他日後找不到是誰建的。**

## 九、版面三處（使用者實例，`§104b`）
```
① voucher_lines **已有 summary 欄** ✅ 我原設計就有 per-line 摘要
② **合計列**：借貸平衡不只是一道檢查，**是版面上要印出來的一列**
   ⇒ 匯出（Excel／PDF）與畫面都要有；而它的值 = SUM(debit)／SUM(credit)
   ⚙️ §37a 同源同單位：**畫面的合計與匯出的合計必須是同一支函式算的**
③ 🔴 簽核三格（製票／覆核／主管）**與狀態機不是同一組東西**
```
### ⇒ 兩者的對應（設計決定）
```
製票  = 建立者（created_by）           ⇒ 草稿階段就確定
覆核  = 第一層簽核人                   ⇒ 待審核 → 簽核中
主管  = 最後一層簽核人                 ⇒ 簽核中 → 已核准
⇒ 版面三格是**簽名位**（誰、什麼時候），狀態機是**流程位置**
⇒ ⇒ 三格的值從簽核紀錄取，**不是從 status 欄推**
```
⚠️ 實例上「覆核／主管」是空的 ⇒ **空是合法的**（還沒簽）
   ⇒ 而「已過帳且覆核為空」是否合法 ⇒ **要問**（可能他們實務上只有製票簽）

## 🔴 十、摘要 ＝ f(範本, 來源)，**產生當下凍結**
> 使用者原話：「出納可編譯範本，直接帶入範本文字＋這個發票的內容，未來可長期使用」

```
voucher_line_summaries 的來源  = 範本文字 ＋ 來源單據欄位
🔴 **產生當下凍結**：存**文字本身** ＋ template_id ＋ **template_version**
☠️ 否則一張已過帳的傳票，會因為別人改了來源而改變內容
📌 不是新發明：db.py:1300-1301 逐字「**已定案文件不隨來源異動**」⇒ 沿用
🔑 與 §31 的「模板套用時複製快照」**完全同一條**
```
### ⚠️ 而「存 template_version」有一個 A 沒講到的連鎖後果
```
存版本號 ⇒ 表示**舊版必須留著**（已過帳的傳票引用它）
⇒ ⇒ 範本表**不可以就地覆蓋**
✅ 而它不必做成完整的事件流，只要：
   voucher_templates(id, version, body, created_by, created_at, is_current)
   編輯 ⇒ **新增一列 version+1，舊列 is_current=0**（不刪）
   ⇒ 追溯時用 (template_id, version) 取得當初那一版
```

### 🔴 十一、「可以帶什麼」必須是**封閉清單**，而且在**儲存範本時**就擋
```
A 的理由（成立）：自由字串會引用不存在的欄位，**而它只印出空白，沒有錯誤訊息**
✅ 而我要補：**不要等到產生摘要時才發現** ——
⚙️ **儲存範本時驗證每一個佔位符都在清單裡，不在就拒絕儲存並指出是哪一個**
🔑 理由：範本「未來可長期使用」（使用者原話）
   ⇒ 一個壞掉的範本會**每次都印空白**，而它看起來像使用者自己沒填
```
```
封閉清單（起始版，要 A 確認）：
  來源單據   發票號／發票日期／單號（報價單、請款單…）／客戶名稱／廠商名稱
  金額       未稅／稅額／含稅／本行金額
  日期       單據日期／上傳檔案日期（使用者明說）
  其他       案件編號／專案名稱
⚠️ 而清單要能**擴充而不破壞既有範本** ⇒ 只增不刪，刪要先查有沒有範本在用
```

### ⚙️ 十二、「最後核算金額」的第二層（`§104c`）
```
帶入的金額 vs 來源**現在**的金額
過帳前  不一致 ⇒ **明著告訴他，不可靜默用舊值**
過帳後  凍結，不再比對（否則已過帳的傳票會一直跳警告）
```
🔑 ⇒ 那個比對只在「可編輯狀態」時跑，而它的結果**不阻擋過帳，只提示** ——
   因為「來源改了而傳票不改」可能正是對的（單據作廢重開時）。

## 十三、單號格式（實例證實）
```
20260330-006   = YYYYMMDD-NNN（當日流水）
⚠️ 而它**沒有 -Rn** ⇒ 那不是反證（它沒被退過）
🔴 `-Rn` 的實際格式我仍然標**未查**（只讀到 quotations.py:4305 的 docstring）
```

---
# 【修訂 v3】2026-09-23 00:1x — 依 `§105`／`§106`

## ✅ 十四、狀態機定案（使用者裁示）
```
已核准 ──過帳──▶ 已過帳     而「已核准」**要簽核走完**（製票／覆核／主管三格都要簽）
```
🔴 **不做越權通道。** 使用者原話「要簽，那張是特例」——
   而 A 給的三個選項裡有「可以被越過（而越過會留痕）」，**他選的不是那一個**。
📌 `§6`：**使用者明著沒選的那一個選項，也是一種資訊。**

### ⚠️ 而「那張是特例」帶出一個**必須先寫下來**的邊界情況
```
實例那張（已過帳、覆核為空）**不符合新規則**
⇒ 日後匯入舊傳票時會被擋
⇒ ☠️ **那不是缺陷，是規則收緊的必然結果**
```
🔑 **不先寫下來的話，日後有人會把它當成 bug 去「修」那道守門。**
⇒ 規格要求：匯入舊資料時走**明著標記的歷史匯入路徑**，而不是放寬守門。

---
## ✅ 十五、`source` 三態 ⇒ **改 `v93`，而它有一個必須先驗的前置**
**A 的判斷成立，我補查了它沒查的範圍：**
```
$ ls backend/*.db
  motrix.db (0 bytes) ／ motrix_erp.db (7.3MB) ／ motrix_erp_demo.db (1.0MB)
$ 三個都查 account_items ⇒ **全部 NOT YET**
$ 正式機：最後一次部署 2026-09-22 18:56（deploy_dashboard_history 首筆）
  而 v93/v94 是那之後才 commit 的 ⇒ **正式機不可能有** ✅
```
🔑 〈凍住的歷史不要回溯改寫〉管的是「**已經跑過的**」—— 而 v93 還不是歷史。

### 🔴 而 A 自己加的那個條件需要一個**落點**，否則沒有人會去查
```
A 寫：「只要有一台機器跑過（含開發機）⇒ 立刻變成加新的一支」✅ 對
⚠️ 而那是一個要**有人記得去查**的條件 ⇒ 〈計數器要有落點〉
```
⇒ **可操作前置**：**改 `v93` 之前，B 必須跑一次下列查詢並把輸出貼進交付**
```
三個 .db 各查一次 account_items 是否存在
⇒ 任何一個回「存在」⇒ **停手，改成加 v95**
```

---
## 🔴 十六、「如果有修改，要能警示」（使用者新增）——與凍結是同一件事的兩半
```
只凍不警  傳票是對的，**而沒有人知道它與現況已經不一樣了**
只警不凍  傳票會自己變，**警示也就沒有比較的基準**
🔑 ⇒ **凍住的那一份副本，正是偵測「被改過」的唯一依據**
```
### ⇒ 三個警示來源
```
① 來源單據被改   比對「凍結時的值」vs「來源現在的值」
                 過帳前 ⇒ 提示；過帳後 ⇒ 不再比對（否則會一直跳）
② 範本被改       🔴 **編輯者要被告知「目前有 N 張傳票在用這個範本」**
                 ⇒ 那是它做決定前需要的資訊，不是事後通知
③ 傳票自己被改   ⇒ 那就是 voucher_edit_log（第四節）
```
### ⚙️ 而「看到警示之後仍然過帳」是一個決定 ⇒ 要留痕
```
vouchers 加：
  posted_with_warning      INTEGER NOT NULL DEFAULT 0
  posted_warning_snapshot  TEXT    NOT NULL DEFAULT ''   -- **當時警示的內容**
```
🔑 **要記的是「他當時看到什麼」，不只是「他看過警示」** ——
   ☠️ 否則日後查帳時，只知道有人按了確認，**而不知道他確認的是什麼**。
📌 與 §37d「改前改後都要記」同一條：**一個沒有內容的留痕，等於只留了一個時間戳。**

---
## ✅ 十七、要問會計師的那一組（現在共三題）
```
① 「誰預覽過」的紀錄算不算會計帳簿（⇒ 10 年不可刪／可設保留期）
② 《商業會計項目表》112 年版之後有無更新版（⇒ 若有，547 會是一個精確的錯誤數字）
③ **「應付獎金」怎麼記**：2191 應付薪資／2197 其他應付費用／自訂一個
```

---
# 【修訂 v4】2026-09-23 00:2x — 依 A 的審閱 `§107`（R1–R7）

## ✅ R1 外鍵改用業務鍵（實查確認）
```
db.py:4065  account_items( code TEXT PRIMARY KEY, level, name, name_en, parent_code, source )
⇒ **沒有 id 欄** ⇒ A 對
```
```sql
voucher_lines.account_item_id  →  **account_code TEXT NOT NULL**   -- → account_items(code)
```
### 🔑 而它引出一條判準，要寫下來（否則 R1 與 R3 看起來矛盾）
```
會被 migration **重建**的表（account_items，v94 會重跑）⇒ 用**業務鍵**（code）
業務資料表（vouchers，不會被重建）                      ⇒ 用 **id** 沒問題
```
📌 ⇒ 所以 R1 用 `code`、R3 用 `voucher_id`，**兩者不衝突，判準是「這張表會不會被重建」。**

---
## 🔴 R2 凍結漏了一格 —— **而 `account_name_snapshot` 解不了那一格**
A 指出要凍 `account_name`（✅ 對）。**而代號本身也會變：**
```
code 是 PRIMARY KEY，而 SQLite 允許 UPDATE PRIMARY KEY
TRIGGER 只擋 source='statutory'
⇒ ⇒ **custom／system_default 的 code 可以被改**
⇒ ⇒ 而 voucher_lines.account_code 指向它 ⇒ **變成孤兒，而且 SQLite 沒有外鍵強制**
```
☠️ 凍結 `name` 救不了這一格：**名稱凍住了，而那一行指向的科目不存在了。**
### ⇒ 兩件都要
```sql
voucher_lines 加：
  account_code           TEXT NOT NULL   -- 連結
  account_name_snapshot  TEXT NOT NULL   -- 過帳時凍結（版面要印）
```
```
⚙️ 而連結那一端要擋在資料層：
   **已被任何傳票引用的 account_items，其 code 不可修改**
   ⇒ 新增 TRIGGER：BEFORE UPDATE OF code ON account_items
      WHEN EXISTS(SELECT 1 FROM voucher_lines WHERE account_code = OLD.code)
      BEGIN SELECT RAISE(ABORT, '此科目已被傳票引用，代號不可修改'); END;
```
🔑 與 `§38d`（已入帳的單據不可作廢，只能紅字沖銷）**同一條原則往上游延伸**。

### ⚠️ 而 `source` 的實作目前是兩態，與裁示不符
```
db.py:4070  source TEXT NOT NULL DEFAULT 'custom'   # 註解寫 statutory / custom
而 §十五 已裁三態：statutory / system_default / custom
⇒ **改 v93 時要一起改**（A 已裁「改 v93」）
```

---
## ✅ R3 附件綁 `voucher_id`（實查確認）
```
helpers/uploads.py:42  save_document_files(subfolder, doc_no, files, uploaded_by, watermark_by)
                       ⇒ uploads/{subfolder}/{doc_no}/{uuid}{ext}
```
✅ A 的裁定採用，**而它比想像中便宜**：
```
doc_no 參數是字串 ⇒ 傳 **str(voucher_id)** 進去即可
⇒ **不必改 helper，「沿用既有前例」仍然成立** —— 只是傳的值不同
```
📌 而 A 查到的那一句要留在規格裡：
> 「**會升版的單號」與「綁單號的附件」從來沒有同時出現過 ⇒ 沒有前例可沿用。**

---
## ✅ R4 `voucher_date` = 建立當日，不可編輯（使用者裁示）
```
使用者原話：「傳票號碼由系統發、**傳票日期由系統發**、狀態由系統發」
⇒ 我原本寫的「（≠ 建立日）」**與裁示相反**，已改
```
### ⚠️ 已知代價，現在就寫進規格（不寫的話日後會被當成 bug）
```
☠️ **做不了「月底補登上個月的帳」。**
📌 與 §十四「那張是特例」同一條：規則收緊的必然結果，不是缺陷。
⇒ 日後若要補登，走**明著標記的歷史匯入路徑**，不要放寬這一條。
```

---
## 🔴 R7 `-Rn` 不可沿用（A 實跑，我採用）
```
quotations.py:164   ^(MQ-\d{6}-\d{3})(?:-R(\d+))?$      ← **寫死 MQ- 前綴**
A 實跑：20260330-006 → -R1 → **-R1-R1**（不是 -R2）
☠️ 而 UNIQUE INDEX 擋不住（'-R1-R1' 與 '-R1' 是不同字串）
⇒ **不報錯，只是產生一個錯的單號**
```
### ⇒ 傳票自己的一支
```
格式    YYYYMMDD-NNN[-Rn]      例：20260330-006-R2
規則    退回時 n+1；n 從**現有最大值**解析，不是從字串尾巴加
⚙️ 守門  同一個 base（YYYYMMDD-NNN）底下，-Rn 的 n 必須唯一且連續
⚙️ 反向控制：餵一個已經有 -R1 的單號，**必須產生 -R2 而不是 -R1-R1**
```
🔑 那個反向控制正是 A 實跑抓到的那一個，**要寫成題，不要只寫在規格裡**。

---
## ✅ R5 我的證據被換掉（結論一樣，我認）
```
我用   deploy_dashboard_history 首筆 18:56
☠️ 而那依賴「那張表記得住所有部署」—— **它自己是新加的**
A 換成 最新的包 20260922_200604_7bc1fb8（09-22 20:06）比 v93 的 commit（09-23 00:00）**早四小時**
        ⇒ 主詞是「**所有已產出的升級檔**」，不是「所有被記錄下來的部署」
```
📌 **這次輪到我：結論的主詞比查詢的範圍大。**

---
## ✅ R6 落點收緊（A 的版本更好）
```
我提的   B 要跑一次檢查並貼輸出
A 收緊   **交不出來就不收那個 commit**
⚠️ 範圍限**持久化的 db**；pytest 暫存 db 跑過不算（拋棄式的，不是歷史）
```

---
# 【修訂 v5】2026-09-23 00:2x — 依 `§108`，＋一個新發現

## ✅ R2 理由改寫（A 實跑推翻我的前提，我認）
```
❌ 我寫的    「SQLite **無外鍵強制** ⇒ 變成孤兒」        ← **可查證為假**
✅ 實查      db.py:151  每一條連線都 PRAGMA foreign_keys=ON
```
### ⇒ 兩道都要，而**理由是這個**
```
① account_code TEXT NOT NULL **REFERENCES account_items(code)**
② TRIGGER：BEFORE **UPDATE OF code** ／ BEFORE **DELETE** ON account_items
           WHEN EXISTS(SELECT 1 FROM voucher_lines WHERE account_code = OLD.code)
```
🔑 **② 不是因為 SQLite 不強制（它有強制）—— ② 防的是「那個強制隨時可能是關的」：**
```
db.py:151  PRAGMA foreign_keys=ON  **包在 try/except Exception: pass 裡**
db.py:230  demo 重置路徑**明著關掉它**（PRAGMA foreign_keys=OFF）
```
☠️ 〈降級之後它還是會動〉：pragma 沒設成功 ⇒ 系統照常運作 ⇒ **沒有任何東西會說話。**
📌 **而理由必須對的原因**（A 的原話，我照收）：
> 一個對的防護配一個錯的理由 ⇒ 日後有人查到 FK 是 ON ⇒ **認定 ② 多餘 ⇒ 正當地刪掉它**。

## ✅ 補上 `DELETE`（我原本只寫 UPDATE OF code）
A 實測 A)／C) 兩格：**DELETE 造成一模一樣的孤兒。**

## ✅ 判準補成三態（A 的補充）
```
會被 migration 重建          ⇒ 用業務鍵
不重建、鍵不會變             ⇒ 用 id
**不重建、而鍵本身可被使用者改** ⇒ 用 id ＋ 把鍵凍進引用端（就是 account_code 這一格）
🔑 判準的主詞是「**這個鍵會不會變**」，重建只是它會變的其中一個原因
```

---
# ☠️ R8（**A-2 新發現，有時效**）：**v93 的 TRIGGER 會讓 demo 重置壞掉**

## 實查
```python
db.py:227-233（逐字）
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    conn.execute("PRAGMA foreign_keys=OFF")
    for t in tables:
        conn.execute(f"DELETE FROM {t}")        # ← **包含 account_items**
```
```
而 v93 已落地的 TRIGGER（B 寫的）：
    BEFORE DELETE ON account_items WHEN OLD.source='statutory'
    BEGIN SELECT RAISE(ABORT, '法定會計項目不可刪除'); END;
```
🔑 **`PRAGMA foreign_keys=OFF` 不影響 TRIGGER** ⇒ **擋不掉**。

## ☠️ ⇒ 後果比「demo 登入失敗」更糟
```
tables 的順序是 sqlite_master 的順序
⇒ account_items 若排在中間 ⇒ **前面的表已刪、後面的沒刪**
⇒ ⇒ **留下一個半清空的 demo 資料庫**，而例外往上拋
```
⚠️ 而 `init_db(DEMO_DB_PATH)` 在後面重建 —— **但 migration 只在版本升級時跑**
⇒ 已經是 v94 的庫**不會重跑匯入** ⇒ **那 547 筆刪掉就不會回來**。

## ✅ ⇒ 正確解法：**把 `account_items` 排除在 demo 重置的刪除清單外**
```
❌ 甲 DROP TRIGGER → DELETE → 重建   ⇒ 要硬編碼 trigger 名，新增時會漏
❌ 乙 改成刪檔重建                   ⇒ 大改動
❌ 丙 TRIGGER 加「非 demo 才生效」   ⇒ TRIGGER 不知道自己在哪個庫
✅ 丁 **account_items 不在清除清單裡**
```
🔑 **而丁不是為了繞過 TRIGGER —— 它本身就是對的**：
> **法定科目 547 筆是「系統資料」，不是「使用者資料」。**
> demo 重置的目的是清掉使用者資料，而那 547 筆本來就該在。
⚙️ 而排除清單要能被檢查：**新增一張「系統資料表」而沒加進排除清單 ⇒ 要紅**
   （否則下一張系統資料表會再踩一次，而症狀一樣是半毀的 demo 庫）

---
# 【定稿 v6】2026-09-23 00:3x — 依 `§109`

## ✅ R8 後果更正（A 實跑，我認）
```
❌ 我寫的  「留下一個半清空的 demo 資料庫」 ⇒ **實跑為假**
✅ 實際    那一串 DELETE 全在同一個隱式交易裡，conn.commit() 在迴圈**之後**
           ⇒ 中途 ABORT ⇒ commit 沒發生 ⇒ finally: close() **整筆回捲**
⇒ 真正的後果：**demo 登入每次 500**（auth.py:376-377 無 try/except）
```
⚠️ **方向是高報。** 〈把自己的動作當成對象的性質〉：**別人會照我的嚴重度重排順序**，
而「安靜毀損」會讓它插到該先做的事前面。**它仍要修，而不必插隊。**

## ✅ 而 A 的時序推論（它標「讀碼推得」）**我驗了它的前提**
```
$ SELECT * FROM schema_version
  motrix_erp.db       ⇒ **92**（2026-09-22T22:09:45）
  motrix_erp_demo.db  ⇒ **92**（同上）
⇒ A 的「demo 庫現在 v92」**為真** ⇒ 時序推論的地基成立
```
```
第 1 次 demo 登入  清空成功（account_items 還不存在）⇒ init_db() 升 v94 ⇒ 載入 547 筆
第 2 次 demo 登入  ⇒ DELETE FROM account_items ⇒ **ABORT ⇒ 500**
🔑 ⇒ **「我登入 demo 試過了，可以」會漏掉它。驗收必須連登兩次。**
```
📌 而主庫安全：它不會被 reset，且 v94 只會在啟動時升一次。

## ⚙️ R8 守門改成**雙向**（A 指出我的只有一個方向）
```
❌ 我提的  新增系統資料表沒登記 ⇒ 紅
☠️ 那可以靠**把每一張表都放進排除清單**變綠 ⇒ demo 從此不再清空任何東西
✅ 改成笛卡兒積（§54c 同形狀）：
   **每一張表必須落在「使用者資料」或「系統資料」其中一邊，互斥且窮盡**
   缺一張 ⇒ 紅   ／   兩邊都有 ⇒ 紅   ／   多出一張不存在的表 ⇒ 紅
```
📌 分類表建議與表定義放在一起（`db.py`），守門讀它 ＋ 讀 `sqlite_master` 比對。

---
# ✅ 定稿說明
```
§零～§十七 ＋ R1–R8 ＋ 三態 source ＋ 雙向守門 ⇒ 本檔即 SPEC-VOUCHER 定稿
未查清單（3 格）刻意保留，A 已明示不必猜：
  ✗ 9–11 支 router 的狀態**轉移**是否一致
  ✗ 分層簽核的既有 approval 表要不要沿用
  ✗ custom_fields 用 JSON 是否與「匯出照當下結構產生」相容
```
