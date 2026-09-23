# `BN2`～`BN5` 獎金分潤四項 —— 施工圖

> A-2 撰寫／2026-09-23。量測座標 **`8a3c274`**。
> ⚠️ 量測時工作樹有 **1 個異動**（不是我的）。
> **單一版本、無修訂層。照這一份做。**

**使用者原話（逐字）**
```
「1.獎金分潤，獎金項目只有最高管理者可見，
  2.獎金項目內人員來源可由最高管理者手動新增，
  3.產生獎金單名稱改成產生獎金分潤單，
  4.案件編號用下拉式選單，方便最高管理者產出獎金分潤單」
```

---

## §1 `BN2` 獎金項目只有最高管理者可見

### 現況（實查）

```
GET /api/bonus/items   _require_user(authorization)      ← **任何登入者**
                       回 {items, person_sources, can_edit: role=='superadmin'}
⇒ 「可不可以編」已經分了，「可不可以看」**沒有分**
```

### 🔴 而改成 `require_superadmin` 之後，非 superadmin 會看到**一片空白**

A 問的是「頁面現在有沒有區分 403 與空清單」。**有區分，而區分之後那句話沒有人看得到。**

```
bonus.js loadItems()
    if (!r.ok) throw new Error('HTTP ' + r.status)     ← 403 走這裡
    ...
    this.itemsLoaded = true                            ← **只在成功時才設 true**
  catch (e)
    this.itemErr = '獎金項目載入失敗（HTTP 403）。請重新整理…'

bonus.html:109  <section x-show="isManager && itemsLoaded">     ← 整個區塊
        :115       <template x-if="itemErr"> … </template>      ← **錯誤訊息在區塊裡面**
```

☠️ ⇒ **`itemErr` 被關在一個「出錯時必定隱藏」的區塊裡。**
```
403 => itemsLoaded 維持 false => section 不顯示 => **連錯誤訊息都看不到**
```
🔑 **比空表更糟：空表至少說了一句話（雖然是假的），這裡一句話都沒有。**
⚠️ 而這**不是 `BN2` 造成的** —— 今天任何原因的載入失敗都是這樣，
**只是 `BN2` 會讓它從「例外」變成「每一個非 superadmin 的日常」**。

### ⇒ 要做的三件

```
① 端點改 require_superadmin=True
② 🔴 `itemErr`／載入失敗的呈現**移到 section 外面**
   （或 section 的條件改成 `isManager && (itemsLoaded || itemErr)`）
③ 403 的文案要**說得出原因與出路**，不是「請重新整理」
   ✅「獎金項目僅最高管理員（superadmin）可檢視。若需調整，請洽最高管理員。」
   ☠️「載入失敗，請重新整理」—— **重新整理不會有幫助**，
      而它會讓使用者一直按，然後回報一個沒有壞的東西
```

⚠️ `can_edit` 那一格**不要拿掉**：端點改成只有 superadmin 讀得到之後，
`can_edit` 恆為 true，**而它仍然是後端說的** —— 前端不要改成自己判 `role`。

---

## §2 `BN3` 人員來源可由最高管理者手動新增

A 已裁（`§216`）：**新增來源類型做不出來**（來源背後是撈人的程式邏輯），
⇒ 裁定為新增一種來源 **`manual`（手動指定）**，項目直接掛人員清單。**本節只寫落地形狀。**

### `people_for_item()` 現在吃什麼

```python
source = item["person_source"]
if source == "case_stages.assigned_to":   # 逐筆解析 JSON 陣列
    …
else:                                      # 其餘：case.get(source)
    name = case.get(source)
⇒ 回 (ok, people, note)；people 是 **username 的 list**
```

🔑 ⇒ **`manual` 只要在那個 `if/else` 前面多一支，回同樣的 `(ok, people, note)`**
⇒ **不用開第二條路**，下游（`split_award`／`bonus_award_lines`）一行都不必動。

### 人員清單存哪

`bonus_items` 現有欄位：`id / name / person_source / sort_order / is_active / created_by / created_at / updated_at`

```
✅ 建議：**新表** bonus_item_people(bonus_item_id, username)
   而**不是**在 bonus_items 加一個 JSON 欄位
```
理由：
```
① 要能回答「這個人被哪些獎金項目指定」⇒ JSON 欄位查不動
   （與 JV3 選資料表不選 JSON 欄位同一個理由）
② 綁使用者帳號要有外鍵語意；JSON 裡放什麼都塞得進去
```

