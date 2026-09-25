"""IP-1 `dispatch.row` 取用方這一側：**外包工班不在也要成立**的題（2026-09-26 自 test_dispatch_connector 拆出）。

拿掉提供者（或外包工班根本沒裝）⇒ 營運報表／月支出／待補登與傳票摘要來源照常回應，並明說少了派工那一類；
頁面讀得到那個說明；產品碼沒有人 import 外包工班的私有序列化函式。
正對照（提供者在時派工確實算進來）與契約形狀在 `modules/subcontract/tests/test_dispatch_row_provider.py`（隨模組搬走）。
"""
import json

from core import registry

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


def _responses(client, h):
    rep = client.get(f"/api/reports/expenses-monthly?year={YEAR}&month={YEAR}-03", headers=h)
    cash = client.get(f"/api/reports/expenses-monthly?year={YEAR}&month={YEAR}-03&basis=cash", headers=h)
    src = client.get(f"/api/vouchers/summary-sources?quote_no={QNO}", headers=h)
    for r in (rep, cash, src):
        assert r.status_code == 200, r.text
    return rep.json(), cash.json(), src.json()


def test_absence_is_said_in_report_flags_and_voucher_sources(client, make_user, monkeypatch):
    _seed()
    h = _sa(client, make_user)
    _drop_dispatch_row(monkeypatch)
    rep, cash, src = _responses(client, h)
    # 營運報表／月支出＋待補登（同一份回應）
    assert [u["category"] for u in rep["unavailable"]] == ["contractor"]
    assert "未安裝" in rep["unavailable"][0]["reason"]
    assert rep["expenses"]["unavailable"] == rep["unavailable"]
    # 現金口徑讀匯款申請快照，不受影響 ⇒ 不說缺
    assert cash["unavailable"] == []
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
    assert "this.sourceUnavailable = d.unavailable" in (fe / "js" / "voucher.js").read_text(encoding="utf-8")
    assert 'data-testid="source-unavailable"' in (fe / "pages" / "voucher.html").read_text(encoding="utf-8")
