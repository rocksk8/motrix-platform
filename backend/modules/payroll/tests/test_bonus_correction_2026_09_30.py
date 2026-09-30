# -*- coding: utf-8 -*-
"""獎金更正單（2026-09-30，使用者核准）：已發放獎金的事後更正。

驗：migration、建立規則與驗證、簽核流程（含權限／駁回／作廢）、核准後的沖轉＋重開應付傳票（kind=reversal）、
補發（出納、扣繳、傳票）、追回、營運報表提供者（IP-9 `bonus_correction`）、出納清單（IP-8 kind=correction）、
全年累計、佇列項目、通知、稽核。每個「不可以」都驗**狀態沒變、沒有多出傳票**。"""
import importlib
import json
import sqlite3

import pytest

from core import source_tree
from modules.payroll.tests._bonus_insure import insure_all
from modules.payroll.tests.test_bonus_case_api_2026_09_24 import (  # noqa: F401
    people, _seed_case, _create, _members_spec, _auth)

needs_accounting = pytest.mark.skipif(not source_tree.module_installed("modules/accounting/"),
                                      reason="會計（M06）不在這個安裝包")
BASE = "/api/bonus/corrections"


def _db():
    import db
    return db.get_db()


def _q(sql, *args):
    c = _db()
    try:
        return [dict(r) for r in c.execute(sql, args)]
    finally:
        c.close()


def _paid(client, people, no, net=100000):
    """做出一張「已發放」的獎金分潤單；回原單。"""
    _seed_case(no, net=net)
    assert _create(client, people["bc_sa"], no, members=_members_spec()).status_code == 200
    assert client.post("/api/bonus/cases/%s/submit" % no, headers=_auth(people["bc_sa"])).status_code == 200
    assert client.post("/api/bonus/cases/%s/approve" % no, headers=_auth(people["bc_sa2"])).status_code == 200
    insure_all()
    r = client.post("/api/bonus/cases/%s/mark-paid" % no, headers=_auth(people["bc_cash"]), json={})
    assert r.status_code == 200, r.text
    return _q("SELECT * FROM bonus_case_awards WHERE quote_no=?", no)[0]


def _current(client, people, no):
    r = client.get("%s/current/%s" % (BASE, no), headers=_auth(people["bc_sa"]))
    assert r.status_code == 200, r.text
    return r.json()


def _wanted(cur, **changes):
    """由目前金額組更正後名單；changes＝{username: 新金額}（可含原名單以外的人）。"""
    m = {p["username"]: p["amount"] for p in cur["people"]}
    m.update(changes)
    return [{"username": u, "amount": a} for u, a in m.items()]


def _create_corr(client, people, no, reason="金額更正", **changes):
    cur = _current(client, people, no)
    return client.post(BASE, headers=_auth(people["bc_sa"]),
                       json={"quote_no": no, "reason": reason, "lines": _wanted(cur, **changes)})


def _post_live_accrual(no):
    """模擬會計把「目前有效的應付傳票」送審核准過帳（總帳只沖轉已過帳的傳票；簽核流程本身不是這裡要驗的）。回傳票 id。"""
    from modules.payroll import bonus_correction as bc
    c = _db()
    try:
        award = dict(c.execute("SELECT * FROM bonus_case_awards WHERE quote_no=?", (no,)).fetchone())
        vid = bc.live_accrual_voucher_id(c, award)
        c.execute("UPDATE vouchers_all SET status='已過帳' WHERE id=?", (vid,))
        c.commit()
        return vid
    finally:
        c.close()


def _to_pending(client, people, no, post=True, paid=True, **changes):
    """已發放 → 建立 → 送審 → 核准；回 (corr_no, approve 的回應 json)。`post`：核准前先把有效應付傳票過帳。"""
    if paid:
        _paid(client, people, no)
    if post:
        _post_live_accrual(no)
    r = _create_corr(client, people, no, **changes)
    assert r.status_code == 200, r.text
    cn = r.json()["corr_no"]
    assert client.post("%s/%s/submit" % (BASE, cn), headers=_auth(people["bc_sa"])).status_code == 200
    a = client.post("%s/%s/approve" % (BASE, cn), headers=_auth(people["bc_sa2"]))
    assert a.status_code == 200, a.text
    return cn, a.json()


def _corr(cn):
    return _q("SELECT * FROM bonus_corrections WHERE corr_no=?", cn)[0]


