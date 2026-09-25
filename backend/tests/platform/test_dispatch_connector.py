"""IP-1 連接器 `dispatch.row`（INTEGRATION-POINTS.md）：M04 派工單列序列化。

契約：M04（routers/vendor_contractors）匯入時以 `core.registry.provide` 登記；使用方以
`single_provider("dispatch.row")` 取用，拿到 None 就退化成「沒有派工資訊」，不可以壞掉。

① 契約形狀：使用方實際讀的欄位全部都在（欄位改名／刪除 ⇒ 這題紅 ⇒ 要升契約版本）
② registry 規則：重複登記不同函式報錯；多個提供者報錯；沒有 ⇒ None
③ 反向控制：拿掉提供者後，recognition／reports／vouchers 三處照常回結果，只少派工那一類
   ——同一批資料、同一個呼叫，有提供者時派工那一類必須非空（否則「少了」是假的）
"""
import json
import sqlite3

import pytest

from core import registry

QNO = "MQ-IP1-0925"
YEAR = 2026

#: 使用方讀的欄位（helpers/recognition.dispatch_entries、routers/vouchers._dispatch_expense_entry）
CONSUMED_KEYS = {"id", "quoteNo", "vendorName", "scope", "items", "personnel", "totalAmount",
                 "personnelTotal", "grandTotal", "invoiceNo", "acceptedAt"}


def _sample_row():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE d (id INTEGER, quote_no TEXT, vendor_id INTEGER, vendor_name TEXT, dispatch_date TEXT,"
              " scope TEXT, items_json TEXT, total_amount REAL, tax_rate REAL, personnel_json TEXT, status TEXT,"
              " notes TEXT, invoice_no TEXT, created_by TEXT, created_at TEXT, updated_at TEXT)")
    c.execute("INSERT INTO d VALUES (1,'Q',1,'承攬甲','2026-03-01','配線','[]',1000,0.05,"
              "'[{\"name\":\"王\",\"amount\":500}]','draft','','INV1','u','t','t')")
    return c.execute("SELECT * FROM d").fetchone()


def test_contract_shape_has_every_consumed_key(client):
    fn = registry.single_provider("dispatch.row")
    assert fn is not None, "M04 沒有登記 dispatch.row（routers/vendor_contractors 匯入時應 provide）"
    d = fn(_sample_row())
    assert CONSUMED_KEYS <= set(d), CONSUMED_KEYS - set(d)
    assert d["grandTotal"] == 1000 + 50 + 500          # 含稅承攬商費用＋外包人員


def test_registry_rules(monkeypatch):
    monkeypatch.setattr(registry, "_LEGACY_PROVIDERS", {})
    assert registry.single_provider("x.cap") is None and registry.providers("x.cap") == {}
    f, g = (lambda r: 1), (lambda r: 2)
    registry.provide("x.cap", "a", f)
    registry.provide("x.cap", "a", f)                 # 同一個函式重複登記：允許（匯入兩次）
    with pytest.raises(ValueError):
        registry.provide("x.cap", "a", g)
    assert registry.single_provider("x.cap") is f
    registry.provide("x.cap", "b", g)
    with pytest.raises(RuntimeError):
        registry.single_provider("x.cap")


def _seed():
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
                     " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     (QNO, "已送出", "客", "案", 100, 95, json.dumps({}), "2026-03-01", "2026-03-01"))
        conn.execute("INSERT INTO vendor_contractors (name) VALUES ('承攬甲')")
        vid = conn.execute("SELECT id FROM vendor_contractors WHERE name='承攬甲'").fetchone()["id"]
        conn.execute("INSERT INTO contractor_dispatches (quote_no, vendor_id, dispatch_date, scope, items_json,"
                     " total_amount, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     (QNO, vid, f"{YEAR}-03-01", "配線", "[]", 1000, "draft", "t", "t"))
        conn.execute("INSERT INTO case_extra_expenses (quote_no, description, total_cost, expense_date)"
                     " VALUES (?,?,?,?)", (QNO, "吊車", 300, f"{YEAR}-03-02"))
        conn.commit()
    finally:
        conn.close()


def _observe():
    """三個使用方各呼叫一次，回傳 (派工那一類的筆數, 其他類是否照常)。"""
    import db
    from helpers.recognition import dispatch_entries
    from routers.reports import _collect_expenses
    from routers.vouchers import _case_expense_sources
    conn = db.get_db()
    try:
        rec = dispatch_entries(conn, "accrual")
        rep = _collect_expenses(YEAR, basis="accrual", conn=conn)
        vou = _case_expense_sources(conn, QNO)
    finally:
        conn.close()
    kinds = [x["kind"] for x in vou]
    return {
        "recognition_dispatch": len([e for e in rec if e["quoteNo"] == QNO]),
        "reports_contractor": len([e for e in rep["details"]["contractor"] if e["quoteNo"] == QNO]),
        "vouchers_dispatch": kinds.count("contractor_dispatch"),
        "vouchers_extra_still_there": kinds.count("extra_expense") == 1,
    }


def test_consumers_degrade_when_provider_is_absent(client, monkeypatch):
    _seed()
    with_provider = _observe()
    assert with_provider == {"recognition_dispatch": 1, "reports_contractor": 1, "vouchers_dispatch": 1,
                             "vouchers_extra_still_there": True}, with_provider   # 正對照：派工確實在
    monkeypatch.setattr(registry, "_LEGACY_PROVIDERS",
                        {k: v for k, v in registry._LEGACY_PROVIDERS.items() if k[0] != "dispatch.row"})
    assert registry.single_provider("dispatch.row") is None
    without = _observe()                                   # 不丟例外 = 仍然可用
    assert without == {"recognition_dispatch": 0, "reports_contractor": 0, "vouchers_dispatch": 0,
                       "vouchers_extra_still_there": True}, without


def test_no_one_imports_the_private_function_anymore():
    """邊界：別組不可再 import routers.vendor_contractors 的私有序列化函式。"""
    from pathlib import Path
    backend = Path(__file__).resolve().parents[2]
    hits = [str(p.relative_to(backend)) for p in backend.rglob("*.py")
            if "tests" not in p.parts and p.name != "vendor_contractors.py"
            and "import _dispatch_row" in p.read_text(encoding="utf-8")]
    assert hits == []
