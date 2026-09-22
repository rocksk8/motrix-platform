> 🔴 **這一份是施工圖：單一版本、無修訂層。照這一份做。**
> 修訂過程（六層，含被推翻的版本）在 `SPEC-VOUCHER-HISTORY.md`。
> ⚠️ **不要照 HISTORY 實作** —— 它的三個 DDL 區塊是被推翻的那一版（`§111`）。

# 傳票 —— **定稿段（施工圖）**
> A-2 2026-09-23 00:4x ／ migration **v95 起** ／ 基準 `ad9945d`
> 🔴 **本檔沒有修訂層。決議過程在 `SPEC-VOUCHER-HISTORY.md`，兩者物理分離。**
> ☠️ 上一行原本寫 `SPEC-VOUCHER.md`（**指向它自己**），是 A 落 repo 時改名而沒跟著改的——
>    留著，因為它是〈訊息裡點名檔案會被改名反轉〉那一條的第二個實例。
> ⚠️ 判準：**本檔不得出現任何一個被推翻過的字。** 有衝突時以本檔為準。

---
# 一、狀態機
```
草稿 ──送審──▶ 待審核 ──簽核──▶ 簽核中 ──簽核──▶ 已核准 ──過帳──▶ 已過帳 🔒
  ▲                                              │
  └──── 退回修改（清除簽核 ＋ 單號升版 -Rn）◀─────┘
```
```
狀態值    "草稿" / "待審核" / "簽核中" / "已核准" / "已過帳"
可編輯    **只有 "草稿"**
已核准    簽核走完（製票／覆核／主管三格都要簽），**帳還沒動** ⇒ 仍可退回
已過帳    帳已動 ⇒ **不可退回，只能作廢重開**
```
**單號**：`YYYYMMDD-NNN[-Rn]`（例 `20260330-006-R2`）
```
退回時 n 從**現有最大值**解析後 +1，**不可在字串尾巴直接接 -R1**
❌ 不可沿用 quotations.py:164（寫死 MQ- 前綴；實跑會產生 -R1-R1，而 UNIQUE 擋不住）
⚙️ 反向控制：餵一個已有 -R1 的單號 ⇒ **必須產生 -R2**
```

---
# 二、DDL

## 2.1 `vouchers`
```sql
CREATE TABLE vouchers (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    voucher_no              TEXT    NOT NULL,              -- YYYYMMDD-NNN[-Rn]
    voucher_date            TEXT    NOT NULL,              -- 可編輯（**僅草稿**），預設建檔當天（使用者 2026-09-23 改裁）
    category                TEXT    NOT NULL DEFAULT '轉',  -- 傳票別，沿用 T100 voucherCategory
    summary                 TEXT    NOT NULL DEFAULT '',   -- 單據層摘要
    status                  TEXT    NOT NULL DEFAULT '草稿',
    created_by              TEXT    NOT NULL,              -- **製票**（版面三格之一）
    posted_at               TEXT    NOT NULL DEFAULT '',
    posted_by               TEXT    NOT NULL DEFAULT '',
    posted_with_warning     INTEGER NOT NULL DEFAULT 0,    -- 帶警示仍過帳
    posted_warning_snapshot TEXT    NOT NULL DEFAULT '',   -- **當時警示的內容**，不只是旗標
    voided_at               TEXT    NOT NULL DEFAULT '',
    voided_by               TEXT    NOT NULL DEFAULT '',
    void_reason             TEXT    NOT NULL DEFAULT '',
    supersedes_no           TEXT    NOT NULL DEFAULT '',   -- 本張取代了哪一張
    ledger_confirmed        INTEGER NOT NULL DEFAULT 0,    -- 0 ⇒ 要進首頁「未確認」計數
    custom_fields           TEXT    NOT NULL DEFAULT '{}', -- 只在「草稿」可新增
    created_at              TEXT    NOT NULL,
    updated_at              TEXT    NOT NULL
);
CREATE UNIQUE INDEX idx_vouchers_no     ON vouchers(voucher_no);
CREATE INDEX        idx_vouchers_status ON vouchers(status);
CREATE INDEX        idx_vouchers_date   ON vouchers(voucher_date);
CREATE INDEX        idx_vouchers_ledger ON vouchers(ledger_confirmed);
```
🔁 `voucher_date` **裁示已翻面**（2026-09-23，使用者）：

