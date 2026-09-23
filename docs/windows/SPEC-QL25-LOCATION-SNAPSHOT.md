# `SPEC-QL25` · 報價單的據點身分要凍結

> 座標：`ebfd238`（工作樹：本檔為新增）
> 作者：視窗 A-2 ／ 2026-09-23
> 使用者逐字：「預設據點的部分，會強制帶到已經成立或是未成立的報價單，
> **應該以報價單成立當下的據點為主**」
> A 已裁：① 凍結時機＝**按「送出」那一刻** ② 舊單**等使用者填完設定後一次補**

---

## §1 🔴 這一條**翻掉了 `QL10`**，而翻面的守門不會自己翻面

`backend/pdf_gen.py:104-106` 逐字：

```python
# 📌 **讀即時值不做快照**（QL10，A 裁定）：匯款帳號要回答的是
#    「**現在**該匯到哪」——舊單據印出舊帳號，對方會照著匯到一個
#    已經關掉的帳戶。
_ident = location_identity(_location_of(q))
```

☠️ **那段註解會用一個很有道理的訊息擋住正確實作。**
⇒ 改它的時候**必須連同註解一起改**，並寫下「依據 `QL25`（使用者 2026-09-23）」。
📌 〈守門守的對象被搬走〉的鏡像那一面：**裁示翻面，而守門不會自己翻面。**

---

## §2 🔑 而 `QL10` 的理由**套的是請款單，不是報價單**（實查）

```
報價單 PDF 用到的身分欄位（_build_quote_html:107 -> _identity_head / _identity_foot）
   company_name ／ company_name_en ／ tax_id ／ phone ／ email
   🔴 **一個銀行欄位都沒有。**

_ident 的銀行欄位（bank_name／bank_branch／bank_account_number）
   只出現在 pdf_gen.py:2146-2149
   => **`_build_payment_request_html`（請款單），僅此一支。**
```

> ### ⇒ `QL25` 與 `QL10` 的**理由**不衝突，只與它的**射程**衝突。
> `QL10` 的理由（「匯款帳號要回答**現在**該匯到哪」）是對的，
> **而它被寫成一條比自己的理由寬的規則。**

### 🔴 2026-09-23 A 裁定之後，這一段的結論**更強了**

使用者裁「**下游也讀報價單的快照**」⇒ 8 支 builder 全部涉及，含請款單。
而因為快照**只含五個抬頭欄位**（§3 收窄），規則自然分成兩半：

```
抬頭五欄  有快照用快照、沒有才即時查
銀行四欄  **一律即時值** —— `QL10` 原封不動
```

> ### 🔑 `QL10` 與 `QL25` **不必互相讓步 —— 它們管的是不同的欄位。**

☠️ 而這是 §3 那個收窄換來的：**若當初整包存 `location_identity()` 的回傳**，
現在就得在「下游讀快照」與「請款單不可以印舊帳號」之間**二選一**。

⚠️ 這一段要寫進 `pdf_gen.py` 的註解，否則下一個人會把兩半一起改。

---

## §3 快照存哪 —— **照 `QL16`／`QL17` 的先例**

### 先例（薪資單，`pdf_gen.py:570-600`）

```python
company  = d.get('companyName', '')        # ← data_json 的平鍵，存**內容**
tax_id   = d.get('companyTaxId', '')
contact  = d.get('companyContactInfo', '')

if not (company or tax_id or contact):     # 沒快照
    _live = location_identity(None)        # 用即時值
    _reprint_note = '※ 本件甲方抬頭為<strong>現行</strong>公司資料…'   # **而且標明**
```

🔑 先例已經做對三件事：
```
① 存**內容**不存 id      => 據點之後被改，重印不會變
② 落空時用即時值         => 一張印不出來的單比印錯抬頭更糟
③ **而且在文件上標明**   => 〈降級之後它還是會動〉：降級可以，**降級必須看得見**
```

### `QL25` 的落點

```
quotations.data_json["locationIdentity"] = {
    "company_name":    "...",
    "company_name_en": "...",
    "tax_id":          "...",
    "phone":           "...",
    "email":           "...",
    "_locationId":     "loc_1",     # 只為稽核，**不拿來重查**
    "_frozenAt":       "2026-09-23T...",
}
```

