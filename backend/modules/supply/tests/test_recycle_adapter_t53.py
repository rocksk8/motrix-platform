# -*- coding: utf-8 -*-
"""第 53 班 P1（供應模組）：出貨單進刪除暫存區——刪除端點、還原逐欄相等、D1 不放寬、『刪除已核可』（已扣庫存序號明確拒絕）、暫存區不在時照舊硬刪並明說。"""
import json
import os

import pytest

import db
from helpers import recycle_bin as RB
from helpers import uploads as UP


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def who(client, make_user):
    su, sp = make_user(username="rbs_su", role="superadmin")
    ad, ap = make_user(username="rbs_admin", role="admin")
    return _login(client, su, sp), _login(client, ad, ap)


@pytest.fixture(autouse=True)
def _clean_bin(client):
    yield
    cn = db.get_db()
    cn.execute("DELETE FROM recycle_bin")
    cn.commit()
    cn.close()


def _q(sql, args=()):
    cn = db.get_db()
    try:
        return [dict(r) for r in cn.execute(sql, args).fetchall()]
    finally:
        cn.close()


def _x(sql, args=()):
    cn = db.get_db()
    try:
        cn.execute(sql, args)
        cn.commit()
    finally:
        cn.close()


def _note(no, qn="", status="草稿", rel=None):
    files = [{"id": "s1", "filename": "s.pdf", "path": rel}] if rel else []
    _x("INSERT INTO shipping_notes (note_no, quote_no, status, customer_name, items_json, data_json, created_by, created_at, updated_at, signed_files_json, is_signed)"
       " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
       (no, qn, status, "客戶", json.dumps([{"description": "交換器", "quantity": 1}]), "{}", "rbs_su", "2026-10-01", "2026-10-01", json.dumps(files), 1 if rel else 0))


def _file(rel):
    full = os.path.join(UP.UPLOADS_ROOT, *rel.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write("x")
    return full


def test_shipping_note_delete_goes_to_the_bin_and_restores_identically(client, who):
    su, _ = who
    rel = "rbs/sn/s.pdf"
    full = _file(rel)
    _note("SN-RBS-1", rel=rel)
    before = _q("SELECT * FROM shipping_notes WHERE note_no='SN-RBS-1'")[0]
    r = client.delete("/api/shipping-notes/SN-RBS-1", headers=su)
    assert r.status_code == 200 and r.json() == {"ok": True}, r.text
    assert _q("SELECT 1 FROM shipping_notes WHERE note_no='SN-RBS-1'") == [] and not os.path.exists(full)
    b = _q("SELECT * FROM recycle_bin")
    assert len(b) == 1 and b[0]["entity_type"] == "shipping_note" and b[0]["file_count"] == 1
    assert client.post("/api/recycle-bin/%d/restore" % b[0]["id"], headers=su).status_code == 200
    assert _q("SELECT * FROM shipping_notes WHERE note_no='SN-RBS-1'")[0] == before and os.path.isfile(full)


def test_shipping_note_restore_conflict_and_missing_parent(client, who):
    su, _ = who
    _x("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
       ("MQ-RBS-9", "已送出", "客戶", "專案", "{}", "2026-10-01", "2026-10-01"))
    _note("SN-RBS-2", qn="MQ-RBS-9")
    assert client.delete("/api/shipping-notes/SN-RBS-2", headers=su).status_code == 200
    bid = _q("SELECT id FROM recycle_bin")[0]["id"]
    _x("DELETE FROM quotations WHERE quote_no='MQ-RBS-9'")
    r = client.post("/api/recycle-bin/%d/restore" % bid, headers=su)
    assert r.status_code == 409 and "不在了" in r.text
    _x("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
       ("MQ-RBS-9", "已送出", "客戶", "專案", "{}", "2026-10-01", "2026-10-01"))
    _note("SN-RBS-2", qn="MQ-RBS-9")
    r = client.post("/api/recycle-bin/%d/restore" % bid, headers=su)
    assert r.status_code == 409 and "占用" in r.text
    _x("DELETE FROM shipping_notes WHERE note_no='SN-RBS-2'")
    assert client.post("/api/recycle-bin/%d/restore" % bid, headers=su).status_code == 200


def test_rules_not_relaxed_and_approved_path(client, who):
    su, ad = who
    _note("SN-RBS-3", status="已核准")
    assert client.delete("/api/shipping-notes/SN-RBS-3", headers=su).status_code == 409           # D1：仍然只有草稿
    body = {"entity_type": "shipping_note", "entity_id": "SN-RBS-3", "confirm": True, "confirm_text": "SN-RBS-3"}
    assert client.post("/api/recycle-bin/delete-approved", headers=ad, json=body).status_code == 403
    _x("INSERT INTO stock_items (part_no, serial_no, shipping_note_no, status) VALUES ('P-RBS','SER-RBS','SN-RBS-3','shipped')")
    r = client.post("/api/recycle-bin/delete-approved", headers=su, json=body)
    assert r.status_code in (400, 409) and "庫存" in r.text and _q("SELECT 1 FROM shipping_notes WHERE note_no='SN-RBS-3'") != []
    _x("DELETE FROM stock_items WHERE shipping_note_no='SN-RBS-3'")
    r = client.post("/api/recycle-bin/delete-approved", headers=su, json=body)
    assert r.status_code == 200 and _q("SELECT via FROM recycle_bin")[0]["via"] == "approved"


def test_without_bin_module_hard_deletes_and_says_so(client, who, monkeypatch):
    su, _ = who
    _note("SN-RBS-4")
    monkeypatch.setattr(RB, "delete", lambda *a, **k: None)
    r = client.delete("/api/shipping-notes/SN-RBS-4", headers=su)
    assert r.status_code == 200 and r.json()["binned"] is False and "無法還原" in r.json()["notice"]
    assert _q("SELECT 1 FROM shipping_notes WHERE note_no='SN-RBS-4'") == [] and _q("SELECT 1 FROM recycle_bin") == []


def test_adapter_registered_by_supply():
    assert "shipping_note" in RB.adapters() and RB.adapters()["shipping_note"].label == "出貨單"
