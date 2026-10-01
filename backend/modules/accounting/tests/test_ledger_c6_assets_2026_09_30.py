# -*- coding: utf-8 -*-
"""總帳 C6 · 固定資產：資產卡片、直線法折舊（累計值相減、最後一個月湊足）、估計變動不追溯、取得 E13a／每月折舊 E13b 事件、折舊表對帳、API。
反向控制：草稿卡片不產生分錄；未結束的月份不折舊；估計變動要原因且不能回溯已有折舊草稿的月份；引擎整合冪等。
"""
import datetime as _dt

import pytest

import db
from modules.accounting.ledger import engine as E
from modules.accounting.ledger import features as F
from modules.accounting.ledger import fixed_assets as FA
from modules.accounting.ledger import roles as ROLES


@pytest.fixture
def conn(client, monkeypatch):
    monkeypatch.setattr(FA, "_today", lambda: _dt.date(2181, 12, 31))
    c = db.get_db()
    ROLES.ensure_meta(c)
    ROLES.ensure_default_roles(c)
    c.execute("DELETE FROM fa_assets")
    c.execute("DELETE FROM fa_revisions")
    c.commit()
    yield c
    c.close()


def _asset(conn, **kw):
    b = {"name": "筆電", "category": "computer", "acquired_on": "2180-01-10", "in_service_on": "2180-01-15", "cost": 12000, "input_tax": 600,
         "life_years": 3, "salvage": 3000, "invoice_no": "AB12345678"}
    b.update(kw)
    r = FA.create_asset(conn, b, "acc")
    conn.commit()
    return r


def test_formula_sums_to_depreciable_and_last_month_settles():
    a = {"in_service_on": "2180-01-15", "cost": 10000, "salvage": 2500, "life_years": 3}
    months = [FA._month_add("2180-01", i) for i in range(40)]
    amts = [FA.monthly_amount(a, m) for m in months]
    assert sum(amts) == 7500 and amts[0] == 208 and amts[35] == 208 and amts[36] == 0 and FA.monthly_amount(a, "2179-12") == 0
    assert max(amts) - min(a for a in amts[:36]) <= 1                                 # 每月只差分位進位


def test_revision_reforecasts_remaining_without_touching_past():
    a = {"in_service_on": "2180-01-15", "cost": 10000, "salvage": 2500, "life_years": 3}
    rev = [{"effective_month": "2181-01", "life_years": 5, "salvage": 2000}]
    past = [FA.monthly_amount(a, FA._month_add("2180-01", i), rev) for i in range(12)]
    assert past == [FA.monthly_amount(a, FA._month_add("2180-01", i)) for i in range(12)]           # 生效前不變
    total = sum(FA.monthly_amount(a, FA._month_add("2180-01", i), rev) for i in range(80))
    assert total == 8000                                                               # 總折舊＝成本－新殘值


def test_create_validations_numbering_and_defaults(conn):
    r = _asset(conn, salvage=None)
    assert r["asset_no"] == "FA-2180-001" and r["salvage"] == FA.default_salvage(12000, 3) and r["tax_capitalized"] is False        # 未達 8 萬
    assert _asset(conn, cost=100000)["tax_capitalized"] is True
    for bad in ({"category": "nope"}, {"name": " "}, {"cost": 0}, {"life_years": 0}, {"salvage": 12000}, {"in_service_on": "2179-01-01"}, {"acquired_on": "x"}):
        with pytest.raises(FA.AssetError):
            FA.create_asset(conn, dict({"name": "x", "category": "computer", "acquired_on": "2180-01-10", "cost": 5000}, **bad), "acc")


def test_draft_card_produces_no_events_until_activated(conn):
    r = _asset(conn)
    assert FA.gl_events("2180-01-01", "2181-12-31")["events"] == []
    FA.activate(conn, r["id"], "acc")
    conn.commit()
    with pytest.raises(FA.AssetError):
        FA.activate(conn, r["id"], "acc")
    codes = sorted({e["event_code"] for e in FA.gl_events("2180-01-01", "2181-12-31")["events"]})
    assert codes == ["E13a", "E13b"]


