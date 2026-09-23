# `SPEC-EM3` · 例外的內容不可以上畫面

> 座標：`d0da890`（工作樹：本檔為新增）
> 作者：視窗 A-2 ／ 2026-09-23
> `STATE.md` 原列：「**19 處**把例外物件直接放進 `detail`」
> ⇒ **複量結果 18，而母體要先切成三層**（§2）。

---

## §1 判準

> ### 這個 `detail` 會不會把**我們沒有寫過的字**送到使用者畫面上？

```
資料表名 ／ 欄位名 ／ 暫存檔路徑 ／ SQL 片段 ／ 函式庫版本
=> 它們全部來自例外物件，而**沒有一個是我們決定要說的**
```

### 🔴 而「把 `{e}` 拿掉」**不是修法**

```
❌ raise HTTPException(500, "PDF 產生失敗")
   => 畫面乾淨了，而**診斷能力一起消失** ——
      客戶說「PDF 產生失敗」，而我們手上什麼都沒有
✅ raise HTTPException(500, f"PDF 產生失敗（代碼 {trace_id}）")
   ＋ logger.exception("pdf_gen failed trace=%s", trace_id)
```
🔑 **要移動的是「例外內容的去處」，不是把它刪掉。**

### ⚠️ 補記（2026-09-23 同日）：**那個「去處」的終點今天是斷的**

```
⚙️ `EM7 §6` 實查：`logs/server.log` **沒有任何端點或頁面呈現它**
=> 客戶報「代碼 a3f9」之後，唯一的查法是**進正式機 grep**
```
> ### 🔑 而這**不改變本規格的修法** —— `trace_id` ＋ `logger.exception`
> ### 仍然是對的第一步（今天連 `trace_id` 都沒有）。

```
🔴 改變的是**它能宣告什麼**：
   ✅ 可以說「出事時查得回來」
   ❌ **不可以**說「使用者報代碼給我們就查得到」——
      那中間少了一個「誰去查、怎麼查」
⇒ 落點的三層見 `SPEC-EM7 §6`；而是否要為 `trace_id` 做一個查詢入口，
  是一個**獨立的決定**，不在本規格範圍
📌 而我把它寫在這裡而不是改掉修法 ——
  🔑 〈推翻的證據不會自動支持替代方案〉：
  「log 沒有出口」推翻了「寫進 log 就完成了」，
  **而它不自動支持「所以要改成別的做法」**
```

---

## §2 母體：**三層，18 / 17 / 18**

判定用 AST（不掃字串）：`HTTPException(detail=X)` 而 X 的運算式引用到
`except … as e` 綁的名字。

```
🔴 A 組  except **Exception**              **18 處**  <= **要改**
🟡 B 組  except **我們自己的例外類別**      **17 處**  <= 🔴 **不要動**
🟢 C 組  except ValueError／RuntimeError     18 處    <= **本輪不動**（§5）
⚙️ 加總 18 + 17 + 18 = **53** ✅
```

### ☠️ 我第一版數出 **53**，而那是把三種東西數成一個

🔑 〈判準的寬窄都會騙人〉的施作版：
> **報一個數字之前，先問「這個母體裡有幾種東西」，答不出「一種」就要先切開。**

---

## §3 🔴 A 組 **18 處** —— 要改的就是這些

```
routers/completion_notes.py    :636   f'PDF 產生失敗：{e}'
routers/contractor_vouchers.py :652   f'PDF 產生失敗：{e}'
routers/customers.py           :82    f'建立失敗：{e}'
routers/invoice_vouchers.py    :686   f'PDF 產生失敗：{e}'
routers/network_plans.py       :270   f'拓樸圖產生失敗：{e}'
routers/network_plans.py       :340   f'檔案解析失敗，請確認上傳的是本系統匯出的 Excel 範本：{e}'
routers/network_plans_quick.py :37    f'拓樸圖產生失敗：{e}'
routers/payment_requests.py    :843   f'PDF 產生失敗：{e}'
routers/payslips.py            :430   f'PDF 產生失敗：{e}'
routers/payslips.py            :447   f'PDF 產生失敗：{e}'
routers/quotations.py          :1353  str(e)
routers/quotations.py          :4841  f'PDF 產生失敗：{e}'
routers/quotations.py          :5004  f'結案報表 PDF 產生失敗：{e}'
routers/quotations.py          :5033  f'專案執行報告 PDF 產生失敗：{e}'
routers/shipping_notes.py      :597   f'PDF 產生失敗：{e}'
routers/suppliers.py           :82    f'建立失敗：{e}'
routers/system.py              :1898  f'建立測試事件失敗：{e}'
routers/system.py              :1921  f'SMTP 連線失敗：{e}'
```

⚠️ `quotations.py:1353` 是 **`str(e)` 單獨用** ——
它連一句自己的話都沒有，使用者看到的**整句都是例外文字**。

---

## §4 🔴🔴 B 組 **17 處** —— **不要動，而它們看起來一模一樣**

```
routers/bonus.py                :636          UnresolvedManagerError
routers/case_extra_expenses.py  :340  :865    UnresolvedManagerError
routers/completion_notes.py     :399  :492    UnresolvedManagerError
routers/contractor_vouchers.py  :399  :500    UnresolvedManagerError
routers/invoice_vouchers.py     :438  :538    UnresolvedManagerError
routers/payment_requests.py     :596  :695    UnresolvedManagerError
routers/quotations.py           :1444 :4361   UnresolvedManagerError
routers/shipping_notes.py       :293  :397    UnresolvedManagerError
routers/vouchers.py             :487          UnresolvedManagerError
routers/vouchers.py             :878          **MissingOldValue**
```

