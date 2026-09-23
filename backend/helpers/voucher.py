# -*- coding: utf-8 -*-
"""傳票的**純邏輯**：狀態機、借貸平衡、單號升版。

規格來源：`docs/windows/SPEC-VOUCHER.md`（施工圖）。
第一行逐字：`🔴 **這一份是施工圖：單一版本、無修訂層。照這一份做。**`
⚠️ **不要照 `SPEC-VOUCHER-HISTORY.md` 實作** —— 那一份的 DDL 是被推翻的版本。
⚠️ 而**不要用行數認那個檔**（A 2026-09-23 更正）：行數是三個識別裡唯一會因為
   「同一個檔被編輯」而失效的，而失效時不會有人發現。

## 🔑 為什麼這些判斷在 helper 裡，不在 endpoint 裡

```
內嵌在 endpoint  =>  只有**走過那條路**才驗得到
抽成純函式      =>  可以直接餵一個狀態值問它
```
⇒ 這一支**不碰資料庫、不碰 request**，它只吃值回值。
📌 〈模組化：L2 功能模組彼此不可依賴〉：所以它也**不 import 任何 router**。
"""
import datetime as _dt
import json
import logging
import re

#: 施工圖 `§一`「狀態值」那一行，**逐字五個**。
#:
#: ⚠️ 「作廢」**不是狀態**，是動作 —— 它落在 `voided_at`／`voided_by`／
#:    `void_reason`／`supersedes_no` 四個欄位上（`supersedes_no` 由
#:    `routers/vouchers.py::void_voucher()` 的重開路徑寫入，`JV24 §5②`；
#:    在那之前這一欄從來沒被寫過，這句話有四分之一是空話）。
#: ☠️ 把它加成第六個狀態的後果很安靜：作廢之後 status 變成「作廢」⇒
#:    「已過帳的傳票」這個查詢**查不到它** ⇒ 而帳上那一筆還在。
#: 🔑 集合要**可以被數**：散在 `if/elif` 裡的狀態數不出來，
#:    而多出來的那一個在畫面上看起來很正常。
VOUCHER_STATUSES = ("草稿", "待審核", "簽核中", "已核准", "已過帳")

#: 施工圖 `§一`「可編輯 **只有 "草稿"**」。
#:
#: ☠️ 多一個的後果很具體：**簽核中的單被改掉，而簽過的人不知道。**
EDITABLE_STATUSES = ("草稿",)

#: 已過帳 ⇒ 帳已經動了。施工圖 `§一`：**不可退回，只能作廢重開。**
#:
#: 🔑 「退回」與「作廢重開」不是同一件事：
#: ```
#: 退回      同一張單，清除簽核 ＋ 單號升版 -Rn，改完再走一次
#: 作廢重開  **原單留著**（作廢），另開一張 => 帳上看得到那一次作廢
#: ```
#: 📌 那是會計上的要求，不是 UI 偏好：**已入帳的東西不可以被無痕修改。**
_TERMINAL_STATUSES = ("已過帳",)


def can_edit(status):
    """這個狀態可不可以改內容（含 `voucher_date`）。

    ⚠️ `voucher_date` **也走這一支** —— 施工圖 `:40` 逐字是
    「可編輯（**僅草稿**），預設建檔當天」。
    ☠️ 那行註解原本只寫「可編輯」⇒ 只看 DDL 的人會做成「隨時可改」，
       而一張已過帳的傳票被改掉日期 ⇒ **它換了一個會計期間，而帳上那一筆沒動。**
    """
    return status in EDITABLE_STATUSES


def can_send_back(status):
    """可不可以「退回修改」（狀態回草稿 ＋ 清除簽核 ＋ 單號升版 -Rn）。

    ```
    草稿    ✗  它已經可以編輯了 —— 退回不但沒有意義，還會白白升一版
    待審核  ✅
    簽核中  ✅
    已核准  ✅  施工圖 `§一`：「**帳還沒動** => 仍可退回」
    已過帳  ✗  施工圖 `§一`：「帳已動 => **不可退回，只能作廢重開**」
    ```

    ## 🔑 這一組值是**兩個來源的聯集**（A 2026-09-23 裁定）

    ```
    既有慣例（quotations.py:4309 逐字）
        "... WHERE quote_no=? AND status IN ('待審核','簽核中')"
        => 待審核 ✅  簽核中 ✅  **已核准 ✗**
    施工圖 `§一`
        "已核准  簽核走完（製票／覆核／主管三格都要簽），**帳還沒動** => 仍可退回"
        => 已核准 ✅
    ```
    ⚠️ **而它不是「取比較寬的那一個」這種妥協** —— 兩邊都對，
       因為兩個模組的「已核准」**意義不同**：
    ```
    報價單的「已核准」＝ 終點        => 不准退回是合理的
    傳票的「已核准」  ≠ 終點        => 帳還沒動，退回是流程的正常動作
    ```
    🔑 ⇒ 寫下這兩行依據是**必要的**：少了它，下一個人翻到
       `quotations.py:4309` 會以為這裡在偏離既有慣例，而**正當地**把它改窄。

    📌 而我原本的理由（規格對中間兩個狀態沉默、我從代價不對稱推出「可以」）
       留著，因為結論雖然相同，**依據強度不同**：
    ```
    我的      「做成不行的話，一張在審的單必須先被核准才退得回去」<= 推理
    A 找到的  既有四個 router 就是這樣寫的                      <= 實查
    ```
    ⚠️ 〈推翻的證據不會自動支持替代方案〉的鏡像：**結論對，不表示當時的依據夠。**
    """
    if status in _TERMINAL_STATUSES:
        return False
    return status in ("待審核", "簽核中", "已核准")