def test_acquisition_event_lines_and_account_override(conn):
    r = _asset(conn)
    FA.activate(conn, r["id"], "acc")
    conn.commit()
    (acq,) = [e for e in FA.gl_events("2180-01-01", "2180-01-31")["events"] if e["event_code"] == "E13a"]
    assert [(l["role"], l["side"], l["amount"]) for l in acq["lines"]] == [("FA_COST", "D", 12000), ("INPUT_TAX", "D", 600), ("FA_PAYABLE", "C", 12600)]
    assert acq["lines"][0]["account_code"] == "1431" and acq["lines"][0]["tax_code"] == "IN-FA" and acq["source_key"] == r["asset_no"]
    from modules.accounting.ledger import contract as C
    assert C.validate_event(acq) == []


def test_monthly_depreciation_events_by_category_and_only_finished_months(conn, monkeypatch):
    a1, a2 = _asset(conn), _asset(conn, name="桌子", category="furniture", cost=6000, input_tax=0, salvage=0, life_years=5)
    for x in (a1, a2):
        FA.activate(conn, x["id"], "acc")
    conn.commit()
    evs = {e["source_key"]: e for e in FA.gl_events("2180-01-01", "2180-03-31")["events"] if e["event_code"] == "E13b"}
    jan = evs["fa::218001"]
    assert jan["event_date"] == "2180-01-31" and [(l["side"], l["amount"]) for l in jan["lines"]] == [("D", 250), ("C", 250), ("D", 100), ("C", 100)]
    assert set(evs) == {"fa::218001", "fa::218002", "fa::218003"}
    monkeypatch.setattr(FA, "_today", lambda: _dt.date(2180, 2, 15))                # 2 月還沒結束
    assert {e["source_key"] for e in FA.gl_events("2180-01-01", "2180-03-31")["events"] if e["event_code"] == "E13b"} == {"fa::218001"}


def test_schedule_and_reconciliation_with_gl(conn):
    r = _asset(conn)
    FA.activate(conn, r["id"], "acc")
    conn.commit()
    E.run(conn, "2180-01-01", "2180-03-31", "acc")
    conn.execute("UPDATE vouchers_all SET status='已過帳' WHERE kind='auto' AND status='草稿' AND voided_at=''")
    conn.commit()
    s = FA.schedule(conn, "2180-03")
    (row,) = s["rows"]
    assert (row["period"], row["accum"], row["book"]) == (250, 750, 11250) and s["totals"]["accum"] == 750
    chk = {c["key"]: c for c in s["checks"]}
    assert chk["cost_account"]["ok"] and chk["accum_account"]["ok"]                    # 明細 ＝ 總帳
    conn.execute("UPDATE fa_assets SET cost=cost+1 WHERE id=?", (r["id"],))            # 卡片被偷偷改 ⇒ 對帳紅
    conn.commit()
    assert not {c["key"]: c for c in FA.schedule(conn, "2180-03")["checks"]}["cost_account"]["ok"]


def test_engine_end_to_end_is_idempotent_and_revision_is_not_retroactive(conn):
    r = _asset(conn)
    FA.activate(conn, r["id"], "acc")
    conn.commit()
    res = E.run(conn, "2180-01-01", "2180-03-31", "acc")
    conn.commit()
    assert res["sources"]["fixed_assets"] == "ok" and res["stats"]["created"] == 4          # 取得 1 ＋ 折舊 3
    assert E.run(conn, "2180-01-01", "2180-03-31", "acc")["stats"]["created"] == 0
    with pytest.raises(FA.AssetError):
        FA.add_revision(conn, r["id"], "2180-02", 5, 2000, "重新評估", "acc")               # 2 月已有折舊草稿 ⇒ 不追溯
    with pytest.raises(FA.AssetError):
        FA.add_revision(conn, r["id"], "2181-06", 5, 2000, " ", "acc")                      # 沒原因
    FA.add_revision(conn, r["id"], "2181-06", 5, 2000, "重新評估耐用年限", "acc")
    conn.commit()


