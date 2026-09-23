# `JV10`／`JV11` 傳票預覽 ＋ 匯出閘門 —— 施工圖

> A-2 撰寫／2026-09-23。量測座標 **`ea27ce8`**，量測時工作樹 **2 個異動**（不是我的）。
> **單一版本、無修訂層。照這一份做。**

**使用者原話（逐字）**
```
「傳票匯出pdf顯示尚未設定公司抬頭，要有預覽功能，匯出PDF跟匯出PDF(含附件)，
  未審核通過前不能匯出，並且需背景顯示該流程尚未簽核完成的紅字，像是報價單一樣，
  可原視窗預覽並且預覽後匯出」
```

A 已裁（**不要重新討論**）：
```
🔑 **預覽隨時可看（帶紅字浮水印）；匯出要簽核通過** —— 兩件不矛盾，是分工
🔴 **閘門在後端** —— 前端藏按鈕不算
```

---

## §1 沿用報價單的哪些、另立哪些

### 實查（`frontend/pages/quotation-form.html`）

```
:1969  <div class="modal-overlay" x-show="previewMode" x-transition @click.self="previewMode=null">
:1985  <button class="modal-close" @click="previewMode=null">×</button>
:1988    <div class="preview-wrap">
:1989      <div class="pdf-page" id="pdf-preview-content">
:1993/2003   <div class="pdf-watermark">        ← **兩個，條件不同**
:477   .preview-wrap { … }
:495   .pdf-watermark { position:absolute; inset:0; pointer-events:none; z-index:5;
                        display:grid; grid-template-columns:repeat(3,1fr);
                        grid-template-rows:repeat(4,1fr); }
```

**兩個浮水印各自的條件與文字（逐字）**
```
① x-if="q.dealTag === '未成案'"
     「本案報價未成立」 ／ 「僅供存查使用」「僅供備存使用」（交錯）
② x-if="q.dealTag !== '未成案' && q.status !== '已送出' && q.status !== '已確認'"
     「報價單預覽稿」 ／ 「尚未正式生效」
```

### ⇒ 沿用 **CSS**，**不共用 DOM**

```
✅ 沿用   .modal-overlay ／ .preview-wrap ／ .pdf-page ／ .pdf-watermark
          —— 它們是**版面機制**（遮罩、置中、3×4 浮水印格），與單據種類無關
❌ 不沿用 #pdf-preview-content 這個 **id**
          —— id 全頁唯一；傳票另立 #voucher-preview-content
❌ 不共用 浮水印的**條件與文字**（報價單的條件讀 dealTag／status，傳票讀簽核鏈）
```
🔴 **而 A 的界線我加一層落地：不要把報價單的樣式「改成」共用。**
```
今天       .pdf-watermark 定義在 quotation-form.html 的 <style> 裡
要沿用     **複製一份到傳票頁**，或抽到共用 css
☠️ 而「抽到共用 css」＝ 一個改動同時動到兩張單據
   ⇒ 本輪**複製**，並在兩邊各留一行註解指向對方
📌 那是刻意的重複：兩張單據的視覺**現在**一樣，而沒有人保證它們永遠一樣
```

---

## §2 🔴 `②` 匯出（含附件）在沒有附件時 —— **今天會「安靜地成功」**

### 實查

```
helpers/voucher_pdf.py:374   if with_attachments:
                                 rows = SELECT … WHERE voucher_id=? AND deleted_at=''
                             ⇒ 0 筆 => rows=[] => split_attachments([]) => 全空
⇒ 產出的 PDF **與 with_attachments=False 一模一樣**

frontend/pages/voucher.html:~416  <button :disabled="exporting" @click="exportPdf(true)">
                                     匯出 PDF（含附件）
⇒ **只在匯出中才停用**，沒有附件時照樣可以按
```

☠️ **使用者按了「含附件」，拿到一份沒有附件的 PDF，而系統說「已匯出（含附件）。」**
🔑 他分不出「附件沒被併進去」與「本來就沒有附件」—— **兩件事，同一個結果。**

### ⇒ 照 A 裁的：**停用 ＋ 說出為什麼**

```
附件數 0  -> 按鈕 disabled，旁邊一句「這張傳票沒有附件」
附件數 N  -> 按鈕可按，標示「（N 個附件）」
```
⚠️ **附件數要從後端來**（`GET /api/vouchers/{id}` 帶 `attachment_count`），
**不要讓前端自己數它載到的清單** —— 日後加分頁或篩選，那個數字會安靜地變小。
📌 與 `BN5` 的 `custom_count` 同一條。

---

## §3 🔴 `③` 「未審核通過」是哪一個狀態 —— **不要釘狀態字串，也不要釘 v99 六欄**

