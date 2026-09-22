# -*- coding: utf-8 -*-
"""傳票（`FN4②` 的呼叫端）—— 讀一張、改草稿。

施工圖：`docs/windows/SPEC-VOUCHER.md`。

# 🔴 這一支存在的第一個理由：**讓 `append_edit_log()` 有人叫**

```
helpers/edit_log.py  規則寫好了、測試綠了
routers/vouchers.py  **不存在** => 沒有任何人在「改」的時候叫它
```
☠️ 〈兩個都對而路不存在〉：規則對、函式對、題目也對，**而它不會生效**。
🔑 而這種缺陷**讀規格看不出來** —— 規格說「改過要留痕」，函式也真的會留痕。

# ⚠️ 本輪只做「讀」與「改草稿」

過帳、送審、退回、作廢那幾條走 `helpers.voucher` 的純邏輯，
而它們的端點**沒有派工** ⇒ 不在這裡順手加。
"""
import datetime as _dt
from datetime import datetime

from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from helpers import _require_user, _tok, _audit, require_any_module
from helpers.edit_log import append_edit_log, MissingOldValue
from helpers.voucher import (
    EDITABLE_STATUSES, can_edit, describe_balance, get_voucher,
    next_voucher_no, post_voucher, can_send_back, next_revision_no,
    diff_lines,
)

router = APIRouter(prefix="/api/vouchers", tags=["vouchers"])

#: 看得到傳票的人。傳票是會計憑證 ⇒ 與出納同一群受眾。
#:
#: 🔴 用 `require_any_module` 而**不是** `user["role"] in ("superadmin","admin")`：
#:    後者讓 admin 直通，而 2026-09-14 使用者裁示逐字是
#:    「管理者一樣依據有開權限的內容去顯示，沒開的就不顯示」
#:    ⇒ **只有 superadmin 直通**，admin 也必須真的持有模組。
#: ☠️ 而 `_require_user()` 單獨用是不夠的：那等於**任何登入者**都讀得到
#:    全公司的會計憑證，而畫面上看不出來 —— 側欄沒有入口不代表 API 擋得住。
_VOUCHER_MODULES = ("cashier", "finance")


def _require_voucher_access(user):
    require_any_module(user, _VOUCHER_MODULES, "傳票")

def _user_name(user):
    """寫進 `*_by` 欄位的值：**`username`，不是 token，也不是 id**。

    ## ☠️ 原本寫的是 `_tok(authorization)` —— 那是**原始 bearer token**

    ```
    寫入  created_by / submitted_by / checked_by / manager_by / voided_by / posted_by
    讀出  SELECT * -> dict(row)  => 任何有 cashier／finance 的人都拿得到
    ```
    而 token 有效期 **30 天**，且 `auth.py:216` 的條件讓 **NULL 等於永不過期**。
    🔑 ⇒ 那不是「欄位存錯東西」，是**把別人的憑證發給其他使用者**。

    ## ⚠️ 用 `username` 而不是 `id`

    `auth.py:1502` 的可更新白名單是 display_name／email／phone／modules／
    notification_muted／department_id／password ⇒ **`username` 不可改**
    ⇒ 它當歷史紀錄是穩定的。
    📌 而 `visible_lines(lines, username, …)` 與獎金的可見性判斷**已經用 username**
       ⇒ 零轉換層。

    ## 🔴 而版面上那一格會印出它

    `signatures_of()` 把這些欄位當成「簽名的人」回傳
    ⇒ 舊寫法會讓傳票的「製票」格印出一串 64 字元的 token。
    """
    return (user or {}).get("username") or ""


#: 草稿可以改的欄位。**白名單，不是黑名單。**
#:
#: ☠️ 黑名單的話，日後 DDL 加一欄就自動變成「可以改」——
#:    而沒有人會發現 `posted_by` 突然變得可以從前端改掉。
#: ⚠️ `voucher_no` **不在裡面**：它由退回升版產生，不是使用者填的。
EDITABLE_FIELDS = ("voucher_date", "category", "summary")


