# -*- coding: utf-8 -*-
"""總帳 C4 · 存貨帳（移動加權平均，07-inventory-cost）與出庫成本 E10（mode=stock）。
存貨鏈：入庫、部分出庫（四捨五入）、出清取整筆、不足擋下、冪等、以原金額回沖、進貨成本被改另記 adjust。
提供者：出貨單核准（shipped）與案件認領（installed）產生 E10 事件（只有料號／件數，沒有金額）。
引擎整合：進貨先入帳 ⇒ 出庫依均價 ⇒ 借營業成本（依案件）貸存貨；沒進貨 ⇒ blocked_inventory；退回入庫 ⇒ 以原金額回沖；均價變動不算來源變動。
"""
import pytest

import db
from modules.accounting.ledger import contract as C
from modules.accounting.ledger import engine as E
from modules.accounting.ledger import inventory as INV
from modules.accounting.ledger import roles as ROLES
from modules.supply import gl_events as G

_N = [0]


@pytest.fixture
def conn(client):
    c = db.get_db()
    ROLES.ensure_meta(c)
    ROLES.ensure_default_roles(c)
    c.commit()
    yield c
    c.close()


def _part():
    _N[0] += 1
    return "P-INV-%d-%d" % (id(_N), _N[0])


# ── 存貨鏈（純算）──────────────────────────────────────────────────────

def test_chain_receipt_partial_issue_and_full_clear(conn):
    p = _part()
    INV.receipt(conn, p, 3, 1000, "B1")
    INV.receipt(conn, p, 2, 1500, "B2")                                   # 5 件、2500（均價 500）
    assert INV.state(conn, p) == (5, 2500)
    _, a1 = INV.issue(conn, p, 2, "stock_issue", "N1@1")
    assert a1 == 1000 and INV.state(conn, p) == (3, 1500)
    INV.receipt(conn, p, 1, 1001, "B3")                                   # 4 件、2501
    _, a2 = INV.issue(conn, p, 3, "stock_issue", "N2@1")
    assert a2 == round(2501 * 3 / 4 + 1e-9) and INV.state(conn, p)[0] == 1     # 1875.75 ⇒ 1876
    _, a3 = INV.issue(conn, p, 1, "stock_issue", "N3@1")
    assert a3 == 2501 - a2 and INV.state(conn, p) == (0, 0)               # 出清取整筆，不殘留分位差


def test_chain_insufficient_stock_and_no_partial_write(conn):
    p = _part()
    INV.receipt(conn, p, 1, 100, "B1")
    with pytest.raises(INV.InsufficientStock):
        INV.issue(conn, p, 2, "stock_issue", "N1@1")
    assert INV.state(conn, p) == (1, 100)


def test_chain_is_idempotent_and_reverse_uses_original_amount(conn):
    p = _part()
    INV.receipt(conn, p, 4, 1000, "B1")
    mid, amt = INV.issue(conn, p, 2, "stock_issue", "N1@1")
    assert INV.issue(conn, p, 2, "stock_issue", "N1@1") == (mid, amt) and INV.state(conn, p) == (2, 500)     # 重跑不重扣
    INV.receipt(conn, p, 4, 4000, "B2")                                   # 均價變了：6 件、4500
    rid = INV.reverse_issue(conn, p, "stock_issue", "N1@1")
    assert INV.state(conn, p) == (8, 5000) and rid                        # 以原金額 500 回沖，不是現行均價
    assert INV.reverse_issue(conn, p, "stock_issue", "N1@1") == rid       # 已回沖 ⇒ 冪等
    assert INV.reverse_issue(conn, p, "stock_issue", "NOPE@1") is None


def test_chain_receipt_cost_change_records_adjust_not_rewrite(conn):
    p = _part()
    INV.receipt(conn, p, 2, 1000, "B1")
    INV.receipt(conn, p, 2, 1200, "B1")                                   # 同批成本被改
    assert INV.state(conn, p) == (2, 1200)
    kinds = [r[0] for r in conn.execute("SELECT move_type FROM gl_inv_moves WHERE part_no=? ORDER BY id", (p,))]
    assert kinds == ["receipt", "adjust"]
    INV.receipt(conn, p, 2, 1200, "B1")                                   # 再跑 ⇒ 不再多記
    assert len(conn.execute("SELECT id FROM gl_inv_moves WHERE part_no=?", (p,)).fetchall()) == 2


