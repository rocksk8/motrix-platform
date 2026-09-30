# -*- coding: utf-8 -*-
"""總帳功能旗標 `ready`：尚未出貨的功能顯示『開發中』、不能開啟（PUT 回 409）；已出貨的照常。守門：READY 必須是 FEATURES 的子集。"""
import pytest

import db
from modules.accounting.ledger import features as F


def _tok(client, make_user):
    u, p = make_user(username="rdy_admin%d" % id(client), role="superadmin")
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def test_ready_is_a_subset_and_listing_reports_it(client):
    assert F.READY <= set(F.FEATURES) and F.READY == {"engine_drafts", "tax401", "withholding", "source_annotations"}
    c = db.get_db()
    try:
        rows = {r["key"]: r for r in F.listing(c)}
    finally:
        c.close()
    assert rows["engine_drafts"]["ready"] and rows["tax401"]["ready"] and rows["withholding"]["ready"] and rows["source_annotations"]["ready"]
    assert rows["fixed_assets"]["ready"] is False and rows["custom_records"]["ready"] is False and not any(r["enabled"] for r in rows.values())     # 預設全關


def test_put_refuses_to_enable_unbuilt_features_but_allows_ready_and_disabling(client, make_user):
    h = _tok(client, make_user)
    for key in ("fixed_assets", "invoice_adjustments", "custom_records", "backfill", "inventory_cost"):
        r = client.put("/api/ledger/features/" + key, headers=h, json={"enabled": True})
        assert r.status_code == 409 and "開發中" in r.json()["detail"], key
        assert client.put("/api/ledger/features/" + key, headers=h, json={"enabled": False}).status_code == 200      # 關閉永遠允許
    for key in ("engine_drafts", "tax401", "withholding", "source_annotations"):                     # 已出貨的可以開、可以關
        assert client.put("/api/ledger/features/" + key, headers=h, json={"enabled": True}).status_code == 200, key
        assert client.put("/api/ledger/features/" + key, headers=h, json={"enabled": False}).status_code == 200, key
    lst = {f["key"]: f for f in client.get("/api/ledger/features", headers=h).json()["features"]}
    assert lst["fixed_assets"]["ready"] is False and lst["engine_drafts"]["ready"] is True


def test_a_stale_flag_of_an_unready_feature_does_not_open_it(client, make_user):
    """殘留的 feature.x=1（舊版開過）：有效旗標仍是關，端點回 409、頁籤資料不出——旗標的唯一入口 flags() 就把 READY 算進去。"""
    h = _tok(client, make_user)
    c = db.get_db()
    try:
        for k in ("fixed_assets", "inventory_cost", "custom_records"):
            F.set_flag(c, k, True)                                   # 直接寫紀錄（繞過 PUT 的 409）
        F.set_flag(c, "engine_drafts", True)
        c.commit()
        eff = F.flags(c)
    finally:
        c.close()
    assert eff["fixed_assets"] is False and eff["inventory_cost"] is False and eff["custom_records"] is False
    assert eff["engine_drafts"] is True                              # 已出貨的照常
    lst = {f["key"]: f for f in client.get("/api/ledger/features", headers=h).json()["features"]}
    assert lst["fixed_assets"]["enabled"] is False and lst["engine_drafts"]["enabled"] is True
    for path in ("/api/ledger/tax401?year=2026&period=1", "/api/ledger/withholding", "/api/ledger/annotations"):      # 已出貨但旗標沒開（預設關）：端點仍 409
        assert client.get(path, headers=h).status_code == 409, path
    c = db.get_db()
    try:
        for k in ("inventory_cost", "custom_records", "fixed_assets", "engine_drafts"):
            F.set_flag(c, k, False)
        c.commit()
    finally:
        c.close()
