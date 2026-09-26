"""IP-98 `receivables.income_items`／IP-99 `receivables.tax_invoices` 取用方這一側：**M05 不在也要成立**的題（2026-09-26 M05 搬遷）。

提供方的登記與正對照在 `modules/arap/tests/test_receivables_providers.py`（隨模組搬走）。
M05 不在（拿掉兩個 provider）：
① M08 營運報表（現金口徑）：200、收入清單空、`incomeNotice` 明說——不是「這個月沒有收款」
② M08 稅務匯出：404＋`RECEIVABLES_MISSING`（不回空的 Excel 假裝沒有發票）
③ M06 T100 預覽：200、`notice` 列出不含收款事件
正對照：provider 在時 ① 的 `incomeNotice` 是空字串、權責口徑不受影響。
"""
import pytest

from core import registry, source_tree


def _sa(client, make_user):
    u, p = make_user("rcv_absent_sa", "Conn-Pass-123", role="superadmin")[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _drop(monkeypatch, *caps):
    orig_single, orig_prov = registry.single_provider, registry.providers
    monkeypatch.setattr(registry, "single_provider", lambda cap: None if cap in caps else orig_single(cap))
    monkeypatch.setattr(registry, "providers", lambda cap: {} if cap in caps else orig_prov(cap))


CAPS = ("receivables.income_items", "receivables.tax_invoices")


def _analytics():
    return source_tree.module_installed("modules/analytics/")


def test_reports_without_m05(client, make_user, monkeypatch):
    if not _analytics():
        pytest.skip("M08 營運分析不在這個安裝包 ⇒ 報表端點本來就不在（PLAYBOOK §B-11）")
    from modules.analytics.api import reports as rp
    h = _sa(client, make_user)
    _drop(monkeypatch, *CAPS)
    r = client.get("/api/reports/expenses-monthly?year=2026&month=2026-09&basis=cash", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["incomeNotice"] == rp.RECEIVABLES_MISSING and r.json()["monthIncomeItems"] == []
    acc = client.get("/api/reports/expenses-monthly?year=2026&month=2026-09&basis=accrual", headers=h)
    assert acc.status_code == 200 and acc.json()["incomeNotice"] == ""          # 權責口徑的收入來自 M01 的階段，不受影響
    t = client.get("/api/reports/tax-export?year=2026&month=9", headers=h)
    assert t.status_code == 404 and t.json()["detail"] == rp.RECEIVABLES_MISSING


def test_reports_income_notice_is_empty_when_m05_is_present(client, make_user):
    if not (_analytics() and source_tree.module_installed("modules/arap/")):
        pytest.skip("M08 或 M05 不在這個安裝包 ⇒ 沒有正對照可做；⚠ skip 不是驗過")
    h = _sa(client, make_user)
    r = client.get("/api/reports/expenses-monthly?year=2026&month=2026-09&basis=cash", headers=h)
    assert r.status_code == 200 and r.json()["incomeNotice"] == ""


def test_t100_preview_without_m05(client, make_user, monkeypatch):
    from routers import accounting_export as ae
    h = _sa(client, make_user)
    _drop(monkeypatch, *CAPS)
    prev = client.get("/api/reports/t100-export/preview?start=2026-09-01&end=2026-09-30", headers=h)
    assert prev.status_code == 200, prev.text
    assert ae.T100_RECEIVABLES_MISSING in prev.json()["notice"].split("；")
    # 兩個都缺 ⇒ 兩句並列（IP-14 的承攬商＋本串接點的收款事件）
    _drop(monkeypatch, "contractor_voucher.public")
    both = client.get("/api/reports/t100-export/preview?start=2026-09-01&end=2026-09-30", headers=h).json()["notice"].split("；")
    assert set(both) == {ae.T100_RECEIVABLES_MISSING, ae.T100_CONTRACTOR_MISSING}, both