### 現況

```
helpers/voucher.py:30  VOUCHER_STATUSES = ("草稿","待審核","簽核中","已核准","已過帳")
                  :45  _TERMINAL_STATUSES = ("已過帳",)
vouchers_all 現有欄位  submitted_by/at、checked_by/at、manager_by/at  ← **v99 的固定三格**
                       **尚未有 approval_json**（B 正在做 `AS2 (c)`）
```

### ⇒ 判準：**一個 helper，一個呼叫端**

```python
# helpers/voucher.py
def approval_done(voucher) -> bool:
    """簽核鏈走完了沒有。**這是唯一的判準來源。**"""
```
```
🔴 呼叫端只有一個（匯出端點）⇒ AS2 (c) 落地時**只改這一支的內部**
☠️ 而以下三種寫法**都不可以出現在端點裡**：
   status in ("已核准","已過帳")        <= 釘狀態字串，AS2 之後語意會漂
   manager_by != ""                      <= 釘 v99 六欄，AS2 之後那三格不是真相
   approval_json 的 currentTier 比較     <= 釘實作細節，散出去就是規則有兩份
```
📌 `AS2 (c)` 之後，`approval_done()` 內部改成讀 `approval_json`
（`currentTier >= len(tiers)`，與 `case_extra_expenses` **完全同形**，A 已裁）。
⚙️ **驗收釘的是「呼叫端只有一個」**，不是「它怎麼判斷」——
後者會隨 `AS2` 改變，而前者不會。

### ⚠️ 已過帳的傳票

```
已過帳 ⇒ 必然已核准 ⇒ 匯出必然放行
而**不要**寫成 `status == "已過帳" or approval_done()`
⇒ 那是在 approval_done() 外面又加一個判準 ⇒ 兩份
⇒ 讓 approval_done() 自己涵蓋它
```

---

## §4 `④` 擋下匯出時要說「還差誰簽／第幾關」

### 算得出來，**而今天沒有人吐出它**

```
helpers/tiered_approval.py:329  first_pending_approver(tier) -> {username, displayName, …}
                           :75  current_tier_idx(appr)       -> int
呼叫端：**只有 tiered_approval.py:370 自己**（`plan_self_cascade` 內部）
⇒ 沒有任何端點把它回給使用者
```
🔑 **與 `BN1` 的 `people_for_item` 同一個形狀**：規則寫好了，而沒有人叫它。

### ⇒ 擋下時的回應要帶三件

```
403（或 409）＋ detail 要說出：
  ① 目前在第幾關 / 共幾關        currentTier + 1 ／ len(tiers)
  ② 這一關在等誰                 first_pending_approver(tiers[ct])
  ③ 出路                         「請等候簽核完成後再匯出。」
```
☠️ 只回「未簽核完成，不能匯出」⇒ 使用者不知道**要去催誰**，
而他會去問人 —— 那是〈`action` 留空〉的同一個後果。
⚠️ **`AS2 (c)` 之前** `approval_json` 不存在 ⇒ ①② 算不出來
⇒ 那段期間**只回 ③**，而**不要編一個假的層數**。
📌 ⇒ 實作順序：`JV10` 的閘門可以先上，①② 等 `AS2 (c)`。

---

## §5 `⑤` 已作廢的傳票：浮水印該說什麼 —— **沒有慣例可循**

### 實查

```
backend/pdf_gen.py 對「作廢」命中 **0 次**
前端 .pdf-watermark 只有報價單那兩種條件（未成案／預覽稿）
⇒ **這個 repo 沒有「作廢」浮水印的慣例**
```

### ⇒ 本節**只提建議，等 A／使用者裁**

```
📌 A-2 建議三種浮水印，互斥，依序判斷：
   ① voided_at != ''        「已作廢」／「僅供存查」
   ② 未簽核完成             「尚未簽核完成」／「不得作為憑證」   ← 使用者要的紅字
   ③ 簽核完成而未過帳       「預覽稿」／「尚未過帳」
   簽核完成且已過帳         **無浮水印**（那是正式憑證）
```
⚠️ 而 ①②③ 的**文字**我是照報價單的語感寫的，**不是既有慣例** ⇒ **未裁**。
🔴 而 ① 必須優先於 ②：一張作廢的傳票可能同時「未簽核完成」，
**而使用者要知道的第一件事是它已經作廢**。

### ⚠️ 已作廢的傳票**匯出不受閘門限制**

