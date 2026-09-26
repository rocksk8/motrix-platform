"""IP-8 `bonus.payouts`／IP-9 `expense.entries` 取用方這一側：**M07 不在也要成立**的題（2026-09-26 M07 搬遷）。

提供方的正對照（有資料時出納頁與報表確實列出）在 `modules/payroll/tests/test_bonus_payout_connectors.py`（隨模組搬走）。
這裡不建任何獎金資料：M07 不在時本來就沒有。
① 出納獎金待發放：200、`available: false`、`notice` 明說
② 執行歷史帶 `bonusNotice`、`bonusPaid: []`；Excel 匯出照常
③ 營運報表照常回應（IP-9 不另加提示）
"""
from core import registry


def _sa(client, make_user):
    u, p = make_user("ip8_absent_sa", "Conn-Pass-123", role="superadmin")[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _drop(monkeypatch, *caps):
    monkeypatch.setattr(registry, "_LEGACY_PROVIDERS",
                        {k: v for k, v in registry._LEGACY_PROVIDERS.items() if k[0] not in caps})
    orig = registry.providers
    monkeypatch.setattr(registry, "providers", lambda cap: {} if cap in caps else orig(cap))


def test_cashier_and_report_without_payroll(client, make_user, monkeypatch):
    from modules.arap.api import cashier
    h = _sa(client, make_user)
    _drop(monkeypatch, "bonus.payouts", "expense.entries")
    q = client.get("/api/cashier/bonus-queue", headers=h)
    assert q.status_code == 200
    assert q.json() == {"available": False, "visible": True, "notice": cashier.BONUS_MISSING, "items": []}
    hist = client.get("/api/cashier/execution-history", headers=h)
    assert hist.status_code == 200 and hist.json()["bonusNotice"] == cashier.BONUS_MISSING and hist.json()["bonusPaid"] == []
    assert client.get("/api/cashier/export", headers=h).status_code == 200
    # 營運報表屬 M08（modules/analytics）：在 ⇒ 照常 200；不在 ⇒ 端點本來就不在（第六班列車 core-only 反向控制，M07×M08 交會）
    from core import source_tree
    want = 200 if source_tree.module_installed("modules/analytics/") else 404
    assert client.get("/api/reports/expenses-monthly?year=2026", headers=h).status_code == want