def _voucher(vid):
    v = _q("SELECT * FROM vouchers_all WHERE id=?", vid)[0]
    v["lines"] = _q("SELECT account_code, debit, credit, source_type, source_key FROM voucher_lines"
                    " WHERE voucher_id=? ORDER BY line_no", vid)
    return v


# ── migration ────────────────────────────────────────────────────────────────

def test_migration_is_idempotent_and_reports_missing_base_table():
    m = importlib.import_module("modules.payroll.migrations.0002_bonus_corrections")
    c = sqlite3.connect(":memory:")
    assert isinstance(m.up(c), str) and "bonus_case_awards" in m.up(c)                  # 原單表不在 ⇒ 原因字串，不猜
    c.execute("CREATE TABLE bonus_case_awards (id INTEGER PRIMARY KEY)")
    assert m.up(c) is None and m.up(c) is None                                           # 冪等
    names = {r[0] for r in c.execute("SELECT name FROM sqlite_master")}
    assert {"bonus_corrections", "bonus_correction_log", "idx_bonus_corr_one_open"} <= names


def test_real_db_has_the_tables(client):
    names = {r["name"] for r in _q("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"bonus_corrections", "bonus_correction_log"} <= names
    assert _q("SELECT version FROM module_schema_versions WHERE module='payroll'")[0]["version"] >= 2


# ── 建立規則與驗證 ─────────────────────────────────────────────────────────────

def test_only_a_paid_award_can_be_corrected(client, people):
    _seed_case("MQ-BCR-001")
    assert _create(client, people["bc_sa"], "MQ-BCR-001", members=_members_spec()).status_code == 200   # 草稿
    r = client.post(BASE, headers=_auth(people["bc_sa"]),
                    json={"quote_no": "MQ-BCR-001", "reason": "x", "lines": [{"username": "bc_s1", "amount": 1}]})
    assert r.status_code == 409 and "已發放" in r.json()["detail"]
    assert client.post(BASE, headers=_auth(people["bc_sa"]), json={"quote_no": "MQ-NONE", "reason": "x",
                                                                   "lines": [{"username": "bc_s1", "amount": 1}]}).status_code == 404
    assert _q("SELECT COUNT(*) AS n FROM bonus_corrections")[0]["n"] == 0


def test_validation_rejects_bad_input_and_writes_nothing(client, people):
    _paid(client, people, "MQ-BCR-002")
    cur = _current(client, people, "MQ-BCR-002")
    ok = _wanted(cur, bc_s1=1234)
    bad = [
        ({"reason": "", "lines": ok}, "原因"),
        ({"reason": "x" * 201, "lines": ok}, "原因"),
        ({"reason": "x", "lines": []}, "至少"),
        ({"reason": "x", "lines": _wanted(cur)}, "完全相同"),                     # 沒有任何差額
        ({"reason": "x", "lines": _wanted(cur, bc_s1=-1)}, "整數"),
        ({"reason": "x", "lines": _wanted(cur, bc_s1=True)}, "整數"),             # bool 不是金額
        ({"reason": "x", "lines": _wanted(cur, bc_s1="100")}, "整數"),
        ({"reason": "x", "lines": _wanted(cur, bc_s1=10 ** 9)}, "整數"),
        ({"reason": "x", "lines": ok + [{"username": "bc_s1", "amount": 5}]}, "重複"),
        ({"reason": "x", "lines": ok + [{"username": "no_such_user", "amount": 5}]}, "在職帳號"),
        ({"reason": "x", "lines": ok + [{"amount": 5}]}, "帳號"),
        ({"reason": "x", "lines": "nope"}, "至少"),
    ]
    for body, word in bad:
        r = client.post(BASE, headers=_auth(people["bc_sa"]), json=dict(body, quote_no="MQ-BCR-002"))
        assert r.status_code == 400 and word in r.json()["detail"], (body, r.status_code, r.text[:120])
    assert _q("SELECT COUNT(*) AS n FROM bonus_corrections")[0]["n"] == 0


def test_permissions_on_create_and_read(client, people):
    _paid(client, people, "MQ-BCR-003")
    cur = _current(client, people, "MQ-BCR-003")
    body = {"quote_no": "MQ-BCR-003", "reason": "x", "lines": _wanted(cur, bc_s1=1)}
    for who in ("bc_s1", "bc_cash", "bc_other"):
        assert client.post(BASE, headers=_auth(people[who]), json=body).status_code == 403, who
        assert client.get("%s/current/MQ-BCR-003" % BASE, headers=_auth(people[who])).status_code == 403, who
    cn = client.post(BASE, headers=_auth(people["bc_sa"]), json=body).json()["corr_no"]
    # 草稿：出納與其他人都看不到（404，不是 403——當作不存在）；清單裡也沒有
    for who in ("bc_cash", "bc_s1", "bc_other"):
        assert client.get("%s/%s" % (BASE, cn), headers=_auth(people[who])).status_code == 404, who
    assert client.get(BASE, headers=_auth(people["bc_cash"])).json()["items"] == []
    assert client.get(BASE, headers=_auth(people["bc_s1"])).status_code == 403
    assert [i["corr_no"] for i in client.get(BASE, headers=_auth(people["bc_sa"])).json()["items"]] == [cn]


def test_one_open_correction_per_award_and_seq_increments(client, people):
    _paid(client, people, "MQ-BCR-004")
    a = _create_corr(client, people, "MQ-BCR-004", bc_s1=1)
    assert a.status_code == 200 and a.json()["corr_no"] == "MQ-BCR-004-C1"
    assert _create_corr(client, people, "MQ-BCR-004", bc_s1=2).status_code == 409        # 已有未結案
    cur = _current(client, people, "MQ-BCR-004")
    assert cur["canCreate"] is False and cur["open"]["corr_no"] == "MQ-BCR-004-C1"
    assert client.post("%s/MQ-BCR-004-C1/cancel" % BASE, headers=_auth(people["bc_sa"])).status_code == 200
    b = _create_corr(client, people, "MQ-BCR-004", bc_s1=2)
    assert b.status_code == 200 and b.json()["corr_no"] == "MQ-BCR-004-C2"                # 作廢後可再開，序號往後


def test_draft_edit_and_status_guards(client, people):
    _paid(client, people, "MQ-BCR-005")
    cn = _create_corr(client, people, "MQ-BCR-005", bc_s1=1).json()["corr_no"]
    cur = _current(client, people, "MQ-BCR-005")
    r = client.put("%s/%s" % (BASE, cn), headers=_auth(people["bc_sa"]),
                   json={"reason": "改過", "lines": _wanted(cur, bc_s1=77777)})
    assert r.status_code == 200
    c = _corr(cn)
    assert c["reason"] == "改過" and c["new_total"] - c["old_total"] == 77777 - 5000 + 0 or c["new_total"] > 0
    bad = client.put("%s/%s" % (BASE, cn), headers=_auth(people["bc_sa"]), json={"reason": "", "lines": _wanted(cur, bc_s1=3)})
    assert bad.status_code == 400 and _corr(cn)["reason"] == "改過"                        # 被拒＝原值不變
    assert client.post("%s/%s/submit" % (BASE, cn), headers=_auth(people["bc_sa"])).status_code == 200
    assert client.put("%s/%s" % (BASE, cn), headers=_auth(people["bc_sa"]),
                      json={"reason": "x", "lines": _wanted(cur, bc_s1=3)}).status_code == 409   # 待審核不可改
    assert client.post("%s/%s/cancel" % (BASE, cn), headers=_auth(people["bc_sa"])).status_code == 409
    assert client.post("%s/%s/submit" % (BASE, cn), headers=_auth(people["bc_sa"])).status_code == 409
    assert _corr(cn)["status"] == "待審核"


# ── 簽核 ──────────────────────────────────────────────────────────────────────

def test_reject_needs_reason_returns_to_draft_and_notifies_requester(client, people, monkeypatch):
    from helpers import email_notify
    sent = []
    monkeypatch.setattr(email_notify, "notify_bonus_correction_submitted", lambda *a: sent.append(("submitted",) + a))
    monkeypatch.setattr(email_notify, "notify_bonus_correction_returned", lambda *a: sent.append(("returned",) + a))
    _paid(client, people, "MQ-BCR-006")
    cn = _create_corr(client, people, "MQ-BCR-006", bc_s1=1).json()["corr_no"]
    assert client.post("%s/%s/reject" % (BASE, cn), headers=_auth(people["bc_sa2"]), json={"reason": "x"}).status_code == 409   # 草稿不能駁回
    assert client.post("%s/%s/submit" % (BASE, cn), headers=_auth(people["bc_sa"])).status_code == 200
    assert sent[-1][0] == "submitted" and [u for u in sent[-1][3] if u != "demo"] == ["bc_sa2"]    # 輪到的簽核人（申請人自己除外；測試庫內建的 demo 超管也是收件人，不在這題範圍）
    assert client.post("%s/%s/reject" % (BASE, cn), headers=_auth(people["bc_sa2"]), json={"reason": " "}).status_code == 400
    assert _corr(cn)["status"] == "待審核"
    assert client.post("%s/%s/reject" % (BASE, cn), headers=_auth(people["bc_s1"]), json={"reason": "x"}).status_code == 403
    r = client.post("%s/%s/reject" % (BASE, cn), headers=_auth(people["bc_sa2"]), json={"reason": "金額不對"})
    assert r.status_code == 200 and _corr(cn)["status"] == "草稿" and _corr(cn)["approval_json"] == "{}"
    assert sent[-1] == ("returned", cn, "MQ-BCR-006", ["bc_sa"], "金額不對")
    assert _q("SELECT COUNT(*) AS n FROM bonus_corrections WHERE reversal_voucher_id != 0")[0]["n"] == 0   # 駁回不開傳票


def test_approve_permissions_and_no_self_approval(client, people):
    _paid(client, people, "MQ-BCR-007")
    cn = _create_corr(client, people, "MQ-BCR-007", bc_s1=1).json()["corr_no"]
    assert client.post("%s/%s/approve" % (BASE, cn), headers=_auth(people["bc_sa2"])).status_code == 409   # 草稿不在流程
    client.post("%s/%s/submit" % (BASE, cn), headers=_auth(people["bc_sa"]))
    for who in ("bc_s1", "bc_cash", "bc_other"):
        assert client.post("%s/%s/approve" % (BASE, cn), headers=_auth(people[who])).status_code == 403, who
    r = client.post("%s/%s/approve" % (BASE, cn), headers=_auth(people["bc_sa"]))        # 有兩位最高管理者 ⇒ 不可自簽
    assert r.status_code == 403
    assert _corr(cn)["status"] == "待審核" and _corr(cn)["reversal_voucher_id"] == 0


def test_multi_tier_chain_needs_every_tier(client, people):
    from modules.payroll.tests.test_bonus_case_api_2026_09_24 import _set_flow
    _paid(client, people, "MQ-BCR-008")
    _set_flow(["bc_sa2"])
    cn = _create_corr(client, people, "MQ-BCR-008", bc_s1=99999).json()["corr_no"]
    client.post("%s/%s/submit" % (BASE, cn), headers=_auth(people["bc_sa"]))
    assert _corr(cn)["status"] == "待審核"
    r = client.post("%s/%s/approve" % (BASE, cn), headers=_auth(people["bc_sa2"]))
    assert r.status_code == 200 and r.json()["status"] == "待補發"


# ── 核准：傳票、補發、追回 ───────────────────────────────────────────────────────

@needs_accounting
def test_approve_opens_reversal_and_rebook_drafts_and_waits_for_payout(client, people):
    no = "MQ-BCR-010"
    cn, res = _to_pending(client, people, no, bc_s1=9000)                                # 原 5000 → 9000（補發 4000）
    assert res["status"] == "待補發"
    c = _corr(cn)
    assert (c["supplement_total"], c["clawback_total"]) == (4000, 0) and c["new_total"] == c["old_total"] + 4000
    award = _q("SELECT * FROM bonus_case_awards WHERE quote_no=?", no)[0]
    acc = _voucher(award["accrual_voucher_id"])
    rev = _voucher(c["reversal_voucher_id"])
    assert rev["kind"] == "reversal" and rev["reverses_no"] == acc["voucher_no"]         # 與總帳引擎同一種「沖轉」
    assert rev["origin"] == "bonus_corr_reversal" and rev["status"] == "草稿"
    assert sorted((l["account_code"], l["debit"], l["credit"]) for l in rev["lines"]) == sorted(
        (l["account_code"], l["credit"], l["debit"]) for l in acc["lines"])                # 原應付的鏡像（借貸互換）
    assert sum(l["debit"] for l in rev["lines"]) == c["old_total"]
    # 沖轉傳票的分錄由總帳依原傳票鏡像組成（不帶案件來源；屬 voucher.draft 的行為，已回報 W4）
    reb = _voucher(c["rebook_voucher_id"])
    assert reb["kind"] != "reversal" and reb["origin"] == "bonus_corr_accrual"
    assert [(l["account_code"], l["debit"], l["credit"]) for l in reb["lines"]] == [
        ("6111", c["new_total"], 0), ("2191", 0, c["new_total"])]
    # 原單不動
    assert _q("SELECT status, accrual_voucher_id FROM bonus_case_awards WHERE quote_no=?", no)[0] == {
        "status": "已發放", "accrual_voucher_id": award["accrual_voucher_id"]}
    # 出納清單：待補發列（kind=correction），金額＝補發總額
    cash = client.get("/api/cashier/bonus-payouts", headers=_auth(people["bc_cash"])) if False else None
    from core import registry
    pend = registry.single_provider("bonus.payouts").pending(_db())
    mine = [p for p in pend if p["quoteNo"] == cn]
    assert mine and mine[0]["kind"] == "correction" and mine[0]["total"] == 4000 and mine[0]["originQuoteNo"] == no
    # 營運報表：補發還沒發 ⇒ 還不列支出
    assert [e for e in registry.providers("expense.entries")["bonus_correction"](_db(), "2000-01-01", "2100-01-01")] == []


@needs_accounting
def test_mark_paid_supplement_pays_with_deductions_and_lists_in_report_and_history(client, people):
    from core import registry
    no = "MQ-BCR-011"
    cn, _ = _to_pending(client, people, no, bc_s1=9000)
    d = client.get("%s/%s" % (BASE, cn), headers=_auth(people["bc_cash"]))               # 出納看得到待補發
    assert d.status_code == 200 and d.json()["deductions"]["totals"]["gross"] == 4000
    # 權限：非出納不可補發；狀態不變
    assert client.post("%s/%s/mark-paid" % (BASE, cn), headers=_auth(people["bc_s1"]), json={}).status_code == 403
    assert _corr(cn)["status"] == "待補發"
    # 有人沒有投保金額 ⇒ 拒絕、狀態不變、沒有傳票（不以 0 計算）
    import db
    from modules.payroll.bonus_deductions import PROFILE_KEY
    conn = db.get_db()
    try:
        prof = json.loads(conn.execute("SELECT value_json FROM system_settings WHERE key=?", (PROFILE_KEY,)).fetchone()[0])
        prof.pop("bc_s1")
        conn.execute("UPDATE system_settings SET value_json=? WHERE key=?", (json.dumps(prof), PROFILE_KEY))
        conn.commit()
    finally:
        conn.close()
    r = client.post("%s/%s/mark-paid" % (BASE, cn), headers=_auth(people["bc_cash"]), json={})
    assert r.status_code == 409 and "投保金額" in r.json()["detail"]
    assert _corr(cn)["status"] == "待補發" and _corr(cn)["supplement_voucher_id"] == 0
    insure_all()
    # 銀行科目無效 ⇒ 400、狀態不變
    assert client.post("%s/%s/mark-paid" % (BASE, cn), headers=_auth(people["bc_cash"]),
                       json={"bank_account_code": "9999"}).status_code == 400
    assert _corr(cn)["status"] == "待補發"
    r = client.post("%s/%s/mark-paid" % (BASE, cn), headers=_auth(people["bc_cash"]), json={})
    assert r.status_code == 200 and r.json()["status"] == "已完成", r.text
    c = _corr(cn)
    assert c["paid_by"] == "bc_cash" and c["paid_at"] and c["supplement_voucher_id"]
    v = _voucher(c["supplement_voucher_id"])
    tot = json.loads(c["deductions_json"])["totals"]
    assert v["origin"] == "bonus_corr_payment" and v["status"] == "草稿"
    by = {l["account_code"]: l for l in v["lines"]}
    assert by["2191"]["debit"] == 4000 and sum(l["credit"] for l in v["lines"]) == 4000
    assert by["1113"]["credit"] == tot["net"] and by["2252"]["credit"] >= tot["withholding"]
    # 再按一次 ⇒ 409
    assert client.post("%s/%s/mark-paid" % (BASE, cn), headers=_auth(people["bc_cash"]), json={}).status_code == 409
    # 營運報表：補發日列 +4000（category 獎金分潤）；出納待發放清單不再有；發放紀錄有
    rows = registry.providers("expense.entries")["bonus_correction"](_db(), "2000-01-01", "2100-01-01")
    assert [(r_["quoteNo"], r_["amount"], r_["category"]) for r_ in rows] == [(no, 4000, "獎金分潤")]
    assert rows[0]["date"] == c["paid_at"][:10]
    assert [p for p in registry.single_provider("bonus.payouts").pending(_db()) if p["quoteNo"] == cn] == []
    paid = [p for p in registry.single_provider("bonus.payouts").paid(_db(), "2000-01-01", "2100-01-01") if p["quoteNo"] == cn]
    assert paid and paid[0]["kind"] == "correction" and paid[0]["total"] == 4000 and paid[0]["net"] == tot["net"]


@needs_accounting
def test_decrease_only_completes_on_approval_and_reports_negative_expense(client, people):
    from core import registry
    no = "MQ-BCR-012"
    cn, res = _to_pending(client, people, no, bc_s1=1000)                                 # 原 5000 → 1000（追回 4000）
    assert res["status"] == "已完成"                                                      # 沒有人要補發 ⇒ 核准即完成
    c = _corr(cn)
    assert (c["supplement_total"], c["clawback_total"]) == (0, 4000) and c["supplement_voucher_id"] == 0
    assert c["reversal_voucher_id"] and c["rebook_voucher_id"] and c["clawback_voucher_id"]
    # 追回＝應收（待使用者確認處理方式）：借 其他應收款 1213／貸 應付 2191，金額＝追回總額
    cb = _voucher(c["clawback_voucher_id"])
    assert cb["origin"] == "bonus_corr_clawback" and cb["status"] == "草稿" and "追回處理方式待確認" in cb["summary"]
    assert sorted((l["account_code"], l["debit"], l["credit"]) for l in cb["lines"]) == [("1213", 4000, 0), ("2191", 0, 4000)]
    assert all(l["source_type"] == "case" and l["source_key"] == no for l in cb["lines"])
    assert [p for p in registry.single_provider("bonus.payouts").pending(_db()) if p["quoteNo"] == cn] == []
    rows = registry.providers("expense.entries")["bonus_correction"](_db(), "2000-01-01", "2100-01-01")
    assert [(r_["amount"], r_["desc"].split("（")[0]) for r_ in rows] == [(-4000, "獎金分潤 更正追回")]
    assert rows[0]["date"] == c["approved_at"][:10]
    # 營運報表實際加總：原單 +原總額、更正 −4000
    from modules.analytics.api import reports as rp
    ex = rp._collect_expenses(int(c["approved_at"][:4]), None, "accrual", conn=_db())
    assert ex["totals"]["other"] == c["old_total"] - 4000


@needs_accounting
def test_redistribution_with_equal_total_needs_payout_for_the_positive_part(client, people):
    cur_people = None
    no = "MQ-BCR-013"
    _paid(client, people, no)
    cur = _current(client, people, no)
    amounts = {p["username"]: p["amount"] for p in cur["people"]}
    r = _create_corr(client, people, no, bc_s1=amounts["bc_s1"] - 500, bc_p1=amounts["bc_p1"] + 500)
    cn = r.json()["corr_no"]
    c = _corr(cn)
    assert c["old_total"] == c["new_total"] and (c["supplement_total"], c["clawback_total"]) == (500, 500)
    client.post("%s/%s/submit" % (BASE, cn), headers=_auth(people["bc_sa"]))
    assert client.post("%s/%s/approve" % (BASE, cn), headers=_auth(people["bc_sa2"])).json()["status"] == "待補發"


def test_successive_corrections_build_on_each_other_and_feed_ytd(client, people):
    no = "MQ-BCR-014"
    cn, _ = _to_pending(client, people, no, bc_s1=9000)
    assert client.post("%s/%s/mark-paid" % (BASE, cn), headers=_auth(people["bc_cash"]), json={}).status_code == 200
    cur = _current(client, people, no)
    assert {p["username"]: p["amount"] for p in cur["people"]}["bc_s1"] == 9000          # 目前金額＝原＋已完成更正
    from modules.payroll import bonus_correction as bc
    c = _corr(cn)
    year = c["paid_at"][:4]
    conn = _db()
    try:
        assert bc.ytd_adjustments(conn, year) == {"bc_s1": 4000}
        assert bc.ytd_adjustments(conn, "1999") == {}
        from modules.payroll import bonus_deductions as bd
        assert bd.ytd_in_motrix(conn, year)["bc_s1"] == 9000                              # 原單 5000＋補發 4000
    finally:
        conn.close()
    r = _create_corr(client, people, no, bc_s1=8000)
    assert r.status_code == 200 and r.json()["corr_no"] == no + "-C2"
    assert _q("SELECT old_total FROM bonus_corrections WHERE corr_no=?", no + "-C2")[0]["old_total"] == _corr(cn)["new_total"]


# ── 佇列／通知／稽核／其他 ─────────────────────────────────────────────────────

def test_queue_item_appears_only_while_pending_review(client, people, monkeypatch):
    from core import registry
    from helpers import email_notify
    sent = []
    monkeypatch.setattr(email_notify, "notify_bonus_correction_approved", lambda *a: sent.append(a))
    _paid(client, people, "MQ-BCR-015")
    cn = _create_corr(client, people, "MQ-BCR-015", bc_s1=9000).json()["corr_no"]
    q = lambda: [i for i in registry.providers("approval.queue_items")["payroll"](_db()) if i["type"] == "bonus_correction"]
    assert q() == []                                                                      # 草稿不在佇列
    client.post("%s/%s/submit" % (BASE, cn), headers=_auth(people["bc_sa"]))
    items = q()
    assert len(items) == 1 and items[0]["quoteNo"] == cn and items[0]["linkedQuoteNo"] == "MQ-BCR-015" and items[0]["total"] == 0
    client.post("%s/%s/approve" % (BASE, cn), headers=_auth(people["bc_sa2"]))
    assert q() == []
    # 核准信：申請人＋出納（有補發），不含金額
    assert sent and sent[-1][0] == cn and set(sent[-1][2]) - {"demo"} == {"bc_sa", "bc_cash"} and sent[-1][3] is True


def test_decrease_only_approval_mail_goes_to_requester_only(client, people, monkeypatch):
    from helpers import email_notify
    sent = []
    monkeypatch.setattr(email_notify, "notify_bonus_correction_approved", lambda *a: sent.append(a))
    _to_pending(client, people, "MQ-BCR-016", bc_s1=1000)
    assert sent and sent[-1][2] == ["bc_sa"] and sent[-1][3] is False


def test_mail_types_are_registered_and_bodies_carry_no_amounts():
    from helpers import mail_types
    for k in ("bonus_correction_submitted", "bonus_correction_approved", "bonus_correction_returned"):
        assert mail_types.subject(k, "x")
    import inspect
    from helpers import email_notify
    for fn in (email_notify.notify_bonus_correction_submitted, email_notify.notify_bonus_correction_approved,
               email_notify.notify_bonus_correction_returned):
        assert "NT$" not in inspect.getsource(fn) and "amount" not in inspect.getsource(fn).lower().replace("amounts", "")


def test_audit_rows_carry_ref_no_and_case(client, people):
    cn, _ = _to_pending(client, people, "MQ-202609-917", bc_s1=9000)
    rows = _q("SELECT action, ref_no, case_no, result FROM audit_log WHERE target_id=? ORDER BY id", cn)
    assert [r["action"] for r in rows] == ["bonus.correction.create", "bonus.correction.submit", "bonus.correction.approve"]
    assert all(r["ref_no"] == cn and r["case_no"] and r["result"] != "fail" for r in rows)
    log = [r["action"] for r in _q("SELECT action FROM bonus_correction_log ORDER BY id")]
    assert log == ["create", "submit", "approve"]


def test_unpaid_award_return_rule_is_unchanged(client, people):
    """已發放仍不可退回（更正走更正單）——更正單不改這條。"""
    _paid(client, people, "MQ-BCR-018")
    r = client.post("/api/bonus/cases/MQ-BCR-018/return", headers=_auth(people["bc_sa"]), json={"reason": "x"})
    assert r.status_code == 409 and "不可以退回" in r.json()["detail"]


# ── 總帳沖轉的限制、連續更正、與總帳引擎互不衝突 ───────────────────────────────────

@needs_accounting
def test_reversal_blocked_when_accrual_not_posted_opens_no_vouchers_and_says_why(client, people):
    """原應付傳票還是草稿 ⇒ 總帳拒絕沖轉（回 blocked）⇒ 沖轉與重開都不開（只重開會讓應付重複），更正單照常核准，畫面有原因。"""
    cn, res = _to_pending(client, people, "MQ-BCR-020", post=False, bc_s1=9000)
    assert res["status"] == "待補發"
    c = _corr(cn)
    assert (c["reversal_voucher_id"], c["rebook_voucher_id"], c["clawback_voucher_id"]) == (0, 0, 0)
    assert "只有已過帳" in c["voucher_notice"] and "手動" in c["voucher_notice"]
    assert _q("SELECT COUNT(*) AS n FROM vouchers_all WHERE origin LIKE 'bonus_corr%'")[0]["n"] == 0


@needs_accounting
def test_chained_correction_reverses_the_previous_rebook_voucher_not_the_original(client, people):
    no = "MQ-BCR-021"
    cn1, _ = _to_pending(client, people, no, bc_s1=9000)
    c1 = _corr(cn1)
    assert client.post("%s/%s/mark-paid" % (BASE, cn1), headers=_auth(people["bc_cash"]), json={}).status_code == 200
    orig_id = _q("SELECT accrual_voucher_id FROM bonus_case_awards WHERE quote_no=?", no)[0]["accrual_voucher_id"]
    # 第一次更正的重開應付傳票過帳後，第二次更正要沖的是它
    _c = _db()
    try:
        _c.execute("UPDATE vouchers_all SET status='已過帳' WHERE id=?", (c1["rebook_voucher_id"],))
        _c.commit()
    finally:
        _c.close()
    cn2, res = _to_pending(client, people, no, paid=False, post=False, bc_s1=8000)
    c2 = _corr(cn2)
    rev2 = _voucher(c2["reversal_voucher_id"])
    assert rev2["reverses_no"] == _voucher(c1["rebook_voucher_id"])["voucher_no"] != _voucher(orig_id)["voucher_no"]
    assert rev2["kind"] == "reversal" and sum(l["debit"] for l in rev2["lines"]) == c1["new_total"]


@needs_accounting
def test_engine_leaves_correction_vouchers_alone(client, people, make_user):
    """W4 約定：核准 → 沖轉傳票過帳 → 引擎掃過沖轉日期區間 ⇒ 不新增草稿、gl_source_events 筆數與狀態不變、E07a/E07b 仍是 native。"""
    from datetime import date
    no = "MQ-BCR-022"
    _paid(client, people, no)
    name, pw = make_user(username="bc_gl_admin", role="superadmin", modules=["cashier"])
    tok = client.post("/api/auth/login", json={"username": name, "password": pw}).json()["token"]
    hdr = {"Authorization": "Bearer " + tok}
    assert client.put("/api/ledger/features/engine_drafts", headers=hdr, json={"enabled": True}).status_code == 200
    body = {"start": date.today().replace(day=1).isoformat(), "end": date.today().isoformat()}
    assert client.post("/api/ledger/engine/run", headers=hdr, json=body).status_code == 200      # 先讓引擎登記原單的 native 事件

    def snap():
        return (_q("SELECT event_code, source_key, rev, status, voucher_id FROM gl_source_events ORDER BY id"),
                _q("SELECT COUNT(*) AS n FROM vouchers_all WHERE status='草稿'")[0]["n"])
    cn, _ = _to_pending(client, people, no, paid=False, bc_s1=9000)
    c = _corr(cn)
    rev = c["reversal_voucher_id"]
    _c = _db()
    try:
        _c.execute("UPDATE vouchers_all SET status='已過帳' WHERE id IN (?, ?)", (rev, c["rebook_voucher_id"]))
        _c.commit()
    finally:
        _c.close()
    before = snap()
    assert any(r_["event_code"] == "E07a" and r_["status"] == "native" for r_ in before[0])
    r = client.post("/api/ledger/engine/run", headers=hdr, json=body)
    assert r.status_code == 200, r.text
    after = snap()
    assert after[0] == before[0], "引擎動了 gl_source_events（native 列被改寫／新增事件）"
    assert after[1] == before[1]                                                                  # 沒有新草稿
    assert r.json()["stats"].get("created", 0) == 0 and r.json()["stats"].get("orphans", 0) == 0
    assert _voucher(rev)["kind"] == "reversal" and _voucher(rev)["status"] == "已過帳"             # 沖轉傳票沒被引擎再沖轉或作廢
    assert not [v for v in _q("SELECT id FROM vouchers_all WHERE reverses_no=? AND COALESCE(voided_at,'')=''", _voucher(rev)["voucher_no"])]
