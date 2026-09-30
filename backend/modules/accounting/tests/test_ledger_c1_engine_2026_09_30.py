# -*- coding: utf-8 -*-
"""總帳 C1 · 分錄引擎（proposal-gl/02-events-engine.md）＋ arap 銷項／收款事件提供者。

引擎：冪等、草稿可重建、已過帳不動（drift＋反向草稿）、來源消失（orphan）、期間已結帳／缺科目（blocked）、使用者作廢草稿不再重建（rejected）。
提供者：E01 開立發票、E03 收款（W2 語意：實收＋手續費＝含稅收入）、先收款後開票的預收沖轉。
反向控制：來源模組壞掉不可把它的事件誤判成 orphan；沒有提供者時明說；旗標關閉時 API 擋下。
"""
import json
from datetime import datetime

import pytest

import db
from core import registry
from modules.accounting.ledger import contract as C
from modules.accounting.ledger import engine as E
from modules.accounting.ledger import periods as P
from modules.accounting.ledger import reports as R
from modules.accounting.ledger import roles as ROLES

_N = [0]


@pytest.fixture
def conn(client):
    c = db.get_db()
    ROLES.ensure_meta(c)
    ROLES.ensure_default_roles(c)
    c.commit()
    yield c
    c.close()


@pytest.fixture
def fake(monkeypatch):
    """只保留本題登記的 gl.events 提供者（鍵 fake）；回傳 (設定事件清單的函式, 讓提供者丟例外的函式)。"""
    monkeypatch.setattr(registry, "_LEGACY_PROVIDERS", {})
    monkeypatch.setattr(registry, "_LOADED", {})
    state = {"events": [], "boom": False}

    def provider(start, end, changed_since=""):
        if state["boom"]:
            raise RuntimeError("壞了")
        return {"events": list(state["events"])}
    registry._LEGACY_PROVIDERS[("gl.events", "fake")] = provider
    return state


def _ev(key, date="2170-05-10", pretax=1000, tax=50, **kw):
    e = {"source_type": "t_invoice", "source_key": key, "event_code": "E01", "event_date": date, "doc_no": "AB1234%04d" % (hash(key) % 10000),
         "case_no": "Q-" + key, "party": {"key": "12345678", "name": "甲公司"}, "tax_code": "OUT-5",
         "lines": [{"role": "AR", "side": "D", "amount": pretax + tax}, {"role": "REV_SALES", "side": "C", "amount": pretax},
                   {"role": "OUTPUT_TAX", "side": "C", "amount": tax}]}
    e.update(kw)
    return e


def _run(conn, start="2170-05-01", end="2170-05-31"):
    r = E.run(conn, start, end, "acc")
    conn.commit()
    return r


def _events(conn, key=None):
    q = "SELECT * FROM gl_source_events" + (" WHERE source_key=?" if key else "") + " ORDER BY id"
    return [dict(r) for r in conn.execute(q, (key,) if key else ())]


def _voucher(conn, vid):
    return dict(conn.execute("SELECT * FROM vouchers_all WHERE id=?", (vid,)).fetchone())


def _lines(conn, vid):
    return [dict(r) for r in conn.execute("SELECT * FROM voucher_lines WHERE voucher_id=? ORDER BY line_no", (vid,))]


def _post(conn, vid):
    conn.execute("UPDATE vouchers_all SET status='已過帳' WHERE id=?", (vid,))
    conn.commit()


# ── 引擎：建立、冪等、維度 ────────────────────────────────────────────────

def test_first_run_makes_a_balanced_draft_with_dimensions(conn, fake):
    fake["events"] = [_ev("k1")]
    r = _run(conn)
    assert r["stats"]["created"] == 1 and r["sources"]["fake"] == "ok"
    (row,) = _events(conn, "k1")
    assert row["status"] == "drafted" and row["rev"] == 1 and row["amount"] == 1050
    v = _voucher(conn, row["voucher_id"])
    assert (v["kind"], v["origin"], v["status"], v["gl_event_id"], v["voucher_date"]) == ("auto", "gl:E01", "草稿", row["id"], "2170-05-10")
    assert len(v["summary"]) <= 60
    ls = _lines(conn, v["id"])
    assert [(l["account_code"], l["debit"], l["credit"]) for l in ls] == [("1191", 1050, 0), ("4111", 0, 1000), ("2204", 0, 50)]
    assert all((l["case_no"], l["party_key"], l["tax_code"]) == ("Q-k1", "12345678", "OUT-5") for l in ls) and ls[0]["doc_no"] == v["summary"].split()[0]


