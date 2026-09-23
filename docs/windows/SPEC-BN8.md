# `BN8` 獎金分潤單簽核流程（第九個 doc type）—— 施工圖

> A-2 撰寫／2026-09-23。量測座標 **`dce8c73`**，量測時工作樹 **3 個異動**（不是我的）。
> **單一版本、無修訂層。照這一份做。**
> 使用者已選 **(a)**：獎金分潤單成為 `APPROVAL_DOC_TYPES` 的**第九個**。

---

## §1 照抄 `AS2 (c)`，**不要另創**

B 的 `v101`（`_m101_voucher_approval`）已經把形狀定下來了。逐字照它：

```python
cols = {r["name"] for r in conn.execute("PRAGMA table_info(bonus_awards)")}
if "approval_json" not in cols:
    conn.execute("ALTER TABLE bonus_awards ADD COLUMN"
                 " approval_json TEXT NOT NULL DEFAULT '{}'")
```

**三件照抄的理由（B 的 docstring 逐字）**
```
① DEFAULT '{}' 而不是 NULL —— 讀取端一律 json.loads(... or "{}")，
   NULL 與 '{}' 在那裡等價，而 NOT NULL 讓「沒有鏈」**只有一種寫法**
② 與最近一個加進來的 doc type（extra_expense）完全同形
   => tiered_approval 那一整套原樣可用，**一行都不用改**
③ PRAGMA 先查再 ALTER —— 重跑 migration 不會炸
```
⚠️ **不要建 `bonus_approvals` 明細表** —— 那會是**第四種**形狀
（`case_extra_expenses.approval_json`／`data_json.$.approval`／`vouchers_all.approval_json`）。
📌 我上一份對 `AS2` 建議明細表，**而 B 實查推翻了它的前提**：
既有已經是兩種形狀，新建明細表會是第三種。**判準是「跟哪一份對齊」，不是「有沒有兩份」。**

### 🔴 而有一格與傳票**不同**，要重新想：用印欄的資料從哪來

```
傳票   v99 已有 submitted_by/at、checked_by/at、manager_by/at
       => signatures_of() 有鏈時照鏈畫，沒鏈時退回那六欄
獎金單 **一格都沒有**（bonus_awards 只有 created_by／created_at）
```
✅ **而那讓獎金單比傳票乾淨**：
```
簽核鏈是唯一的來源，沒有「投影欄位」要維護
=> bonus_signatures_of(award) 只讀 approval_json，沒有 fallback 分支
```
⚠️ **一格例外**：「製表」那一格用 `created_by` ／ `created_at`
（與傳票的「製票」同一個做法，**而它不算一層**）。

⚠️ 而 `signatures_of()` 那一支**不可以直接重用** —— 它讀 `vouchers_all` 的欄位名。
⇒ 抽共用的部分（「有鏈就照鏈畫，一層一格；讀不出來就印在紙上」）
或**各寫一支而註解互指**。
📌 A-2 建議**各寫一支**：兩者的 fallback 不同（傳票有六欄、獎金單沒有），
硬抽共用會生出一個帶旗標的函式。

---

## §2 狀態機：**建議四個狀態，而「已發放」不是狀態**

### 現況（實查）

```
bonus_awards.status   建立時寫 '草稿'，而 **UPDATE 全 repo 只有一處且只寫 voided_***
                      => status 建立之後**從來不會改**
實際資料              正式 DB 1 筆（id=1, MQ-202607-028, 草稿）／demo 0 筆
```

### 🔴 而 schema **已經**編碼了「兩個事件」

```
bonus_awards.voucher_no_accrual   核定那筆傳票
bonus_awards.voucher_no_payment   發放那筆傳票
⇒ 使用者早先裁過「獎金入帳**兩筆傳票**」
⚠️ 而它們**今天零寫入端**（只有 DDL）
```

### ⇒ A-2 建議（**不是定案，A 要裁**）

```
status（只管簽核流程，四個）
  草稿 -> 待審核 -> 簽核中 -> 已核准
「錢的事」由那兩個欄位表達，**不是狀態**
  已入帳 = voucher_no_accrual != ''
  已發放 = voucher_no_payment != ''
```

