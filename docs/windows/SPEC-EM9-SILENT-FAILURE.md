# `SPEC-EM9` · 寫入失敗不可以是靜默的

> 座標：`3e9af3e`（工作樹：本檔為新增）
> 作者：視窗 A-2 ／ 2026-09-23
> 起點：查 `EM1` 時撞到的 `inventory.html:744-750`（`SPEC-EM1.md §2c`）

---

## §1 判準

> ### 使用者按下按鈕之後，**失敗與成功長得一不一樣**。

```
GET  失敗  => 畫面空著、清單沒東西  => 使用者**看得到不對勁**
寫入 失敗  => 畫面**跟成功一模一樣** => 他**分不出來**
```

🔑 所以這一題只收**寫入類**（POST／PUT／PATCH／DELETE）。
📌 這個前置判準排在「有沒有顯示錯誤」之前——和 `EM1` 的
「使用者到不到得了這個錯誤」是同一招。

### 結構判準（可機器判定）

> 一支函式裡有寫入型 `fetch`，而**整支函式裡失敗分支不存在**：
> 沒有 `!x.ok`、沒有 `} else`、catch 是空的或沒有 catch。

☠️ **不要用「有沒有 alert／toast」這種詞彙清單**——見 §3。

---

## §2 母體（四輪掃描，座標 `d59f47f`）

```
frontend/**/*.{html,js}（排除 rollback）  fetch( 呼叫點 **608** 個，81 個檔

v4 命中（寫入類 × 整支函式無失敗分支）        = **69**
  − logout() 同一份複製碼                     = 20   （§4a 排除，有理由）
  − 函式邊界沒抓到 10 處 => **已逐一讀完**（§4b）
        ❌ 誤報 3 ／ ✅ 有理由排除 4 ／ 🔴 真命中 **3**
  ────────────────────────────────────────────────
  要處理的                                    = 39 + 3 = **42**
```

🔑 §4b 那 10 處**三種結果都出現了** —— 誤報、該排除、真缺陷。
⇒ 「工具判不出來的那一批」**不可以整批排除，也不可以整批當缺陷**。
☠️ 其中 `vendor-contractors.html:779`（銀行存摺 PUT 沒驗 `r.ok`）
   是**被外層的 `!r.ok` 誤判成安全**的 —— 那一句是**前一支 fetch** 的。

### §2a 39 處的分布

```
js/case-management.js   1188 loadCaseActivity      POST
                        2125 addStageAssignee      POST
                        2133 removeStageAssignee   DELETE
                        2455 updateVisit           PUT
                        2479 dragEnd               PATCH
                        3104 deleteUpdate          DELETE
                        3347 deleteDispatch        DELETE
dev-crm.html            1761 changeStatus          PATCH
                        1795 cancelDeleteRequest   POST
                        1955 deleteLog             DELETE
                        1960 approveLog            PATCH
                        1971 approveLogFromModal   PATCH
                        2023 cancelRelinkRequest   POST
                        2054 markConverted         PATCH
inventory.html           747 adjustItem            POST     <= 起點
                         755 deleteItem            DELETE
contractors.html         687 toggleActive          PATCH
                         702 toggleActiveFromPane  PATCH
users.html              1268 toggleActive          PATCH
customer-log.html        782 persist               PATCH
supplier-log.html        758 persist               PATCH
daily-tasks.html        3552 moveTaskCategory      PUT
parts.html               672 deletePart            DELETE
tender-radar.html        779 remove                DELETE
payslip-form.html        758 confirmExport         POST
                         804 downloadArchivePreview POST
payslips.html            445 confirmExport         POST
                         501 downloadArchivePreview POST
payment-request-form.html 708 confirmExport        POST
static/edit-presence.js  175 release               DELETE   （背景，見 §4c）
static/list-sort.js       21 saveListPref          PUT      （背景，見 §4c）
static/notif.js          219 _markAllRead          PATCH
guide 六頁 deleteItem(kind, item)  DELETE  —— **同一份複製碼 ×6**
   access:858 ／ automation:858 ／ gateway:858 ／ monitor:858
   ／ switch:858 ／ netarch:521
```

### §2b 起點那一支逐字

```js
// frontend/pages/inventory.html:743-750
async adjustItem(it, action) {
  const label = action === 'void' ? '報廢' : '退回庫存'
  if (!confirm(`確認將序號「${it.serial_no}」設為「${label}」？`)) return
  try {
    const r = await fetch(`${API}/inventory/stock-items/${it.id}/adjust`, {...})
    if (r.ok) { await this.openDetail({...}); await this.load() }   // <= 沒有 else
  } catch {}                                                        // <= 沒有訊息
}
```
☠️ 使用者按「報廢」、按「確認」、**而畫面什麼都不做**。

---

## §3 ☠️ 這支掃描器過報過一次，**那一列留著**

