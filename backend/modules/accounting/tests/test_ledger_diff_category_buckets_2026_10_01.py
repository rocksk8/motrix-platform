# -*- coding: utf-8 -*-
"""『與總帳差異』頁的類別層級原因分桶（W4 低風險 #3(b)）：用總帳驗收的 2195-03 情境（真實資料表、真實提供者、真實引擎）。

手算（現金口徑，2195-03）：
  承攬商  報表＝匯款單已付 21,000（A，含稅）＋15,773（B，含稅 10,500＋個人外包 5,273）＝36,773
          總帳＝E04 專案成本 20,000＋10,000＝30,000（不含稅；個人外包已關聯勞報單 ⇒ 記在 E06 勞務費用，歸『其他』）
          差額 ＋6,773 ＝ 稅額 1,500（進項稅 E04：1,000＋500）＋個人外包 5,273；其餘 0
  其他    個人外包桶 −5,273（與承攬商對沖：報表算在承攬商、總帳算在其他）
  每個類別：差額＝各桶加總＋其餘（恆等式）；各類別稅額桶加總＝月合計稅額桶＝總帳進項稅額 1,500
應計口徑沒有稅額桶（報表未稅）：承攬商稅額桶 0。
反向控制在 tests/ 裡不放這裡：見 test_ledger_mutation_guards 的 M7（突變：個人外包桶取 0 ⇒ 本檔紅）。"""
import pytest

import db
from modules.accounting.ledger import features as F
from modules.accounting.ledger import periods as P
from modules.accounting.ledger import roles as ROLES
from modules.accounting.tests.test_ledger_acceptance_2026_10_01 import (
    Y, MAR1, MAR31, START, _login, _seed_bonus, _seed_case, _seed_contractors, _seed_payslips, _seed_stock)

MO = "%d-03" % Y


@pytest.fixture
def booked(client, make_user):
    """跑完驗收情境：引擎 → 一鍵確認到過帳。回 (headers, 已過帳)。"""
    sup = _login(client, make_user, "bk_sup")
    conn = db.get_db()
    conn.isolation_level = None
    try:
        ROLES.ensure_meta(conn)
        ROLES.ensure_default_roles(conn)
        P.create_year(conn, Y, "bk")
        F.set_flag(conn, "engine_drafts", True)
        F.set_flag(conn, "tax401", True)
        F.set_flag(conn, "withholding", True)
        qn = _seed_case(conn)
        _seed_contractors(conn, qn)
        _seed_payslips(conn, client, sup)
        conn.execute("UPDATE payslips SET status='已付款', signed_at=?, payment_date=? WHERE slip_no=?", ("2195-03-19T09:00:00", "2195-03-27", "PS-219503-001"))
        _seed_stock(conn, qn)
        conn.commit()
        r = client.post("/api/ledger/opening", headers=sup, json={"year": Y, "opening_date": START, "rows": [
            {"account_code": "1113", "debit": 500000, "credit": 0}, {"account_code": "3111", "debit": 0, "credit": 500000}]})
        assert r.status_code == 200, r.text
        for act in ("submit", "approve", "approve", "post"):
            assert client.post("/api/vouchers/%d/%s" % (r.json()["voucher_id"], act), headers=sup, json={}).status_code == 200
        _seed_bonus(conn, client, sup)
        assert client.post("/api/ledger/engine/run", headers=sup, json={"start": MAR1, "end": MAR31}).status_code == 200
        ids = [x[0] for x in conn.execute("SELECT voucher_id FROM gl_source_events WHERE status='drafted' AND event_date BETWEEN ? AND ?", (MAR1, MAR31))]
        b = client.post("/api/ledger/engine/batch", headers=sup, json={"voucher_ids": ids, "action": "all"})
        assert b.status_code == 200 and all(x.get("ok") for x in b.json()["results"]), b.text
    finally:
        conn.close()
    return sup


def _month(client, sup, basis):
    j = client.get("/api/reports/ledger-diff", params={"year": Y, "basis": basis}, headers=sup).json()
    assert j["glAvailable"] is True
    return next(m for m in j["months"] if m["month"] == MO)


def test_cash_contractor_and_other_buckets_match_the_hand_computation(client, booked):
    m = _month(client, booked, "cash")
    cats = m["expense"]["categories"]
    c, o = cats["contractor"], cats["other"]
    assert (c["report"], c["gl"], c["diff"]) == (36773, 30000, 6773)
    assert c["buckets"] == {"tax": 1500, "individual": 5273, "manual": 0, "bonus": 0, "residual": 0}
    assert o["buckets"]["individual"] == -5273 and o["buckets"]["tax"] == 0


def test_every_category_diff_equals_its_buckets_and_taxes_add_up(client, booked):
    m = _month(client, booked, "cash")
    cats = m["expense"]["categories"]
    for k, cat in cats.items():
        assert cat["diff"] == sum(cat["buckets"].values()), (k, cat)                # 恆等式（residual 兜底；這題確認 residual 沒有被改成別的東西）
    assert sum(cat["buckets"]["tax"] for cat in cats.values()) == m["expense"]["buckets"]["tax"] == 1500


def test_accrual_basis_tax_bucket_is_the_contractor_tax_included_in_the_report_and_individual_comes_from_the_paid_voucher(client, booked):
    """【2026-10-06 改】應計口徑：派發日 ≥ 2026-10-01 的承攬商成本含稅（報表），總帳稅額在 1268 ⇒ 差額進 tax 分桶（＝報表該月 taxContractor，本情境的 10 月派發稅 1500）；
    原本（35c）是 0。"""
    m = _month(client, booked, "accrual")
    c = m["expense"]["categories"]["contractor"]
    assert c["buckets"]["tax"] == 1500, c["buckets"]
    assert c["buckets"]["individual"] == 5273
    assert c["diff"] == sum(c["buckets"].values())
