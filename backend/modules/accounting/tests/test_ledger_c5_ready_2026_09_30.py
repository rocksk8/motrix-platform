# -*- coding: utf-8 -*-
"""總帳功能旗標 `ready`：尚未出貨的功能顯示『開發中』、不能開啟（PUT 回 409）；已出貨的照常。守門：READY 必須是 FEATURES 的子集。"""
import pytest

import db
from modules.accounting.ledger import features as F


def _tok(client, make_user):
    u, p = make_user(username="rdy_admin%d" % id(client), role="superadmin")
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def test_ready_is_a_subset_and_listing_reports_it():
    assert F.READY <= set(F.FEATURES) and F.READY == {"engine_drafts"}
    c = db.get_db()
    try:
        rows = {r["key"]: r for r in F.listing(c)}
    finally:
        c.close()
    assert rows["engine_drafts"]["ready"] is True and rows["tax401"]["ready"] is False and rows["fixed_assets"]["ready"] is False


def test_put_refuses_to_enable_unbuilt_features_but_allows_ready_and_disabling(client, make_user):
    h = _tok(client, make_user)
    for key in ("fixed_assets", "invoice_adjustments", "custom_records", "backfill", "inventory_cost", "source_annotations", "tax401", "withholding"):
        r = client.put("/api/ledger/features/" + key, headers=h, json={"enabled": True})
        assert r.status_code == 409 and "開發中" in r.json()["detail"], key
        assert client.put("/api/ledger/features/" + key, headers=h, json={"enabled": False}).status_code == 200      # 關閉永遠允許
    assert client.put("/api/ledger/features/engine_drafts", headers=h, json={"enabled": True}).status_code == 200
    assert client.put("/api/ledger/features/engine_drafts", headers=h, json={"enabled": False}).status_code == 200
    lst = {f["key"]: f for f in client.get("/api/ledger/features", headers=h).json()["features"]}
    assert lst["fixed_assets"]["ready"] is False and lst["engine_drafts"]["ready"] is True