def test_rerun_is_idempotent(conn, fake):
    fake["events"] = [_ev("k1"), _ev("k2", pretax=200, tax=10)]
    _run(conn)
    n = conn.execute("SELECT COUNT(*) FROM vouchers_all WHERE kind='auto'").fetchone()[0]
    r = _run(conn)
    assert r["stats"]["created"] == 0 and r["stats"]["scanned"] == 2
    assert conn.execute("SELECT COUNT(*) FROM vouchers_all WHERE kind='auto'").fetchone()[0] == n
    assert len(_events(conn)) == 2


def test_account_code_override_and_missing_role_and_bad_account(conn, fake):
    e = _ev("k1")
    e["lines"][0]["account_code"] = "1113"                                                  # 明指銀行科目
    fake["events"] = [e]
    _run(conn)
    assert _lines(conn, _events(conn, "k1")[0]["voucher_id"])[0]["account_code"] == "1113"
    bad = _ev("k2")
    bad["lines"][0]["account_code"] = "9999"
    fake["events"] = [bad]
    _run(conn)
    row = _events(conn, "k2")[0]
    assert row["status"] == "blocked_no_account" and "9999" in row["note"] and row["voucher_id"] is None
    conn.execute("DELETE FROM gl_account_roles WHERE role='REV_SALES'")
    conn.execute("INSERT INTO gl_account_roles(role,scope_type,scope_key,account_code,effective_from) VALUES ('REV_SALES','','','4111','2999-01-01')")
    conn.commit()
    fake["events"] = [_ev("k3")]
    _run(conn)
    assert _events(conn, "k3")[0]["status"] == "blocked_no_account" and "REV_SALES" in _events(conn, "k3")[0]["note"]
    conn.execute("DELETE FROM gl_account_roles WHERE role='REV_SALES'")
    conn.commit()
    ROLES.ensure_default_roles(conn)
    conn.commit()
    _run(conn)
    assert _events(conn, "k3")[0]["status"] == "drafted"                                    # 補好角色後同一列事件自動放行


# ── 引擎：來源事後被改 ────────────────────────────────────────────────────

def test_changed_source_while_draft_replaces_the_draft(conn, fake):
    fake["events"] = [_ev("k1")]
    _run(conn)
    old = _events(conn, "k1")[0]
    fake["events"] = [_ev("k1", pretax=2000, tax=100)]
    r = _run(conn)
    assert r["stats"]["superseded"] == 1 and r["stats"]["created"] == 1 and r["stats"]["drift"] == 0
    rows = _events(conn, "k1")
    assert [(x["rev"], x["status"]) for x in rows] == [(1, "superseded"), (2, "drafted")] and rows[1]["supersedes_id"] == old["id"]
    assert _voucher(conn, old["voucher_id"])["voided_at"] != ""                             # 舊草稿作廢
    assert _lines(conn, rows[1]["voucher_id"])[0]["debit"] == 2100


def test_changed_source_after_posting_makes_drift_reversal_and_new_draft(conn, fake):
    fake["events"] = [_ev("k1")]
    _run(conn)
    old = _events(conn, "k1")[0]
    _post(conn, old["voucher_id"])
    fake["events"] = [_ev("k1", pretax=2000, tax=100)]
    r = _run(conn)
    assert r["stats"]["drift"] == 1 and r["stats"]["reversals"] == 1
    o, n = _events(conn, "k1")
    assert o["status"] == "drift" and o["reversal_voucher_id"] and n["rev"] == 2 and n["status"] == "drafted"
    assert _voucher(conn, old["voucher_id"])["status"] == "已過帳" and _voucher(conn, old["voucher_id"])["voided_at"] == ""    # 已過帳的舊傳票原封不動
    rv = _voucher(conn, o["reversal_voucher_id"])
    assert (rv["kind"], rv["status"], rv["reverses_no"]) == ("reversal", "草稿", _voucher(conn, old["voucher_id"])["voucher_no"])
    assert [(l["account_code"], l["debit"], l["credit"]) for l in _lines(conn, rv["id"])] == [("1191", 0, 1050), ("4111", 1000, 0), ("2204", 50, 0)]   # 借貸對調
    _post(conn, rv["id"])
    E.sync_statuses(conn)
    assert _events(conn, "k1")[0]["status"] == "reversed"