#: `JV32`：全形數字與全形逗號／句點 ⇒ 半形（貼上的金額常常是全形）。
_FULLWIDTH = str.maketrans("０１２３４５６７８９，．－＋", "0123456789,.-+")
_AMOUNT_RE = re.compile(r"^(-?)(\d+)(?:\.(\d+))?$")
_DECIMAL_MSG = "金額以新台幣元為單位，不可有小數"


def parse_amount(raw):
    """`JV32`：一格金額 ⇒ `(int, None)` 或 `(None, 錯誤訊息)`。

    ```
    接受  1000／"1,000"／"１，０００"／"  1000 "／"1000.00"（小數部分全是 0）／空 ⇒ 0
    擋下  "12.5"、12.5（不可有小數）／負數／看不懂的字
    ```
    ☠️ 取代原本的 `int(x or 0)`：它對 `"1,000"` 丟 ValueError（500），
       對 `12.5` **靜默截斷成 12**——存進去的數字與使用者打的不同，而沒有人被告知。
    ⚠️ `bool` 是 `int` 的子類別 ⇒ 要先擋掉（`True` 不是 1 元）。
    """
    if raw is None or raw == "":
        return 0, None
    if isinstance(raw, bool):
        return None, "金額格式看不懂（%r）" % raw
    if isinstance(raw, int):
        return (raw, None) if raw >= 0 else (None, "金額不可以是負數")
    if isinstance(raw, float):
        if raw != raw or raw in (float("inf"), float("-inf")):
            return None, "金額格式看不懂（%r）" % raw
        if raw != int(raw):
            return None, _DECIMAL_MSG
        return (int(raw), None) if raw >= 0 else (None, "金額不可以是負數")
    text = str(raw).translate(_FULLWIDTH).strip().replace(",", "").replace(" ", "")
    if text == "":
        return 0, None
    m = _AMOUNT_RE.match(text)
    if not m:
        return None, "金額格式看不懂（「%s」）" % str(raw).strip()
    if m.group(3) and m.group(3).strip("0"):
        return None, _DECIMAL_MSG
    if m.group(1):
        return None, "金額不可以是負數"
    return int(m.group(2)), None


def normalize_amount_lines(lines):
    """`JV32`：整組分錄的借貸金額正規化成 int；有問題的**全部列出**（指出第幾行）。

    回 `(normalized, problems)`：`problems` 非空時呼叫端整筆拒絕，**一行都不寫入**。
    📌 同一行借貸都填 ⇒ 擋下：一行分錄只能是借方或貸方其中之一。
    """
    out, problems = [], []
    for i, ln in enumerate(lines or (), start=1):
        ln = dict(ln or {})
        errs = []
        for key, label in (("debit", "借方"), ("credit", "貸方")):
            v, err = parse_amount(ln.get(key))
            if err:
                errs.append("%s%s" % (label, err))
            ln[key] = v if v is not None else 0
        if not errs and ln["debit"] and ln["credit"]:
            errs.append("借方與貸方只能填其中一邊")
        if errs:
            problems.append("第 %d 行：%s" % (i, "；".join(errs)))
        out.append(ln)
    return out, problems


#: `JV29`：傳票名稱（商業會計法 §17；準則 §6 記帳憑證要載明傳票名稱）。
#: ⚠️ 查不到的值（理論上不會有）⇒ 呼叫端退回舊的「傳　票」，不要猜一個名稱。
CATEGORY_TITLES = {"收": "收入傳票", "支": "支出傳票", "轉": "轉帳傳票"}

#: 現金及約當現金（官方《商業會計項目表》三級）。
_CASH_ROOT = "111"


def cash_account_codes(conn):
    """`JV29`：現金類科目＝沿 `parent_code` 往上走得到 `111` 的那些（含 111 本身）。

    ☠️ **不用代號前綴**（`db.py` `_m093` 的警告：二級是範圍代號，前綴不可信），
       而且使用者自訂科目掛在 111 底下時用前綴判會漏掉。
    ⚠️ 迴圈防護：資料若有環（理論上不會），走 20 層就停，不當成現金類。
    """
    parent = {r["code"]: r["parent_code"] for r in conn.execute(
        "SELECT code, parent_code FROM account_items")}
    out = set()
    for code in parent:
        c, n = code, 0
        while c and n < 20:
            if c == _CASH_ROOT:
                out.add(code)
                break
            c, n = parent.get(c), n + 1
    return out


def classify_category(conn, lines):
    """`JV29`：依分錄判斷傳票類別。

    ```
    現金類科目的淨額（借 − 貸）> 0  ⇒ 收（收入傳票）
                                < 0  ⇒ 支（支出傳票）
                                = 0  ⇒ 轉（轉帳傳票；含沒有現金類、與銀行轉存）
    ```
    📌 `lines` 的金額要先經 `normalize_amount_lines()`（int）。
    """
    cash = cash_account_codes(conn)
    net = sum(int(ln.get("debit") or 0) - int(ln.get("credit") or 0)
              for ln in (lines or ()) if (ln.get("account_code") or "").strip() in cash)
    return "收" if net > 0 else ("支" if net < 0 else "轉")


