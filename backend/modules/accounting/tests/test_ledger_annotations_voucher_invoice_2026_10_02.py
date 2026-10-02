# -*- coding: utf-8 -*-
"""31-B S4 補（da 稽核）：分期申請的逐張發票 E04（source_type=contractor_voucher_invoice）也能在『來源憑證補登』補登實際進項稅額與發票日，
畫面有白話名稱。引擎套用補登（contract.apply_annotations）本來就以 (source_type, source_key) 查，這裡只是把新來源類型放進 API 的可補登清單。
反向控制：把新類型拿出 ALLOWED ⇒ PUT 回 400（見最後一題）。"""
import json

import pytest

import db
from core import registry
from modules.accounting.api import ledger_annotations as LA
from modules.accounting.ledger import engine as E
from modules.accounting.ledger import features as F
from modules.accounting.ledger import roles as ROLES

_N = [0]


@pytest.fixture
def conn(client):
    c = db.get_db()
    ROLES.ensure_meta(c)
    ROLES.ensure_default_roles(c)
    F.set_flag(c, "source_annotations", True)
    c.commit()
    yield c
    c.close()


def _login(client, make_user, name):
    u, p = make_user(username="%s%d" % (name, id(client)), role="superadmin")
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(registry, "_LEGACY_PROVIDERS", {})
    monkeypatch.setattr(registry, "_LOADED", {})
    state = {"events": []}
    registry._LEGACY_PROVIDERS[("gl.events", "fake")] = lambda s, e, changed_since="": {"events": list(state["events"])}
    return state


def _e04_installment(date="2182-03-10"):
    _N[0] += 1
    return {"source_type": "contractor_voucher_invoice", "source_key": "PV-RKA-%d-%d" % (id(_N), _N[0]), "event_code": "E04", "event_date": date,
            "doc_no": "ZZ%08d" % _N[0], "case_no": "", "party": {"key": "12345678", "name": "甲"}, "tax_code": "IN-5", "mode": "snapshot",
            "lines": [{"role": "COST_PROJECT", "side": "D", "amount": 10000}, {"role": "INPUT_TAX", "side": "D", "amount": 500}, {"role": "AP", "side": "C", "amount": 10500}],
            "meta": {"tax_estimated": True, "remit_kind": "deposit", "seq": 1}}


def test_installment_invoice_e04_can_be_annotated_and_the_engine_applies_it(client, conn, fake, make_user):
    h = _login(client, make_user, "rka_a")
    ev = _e04_installment()
    fake["events"] = [ev]
    E.run(conn, "2182-03-01", "2182-03-31", "acc")
    conn.commit()
    (it,) = [i for i in client.get("/api/ledger/annotations/pending", headers=h).json()["items"] if i["source_key"] == ev["source_key"]]
    assert it["kind"] == "estimated" and it["can_date"] is True and it["event_code"] == "E04"
    assert it["source_label"] == "承攬商分期申請 " + ev["source_key"] and it["event_label"] == "承攬商發票"
    put = lambda field, value: client.put("/api/ledger/annotations", headers=h, json={"source_type": "contractor_voucher_invoice", "source_key": ev["source_key"], "field": field, "value": value})
    assert put("input_tax", "480").status_code == 200 and put("invoice_date", "2182-03-12").status_code == 200
    E.run(conn, "2182-03-01", "2182-03-31", "acc")
    conn.commit()
    payload = json.loads(conn.execute("SELECT payload_json FROM gl_source_events WHERE source_key=? ORDER BY rev DESC LIMIT 1", (ev["source_key"],)).fetchone()[0])
    lines = [(l["role"], l["side"], l["amount"]) for l in payload["lines"]]
    assert ("INPUT_TAX", "D", 480) in lines and ("AP", "C", 10480) in lines and payload["event_date"] == "2182-03-12"


def test_reverse_control_a_type_outside_the_allowed_list_is_refused(client, conn, monkeypatch, make_user):
    h = _login(client, make_user, "rka_b")
    monkeypatch.setattr(LA, "ALLOWED", {k: v for k, v in LA.ALLOWED.items() if k != "contractor_voucher_invoice"})
    r = client.put("/api/ledger/annotations", headers=h, json={"source_type": "contractor_voucher_invoice", "source_key": "PV-1", "field": "input_tax", "value": "480"})
    assert r.status_code == 400
