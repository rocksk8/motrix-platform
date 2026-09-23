# `SPEC-SL1` · 精算的過期提醒只涵蓋一半

> 座標：`31d240e`（工作樹：本檔為新增）
> 作者：視窗 A-2 ／ 2026-09-23
> 來源：`ACC-BN6 §4` 撿到 —— 「與原始報價毛利差異」完結當下存 −337,439、
> 今天重算 −257,764，**而畫面上沒有任何提示**。

---

## §1 現況：**一個已經存在的警示機制，只涵蓋兩個來源裡的一個**

```js
// settlement.html:893  dispatchStale()
if (this.settlement.status !== 'finalized' || !this._frozenSummary) return null
const frozen = Math.round(this._frozenSummary.dispatchTotal || 0)
const live   = Math.round(this.summary.dispatchTotal || 0)
if (frozen === live) return null
return { frozen, live, diff: live - frozen }
```

```
✅ 承攬商成本改了  => 有黃色警示條（settlement.html:252-262）
🔴 **原始報價改了**  => **沒有任何警示**
🔴 **額外支出改了**  => **沒有任何警示**
```

### ⚙️ 而這件事的規模：**不是十格，是一格**（D 量、我複驗）

```
`_frozenSummary` 全檔只有 **4 行**：
   :734  宣告      `_frozenSummary: null`
   :824  賦值      `this._frozenSummary = saved.summary || null`
   :894  存在檢查  `!this._frozenSummary`
   :895  **欄位級取值只有這一處**：`this._frozenSummary.dispatchTotal`
```
🔑 ⇒ 要多涵蓋兩個來源，是**加兩支同形狀的函式**，不是重寫機制。

---

## §2 🔴🔴 而 `dispatchStale()` **自己就是壞的** —— 先修它

### `undefined || 0` 讓「缺資料」變成「**凍結當時是 0**」

```js
const frozen = Math.round(this._frozenSummary.dispatchTotal || 0)
```

### ⚙️ 實測：**11 張 finalized 裡有 6 張會踩到**

```
MQ-202607-023   dispatchTotal ❌   finalizedAt 2026-07-31
MQ-202607-028   dispatchTotal ❌   2026-07-15
MQ-202607-047   dispatchTotal ❌   2026-07-21
MQ-202607-126   dispatchTotal ❌   2026-07-21
MQ-202607-137   dispatchTotal ❌   2026-07-23
MQ-202608-003   dispatchTotal ✅   2026-08-05
MQ-202608-004   dispatchTotal ✅   2026-08-05
MQ-202608-005   dispatchTotal ✅   2026-08-05
MQ-202608-006   dispatchTotal ✅   2026-08-05
MQ-202608-007   dispatchTotal ✅   2026-08-05
MQ-EXPFILE-001  **summary 是 `{}`**（0 鍵，無 finalizedAt）
```

### ☠️ 而這條分界線**乾淨得沒有一個例外**

```
07-31 以前  5 張  **全缺**
08-05 以後  5 張  **全有**
⚙️ 而其餘 20 個鍵在那 10 張裡都是 **10/10**（含本規格要用的
   `extraTotal` 與 `origNetProfit`）—— 只有 `dispatchTotal` 是 **5/10**
```

> ### 🔑 ⇒ **這不是資料壞掉，是 `calcSummary()` 在 8 月初多了一個欄位。**
> ### ☠️ 而 `|| 0` 把「**那時還沒有這個概念**」翻譯成了「**那時是 0**」。

```
🔴 ⇒ 這件事的射程不是那 6 張 ——
   **下一次 `calcSummary()` 再加一個欄位，就再來一次**，
   而那 5 張 07 月的單今天長什麼樣，就是未來的單到時候會長的樣子。
📌 ⇒ 處置要能吃「**未來的新欄位**」，不是把這 6 張補一補
   （§3 的 `key in snap` 正好就是那個吃法 —— 它不必知道有哪些鍵）
```

### ☠️ 而那 1 張**擋不住**，因為 `{}` 是 truthy

```js
this._frozenSummary = saved.summary || null    // {} || null  ===  {}  ← **truthy**
…
if (… || !this._frozenSummary) return null      // {} 不是 falsy ⇒ **不會 return**
const frozen = Math.round({}.dispatchTotal || 0)  // ⇒ **0**
```

> ### 🔑 那道「沒有快照就不比對」的保護 **看起來擋住了，而它擋的是 `null` 不是「空的」**。
> ### ☠️ ⇒ 畫面會說「完結當下承攬商派發成本：**NT$ 0**」—— **那是編的**。

📌 〈null 不等於 0〉：**「沒有值」與「值是零」是兩件事**，
而這裡它變成了一句**看起來像歷史紀錄**的話。

---

## §3 處置：**三態回傳**

```js
// 三支共用同一個形狀
_staleOf(key) {
  if (this.settlement.status !== 'finalized') return null          // ① 不適用
  const snap = this._frozenSummary
  if (!snap || !(key in snap)) return { unknown: true, key }        // ② **無法判斷**
  const frozen = Math.round(snap[key] || 0)
  const live   = Math.round(this.summary[key] || 0)
  if (frozen === live) return null                                  // ① 一致
  return { frozen, live, diff: live - frozen }                      // ③ 過期
}
dispatchStale()  { return this._staleOf('dispatchTotal') },
origTotalStale() { return this._staleOf('origNetProfit') },
extraStale()     { return this._staleOf('extraTotal') },
```

### 🔑 關鍵在 `!(key in snap)` **不是** `snap[key] == null`

