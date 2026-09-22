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
import re

#: 施工圖 `§一`「狀態值」那一行，**逐字五個**。
#:
#: ⚠️ 「作廢」**不是狀態**，是動作 —— 它落在 `voided_at`／`voided_by`／
#:    `void_reason`／`supersedes_no` 四個欄位上。
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
    voucher["signatures"] = signatures_of(voucher)
    return voucher


#: 版面上的三個簽名格（使用者的實例逐字：製票／覆核／主管）。
#:
#: 🔴 **製票不是一個簽核動作** —— 它就是建立者。
#:    ⇒ 它讀 `created_by`／`created_at`，沒有自己的欄位。
#: ⚠️ 而三格**各有自己的時間戳**，不共用 `updated_at`：
#: ☠️ 共用的話，任何一次編輯都會把「覆核是什麼時候簽的」推掉 ——
#:    而那一列**看起來完全正常**：有人、有時間，只是時間是錯的。
#: ⚠️ 鍵用**中文格名**，與版面上印的三個字一致（使用者的實例逐字）。
#:    英文鍵會讓畫面與 API 各有一套名字，而那一層翻譯沒有人維護。
_SIGNATURE_SLOTS = (
    ("製票", "created_by", "created_at"),
    ("覆核", "checked_by", "checked_at"),
    ("主管", "manager_by", "manager_at"),
)


def signatures_of(voucher):
    """三格簽核：`{格名: {by, at}}`，格名是「製票／覆核／主管」。

    ⚠️ 還沒簽的那一格 `by`／`at` 是**空字串**（欄位的 DEFAULT），
       而呼叫端要分得出「還沒簽」與「簽了而沒有時間」——
       🔑 前者是流程還沒走到，後者是缺陷。
    📌 `§106c`：三格**從簽核紀錄取，不可以從 `status` 欄推** ——
       ☠️ 從 status 推的話，一張退回重送的單會顯示「覆核已簽」而其實被清掉了。
    """
    out = {}
    for label, by_col, at_col in _SIGNATURE_SLOTS:
        out[label] = {
            "by": voucher.get(by_col) or "",
            "at": voucher.get(at_col) or "",
        }
    return out


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