def test_stock_event_contract():
    ev = {"source_type": "x", "source_key": "k", "event_code": "E10", "event_date": "2176-03-05", "mode": "stock", "stock_part_no": "P", "stock_qty": 2}
    assert C.validate_event(ev) == []
    assert any("stock_qty" in x for x in C.validate_event(dict(ev, stock_qty=0)))
    assert any("stock_part_no" in x for x in C.validate_event(dict(ev, stock_part_no="")))
    assert C.canonical_hash(ev) == C.canonical_hash(dict(ev, memo="x")) and C.canonical_hash(ev) != C.canonical_hash(dict(ev, stock_qty=3))


# ── 提供者 ─────────────────────────────────────────────────────────────

def _stock(conn, part, n, cost, batch, created="2176-03-01T09:00:00", invoice_no=""):
    conn.execute("INSERT OR IGNORE INTO parts(part_no, name, cost) VALUES (?,?,?)", (part, "測試", cost))
    conn.execute("INSERT INTO stock_batches(batch_no, part_no, supplier_name, invoice_no, created_at) VALUES (?,?,?,?,?)", (batch, part, "供應商", invoice_no, created))
    ids = []
    for i in range(n):
        cur = conn.execute("INSERT INTO stock_items(part_no, serial_no, status, batch_no, cost, created_at) VALUES (?,?,?,?,?,?)",
                           (part, "%s-%s-%d" % (batch, part, i), "in_stock", batch, cost, created))
        ids.append(cur.lastrowid)
    conn.commit()
    return ids


def _ship(conn, ids, note, quote, at):
    for i in ids:
        conn.execute("UPDATE stock_items SET status='shipped', shipping_note_no=?, quote_no=?, consumed_at=? WHERE id=?", (note, quote, at, i))
    conn.commit()


def test_provider_emits_stock_out_events_without_amounts(conn):
    p = _part()
    ids = _stock(conn, p, 4, 100, "PO-" + p)
    _ship(conn, ids[:2], "SN-" + p, "MQ-INV-1", "2176-03-10T10:00:00")
    conn.execute("UPDATE stock_items SET status='installed', quote_no='MQ-INV-2', consumed_at='2176-03-12T10:00:00' WHERE id=?", (ids[2],))
    conn.commit()
    res = G.gl_events("2176-03-01", "2176-03-31")
    out = {e["source_type"]: e for e in res["events"] if e["event_code"] == "E10" and e["stock_part_no"] == p}
    a, b = out["stock_issue_shipping"], out["stock_issue_claim"]
    assert (a["stock_qty"], a["case_no"], a["event_date"], a["mode"]) == (2, "MQ-INV-1", "2176-03-10", "stock") and "lines" not in a
    assert (b["stock_qty"], b["case_no"], b["source_key"]) == (1, "MQ-INV-2", "MQ-INV-2::%s::2176-03-12" % p)
    assert C.validate_event(a) == [] and C.validate_event(b) == []
    assert not [e for e in G.gl_events("2176-04-01", "2176-04-30")["events"] if e["event_code"] == "E10" and e["stock_part_no"] == p]


def test_provider_reports_void_items_instead_of_silently_skipping(conn):
    p = _part()
    ids = _stock(conn, p, 1, 100, "PO-" + p)
    conn.execute("UPDATE stock_items SET status='void', updated_at='2176-03-15T00:00:00' WHERE id=?", (ids[0],))
    conn.commit()
    assert "作廢" in G.gl_events("2176-03-01", "2176-03-31")["notice"]


# ── 引擎整合 ────────────────────────────────────────────────────────────

def _e10_rows(conn, p):
    return [dict(r) for r in conn.execute("SELECT * FROM gl_source_events WHERE event_code='E10' AND source_key LIKE ? ORDER BY rev", ("%" + p + "%",))]


def _voucher_lines(conn, vid):
    return [(r["account_code"], r["debit"], r["credit"], r["case_no"]) for r in conn.execute(
        "SELECT account_code, debit, credit, case_no FROM voucher_lines WHERE voucher_id=? ORDER BY line_no", (vid,))]


def test_engine_issue_uses_moving_average_and_dimensions(conn):
    p = _part()
    ids = _stock(conn, p, 4, 100, "PO-" + p)                              # 4 件、400
    _ship(conn, ids[:1], "SN-" + p, "MQ-INV-9", "2176-03-10T10:00:00")
    r = E.run(conn, "2176-03-01", "2176-03-31", "acc")
    conn.commit()
    (row,) = _e10_rows(conn, p)
    assert row["status"] == "drafted" and row["amount"] == 100 and r["sources"]["supply"] == "ok"
    lines = _voucher_lines(conn, row["voucher_id"])
    assert (lines[0][1], lines[0][3]) == (100, "MQ-INV-9") and lines[1][2] == 100                 # 借營業成本（依案件）貸存貨
    assert INV.state(conn, p) == (3, 300)
    again = E.run(conn, "2176-03-01", "2176-03-31", "acc")
    conn.commit()
    assert again["stats"]["created"] == 0 and again["stats"]["drift"] == 0 and INV.state(conn, p) == (3, 300)    # 冪等