```
舊裁示  「傳票日期由系統發」 => A-2 讀成「建檔當天且不可改」
新裁示  **日期可選，預設今天**
```
☑️ 成因：使用者當初答的是「號碼／日期／狀態由誰產生」，
   **不是「能不能補登上個月」** —— 而後者是會計的日常（月結補登）。
🔑 而這一項日後才改會牽涉已開出的傳票 => **所以現在問是對的。**

⚙️ 實作要求：
```
預設值   建檔當天（使用者不用自己打）
可編輯   僅限「草稿」狀態（與其他欄位同一個規則）
留痕     改過日期要進 voucher_edit_log（改前→改後）
⚠️ 未來   「月結關帳後不可再補登」是下一步，**本輪不做**（沒有關帳這個功能）
```

## 2.2 `voucher_lines`
```sql
CREATE TABLE voucher_lines (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    voucher_id               INTEGER NOT NULL REFERENCES vouchers(id),
    line_no                  INTEGER NOT NULL,
    account_code             TEXT    NOT NULL REFERENCES account_items(code),
    account_name_snapshot    TEXT    NOT NULL DEFAULT '',  -- **過帳時凍結**（版面要印）
    summary                  TEXT    NOT NULL DEFAULT '',  -- per-line 摘要，**產生當下凍結**
    summary_template_id      INTEGER NOT NULL DEFAULT 0,   -- 追溯：用了哪個範本
    summary_template_version INTEGER NOT NULL DEFAULT 0,   -- 追溯：哪一版
    debit                    INTEGER NOT NULL DEFAULT 0,   -- 兩欄式，沿用 T100
    credit                   INTEGER NOT NULL DEFAULT 0,   -- 其中一欄為 0
    dept_code                TEXT    NOT NULL DEFAULT '',
    source_type              TEXT    NOT NULL DEFAULT '',  -- 決定性連結：型別
    source_id                INTEGER NOT NULL DEFAULT 0,   -- 決定性連結：主鍵
    source_amount_snapshot   INTEGER NOT NULL DEFAULT 0,   -- 帶入當時的來源金額（警示比對基準）
    counterparty             TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX idx_vlines_voucher ON voucher_lines(voucher_id, line_no);
CREATE INDEX idx_vlines_account ON voucher_lines(account_code);
CREATE INDEX idx_vlines_source  ON voucher_lines(source_type, source_id);
```

## 2.3 `voucher_edit_log`
```sql
CREATE TABLE voucher_edit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    voucher_id   INTEGER NOT NULL REFERENCES vouchers(id),
    changed_by   TEXT    NOT NULL,
    changed_at   TEXT    NOT NULL,
    changes_json TEXT    NOT NULL DEFAULT '[]'   -- **改前 → 改後**
);
CREATE INDEX idx_vel_voucher ON voucher_edit_log(voucher_id, changed_at);
```
⚠️ `DEFAULT '[]'` 擋不住空紀錄 ⇒ **「缺改前值就寫入失敗」必須在應用層擋。**

## 2.4 範本（**兩張表，不是一張**）
```sql
CREATE TABLE voucher_templates (            -- 本體，id 穩定
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    created_by  TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);
CREATE TABLE voucher_template_versions (    -- 每次編輯新增一列，**不覆蓋**
    template_id INTEGER NOT NULL REFERENCES voucher_templates(id),
    version     INTEGER NOT NULL,
    body        TEXT    NOT NULL,
    edited_by   TEXT    NOT NULL,
    edited_at   TEXT    NOT NULL,
    is_current  INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (template_id, version)
);
```
📌 **拆兩張的理由**：`AUTOINCREMENT` 只能用在單一 `INTEGER PRIMARY KEY`，
   而 `(id, version)` 複合主鍵下 id 無法自動產生 ⇒ 本體表管 id，版本表管歷史。