def check_balance(lines, status="草稿"):
    """借貸平衡。回 `(ok, diff)`，`diff` 是**借貸差的絕對值**。

    ```
    草稿  允許不平衡  <= 使用者正在打，打到一半本來就不平
    其餘  必須平衡    <= 施工圖 `§六①`：`SUM(debit) == SUM(credit)` 且 **> 0**
    ```
    ☠️ 反過來寫（草稿就擋）的症狀是：**使用者打不完第一行就被擋住**，
    🔑 而它看起來像「很嚴謹」 —— 〈降級之後它還是會動〉的鏡像。

    ## ⚠️ `diff == 0` 不代表可以過帳

    ```
    借 0 ／ 貸 0  =>  diff 是 0，而 ok 是 False（施工圖要求「且 > 0」）
    ```
    ⇒ **不可以拿 `diff` 當判準** —— 要看 `ok`。
    ☠️ 寫成 `if diff: 擋` 的話，一張**全部是 0 的空傳票**會過帳，
       而它在帳上是一筆金額為 0 的分錄：**不報錯，也對不出來。**
    ⇒ 要給使用者看的字串走 `describe_balance()`，它分得出這兩種。
    """
    debit = sum(int(l.get("debit") or 0) for l in lines)
    credit = sum(int(l.get("credit") or 0) for l in lines)
    diff = abs(debit - credit)
    if can_edit(status):
        return True, diff
    return (diff == 0 and debit > 0), diff


def describe_balance(lines, status="草稿"):
    """不能過帳的原因（**說得出差額**）；可以過帳回 `None`。

    ☠️ 只說「借貸不平衡」的話，使用者要自己把每一行加一次 ——
    🔑 **而那個數字是檢查它的人手上就有的。**
    """
    ok, diff = check_balance(lines, status)
    if ok:
        return None
    debit = sum(int(l.get("debit") or 0) for l in lines)
    credit = sum(int(l.get("credit") or 0) for l in lines)
    if diff == 0:
        # 🔑 這一支就是上面那段註解講的第二種：平衡，而金額是 0。
        return "傳票金額為 0，無法過帳：借方與貸方都是 0，請先填入分錄金額。"
    short = "貸方" if debit > credit else "借方"
    return ("借貸不平衡，無法過帳：借方 %s／貸方 %s，%s少 %s。"
            % (f"{debit:,}", f"{credit:,}", short, f"{diff:,}"))


#: 單號尾碼。`base` 用**非貪婪**，所以它抓的是**最後一段** `-Rn`。
#:
#: 🔴 **刻意不寫死任何前綴** —— `quotations.py:164` 把
#:    `^(MQ-\d{6}-\d{3})(?:-R(\d+))?$` 寫死，對不上就無腦 `+ '-R1'`：
#: ```
#: 20260330-006 -> -R1 -> **-R1-R1** -> **-R1-R1-R1**   （實跑，不是讀碼推的）
#: ```
#: ☠️ 而 `UNIQUE INDEX` **擋不住**：`-R1-R1` 與 `-R1` 是不同字串
#:    => **不報錯，只是產生一個看起來像版本號、而不是版本號的東西。**
_REV_SUFFIX = re.compile(r"^(?P<base>.+?)-R(?P<n>\d+)$")


def next_revision_no(voucher_no):
    """`X` → `X-R1`；`X-R1` → `X-R2`。**尾碼永遠只有一段。**

    ⚠️ 這一支**不可以** `from routers.quotations import _next_revision_no`。
    📌 理由不是「不要重用程式碼」，是相依方向：
       傳票依賴報價單的內部函式 ⇒ **改報價單的單號格式會靜默改掉傳票的。**
    🔑 而 `quotations` 那一支在**它自己的地盤上沒有壞**（報價單一律 `MQ-` 格式）
       —— 問題是**借用它**，不是它本身。
    """
    m = _REV_SUFFIX.match(voucher_no or "")
    if not m:
        return "%s-R1" % voucher_no
    return "%s-R%d" % (m.group("base"), int(m.group("n")) + 1)


#: 單號的主體：`YYYYMMDD-NNN`（日期 ＋ 三位流水）。
#:
#: 📌 格式**不是推的** —— 使用者提供的實例逐字是 `20260330-006`
#:    （`docs/reference/傳票-實例-20260330-006.pdf`，分析在 `STATE.md §103b`）。
_DAILY_NO_RE = re.compile(r"^(\d{8})-(\d{3})(?:-R\d+)?$")


