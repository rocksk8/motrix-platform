# -*- coding: utf-8 -*-
"""IP-117（暫定號，列車定號）`stock.case_summary`：該案件的庫存序號彙總（唯讀；M03 → M01 物料流程時間軸）。

只回數量與料號，**沒有任何金額欄位**（成本不在這個介面裡，所以 `caller` 目前不影響內容；簽章保留它，之後若要加成本欄位，遮罩在這裡依 `caller` 做）。
案件可見性由案件側先檢查（本模組不認識案件成員）。讀的是呼叫端傳入的連線，不寫、不 commit。
"""


def case_summary(conn, quote_no, caller=None) -> dict:
    """⇒ {"installed": 台數, "shipped": 台數, "void": 台數, "parts": [{"partNo", "installed", "shipped"}]}（只算 `quote_no` 相同的序號；沒有 ⇒ 全 0）。"""
    out = {"installed": 0, "shipped": 0, "void": 0, "parts": []}
    if not quote_no:
        return out
    rows = conn.execute("SELECT part_no, status, COUNT(*) AS n FROM stock_items WHERE quote_no=? GROUP BY part_no, status ORDER BY part_no", (quote_no,)).fetchall()
    parts = {}
    for r in rows:
        st, n = r["status"], int(r["n"])
        if st in ("installed", "shipped", "void"):
            out[st] += n
        if st in ("installed", "shipped"):
            p = parts.setdefault(r["part_no"] or "", {"partNo": r["part_no"] or "", "installed": 0, "shipped": 0})
            p[st] += n
    out["parts"] = list(parts.values())
    return out