def test_engine_blocks_when_receipt_period_was_not_run_then_recovers(conn):
    p = _part()
    ids = _stock(conn, p, 2, 100, "PO-" + p, created="2176-02-01T09:00:00")          # 進貨在 2 月
    _ship(conn, ids[:1], "SN-" + p, "MQ-INV-8", "2176-03-10T10:00:00")
    E.run(conn, "2176-03-01", "2176-03-31", "acc")                                    # 只跑 3 月：鏈上沒有貨
    conn.commit()
    (row,) = _e10_rows(conn, p)
    assert row["status"] == "blocked_inventory" and "不足" in row["note"] and row["voucher_id"] is None
    E.run(conn, "2176-02-01", "2176-02-28", "acc")                                    # 補跑 2 月 ⇒ 進貨入鏈
    E.run(conn, "2176-03-01", "2176-03-31", "acc")
    conn.commit()
    (row,) = _e10_rows(conn, p)
    assert row["status"] == "drafted" and row["amount"] == 100 and INV.state(conn, p) == (1, 100)


def test_engine_return_to_stock_reverses_the_chain_at_original_amount(conn):
    p = _part()
    ids = _stock(conn, p, 2, 100, "PO-" + p)
    _ship(conn, ids[:1], "SN-" + p, "MQ-INV-7", "2176-03-10T10:00:00")
    E.run(conn, "2176-03-01", "2176-03-31", "acc")
    conn.commit()
    assert INV.state(conn, p) == (1, 100)
    conn.execute("UPDATE stock_items SET status='in_stock', shipping_note_no='', quote_no='', consumed_at='' WHERE id=?", (ids[0],))      # 出貨單撤銷
    conn.commit()
    r = E.run(conn, "2176-03-01", "2176-03-31", "acc")
    conn.commit()
    (row,) = _e10_rows(conn, p)
    assert row["status"] == "orphan" and r["stats"]["orphans"] >= 1 and INV.state(conn, p) == (2, 200)


def test_engine_quantity_change_reissues_and_average_change_is_not_drift(conn):
    p = _part()
    ids = _stock(conn, p, 4, 100, "PO-" + p)
    _ship(conn, ids[:1], "SN-" + p, "MQ-INV-6", "2176-03-10T10:00:00")
    E.run(conn, "2176-03-01", "2176-03-31", "acc")
    conn.commit()
    _stock(conn, p, 4, 300, "PO2-" + p, created="2176-03-20T09:00:00")             # 之後進了更貴的貨：均價變了
    r = E.run(conn, "2176-03-01", "2176-03-31", "acc")
    conn.commit()
    assert r["stats"]["drift"] == 0 and [x["status"] for x in _e10_rows(conn, p)] == ["drafted"]          # 均價變動不重算已出庫成本
    _ship(conn, ids[1:2], "SN-" + p, "MQ-INV-6", "2176-03-10T11:00:00")               # 同一張出貨單多出一件 ⇒ 來源內容變了
    E.run(conn, "2176-03-01", "2176-03-31", "acc")
    conn.commit()
    rows = _e10_rows(conn, p)
    assert [x["status"] for x in rows] == ["superseded", "drafted"] and rows[1]["rev"] == 2
    q, v = INV.state(conn, p)
    assert q == 8 - 2 and v > 0 and rows[1]["amount"] > 0


def test_voiding_the_engine_draft_releases_the_chain(conn):
    p = _part()
    ids = _stock(conn, p, 2, 100, "PO-" + p)
    _ship(conn, ids[:1], "SN-" + p, "MQ-INV-5", "2176-03-10T10:00:00")
    E.run(conn, "2176-03-01", "2176-03-31", "acc")
    conn.commit()
    (row,) = _e10_rows(conn, p)
    conn.execute("UPDATE vouchers_all SET voided_at='2176-03-11T00:00:00' WHERE id=?", (row["voucher_id"],))
    conn.commit()
    E.sync_statuses(conn)
    conn.commit()
    (row,) = _e10_rows(conn, p)
    assert row["status"] == "rejected" and INV.state(conn, p) == (2, 200)             # 傳票被作廢 ⇒ 存貨鏈不留下沒有分錄的出庫
