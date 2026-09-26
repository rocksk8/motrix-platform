"""IP-18 `shipping.list_for_case`、IP-19 `stock.serial`（M03 → M01）：M03 不在的一側（M03 搬遷前置，2026-09-26）。

M03 在的一側（整包帶出出貨單、序號認領／衝突／釋放）隨模組的測試。本檔在 M03 不在時也要綠。
"""
import re
from pathlib import Path

from core import registry
from tests.platform.test_case_stage_connectors import _without

BACKEND = Path(__file__).resolve().parents[2]


def _login(client, make_user, name):
    u, p = make_user(name, "Supply-Pass-123", role="superadmin")[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _case(no):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
                     "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (no, "已送出", "供應客戶", "供應工程", 1000, 952, '{"dealTag": "已成案"}',
                      "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))
        conn.commit()
    finally:
        conn.close()


def _stock(sn, status="in_stock"):
    """庫存表由凍結的 migration 建立，M03 不在時表仍在（資料不動）。"""
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO stock_items (part_no, serial_no, status, created_at, updated_at) VALUES (?,?,?,?,?)",
                     ("NET-SUP", sn, status, "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _q(sql, *args):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def test_without_m03_case_bundle_says_there_are_no_shipping_notes(client, make_user, monkeypatch):
    from routers import quotations as q
    _without(monkeypatch, "shipping.list_for_case", "supply")
    h = _login(client, make_user, "sup_bundle")
    _case("MQ-SUP-B1")
    r = client.get("/api/quotations/MQ-SUP-B1/case-bundle", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["parts"]["shippingNotes"] == {"ok": False, "status": 404, "detail": q.SHIPPING_UNAVAILABLE}
    assert q.SHIPPING_UNAVAILABLE == "採購・庫存・出貨模組未安裝：沒有出貨單資料"


def test_without_m03_device_serials_are_saved_but_not_synced_and_it_says_so(client, make_user, monkeypatch):
    from routers import quotations as q
    _without(monkeypatch, "stock.serial", "supply")
    h = _login(client, make_user, "sup_stock")
    _case("MQ-SUP-S1")
    _stock("SN-SUP-1")
    r = client.patch("/api/quotations/MQ-SUP-S1/case-record", headers=h,
                     json={"case_record": {"devices": [{"id": 1, "sn": "SN-SUP-1"}]}})
    assert r.status_code == 200, r.text
    assert r.json()["stockNotice"] == q.STOCK_UNAVAILABLE and r.json()["stockConflicts"] == []
    assert _q("SELECT status, quote_no FROM stock_items WHERE serial_no='SN-SUP-1'") == [{"status": "in_stock", "quote_no": ""}]
    # 案件資料照存
    import json
    dj = json.loads(_q("SELECT data_json FROM quotations WHERE quote_no='MQ-SUP-S1'")[0]["data_json"])
    assert dj["caseRecord"]["devices"] == [{"id": 1, "sn": "SN-SUP-1"}]


def test_without_m03_no_serial_change_means_no_notice(client, make_user, monkeypatch):
    _without(monkeypatch, "stock.serial", "supply")
    h = _login(client, make_user, "sup_nochg")
    _case("MQ-SUP-S2")
    r = client.patch("/api/quotations/MQ-SUP-S2/case-record", headers=h,
                     json={"case_record": {"devices": [{"id": 1, "name": "AP", "sn": ""}]}})
    assert r.status_code == 200 and "stockNotice" not in r.json(), r.json()


def test_without_m03_t100_preview_says_stock_batches_are_missing(client, make_user, monkeypatch):
    """IP-20：M03 不在 ⇒ T100 預覽照常、不含料件付款傳票，notice 明說；其他來源的說明照舊並列。"""
    from routers import accounting_export as ae
    _without(monkeypatch, "inventory.paid_batches", "supply")
    h = _login(client, make_user, "sup_t100")
    r = client.get("/api/reports/t100-export/preview?start=2026-01-01&end=2026-12-31", headers=h)
    assert r.status_code == 200, r.text
    assert ae.T100_INVENTORY_MISSING in r.json()["notice"].split("；")
    assert not [e for e in r.json()["events"] if e["sourceType"] == "stock_batch"]


def test_m06_no_longer_reads_stock_tables():
    """IP-20 之後會計匯出不直讀 M03 的庫存表。正對照：同一個檔仍讀得到 M06 自己的表。"""
    src = (BACKEND / "routers" / "accounting_export.py").read_text(encoding="utf-8")
    assert "t100_export_confirmations" in src
    assert not re.search(r"\b(FROM|JOIN)\s+(stock_batches|stock_items)\b", src)


def _sql_targets(rel):
    src = (BACKEND / rel).read_text(encoding="utf-8")
    return set(re.findall(r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+([a-z_]+)", src, re.I))


def test_m01_no_longer_writes_stock_items():
    """IP-19 之後 M01 不直寫 M03 的庫存表（table_write_exceptions 對應 debt 已刪）。正對照：同一個掃描抓得到 M01 自己的表。"""
    got = _sql_targets("routers/quotations.py")
    assert "quotations" in got and "case_stages" in got, got
    assert "stock_items" not in got


def test_m01_does_not_import_m03_routers():
    src = (BACKEND / "routers" / "quotations.py").read_text(encoding="utf-8")
    assert not re.search(r"from routers\.(shipping_notes|inventory|suppliers)\b|import (shipping_notes|inventory|suppliers)\b", src)
