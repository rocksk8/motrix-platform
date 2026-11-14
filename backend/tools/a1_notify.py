# -*- coding: utf-8 -*-
"""A1 套用結果的 ERP 端動作（稽核列、站內通知、Email、LINE）。由 `auto_apply.notify_result` 以子行程呼叫。

用法：`python -B a1_notify.py <安裝目錄\\backend>`，stdin 給 `auto_apply.build_notice` 的 JSON。
為什麼是子行程：儀表板是獨立的本機行程，不載入 ERP 的 helpers；這裡用**安裝目錄裡的後端**（套用完的新版）寫庫與發通知，
沿用既有機制：稽核走 `helpers.audit._audit`、站內通知走 `helpers.audit._notify`、Email 與 LINE 走登入失敗告警同一支 `email_notify.send_registered`
（收件人＝信件類型 `system_update_result` 登記的群組「僅最高管理者」加設定頁覆寫；LINE 只給收件人控制裡勾選且已綁定的人，不群發）。
內容只有：包名、結果、停在哪一步、未通過項目 id、報告檔名。三件事各自獨立、各自失敗；結果印成一行 `A1_NOTIFY_RESULT {json}`。
"""
import json
import os
import sys
import threading
import time

EVENT_KEY = "system_update_result"


def _count(table_where, args):
    from db import get_db
    conn = get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM " + table_where, args).fetchone()[0]
    finally:
        conn.close()


def _erp_audit(n):
    """`_audit` 只認 session token（沒有用帳號寫入的版本），這裡沒有 token ⇒ username 欄是空的，套用者放在 detail.by。吞例外 ⇒ 用前後筆數確認真的寫進去。"""
    from helpers import audit as _a
    where = "audit_log WHERE action=? AND target_id=?"
    args = ("system_update.apply", n["name"][:80])
    before = _count(where, args)
    detail = {"by": n.get("by"), "outcome": n.get("outcome"), "stopped_at": n.get("stopped_at"), "failed_items": n.get("failed_items"),
              "report": n.get("report_name"), "chain_head": n.get("chain_head"), "downtime_seconds": n.get("downtime_seconds")}
    # username 欄是空的（_audit 只認 session token）；稽核頁的列表顯示 target_label、關鍵字搜尋也比對它 ⇒ 套用者寫進標籤，看得到也搜得到
    _a._audit("", "system_update.apply", "system_update", n["name"][:80], n["audit_label"][:200], detail)
    return _count(where, args) > before


def _in_app(n):
    from helpers import audit as _a, event_audience
    users = event_audience.group_usernames(EVENT_KEY)
    where = "notifications WHERE type=?"
    before = _count(where, (EVENT_KEY,))
    for u in users:
        _a._notify(u, EVENT_KEY, n["name"][:80], n["name"][:60], n["message"])
    return {"recipients": len(users), "written": _count(where, (EVENT_KEY,)) - before}


def _mail_and_line(n):
    from helpers import email_notify as _en, mail_types
    if mail_types.get(EVENT_KEY) is None:
        return {"error": "信件類型 %s 在安裝版本裡沒有登記（可能是回滾後的舊版）" % EVENT_KEY}
    out = {}
    queued = _en.send_registered("system_update_result", title=n["title"], rows=n["rows"], to_group=True, reason=n["reason"],
                                 badge_text=n["badge_text"], badge_color=n["badge_color"], wait=True, out=out,
                                 line_key="a1_update:%s" % (n.get("chain_head") or "%s@%d" % (n["name"], time.time())))
    for t in list(threading.enumerate()):                       # LINE 在背景執行緒送：行程結束前要等它（daemon 執行緒會被直接砍掉）
        if t is not threading.current_thread() and t.name in ("line-event", "line-push"):
            t.join(timeout=60)
    return {"queued": bool(queued), "outcome": str(out.get("outcome"))}


def main(argv, stdin_text):
    backend = os.path.abspath(argv[1])
    os.chdir(backend)
    sys.path.insert(0, backend)
    n = json.loads(stdin_text)
    res, errors = {}, []
    for key, fn in (("audit_log", _erp_audit), ("in_app", _in_app), ("mail", _mail_and_line)):
        try:
            res[key] = fn(n)
        except Exception as exc:                                # noqa: BLE001 — 三件事各自失敗，不互相拖累
            res[key] = None
            errors.append("%s：%s" % (key, type(exc).__name__))
    # 沒有人收到＝沒有通知：收件人 0 人、站內沒有寫進任何一則、信件沒排入佇列都算失敗（結束碼 2，notify_result 會寫進報告與問題清單）
    in_app, mail = res.get("in_app") or {}, res.get("mail")
    if res.get("in_app") is not None and not in_app.get("recipients"):
        errors.append("沒有任何收件人（最高管理者清單是空的）")
    elif res.get("in_app") is not None and not in_app.get("written"):
        errors.append("站內通知沒有寫進任何一則")
    if isinstance(mail, dict) and "error" not in mail and not mail.get("queued"):
        errors.append("信件未排入")
    ok = res.get("audit_log") is True and isinstance(mail, dict) and "error" not in mail and not errors
    if errors or not ok:
        res["error"] = "；".join(errors) or "有項目沒有完成"
    print("A1_NOTIFY_RESULT " + json.dumps(res, ensure_ascii=False))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv, sys.stdin.buffer.read().decode("utf-8")))