@router.post("")
def create_voucher(body: dict = Body(...), authorization: str = Header(None)):
    """建立一張**草稿**傳票（`JV1`）。

    ## 🔴 草稿**允許不平衡**

    使用者正在打，打到一半本來就不平。
    ☠️ 反過來擋的症狀是「**他打不完第一行就被擋住**」——
       而它看起來很嚴謹，所以不會有人覺得那是缺陷。
    ⇒ 借貸平衡是**過帳**那一關的事（`describe_balance`），不是建立這一關。

    ## ⚠️ 單號由後端發，而規則在 `helpers/voucher.py`

    `next_voucher_no()` 取那一天的**最大值 +1**（不是數幾筆）——
    理由見它的 docstring：作廢單留在表上，數筆數會撞號。
    🔑 而併發撞號由 `UNIQUE INDEX` 擋，這裡把它翻成一句人看得懂的話。
    """
    user = _require_user(authorization)
    _require_voucher_access(user)

    # 🔁 日期**可選，預設今天**（使用者 2026-09-23 改裁）——
    #    舊裁示「建檔當天且不可改」已被推翻，理由是月結補登是會計的日常。
    voucher_date = (body.get("voucher_date") or "").strip() or _dt.date.today().isoformat()
    lines = body.get("lines") or []
    now = _dt.datetime.now().isoformat()

    conn = get_db()
    try:
        no = next_voucher_no(conn, voucher_date)
        try:
            cur = conn.execute(
                "INSERT INTO vouchers_all (voucher_no, voucher_date, category,"
                " summary, status, created_by, created_at, updated_at)"
                " VALUES (?,?,?,?, '草稿', ?,?,?)",
                (no, voucher_date, (body.get("category") or "轉"),
                 (body.get("summary") or ""), _user_name(user), now, now))
        except Exception as exc:                            # noqa: BLE001
            if "UNIQUE" in str(exc).upper():
                raise HTTPException(
                    409, "傳票號碼「%s」剛剛被別人用掉了，請再存一次。" % no)
            raise
        vid = cur.lastrowid
        for i, ln in enumerate(lines, start=1):
            conn.execute(
                "INSERT INTO voucher_lines (voucher_id, line_no, account_code,"
                " summary, debit, credit) VALUES (?,?,?,?,?,?)",
                (vid, i, (ln.get("account_code") or ""),
                 (ln.get("summary") or ""),
                 int(ln.get("debit") or 0), int(ln.get("credit") or 0)))
        conn.commit()
    finally:
        conn.close()

    _audit(_tok(authorization), "voucher.create", "vouchers", str(vid),
           "建立傳票草稿：%s" % no)
    return {"ok": True, "id": vid, "voucher_no": no, "status": "草稿"}


@router.get("")
def list_vouchers(include_voided: bool = False,
                  authorization: str = Header(None)):
    """傳票清單。

    ⚠️ 預設**只列有效的**（走 VIEW `vouchers`）——
       作廢單仍查得到（稽核），而要明著要（`include_voided`）。
    📌 清單**不帶分錄**：一次把幾百張單的分錄都撈回來，
       而畫面上那一層根本不顯示它們。
    """
    user = _require_user(authorization)
    _require_voucher_access(user)
    conn = get_db()
    try:
        # 🔑 有效的走 VIEW、要全部才打實表 —— 而不是自己再寫一次 WHERE：
        #    那個條件只該有一個地方寫著（`v95` 的 VIEW 定義）。
        src = "vouchers_all" if include_voided else "vouchers"
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM %s ORDER BY id DESC" % src)]
    finally:
        conn.close()
    return {"vouchers": rows, "count": len(rows)}


