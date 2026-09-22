# `BN1` 獎金產生單介面 —— 只寫兩件

> A-2 撰寫／2026-09-23。裁定來源 `STATE.md §168`（A）。
> 🔴 **本文件刻意只寫兩件**（A 裁，採 A-2 建議）：
> **① `plan` 端點的契約 ② 空狀態與兩級權限的畫面決定**
> 其餘（基數、拆分、一案一張有效單、拒絕整張單、403／409）**後端已經做完且規則都在
> 伺服器端** ⇒ 直接派 C 寫紅燈＋B 接線，**不要擴成 `JV3` 那種施工圖**。

---

## §0 為什麼需要這一頁（一句話）

```
POST /api/bonus/awards 要 allocations[].person_pct = { username: pct }
而那些 username 由 people_for_item() 決定
$ grep -n people backend/routers/bonus.py
  213 / 222 / 227   ← **三處全在 create_award() 函式內**
六支端點沒有任何一支吐出它  ⇒ **畫面組不出 request body**
```

🔑 這是**契約缺口，不是接線缺口** —— C 不知道要對哪一支端點寫紅燈（它還不存在）。

### 🔴 為什麼是「新增端點」而不是「前端自己算」（A 裁甲）

資料前端其實拿得到（案件 API 有 `assignedTo`，`case-management.js:1623` 在用）
⇒ 前端**做得到**自己照 `person_source` 把人組出來。**而那是把同一條規則抄到第二個地方。**

```
helpers/bonus.py:141 已標「已知的未來來源 quotations.assigned_user_ids」
⇒ 加它的那天：後端改、JS 不會跟
⇒ 症狀是**少發一個人，而總額對得起來**
```

☠️ **對不起來還有人會查，對得起來沒有人會查。**
📌 A 把它寫成一句：**規則只有一份。**

---

## §1 `GET /api/bonus/awards/plan/{quote_no}`

### 權限

```
_is_manager(user)   ← 與 POST /awards **同一道閘**，不要更鬆
                      （routers/bonus.py:40 ⇒ role in ("superadmin","admin")）
```

☠️ 更鬆的後果：一般員工看得到全案每個人的發放對象名單，
而 `visible_lines()` 那條「本人只看得到自己那一列」就被這支端點繞過去了。

### 回應

```json
{
  "quote_no": "MQ-202608-009",
  "base": { "ok": true, "amount": 123456, "error": "" },
  "has_active_award": false,
  "active_award_id": 0,
  "items": [
    { "bonus_item_id": 1, "name": "業務獎金",
      "person_source": "sales_person",
      "ok": true,  "people": ["alice"], "note": "" },
    { "bonus_item_id": 2, "name": "工程獎金",
      "person_source": "case_stages.assigned_to",
      "ok": false, "people": [],        "note": "無可發放對象" }
  ]
}
```

### 🔴 五條不可以改的

```
① **必須呼叫 helpers.bonus.people_for_item()**，不可以在端點裡另寫一份解析
   ⇒ 這是這支端點存在的唯一理由。另寫一份 = 回到「規則有兩份」
② **ok=false 的項目要回傳，不可以濾掉**
   people_for_item() 的 docstring 逐字在防這件事：
   「那個項目從來沒出現在任何一張獎金單上 —— 而**沒有人會發現一個從來不出現的東西**」
   ⇒ 它要出現在畫面上，並**明說為什麼不能發**
③ **note 直接用後端回的字串**，前端不要重寫文案 ⇒ 規則只有一份（同 ①）
④ **base 與 GET /base/{quote_no} 必須是同一個計算來源**（base_amount_for）
   ⚠️ 兩支端點各算一次而算法漂移的話，畫面顯示的基數與實際入帳的基數會不同
⑤ **has_active_award 要回** —— POST /awards 撞到部分唯一索引會回 409，
   而這個模組已經確立「先問再做」（GET /base docstring 逐字：
   「畫面在按下產生之前就該知道答案，而不是按下去才收到一句拒絕」）
```

