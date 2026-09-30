# -*- coding: utf-8 -*-
"""W2 寫入串接矩陣缺口（MONEY-FLOWS §9.3）：L9 系統產生的傳票不可從傳票頁作廢、L6 手工付款傳票已記付款時引擎不重複產生 E06b。
（L1／L2／L8／L10／GL 狀態提供者的測試在下方逐項加入。）"""
import pytest

import db
from modules.accounting.ledger import roles as ROLES
from modules.payroll import gl_events as G

_N = [0]


@pytest.fixture
def conn(client):
    c = db.get_db()
    ROLES.ensure_meta(c)
    ROLES.ensure_default_roles(c)
    c.commit()
    yield c
    c.close()


def _login(client, make_user, name, role="superadmin"):
    kw = {"role": role}
    if role != "superadmin":
        kw["modules"] = ["cashier", "finance"]
    u, p = make_user(username="%s%d" % (name, id(client)), **kw)
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _voucher(conn, status="草稿", kind="manual", origin="", voided=False, date="2189-05-10"):
    _N[0] += 1
    no = "LG%s-%d" % (date.replace("-", ""), _N[0] + 900)
    vid = conn.execute("INSERT INTO vouchers_all(voucher_no, voucher_date, category, summary, status, created_by, created_at, updated_at, kind, origin, voided_at)"
                       " VALUES (?,?, '轉', 'lg', ?, 't','n','n', ?, ?, ?)", (no, date, "已核准" if status == "已過帳" else status, kind, origin, "2189-06-01" if voided else "")).lastrowid
    for i, (code, d, cr) in enumerate((("1113", 10, 0), ("4111", 0, 10)), 1):
        conn.execute("INSERT INTO voucher_lines(voucher_id,line_no,account_code,debit,credit) VALUES (?,?,?,?,?)", (vid, i, code, d, cr))
    if status == "已過帳":
        conn.execute("UPDATE vouchers_all SET status='已過帳' WHERE id=?", (vid,))
    conn.commit()
    return vid, no


# ── L9 ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind,origin,word", [("auto", "", "自動傳票"), ("reversal", "", "反向傳票"), ("manual", "bonus_accrual", "獎金入帳")])
def test_l9_system_generated_vouchers_cannot_be_voided_from_the_voucher_page(client, make_user, conn, kind, origin, word):
    h = _login(client, make_user, "lg9")
    vid, _ = _voucher(conn, kind=kind, origin=origin)
    r = client.post("/api/vouchers/%d/void" % vid, headers=h, json={"reason": "想作廢"})
    assert r.status_code == 409 and word in r.json()["detail"] and "來源單據" in r.json()["detail"]
    assert conn.execute("SELECT COALESCE(voided_at,'') FROM vouchers_all WHERE id=?", (vid,)).fetchone()[0] == ""


def test_l9_manual_vouchers_are_still_voidable(client, make_user, conn):
    h = _login(client, make_user, "lg9b")
    vid, _ = _voucher(conn)
    assert client.post("/api/vouchers/%d/void" % vid, headers=h, json={"reason": "手工傳票作廢"}).status_code == 200


# ── L6 ──────────────────────────────────────────────────────────────────