def next_voucher_no(conn, voucher_date):
    """那一天的下一個單號。`2026-03-30` → `20260330-007`。

    ## 🔴 取**最大值 +1**，不是「數幾筆 +1」

    ```
    數幾筆  003 被作廢 => 剩 2 筆 => 下一個算成 003  => **撞號**
    取最大  003 還在表上（作廢單留著）=> 下一個是 004  ✅
    ```
    ☠️ 而撞號的症狀是 `UNIQUE INDEX` 丟例外 —— 那還算好的；
       真正糟的是**有人先把作廢單刪掉**，那時就會安靜地重用一個用過的號。

    ## ⚠️ 掃 `vouchers_all`，不是 VIEW

    VIEW 濾掉作廢單 ⇒ 用它取最大值就等於上面那個「數幾筆」的錯法。

    ## ⚠️ 併發下仍可能撞號，而**那是 `UNIQUE INDEX` 的事**

    兩個人同一秒建單，兩邊都讀到同一個最大值 ⇒ 第二個寫入會被唯一索引擋下。
    🔑 ⇒ 呼叫端要**把那個例外翻成一句人看得懂的話並請他重試**，
       而不是在這裡加鎖 —— 加鎖會讓一個每天幾十筆的操作付出整表鎖的代價。
    """
    day = (voucher_date or "").replace("-", "")[:8]
    if len(day) != 8 or not day.isdigit():
        raise ValueError("傳票日期格式不正確：%r" % (voucher_date,))
    biggest = 0
    for row in conn.execute(
            "SELECT voucher_no FROM vouchers_all WHERE voucher_no LIKE ?",
            (day + "-%",)):
        m = _DAILY_NO_RE.match(row[0] if not hasattr(row, "keys") else row["voucher_no"])
        if m and m.group(1) == day:
            biggest = max(biggest, int(m.group(2)))
    return "%s-%03d" % (day, biggest + 1)


def revision_of(voucher_no):
    """這張單是第幾版（沒有 `-Rn` 尾碼回 `0`）。

    ⚠️ 回 `0` 不是「查不到」，是「**這是第一版**」——〈null 不等於 0〉的反面：
       這裡兩者確實是同一件事，而值得寫出來，免得下一個人改成 `None`。
    """
    m = _REV_SUFFIX.match(voucher_no or "")
    return int(m.group("n")) if m else 0


def base_no(voucher_no):
    """去掉 `-Rn` 尾碼，回那張單的基底單號（歷次版本的共同身分）。"""
    m = _REV_SUFFIX.match(voucher_no or "")
    return m.group("base") if m else voucher_no


# ══════════════════════════════════════════════════════════════════════
# 過帳與讀取 —— **科目名稱的凍結點在「過帳那一刻」**
# ══════════════════════════════════════════════════════════════════════
#
# 施工圖 `§2.2` 逐字：`account_name_snapshot` **過帳時凍結**（版面要印）。
#
# ## 🔑 凍太早與凍太晚是同一個軸的兩端，而**只有凍太晚會被報修**
# ```
# 凍太晚（列印時照樣去查現值）
#   => 去年的傳票今天印出來不一樣
#   ☠️ 而大部分科目從來沒改過名字 => **只有改過名字的那幾筆是錯的**
#      => 那幾筆看起來也很正常 => 不會有人報修
# 凍太早（建立分錄時就凍）
#   => 使用者改了科目名，回到自己還沒送審的草稿卻沒變
#   => 他會以為改名沒生效，**再改一次**
# ```

#: 已過帳 ⇒ 讀凍結值；其餘一律讀現值。
_FROZEN_STATUS = "已過帳"


def _current_account_names(conn, codes):
    """`{代號: 現在的名稱}`。

    ## ⚠️ 刻意**不用 JOIN**，而理由不是為了閃避守門

    ```
    JOIN 取名字  => 「列印時去查現值」這件事就藏在 SQL 裡，
                   而它與「讀凍結值」長得幾乎一樣
    分開查       => 呼叫點看得出來「我現在要的是**現值**」
    ```
    🔑 ⇒ 過帳那條路**完全不碰科目表**，那是可以一眼看出來的，
       不必去讀 SQL 才知道。

    ## ☠️ 這段註解本身踩過一次「註解重新引入被 grep 的字面值」

    C 有一道結構絆線在掃「以連接方式取科目名稱」那個形狀，而它**掃原始碼的每一行、
    不剝註解** ⇒ 我原本在這裡**逐字寫出**它要找的那兩個詞去說明我為什麼不用它
    ⇒ **那道絆線就亮在這段解釋上**。
    🔑 而它的方向是**假陽性**：把一段寫對的碼報成缺陷。
    📌 ⇒ 寫「為什麼避開某個寫法」時，**不要把那個寫法的字面值寫進去**。
       這是同一個坑的第七次，所以修的是作法：改用描述，不用那兩個詞。
    """
    out = {}
    for code in set(codes):
        row = conn.execute(
            "SELECT name FROM account_items WHERE code = ?", (code,)).fetchone()
        out[code] = (row[0] if row else "") if not hasattr(row, "keys") \
            else row["name"]
    return out


