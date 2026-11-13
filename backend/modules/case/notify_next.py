# -*- coding: utf-8 -*-
"""一條龍 P6（旗標 `onepipe.notify_next`，預設開）：輪到某人時，站內通知他（只通知「輪到您」的人，不轟炸）。

事件與「下一棒」：
- `won`（案件成交）　　　⇒ 持有「採購」模組、且看得到這個案件的人：請開立請購單。
- `po_approved`（採購單核准）⇒ 持有「庫存」模組、且看得到這個案件的人：請準備收貨。
- `arrival_confirmed`（到貨確認）⇒ 保留；等 P2b（一站式到貨）上線後由它呼叫 `notify_next("arrival_confirmed", …)`，收件者＝案件負責人與請購人。

規則：只寫站內通知（`notifications`）；**不發 LINE、不寄信**（LINE 照既有規則，由 LINE 負責人另接）。
收件者不含觸發動作的本人；看不到案件的人不通知（通知會帶案號與客戶名稱，不能讓看不到案件的人知道案件存在）。
旗標關、任何錯誤 ⇒ 什麼都不做、不丟例外（通知失敗不能擋住成交或核准）。
"""
import json
import logging

from db import get_db

logger = logging.getLogger(__name__)

#: 事件 ⇒ (收件者持有的模組, 通知類型, 訊息範本)
_EVENTS = {
    "won": ("procurement", "case_won_next", "案件 %(case)s 已成交，請開立請購單。"),
    "po_approved": ("inventory", "po_approved_next", "案件 %(case)s 的採購單 %(doc)s 已核准，請準備收貨。"),
    "arrival_confirmed": (None, "arrival_confirmed_next", "案件 %(case)s 的採購單 %(doc)s 已到貨確認。"),
}


def _has_module(row, key: str) -> bool:
    """明確持有（superadmin 不因『全部直通』而被通知：他不是輪到的人）。"""
    try:
        return key in json.loads(row["modules"] or "[]")
    except (ValueError, TypeError):
        return False


def recipients(conn, event: str, quote_no: str, exclude: str = "") -> list:
    """這個事件下一棒的人（帳號清單）。事件不認得、或該事件沒有模組型收件者 ⇒ []。"""
    spec = _EVENTS.get(event)
    if not spec or not spec[0]:
        return []
    from helpers.case_access import case_documents_readable
    out = []
    for r in conn.execute("SELECT * FROM users WHERE active=1 ORDER BY username").fetchall():
        u = dict(r)
        if u["username"] == exclude or not _has_module(u, spec[0]):
            continue
        if case_documents_readable(conn, quote_no, u):
            out.append(u["username"])
    return out


def notify_next(event: str, quote_no: str, actor: str = "", doc: str = "", usernames=None) -> int:
    """寫站內通知給下一棒；回傳通知則數。`usernames` 有給（例如到貨確認的案件負責人）就用它，否則依事件找持有模組且看得到案件的人。永不丟例外。"""
    conn = None
    try:
        from helpers.onepipe_flags import flag_on
        spec = _EVENTS.get(event)
        if not spec or not quote_no or not flag_on("notify_next"):
            return 0
        conn = get_db()
        q = conn.execute("SELECT customer_name, project_name FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
        if not q:
            return 0
        names = [n for n in (usernames if usernames is not None else recipients(conn, event, quote_no, exclude=actor)) if n and n != actor]
        if not names:
            return 0
        from helpers.audit import _notify_in_txn
        label = "%s（%s）" % (quote_no, (q["customer_name"] or q["project_name"] or "").strip()) if (q["customer_name"] or q["project_name"]) else quote_no
        ref = "%s:%s" % (quote_no, doc or event)
        if event == "won":                                                      # 重複成案（改標記再改回來）不重發：同一人同一案件已收過就略過
            had = {r["username"] for r in conn.execute("SELECT username FROM notifications WHERE type=? AND ref_id=?", (spec[1], ref)).fetchall()}
            names = [n for n in names if n not in had]
            if not names:
                return 0
        msg = spec[2] % {"case": label, "doc": doc or ""}
        link = ("payment-request.html?case=%s&type=purchase_req" % quote_no) if event == "won" else ("case-management.html?q=%s" % quote_no)
        for n in names:
            _notify_in_txn(conn, n, spec[1], ref, quote_no, msg, link)
        conn.commit()
        return len(names)
    except Exception as e:                                                      # noqa: BLE001  通知失敗不能擋住成交或核准
        logger.warning("notify_next(%s, %s) 失敗：%s", event, quote_no, e)
        return 0
    finally:
        if conn is not None:
            conn.close()
