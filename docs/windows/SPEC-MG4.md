# `SPEC-MG4` · migration 的回填要回報，而**「寫進 log」不算回報**

> 座標：`e850e72`（工作樹：本檔為新增）
> 作者：視窗 A-2 ／ 2026-09-23
> 🔑 A 定調：**它與 `EM7` 是同一族 —— 落點要指出來。**

---

## §1 🔴 現成的實例，而**是我自己的規格造成的**

⚙️ B 已經照 `SPEC-QS1-a §4` 寫了 `_m103_bonus_award_lines_username`（`db.py:4305`，**工作樹未 commit**）。
它**完全照規格做了**：

```python
fk_count = 0; name_count = 0; kept = []
…
logger.warning("m103 bonus_award_lines 回填：經 FK %d 筆／經顯示名 %d 筆／未變更 %d 筆",
               fk_count, name_count, len(kept))
for rid, orig in kept:
    logger.warning("m103 未變更：id=%s username=%r（無法解析成帳號，原值保留）", rid, orig)
```

```
✅ 計數器有、N／M／K 有、K 逐列列名 —— **規格要的每一項都做到了**
🔴 而它全部寫進 `logger.warning`
```

> ### ☠️ 而 `EM7 §6` 今天剛量過：**`logs/server.log` 的消費端 = 0。**
> ### 🔑 ⇒ **我的規格造出了一個沒有人會看到的回報。**

```
📌 而這一格比 EM7 那一格更尖銳：
   EM7 是「**既有的碼**寫進 log 而沒有人看」
   MG4 是「**我剛寫的規格**要求寫進 log，而 B 照做了」
☠️ ⇒ 一個判準在 A 規格裡確立，而**沒有回頭套用到 B 規格**
🔑 ⇒ 這一件要交付的不只是 migration 的落點，
   是「**同一天學到的判準，要回頭掃一次自己已經交出去的規格**」
```

---

## §2 ⚙️ 母體：**30 支有寫入，而讀 `rowcount` 的 = 0**

### 三層切開（`ast` 掃 `db.py` 的 104 支 `_m*`）

```
🔴 回填（UPDATE 依現有資料的條件）= **14**
   _m006_hot_columns             _m007_fix_legacy_display_names
   _m008_fix_legacy_owner_names  _m009_migrate_legacy_visits
   _m010_sales_person_id         _m024_entity_codes
   _m047_invoice_vouchers_amount _m052_fix_stage_json_ids
   _m058_backfill_deal_won_at    _m059_fix_deal_won_at_from_audit_log
   _m074_webauthn_rp_id          _m083_backup_retention_policy
   _m084_backfill_role_bypass_modules                _m103_bonus_award_lines_username

🟡 兩者皆有 = **3**（_m051_case_stages_normalize／_m062_case_project_merge／_m090_quotation_location）

✅ 純種子（只 INSERT 固定內容）= **13**
   六支選型 guide ＋ _m094_load_account_items ＋ 其餘
   🔑 **不需要回報** —— 它要嘛成功、要嘛拋例外，沒有「條件不成立所以沒動」這種狀態
```

### 🔑 判準：**「條件不成立」是不是一個可能的結果？**

```
回填  `UPDATE … WHERE <條件>`  => **可能 0 筆匹配，而 SQL 完全成功**
種子  `INSERT INTO … VALUES`   => 要嘛寫進去、要嘛拋例外
```
📌 ⇒ 那正是 `QS1 §2` 分出來的**洞 B**（比對到 0 筆），
而**種子沒有洞 B**。

### ☠️ 而我第一把尺量出 **34**，差的 4 支是**幽靈**

```
_m043_notification_prefs   docstring 散文：「…so no separate UPDATE is needed」
_m093_account_items        docstring 的**對照表**：「UPDATE statutory -> BLOCKED」
                           ＋ `" BEFORE UPDATE ON account_items"`
_m096_account_item_active  註解裡的說明
_m095_vouchers             註解裡的**反例**：「INSERT INTO vouchers -> OperationalError（當場炸）」
                           ＋ `" BEFORE UPDATE OF code ON account_items"`
```

> ### 🔴 而其中兩支是一種**我沒有想到的載體**：
> ### **`BEFORE UPDATE ON` 是 TRIGGER 的語法** —— 它含 `UPDATE` 而完全不是資料寫入。