### ⚠️ 路由順序：這條路徑現在安全，而它**會在未來被吃掉**

```
現有：POST /api/bonus/awards/{award_id}/void   ← 第三段是字面值 "void"
      GET  /api/bonus/awards                   ← 段數不同
⇒ GET /api/bonus/awards/plan/{quote_no} **不會**被它們攔下（我逐段比對過）
```

🔴 **而日後若有人加 `GET /awards/{award_id}`（讀一張單）並宣告在 `plan` 之前**：
```
/awards/plan/MQ-1  ->  award_id = "plan"  ->  int 轉換失敗  ->  **422**
```
⇒ **`plan` 必須宣告在任何 `/awards/{award_id}` 之前。**

🔴 **這一行的落點是程式碼註解，不是這份規格**（A 裁）。
理由逐字：**「下一個加端點的人不會去讀規格」** —— 寫在他眼前才擋得到。
⇒ 規格這一段的作用只是「B 動工時記得去貼那行註解」，**不是**約束本身。
📌 那不是假設：`GET /api/vouchers/summary-sources` 2026-09-23 就是這樣變成 422 的
（C 實測，成因是同 prefix 的 `@router.get("/{voucher_id}")` 先宣告）。

### ☠️ 單位是**基點**（1/10000），而欄位名字叫 `pct`

```
helpers/bonus.py:37   BASIS_POINTS = 10000
              :88   pool   = base × total_pct  // 10000
              :119  amount = pool × person_pct // 10000
frontend/js/bonus.js  pct(bp) { return (bp / 100).toFixed(2) + '%' }
```

🔑 **50% 要送 `5000`，不是 `50`。**
☠️ 送 `50` 的後果：獎金變成應得的 **1/100**，而畫面上它是一個格式正確的金額
⇒ **沒有人會把它看成錯誤**，只會覺得「怎麼這麼少」。
⇒ `plan` 的回應與 UI 的輸入框都要明著標單位；欄位名 `pct` **不要改**
（改名要動既有 DDL 與 API），改的是**文件與畫面上的標示**。

### 🔴 上界沒有人擋 —— 現在就可以發超過獎金池

```
routers/bonus.py:256   if sum(p[1] for p in pairs) <= 0:  raise 400
                       ↑ **只有下界**
```

沒有任何一處擋這兩件：
```
total_pct  > 10000        => pool > base        => 獎金超過淨利
Σperson_pct > 10000       => Σamount > pool     => remainder_of() **變成負數**
```

📌 而那個不變量**已經寫在 `split_award()` 的 docstring 裡**：
> 「不變量：`Σamount <= pool`，且 `pool - Σamount < 人數`。
> **大於人數表示那不是捨入誤差，是算式錯了。**」

☠️ **寫下來了，而沒有任何一行程式在檢查它。**
⇒ `BN1` 要補在**後端**：`total_pct <= 10000` 且 `Σperson_pct <= 10000`，超過回 400。
⚠️ **不可以只在前端擋** —— `bonus.js` 自己的註解逐字：
「前端過濾是假的：值仍然在 API 回應裡」，同一個道理套在輸入上。

⚙️ **而「等於 10000」與「小於 10000」都要允許**：
少發（例如只發 80%）是合法的公司政策，**不是錯誤**。

### ⚙️ 單位的驗收怎麼寫（**不要寫成「差 100 倍」**）

```python
# ✅ 對任何 base 都精確（實算 base = 1／7／123456／999999／87654321 全 True）
assert pool_for(base, 10000) == base          # ① 10000 基點 = 全額（單位的定義）
assert pool_for(base, 100)   == base // 100   # ② 100 基點 = 1%
assert pool_for(base, 100)   != base          # ③ 把 100 當成「100%」會被抓到
```