```
v2 判準：區塊裡找不到 alert( / toast( / Err= / Msg= ... => 判為靜默
v2 結果：71 處
v2 抽查：case-management.js 的 558／576／726／746 —— **四處全部在過報**
         它們都有 `this._xeFail('上傳失敗：' + (d.detail || r.status))`
         而 `_xeFail` **不在我的詞彙清單裡**
```

### 🔑 最貴的一句：**正負對照當時是通過的**

```
⚙️ 正對照 inventory.html:747  ✅ 亮
⚙️ 負對照 approval-queue.html:1573（alert(detail)）  ✅ 沒有誤收
=> 兩個對照都綠，**而判準是壞的**
```

> **對照只證明工具認得「那一種」寫法，證明不了判準完整。**

📌 修法（v3／v4）：把判準從**字彙**換成**結構**——
不問「有沒有顯示錯誤」，問「**失敗分支存不存在**」。
🔑 判準是〈修作法不要修結果〉：把 `_xeFail` 加進清單只會讓第五次晚一點到。

### v3 又被抓到兩個（第二輪抽查）

```
☠️ 區塊取太小：users.html:1228 的 `!res.ok` 在**外層** => 誤報
☠️ try { } 的 catch 不在區塊裡 => 非空 catch 看不到 => 會誤報
=> v4 把單位從「最近一對大括號」換成「**整支函式**」
   理由：使用者按一次按鈕 = 跑一支函式
```

---

## §4 排除，**每一條都要有理由**（不是「看起來還好」）

### §4a `logout()` ×20 —— **排除**

```js
logout() {
  fetch(`${API}/auth/logout`, { method:'POST', ... })   // 射後不理
  localStorage.removeItem('motrix_session'); location.href = 'login.html'
}
```
✅ **設計上就該這樣**：本機一定要登出，後端通知失敗不該擋住使用者離開。
⚠️ 而它是**同一份複製碼散在 20 個檔**——不是 20 個決定，是 1 個決定抄了 20 次。

### §4b 函式邊界沒抓到的 10 處 —— ✅ **已逐一讀完**（A-2，`75a9737` 之後）

工具外擴會停在 `if`／`for`／`.then` 上，所以這 10 處它沒有能力判定。
🔴 **不可以整批排除，也不可以整批當缺陷** —— 三種結果都出現了：

#### ❌ 誤報 3 處（失敗分支在**外層**，工具切太早）

```
dev-crm.html:1923             `let r` + if/else 兩支 fetch，
                              下面有 if (!r.ok) { this._toast(d.detail || '儲存失敗') }
payment-request-form.html:591 同一形狀，下面有 this.errMsg = ...detail || '儲存失敗'
users.html:1228               同一形狀（第二輪抽查時已驗過）
```
🔑 三處是**同一個寫法**：`let r` 先宣告、`if/else` 兩支 fetch、共用一段 `!r.ok`。
⇒ 守門日後要認得這一形狀，否則它會一直報這三處。

#### ✅ 排除 4 處（有理由）

```
case-management.js:1652   _seedDefaultStagesIfEmpty   背景補建預設階段
quotation-form.html:3587  _seedDefaultStagesIfEmpty   同一份複製碼
                          => 使用者沒按按鈕；補建失敗的話看板是空的，**他看得到**
sidebar.js:161            motrixLogout                同 §4a（射後不理是對的）
login-qr-approve.html:255 QR 自動登入
                          🔑 **刻意的，而且碼裡有逐字註解**：
                          「靜靜退回手動輸入密碼表單，不特別顯示成『錯誤』，
                            因為『這支手機沒登入過這個帳號』是完全正常、
                            預期中的情況，不是使用者的操作失誤。」
                          => 有人做過決定，不是漏掉的
```

#### 🔴 真命中 3 處 —— 而且是**一個新類別**

```
quotation-form.html:2910  改成交標籤   this.q.dealTag = newTag  先改畫面
                                       再 PATCH ... .catch(() => {})
quotation-form.html:3180  匯出 PDF     this.q.exportCount++ 先加
                                       再 POST /export  .catch(() => {})
vendor-contractors.html:779  存摺 PUT  ☠️ 見下
```

> ## ☠️ 新類別：**樂觀更新 ＋ 靜默失敗**
>
> 一般的靜默失敗是「**他不知道失敗了**」。
> 這一類是「**他看到了一個假的成功狀態**」——畫面已經改了，而後端沒有。
> 🔑 下次開啟頁面它會變回去，**而那時候看起來像系統把他的資料弄丟了**。

##### 🔴 `vendor-contractors.html:779` 要單獨講