```
⚙️ 加總自檢：34（第一把尺）= 30（真的有寫入）+ 4（幽靈）✅
🔑 **而抓到它的是加總對不起來**，不是複查
   📌 唯一會自己翻臉的檢查就是加總 —— 其餘每一項都只會說「通過」
⚠️ ⇒ 守門掃這一族時：**剝註解與 docstring**，且 **`UPDATE` 要排除 `BEFORE/AFTER … ON`**
```

---

## §3 處置：**一支 helper，一個落點**

### ① helper：`report_backfill()`

```python
# helpers/migration_report.py（新）
def report_backfill(conn, version, name, *, changed=0, skipped=0, details=None):
    """回填結果寫進 `migration_log`，並同時寫一行 logger（診斷用）。

    🔴 `skipped > 0` 時 `details` 必填 —— 沒有明細的「跳過 N 筆」
       回答不出「是哪幾筆」，而那正是這張表唯一要回答的問題。
    """
```
```
⚠️ 而 `changed == 0 and skipped == 0` 時**照樣寫一列** ——
   🔑 migration 與 `EM7` 在這一格**相反**：
      EM7 的迴圈每天跑 => 寫「跳過 0 筆」會洗版
      migration **一個版號只跑一次** => 「這一版沒有動到任何一列」本身是資訊
   ☠️ 不寫的話，事後分不出「跑過而沒東西可改」與「根本沒跑到」
```

### ② 落點：**新開 `migration_log` 表**

```sql
CREATE TABLE IF NOT EXISTS migration_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  version    INTEGER NOT NULL,
  name       TEXT    NOT NULL,
  ran_at     TEXT    NOT NULL,
  changed    INTEGER NOT NULL DEFAULT 0,
  skipped    INTEGER NOT NULL DEFAULT 0,
  details    TEXT    NOT NULL DEFAULT ''   -- JSON，skipped 的逐筆明細
);
```

#### 🔴 為什麼不用既有的三個地方

```
`schema_version`  ⚙️ 實查**只有 1 列**（`id=1, version=103, applied_at=…`）
                  => 它是「**當前版號**」不是歷史 ⇒ 加欄位會被覆蓋
`audit_log`       ✅ 有頁面（`audit-log.html`）⇒ 看得到
                  🔴 而 `_prune_audit_log(keep_days=730)` 會刪它
                  ☠️ 「那 K 筆從來沒被回填」是一個**永久事實**，
                     它不該在兩年後消失
`logger`          ❌ 消費端 = 0（`EM7 §6` 實查）
```

⚠️ 而新開一張表**有成本**，要講出來：
```
① 又多一張表（`db.py` 已經 78 張）
② 而它**不進既有的任何頁面** => 🔴 沒有人會去看它 —— 見 ③
```

### ③ 🔴 而落點要**有人到得了** —— 否則這一件就是 `EM7` 的翻版

```
✅ 最小可行：`GET /api/system/migration-log`（superadmin）
   ＋ `module-versions.html` 或系統設定頁上一個入口
⚠️ 而**不必做成一個漂亮的頁面** ——
   🔑 判準是「**出事時查得到**」，不是「平常會有人看」
☠️ 但「查得到」要有一條真的路徑：
   一張沒有任何 UI 的表，與一行 log 的差別只是**它不會被輪替掉**
```

📌 ⇒ 這一格**要 A 裁**（§5①）：做端點＋入口，還是只做表？
🔑 而我建議**做端點**，理由是這一件的整個論點就是「log 沒有出口」。

---

## §4 守門

```
✅ 釘：**每一支「回填型」migration 都呼叫 `report_backfill()`**
   ⚙️ 母體判準（`ast`，剝註解與 docstring）：
      函式名 `_m*` ＋ 函式體裡有 `UPDATE <table> SET … WHERE`
      🔴 排除 `BEFORE UPDATE`／`AFTER UPDATE`（那是 TRIGGER，§2）
   ⇒ 命中而沒有呼叫 `report_backfill` => **紅**

⚙️ 合法清單（明碼）：13 支純種子 ＋ 3 支混合裡「只有種子那一半」的部分
   🔑 加總自檢：回填 14 + 混合 3 + 種子 13 = **30**
   ⇒ 而 30 這個數字**會隨新 migration 成長** ——
      ☠️ 所以釘的是「**每一支回填都有呼叫**」，不是「回填 = 14」

🎣 誘餌（合成）：
   A  `UPDATE t SET x=1 WHERE y=2` 而沒有 report_backfill  => **必須亮**
   B  同上但有呼叫                                          => **不可以亮**
   C  `INSERT INTO t VALUES (…)` 只種資料                    => **不可以亮**
   D  docstring 裡寫 `UPDATE …`                              => **不可以亮**（幽靈）
   E  🔴 `CREATE TRIGGER … BEFORE UPDATE ON t`               => **不可以亮**
      🔑 E 是今天實際踩到的那一種，而我原本沒想到
```

