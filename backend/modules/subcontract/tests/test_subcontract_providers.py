"""外包工班的串接點，**需要本模組在的題**（拿掉本模組時跟著消失）：
提供者已登記（IP-1／14／15）、IP-15／IP-14 正對照、IP-17 `quotation.append_items`（M01 → 本模組；含 M01 不在 ⇒ 409）、
本模組不再 import M01。本模組不在時的反向控制在 `tests/platform/test_subcontract_connectors.py`。
"""
import json
import re

import pytest

from core import registry, source_tree

#: 2026-09-26 M05 搬遷：下列題同時需要應收應付（出納／收款資料）
_NEEDS_ARAP = pytest.mark.skipif(not __import__("core.source_tree", fromlist=["x"]).module_installed("modules/arap/"),
                                 reason="需要應收應付（M05）：模組不在這個安裝包（PLAYBOOK §B-11）")

QNO = "MQ-202609-S04"


def _hdr(client, make_user, name="s04_super"):
    u, p = make_user(name, "Conn-Pass-123", role="superadmin")[:2]
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _without(monkeypatch, cap):
    orig = registry.providers
    monkeypatch.setattr(registry, "providers", lambda c: {} if c == cap else orig(c))


def _seed(status="草稿"):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
                     "data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     (QNO, status, "客", "案", 0, 0, json.dumps({"items": [{"id": "orig", "description": "原有"}]}),
                      "2026-09-26T00:00:00", "2026-09-26T00:00:00"))
        conn.execute("INSERT INTO contractor_dispatches (quote_no, dispatch_date, scope, items_json, total_amount, "
                     "status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                     (QNO, "2026-09-26", "items",
                      json.dumps([{"description": "配線", "qty": 3, "unit": "式", "unitPrice": 1200, "note": "n"}]),
                      3600, "pending", "2026-09-26T00:00:00", "2026-09-26T00:00:00"))
        did = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        conn.execute("INSERT INTO contractor_payment_vouchers (voucher_no, dispatch_id, quote_no, status, snapshot_json, "
                     "data_json, is_paid, paid_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     ("CV-S04-1", did, QNO, "已核准", json.dumps({"vendorName": "甲", "grandTotal": 3780}), "{}",
                      0, "", "2026-09-26T00:00:00", "2026-09-26T00:00:00"))
        conn.commit()
        return did
    finally:
        conn.close()


def _items():
    import db
    conn = db.get_db()
    try:
        return json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (QNO,)).fetchone()[0])["items"]
    finally:
        conn.close()


def test_providers_are_registered(client):
    assert set(registry.providers("dispatch.row")) == {"subcontract"}
    assert set(registry.providers("dispatch.list_for_case")) == {"subcontract"}
    assert set(registry.providers("quotation.append_items")) == {"quotations"}
    assert set(registry.providers("contractor_voucher.public")) == {"subcontract"}
    assert set(registry.providers("contractor_voucher.paid_between")) == {"subcontract"}


