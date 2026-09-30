# -*- coding: utf-8 -*-
"""費用單據（A2）入帳驗收（G2＋G4，2026-10-01）：W2 的案件額外支出表（kind／lines_json／pay_method／pay_account_code）經真實提供者
→ 總帳引擎（`apply_category_map`）→ 草稿 → 一鍵確認到過帳 → 試算表。期望值全是**手算的字面數字**，不是從程式讀回來的；
每個斷言印『期望／實際』，全部跑完才判定（比照 test_ledger_acceptance_2026_10_01.py）。

情境（2196 年 1 月；類別對應＝總帳會計在設定頁設的：meal→6134、fare→6112；misc、eqp 沒設對應）
  R1 差旅（無案件）  明細 meal 600＋fare 400＝1,000；01-10 核准、01-20 匯款
     E11 借 6134 600、6112 400／貸 應付 2171 1,000；E11b 借 2171 1,000／貸 銀行 1113 1,000
  R2 差旅（案件 MQ-G2-1）明細 meal 300＋misc（沒對應）200＝500；01-12 核准、未付
     E11 借 6134 300、**專案成本 5811 200**（沒對應＋有案件）／貸 2171 500
  R3 零用金（無案件）fare 250；01-15 核准、01-16 付款（pay_method＝petty_cash）
     E11 借 6112 250／貸 2171 250；E11b 借 2171 250／貸 **零用金 1112** 250
  R4 採購單（無案件）eqp（沒對應）5,000；01-18 核准（認列應付）、01-28 付款、出納指定付款科目 1111
     E11 借 **其他營業費用 6134（無案件絕不用專案成本）** 5,000／貸 2171 5,000；E11b 借 2171 5,000／貸 **1111** 5,000
  R5 請購單 9,999（01-19 核准）：不是金流單據 ⇒ **沒有任何事件**
  R6 舊版額外支出（kind＝''、案件 MQ-G2-1）1,050；01-11 發票、核准：E11 借 5811 1,050／貸 2171 1,050（與 A2 之前相同：單一借方）
  R7 差旅（無案件）明細加總 700≠單據金額 800（不該發生）⇒ 退回單一借方 6134 800／貸 2171 800；01-20 核准
手算（期間 2196-01-01～01-31）：
  6134 借 600＋300＋5,000＋800＝6,700；6112 借 400＋250＝650；5811 借 200＋1,050＝1,250
  2171 貸 1,000＋500＋250＋5,000＋1,050＋800＝8,600、借 1,000＋250＋5,000＝6,250
  1113 貸 1,000；1112 貸 250；1111 貸 5,000
  借方合計 6,700＋650＋1,250＋6,250＝14,850＝貸方合計 8,600＋1,000＋250＋5,000
  事件：草稿 E11×6（R1,R2,R3,R4,R6,R7）＋E11b×3（R1,R3,R4）＝9 張；請購單 0 張
"""
import json
from datetime import datetime

import pytest

import db
from modules.accounting.ledger import category_map as CM
from modules.accounting.ledger import features as F
from modules.accounting.ledger import periods as P
from modules.accounting.ledger import reports as RP
from modules.accounting.ledger import roles as ROLES

Y = 2196
START, END = "%d-01-01" % Y, "%d-01-31" % Y

EXPECTED_TB = {"1111": (0, 5000), "1112": (0, 250), "1113": (0, 1000), "2171": (6250, 8600),
               "5811": (1250, 0), "6112": (650, 0), "6134": (6700, 0)}
EXPECTED_TOTAL = 14850


class Table:
    def __init__(self):
        self.bad = []

    def check(self, name, expected, actual):
        ok = expected == actual
        line = "%s  %-58s 期望=%-14r 實際=%r" % ("PASS" if ok else "FAIL", name, expected, actual)
        print(line)
        if not ok:
            self.bad.append(line)

    def verdict(self):
        assert not self.bad, "\n驗收不符 %d 項（缺陷清單，不可改期望值遷就）：\n  %s\n" % (len(self.bad), "\n  ".join(self.bad))


