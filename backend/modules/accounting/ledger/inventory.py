# -*- coding: utf-8 -*-
"""存貨帳：移動加權平均（proposal-gl/07-inventory-cost.md §2）。

每個料號一條鏈（`gl_inv_moves` 只增不改，`gl_inv_parts` 是各料號目前在庫數量與金額）。**以金額守恆，不存浮點單價**：
- 入庫：數量、金額都加上去（進貨事件 E08 的 `meta.part_no／qty`＋成本合計）。
- 出庫：`amount = round_half_up(value_before × qty_out ÷ qty_before)`；出清（qty_out＝qty_before）時 `amount = value_before`，不殘留分位差。
- 退回（來源消失或數量變小）：以**原出庫列的金額**回沖（`links_move_id`），不是現行均價。
- 進貨成本被改（E08 內容變動）：另記一筆 `adjust`（數量 0、金額差）。
- 均價改變**不重算**已出庫成本（移動平均的本質）；不夠出庫的數量 ⇒ `InsufficientStock`（引擎標 `blocked_inventory`，不猜）。
所有函式不 commit（呼叫端決定交易）；同一 `(ref_type, ref_key, part_no, move_type)` 只會記一次（冪等）。
"""
import datetime as _dt

from helpers.legal_params import round_half_up


class InsufficientStock(Exception):
    """在庫數量不足以出庫（多半是進貨事件所在期間還沒執行引擎，或開帳存貨未建立）。"""


def _now():
    return _dt.datetime.now().isoformat(timespec="microseconds")


def state(conn, part_no):
    """⇒ (在庫數量, 在庫金額)。"""
    r = conn.execute("SELECT qty, value FROM gl_inv_parts WHERE part_no=?", (part_no,)).fetchone()
    return (int(r[0]), int(r[1])) if r else (0, 0)


def issue_amount(conn, part_no, qty):
    """出庫金額（只算不記）。數量不足 ⇒ InsufficientStock。"""
    qb, vb = state(conn, part_no)
    if qty <= 0:
        raise ValueError("出庫數量要大於 0")
    if qty > qb:
        raise InsufficientStock("料號 %s 在庫 %d 不足出庫 %d（進貨事件還沒入帳，或尚未建立開帳存貨）" % (part_no, qb, qty))
    return vb if qty == qb else int(round_half_up(vb * qty / qb))


def record(conn, part_no, move_type, qty, amount, ref_type, ref_key, case_no="", links_move_id=None, at=None):
    """記一筆異動並更新該料號在庫；冪等（同鍵已記過 ⇒ 回既有列 id，不重記）。qty／amount 入為正、出為負。"""
    old = conn.execute("SELECT id FROM gl_inv_moves WHERE ref_type=? AND ref_key=? AND part_no=? AND move_type=?",
                       (ref_type, ref_key, part_no, move_type)).fetchone()
    if old:
        return old[0]
    qb, vb = state(conn, part_no)
    qa, va = qb + int(qty), vb + int(amount)
    if qa < 0 or va < 0:
        raise InsufficientStock("料號 %s 異動後在庫會變負（數量 %d、金額 %d）" % (part_no, qa, va))
    stamp = at or _now()
    cur = conn.execute(
        "INSERT INTO gl_inv_moves(part_no, move_at, move_type, qty, amount, qty_after, value_after, ref_type, ref_key, case_no, links_move_id, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (part_no, stamp, move_type, int(qty), int(amount), qa, va, ref_type, ref_key, case_no or "", links_move_id, _now()))
    conn.execute("INSERT INTO gl_inv_parts(part_no, qty, value, last_move_id, updated_at) VALUES (?,?,?,?,?) "
                 "ON CONFLICT(part_no) DO UPDATE SET qty=excluded.qty, value=excluded.value, last_move_id=excluded.last_move_id, updated_at=excluded.updated_at",
                 (part_no, qa, va, cur.lastrowid, _now()))
    return cur.lastrowid


def receipt(conn, part_no, qty, amount, ref_key, at=None):
    """進貨入庫（批次）。同一批次成本後來被改 ⇒ 另記 adjust（差額），數量不動。"""
    first = conn.execute("SELECT id, amount FROM gl_inv_moves WHERE ref_type='stock_batch' AND ref_key=? AND part_no=? AND move_type='receipt'",
                         (ref_key, part_no)).fetchone()
    if first is None:
        return record(conn, part_no, "receipt", qty, amount, "stock_batch", ref_key, at=at)
    booked = first[1] + sum(r[0] for r in conn.execute(
        "SELECT amount FROM gl_inv_moves WHERE ref_type='stock_batch_adj' AND part_no=? AND ref_key LIKE ?", (part_no, ref_key + "#%")))
    delta = int(amount) - booked
    if delta:
        n = conn.execute("SELECT COUNT(*) FROM gl_inv_moves WHERE ref_type='stock_batch_adj' AND part_no=? AND ref_key LIKE ?",
                         (part_no, ref_key + "#%")).fetchone()[0]
        return record(conn, part_no, "adjust", 0, delta, "stock_batch_adj", "%s#%d" % (ref_key, n + 1), links_move_id=first[0], at=at)
    return first[0]


def issue(conn, part_no, qty, ref_type, ref_key, case_no="", at=None):
    """出庫；回 (異動列 id, 金額)。冪等：同鍵已出庫 ⇒ 回既有列與其金額。"""
    old = conn.execute("SELECT id, amount FROM gl_inv_moves WHERE ref_type=? AND ref_key=? AND part_no=? AND move_type='issue'",
                       (ref_type, ref_key, part_no)).fetchone()
    if old:
        return old[0], -old[1]
    amt = issue_amount(conn, part_no, qty)
    return record(conn, part_no, "issue", -qty, -amt, ref_type, ref_key, case_no, at=at), amt


def reverse_issue(conn, part_no, ref_type, ref_key, at=None):
    """把某次出庫以**原金額**回沖（退回／來源消失）。沒有這次出庫 ⇒ None；已回沖過 ⇒ 既有回沖列 id。"""
    orig = conn.execute("SELECT id, qty, amount, case_no FROM gl_inv_moves WHERE ref_type=? AND ref_key=? AND part_no=? AND move_type='issue'",
                        (ref_type, ref_key, part_no)).fetchone()
    if orig is None:
        return None
    return record(conn, part_no, "return_in", -orig[1], -orig[2], ref_type, ref_key, orig[3], links_move_id=orig[0], at=at)