⚠️ **不要開新欄位。** `location_id` 已經是欄位（`QL2`），而快照是**內容**，
放 `data_json` 與薪資單一致，且 `save_quotation_json()` 已經在寫它。

⚠️ 欄位集**就是 `_identity_head`／`_identity_foot` 用到的那五個**。
☠️ 不要整包存 `location_identity()` 的回傳（它含四個銀行欄位）——
存了就會有人去讀，而那正是 `QL10` 要避免的。

---

## §3b 落地形狀 —— **一支 helper 取代 8 個呼叫點**

### 🔴 更正：不是「五支」，是 **8 支**（7 支非報價單）

```
❌ 我上一版寫「其他五支 builder（出貨單／完工單／三種憑單／結案報告）」
   —— 那個括號自己就是 **6 類**（1+1+3+1），**數字與它自己的清單對不起來**
   ☠️ 而我手上就有 awk 的輸出（8 個 def），**我沒有去數它**
✅ A 獨立數過（`§5v`），`backend/pdf_gen.py` 呼叫
   `location_identity(_location_of(...))` 的有 **8 處**：
    107 _build_quote_html                     <= QL25 本體
   1039 _build_shipping_html                  出貨單
   1399 _build_contractor_voucher_html        承攬商憑單
   1757 _build_invoice_voucher_html           發票憑單
   2065 _build_payment_request_html           請款單（**唯一印銀行欄位的**）
   2565 _build_case_closing_html              結案報告
   3077 _build_project_execution_report_html  **專案執行報告**  <= 我漏掉的那一支
   3270 _build_completion_html                完工單
```

🔑 而 `helpers/company_identity.py:107` 的 docstring **逐字寫著「8 支 builder」** ——
> **那個數字一直都在，而我引用過那段 docstring、還是寫了一個沒數過的數字。**

📌 ⚠️ 檔案是 `backend/pdf_gen.py`，**不是** `backend/helpers/pdf_gen.py`。

### ① 一支 helper

```python
# helpers/company_identity.py
#: 會被快照覆蓋的欄位。**銀行四欄刻意不在裡面**（QL10：帳號要回答「現在」）。
_SNAPSHOT_FIELDS = ("company_name", "company_name_en", "tax_id", "phone", "email")


def identity_for(payload) -> dict:
    """一份單據要印的公司身分。

    即時值當底，**五個抬頭欄位被快照逐欄覆蓋**。
    🔴 銀行四欄**永遠是即時值** —— QL10 沒有被翻掉，它管的是別的欄位。
    """
    loc_id, snap = _resolve(payload)          # ⚠️ **一次查詢**拿到兩樣東西
    out = dict(location_identity(loc_id))
    for f in _SNAPSHOT_FIELDS:
        v = str(snap.get(f) or "").strip()
        if v:
            out[f] = v                        # ⚠️ **逐欄**覆蓋
    return out
```

⚠️ **逐欄不是整組** —— 與 `QL22`（退階要逐欄）同一條規則。
☠️ 整組覆蓋的話：快照裡 `phone` 是空的 ⇒ 印出來的電話也是空的，
   而即時值那邊明明有。

### ② 快照從哪裡來 —— **兩條路，要分別寫清楚**

```
甲 報價單自己      payload 裡就有 => `payload["locationIdentity"]`，**不查 DB**
乙 下游 7 支       payload 只有 quoteNo => 查 quotations
                   🔑 `_location_of()` **已經在查了**（company_identity.py:124）
                   ⇒ 把那一句 `SELECT location_id` 改成
                     `SELECT location_id, data_json`
                   ⚠️ **不要新增第二次查詢**
```

🔴 兩條路都要寫，否則會出現**反面的不一致**：
> **下游凍結了、而報價單自己沒凍結。**