def test_source_that_vanishes_is_orphaned_but_only_when_its_source_answered(conn, fake):
    fake["events"] = [_ev("k1"), _ev("k2", pretax=100, tax=5)]
    _run(conn)
    e1, e2 = _events(conn, "k1")[0], _events(conn, "k2")[0]
    _post(conn, e2["voucher_id"])
    fake["boom"] = True                                                                     # 反向控制：提供者壞了 ⇒ 不可把事件誤判成消失
    r = _run(conn)
    assert r["sources"]["fake"] == "error" and r["stats"]["orphans"] == 0
    assert [x["status"] for x in _events(conn)] == ["drafted", "posted"]
    fake["boom"] = False
    fake["events"] = []                                                                     # 來源正常回應但已沒有這兩筆
    r = _run(conn)
    assert r["stats"]["orphans"] == 2
    a, b = _events(conn, "k1")[0], _events(conn, "k2")[0]
    assert a["status"] == "orphan" and _voucher(conn, e1["voucher_id"])["voided_at"] != ""   # 草稿直接作廢
    assert b["status"] == "orphan" and b["reversal_voucher_id"]                              # 已過帳者產生反向草稿


def test_voucher_voided_by_the_accountant_is_not_recreated(conn, fake):
    fake["events"] = [_ev("k1")]
    _run(conn)
    e = _events(conn, "k1")[0]
    conn.execute("UPDATE vouchers_all SET voided_at='n', voided_by='acc', void_reason='不要' WHERE id=?", (e["voucher_id"],))
    conn.commit()
    r = _run(conn)
    assert _events(conn, "k1")[0]["status"] == "rejected" and r["stats"]["created"] == 0
    assert conn.execute("SELECT COUNT(*) FROM vouchers_all WHERE gl_event_id=?", (e["id"],)).fetchone()[0] == 1
    fake["events"] = [_ev("k1", pretax=5000, tax=250)]                                      # 但來源內容又變了 ⇒ 是新內容，重新產生新版本
    _run(conn)
    assert [x["rev"] for x in _events(conn, "k1")] == [1, 2]


# ── 引擎：期間鎖定 ────────────────────────────────────────────────────────

def test_closed_period_blocks_then_reopening_releases(conn, fake):
    P.create_year(conn, 2171, "t")
    conn.commit()
    pid = conn.execute("SELECT id FROM gl_periods WHERE year=2171 AND period_no=3").fetchone()[0]
    P.close_period(conn, pid, "acc", accept_warnings=True)
    conn.commit()
    fake["events"] = [_ev("k1", date="2171-03-10")]
    r = _run(conn, "2171-03-01", "2171-03-31")
    row = _events(conn, "k1")[0]
    assert row["status"] == "blocked_closed" and row["voucher_id"] is None and r["stats"]["blocked"] == 1 and "結帳" in row["note"]
    P.reopen_period(conn, pid, "acc", "補帳")
    conn.commit()
    _run(conn, "2171-03-01", "2171-03-31")
    row = _events(conn, "k1")[0]
    assert row["status"] == "drafted" and row["rev"] == 1 and len(_events(conn, "k1")) == 1


def test_drift_reversal_dated_in_a_closed_period_says_to_reverse_by_hand(conn, fake, monkeypatch):
    fake["events"] = [_ev("k1")]
    _run(conn)
    old = _events(conn, "k1")[0]
    _post(conn, old["voucher_id"])
    monkeypatch.setattr(P, "lock_error", lambda c, d: "已結帳" if d == datetime.now().date().isoformat() else None)   # 今天所在期間已結帳
    fake["events"] = [_ev("k1", pretax=2000, tax=100)]
    _run(conn)
    o = _events(conn, "k1")[0]
    assert o["status"] == "drift" and o["reversal_voucher_id"] is None and "手工沖轉" in o["note"]


# ── 事件清單、API、整批確認 ───────────────────────────────────────────────