### ☠️ **綁帳號，不存自由文字**（A 的界線，我加一層落地）

```
❌ 存 display_name／自由輸入      打錯一個字那個人就領不到，**而畫面上一切正常**
✅ 存 username（users.username）  ⇒ 與 visible_lines(lines, username) 一致
                                  ⇒ 與 bonus_award_lines.username 一致
```
⚠️ 而 `username` 是 `users` 表的 UNIQUE NOT NULL 且**不在可改欄位白名單裡**
（`auth.py:1502`，B 查過）⇒ 它不會變，適合當識別。

### 三件要擋的

```
① 新增 manual 項目而**沒有指定任何人** => 400
   ☠️ 允許的話 people_for_item 回 (False, [], "無可發放對象")
      ⇒ 那個項目**從來不會出現在任何一張獎金單上**，而沒有人會發現
② 指定的 username **不存在**或 is_active=0 => 400，訊息要說出是哪一個
③ 停用的人員：已經在既有獎金單上的**不動**（凍結），
   而**新的獎金單不可以再發給他**
```

### 📌 它同時解掉一個既有落差

```
_case_people 已回報：quotations.owner／engineer **兩個欄位不存在**
⇒ 用那兩個來源建的項目**永遠發不出去**
⇒ manual 讓使用者有一條路可以自己指定，不必等那兩個欄位
⚠️ 而 PERSON_SOURCES 目前只有兩個值（sales_person／case_stages.assigned_to）
   —— owner／engineer **早就被 A 拿掉了**，所以這裡沒有殘留要清
```

---

## §3 `BN4` 「產生獎金單」改成「產生獎金分潤單」

### 逐處（實查，印出內容不只給數字）

**使用者看得到的 8 處 —— 這些要改**
```
helpers/bonus.py:50    「…無法產生獎金單。」                （錯誤訊息）
routers/bonus.py:339   「僅管理員以上可產生獎金單。」        （403 訊息）
routers/bonus.py:443   「產生獎金單：%s（基數 %s）」          （**稽核訊息**）
frontend/js/bonus.js:291 「已產生獎金單（單號 #…，基數 …）」  （成功訊息）
frontend/pages/bonus.html:87   「金額在產生獎金單的當下就固定下來…」
                        :139  「…您就可以開始產生獎金單。」
                        :184  「產生獎金單」                  （**區塊標題**）
                        :258  「產生中… / 產生獎金單」        （**按鈕**）
```

**註解／docstring 6 處 —— 見下**
```
routers/bonus.py:2     模組 docstring
routers/bonus.py:163   docstring 內
frontend/js/bonus.js:46 / :49 / :155   註解
frontend/pages/bonus.html:178          HTML 註解
```

### ⚠️ 註解要不要改：**要，而理由與 `WD1` 不同**

```
WD1 的線  「這個字串會不會離開這台機器」=> 註解不在範圍（語氣）
BN4 的線  這是**改名**不是改語氣
          ⇒ 註解裡留著舊名字，下一個人 grep「產生獎金單」會找到一半
```
📌 ⇒ **改**，而改註解**不需要驗收題**（它不影響行為）。
⚠️ 只有一個例外：`routers/bonus.py:443` 的稽核訊息**是寫進 `audit_log` 的**
⇒ **既有的舊紀錄不要回頭改**（歷史不可回溯改寫），只改之後產生的。

### ✅ 信件主旨：**沒有**

```
grep 'bonus|獎金' backend/helpers/email_notify.py => **0 命中**
⇒ 獎金模組目前不寄任何信 ⇒ 這一格是空的，不要去找
```

---

## §4 `BN5` 案件編號改下拉式選單

A 已裁：**下拉要列什麼是這一項的全部內容**，不是把 `input` 換成 `select`。

### 🔴 「已結案」不在 `status` 欄位裡

```
quotations.status   只有 已送出 25 ／ 已拒絕 1     ← **沒有「已結案」**
quotations.deal_tag 未成案 11 ／ **已結案 9** ／ 已成案 5 ／ 已提供 1
```
☠️ ⇒ 照 `status` 寫會查到 **0 筆**，而那與「沒有可選的案件」長得一模一樣。
📌 產品碼已經是這樣判的（`quotations.py:271`：`if (row["deal_tag"] or "") != "已結案"`）。

### 查得出來 —— 實跑

