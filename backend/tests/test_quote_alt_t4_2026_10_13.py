# -*- coding: utf-8 -*-
"""M3 T4（T57）：alt_options.plan_view（純函式）＋ GET /api/quotations/{no}/plan-view（成本權限）。"""
import json

import pytest

import db
from modules.case import alt_options as AO
from modules.case import profit_guard as PG
from modules.case.api import alt_plan


def _it(id_, qty, price, cost, group=None, **kw):
    d = {"id": id_, "qty": qty, "unitPrice": price, "cost": cost, "amount": qty * price, "description": "品" + id_}
    if group is not None:
        d["altGroup"] = group
    d.update(kw)
    return d


def _q(picks=None, **kw):
    q = {"items": [_it("a", 2, 1000, 600), _it("x1", 1, 3000, 2000, "投影機"), _it("x2", 1, 5000, 3500, "投影機"),
                   _it("y1", 4, 100, 60, "線材"), _it("y2", 4, 150, 90, "線材"), _it("y3", 4, 200, 90, "線材")], "taxRate": 5}
    if picks is not None:
        q["altPicks"] = picks
    q.update(kw)
    return q


def _expected(q, picks, pct=25, ver=2):
    qq = dict(q, altPicks=picks)
    t = PG.server_totals(qq)
    p = PG.server_profit(dict(qq, tot=t), pct, ver, pretax=t["pretax"], total=t["total"])
    return t, p


@pytest.fixture(autouse=True)
def _v2(monkeypatch):
    monkeypatch.setattr(PG, "current_ver", lambda: 2)
    monkeypatch.setattr(PG, "charity_basis", lambda: "direct")
    monkeypatch.setattr(PG, "default_pct", lambda: 25)


def test_option_row_equals_plain_quote_with_that_pick():
    q = _q()
    v = AO.plan_view(q)
    assert v["baseline"] == {"投影機": "x1", "線材": "y1"}
    for g in v["groups"]:
        for o in g["options"]:
            picks = dict(v["baseline"], **{g["group"]: o["id"]})
            t, p = _expected(q, picks)
            assert o["pretax"] == t["pretax"] and o["total"] == t["total"]
            assert o["totalCost"] == p["totalCost"] and o["netProfit"] == p["netProfit"] and o["directMarginPct"] == p["directMarginPct"]


def test_selection_overrides_baseline_and_bad_selection_falls_back():
    v = AO.plan_view(_q(), {"投影機": "x2", "線材": "nope"})
    assert v["baseline"] == {"投影機": "x2", "線材": "y1"}


def test_current_reflects_stored_picks_and_unpicked_count():
    assert AO.plan_view(_q())["unpicked"] == 2
    v = AO.plan_view(_q({"投影機": "x2"}))
    assert v["unpicked"] == 1
    t, p = _expected(_q(), {"投影機": "x2"})
    assert v["current"]["pretax"] == t["pretax"] and v["current"]["totalCost"] == p["totalCost"]


def test_no_alt_quote_has_no_groups():
    q = {"items": [_it("a", 1, 100, 50)], "taxRate": 5}
    v = AO.plan_view(q, combos=True)
    assert v["groups"] == [] and v["combos"]["total"] == 0 and v["combos"]["rows"] == []


def test_plan_view_does_not_mutate_input():
    q = _q({"投影機": "x1"})
    snap = json.dumps(q, sort_keys=True)
    AO.plan_view(q, {"線材": "y2"}, combos=True)
    assert json.dumps(q, sort_keys=True) == snap


def test_combos_count_sort_and_cap():
    v = AO.plan_view(_q(), combos=True, combo_max=4)
    c = v["combos"]
    assert c["total"] == 6 and c["expanded"] and c["truncated"] and len(c["rows"]) == 4
    pcts = [r["figures"]["directMarginPct"] for r in c["rows"]]
    assert pcts == sorted(pcts, reverse=True)
    full = AO.plan_view(_q(), combos=True, combo_max=24)["combos"]
    assert len(full["rows"]) == 6 and not full["truncated"]