def _login(client, make_user, username, role="superadmin", modules=("finance",)):
    u, p = make_user(username=username, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_api_is_gated_by_the_feature_flag_and_batch_posts_only_engine_vouchers(client, make_user, conn, fake):
    hdr = _login(client, make_user, "gl_c1_a")
    fin = _login(client, make_user, "gl_c1_fin", role="staff", modules=("finance",))
    none = _login(client, make_user, "gl_c1_none", role="staff", modules=())
    body = {"start": "2170-05-01", "end": "2170-05-31"}
    assert client.post("/api/ledger/engine/run", headers=hdr, json=body).status_code == 409           # 旗標預設關
    assert client.get("/api/ledger/engine/events", headers=hdr).status_code == 409
    assert client.put("/api/ledger/features/engine_drafts", headers=hdr, json={"enabled": True}).status_code == 200
    assert client.post("/api/ledger/engine/run", headers=none, json=body).status_code == 403
    assert client.post("/api/ledger/engine/run", headers=hdr, json={"start": "x", "end": "y"}).status_code == 400
    fake["events"] = [_ev("k1"), _ev("k2", pretax=10, tax=0)]
    r = client.post("/api/ledger/engine/run", headers=fin, json=body)
    assert r.status_code == 200 and r.json()["stats"]["created"] == 2, r.text
    ev = client.get("/api/ledger/engine/events", headers=fin).json()
    assert ev["counts"] == {"drafted": 2} and {e["voucher_status"] for e in ev["events"]} == {"草稿"}
    ids = [e["voucher_id"] for e in ev["events"]]
    manual = client.post("/api/vouchers", headers=hdr, json={"summary": "手工", "lines": [{"account_code": "1113", "debit": 1}, {"account_code": "4111", "credit": 1}]}).json()["id"]
    r = client.post("/api/ledger/engine/batch", headers=hdr, json={"voucher_ids": ids + [manual], "action": "all"}).json()
    assert r["ok"] == 2 and r["failed"] == 1 and "不是引擎產生" in [x for x in r["results"] if x["id"] == manual][0]["error"]
    assert {x["status"] for x in r["results"] if x["ok"]} == {"已過帳"}                                 # 送審→核准到底→過帳
    ev = client.get("/api/ledger/engine/events", headers=fin).json()
    assert ev["counts"] == {"posted": 2}                                                              # 事件狀態同步回 posted
    assert client.post("/api/ledger/engine/batch", headers=hdr, json={"voucher_ids": [], "action": "all"}).status_code == 400
    assert client.post("/api/ledger/engine/batch", headers=hdr, json={"voucher_ids": ids, "action": "nope"}).status_code == 400
    runs = client.get("/api/ledger/engine/runs", headers=fin).json()["runs"]
    assert runs and runs[0]["created"] == 2
    assert conn.execute("SELECT COUNT(*) FROM gl_confirm_batches").fetchone()[0] == 1


# ── arap 提供者：銷項發票與收款 ───────────────────────────────────────────

def _quote(conn, no, items, total=10500, pretax=10000, **extra):
    data = {"quoteNo": no, "dealTag": "已成案", "caseRecord": {"payment": {"items": items}}}
    data.update(extra)
    now = datetime.now().isoformat()
    conn.execute("INSERT INTO quotations (quote_no, status, total, pretax, data_json, created_at, updated_at, customer_name) VALUES (?,?,?,?,?,?,?,?)",
                 (no, "已成案", total, pretax, json.dumps(data, ensure_ascii=False), now, now, "甲公司"))
    conn.commit()


def _arap(conn, start="2170-09-01", end="2170-09-30"):
    from modules.arap.gl_events import gl_events
    return gl_events(start, end)


def _by(res, code, key_part=""):
    return [e for e in res["events"] if e["event_code"] == code and key_part in e["source_key"]]


def _sum(ev, side):
    return sum(l["amount"] for l in ev["lines"] if l["side"] == side)


def test_arap_invoice_and_receipt_with_fee(conn):
    _quote(conn, "MQ-C1-A", [{"id": "p1", "type": "全額", "amount": 10500, "invoiceNo": "AB12345678", "invoiceDate": "2170-09-10",
                              "received": True, "receivedAt": "2170-09-15", "actualAmount": 10485, "feeAmount": 15, "bankAccountCode": "1113"}])
    res = _arap(conn)
    (inv,) = _by(res, "E01", "MQ-C1-A")
    assert (inv["event_date"], inv["doc_no"], inv["tax_code"], inv["source_key"]) == ("2170-09-10", "AB12345678", "OUT-5", "MQ-C1-A::AB12345678")
    assert [(l["role"], l["side"], l["amount"]) for l in inv["lines"]] == [("AR", "D", 10500), ("REV_SALES", "C", 10000), ("OUTPUT_TAX", "C", 500)]
    (rec,) = _by(res, "E03", "MQ-C1-A")
    assert rec["source_key"] == "MQ-C1-A::p1" and rec["event_date"] == "2170-09-15"
    got = [(l["role"], l["side"], l["amount"]) for l in rec["lines"]]
    assert got == [("BANK", "D", 10485), ("FEE", "D", 15), ("AR", "C", 10500)]                        # 實收＋手續費＝含稅收入，貸應收
    assert rec["lines"][0]["account_code"] == "1113"
    for e in (inv, rec):
        assert _sum(e, "D") == _sum(e, "C") and C.validate_event(e) == []
    assert not res["notice"]


def test_arap_receipt_before_invoice_uses_advance_and_reclass(conn):
    _quote(conn, "MQ-C1-B", [{"id": "p1", "amount": 10500, "invoiceNo": "AB00000001", "invoiceDate": "2170-09-20",
                              "received": True, "receivedAt": "2170-09-05", "actualAmount": 10500}])
    res = _arap(conn)
    (rec,) = _by(res, "E03", "MQ-C1-B")
    assert rec["lines"][-1]["role"] == "ADV_RCPT" and rec["meta"]["advance"] is True             # 收款時還沒開票 ⇒ 預收貨款
    (inv,) = _by(res, "E01", "MQ-C1-B")
    roles = [(l["role"], l["side"], l["amount"]) for l in inv["lines"]]
    assert ("ADV_RCPT", "D", 10500) in roles and ("AR", "C", 10500) in roles                    # 開票時沖轉預收
    assert _sum(inv, "D") == _sum(inv, "C")


def test_arap_receipt_without_invoice_is_advance_and_has_no_e01(conn):
    _quote(conn, "MQ-C1-C", [{"id": "p1", "amount": 10500, "received": True, "receivedAt": "2170-09-07", "actualAmount": 10500}])
    res = _arap(conn)
    assert _by(res, "E01", "MQ-C1-C") == [] and _by(res, "E03", "MQ-C1-C")[0]["lines"][-1]["role"] == "ADV_RCPT"


def test_arap_date_windows_and_zero_tax_code(conn):
    _quote(conn, "MQ-C1-D", [{"id": "p1", "amount": 10000, "invoiceNo": "AB00000002", "invoiceDate": "2170-08-30"}],
           total=10000, pretax=10000, taxType="zero")
    assert _by(_arap(conn), "E01", "MQ-C1-D") == []                                                # 8 月開的不在 9 月窗
    res = _arap(conn, "2170-08-01", "2170-08-31")
    (inv,) = _by(res, "E01", "MQ-C1-D")
    assert inv["tax_code"] == "OUT-0" and [l["role"] for l in inv["lines"]] == ["AR", "REV_SALES"]     # 零稅率：沒有銷項稅額行


def test_arap_notices_are_honest_about_weak_keys_missing_dates_and_differences(conn):
    _quote(conn, "MQ-C1-E", [{"amount": 10500, "invoiceNo": "AB00000003", "received": True, "receivedAt": "2170-09-12", "actualAmount": 10000}])
    res = _arap(conn)
    n = res["notice"]
    assert "沒有填開立日期" in n and "沒有不可變的 id" in n and "不一致" in n
    (rec,) = _by(res, "E03", "MQ-C1-E")
    assert rec["source_key"].endswith("::idx0") and rec["meta"]["weak_key"] is True
    assert _sum(rec, "D") == _sum(rec, "C") == 10000                                                # 只沖實收；差額留在應收餘額，不自行沖


def test_engine_with_the_real_arap_provider_end_to_end(conn):
    """不用 fake：走真的 registry 上的 arap 提供者 ⇒ 草稿 ⇒ 試算表（含草稿）看得到應收與收入。"""
    _quote(conn, "MQ-C1-F", [{"id": "p1", "amount": 10500, "invoiceNo": "AB00000004", "invoiceDate": "2170-09-10",
                              "received": True, "receivedAt": "2170-09-15", "actualAmount": 10485, "feeAmount": 15}])
    r = E.run(conn, "2170-09-01", "2170-09-30", "acc")
    conn.commit()
    assert r["sources"]["arap"] == "ok" and r["stats"]["created"] >= 2
    tb = R.trial_balance(conn, "2170-09-01", "2170-09-30", include_drafts=True)
    rows = {x["code"]: x for x in tb["rows"]}
    assert rows["1191"]["period_debit"] >= 10500 and rows["1191"]["period_credit"] >= 10500 and rows["4111"]["period_credit"] >= 10000
    assert rows["7243"]["period_debit"] >= 15 and tb["balanced"]
    again = E.run(conn, "2170-09-01", "2170-09-30", "acc")
    assert again["stats"]["created"] == 0                                                           # 冪等