## 2.5 TRIGGER（兩支，建在 `account_items` 上）
```sql
CREATE TRIGGER account_items_referenced_code_no_update
BEFORE UPDATE OF code ON account_items
WHEN EXISTS (SELECT 1 FROM voucher_lines WHERE account_code = OLD.code)
BEGIN SELECT RAISE(ABORT, '此科目已被傳票引用，代號不可修改'); END;

CREATE TRIGGER account_items_referenced_no_delete
BEFORE DELETE ON account_items
WHEN EXISTS (SELECT 1 FROM voucher_lines WHERE account_code = OLD.code)
BEGIN SELECT RAISE(ABORT, '此科目已被傳票引用，不可刪除'); END;
```
🔑 **它們存在的理由（寫進註解，否則日後會被正當地刪掉）**：
> `account_code` 已宣告 `REFERENCES`，而 SQLite 的外鍵強制**隨時可能是關的**：
> `db.py:151` 的 `PRAGMA foreign_keys=ON` **包在 `try/except: pass` 裡**，
> 而 `db.py:230` 的 demo 重置路徑**明著關掉它**。
> ⇒ **這兩支 TRIGGER 防的是「FK 被關掉的那一條路」，不是「SQLite 不強制」。**
⚙️ 正對照：對 `source='custom'` 且**未被引用**的科目改 code ⇒ **必須成功**。

---
# 三、附件
```
路徑慣例   uploads/{subfolder}/{**voucher_id**}/{uuid}{ext}
           ⇒ 呼叫 save_document_files(subfolder, **str(voucher_id)**, …)
           ⇒ **不必改 helper**
🔴 不可綁 voucher_no：退回會升版成 -Rn ⇒ 附件跟丟
📌 依據：「會升版的單號」與「綁單號的附件」在本專案從未同時出現過 ⇒ 無前例可沿用
```

---
# 四、摘要（範本 ＋ 來源）
```
摘要 = f(範本, 來源)，**產生當下凍結**：存文字本身 ＋ template_id ＋ template_version
⚙️ 佔位符必須在封閉清單內，**儲存範本時**就驗證，不在就拒絕儲存並指出是哪一個
   （不可等到產生摘要時才發現 ⇒ 壞範本會每次印空白，看起來像使用者沒填）
```
**封閉清單（起始版，只增不刪；刪前要查有沒有範本在用）**
```
發票號／發票日期／單號／客戶名稱／廠商名稱
未稅／稅額／含稅／本行金額
單據日期／上傳檔案日期
案件編號／專案名稱
```

---
# 五、警示（三個來源）
```
① 來源單據被改  比對 source_amount_snapshot vs 來源現值
                過帳前 ⇒ **提示，不阻擋過帳**；過帳後 ⇒ 不再比對
② 範本被改      **編輯者要被告知「目前有 N 張傳票在用這個範本」**（決定前，不是事後）
③ 傳票被改      ⇒ voucher_edit_log
```
⚙️ 「看到警示仍然過帳」⇒ `posted_with_warning=1` ＋ `posted_warning_snapshot` 存**當時警示的內容**。

---
# 六、過帳前檢查
```
① SUM(debit) == SUM(credit) 且 > 0       ⇒ 不平衡**拒絕過帳並說出差額**
② status == '已核准'（簽核三格都簽）
③ 寫入 account_name_snapshot（凍結）
④ 法定副本：ERP db 先寫（過帳成立）→ 法定本後寫
   失敗 ⇒ ledger_confirmed=0 ＋ 進補寫佇列，**不阻擋過帳**
   🔴 **未確認筆數必須出現在使用者每天會看的地方**（少了它，丙案退化成乙案）
```
⚙️ 合計列：畫面與匯出**必須用同一支函式算**（§37a 同源同單位）。

---
# 七、Migration
```
v95  vouchers ／ voucher_lines ／ voucher_edit_log ／
     voucher_templates ／ voucher_template_versions ／ 索引 ／ 兩支 TRIGGER
```
⚠️ 前置（交不出來就不收）：**改任何已存在的 migration 前，先查三個持久化 .db
   的目標表是否存在，並把輸出貼進交付。** 任一存在 ⇒ 停手，改成加新的一支。

---
# 八、與 demo 重置的關係
```
🔴 account_items **排除在 demo 重置的清除清單外**（法定 547 筆是系統資料，不是使用者資料）
⚙️ 守門用笛卡兒積：**每一張表必須落在「使用者資料」或「系統資料」其中一邊，互斥且窮盡**
   缺一張 ⇒ 紅 ／ 兩邊都有 ⇒ 紅 ／ 多出一張不存在的表 ⇒ 紅
⚠️ 驗收：**demo 必須連續登入兩次**（第一次不會發作）
```

---
# 九、未查（A 已明示不必補）
```
✗ 9–11 支 router 的狀態**轉移**是否一致（只比對過字串）
✗ 分層簽核的既有 approval 表，傳票要不要沿用
✗ custom_fields 用 JSON 是否與「匯出照當下結構產生」相容
```