**三個理由**
```
① 與 vouchers_all 已經做過的切分**同一條**：
   「走到流程哪裡」= status ／「現在算不算數」= voided_at
   ☠️ 那裡的 docstring 逐字寫過：把「作廢」做成第六個狀態，
      「已過帳的傳票」這個查詢就**查不到它**，而帳上那一筆還在
   ⇒ 這裡同理：把「已發放」做成狀態，「已核准的單」會**查不到已發放的那些**
② 兩個欄位**已經存在**，它們是那件事的自然歸宿
③ 畫面要顯示「已發放」⇒ **推導**，不要新增狀態
   （同 `vouchers` VIEW 的做法：預設查到的就是有效的）
```

⚠️ **而 A 問的那一格我答不了，要使用者裁**：
> 「已核准」與「錢真的出去了」可能是兩件事

```
它是兩件事 —— 而問題不是「要不要分」，是**誰按下「已發放」**：
  (i)  出納開了發放傳票 => 自動回填 voucher_no_payment
  (ii) 最高管理者手動標記
📌 A-2 傾向 (i)（那筆傳票就是證據，不必有人再按一次）
⚠️ 而 (i) 需要傳票那一側回寫獎金單 —— **那是一條新的相依**，要裁
```

---

## §3 三支端點

照 `vouchers.py` 那三支的形狀（`submit` / `approve` / `send-back`）：

```
POST /api/bonus/awards/{award_id}/submit      草稿 -> 待審核
POST /api/bonus/awards/{award_id}/approve     簽一層；簽完最後一層 -> 已核准
POST /api/bonus/awards/{award_id}/reject      退回 -> 草稿（清除簽核）
```

### 🔴 權限：**只有最高管理者**（`superadmin`），不要用 `_is_manager`

```
使用者 2026-09-23 逐字：「**產生獎金分潤單這些也只有最高管理員可見**」
而 _is_manager 回 role in ("superadmin", **"admin"**)
   —— 那支 docstring 自己標了「A 🟡 預設沿用，**未經使用者確認**」
⇒ **現在確認了。三支端點一律 require_superadmin=True。**
```
⚠️ 而 `GET /awards` 的**可見性**不要一起改：
```
bonus.py:307-310 已實作「與自己無關的單完全不出現」
⇒ 一般員工仍然看得到**自己那一列**（使用者要的正是這個）
☠️ 把 GET 也改成 superadmin ⇒ 員工看不到自己領多少
```
🔑 **「誰能操作」與「誰能看見」是兩個問題** —— 這個模組已經分開了，不要合併。

### ⚠️ 送審時建鏈，照 `submit_voucher` 的做法

```
resolve_active_flow_setting("bonus") -> setting_to_active_tiers(...)
⇒ 而 "bonus" 要先進 APPROVAL_DOC_TYPES ＋ APPROVAL_DOC_TYPE_LABELS
   標籤建議：**「獎金分潤單」**（不要只寫「獎金」）
⚠️ DEFAULT_UNIFIED_DOC_TYPES 加不加 —— **待裁**
   （加了＝預設跟大家同一條流程；不加＝自己一條 bonus_approval_flow）
```

---

## §4 既有那 1 筆草稿：**migration 不要碰它**

```
正式 DB  1 筆（id=1, status='草稿', voided_at=''）
demo DB  0 筆
```

⇒ **migration 只加欄位，不 UPDATE 任何一列。**
```
它本來就是「草稿」⇒ approval_json 的 DEFAULT '{}' 對它是正確的
（沒有鏈 = 還沒送審）
```
🔴 **而 migration 不可以呼叫任何會演進的 helper**
（〈凍住的歷史不要呼叫活的程式碼〉）：
```
❌ migration 裡呼叫 setting_to_active_tiers() 去補鏈
   => 歷史被回溯改寫，而症狀只出現在「完整降版再升版」那條路上
      —— 那條路就是**全新安裝與災難還原**
✅ 只 ALTER TABLE，鏈在它下次送審時才建
```

---

## §5 作廢與簽核的關係

### 現況

```
POST /awards/{id}/void   _is_manager ＋ 要 reason，**完全不看 status**
                         UPDATE 只寫 voided_at/by/reason
傳票那一側  void 是「已過帳」**唯一的出路**（docstring 逐字：
            少了它，一張開錯的已過帳傳票**從此沒有出路**）
```