def _login(client, make_user):
    u, p = make_user(username="xf_sup%d" % id(client), role="superadmin", modules=("cashier", "finance"))
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _have_a2_columns(conn):
    return {"kind", "lines_json", "pay_method", "pay_account_code"} <= {r[1] for r in conn.execute("PRAGMA table_info(case_extra_expenses)")}


def _row(conn, *, kind, quote_no, lines, total, approved, paid="", pay_method="", pay_account="", invoice_date="", desc="x"):
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO case_extra_expenses(quote_no, category, description, total_cost, expense_date, doc_no, status, approval_json, invoice_date, paid_date,"
        " remit_actual, remit_fee, remit_review, created_at, kind, lines_json, pay_method, pay_account_code)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (quote_no, "其他", desc, total, approved, "D-%s" % desc, "已核准", json.dumps({"steps": [{"approvedAt": approved}]}), invoice_date, paid,
         None, 0, "", now, kind, json.dumps(lines, ensure_ascii=False), pay_method, pay_account))


def test_typed_expense_forms_post_to_the_hand_computed_accounts(client, make_user):
    T = Table()
    sup = _login(client, make_user)
    conn = db.get_db()
    conn.isolation_level = None
    try:
        if not _have_a2_columns(conn):
            pytest.skip("案件費用單據欄位（case migration 0003）不在這個安裝包")
        ROLES.ensure_meta(conn)
        ROLES.ensure_default_roles(conn)
        P.create_year(conn, Y, "xf")
        F.set_flag(conn, "engine_drafts", True)
        for code, name in (("meal", "餐費"), ("fare", "交通")):
            CM.upsert_category(conn, code, name, "taxable", 1)
        CM.upsert_category(conn, "misc", "雜項", "", 2)
        CM.upsert_category(conn, "eqp", "設備", "", 3)
        CM.upsert_map(conn, "meal", account_code="6134")
        CM.upsert_map(conn, "fare", account_code="6112")
        now = datetime.now().isoformat()
        conn.execute("INSERT INTO quotations (quote_no, status, total, pretax, data_json, created_at, updated_at, customer_name, deal_tag) VALUES (?,?,?,?,?,?,?,?,?)",
                     ("MQ-G2-1", "已成案", 10500, 10000, json.dumps({"quoteNo": "MQ-G2-1", "dealTag": "已成案"}), now, now, "甲公司", "已成案"))
        J = "%d-01-" % Y
        _row(conn, kind="travel", quote_no="", lines=[{"categoryCode": "meal", "amount": 600}, {"categoryCode": "fare", "amount": 400}], total=1000,
             approved=J + "10", paid=J + "20", pay_method="transfer", desc="R1")
        _row(conn, kind="travel", quote_no="MQ-G2-1", lines=[{"categoryCode": "meal", "amount": 300}, {"categoryCode": "misc", "amount": 200}], total=500,
             approved=J + "12", desc="R2")
        _row(conn, kind="petty_cash", quote_no="", lines=[{"categoryCode": "fare", "amount": 250}], total=250, approved=J + "15", paid=J + "16",
             pay_method="petty_cash", desc="R3")
        _row(conn, kind="purchase_order", quote_no="", lines=[{"categoryCode": "eqp", "amount": 5000}], total=5000, approved=J + "18", paid=J + "28",
             pay_method="transfer", pay_account="1111", desc="R4")
        _row(conn, kind="purchase_req", quote_no="", lines=[{"categoryCode": "eqp", "amount": 9999}], total=9999, approved=J + "19", desc="R5")
        _row(conn, kind="", quote_no="MQ-G2-1", lines=[], total=1050, approved=J + "11", invoice_date=J + "11", desc="R6")
        _row(conn, kind="travel", quote_no="", lines=[{"categoryCode": "meal", "amount": 700}], total=800, approved=J + "20", desc="R7")
        conn.commit()

        run = client.post("/api/ledger/engine/run", headers=sup, json={"start": START, "end": END})
        T.check("引擎執行（HTTP）", 200, run.status_code)
        T.check("case 來源讀取成功", "ok", (run.json().get("sources") or {}).get("case"))
        evs = [dict(r) for r in conn.execute("SELECT event_code, source_key, status, voucher_id FROM gl_source_events"
                                             " WHERE event_date BETWEEN ? AND ? AND source_type LIKE 'case_extra_expense%'", (START, END))]
        T.check("事件：E11×6、E11b×3、草稿 9", (6, 3, 9), (sum(1 for e in evs if e["event_code"] == "E11"), sum(1 for e in evs if e["event_code"] == "E11b"),
                                                     sum(1 for e in evs if e["status"] == "drafted")))
        r5 = str(conn.execute("SELECT id FROM case_extra_expenses WHERE description='R5'").fetchone()[0])
        T.check("請購單（R5）沒有任何事件", 0, conn.execute("SELECT COUNT(*) FROM gl_source_events WHERE source_key=?", (r5,)).fetchone()[0])
        T.check("被擋／缺科目", 0, sum(1 for e in evs if str(e["status"]).startswith("blocked")))

        ids = [e["voucher_id"] for e in evs if e["status"] == "drafted"]
        b = client.post("/api/ledger/engine/batch", headers=sup, json={"voucher_ids": ids, "action": "all"})
        T.check("一鍵確認到過帳（HTTP）", 200, b.status_code)
        T.check("9 張全部成功", 9, sum(1 for x in (b.json().get("results") or []) if x.get("ok")) if b.status_code == 200 else -1)

        def lines_of(desc, code):
            eid = str(conn.execute("SELECT id FROM case_extra_expenses WHERE description=?", (desc,)).fetchone()[0])
            r = conn.execute("SELECT voucher_id FROM gl_source_events WHERE source_key=? AND event_code=? ORDER BY rev DESC LIMIT 1", (eid, code)).fetchone()
            return sorted((l["account_code"], l["debit"], l["credit"]) for l in conn.execute("SELECT account_code, debit, credit FROM voucher_lines WHERE voucher_id=?", (r[0],)))

        T.check("R1 E11", [("2171", 0, 1000), ("6112", 400, 0), ("6134", 600, 0)], lines_of("R1", "E11"))
        T.check("R1 E11b（銀行）", [("1113", 0, 1000), ("2171", 1000, 0)], lines_of("R1", "E11b"))
        T.check("R2 E11（沒對應＋有案件＝專案成本）", [("2171", 0, 500), ("5811", 200, 0), ("6134", 300, 0)], lines_of("R2", "E11"))
        T.check("R3 E11", [("2171", 0, 250), ("6112", 250, 0)], lines_of("R3", "E11"))
        T.check("R3 E11b（零用金）", [("1112", 0, 250), ("2171", 250, 0)], lines_of("R3", "E11b"))
        T.check("R4 E11（無案件、沒對應＝其他營業費用，不是專案成本）", [("2171", 0, 5000), ("6134", 5000, 0)], lines_of("R4", "E11"))
        T.check("R4 E11b（出納指定科目 1111）", [("1111", 0, 5000), ("2171", 5000, 0)], lines_of("R4", "E11b"))
        T.check("R6 舊版 E11（單一借方，與 A2 之前相同）", [("2171", 0, 1050), ("5811", 1050, 0)], lines_of("R6", "E11"))
        T.check("R7 明細對不上金額 ⇒ 單一借方", [("2171", 0, 800), ("6134", 800, 0)], lines_of("R7", "E11"))

        tbr = RP.trial_balance(conn, START, END)
        tb = {r["code"]: r for r in tbr["rows"] if r["code"]}
        T.check("試算表科目集合", sorted(EXPECTED_TB), sorted(tb))
        for code, (d, c) in sorted(EXPECTED_TB.items()):
            T.check("試算表 %s 借／貸" % code, (d, c), (tb[code]["period_debit"], tb[code]["period_credit"]) if code in tb else None)
        T.check("借方合計＝貸方合計＝14,850", (EXPECTED_TOTAL, EXPECTED_TOTAL), (tbr["totals"]["period_debit"], tbr["totals"]["period_credit"]))
    finally:
        conn.close()
    T.verdict()
