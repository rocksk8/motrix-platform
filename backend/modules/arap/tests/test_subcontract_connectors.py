"""需要應收應付（M05）的題：刪掉 modules/arap 時隨模組消失（PLAYBOOK §B-11）。

（2026-09-26 自 tests/platform/test_subcontract_connectors.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
外包工班 外包工班的串接點，**取用方這一側、外包工班 不在也要成立的題**（2026-09-26）：
IP-15 `dispatch.list_for_case`（M01 案件整包）、IP-14 `contractor_voucher.public`（M05 出納、M06 T100 匯出）
拿掉提供者 ⇒ 照常回應並明說；M01／M05／M06 不再直接 import 外包工班。
提供方的登記與正對照在 `modules/subcontract/tests/test_subcontract_providers.py`（隨模組搬走）。
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


# ── IP-15（外包工班 不在）─────────────────────────────────────────────────────────


# ── IP-14（外包工班 不在）─────────────────────────────────────────────────────────

def test_cashier_and_t100_without_m04(client, make_user, monkeypatch):
    from modules.accounting.api import accounting_export as ae
    from modules.arap.api import cashier as ca
    h = _hdr(client, make_user)
    _seed()
    _without(monkeypatch, "contractor_voucher.public")
    r = client.get("/api/cashier/payable-queue", headers=h)
    assert r.status_code == 404 and r.json()["detail"] == ca.CONTRACTOR_MISSING
    hist = client.get("/api/cashier/execution-history?start=2026-09-01&end=2026-09-30", headers=h)
    assert hist.status_code == 200 and hist.json()["outgoing"] == [] and hist.json()["contractorNotice"] == ca.CONTRACTOR_MISSING
    prev = client.get("/api/reports/t100-export/preview?start=2026-09-01&end=2026-09-30", headers=h)
    assert prev.status_code == 200 and ae.T100_CONTRACTOR_MISSING in prev.json()["notice"].split("；")   # 其他來源的說明可能並列（IP-20）
    x = client.get("/api/cashier/export?start=2026-09-01&end=2026-09-30", headers=h)
    assert x.status_code == 200
    import io
    import openpyxl
    ws = openpyxl.load_workbook(io.BytesIO(x.content))["已匯款明細"]
    assert ws.cell(row=3, column=1).value == ca.CONTRACTOR_MISSING


# ── 相依已切斷（M01／M05／M06 這一側）────────────────────────────────────────────


def test_bank_reconcile_without_m04_says_why(client, make_user, monkeypatch):
    """銀行對帳（2026-09-26 自 M08 收回 M05）比對的是承攬商匯款申請 ⇒ M04 不在：404＋CONTRACTOR_MISSING（同待付款），
    不回一份「全部未配對」的結果假裝比對過。正對照：M04 在 ⇒ 200。"""
    from modules.arap.api import cashier as ca
    h = _hdr(client, make_user, "s04_bank")
    csv = ("日期,金額\n2026-09-01,100\n").encode("utf-8")
    ok = client.post("/api/reports/bank-reconcile", headers=h, files={"file": ("b.csv", csv, "text/csv")})
    assert ok.status_code == 200, ok.text
    _without(monkeypatch, "contractor_voucher.public")
    r = client.post("/api/reports/bank-reconcile", headers=h, files={"file": ("b.csv", csv, "text/csv")})
    assert r.status_code == 404 and r.json()["detail"] == ca.CONTRACTOR_MISSING