def get_voucher(conn, voucher_id):
    """讀一張傳票（含分錄）。查不到回 `None`。

    ⚠️ 查 `vouchers_all`（**實表**）而不是 VIEW：**這一支要讀得到作廢單** ——
       稽核要看得見「這一張作廢過」，而 VIEW 會把它濾掉。

    ## 🔴 `account_name` 的來源由 `status` 決定
    ```
    已過帳  => account_name_snapshot（**過帳當時**的名字）
    其餘    => account_items 的現值
    ```
    ☠️ 而已過帳時**不做「snapshot 是空的就退回查現值」那種退路**：
       那會讓一個真正的缺陷（過帳沒寫 snapshot）**變成看起來正常**，
       🔑 〈降級之後它還是會動〉—— 成功而降低了正確性的那一種，沒有人會報修。
    """
    row = conn.execute(
        "SELECT * FROM vouchers_all WHERE id = ?", (voucher_id,)).fetchone()
    if row is None:
        return None
    voucher = dict(row)

    lines = [dict(r) for r in conn.execute(
        "SELECT * FROM voucher_lines WHERE voucher_id = ? ORDER BY line_no",
        (voucher_id,))]

    if voucher.get("status") == _FROZEN_STATUS:
        for ln in lines:
            ln["account_name"] = ln.get("account_name_snapshot") or ""
    else:
        names = _current_account_names(conn, [l["account_code"] for l in lines])
        for ln in lines:
            ln["account_name"] = names.get(ln["account_code"], "")

    voucher["lines"] = lines
    voucher["signatures"] = resolve_display_names(conn, signatures_of(voucher))
    # `JV34③`：表頭列「附件 N 張」（準則 §6 的原始憑證張數）——**未刪除的**附件數。
    #    算在這裡而不是 `preview_html()`／`export_voucher_pdf()` 各算一次：
    #    兩條輸出路徑共用這一個數字，不會一邊有一邊沒有。
    voucher["attachment_count"] = conn.execute(
        "SELECT COUNT(*) FROM voucher_attachments WHERE voucher_id = ? AND deleted_at = ''",
        (voucher_id,)).fetchone()[0]
    return voucher


def resolve_display_names(conn, slots):
    """`JV13`：`signatures_of()` 的 `by` 存的是 **username**（穩定識別、
    `_user_name()` 寫入的就是它），而印在紙上／畫面上的要是**顯示名稱**。

    ## 🔴 修的是輸出這一層，不改存的值

    ```
    signatures_of()          仍然回 username —— 那是它的職責（讀簽核紀錄）
    get_voucher() 的回傳值    包一層，把 by 換成顯示名稱
    ```
    ⚠️ 兩者混在一起會兩頭不討好：`signatures_of()` 若直接回顯示名稱，
       它就不再是「簽核紀錄的原始值」，而變成一個**跟查詢時機綁定**的東西
       （使用者改名之後，舊的 `approval_json` 裡沒有任何欄位需要跟著動，
       這裡永遠查的是**現在**的顯示名稱）。

    ⚠️ **查不到顯示名稱時落回 username，不要印空白**（`STATE.md §257`
       JV13 逐字）—— 空白比印一個帳號更難查（帳號至少查得到是誰）。

    📌 這裡才用得到 `conn`，`signatures_of()` 本身仍然不碰資料庫
       （模組開頭的原則：純邏輯，可以直接餵值問它，不必先造一個 DB）。

    🔴 `BN7` 沿用：這支對 `slots` 的形狀（`{格名: {by, at}}`）沒有任何
    傳票專屬的假設，`helpers/bonus_pdf.py` 直接 import 這一支處理
    `bonus_signatures_of()` 的輸出，不重寫一份——原本的底線 `_` 已拿掉
    （原本只有一個呼叫端，現在是共用工具，保留底線會誤導成「模組內部
    專用，不可外部 import」）。
    """
    usernames = {(v or {}).get("by") for v in slots.values()} - {"", None}
    if not usernames:
        return slots
    placeholders = ",".join("?" for _ in usernames)
    rows = conn.execute(
        "SELECT username, display_name FROM users WHERE username IN (%s)"
        % placeholders, tuple(usernames)).fetchall()
    names = {r["username"]: (r["display_name"] or r["username"]) for r in rows}
    out = {}
    for label, cell in slots.items():
        cell = dict(cell or {})
        by = cell.get("by") or ""
        if by:
            cell["by"] = names.get(by, by)
        out[label] = cell
    return out


#: 版面上的三個簽名格（使用者的實例逐字：製票／覆核／主管）。
#:
#: 🔴 **製票不是一個簽核動作** —— 它就是建立者。
#:    ⇒ 它讀 `created_by`／`created_at`，沒有自己的欄位。
#: ⚠️ 而三格**各有自己的時間戳**，不共用 `updated_at`：
#: ☠️ 共用的話，任何一次編輯都會把「覆核是什麼時候簽的」推掉 ——
#:    而那一列**看起來完全正常**：有人、有時間，只是時間是錯的。
#: ⚠️ 鍵用**中文格名**，與版面上印的三個字一致（使用者的實例逐字）。
#:    英文鍵會讓畫面與 API 各有一套名字，而那一層翻譯沒有人維護。
logger = logging.getLogger(__name__)

_SIGNATURE_SLOTS = (
    ("製票", "created_by", "created_at"),
    ("覆核", "checked_by", "checked_at"),
    ("主管", "manager_by", "manager_at"),
)


#: 前兩層的名字沿用實例 PDF 上的字；第三層起用「第 N 層」。
#: 🔑 這樣**沒有設定過簽核流程的公司，版面一個字都不會變**。
_TIER_LABELS = ("覆核", "主管")


class VoucherChainUnreadable(Exception):
    """簽核鏈存在而**讀不出來**。與「沒有簽核鏈」是兩件事。

    ☠️ 這兩者折疊在一起的後果不是版面錯，是**閘門靜默放行**：
    ```
    讀取失敗 -> 回 [] -> 讀起來就是「這張單不需要簽核」
             -> 閘門判「沒有需要簽核的關卡」-> **判定已完成** -> 放行
    ```
    🔑 一個未簽核的傳票因此匯得出去，**而畫面上完全正常**。
    ⇒ 所以這裡**丟**，不回 `[]`、也不回 `None`（回 None 只是把同一個問題
      往下移一層：呼叫端一個 `or []` 就又折回去了）。
    """


