"""M04 外包工班搬遷前置的三個串接點（2026-09-26）：IP-12 `dispatch.list_for_case`、IP-13 `quotation.append_items`、
IP-14 `contractor_voucher.public`。每一個都驗：提供者已登記、正對照、**反向控制**（拿掉提供者 ⇒ 照常回應並明說）。
另驗 M04 不再 import M01（save_quotation_json）、M01／M05／M06 不再 import M04。
"""
import json
import re

import pytest

from core import registry, source_tree

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
    assert set(registry.providers("dispatch.list_for_case")) == {"subcontract"}
    assert set(registry.providers("quotation.append_items")) == {"quotations"}
    assert set(registry.providers("contractor_voucher.public")) == {"subcontract"}


# ── IP-13 ─────────────────────────────────────────────────────────────────────

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
    from routers import vendor_contractors as vc
    h = _hdr(client, make_user)
    did = _seed()
    _without(monkeypatch, "quotation.append_items")
    r = client.post("/api/contractor-dispatches/%d/import-to-quote" % did, headers=h)
    assert r.status_code == 409 and r.json()["detail"] == vc.QUOTE_IMPORT_UNAVAILABLE
    assert len(_items()) == 1


# ── IP-12 ─────────────────────────────────────────────────────────────────────

def test_case_bundle_dispatches_part(client, make_user, monkeypatch):
    from routers import quotations as q
    h = _hdr(client, make_user)
    _seed()
    got = client.get("/api/quotations/%s/case-bundle" % QNO, headers=h).json()["parts"]["dispatches"]
    assert got["ok"] is True and [d["quoteNo"] for d in got["data"]] == [QNO]
    _without(monkeypatch, "dispatch.list_for_case")
    r = client.get("/api/quotations/%s/case-bundle" % QNO, headers=h)
    assert r.status_code == 200
    assert r.json()["parts"]["dispatches"] == {"ok": False, "status": 404, "detail": q.DISPATCHES_UNAVAILABLE}
    assert r.json()["parts"]["updates"]["ok"] is True                     # 其他段照常


# ── IP-14 ─────────────────────────────────────────────────────────────────────

def test_cashier_and_t100_with_and_without_m04(client, make_user, monkeypatch):
    from routers import accounting_export as ae, cashier as ca
    h = _hdr(client, make_user)
    _seed()
    r = client.get("/api/cashier/payable-queue", headers=h)
    assert r.status_code == 200 and [v["voucherNo"] for v in r.json()] == ["CV-S04-1"]
    hist = client.get("/api/cashier/execution-history?start=2026-09-01&end=2026-09-30", headers=h).json()
    assert hist["contractorNotice"] == ""
    prev = client.get("/api/reports/t100-export/preview?start=2026-09-01&end=2026-09-30", headers=h).json()
    assert prev["notice"] == ""

    _without(monkeypatch, "contractor_voucher.public")
    r = client.get("/api/cashier/payable-queue", headers=h)
    assert r.status_code == 404 and r.json()["detail"] == ca.CONTRACTOR_MISSING
    hist = client.get("/api/cashier/execution-history?start=2026-09-01&end=2026-09-30", headers=h)
    assert hist.status_code == 200 and hist.json()["outgoing"] == [] and hist.json()["contractorNotice"] == ca.CONTRACTOR_MISSING
    prev = client.get("/api/reports/t100-export/preview?start=2026-09-01&end=2026-09-30", headers=h)
    assert prev.status_code == 200 and prev.json()["notice"] == ae.T100_CONTRACTOR_MISSING
    x = client.get("/api/cashier/export?start=2026-09-01&end=2026-09-30", headers=h)
    assert x.status_code == 200
    import io
    import openpyxl
    ws = openpyxl.load_workbook(io.BytesIO(x.content))["已匯款明細"]
    assert ws.cell(row=3, column=1).value == ca.CONTRACTOR_MISSING


# ── 相依已切斷 ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel,pattern", [
    ("routers/vendor_contractors.py", r"save_quotation_json|helpers\.recognition"),
    ("routers/quotations.py", r"from routers\.vendor_contractors import"),
    ("routers/cashier.py", r"from routers\.contractor_vouchers import"),
    ("routers/accounting_export.py", r"from routers\.contractor_vouchers import"),
])
def test_no_direct_imports_across(rel, pattern):
    text = (source_tree.BACKEND / rel).read_text(encoding="utf-8")
    assert not re.search(pattern, text), "%s 仍直接引用：%s" % (rel, pattern)