```
`key in snap`  問的是「**這個鍵存不存在**」  ✅
`snap[key]`    問的是「**它的值是什麼**」    ❌ 而 0 與 undefined 在這裡同樣 falsy
☠️ 用後者的話，一張「凍結當時真的是 0」的單會被誤報成「無法判斷」
```

### ⚠️ 而 ② 要**說得出為什麼**，不可以什麼都不顯示

```
❌ 回 null（什麼都不顯示）=> 使用者**以為沒有問題**
✅ 「**這張單完結時沒有留下「承攬商派發成本」的紀錄，因此無法判斷是否已過期。**」
🔑 A 的裁定：「無法判斷」要說得出為什麼
📌 〈唯讀動作：拒絕 vs 略過〉的第三條路：**把缺口輸出出來**
```

⚠️ 而它的樣式**要與「已過期」分得開**：
```
已過期    黃色警示條（既有 .stale-banner）
無法判斷  **灰色**，措辭是「無法判斷」不是「已異動」
☠️ 兩者同色的話，使用者會把「不知道」當成「有問題」——而他會去查一個不存在的差異
```

---

## §4 三支各自比對哪一個欄位

```
dispatchStale()   `dispatchTotal`   承攬商派發成本（既有）
extraStale()      `extraTotal`      額外支出
origTotalStale()  `origNetProfit`   🔑 **原始預估淨利**，不是 origTotalCost
```

### 🔴 第三支為什麼是 `origNetProfit`

```
`ACC-BN6 §4` 實測：profitDiff 的漂移來自 **origNetProfit**
   完結當下 origNetProfit = 821,252（由 profitDiff 反推）
   今天       tot.netProfit  = 741,577
=> 而 profitDiff = netProfit − origNetProfit ⇒ **它才是漂移的源頭**
```
⚠️ 而 `origTotalCost`／`origMarginPct` 也在 summary 裡，
⇒ **若要三個都比，那是三支不是一支** —— 本規格**只做 `origNetProfit`**，
理由：它是**使用者會看到的那一格**（「與原始報價毛利差異」）的直接輸入。

---

## §5 驗收（`AC1`）

```
① 後端  無異動（summary 是既有的凍結快照）
② 前端  三支 stale 函式 ＋ 三個警示位置；「無法判斷」用灰色且說得出為什麼
③ 頁面  ⓐ 開 `MQ-202608-007` -> 改一筆派工金額 -> 重整
           => 黃色「已異動」條（**既有行為，不可以壞**）
        ⓑ 開 `MQ-202607-023`（缺 `dispatchTotal` 鍵）
           => **灰色「無法判斷」**，而**不是**「完結當下 NT$ 0」
           🔑 ⓑ 是這一件的核心 —— 改之前它會印一個編的 0
        ⓒ 開 `MQ-EXPFILE-001`（summary 是 `{}`）=> 同 ⓑ
           ☠️ 少了 ⓒ，「只判 `!snap`」的修法也會綠 —— 而 `{}` 是 truthy
        ⓓ 開 `MQ-202608-007` -> 改報價單的品項成本 -> 重整
           => **原始預估那一側**出現警示（新行為）
        ⓔ 負對照：沒有任何異動的單 -> **三條警示都不出現**
           🔑 少了 ⓔ，「永遠顯示無法判斷」也會綠
```

---

## §6 守門

```
✅ 釘：三支 stale 函式**都用 `key in snap` 判存在**，不用真假值
   ⚙️ 誘餌：造一張「凍結當時真的是 0」的單 => **不可以**被報成「無法判斷」
   ☠️ 那是這道判準唯一會誤報的地方
✅ 釘：`_frozenSummary` 的**欄位級取值只能在 `_staleOf()` 裡**
   ⚙️ 掃 settlement.html：`_frozenSummary.` 後面接欄位名的地方 = **1 處**
   🔑 那是 D 量到的現況（欄位級取值只有 1 處）—— **守住它**
```

---

## §7 我沒查什麼

```
① `extraTotal` 會不會過期 —— **沒有實例**
   ⚠️ 額外支出是從 `case_extra_expenses` 表即時算的（`settlement.html:946`），
      而 summary 裡存的是完結當下的值 ⇒ **機制上會過期，而我沒有找到一張真的過期的**
   🔑 ⇒ 同 `EM7` 的那一格：**機制存在 ≠ 今天會踩到**，要分開報
② `origTotalCost`／`origMarginPct` 要不要也比 —— §4 說明了為什麼本輪不做，
   **而那是一個選擇不是一個結論**
③ ✅ 已查（見 §2）：07/31 與 08/05 之間 `calcSummary()` 多了這個欄位
   ⚠️ 而我**沒有去 git 歷史確認是哪一個 commit 加的** ——
      「8 月初加的」是從 finalizedAt 的分界推的，不是從 diff 讀的
   🔑 推論成立不代表成因找到了 ⇒ B 若要確認，去查 `dispatchTotal` 的 blame
④ 警示條同時出現三條時的**版面** —— 沒查（`.stale-banner` 只設計給一條）
⑤ 🔴 `MQ-EXPFILE-001` 的 `summary` **為什麼是 `{}`** —— 沒查
   ⚠️ 它連 `finalizedAt` 都沒有 ⇒ 可能是測試資料手動塞 `status:'finalized'` 造出來的
   🔑 若是，那它**不是一個真實會發生的狀態** —— 而處置**不變**
      （`{}` 是 truthy 這件事與它怎麼來的無關），只是驗收 ⓒ 要標明它是人造的
```