### ⇒ A-2 建議（**要 A 裁**）

```
① 任何狀態都可以作廢（含已核准）—— 沿用傳票那一條
   🔑 理由相同：**不留出路的後果是「開錯了而改不掉」**
   ⚠️ 而權限同步改成 superadmin（與三支端點一致）
② 🔴 **已發放（voucher_no_payment != ''）的單，作廢不是一個旗標**
   錢已經出去了 ⇒ 作廢要**開一張沖銷傳票**，不是把 voided_at 寫上去
   ☠️ 只寫旗標的後果：帳上那筆錢還在，而獎金單說它作廢了
   ⇒ **本輪擋下來**（400：「這張單已經發放，請先開立沖銷傳票」），
      而沖銷流程**本規格不做**
```
⚠️ ② 今天**觸發不到**（`voucher_no_payment` 零寫入端）——
📌 而那正是要現在寫下來的理由：**接線的那一天沒有人會想起這一格。**

---

## §5b 🔴 簽核佇列 —— A 裁「要做，列進 `BN8`」，**而我查到一件已經上線的缺口**

### 佇列有兩支端點，而它們是**兩段各自獨立的查詢**

```
GET /api/approval-queue         quotations.py:3716   九個 type，各一段手寫 SQL
GET /api/approval-queue/count   quotations.py:4096   **另外九段手寫 SQL**
現有九種 type：
  quotation／contractor_voucher／invoice_voucher／shipping_note／
  payment_request／completion_note／case_change／extra_expense／extra_expense_change
```

### ☠️ 而 `voucher`（會計傳票）**兩邊都沒有** —— 那是今天就存在的缺口

```
vouchers.py:486   送審會 UPDATE vouchers_all SET status='待審核'
APPROVAL_DOC_TYPES 第八個就是 voucher（AS2 已落地）
而兩支佇列端點裡 `vouchers_all` 命中 **0**
⇒ **一張送審的傳票，簽核人在佇列上看不到它。**
```
🔑 〈兩個都對而路不存在〉：送審端點對、簽核端點對、而**沒有人知道有單在等**。
📌 **這不是 `BN8` 造成的，而 `BN8` 會用同一種方式再犯一次** ⇒ 一起補。

### ⚠️ 而既有那道守門**抓不到這一種**

```
test_approval_queue_badge_consistency_2026_09_15.py
  docstring 逐字：使用者回報「我跟另一位是最高管理者，需要我簽核但簽核佇列未顯示」
  它驗的是：對**它自己種的那組資料**，count == 佇列裡 canApprove 為真的項目數
```
☠️ **一個型別若兩邊都沒有，兩邊都回 0 ⇒ `0 == 0` ⇒ 綠。**
🔑 **它是「一致性」守門，不是「完整性」守門** —— 而它的寬度等於它種的 fixture。
⇒ 所以 `voucher` 缺了這麼久沒有人發現。

### ⇒ `BN8` 要做三件

```
① bonus_awards 進 **兩支**端點（type = "bonus_award"）
② **順手把 voucher 也補進去**（它今天就缺，而成本是同一段程式碼旁邊多一段）
   ⚠️ 若 A 認為那是另一個編號的事，**請回覆** —— 而它不該留著
③ 🔴 加一道**完整性**守門（新的，不是改既有那支）：
   APPROVAL_DOC_TYPES 裡**有 submit 端點**的每一個 type，
   都必須在 `/api/approval-queue` 與 `/api/approval-queue/count` **兩邊**出現
   ⚙️ 判定用 ast／字串比對兩支函式的來源表，而**基準要寫死今天的清單**
   ☠️ 沒有這一道，下一個 doc type 會用完全一樣的方式消失
```
📌 ③ 才是這一格真正的產出：**②只修今天那一個，③讓第三次不可能發生。**

---

## §6 驗收（`AC1`：後端＋前端＋頁面三者皆備）