```python
def _resolve(payload):
    """(據點 id, 快照 dict)。**一次查詢**，兩條路分別處理。"""
    payload = payload or {}
    direct = str(payload.get("locationId") or "").strip()
    if direct:
        # 甲：報價單表單直送、測試直塞 => 快照就在同一個 payload 裡
        return direct, (payload.get("locationIdentity") or {})
    quote_no = str(payload.get("quoteNo") or payload.get("quote_no") or "").strip()
    if not quote_no:
        return "", (payload.get("locationIdentity") or {})
    try:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT location_id, data_json FROM quotations WHERE quote_no=?",
                (quote_no,)).fetchone()
        finally:
            conn.close()
    except Exception:       # noqa: BLE001 —— 查不到就退回主要據點＋無快照
        return "", {}
    if not row:
        return "", {}
    try:
        d = json.loads(row["data_json"] or "{}")
    except Exception:       # noqa: BLE001
        d = {}
    return (str(row["location_id"] or "").strip(),
            d.get("locationIdentity") or {})
```

⚠️ **甲那條路的 payload 沒有 `locationIdentity` 時要退回即時值**，不是報錯 ——
既有測試就是直接塞 `locationId` 而不塞快照的（`company_identity.py:100` 的 docstring）。

### ③ 守門：請款單的銀行四欄**不可以來自快照**

```
⚙️ 正對照（**釘行為不是釘結構**）
   拿一筆「據點**改過銀行帳號**」的資料 => 斷言請款單印出來的是**新帳號**
   ❌ 不可以只斷言「快照裡沒有銀行欄位」—— 那是釘資料結構
      ☠️ 有人日後把銀行欄位加進 _SNAPSHOT_FIELDS，結構那題會紅，
         **而如果他同時改了那題的清單，行為那題才是唯一擋得住的**
```

### ④ 退路：**沒有快照就整份走即時值**

```
26 張舊單在補快照之前都走它
⚠️ 而「整份」是指五個抬頭欄位都落空 => out 就是 location_identity() 的原樣
   🔑 這與 §5 ③ 是同一條，不是新規則
```

---

## §4 寫入時機 —— 「按送出那一刻」**在程式裡是三個入口**

### ⚠️ 先釐清一個詞：這個 repo 裡「送出」有兩個意思

```
使用者按的那顆鈕      => status 變 **待審核**
`已送出` 這個狀態     => **簽核通過之後**才到（quotations.py:4383）
```
🔑 而 A 的括號「**草稿階段仍跟著設定走，改得動**」決定了答案：
> **凍結點＝離開「草稿」那一刻＝ status 變「待審核」。**
📌 **不是**變「已送出」那一刻 —— 那時已經簽完，中間簽核人看到的抬頭會是即時值。

### 三個入口（**每一個都要拍**，漏一個就是一張會變的單）

```
① routers/quotations.py:1317   建立即送審（POST，body.status == "待審核"）
                               ⚠️ 沒有草稿步驟，直接 INSERT 成待審核
② routers/quotations.py:1426   PUT 送審（new_status == "待審核"）
                               ⚠️ 含 **解鎖編輯強制重簽**（:1415 is_unlock_edit）
③ routers/quotations.py:1596   PATCH /status（_STATUS_PATCH_WHITELIST 含「待審核」）
                               ⚠️ superadmin 手動改狀態，走的是**另一條 UPDATE**
```

☠️ ③ 最容易漏：它不叫 submit、不經過 `save_quotation_json()`，
**是一句獨立的 `UPDATE quotations SET status=?`**。
🔑 〈證據的適用範圍〉：**看到一個 `submit` 端點就認定它是唯一入口** —— 那正是這裡的陷阱。

### 兩條**回草稿**的路 ⇒ 再送審時**重拍**

```
routers/quotations.py:1616  recall_quotation   申請人收回
routers/quotations.py:4402  reject_quotation   簽核退回（⚠️ **它會換單號**）
```
⇒ 規則**兩半**（本版修訂，見 §5「草稿要跟著設定走」那一段）：

```
離開草稿（3 個入口）  => **覆蓋**快照（不是「只寫一次」）
回到草稿（2 條路）    => **清掉**快照
```

🔴 ⚠️ 上一版寫「不需要在回草稿時清快照」，**那是錯的** —— 這一列留著。
```
當時的推理：每次離開草稿都覆蓋 => 再送審時自然是新值
☠️ 而它漏掉「**收回成草稿之後、還沒再送審**」那一段時間：
   快照還在 => 印草稿時印的是舊抬頭
   而 A 裁的是「**草稿階段仍跟著設定走，改得動**」
🔑 漏掉的不是一條規則，是一個**狀態**。
```

---

