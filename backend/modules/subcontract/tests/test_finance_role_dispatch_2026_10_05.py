# -*- coding: utf-8 -*-
"""第42班（Q5，使用者已同意的預設答案）：承攬派發——建立／狀態／驗收＝一般管理（admin 維持）；
發票日、發票附件與「含金額欄位（品項／人員金額、稅率）的修改」＝財務角色（或 superadmin）。
"""
import json

import pytest

from tests._requires import skip_module_unless

skip_module_unless("subcontract", "本檔全部是 M04（承攬）的派發端點")


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def world(client, make_user):
    adm = _login(client, *make_user("qd_adm", role="admin"))
    fin = _login(client, *make_user("qd_fin", role="finance", modules=["procurement", "case_manage", "contractor_list", "finance", "cashier"]))
    r = client.post("/api/vendor-contractors", headers=adm, json={"name": "廠商Q5", "data": {}})
    assert r.status_code == 201, r.text
    return {"adm": adm, "fin": fin, "vendor": r.json()["id"]}


def _body(vendor, amount=10000, **kw):
    b = {"quote_no": "MQ-Q5-001", "vendor_id": vendor, "dispatch_date": "2026-10-01", "scope": "施工",
         "items_json": [{"description": "品項", "qty": 1, "unit": "式", "unitPrice": amount, "amount": amount}], "notes": "備註"}
    b.update(kw)
    return b


def _create(client, world):
    r = client.post("/api/contractor-dispatches", headers=world["adm"], json=_body(world["vendor"]))
    assert r.status_code == 201, r.text          # 建立＝一般管理（admin 維持）
    return r.json()["id"]


def test_admin_creates_and_edits_non_money_fields(client, world):
    did = _create(client, world)
    r = client.put("/api/contractor-dispatches/%d" % did, headers=world["adm"],
                   json=_body(world["vendor"], scope="改過的範圍", notes="改過的備註"))
    assert r.status_code == 200, r.text


def test_admin_cannot_change_amounts_or_tax_or_invoice_date_but_finance_can(client, world):
    did = _create(client, world)
    put = lambda h, **kw: client.put("/api/contractor-dispatches/%d" % did, headers=h, json=_body(world["vendor"], **kw))
    assert put(world["adm"], amount=20000).status_code == 403                          # 金額
    assert put(world["adm"], tax_rate=0.0).status_code == 403                           # 稅率
    assert put(world["adm"], invoice_date="2026-10-02").status_code == 403              # 發票日（整筆編輯路徑）
    assert put(world["fin"], amount=20000).status_code == 200
    assert put(world["fin"], amount=20000, invoice_date="2026-10-02").status_code == 200


def test_invoice_date_and_invoice_files_are_finance_only(client, world):
    did = _create(client, world)
    url = "/api/contractor-dispatches/%d/invoice-date" % did
    assert client.patch(url, headers=world["adm"], json={"invoiceDate": "2026-10-02"}).status_code == 403
    assert client.patch(url, headers=world["fin"], json={"invoiceDate": "2026-10-02"}).status_code == 200
    f = {"files": ("inv.pdf", b"%PDF-1.4 test", "application/pdf")}
    assert client.post("/api/contractor-dispatches/%d/invoice-files" % did, headers=world["adm"], files=f).status_code == 403
    assert client.delete("/api/contractor-dispatches/%d/invoice-files/NOPE" % did, headers=world["adm"]).status_code == 403


def test_create_status_and_accept_stay_general(client, world):
    did = _create(client, world)
    r = client.post("/api/contractor-dispatches/%d/status" % did, headers=world["adm"], json={"action": "cancel"})
    assert r.status_code != 403, r.text           # 狀態＝一般管理（具體結果依流程；只驗不是財務角色擋）
