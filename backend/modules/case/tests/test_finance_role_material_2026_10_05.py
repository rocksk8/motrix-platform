# -*- coding: utf-8 -*-
"""第42班（Q6，使用者已同意的預設答案）：叫料單——建立／送審／到貨確認＝一般管理（admin 維持）；
只有「取消已核准的叫料單」與「改成本單價」要財務角色（或 superadmin）。
"""
import pytest

from tests._requires import skip_module_unless

skip_module_unless("case", "本檔全部是 M01 的叫料審核")

from modules.case.tests.test_material_guard_2026_10_02 import (  # noqa: E402
    NO, _cr, _flow, _login, _order, _q, _seed, _status,
)


def _patch(client, h, rows):
    """專屬端點（UI 用的路徑）：整份取代叫料清單。"""
    return client.patch("/api/quotations/%s/material-orders" % NO, json={"materialOrders": rows}, headers=h)


@pytest.fixture(autouse=True)
def _po_rule_off(monkeypatch):
    from modules.case import material_approval as _MA
    monkeypatch.setattr(_MA, "PO_REQUIRED", False)


@pytest.fixture
def world(client, make_user):
    adm, ap = make_user(username="fr_adm", role="admin")
    fin, fp = make_user(username="fr_fin", role="finance")
    _seed(assigned=[_q("SELECT id FROM users WHERE username=?", (fin,))[0]["id"]])      # 財務角色要改單價得是案件成員（案件存取規則不變）
    return {"adm": _login(client, adm, ap), "fin": _login(client, fin, fp)}


def test_admin_keeps_create_submit_and_arrival_confirm(client, world):
    new = _cr()["materialOrders"] + [_order("N1", "新品", 1, 100)]
    r = _patch(client, world["adm"], new)
    assert r.status_code == 200 and "rejected" not in r.json(), r.text         # 建立
    assert _status("N1") == "草稿"
    _flow([])
    r = client.post("/api/quotations/%s/material-orders/N1/submit" % NO, headers=world["adm"])
    assert r.status_code == 200 and r.json()["status"] == "已核准", r.text      # 送審
    r = client.post("/api/quotations/%s/material-orders/N1/receive" % NO, json={"receivedOn": "2026-10-05"}, headers=world["adm"])
    assert r.status_code == 200, r.text                                         # 到貨確認
    edit = _cr()["materialOrders"]
    edit[-1]["notes"] = "備註可以改"
    assert "rejected" not in _patch(client, world["adm"], edit).json()    # 非單價欄位的編輯照常


def test_admin_cannot_change_unit_cost_but_finance_can(client, world):
    edit = _cr()["materialOrders"]
    edit[0]["unitPrice"], edit[0]["totalPrice"] = 1, 2
    r = _patch(client, world["adm"], edit)
    assert [(x["itemId"], x["code"]) for x in r.json()["rejected"]] == [("L1", "no_permission")], r.text
    assert _cr()["materialOrders"][0]["unitPrice"] == 1500                       # 沒被改
    r = _patch(client, world["fin"], edit)
    assert r.status_code == 200 and not r.json().get("rejected"), r.text          # 財務角色可
    assert _cr()["materialOrders"][0]["unitPrice"] == 1


def test_admin_cannot_cancel_an_approved_order_but_finance_can(client, world):
    _flow([])
    assert client.post("/api/quotations/%s/material-orders/L1/submit" % NO, headers=world["adm"]).json()["status"] == "已核准"
    r = client.post("/api/quotations/%s/material-orders/L1/cancel" % NO, json={"reason": "測試取消"}, headers=world["adm"])
    assert r.status_code == 403, r.text
    assert _status("L1") == "已核准"
    r = client.post("/api/quotations/%s/material-orders/L1/cancel" % NO, json={"reason": "測試取消"}, headers=world["fin"])
    assert r.status_code == 200, r.text
    assert _status("L1") == "已取消"