```
helpers/voucher_pdf.py:363 docstring 逐字：「已作廢的傳票**也要印得出來**」
⇒ 稽核要看得見它當時長什麼樣
⇒ **閘門只擋「未簽核完成而想匯出正式版」**，不擋作廢單
```
📌 那與 `JV5` 的「匯出是唯讀動作」同一條：**拒絕匯出擋住的是使用者**。

---

## §6 `JV11` 預覽：原視窗、預覽後可匯出

使用者原話：**「可原視窗預覽並且預覽後匯出」**。

```
① 預覽 = 同一頁的 modal（不開新分頁、不下載檔案）
   ⇒ 沿用 quotation-form 的 modal-overlay 結構（§1）
② 預覽內容 = **傳票本體的 HTML**，與 PDF 用的是**同一份模板**
   🔴 否則預覽與匯出會長不一樣 —— 而預覽的全部價值就是「所見即所得」
③ 預覽**隨時可看**（草稿也可以），而**帶浮水印**（§5）
④ modal 裡直接有「匯出 PDF」與「匯出 PDF（含附件）」
   ⇒ 未簽核完成時那兩顆**停用**，並顯示 §4 的三件
```

⚠️ **預覽不可以打 `pdf-download`** —— 那會產生一份 PDF 再丟掉（Edge 是稀缺資源，
有 semaphore ＋ 120 秒逾時）。
⇒ 預覽走**回 HTML 的端點**或前端自己用同一份模板渲染，**而模板只有一份**。

---

## §7 驗收（`AC1`：後端＋前端＋頁面三者皆備）

```
後端 ① 未簽核完成 -> `pdf-download` 回 **403**（不是 200 空檔、不是 500）
        ⚙️ **後端擋** —— 直接打 API 也要擋得住（前端藏按鈕不算）
     ② 403 的 detail 含「第 N 關／共 M 關」與**待簽人的名字**
        ⚠️ AS2 (c) 之前只要求含出路那一句
     ③ 🔴 **`approval_done()` 的呼叫端只有一個**
        ⚙️ ast 掃：端點裡不可以出現 `status in (…)`／`manager_by`／`currentTier` 的比較
        ☠️ 這一題是 §3 的全部 —— 它紅而其他全綠 = AS2 上線那天要改五個地方
     ④ 已作廢的傳票 -> **匯出得出來**（不受閘門限制）
     ⑤ GET /api/vouchers/{id} 帶 `attachment_count`
     ⑥ 附件 0 筆而 `?with_attachments=1` -> **不可以回一份與無附件版相同的 PDF
        而訊息說「已匯出（含附件）」**
        ⇒ 後端回應要標明「本次併入 0 個附件」
     ⑦ 先斷言 status_code in (200, 400, 403) 再看內容（`§166` 三種臉）
前端 ⑧ 預覽 modal 可開可關，且**不打 pdf-download**
        ⚙️ 觀測點：預覽時 Edge **不應被呼叫**（計數或 monkeypatch）
     ⑨ 附件 0 筆 -> 「含附件」按鈕 disabled 且旁邊有「這張傳票沒有附件」
     ⑩ 未簽核完成 -> 兩顆匯出鈕 disabled ＋ 顯示還差誰
頁面 ⑪ 預覽內容與匯出的 PDF **同一份模板**
        ⚙️ 觀測點：模板檔只有一份（ast／檔案數），不是比對兩份輸出長得像
     ⑫ 浮水印在預覽上看得到，且 `voided_at != ''` 時顯示的是**作廢**那一種
```

⚠️ **③ 與 ⑥ 是這一份的核心。**
`③` 決定 `AS2` 上線那天要改一個地方還是五個；
`⑥` 是今天就存在、而**沒有人會回報**的那一種（它「成功」了）。

---

## §8 待裁與我沒做的

### 待裁
```
① 三種浮水印的**文字**（§5）—— 我照報價單語感寫的，**沒有既有慣例**
② 已作廢的傳票，浮水印優先序是否照我排的（作廢 > 未簽核 > 預覽稿）
③ 預覽要不要也顯示附件清單（使用者只說「預覽」，沒說預覽什麼）
```

### 我沒做的
```
✗ 沒有實作、沒有跑任何測試
✗ 沒開瀏覽器看報價單 modal 的**實際渲染**（只讀原始碼）
✗ 沒查 `.pdf-watermark` 的 3×4 格在**傳票那種短版面**上會不會擠成一團
  ⚠️ 傳票內容只佔頁高 31.8%（三格版），而報價單是滿頁 ⇒ **視覺結果未驗**
✗ 沒查 `split_attachments()` 對 0 筆的實際回傳（只讀到 rows=[] 這一步）
✗ `approval_done()` 在 `AS2 (c)` 之前要怎麼過渡，我寫了方向而**沒有查 B 的進度**
```