# ══════════════════════════════════════════════════════════════════════
# 🔴 要加**靜態** GET 路徑（例如 `/summary-sources`）的人：**宣告在這一行之前**
# ══════════════════════════════════════════════════════════════════════
#
# 下面這條 `GET /{voucher_id}` 是本 router 第一條動態 GET 路由。
# FastAPI 依**宣告順序**比對 ⇒ 任何宣告在它後面的靜態 GET 路徑會先命中它，
# 然後 `voucher_id: int` 解析失敗。
#
# ☠️ 而失敗的樣子是 **422，不是 404**：
# ```
# GET /api/vouchers/summary-sources  =>  422 {"detail":"參數不正確…"}
# ```
# 🔑 **422 讀起來像「我參數傳錯了」，而實際是「這條路根本還沒做」** ——
#    查的人會去翻自己的呼叫端，而問題在這個檔案的行號順序上。
# 📌 這一段寫在這裡而不是寫進規格：**下一個加端點的人不會去讀規格，
#    而他一定會看到這一行。**（C 2026-09-23 實測 `summary-sources` 回 422。）
@router.get("/{voucher_id}")
def read_voucher(voucher_id: int, authorization: str = Header(None)):
    """讀一張傳票（含分錄）。科目名稱依 `status` 決定取凍結值或現值。"""
    _require_voucher_access(_require_user(authorization))
    conn = get_db()
    try:
        data = get_voucher(conn, voucher_id)
    finally:
        conn.close()
    if data is None:
        raise HTTPException(404, "找不到這張傳票。")
    return data


#: 簽核兩層（A `§161` 裁定，**寫死**）。
#:
#: ```
#: 製票  建立者 => `created_by`／`created_at`，**不算一層**
#: 覆核  第 1 層 => checked_by／checked_at
#: 主管  第 2 層 => manager_by／manager_at
#: ```
#: ⚠️ **不接既有 `approval_settings`** —— 那是承攬商匯款單那一套，層數可設定。
#: 🔑 兩套混在一起的話，改了那邊的設定會**靜默改掉傳票的簽核流程**。
_SIGN_SLOTS = (("checked", "簽核中"), ("manager", "已核准"))


def _load(conn, voucher_id):
    row = conn.execute("SELECT * FROM vouchers_all WHERE id = ?",
                       (voucher_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "找不到這張傳票。")
    v = dict(row)
    if v.get("voided_at"):
        raise HTTPException(400, "這張傳票已經作廢。")
    return v


@router.post("/{voucher_id}/submit")
def submit_voucher(voucher_id: int, body: dict = Body(default={}),
                   authorization: str = Header(None)):
    """送審：草稿 → 待審核。"""
    user = _require_user(authorization)
    _require_voucher_access(user)
    conn = get_db()
    try:
        v = _load(conn, voucher_id)
        if v.get("status") != "草稿":
            raise HTTPException(
                400, "只有草稿可以送審，這一張現在是「%s」。" % v.get("status"))
        now = _dt.datetime.now().isoformat()
        conn.execute(
            "UPDATE vouchers_all SET status='待審核', submitted_by=?,"
            " submitted_at=?, updated_at=? WHERE id=?",
            (_user_name(user), now, now, voucher_id))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "voucher.submit", "vouchers", str(voucher_id),
           "傳票送審")
    return {"ok": True, "status": "待審核"}


