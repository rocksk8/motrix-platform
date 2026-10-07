"""一次性：把既有的 Google 行事曆「付款待辦」事件重新對齊成現行內容（第 45 班稽核 S4）。

為什麼：第 45 班（預定付款日 Q4）之後 `payable_calendar.compose` 不再放「受款人」「付款條件」，但**已經建立**的事件說明欄仍帶舊文字，
要等該筆下一次被 `fire`（改預定日、付款、作廢…）才會被覆寫。若要立刻去掉舊文字，跑這支：對每一筆「現在仍符合條件」的額外支出呼叫
`payable_calendar.sync(id)`（upsert 同一個事件識別 `case:<id>`，內容用現行的 compose）。不符合條件的（已付款、作廢…）不碰——它們的事件在當下就已被刪除。

用法（預設只列出，不呼叫 Google、不寫資料庫）：
    python tools/payable_calendar_resync.py [--db PATH]                      # dry-run：列出會重新對齊的額外支出 id
    python tools/payable_calendar_resync.py --apply [--limit N] [--sleep S]  # 真的對齊（用目前設定的資料庫；不接受 --db）
說明：
- 事件種類 `payable_due` 的開關關閉時 L1 不碰 Google（零流量），`--apply` 會等於什麼都沒做——先在行事曆設定確認有開。
- 每筆之間睡 `--sleep` 秒（預設 0.5）避免打滿 Google API 配額；`--limit` 可分批。輸出只有 id 與筆數，不含任何名稱或金額。
- 只讀資料庫；寫入只有對 Google 行事曆的 upsert。可重複執行（冪等）。
結束碼：0 完成；2 用法錯誤（例如 --apply 同時給 --db）／讀不到資料庫。
"""
import argparse
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def eligible_ids(conn) -> list:
    """現在仍符合「付款待辦」條件的額外支出 id（已核准、未付款、可付款類型、預定付款日合法）。"""
    from modules.case import payable_calendar as PC
    out = []
    for r in conn.execute("SELECT * FROM case_extra_expenses WHERE status='已核准' AND COALESCE(paid_date,'')='' ORDER BY id").fetchall():
        if PC.eligible(r):
            out.append(r["id"])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=0.5)
    a = ap.parse_args(argv)
    if a.apply and a.db:
        print("--apply 一律用目前設定的資料庫與行事曆設定，不接受 --db（避免對著一份複本去改真正的行事曆）")
        return 2
    try:
        if a.db:
            conn = sqlite3.connect("file:%s?mode=ro" % a.db.replace("\\", "/"), uri=True)
            conn.row_factory = sqlite3.Row
        else:
            import db
            conn = db.get_db()
    except Exception as e:                                  # noqa: BLE001
        print("讀不到資料庫：%s" % e)
        return 2
    try:
        try:
            ids = eligible_ids(conn)
        except sqlite3.OperationalError as e:
            print("沒有額外支出資料表（%s）：無事可做" % e)
            return 0
    finally:
        conn.close()
    if a.limit and a.limit > 0:
        ids = ids[:a.limit]
    print("會重新對齊 %d 筆「付款待辦」事件：%s" % (len(ids), "、".join(str(i) for i in ids[:50]) + (" …" if len(ids) > 50 else "")))
    if not a.apply:
        print("（dry-run；加 --apply 才會呼叫行事曆）")
        return 0
    from modules.case import payable_calendar as PC
    for n, i in enumerate(ids, 1):
        PC.sync(i)
        if a.sleep > 0 and n < len(ids):
            time.sleep(a.sleep)
    print("已對齊 %d 筆" % len(ids))
    return 0


if __name__ == "__main__":
    sys.exit(main())
