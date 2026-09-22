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
from datetime import datetime

from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from helpers import _require_user, _tok, _audit, require_any_module
from helpers.edit_log import append_edit_log, MissingOldValue
from helpers.voucher import EDITABLE_STATUSES, can_edit, get_voucher

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
