# `SPEC-JV25` · 傳票預覽的顯示高度過小

> 座標：`abda414`（工作樹：本檔為新增）
> 作者：視窗 A-2 ／ 2026-09-23
> 使用者原話：「**傳票預覽的顯示高度過小**」

---

## §1 🔑 這是 `JV19` 的**副作用**，不是新缺陷

```
JV19 之前  .vc-preview-frame{height:**72vh**}   <= **固定值**
           1280×800 時吃掉 616px 可用高度裡的 576px
           => 只剩 40px 給附件清單與訊息 => **訊息被推出可視範圍**
JV19 之後  改成 flex：iframe `flex:1 1 auto; min-height:220px`
           附件清單與訊息 `flex:0 0 auto` **優先拿滿**
           => **iframe 被壓縮**
```

> ### 📌 修好「看不到訊息」，換來「看不清楚內容」——
> ### ☠️ **同一份高度被三個東西搶。**

🔑 〈防護的副作用落在盲側〉：
**加防護時要問「它擋不到的那一側會不會更難看見」** ——
而這一次那一側是**使用者原本沒有抱怨的那個東西**。

---

## §2 實測：高度是怎麼分掉的

### 版面鏈（`frontend/css/style.css` ＋ `voucher.html` 的覆寫）

```
.modal-overlay   padding: 1rem（16px），align-items: center
.modal-box       max-height: calc(100dvh - 2rem)   => 1280×800 時 **768px**
                 display: flex; flex-direction: column
                 ⚠️ voucher.html:121 覆寫 max-width: 860px（傳票是 A4 版面）
.modal-head      padding 18px 22px，flex-shrink: 0   ≈ 58px
.modal-foot      padding 14px 22px，flex-shrink: 0   ≈ 58px
.modal-body      flex: 1; overflow-y: auto
                 ⇒ 可用 ≈ **652px**（`JV19` 用 Playwright 量到 **616px**，以它為準）
```

### 🔴 而 `.modal-body` 裡面**只有一個東西有上限**

```
.vc-preview-wrap   flex: 1 1 auto; min-height: 220px; padding: 16px   <= **會縮**
.vc-preview-frame  flex: 1 1 auto; min-height: 220px                   <= **會縮**
.vc-preview-atts   **flex: 0 0 auto**                                  <= 🔴 **不縮、沒有上限**
   而 attErr／attMsg 的節點**在它裡面**（voucher.html:573-579）
```

> ### ☠️ `.vc-preview-atts` 是「**拿走它需要的全部高度**」，而它需要多少由附件數決定。

```
一列 .vc-att__row ≈ 28px（font 12~13px ＋ padding）
=> 10 個附件 ≈ 標題 26 ＋ 280 ＋ padding 16 = **322px**
=> iframe 只剩 616 − 322 = **294px**，逼近 min-height:220px 的底線
```

🔑 ⇒ **問題不是「iframe 太小」，是「附件清單沒有上限」。**

---

## §3 處置：**讓三者不要競爭同一份高度**

### ① 訊息搬到 `.modal-foot` 那一層

```
現在  attErr／attMsg 在 .vc-preview-atts 裡（**佔 body 高度**）
改成  搬進 .modal-foot（它已經 flex-shrink: 0，**不佔 body 高度**）
```
✅ 而 `.modal-foot` 已經 `flex-wrap: wrap` ⇒ 訊息與按鈕會自己換行，不必改它的樣式。

⚠️ **而 `JV19` 的保證不可以退化**：
```
JV19 要的是「訊息**在視窗上**不是在背景」
=> 搬到 modal-foot **仍然在視窗上**，而且比原本更穩（它從不被壓縮）
🔴 而 JV19 的三題**不可以退回** —— 見 §5
```

### ② 附件清單：**自己可捲動，且有高度上限**

```css
.vc-preview-atts{
  flex: 0 1 auto;          /* 🔑 從 0 0 改成 0 1：**可以被壓縮** */
  max-height: 140px;
  overflow-y: auto;
}
```

#### 🔴 **140px 的依據**（A 問的那一格）

```
標題列 .vc-preview-atts__hd   ≈ 20px ＋ margin-bottom 6px  = 26
三列 .vc-att__row × 28px                                    = 84
容器 padding-top 12 ＋ padding-bottom 4                     = 16
──                                                          = **126px**
⇒ 取 **140px**（留 14px 餘裕給字型差異）
```

> ### 判準：**不必捲就看得到「有幾筆」以及「前三筆是什麼」。**

