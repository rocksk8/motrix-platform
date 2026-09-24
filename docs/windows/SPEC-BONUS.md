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
✅ **⇒ 沒有 `netProfit` ⇒ 拒絕產生獎金單。**
### 🔴 而拒絕訊息**必須講出路**，不可以只說「沒有淨利」
```
副作用  **舊案就永遠發不了獎金**，而使用者看不出路在哪裡
出路    settlement.html:944-948 是**儲存時算**的
        ⇒ ⇒ **重新儲存那一案的精算，就會補上 netProfit**
```
📌 訊息要寫成：「這個案件的精算是舊格式（沒有淨利欄位）。
   **請重新開啟並儲存一次該案的精算，系統會自動補算。**」
🔑 與 `RAISE(ABORT)` 那一條同源：**那句話是使用者唯一看得到的東西。**
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
    -- 作廢／重開鏈（與傳票 §35 同一條原則：作廢留痕、重開一張）
    voided_at             TEXT    NOT NULL DEFAULT '',
    voided_by             TEXT    NOT NULL DEFAULT '',
    void_reason           TEXT    NOT NULL DEFAULT '',
    supersedes_id         INTEGER NOT NULL DEFAULT 0,   -- 本筆取代了哪一筆
    created_by            TEXT    NOT NULL,
    created_at            TEXT    NOT NULL,
    updated_at            TEXT    NOT NULL
);
-- 🔴 **部分**唯一索引：一個案件同時只能有一筆**有效**獎金，而作廢後可以重開
CREATE UNIQUE INDEX idx_bonus_awards_case_active
    ON bonus_awards(quote_no) **WHERE voided_at = ''**;
```
## 🔴 而這個索引落實的**不是**「依案件獨立發放」，兩者要分開講
```
「不做跨案件結算」＝ **一筆獎金不可橫跨多案**
                    ⇒ 靠的是 `quote_no` 是**單一欄位**（不是清單），**不是唯一性**
這個部分索引強制的 ＝ **一個案件同時只能有一筆有效獎金**
```
☠️ 若寫成完全唯一（無 WHERE）⇒ **發錯了改不了** ——
   而傳票那邊有完整的作廢重開鏈（使用者親口裁的）
   ⇒ **兩個模組對「錯了怎麼辦」會不一致，而獎金還會開傳票。**
✅ 實跑驗證（A）：第二筆未作廢 ⇒ IntegrityError／作廢後重開 ⇒ OK／再一筆 ⇒ IntegrityError
   ⇒ **有效 1 列、歷史留著。**

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
sales_person / sales_person_id   業務           ← 使用者裁示的兩個來源之一
**case_stages.assigned_to**      各執行階段負責人（JSON 陣列）← 另一個
```
### 🔴 `owner`／`engineer` **已移除**（2026-09-23，B 實查兩個欄位都不存在）
```
本規格 §一⑤ 的使用者裁示逐字只有兩個來源：
  業務獎金 → sales_person ／ 專案執行獎金 → case_stages.assigned_to
⇒ ⇒ `owner`／`engineer` 是**本規格 §四 自己加的**，使用者從未提過
⇒ 而 B 實查 quotations：**兩個欄位都不存在**
```
📌 **留著這一列，不當沒發生過**：代價歸屬掃描當時就標了這一格
   （「`owner`／`engineer` 無對應項目 ｜ **沒有人** ｜ 🔴 不是代價，是還沒有人定義」）
   —— **那個標註現在成真了**，而它是掃描第一次抓到自己憑空加的東西。

### ⚠️ 已知的未來來源，**本輪不接**
```
quotations 另有 **assigned_user_ids**（A 補查）
⇒ 它可能是「這個案子有哪些人」的第三個來源
⇒ 🔴 而**沒有人裁示過它要不要進獎金** ⇒ 本輪不接，不自己決定
```
### ⚠️ 兩個實作約束
```
① db.py:1471  case_stages.assigned_to TEXT NOT NULL **DEFAULT '[]'**
   ⇒ 讀到空陣列 ⇒ 🔴 **拒絕產生該項目的撥付並標「無可發放對象」**
   ⇒ **不可靜默算成 0 筆，也不可把金額併給別的項目**
② db.py:1459 註解逐字：「assigned_to/depends_on **刻意維持 JSON text 欄位**，
   不再往下正規化成 join table」⇒ **彙整不能用一句 SQL JOIN，要在應用層逐筆解析**
```
📌 上面那一節已處理 `owner`／`engineer`。**本施工圖不替使用者決定任何來源。**

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
      ⇒ 落實方式：`bonus_awards.quote_no` 是**單一欄位**，不是清單
```

---
# 九、⚙️ 代價歸屬掃描（定稿前跑，**兩問**）
> 第一問：**誰決定的**（答不出名字 ⇒ 移出施工圖）
> 第二問：**這個決定的副作用列過了嗎**（「我比較過三個選項」不算 —— 那是選擇的理由）

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
✗ bonus 的 migration 版本號（等 A 指派，傳票用掉 v95）
✗ 「最高管理者」是否沿用 superadmin（A 已 🟡 預設沿用，未經使用者確認）
✗ 營運報表現行可見範圍的實際實作（只知道不可沿用，未讀它怎麼寫的）
```

---

# 十一、🔴 2026-09-24 重新設計（使用者：「上一次開發的內容我無法接受」）——**本節取代前面各節的流程與畫面**

