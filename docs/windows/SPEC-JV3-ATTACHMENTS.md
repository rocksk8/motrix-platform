# `JV3` 傳票附件 —— 施工圖

> A-2 撰寫／2026-09-23。**單一版本、無修訂層。照這一份做。**
> 三項裁定已併入（`STATE.md §163`，A 2026-09-23）：
> **① 作廢重開要複製附件 ② 草稿刪除只軟刪 DB 列、bytes 留著 ③ PDF 合併加 `pypdf`**
> 全部數字都是本機實查。**沒查過的一律標「待查」，不推。**

---

## §0 先講三件會讓人做錯的實況

```
① 這個 repo **沒有任何附件資料表**（94 張表逐一看過）
   附件 metadata 一律存在**擁有者單據的 JSON 欄位**裡
   實體檔走 helpers/uploads.py::save_document_files()
② 既有的刪除是 os.remove() ＋ except: pass —— **沒有簽核、沒有快照**
   ⇒ 使用者「刪除要簽核＋快照」那一條，**目前一處都沒有落實**
   🔴 而裁定 ② 之後，這一支**不可以被 JV3 重用**（見 §5）
③ 正式機**沒有任何 Python PDF 套件**（requirements.txt 12 項）
   PDF 一律走 **Edge Headless --print-to-pdf**
```

⚠️ 第 ③ 點的射程，寫在最前面因為它差點造成一個錯誤決定：
`pymupdf`／`pdfplumber` **裝在開發機上、不在 `requirements.txt`**。
A-2 用它們讀過參考 PDF，A 查合併方案時差點把它當成「零新增套件」。
🔑 **判準是「`requirements.txt` 裡有沒有」，不是「import 得到嗎」。**

---

## §1 綁什麼：`voucher_id`，不是 `voucher_no`

```
voucher_no  退回升版 X -> X-R1 -> X-R2   **會變**
voucher_id  AUTOINCREMENT 主鍵            **不變**
```

**依據（不是推的）**：`helpers/voucher.py` `can_send_back` docstring 逐字

```
退回      **同一張單**，清除簽核 ＋ 單號升版 -Rn，改完再走一次
作廢重開  原單留著（作廢），**另開一張**
```

⇒ 升版**不換列** ⇒ `voucher_id` 跨版穩定。
📌 而 `voucher_lines` 與 `voucher_edit_log` **已經**都綁 `voucher_id`
（`REFERENCES vouchers_all(id)`，v95）⇒ 本表沿用，不是新慣例。

### 🔴 實體路徑也不可以含 `voucher_no`

既有 helper 把 `doc_no` **寫進路徑**：`uploads/{subfolder}/{doc_no}/{uuid}{ext}`。
⇒ 呼叫時 `doc_no = str(voucher_id)`：

```
uploads/voucher_attachments/{voucher_id}/{uuid}{ext}
```

✅ 這樣 `save_document_files()` **零修改**即可重用。
（⚠️ `delete_document_file()` 不能重用，理由在 §5。）

### 🔴 裁定 ①：作廢重開**要複製附件**

作廢重開是**另開一張**（新 `voucher_id`）⇒ 不複製的話新單附件是空的。

```
複製時新增一列，且：
  file_id        重新產生（idx_vatt_file 是 UNIQUE，不可沿用）
  path           指向**新** voucher_id 的目錄（實體檔真的複製一份）
  source_type    'voucher'
  source_doc_no  str(原 voucher_id)   ← **存 id 不存 no**，理由同 §1
  source_file_id 原那一列的 file_id
```

**🔴 兩格不可以省（C 寫紅燈時多釘的，A 2026-09-23 裁保留）**

```
① 已刪的那一筆（deleted_at 非空）**不複製**
   => 使用者刪掉它是**有意的**，重開不該把它撿回來
② file_id **不可共用**，每一筆重新產生
   => 共用的話：在新單刪掉一個，**原單的憑證跟著不見**
```