def test_api_flag_permissions_and_audit(client, conn, make_user):
    u, p = make_user(username="fa_admin%d" % id(client), role="superadmin")
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    assert client.get("/api/ledger/assets", headers=h).status_code == 409
    F.set_flag(conn, "fixed_assets", True)
    conn.commit()
    body = {"name": "伺服器", "category": "computer", "acquired_on": "2180-05-02", "cost": 90000, "input_tax": 4500, "life_years": 3, "invoice_no": "ZZ00000001"}
    c = client.post("/api/ledger/assets", headers=h, json=body)
    assert c.status_code == 200 and c.json()["tax_capitalized"] is True
    aid = c.json()["id"]
    assert client.post("/api/ledger/assets", headers=h, json=dict(body, cost=-1)).status_code == 400
    assert client.patch("/api/ledger/assets/%d" % aid, headers=h, json={"note": "機房"}).status_code == 200
    assert client.post("/api/ledger/assets/%d/activate" % aid, headers=h).status_code == 200
    assert client.patch("/api/ledger/assets/%d" % aid, headers=h, json={"note": "x"}).status_code == 400            # 啟用後不可直接改
    assert client.post("/api/ledger/assets/%d/activate" % aid, headers=h).status_code == 400
    lst = client.get("/api/ledger/assets", headers=h).json()
    assert any(a["id"] == aid and a["status"] == "active" for a in lst["assets"]) and any(k["code"] == "computer" for k in lst["categories"])
    assert client.get("/api/ledger/assets/schedule?ym=2180-06", headers=h).status_code == 200
    assert client.get("/api/ledger/assets/schedule?ym=2180-13", headers=h).status_code == 400
    rv = client.post("/api/ledger/assets/%d/revision" % aid, headers=h, json={"effective_month": "2181-06", "life_years": 5, "salvage": 5000, "reason": "改用年限"})
    assert rv.status_code == 200
    c2 = db.get_db()
    try:
        n = c2.execute("SELECT COUNT(*) FROM audit_log WHERE action LIKE 'ledger.asset.%'").fetchone()[0]
    finally:
        c2.close()
    assert n >= 4


def test_write_endpoints_are_superadmin_only_but_finance_can_read(client, conn, make_user):
    """主持裁示 2026-10-01：寫入＝只有最高管理者（規則 B）；讀＝cashier／finance。"""
    sa, sp = make_user(username="fa_sa%d" % id(client), role="superadmin")
    fin, fp = make_user(username="fa_fin%d" % id(client), role="staff", modules=["finance"])
    hs = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": sa, "password": sp}).json()["token"]}
    hf = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": fin, "password": fp}).json()["token"]}
    F.set_flag(conn, "fixed_assets", True)
    conn.commit()
    body = {"name": "伺服器", "category": "computer", "acquired_on": "2180-05-02", "cost": 90000, "life_years": 3}
    assert client.post("/api/ledger/assets", headers=hf, json=body).status_code == 403
    aid = client.post("/api/ledger/assets", headers=hs, json=body).json()["id"]
    assert client.get("/api/ledger/assets", headers=hf).status_code == 200                       # 讀：財務可以
    assert client.get("/api/ledger/assets/schedule?ym=2180-06", headers=hf).status_code == 200
    for method, url, kw in (("patch", "/api/ledger/assets/%d" % aid, {"json": {"note": "x"}}), ("post", "/api/ledger/assets/%d/activate" % aid, {}),
                            ("post", "/api/ledger/assets/%d/revision" % aid, {"json": {"effective_month": "2181-06", "life_years": 5, "salvage": 1, "reason": "x"}})):
        assert getattr(client, method)(url, headers=hf, **kw).status_code == 403, url
