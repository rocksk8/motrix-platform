# `SPEC-EM12` · 跨 fetch 的假保護

> 座標：`50a8d13`（工作樹：本檔為新增）
> 作者：視窗 A-2 ／ 2026-09-23
> 來源：查 `EM9` §4b 那 10 處時撿到 `vendor-contractors.html:779`，
> A 發編號並批准盤點（`§5z`）。

---

## §1 判準 —— **它不是 `EM9`，而 `EM9` 抓不到它**

```
EM9   問「這**支函式**有沒有失敗分支」
EM12  問「這**一支 fetch** 的回應有沒有被檢查」
```

> ### ☠️ **一個「有保護」的函式裡，可以有一支完全沒被保護的請求。**

`EM9` v4 掃 `vendor-contractors.html` 的 `save()` 時**沒有把它列進來** ——
因為那支函式**有**失敗分支（屬於**前一支** fetch 的）。

### 逐支比對，**不是數數量**

A 2026-09-23 指出：光數「有幾個 `if (!r.ok)`」不夠，
`779` 那一處**數量對得上而對象錯了**。⇒ 判準改成：

```
每一支**寫入型** fetch（POST／PUT／PATCH／DELETE）各自問：
  ① 裸 `await fetch(...)`，沒指派、也沒接 .then/.catch      => **沒被檢查**
  ② 指派給 X，而從這一支之後到函式結尾找不到 `X.ok`／`X.status` => **沒被檢查**
  ③ 只接了一個**空的** `.catch(() => {})`                    => **沒被檢查**
```

---

## §2 母體（`d59f47f` 實掃）

```
含 2 支以上 fetch 的函式              = **44 支**
其中「這一支寫入沒被檢查」            = **7 處**
   🔴 真的要修            = **2 處**
   🟡 降級（有理由，不排除）= **5 處**
```

### ⚙️ 三個對照組全部通過

```
⚙️ 正對照 vendor-contractors.html:779（存摺 PUT）  ✅ 亮
⚙️ 正對照 contractors.html:666（身分證 PUT）      ✅ 亮
⚙️ 負對照 module-versions.html（`.then` 有檢查）   ✅ 沒有誤收
```

---

## §3 🔴 要修的 2 處 —— **兩處逐字同構，而都在個資線上**

```
pages/contractors.html:666         PUT /contractors/{id}/id-card
                                   送的是 **身分證正面＋反面＋存摺**
pages/vendor-contractors.html:779  PUT /vendor-contractors/{id}/passbook
                                   送的是 **存摺**
```

```js
const r = await fetch(url, {...})
if (!r.ok) { this.errMsg = …; this.saving = false; return }   // <= 這是**前一支**的檢查
const d = await r.json()
const targetId = this.editId || d.id
if (…Preview !== null && targetId) {
  await fetch(`.../id-card`, { method: 'PUT', … })            // <= **裸的，完全沒接回應**
}
this.showModal = false      // 視窗關掉
await this.load()           // 清單刷新
```

> ### ☠️ 使用者上傳身分證／存摺，**視窗關了、清單刷新了，而檔案沒有進去。**

🔑 而它**被外層的 `!r.ok` 誤判成安全** —— 那一句屬於**前一支 fetch**，
而**人眼掃過去會以為這一段有保護**。
📌 落在 `STATE.md §3t` 那條個資線上（存摺／銀行帳號／身分證掃描檔）。

### 狀態

```
✅ vendor-contractors.html:779  B 已修（`b349ee7`）
🔴 contractors.html:666         **還沒修** —— 而它送的欄位**比另一支多兩個**
                                （身分證正面／反面）
```

### 修法

```js
const r2 = await fetch(`${API}/contractors/${targetId}/id-card`, {...})
if (!r2.ok) {
  this.errMsg = (await r2.json().catch(() => ({}))).detail || '證件檔上傳失敗'
  this.saving = false
  return                     // 🔴 **不要關視窗、不要刷新清單**
}
```

⚠️ **主檔已經存成功了，而證件檔沒有** —— 這是一個**部分成功**的狀態。
```
訊息要說清楚是**哪一半**失敗：
  ✅「基本資料已儲存，而**證件檔上傳失敗**（…），請重新上傳」
  ❌「儲存失敗」 <= 他會以為整筆都沒存，然後重打一次
```

---

## §4 🟡 降級的 5 處 —— **不排除，而不是這一件的主體**

```
js/case-management.js:874   previewCompletionPdf
js/case-management.js:3693  downloadShippingPdf
js/case-management.js:3946  downloadContractorVoucherPdf
js/case-management.js:4212  downloadInvoiceVoucherPdf
pages/completion-note-form.html:510  previewPdf
```