🔑 **② 的理由比 ① 硬，而硬在它不由使用者的行為決定**：
```
① 是「尊重使用者的意圖」        —— 意圖可以改變，規則就跟著可議
② 是「已作廢的歷史不可被後來的動作改寫」 —— **稽核的不可變性**
```
⚠️ 原單是**已作廢的歷史**，而稽核要看得見「它當時附了什麼」。
☠️ 共用 `file_id` 的失敗方式很安靜：新單那邊的刪除**成功了**，
而少掉的是一張已結案的傳票的憑證 —— **沒有人會在當下發現。**
📌 而 DDL 的 `idx_vatt_file` 是 UNIQUE ⇒ 資料層本來就擋得住「同一個 id 兩列」，
**而擋不住「兩列指向同一個實體檔」** ⇒ 所以實體檔也要真的複製一份（見上）。

📌 `source_doc_no` 存 id 的理由：與其他九類一致，且 no 可由 id 查得；
反過來不成立（no 會升版）。
⚠️ 儲存翻倍是已知代價，**A-2 沒有量過實際容量**；A 裁「作廢重開是低頻動作，
本輪接受」。⇒ 這是一個**明著接受的代價，不是沒看到的洞**。

---

## §2 資料表 `voucher_attachments`（新 migration，**動 `db.py` 前先宣告**）

### 🔴 本節**刻意不寫版本號**

```
✗ 不要寫「v99」「v100」—— 一個寫進文件的號碼是**一份會過期的拷貝**
✅ 動手當下自己取：
   $ grep -n '^CURRENT_VERSION' backend/db.py
   $ grep -c '# v[0-9]' backend/db.py     # 或直接看 _MIGRATIONS 清單尾巴
```

☠️ 兩人同時加 migration，**git 不會衝突，只會在執行時撞版本號**。
📌 2026-09-23 實例：本文件初版寫「`CURRENT_VERSION = 98`（寫成時）」，
而 B 在同一小時內加了 `_m099_voucher_signatures` ⇒ 那個數字**當天就過期**。
🔑 **釘一個新號碼（例如改寫成 v100）會用同一種方式再過期一次** ——
所以這裡改成「不寫號碼，寫取號的指令」。

⚠️ `db.py` 是鎖定檔：**動它之前要宣告**（`MULTIWIN-PROTOCOL.md`）。
✅ 而號碼本身有守門：`test_migration_numbering_2026_09_23.py` 的 `MG1②`
（`_mNNN` 前綴不可重號）＋ `MG1③`（連續、無跳號）會擋下來，**且有正對照**。

```sql
CREATE TABLE IF NOT EXISTS voucher_attachments (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  -- 🔴 指向實表，不是 VIEW。作廢單的附件必須留著（稽核要看得到）
  voucher_id       INTEGER NOT NULL REFERENCES vouchers_all(id),
  file_id          TEXT    NOT NULL,          -- 對應 save_document_files() 的 id
  filename         TEXT    NOT NULL,          -- 使用者原始檔名
  path             TEXT    NOT NULL,          -- uploads/ 相對路徑（含 demo 前綴）
  size             INTEGER NOT NULL DEFAULT 0,
  mime             TEXT    NOT NULL DEFAULT '',
  -- 🔑 來源三欄：**決定性連結**，不是一段描述文字（§37b 已裁）
  source_type      TEXT    NOT NULL DEFAULT '',  -- '' = 當場上傳；否則見 §3 表
  source_doc_no    TEXT    NOT NULL DEFAULT '',  -- 來源單號／主鍵（字串，見 §3）
  source_file_id   TEXT    NOT NULL DEFAULT '',  -- 來源 JSON 陣列裡那筆的 id
  uploaded_by      TEXT    NOT NULL,
  uploaded_at      TEXT    NOT NULL,
  -- 🔴 軟刪除：**只有草稿階段可刪**（§5）。非空 = 已刪，**而實體檔留著**
  deleted_at       TEXT    NOT NULL DEFAULT '',
  deleted_by       TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_vatt_voucher
    ON voucher_attachments(voucher_id, deleted_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_vatt_file
    ON voucher_attachments(file_id);
CREATE INDEX IF NOT EXISTS idx_vatt_source
    ON voucher_attachments(source_type, source_doc_no);
```

### 🔴 為什麼是資料表，而既有附件是 JSON 欄位

```
既有：附件只被它的擁有者讀              => JSON 陣列夠用
JV3：要回答「這個檔案被哪幾張傳票引用過」 => JSON 欄位**查不動**
```

📌 而那個查詢不是想像的：`JV7` 的來源清單要標示「已被引用」，
否則同一張發票會被帶進兩張傳票而**沒有人看得出來** ⇒ 重複入帳。