@router.post("/{voucher_id}/approve")
def approve_voucher(voucher_id: int, body: dict = Body(default={}),
                    authorization: str = Header(None)):
    """簽核通過。**兩層**：待審核 →（覆核）→ 簽核中 →（主管）→ 已核准。

    ## ⚠️ 每一格寫**自己的**時間戳，不共用 `updated_at`

    ☠️ 共用的話，任何一次編輯都會把「覆核是什麼時候簽的」推掉 ——
       而那一列**看起來完全正常**：有人、有時間，只是時間是錯的。
    ⚙️ 而判準是「簽完主管之後覆核的時間戳沒被改掉」，
       **不是**「三格時間不可以相同」—— 小公司常常同一個人連按兩次，
       🔑 **真的會同一秒**，那種斷言會紅在一個正確的實作上。
    """
    user = _require_user(authorization)
    _require_voucher_access(user)
    conn = get_db()
    try:
        v = _load(conn, voucher_id)
        status = v.get("status")
        if status == "待審核":
            slot, nxt = "checked", "簽核中"
        elif status == "簽核中":
            slot, nxt = "manager", "已核准"
        else:
            raise HTTPException(
                400, "「%s」的傳票不在簽核流程裡。" % status)
        now = _dt.datetime.now().isoformat()
        # 🔑 只寫**這一格**的兩欄 —— 另一格的時間戳完全不碰。
        conn.execute(
            "UPDATE vouchers_all SET status=?, %s_by=?, %s_at=?, updated_at=?"
            " WHERE id=?" % (slot, slot),
            (nxt, _user_name(user), now, now, voucher_id))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "voucher.approve", "vouchers", str(voucher_id),
           "傳票簽核：%s" % nxt)
    return {"ok": True, "status": nxt}


@router.post("/{voucher_id}/send-back")
def send_back_voucher(voucher_id: int, body: dict = Body(default={}),
                      authorization: str = Header(None)):
    """退回修改：狀態回草稿 ＋ **清除簽核** ＋ **單號升版 `-Rn`**。

    ## 🔴 三件要一起做，少一件都會留下一個看不出來的錯

    ```
    狀態回草稿    少了它 => 退回的單卡在簽核中，沒有人能改
    清除簽核      少了它 => **帶著上一輪的簽名走完流程**
                          而簽過的人不知道他簽的已經被改過了
    單號升版      少了它 => 同一張被退兩次**看不出來**（§103e：財務不可接受）
    ```
    ⚠️ 升版走 `next_revision_no()` —— **不可以**借用報價單那一支：
       它把 `MQ-` 前綴寫死，對不上就無腦 `+ '-R1'` ⇒ 第二次會變 `-R1-R1`，
       而 `UNIQUE INDEX` 擋不住（不同字串）⇒ **不報錯，只是產生一個錯的單號**。
    """
    user = _require_user(authorization)
    _require_voucher_access(user)
    conn = get_db()
    try:
        v = _load(conn, voucher_id)
        if not can_send_back(v.get("status")):
            raise HTTPException(
                400, "「%s」的傳票不能退回。%s"
                     % (v.get("status"),
                        "已過帳只能作廢重開。" if v.get("status") == "已過帳" else ""))
        new_no = next_revision_no(v.get("voucher_no"))
        now = _dt.datetime.now().isoformat()
        conn.execute(
            "UPDATE vouchers_all SET status='草稿', voucher_no=?,"
            " submitted_by='', submitted_at='', checked_by='', checked_at='',"
            " manager_by='', manager_at='', updated_at=? WHERE id=?",
            (new_no, now, voucher_id))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "voucher.send_back", "vouchers",
           str(voucher_id), "傳票退回：%s（%s）"
           % (new_no, (body or {}).get("reason") or "未填原因"))
    return {"ok": True, "status": "草稿", "voucher_no": new_no}


@router.post("/{voucher_id}/void")
def void_voucher(voucher_id: int, body: dict = Body(default={}),
                 authorization: str = Header(None)):
    """作廢。**原單留著**，只是從有效清單消失。

    ⚙️ 這是「已過帳」唯一的出路（退回被擋）——
    ☠️ 少了它，一張開錯的已過帳傳票**從此沒有出路**。
    """
    user = _require_user(authorization)
    _require_voucher_access(user)
    reason = ((body or {}).get("reason") or "").strip()
    if not reason:
        # 🔑 沒有理由的作廢等於沒有留痕：事後沒有人回得出為什麼。
        raise HTTPException(400, "請填寫作廢原因。")
    now = _dt.datetime.now().isoformat()
    conn = get_db()
    try:
        _load(conn, voucher_id)          # 已作廢的會在這裡被擋掉
        conn.execute(
            "UPDATE vouchers_all SET voided_at=?, voided_by=?, void_reason=?,"
            " updated_at=? WHERE id=?",
            (now, _user_name(user), reason, now, voucher_id))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "voucher.void", "vouchers", str(voucher_id),
           "傳票作廢：%s" % reason)
    return {"ok": True, "voided_at": now}


