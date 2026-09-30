# -*- coding: utf-8 -*-
"""來源憑證補登 API（旗標 source_annotations）：驗證、新增／修改／刪除（稽核含舊值）、權限（讀＝出納／財務、寫＝財務）、
待補登清單（稅額估計／未拆稅的事件）、補登後引擎重建草稿並套用補登值。
"""
import json

import pytest

import db
from core import registry
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


def _login(client, make_user, name, role="superadmin", modules=None):
    kw = {"role": role}
    if modules is not None:
        kw["modules"] = modules
    u, p = make_user(username="%s%d" % (name, id(client)), **kw)
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(registry, "_LEGACY_PROVIDERS", {})
    monkeypatch.setattr(registry, "_LOADED", {})
    state = {"events": []}
    registry._LEGACY_PROVIDERS[("gl.events", "fake")] = lambda s, e, changed_since="": {"events": list(state["events"])}
    return state


def _e04(key=None, date="2182-03-10"):
    _N[0] += 1
    key = key or "D-%d-%d" % (id(_N), _N[0])
    return {"source_type": "contractor_dispatch", "source_key": key, "event_code": "E04", "event_date": date, "doc_no": "ZZ%08d" % _N[0], "case_no": "",
            "party": {"key": "12345678", "name": "甲"}, "tax_code": "IN-5", "mode": "snapshot",
            "lines": [{"role": "COST_PROJECT", "side": "D", "amount": 10000}, {"role": "INPUT_TAX", "side": "D", "amount": 500}, {"role": "AP", "side": "C", "amount": 10500}],
            "meta": {"tax_estimated": True}}


def test_flag_off_is_409_and_validation_messages(client, conn, make_user):
    h = _login(client, make_user, "an_a")
    F.set_flag(conn, "source_annotations", False)
    conn.commit()
    assert client.get("/api/ledger/annotations", headers=h).status_code == 409
    F.set_flag(conn, "source_annotations", True)
    conn.commit()
    put = lambda **kw: client.put("/api/ledger/annotations", headers=h, json=dict({"source_type": "contractor_dispatch", "source_key": "1", "field": "input_tax", "value": "480"}, **kw))
    assert put(source_type="nope").status_code == 400
    assert put(field="invoice_date", source_type="case_extra_expense", value="2182-01-01").status_code == 400          # 額外支出只能補稅額
    assert put(value="-5").status_code == 400 and put(value="1.5").status_code == 400 and put(value="abc").status_code == 400 and put(value="").status_code == 400
    assert put(field="invoice_date", value="2182-13-40").status_code == 400
    assert put(source_key="  ").status_code == 400 and put(source_key="x" * 121).status_code == 400
    assert put().status_code == 200


def test_put_update_delete_with_audit_and_previous_value(client, conn, make_user):
    h = _login(client, make_user, "an_b")
    body = {"source_type": "stock_batch_invoice", "source_key": "PO-1", "field": "input_tax", "value": "140"}
    r1 = client.put("/api/ledger/annotations", headers=h, json=body).json()
    assert r1["previous"] is None and r1["value"] == "140"
    r2 = client.put("/api/ledger/annotations", headers=h, json=dict(body, value=" 150 ")).json()
    assert r2["previous"] == "140" and r2["value"] == "150"
    rows = client.get("/api/ledger/annotations?source_type=stock_batch_invoice", headers=h).json()["annotations"]
    assert [(x["source_key"], x["field"], x["value"]) for x in rows] == [("PO-1", "input_tax", "150")]
    assert client.delete("/api/ledger/annotations/%d" % rows[0]["id"], headers=h).status_code == 200
    assert client.delete("/api/ledger/annotations/%d" % rows[0]["id"], headers=h).status_code == 404
    c = db.get_db()
    try:
        acts = [r[0] for r in c.execute("SELECT target_label FROM audit_log WHERE action IN ('ledger.annotation.put','ledger.annotation.delete') ORDER BY id")]
    finally:
        c.close()
    assert any("原值：140" in a for a in acts) and any("刪除補登" in a for a in acts)