⚙️ **③ 的前提是 `base >= 1`**（C 2026-09-23 import 產品碼實跑：`b` 在 `0~2999`
裡**只有 `b = 0` 不成立**）⇒ 測試資料不必挑大的，`base = 1` 也行。
📌 A-2 原本寫「`base > 100`」**太嚴**，那會讓人以為要準備特別的資料。

🔑 **① 與 ③ 要一起，它們抓的是相反的兩個方向**：
```
單位被實作成 // 100（百分比） => pool_for(base,10000) 變成 base×100 => **① 紅**
單位被呼叫端當成百分比餵     => 100 被當 100% 而實際是 1%        => **③ 紅**
```
⇒ 兩條都不依賴 `base` 整除。

☠️ **不可以寫 `pool(5000) == pool(50) * 100`** —— `pool` 是整數無條件捨去：
```
base=123456    pool(50)=617     pool(5000)=61728      **差 28**，不是 100 倍
base=999999    pool(50)=4999    pool(5000)=499999     **差 99**
base=87654321  pool(50)=438271  pool(5000)=43827160   **差 60**
只有 base 是 10000 的倍數時才剛好成立
```
🔑 那種寫法會**紅在正確的碼上**，而訊息指向 `split_award()`
⇒ 下一個人最省力的反應是去「修」那個先乘後除，**而那會真的弄壞精度**。

### ⚙️ 驗收要釘的（給 C）

```
① 端點回的 people，與 POST /awards 實際發放的對象**逐字相同**
   🔑 觀測方式：同一個案件，先打 plan 拿 people，再 POST 建單，
      比對 bonus_award_lines.username 集合 == plan 回的 people 集合
   ⇒ 這一題釘的是**不變量**（兩邊同源），不是實作細節
② ok 與 people 必須一致：ok=true 且 people==[] 要紅，ok=false 且 people!=[] 也要紅
   ☠️ 否則畫面會出現「可以發放，但沒有人」
③ 非管理者呼叫 -> 403（不是 200 空清單）
④ **反向控制**：把 person_source 改成一個解析不出人的值，
   那個項目要變成 ok=false 且仍然**出現在 items 裡**
⑤ ⚠️ 先斷言 status_code in (200, 400, 403) 再看內容
   —— 端點不存在時這個 repo 有三種臉：404／405／**422**（見 §166）
```

---

## §2 空狀態與兩級權限

### 實況（實測，不是推的）

```
權限兩級
  POST /api/bonus/items   _require_user(require_superadmin=True)   ← **只有 superadmin**
  POST /api/bonus/awards  _is_manager(user)  = role in (superadmin, admin)

資料
  bonus_items  motrix_erp.db 0 列 ／ motrix_erp_demo.db 0 列
  產品碼裡 INSERT INTO bonus_items 只有一處：POST /items
⇒ **第一次打開獎金頁，項目清單必定是空的**
```

### 🔴 裁定：同一頁分區塊，**不拆頁**（A 裁）

依據：`superadmin` 是 `_is_manager` 的子集之一 ⇒ 他一個人走得完全程。

### ☠️ 而真正要決定的是 `admin` 那一格 —— 他走不完

```
admin  可以產生獎金單（_is_manager 過）
       **不能新增獎金項目**（require_superadmin 擋）
⇒ 公司裡只有 admin 在用的那天，他打開頁面看到空清單，而**他修不好它**
```

🔴 ⇒ 空狀態**必須說出三件**，不可以只畫一個空盒子：

```
① 為什麼是空的      「尚未建立任何獎金項目」
② 誰能解決          「請最高管理員（superadmin）到本頁『獎金項目』區塊新增」
③ 目前的我行不行    superadmin -> 直接給新增按鈕
                    admin      -> **不給按鈕**，顯示上面那句話
```

⚠️ **這一條的副作用落在盲側**：只給 admin 一個空清單的話，
**他會以為功能壞了，而那與功能真的壞了長得一模一樣** ⇒ 他會去報修一個沒有壞的東西。

### ⚠️ 不在 migration 塞預設獎金項目（A 裁）