def parse_approval_json(voucher):
    """`approval_json` 的原始解析（整包 dict，含 `tiers`／`currentTier`）。

    **共用件**——`JV27`：`routers/vouchers.py` 原本自己重新 `json.loads`
    了一次（`_appr_of()`），兩套解析各自維護、行為各自漂移。這裡是唯一
    的解析入口，`_chain_tiers()` 疊在它上面；`routers/vouchers.py` 也
    改叫這支，不再自己 parse。

    ```
    沒有 approval_json   => **回 {}**（明確的「沒有設定簽核流程」）
    有而解析失敗          => **raise VoucherChainUnreadable**
    ```
    """
    raw = voucher.get("approval_json")
    if not raw:
        return {}
    try:
        return json.loads(raw) or {}
    except (TypeError, ValueError) as exc:
        # 📌 訊息裡寫出**哪一個動作**失敗，以及**fail-closed 這個選擇本身**
        #    （比照 `archive.py:288` 那個寫法 —— 它連選擇都寫進訊息）。
        logger.warning(
            "傳票 %s 的簽核鏈解析失敗（fail-closed：一律視為**未簽核完成**）：%s",
            voucher.get("id"), exc)
        raise VoucherChainUnreadable(
            "這張傳票的簽核資料讀不出來，無法判斷是否已完成簽核。") from exc


def _chain_tiers(voucher):
    """這張單的簽核鏈（`AS2` 的 `approval_json`），只取 `tiers` 那一段。

    ```
    沒有 approval_json   => **回 []**（明確的「沒有設定簽核流程」）
    有而解析失敗          => **raise VoucherChainUnreadable**（疊在 `parse_approval_json` 上）
    ```

    ## ☠️ 我上一版在這裡回 `[]`，而那個取捨**只對當時的呼叫端成立**

    當時只有 `signatures_of()`（版面）讀它，而版面壞掉不該讓整張單讀不出來
    ⇒ 「壞了就當沒有」是對的。
    🔴 **而 `JV11` 的匯出閘門要讀同一份資料，它的錯誤方向相反。**
    ⇒ 那不是守門變了、也不是對象變了，是**多了一個用途，而原本的取捨只對舊用途成立**。
    ⚠️ 判準：**為一份既有資料加一個新消費端時，去讀它的失敗行為是為誰設計的。**
    """
    return parse_approval_json(voucher).get("tiers") or []


def _with_bookkeeper(out, voucher):
    """`JV31`：最後補一格「記帳」（過帳的人）。還沒過帳 ⇒ 空字串（流程還沒走到）。"""
    out["記帳"] = {"by": voucher.get("posted_by") or "", "at": voucher.get("posted_at") or ""}
    return out


def signatures_of(voucher):
    """簽核格：`{格名: {by, at}}`，順序＝製票 → 各層（內建兩層是「覆核／主管」）→ **記帳**。

    🔴 `JV31`（商業會計法 §35：記帳憑證要有主辦及經辦會計人員簽章）：最後一格
       「記帳」＝過帳的人（`posted_by`／`posted_at`，`post_voucher()` 寫入）。
       **三條 return 路徑都要加**——只加在一條的話，那條以外的傳票紙上少一格，
       而它看起來就是一張正常的傳票。

    ⚠️ 還沒簽的那一格 `by`／`at` 是**空字串**（欄位的 DEFAULT），
       而呼叫端要分得出「還沒簽」與「簽了而沒有時間」——
       🔑 前者是流程還沒走到，後者是缺陷。
    📌 `§106c`：三格**從簽核紀錄取，不可以從 `status` 欄推** ——
       ☠️ 從 status 推的話，一張退回重送的單會顯示「覆核已簽」而其實被清掉了。
    """
    out = {"製票": {"by": voucher.get("created_by") or "",
                   "at": voucher.get("created_at") or ""}}

    # 🔴 `AS2`：**有簽核鏈就照鏈畫，一層一格。**
    #
    # 使用者 2026-09-23 裁：「**超過兩層就把版面往下加列**」
    # ⇒ 三格是**目前的層數**，不是版面規則。
    # ☠️ 寫死三格的話，第三層那天**會靜默掉一格** —— 紙上少一個簽名，
    #    而它看起來就是一張正常的傳票。
    # ⚠️ 前兩層沿用「覆核／主管」這兩個名字：沒有設定簽核流程的公司
    #    （內建兩層）看到的版面**一個字都不會變**。
    # ⚠️ 讀不出來時**印在紙上**，不要安靜退回內建三格 ——
    #    同 `JV5` 的「把缺口輸出出來」：紙上要看得出「這一張的簽核狀態不明」。
    try:
        tiers = _chain_tiers(voucher)
    except VoucherChainUnreadable:
        out["簽核資料無法讀取"] = {"by": "", "at": ""}
        return _with_bookkeeper(out, voucher)
    if tiers:
        for i, tier in enumerate(tiers):
            label = _TIER_LABELS[i] if i < len(_TIER_LABELS) else "第 %d 層" % (i + 1)
            out[label] = {"by": (tier or {}).get("approvedBy") or "",
                          "at": (tier or {}).get("approvedAt") or ""}
        return _with_bookkeeper(out, voucher)

    for label, by_col, at_col in _SIGNATURE_SLOTS[1:]:
        out[label] = {
            "by": voucher.get(by_col) or "",
            "at": voucher.get(at_col) or "",
        }
    return _with_bookkeeper(out, voucher)