def test_paid_between_lists_only_paid_vouchers_in_range_with_the_public_shape(client):
    """IP-14 paid_between：只回已付款、paid_at 在區間內（含頭尾兩天）的；形狀與 contractor_voucher.public 相同。"""
    import db
    _seed()
    conn = db.get_db()
    try:
        for no, paid, at in (("CV-P-IN1", 1, "2026-09-01T09:00:00"), ("CV-P-IN2", 1, "2026-09-30T18:00:00"),
                             ("CV-P-OUT", 1, "2026-10-01T00:00:01"), ("CV-P-UNPAID", 0, "2026-09-15T00:00:00")):
            conn.execute("INSERT INTO contractor_dispatches (quote_no, dispatch_date, scope, items_json, total_amount, "
                         "status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                         (QNO, "2026-09-01", "amount", "[]", 100, "completed", "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
            d2 = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]     # 一張派工一張憑據（dispatch_id UNIQUE）
            conn.execute("INSERT INTO contractor_payment_vouchers (voucher_no, dispatch_id, quote_no, status, snapshot_json, "
                         "data_json, is_paid, paid_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (no, d2, QNO, "已核准", json.dumps({"vendorName": "乙", "grandTotal": 100}), "{}",
                          paid, at, "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        conn.commit()
        rows = {r["voucher_no"]: r for r in conn.execute("SELECT * FROM contractor_payment_vouchers").fetchall()}
    finally:
        conn.close()
    got = registry.single_provider("contractor_voucher.paid_between")("2026-09-01", "2026-09-30")
    assert [v["voucherNo"] for v in got] == ["CV-P-IN1", "CV-P-IN2"], got
    pub = registry.single_provider("contractor_voucher.public")
    assert got[0] == pub(rows["CV-P-IN1"], include_snapshot=False)          # 同一個對外形狀


# ── IP-17 ─────────────────────────────────────────────────────────────────────

def test_import_to_quote_goes_through_m01(client, make_user):
    h = _hdr(client, make_user)
    did = _seed()
    r = client.post("/api/contractor-dispatches/%d/import-to-quote" % did, headers=h)
    assert r.status_code == 200 and r.json()["imported"] == 1, r.text
    items = _items()
    assert items[0]["id"] == "orig" and items[1]["type"] == "header" and "外包承攬" in items[1]["description"]
    assert {k: items[2][k] for k in ("description", "qty", "unit", "cost", "margin", "notes")} == \
        {"description": "配線", "qty": 3.0, "unit": "式", "cost": 1200.0, "margin": 0.30, "notes": "n"}


def test_import_to_quote_refuses_non_draft(client, make_user):
    h = _hdr(client, make_user)
    did = _seed(status="已送出")
    r = client.post("/api/contractor-dispatches/%d/import-to-quote" % did, headers=h)
    assert r.status_code == 409 and "解鎖" in r.json()["detail"] and len(_items()) == 1


def test_import_to_quote_without_m01_is_409_and_touches_nothing(client, make_user, monkeypatch):
    from modules.subcontract.api import vendor_contractors as vc
    h = _hdr(client, make_user)
    did = _seed()
    _without(monkeypatch, "quotation.append_items")
    r = client.post("/api/contractor-dispatches/%d/import-to-quote" % did, headers=h)
    assert r.status_code == 409 and r.json()["detail"] == vc.QUOTE_IMPORT_UNAVAILABLE
    assert len(_items()) == 1


# ── IP-15（本模組在）───────────────────────────────────────────────────────────

def test_case_bundle_dispatches_part(client, make_user):
    h = _hdr(client, make_user)
    _seed()
    got = client.get("/api/quotations/%s/case-bundle" % QNO, headers=h).json()["parts"]["dispatches"]
    assert got["ok"] is True and [d["quoteNo"] for d in got["data"]] == [QNO]


# ── IP-14（本模組在）───────────────────────────────────────────────────────────

@_NEEDS_ARAP
def test_cashier_and_t100_with_m04(client, make_user):
    h = _hdr(client, make_user)
    _seed()
    r = client.get("/api/cashier/payable-queue", headers=h)
    assert r.status_code == 200 and [v["voucherNo"] for v in r.json()] == ["CV-S04-1"]
    hist = client.get("/api/cashier/execution-history?start=2026-09-01&end=2026-09-30", headers=h).json()
    assert hist["contractorNotice"] == ""
    prev = client.get("/api/reports/t100-export/preview?start=2026-09-01&end=2026-09-30", headers=h).json()
    from routers import accounting_export as ae
    assert ae.T100_CONTRACTOR_MISSING not in prev["notice"].split("；")   # M04 在；其他模組（IP-20 M03）不在時的說明可能並列


# ── 相依已切斷（本模組這一側）─────────────────────────────────────────────────────

def test_subcontract_does_not_import_the_case_module():
    text = (source_tree.BACKEND / "modules" / "subcontract" / "api" / "vendor_contractors.py").read_text(encoding="utf-8")
    assert not re.search(r"save_quotation_json|helpers\.recognition|helpers\.quotations", text)
