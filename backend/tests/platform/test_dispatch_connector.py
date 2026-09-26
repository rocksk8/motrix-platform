"""IP-1 `dispatch.row` 取用方這一側：**外包工班不在也要成立**的題（2026-09-26 自 test_dispatch_connector 拆出）。

拿掉提供者（或外包工班根本沒裝）⇒ 傳票摘要來源照常回應，並明說少了派工那一類；
（營運報表／月支出／待補登那一處在 `modules/analytics/tests/test_reports_dispatch_row_consumer.py`，營運分析模組拿掉就一起拿掉；第六班列車交會）
頁面讀得到那個說明；產品碼沒有人 import 外包工班的私有序列化函式。
正對照（提供者在時派工確實算進來）與契約形狀在 `modules/subcontract/tests/test_dispatch_row_provider.py`（隨模組搬走）。
"""
import json

from core import registry
from core import source_tree
import pytest

QNO = "MQ-IP1-0925"
YEAR = 2026


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


def _drop_dispatch_row(monkeypatch):
    monkeypatch.setattr(registry, "_LEGACY_PROVIDERS",
                        {k: v for k, v in registry._LEGACY_PROVIDERS.items() if k[0] != "dispatch.row"})
    orig = registry.providers
    monkeypatch.setattr(registry, "providers", lambda cap: {} if cap == "dispatch.row" else orig(cap))


def _sa(client, make_user):
    name, pw = make_user(username="ip1_sa", role="superadmin")
    r = client.post("/api/auth/login", json={"username": name, "password": pw})
    return {"Authorization": "Bearer " + r.json()["token"]}


def _sources(client, h):
    src = client.get(f"/api/vouchers/summary-sources?quote_no={QNO}", headers=h)
    assert src.status_code == 200, src.text
    return src.json()


def test_absence_is_said_in_voucher_sources(client, make_user, monkeypatch):
    """營運報表那一半在 modules/analytics/tests/test_reports_dispatch_row_consumer.py。"""
    if not source_tree.module_installed("modules/accounting/"):
        pytest.skip("會計（M06）不在這個安裝包（PLAYBOOK §B-11）")
    _seed()
    h = _sa(client, make_user)
    _drop_dispatch_row(monkeypatch)
    src = _sources(client, h)
    # 傳票摘要來源：額外支出照常，派工那一類明說缺
    assert [u["category"] for u in src["unavailable"]] == ["contractor_dispatch"]
    assert [e["kind"] for e in src["tabs"]["支出項"]] == ["extra_expense"]


def test_no_one_imports_the_private_function_anymore():
    """邊界：別組不可再 import routers.vendor_contractors 的私有序列化函式。"""
    from pathlib import Path
    backend = Path(__file__).resolve().parents[2]
    hits = [str(p.relative_to(backend)) for p in backend.rglob("*.py")
            if "tests" not in p.parts and p.name != "vendor_contractors.py"
            and "import _dispatch_row" in p.read_text(encoding="utf-8")]
    assert hits == []


def test_pages_render_the_absence():
    from pathlib import Path
    fe = Path(__file__).resolve().parents[3] / "frontend"
    assert "(this.expensesData || {}).unavailable" in (fe / "js" / "reports.js").read_text(encoding="utf-8")
    assert 'data-testid="expense-unavailable"' in (fe / "pages" / "reports.html").read_text(encoding="utf-8")
    # 2026-09-26（A）：與因權限沒列出的 hidden 並列顯示 ⇒ unavailable 仍在最前面
    assert "this.sourceUnavailable = (d.unavailable || []).concat(d.hidden || [])" in (fe / "js" / "voucher.js").read_text(encoding="utf-8")
    assert 'data-testid="source-unavailable"' in (fe / "pages" / "voucher.html").read_text(encoding="utf-8")
