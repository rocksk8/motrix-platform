# -*- coding: utf-8 -*-
"""MONEY-FLOWS §9 L3：來源已入總帳時，寫入端點回 `glWarning`（非阻擋）。

提供者 `gl.source_status`（只回 posted／drift）、L1 `helpers.gl_status.gl_posted_warning`（沒有提供者／丟例外 ⇒ None）、
整合：`mark_payment` 取消已入帳的收款 ⇒ 回應帶 glWarning；沒入帳／只是草稿 ⇒ 沒有。"""
import json

import pytest

import db
from helpers import gl_status as GS
from modules.accounting.ledger import source_status as SS


def _event(conn, stype, key, status, code="E03", voucher_id=None, date="2200-02-10"):
    conn.execute("INSERT INTO gl_source_events (source_type, source_key, event_code, rev, event_date, status, voucher_id)"
                 " VALUES (?,?,?,?,?,?,?)", (stype, key, code, 1, date, status, voucher_id))
    conn.commit()


@pytest.fixture
def conn(client):
    c = db.get_db()
    yield c
    c.close()


def test_provider_reports_only_posted_and_drift(conn):
    cur = conn.execute("INSERT INTO vouchers_all(voucher_no, voucher_date, category, summary, status, created_by, created_at, updated_at)"
                       " VALUES ('20000101-001','2200-02-10','轉','s','已過帳','t','n','n')")
    _event(conn, "quotation_receipt", "MQ-X::it1", "posted", voucher_id=cur.lastrowid)
    _event(conn, "quotation_receipt", "MQ-X::it2", "drafted")
    _event(conn, "quotation_receipt", "MQ-X::it3", "drift")
    assert [h["status"] for h in SS.source_status(conn, "quotation_receipt", "MQ-X::it1")] == ["posted"]
    assert SS.source_status(conn, "quotation_receipt", "MQ-X::it1")[0]["voucher_no"] == "20000101-001"
    assert SS.source_status(conn, "quotation_receipt", "MQ-X::it2") == []                      # 草稿不算入帳
    assert [h["status"] for h in SS.source_status(conn, "quotation_receipt", "MQ-X::it3")] == ["drift"]
    assert len(SS.source_status(conn, "quotation_receipt", "MQ-X::", prefix=True)) == 2           # 前綴：posted＋drift
    assert SS.source_status(conn, "quotation_receipt", "MQ-X_%", prefix=True) == []               # 萬用字元當字面值
    assert SS.source_status(conn, "quotation_receipt", "nope") == []


def test_helper_message_and_fail_safe(conn, monkeypatch):
    _event(conn, "contractor_dispatch", "7", "posted")
    msg = GS.gl_posted_warning(conn, "contractor_dispatch", "7")
    assert msg and "已入總帳" in msg and "沖轉草稿" in msg
    assert GS.gl_posted_warning(conn, "contractor_dispatch", "8") is None
    from core import registry
    monkeypatch.setattr(registry, "providers", lambda cap: {})
    assert GS.gl_posted_warning(conn, "contractor_dispatch", "7") is None                        # 沒有提供者 ⇒ 沒有提示
    monkeypatch.setattr(registry, "providers", lambda cap: {"accounting": lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))})
    assert GS.gl_posted_warning(conn, "contractor_dispatch", "7") is None                        # 提供者壞 ⇒ 不擋、不提示


def _seed_received(conn, qno="MQ-GW-001"):
    conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at, deal_tag)"
                 " VALUES (?,?,?,?,?,?,?,?)",
                 (qno, "已送出", "客戶", "專案", json.dumps({"caseRecord": {"payment": {"items": [
                     {"id": "it1", "type": "訂金款", "pct": 30, "amount": 30000, "received": True, "receivedAt": "2200-02-10",
                      "actualAmount": 30000, "feeAmount": 0, "invoiceNo": ""}]}}}), "n", "n", "已成案"))
    conn.commit()


def _admin(client, make_user):
    u, p = make_user(username="gw_admin", role="admin", modules=None)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_unmarking_a_posted_receipt_returns_glwarning(client, conn, make_user):
    """**反向控制**：拿掉 mark_payment 的 gl_posted_warning 呼叫 ⇒ 這題紅。"""
    _seed_received(conn)
    _event(conn, "quotation_receipt", "MQ-GW-001::it1", "posted")
    h = _admin(client, make_user)
    r = client.patch("/api/quotations/MQ-GW-001/payment/0", headers=h, json={"received": False, "receivedAt": "", "itemId": "it1"})
    assert r.status_code == 200, r.text
    assert "已入總帳" in (r.json().get("glWarning") or "")


def test_unmarking_a_not_posted_receipt_has_no_warning(client, conn, make_user):
    _seed_received(conn, "MQ-GW-002")
    _event(conn, "quotation_receipt", "MQ-GW-002::it1", "drafted")
    h = _admin(client, make_user)
    r = client.patch("/api/quotations/MQ-GW-002/payment/0", headers=h, json={"received": False, "receivedAt": "", "itemId": "it1"})
    assert r.status_code == 200, r.text
    assert "glWarning" not in r.json()


def test_case_record_save_changing_a_posted_receipt_returns_glwarning(client, conn, make_user):
    _seed_received(conn, "MQ-GW-003")
    _event(conn, "quotation_receipt", "MQ-GW-003::it1", "posted")
    h = _admin(client, make_user)
    item = {"id": "it1", "type": "訂金款", "pct": 30, "amount": 30000, "received": True, "receivedAt": "2200-02-10",
            "actualAmount": 29000, "feeAmount": 1000, "invoiceNo": ""}
    r = client.patch("/api/quotations/MQ-GW-003/case-record", headers=h, json={"case_record": {"payment": {"items": [item]}}})
    assert r.status_code == 200, r.text
    assert "已入總帳" in (r.json().get("glWarning") or "")


def test_dispatch_invoice_date_change_on_a_posted_dispatch_returns_glwarning(client, conn, make_user):
    """派工改發票日（E04 已入帳）⇒ 回應帶 glWarning；沒入帳／日期沒變 ⇒ 沒有。**反向控制**：拿掉 invoice-date 端點的呼叫 ⇒ 紅。"""
    u, p = make_user(username="gw_disp", role="superadmin", modules=[])
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    conn.execute("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at, deal_tag)"
                 " VALUES ('MQ-GW-D1','已送出','客戶','專案','{}','n','n','已成案')")
    vid = conn.execute("INSERT INTO vendor_contractors (name) VALUES ('廠商')").lastrowid
    did = conn.execute("INSERT INTO contractor_dispatches (quote_no, vendor_id) VALUES ('MQ-GW-D1', ?)", (vid,)).lastrowid
    conn.commit()
    url = "/api/contractor-dispatches/%d/invoice-date" % did
    ok = client.patch(url, headers=h, json={"invoiceDate": "2200-02-01"})
    assert ok.status_code == 200 and "glWarning" not in ok.json()                     # 還沒入帳
    _event(conn, "contractor_dispatch", str(did), "posted", code="E04")
    same = client.patch(url, headers=h, json={"invoiceDate": "2200-02-01"})
    assert same.status_code == 200 and "glWarning" not in same.json()                 # 日期沒變 ⇒ 不提示
    changed = client.patch(url, headers=h, json={"invoiceDate": "2200-03-01"})
    assert changed.status_code == 200 and "已入總帳" in (changed.json().get("glWarning") or "")