### ⚠️ 本表要加進每日備份，否則稽核題會紅

`backend/archive.py:1606-1610` 傳票五張表**都已列入**。
⇒ 本表要一起加：`"傳票附件": "SELECT * FROM voucher_attachments ORDER BY id"`。
☠️ 不加的話 `test_system_audit_2026_09_14.py:124` 的 `undecided` 會多一張 ⇒ **紅**。
（那一題是刻意的：新表必須有人**做過決定**，不是必須被備份。）

---

## §3 來源清單：`(c) 都要` 的**逐項落地**（`JV3` 與 `JV7` 共用同一份）

使用者裁 **(c) 都要**（`§159` ①）。實查後，「都要」對應到**九個**既有存放點：

| # | `source_type` | subfolder（實體路徑） | `source_doc_no` | metadata 位置 | 呼叫端 |
|---|---|---|---|---|---|
| 1 | `quotation_signed` | `quotations` | `quote_no` | `quotations.**signed_files_json**` | `quotations.py:1173` |
| 2 | `case_update` | `case_updates` | `quote_no` | `case_updates.files_json` | `quotations.py:4621` |
| 3 | `payment_item` | `quotation_payment_items` | `{quote_no}_{idx}` | 陣列內 `invoiceFiles` | `quotations.py:3129` |
| 4 | `material` | `quotation_materials` | `{quote_no}_{idx}` | 陣列內 `files` | `quotations.py:3205` |
| 5 | `material_invoice` | `quotation_materials_invoices` | `{quote_no}_{idx}` | 陣列內 `invoiceFiles` | `quotations.py:3268` |
| 6 | `extra_expense` | `case_extra_expense` | `{quote_no}_{exp_id}` | `case_extra_expenses.files_json` | `case_extra_expenses.py:569` |
| 7 | `invoice_voucher` | `invoice_vouchers` | `voucher_no` | `invoice_vouchers.**issued_files_json**` | `invoice_vouchers.py:738` |
| 8 | `contractor_dispatch` | `contractor_dispatches` | `str(did)` | `files_json` | `vendor_contractors.py:602` |
| 9 | `contractor_invoice` | `contractor_dispatch_invoices` | `str(did)` | `invoice_files_json` | `vendor_contractors.py:670` |

（第 10 個 `source_type` 是 `voucher`，只由裁定 ① 的作廢重開複製產生，見 `§1`。）

**對應使用者講的三類**

```
發票       => 7（開票申請）＋ 5（購料發票）＋ 9（承攬商發票）＋ 3（收款發票）
承攬商支出 => 8 ＋ 9
購料       => 4 ＋ 5
案件既有   => 1 ＋ 2 ＋ 3 ＋ 6（4/5 也掛在案件下）
```

### ✅ 九類的欄位名已逐一對過 `PRAGMA table_info`（A-2 2026-09-23）

初版這張表的欄位名是**從呼叫端上下文讀的**，A-2 當時標了「沒逐一開 DDL 對」。
現在對過了，**九類裡有一類是錯的、一類不完整**：

```
#1 quotation   規格原寫 quotations.**files_json**
               實際     quotations.**signed_files_json**（該表根本沒有 files_json）
               ⇒ 而它的語意也更窄：那是**報價單回簽檔**，不是「報價單的附件」
               ⇒ source_type 一併改名 quotation -> **quotation_signed**
#7 invoice_voucher  原寫只到表名，未指欄 ⇒ 補 **issued_files_json**
其餘七類            ✅ 對得上
```

☠️ **錯一個的症狀是「那一類的清單永遠是空的，而它不會報錯」**（B 的說法，準）
⇒ 實作時**再對一次**：`PRAGMA table_info` 是權威，`db.py` 的原始碼不是
（A-2 第一次用 regex 掃 `db.py` 就跨到隔壁表，撈出三個不屬於 `quotations` 的欄位）。

### 🔴 「購料」**不在** `material_orders` —— 這一格最容易踩

```
$ grep -c 'files_json\|UploadFile' backend/routers/material_orders.py
0
```

⇒ 購料附件實際掛在**報價單底下的材料明細**（#4／#5），不是採購單模組。
☠️ 找錯地方的話會做出一個**永遠是空的清單，而它不會報錯** ——
畫面上看起來像「這個案件沒有購料附件」，而不是像一個缺陷。