def test_combos_not_computed_unless_requested():
    assert "combos" not in AO.plan_view(_q())


def test_combo_product_over_hard_cap_returns_only_total():
    items = [_it("a", 1, 100, 50)]
    for g in range(8):                       # 2^8 = 256 > 200
        items += [_it("g%da" % g, 1, 100, 50, "G%d" % g), _it("g%db" % g, 1, 120, 50, "G%d" % g)]
    c = AO.plan_view({"items": items, "taxRate": 5}, combos=True, combo_max=24)["combos"]
    assert c["total"] == 256 and c["rows"] == [] and c["truncated"] and not c["expanded"]


def test_settled_quote_uses_stamped_ratio_and_version():
    q = _q(tot={"formulaVer": 2, "overheadPct": 30})
    st = AO.stamps(q, settled=True)
    assert st[0] == 30 and st[1] == 2
    assert AO.stamps(_q(), settled=True)[1] == 1        # 舊單沒有戳記 ⇒ 舊口徑
    v = AO.plan_view(q, settled=True)
    assert v["settled"] is True and v["overheadPct"] == 30


# --- 端點 -------------------------------------------------------------------------

def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def admin_h(client, make_user):
    u, p = make_user(username="alt_plan_admin", role="admin")
    return _login(client, u, p)


def _make(client, h):
    body = {"customerName": "擇一客", "projectName": "擇一案", "salesPerson": "", "quoteDate": "2026-10-13", "taxRate": 5,
            "items": _q()["items"], "tot": {}}
    r = client.post("/api/quotations", json={"status": "草稿", "data": body}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["quote_no"]


def test_endpoint_returns_plan_for_cost_visible_user(client, admin_h):
    no = _make(client, admin_h)
    r = client.get("/api/quotations/%s/plan-view" % no, headers=admin_h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert [g["group"] for g in d["groups"]] == ["投影機", "線材"] and "combos" not in d
    r = client.get("/api/quotations/%s/plan-view?combos=true&picks=%s" % (no, json.dumps({"線材": "y3"}, ensure_ascii=False)), headers=admin_h)
    assert r.status_code == 200 and r.json()["baseline"]["線材"] == "y3" and r.json()["combos"]["total"] == 6


def test_endpoint_denies_without_cost_permission_and_leaks_nothing(client, admin_h, monkeypatch):
    no = _make(client, admin_h)
    monkeypatch.setattr(alt_plan, "quote_money_visible", lambda u: False)
    r = client.get("/api/quotations/%s/plan-view" % no, headers=admin_h)
    assert r.status_code == 403
    for k in ("totalCost", "directProfit", "adminCost", "netProfit", "groups", "combos"):
        assert k not in r.text


def test_endpoint_rejects_bad_picks_and_unknown_quote(client, admin_h):
    no = _make(client, admin_h)
    assert client.get("/api/quotations/%s/plan-view?picks=not-json" % no, headers=admin_h).status_code == 422
    assert client.get("/api/quotations/%s/plan-view?picks=[1]" % no, headers=admin_h).status_code == 422
    assert client.get("/api/quotations/NOPE-0/plan-view", headers=admin_h).status_code == 404
    assert client.get("/api/quotations/%s/plan-view" % no).status_code in (401, 403)


def test_endpoint_is_read_only(client, admin_h):
    no = _make(client, admin_h)
    cn = db.get_db()
    before = cn.execute("SELECT data_json, updated_at FROM quotations WHERE quote_no=?", (no,)).fetchone()
    n_audit = cn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] if cn.execute("SELECT name FROM sqlite_master WHERE name='audit_log'").fetchone() else 0
    cn.close()
    client.get("/api/quotations/%s/plan-view?combos=true" % no, headers=admin_h)
    cn = db.get_db()
    after = cn.execute("SELECT data_json, updated_at FROM quotations WHERE quote_no=?", (no,)).fetchone()
    n2 = cn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] if cn.execute("SELECT name FROM sqlite_master WHERE name='audit_log'").fetchone() else 0
    cn.close()
    assert tuple(before) == tuple(after) and n_audit == n2