def approval_done(voucher):
    """匯出（不是預覽）能不能放行。回 `(ok, message)`，`ok` 為真時 `message` 是 `""`。

    ## 🔴 `JV11`：條件是「未簽核完成」，不是「狀態不等於已核准」

    `voucher_pdf.py:363` 已有裁定：**已作廢的傳票也要印得出來**——一份
    法定保存五年的憑證，作廢單正是稽核最需要看到的那一種。而使用者另外
    裁示**作廢優先於未簽核**：一張還沒簽核就被作廢的單，仍然放行，不管
    簽到第幾層。
    ☠️ 寫成「狀態不等於已核准就擋」的話，這支會**牴觸一條已經存在的裁定**
       ——那是 B 最省力的實作，而它會全綠，因為沒有任何一題會同時檢查
       「作廢」與「未簽核」兩個條件疊在一起。

    ## 🔴 判準是**逐一列舉**，不是「已核准以外都擋」——那句話本身就漏過一次

    這支第一版只認 `已核准`，漏了 `已過帳`（C 實跑抓到：`post_voucher()`
    的過帳前檢查②要求 `status == '已核准'` 才能過帳，所以**已過帳永遠是
    已核准的下游**——一張已過帳的傳票一定簽核完成過，不會再變，理由與
    「已作廢也要印得出來」同一族：**閘門的條件列舉不全，每一個漏掉的
    狀態都是一張印不出來的憑證**）。⇒ 判準改成**把整個狀態機列出來逐一
    決定**，不要再用「不等於某個值」這種會漏的寫法：

    ```
    voucher_lines.status（`SPEC-VOUCHER.md §一`）＋ voided_at 這條正交的軸
      草稿    ✗  還沒送審，沒有東西可簽
      待審核  ✗  簽核中，未完成
      簽核中  ✗  同上
      已核准  ✅ 簽核完成
      已過帳  ✅ 已核准的下游，帳已經動了
      （任何狀態）＋已作廢  ✅ 作廢優先，不管簽到第幾層
    ```
    🔑 判準是「**這個狀態的傳票，使用者需不需要印出來**」——除了草稿／
    待審核／簽核中（都還沒完成，紙上會有空簽名格）以外全部要放行。
    📌 **下一次加傳票狀態的人，照著這張表決定要不要加進放行分支**——
    這張表本身就是那個決定的落點，不要讓它又變回「只認一個值」。

    ## ⚠️ fail-closed：讀不出簽核鏈時**擋下來**，不是放行

    與 `signatures_of()` 對 `VoucherChainUnreadable` 的處理方向相反——那支
    是版面，讀不出來就在紙上印一格「簽核資料無法讀取」，版面本身不能垮。
    這裡是**匯出閘門**，讀不出來代表判斷不出「有沒有簽完」，寧可多擋一次
    也不要放行一張可能還沒簽完的傳票。
    📌 〈守門守的對象被搬走〉：同一份 `approval_json`，多了一個新消費端
       （匯出閘門）之後，原本那支的失敗行為（放行）只對舊用途（版面）成立。
    """
    if voucher.get("voided_at"):
        return True, ""
    if voucher.get("status") in ("已核准", "已過帳"):
        return True, ""
    try:
        tiers = _chain_tiers(voucher)
    except VoucherChainUnreadable:
        return False, "這張傳票的簽核資料讀不出來，無法判斷是否已完成簽核，暫不能匯出。"
    if tiers:
        try:
            appr = json.loads(voucher.get("approval_json") or "{}") or {}
        except (TypeError, ValueError):
            appr = {}
        idx = int(appr.get("currentTier") or 0)
        idx = max(0, min(idx, len(tiers) - 1))
        label = _TIER_LABELS[idx] if idx < len(_TIER_LABELS) else "第 %d 層" % (idx + 1)
        return False, ("這張傳票尚未簽核完成，還差「%s」（第 %d／%d 層）簽核，暫不能匯出。"
                       % (label, idx + 1, len(tiers)))
    # ⚠️ 沒有設定過流程：維持 §161 的內建兩格。
    if not (voucher.get("checked_by") or ""):
        return False, "這張傳票尚未簽核完成，還差覆核簽核，暫不能匯出。"
    return False, "這張傳票尚未簽核完成，還差主管簽核，暫不能匯出。"