### ⚠️ 刻意排除的兩處

```
completion_notes / shipping_notes / dev_logs  => 不是會計憑證，排除
_pending_case_changes/{change_id}             => **待核准的暫存附件**，排除
   依據 case_extra_expenses.py:629 逐字：「核准前不會出現在正式附件清單」
   ☠️ 帶進傳票 = 讓一個還沒核准的東西變成憑證
```

---

## §4 帶入 = **複製檔案**，不是引用

```
引用（只存路徑）  => 別人刪掉來源附件 ⇒ **一張已過帳傳票的憑證消失**
複製             => 多佔空間，而憑證留得住
```

**為什麼不能靠「禁止刪除來源」擋**（v95 對會計科目就是這樣擋的）：

```
account_items  刪除走 SQL        => CREATE TRIGGER ... RAISE(ABORT) 擋得到 ✅
附件           刪除走 os.remove() => **沒有任何 DB TRIGGER 攔得到** ❌
               而 metadata 在 JSON 欄位裡 ⇒ 連外鍵都指不過去
```

🔑 ⇒ 科目那一招**在這裡不成立**，理由是實作路徑不同，不是偏好不同。

**複製時機＝使用者按下「帶入」的當下**，不是過帳時。
依據：`case_extra_expenses.py:629` 逐字「新檔案在**草稿階段就實際落地**」——
沿用既有慣例；且過帳才複製的話，草稿期間來源被刪就已經來不及。

⚠️ 複製後 `source_*` 三欄仍要填 ⇒ 它記的是**出處**，不是取檔路徑。

### 🔴 兩個「來源不完整」的情況必須明著決定（A-2 2026-09-23 實查後補）

實查開發機（`PRAGMA` ＋ 讀 JSON ＋ 數磁碟）：

```
六個來源欄位裡的檔案 metadata 總筆數   **1**
  唯一那筆 keys = ['filename','id','path']
  缺 size／mime／uploadedBy／uploadedAt（`save_document_files()` 會寫的七個裡缺四個）
uploads/ 底下的實際檔案數              **0**
  ⇒ 那一筆的 `path` **指向一個不存在的檔**
```

🔑 ⇒ **這台機器上沒有可以據以判斷「正式機的 JSON 長什麼樣」的樣本。**
☠️ 不要從那 1 筆推論「既有資料都缺四個欄位」—— 它是孤兒，幾乎確定是測試資料。
📌 〈空集合上的斷言〉：**樣本數 1，而且它的檔案不存在。**

**⇒ 所以要決定的不是「怎麼相容」，是「不完整時做什麼」，而且要大聲：**

```
① 來源 metadata 缺欄位（size／mime／uploadedBy／uploadedAt 任一）
   => **照樣複製**，缺的欄位留空，而**在回應裡回報「這幾筆的資訊不完整」**
   ☠️ 靜默補預設值的後果：傳票上顯示一個看起來正常的上傳者與時間，**而那是我們編的**
② 來源的**實體檔不存在**
   => **整批拒絕**（400），明說是哪一筆
   ☠️ 跳過那一筆的後果：使用者以為附件帶進來了，
      而過帳之後才發現那張憑證從來沒有存在過
   ⚠️ 而它不是理論情況 —— 開發機上唯一那筆就是這樣
```

⚙️ ⇒ 驗收要有一題：**來源檔被刪掉之後執行帶入 ⇒ 400 且 `voucher_attachments` 零新增**
（不是「跳過它而其餘成功」）。

---

## §5 刪除：草稿可刪（**軟刪，bytes 留著**），離開草稿不可刪

```
草稿    可刪。UPDATE voucher_attachments SET deleted_at=?, deleted_by=?
        ＋ 寫一列 voucher_edit_log（field='attachment', from=檔名, to=''）
        🔴 **實體檔不刪**（裁定 ②）
非草稿  **不可刪**，一律 403。要移除 ⇒ 作廢整張傳票重開
```

### 🔴 裁定 ② 的實作後果：**`delete_document_file()` 不可以重用**

```
helpers/uploads.py:100  delete_document_file()
  -> os.remove(full)          ← **它會真的刪掉實體檔**
  -> 回傳「移除該筆之後的陣列」 ← 而我們用資料表，不是 JSON 陣列
```