## §5 讀取順序

```
8 支 builder 一律改成   _ident = identity_for(payload)      （§3b ①）
① 有快照的欄位            => 用快照（**逐欄**）
② 沒快照的欄位            => 即時值
③ 完全沒快照（26 張舊單） => 整份即時值  ← **這條退路要留著**
```

### 🔴 「草稿要跟著設定走」改成**在寫入端處理**（本版修訂）

上一版寫成讀取時檢查 `status != "草稿"`。**改掉，理由是成本**：

```
甲（上一版）讀取時看 status
   => 8 支 builder 的 payload 都要帶得到報價單的 status
      而下游 7 支的 payload 是**它們自己的單據**，status 是它們自己的
   ⇒ 要在 _resolve() 的查詢再多取 quotations.status，並想清楚
     「出貨單已出、而報價單被收回成草稿」時算誰的
   ☠️ 那是一個**不需要存在的狀態組合**

乙（本版）**回草稿時清掉快照**
   => 讀取端只問「有沒有」，8 支一致
   落點只有兩處：recall_quotation:1616 ／ reject_quotation:4402
```

**乙的副作用**（分開寫，不是優點）：
```
⚠️ 日後若新增第三條回草稿的路，**它不會自己清快照**
   => 症狀是「一張草稿印出舊抬頭」，而**那與正常運作長得很像**
⇒ 守門要釘：**任何把 quotations.status 寫成 '草稿' 的地方，
   都要一併清掉 data_json["locationIdentity"]**
   ⚙️ 正對照＝那兩處；誘餌＝自己留一個合成的第三處
```

🔴 **不要動 `location_identity()` 本身**（`QL5`／`QL8` 裁過落空順序）。
> 快照是「**在送出那一刻呼叫它一次、把結果存下來**」，**不是改它**。

⚠️ ③ 要不要像薪資單一樣**在 PDF 上標明**？
```
薪資單（QL17）標了，理由是「員工可能拿去報稅或貸款」
報價單：補快照之後這條路只剩「送審前就存在、而設定當時是空的」那種單
⇒ 建議**不標**，而把理由寫在碼裡
📌 差別在 §6 —— 薪資單沒有補快照的動作，報價單有
```

---

## §6 一次補快照 —— **冪等，而判準是「鍵在不在」**

```
對象  status != '草稿' 且 data_json 沒有 "locationIdentity" 鍵的報價單
動作  用它現在的 location_id 呼叫 location_identity() 一次，寫進去
```

### 🔴 判準用「**鍵在不在**」不是「**值是不是空的**」

```python
if "locationIdentity" not in d:      # ✅
if not d.get("locationIdentity"):    # ❌ 快照存在而內容全空時會被再寫一次
```
🔑 〈null 不等於 0〉：**「沒有快照」與「快照是空的」是兩件事。**
☠️ 用真假值的話，這支腳本**每跑一次就把空快照換成今天的值** ——
而它看起來完全正常。

### ⚠️ 時機

```
使用者**填完設定之後**才跑（A 裁）
🔑 那個時機是對的：**現在那些欄位是空的 => 現在補，補進去的是空的**
   等他填完再補，就不必決定「舊單用新值還是舊值」
```
📌 ⇒ 這支腳本**不可以在 migration 裡自動跑**（migration 會在部署當下跑，
而使用者那時還沒填）。它是一個**手動觸發**的維運動作。

---

## §7 驗收（`AC1`）

```
① 後端  三個入口都拍；讀取三段順序；補快照腳本冪等
② 前端  無異動（快照對前端透明）
③ 頁面  ⓐ 建一張草稿 -> 改據點名稱 -> 重印 => **抬頭跟著變**（草稿）
        ⓑ 送審 -> 改據點名稱 -> 重印     => **抬頭不變**（已凍結）
        ⓒ 收回成草稿 -> 再送審 -> 改名 -> 重印 => **抬頭是第二次送審時的值**
```

### 🔴🔴 給 C：**這一件的迴歸保護是零**

```
既有 21 題**沒有一題**會因為做錯而紅（§8 已查）
=> 那不是「安全」，那是「**做錯了沒有人會說**」
⇒ 題要從頭寫，而且**寫完要先證明它會紅**
```

