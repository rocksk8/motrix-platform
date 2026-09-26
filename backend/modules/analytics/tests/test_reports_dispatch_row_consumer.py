"""IP-1 `dispatch.row` 的營運報表使用方（自 tests/platform/test_dispatch_connector.py 拆出，M08 搬遷反向控制）。

拿掉本模組 ⇒ 本檔一起消失；tests/platform 那一份只驗 L1 recognition 與 M06 傳票兩個使用方。
"""
from core import registry
from tests.platform.test_dispatch_connector import QNO, YEAR, _sa, _seed, drop_dispatch_provider


def _contractor_rows():
    import db
    from modules.analytics.api.reports import _collect_expenses
    conn = db.get_db()
    try:
        rep = _collect_expenses(YEAR, basis="accrual", conn=conn)
    finally:
        conn.close()
    return [e for e in rep["details"]["contractor"] if e["quoteNo"] == QNO]


def test_report_degrades_when_provider_is_absent(client, monkeypatch):
    _seed()
    assert len(_contractor_rows()) == 1                    # 正對照：派工確實在
    drop_dispatch_provider(monkeypatch)
    assert registry.single_provider("dispatch.row") is None
    assert _contractor_rows() == []                        # 不丟例外，只少派工那一類


def _reports(client, h):
    rep = client.get(f"/api/reports/expenses-monthly?year={YEAR}&month={YEAR}-03", headers=h)
    cash = client.get(f"/api/reports/expenses-monthly?year={YEAR}&month={YEAR}-03&basis=cash", headers=h)
    for r in (rep, cash):
        assert r.status_code == 200, r.text
    return rep.json(), cash.json()


def test_absence_is_said_in_report_flags(client, make_user, monkeypatch):
    _seed()
    h = _sa(client, make_user)
    rep, cash = _reports(client, h)
    # 正對照：提供者在 ⇒ 沒有 unavailable，而且派工確實算進來了
    assert rep["unavailable"] == [] and rep["expenses"]["unavailable"] == []
    assert [e for e in rep["expenses"]["details"]["contractor"] if e["quoteNo"] == QNO]
    drop_dispatch_provider(monkeypatch)
    rep, cash = _reports(client, h)
    # 營運報表／月支出＋待補登（同一份回應）
    assert [u["category"] for u in rep["unavailable"]] == ["contractor"]
    assert "未安裝" in rep["unavailable"][0]["reason"]
    assert rep["expenses"]["unavailable"] == rep["unavailable"]
    # 現金口徑讀匯款申請快照，不受影響 ⇒ 不說缺
    assert cash["unavailable"] == []
