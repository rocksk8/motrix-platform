# 獎金分潤 `FN2` —— **施工圖**
> A-2 2026-09-23 01:3x ／ 基準 `c9c29b3` ／ 落點 `docs/windows/SPEC-BONUS.md`
> 🔴 **本檔沒有修訂層。** 判準：**不得出現任何一個被推翻的字。**
> ⚠️ 誰在等：**B**（傳票 ④⑥ 交完就是它）

---
# 一、使用者原話（逐字，不改寫）
```
「新開發案件精算完結後，會有獎金分潤的衍生，一樣加在營運報表那個模組獨立」
「項目可由**最高管理者**定義，由案件**結案的最終金額**按比例去撥付」
「總金額比例由最高管理者定義，**人員撥付比例也是**，並可制定成**模板**，**依案件獨立發放**」
「獎金分潤子模組是依據案件的**實際獲利**去拆比例給參與者」
```
## 已裁四項（不要重問）
```
① 基數 ＝ **淨利**   ② 負數 ⇒ **當 0 不發**
③ 可見 ＝ **管理者＋本人**   ④ 參與者 ＝ **只含內部員工**
⑤ 人員來源 ⇒ **每個獎金項目各自綁一個來源**（業務獎金→sales_person／
   專案執行獎金→case_stages.assigned_to）；同一人身兼兩職領兩份
```

---
# 二、🔴 基數：`netProfit` 的**已存值**，而它有兩條禁令

## 2.1 算式（實查，貼行號）
```javascript
frontend/pages/settlement.html
:944  const grossProfit     = quotedPretax - totalActualCost
:946  const adminCost       = Math.round(quotedPretax * 0.10)   // **案件內，非公司當期**
:947  const charityDonation = Math.round(grossProfit * 0.01)
:948  const netProfit       = grossProfit - adminCost - charityDonation
```
🔑 `adminCost` 是**該案報價未稅的 10%** ⇒ **完全是案件本身的函數**，
   與公司當期花了多少錢無關。（這一點曾被講錯過一次，故貼原始碼。）

## 2.2 🔴 禁令一：**不可以自己重算**
```
10% 與 1% 這兩個係數只寫在 settlement.html:946-947
後端沒有第二份實作（pdf_gen.py:2641 與 routers/reports.py:2013 都是**讀已存值**）
⇒ 獎金模組若自己乘一次 ⇒ **第三份實作，而三份一定會分岔**
✅ 一律取 settlement.summary.netProfit 的已存值
```

## 2.3 ☠️ 禁令二：**不可以退回用 `grossProfit`**（A 未提，A-2 實查）
```
routers/reports.py:338 註解逐字：
  「**Fallback to gross fields for legacy settlements saved before netProfit was recorded.**」
:340  int(settle.get("netProfit") or settle.get("grossProfit") or 0)
```
```
⇒ **舊精算資料沒有 netProfit** ⇒ reports.py 退回用毛利（對報表是合理的折衷）
☠️ 而獎金若照抄那個 fallback：
   毛利 > 淨利（差 adminCost ＋ charityDonation）⇒ **獎金會發多**
   而它**不報錯，畫面上每個數字都正常**
```
✅ **⇒ 沒有 `netProfit` ⇒ 拒絕產生獎金單，並說出「這個案件的精算沒有淨利欄位」。**
### ⚠️ 而這一條在開發機上永遠不會被觸發
```
$ 開發機 26 張報價單／12 張有 settlement.summary／**12 張都有 netProfit／0 張是舊資料**
⇒ **開發機沒有樣本** ⇒ 而 reports.py 那段 fallback 的存在就是「曾經有過」的證據
⇒ ⇒ ⚙️ **那一題必須用假資料造一筆「只有 grossProfit」的精算來驗**
```

---
# 三、資料表（migration 版本由 A 指派，**不要沿用本檔猜測**）