@router.post("/{voucher_id}/post")
def post_voucher_endpoint(voucher_id: int, body: dict = Body(default={}),
                          authorization: str = Header(None)):
    """過帳（`JV1`，A `§162` 從 `JV2` 移進來）。

    ## 🔴 這一支是 `helpers.voucher.post_voucher()` 的**薄包裝**

    ☠️ 在這裡再寫一份平衡檢查的話，就是**第二份判準** ——
       而兩份會分岔，分岔之後沒有人知道哪一份是真的，
       🔑 **而它一開始是綠的**。
    ⇒ 借貸差額那句話由 `describe_balance()` 算（它已經說得出「貸方少 100」），
      狀態、凍結科目名稱、`posted_at`／`posted_by` 全在那支 helper 裡。

    ## ⚠️ 本輪**只有過帳**

    `submit`／`approve`／`send-back`／`void` 是 `JV2`，不在這裡順手加。
    """
    user = _require_user(authorization)
    _require_voucher_access(user)
    conn = get_db()
    try:
        ok, err = post_voucher(conn, voucher_id, _user_name(user))
        if not ok:
            # 🔑 `err` 是**給使用者看的字串**（含差額）⇒ 原樣帶出去，
            #    不要在這裡改寫成一句更短的話。
            conn.rollback()
            raise HTTPException(400, err)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "voucher.post", "vouchers", str(voucher_id),
           "傳票過帳")
    return {"ok": True, "status": "已過帳"}


