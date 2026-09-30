# -*- coding: utf-8 -*-
"""總帳端到端驗收（2026-10-01，使用者問：新的財務功能正常嗎？頁面與資料的連結有證據嗎？）。

這一支**不驗程式的內部邏輯**，驗的是：在一份接近真實的多來源資料上，整條路（來源資料 → 引擎草稿 → 送審 → 最高管理者核准 → 過帳 →
試算表／總帳／資產負債表／損益表／現金流量表／營業稅 401／扣繳清單）出來的**每一個數字**，是否等於**先用紙筆從來源資料算出來的期望值**。

🔴 期望值全部是下面寫死的字面數字，依本檔的『推導』一節逐筆手算；**不是**從被測程式讀回來的。每個斷言都印出「期望／實際」，
   全部斷言跑完才一起判定（不是遇到第一個就停）：不符的項目就是一份缺陷清單，**不可以為了讓它綠而改期望值**。

情境（2195 年 3 月；會計年度 2195 整年、12 期；全部走真實的來源模組提供者與 API，不用 fake 事件）
  期初  2195-01-01  借 銀行 1113 500,000／貸 股本 3111 500,000
  A 案件收款  報價單 MQ-ACC-1（未稅 10,000＋稅 500）：發票 03-10；03-15 收款實收 10,485、客戶內扣手續費 15
      E01 借 應收 1191 10,500／貸 銷貨收入 4111 10,000、銷項稅額 2204 500
      E03 借 銀行 10,485、手續費 7243 15／貸 應收 10,500
  B 承攬派工 A（未稅 20,000、稅 5%）：發票 03-12，匯款 03-20 21,000
      E04 借 專案成本 5811 20,000、進項稅額 1268 1,000／貸 應付 2171 21,000；E05 借 應付 21,000／貸 銀行 21,000
  C 承攬派工 B（未稅 10,000、稅 5%）＋個人外包（已關聯勞報單 ACC-SLIP-1，5,273）：發票 03-14，匯款 03-22 合計 15,773
      E04 借 5811 10,000、1268 500／貸 2171 10,500；E05 借 應付 10,500、其他應付 2206 5,273／貸 銀行 15,773（個人部分付的是勞報單的應付）
  D 勞報單 ACC-SLIP-1（經匯款單付款）：給付 6,000、所得稅 600、二代健保 127、實付 5,273（03-16）
      E06 借 勞務費用 6133 6,000／貸 代扣 2252 600＋127、其他應付 2206 5,273（不產生 E06b：付款已在 C 的匯款單）
  E 勞報單 ACC-SLIP-2（直接付款）：給付 10,000、所得稅 1,000、二代健保 211、實付 8,789（03-18），03-25 付款
      E06 借 6133 10,000／貸 2252 1,000＋211、2206 8,789；E06b 借 2206 8,789／貸 銀行 8,789
  F 獎金（既有傳票登記為 native）：03-22 核准應付 借 薪資 6111 5,000／貸 應付薪資 2191 5,000；03-28 發放 借 2191 5,000／貸 銀行 5,000
  G 案件額外支出 1,050（03-11 發票、已核准、未拆稅、未付款）：E11 借 5811 1,050／貸 應付 1,050
  H 叫料 2,100（03-05 發票、03-20 付款）：E12 借 5811 2,100／貸 應付；E12b 借 應付 2,100／貸 銀行 2,100
  I 進貨 4 件 @100（03-05 入庫、03-26 付款，無發票）、03-20 出貨 1 件給 MQ-ACC-1
      E08 借 存貨 1231 400／貸 應付 400；E09 借 應付 400／貸 銀行 400；E10 借 營業成本 5111 100／貸 存貨 100（移動加權平均：100）
  （固定資產 C6 尚未合入主線、自訂模組入帳 C7 尚未出貨 ⇒ 不在本情境；見 docs/platform/LEDGER-ACCEPTANCE.md）

推導（每個科目的借方／貸方合計，手算）見 EXPECTED_TB；合計借方＝貸方＝630,212。
  期末 銀行 1113 ＝ 500,000＋10,485 − (21,000＋15,773＋8,789＋5,000＋400＋2,100) ＝ 457,423
  應付 2171：貸 21,000＋10,500＋400＋1,050＋2,100 ＝ 35,050、借 21,000＋10,500＋400＋2,100 ＝ 34,000 ⇒ 貸方餘額 1,050（未付的額外支出）
  損益：收入 10,000；成本費用 COGS 100＋專案成本 (20,000＋10,000＋1,050＋2,100)＝33,150＋薪資 5,000＋勞務 16,000＋手續費 15 ⇒ 淨損 −44,265
  資產負債表：資產 457,423＋存貨 300＋進項稅額 1,500 ＝ 459,223；負債 應付 1,050＋銷項稅額 500＋代扣 1,938 ＝ 3,488；權益 500,000−44,265 ＝ 455,735；3,488＋455,735＝459,223
  現金流量（2195-01-01～03-31）：現金淨變動＝期末現金 457,423
  營業稅 401（第 2 期 3～4 月）：銷項 500、進項 1,500 ⇒ 小計 1,500、應實繳 0、留抵 1,000
  扣繳（2195-03）：所得稅 600＋1,000＝1,600、二代健保 127＋211＝338，合計 1,938 ＝ 科目 2252 當月貸方
"""
import json
from datetime import datetime