def test_permissions_cashier_reads_finance_writes_others_denied(client, conn, make_user):
    cashier = _login(client, make_user, "an_c", role="staff", modules=("cashier",))
    finance = _login(client, make_user, "an_f", role="staff", modules=("finance",))
    none = _login(client, make_user, "an_n", role="staff", modules=())
    body = {"source_type": "contractor_dispatch", "source_key": "9", "field": "input_tax", "value": "10"}
    assert client.get("/api/ledger/annotations", headers=cashier).status_code == 200
    assert client.put("/api/ledger/annotations", headers=cashier, json=body).status_code == 403
    assert client.put("/api/ledger/annotations", headers=finance, json=body).status_code == 200
    assert client.get("/api/ledger/annotations", headers=none).status_code == 403
    assert client.get("/api/ledger/annotations/pending", headers=none).status_code == 403


def test_pending_lists_estimated_events_and_annotation_rebuilds_the_draft(client, conn, fake, make_user):
    h = _login(client, make_user, "an_d")
    ev = _e04()
    fake["events"] = [ev]
    E.run(conn, "2182-03-01", "2182-03-31", "acc")
    conn.commit()
    items = client.get("/api/ledger/annotations/pending", headers=h).json()["items"]
    (it,) = [i for i in items if i["source_key"] == ev["source_key"]]
    assert it["kind"] == "estimated" and it["input_tax"] == "" and it["can_date"] is True and it["event_code"] == "E04"
    assert client.put("/api/ledger/annotations", headers=h, json={"source_type": it["source_type"], "source_key": it["source_key"], "field": "input_tax", "value": "480"}).status_code == 200
    r = E.run(conn, "2182-03-01", "2182-03-31", "acc")
    conn.commit()
    assert r["stats"]["superseded"] >= 1 or r["stats"]["created"] >= 1                          # 內容變了 ⇒ 未過帳草稿重建
    lines = [(l["role"], l["side"], l["amount"]) for l in json.loads(conn.execute(
        "SELECT payload_json FROM gl_source_events WHERE source_key=? ORDER BY rev DESC LIMIT 1", (ev["source_key"],)).fetchone()[0])["lines"]]
    assert ("INPUT_TAX", "D", 480) in lines and ("AP", "C", 10480) in lines
    (it2,) = [i for i in client.get("/api/ledger/annotations/pending", headers=h).json()["items"] if i["source_key"] == ev["source_key"]]
    assert it2["kind"] == "annotated" and it2["input_tax"] == "480" and it2["input_tax_id"]
    assert client.delete("/api/ledger/annotations/%d" % it2["input_tax_id"], headers=h).status_code == 200


def test_pending_ignores_events_with_exact_tax(client, conn, fake, make_user):
    h = _login(client, make_user, "an_e")
    ev = _e04()
    ev["meta"] = {}
    fake["events"] = [ev]
    E.run(conn, "2182-03-01", "2182-03-31", "acc")
    conn.commit()
    assert not [i for i in client.get("/api/ledger/annotations/pending", headers=h).json()["items"] if i["source_key"] == ev["source_key"]]


def test_pending_items_carry_plain_language_labels(client, conn, fake, make_user):
    """R3：待補登清單給白話名稱（承攬商派工＋單號、承攬商發票），畫面不必顯示 contractor_dispatch／E04。"""
    h = _login(client, make_user, "an_lbl")
    ev = _e04()
    fake["events"] = [ev]
    E.run(conn, "2182-03-01", "2182-03-31", "acc")
    conn.commit()
    (it,) = [i for i in client.get("/api/ledger/annotations/pending", headers=h).json()["items"] if i["source_key"] == ev["source_key"]]
    assert it["source_label"] == "承攬商派工 " + ev["source_key"] and it["event_label"] == "承攬商發票"