形狀相同：**PDF 已經 `window.open` 之後**，補一支
`POST …/export?mode=preview` 並 `.catch(() => {})`。

```
✅ 使用者**拿到 PDF 了** => 不是假的成功狀態，不是 EM11
⚠️ 而失敗時**匯出紀錄少一筆，而沒有人會知道** —— 那是**稽核軌跡**
```

📌 只有 `downloadShippingPdf:3693` 有註解說明是刻意的
（「記錄匯出（fire-and-forget，不阻塞 PDF 下載）」）。
⇒ **其餘 4 處補同一句註解**，讓下一個掃描的人不用重查一次。

---

## §5 驗收（`AC1`）

```
① 後端  無異動
② 前端  contractors.html:666 檢查 r2.ok；失敗時**不關視窗、不刷新**
③ 頁面  ⓐ 讓 `/contractors/{id}/id-card` 回 500（或斷網），上傳身分證後按儲存
           => **視窗不關**，且訊息說得出是**證件檔**失敗
        ⓑ 主檔的內容**仍然存進去了**（部分成功要說清楚，不是整筆回滾）
        ⓒ 負對照：一切正常時，視窗**照常關閉**、清單**照常刷新**
           🔑 少了 ⓒ，「乾脆永遠不關視窗」也會綠
```

---

## §6 守門

```
✅ 釘：`frontend/**` 的每一支寫入型 fetch，**它自己的回應要被檢查**
   ⚙️ 正對照 §3 那 2 處 —— **改之前都要亮**
   ⚙️ 負對照 module-versions.html 的 `.then(r => r.ok ? … : …)` **不可以亮**
   🎣 誘餌   自己留一支合成的「兩支 fetch 而只檢查第一支」的函式
             ⚠️ **不要拿 §3 那兩處當誘餌** —— 它們修好那天誘餌就失效

✅ 排除清單：§4 那 5 處明著寫進去並註明「**fire-and-forget，有理由**」
   ⚠️ 反向控制：清單長度**除了那 5 筆以外不可以變長**
```

### ☠️ 而這道守門的工具本身有一個**已知會壞的地方**

```
判「哪一支 fetch」要先知道「**這支函式從哪裡到哪裡**」
而 `if (...) {` / `for (...) {` / `while (...) {` 在正則上**與函式標頭完全同形**
=> 負向前瞻必須配 `(?<![\w$])`，否則往後挪一格（`if` 的 `f`）就繞過去了
```
🔑 這不是假設 —— **我的掃描器就是這樣壞掉的**（見 §7）。

---

## §7 ⚠️ 這份盤點的工具壞過兩次，**兩次都留著**

### 第一次：`\b` 被 heredoc 吃掉

```
用 bash heredoc 寫掃描器 => `function\b` 變 `function`、`(?:if|for|…)\b` 變 `(?:if|for|…)`
=> `if (...)` 被當成函式邊界 => `779` 那支 fetch 自己一組
=> `len(poss) < 2` 篩掉 => **正對照不亮**
```

> ### 🔑 最有診斷價值的訊號是：**我連改三次正則，輸出一字不差。**
> ### **改動之後輸出完全相同，不是「這個改動不重要」，是「改的東西沒生效」。**

⚠️ 而它與記憶裡那一條的**方向相反**：
```
記的是    `\b` 被壓成 0x08 => 永遠不匹配 => **假陽性**
這次是    `\b` **整個消失** => 匹配更寬  => **假陰性（少報缺陷）**
```
📌 ⇒ 掃描器改用 `Write` 工具寫，不走 heredoc。

### 第二次：`this.fetch()` 被當成瀏覽器 API

```
`\bfetch\(` 會命中 `this.fetch(`（`.` 是 `\b` 認得的字界）
=> module-versions.html 的 3 處頁面自訂重載方法被收進來
✅ 而它**沒有污染這份母體**：自訂 fetch 不帶 `method:`，全被歸成 GET 排掉了
   （實際查過，不是推的）
⇒ 正確的 pattern 是 `(?<![.\w])fetch\(`
```

---

## §8 我沒查什麼

```
① 「這一支 fetch 失敗時，畫面**應該**怎麼辦」我只對 §3 那兩處寫了
   其餘 5 處是**降級**，而降級之後**要不要補一個安靜的重試**沒查
② 跨函式的檢查（本函式 return false，呼叫者才判）—— **沒追**
   ⚠️ 那一類會被算成命中 => §3/§4 的分類就是在擋它，而我只逐一看了這 7 處
③ 非 `fetch` 的寫入（XMLHttpRequest／form submit）—— 沒查
④ `contractors.html:666` 那一處**我沒有實際跑過**失敗情境
   ⇒ 「視窗會關、清單會刷新」是**讀碼所得**
```