import pytest

import db
from core import registry
from modules.accounting.ledger import features as F
from modules.accounting.ledger import periods as P
from modules.accounting.ledger import reports as RP
from modules.accounting.ledger import roles as ROLES
from modules.accounting.ledger import statements as ST
from modules.accounting.ledger import withholding as WH

Y = 2195
START, END, MAR1, MAR31 = "%d-01-01" % Y, "%d-03-31" % Y, "%d-03-01" % Y, "%d-03-31" % Y

#: 每個科目（借方合計, 貸方合計）——手算，見模組說明的情境與推導
EXPECTED_TB = {
    "1113": (510485, 53062), "1191": (10500, 10500), "1231": (400, 100), "1268": (1500, 0),
    "2171": (34000, 35050), "2191": (5000, 5000), "2204": (0, 500), "2206": (14062, 14062), "2252": (0, 1938),
    "3111": (0, 500000), "4111": (0, 10000),
    "5111": (100, 0), "5811": (33150, 0), "6111": (5000, 0), "6133": (16000, 0), "7243": (15, 0),
}
EXPECTED_TOTAL = 630212
EXPECTED_CLOSING_NET = {"1113": 457423, "1231": 300, "1268": 1500, "2171": -1050, "2204": -500, "2252": -1938, "3111": -500000, "4111": -10000,
                        "5111": 100, "5811": 33150, "6111": 5000, "6133": 16000, "7243": 15, "1191": 0, "2191": 0, "2206": 0}


class Table:
    """每個斷言印『期望／實際』；全部跑完才判定（不是遇到第一個就停）。"""

    def __init__(self):
        self.rows, self.bad = [], []

    def check(self, name, expected, actual):
        ok = expected == actual
        line = "%s  %-58s 期望=%-14r 實際=%r" % ("PASS" if ok else "FAIL", name, expected, actual)
        print(line)
        self.rows.append(line)
        if not ok:
            self.bad.append(line)
        return ok

    def verdict(self):
        assert not self.bad, "\n驗收不符 %d 項（缺陷清單，不可改期望值遷就）：\n  %s\n" % (len(self.bad), "\n  ".join(self.bad))


# ── 來源資料（真實資料表，經真實提供者）──────────────────────────────────────