> 使用者逐字：「獎金分潤像是案件管理的頁面，已經精算完成的顯示在內，幾個狀態，未精算、已精算、草稿、待審核、待撥放、已撥放，到待發放才讓非超級管理員且在發放名單的人員看到，假設精算完成這一案是賺100元，總淨利的10%(可改但預設10%)，這10%會撥給業務、專案、後勤人員(複數人員可設立群組)，最終計算沒人可領多少金額，會顯示每人比例，未撥放前超級管理員都可退回修改」
>
> 表單裁示（同日）：三類分配「預設比例，每案可調」；類內「預設平均，可改個人比例」；審核「走簽核設定；出納標已發放」；舊功能「重做成新流程，舊資料保留唯讀」；預設比例「50／30／20」；名單「如案件管理有則先自動帶入，有些早期案件沒有則可以手動指定人或群組」；尾差「尾差留公司」；比率「全域預設 10%，每案可改；虧損不發」。

## 11.1 頁面：以案件為中心（像案件管理）
- 左側案件清單（可搜尋、依狀態篩選），右側該案的獎金明細；狀態徽章：**未精算／已精算／草稿／待審核／待發放／已發放**（使用者口語「撥放」＝發放）。
- 未精算、已精算由案件精算狀態推得（`settlement.status`），不另存；草稿之後才有獎金分潤單。
- 淨利 ≤ 0 的已精算案件顯示「無獎金」，不能建立草稿。

## 11.2 計算（金額整數、比例用基點，沿用 §五）
```
獎金池 = floor(該案精算淨利（settlement.summary.netProfit 已存值，§二禁令照舊）× 比率)   比率預設 10%（全域設定），草稿可逐案覆寫
三類   = 業務 50%／專案 30%／後勤 20%（全域預設，草稿可逐案調；合計須 100%）
類內   = 預設平均；草稿可逐人調比例（類內合計須 100%）
每人   = floor(獎金池 × 類比例 × 個人比例)      ⇒ 尾差留公司（合計 ≤ 獎金池，差額顯示為「尾差（留公司）」）
顯示   = 每人金額＋占獎金池的比例
```
⚠ 這裡的 10% 是**獎金比率**，與 `settlement.html` 的管理費 10%／公益 1% 無關，不可共用常數。

## 11.3 名單
- 業務＝報價單業務人員；專案／後勤＝案件管理中已設定的角色（`caseRecord.roles`，實作前讀碼確認對應）——**有就自動帶入**。
- 早期案件沒有角色 ⇒ 草稿時手動指定人或**群組**（沿用 `bonus_groups`／`bonus_group_members`）；任何案件草稿時都可增減。
- 某一類沒有人 ⇒ 那一類的金額不發（留公司），畫面明示。

## 11.4 流程與權限
```
已精算 ──建立──▶ 草稿 ──送審──▶ 待審核 ──簽核完成──▶ 待發放 ──出納標記──▶ 已發放
                  ▲______________ 最高管理者退回（已發放前任何時點）____________|
```
- 建立／編輯草稿／送審／退回：最高管理者。退回回到草稿，留編寫紀錄（沿用 `bonus_award_edit_log`＋不可刪 TRIGGER）。
- 審核：走共用簽核引擎（`bonus_approval_flow`；設定頁要能設到——N8① 一併修）。
- 已發放：**出納**標記，記日期與操作者；已發放後不可退回。
- **可見性**：待發放之前只有最高管理者看得到；**待發放起**，發放名單上的人只看得到**自己那一列**（金額＋比例）。過濾在後端（§七原則照舊）。

## 11.5 舊功能
- 舊的「獎金項目＋分潤單」停止新增，舊資料保留**唯讀**（舊入口可查閱）；新頁面取代側欄入口。
- 入帳兩筆傳票（§六）與「應付獎金」科目（會計師三題之一）**不在本期**，已發放只記狀態。

## 11.6 驗收（題先紅）
- 淨利 100、比率 10%、50/30/20、業務 1 人／專案 2 人／後勤 3 人 ⇒ 每人金額與尾差逐一斷言。
- 可見性：待審核時一般人看不到；待發放時名單上的人只看到自己那一列（API 回應裡沒有別人的值）。
- 最高管理者在待發放退回 ⇒ 回草稿、留紀錄；已發放後退回 ⇒ 擋。
- 早期案件無角色 ⇒ 手動指定群組可建立；淨利 ≤ 0 ⇒ 不能建立。
- 使用者可見的改動附頁面實測。

## 11.7 補充裁示（2026-09-24，使用者表單）
- **名單**：業務＝報價單業務人員（`quotations.sales_person`）；**專案＝案件「執行負責」**（`caseRecord.roles.executor`）；**後勤不自動帶入**，草稿時手動指定人或群組。roles 存的是顯示名稱 ⇒ 轉 username；同名或查無 ⇒ 不帶、標「請手動指定」。原文：「專案＝執行負責，後勤手動指定」。
- **類內平均**：同類每人 `floor(類金額／人數)`，零頭留公司。原文：「每人一樣多，零頭留公司」。
- **舊分潤單**：原文「舊的都是開發機測試用，直接作廢」⇒ 新頁面不理會舊單、不做唯讀舊畫面；舊寫入端點回 410。**不以 migration 作廢任何資料**（migration 會在正式機執行）。
- **migration**：新表三張用 v112（v111 歸 JV36），撞號順延。
- **W1（簽核人可見性）**：使用者原文「簽核人只能是最高管理者」⇒ 送審時簽核鏈（含代理人解析）出現非 superadmin 即擋（400）；設定頁提示此限制；§11.4 可見性照字面。