## 3.1 `bonus_items`（獎金項目，最高管理者維護）
```sql
CREATE TABLE bonus_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,          -- 業務獎金／專案執行獎金／…
    person_source TEXT    NOT NULL,          -- 🔴 **必填**：人員來源（見 §四）
    sort_order    INTEGER NOT NULL DEFAULT 0,
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_by    TEXT    NOT NULL,
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL
);
```
⚙️ **`person_source` 為空不准儲存**（不是存了再算出 0 人）。

## 3.2 `bonus_templates` ＋ `bonus_template_versions`（兩張，理由同傳票範本）
```sql
CREATE TABLE bonus_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE bonus_template_versions (
    template_id INTEGER NOT NULL REFERENCES bonus_templates(id),
    version     INTEGER NOT NULL,
    body_json   TEXT    NOT NULL,   -- {項目: 總額比例, 人員比例規則…}
    edited_by   TEXT    NOT NULL,
    edited_at   TEXT    NOT NULL,
    is_current  INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (template_id, version)
);
```
📌 拆兩張的理由：`AUTOINCREMENT` 不能用在複合主鍵（與傳票範本同一個理由）。

## 3.3 `bonus_awards`（每案一筆，**套用當下凍結**）
```sql
CREATE TABLE bonus_awards (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_no              TEXT    NOT NULL,       -- 案件
    base_amount           INTEGER NOT NULL,       -- **凍結的 netProfit**
    base_source           TEXT    NOT NULL DEFAULT 'settlement.summary.netProfit',
    template_id           INTEGER NOT NULL DEFAULT 0,
    template_version      INTEGER NOT NULL DEFAULT 0,   -- 🔴 **凍結：改模板不影響已發放**
    status                TEXT    NOT NULL DEFAULT '草稿',
    voucher_no_accrual    TEXT    NOT NULL DEFAULT '',  -- 核定那筆傳票
    voucher_no_payment    TEXT    NOT NULL DEFAULT '',  -- 發放那筆傳票
    created_by            TEXT    NOT NULL,
    created_at            TEXT    NOT NULL,
    updated_at            TEXT    NOT NULL
);
CREATE UNIQUE INDEX idx_bonus_awards_case ON bonus_awards(quote_no);
```
🔴 `UNIQUE(quote_no)` 直接落實使用者的「**依案件獨立發放**」⇒ **不做跨案件結算。**

## 3.4 `bonus_award_lines`（每人一列）
```sql
CREATE TABLE bonus_award_lines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    award_id        INTEGER NOT NULL REFERENCES bonus_awards(id),
    bonus_item_id   INTEGER NOT NULL REFERENCES bonus_items(id),
    item_name_snapshot TEXT NOT NULL,          -- 凍結（項目可能改名）
    username        TEXT    NOT NULL,
    person_source_snapshot TEXT NOT NULL,      -- 凍結：這個人是從哪個來源來的
    total_pct       INTEGER NOT NULL,          -- 總額比例（基點，見 §五）
    person_pct      INTEGER NOT NULL,          -- 人員比例（基點）
    amount          INTEGER NOT NULL           -- 實際金額
);
CREATE INDEX idx_bonus_lines_award ON bonus_award_lines(award_id);
CREATE INDEX idx_bonus_lines_user  ON bonus_award_lines(username);
```

---
# 四、參與人員：**彙整，不是新建**（實查）
```
sales_person / sales_person_id   業務
owner                            案件擁有者
engineer                         工程師
**case_stages.assigned_to**      各執行階段負責人（JSON 陣列）
```
### ⚠️ 兩個實作約束
```
① db.py:1471  case_stages.assigned_to TEXT NOT NULL **DEFAULT '[]'**
   ⇒ 讀到空陣列 ⇒ 🔴 **拒絕產生該項目的撥付並標「無可發放對象」**
   ⇒ **不可靜默算成 0 筆，也不可把金額併給別的項目**
② db.py:1459 註解逐字：「assigned_to/depends_on **刻意維持 JSON text 欄位**，
   不再往下正規化成 join table」⇒ **彙整不能用一句 SQL JOIN，要在應用層逐筆解析**
```
📌 `owner`／`engineer` 目前**沒有對應的獎金項目** —— 那是「還沒有人定義」，
   **不是「決定不做」**。本施工圖不替使用者決定。