def _login(client, make_user, name, role="superadmin", modules=("cashier", "finance")):
    kw = {"role": role}
    if role != "superadmin":
        kw["modules"] = list(modules)
    u, p = make_user(username="%s%d" % (name, id(client)), **kw)
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _seed_case(conn):
    qn = "MQ-ACC-1"
    data = {"quoteNo": qn, "dealTag": "已成案", "caseRecord": {
        "payment": {"items": [{"id": "p1", "type": "全額", "amount": 10500, "invoiceNo": "AB12345678", "invoiceDate": "%d-03-10" % Y,
                               "received": True, "receivedAt": "%d-03-15" % Y, "actualAmount": 10485, "feeAmount": 15, "bankAccountCode": "1113"}]},
        "materialOrders": [{"itemId": "m1", "itemName": "線材", "totalPrice": 2100, "invoiceDate": "%d-03-05" % Y, "paidStatus": "paid",
                            "paidDate": "%d-03-20" % Y, "paidAmount": 2100}]}}
    now = datetime.now().isoformat()
    conn.execute("INSERT INTO quotations (quote_no, status, total, pretax, data_json, created_at, updated_at, customer_name, deal_tag) VALUES (?,?,?,?,?,?,?,?,?)",
                 (qn, "已成案", 10500, 10000, json.dumps(data, ensure_ascii=False), now, now, "甲公司", "已成案"))
    conn.execute("INSERT INTO case_extra_expenses(quote_no, category, description, total_cost, expense_date, doc_no, status, approval_json, invoice_date, paid_date,"
                 " remit_actual, remit_fee, remit_review, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (qn, "材料", "額外支出", 1050, "%d-03-11" % Y, "D-ACC", "已核准", json.dumps({"steps": [{"approvedAt": "%d-03-12" % Y}]}), "%d-03-11" % Y, "", None, 0, "", now))
    return qn


def _seed_contractors(conn, qn):
    def vendor(n):
        return conn.execute("INSERT INTO vendor_contractors(name, tax_id, data_json, active) VALUES (?,?,?,1)", ("乙工程行%d" % n, "8765000%d" % n, "{}")).lastrowid

    def dispatch(total, inv_no, inv_date):
        return conn.execute("INSERT INTO contractor_dispatches(quote_no, vendor_id, dispatch_date, total_amount, tax_rate, status, invoice_no, invoice_date)"
                            " VALUES (?,?,?,?,?,?,?,?)", (qn, vendor(total), "%d-03-01" % Y, total, 0.05, "accepted", inv_no, inv_date)).lastrowid

    def voucher(no, did, grand, paid, people=None, personnel_total=0):
        snap = {"vendorName": "乙工程行", "vendorTaxId": "87650001", "grandTotal": grand, "personnelTotal": personnel_total, "personnel": people or []}
        conn.execute("INSERT INTO contractor_payment_vouchers(voucher_no, dispatch_id, quote_no, status, snapshot_json, is_paid, paid_at, paid_bank_account_code,"
                     " remit_actual, remit_fee, remit_review) VALUES (?,?,?,?,?,1,?,?,?,?,?)",
                     (no, did, qn, "已核可", json.dumps(snap, ensure_ascii=False), paid, "1113", None, 0, ""))
    a = dispatch(20000, "ZZ00000011", "%d-03-12" % Y)
    voucher("PV-ACC-A", a, 21000, "%d-03-20" % Y)
    b = dispatch(10000, "ZZ00000012", "%d-03-14" % Y)
    voucher("PV-ACC-B", b, 15773, "%d-03-22" % Y, people=[{"name": "王小明", "amount": 5273, "payslipNo": "ACC-SLIP-1"}], personnel_total=5273)
    return a


def _seed_payslips(conn):
    def slip(no, gross, tax, nhi, net, slip_date, status, pay, data):
        cid = conn.execute("INSERT INTO contractors(name, id_number) VALUES (?,?)", ("王小明", "A123456789")).lastrowid
        conn.execute("INSERT INTO payslips(slip_no, contractor_id, contractor_name, income_type, gross_amount, tax_withheld, nhi_supplement, net_amount,"
                     " slip_date, status, signed_at, payment_date, data_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (no, cid, "王小明", "9A", gross, tax, nhi, net, slip_date, status, slip_date + "T09:00:00", pay, json.dumps(data)))
    slip("ACC-SLIP-1", 6000, 600, 127, 5273, "%d-03-16" % Y, "已付款", "%d-03-22" % Y, {"paid_via_remit": True})
    slip("ACC-SLIP-2", 10000, 1000, 211, 8789, "%d-03-18" % Y, "已付款", "%d-03-25" % Y, {})


def _seed_stock(conn, qn):
    conn.execute("INSERT OR IGNORE INTO parts(part_no, name, cost) VALUES ('ACC-P1', '驗收料', 100)")
    conn.execute("INSERT INTO stock_batches(batch_no, part_no, supplier_name, invoice_no, is_paid, paid_at, paid_bank_account_code, created_at) VALUES (?,?,?,?,1,?,?,?)",
                 ("ACC-PO-1", "ACC-P1", "供應商", "", "%d-03-26" % Y, "1113", "%d-03-05T09:00:00" % Y))
    ids = [conn.execute("INSERT INTO stock_items(part_no, serial_no, status, batch_no, cost, created_at) VALUES (?,?,?,?,?,?)",
                        ("ACC-P1", "ACC-SN-%d" % i, "in_stock", "ACC-PO-1", 100, "%d-03-05T09:00:00" % Y)).lastrowid for i in range(4)]
    conn.execute("UPDATE stock_items SET status='shipped', shipping_note_no='SN-ACC', quote_no=?, consumed_at=? WHERE id=?", (qn, "%d-03-20T10:00:00" % Y, ids[0]))


def _seed_bonus(conn, client, sup):
    mk = registry.single_provider("voucher.draft")
    va = mk(conn, voucher_date="%d-03-22" % Y, summary="獎金分潤核准", created_by="t", now="%d-03-22T00:00:00" % Y, origin="bonus_accrual",
            lines=[{"account_code": "6111", "summary": "x", "debit": 5000, "credit": 0}, {"account_code": "2191", "summary": "x", "debit": 0, "credit": 5000}])["id"]
    vp = mk(conn, voucher_date="%d-03-28" % Y, summary="獎金發放", created_by="t", now="%d-03-28T00:00:00" % Y, origin="bonus_payment",
            lines=[{"account_code": "2191", "summary": "x", "debit": 5000, "credit": 0}, {"account_code": "1113", "summary": "x", "debit": 0, "credit": 5000}])["id"]
    now = datetime.now().isoformat()
    conn.execute("INSERT INTO bonus_case_awards(quote_no, status, net_profit, rate_bp, split_json, pool_amount, created_by, created_at, updated_by, updated_at,"
                 " accrual_voucher_id, payment_voucher_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", ("MQ-ACC-1", "已發放", "1000", 1000, "{}", 100, "t", now, "t", now, va, vp))
    conn.commit()
    for vid in (va, vp):
        for act in ("submit", "approve", "approve", "post"):
            r = client.post("/api/vouchers/%d/%s" % (vid, act), headers=sup, json={})
            assert r.status_code == 200, (act, r.text)


def _tb(conn, include_drafts=False):
    rows = RP.trial_balance(conn, START, END, include_drafts=include_drafts)["rows"]
    return {r["code"]: r for r in rows if r["code"]}


def test_ledger_acceptance_end_to_end(client, make_user):
    T = Table()
    sup = _login(client, make_user, "acc_sup")
    conn = db.get_db()
    try:
        ROLES.ensure_meta(conn)
        ROLES.ensure_default_roles(conn)
        P.create_year(conn, Y, "acc")
        F.set_flag(conn, "engine_drafts", True)
        F.set_flag(conn, "tax401", True)
        F.set_flag(conn, "withholding", True)
        qn = _seed_case(conn)
        dispatch_a = _seed_contractors(conn, qn)
        _seed_payslips(conn)
        _seed_stock(conn, qn)
        conn.commit()

        # ── 1 期初餘額（平衡）→ 草稿 → 送審 → 最高管理者核准 → 過帳 ──
        r = client.post("/api/ledger/opening", headers=sup, json={"year": Y, "opening_date": START, "rows": [
            {"account_code": "1113", "debit": 500000, "credit": 0}, {"account_code": "3111", "debit": 0, "credit": 500000}]})
        T.check("期初餘額傳票建立（HTTP）", 200, r.status_code)
        ovid = r.json()["voucher_id"]
        for act in ("submit", "approve", "approve", "post"):
            T.check("期初傳票 %s（HTTP）" % act, 200, client.post("/api/vouchers/%d/%s" % (ovid, act), headers=sup, json={}).status_code)
        _seed_bonus(conn, client, sup)

        # ── 2 引擎：各來源 → 草稿 ──
        run = client.post("/api/ledger/engine/run", headers=sup, json={"start": MAR1, "end": MAR31})
        T.check("引擎執行（HTTP）", 200, run.status_code)
        ev = {(r["status"], r["event_code"]) for r in conn.execute("SELECT status, event_code FROM gl_source_events WHERE event_date BETWEEN ? AND ?", (MAR1, MAR31))}
        counts = {}
        for r in conn.execute("SELECT status, COUNT(*) n FROM gl_source_events WHERE event_date BETWEEN ? AND ? GROUP BY status", (MAR1, MAR31)):
            counts[r["status"]] = r["n"]
        T.check("事件：草稿 15（E01,E03,E04×2,E05×2,E06×2,E06b,E08,E09,E10,E11,E12,E12b）", 15, counts.get("drafted", 0))
        T.check("事件：native 2（獎金核准／發放既有傳票）", 2, counts.get("native", 0))
        T.check("事件：被擋／缺科目／在庫不足", 0, sum(counts.get(k, 0) for k in ("blocked_closed", "blocked_no_account", "blocked_inventory")))
        T.check("草稿傳票不計入已過帳試算表（借方合計仍只有期初）", 500000, _tb(conn)["1113"]["period_debit"] + 0)

        # ── 3 整批送審 → 核准（含最終關卡＝最高管理者）→ 過帳 ──
        ids = [r[0] for r in conn.execute("SELECT voucher_id FROM gl_source_events WHERE status='drafted' AND event_date BETWEEN ? AND ?", (MAR1, MAR31))]
        b = client.post("/api/ledger/engine/batch", headers=sup, json={"voucher_ids": ids, "action": "all"})
        T.check("一鍵確認到過帳（HTTP）", 200, b.status_code)
        res = b.json()["results"] if b.status_code == 200 else []
        T.check("一鍵確認：15 張全部成功", 15, sum(1 for x in res if x.get("ok")))
        T.check("傳票狀態：15 張全部已過帳", 15, conn.execute("SELECT COUNT(*) FROM vouchers_all WHERE id IN (%s) AND status='已過帳'" % ",".join(map(str, ids))).fetchone()[0])

        # ── 4 試算表：逐科目借貸合計＝手算；總計借＝貸 ──
        tb = RP.trial_balance(conn, START, END)
        T.check("試算表 總借方", EXPECTED_TOTAL, tb["totals"]["period_debit"])
        T.check("試算表 總貸方", EXPECTED_TOTAL, tb["totals"]["period_credit"])
        rows = _tb(conn)
        for code, (d, c) in sorted(EXPECTED_TB.items()):
            r = rows.get(code) or {"period_debit": 0, "period_credit": 0}
            T.check("試算表 %s 借方合計" % code, d, r["period_debit"])
            T.check("試算表 %s 貸方合計" % code, c, r["period_credit"])
        T.check("試算表 沒有多出手算表以外的科目", sorted(EXPECTED_TB), sorted(c for c, r in rows.items() if r["period_debit"] or r["period_credit"]))
        for code, net in sorted(EXPECTED_CLOSING_NET.items()):
            r = rows.get(code) or {"closing_debit": 0, "closing_credit": 0}
            T.check("試算表 %s 期末餘額（借為正）" % code, net, r["closing_debit"] - r["closing_credit"])

        # ── 5 總帳（分類帳）：逐筆餘額、期末 ──
        gl = RP.general_ledger(conn, "1113", START, END)
        T.check("總帳 1113 期末餘額", 457423, gl["closing"])
        T.check("總帳 1113 期間借方／貸方", (510485, 53062), (gl["period_debit"], gl["period_credit"]))
        T.check("總帳 1113 最後一筆的累計餘額＝期末", 457423, gl["lines"][-1]["balance"])
        gl2 = RP.general_ledger(conn, "2171", START, END)
        T.check("總帳 2171 期末（貸方 1,050＝未付的額外支出）", -1050, gl2["closing"])

        # ── 6 資產負債表／損益表／現金流量表 ──
        bs = ST.balance_sheet(conn, END)
        T.check("資產負債表 資產", 459223, bs["totals"]["assets"])
        T.check("資產負債表 負債", 3488, bs["totals"]["liabilities"])
        T.check("資產負債表 權益（股本 500,000＋本期損益 −44,265）", 455735, bs["totals"]["equity"])
        T.check("資產負債表 A＝L＋E", True, bs["totals"]["assets"] == bs["totals"]["liabilities"] + bs["totals"]["equity"] and bs["checks"]["balanced"])
        inc = ST.income_statement(conn, START, END)
        T.check("損益表 本期淨利（淨損）", -44265, inc["net_income"]["period"])
        T.check("損益表 年初至今淨利", -44265, inc["net_income"]["ytd"])
        T.check("損益表 與試算表相符", True, inc["checks"]["balanced"])
        from modules.accounting.ledger import cashflow as CF
        cf = CF.cash_flow_statement(conn, START, END, False)
        T.check("現金流量表 現金淨變動＝銀行科目變動", 457423, cf["cash_change"])
        T.check("現金流量表 期末現金", 457423, cf["cash_closing"])
        T.check("現金流量表 三大活動合計＝現金淨變動", 457423, cf["net_change"])
        T.check("現金流量表 自檢平衡", True, cf["checks"].get("balanced"))

        # ── 7 營業稅 401（第 2 期 3～4 月）──
        t = client.get("/api/ledger/tax401?year=%d&period=2" % Y, headers=sup)
        T.check("401 查詢（HTTP）", 200, t.status_code)
        if t.status_code == 200:
            calc = t.json()["calc"]
            T.check("401 101 銷項稅額合計", 500, calc["101"])
            T.check("401 107 得扣抵進項稅額合計", 1500, calc["107"])
            T.check("401 110 小計（含上期留抵 0）", 1500, calc["110"])
            T.check("401 111 本期應實繳", 0, calc["111"])
            T.check("401 112 本期申報留抵", 1000, calc["112"])
            T.check("401 銷售額 21（應稅）", 10000, calc["21"])
            T.check("401 與發票／帳上對帳全部相符", [], [c["key"] for c in t.json()["checks"] if c["ok"] is False])

        # ── 8 扣繳清單（2195-03）──
        w = WH.report(conn, "%d-03" % Y, today="%d-04-01" % Y)
        g = {x["kind"]: x for x in w["groups"]}
        T.check("扣繳 所得稅 筆數／合計", (2, 1600), (g["income_tax"]["count"], g["income_tax"]["total"]))
        T.check("扣繳 二代健保 筆數／合計", (2, 338), (g["nhi"]["count"], g["nhi"]["total"]))
        T.check("扣繳 清單合計＝代扣科目 2252 當月貸方", (1938, 1938, True), (w["checks"][0]["left"], w["checks"][0]["right"], w["checks"][0]["ok"]))

        # ── 9 與來源資料獨立對照（來源端的數字，不經總帳）──
        T.check("收入：報價單未稅 10,000＝總帳 4111", 10000, rows["4111"]["period_credit"])
        T.check("銷項稅額：報價單 500＝總帳 2204", 500, rows["2204"]["period_credit"])
        T.check("代扣：勞報單 (600+127+1000+211)＝總帳 2252", 1938, rows["2252"]["period_credit"])
        T.check("承攬成本：派工 20,000＋10,000＝專案成本裡的派工部分（5811 另含額外支出 1,050＋叫料 2,100）", 30000 + 1050 + 2100, rows["5811"]["period_debit"])
        T.check("存貨：進 4 件×100 − 出 1 件×100＝300", 300, rows["1231"]["period_debit"] - rows["1231"]["period_credit"])

        # ── 10 冪等：再跑一次引擎，不新增草稿、帳不變 ──
        n_v = conn.execute("SELECT COUNT(*) FROM vouchers_all").fetchone()[0]
        again = client.post("/api/ledger/engine/run", headers=sup, json={"start": MAR1, "end": MAR31}).json()
        T.check("冪等：再跑引擎 新增草稿 0", 0, again["stats"]["created"])
        T.check("冪等：來源變動／消失 0", (0, 0), (again["stats"]["drift"], again["stats"]["orphans"]))
        T.check("冪等：傳票總數不變", n_v, conn.execute("SELECT COUNT(*) FROM vouchers_all").fetchone()[0])
        T.check("冪等：試算表總借方不變", EXPECTED_TOTAL, RP.trial_balance(conn, START, END)["totals"]["period_debit"])

        # ── 11 已過帳後來源被改：舊傳票不動，drift＋反向草稿＋新內容草稿 ──
        conn.execute("UPDATE contractor_dispatches SET total_amount=22000 WHERE id=?", (dispatch_a,))        # 派工 A 未稅 20,000→22,000（稅 1,100、應付 23,100）
        conn.commit()
        r2 = client.post("/api/ledger/engine/run", headers=sup, json={"start": MAR1, "end": MAR31}).json()
        T.check("來源改後 偵測到變動（drift）", 1, r2["stats"]["drift"])
        rows_e04 = conn.execute("SELECT status, rev FROM gl_source_events WHERE source_type='contractor_dispatch' AND source_key=? ORDER BY rev", (str(dispatch_a),)).fetchall()
        T.check("來源改後 E04 舊版標 drift、新版草稿", [("drift", 1), ("drafted", 2)], [(x["status"], x["rev"]) for x in rows_e04])
        orig_no = conn.execute("SELECT v.voucher_no FROM gl_source_events e JOIN vouchers_all v ON v.id=e.voucher_id WHERE e.source_type='contractor_dispatch' AND e.source_key=? AND e.rev=1",
                               (str(dispatch_a),)).fetchone()[0]
        T.check("來源改後 產生 1 張反向草稿（kind=reversal、指向原傳票）", 1, conn.execute("SELECT COUNT(*) FROM vouchers_all WHERE kind='reversal' AND status='草稿' AND reverses_no=?", (orig_no,)).fetchone()[0])
        T.check("來源改後 已過帳的帳不變（草稿不計入）", EXPECTED_TOTAL, RP.trial_balance(conn, START, END)["totals"]["period_debit"])
        T.check("來源改後 含草稿的試算表仍借貸平衡", True, RP.trial_balance(conn, START, END, include_drafts=True)["balanced"])

        # ── 12 結帳後過帳：被擋 ──
        new_draft = conn.execute("SELECT voucher_id FROM gl_source_events WHERE source_type='contractor_dispatch' AND source_key=? AND rev=2", (str(dispatch_a),)).fetchone()[0]
        for act in ("submit", "approve", "approve"):
            client.post("/api/vouchers/%d/%s" % (new_draft, act), headers=sup, json={})
        pid = conn.execute("SELECT id FROM gl_periods WHERE year=? AND period_no=3", (Y,)).fetchone()[0]
        cl = client.post("/api/ledger/periods/%d/close" % pid, headers=sup, json={"accept_warnings": True})
        T.check("第 3 期結帳（HTTP）", 200, cl.status_code)
        blocked = client.post("/api/vouchers/%d/post" % new_draft, headers=sup, json={})
        T.check("結帳後過帳該期傳票：被擋（HTTP）", 400, blocked.status_code)
        T.check("結帳後過帳：訊息說明期間已結帳", True, "結帳" in (blocked.json().get("detail") or ""))
        T.check("結帳後該傳票仍未過帳", "已核准", conn.execute("SELECT status FROM vouchers_all WHERE id=?", (new_draft,)).fetchone()[0])
    finally:
        conn.close()
    T.verdict()
