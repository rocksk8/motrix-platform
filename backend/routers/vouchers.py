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
    next_voucher_no, post_voucher,
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
                 (body.get("summary") or ""), _tok(authorization), now, now))
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
        ok, err = post_voucher(conn, voucher_id, _tok(authorization))
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

        if not changes:
            # ⚙️ 反向控制的那一格：沒有改動就什麼都不做，**包括不寫紀錄**。
            return {"ok": True, "changed": 0}

        now = datetime.now().isoformat()
        sets = ", ".join("%s = ?" % f for f in updates)
        conn.execute(
            "UPDATE vouchers_all SET %s, updated_at = ? WHERE id = ?" % sets,
            list(updates.values()) + [now, voucher_id])
        try:
            append_edit_log(conn, voucher_id, _tok(authorization), changes,
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
           "修改傳票：%s" % "／".join(c["field"] for c in changes))
    return {"ok": True, "changed": len(changes)}