### ⚠️ 而**不要**釘「`rowcount` 有被讀」

```
☠️ `_m103` 沒有讀 rowcount，而它**做對了**（自己數迴圈裡的筆數）
=> 釘 rowcount 會逼 B 把一支正確的實作改成用 rowcount，而那反而更差
   （逐列處理時 rowcount 只會是最後一次 UPDATE 的結果）
🔑 ⇒ 釘的是「**有沒有回報**」，不是「用什麼方式數」
📌 〈守門守的對象被搬走〉：釘實作細節，換一種寫法就失效
```

---

## §5 ⏳ 待使用者回來確認

```
① ✅ **我們裁（工程判斷，不必等使用者）**　**落點要做到哪一層**
   我裁：**新開 `migration_log` 表 ＋ 一支 superadmin 端點 ＋ 一個入口**
   依據：這一件的整個論點就是「log 沒有出口」——
        只做表而沒有入口，等於把同一個問題往下搬一層
   ⚠️ 成本：一張新表 ＋ 一支端點 ＋ 一個連結
   ⇒ **若他只要表不要端點**：那要接受「出事時要有人開資料庫查」，
      而 §3③ 那句話（「與一行 log 的差別只是它不會被輪替掉」）就是這個選擇的描述

② ✅ **我們裁（工程判斷，不必等使用者）**　**`_m103` 要不要回頭改**
   我裁：**要**（它是本規格的第一個使用者）
   依據：它是現成的、剛寫好的、而且 B 手上還熱著
   ⚠️ 而那表示 `QS1-a` 的驗收要跟著改（從「log 裡有」改成「`migration_log` 裡有」）
   ⇒ **若他要等下一支 migration 再開始**：`_m103` 的那三行 log 會是
      唯一的紀錄，而它會在 log 輪替時消失

③ ✅ **我們裁（工程判斷，不必等使用者）**　**`changed == 0 and skipped == 0` 時要不要寫一列**
   我裁：**要寫**
   依據：migration 一個版號只跑一次 ⇒ 「這一版沒動到任何一列」本身是資訊；
        不寫的話分不出「跑過而沒東西可改」與「根本沒跑到」
   ⚠️ 而它與 `EM7` 的裁定**相反**（那邊是 N=0 不要寫）——
      🔑 差別在頻率：EM7 的迴圈每天跑，migration 只跑一次
   ⇒ **若他要一致**：那要挑一邊，而我認為**不該一致** —— 兩者的頻率不同
```

---

## §6 我沒查什麼

```
① 那 14 支回填**今天各自漏掉幾筆** —— **沒查**
   ⚙️ 已知 2 支有問題：`_m006`（WHERE deal_tag='' AND settle_status=''）
      與 `_m010`（display_name 比對不到 'test3'）—— 那是 `QS1 §2b` 查的
   🔴 其餘 12 支我**一支都沒讀**
   ⇒ 本規格是「往後要回報」，**不是「回頭補查」** —— 後者是另一件事
   ☠️ 而它們的資料今天已經是錯的，而沒有人知道是哪幾筆
② `migration_log` 要不要進每日備份 —— **沒查**備份的表清單
   ⚠️ 若不進，那它在災難還原之後就空了
   🔑 而「那 K 筆沒被回填」正是災難還原後最需要知道的事
③ 混合那 3 支（`_m051`／`_m062`／`_m090`）的 UPDATE 半邊**各自在做什麼**
   —— 沒讀，而 §4 的合法清單把它們算成「要呼叫」
   ⚠️ 若其中有純粹的結構調整（不是回填），那分類要修
④ `_m103` 是 B 在工作樹裡新寫的（**尚未 commit**）——
   ⚠️ 我讀的是**還沒進版控的碼**，它可能還會改
   🔑 ⇒ §1 的引用要標時間，而**不要拿它當一個穩定的事實**
```
