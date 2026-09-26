"""外包工班 外包工班的串接點，**取用方這一側、外包工班 不在也要成立的題**（2026-09-26）：
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

def test_case_bundle_without_m04(client, make_user, monkeypatch):
    from routers import quotations as q
    h = _hdr(client, make_user)
    _seed()
    _without(monkeypatch, "dispatch.list_for_case")
    r = client.get("/api/quotations/%s/case-bundle" % QNO, headers=h)
    assert r.status_code == 200
    assert r.json()["parts"]["dispatches"] == {"ok": False, "status": 404, "detail": q.DISPATCHES_UNAVAILABLE}
    assert r.json()["parts"]["updates"]["ok"] is True                     # 其他段照常


# ── IP-14（外包工班 不在）─────────────────────────────────────────────────────────


# ── 相依已切斷（M01／M05／M06 這一側）────────────────────────────────────────────

@pytest.mark.parametrize("rel,pattern", [
    ("routers/quotations.py", r"from (routers|modules\.subcontract)[\w.]* import .*(list_dispatches|vendor_contractors)"),
    ("modules/arap/api/cashier.py", r"contractor_vouchers import|_voucher_public"),     # 2026-09-26 出納搬進 M05
    ("routers/accounting_export.py", r"contractor_vouchers import|_voucher_public"),
])
def test_no_direct_imports_across(rel, pattern):
    if not source_tree.module_installed(rel):
        pytest.skip("%s 的模組不在這個安裝包（PLAYBOOK §B-11）" % rel)
    text = (source_tree.BACKEND / rel).read_text(encoding="utf-8")
    assert not re.search(pattern, text), "%s 仍直接引用：%s" % (rel, pattern)


def test_accounting_export_no_longer_reads_the_subcontract_tables():
    """IP-14 paid_between（2026-09-26）：M06 的 T100 匯出不再自己讀 contractor_payment_vouchers（只經 provider）。"""
    text = (source_tree.BACKEND / "routers" / "accounting_export.py").read_text(encoding="utf-8")
    import ast as _ast
    sql = [n.value for n in _ast.walk(_ast.parse(text)) if isinstance(n, _ast.Constant) and isinstance(n.value, str)
           and "contractor_payment_vouchers" in n.value and ("SELECT" in n.value.upper() or "FROM" in n.value.upper())]
    assert sql == [], sql
    assert 'single_provider("contractor_voucher.paid_between")' in text