⇒ `JV3` 的刪除**自己寫**，只做 `UPDATE`。
☠️ 這一條要寫在程式碼註解裡：那支 helper 名字正好、簽章也接近，
**下一個人會很自然地拿它來用**，而後果是 bytes 沒了 —— 一個無聲的違裁。

### 為什麼「離開草稿不可刪」（A-2 判定，A 採納）

```
① 《商業會計法》§38：憑證 ≥5 年，起算「年度決算程序辦理終了後」
② case_extra_expenses.py:633 逐字：「刻意不支援刪除已核准的既有附件：
   已經被簽核人看過、已計入成本的憑證不該被單方面移除」 ⇒ 既有慣例同向
③ 送審後可刪 = 簽核人看過的東西可以在他不知情時消失
```

🔑 **「不可刪」比「刪除要簽核」更嚴，而且不需要新的簽核流程**
——少一條流程就少一處會壞的地方。

### ⚠️ 裁定 ② 堵住的那個洞

```
archive.py:1027 _mirror_uploads()  「鏡像只增不減——即使來源檔案被刪除，
                                    鏡像裡的舊副本仍保留」
```

⇒ 已進雲端鏡像的檔案，刪了也還在 ✅
☠️ **而當天上傳、當天刪掉的檔案從來沒被鏡像過** ⇒ 硬刪等於不可復原。
⇒ 裁定 ② 保留 bytes，正是為了這一段空窗。

---

## §6 端點（路徑照 `§160` 定案）

```
POST   /api/vouchers/{voucher_id}/attachments              上傳／帶入
DELETE /api/vouchers/{voucher_id}/attachments/{file_id}    軟刪（僅草稿）
GET    /api/vouchers/summary-sources                       來源清單（JV3＋JV7 共用）
```

**權限**：一律 `require_any_module(user, ("cashier","finance"), "傳票")`
——與 `vouchers.py:39` **同一道閘**，不要另立。
☠️ 只用 `_require_user()` ＝ 任何登入者讀得到全公司會計憑證，而畫面上看不出來。

**`POST` 兩種形態，走同一支**

```
multipart files=[...]                        => 當場上傳，source_type=''
json {"picks":[{type,docNo,fileId},...]}     => 帶入，後端自己去來源拿檔複製
```

⚠️ **帶入不可以讓前端傳路徑進來** —— 那等於開一個任意檔案讀取。
⇒ 只收 `(type, docNo, fileId)`，路徑由後端依 `§3` 表自己組。

**檔案限制沿用既有**：`.jpg/.jpeg/.png/.pdf`，單檔 20MB
（`helpers/uploads.py:22-23`）。⚠️ 不要在這裡放寬，**三處共用同一份常數**。

---

## §7 裁定 ③：加 `pypdf`，供 `衍-1`（與附件合併輸出）使用

```
PDF 產生 = Edge Headless --print-to-pdf（pdf_gen.py:1663）
⇒ Edge **只能把 HTML 印成 PDF，不能合併既有 PDF**
```

| 附件型別 | 合併做得到嗎 | 代價 |
|---|---|---|
| jpg／png | ✅ 做得到 | 圖片 `<img>` 進同一份 HTML，Edge 一次印出。**零新套件** |
| pdf | ❌ 做不到 | 要新增套件 ⇒ **正式機要裝一個新相依** |

### ✅ `pypdf` 的實查（A-2 查 PyPI，2026-09-23）

```
最新版        6.19.0
輪子          pypdf-6.19.0-py3-none-any.whl   ⇒ **純 Python，無 C 擴充**
requires      typing_extensions>=4.0  **僅 Python < 3.11**
本機 Python   3.11.15
⇒ 在這個環境下 pypdf 的轉移相依是 **0 個**
requires_python  >=3.9
```

📌 選 `pypdf` 不選 `pymupdf` 的理由成立且已驗證：`pymupdf` 有 C 擴充，
`pypdf` 是 `py3-none-any`，正式機安裝風險低。

### 🔴 `pypdf` 是 **`JV5` 的相依，不是 `JV3` 的** —— `JV3` **不動** `requirements.txt`

`JV3` 是附件上傳／帶入／刪除，**一行都用不到 `pypdf`**；用到它的是 `JV5`
的合併輸出。**相依跟著消費者走**（A 2026-09-23 裁定）。
🔑 理由不是潔癖：相依寫在這裡的話，「若 `JV5` 延後就要一起延後」是一條
**靠人記得**的規則 —— 而放對地方就不需要記得。