@router.put("/{voucher_id}")
def update_voucher(voucher_id: int, body: dict = Body(...),
                   authorization: str = Header(None)):
    """改一張**草稿**傳票。有改到東西才寫一列編寫紀錄。

    ## 🔴 「剛好一列」，不是「至少一列」

    ```
    0 列  => 改過而沒有留痕（這一題要抓的）
    2 列+ => 改一次留兩筆痕，**稽核讀起來像改了兩次**
    ```
    ⇒ 一次 `PUT` 把所有變動收成**一筆** `changes_json`，不是每欄寫一列。

    ## ⚙️ 沒有改動 ⇒ **不寫**

    ☠️ 一列 `changes_json='[]'` 的留痕看起來像有記錄，而它什麼都沒說；
       而使用者按了「儲存」卻沒改東西是**日常**，不是例外
       ⇒ 那樣稽核紀錄會被灌滿沒有內容的列。

    ## ⚠️ 比對用**原值**，而寫入前先算好差異

    🔑 先算差異再寫，順序不可以反：
    ☠️ 先寫再算的話，`from` 會變成**新值**（因為它已經被覆蓋了），
       而那一列**看起來完全正常** —— 它有時間、有人、有欄位名，
       只是 `from` 與 `to` 一樣。
    """
    user = _require_user(authorization)
    # ⚠️ 改與讀用**同一道閘**，而不是「讀鬆一點、改緊一點」——
    #    再緊的那一層是 `can_edit(status)`：只有草稿改得動。
    #    🔑 兩道閘各自回答不同的問題：**誰**可以碰／這張單**現在**可不可以碰。
    _require_voucher_access(user)
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM vouchers_all WHERE id = ?",
                           (voucher_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "找不到這張傳票。")
        current = dict(row)
        if current.get("voided_at"):
            raise HTTPException(400, "這張傳票已經作廢，不能修改。")
        if not can_edit(current.get("status")):
            raise HTTPException(
                400, "只有「%s」可以修改，這一張現在是「%s」。"
                     % ("／".join(EDITABLE_STATUSES), current.get("status")))

        # 🔑 **先算差異**（用原值），再寫入。
        changes = []
        updates = {}
        for field in EDITABLE_FIELDS:
            if field not in body:
                continue
            new = body[field]
            old = current.get(field)
            # ⚠️ 用 `!=` 比對原值：兩者都可能是空字串，
            #    而「空 → 空」不是改動。
            if new == old:
                continue
            changes.append({"field": field, "from": old, "to": new})
            updates[field] = new

        # 🔴 **分錄：`lines` 有帶才動它，沒帶就一個字都不碰。**
        #
        # ☠️ 最自然的實作是「刪掉舊的 -> 重寫新的」，而**沒帶 `lines` 的 PUT
        #    若照樣走刪除那一步，分錄會全沒** —— 那比「存不進去」更糟：
        #    單子還在、狀態還是草稿，**只是內容空了**，而且不報錯。
        # 🔑 ⇒ 判斷用 `"lines" in body`（鍵在不在），**不用值的真假**：
        #    送 `lines: []` 是「把分錄清空」，與「沒提到分錄」是兩件事。
        line_changes = []
        new_lines = None
        if "lines" in body:
            new_lines = body.get("lines") or []
            old_lines = [dict(r) for r in conn.execute(
                "SELECT * FROM voucher_lines WHERE voucher_id = ?"
                " ORDER BY line_no", (voucher_id,))]
            # 📌 逐行 diff（`§103e`）—— 整包記一筆的話，同一張被退兩次
            #    **看不出來第二次改了什麼**，而那在財務上不可接受。
            line_changes = diff_lines(old_lines, new_lines)

        # ⚙️ 反向控制的那一格：沒有改動就什麼都不做，**包括不寫紀錄**。
        #    ⚠️ 而「沒有改動」現在要把分錄一起算進來 ——
        #    ☠️ 只看 `changes` 的話，一次「只改了分錄」的儲存會在這裡
        #       提早 return，而分錄**根本沒被寫進去**。
        if not changes and not line_changes:
            return {"ok": True, "changed": 0}

        now = datetime.now().isoformat()
        if updates:
            sets = ", ".join("%s = ?" % f for f in updates)
            conn.execute(
                "UPDATE vouchers_all SET %s, updated_at = ? WHERE id = ?" % sets,
                list(updates.values()) + [now, voucher_id])
        else:
            conn.execute("UPDATE vouchers_all SET updated_at = ? WHERE id = ?",
                         (now, voucher_id))
        if new_lines is not None:
            # ⚠️ 重寫整組（刪舊寫新）—— 而它只在 `lines` 有帶的時候才發生。
            #    🔑 行號在這裡**重新編**：它是位置不是身分，
            #       而 `diff_lines()` 刻意不比對它（整行搬動不算改動）。
            conn.execute("DELETE FROM voucher_lines WHERE voucher_id = ?",
                         (voucher_id,))
            for n, ln in enumerate(new_lines, start=1):
                conn.execute(
                    "INSERT INTO voucher_lines (voucher_id, line_no,"
                    " account_code, summary, debit, credit)"
                    " VALUES (?,?,?,?,?,?)",
                    (voucher_id, n, (ln.get("account_code") or ""),
                     (ln.get("summary") or ""),
                     int(ln.get("debit") or 0), int(ln.get("credit") or 0)))
        try:
            append_edit_log(conn, voucher_id, _user_name(user),
                            changes + line_changes,
                            table="voucher_edit_log", changed_at=now)
        except MissingOldValue as exc:
            # 🔑 規則擋下來 ⇒ **整筆退回**，不要留下「改了而沒有紀錄」的狀態。
            conn.rollback()
            raise HTTPException(400, str(exc))
        conn.commit()
    finally:
        conn.close()

    _audit(_tok(authorization), "voucher.update", "vouchers",
           str(voucher_id),
           "修改傳票：%s"
           % "／".join(c["field"] for c in (changes + line_changes)))
    return {"ok": True, "changed": len(changes) + len(line_changes)}