```sql
deal_tag = '已結案'                                              -> 9 筆
  AND json_extract(data_json,'$.settlement.status') = 'finalized' -> 9 筆
  AND netProfit > 0                                               -> **8 筆**
```
```
settlement.status 分佈：NULL 13 ／ draft 2 ／ finalized 11
已產過有效獎金單的案件（bonus_awards WHERE voided_at=''）-> **0 筆**
```

### ☠️ 那一筆差額正是 A 警告的形狀

```
已結案且已精算 9 筆，而淨利 > 0 的只有 **8 筆**
⇒ 有 **1 筆**淨利 ≤ 0
```
🔑 **若下拉用 `netProfit > 0` 過濾，那一筆會安靜消失** ——
使用者只會看到「選單裡沒有它」，而他不知道為什麼。
⇒ **列出來，並標示原因**（例如「淨利 0 或負數，不發放」且不可選）。
📌 那與 `BN1` 的 `ok=false` 項目「要回傳不可以濾掉」是**同一條規則**。

### ⇒ 下拉要列什麼

```
母體      deal_tag = '已結案' 且 settlement.status = 'finalized'   （今天 9 筆）
每一筆要帶  quote_no ／ customer_name ／ project_name ／ netProfit
標示（不要濾掉）
  ① 淨利 ≤ 0            -> 標「無可分配基數」，**不可選**
  ② 已有有效獎金單       -> 標「已產生（#id）」，**不可選**，而**看得到**
     ⚠️ 作廢之後要能再產一次 ⇒ 判斷用 `voided_at = ''`，不是「有沒有紀錄」
空狀態要說得出原因
  沒有已精算的案件       -> 「目前沒有已結案且已完成精算的案件。」
  非管理者               -> 「您沒有產生獎金分潤單的權限。」
  ☠️ **不是一個空的 select**
```

⚠️ **不要把兩個原因合成一句**：「沒有可選的案件」同時是
「真的沒有」與「你沒有權限」的答案，而**它們的下一步完全不同**。

---

## §5 驗收（`AC1`：後端＋前端＋頁面三者皆備）

```
BN2 ① GET /api/bonus/items 非 superadmin -> 403
    ② 🔴 403 時**畫面上看得到那句話**
       ⚙️ 觀測點：錯誤文字所在的 DOM **不可以**在 `x-show="…itemsLoaded"` 底下
       ☠️ 只驗「itemErr 有值」會綠 —— 它有值，而沒有人看得到
    ③ 403 的文案含「superadmin」與「請洽」，**不含「請重新整理」**

BN3 ④ 建 manual 項目不指定任何人 -> 400
    ⑤ 指定不存在的 username -> 400 且訊息說出是哪一個
    ⑥ people_for_item(manual 項目, 任一案件) 回的 people == 指定的那些人
       ⚙️ **不依賴案件內容**（manual 與案件無關，這是它與其他來源的差別）
    ⑦ 停用一個被指定的人 -> **既有獎金單不變**，而新產的單不含他

BN4 ⑧ 使用者看得到的 8 處都改完；**audit_log 既有紀錄不變**
    ⚠️ ⑧ 用「舊字串在使用者可見的字串裡命中 0」驗，
       而**註解要排除**（否則會把改註解變成驗收條件）

BN5 ⑨ 下拉母體 == deal_tag='已結案' 且 settlement.status='finalized'
    ⑩ 🔴 淨利 ≤ 0 的案件**出現在清單裡**且不可選、且標了原因
       ☠️ 這一題紅而其他全綠 = 我們做了一個會讓案件消失的選單
    ⑪ 已有有效獎金單的案件**出現且標示**；作廢之後**同一個案件再次可選**
    ⑫ 空狀態分得出「沒有已精算的案件」與「你沒有權限」
    ⑬ 先斷言 status_code in (200, 400, 403) 再看內容（`§166` 三種臉）
```

---

## §6 我沒做的

```
✗ 沒有實作、沒有跑任何測試
✗ `BN2` 我讀的是 bonus.js／bonus.html 的**磁碟版本**
  ⚠️ 666 上跑的是 dd50d2e（05:56 載入，無 --reload）⇒ **使用者看到的不是這一份**
✗ 沒查 admin（非 superadmin）在 BN2 之後**整頁**還剩什麼
  （只查了「獎金項目」那一個 section）
✗ `BN3` 的停用人員規則（⑦）我**沒查**既有是否已有同類處置可沿用
✗ `BN5` 的 9 筆我沒有逐筆打開看 —— 只跑了聚合查詢
✗ 沒查前端下拉在案件數量成長後的效能（今天 26 筆，**沒有分頁需求**）
```