```js
const r = await fetch(url, {...})
if (!r.ok) { this.errMsg = (...).detail || '儲存失敗'; this.saving = false; return }   // 這是**前一支**的
const d = await r.json()
const targetId = this.editId || d.id
if (this.bankPassbookPreview !== null && targetId) {
  await fetch(`${API}/vendor-contractors/${targetId}/passbook`, { method: 'PUT', ... })  // <= **完全沒驗 r.ok**
}
this.showModal = false      // <= 視窗關掉
await this.load()           // <= 看起來存好了
```

☠️ 使用者上傳**銀行存摺影本**，視窗關了、清單刷新了，**而存摺沒有存進去**。
🔑 它是這 10 處裡**唯一一個被外層的 `!r.ok` 誤判成安全**的——
外層那一句是**前一支 fetch** 的，而人眼掃過去會以為這一段有保護。
📌 而它落在個資那條線上（`STATE.md §3t`：存摺／銀行帳號）。

⇒ **這一處建議獨立編號、優先於其餘 39 條。**

### §4c 背景自動呼叫 3 處 —— **降級，不排除**

```
edit-presence.js:175  release()        離開頁面時釋放編輯鎖
list-sort.js:21       saveListPref()   排序偏好自動存
notif.js:219          _markAllRead()   通知全部已讀
```
⚠️ 使用者**沒有按按鈕**，所以沒有「等待結果」的期待 ⇒ 不必跳錯誤。
🔴 **但 `_markAllRead` 是他按的**——它按了之後紅點沒消，他會再按一次。
⇒ `_markAllRead` 留在要修的那一側；另外兩支降級。

---

## §5 處置：**分兩層，不要全部加 toast**

### ① 必須說話（39 − 排除 後的那些）

```
失敗時至少要有一句使用者看得到的話，**而且要說失敗的是什麼動作**
  ✅ 「報廢失敗：庫存項目已被異動」
  ❌ 「操作失敗」          <= 他有三個按鈕，不知道是哪一個
  ❌ console.error(...)    <= 使用者看不到 devtools
```

### ② 成功回饋**不強制**

⚠️ 不要順手在 39 個地方都加成功 toast——
**那會把一個「失敗看不見」的問題換成一個「畫面一直跳訊息」的問題**，
而且它不在任何人的裁示裡。
🔑 判準是**失敗時他知不知道**，不是**成功時他爽不爽**。

### ③ guide 六頁：**改一次，同步六份**

```
access ／ automation ／ gateway ／ monitor ／ switch ／ netarch
同一份 deleteItem(kind, item)，只有端點名與標籤字串不同
⚠️ 只改其中一份 = 五份還是靜默的，而**測試若只測一頁會全綠**
```

---

## §6 守門

### ✅ 釘的不變量

> 前端每一個寫入型 `fetch`，**它所在的函式裡必須存在失敗分支**。

### ⚙️ 對照組

```
正對照  inventory.html:747  adjustItem          **必須亮**
        dev-crm.html:1795   cancelDeleteRequest **必須亮**
負對照  case-management.js:558  xeUploadFile（有 _xeFail）  **不可以亮**
        users.html:1228       saveUser（!res.ok 在外層）  **不可以亮**
        🔑 這兩個負對照是**兩種不同的失效**：
           前者驗「認不認得自訂 helper」，後者驗「區塊取得夠不夠大」
誘餌    自己留一支合成的靜默函式，確認新寫的也會被抓到
        ⚠️ 不要拿上面 39 條的任何一條當誘餌 —— 它們修好那天誘餌就失效
```

### 🔴 排除清單要有反向控制

```
logout ×20 與背景 2 支是**明著排除**的
=> 要有一題驗「排除清單的長度沒有變長」
   否則可以靠把命中全寫進排除清單變綠
```

---

## §7 驗收（`AC1`）

```
① 後端  不涉及
② 前端  §2a 清單（扣掉 §4 排除項）每一支都有失敗分支且有訊息
③ 頁面  斷網或讓端點回 403，按下按鈕：
        ⓐ 畫面出現一句話，且那句話**指名是哪個動作**
        ⓑ 列表**不可以**看起來像成功了
        🔑 ⓑ 是重點 —— 目前的症狀是「畫面沒變」，
           而「失敗」與「成功但沒刷新」對使用者是同一件事
```

---

## §8 我沒查什麼

```
① ~~§4b 那 10 處沒逐一打開~~ => **已補做**（見 §4b），但那是**讀**不是**跑**
② 「有失敗分支」不等於「訊息說得清楚」—— 本規格**只驗分支存在**，
   訊息措辭是 `EM1` 的題目
③ 回饋寫在**呼叫者那一層**的情形（本函式 return false，外面才 alert）
   —— v4 取到函式為止就停，**跨函式的沒追**
   ⇒ 這一類會被算成命中 => §4b 的人工判讀就是在擋它
④ 非 fetch 的寫入（XMLHttpRequest／form submit／a[download]）
```