def _slip(conn, voucher_no="", status="已付款", pay="2189-05-20"):
    _N[0] += 1
    no = "LG-L6-%d" % _N[0]
    cid = conn.execute("INSERT INTO contractors(name, id_number) VALUES (?,?)", ("甲", "A123456789")).lastrowid
    conn.execute("INSERT INTO payslips(slip_no, contractor_id, contractor_name, income_type, gross_amount, tax_withheld, nhi_supplement, net_amount, "
                 "slip_date, status, signed_at, payment_date, voucher_no) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (no, cid, "甲", "9A", 10000, 1000, 211, 8789, "2189-05-10", status, "2189-05-12T09:00:00", pay, voucher_no))
    conn.commit()
    return no


def _e06b(no):
    return [e for e in G.gl_events("2189-05-01", "2189-05-31")["events"] if e["event_code"] == "E06b" and e["source_key"] == no]


def test_l6_a_manual_payment_voucher_suppresses_the_engine_payment_event(conn):
    _, vno = _voucher(conn, status="已過帳")
    no = _slip(conn, voucher_no=vno)
    assert _e06b(no) == []                                                  # 手工傳票已記付款 ⇒ 不重複
    assert "手工傳票記帳" in G.gl_events("2189-05-01", "2189-05-31")["notice"]
    assert any(e["event_code"] == "E06" and e["source_key"] == no for e in G.gl_events("2189-05-01", "2189-05-31")["events"])   # 應付照樣入帳


@pytest.mark.parametrize("kw,why", [({"voided": True}, "作廢的手工傳票不算"), ({"kind": "auto"}, "引擎自己產生的不算（否則自己的傳票被判來源消失）"),
                                    ({"origin": "bonus_payment"}, "獎金入帳傳票不算")])
def test_l6_only_valid_manual_vouchers_count(conn, kw, why):
    _, vno = _voucher(conn, status="已過帳", **kw)
    no = _slip(conn, voucher_no=vno)
    assert len(_e06b(no)) == 1, why


def test_l6_unknown_or_empty_voucher_number_still_produces_the_event(conn):
    assert len(_e06b(_slip(conn, voucher_no="NOPE-0001"))) == 1
    assert len(_e06b(_slip(conn, voucher_no=""))) == 1


# ── L2 / L1 / GL 狀態提供者 ─────────────────────────────────────────────

from core import registry  # noqa: E402
from modules.accounting.ledger import auto_run as AR  # noqa: E402
from modules.accounting.ledger import engine as E  # noqa: E402
from modules.accounting.ledger import features as F  # noqa: E402


@pytest.fixture
def fake(monkeypatch, conn):
    monkeypatch.setattr(registry, "_LEGACY_PROVIDERS", {})
    monkeypatch.setattr(registry, "_LOADED", {})
    state = {"events": []}
    registry._LEGACY_PROVIDERS[("gl.events", "fake")] = lambda s, e, changed_since="": {"events": [ev for ev in state["events"] if s <= ev["event_date"] <= e]}
    return state


def _ev(key, date, amount=1000, code="E04"):
    return {"source_type": "contractor_dispatch", "source_key": key, "event_code": code, "event_date": date, "doc_no": "ZZ" + key, "case_no": "",
            "party": {"key": "12345678", "name": "甲"}, "tax_code": "IN-5", "mode": "snapshot",
            "lines": [{"role": "COST_PROJECT", "side": "D", "amount": amount}, {"role": "INPUT_TAX", "side": "D", "amount": amount // 20},
                      {"role": "AP", "side": "C", "amount": amount + amount // 20}], "meta": {}}


def _post(conn, key):
    vid = conn.execute("SELECT voucher_id FROM gl_source_events WHERE source_key=? ORDER BY rev DESC", (key,)).fetchone()[0]
    conn.execute("UPDATE vouchers_all SET status='已核准' WHERE id=?", (vid,))
    conn.execute("UPDATE vouchers_all SET status='已過帳' WHERE id=?", (vid,))
    conn.commit()
    return vid


def test_l2_an_old_posted_event_outside_the_window_is_still_detected_as_drift(conn, fake):
    fake["events"] = [_ev("L2-A", "2189-01-10")]
    E.run(conn, "2189-01-01", "2189-01-31", "acc")
    conn.commit()
    _post(conn, "L2-A")
    fake["events"] = [_ev("L2-A", "2189-01-10", amount=2000)]              # 來源之後被改
    r = E.run(conn, "2189-03-01", "2189-03-31", "acc")                    # 執行的是 3 月，事件在 1 月
    conn.commit()
    assert r["stats"]["drift"] >= 1
    rows = [x[0] for x in conn.execute("SELECT status FROM gl_source_events WHERE source_key='L2-A' ORDER BY rev").fetchall()]
    assert rows[0] == "drift" and len(rows) == 2                            # 舊列 drift，新版本另產


def test_l2_an_old_posted_event_whose_source_vanished_is_reversed_outside_the_window(conn, fake):
    fake["events"] = [_ev("L2-B", "2189-01-12")]
    E.run(conn, "2189-01-01", "2189-01-31", "acc")
    conn.commit()
    _post(conn, "L2-B")
    fake["events"] = []
    r = E.run(conn, "2189-03-01", "2189-03-31", "acc")
    conn.commit()
    assert r["stats"]["orphans"] == 1
    assert conn.execute("SELECT status FROM gl_source_events WHERE source_key='L2-B'").fetchone()[0] == "orphan"


def test_l2_unknown_old_source_data_is_not_created_outside_the_window(conn, fake):
    fake["events"] = [_ev("L2-C", "2189-01-15")]                            # 從沒跑過 1 月
    r = E.run(conn, "2189-03-01", "2189-03-31", "acc")
    conn.commit()
    assert r["stats"]["created"] == 0
    assert conn.execute("SELECT COUNT(*) FROM gl_source_events WHERE source_key='L2-C'").fetchone()[0] == 0     # 補登多年是 C8，不在這裡偷做


def test_l1_pending_changes_counts_new_changed_and_gone_without_writing(conn, fake):
    fake["events"] = [_ev("L1-A", "2189-05-10"), _ev("L1-B", "2189-05-11")]
    E.run(conn, "2189-05-01", "2189-05-31", "acc")
    conn.commit()
    before = conn.execute("SELECT COUNT(*) FROM gl_source_events").fetchone()[0]
    fake["events"] = [_ev("L1-A", "2189-05-10", amount=3000), _ev("L1-C", "2189-05-12")]         # A 變動、B 消失、C 新增
    p = E.pending_changes(conn, "2189-05-01", "2189-05-31")
    assert (p["new"], p["changed"], p["gone"], p["total"]) == (1, 1, 1, 3)
    assert conn.execute("SELECT COUNT(*) FROM gl_source_events").fetchone()[0] == before                # 唯讀


def test_l1_auto_run_only_runs_when_the_flag_is_on_and_records_the_result(conn, fake):
    F.set_flag(conn, "engine_drafts", False)
    conn.commit()
    n0 = conn.execute("SELECT COUNT(*) FROM gl_engine_runs").fetchone()[0]
    assert AR.run_once() == {"skipped": "off"}
    assert conn.execute("SELECT COUNT(*) FROM gl_engine_runs").fetchone()[0] == n0                   # 關著：什麼都不寫
    F.set_flag(conn, "engine_drafts", True)
    conn.commit()
    import datetime as dt
    fake["events"] = [_ev("L1-AUTO", dt.date.today().isoformat())]
    out = AR.run_once()
    assert out["ok"] is True and out["stats"]["created"] == 1
    st = AR.status(conn)
    assert st["auto_result"]["ok"] is True and st["auto_last"] and st["last_run"]["started_by"] == "auto"
    assert conn.execute("SELECT COUNT(*) FROM gl_engine_runs").fetchone()[0] == n0 + 1
    F.set_flag(conn, "engine_drafts", False)
    conn.commit()


def test_l1_auto_run_survives_a_crashing_engine_and_says_so(conn, fake, monkeypatch):
    F.set_flag(conn, "engine_drafts", True)
    conn.commit()
    monkeypatch.setattr(AR._engine, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = AR.run_once()
    assert out["ok"] is False and "boom" in out["error"]
    assert "boom" in AR.status(conn)["auto_result"]["error"]                # 失敗也留在畫面讀得到的地方
    F.set_flag(conn, "engine_drafts", False)
    conn.commit()


def test_l1_status_endpoint_needs_the_flag_and_reads_only(client, make_user, conn, fake):
    h = _login(client, make_user, "lg1")
    F.set_flag(conn, "engine_drafts", False)
    conn.commit()
    assert client.get("/api/ledger/engine/status", headers=h).status_code == 409
    F.set_flag(conn, "engine_drafts", True)
    conn.commit()
    r = client.get("/api/ledger/engine/status", headers=h)
    assert r.status_code == 200 and set(r.json()["pending"]) == {"new", "changed", "gone", "total"}
    F.set_flag(conn, "engine_drafts", False)
    conn.commit()


# ── L8：E01 與報表／E03 同口徑（案件降級後不再入帳）───────────────────────

import json  # noqa: E402
from datetime import datetime  # noqa: E402


def _quote(conn, no, deal="已成案"):
    data = {"quoteNo": no, "dealTag": deal, "caseRecord": {"payment": {"items": [
        {"id": "p1", "amount": 10500, "invoiceNo": "AB%s" % no[-8:], "invoiceDate": "2189-07-10"}]}}}
    now = datetime.now().isoformat()
    conn.execute("INSERT INTO quotations (quote_no, status, total, pretax, data_json, created_at, updated_at, customer_name, deal_tag) VALUES (?,?,?,?,?,?,?,?,?)",
                 (no, deal or "草稿", 10500, 10000, json.dumps(data, ensure_ascii=False), now, now, "甲公司", deal))
    conn.commit()


def _e01(no):
    from modules.arap.gl_events import gl_events
    res = gl_events("2189-07-01", "2189-07-31")
    return [e for e in res["events"] if e["event_code"] == "E01" and e["source_key"].startswith(no)], res["notice"]


def test_l8_e01_follows_the_deal_tag_like_the_report_and_e03(conn):
    _quote(conn, "MQ-L8-00000001")
    evs, notice = _e01("MQ-L8-00000001")
    assert len(evs) == 1 and "不是「已成案" not in notice
    conn.execute("UPDATE quotations SET deal_tag='', data_json=json_set(data_json,'$.dealTag','洽談中') WHERE quote_no='MQ-L8-00000001'")   # 案件降級
    conn.commit()
    evs, notice = _e01("MQ-L8-00000001")
    assert evs == [] and "不是「已成案／已結案」" in notice


def test_l8_closed_cases_still_count_and_the_column_wins_over_json(conn):
    _quote(conn, "MQ-L8-00000002", deal="已結案")
    assert len(_e01("MQ-L8-00000002")[0]) == 1
    conn.execute("UPDATE quotations SET deal_tag='已成案', data_json=json_set(data_json,'$.dealTag','洽談中') WHERE quote_no='MQ-L8-00000002'")   # 欄位優先於 JSON
    conn.commit()
    assert len(_e01("MQ-L8-00000002")[0]) == 1


def test_l8_a_posted_e01_of_a_downgraded_case_is_reversed_by_the_engine(conn):
    _quote(conn, "MQ-L8-00000003")
    E.run(conn, "2189-07-01", "2189-07-31", "acc")
    conn.commit()
    vid = conn.execute("SELECT voucher_id FROM gl_source_events WHERE source_key LIKE 'MQ-L8-00000003%' AND event_code='E01'").fetchone()[0]
    conn.execute("UPDATE vouchers_all SET status='已核准' WHERE id=?", (vid,))
    conn.execute("UPDATE vouchers_all SET status='已過帳' WHERE id=?", (vid,))
    conn.execute("UPDATE quotations SET deal_tag='', data_json=json_set(data_json,'$.dealTag','洽談中') WHERE quote_no='MQ-L8-00000003'")
    conn.commit()
    r = E.run(conn, "2189-07-01", "2189-07-31", "acc")
    conn.commit()
    row = conn.execute("SELECT status, reversal_voucher_id FROM gl_source_events WHERE source_key LIKE 'MQ-L8-00000003%' AND event_code='E01'").fetchone()
    assert row["status"] == "orphan" and row["reversal_voucher_id"] and r["stats"]["orphans"] >= 1


# ── voucher.draft(reverses_voucher_id)：獎金更正單的反向草稿 ─────────────────

def _prov():
    from modules.accounting.api.voucher_providers import _provide_voucher_draft
    return _provide_voucher_draft


def test_reversal_draft_mirrors_a_posted_voucher_and_is_marked(conn):
    vid, no = _voucher(conn, status="已過帳", date="2189-08-10")
    r = _prov()(conn, summary="更正", created_by="w2", now="2189-08-11T09:00:00", origin="bonus_correction", reverses_voucher_id=vid, voucher_date="2189-08-11")
    conn.commit()
    assert set(r) == {"id", "voucher_no"}
    v = conn.execute("SELECT kind, reverses_no, origin, status, voucher_date FROM vouchers_all WHERE id=?", (r["id"],)).fetchone()
    assert (v["kind"], v["reverses_no"], v["origin"], v["status"], v["voucher_date"]) == ("reversal", no, "bonus_correction", "草稿", "2189-08-11")
    got = [(l["account_code"], l["debit"], l["credit"]) for l in conn.execute("SELECT * FROM voucher_lines WHERE voucher_id=? ORDER BY line_no", (r["id"],))]
    assert got == [("1113", 0, 10), ("4111", 10, 0)]                              # 原：借1113/貸4111 ⇒ 互換


def test_reversal_draft_refusals_return_a_reason_instead_of_raising(conn):
    draft, _ = _voucher(conn, status="草稿", date="2189-08-12")
    assert "只有已過帳" in _prov()(conn, summary="x", created_by="w2", now="n", reverses_voucher_id=draft)["blocked"]
    voided, _ = _voucher(conn, status="已過帳", voided=True, date="2189-08-12")
    assert "作廢" in _prov()(conn, summary="x", created_by="w2", now="n", reverses_voucher_id=voided)["blocked"]
    assert "不存在" in _prov()(conn, summary="x", created_by="w2", now="n", reverses_voucher_id=99999999)["blocked"]
    posted, _ = _voucher(conn, status="已過帳", date="2189-08-13")
    first = _prov()(conn, summary="x", created_by="w2", now="2189-08-14T00:00:00", reverses_voucher_id=posted, voucher_date="2189-08-14")
    assert "id" in first
    assert "已經有沖轉" in _prov()(conn, summary="x", created_by="w2", now="2189-08-14T00:00:00", reverses_voucher_id=posted, voucher_date="2189-08-14")["blocked"]


def test_reversal_into_a_closed_period_is_blocked(conn):
    from modules.accounting.ledger import periods as P
    P.create_year(conn, 2188, "t")
    conn.commit()
    posted, _ = _voucher(conn, status="已過帳", date="2188-03-10")
    pid = conn.execute("SELECT id FROM gl_periods WHERE year=2188 AND period_no=3").fetchone()[0]
    P.close_period(conn, pid, "t", True, "")
    conn.commit()
    r = _prov()(conn, summary="x", created_by="w2", now="2188-03-20T00:00:00", reverses_voucher_id=posted, voucher_date="2188-03-20")
    assert "blocked" in r and "重開" in r["blocked"]


def test_engine_ignores_a_native_row_after_its_reversal_posts(conn, fake):
    """W2 的問題(2)：原傳票是 native 登記；沖轉傳票過帳後跑引擎 ⇒ 不產生新草稿、native 列狀態不變。"""
    vid, no = _voucher(conn, status="已過帳", date="2189-09-05")
    ev = {"source_type": "bonus_award", "source_key": "BON-NAT-1", "event_code": "E07b", "event_date": "2189-09-05", "doc_no": "BON-NAT-1", "case_no": "",
          "party": {"key": "", "name": ""}, "tax_code": "", "mode": "native", "native_voucher_id": vid, "meta": {}}
    fake["events"] = [ev]
    E.run(conn, "2189-09-01", "2189-09-30", "acc")
    conn.commit()
    assert conn.execute("SELECT status FROM gl_source_events WHERE source_key='BON-NAT-1'").fetchone()[0] == "native"
    r = _prov()(conn, summary="更正", created_by="w2", now="2189-09-20T00:00:00", reverses_voucher_id=vid, voucher_date="2189-09-20")
    conn.execute("UPDATE vouchers_all SET status='已核准' WHERE id=?", (r["id"],))
    conn.execute("UPDATE vouchers_all SET status='已過帳' WHERE id=?", (r["id"],))
    conn.commit()
    n0 = conn.execute("SELECT COUNT(*) FROM vouchers_all WHERE kind='auto'").fetchone()[0]
    res = E.run(conn, "2189-09-01", "2189-09-30", "acc")
    conn.commit()
    rows = conn.execute("SELECT status, rev FROM gl_source_events WHERE source_key='BON-NAT-1'").fetchall()
    assert [(x[0], x[1]) for x in rows] == [("native", 1)] and res["stats"]["orphans"] == 0 and res["stats"]["drift"] == 0
    assert conn.execute("SELECT COUNT(*) FROM vouchers_all WHERE kind='auto'").fetchone()[0] == n0