⇒ 本節只留給 `JV5` 的那份查證結果（上面那塊），以及它動 `requirements.txt`
時必須遵守的這一條：

```
☠️ **requirements.txt 必須維持純 ASCII**
   檔內 HC2a 逐字：pip_audit 用系統編碼（此機 cp932）讀它，
   **一個 CJK 註解就讓整個弱點掃描從來沒跑過，而且是靜默的**
   ⇒ 加的那一行若要註解，寫英文，或不寫
📌 宣告用範圍不要釘死版本：pypdf>=6.0.0（〈版本適配：不可變成孤兒〉）
📌 正式機要重跑 pip install -r ⇒ DEPLOY.md 要提到多一個套件
```

---

## §8 驗收（`AC1`：後端＋前端＋頁面三者皆備才算完成）

```
後端 ① POST 當場上傳 -> 檔案落地 ＋ 表裡一列 ＋ path **不含** voucher_no
     ② 退回升版後（no 變 -R1）**同一批附件仍讀得到**          ← 防 §1
     ③ 草稿 DELETE -> deleted_at 非空、清單不再列出它，
        **且實體檔仍在**（裁定 ②）                            ← 防誤用 helper
     ④ 非草稿 DELETE -> 403，且 deleted_at **仍為空**
        （反向控制：不是只看回應碼，要看它真的沒動到資料）
     ⑤ 帶入後刪掉來源附件 -> 傳票這邊**仍讀得到**              ← 防 §4
     ⑥ 作廢重開 -> 新單附件筆數 == 原單未刪筆數，
        且新舊 file_id **不相同**、實體檔是兩份                ← 防 §1 裁定 ①
     ⑦ picks 傳一個不屬於 §3 九類的 type -> 400（不是 403、不是 500）
     ⑧ voucher_attachments 有進 _daily_backup_tables()
前端 ⑨ 上傳／帶入／刪除三個動作都**打得到 API**（不是骨架）
頁面 ⑩ voucher.html 看得到附件清單，且非草稿時刪除鈕**不存在**（不是 disabled）
```

⚠️ **②③⑤⑥ 是這份規格的核心。其他題綠了而它們紅 ＝ 沒做到。**
☠️ 而 2026-09-23 05:0x 實測：9 支傳票測試檔有 **7 支打 0 支 API**（直接叫 helper）
⇒ 本項驗收題**必須經由 `client.post/get/delete`**，不可以直接叫 helper。
🔑 那正是「10 支規則只有 2 支有 router 呼叫端、而測試全綠」的成因。

### ☠️ 寫這些題之前先看這一條：**不存在的路由回 405，不是 404**

```
main.py:657  app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True))
             ⇒ 這一行吃掉**所有**沒被 router 接走的路徑
             ⇒ StaticFiles 只處理 GET/HEAD
             ⇒ **POST／PUT／DELETE 到一個還沒實作的端點 => 405**
```

而 405 的回應內容是 `{"detail":"Method Not Allowed"}` ⇒

```python
assert "不平衡" not in r.text        # 端點還不存在時**永遠成立** ⇒ 假綠燈
assert r.status_code != 404          # 405 != 404 ⇒ **擋不到**
```

📌 這不是假設：`JV1` 的 `_post_action` 2026-09-23 就是這樣漏掉的（C 已修）。
⇒ **本節 ③④⑦ 三題（DELETE／POST 錯誤型別）在 B 接上端點之前一定要先確認
它們是紅的**，而且判斷「紅得對不對」要看**回應碼不是 405**。
🔑 一律先斷言 `r.status_code in (200, 400, 403)`，再去看內容。

---

## §9 我沒做的

```
✗ 沒有跑過任何測試（撰寫時在凍結期）
✗ §3 那九處的 metadata 欄位名，我讀的是呼叫端上下文，**沒有逐一開 DDL 對**
✗ 沒有量既有九處附件的實際筆數／總容量
  ⇒ 複製策略（§4）＋作廢重開複製（§1）的儲存成本**未估**，A 明著接受
✗ pypdf 我查的是 PyPI metadata，**沒有實際安裝或跑過合併**
✗ 參考版面那張 PDF **沒有文字層**（見 §103b）⇒ 版面文字是渲染讀的，不是擷取的
```