```
後端 ① "bonus" 在 APPROVAL_DOC_TYPES 裡，標籤是「獎金分潤單」
     ② submit 後 approval_json 有鏈，且**層數 == 簽核設定的層數**
        ⚙️ 觀測方式：**把設定改成三層**再送審，鏈必須三層
        ☠️ 只驗「兩層時能過」的話，寫死與讀設定**結果一樣**
     ③ approve 逐層推進；簽完最後一層 -> status='已核准'
        ⚙️ **三個不同的人依序簽**（既有那題是 cascade 自簽，涵蓋不到「換人」）
     ④ reject -> 回草稿且**鏈被清掉**（不是留著標記）
     ⑤ 🔴 三支端點非 superadmin -> **403**
        而 `GET /awards` 一般員工**仍然看得到自己那一列**
        ☠️ 這一題是 §3 的全部：把可見性一起收緊 = 員工看不到自己領多少
     ⑥ migration 跑完，既有那 1 筆 status **仍是「草稿」**、approval_json == '{}'
        ⚙️ 而**不是**去驗「有幾筆」—— 驗那一筆**沒有被動過**
     ⑦ 已核准的單**仍然可以作廢**
     ⑧ voucher_no_payment 非空的單 -> 作廢回 **400** 且訊息提到沖銷
        ⚠️ 今天要**自己種**那個欄位才測得到（零寫入端）
     ⑨ 送審後的獎金單**出現在 `/api/approval-queue`**，
        且 `/api/approval-queue/count` 的數字**同步 +1**
        ☠️ 只加一邊 = 「列得出來而 topbar 是 0」或反過來，
           而既有註解逐字：**兩邊矛盾比兩邊都沒有更難查**
     ⑩ 🔴 **完整性守門**：APPROVAL_DOC_TYPES 裡有 submit 端點的 type，
        兩支佇列端點都要涵蓋
        ⚙️ 正對照：拿掉其中一個 type，那一題必須紅
        ⚠️ 它今天就會抓到 **voucher**（見 §5b）—— 那是預期的，不是誤報
     ⑪ 先斷言 status_code in (200, 400, 403) 再看內容（`§166` 三種臉）
前端 ⑩ 獎金頁有送審／簽核／退回三個會送出的動作（superadmin 才看得到）
頁面 ⑪ 用印欄**依鏈的層數畫**（製表 ＋ N 層），未簽的層印空格
     ⑫ 鏈讀不出來時**印在紙上**（「簽核資料無法讀取」），不要安靜退回固定格
```

⚠️ **⑤ 與 ⑥ 是最容易做錯的兩題**：
`⑤` 把「能操作」與「能看見」混在一起；`⑥` 用「筆數」驗一件其實是「沒被動過」的事。

---

## §7 待裁（**不要自己決定**）與我沒做的

### ✅ 已裁（A 2026-09-23，`STATE.md §234`）
```
① 狀態機四個（草稿／待審核／簽核中／已核准），
   已入帳 = voucher_no_accrual != ''、已發放 = voucher_no_payment != ''
③ "bonus" **不進** DEFAULT_UNIFIED_DOC_TYPES（同 voucher，先做可逆的那一邊）
④ 任何狀態都可作廢
⑤ 已發放的單作廢**本輪回 400** 擋下；沖銷流程本規格不做
```

### ⏳ 待使用者裁
```
② 誰按下「已發放」：出納開發放傳票**自動回填**，還是最高管理者**手動標記**
   📌 A-2 傾向自動回填（那筆傳票就是證據）
   ⚠️ 而它需要傳票那一側回寫獎金單 —— **那是一條新的相依**，A 已把代價寫進選項
```

### 待回覆
```
🔴 `voucher` 今天就不在簽核佇列裡（§5b）—— 我建議在 `BN8` 一起補
   ⚠️ 若 A 認為那是另一個編號的事，請回覆；**而它不該留著**
```

### 我沒做的
```
✗ 沒有實作、沒有跑任何測試
✗ 沒讀 B 的 v101 **完整實作**（讀了 migration 與 signatures_of，
  **沒讀他三支端點怎麼寫的**）⇒ 照抄之前 B 要自己再對一次
✗ 沒查 bonus 前端現在有沒有可以掛這三個動作的位置
✗ 沒查「簽核佇列」（approval-queue）要不要把獎金單也列進去
  ⚠️ 那一格會決定簽核人**怎麼知道有單要簽** —— **未查，而它可能是必要的**
✗ 沒查獎金單送審後**還能不能改比例**（傳票是「只有草稿可改」，獎金單沒有對應規則）
```