### 🔴 驗收要分得出「**有快照**」與「**快照是空的**」

```
☠️ 兩者在 PDF 上長得一樣（都印出即時值或空白）
⇒ 題目要**直接讀 data_json**，不要只看 PDF：
   assert "locationIdentity" in d        <= 有沒有拍
   assert d["locationIdentity"]["company_name"] == 送審當下的值   <= 拍對沒有
⚠️ 而斷言的值要**與即時值不同**（送審後先改一次設定再驗），
   否則「讀快照」與「讀即時值」兩種實作都會綠
   🔑 〈假綠燈：斷言驗到自己設的值〉
```

---

## §8 守門

```
✅ 釘：離開草稿的**每一條路**都留下快照
   ⚙️ 正對照 三個入口各一題
   ⚠️ **不要只測 PUT 那一支** —— ③ 走的是獨立 UPDATE，最容易被漏
✅ 釘：**回到草稿的每一條路都清掉快照**（§4 修訂）
   ⚙️ 正對照 recall:1616 ／ reject:4402 各一題
   🎣 誘餌   自己留一個合成的第三條路，確認守門抓得到「新增的那一條」
   ☠️ 症狀是「一張草稿印出舊抬頭」，**而那與正常運作長得很像**
✅ 釘：請款單的**銀行四欄仍然是即時值**（QL10 沒有被翻掉）
   ⚙️ 正對照 **釘行為**：據點改過銀行帳號 => 斷言印出來的是**新帳號**
   ❌ 不可以只斷言「快照裡沒有銀行欄位」—— 那是釘資料結構
      ☠️ 有人日後把銀行欄位加進 `_SNAPSHOT_FIELDS`，結構那題會紅，
         **而他同時改掉那題的清單就綠了** —— 行為那題才是唯一擋得住的
✅ 釘：快照裡**不出現銀行欄位**（結構，與上一條**兩題都要**）
   🔑 兩題分辨的是不同的失效：結構題擋「存進去」，行為題擋「讀出來」
✅ 釘：**這 8 支具名的 builder 全部走 `identity_for()`**
```

### 🔴 釘**名單**，不要釘數字（A 2026-09-23）

```python
#: QL25 的射程。**逐字列名，不要用數量。**
_QL25_BUILDERS = (
    "_build_quote_html",
    "_build_shipping_html",
    "_build_contractor_voucher_html",
    "_build_invoice_voucher_html",
    "_build_payment_request_html",
    "_build_case_closing_html",
    "_build_project_execution_report_html",
    "_build_completion_html",
)
```

```
☠️ 釘「呼叫點 = 8」的失效模式：
   有人新增第九支 builder => 這題紅
   而**最省力的反應是把 8 改成 9**，沒有人去檢查那一支有沒有接上
   => 守門從「檢查」退化成「**記帳**」，而那一步不會留痕跡
```

⇒ 新增 builder 要**明著加進這份名單**，並在加的時候**說出它為什麼要／不要抬頭**。

### ⚠️ 而 `pdf_gen.py` 裡的 builder 是 **9 支**，不是 8 支

```
實掃（每一支 `_build_*_html` 各自看有沒有呼叫 location_identity）：
  ✅ _build_quote_html                     (96)    <= QL25
  ✅ **_build_payslip_html**               (565)   <= 🔴 **例外，見下**
  ✅ _build_shipping_html                  (1031)
  ✅ _build_contractor_voucher_html        (1391)
  ✅ _build_invoice_voucher_html           (1749)
  ✅ _build_payment_request_html           (2057)
  ✅ _build_case_closing_html              (2557)
  ✅ _build_project_execution_report_html  (3069)
  ✅ _build_completion_html                (3262)
=> **9 支全部**呼叫 location_identity
```

### 🔴 例外只有一支，而它的理由**不是「薪資單沒有抬頭」**

```
❌ 錯的理由：「_build_payslip_html 本來就不該有抬頭」
   => 照這個理由做，會**把薪資單的抬頭拿掉**
✅ 實際：薪資單**有抬頭，而且它已經有自己的快照**（QL16）
   pdf_gen.py:578-580   company = d.get('companyName')  ← 讀自己的
   pdf_gen.py:593       location_identity(**None**)      ← 只在沒快照時落空用

🔑 兩者的**呼叫形狀就不同**：
   QL25 的 8 支   location_identity(_location_of(x))   <= 要換成 identity_for(x)
   薪資單那 1 支  location_identity(**None**)           <= **不要動**
```

