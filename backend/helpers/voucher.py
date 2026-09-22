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