```
✅ 而「有幾筆」**已經在標題裡**（`附件（N 筆）`，voucher.html:555）
   => 上限不必容納全部，只要容納「看得出這是什麼東西」的前幾筆
⚠️ 而**不要用百分比** —— `max-height: 30%` 在小視窗上會變成 60px（連標題都放不下）
   🔑 絕對值在這裡比較誠實：**下限由內容決定，不由視窗決定**
```

### ③ iframe 拿回高度，而**高度要穩定**

```
.vc-preview-wrap／.vc-preview-frame 維持 flex: 1 1 auto; min-height: 220px
=> 附件清單封頂 140 之後，iframe 在 1280×800 拿到 ≈ 616 − 140 − 16 = **460px**
   （`JV19` 之前是 576px，之後最糟 220px ⇒ **460 是兩者之間而且穩定**）
```

#### ☠️ 而「穩定」要明著驗

```
🔴 高度**不可以隨狀態變**：
   ① 載入中 -> 載完                    .vc-preview-loading 已是 flex:1 1 auto ✅
   ② 有附件 -> 沒附件                  封頂之後差 ≤140px，而**不會跳到 220**
   ③ **按下匯出的瞬間**（訊息出現）     ✅ 訊息搬到 foot 之後**完全不影響 body**
☠️ ③ 是最刺的一個 —— 使用者**正在看那張紙**，而畫面在他眼前跳動
```

---

## §4 驗收（`AC1`）

```
① 後端  無異動
② 前端  訊息在 modal-foot；.vc-preview-atts 封頂 140px 且可捲
③ 頁面  ⓐ 1280×800，開一張**沒有附件**的傳票 -> 量 iframe 高度
        ⓑ 同一張，**掛 10 個附件** -> 再量一次
           => 兩次的差 **≤ 140px**，且**都 ≥ 400px**
           🔑 ⓑ 是這一件的核心 —— 附件多寡不可以把 iframe 壓到底線
        ⓒ 按「匯出 PDF（含附件）」-> 訊息出現
           => **iframe 高度一個像素都不變**
           ☠️ 那是使用者「正在看那張紙」的那一刻
        ⓓ 附件 10 筆時，清單**自己捲得動**，而不是被裁掉
```

### ⚠️ 量法要固定，否則三次量出三個數字

```
用 Playwright 量 `[data-testid="voucher-preview-frame"]` 的 boundingBox().height
⚠️ 而視窗大小要**明著設定**（1280×800）—— 預設視窗大小會隨環境變
📌 〈瀏覽器量測陷阱〉：隱藏視窗裡 rAF 不跑；量高度前要等 modal 的轉場結束
```

---

## §5 🔴 `JV19` 的三題**不可以退回** —— 它們是這一件的對照組

```
☠️ 「改回固定 72vh」會讓本件的新題**全部綠**
   —— iframe 高度穩定、附件不搶高度、匯出時不跳動
   **而那是把上一個使用者回報放回去。**
```

> ### 🔑 ⇒ 驗收要**同時跑 `JV19` 的三題與本件的四題**，
> ### 而題檔要互相指名。

⚙️ **而 `JV19` 那三題本身要先確認它們現在是綠的** ——
```
⚠️ 若其中有一題現在是紅的，那表示 JV19 的修法已經被某次改動打掉
   => 那是**另一個問題**，不要在這一件裡順手修
```

---

## §6 我沒查什麼

```
① 一列 `.vc-att__row` 的**實際高度**我是**估的**（28px，由 font-size 與 padding 推）
   🔴 ⇒ 140px 這個數字**要 C 量過再定**
   ⚙️ 量法：Playwright 取一列的 boundingBox().height，乘三加標題與 padding
   ⚠️ 而**不要因為量出來是 132 就改成 132** —— 留餘裕是刻意的（字型會變）
② 手機版（`.modal-body{max-height:70vh}` 那一組覆寫，style.css:1383）
   —— **沒查**它在窄螢幕上怎麼分
   ⚠️ 而手機版是另建的 `frontend/m/`，這一頁可能根本不在那裡
③ 附件**檔名很長**時會不會換行 ⇒ 一列變兩列 ⇒ 我的 28px 估算失效 —— 沒查
④ `.vc-preview-loading` 的 `padding:60px` 在 flex 容器裡實際佔多高 —— 沒量
⑤ 使用者說「過小」時**用的是什麼螢幕** —— 沒問
   🔑 而 1280×800 是 `JV19` 量測用的那一台，**不必然是他的**
   ⇒ 若他用的是更小的螢幕，§3 的數字要重算
```