比例是**公司政策**，不替使用者決定。
📌 ⇒ 所以空狀態不是暫時現象，它是**每一個新客戶的第一天**，要當成正式畫面設計。

---

## §3 `GET /api/bonus/awards` 夠不夠支撐清單頁（A 指定要補的射程）

**結論：夠用，而缺兩樣，其中一樣後端不必改。**

### 已經有的

```
每張單  id / quote_no / base_amount（僅管理者）/ base_source / status
        voucher_no_accrual / voucher_no_payment（兩筆傳票）
        voided_at / voided_by / void_reason / supersedes_id / created_at
        lines[]（已依 visible_lines 過濾）/ visible_total
頂層    is_manager
可見性  非管理者：只看得到自己有分錄的單，且只看得到自己那一列，不給 base_amount
```

### 🔴 缺一：**案件名稱／客戶**

```
只回 quote_no ⇒ 清單上只有單號，沒有「這是哪一個案子」
⇒ 前端要嘛每張單再查一次（N+1），要嘛後端 JOIN 一欄進來
```
✅ **裁定（A 2026-09-23）：後端加。** `LEFT JOIN quotations` 取案名與客戶。
理由：清單頁必然要它，而 N+1 的成本隨案件數成長。

⚠️ **只取 `customer_name` 與案件名兩欄，不可以 `SELECT q.*`**（A 明著裁）。
☠️ `SELECT q.*` 正是 token 那件的形狀：把一整列拉進回應，
而**下一個人加欄位時不會回來看這支端點回給誰**。

### ✅ 缺二：**顯示名** —— 後端不必改

```
lines[].username 是帳號，不是人名
而 GET /api/users/selectable（auth.py:1566）只要 _require_user
⇒ **任何登入者都呼叫得到**，回 id/username/display_name/role
⇒ 前端自己對照即可
```

### ⚠️ 兩件標出來不處理

```
① **無分頁**：SELECT * FROM bonus_awards 全撈。現在 0 列，
   而獎金單是**每案一張** ⇒ 會隨案件數線性成長。本輪不做，標著
② base_source 欄位有值（預設 settlement.summary.netProfit）而沒有任何消費端
   ⇒ 不是缺陷，但清單頁若要顯示「基數怎麼來的」，它已經在那裡
```

### ✅ 一個曾經的出貨阻擋 —— **已修，而這一列留著**

```
2026-09-23 05:0x  A-2 量 GET /awards 時撞到：
  created_by / voided_by 存的是 **session token**（_tok(auth) = auth[7:]）
  而 GET /awards 的 SELECT * 會把它回給其他使用者
  ⇒ 員工拿得到產生那張單的管理者的 token（有效期 30 天）
2026-09-23 05:54  B 修掉（dd50d2e）：新增 _actor(user) -> user["username"]
```

📌 **留著這一列不是為了記功**，是因為那個形狀還會再出現：
```
_tok(authorization) 在 _audit(...) 裡是**正確**用法（第一個參數本來就是 token）
而同一個表達式寫進欄位就是外洩 ⇒ **同一段程式碼，兩種對錯**
```
⚠️ ⇒ 日後看到 `_tok(authorization)` 要先問**它要去哪裡**，不是問它長得對不對。

---

## §4 我沒做的

```
✗ 沒跑任何測試（撰寫時 B 在跑全量）
✗ 沒有實際打過任何端點（沒動 666）⇒ 以上全部是讀碼推的
✗ 沒讀 frontend/js/bonus.js 的內容（只量了互動元件：<button/<select/<input/@click/x-model 全 0，
  以及它只 fetch 一處 /api/bonus/awards）
✗ 「案件 API 有 assignedTo」是從前端在用它推的，**沒回頭讀後端是哪一支端點回的**
✗ 沒設計畫面版面（欄位排列、比例輸入的互動）—— 那是 B 的範圍
✗ 獎金單的**狀態機**（草稿之後怎麼走、兩筆傳票何時開）不在本頁範圍
```