def post_voucher(conn, voucher_id, user):
    """過帳。回 `(ok, err)` —— `err` 是**給使用者看的字串**，成功時 `None`。

    施工圖 `§六` 的過帳前檢查：
    ```
    ① SUM(debit) == SUM(credit) 且 > 0   => 不平衡**拒絕並說出差額**
    ② status == '已核准'
    ③ 寫入 account_name_snapshot（凍結）
    ```
    ⚠️ ④（法定副本／`ledger_confirmed`）**本輪不做** —— 沒有派工，
       而 `ledger_confirmed` 的預設值 0 已經讓它日後接得上。
    """
    row = conn.execute(
        "SELECT * FROM vouchers_all WHERE id = ?", (voucher_id,)).fetchone()
    if row is None:
        return False, "找不到這張傳票。"
    voucher = dict(row)

    if voucher.get("voided_at"):
        return False, "這張傳票已經作廢，不能過帳。"

    lines = [dict(r) for r in conn.execute(
        "SELECT * FROM voucher_lines WHERE voucher_id = ? ORDER BY line_no",
        (voucher_id,))]

    # 🔴 **先驗平衡，再驗狀態** —— 順序照施工圖 `§六` 的編號（① 平衡 ② 狀態）。
    #
    # ☠️ 反過來的話，一張**草稿而且不平衡**的傳票只會收到
    #    「只有已核准可以過帳」—— 那句話是對的，
    #    🔑 **而它把使用者真正要修的那件事藏起來了**：他送審之後才會發現不平衡，
    #       那時已經有人簽過名了。
    #
    # ⚠️ 而這裡**不能用那張單目前的 status 去評平衡** ——
    #    `check_balance()` 對「草稿」一律回 True（草稿允許不平衡，那是對的）。
    #    ☠️ 傳 `voucher["status"]` 進去的話，草稿永遠算「平衡」⇒ 這一關形同不存在。
    #    ⇒ 明著用**過帳的規則**去評：問的是「如果要過帳，這些分錄過得了嗎」。
    err = describe_balance(lines, status=_FROZEN_STATUS)
    if err:
        return False, err

    if voucher.get("status") != "已核准":
        # 🔑 說出**現在是什麼狀態**，不要只說「狀態不對」——
        #    否則使用者要自己回去翻那張單才知道卡在哪。
        return False, ("只有「已核准」的傳票可以過帳，這一張現在是「%s」。"
                       % voucher.get("status"))

    # ③ 凍結科目名稱。**先凍分錄再改狀態** ——
    # ☠️ 反過來的話，中途失敗會留下一張「已過帳而沒有凍結值」的傳票，
    #    而 `get_voucher` 對它會印出空白的科目名稱。
    names = _current_account_names(conn, [l["account_code"] for l in lines])
    for ln in lines:
        conn.execute(
            "UPDATE voucher_lines SET account_name_snapshot = ? WHERE id = ?",
            (names.get(ln["account_code"], ""), ln["id"]))

    now = _dt.datetime.now().isoformat()
    conn.execute(
        "UPDATE vouchers_all SET status = ?, posted_at = ?, posted_by = ?,"
        " updated_at = ? WHERE id = ?",
        (_FROZEN_STATUS, now, user or "", now, voucher_id))
    return True, None


#: 分錄上會被比對的欄位。**不含 `line_no`** —— 行號是位置不是內容，
#: 整行搬動時比對行號會產生一堆假的「改動」。
_LINE_FIELDS = ("account_code", "summary", "debit", "credit")


def _norm_line(ln):
    """把一行分錄正規化成比對用的形狀。

    ⚠️ 兩邊來源不同：**舊的**來自資料庫（`debit` 是 int、`summary` 不會是 None），
       **新的**來自 request body（可能是字串、可能缺鍵）。
    ☠️ 不正規化的話，`1000` 與 `"1000"` 會被判成一次改動 ⇒
       使用者什麼都沒改而編寫紀錄多一筆 —— 而那一筆讀起來完全合理。
    """
    ln = ln or {}
    return {
        "account_code": (ln.get("account_code") or "").strip(),
        "summary": (ln.get("summary") or "").strip(),
        "debit": int(ln.get("debit") or 0),
        "credit": int(ln.get("credit") or 0),
    }


def diff_lines(old, new):
    """逐行比對分錄，回 `append_edit_log()` 吃得下的 changes 清單。

    ## 🔴 為什麼是**逐行**而不是整包記一筆（`§103e`）

    ```
    整包  {"field": "lines", "from": "2 行", "to": "2 行"}
          => 同一張被退兩次，**看不出來第二次改了什麼**
    ```
    而 `§103e` 對退回升版的要求逐字是「同一張被退兩次看不出來是財務不可接受」
    ⇒ 同一條精神套在分錄上。

    ## 📌 每一筆長什麼樣

    ```
    改欄位  {"field": "lines[0].debit",  "from": 1000, "to": 7777}
    新增行  {"field": "lines[2]",        "from": None, "to": {…}}
    刪掉行  {"field": "lines[2]",        "from": {…},  "to": None}
    ```
    ⚠️ `from`／`to` 這兩個**鍵一定要在**（即使值是 `None`）——
       `append_edit_log()` 用 `"from" not in ch` 判斷，不是用值的真假。
       ☠️ 用真假值的話，一筆「原本是空白」的改動會被當成沒記錄改前值。

    ## ⚙️ 沒有改動就回空清單

    呼叫端要據此決定「**不寫**編寫紀錄」——
    ☠️ 一列 `changes_json='[]'` 看起來像有記錄，而它什麼都沒說。
    """
    a = [_norm_line(x) for x in (old or ())]
    b = [_norm_line(x) for x in (new or ())]
    out = []
    for i in range(max(len(a), len(b))):
        if i >= len(b):
            out.append({"field": "lines[%d]" % i, "from": a[i], "to": None})
            continue
        if i >= len(a):
            out.append({"field": "lines[%d]" % i, "from": None, "to": b[i]})
            continue
        for f in _LINE_FIELDS:
            if a[i][f] != b[i][f]:
                out.append({"field": "lines[%d].%s" % (i, f),
                            "from": a[i][f], "to": b[i][f]})
    return out