---
# 五、計算（**金額全部用整數，比例用基點**）
```
基數      base = settlement.summary.netProfit（已存值）
負數      base < 0 ⇒ **base = 0，不發**（使用者裁）
總額      pool = base × total_pct / 10000
個人      amount = pool × person_pct / 10000
尾差      **歸公司**（A 裁，未反對即生效）⇒ 不落在任何一個人身上
```
⚙️ **比例用基點（1/10000）而非浮點** —— 浮點相加不等於 1 是一個沒有錯誤訊息的缺陷。
⚙️ 守門：同一個 award 底下，各人 amount 之和 **≤ pool**，而差額必須等於尾差。

---
# 六、入帳：**兩筆傳票**（使用者裁）
```
核定   借 獎金費用   / 貸 **應付獎金**      ⇒ bonus_awards.voucher_no_accrual
發放   借 應付獎金   / 貸 銀行存款          ⇒ bonus_awards.voucher_no_payment
```
## 🔴 而「應付獎金」的科目**未決**（會計師三題之一）
```
⇒ 🔴 **不可以把科目代號寫死進 DDL 或程式碼**
✅ 存在設定裡（沿用 T100 六個欄位的形狀），**預設 2191 應付薪資**
   理由：預設值的判準不是「哪個比較好」，是「**猜錯時哪個比較好收拾**」
   —— 用法定科目，日後要拆出來是新增一個科目＋改設定；
      用自訂科目而會計師說不行，**已開出的傳票都指向一個不該存在的科目**
⚙️ 守門：設定值指向一個不存在／已停用的 account_item ⇒ 設定頁必須擋
```

---
# 七、可見性（使用者裁）
```
管理者  全部
本人    **只看得到自己那一列**（bonus_award_lines.username = 自己）
其他人  看不到
🔴 現行營運報表的可見範圍**不可沿用** —— 沿用＝全公司看得到每個人領多少
```
📌 「本人」是一條**規則**不是一個角色（§37c）⇒ 明著授予，不從角色推論。

---
# 八、範圍（寫死，免得開工時擴張）
```
做    營運報表底下的獨立子模組（與財務出納並列）
做    項目自訂／總額比例／人員比例／模板＋套用快照／依案件獨立發放
不做  **不碰精算既有邏輯**（只讀結果，不改它怎麼算）
不做  不做薪資單、不接薪轉、不碰勞健保
不做  **不做跨案件結算**（使用者明說「依案件獨立發放」）
```

---
# 九、⚙️ 代價歸屬掃描（定稿前跑，A-2 已跑）
| 代價／限制 | 誰決定的 | 判定 |
|---|---|---|
| 不做跨案件結算 | **使用者**（「依案件獨立發放」） | ✅ 真代價 |
| 負數當 0 不發 | **使用者** | ✅ |
| 尾差歸公司 | **A**（🟡 未反對即生效） | ✅ 有名字 |
| 沒有 netProfit 就拒絕 | **A-2**（本檔提出） | ⚠️ **要 A 核** |
| `owner`／`engineer` 無對應項目 | **沒有人** | 🔴 **不是代價，是還沒有人定義** ⇒ 已標明 |
| 「應付獎金」科目 | **未決** | 🔴 進提問清單，不寫死 |

---
# 十、⚠️ 未查
```
✗ 「結案的最終金額」是否就是 netProfit —— 使用者兩句話（「結案的最終金額」／
  「實際獲利」）我讀成同一件事，**而那是我的解讀**
✗ bonus 的 migration 版本號（等 A 指派，傳票用掉 v95）
✗ 「最高管理者」是否沿用 superadmin（A 已 🟡 預設沿用，未經使用者確認）
✗ 營運報表現行可見範圍的實際實作（只知道不可沿用，未讀它怎麼寫的）
```