⇒ 守門的掃描判準用 **`location_identity(_location_of(`** 這個字串，
   `location_identity(None)` 自然不在射程內 —— **不必寫例外清單**。
📌 〈判準的寬窄都會騙人〉：**例外數得出來（1 支），就釘已知集合**；
   而這裡更好的是**判準本身就分得開**，連清單都不需要。

```
⚙️ 正對照   `location_identity(_location_of(` 的殘留 = **0**
⚙️ 反向控制 `_QL25_BUILDERS` 裡每一個名字，在 pdf_gen.py 裡都找得到
             且**它的函式體內有 `identity_for(`**
   ☠️ 光數呼叫點擋不到「某一支被改成不印抬頭」——
      而**逐名檢查函式體**擋得到
⚙️ 負對照   `_build_payslip_html` **不可以**出現 `identity_for(`
             🔑 它動了就是 QL16 被踩掉
```

---

## §8b 🔴 退回會換單號 —— 而**沒有任何東西跟著改**（A 2026-09-23 追問）

### 實查

```
routers/quotations.py:4465（reject_quotation 的**唯一一次寫入**）
   UPDATE quotations SET quote_no=?, status='草稿', data_json=?, updated_at=?
   WHERE quote_no=?
   => MQ-202609-001  ->  MQ-202609-001-R1（_next_revision_no:164）
   🔴 **原地改名，舊單號從此不存在於 quotations 表**

db.py 裡有 `quote_no` 欄位的表 = **18 張**
全 backend 的 `SET quote_no=` = **1 句**（就是上面那一句）
=> **沒有任何連動。**
```

### ⇒ 對 `QL25` 的直接後果

```
下游 7 支存的是**舊單號** => _location_of() 查不到 => 回 ""
=> 據點落到**主要據點**，且**沒有快照** => 整份走即時值
☠️ 一張原本印分公司抬頭的出貨單，在它的報價單被退回之後，
   重印會變成**總公司抬頭** —— 而沒有任何訊息說為什麼
```

🔑 而這是**既有缺陷，不是 `QL25` 造成的** ——
`QL25` 只是讓它**多壞一格**（原本只有據點會掉，現在快照也跟著掉）。

### ⚠️ 可達性：`case_stages` 在退回**之前**就存在

```
quotations.py:1302  建立報價單時就 _sync_json_stages_to_table(conn, qno, …)
=> 每一張有階段的報價單被退回時，case_stages 都還指著舊單號
```

### 🔴 而這一題**本規格不修**，理由與範圍

```
它跨 18 張表，而 QL25 的射程是「抬頭要不要凍結」
⇒ **另開編號**，並且要先回答一個沒有人裁過的問題：
   **退回改單號之後，舊單號的紙還在外面流通嗎？**
   ⓐ 在  => 舊單號必須還查得到（改名是錯的做法，應該是新增一列）
   ⓑ 不在 => 那 18 張表要連動改名
   🔑 **兩個答案的修法完全相反**，所以不能猜
```

⚠️ 我**沒有實際跑一次 reject 去看 `case_stages` 變成什麼** ——
上面說的是讀碼推出來的，而**要確認只能跑**。
⇒ 回報時標成「讀碼所得，未跑」。

---

## §9 我沒查什麼

```
① 26 張舊單的 location_id 全是 loc_1 —— 那是 A 給的數字，我**沒有自己數**
② 補快照腳本要放哪（backend/tools/？）沒查既有的維運腳本慣例
③ 其他五支 builder（出貨單／完工單／三種憑單／結案報告）
   它們也走 _location_of(quoteNo) 去查報價單的 location_id
   ⚠️ **本規格沒有動它們** —— 而「報價單凍結了、它的下游單據沒凍結」
      是一個我沒有問過使用者的狀態
   ⇒ 建議 A 問一次：**下游單據要不要跟著報價單的快照走**
④ 前端有沒有地方顯示「這張單用的是哪個據點」（QL15 說清單有）——
   凍結之後那個顯示要不要改讀快照，沒查
```