> ### ☠️ 它們的寫法是 `str(e)` —— **與 A 組的 `quotations.py:1353` 完全一樣**。
> ### 而 `UnresolvedManagerError` 是**我們自己 raise 的**，
> ### `str(e)` 拿到的是**我們自己寫的那句話**（「找不到 X 的主管」之類）。

🔑 **改掉它們 = 把我們自己寫的訊息換成一個追蹤碼** ——
使用者從「知道是誰沒設主管」變成「拿到一串代碼」。

📌 這是〈機械修法會刪掉解釋修法的那段文字〉的變形：
**一個以「把 `str(e)` 清成 0」為目標的修法，會連這 17 處一起清掉。**

---

## §5 🟢 C 組 18 處 —— **本輪不動，而理由要寫下來**

```
except ValueError／RuntimeError as e: raise HTTPException(400, str(e))
```

```
它們**多半**是我們自己 `raise ValueError("…")` 的驗證錯誤
⚠️ 而**多半**這兩個字就是不動它的理由 —— 我**沒有逐處追誰丟的**
   （`int()`／`json.loads()`／`date.fromisoformat()` 丟的 ValueError
     會把函式庫的英文訊息送上畫面）
```
⇒ 本輪列為**待查**，不是「已判定安全」。
🔴 **不可以在驗收裡寫「C 組 = 0」** —— 那會把它們推向「一起改掉」。

---

## §6 落地形狀

### §6a 追蹤碼：**一支共用 helper，而它不可以是序號**

```python
# helpers/errors.py（新）
def trace_id() -> str:
    """給使用者看的錯誤代碼。**不可猜、不可枚舉。**"""
    return secrets.token_hex(4)      # 8 碼 hex
```

```
❌ 流水號（ERR-001、ERR-002）=> **可猜**，而且它洩漏「系統出過幾次錯」
❌ 時間戳                     => 可猜，且兩個同時發生的錯會撞
✅ 隨機 8 碼 hex
```
⚠️ 而 `secrets` 不是 `random` —— `random` 可預測。

### §6b 兩邊都要有，**而且是同一個值**

```python
except Exception as e:
    tid = trace_id()
    logger.exception("completion_note pdf failed trace=%s", tid)   # 全文進 log
    raise HTTPException(500, f"PDF 產生失敗（代碼 {tid}）")          # 畫面只有代碼
```

☠️ **順序不可以顛倒** —— 先組訊息再 log 的話，
log 失敗時使用者拿到一個**查不到的代碼**，而那比沒有代碼更糟。

### §6c ⚠️ 訊息的前半段**要保留**

```
✅ 「**PDF 產生失敗**（代碼 a3f9c201）」
❌ 「操作失敗（代碼 a3f9c201）」
🔑 A 組那 18 處**已經有**一句自己的話（除了 quotations.py:1353）
   => 改的是後半段，**不是整句重寫**
```

📌 而 `quotations.py:1353` 沒有自己的話 ⇒ **要補一句**，
而補什麼要看那一段在做什麼（B 開工時決定，規格不猜）。

---

## §7 驗收（`AC1`）

```
① 後端  A 組 18 處：detail 不含例外內容、含追蹤碼；log 有全文且**同一個 tid**
② 前端  無異動
③ 頁面  ⓐ 讓 PDF 產生失敗 => 畫面顯示「PDF 產生失敗（代碼 XXXXXXXX）」
        ⓑ 拿那個代碼去 `logs/server.log` **搜得到**，且那裡有例外全文
           🔑 ⓑ 是這一件的重點 —— 沒有它，追蹤碼只是一個好看的裝飾
        ⓒ 連續觸發兩次 => **兩個不同的代碼**（不是同一個、也不是 +1）
```

### 🔴 兩個數字都要釘死

```
✅ 該改的       = **18**（§3 逐行列名）
✅ **不該動的**  = **17**（§4 逐行列名）
⚠️ 待查的       = 18（§5，**不列入任何一邊**）
```

> ### ☠️ 只釘「該改的 = 18」而不釘「不該動的 = 17」，
> ### 會讓一個以「清乾淨」為目標的修法**把 B 組一起清掉，而驗收全綠**。

⚙️ **反向控制**：B 組那 17 處的 `str(e)` 要有一題**斷言它們還在**。
🔑 〈守門要驗有沒有人做過決定〉—— 而「該改的 = 0」這種條件**本身就是推力**。

---

## §8 我沒查什麼

```
① C 組 18 處**沒有逐處追誰丟的 ValueError／RuntimeError**（§5）
   ⇒ 它們是「待查」不是「安全」
② 例外先存進中間變數再放進 detail（`msg = str(e)` -> `detail=msg`）——
   **我的 AST 掃不到**，而它是同一件事
   ⚠️ ⇒ **18 是下限不是全貌**
③ 非 `HTTPException` 的出口（直接 `return {"error": str(e)}`）—— 沒查
④ 前端有沒有把 `detail` 再寫進別的地方（localStorage／console）—— 沒查
   📌 〈外洩的出口不一定是你寫的〉：uvicorn access log 記的是網址，
      而 detail 走的是回應主體 —— **那一條在這裡不適用**，我確認過
⑤ `logs/server.log` 的**保存期限與存取權限** —— 追蹤碼要能查得到才有意義，
   而「誰查得到 log」我沒查
```
